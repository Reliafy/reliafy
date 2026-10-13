"""Reliafy Maintenance photos: the size and formats read, decoding off the
event loop a few at a time, photo links' places, expiry and maker, removed
photos and declined locations."""

import io
import struct
import zlib
from datetime import datetime, timedelta, timezone

import mongomock
import pytest
from PIL import Image

from backend.maintenance import photos
from backend.maintenance.service import PROJECTORS, Maintenance
from backend.maintenance.store import GraphStore

UID = "user-l"


def _png_gray(w: int, h: int) -> bytes:
    raw = zlib.compress(b"".join(b"\x00" + b"\x00" * w for _ in range(h)), 9)

    def chunk(t, d):
        return struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xffffffff)

    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 0, 0, 0, 0))
            + chunk(b"IDAT", raw) + chunk(b"IEND", b""))


def _jpeg(size=(800, 600), gps=True) -> bytes:
    from PIL.TiffImagePlugin import IFDRational

    img = Image.new("RGB", size, (200, 30, 30))
    exif = Image.Exif()
    if gps:
        exif[0x8825] = {1: "S", 2: (IFDRational(27), IFDRational(28), IFDRational(12)),
                        3: "E", 4: (IFDRational(153), IFDRational(1), IFDRational(30))}
    buf = io.BytesIO()
    img.save(buf, "JPEG", exif=exif)
    return buf.getvalue()


@pytest.fixture()
def api(monkeypatch, tmp_path):
    from fastapi.testclient import TestClient

    from backend import config, db
    from backend.auth import get_current_user
    from backend.main import app
    from backend.routers import maintenance as router

    monkeypatch.setattr(config, "AUTH_DISABLED", False)
    monkeypatch.setattr(config, "BILLING_ENABLED", False)
    monkeypatch.setattr(config, "MAINTENANCE_ENABLED", True)
    monkeypatch.setattr(config, "MAINTENANCE_EMAILS", {"l@example.org"})
    test_db = mongomock.MongoClient()["maint_limits_api"]
    monkeypatch.setattr(db, "_db", test_db)
    monkeypatch.setattr(db, "_simulated", True)
    monkeypatch.setattr(router, "_store", GraphStore(":memory:", PROJECTORS))
    monkeypatch.setattr(router, "_photo_store", photos.FilePhotoStore(str(tmp_path)))
    user = {"uid": UID, "email": "l@example.org", "name": "L", "email_verified": True}
    test_db.users.insert_one({"_id": UID, "email": "l@example.org", "name": "L", "email_verified": True})
    app.dependency_overrides[get_current_user] = lambda: user
    try:
        yield {"client": TestClient(app), "db": test_db, "user": user, "app": app, "router": router}
    finally:
        app.dependency_overrides.clear()



# ---- photos ------------------------------------------------------------------------------------

def test_photos_over_the_pixel_limit_are_refused_before_decoding():
    with pytest.raises(photos.BadPhoto, match="too large"):
        photos.clean(_png_gray(7000, 7000))  # 49 Mpx in a few KB
    with pytest.raises(photos.BadPhoto, match="too large"):
        photos.clean(_png_gray(10000, 11900))
    assert photos.clean(_png_gray(2000, 1500))["width"] == photos.FULL_PX


def test_only_jpeg_png_and_webp_are_read():
    for fmt in ("BMP", "TIFF", "GIF"):
        buf = io.BytesIO()
        Image.new("RGB", (50, 50)).save(buf, fmt)
        with pytest.raises(photos.BadPhoto):
            photos.clean(buf.getvalue())
    for fmt in ("PNG", "WEBP"):
        buf = io.BytesIO()
        Image.new("RGB", (50, 50)).save(buf, fmt)
        assert photos.clean(buf.getvalue())["width"] == 50


def test_any_decoder_failure_is_an_unreadable_photo(monkeypatch):
    def broken(img):
        raise ZeroDivisionError("bad header")

    monkeypatch.setattr(photos.ImageOps, "exif_transpose", broken)
    with pytest.raises(photos.BadPhoto, match="isn't a photo"):
        photos.clean(_jpeg())


def test_photo_decoding_waits_for_a_free_slot(monkeypatch):
    import threading

    monkeypatch.setattr(photos, "_decoding", threading.BoundedSemaphore(1))
    monkeypatch.setattr(photos, "DECODE_WAIT", 0.01)
    photos._decoding.acquire()
    try:
        with pytest.raises(photos.Busy):
            photos.clean(_jpeg())
    finally:
        photos._decoding.release()
    assert photos.clean(_jpeg())["gps"]


def test_link_places_are_taken_one_at_a_time_and_expire():
    links = photos.PhotoLinks(mongomock.MongoClient()["links_places"])
    doc, _ = links.create(UID, UID, {"id": "p1", "label": "Position", "name": "Pump"})
    assert all(links.reserve(doc["_id"]) for _ in range(photos.MAX_PER_LINK))
    assert not links.reserve(doc["_id"])
    links.release(doc["_id"])
    assert links.reserve(doc["_id"])
    links._links.update_one({"_id": doc["_id"]}, {"$set": {"n": 0, "expires_at": datetime.now(timezone.utc)
                                                           - timedelta(minutes=1)}})
    assert not links.reserve(doc["_id"])


def test_a_declined_location_is_dropped():
    links = photos.PhotoLinks(mongomock.MongoClient()["links_gps"])
    doc, _ = links.create(UID, UID, {"id": "p1", "label": "Position", "name": "Pump"})
    links.add_photo(doc["_id"], "ph1", {"lat": -27.47, "lon": 153.02})
    links.add_photo(doc["_id"], "ph2", {"lat": -27.48, "lon": 153.03})
    assert links.answer(doc["_id"], "ph1", "declined")["lat"] == -27.47
    assert links.answer(doc["_id"], "ph1", "saved") is None  # answered once
    stored = links.get(doc["_id"])
    assert stored["gps_offers"][0] == {"photo_id": "ph1", "answer": "declined"}
    assert photos.PhotoLinks.public(stored)["location_offers"] == [
        {"photo_id": "ph1", "answer": "declined"},
        {"photo_id": "ph2", "lat": -27.48, "lon": 153.03, "answer": None}]


def test_the_links_index_is_made_once_per_database(monkeypatch):
    db = mongomock.MongoClient()["links_index"]
    calls = []
    real = type(db["maintenance_photo_links"]).create_index
    monkeypatch.setattr(type(db["maintenance_photo_links"]), "create_index",
                        lambda self, *a, **k: (calls.append(a), real(self, *a, **k))[1])
    for _ in range(3):
        photos.PhotoLinks(db)
    assert len(calls) == 1


def test_a_removed_photo_isnt_served_and_its_bytes_are_deleted(api):
    client, router = api["client"], api["router"]
    pid = client.post("/api/maintenance/positions", json={"name": "P"}).json()["id"]
    photo_id = client.post(f"/api/maintenance/photos?target_id={pid}", content=_jpeg(gps=False)).json()["photo"]["id"]
    got = client.get(f"/api/maintenance/photos/{photo_id}?size=full")
    assert got.status_code == 200 and "max-age=300" in got.headers["cache-control"]
    assert client.delete(f"/api/maintenance/photos/{photo_id}").status_code == 200
    assert client.get(f"/api/maintenance/photos/{photo_id}?size=full").status_code == 404
    assert router.get_photo_store().get(photo_id, "full") is None
    assert client.post(f"/api/maintenance/photos?target_id={pid}", content=_png_gray(7000, 7000)).status_code == 422


def _link(api, pid):
    link = api["client"].post("/api/maintenance/photo-links", json={"target_id": pid}).json()
    return link, link["url"].split("testserver", 1)[1]


def test_links_check_their_form_before_the_database(api, monkeypatch):
    client, router = api["client"], api["router"]

    def no_db():
        raise AssertionError("database used")

    monkeypatch.setattr(router, "photo_links", no_db)
    for path in ("/photos/up/x?t=x", "/photos/up/" + "0" * 24, "/photos/up/" + "g" * 24 + "?t=abc"):
        assert client.post(path, content=b"x").status_code == 404
        assert client.post(path.split("?")[0] + "/location" + ("?" + path.split("?")[1] if "?" in path else ""),
                           json={"photo_id": "x", "save": True}).status_code == 404
        assert client.get(path).status_code == 404


def test_a_link_stops_working_once_expired_or_its_maker_loses_access(api, monkeypatch):
    from backend import config

    client, db = api["client"], api["db"]
    pid = client.post("/api/maintenance/positions", json={"name": "Pool pump"}).json()["id"]
    link, path = _link(api, pid)
    sent = client.post(path, content=_jpeg())
    assert sent.status_code == 200 and sent.json()["location_offer"]
    base, query = path.split("?")
    # Expired: no more photos, and no location answers.
    db.maintenance_photo_links.update_one({"_id": link["link_id"]},
                                          {"$set": {"expires_at": datetime.now(timezone.utc) - timedelta(minutes=1)}})
    assert client.post(path, content=_jpeg()).status_code == 410
    answer = client.post(f"{base}/location?{query}", json={"photo_id": sent.json()["photo_id"], "save": True})
    assert answer.status_code == 410
    assert Maintenance(api["router"].get_store(), UID).position(pid)["coordinates"] is None
    # A fresh link, from someone no longer allowed Maintenance.
    link, path = _link(api, pid)
    monkeypatch.setattr(config, "MAINTENANCE_EMAILS", set())
    assert client.post(path, content=_jpeg()).status_code == 410
    monkeypatch.setattr(config, "MAINTENANCE_EMAILS", {"l@example.org"})
    assert client.post(path, content=_jpeg()).status_code == 200
    doc = db.maintenance_photo_links.find_one({"_id": link["link_id"]})
    assert doc["n"] == 1 and len(doc["photos"]) == 1


def test_a_refused_photo_gives_its_link_place_back(api):
    client, db = api["client"], api["db"]
    pid = client.post("/api/maintenance/positions", json={"name": "P"}).json()["id"]
    link, path = _link(api, pid)
    assert client.post(path, content=b"not an image").status_code == 422
    assert client.post(path, content=_png_gray(7000, 7000)).status_code == 422
    assert db.maintenance_photo_links.find_one({"_id": link["link_id"]})["n"] == 0


def test_a_team_link_needs_its_maker_still_able_to_edit(api, monkeypatch):
    from backend.routers import maintenance as router
    from backend.services import access as access_service

    doc = {"uid": UID, "org": "team:t1"}
    assert not router._creator_may_write(doc)  # not a member
    api["db"].teams.insert_one({"_id": "t1", "owner_uid": UID, "members": [{"uid": UID}],
                                "created_at": datetime.now(timezone.utc)})
    assert router._creator_may_write(doc)
    monkeypatch.setattr(access_service, "member_can_edit", lambda *a: False)
    assert not router._creator_may_write(doc)
    assert not router._creator_may_write({"uid": UID, "org": "someone-else"})
