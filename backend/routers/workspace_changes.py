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

router = APIRouter(prefix="/api")


@router.get("/changes")
def workspace_changes_summary(days: int | None = None, since: str | None = None,
                              session=Depends(get_session), ctx: AccessCtx = Depends(get_access)) -> JSONResponse:
    try:
        period = workspace_changes.resolve_period(session, ctx.uid, since=since, days=days,
                                                  tz=time_zones.zone(ctx.time_zone))
    except workspace_changes.PeriodError as exc:
        return JSONResponse(status_code=422, content={"detail": str(exc)})
    return JSONResponse(content=workspace_changes.summarize(session, ctx.list_owners, ctx.uid, period))
