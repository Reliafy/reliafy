"""``GET /api/changes`` — what changed in the active workspace over a period (#41).

``days`` (default 30) or ``since`` (``last_visit`` or an ISO date). Personal
is the user's own items; a team workspace is the team's
(``backend/services/workspace_changes.py``).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

from backend.db import get_session
from backend.services import time_zones, workspace_changes
from backend.services.access import AccessCtx, get_access
from backend.errors import client_message

router = APIRouter(prefix="/api")


@router.get("/changes")
def workspace_changes_summary(days: int | None = None, since: str | None = None,
                              session=Depends(get_session), ctx: AccessCtx = Depends(get_access)) -> JSONResponse:
    try:
        return JSONResponse(content=changes_payload(session, ctx, days=days, since=since))
    except workspace_changes.PeriodError as exc:
        return JSONResponse(status_code=422, content={"detail": client_message(exc)})


def changes_payload(session, ctx: AccessCtx, days: int | None = None, since: str | None = None,
                    rcm_all=None) -> dict:
    """What changed over the period (also Home's summary, which passes the RCM it has
    already read as ``rcm_all``); raises PeriodError for a bad one."""
    period = workspace_changes.resolve_period(session, ctx.uid, since=since, days=days,
                                              tz=time_zones.zone(ctx.time_zone))
    return workspace_changes.summarize(session, ctx.list_owners, ctx.uid, period, user=ctx.user,
                                       rcm_all=rcm_all)
