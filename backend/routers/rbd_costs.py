"""Cheapest design of a repairable RBD (#99): the redundancy with the lowest
total cost of ownership over a horizon (RePyability's
``RepairableRBD.allocate_redundancy``).

Paid-gated like the availability simulation: the exact long-run availability
and cost figures of a repairable diagram come only with the (paid)
availability analysis, and a cost-optimal design reports both. Nothing is
saved — the builder puts the chosen design on the canvas for the user to
review and save.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Body, Depends
from fastapi.responses import JSONResponse

from backend.db import get_session
from backend.routers.rbds import AVAILABILITY_PRO_PAYLOAD
from backend.services import billing as billing_service
from backend.services import models as models_service
from backend.services import rbd_costs
from backend.services.access import AccessCtx, get_access
from backend.services.rbd_analysis import AnalysisError

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api")


@router.post("/rbds/design/cheapest")
def cheapest_rbd_design(
    graph: dict = Body(...),
    horizon: float | None = Body(default=None),
    min_availability: float | None = Body(default=None),
    blocks: list | None = Body(default=None),
    discount_rate: float | None = Body(default=None),
    session=Depends(get_session),
    ctx: AccessCtx = Depends(get_access),
) -> JSONResponse:
    """How many copies of each priced block own the diagram for ``horizon`` at
    the lowest total cost (purchase + running + lost production), optionally
    at least ``min_availability`` available; with the design as drawn for
    comparison and the diagram with the copies drawn on it. ``discount_rate``
    (% a year; default the diagram's) makes the totals present values (#219)."""
    if not billing_service.premium_compute_allowed(session, ctx.user):
        return JSONResponse(status_code=402, content=AVAILABILITY_PRO_PAYLOAD)
    owners = ctx.read_owners

    def resolve_model(model_id: str):
        return models_service.get_live_model(session, model_id, owners)

    try:
        result = rbd_costs.cheapest_design(
            graph, resolve_model, horizon=horizon, min_availability=min_availability,
            blocks=[str(b) for b in blocks] if blocks else None, discount_rate=discount_rate,
        )
    except AnalysisError as exc:
        return JSONResponse(status_code=422, content={"detail": str(exc)})
    except Exception:  # pragma: no cover - defensive
        logger.exception("Cheapest repairable design failed")
        return JSONResponse(
            status_code=500, content={"detail": "Couldn't find the cheapest design for this diagram."}
        )
    return JSONResponse(content=result)
