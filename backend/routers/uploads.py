"""``PUT /api/uploads/{upload_id}?t=…`` — where an agent sends a file.

The other half of the MCP ``create_upload`` tool (see
:mod:`backend.services.uploads`, which carries the security review). No user
auth: the agent's HTTP client (``curl`` in a sandbox) has none, so the
single-use ``t`` token is the credential. ``POST`` with a raw body works the
same, for clients that can't ``PUT``. Nothing here ever returns stored bytes.

Order of checks, cheapest and least revealing first: the rate limits (per
client IP, then per upload id), the token (constant time; a missing upload and
a wrong token are the same 404), the token's state (expired 410 / used 409),
the declared ``Content-Length`` (413), then the body, counted as it streams
(413 as soon as it passes the cap — what arrived is dropped and the link can
be used again with a smaller file).
"""

from __future__ import annotations

import hashlib
import logging
import time

from anyio import to_thread
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from backend.routers.telemetry import _client_ip
from backend.services import public_links as links_service
from backend.services import uploads as uploads_service
from backend.services import usage as usage_service

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api")

_NOT_FOUND = "This upload link is invalid or has expired. Call create_upload for a new one."
_NO_STORE = {"Cache-Control": "no-store"}


def _db():
    from backend.db import get_db

    return get_db()


def _ip_key(request: Request) -> str:
    """A salted hash of the client IP (never the IP itself)."""
    from backend import config

    ip = _client_ip(request)
    return "upload-ip:" + hashlib.sha256(f"{config.METRICS_SALT}|upload|{ip}".encode()).hexdigest()[:24]


def _record(doc: dict, outcome: str, started: float) -> None:
    """One ``upload_put`` usage event for the upload's owner: the feature
    name and outcome only — never the URL, its token or anything uploaded."""
    usage_service.record(
        _db(), uid=doc["uid"], channel="mcp", feature="upload_put", outcome=outcome,
        plan=doc.get("plan") or "", client=doc.get("client") or "",
        ms=(time.perf_counter() - started) * 1000)


def _json(status: int, detail: str, **extra) -> JSONResponse:
    return JSONResponse(status_code=status, content={"detail": detail, **extra}, headers=_NO_STORE)


@router.api_route("/uploads/{upload_id}", methods=["PUT", "POST"], include_in_schema=False)
async def receive_upload(upload_id: str, request: Request) -> JSONResponse:
    started = time.perf_counter()
    db = _db()
    token = request.query_params.get("t") or ""

    def limited() -> bool:
        return (not links_service.consume_attempt(db, _ip_key(request), uploads_service.IP_ATTEMPTS)
                or not links_service.consume_attempt(db, f"upload:{upload_id[:64]}",
                                                     uploads_service.UPLOAD_ATTEMPTS))

    if await to_thread.run_sync(limited):
        return JSONResponse(
            status_code=429, content={"detail": "Too many attempts. Wait a few minutes, then try again."},
            headers={"Retry-After": str(links_service.retry_after_seconds()), **_NO_STORE})

    doc = await to_thread.run_sync(uploads_service.check_token, db, upload_id, token)
    if doc is None:
        return _json(404, _NOT_FOUND)

    declared = request.headers.get("content-length")
    if declared and declared.isdigit() and int(declared) > doc["max_bytes"]:
        await to_thread.run_sync(_record, doc, "error", started)
        return _too_large(doc)

    claimed = await to_thread.run_sync(uploads_service.claim, db, doc["_id"])
    if claimed is None:
        current = await to_thread.run_sync(lambda: db.uploads.find_one({"_id": doc["_id"]})) or doc
        status, detail = uploads_service.status_refusal(current)
        return _json(status, detail)
    claim_id = claimed["claim"]

    cap = doc["max_bytes"]
    digest = hashlib.sha256()
    buf = bytearray()
    head = bytearray()
    size = n = 0
    try:
        async for piece in request.stream():
            if not piece:
                continue
            size += len(piece)
            if size > cap:
                await to_thread.run_sync(uploads_service.release, db, doc["_id"], claim_id)
                await to_thread.run_sync(_record, doc, "error", started)
                return _too_large(doc)
            digest.update(piece)
            if len(head) < 65536:
                head.extend(piece[: 65536 - len(head)])
            buf.extend(piece)
            while len(buf) >= uploads_service.CHUNK_BYTES:
                part = bytes(buf[: uploads_service.CHUNK_BYTES])
                del buf[: uploads_service.CHUNK_BYTES]
                await to_thread.run_sync(uploads_service.write_chunk, db, doc["_id"], n, part, claim_id)
                n += 1
        if size == 0:
            await to_thread.run_sync(uploads_service.release, db, doc["_id"], claim_id)
            await to_thread.run_sync(_record, doc, "error", started)
            return _json(400, "The request had no body. Send the file's bytes, e.g. curl --data-binary @file.")
        if buf:
            await to_thread.run_sync(uploads_service.write_chunk, db, doc["_id"], n, bytes(buf), claim_id)
        out = await to_thread.run_sync(uploads_service.finish, db, doc["_id"], claim_id, size,
                                       digest.hexdigest(), bytes(head))
        if out is None:
            # Another PUT took the slot over: its file is the one kept.
            await to_thread.run_sync(_record, doc, "error", started)
            return _json(409, "Another upload to this link took its place. Create a new upload to send this file.")
    except BaseException:
        # Cut off mid-stream (or a storage error): drop the partial file so
        # the link can be retried, then let the error take its course. Run
        # inline — a cancelled task can't await a worker thread.
        logger.warning("upload %s: receive failed", doc["_id"], exc_info=True)
        try:
            uploads_service.release(db, doc["_id"], claim_id)
        except Exception:  # noqa: BLE001
            logger.warning("upload %s: could not release", doc["_id"], exc_info=True)
        raise
    await to_thread.run_sync(_record, doc, "ok", started)
    logger.info("upload %s received: purpose=%s bytes=%d format=%s",
                doc["_id"], doc.get("purpose"), size, out["detected_format"])
    return JSONResponse(content={
        **out,
        "filename": doc.get("filename"),
        "next": _next_step(doc.get("purpose")),
    }, headers=_NO_STORE)


def _too_large(doc: dict) -> JSONResponse:
    mb = doc["max_bytes"] / 1048576
    return _json(413, f"The file is larger than this upload allows ({mb:.0f} MB). Export just the part you "
                      "need (one project, one sheet) and send that.", max_bytes=doc["max_bytes"])


def _next_step(purpose: str | None) -> str:
    tool = {"rbd_import": "import_rbd", "excel": "import_excel", "dataset": "upload_dataset",
            "outage_log": "upload_outage_log"}.get(purpose or "", "the import tool")
    return f"Uploaded. Now call {tool} with this upload_id (inspect_upload first to see sheets and columns)."
