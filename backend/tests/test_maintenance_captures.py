"""Field reports (backend/maintenance/captures.py, routers/field_reports.py):
notes, photos, sound and files recorded in the field. Sending anything twice
never makes a second copy; an attachment resumes from where the server got to;
photos are cleaned, sound is kept as it came with its length; content is
deleted at the end of its keep time while the record stays; a rebuilt graph
equals the live one."""

import matplotlib

matplotlib.use("Agg")

import hashlib
import io
import struct
import uuid
from datetime import date, datetime, timedelta, timezone

import mongomock
import pytest
from PIL import Image

from backend.maintenance import captures, photos
from backend.maintenance.service import PROJECTORS, Invalid, LimitReached, Maintenance, NotFound
from backend.maintenance.store import GraphStore
from backend.tests.test_api_tools import A, B, _auth, env, maint  # noqa: F401 - fixtures
from backend.tests.test_maintenance_documents import pdf

pytestmark = pytest.mark.usefixtures("mcp_on")

UID = "user-c"


def new_id() -> str:
    return uuid.uuid4().hex


def jpeg(size=(1800, 1200), gps=True, colour=(200, 60, 40)) -> bytes:
    img = Image.new("RGB", size, colour)
    exif = Image.Exif()
    exif[271] = "PhoneMaker"
    if gps:
        exif[0x8825] = {1: "S", 2: (27.0, 28.0, 12.0), 3: "E", 4: (153.0, 1.0, 30.0)}
    buf = io.BytesIO()
    img.save(buf, "JPEG", exif=exif)
    return buf.getvalue()


def m4a(seconds: float = 12.5, size: int = 3000) -> bytes:
    """Bytes shaped like an .m4a: an ftyp box, a movie header saying how long, padding."""
    ftyp = struct.pack(">I", 20) + b"ftypM4A \x00\x00\x00\x00M4A "
    mvhd = b"mvhd" + bytes(4) + bytes(8) + struct.pack(">II", 1000, int(seconds * 1000))
    moov = struct.pack(">I", 8 + 4 + len(mvhd)) + b"moov" + struct.pack(">I", 4 + len(mvhd)) + mvhd
    body = ftyp + moov
    return body + bytes((i * 7) % 251 for i in range(max(0, size - len(body))))


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


@pytest.fixture()
def world(tmp_path):
    store = GraphStore(":memory:", PROJECTORS)
    m = Maintenance(store, UID, UID)
    db = mongomock.MongoClient()["captures"]
    c = captures.Captures(m, captures.FileCaptureStore(str(tmp_path / "captures")),
                          photos.FilePhotoStore(str(tmp_path / "photos")), db)
    return m, c


def send(c, cid, mid, data, kind, piece=None, **declared):
    """Declare and send an attachment in pieces; the last answer."""
    out = c.declare(cid, mid, kind=kind, size=len(data), sha256=sha(data), **declared)
    step = piece or len(data)
    while not out["complete"]:
        at = out["received"]
        out = c.append(cid, mid, at, data[at:at + step])
    return out


# ---- the report itself --------------------------------------------------------------------

def test_a_report_is_made_once_whatever_is_sent_again(world):
    m, c = world
    pos = m.create_position("Feed pump")
    wo = m.open_work_order(pos["id"], "Check seal") if hasattr(m, "open_work_order") else None
    cid = new_id()
    about = [pos["id"], "0" * 32] + ([wo["id"]] if wo else [])
    first = c.create(cid, notes="Seal weeping on the drive end.\r\nAbout a drop a second.",
                     taken_at="2026-11-12T09:30:00+10:00", device_tz="Australia/Brisbane", about=about,
                     location={"lat": -27.4698, "lon": 153.0251, "accuracy_m": 8}, media_expected=2,
                     by_name="Sam", via="app")
    assert first["created"] is True and first["number"] == 1 and first["title"] == "Field report 1"
    assert first["status"] == "new" and first["notes"].splitlines()[1] == "About a drop a second."
    assert first["location"] == {"lat": -27.4698, "lon": 153.0251, "accuracy_m": 8.0}
    assert {a["id"] for a in first["about"]} == set(about) - {"0" * 32} and first["about_missing"] == 1
    assert first["taken_at"] == "2026-11-12T09:30:00+10:00" and first["by"] == UID and first["by_name"] == "Sam"
    assert first["media_expected"] == 2 and first["complete"] is False
    events = m.s.event_count(UID)

    # Sent again (a lost answer), even with other words: the report that exists, untouched.
    again = c.create(cid, notes="something else", about=[])
    assert again["created"] is False and again["notes"] == first["notes"] and again["number"] == 1
    assert m.s.event_count(UID) == events
    # A dashed UUID is the same id.
    assert c.get(str(uuid.UUID(cid)))["id"] == cid

    # Notes and location are not in the event log (it can never be rewritten).
    logged = str(m.s.events(UID, limit=500))
    assert "capture.created" in logged and "weeping" not in logged and "153.0251" not in logged
    node = m.s.node(UID, cid, "Capture")
    assert "notes" not in node and "location" not in node and node["has_notes"] and node["has_location"]

    with pytest.raises(Invalid, match="UUID"):
        c.create("not-an-id")
    with pytest.raises(Invalid, match="already used"):
        c.create(pos["id"])
    with pytest.raises(Invalid, match="at most"):
        c.create(new_id(), notes="x" * (captures.MAX_NOTES + 1))
    with pytest.raises(Invalid, match="lat"):
        c.create(new_id(), location={"lat": 123, "lon": 0})
    assert len(c.list()["reports"]) == 1  # nothing half-made by the refusals


def test_a_bad_phone_clock_never_loses_a_report(world):
    m, c = world
    ahead = (datetime.now(timezone.utc) + timedelta(hours=3)).isoformat()
    out = c.create(new_id(), notes="clock ahead", taken_at=ahead)
    assert out["clock_suspect"] is True and out["created"]
    assert c.create(new_id(), notes="no time given")["clock_suspect"] is False
    assert c.create(new_id(), taken_at="2026-11-12T09:30:00")["taken_at"].endswith("+00:00")
    with pytest.raises(Invalid, match="taken_at"):
        c.create(new_id(), taken_at="yesterday")


def test_list_filters_and_previews(world):
    m, c = world
    pos = m.create_position("Conveyor")
    a = c.create(new_id(), notes="n" * 300, about=[pos["id"]])
    b = c.create(new_id(), notes="short")
    c.set_status(b["id"], "parsed", "Reading added to the meter")
    listing = c.list()
    assert [r["number"] for r in listing["reports"]] == [2, 1] and listing["counts"] == {"new": 1, "parsed": 1, "done": 0}
    brief = next(r for r in listing["reports"] if r["id"] == a["id"])
    assert "notes" not in brief and len(brief["notes_preview"]) == 201 and brief["notes_preview"].endswith("…")
    assert [r["id"] for r in c.list(status="parsed")["reports"]] == [b["id"]]
    assert [r["id"] for r in c.list(about_id=pos["id"])["reports"]] == [a["id"]]
    assert len(c.list(mine=True)["reports"]) == 2
    other = captures.Captures(Maintenance(m.s, UID, "someone-else"), c.files, c.photos, c.uploads._docs.database)
    assert other.list(mine=True)["reports"] == []
    with pytest.raises(Invalid):
        c.list(status="nope")


# ---- attachments ----------------------------------------------------------------------------

def test_a_photo_is_cleaned_and_shown_on_the_report(world):
    m, c = world
    cid, mid = c.create(new_id(), notes="photo")["id"], new_id()
    raw = jpeg()
    out = send(c, cid, mid, raw, "photo", piece=1000, caption="Drive end", mime="image/jpeg")
    assert out["complete"] and out["media"]["kind"] == "photo" and out["media"]["caption"] == "Drive end"
    assert max(out["media"]["width"], out["media"]["height"]) == photos.FULL_PX
    data, mime, _ = c.served(cid, mid)
    kept = Image.open(io.BytesIO(data))
    assert mime == "image/jpeg" and len(kept.getexif()) == 0 and kept.size == (1600, 1067)
    assert max(Image.open(io.BytesIO(c.served(cid, mid, "thumb")[0])).size) == photos.THUMB_PX
    assert c.files.read(mid) is None  # the original, with its metadata, isn't kept
    report = c.get(cid)
    assert report["counts"] == {"photo": 1, "audio": 0, "file": 0} and report["location"] is None
    # It is an ordinary photo: it can be shown on the pump it is of.
    pos = m.create_position("Feed pump")
    m.link_photo(mid, pos["id"])
    assert [p["id"] for p in m.photos_of(pos["id"])] == [mid]
    assert m.photo(mid)["on"][-1]["kind"] == "Capture"


def test_sound_is_kept_as_it_came_with_its_length(world):
    m, c = world
    cid, mid = c.create(new_id())["id"], new_id()
    raw = m4a(seconds=12.5, size=5000)
    out = send(c, cid, mid, raw, "audio", piece=1024, duration_s=99, mime="audio/m4a", name="Bearing noise.m4a")
    media = out["media"]
    assert media == {"id": mid, "kind": "audio", "mime": "audio/mp4", "size": 5000, "name": "Bearing noise.m4a",
                     "duration_s": 12.5}  # the file's own length wins over what the sender said
    assert c.served(cid, mid) == (raw, "audio/mp4", "Bearing noise.m4a")
    assert c.get(cid)["audio_seconds"] == 12.5
    # A browser's recording (WebM) has no simple header: the sender's length is kept.
    web, wid = b"\x1aE\xdf\xa3" + b"\x42\x82\x84webmA_OPUS" + bytes(500), new_id()
    assert send(c, cid, wid, web, "audio", duration_s=7.26)["media"] | {"name": ""} == {
        "id": wid, "kind": "audio", "mime": "audio/webm", "size": len(web), "name": "", "duration_s": 7.3}
    for bad, words in ((b"<html>" + bytes(100), "isn't a sound recording"),
                       (struct.pack(">I", 20) + b"ftypisom" + bytes(8) + b"hdlr" + bytes(8) + b"vide" + bytes(50),
                        "Video")):
        bid = new_id()
        with pytest.raises(Invalid, match=words):
            send(c, cid, bid, bad, "audio")
        with pytest.raises(Invalid, match=words):  # asked again: the same answer, nothing to resend
            c.declare(cid, bid, kind="audio", size=len(bad), sha256=sha(bad))
        assert c.files.read(bid) is None
    assert c.get(cid)["counts"]["audio"] == 2


def test_a_file_is_a_pdf(world):
    m, c = world
    cid, mid = c.create(new_id())["id"], new_id()
    out = send(c, cid, mid, pdf("Permit"), "file", name="../Permit to work.PDF")
    assert out["media"]["mime"] == "application/pdf" and out["media"]["name"] == "Permit to work.pdf"
    with pytest.raises(Invalid, match="isn't a PDF"):
        send(c, cid, new_id(), b"PK\x03\x04 workbook", "file")


def test_an_upload_resumes_and_a_repeat_is_ignored(world):
    m, c = world
    cid, mid = c.create(new_id())["id"], new_id()
    raw = m4a(size=10_000)
    d = c.declare(cid, mid, kind="audio", size=len(raw), sha256=sha(raw), duration_s=3)
    assert d == {"media_id": mid, "complete": False, "received": 0, "size": 10_000,
                 "chunk_bytes": captures.CHUNK_BYTES, "max_chunk_bytes": captures.MAX_CHUNK_BYTES}
    assert c.append(cid, mid, 0, raw[:4000])["received"] == 4000
    # The answer was lost and the phone sends the piece again: accepted, nothing doubled.
    assert c.append(cid, mid, 0, raw[:4000])["received"] == 4000
    # The app was killed; on restart it asks where the server got to.
    assert c.declare(cid, mid, kind="audio", size=len(raw), sha256=sha(raw))["received"] == 4000
    # A piece from too far on is refused with where to carry on from.
    with pytest.raises(captures.OffsetConflict) as gap:
        c.append(cid, mid, 6000, raw[6000:8000])
    assert gap.value.received == 4000
    # A piece overlapping what is there: only its new bytes are taken.
    assert c.append(cid, mid, 3000, raw[3000:7000])["received"] == 7000
    with pytest.raises(Invalid, match="must fit"):
        c.append(cid, mid, 7000, raw[7000:] + b"extra")
    done = c.append(cid, mid, 7000, raw[7000:])
    assert done["complete"] and c.served(cid, mid)[0] == raw
    events = m.s.event_count(UID)
    # Everything after that is a repeat: the last piece, the declaration, the whole file.
    assert c.append(cid, mid, 7000, raw[7000:])["complete"]
    assert c.declare(cid, mid, kind="audio", size=len(raw))["complete"]
    assert send(c, cid, mid, raw, "audio")["media"]["id"] == mid
    assert m.s.event_count(UID) == events and c.get(cid)["counts"]["audio"] == 1
    # The same id for another file is a mistake, said plainly.
    other = new_id()
    c.declare(cid, other, kind="audio", size=500)
    with pytest.raises(Invalid, match="different file"):
        c.declare(cid, other, kind="audio", size=600)
    with pytest.raises(NotFound):
        c.append(cid, new_id(), 0, b"x")  # never declared


def test_bytes_that_all_arrived_but_were_never_recorded_are_recorded_on_the_next_ask(world, monkeypatch):
    m, c = world
    cid, mid = c.create(new_id())["id"], new_id()
    raw = jpeg(size=(400, 300))
    c.declare(cid, mid, kind="photo", size=len(raw), sha256=sha(raw))

    def busy(_raw):
        raise photos.Busy("Too many photos are being processed right now. Try again in a minute.")

    monkeypatch.setattr(photos, "clean", busy)
    with pytest.raises(photos.Busy):
        c.append(cid, mid, 0, raw)
    assert c.files.size(mid) == len(raw) and c.get(cid)["counts"]["photo"] == 0  # kept, not recorded
    monkeypatch.undo()
    assert c.declare(cid, mid, kind="photo", size=len(raw), sha256=sha(raw))["complete"]
    assert c.get(cid)["counts"]["photo"] == 1


def test_damaged_bytes_start_again_and_an_unreadable_photo_is_refused_for_good(world):
    m, c = world
    cid, mid = c.create(new_id())["id"], new_id()
    raw = m4a(size=2000)
    c.declare(cid, mid, kind="audio", size=len(raw), sha256=sha(raw))
    with pytest.raises(captures.OffsetConflict) as damaged:
        c.append(cid, mid, 0, raw[:1000] + bytes(1000))
    assert damaged.value.received == 0 and c.files.size(mid) == 0
    assert c.append(cid, mid, 0, raw)["complete"]

    bad = new_id()
    with pytest.raises(Invalid, match="isn't a photo"):
        send(c, cid, bad, b"%PDF-1.4 not a photo", "photo")
    with pytest.raises(Invalid, match="isn't a photo"):
        c.append(cid, bad, 0, b"%PDF-1.4 not a photo")
    assert c.get(cid)["counts"] == {"photo": 0, "audio": 1, "file": 0}


def test_limits(world, monkeypatch):
    m, c = world
    cid = c.create(new_id())["id"]
    for kind, words in (("photo", "over 20 MB"), ("audio", "over 40 MB"), ("file", "over 20 MB")):
        with pytest.raises(LimitReached, match=words):
            c.declare(cid, new_id(), kind=kind, size=41 * 1024 * 1024)
    with pytest.raises(Invalid, match="empty"):
        c.declare(cid, new_id(), kind="audio", size=0)
    with pytest.raises(Invalid, match="kind"):
        c.declare(cid, new_id(), kind="video", size=10)
    with pytest.raises(LimitReached, match="60 minutes"):
        c.declare(cid, new_id(), kind="audio", size=10, duration_s=3601)
    monkeypatch.setattr(captures, "MAX_PHOTOS_EACH", 1)
    send(c, cid, new_id(), jpeg(size=(200, 200)), "photo")
    with pytest.raises(LimitReached, match="at most 1 photos"):
        c.declare(cid, new_id(), kind="photo", size=10)
    # The workspace's room for sound and files counts what is stored and what is on its way.
    monkeypatch.setattr(captures, "workspace_bytes", lambda: 6000)
    send(c, cid, new_id(), m4a(size=3000), "audio")
    c.declare(cid, new_id(), kind="audio", size=2500)
    with pytest.raises(LimitReached, match="make room"):
        c.declare(cid, new_id(), kind="audio", size=1000)
    monkeypatch.setattr(captures, "MAX_CHUNK_BYTES", 100)
    mid = new_id()
    c.declare(cid, mid, kind="file", size=500)
    with pytest.raises(Invalid, match="A piece is at most"):
        c.append(cid, mid, 0, bytes(101))


# ---- status, keeping, retention ---------------------------------------------------------------

def test_status_keep_and_retention(world, monkeypatch):
    m, c = world
    day = date(2026, 11, 12)
    monkeypatch.setattr(Maintenance, "today", lambda self: day.isoformat())
    pos = m.create_position("Feed pump")
    cid = c.create(new_id(), notes="Leak", location={"lat": 1, "lon": 2})["id"]
    linked, loose, sound = new_id(), new_id(), new_id()
    send(c, cid, linked, jpeg(size=(300, 200)), "photo")
    send(c, cid, loose, jpeg(size=(300, 200), colour=(1, 2, 3)), "photo")
    send(c, cid, sound, m4a(), "audio")
    m.link_photo(linked, pos["id"])  # promoted: shown on the pump as well
    assert c.get(cid)["expires_on"] == "2027-02-10"  # 90 days untouched

    assert c.set_status(cid, "parsed", "Photo linked to the pump")["expires_on"] == "2027-02-10"
    done = c.set_status(cid, "done")
    assert done["status"] == "done" and done["expires_on"] == "2026-12-12"  # 30 days after done
    assert c.set_status(cid, "new")["expires_on"] == "2027-02-10"
    with pytest.raises(Invalid, match="one of new, parsed, done"):
        c.set_status(cid, "rejected")
    kept = c.keep(cid)
    assert kept["keep"] is True and kept["expires_on"] is None
    assert c.keep(cid, False)["expires_on"] == "2027-02-10"
    monkeypatch.setattr(captures, "MAX_KEPT", 1)
    c.keep(cid)
    extra = c.create(new_id())["id"]
    with pytest.raises(LimitReached, match="At most 1"):
        c.keep(extra)
    c.expire(extra, "deleted")
    c.keep(cid, False)
    c.set_status(cid, "done")

    assert c.expire_due() == 0
    day = date(2026, 12, 12)
    untouched = c.create(new_id(), notes="later")["id"]
    assert c.expire_due() == 1
    gone = c.get(cid)
    assert gone["expired"] and gone["notes"] == "" and gone["location"] is None and gone["media"] == []
    assert gone["status"] == "done" and gone["number"] == 1  # the record that it existed stays
    assert c.files.content(cid) is None and c.files.read(sound) is None
    assert c.served(cid, sound) is None and c.served(cid, loose) is None
    assert c.photos.get(loose, "full") is None and m.photo(loose)["removed"] is True
    # The photo someone linked to the pump is still there, and only there.
    assert c.photos.get(linked, "full") is not None
    assert [t["kind"] for t in m.photo(linked)["on"]] == ["Position"]
    assert [r["id"] for r in c.list()["reports"]] == [untouched]
    assert len(c.list(include_expired=True)["reports"]) == 3
    with pytest.raises(Invalid, match="deleted"):
        c.declare(cid, new_id(), kind="photo", size=10)
    assert c.expire(cid) == {"expired": cid, "photos_removed": 0, "media_removed": 0}  # again: nothing to do

    # Deleting by hand is the same thing, now.
    assert c.expire(untouched, "deleted")["expired"] == untouched
    assert c.get(untouched)["expired"] and c.list()["reports"] == []


def test_the_daily_run_expires_reports(world, monkeypatch, tmp_path):
    from backend.maintenance import daily
    from backend.routers import field_reports
    from backend.routers import maintenance as router

    m, c = world
    monkeypatch.setattr(field_reports, "_capture_store", c.files)
    monkeypatch.setattr(router, "_photo_store", c.photos)
    cid = c.create(new_id(), notes="old")["id"]
    send(c, cid, new_id(), m4a(), "audio")
    fresh = c.create(new_id(), notes="new")["id"]
    db = mongomock.MongoClient()["daily_captures"]
    day = date.fromisoformat(m.today())
    assert "field_reports" in daily.run(db, m.s, today=day) and not c.get(cid)["expired"]
    monkeypatch.setattr(Maintenance, "today", lambda self: (day + timedelta(days=captures.KEEP_DAYS)).isoformat())
    c.keep(fresh)
    result = daily.run(db, m.s, today=day + timedelta(days=captures.KEEP_DAYS))
    assert result["field_reports"] == {"orgs": 1, "expired": 1}
    assert c.get(cid)["expired"] and not c.get(fresh)["expired"]


def test_a_rebuilt_graph_equals_the_live_one(world, monkeypatch):
    m, c = world
    pos = m.create_position("Feed pump")
    cid = c.create(new_id(), notes="Leak", about=[pos["id"], "f" * 32], media_expected=3)["id"]
    photo = new_id()
    send(c, cid, photo, jpeg(size=(300, 200)), "photo", caption="Seal")
    send(c, cid, new_id(), m4a(), "audio", duration_s=4)
    send(c, cid, new_id(), pdf(), "file", name="permit.pdf")
    m.link_photo(photo, pos["id"])
    c.set_status(cid, "parsed", "linked")
    c.keep(cid)
    c.keep(cid, False)
    c.set_status(cid, "done")
    second = c.create(new_id(), notes="second")["id"]
    send(c, second, new_id(), jpeg(size=(200, 200)), "photo")
    before = m.s.snapshot()
    m.s.rebuild()
    assert m.s.snapshot() == before
    c.expire(cid, "deleted")
    c.expire(second)
    before = m.s.snapshot()
    m.s.rebuild()
    assert m.s.snapshot() == before


@pytest.mark.parametrize("make", ["file", "mongo"])
def test_the_stores_keep_pieces_in_order(tmp_path, make):
    store = (captures.FileCaptureStore(str(tmp_path)) if make == "file"
             else captures.MongoCaptureStore(mongomock.MongoClient()["capture_store"]))
    mid, cid = new_id(), new_id()
    assert store.size(mid) == 0 and store.read(mid) is None
    store.append(mid, 0, b"abc")
    store.append(mid, 3, b"defg")
    store.append(mid, 3, b"defg")  # the same piece again
    assert store.size(mid) == 7 and store.read(mid) == b"abcdefg"
    store.delete(mid)
    assert store.size(mid) == 0 and store.read(mid) is None
    store.put_content(cid, "org", {"notes": "n", "location": None})
    assert store.content(cid) == {"notes": "n", "location": None}
    assert store.contents([cid, new_id()]) == {cid: {"notes": "n", "location": None}}
    store.delete_content(cid)
    assert store.content(cid) is None
    if make == "file":
        with pytest.raises(KeyError):
            store.append("../../etc/passwd", 0, b"x")


def test_sniffing():
    assert captures.sniff_audio(m4a()) == "audio/mp4" and captures.mp4_seconds(m4a(61.2)) == 61.2
    assert captures.sniff_audio(b"OggS" + bytes(20)) == "audio/ogg"
    assert captures.sniff_audio(b"RIFF\x00\x00\x00\x00WAVEfmt ") == "audio/wav"
    assert captures.sniff_audio(b"ID3\x03" + bytes(20)) == "audio/mpeg"
    assert captures.sniff_audio(b"\xff\xf1" + bytes(20)) == "audio/aac"
    assert captures.sniff_audio(b"\x1aE\xdf\xa3" + b"V_VP9" + bytes(20)) is None
    assert captures.sniff_audio(b"") is None and captures.mp4_seconds(b"mvhd") is None


# ---- over HTTP: the phone and the CLI (/api/v1), the web inbox (/api/maintenance) ------------

@pytest.fixture()
def http(maint, monkeypatch, tmp_path):
    from backend.routers import field_reports

    monkeypatch.setattr(field_reports, "_capture_store", captures.FileCaptureStore(str(tmp_path / "captures")))
    return maint


BASE = "/api/v1/maintenance/captures"


def test_the_api_end_to_end(http):
    c, head = http.client, _auth(http.token[A])
    pos = http.post("/api/v1/maintenance/positions.create", {"name": "Pump A"}).json()
    cid, photo, sound = new_id(), new_id(), new_id()
    body = {"notes": "Bearing is loud", "taken_at": "2026-11-12T09:30:00+10:00", "about_id": pos["id"],
            "media_expected": 2}
    made = c.put(f"{BASE}/{cid}", json={**body, "via": "app"}, headers=head)
    assert made.status_code == 200, made.text
    assert made.json()["created"] is True and made.json()["via"] == "app" and made.json()["by_name"] == "A"
    assert c.put(f"{BASE}/{cid}", json=body, headers=head).json()["created"] is False

    raw = jpeg()
    d = c.post(f"{BASE}/{cid}/media/{photo}", json={"kind": "photo", "size": len(raw), "sha256": sha(raw)},
               headers=head)
    assert d.status_code == 200 and d.json()["received"] == 0
    half = len(raw) // 2
    assert c.put(f"{BASE}/{cid}/media/{photo}?offset=0", content=raw[:half], headers=head).json()["received"] == half
    gap = c.put(f"{BASE}/{cid}/media/{photo}?offset={half + 10}", content=raw[half + 10:], headers=head)
    assert gap.status_code == 409 and gap.json()["received"] == half
    last = c.put(f"{BASE}/{cid}/media/{photo}?offset={half}", content=raw[half:], headers=head)
    assert last.status_code == 200 and last.json()["complete"] is True
    assert c.put(f"{BASE}/{cid}/media/{photo}?offset={half}", content=raw[half:], headers=head).json()["complete"]

    clip = m4a(seconds=8, size=4000)
    c.post(f"{BASE}/{cid}/media/{sound}", json={"kind": "audio", "size": len(clip)}, headers=head)
    assert c.put(f"{BASE}/{cid}/media/{sound}?offset=0", content=clip, headers=head).json()["media"]["duration_s"] == 8

    got = c.get(f"{BASE}/{cid}", headers=head).json()
    assert got["complete"] and got["counts"] == {"photo": 1, "audio": 1, "file": 0} and "data_notice" in got
    assert got["via"] == "app"
    assert got["about"] == [{"id": pos["id"], "kind": "Position", "name": "Pump A"}]
    img = c.get(f"{BASE}/{cid}/media/{photo}?size=thumb", headers=head)
    assert img.headers["content-type"] == "image/jpeg" and img.headers["x-content-type-options"] == "nosniff"
    assert len(Image.open(io.BytesIO(img.content)).getexif()) == 0
    part = c.get(f"{BASE}/{cid}/media/{sound}", headers={**head, "Range": "bytes=100-199"})
    assert part.status_code == 206 and part.content == clip[100:200]
    assert part.headers["content-range"] == f"bytes 100-199/{len(clip)}"
    assert c.get(f"{BASE}/{cid}/media/{sound}", headers={**head, "Range": "bytes=-50"}).content == clip[-50:]
    assert c.get(f"{BASE}/{cid}/media/{sound}", headers={**head, "Range": "bytes=9999-"}).status_code == 416
    assert c.get(f"{BASE}/{cid}/media/{new_id()}", headers=head).status_code == 404

    # POST works where PUT does (a browser on another origin may only GET and POST).
    pid, page = new_id(), pdf()
    assert c.post(f"{BASE}/{cid}", json=body, headers=head).json()["created"] is False
    c.post(f"{BASE}/{cid}/media/{pid}", json={"kind": "file", "size": len(page), "name": "p.pdf"}, headers=head)
    sent = c.post(f"{BASE}/{cid}/media/{pid}/bytes?offset=0", content=page, headers=head)
    assert sent.status_code == 200 and sent.json()["media"]["name"] == "p.pdf"
    assert c.delete(f"/api/maintenance/captures/{cid}").status_code == 401

    listed = c.get(f"{BASE}?mine=true", headers=head).json()
    assert [r["id"] for r in listed["reports"]] == [cid] and listed["keep_days"] == 90
    assert c.post(f"{BASE}/{cid}/status", json={"status": "parsed", "note": "ok"}, headers=head).json()[
        "status"] == "parsed"
    assert c.post(f"{BASE}/{cid}/status", json={"status": "gone"}, headers=head).status_code == 422
    assert c.post(f"{BASE}/{cid}/keep", json={}, headers=head).json()["keep"] is True
    assert c.delete(f"{BASE}/{cid}", headers=head).json()["expired"] == cid
    assert c.get(f"{BASE}/{cid}", headers=head).json()["expired"] is True

    # Too big a piece, a bad id, and what a route answers to the wrong caller.
    big = c.put(f"{BASE}/{cid}/media/{new_id()}?offset=0", content=bytes(captures.MAX_CHUNK_BYTES + 1), headers=head)
    assert big.status_code == 413
    assert c.put(f"{BASE}/nope", json={}, headers=head).status_code == 422
    assert c.get(f"{BASE}/{new_id()}", headers=head).status_code == 404
    assert c.get(BASE).status_code == 401
    assert c.get(BASE, headers=_auth(http.token[B])).status_code == 404  # not a Maintenance user
    assert c.get(f"{BASE}/{cid}", headers=_auth(http.token[B])).status_code == 404
    assert c.put(f"{BASE}/{new_id()}", json={}, headers=_auth(http.read_only)).status_code == 403
    assert c.get(BASE, headers=_auth(http.read_only)).status_code == 200


def test_the_spec_lists_them_only_for_maintenance_users(http):
    from backend.routers import field_reports

    spec = http.client.get("/api/v1/openapi.json", headers=_auth(http.token[A])).json()
    for name, entry in field_reports.REST_ONLY.items():
        op = spec["paths"][entry["path"]][entry["method"].lower()]
        assert op["operationId"] == name and op["x-reliafy-rest-only"] is True
    other = http.client.get("/api/v1/openapi.json", headers=_auth(http.token[B])).json()
    assert not any("captures" in p for p in other["paths"])
    listing = http.client.get("/api/v1/tools", headers=_auth(http.token[B])).json()
    assert not any("captures" in r["name"] for r in listing["rest_only"])
    assert not any("captures" in p for p in http.client.get("/api/v1/openapi.json").json()["paths"])


def test_the_web_inbox(http):
    from backend.auth import get_current_user
    from backend.main import app

    c, head = http.client, _auth(http.token[A])
    cid, sound = new_id(), new_id()
    c.put(f"{BASE}/{cid}", json={"notes": "From the phone"}, headers=head)
    clip = m4a()
    c.post(f"{BASE}/{cid}/media/{sound}", json={"kind": "audio", "size": len(clip)}, headers=head)
    c.put(f"{BASE}/{cid}/media/{sound}?offset=0", content=clip, headers=head)
    assert c.get("/api/maintenance/captures").status_code == 401
    app.dependency_overrides[get_current_user] = lambda: {
        "uid": A, "email": "a@example.org", "name": "A", "email_verified": True}
    try:
        inbox = c.get("/api/maintenance/captures").json()
        assert [r["notes_preview"] for r in inbox["reports"]] == ["From the phone"]
        assert c.get(f"/api/maintenance/captures/{cid}").json()["media"][0]["duration_s"] == 12.5
        played = c.get(f"/api/maintenance/captures/{cid}/media/{sound}", headers={"Range": "bytes=0-9"})
        assert played.status_code == 206 and played.content == clip[:10]
        assert c.post(f"/api/maintenance/captures/{cid}/status", json={"status": "done"}).json()["status"] == "done"
        assert c.post(f"/api/maintenance/captures/{cid}/keep", json={"keep": True}).json()["expires_on"] is None
        assert c.delete(f"/api/maintenance/captures/{cid}").json()["media_removed"] == 1
        assert c.get("/api/maintenance/captures").json()["reports"] == []
    finally:
        app.dependency_overrides.pop(get_current_user, None)
