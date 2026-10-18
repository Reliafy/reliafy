"""Photos in Reliafy Maintenance: cleaned of metadata, stored, linked to what
they show; added from a phone through a link; the location offered, never kept
on the photo; and over MCP, where Claude can look at them."""

import io

import mongomock
import pytest
from PIL import Image
from PIL.TiffImagePlugin import IFDRational

from backend.maintenance import photos
from backend.maintenance.service import PROJECTORS, Maintenance
from backend.maintenance.store import GraphStore

UID = "user-p"


def _jpeg(gps=True, orientation=6, size=(800, 600)) -> bytes:
    img = Image.new("RGB", size, (200, 30, 30))
    exif = Image.Exif()
    exif[0x0112] = orientation
    exif[0x010F] = "PhoneCo"  # camera make: must not survive
    exif[0x8769] = {36867: "2024:05:01 10:00:00"}
    if gps:
        exif[0x8825] = {1: "S", 2: (IFDRational(27), IFDRational(28), IFDRational(12)),
                        3: "E", 4: (IFDRational(153), IFDRational(1), IFDRational(30))}
    buf = io.BytesIO()
    img.save(buf, "JPEG", exif=exif)
    return buf.getvalue()


def test_clean_strips_metadata_keeps_date_and_offers_location():
    out = photos.clean(_jpeg())
    assert out["gps"] == {"lat": pytest.approx(-27.47, abs=1e-3), "lon": pytest.approx(153.025, abs=1e-3)}
    assert out["taken_on"] == "2024-05-01"
    full = Image.open(io.BytesIO(out["full"]))
    assert full.size == (600, 800)  # turned upright from the orientation flag
    assert len(full.getexif()) == 0 and "exif" not in full.info
    assert max(Image.open(io.BytesIO(out["thumb"])).size) == photos.THUMB_PX
    assert photos.clean(_jpeg(gps=False))["gps"] is None
    with pytest.raises(photos.BadPhoto):
        photos.clean(b"not an image at all")


def test_photos_attach_to_positions_items_and_coordinates(tmp_path):
    m = Maintenance(GraphStore(":memory:", PROJECTORS), UID)
    pos = m.create_position("Hot water system")
    m.fit(pos["id"], new_item={"name": "Rheem 315"})
    item_id = m.position(pos["id"])["fitted"]["item"]["id"]
    store = photos.FilePhotoStore(str(tmp_path))
    cleaned = photos.clean(_jpeg())
    store.put("abc123", "full", cleaned["full"])
    m.add_photo("abc123", item_id, cleaned, "Nameplate")
    assert store.get("abc123", "full") == cleaned["full"]
    detail = m.position(pos["id"])
    assert detail["photos"] == [] and detail["item_photos"][0]["caption"] == "Nameplate"
    saved = m.set_coordinates(pos["id"], -27.47, 153.025, "photo")
    assert saved["coordinates"]["source"] == "photo" and m.position(pos["id"])["coordinates"]["lat"] == -27.47
    m.remove_photo("abc123")
    assert m.position(pos["id"])["item_photos"] == []


@pytest.fixture()
def app_env(monkeypatch, tmp_path):
    from backend import config, db
    from backend.routers import ingest as ingest_router
    from backend.routers import maintenance as router
    from backend.services import tokens

    monkeypatch.setattr(config, "AUTH_DISABLED", False)
    monkeypatch.setattr(config, "BILLING_ENABLED", False)
    monkeypatch.setattr(config, "MAINTENANCE_ENABLED", True)
    monkeypatch.setattr(config, "MAINTENANCE_EMAILS", {"p@example.org"})
    test_db = mongomock.MongoClient()["maint_photos"]
    monkeypatch.setattr(db, "_db", test_db)
    monkeypatch.setattr(db, "_simulated", True)
    monkeypatch.setattr(router, "_store", GraphStore(":memory:", PROJECTORS))
    monkeypatch.setattr(router, "_photo_store", photos.FilePhotoStore(str(tmp_path)))
    ingest_router._hits.clear()
    test_db.users.insert_one({"_id": UID, "email": "p@example.org", "name": "P", "email_verified": True})
    return {"db": test_db, "token": tokens.create_token(test_db, UID, "mcp")["token"]}


def test_app_upload_and_phone_link(app_env):
    from fastapi.testclient import TestClient

    from backend.auth import get_current_user
    from backend.main import app

    client = TestClient(app)
    app.dependency_overrides[get_current_user] = lambda: {
        "uid": UID, "email": "p@example.org", "name": "P", "email_verified": True}
    try:
        pid = client.post("/api/maintenance/positions", json={"name": "Pool pump"}).json()["id"]
        up = client.post(f"/api/maintenance/photos?target_id={pid}&caption=Front",
                         content=_jpeg(), headers={"Content-Type": "image/jpeg"})
        assert up.status_code == 200, up.text
        assert up.json()["location_offer"]["lat"] == pytest.approx(-27.47, abs=1e-3)
        photo_id = up.json()["photo"]["id"]
        img = client.get(f"/api/maintenance/photos/{photo_id}?size=full")
        assert img.status_code == 200 and img.headers["content-type"] == "image/jpeg"
        assert len(Image.open(io.BytesIO(img.content)).getexif()) == 0
        bad = client.post(f"/api/maintenance/photos?target_id={pid}", content=b"%PDF-1.4 nope")
        assert bad.status_code == 422

        link = client.post("/api/maintenance/photo-links", json={"target_id": pid}).json()
        path = link["url"].split("testserver", 1)[1]
        app.dependency_overrides.pop(get_current_user)  # the phone isn't signed in

        page = client.get(path)
        assert page.status_code == 200 and "Pool pump" in page.text and "nonce-" in page.headers["content-security-policy"]
        assert client.get(path.replace("t=", "t=x")).status_code == 404  # wrong token
        sent = client.post(path, content=_jpeg(), headers={"Content-Type": "image/jpeg"})
        assert sent.status_code == 200 and sent.json()["location_offer"]
        base, query = path.split("?")
        answered = client.post(f"{base}/location?{query}", json={"photo_id": sent.json()["photo_id"], "save": True})
        assert answered.json() == {"saved": True}
        doc = app_env["db"]["maintenance_photo_links"].find_one({"_id": link["link_id"]})
        assert doc["gps_offers"][0]["answer"] == "saved" and len(doc["photos"]) == 1

        app.dependency_overrides[get_current_user] = lambda: {
            "uid": UID, "email": "p@example.org", "name": "P", "email_verified": True}
        detail = client.get(f"/api/maintenance/positions/{pid}").json()
        assert len(detail["photos"]) == 2 and detail["coordinates"]["source"] == "photo"
    finally:
        app.dependency_overrides.pop(get_current_user, None)


def test_photos_over_mcp(app_env):
    import anyio
    import httpx2
    from mcp import Client
    from mcp.client.streamable_http import streamable_http_client

    from backend.main import app
    from backend.maintenance import mcp_tools
    from backend.mcp_server import mcp_http_app

    mcp_tools.register()
    try:
        async def flow(client):
            pos = (await client.call_tool("maintenance_positions", {"action": "create",
                                                                     "name": "Hot water system"})).structured_content
            link = (await client.call_tool("maintenance_attachments", {"action": "photo_link",
                                                                       "target_id": pos["id"]})).structured_content
            path = link["url"].split("testserver", 1)[1]
            async with httpx2.AsyncClient(transport=httpx2.ASGITransport(app=app),
                                          base_url="http://testserver") as phone:
                r = await phone.post(path, content=_jpeg(), headers={"Content-Type": "image/jpeg"})
                assert r.status_code == 200, r.text
            status = (await client.call_tool("maintenance_get", {"kind": "photo_link",
                                                               "id": link["link_id"]})).structured_content
            photo_id = status["photos"][0]
            assert status["location_offers"][0]["answer"] is None
            seen = await client.call_tool("maintenance_view_photo", {"photo_id": photo_id})
            listed = (await client.call_tool("maintenance_list", {"kind": "photos",
                                                                  "target_id": pos["id"]})).structured_content
            return seen, listed

        async def main():
            async with mcp_http_app.lifespan():
                async with httpx2.AsyncClient(
                    transport=httpx2.ASGITransport(app=app), base_url="http://testserver",
                    headers={"Authorization": f"Bearer {app_env['token']}"},
                ) as hc:
                    async with Client(streamable_http_client("http://testserver/mcp", http_client=hc),
                                      mode="legacy") as client:
                        return await flow(client)

        seen, listed = anyio.run(main)
        assert not seen.is_error and seen.content[0].type == "image" and seen.content[0].mime_type == "image/jpeg"
        assert len(listed["photos"]) == 1
    finally:
        mcp_tools.unregister()


# ---- HEIC/HEIF (an iPhone's default) -------------------------------------------------------

def _heic(orientation=6, size=(800, 600), gps=True, icc=None) -> bytes:
    """A real HEIC, encoded here with pillow-heif (a test-only install): the
    app decodes with pi-heif, its decode-only build. The EXIF orientation is
    written as the HEIF rotation, as a phone does."""
    import pillow_heif

    img = Image.new("RGB", size, (200, 30, 30))
    img.paste((30, 200, 30), (0, 0, size[0] // 4, size[1] // 4))  # a green top-left corner
    exif = Image.Exif()
    exif[0x0112] = orientation
    exif[0x010F] = "PhoneCo"
    exif[0x8769] = {36867: "2024:05:01 10:00:00"}
    if gps:
        exif[0x8825] = {1: "S", 2: (IFDRational(27), IFDRational(28), IFDRational(12)),
                        3: "E", 4: (IFDRational(153), IFDRational(1), IFDRational(30))}
    buf = io.BytesIO()
    extra = {"icc_profile": icc} if icc else {}
    pillow_heif.from_pillow(img).save(buf, quality=90, exif=exif.tobytes(), **extra)
    return buf.getvalue()


def test_heic_is_read_and_comes_out_as_a_clean_upright_jpeg():
    assert "HEIF" in photos.FORMATS and "HEIC" in photos.READABLE
    raw = _heic()
    assert raw[4:12] == b"ftypheic"
    out = photos.clean(raw)
    assert out["taken_on"] == "2024-05-01"
    assert out["gps"] == {"lat": pytest.approx(-27.47, abs=1e-3), "lon": pytest.approx(153.025, abs=1e-3)}
    full = Image.open(io.BytesIO(out["full"]))
    assert full.format == "JPEG" and full.size == (600, 800)  # turned upright once, not twice
    assert len(full.getexif()) == 0 and "exif" not in full.info and "icc_profile" not in full.info
    # Orientation 6 turns the picture a quarter clockwise: the green top-left
    # corner of the stored image ends up top-right.
    r, g, b = full.convert("RGB").getpixel((full.width - 20, 20))
    assert g > 150 and r < 100
    thumb = Image.open(io.BytesIO(out["thumb"]))
    assert thumb.format == "JPEG" and max(thumb.size) == photos.THUMB_PX and len(thumb.getexif()) == 0
    big = photos.clean(_heic(orientation=1, size=(2400, 1800), gps=False))
    assert (big["width"], big["height"]) == (photos.FULL_PX, 1200) and big["gps"] is None


def test_photo_colour_profiles_are_converted_to_srgb(monkeypatch):
    from PIL import ImageCms

    seen = []
    real = photos.ImageCms.profileToProfile

    def spy(img, src, dst, **kw):
        seen.append(src.profile.profile_description)
        return real(img, src, dst, **kw)

    monkeypatch.setattr(photos.ImageCms, "profileToProfile", spy)
    srgb = ImageCms.ImageCmsProfile(ImageCms.createProfile("sRGB")).tobytes()
    out = photos.clean(_heic(orientation=1, gps=False, icc=srgb))
    assert seen and "sRGB" in seen[0]  # the HEIC's own profile was used for the conversion
    px = Image.open(io.BytesIO(out["full"])).convert("RGB").getpixel((700, 500))
    assert all(abs(a - b) < 12 for a, b in zip(px, (200, 30, 30)))
    assert "icc_profile" not in Image.open(io.BytesIO(out["full"])).info
    # A broken profile just leaves the pixels as they are.
    buf = io.BytesIO()
    Image.new("RGB", (64, 64), (200, 30, 30)).save(buf, "JPEG", icc_profile=b"not a profile")
    kept = Image.open(io.BytesIO(photos.clean(buf.getvalue())["full"])).convert("RGB").getpixel((32, 32))
    assert all(abs(a - b) < 12 for a, b in zip(kept, (200, 30, 30)))
    # A CMYK JPEG with no profile still comes out RGB.
    buf = io.BytesIO()
    Image.new("CMYK", (64, 64), (0, 200, 200, 0)).save(buf, "JPEG")
    assert Image.open(io.BytesIO(photos.clean(buf.getvalue())["full"])).mode == "RGB"


def test_a_heic_that_isnt_one_is_refused_politely():
    fake = b"\x00\x00\x00\x18ftypheic\x00\x00\x00\x00mif1heic" + b"\x00" * 200
    for raw in (fake, _heic()[:300], b"just text named IMG_0001.HEIC"):
        with pytest.raises(photos.BadPhoto, match=r"isn't a photo Reliafy can read \(JPEG, PNG, WebP or HEIC\)"):
            photos.clean(raw)


def test_heic_through_the_app_and_the_phone_link(app_env):
    from fastapi.testclient import TestClient

    from backend.auth import get_current_user
    from backend.main import app

    client = TestClient(app)
    app.dependency_overrides[get_current_user] = lambda: {
        "uid": UID, "email": "p@example.org", "name": "P", "email_verified": True}
    try:
        pid = client.post("/api/maintenance/positions", json={"name": "Pool pump"}).json()["id"]
        up = client.post(f"/api/maintenance/photos?target_id={pid}", content=_heic(),
                         headers={"Content-Type": "image/heic"})
        assert up.status_code == 200, up.text
        img = client.get(f"/api/maintenance/photos/{up.json()['photo']['id']}?size=full")
        assert img.headers["content-type"] == "image/jpeg" and Image.open(io.BytesIO(img.content)).size == (600, 800)
        bad = client.post(f"/api/maintenance/photos?target_id={pid}", content=b"\x00\x00\x00\x18ftypheic" + b"\x00" * 64,
                          headers={"Content-Type": "image/heic"})
        assert bad.status_code == 422 and "HEIC" in bad.json()["detail"]

        link = client.post("/api/maintenance/photo-links", json={"target_id": pid}).json()
        path = link["url"].split("testserver", 1)[1]
        app.dependency_overrides.pop(get_current_user)
        assert 'accept="image/*,.heic,.heif"' in client.get(path).text
        sent = client.post(path, content=_heic(), headers={"Content-Type": "image/heic"})
        assert sent.status_code == 200 and sent.json()["location_offer"]
    finally:
        app.dependency_overrides.pop(get_current_user, None)


# ---- one photo, several places --------------------------------------------------------------

def _places(m, photo_id):
    return sorted(t["id"] for t in m.photo(photo_id)["on"])


def _wo_photo(m):
    loc = m.create_location("Plant room")
    pos = m.create_position("Pool pump", location_id=loc["id"])
    m.fit(pos["id"], new_item={"name": "Motor"})
    item_id = m.position(pos["id"])["fitted"]["item"]["id"]
    wo = m.open_work_order(pos["id"], "Replace seal")
    m.add_photo("ph1", wo["id"], {"width": 10, "height": 10}, "Nameplate")
    return loc["id"], pos["id"], item_id, wo["id"]


def test_a_photo_links_to_more_places_and_moves(tmp_path):
    m = Maintenance(GraphStore(":memory:", PROJECTORS), UID)
    loc, pos, item, wo = _wo_photo(m)
    assert _places(m, "ph1") == [wo] and m.photos_of(wo)[0]["also_on"] == []

    m.link_photo("ph1", pos)
    m.link_photo("ph1", loc)
    events = len(m.s.events(m.org, 500))
    m.link_photo("ph1", pos)  # already there: nothing new in the log
    assert len(m.s.events(m.org, 500)) == events
    assert _places(m, "ph1") == sorted([wo, pos, loc])
    on_pos = m.position(pos)["photos"][0]
    assert {x["id"] for x in on_pos["also_on"]} == {wo, loc}
    assert [x["kind"] for x in m.photo("ph1")["on"]] == ["Position", "Location", "WorkOrder"]
    assert m.location(loc)["photos"][0]["id"] == "ph1"
    assert m.work_order(wo)["photos"][0]["also_on"][0]["name"] == "Pool pump"

    m.unlink_photo("ph1", loc)
    assert _places(m, "ph1") == sorted([wo, pos]) and m.location(loc)["photos"] == []
    with pytest.raises(Exception, match="isn't on that"):
        m.unlink_photo("ph1", loc)

    # Move off one place (the work order) to the item.
    m.move_photo("ph1", item, from_id=wo)
    assert _places(m, "ph1") == sorted([pos, item]) and m.work_order(wo)["photos"] == []
    # Move with no from: only on the new place.
    m.move_photo("ph1", loc)
    assert _places(m, "ph1") == [loc]
    with pytest.raises(Exception, match="only place"):
        m.unlink_photo("ph1", loc)
    with pytest.raises(Exception):
        m.link_photo("ph1", "nope")
    with pytest.raises(Exception, match="moved from"):
        m.move_photo("ph1", pos, from_id=wo)

    before = m.s.snapshot()
    m.s.rebuild()
    assert m.s.snapshot() == before
    assert _places(m, "ph1") == [loc] and m.location(loc)["photos"][0]["id"] == "ph1"


def test_a_removed_photo_goes_from_every_place(tmp_path):
    m = Maintenance(GraphStore(":memory:", PROJECTORS), UID)
    loc, pos, item, wo = _wo_photo(m)
    m.link_photo("ph1", pos)
    m.link_photo("ph1", item)
    m.remove_photo("ph1")
    assert m.work_order(wo)["photos"] == [] and m.position(pos)["photos"] == []
    assert m.position(pos)["item_photos"] == [] and m.item(item)["photos"] == []
    for act in (lambda: m.link_photo("ph1", loc), lambda: m.unlink_photo("ph1", pos),
                lambda: m.move_photo("ph1", loc)):
        with pytest.raises(Exception, match="removed"):
            act()
    before = m.s.snapshot()
    m.s.rebuild()
    assert m.s.snapshot() == before and m.item(item)["photos"] == []


def test_link_and_move_in_the_app_and_over_mcp(app_env):
    import anyio
    import httpx2
    from fastapi.testclient import TestClient
    from mcp import Client
    from mcp.client.streamable_http import streamable_http_client

    from backend.auth import get_current_user
    from backend.main import app
    from backend.maintenance import mcp_tools
    from backend.mcp_server import mcp_http_app

    client = TestClient(app)
    app.dependency_overrides[get_current_user] = lambda: {
        "uid": UID, "email": "p@example.org", "name": "P", "email_verified": True}
    try:
        a = client.post("/api/maintenance/positions", json={"name": "Pump A"}).json()["id"]
        b = client.post("/api/maintenance/positions", json={"name": "Pump B"}).json()["id"]
        photo_id = client.post(f"/api/maintenance/photos?target_id={a}", content=_jpeg(),
                               headers={"Content-Type": "image/jpeg"}).json()["photo"]["id"]
        r = client.post(f"/api/maintenance/photos/{photo_id}/link", json={"target_id": b})
        assert r.status_code == 200 and {x["id"] for x in r.json()["on"]} == {a, b}
        r = client.post(f"/api/maintenance/photos/{photo_id}/unlink", json={"target_id": a})
        assert r.status_code == 200 and [x["id"] for x in r.json()["on"]] == [b]
        r = client.post(f"/api/maintenance/photos/{photo_id}/unlink", json={"target_id": b})
        assert r.status_code == 422 and "only place" in r.json()["detail"]
        r = client.post(f"/api/maintenance/photos/{photo_id}/move", json={"target_id": a, "from_id": b})
        assert [x["id"] for x in r.json()["on"]] == [a]
        assert client.get(f"/api/maintenance/positions/{b}").json()["photos"] == []
    finally:
        app.dependency_overrides.pop(get_current_user, None)

    mcp_tools.register()
    try:
        async def flow(mc):
            linked = (await mc.call_tool("maintenance_attachments", {"action": "link_photo", "photo_id": photo_id,
                                                                     "target_id": b})).structured_content
            moved = (await mc.call_tool("maintenance_attachments", {"action": "move_photo", "photo_id": photo_id,
                                                                    "target_id": b, "from_id": a})).structured_content
            refused = await mc.call_tool("maintenance_attachments", {"action": "unlink_photo", "photo_id": photo_id,
                                                                     "target_id": b})
            listed = (await mc.call_tool("maintenance_list", {"kind": "photos", "target_id": b})).structured_content
            return linked, moved, refused, listed

        async def main():
            async with mcp_http_app.lifespan():
                async with httpx2.AsyncClient(
                    transport=httpx2.ASGITransport(app=app), base_url="http://testserver",
                    headers={"Authorization": f"Bearer {app_env['token']}"},
                ) as hc:
                    async with Client(streamable_http_client("http://testserver/mcp", http_client=hc),
                                      mode="legacy") as mc:
                        return await flow(mc)

        linked, moved, refused, listed = anyio.run(main)
        assert {x["id"] for x in linked["on"]} == {a, b}
        assert [x["id"] for x in moved["on"]] == [b]
        assert refused.is_error and "only place" in refused.content[0].text
        assert listed["photos"][0]["id"] == photo_id and listed["photos"][0]["also_on"] == []
    finally:
        mcp_tools.unregister()
