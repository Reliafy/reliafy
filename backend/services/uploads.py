"""Upload links: files reach Reliafy without passing through an agent's context.

An MCP agent that wants to import a file (a BlockSim project, an Excel
workbook, a CSV of failure times) calls the ``uploads create`` tool, gets a
single-use URL, sends the bytes there with a plain HTTP ``PUT`` (``curl``),
then calls ``uploads import_rbd`` / ``uploads import_excel`` / ``datasets upload`` /
``rbd upload_outage_log`` with the ``upload_id``. The file's contents never sit
in a tool call, so a 20 MB workbook costs the agent a few hundred tokens,
not millions.

Storage: two collections, not GridFS.

* ``uploads`` — one document per upload slot: the owner, the purpose, the
  filename, the size cap, the token's *hash*, the state (``pending`` →
  ``receiving`` → ``ready``), and once received the size, sha256 and the
  detected format.
* ``upload_chunks`` — the bytes, in 1 MiB chunks (well under Mongo's 16 MB
  document limit), keyed ``<upload_id>:<n>``.

Both carry ``delete_at`` with a TTL index, so Mongo itself drops an upload an
hour after it arrived (a slot nobody used goes 1 h 15 min after it was made).
GridFS would need a cron for that — a TTL on ``fs.files`` leaves the chunks
behind — and doesn't run on the in-memory simulator without patching pymongo's
``gridfs``. A successful import deletes the upload at once.

Security review (keep it true when changing this module):

* **The token is the only credential.** The ``PUT`` carries no user auth (an
  agent's shell has none), so the URL's ``t`` is a 32-byte random secret
  (:func:`secrets.token_urlsafe`), stored only as its SHA-256 and compared in
  constant time (:func:`hmac.compare_digest`). It is bound to one upload
  (owner, purpose, filename, size cap) and expires 15 minutes after it was
  made; the first successful ``PUT`` consumes it (an atomic state change, so
  two racing ``PUT``s can't both land).
* **The token is never logged.** It's in the query string, so: our own log
  lines name the upload id only; usage events (:mod:`backend.services.usage`)
  hold feature names, never a path or query; and :func:`redact_query` is
  installed as a filter on uvicorn's access log (``backend/main.py``). The
  hosting platform's own request log (Cloud Run) records full URLs for the
  operator — acceptable for a hashed-at-rest, single-use, 15-minute secret,
  but it's why the token is useless once consumed.
* **Rate limits** before the token is even checked: per upload id and per
  (hashed) client IP, in fixed windows kept in Mongo (the share-link unlock
  limiter's :func:`backend.services.public_links.consume_attempt`).
* **Size limits** are enforced while the body streams (413 the moment it
  passes the cap; a ``Content-Length`` over the cap is refused before a byte
  is read). Every cap is at most :data:`HARD_MAX_BYTES` (30 MB), under Cloud
  Run's 32 MiB HTTP/1 request-body limit.
* **Content is never executed or served back.** Bytes are stored opaquely;
  nothing ever returns them over HTTP. They are read only by the existing
  importers, which already treat uploads as hostile: defusedxml for XML
  (Open-PSA, and openpyxl's workbook parsing), zip-bomb checks on workbooks
  (:mod:`backend.services.excel`), a shared decompression budget for gzip
  (BlockSim ``.rsgz``), and row / block / nesting caps.
* **Parts through MCP** (:func:`write_part`, for agents that can't reach
  the URL at all) need no token: the caller is the signed-in MCP user, and
  the slot must be theirs. They claim the slot like a PUT (one sender at a
  time), count towards the same size cap, and each part is capped well
  under the MCP request limit.
* **Uploads are private.** Only the creator can inspect or import one; any
  other user gets "not found" (existence isn't revealed). Uploads never count
  towards storage caps and aren't listed anywhere.
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import re
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

from pymongo import ReturnDocument

from backend import config

logger = logging.getLogger(__name__)

# What an upload is for: the tool that will read it, and so its size cap.
PURPOSES = ("rbd_import", "excel", "dataset", "outage_log")

# Cloud Run refuses an HTTP/1 request body over 32 MiB before it reaches the
# app, so no upload may be larger than this, whatever the importer allows
# (the RBD importer and the Excel reader take 50 MB files from the web app,
# which uploads through the same 32 MiB limit in practice).
HARD_MAX_BYTES = 30 * 1024 * 1024

TOKEN_TTL = timedelta(minutes=15)       # the URL works this long
KEEP_AFTER_UPLOAD = timedelta(hours=1)  # the received bytes are kept this long
CHUNK_BYTES = 1024 * 1024
# A slot stuck "receiving" this long (an instance died mid-PUT) can be claimed
# again: longer than Cloud Run's request timeout (600 s), so a PUT still
# streaming is never taken over. Each claim also tags its chunks, so even a
# takeover can't mix two PUTs' bytes.
STALE_RECEIVING = timedelta(minutes=11)

# PUT attempts allowed per fixed window (see public_links.ATTEMPT_WINDOW_SECONDS),
# counted before the token is checked.
UPLOAD_ATTEMPTS = 10
IP_ATTEMPTS = 60

_EXCEL_EXT = (".xlsx", ".xlsm", ".xltx", ".xltm")
_TOKEN_RE = re.compile(r"([?&]t=)[^&\s\"]+")


class UploadError(ValueError):
    """A user-facing problem with an upload (the message says what to do)."""


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _aware(dt: Optional[datetime]) -> Optional[datetime]:
    """Mongo hands datetimes back naive (UTC)."""
    if dt is not None and dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


def ensure_indexes(db) -> None:
    """TTL: Mongo drops each upload (and its chunks) at ``delete_at``."""
    db.uploads.create_index([("delete_at", 1)], expireAfterSeconds=0)
    db.uploads.create_index([("uid", 1), ("created_at", -1)])
    db.upload_chunks.create_index([("delete_at", 1)], expireAfterSeconds=0)
    db.upload_chunks.create_index([("upload_id", 1), ("n", 1)])


def hash_token(token: str) -> str:
    return hashlib.sha256((token or "").encode()).hexdigest()


def redact_query(text: str) -> str:
    """``…/api/uploads/<id>?t=SECRET`` -> ``…?t=[redacted]`` (for log lines)."""
    return _TOKEN_RE.sub(r"\1[redacted]", text or "")


def _ext(filename: str) -> str:
    name = (filename or "").lower().rsplit("/", 1)[-1]
    return "." + name.rsplit(".", 1)[-1] if "." in name else ""


def max_bytes_for(purpose: str, filename: str) -> int:
    """The size cap for an upload: the importer's own limit, never above
    :data:`HARD_MAX_BYTES`. Datasets and outage logs given as CSV text keep
    the dataset limit (``MAX_UPLOAD_BYTES``); as a workbook they get the
    Excel reader's."""
    from backend.services import excel
    from backend.services.rbd_import.types import MAX_UPLOAD_BYTES as RBD_MAX

    if purpose == "rbd_import":
        cap = RBD_MAX
    elif purpose == "excel":
        cap = excel.MAX_FILE_BYTES
    elif purpose in ("dataset", "outage_log"):
        cap = excel.MAX_FILE_BYTES if _ext(filename) in _EXCEL_EXT else config.MAX_UPLOAD_BYTES
    else:
        raise UploadError(f"purpose must be one of {', '.join(PURPOSES)}.")
    return min(cap, HARD_MAX_BYTES)


def _clean_filename(filename: str) -> str:
    name = (filename or "").replace("\\", "/").rsplit("/", 1)[-1].strip()
    name = "".join(ch for ch in name if ch.isprintable())[:200]
    if not name:
        raise UploadError("Give the file's name (with its extension, e.g. plant.rsgz or failures.xlsx).")
    return name


def create(db, uid: str, purpose: str, filename: str, size_bytes: Optional[int] = None,
           plan: str = "", client: str = "") -> tuple[dict, str]:
    """Make an upload slot. Returns ``(doc, token)`` — the token is shown to
    the caller once and stored only as a hash."""
    if purpose not in PURPOSES:
        raise UploadError(f"purpose must be one of {', '.join(PURPOSES)}.")
    filename = _clean_filename(filename)
    cap = max_bytes_for(purpose, filename)
    if size_bytes is not None:
        if size_bytes <= 0:
            raise UploadError("size_bytes must be positive (or omit it).")
        if size_bytes > cap:
            raise UploadError(
                f"The file is {size_bytes / 1048576:.1f} MB; uploads for {purpose} are limited to "
                f"{cap / 1048576:.0f} MB. Export just the part you need (one project, one sheet) and upload that.")
    token = secrets.token_urlsafe(32)
    now = _now()
    doc = {
        "_id": uuid.uuid4().hex,
        "uid": uid,
        "purpose": purpose,
        "filename": filename,
        "max_bytes": cap,
        "token_hash": hash_token(token),
        "status": "pending",
        "created_at": now,
        "expires_at": now + TOKEN_TTL,
        "delete_at": now + TOKEN_TTL + KEEP_AFTER_UPLOAD,
        # For the usage event the PUT records (it carries no user auth).
        "plan": (plan or "")[:16],
        "client": (client or "")[:32],
    }
    db.uploads.insert_one(doc)
    return doc, token


# ---- receiving (the PUT) ------------------------------------------------------------

def check_token(db, upload_id: str, token: str) -> Optional[dict]:
    """The upload if ``token`` is its token (constant-time), else None — a
    missing upload and a wrong token look the same."""
    doc = db.uploads.find_one({"_id": str(upload_id or "")[:64]})
    # Compare even when there's no upload, so timing doesn't say which.
    expected = (doc or {}).get("token_hash") or hash_token(secrets.token_hex(16))
    ok = hmac.compare_digest(hash_token(token or ""), expected)
    return doc if (doc is not None and ok) else None


def claim(db, upload_id: str) -> Optional[dict]:
    """Atomically move a pending (or stale receiving) slot whose token hasn't
    expired to ``receiving``: only one PUT can hold it. The returned slot's
    ``claim`` (a fresh random id) tags that PUT's chunks and guards the
    release and finish only it may do."""
    now = _now()
    return db.uploads.find_one_and_update(
        {"_id": upload_id, "expires_at": {"$gt": now},
         "$or": [{"status": "pending"},
                 {"status": "receiving", "receiving_since": {"$lt": now - STALE_RECEIVING}}]},
        {"$set": {"status": "receiving", "receiving_since": now, "claim": secrets.token_hex(16)},
         "$unset": {"via": ""}},
        return_document=ReturnDocument.AFTER,
    )


def release(db, upload_id: str, claim_id: str) -> None:
    """A PUT that failed (too large, empty, cut off): drop what it sent and,
    if it still holds the slot, let the URL be used again until it expires."""
    db.upload_chunks.delete_many({"upload_id": upload_id, "claim": claim_id})
    db.uploads.update_one({"_id": upload_id, "status": "receiving", "claim": claim_id},
                          {"$set": {"status": "pending"},
                           "$unset": {"receiving_since": "", "claim": "", "via": ""}})


def write_chunk(db, upload_id: str, n: int, data: bytes, claim_id: str) -> None:
    db.upload_chunks.insert_one({
        "_id": f"{upload_id}:{claim_id}:{n:05d}", "upload_id": upload_id, "claim": claim_id, "n": n,
        "data": bytes(data), "delete_at": _now() + KEEP_AFTER_UPLOAD,
    })


def finish(db, upload_id: str, claim_id: str, size: int, sha256: str, head: bytes) -> Optional[dict]:
    """Mark the upload received (the token is now spent) — or, when this PUT
    no longer holds the slot, drop its chunks and return None."""
    detected = detect_format(head)
    now = _now()
    done = db.uploads.update_one(
        {"_id": upload_id, "status": "receiving", "claim": claim_id},
        {"$set": {"status": "ready", "size": size, "sha256": sha256, "detected_format": detected,
                  "received_at": now, "delete_at": now + KEEP_AFTER_UPLOAD},
         "$unset": {"receiving_since": ""}},
    )
    if not done.modified_count:
        db.upload_chunks.delete_many({"upload_id": upload_id, "claim": claim_id})
        return None
    return {"upload_id": upload_id, "size": size, "sha256": sha256, "detected_format": detected}


def status_refusal(doc: dict) -> tuple[int, str]:
    """Why a valid token can't be used now: (status, message)."""
    if doc.get("status") == "ready":
        return 409, "This upload link has already been used — the file is uploaded. Create a new upload to send another file."
    if doc.get("status") == "receiving":
        return 409, "A file is already being sent to this upload link."
    return 410, "This upload link has expired (links last 15 minutes). Call uploads create for a new one."


def next_step(purpose: Optional[str]) -> str:
    """What to call once the file has arrived."""
    tool = {"rbd_import": "uploads import_rbd", "excel": "uploads import_excel", "dataset": "datasets upload",
            "outage_log": "rbd upload_outage_log"}.get(purpose or "", "the import")
    return f"Uploaded. Now call {tool} with this upload_id (get kind upload first to see sheets and columns)."


# ---- receiving in parts (the uploads send_part MCP tool) -----------------------------
#
# An agent whose sandbox can't reach the upload URL at all (an egress proxy
# refusing both hosts) sends the file through the MCP connection instead:
# base64 parts written into the same upload slot the PUT would fill, so every
# tool that takes an upload_id works unchanged. The caller is the
# authenticated MCP user, so no token: the slot must be theirs. The rules are
# the PUT's — one sender per slot (the first part claims it, as a PUT does),
# the slot's size cap, the format detected from the first bytes once the last
# part is in — plus a cap per part (each is one MCP request, well under
# ``config.MAX_REQUEST_BYTES``) and on the number of parts. A part sent again
# replaces itself, so a retry after a dropped call is harmless. The file must
# be complete before the slot's original ``delete_at`` (75 minutes after
# uploads create); the token's 15 minutes only bound when the first part may
# arrive.

PART_MAX_BYTES = CHUNK_BYTES   # decoded bytes per part: one stored chunk
MAX_PARTS = 1000


def _parts_slot(db, upload_id: str, uid: str) -> dict:
    """The caller's slot, claimed for parts on the first one."""
    doc = db.uploads.find_one({"_id": str(upload_id or "")[:64], "uid": uid})
    now = _now()
    if doc is None or (_aware(doc.get("delete_at")) or now) <= now:
        raise UploadError("Upload not found — it may have expired. Call uploads create and send the file again.")
    if doc.get("status") == "pending":
        claimed = db.uploads.find_one_and_update(
            {"_id": doc["_id"], "uid": uid, "status": "pending", "expires_at": {"$gt": now}},
            {"$set": {"status": "receiving", "receiving_since": now, "claim": secrets.token_hex(16),
                      "via": "parts"}},
            return_document=ReturnDocument.AFTER,
        )
        doc = claimed or db.uploads.find_one({"_id": doc["_id"], "uid": uid}) or doc
    status = doc.get("status")
    if status == "ready":
        raise UploadError("This upload is already complete. Call the import tool with its upload_id, or "
                          "uploads create for another file.")
    if status == "pending":
        raise UploadError("This upload's link expired before any of the file arrived (it lasts 15 minutes). "
                          "Call uploads create again.")
    if doc.get("via") != "parts":
        raise UploadError("This file is already being sent to the upload URL by HTTP. Wait for that, or call "
                          "uploads create for a new upload.")
    return doc


def decode_part(data_base64: str) -> bytes:
    """A part's bytes from base64 (standard or URL-safe; line breaks and
    missing padding allowed)."""
    import base64
    import binascii

    text = "".join(str(data_base64 or "").split()).translate(str.maketrans("-_", "+/"))
    text += "=" * (-len(text) % 4)
    try:
        return base64.b64decode(text, validate=True)
    except (binascii.Error, ValueError):
        raise UploadError("data_base64 isn't valid base64. Encode the part's raw bytes "
                          "(e.g. base64.b64encode(chunk).decode()).") from None


def write_part(db, upload_id: str, uid: str, index: int, data: bytes, last: bool,
               sha256: Optional[str] = None) -> dict:
    """Store part ``index`` of the caller's upload; with ``last``, check that
    parts 0..index are all there (and match ``sha256``, when given) and mark
    the upload received, exactly as a finished PUT does."""
    if not isinstance(index, int) or not 0 <= index < MAX_PARTS:
        raise UploadError(f"part_index runs from 0 to {MAX_PARTS - 1}.")
    if not data:
        raise UploadError("This part is empty. Send the file's bytes, base64-encoded.")
    if len(data) > PART_MAX_BYTES:
        raise UploadError(f"A part holds at most {PART_MAX_BYTES // 1024} KB of the file "
                          f"(this one has {len(data) // 1024} KB). Split it into smaller parts.")
    doc = _parts_slot(db, upload_id, uid)
    claim_id, cap = doc["claim"], doc["max_bytes"]
    sizes = {c["n"]: c.get("size", 0) for c in db.upload_chunks.find(
        {"upload_id": doc["_id"], "claim": claim_id}, {"n": 1, "size": 1})}
    sizes[index] = len(data)
    total = sum(sizes.values())
    if total > cap:
        release(db, doc["_id"], claim_id)
        raise UploadError(f"The file is larger than this upload allows ({cap / 1048576:.0f} MB), so the parts "
                          "sent were dropped. Export just the part you need (one sheet, one project) and send "
                          "that with a new uploads create.")
    db.upload_chunks.replace_one(
        {"_id": f"{doc['_id']}:{claim_id}:{index:05d}"},
        {"upload_id": doc["_id"], "claim": claim_id, "n": index, "data": bytes(data), "size": len(data),
         "delete_at": doc["delete_at"]},
        upsert=True,
    )
    db.uploads.update_one({"_id": doc["_id"], "claim": claim_id}, {"$set": {"receiving_since": _now()}})
    out = {"upload_id": doc["_id"], "part_index": index, "parts_received": len(sizes), "bytes_received": total}
    if not last:
        return {**out, "done": False, "next": f"Send part {index + 1} (last=true if it's the final one)."}

    extra = sorted(n for n in sizes if n > index)
    if extra:
        raise UploadError(f"Parts after {index} were sent ({', '.join(map(str, extra[:10]))}), so part {index} "
                          "can't be the last. Send last=true on the highest part.")
    missing = [n for n in range(index + 1) if n not in sizes]
    if missing:
        listed = ", ".join(map(str, missing[:20])) + (" …" if len(missing) > 20 else "")
        what = f"Parts {listed} haven't" if len(missing) > 1 else f"Part {listed} hasn't"
        raise UploadError(f"{what} arrived. Send {'them' if len(missing) > 1 else 'it'}, then send part {index} "
                          "again with last=true.")
    parts = sorted(db.upload_chunks.find({"upload_id": doc["_id"], "claim": claim_id}), key=lambda c: c["n"])
    whole = b"".join(bytes(c["data"]) for c in parts)
    digest = hashlib.sha256(whole).hexdigest()
    if sha256 and digest != sha256.strip().lower():
        release(db, doc["_id"], claim_id)
        raise UploadError("The parts put together don't match the sha256 you gave (a part was mistyped or "
                          "cut short), so they were dropped. Send the file again from part 0 (call uploads create "
                          "first if its 15 minutes are up).")
    done = finish(db, doc["_id"], claim_id, len(whole), digest, whole[:65536])
    if done is None:
        raise UploadError("Another upload to this link took its place. Call uploads create to send this file.")
    # The chunks live as long as the received upload (finish moved its delete_at).
    received = db.uploads.find_one({"_id": doc["_id"]}, {"delete_at": 1}) or {}
    if received.get("delete_at"):
        db.upload_chunks.update_many({"upload_id": doc["_id"], "claim": claim_id},
                                     {"$set": {"delete_at": received["delete_at"]}})
    logger.info("upload %s received in %d parts: purpose=%s bytes=%d format=%s",
                doc["_id"], len(parts), doc.get("purpose"), len(whole), done["detected_format"])
    return {**out, "done": True, "size": done["size"], "sha256": done["sha256"],
            "detected_format": done["detected_format"], "filename": doc.get("filename"),
            "next": next_step(doc.get("purpose"))}


# ---- format detection ----------------------------------------------------------

def detect_format(head: bytes) -> str:
    """What the bytes are, from their first few KB (magic bytes, then text
    shape): ``xlsx``, ``zip``, ``rsgz`` (gzip — a BlockSim pack), ``rsr``
    (an Access/Jet database — a BlockSim project), ``xls`` (an OLE compound
    file: legacy Excel or an encrypted workbook), ``xml``, ``repyability``
    (RePyability JSON), ``galileo``,
    ``csv``, ``text`` or ``binary``."""
    from backend.services.rbd_import import blocksim, galileo, repyability

    head = head or b""
    if head.startswith(b"PK\x03\x04"):
        return "xlsx" if (b"xl/" in head or b"[Content_Types].xml" in head) else "zip"
    if head[:2] == b"\x1f\x8b":
        return "rsgz"
    if blocksim._is_jet(head[:32]):
        return "rsr"
    if head.startswith(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"):
        return "xls"
    if b"\x00" in head[:4096]:
        return "binary"
    text = head.decode("utf-8", "replace").lstrip("﻿ \t\r\n")
    if text.startswith("<"):
        return "xml"
    if repyability.sniff(head, ""):
        return "repyability"
    if galileo.sniff(head, ""):
        return "galileo"
    first = next((ln for ln in text.splitlines() if ln.strip()), "")
    if any(d in first for d in ",\t;|"):
        return "csv"
    return "text"


# ---- reading (the import tools) ------------------------------------------------------

def get(db, upload_id: str, uid: str) -> dict:
    """The caller's received upload, or :class:`UploadError` — the same
    "not found" for someone else's upload as for a missing one."""
    doc = db.uploads.find_one({"_id": str(upload_id or ""), "uid": uid})
    if doc is None or (_aware(doc.get("delete_at")) or _now()) <= _now():
        raise UploadError("Upload not found — it may have expired (uploads are kept for an hour). "
                          "Call uploads create and send the file again.")
    if doc.get("status") != "ready":
        if doc.get("via") == "parts":
            raise UploadError("The file isn't complete yet: send its remaining parts with uploads send_part "
                              "(last=true on the final one), then call this again.")
        if _aware(doc.get("expires_at")) and _aware(doc["expires_at"]) <= _now():
            raise UploadError("Nothing was sent to this upload before its link expired. Call uploads create again.")
        raise UploadError("The file hasn't arrived yet: send it with an HTTP PUT to the upload URL "
                          "(the curl command uploads create gave) — or, if that can't get through, in parts "
                          "with uploads send_part — then call this again.")
    return doc


def read(db, upload_id: str, uid: str) -> tuple[dict, bytes]:
    """The caller's upload and its bytes (integrity-checked)."""
    doc = get(db, upload_id, uid)
    parts = sorted(db.upload_chunks.find({"upload_id": doc["_id"], "claim": doc.get("claim")}),
                   key=lambda c: c["n"])
    data = b"".join(bytes(c["data"]) for c in parts)
    if len(data) != doc.get("size") or hashlib.sha256(data).hexdigest() != doc.get("sha256"):
        logger.warning("upload %s failed its integrity check", doc["_id"])
        raise UploadError("The uploaded file is incomplete. Call uploads create and send it again.")
    return doc, data


def delete(db, upload_id: str) -> None:
    db.upload_chunks.delete_many({"upload_id": upload_id})
    db.uploads.delete_one({"_id": upload_id})


def brief(doc: dict) -> dict:
    """What a tool says about an upload (never the token)."""
    return {
        "upload_id": doc["_id"],
        "filename": doc.get("filename"),
        "purpose": doc.get("purpose"),
        "size": doc.get("size"),
        "sha256": doc.get("sha256"),
        "detected_format": doc.get("detected_format"),
    }


def is_excel(doc: dict) -> bool:
    return doc.get("detected_format") in ("xlsx", "xls", "zip") or _ext(doc.get("filename", "")) in _EXCEL_EXT


def as_text(data: bytes) -> str:
    """CSV / TSV bytes as text (UTF-8, falling back to Latin-1 — Excel's
    "CSV" on Windows)."""
    try:
        return data.decode("utf-8-sig")
    except UnicodeDecodeError:
        return data.decode("latin-1")


# ---- inspection (get kind upload) ---------------------------------------------------

INSPECT_SHEETS = 20        # sheets described in full
INSPECT_SAMPLE_ROWS = 3
INSPECT_DIAGRAMS = 50


def inspect(doc: dict, data: bytes) -> dict:
    """What an agent needs to pick an import: for a workbook, each sheet's
    header row, columns, row count, a few sample rows and what it looks like
    (an RCM worksheet, an RBD template); for a diagram file, a parse preview
    (diagram names and block counts); for CSV text, its columns and rows.
    Raises the importers' own user-facing errors."""
    fmt = doc.get("detected_format")
    if is_excel(doc):
        return {"kind": "workbook", **_inspect_workbook(data, doc.get("filename") or "")}
    if fmt in ("rsgz", "rsr", "xml", "repyability", "galileo"):
        return {"kind": "diagram_file", **preview_diagrams(data, doc.get("filename") or "")}
    if fmt in ("csv", "text"):
        return {"kind": "table", **_inspect_text(data)}
    return {"kind": "unknown", "note": "Reliafy doesn't recognise this file's format."}


def _inspect_workbook(data: bytes, filename: str) -> dict:
    from backend.services import excel, rcm_import
    from backend.services.rbd_import import excel as rbd_excel

    info = excel.inspect(data, filename)
    sheets, looks_like_template = [], False
    for s in info["sheets"][:INSPECT_SHEETS]:
        entry = {"name": s["name"], "rows": s["rows"], "header_row": s["guessed_header_row"]}
        if s["rows"] == 0:
            sheets.append({**entry, "columns": [], "note": "empty"})
            continue
        try:
            table = excel.read_table(data, s["name"], None, filename, max_rows=INSPECT_SAMPLE_ROWS)
        except excel.ExcelError as exc:
            sheets.append({**entry, "columns": [], "note": str(exc)})
            continue
        entry.update({
            "header_row": table.header_row,
            "data_rows": max(0, s["rows"] - (1 if table.header_row else 0)),
            "columns": table.header,
            "sample_rows": [[excel.display(v) for v in r] for r in table.rows[:INSPECT_SAMPLE_ROWS]],
        })
        hints = {}
        rcm_guess = excel.guess_mapping(table.header, rcm_import.FIELDS)
        if "mode" in rcm_guess and len(rcm_guess) >= 2:
            hints["rcm"] = rcm_guess
        block_guess = excel.guess_mapping(table.header, rbd_excel.BLOCK_FIELDS)
        if rbd_excel._is_blocks(block_guess):
            hints["rbd_blocks"] = block_guess
            looks_like_template = True
        if hints:
            entry["looks_like"] = hints
        if s.get("notes"):
            entry["notes"] = s["notes"]
        sheets.append(entry)
    out: dict = {"sheets": sheets}
    if len(info["sheets"]) > INSPECT_SHEETS:
        out["more_sheets"] = [s["name"] for s in info["sheets"][INSPECT_SHEETS:]]
    if looks_like_template:
        try:
            out["rbd_template"] = preview_diagrams(data, filename, fmt="excel")
        except ValueError as exc:  # a hint, not the import
            out["rbd_template"] = {"error": str(exc)}
        except Exception:  # noqa: BLE001
            out["rbd_template"] = {"error": "Couldn't read it as an RBD template."}
    return out


def _inspect_text(data: bytes) -> dict:
    import io

    import pandas as pd

    text = as_text(data).strip()
    header = next((ln for ln in text.splitlines() if ln.strip()), "")
    delim = max("\t,;|", key=lambda d: header.count(d))
    if not header or header.count(delim) == 0:
        return {"columns": [header.strip()] if header else [], "rows": max(0, len(text.splitlines()) - 1),
                "note": "Only one column found — a table needs columns separated by commas or tabs."}
    try:
        df = pd.read_csv(io.StringIO(text), sep=delim, dtype=str, keep_default_na=False,
                         skipinitialspace=True, engine="python")
    except Exception as exc:  # noqa: BLE001
        return {"note": f"Couldn't read the table: {exc}"}
    return {
        "delimiter": {"\t": "tab", ",": "comma", ";": "semicolon", "|": "pipe"}[delim],
        "columns": [str(c) for c in df.columns],
        "rows": int(df.shape[0]),
        "sample_rows": df.head(INSPECT_SAMPLE_ROWS).astype(str).values.tolist(),
    }


def preview_diagrams(data: bytes, filename: str, fmt: Optional[str] = None,
                     excel_mapping: Optional[dict] = None) -> dict:
    """Parse a diagram file without saving: each diagram's name, format,
    block count and number of import notes."""
    from backend.services import rbd_import

    diagrams = rbd_import.import_file(data, filename, excel_mapping=excel_mapping, format=fmt)
    items = [{
        "name": d.name,
        "source_format": d.source_format,
        "n_blocks": sum(1 for n in (d.graph or {}).get("nodes") or [] if n.get("type") not in ("input", "output")),
        "n_warnings": len(d.warnings),
    } for d in diagrams[:INSPECT_DIAGRAMS]]
    out = {"diagrams": items, "n_diagrams": len(diagrams)}
    if len(diagrams) > INSPECT_DIAGRAMS:
        out["note"] = f"Showing the first {INSPECT_DIAGRAMS} of {len(diagrams)} diagrams."
    return out
