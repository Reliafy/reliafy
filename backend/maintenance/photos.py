"""Photos for Reliafy Maintenance: cleaned, stored, and linked into the graph.

Every photo is re-encoded before it's kept: turned upright, shrunk to at most
1600 px (and a 400 px thumbnail), saved as JPEG with **no metadata** (no GPS,
no camera details, nothing hidden in the file). The location and date it was
taken are read first: the date is kept on the photo; the location is *offered*
to the person uploading (save it as where the equipment is?) and kept only if
they say yes, as coordinates on the equipment, never on the photo.

Bytes are kept outside the graph, in a :class:`MongoPhotoStore` (a deployment)
or a :class:`FilePhotoStore` (a local install); the graph has a Photo node
linked to what it shows.

Photo links let a phone add photos with no sign-in: an MCP tool (or the app)
makes a link for one position, location, item or work order; whoever opens it
can add up to ``MAX_PER_LINK`` photos until it expires. Its secret token is
stored only as a hash, like upload links (backend/services/uploads.py).
"""

from __future__ import annotations

import hashlib
import hmac
import io
import os
import secrets
import threading
from datetime import date, datetime, timedelta, timezone

from PIL import Image, ImageOps
from PIL import JpegImagePlugin, MpoImagePlugin, PngImagePlugin, WebPImagePlugin  # noqa: F401 - FORMATS

FULL_PX = 1600
THUMB_PX = 400
MAX_UPLOAD_BYTES = 20 * 1024 * 1024
MAX_PIXELS = 40_000_000  # width x height: a phone's photo is 12-50 Mpx before it's shrunk
MAX_PER_LINK = 20
LINK_MINUTES = 30
PHOTO_TARGETS = ("Position", "Location", "Item", "WorkOrder")
# The decoders tried: JPEG (with MPO, a JPEG with extra frames as some phones
# save, which recent Pillow opens through JPEG), PNG and WebP. Nothing else.
FORMATS = tuple(f for f in ("JPEG", "MPO", "PNG", "WEBP") if f in Image.OPEN)

# Pillow warns above MAX_IMAGE_PIXELS and raises above twice it: so it raises
# above MAX_PIXELS, behind clean()'s own check of the size.
Image.MAX_IMAGE_PIXELS = MAX_PIXELS // 2

# Decoding is CPU- and memory-heavy: at most this many at once in a process.
DECODE_SLOTS = 2
DECODE_WAIT = 60  # seconds to wait for a slot
_decoding = threading.BoundedSemaphore(DECODE_SLOTS)


class BadPhoto(ValueError):
    """Not an image we can read, or too big."""


class Busy(BadPhoto):
    """Too many photos being processed at once (try again shortly)."""


# ---- cleaning ----------------------------------------------------------------------

def _rational(value) -> float:
    try:
        return float(value)
    except TypeError:
        num, den = value
        return float(num) / float(den)


def _gps(exif) -> dict | None:
    try:
        gps = exif.get_ifd(0x8825)
        if not gps or 2 not in gps or 4 not in gps:
            return None
        lat = sum(_rational(v) / 60 ** i for i, v in enumerate(gps[2]))
        lon = sum(_rational(v) / 60 ** i for i, v in enumerate(gps[4]))
        if str(gps.get(1, "N")).upper().startswith("S"):
            lat = -lat
        if str(gps.get(3, "E")).upper().startswith("W"):
            lon = -lon
        if not (-90 <= lat <= 90 and -180 <= lon <= 180) or (lat == 0 and lon == 0):
            return None
        return {"lat": round(lat, 6), "lon": round(lon, 6)}
    except Exception:  # noqa: BLE001 - a malformed GPS block just means no location
        return None


def _taken_on(exif) -> str | None:
    try:
        raw = exif.get_ifd(0x8769).get(36867) or exif.get(306)
        return datetime.strptime(str(raw).strip()[:19], "%Y:%m:%d %H:%M:%S").date().isoformat()
    except Exception:  # noqa: BLE001
        return None


def _jpeg(img: Image.Image, px: int) -> bytes:
    copy = img.copy()
    copy.thumbnail((px, px), Image.Resampling.LANCZOS)
    buf = io.BytesIO()
    copy.save(buf, "JPEG", quality=85, optimize=True)  # no exif= : nothing carried over
    return buf.getvalue()


def _open(raw: bytes) -> Image.Image:
    """Open (not yet decode) an upload, refusing other formats and anything
    over MAX_PIXELS: the size is in the header, read before any pixel is."""
    img = Image.open(io.BytesIO(raw), formats=FORMATS)
    width, height = img.size
    if width <= 0 or height <= 0 or width * height > MAX_PIXELS:
        raise BadPhoto(f"The photo is too large ({width} x {height}); at most {MAX_PIXELS // 1_000_000} "
                       "megapixels.")
    return img


def clean(raw: bytes) -> dict:
    """Read an uploaded image and return its cleaned versions and what was in
    its metadata: ``full``, ``thumb`` (JPEG bytes), ``width``, ``height``,
    ``taken_on`` and ``gps`` (or None).

    At most DECODE_SLOTS run at once in a process; call it off the event loop
    (it blocks)."""
    if not raw:
        raise BadPhoto("The photo is empty.")
    if len(raw) > MAX_UPLOAD_BYTES:
        raise BadPhoto(f"The photo is over {MAX_UPLOAD_BYTES // (1024 * 1024)} MB.")
    if not _decoding.acquire(timeout=DECODE_WAIT):
        raise Busy("Too many photos are being processed right now. Try again in a minute.")
    try:
        return _clean(raw)
    finally:
        _decoding.release()


def _clean(raw: bytes) -> dict:
    try:
        img = _open(raw)
        img.verify()  # structure check; the image must be reopened afterwards
        img = _open(raw)
        exif = img.getexif()
        gps, taken = _gps(exif), _taken_on(exif)
        img.draft("RGB", (FULL_PX * 2, FULL_PX * 2))  # a JPEG decodes at a reduced scale when it can
        img = ImageOps.exif_transpose(img)  # upright, as the camera held it
        if img.mode not in ("RGB", "L"):
            img = img.convert("RGB")
        img.thumbnail((FULL_PX, FULL_PX), Image.Resampling.LANCZOS)  # shrink before any more copies
        img = img.convert("RGB")
        full = _jpeg(img, FULL_PX)
        width, height = Image.open(io.BytesIO(full)).size
        thumb = _jpeg(img, THUMB_PX)
    except BadPhoto:
        raise
    except Image.DecompressionBombError:
        raise BadPhoto(f"The photo is too large; at most {MAX_PIXELS // 1_000_000} megapixels.") from None
    except Exception:  # noqa: BLE001 - any decoder failure is an unreadable photo
        raise BadPhoto("That isn't a photo Reliafy can read (JPEG, PNG or WebP).") from None
    return {"full": full, "thumb": thumb, "width": width, "height": height, "taken_on": taken, "gps": gps}


# ---- storing the bytes ------------------------------------------------------------------

class MongoPhotoStore:
    """Photo bytes as documents (a cleaned photo is a few hundred KB, far under
    MongoDB's 16 MB limit)."""

    def __init__(self, db):
        self._files = db["maintenance_photo_files"]

    def put(self, photo_id: str, size: str, data: bytes) -> None:
        from bson.binary import Binary

        self._files.replace_one({"_id": f"{photo_id}:{size}"},
                                 {"_id": f"{photo_id}:{size}", "data": Binary(data)}, upsert=True)

    def get(self, photo_id: str, size: str) -> bytes | None:
        doc = self._files.find_one({"_id": f"{photo_id}:{size}"})
        return bytes(doc["data"]) if doc else None

    def delete(self, photo_id: str) -> None:
        self._files.delete_many({"_id": {"$in": [f"{photo_id}:full", f"{photo_id}:thumb"]}})


class FilePhotoStore:
    """Photo bytes as files in a folder (a local install)."""

    def __init__(self, folder: str):
        self._folder = folder
        os.makedirs(folder, exist_ok=True)

    def _path(self, photo_id: str, size: str) -> str:
        if not photo_id.isalnum():
            raise KeyError(photo_id)
        return os.path.join(self._folder, f"{photo_id}-{size}.jpg")

    def put(self, photo_id: str, size: str, data: bytes) -> None:
        tmp = self._path(photo_id, size) + ".tmp"
        with open(tmp, "wb") as f:
            f.write(data)
        os.replace(tmp, self._path(photo_id, size))

    def get(self, photo_id: str, size: str) -> bytes | None:
        try:
            with open(self._path(photo_id, size), "rb") as f:
                return f.read()
        except (FileNotFoundError, KeyError):
            return None

    def delete(self, photo_id: str) -> None:
        for size in ("full", "thumb"):
            try:
                os.remove(self._path(photo_id, size))
            except (FileNotFoundError, KeyError):
                pass


# ---- photo links ------------------------------------------------------------------------

def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


_indexed: set = set()  # databases whose links collection has its TTL index (once a process)
_index_lock = threading.Lock()


def link_id_ok(link_id: str) -> bool:
    """Whether ``link_id`` has the form of a link's id (24 hex digits)."""
    return isinstance(link_id, str) and len(link_id) == 24 and all(c in "0123456789abcdef" for c in link_id)


class PhotoLinks:
    """Short-lived links for adding photos from a phone, in MongoDB (the app's
    database: the real one, or the simulator locally)."""

    def __init__(self, db):
        self._links = db["maintenance_photo_links"]
        key = id(db)
        if key not in _indexed:
            with _index_lock:
                if key not in _indexed:
                    self._links.create_index("delete_at", expireAfterSeconds=0)
                    _indexed.add(key)

    def create(self, org: str, uid: str, target: dict, caption: str = "") -> tuple[dict, str]:
        token = secrets.token_urlsafe(32)
        now = _now()
        doc = {
            "_id": secrets.token_hex(12), "token_hash": _hash(token), "org": org, "uid": uid,
            "target_id": target["id"], "target_label": target["label"],
            "target_name": target.get("name") or target.get("title") or "",
            "caption": caption, "created_at": now, "expires_at": now + timedelta(minutes=LINK_MINUTES),
            "delete_at": now + timedelta(days=2), "photos": [], "gps_offers": [], "n": 0,
        }
        self._links.insert_one(doc)
        return doc, token

    def get(self, link_id: str, token: str | None = None, org: str | None = None) -> dict | None:
        doc = self._links.find_one({"_id": str(link_id)})
        if doc is None:
            return None
        if token is not None and not hmac.compare_digest(doc["token_hash"], _hash(token)):
            return None
        if org is not None and doc["org"] != org:
            return None
        return doc

    @staticmethod
    def expired(doc: dict) -> bool:
        return _now() > _aware(doc["expires_at"])

    def usable(self, doc: dict) -> str | None:
        """Why the link can't take another photo, or None if it can."""
        if self.expired(doc):
            return "This link has expired. Ask for a new one."
        if max(len(doc["photos"]), doc.get("n", 0)) >= MAX_PER_LINK:
            return f"This link has taken its {MAX_PER_LINK} photos. Ask for a new one."
        return None

    def reserve(self, link_id: str) -> bool:
        """Take one of the link's MAX_PER_LINK places for a photo on its way, in
        one step, so uploads at the same moment can't pass the limit together.
        False when it has expired or has no place left. Give the place back with
        :meth:`release` if the photo isn't kept."""
        taken = self._links.find_one_and_update(
            {"_id": link_id, "expires_at": {"$gt": _now()},
             "$or": [{"n": {"$lt": MAX_PER_LINK}}, {"n": {"$exists": False}}]},
            {"$inc": {"n": 1}})
        return taken is not None

    def release(self, link_id: str) -> None:
        self._links.update_one({"_id": link_id, "n": {"$gt": 0}}, {"$inc": {"n": -1}})

    def add_photo(self, link_id: str, photo_id: str, gps: dict | None) -> None:
        update = {"$push": {"photos": photo_id}}
        if gps:
            update["$push"]["gps_offers"] = {"photo_id": photo_id, **gps, "answer": None}
        self._links.update_one({"_id": link_id}, update)

    def answer(self, link_id: str, photo_id: str, answer: str) -> dict | None:
        """Record the uploader's answer for a photo's location, once. A declined
        location is dropped from the link. Returns the offer (with the location),
        or None if there's no unanswered offer for that photo."""
        doc = self._links.find_one({"_id": link_id})
        offer = next((o for o in (doc or {}).get("gps_offers", []) if o.get("photo_id") == photo_id), None)
        if offer is None or offer.get("answer") is not None:
            return None
        update = {"$set": {"gps_offers.$.answer": answer}}
        if answer != "saved":
            update["$unset"] = {"gps_offers.$.lat": "", "gps_offers.$.lon": ""}
        done = self._links.update_one(
            {"_id": link_id, "gps_offers": {"$elemMatch": {"photo_id": photo_id, "answer": None}}}, update)
        return offer if done.modified_count else None

    @staticmethod
    def public(doc: dict) -> dict:
        """The link as its creator sees it. A location the uploader declined isn't
        in it (it isn't kept)."""
        return {
            "link_id": doc["_id"], "target": {"id": doc["target_id"], "kind": doc["target_label"],
                                              "name": doc["target_name"]},
            "expires_at": _aware(doc["expires_at"]).isoformat(), "photos": list(doc["photos"]),
            "location_offers": [
                {"photo_id": o["photo_id"], "answer": o.get("answer")} if o.get("answer") == "declined" else
                {"photo_id": o["photo_id"], "lat": o["lat"], "lon": o["lon"], "answer": o.get("answer")}
                for o in doc["gps_offers"] if o.get("answer") == "declined" or "lat" in o],
        }


def today() -> str:
    return date.today().isoformat()
