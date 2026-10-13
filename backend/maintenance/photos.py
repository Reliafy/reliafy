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
from datetime import date, datetime, timedelta, timezone

from PIL import Image, ImageOps, UnidentifiedImageError

FULL_PX = 1600
THUMB_PX = 400
MAX_UPLOAD_BYTES = 20 * 1024 * 1024
MAX_PIXELS = 60_000_000  # refuse decompression bombs well before memory trouble
MAX_PER_LINK = 20
LINK_MINUTES = 30
PHOTO_TARGETS = ("Position", "Location", "Item", "WorkOrder")

Image.MAX_IMAGE_PIXELS = MAX_PIXELS


class BadPhoto(ValueError):
    """Not an image we can read, or too big."""


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


def clean(raw: bytes) -> dict:
    """Read an uploaded image and return its cleaned versions and what was in
    its metadata: ``full``, ``thumb`` (JPEG bytes), ``width``, ``height``,
    ``taken_on`` and ``gps`` (or None)."""
    if not raw:
        raise BadPhoto("The photo is empty.")
    if len(raw) > MAX_UPLOAD_BYTES:
        raise BadPhoto(f"The photo is over {MAX_UPLOAD_BYTES // (1024 * 1024)} MB.")
    try:
        img = Image.open(io.BytesIO(raw))
        img.verify()  # structure check; the image must be reopened afterwards
        img = Image.open(io.BytesIO(raw))
        exif = img.getexif()
        gps, taken = _gps(exif), _taken_on(exif)
        img = ImageOps.exif_transpose(img)  # upright, as the camera held it
        img = img.convert("RGB")
    except (UnidentifiedImageError, Image.DecompressionBombError, OSError, SyntaxError, ValueError):
        raise BadPhoto("That isn't a photo Reliafy can read (JPEG, PNG or WebP).") from None
    full = _jpeg(img, FULL_PX)
    width, height = Image.open(io.BytesIO(full)).size
    return {"full": full, "thumb": _jpeg(img, THUMB_PX), "width": width, "height": height,
            "taken_on": taken, "gps": gps}


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


class PhotoLinks:
    """Short-lived links for adding photos from a phone, in MongoDB (the app's
    database: the real one, or the simulator locally)."""

    def __init__(self, db):
        self._links = db["maintenance_photo_links"]
        self._links.create_index("delete_at", expireAfterSeconds=0)

    def create(self, org: str, uid: str, target: dict, caption: str = "") -> tuple[dict, str]:
        token = secrets.token_urlsafe(32)
        now = _now()
        doc = {
            "_id": secrets.token_hex(12), "token_hash": _hash(token), "org": org, "uid": uid,
            "target_id": target["id"], "target_label": target["label"],
            "target_name": target.get("name") or target.get("title") or "",
            "caption": caption, "created_at": now, "expires_at": now + timedelta(minutes=LINK_MINUTES),
            "delete_at": now + timedelta(days=2), "photos": [], "gps_offers": [],
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

    def usable(self, doc: dict) -> str | None:
        """Why the link can't take another photo, or None if it can."""
        if _now() > _aware(doc["expires_at"]):
            return "This link has expired. Ask for a new one."
        if len(doc["photos"]) >= MAX_PER_LINK:
            return f"This link has taken its {MAX_PER_LINK} photos. Ask for a new one."
        return None

    def add_photo(self, link_id: str, photo_id: str, gps: dict | None) -> None:
        update = {"$push": {"photos": photo_id}}
        if gps:
            update["$push"]["gps_offers"] = {"photo_id": photo_id, **gps, "answer": None}
        self._links.update_one({"_id": link_id}, update)

    def answer(self, link_id: str, photo_id: str, answer: str) -> dict | None:
        doc = self._links.find_one({"_id": link_id})
        offer = next((o for o in (doc or {}).get("gps_offers", []) if o["photo_id"] == photo_id), None)
        if offer is None:
            return None
        self._links.update_one({"_id": link_id, "gps_offers.photo_id": photo_id},
                               {"$set": {"gps_offers.$.answer": answer}})
        return offer

    @staticmethod
    def public(doc: dict) -> dict:
        return {
            "link_id": doc["_id"], "target": {"id": doc["target_id"], "kind": doc["target_label"],
                                              "name": doc["target_name"]},
            "expires_at": _aware(doc["expires_at"]).isoformat(), "photos": list(doc["photos"]),
            "location_offers": [{"photo_id": o["photo_id"], "lat": o["lat"], "lon": o["lon"],
                                 "answer": o["answer"]} for o in doc["gps_offers"]],
        }


def today() -> str:
    return date.today().isoformat()
