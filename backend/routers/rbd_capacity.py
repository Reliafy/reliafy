"""Production availability for RBDs: the share of a demand delivered (#122).

Free for everyone: the capacity distribution is exact, with no simulation.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Body, Depends
from fastapi.responses import JSONResponse

from backend.db import get_session
from backend.services import rbd_capacity
from backend.services.access import AccessCtx, get_access
from backend.services.rbd_analysis import AnalysisError

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api")


@router.post("/rbds/production")
def rbd_production(
    graph: dict = Body(...),
    t: float | None = Body(default=None),
    session=Depends(get_session),
    ctx: AccessCtx = Depends(get_access),
) -> JSONResponse:
    """The diagram's capacity distribution and production availability: in
    the long run and over its period (repairable), or at ``t``
    (non-repairable). ``{"production": null}`` when no block has a
    capacity."""
    try:
        result = rbd_capacity.production_for_owner(session, graph, ctx.read_owners, t=t)
    except (rbd_capacity.CapacityError, AnalysisError) as exc:
        return JSONResponse(status_code=422, content={"detail": str(exc)})
    except Exception:  # pragma: no cover - defensive
        logger.exception("Production availability failed")
        return JSONResponse(status_code=500, content={"detail": "Couldn't work out this diagram's production."})
    return JSONResponse(content={"production": result})
