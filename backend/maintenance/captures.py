"""Field reports ("captures"): what someone saw, as they recorded it.

A field report is a bundle of notes, photos, sound recordings and files, made
on a phone (often with no signal) or sent through the API. It may be *about*
something (positions, locations, items or work orders) or about nothing yet.
It is a plain data dump: it changes nothing else in the workspace and proposes
nothing. A person, or their agent, reads it later and makes any changes with
the ordinary screens and tools, then marks it ``parsed`` and ``done``.

Three rules shape this module:

* **Sending twice never makes a second copy.** The report's id and every
  attachment's id are made by the sender. Creating a report that exists
  answers with the one that exists; an attachment that has arrived answers
  "complete"; bytes are sent in pieces by offset, and a piece that is already
  there is accepted and ignored, so a phone can resume from where the server
  got to after a dropped connection, an app kill or a restart.
* **Content lives outside the event log.** The log is never rewritten, so the
  notes, the location and the bytes are kept in a content store
  (:class:`MongoCaptureStore`, :class:`FileCaptureStore`) and the log holds
  only what a report *is* (when, who, what it points at, how many attachments,
  their sizes). That is what lets retention, and a privacy request, really
  delete them.
* **Photos take the ordinary path.** A report's photo is a Photo node shown on
  the report, cleaned by photos.py (turned upright, shrunk, saved as a JPEG
  with no metadata), so it can be linked or moved to the asset it shows like
  any other photo. A location inside a photo is dropped; a report's location
  is its own field, sent only when its author chose to add it.

Sound is kept as it came (AAC in an .m4a from a phone, Opus in WebM or Ogg from
a browser, MP3, WAV), never transcribed, with its length. Files are PDFs,
checked and kept as documents.py keeps them.

Retention: a report's content is deleted :data:`KEEP_DAYS` days after it was
made, or :data:`KEEP_DAYS_DONE` days after it was marked done if that is
sooner, unless it is pinned ("keep"). Photos that were linked to something
else by then stay there. The event log keeps that the report existed.

Events (new types; older logs replay unchanged):

* ``capture.created {id, number, title, taken_at, device_tz, at, on, by,
  by_name, via, about, about_missing, has_notes, has_location, media_expected,
  clock_suspect, expires_on}``
* ``capture.media_added {id, capture_id, kind, mime, size, sha256, name,
  duration_s, on}`` (sound and files; a photo is ``photo.added``)
* ``capture.status {id, status, note, by, on, expires_on}``
* ``capture.kept {id, keep, on, expires_on}``
* ``capture.expired {id, on, reason}``
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import struct
import threading
from datetime import date, datetime, timedelta, timezone

from backend import config
from backend.maintenance.store import GraphStore

STATUSES = ("new", "parsed", "done")
MEDIA_KINDS = ("photo", "audio", "file")
ABOUT_KINDS = ("Position", "Location", "Item", "WorkOrder")
VIA = ("app", "api", "phone")

KEEP_DAYS = 90  # untouched
KEEP_DAYS_DONE = 30  # after it was marked done
MAX_KEPT = 50  # reports pinned in one workspace
MAX_CAPTURES = 20_000  # reports one workspace's graph holds (expired ones count: they stay as records)
MAX_NOTES = 20_000  # characters
MAX_ABOUT = 20
MAX_PHOTOS_EACH = 100
MAX_ATTACHMENTS_EACH = 150
MAX_AUDIO_SECONDS = 60 * 60  # per report
MAX_AUDIO_BYTES = 40 * 1024 * 1024  # one recording (an hour of AAC is about 15-30 MB)
MAX_FILE_BYTES = 20 * 1024 * 1024
MAX_PHOTO_BYTES = 20 * 1024 * 1024  # photos.MAX_UPLOAD_BYTES
#: The piece size a sender should use, and the most one request may carry
#: (well under Cloud Run's 32 MiB request limit).
CHUNK_BYTES = 4 * 1024 * 1024
MAX_CHUNK_BYTES = 8 * 1024 * 1024
SESSION_DAYS = 7  # an unfinished upload is forgotten after this
CLOCK_TOLERANCE = timedelta(minutes=10)
_ID = re.compile(r"^[0-9a-f]{32}$")
_MIME = re.compile(r"^[a-z0-9][a-z0-9.+-]{0,40}/[a-z0-9][a-z0-9.+-]{0,60}$")


def workspace_bytes() -> int:
    """How much sound and file content one workspace's reports may hold."""
    return int(getattr(config, "MAINTENANCE_CAPTURE_BYTES", 100 * 1024 * 1024))


def _sv():
    from backend.maintenance import service

    return service


class OffsetConflict(Exception):
    """A piece didn't start where the server has got to: ``received`` is where
    to carry on from (HTTP 409)."""

    def __init__(self, received: int, text: str):
        super().__init__(text)
        self.received = received


def clean_id(value, what: str = "id") -> str:
    """An id made by the sender: 32 hex digits (a UUID, with or without dashes)."""
    text = str(value or "").strip().lower().replace("-", "")
    if not _ID.match(text):
        raise _sv().Invalid(f"The {what} must be a UUID (32 hex digits) made by the sender; got {str(value)[:40]!r}.")
    return text


# ---- projectors ---------------------------------------------------------------------------

def _created(s: GraphStore, org: str, p: dict) -> None:
    s.put_node(org, p["id"], "Capture", {
        "number": p["number"], "title": p["title"], "status": "new", "status_note": "", "status_by": None,
        "status_on": None, "taken_at": p["taken_at"], "device_tz": p.get("device_tz"), "received_at": p["at"],
        "created_on": p["on"], "by": p.get("by"), "by_name": p.get("by_name", ""), "via": p.get("via", "app"),
        "has_notes": bool(p.get("has_notes")), "has_location": bool(p.get("has_location")),
        "media_expected": p.get("media_expected"), "about_missing": list(p.get("about_missing") or []),
        "clock_suspect": bool(p.get("clock_suspect")), "media": [], "keep": False,
        "expires_on": p.get("expires_on"), "expired": False, "expired_on": None, "expired_reason": None,
    })
    for target in p.get("about") or []:
        s.put_edge(org, "ABOUT", p["id"], target)


def _media_added(s: GraphStore, org: str, p: dict) -> None:
    capture = s.node(org, p["capture_id"])
    media = [dict(m) for m in capture.get("media") or []]
    if any(m["id"] == p["id"] for m in media):
        return  # the same attachment recorded twice (two sends at the same moment): once
    media.append({k: p.get(k) for k in ("id", "kind", "mime", "size", "sha256", "name", "duration_s")}
                 | {"added_on": p["on"]})
    s.patch_node(org, p["capture_id"], {"media": media})


def _status(s: GraphStore, org: str, p: dict) -> None:
    s.patch_node(org, p["id"], {"status": p["status"], "status_note": p.get("note", ""), "status_by": p.get("by"),
                                "status_on": p["on"], "expires_on": p.get("expires_on")})


def _kept(s: GraphStore, org: str, p: dict) -> None:
    s.patch_node(org, p["id"], {"keep": bool(p["keep"]), "expires_on": p.get("expires_on")})


def _expired(s: GraphStore, org: str, p: dict) -> None:
    s.patch_node(org, p["id"], {"expired": True, "expired_on": p["on"], "expired_reason": p.get("reason"),
                                "media": [], "has_notes": False, "has_location": False, "keep": False,
                                "expires_on": None})


PROJECTORS = {
    "capture.created": _created,
    "capture.media_added": _media_added,
    "capture.status": _status,
    "capture.kept": _kept,
    "capture.expired": _expired,
}


# ---- the operations on the graph (a mixin of Maintenance) ---------------------------------

def _plus(day: str, days: int) -> str:
    return (date.fromisoformat(day) + timedelta(days=days)).isoformat()


def _taken_at(value, now: datetime) -> tuple[str, bool]:
    """When the report was made, as the device wrote it (ISO, with its offset),
    and whether the device's clock looks wrong (ahead of the server's). A time
    with no offset is read as UTC. Never refused for being early or late: a
    report from a phone with a bad clock is still a report."""
    sv = _sv()
    if value in (None, ""):
        return now.isoformat(timespec="seconds"), False
    try:
        at = datetime.fromisoformat(str(value).strip().replace("Z", "+00:00"))
    except ValueError:
        raise sv.Invalid(f"taken_at must be a time like 2026-11-12T09:30:00+10:00; got {str(value)[:40]!r}.")
    if at.tzinfo is None:
        at = at.replace(tzinfo=timezone.utc)
    if not 2000 <= at.year <= 2100:
        raise sv.Invalid("taken_at must be between 2000 and 2100.")
    return at.isoformat(timespec="seconds"), at - now > CLOCK_TOLERANCE


class CaptureOps:
    """Methods added to ``Maintenance``: the report as the graph knows it. The
    content (notes, location, bytes) is handled by :class:`Captures`."""

    def _capture(self, capture_id: str, live: bool = False) -> dict:
        sv = _sv()
        node = self.s.node(self.org, str(capture_id or ""), "Capture")
        if node is None:
            raise sv.NotFound(f"Capture {capture_id}")
        if live and node.get("expired"):
            raise sv.Invalid("That field report's content has been deleted (it passed its keep-until date, or "
                             "someone deleted it).")
        return node

    def _capture_expiry(self, node: dict, status: str | None = None, status_on: str | None = None,
                        keep: bool | None = None) -> str | None:
        """The day a report's content is deleted: KEEP_DAYS after it was made,
        KEEP_DAYS_DONE after it was marked done if sooner, never while pinned."""
        keep = node.get("keep") if keep is None else keep
        if keep:
            return None
        status = status or node.get("status")
        day = _plus(node["created_on"], KEEP_DAYS)
        if status == "done":
            day = min(day, _plus(status_on or node.get("status_on") or self.today(), KEEP_DAYS_DONE))
        return day

    def record_capture(self, capture_id: str, taken_at=None, device_tz=None, about=None, has_notes=False,
                       has_location=False, media_expected=None, by_name="", via="app") -> tuple[dict, bool]:
        """Record a new report (its content already stored). Answers the node
        and True; or, for an id that already has a report, that report and
        False, unchanged."""
        sv = _sv()
        existing = self.s.node(self.org, capture_id)
        if existing is not None:
            if existing["label"] != "Capture":
                raise sv.Invalid("That id is already used by something else in this workspace. Make a new id.")
            return existing, False
        self._quota("Capture", MAX_CAPTURES, what="field reports")
        now = datetime.now(timezone.utc)
        taken, suspect = _taken_at(taken_at, now)
        found, missing = [], []
        for target in list(dict.fromkeys(str(a) for a in (about or []) if a))[:MAX_ABOUT]:
            node = self.s.node(self.org, target)
            (found if node is not None and node["label"] in ABOUT_KINDS else missing).append(target)
        number = max((c.get("number") or 0 for c in self.s.nodes(self.org, "Capture")), default=0) + 1
        expected = None
        if media_expected is not None:
            expected = max(0, min(int(media_expected), MAX_ATTACHMENTS_EACH))
        on = self.today()
        self._emit("capture.created", {
            "id": capture_id, "number": number, "title": f"Field report {number}", "taken_at": taken,
            "device_tz": sv._text(device_tz, "time zone", max_len=64) or None,
            "at": now.isoformat(timespec="seconds"), "on": on, "by": self.actor,
            "by_name": sv._text(by_name, "name")[:120], "via": via if via in VIA else "api",
            "about": found, "about_missing": missing, "has_notes": bool(has_notes),
            "has_location": bool(has_location), "media_expected": expected, "clock_suspect": suspect,
            "expires_on": _plus(on, KEEP_DAYS),
        })
        return self._capture(capture_id), True

    def record_capture_media(self, capture_id: str, media_id: str, kind: str, mime: str, size: int, sha256: str,
                             name: str = "", duration_s: float | None = None) -> None:
        """A sound recording or a file whose bytes are stored (once per id)."""
        node = self._capture(capture_id, live=True)
        if any(m["id"] == media_id for m in node.get("media") or []):
            return
        self._emit("capture.media_added", {
            "id": media_id, "capture_id": capture_id, "kind": kind, "mime": mime, "size": int(size),
            "sha256": sha256, "name": name, "duration_s": duration_s, "on": self.today(),
        })

    def record_capture_photo(self, capture_id: str, photo_id: str, cleaned: dict, caption: str = "") -> None:
        """A cleaned photo whose bytes are stored, shown on the report (once per id)."""
        self._capture(capture_id, live=True)
        if self.s.node(self.org, photo_id, "Photo") is not None:
            return
        self.check_photo_quota()
        self._emit("photo.added", {
            "id": photo_id, "target_id": capture_id, "caption": _sv()._text(caption, "caption"),
            "taken_on": cleaned.get("taken_on"), "width": cleaned.get("width"), "height": cleaned.get("height"),
            "via": "report", "on": self.today(),
        })

    def set_capture_status(self, capture_id: str, status: str, note: str = "") -> dict:
        """Mark a report new, parsed (read, and what it says is in the records)
        or done (nothing more to do with it). Done starts the shorter keep time."""
        sv = _sv()
        node = self._capture(capture_id)
        if status not in STATUSES:
            raise sv.Invalid(f"A field report's status is one of {', '.join(STATUSES)}; got {str(status)[:40]!r}.")
        note = sv._text(note, "note")
        if node["status"] == status and (node.get("status_note") or "") == note:
            return node
        on = self.today()
        self._emit("capture.status", {
            "id": capture_id, "status": status, "note": note, "by": self.actor, "on": on,
            "expires_on": None if node.get("expired") else self._capture_expiry(node, status=status, status_on=on),
        })
        return self._capture(capture_id)

    def keep_capture(self, capture_id: str, keep: bool = True) -> dict:
        """Pin a report so its content isn't deleted (at most MAX_KEPT), or unpin it."""
        sv = _sv()
        node = self._capture(capture_id, live=True)
        keep = bool(keep)
        if bool(node.get("keep")) == keep:
            return node
        if keep and self.limited:
            kept = sum(1 for c in self.s.nodes(self.org, "Capture") if c.get("keep") and not c.get("expired"))
            if kept >= MAX_KEPT:
                raise sv.LimitReached(f"At most {MAX_KEPT} field reports can be kept. Unpin one first.")
        self._emit("capture.kept", {"id": capture_id, "keep": keep, "on": self.today(),
                                    "expires_on": self._capture_expiry(node, keep=keep)})
        return self._capture(capture_id)

    def expire_capture(self, capture_id: str, reason: str = "retention") -> dict:
        """Record that a report's content is gone. Its photos that also show
        somewhere else stay there (taken off the report); the others are
        removed. Answers {"photos_removed": [...], "media": [...]}: the ids
        whose bytes the caller must now delete."""
        node = self._capture(capture_id)
        if node.get("expired"):
            return {"photos_removed": [], "media": []}
        removed = []
        for photo in self.photos_of(capture_id):
            if photo["also_on"]:
                self._emit("photo.unlinked", {"id": photo["id"], "target_id": capture_id, "on": self.today()})
            else:
                self._emit("photo.removed", {"id": photo["id"], "on": self.today()})
                removed.append(photo["id"])
        media = [m["id"] for m in node.get("media") or []]
        self._emit("capture.expired", {"id": capture_id, "on": self.today(), "reason": reason})
        return {"photos_removed": removed, "media": media}

    def captures_due(self) -> list[str]:
        """Reports whose keep-until day has come."""
        today = self.today()
        return [c["id"] for c in self.s.nodes(self.org, "Capture")
                if not c.get("expired") and not c.get("keep") and c.get("expires_on") and c["expires_on"] <= today]


# ---- what the bytes are ---------------------------------------------------------------------

def sniff_audio(raw: bytes) -> str | None:
    """The sound format, from the bytes themselves (the declared type is
    ignored): its media type, or None if it isn't sound we keep. A video is
    not sound."""
    head = raw[:16]
    if len(head) >= 12 and head[4:8] == b"ftyp":  # MP4 family: .m4a (AAC), .3gp
        return None if re.search(rb"hdlr.{8}vide", raw, re.S) else "audio/mp4"
    if head[:4] == b"\x1aE\xdf\xa3":  # Matroska / WebM (Opus from a browser)
        return None if b"V_VP" in raw[:4096] or b"V_AV1" in raw[:4096] or b"V_MPEG" in raw[:4096] else "audio/webm"
    if head[:4] == b"OggS":
        return "audio/ogg"
    if head[:4] == b"RIFF" and head[8:12] == b"WAVE":
        return "audio/wav"
    if head[:3] == b"ID3":
        return "audio/mpeg"
    if len(head) >= 2 and head[0] == 0xFF and head[1] & 0xF6 == 0xF0:  # ADTS
        return "audio/aac"
    if len(head) >= 2 and head[0] == 0xFF and head[1] & 0xE0 == 0xE0:  # an MPEG audio frame
        return "audio/mpeg"
    return None


def mp4_seconds(raw: bytes) -> float | None:
    """An MP4 file's length from its movie header, if it has one."""
    at = raw.find(b"mvhd")
    try:
        if at < 0:
            return None
        if raw[at + 4] == 0:
            scale, length = struct.unpack(">II", raw[at + 16:at + 24])
        else:
            scale, = struct.unpack(">I", raw[at + 24:at + 28])
            length, = struct.unpack(">Q", raw[at + 28:at + 36])
        if scale <= 0 or length <= 0:
            return None
        seconds = length / scale
        return round(seconds, 1) if 0 < seconds < 24 * 3600 else None
    except (struct.error, IndexError):
        return None


_EXTENSIONS = {"audio/mp4": "m4a", "audio/webm": "webm", "audio/ogg": "ogg", "audio/wav": "wav",
               "audio/mpeg": "mp3", "audio/aac": "aac", "application/pdf": "pdf", "image/jpeg": "jpg"}


# ---- storing the content --------------------------------------------------------------------

class MongoCaptureStore:
    """Report content in MongoDB: one document of notes and location per
    report; bytes in pieces of at most MAX_CHUNK_BYTES, keyed by where each
    starts."""

    def __init__(self, db):
        self._content = db["maintenance_capture_content"]
        self._chunks = db["maintenance_capture_files"]

    def put_content(self, capture_id: str, org: str, content: dict) -> None:
        self._content.replace_one({"_id": capture_id}, {"_id": capture_id, "org": org, **content}, upsert=True)

    def content(self, capture_id: str) -> dict | None:
        doc = self._content.find_one({"_id": capture_id})
        return {k: v for k, v in doc.items() if k not in ("_id", "org")} if doc else None

    def contents(self, capture_ids: list[str]) -> dict[str, dict]:
        return {d["_id"]: {k: v for k, v in d.items() if k not in ("_id", "org")}
                for d in self._content.find({"_id": {"$in": list(capture_ids)}})}

    def delete_content(self, capture_id: str) -> None:
        self._content.delete_one({"_id": capture_id})

    def _pieces(self, media_id: str, data: bool) -> list[dict]:
        found = self._chunks.find({"media": media_id}) if data else self._chunks.find({"media": media_id},
                                                                                      {"data": 0})
        return sorted(found, key=lambda c: c["offset"])

    def size(self, media_id: str) -> int:
        """How many bytes have arrived, in order from the start."""
        end = 0
        for piece in self._pieces(media_id, data=False):
            if piece["offset"] != end:
                break
            end += piece["len"]
        return end

    def append(self, media_id: str, offset: int, data: bytes) -> None:
        from bson.binary import Binary

        key = f"{media_id}:{offset:012d}"
        self._chunks.replace_one({"_id": key}, {"_id": key, "media": media_id, "offset": offset, "len": len(data),
                                                 "data": Binary(data)}, upsert=True)

    def read(self, media_id: str) -> bytes | None:
        out, end = bytearray(), 0
        for piece in self._pieces(media_id, data=True):
            if piece["offset"] != end:
                break
            out += bytes(piece["data"])
            end += piece["len"]
        return bytes(out) if out else None

    def delete(self, media_id: str) -> None:
        self._chunks.delete_many({"media": media_id})


class FileCaptureStore:
    """Report content as files in a folder (a local install)."""

    def __init__(self, folder: str):
        self._folder = os.path.realpath(folder)
        os.makedirs(self._folder, exist_ok=True)
        self._lock = threading.Lock()

    def _path(self, an_id: str, ext: str) -> str:
        if not _ID.match(str(an_id or "")):
            raise KeyError(an_id)
        path = os.path.realpath(os.path.join(self._folder, f"{an_id}.{ext}"))
        if os.path.dirname(path) != self._folder:
            raise KeyError(an_id)
        return path

    def put_content(self, capture_id: str, org: str, content: dict) -> None:
        tmp = self._path(capture_id, "json") + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump({"org": org, **content}, f)
        os.replace(tmp, self._path(capture_id, "json"))

    def content(self, capture_id: str) -> dict | None:
        try:
            with open(self._path(capture_id, "json"), encoding="utf-8") as f:
                doc = json.load(f)
        except (FileNotFoundError, KeyError, ValueError):
            return None
        doc.pop("org", None)
        return doc

    def contents(self, capture_ids: list[str]) -> dict[str, dict]:
        found = {cid: self.content(cid) for cid in capture_ids}
        return {cid: doc for cid, doc in found.items() if doc is not None}

    def delete_content(self, capture_id: str) -> None:
        try:
            os.remove(self._path(capture_id, "json"))
        except (FileNotFoundError, KeyError):
            pass

    def size(self, media_id: str) -> int:
        try:
            return os.path.getsize(self._path(media_id, "bin"))
        except (FileNotFoundError, KeyError):
            return 0

    def append(self, media_id: str, offset: int, data: bytes) -> None:
        path = self._path(media_id, "bin")
        with self._lock:
            with open(path, "r+b" if os.path.exists(path) else "w+b") as f:
                f.seek(offset)
                f.write(data)

    def read(self, media_id: str) -> bytes | None:
        try:
            with open(self._path(media_id, "bin"), "rb") as f:
                return f.read()
        except (FileNotFoundError, KeyError):
            return None

    def delete(self, media_id: str) -> None:
        try:
            os.remove(self._path(media_id, "bin"))
        except (FileNotFoundError, KeyError):
            pass


_indexed: set = set()
_index_lock = threading.Lock()


def _now() -> datetime:
    return datetime.now(timezone.utc)


class Uploads:
    """Attachments on their way: what the sender said each one is, in MongoDB
    (the app's database, or the simulator locally). How much has arrived is
    read from the content store itself, never kept here."""

    def __init__(self, db):
        self._docs = db["maintenance_capture_uploads"]
        key = id(db)
        if key not in _indexed:
            with _index_lock:
                if key not in _indexed:
                    self._docs.create_index("delete_at", expireAfterSeconds=0)
                    _indexed.add(key)

    def get(self, media_id: str) -> dict | None:
        return self._docs.find_one({"_id": media_id})

    def start(self, doc: dict) -> dict:
        doc = {**doc, "state": "open", "created_at": _now(), "delete_at": _now() + timedelta(days=SESSION_DAYS)}
        self._docs.replace_one({"_id": doc["_id"]}, doc, upsert=True)
        return doc

    def finish(self, media_id: str, state: str, message: str = "") -> None:
        self._docs.update_one({"_id": media_id}, {"$set": {"state": state, "message": message}})

    def open_bytes(self, org: str) -> int:
        """Declared sizes of the sound and files still arriving for a workspace."""
        return sum(int(d.get("size") or 0) for d in self._docs.find({"org": org, "state": "open"})
                   if d.get("kind") != "photo")


# ---- the reports, content and all ---------------------------------------------------------

class Captures:
    """One workspace's field reports: the graph (``m``), their content
    (``files``), photo bytes (``photos``) and uploads in progress (``db``)."""

    def __init__(self, m, files, photos, db):
        self.m, self.files, self.photos = m, files, photos
        self.uploads = Uploads(db)

    # -- reading

    def _about(self, capture_id: str) -> list[dict]:
        found = [{"id": n["id"], "kind": n["label"],
                  "name": n.get("name") or n.get("title") or n.get("subject") or ""}
                 | ({"number": n["number"]} if n["label"] == "WorkOrder" and n.get("number") is not None else {})
                 for n in self.m.s.out(self.m.org, capture_id, "ABOUT") if n["label"] in ABOUT_KINDS]
        found.sort(key=lambda t: (ABOUT_KINDS.index(t["kind"]), (t["name"] or "").lower(), t["id"]))
        return found

    def _media(self, node: dict) -> list[dict]:
        if node.get("expired"):
            return []
        photos = [{"id": p["id"], "kind": "photo", "mime": "image/jpeg", "caption": p.get("caption") or "",
                   "width": p.get("width"), "height": p.get("height"), "also_on": p["also_on"]}
                  for p in self.m.photos_of(node["id"])]
        others = [{k: m.get(k) for k in ("id", "kind", "mime", "size", "name", "duration_s")}
                  for m in node.get("media") or []]
        return photos + others

    def _view(self, node: dict, content: dict | None, full: bool) -> dict:
        media = self._media(node)
        notes = (content or {}).get("notes") or ""
        out = {
            "id": node["id"], "number": node["number"], "title": node["title"], "status": node["status"],
            "status_note": node.get("status_note") or "", "status_on": node.get("status_on"),
            "taken_at": node["taken_at"], "device_tz": node.get("device_tz"), "received_at": node["received_at"],
            "clock_suspect": bool(node.get("clock_suspect")), "by": node.get("by"),
            "by_name": node.get("by_name") or "", "via": node.get("via"), "about": self._about(node["id"]),
            "about_missing": len(node.get("about_missing") or []),
            "counts": {kind: sum(1 for m in media if m["kind"] == kind) for kind in MEDIA_KINDS},
            "audio_seconds": round(sum(m.get("duration_s") or 0 for m in media if m["kind"] == "audio"), 1),
            "media_expected": node.get("media_expected"), "media_arrived": len(media),
            "complete": node.get("media_expected") is None or len(media) >= node["media_expected"],
            "keep": bool(node.get("keep")), "expires_on": node.get("expires_on"),
            "expired": bool(node.get("expired")), "expired_on": node.get("expired_on"),
            "has_location": bool(node.get("has_location")),
        }
        if full:
            out |= {"notes": notes, "location": (content or {}).get("location"), "media": media}
        else:
            out["notes_preview"] = notes[:200] + ("…" if len(notes) > 200 else "")
        return out

    def get(self, capture_id: str) -> dict:
        node = self.m._capture(clean_id(capture_id, "report id"))
        return self._view(node, None if node.get("expired") else self.files.content(node["id"]), full=True)

    def list(self, status: str | None = None, mine: bool = False, about_id: str | None = None,
             include_expired: bool = False, limit: int = 100) -> dict:
        sv = _sv()
        if status and status not in STATUSES:
            raise sv.Invalid(f"status is one of {', '.join(STATUSES)}.")
        nodes = self.m.s.nodes(self.m.org, "Capture")
        if about_id:
            ids = {n["id"] for n in self.m.s.inn(self.m.org, str(about_id), "ABOUT")}
            nodes = [n for n in nodes if n["id"] in ids]
        nodes = [n for n in nodes
                 if (include_expired or not n.get("expired")) and (not status or n["status"] == status)
                 and (not mine or n.get("by") == self.m.actor)]
        nodes.sort(key=lambda n: (n["received_at"], n["number"]), reverse=True)
        counts = {s: sum(1 for n in nodes if n["status"] == s) for s in STATUSES}
        limit = max(1, min(int(limit or 100), 500))
        page = nodes[:limit]
        contents = self.files.contents([n["id"] for n in page if not n.get("expired")])
        return {"reports": [self._view(n, contents.get(n["id"]), full=False) for n in page],
                "total": len(nodes), "counts": counts,
                "keep_days": KEEP_DAYS, "keep_days_done": KEEP_DAYS_DONE}

    # -- writing

    @staticmethod
    def _location(value) -> dict | None:
        """A location the author chose to add: {lat, lon, accuracy_m?}."""
        sv = _sv()
        if value in (None, "", {}):
            return None
        try:
            lat, lon = float(value["lat"]), float(value["lon"])
            accuracy = value.get("accuracy_m")
            accuracy = None if accuracy in (None, "") else round(max(0.0, float(accuracy)), 1)
        except (KeyError, TypeError, ValueError):
            raise sv.Invalid("location is {lat, lon} in decimal degrees (and accuracy_m, optional).")
        if not (-90 <= lat <= 90 and -180 <= lon <= 180):
            raise sv.Invalid("location is {lat, lon} in decimal degrees: lat -90 to 90, lon -180 to 180.")
        return {"lat": round(lat, 6), "lon": round(lon, 6), "accuracy_m": accuracy}

    def create(self, capture_id: str, notes: str = "", taken_at=None, device_tz=None, about=None, location=None,
               media_expected=None, by_name: str = "", via: str = "app") -> dict:
        """A new report; or, for an id that already has one, that report as it
        is (``created`` False): sending it again changes nothing."""
        sv = _sv()
        capture_id = clean_id(capture_id, "report id")
        existing = self.m.s.node(self.m.org, capture_id, "Capture")
        if existing is not None:
            return self.get(capture_id) | {"created": False}
        notes = str(notes or "").replace("\r\n", "\n").replace("\r", "\n").strip()
        if len(notes) > MAX_NOTES:
            raise sv.Invalid(f"A field report's notes are at most {MAX_NOTES:,} characters; these are {len(notes):,}. "
                             "Shorten them, or send the rest as a second report.")
        where = self._location(location)
        if isinstance(about, str):
            about = [about]
        self.m.check_limits()
        # Content first: a report in the graph always has its content; content with
        # no report (the event refused) is removed again.
        self.files.put_content(capture_id, self.m.org, {"notes": notes, "location": where})
        try:
            _, created = self.m.record_capture(
                capture_id, taken_at=taken_at, device_tz=device_tz, about=about, has_notes=bool(notes),
                has_location=where is not None, media_expected=media_expected, by_name=by_name, via=via)
        except Exception:
            if self.m.s.node(self.m.org, capture_id, "Capture") is None:
                self.files.delete_content(capture_id)
            raise
        return self.get(capture_id) | {"created": created}

    def set_status(self, capture_id: str, status: str, note: str = "") -> dict:
        self.m.set_capture_status(clean_id(capture_id, "report id"), status, note)
        return self.get(capture_id)

    def keep(self, capture_id: str, keep: bool = True) -> dict:
        self.m.keep_capture(clean_id(capture_id, "report id"), keep)
        return self.get(capture_id)

    def expire(self, capture_id: str, reason: str = "retention") -> dict:
        """Delete a report's content for good; the record that it existed stays."""
        capture_id = clean_id(capture_id, "report id")
        gone = self.m.expire_capture(capture_id, reason)
        for photo_id in gone["photos_removed"]:
            self.photos.delete(photo_id)
        for media_id in gone["media"]:
            self.files.delete(media_id)
        self.files.delete_content(capture_id)
        return {"expired": capture_id, "photos_removed": len(gone["photos_removed"]),
                "media_removed": len(gone["media"])}

    def expire_due(self) -> int:
        """The daily run: delete what has passed its keep-until day."""
        due = self.m.captures_due()
        for capture_id in due:
            self.expire(capture_id)
        return len(due)

    # -- attachments

    def _arrived(self, node: dict, media_id: str) -> dict | None:
        """The attachment as the report holds it, if it has fully arrived."""
        return next((m for m in self._media(node) if m["id"] == media_id), None)

    def _stored_bytes(self) -> int:
        return sum(int(m.get("size") or 0) for c in self.m.s.nodes(self.m.org, "Capture") if not c.get("expired")
                   for m in c.get("media") or [])

    def declare(self, capture_id: str, media_id: str, kind: str, size, mime: str = "", sha256: str = "",
                name: str = "", duration_s=None, caption: str = "") -> dict:
        """Say what an attachment is before sending it; or ask how much of it
        has arrived. Safe to call any number of times: it answers ``received``
        (carry on from there) and ``complete``."""
        sv = _sv()
        capture_id, media_id = clean_id(capture_id, "report id"), clean_id(media_id, "attachment id")
        node = self.m._capture(capture_id, live=True)
        arrived = self._arrived(node, media_id)
        if arrived is not None:
            return {"media_id": media_id, "complete": True, "received": arrived.get("size"), "media": arrived}
        if kind not in MEDIA_KINDS:
            raise sv.Invalid(f"An attachment's kind is one of {', '.join(MEDIA_KINDS)}; got {str(kind)[:40]!r}.")
        try:
            size = int(size)
        except (TypeError, ValueError):
            raise sv.Invalid("size (the attachment's length in bytes) is required.")
        sha256 = str(sha256 or "").strip().lower()
        if sha256 and not re.fullmatch(r"[0-9a-f]{64}", sha256):
            raise sv.Invalid("sha256 is the attachment's SHA-256 as 64 hex digits (or leave it out).")
        session = self.uploads.get(media_id)
        if session is not None and (session["org"] != self.m.org or session["capture_id"] != capture_id
                                    or session["size"] != size or session["kind"] != kind
                                    or (sha256 and session.get("sha256") and session["sha256"] != sha256)):
            raise sv.Invalid("That attachment id was already used for a different file. Make a new id.")
        if session is not None and session["state"] == "refused":
            raise sv.Invalid(session.get("message") or "That attachment was refused.")
        if session is None:
            session = self._start(node, media_id, kind, size, mime, sha256, name, duration_s, caption)
        received = min(self.files.size(media_id), size)
        if received >= size:  # all here but not recorded (the answer to the last piece was lost mid-way)
            return self._finish(node, session)
        return {"media_id": media_id, "complete": False, "received": received, "size": size,
                "chunk_bytes": CHUNK_BYTES, "max_chunk_bytes": MAX_CHUNK_BYTES}

    def _start(self, node: dict, media_id: str, kind: str, size: int, mime: str, sha256: str, name: str,
               duration_s, caption: str) -> dict:
        sv = _sv()
        if self.m.s.node(self.m.org, media_id) is not None:
            raise sv.Invalid("That attachment id is already used by something else in this workspace. Make a new id.")
        cap = {"photo": MAX_PHOTO_BYTES, "audio": MAX_AUDIO_BYTES, "file": MAX_FILE_BYTES}[kind]
        what = {"photo": "photo", "audio": "sound recording", "file": "file"}[kind]
        if size <= 0:
            raise sv.Invalid(f"The {what} is empty.")
        if size > cap:
            raise sv.LimitReached(f"The {what} is over {cap // (1024 * 1024)} MB, the most one can be.")
        media = self._media(node)
        if len(media) >= MAX_ATTACHMENTS_EACH:
            raise sv.LimitReached(f"A field report holds at most {MAX_ATTACHMENTS_EACH} attachments. "
                                  "Send the rest as a second report.")
        try:
            seconds = None if duration_s in (None, "") else round(max(0.0, float(duration_s)), 1)
        except (TypeError, ValueError):
            raise sv.Invalid("duration_s is the recording's length in seconds.")
        if kind == "photo":
            if sum(1 for m in media if m["kind"] == "photo") >= MAX_PHOTOS_EACH:
                raise sv.LimitReached(f"A field report holds at most {MAX_PHOTOS_EACH} photos. "
                                      "Send the rest as a second report.")
            self.m.check_photo_quota()
        else:
            if kind == "audio" and sum(m.get("duration_s") or 0 for m in media if m["kind"] == "audio") \
                    + (seconds or 0) > MAX_AUDIO_SECONDS:
                raise sv.LimitReached(f"A field report holds at most {MAX_AUDIO_SECONDS // 60} minutes of sound. "
                                      "Send the rest as a second report.")
            if self.m.limited and self._stored_bytes() + self.uploads.open_bytes(self.m.org) + size \
                    > workspace_bytes():
                raise sv.LimitReached(
                    f"This workspace's field reports can hold {workspace_bytes() // (1024 * 1024)} MB of sound "
                    "and files, and this would pass it. Mark old reports done or delete them to make room.")
        mime = str(mime or "").strip().lower().split(";")[0]
        return self.uploads.start({
            "_id": media_id, "org": self.m.org, "capture_id": node["id"], "kind": kind, "size": size,
            "mime": mime if _MIME.match(mime) else "", "sha256": sha256,
            "name": sv._text(name, "file name")[:120], "duration_s": seconds,
            "caption": sv._text(caption, "caption")[:200],
        })

    def append(self, capture_id: str, media_id: str, offset, data: bytes) -> dict:
        """One piece of an attachment, starting at ``offset``. A piece that has
        already arrived is accepted and ignored; one that starts past what has
        arrived is refused with where to carry on from. The last piece records
        the attachment."""
        sv = _sv()
        capture_id, media_id = clean_id(capture_id, "report id"), clean_id(media_id, "attachment id")
        node = self.m._capture(capture_id, live=True)
        arrived = self._arrived(node, media_id)
        if arrived is not None:
            return {"media_id": media_id, "complete": True, "received": arrived.get("size"), "media": arrived}
        session = self.uploads.get(media_id)
        if session is None or session["org"] != self.m.org or session["capture_id"] != capture_id:
            raise sv.NotFound(f"Upload {media_id}")
        if session["state"] == "refused":
            raise sv.Invalid(session.get("message") or "That attachment was refused.")
        try:
            offset = int(offset)
        except (TypeError, ValueError):
            raise sv.Invalid("offset (where this piece starts, in bytes) is required.")
        size = session["size"]
        if offset < 0 or len(data) > MAX_CHUNK_BYTES or offset + len(data) > size:
            raise sv.Invalid(f"A piece is at most {MAX_CHUNK_BYTES // (1024 * 1024)} MB and must fit inside the "
                             f"{size:,} bytes declared.")
        received = min(self.files.size(media_id), size)
        if offset > received:
            raise OffsetConflict(received, f"The server has {received:,} bytes of this attachment; "
                                           f"send from there, not from {offset:,}.")
        if offset + len(data) > received:  # new bytes (any part already here is skipped)
            self.files.append(media_id, received, data[received - offset:])
            received = offset + len(data)
        if received < size:
            return {"media_id": media_id, "complete": False, "received": received, "size": size}
        return self._finish(node, session)

    def _finish(self, node: dict, session: dict) -> dict:
        """All the bytes are here: check them, clean a photo, record it."""
        sv = _sv()
        from backend.maintenance import documents as documents_mod
        from backend.maintenance import photos as photos_mod

        media_id, kind = session["_id"], session["kind"]
        raw = self.files.read(media_id) or b""
        digest = hashlib.sha256(raw).hexdigest()
        if len(raw) != session["size"] or (session.get("sha256") and digest != session["sha256"]):
            self.files.delete(media_id)
            raise OffsetConflict(0, "The attachment arrived damaged. Send it again from the start.")

        def refuse(message: str):
            self.files.delete(media_id)
            self.uploads.finish(media_id, "refused", message)
            return sv.Invalid(message)

        if kind == "photo":
            try:
                cleaned = photos_mod.clean(raw)  # Busy passes up: the bytes stay, the sender tries again
            except photos_mod.Busy:
                raise
            except photos_mod.BadPhoto as err:
                raise refuse(str(err)) from None
            self.photos.put(media_id, "full", cleaned["full"])
            self.photos.put(media_id, "thumb", cleaned["thumb"])
            try:
                self.m.record_capture_photo(node["id"], media_id, cleaned, session.get("caption") or "")
            except Exception:
                if self.m.s.node(self.m.org, media_id, "Photo") is None:
                    self.photos.delete(media_id)
                raise
            self.files.delete(media_id)  # the original (with its metadata) isn't kept
        else:
            if kind == "audio":
                mime = sniff_audio(raw)
                if mime is None:
                    raise refuse("That isn't a sound recording Reliafy keeps (AAC in .m4a, Opus in WebM or Ogg, "
                                 "MP3 or WAV). Video isn't accepted.")
                seconds = (mp4_seconds(raw) if mime == "audio/mp4" else None) or session.get("duration_s")
                name = session.get("name") or f"recording.{_EXTENSIONS[mime]}"
            else:
                try:
                    documents_mod.check_pdf(raw)
                except documents_mod.BadDocument as err:
                    raise refuse(str(err)) from None
                mime, seconds = "application/pdf", None
                name = documents_mod.file_name(session.get("name") or "file.pdf")
            self.m.record_capture_media(node["id"], media_id, kind, mime, len(raw), digest, name, seconds)
        self.uploads.finish(media_id, "done")
        fresh = self.m._capture(node["id"])
        return {"media_id": media_id, "complete": True, "received": session["size"],
                "media": self._arrived(fresh, media_id)}

    def served(self, capture_id: str, media_id: str, size: str = "full") -> tuple[bytes, str, str] | None:
        """An attachment's bytes, media type and file name, if the report is in
        this workspace and still has it."""
        sv = _sv()
        try:
            node = self.m._capture(clean_id(capture_id, "report id"))
            media = self._arrived(node, clean_id(media_id, "attachment id"))
        except (sv.NotFound, sv.Invalid):
            return None
        if media is None:
            return None
        if media["kind"] == "photo":
            data = self.photos.get(media["id"], "full" if size == "full" else "thumb")
            return (data, "image/jpeg", f"photo-{media['id'][:8]}.jpg") if data else None
        data = self.files.read(media["id"])
        return (data, media["mime"], media.get("name") or media["id"]) if data else None


def retention_run(store, files, photos, db) -> dict:
    """The daily run's step: in every workspace with field reports, delete the
    content of those past their keep-until day."""
    import logging

    from backend.maintenance.service import Maintenance
    from backend.services import time_zones

    result = {"orgs": 0, "expired": 0}
    for org in store.orgs_with("Capture"):
        try:
            zone = None if org.startswith("team:") else time_zones.of_owner(db, org)
            m = Maintenance(store, org, None, limited=False, time_zone=zone)
            result["expired"] += Captures(m, files, photos, db).expire_due()
            result["orgs"] += 1
        except Exception:  # noqa: BLE001 - one workspace's trouble mustn't stop the others
            logging.getLogger(__name__).exception("field report retention failed for %s", org)
            result["failed"] = result.get("failed", 0) + 1
    return result
