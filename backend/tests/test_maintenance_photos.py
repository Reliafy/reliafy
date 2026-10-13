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
            pos = (await client.call_tool("create_position", {"name": "Hot water system"})).structured_content
            link = (await client.call_tool("create_photo_link", {"target_id": pos["id"]})).structured_content
            path = link["url"].split("testserver", 1)[1]
            async with httpx2.AsyncClient(transport=httpx2.ASGITransport(app=app),
                                          base_url="http://testserver") as phone:
                r = await phone.post(path, content=_jpeg(), headers={"Content-Type": "image/jpeg"})
                assert r.status_code == 200, r.text
            status = (await client.call_tool("photo_link_status", {"link_id": link["link_id"]})).structured_content
            photo_id = status["photos"][0]
            assert status["location_offers"][0]["answer"] is None
            seen = await client.call_tool("get_photo", {"photo_id": photo_id})
            listed = (await client.call_tool("list_photos", {"target_id": pos["id"]})).structured_content
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
