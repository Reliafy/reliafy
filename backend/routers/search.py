"""``GET /api/search``: the app's one search for everything (the header's search box and
⌘K / Ctrl-K). The ranking and the access rules are backend/services/global_search.py."""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, Query
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse

from backend.db import get_session
from backend.services import global_search
from backend.services.access import AccessCtx, get_access
from backend.errors import client_message

router = APIRouter(prefix="/api", tags=["search"])


def maintenance_for(ctx: AccessCtx):
    """A function making the workspace's Reliafy Maintenance, or None when the viewer
    may not use it (it's off, or they aren't one of its users)."""
    from backend.maintenance.access import allowed

    if not allowed(ctx.user):
        return None

    def make():
        from backend.maintenance.service import Maintenance
        from backend.routers.maintenance import get_store

        return Maintenance(get_store(), ctx.write_owner, ctx.uid, time_zone=ctx.time_zone)

    return make


def work_orders_on() -> bool:
    from backend.maintenance.service import work_management_on

    return work_management_on()


@router.get("/search")
async def search(
    q: str = Query(default="", max_length=global_search.MAX_QUERY, description="What to look for."),
    kinds: Optional[str] = Query(default=None, description="Only these kinds, comma-separated (default: every kind)."),
    limit: int = Query(default=global_search.DEFAULT_LIMIT, ge=1, le=global_search.MAX_LIMIT,
                       description="The most results of each kind."),
    session=Depends(get_session),
    ctx: AccessCtx = Depends(get_access),
) -> JSONResponse:
    """The best matches of each kind the viewer can open in the active workspace, grouped
    by kind, best first."""
    try:
        out = await run_in_threadpool(global_search.search, session, ctx, q, kinds, limit,
                                      maintenance_for(ctx), work_orders_on())
    except ValueError as err:
        return JSONResponse(status_code=422, content={"detail": client_message(err)})
    return JSONResponse(content=out)
