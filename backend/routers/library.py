"""The reliability data library over plain HTTP: public reads, no sign-in.

The library is published reference data (every record cited, under a
licence that allows republishing), the same for everyone, so these routes
need no account and are cacheable. The same reads are the MCP ``library``
tool, and so ``POST /api/v1/library/{search,get,sources}`` and ``reliafy
library ...`` for API tokens. A per-address limit keeps one client from
hammering them.
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse

from backend.library import service
from backend.ratelimit import SlidingWindowLimiter
from backend.request_ip import client_ip

router = APIRouter(prefix="/api/library")

_LIMIT = SlidingWindowLimiter(120)
_CACHE = {"Cache-Control": "public, max-age=3600"}


def _limited(request: Request) -> Optional[JSONResponse]:
    if not _LIMIT.allow(client_ip(request) or "unknown"):
        return JSONResponse(status_code=429, content={"detail": "Too many requests. Try again in a minute."},
                            headers={"Retry-After": "60"})
    return None


@router.get("/sources")
def library_sources(request: Request) -> JSONResponse:
    """The library's sources, their licences and what each holds."""
    return _limited(request) or JSONResponse(content=service.sources(), headers=_CACHE)


@router.get("/search")
def library_search(
    request: Request,
    q: Optional[str] = Query(default=None, max_length=200, description="Words to look for."),
    source: Optional[str] = None,
    equipment_type: Optional[str] = None,
    kind: Optional[str] = None,
    page: int = 1,
    page_size: int = service.DEFAULT_PAGE_SIZE,
) -> JSONResponse:
    """A page of matching records, best first, with counts."""
    limited = _limited(request)
    if limited:
        return limited
    try:
        out = service.search(q, source=source, equipment_type=equipment_type, kind=kind, page=page,
                             page_size=page_size)
    except ValueError as exc:
        return JSONResponse(status_code=422, content={"detail": str(exc)})
    return JSONResponse(content=out, headers=_CACHE)


@router.get("/records/{record_id}")
def library_record(record_id: str, request: Request) -> JSONResponse:
    """One record in full, with the model a block would use."""
    limited = _limited(request)
    if limited:
        return limited
    try:
        return JSONResponse(content=service.detail(record_id), headers=_CACHE)
    except service.LibraryNotFound as exc:
        return JSONResponse(status_code=404, content={"detail": str(exc)})
