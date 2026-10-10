"""The node covariate modal's live preview (#52): see
:mod:`backend.services.rbd_tvc`.

``POST /api/rbds/tvc-preview`` with ``{"model_id", "schedules": {name:
{"expression": …} | {"table": […], "period": …}}, "constants": {name: value},
"t_max"}`` returns each covariate's stair-step path, the block's reliability
R(t) along it and any extrapolation warning — or a 422 saying, in plain
words, why the schedule can't be used. Free for everyone, as the analysis it
previews is. The model resolves as the analysis resolves it: a saved
regression model the caller can read, re-fitted on demand.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Body, Depends
from fastapi.responses import JSONResponse

from backend import fitting
from backend.db import get_session
from backend.services import models as models_service
from backend.services import rbd_tvc
from backend.services.access import AccessCtx, get_access

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api")


@router.post("/rbds/tvc-preview")
def tvc_preview(
    model_id: str = Body(...),
    schedules: dict = Body(default={}),
    constants: dict = Body(default={}),
    t_max: float | None = Body(default=None),
    session=Depends(get_session),
    ctx: AccessCtx = Depends(get_access),
) -> JSONResponse:
    try:
        entry = models_service.get_live_model(session, model_id, ctx.read_owners)
    except (models_service.ModelNotFound, fitting.FitError):
        entry = None
    if not entry:
        return JSONResponse(status_code=404, content={"detail": "Model not found — re-fit it or pick another."})
    if not isinstance(schedules, dict) or not isinstance(constants, dict):
        return JSONResponse(status_code=422, content={"detail": "schedules and constants are objects keyed by "
                                                                "covariate name."})
    try:
        return JSONResponse(content=rbd_tvc.preview(entry, schedules, constants, t_max))
    except rbd_tvc.ScheduleError as exc:
        return JSONResponse(status_code=422, content={"detail": str(exc)})
    except ValueError as exc:  # the engine refusing the model along the path
        return JSONResponse(status_code=422, content={"detail": str(exc) or "This schedule can't be evaluated."})
    except Exception:  # pragma: no cover - defensive
        logger.exception("Failed to preview a covariate schedule")
        return JSONResponse(status_code=500, content={"detail": "Couldn't preview the schedule. The error has "
                                                                "been logged."})
