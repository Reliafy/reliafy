"""Request-size limits.

:class:`BodySizeLimitMiddleware` caps every request body before any route
parses it: a declared ``Content-Length`` over the route's cap is answered 413
straight away, and a body without one (chunked) is counted as it streams and
refused once it passes the cap. Caps are looked up per request, so tests and
config changes apply without a restart.

:func:`read_upload` reads an uploaded file with a cap, for the routes that take
a CSV file.
"""

from __future__ import annotations

from fastapi import HTTPException

from backend import config

_MB = 1024 * 1024
# Room for multipart boundaries and the form's other fields.
_FORM_OVERHEAD = 256 * 1024

# Routes whose body is one CSV upload (plus a few form fields).
_CSV_ROUTES = frozenset({
    "/api/columns",
    "/api/models",
    "/api/alt/fit",
    "/api/alt/models",
    "/api/degradation/fit",
    "/api/degradation/models",
    "/api/recurrent/fit",
    "/api/recurrent/models",
})
_CSV_PREFIXES = ("/api/fit/",)

# Routes that accept an Excel workbook or a diagram file, up to the importers'
# own limits.
_FILE_ROUTES = frozenset({"/api/datasets", "/api/rbds/import", "/api/rcm/import",
                          "/api/rcm/import/preview"})
_FILE_PREFIXES = ("/api/excel/",)


def _file_cap() -> int:
    from backend.services import excel
    from backend.services.rbd_import.types import MAX_UPLOAD_BYTES as RBD_MAX

    return max(excel.MAX_FILE_BYTES, RBD_MAX, config.MAX_UPLOAD_BYTES) + _MB


def body_limit(path: str) -> int:
    """The largest request body ``path`` accepts, in bytes."""
    if path.startswith("/api/uploads/"):
        from backend.services.uploads import HARD_MAX_BYTES

        return HARD_MAX_BYTES + _MB
    if path in _FILE_ROUTES or path.startswith(_FILE_PREFIXES):
        return _file_cap()
    if path in _CSV_ROUTES or path.startswith(_CSV_PREFIXES):
        return config.MAX_UPLOAD_BYTES + _FORM_OVERHEAD
    return config.MAX_REQUEST_BYTES


def _size(n: int) -> str:
    return f"{n / _MB:.0f} MB" if n >= _MB else f"{max(1, n // 1024)} KB"


def _too_large_detail(limit: int) -> str:
    return f"The request is too large. The limit is {_size(limit)}."


class BodyTooLarge(HTTPException):
    def __init__(self, limit: int):
        super().__init__(status_code=413, detail=_too_large_detail(limit))


class BodySizeLimitMiddleware:
    """Pure ASGI, so it never buffers a body itself."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        limit = body_limit(scope.get("path", ""))
        declared = None
        for name, value in scope.get("headers") or ():
            if name == b"content-length":
                try:
                    declared = int(value)
                except ValueError:
                    declared = None
                break
        if declared is not None and declared > limit:
            await _reject(send, limit)
            return

        received = 0

        async def capped_receive():
            nonlocal received
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > limit:
                    raise BodyTooLarge(limit)
            return message

        started = False

        async def tracking_send(message):
            nonlocal started
            if message["type"] == "http.response.start":
                started = True
            await send(message)

        try:
            await self.app(scope, capped_receive, tracking_send)
        except BodyTooLarge:
            if started:
                raise
            await _reject(send, limit)


async def _reject(send, limit: int) -> None:
    import json

    body = json.dumps({"detail": _too_large_detail(limit)}).encode()
    await send({
        "type": "http.response.start",
        "status": 413,
        "headers": [
            (b"content-type", b"application/json"),
            (b"content-length", str(len(body)).encode()),
            (b"connection", b"close"),
        ],
    })
    await send({"type": "http.response.body", "body": body})


def read_upload(file, cap: int | None = None) -> bytes:
    """An uploaded file's bytes, refusing (413) one over ``cap`` (default the
    CSV limit, ``MAX_UPLOAD_BYTES``). Reads at most one byte past the cap.
    For sync route handlers (FastAPI runs them in its threadpool)."""
    cap = config.MAX_UPLOAD_BYTES if cap is None else cap
    data = file.file.read(cap + 1)
    if len(data) > cap:
        raise HTTPException(
            status_code=413,
            detail=(f"That file is too large. The limit is {_size(cap)} — "
                    "try trimming unused columns or rows."),
        )
    return data
