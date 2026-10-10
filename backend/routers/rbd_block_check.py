"""Check by simulation (#326): a standby or load-sharing block's exact mean
life beside its simulated estimate and interval. Quick (a fraction of a
second) and free, like the exact figures."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Body, Depends
from fastapi.responses import JSONResponse

from backend.db import get_session
from backend.services import models as models_service
from backend.services import rbd_block_check
from backend.services.access import AccessCtx, get_access
from backend.services.rbd_analysis import AnalysisError

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api")


@router.post("/rbds/check-block-mean")
def check_block_mean(
    node: dict = Body(...),
    unit: str | None = Body(default=None),
    session=Depends(get_session),
    ctx: AccessCtx = Depends(get_access),
) -> JSONResponse:
    """``node`` (a standby or load-sharing block as the builder stores it):
    its exact mean life and the simulated mean with a 95% interval."""

    def resolve_model(model_id: str):
        return models_service.get_live_model(session, model_id, ctx.read_owners)

    try:
        result = rbd_block_check.check_mean(node, resolve_model, unit or "")
    except AnalysisError as exc:
        return JSONResponse(status_code=422, content={"detail": str(exc)})
    except Exception:  # pragma: no cover - defensive
        logger.exception("Failed to check a block's mean")
        return JSONResponse(status_code=500, content={"detail": "Failed to check the block. The error has been logged."})
    return JSONResponse(content=result)
