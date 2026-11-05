"""Stored documents for Reliafy Maintenance: PDFs kept in the workspace.

A document is either a link (a web address, ``document.added``) or a PDF
kept here (``document.uploaded``), on an item, a position or a position class.
This module holds what's special about the PDFs; the graph side is in
service.py, the routes in backend/routers/maintenance.py.

Security review (keep it true when changing this module):

* **Only PDFs.** A file is kept only if its bytes start with ``%PDF-`` (the
  name and declared type are ignored), it isn't empty and it's at most
  :data:`MAX_UPLOAD_BYTES` (well under Cloud Run's 32 MiB request limit).
* **Opaque bytes.** Nothing on the server opens, parses, renders or runs a
  stored PDF; its contents are never logged. It's kept as it came and served
  back as ``application/pdf`` with ``X-Content-Type-Options: nosniff`` and a
  Content-Disposition built from a cleaned file name (:func:`disposition`), so
  a browser shows it in its own PDF viewer or saves it, never as a page of
  the app.
* **Owner only.** Bytes are served only through a document in the caller's
  workspace that hasn't been removed: anything else is "not found". Removing
  a document deletes its bytes (the history keeps that it was there).
* **Download links** (for agents, which have no sign-in to send): a random
  token, stored only as its hash, for one document, for :data:`LINK_MINUTES`.
  The token is in the query string as ``t``, which the access log redacts.

Bytes are kept outside the graph, like photos (photos.py): in MongoDB in
1 MiB chunks (a deployment; a document is limited to 16 MB) or as files in a
folder (a local install).
"""

from __future__ import annotations

import hashlib
import hmac
import os
import re
import secrets
import threading
import unicodedata
from datetime import datetime, timedelta, timezone
from urllib.parse import quote

from backend.maintenance.service import Invalid

MAX_UPLOAD_BYTES = 20 * 1024 * 1024
MAX_MB = MAX_UPLOAD_BYTES // (1024 * 1024)
CONTENT_TYPE = "application/pdf"
CHUNK_BYTES = 1024 * 1024
LINK_MINUTES = 15
MAGIC = b"%PDF-"


class BadDocument(Invalid):
    """Not a PDF, empty, or too big (the message says what to do)."""


def too_big() -> BadDocument:
    return BadDocument(f"The file is over {MAX_MB} MB, the most a stored PDF can be. Make it smaller (save it "
                       "again with reduced size, or split it), or link to it with a web address instead.")


def check_pdf(raw: bytes) -> None:
    """Refuse anything that isn't a PDF within the size limit."""
    if not raw:
        raise BadDocument("The file is empty. Choose the PDF again.")
    if len(raw) > MAX_UPLOAD_BYTES:
        raise too_big()
    if not raw.startswith(MAGIC):
        raise BadDocument("That file isn't a PDF. Only PDF files can be stored; for anything else, add a link "
                          "(a web address) instead.")


def file_name(name: str) -> str:
    """The name to show and to save it under: no folders, no control
    characters, at most 120 characters, ending in .pdf."""
    text = str(name or "").replace("\\", "/").rsplit("/", 1)[-1]
    text = "".join(ch for ch in unicodedata.normalize("NFC", text) if ch.isprintable()).strip().strip(".")
    if text.lower().endswith(".pdf"):
        text = text[:-4].rstrip()
    return (text[:116].rstrip() or "document") + ".pdf"


def title_from(name: str) -> str:
    """A title from a file name: 'pump-manual.pdf' -> 'pump-manual'."""
    return file_name(name)[:-4]


def disposition(name: str, download: bool) -> str:
    """A Content-Disposition header for a stored PDF: inline (the browser's
    viewer) or attachment (save it), with an ASCII fallback name and the real
    one percent-encoded (RFC 6266 / 5987). Nothing in it can end the header
    or add a parameter."""
    name = file_name(name)
    ascii_name = re.sub(r"[^A-Za-z0-9._ -]", "_", unicodedata.normalize("NFKD", name).encode(
        "ascii", "ignore").decode()) or "document.pdf"
    kind = "attachment" if download else "inline"
    return f"{kind}; filename=\"{ascii_name}\"; filename*=UTF-8''{quote(name, safe='')}"


def headers(name: str, download: bool, cache: str = "private, max-age=300") -> dict:
    """The headers a stored PDF is served with."""
    return {"Content-Disposition": disposition(name, download), "X-Content-Type-Options": "nosniff",
            "Cache-Control": cache, "Referrer-Policy": "no-referrer", "X-Robots-Tag": "noindex"}


# ---- storing the bytes ------------------------------------------------------------------

class MongoDocumentStore:
    """PDF bytes in MongoDB, in chunks (a stored PDF can be larger than a
    MongoDB document may be)."""

    def __init__(self, db):
        self._chunks = db["maintenance_document_files"]

    def put(self, document_id: str, data: bytes) -> None:
        from bson.binary import Binary

        self.delete(document_id)
        for n, start in enumerate(range(0, len(data), CHUNK_BYTES)):
            self._chunks.insert_one({"_id": f"{document_id}:{n:05d}", "doc": document_id, "n": n,
                                     "data": Binary(data[start:start + CHUNK_BYTES])})

    def get(self, document_id: str) -> bytes | None:
        parts = sorted(self._chunks.find({"doc": document_id}), key=lambda c: c["n"])
        return b"".join(bytes(c["data"]) for c in parts) if parts else None

    def delete(self, document_id: str) -> None:
        self._chunks.delete_many({"doc": document_id})


class FileDocumentStore:
    """PDF bytes as files in a folder (a local install)."""

    def __init__(self, folder: str):
        self._folder = folder
        os.makedirs(folder, exist_ok=True)

    def _path(self, document_id: str) -> str:
        if not document_id.isalnum():
            raise KeyError(document_id)
        return os.path.join(self._folder, f"{document_id}.pdf")

    def put(self, document_id: str, data: bytes) -> None:
        tmp = self._path(document_id) + ".tmp"
        with open(tmp, "wb") as f:
            f.write(data)
        os.replace(tmp, self._path(document_id))

    def get(self, document_id: str) -> bytes | None:
        try:
            with open(self._path(document_id), "rb") as f:
                return f.read()
        except (FileNotFoundError, KeyError):
            return None

    def delete(self, document_id: str) -> None:
        try:
            os.remove(self._path(document_id))
        except (FileNotFoundError, KeyError):
            pass


# ---- download links ---------------------------------------------------------------------

def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


_indexed: set = set()
_index_lock = threading.Lock()


def link_id_ok(link_id: str) -> bool:
    return isinstance(link_id, str) and len(link_id) == 24 and all(c in "0123456789abcdef" for c in link_id)


class DocumentLinks:
    """Short-lived links to read one stored PDF with no sign-in (for an agent
    that has no session to send), in MongoDB."""

    def __init__(self, db):
        self._links = db["maintenance_document_links"]
        key = id(db)
        if key not in _indexed:
            with _index_lock:
                if key not in _indexed:
                    self._links.create_index("delete_at", expireAfterSeconds=0)
                    _indexed.add(key)

    def create(self, org: str, document_id: str) -> tuple[dict, str]:
        token = secrets.token_urlsafe(32)
        now = _now()
        doc = {"_id": secrets.token_hex(12), "token_hash": _hash(token), "org": org, "document_id": document_id,
               "created_at": now, "expires_at": now + timedelta(minutes=LINK_MINUTES),
               "delete_at": now + timedelta(days=1)}
        self._links.insert_one(doc)
        return doc, token

    def get(self, link_id: str, token: str) -> dict | None:
        """The link if ``token`` is its token and it hasn't expired, else None
        (a missing link, a wrong token and an expired one look the same)."""
        doc = self._links.find_one({"_id": str(link_id)}) if link_id_ok(link_id) else None
        expected = (doc or {}).get("token_hash") or _hash(secrets.token_hex(16))
        if not hmac.compare_digest(expected, _hash(token or "")) or doc is None:
            return None
        if _now() > _aware(doc["expires_at"]):
            return None
        return doc
