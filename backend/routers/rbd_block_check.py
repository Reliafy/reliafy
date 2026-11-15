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
from backend.errors import client_message

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
    its exact mean life and the simulated mean with a 90% interval."""

    def resolve_model(model_id: str):
        return models_service.get_live_model(session, model_id, ctx.read_owners)

    try:
        result = rbd_block_check.check_mean(node, resolve_model, unit or "")
    except AnalysisError as exc:
        return JSONResponse(status_code=422, content={"detail": client_message(exc)})
    except Exception:  # pragma: no cover - defensive
        logger.exception("Failed to check a block's mean")
        return JSONResponse(status_code=500, content={"detail": "Failed to check the block. The error has been logged."})
    return JSONResponse(content=result)


@router.post("/rbds/standby-route")
def standby_route(
    node: dict = Body(..., embed=True),
    session=Depends(get_session),
    ctx: AccessCtx = Depends(get_access),
) -> JSONResponse:
    """A standby block's arrangement in words and how it's worked out: exact
    or numerical (free), or only by simulation (RePyability's plain refusal,
    and the offer to simulate it with Pro). Quick and free: it simulates
    nothing."""
    from backend.services import rbd_standby

    def resolve_model(model_id: str):
        return models_service.get_live_model(session, model_id, ctx.read_owners)

    try:
        result = rbd_standby.route_of(node, resolve_model)
    except AnalysisError as exc:
        return JSONResponse(status_code=422, content={"detail": client_message(exc)})
    except Exception:  # pragma: no cover - defensive
        logger.exception("Failed to read a standby block's route")
        return JSONResponse(status_code=500, content={"detail": "Failed to read the block. The error has been logged."})
    return JSONResponse(content=result)


@router.post("/rbds/repairable-block")
def repairable_block(
    node: dict = Body(...),
    unit: str | None = Body(default=None),
    repairable: bool = Body(default=True),
    session=Depends(get_session),
    ctx: AccessCtx = Depends(get_access),
) -> JSONResponse:
    """A block on a fitted repairable model (#367), for its "Repairs and replacement" section: the
    model in words, whether it can wear out (and so needs a replacement rule), the suggested rule
    for its costs and how its long-run availability is worked out (exact/simulated, Free/Pro, read
    from RePyability's analysis routes). Quick and free: it works nothing out for the diagram."""
    from backend.services import rbd_repairable_blocks

    def resolve_model(model_id: str):
        return models_service.get_live_model(session, model_id, ctx.read_owners)

    try:
        result = rbd_repairable_blocks.block_summary(node, resolve_model, unit or "", repairable)
    except AnalysisError as exc:
        return JSONResponse(status_code=422, content={"detail": client_message(exc)})
    except Exception:  # pragma: no cover - defensive
        logger.exception("Failed to summarise a repairable block")
        return JSONResponse(status_code=500, content={"detail": "Failed to read the block. The error has been logged."})
    return JSONResponse(content=result)
