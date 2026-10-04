"""Compare two repairable RBDs (#104): "Compare with…" on the availability
results. Paid-gated exactly like the availability simulation it builds on."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Body, Depends
from fastapi.responses import JSONResponse

from backend.db import get_session
from backend.routers.rbds import AVAILABILITY_PRO_PAYLOAD
from backend.schema import Rbd
from backend.services import access as access_service
from backend.services import billing as billing_service
from backend.services import rbd_compare
from backend.services.access import AccessCtx, get_access
from backend.services.rbd_analysis import AnalysisError

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api")


@router.post("/rbds/compare")
def compare_rbds(
    graph: dict = Body(...),
    other_id: str | None = Body(default=None),
    other_graph: dict | None = Body(default=None),
    name: str | None = Body(default=None),
    other_name: str | None = Body(default=None),
    t_max: float | None = Body(default=None),
    session=Depends(get_session),
    ctx: AccessCtx = Depends(get_access),
) -> JSONResponse:
    """Design B (``other_id``, a saved diagram the caller can read, or an
    ``other_graph``) against design A (``graph``, the diagram in the builder,
    saved or not): the simulated difference in availability over the window
    (B − A) with its confidence interval, from common random numbers, plus
    both exact long-run availabilities. ``t_max`` fixes the window."""
    if not billing_service.premium_compute_allowed(session, ctx.user):
        return JSONResponse(status_code=402, content=AVAILABILITY_PRO_PAYLOAD)

    owners_b = ctx.read_owners
    if other_id:
        other, _ = access_service.fetch_readable(session, "rbds", Rbd, other_id, ctx)
        if other is None or other.id in ctx.hidden:
            return JSONResponse(status_code=404, content={"detail": "RBD not found."})
        other_graph = other.graph or {}
        other_name = other_name or other.name
        owners_b = [*ctx.read_owners, other.owner_id]
    elif not isinstance(other_graph, dict):
        return JSONResponse(status_code=422, content={"detail": "Pick a diagram to compare with."})

    try:
        result = rbd_compare.compare_graphs(
            session, graph, other_graph, ctx.read_owners, owners_b, t_simulation=t_max,
        )
    except AnalysisError as exc:
        return JSONResponse(status_code=422, content={"detail": str(exc)})
    except Exception:  # pragma: no cover - defensive
        logger.exception("Failed to compare RBDs")
        return JSONResponse(status_code=500, content={"detail": "Failed to compare the diagrams. The error has been logged."})
    result["designs"]["a"]["name"] = name or "This diagram"
    result["designs"]["b"]["name"] = other_name or "The other diagram"
    return JSONResponse(content=result)
