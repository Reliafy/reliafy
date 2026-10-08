"""What to improve (#225): a repairable RBD's levers ranked by what a step of
each gains in availability (or cost), from RePyability 0.12's lever
sensitivity. See :mod:`backend.services.rbd_sensitivity`.

Gating follows the availability analysis: the exact and numerical answers
are free for everyone; where RePyability has no exact or numerical route
(limited repair crews for wear-out lives, say) the effects are simulated,
and that is Pro (or purchased credits), as the simulation is. The exact long
run of a diagram up to ``INLINE_MAX_BLOCKS`` blocks answers in the request;
the rest (numerical, over a window, simulated, larger) runs as a compute job
(#149) to poll at ``GET /api/rbd-jobs/{job_id}``, within the block limits of
``rbd_sensitivity.block_limit``.
"""

from __future__ import annotations

import json
import logging
from typing import Optional

from fastapi import APIRouter, Body, Depends
from fastapi.responses import JSONResponse

from backend.db import get_session
from backend.schema import Rbd
from backend.services import access as access_service
from backend.services import billing as billing_service
from backend.services import models as models_service
from backend.services import rbd_jobs as rbd_jobs_service
from backend.services import rbd_sensitivity
from backend.services import rbds as rbds_service
from backend.services import usage as usage_service
from backend.services.access import AccessCtx, get_access
from backend.services.rbd_analysis import AnalysisError, require_blocks

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api")

SIMULATION_PRO_MESSAGE = (
    "This diagram has no exact long-run route (RePyability's reason is above), so each lever's effect "
    "is simulated — that's part of Pro, or buy AI credits. Or download the diagram as Python and run "
    "RePyability's parameter_sensitivity on a simplified copy locally."
)
NEEDS_SIMULATION_MESSAGE = (
    "This diagram has no exact long-run route, so each lever's effect is simulated: four paired "
    "simulations per lever, which takes a minute or two."
)


def sensitivity_payload(session, ctx: AccessCtx, graph: dict, rbd: Optional[Rbd], resolve_owners, *,
                        window=None, step=None, rank_by=None, costs=None, order=None, simulate: bool = False
                        ) -> tuple[int, dict]:
    """What to improve, as ``(status, payload)``: 200 with the ranked levers
    (or a ``status`` saying why there are none yet: ``too_large``,
    ``pro_required``, ``needs_simulation``), 202 with a job to poll, 503 when
    the queue can't take it. ``simulate`` asks for the simulated route where
    the diagram needs it (an entitled user's click). Shared by the REST
    endpoint and the MCP server. Raises :class:`AnalysisError` for bad
    input or a diagram the availability analysis can't build."""
    require_blocks(graph)
    if not (graph or {}).get("repairable"):
        raise AnalysisError("What to improve is for repairable (availability) diagrams — give the blocks "
                            "repair times and mark the diagram repairable.")
    options = rbd_sensitivity.options(window=window, step=step, rank_by=rank_by, costs=costs, order=order)

    def resolve_model(model_id: str):
        return models_service.get_live_model(session, model_id, resolve_owners)

    plan = rbd_sensitivity.plan(graph, resolve_model, options.get("window"))
    head = {"kind": "sensitivity", "basis": plan["basis"], "basis_reason": plan["reason"],
            "n_blocks": plan["n_blocks"], "unit": (graph.get("unit") or "").strip()}
    if plan["too_large"]:
        return 200, {**head, "status": "too_large", "message": rbd_sensitivity.too_large_message(
            plan["n_blocks"], plan["limit"], plan["basis"], plan["window"])}
    entitled = billing_service.premium_compute_allowed(session, ctx.user)
    if plan["basis"] == "simulation":
        if not entitled:
            return 200, {**head, "status": "pro_required", "upgrade": True, "message": SIMULATION_PRO_MESSAGE}
        if not simulate:
            return 200, {**head, "status": "needs_simulation", "can_simulate": True,
                         "message": NEEDS_SIMULATION_MESSAGE}
    if plan["inline"]:
        result = rbd_sensitivity.analyze_sensitivity(graph, resolve_model, simulate=False, **options)
        return 200, {**result, "can_simulate": entitled}
    models = rbds_service.model_fingerprints(session, graph, resolve_owners)
    key = ("sensitivity|" + rbds_service.availability_cache_key(graph, None, models) + "|"
           + json.dumps(options, sort_keys=True, default=float))
    code, payload = rbd_jobs_service.run_sensitivity(
        session, uid=ctx.uid, graph=graph, options=options, cache_key=key,
        rbd_id=rbd.id if rbd is not None else None, resolve_model=resolve_model, resolve_owners=resolve_owners)
    if code == 200:
        payload = {**payload, "can_simulate": entitled}
    elif code == 202:
        payload = {**head, **payload, "can_simulate": entitled}
    return code, payload


@router.post("/rbds/sensitivity")
def rbd_sensitivity_endpoint(
    graph: dict = Body(...),
    rbd_id: str | None = Body(default=None),
    window: float | None = Body(default=None),
    step: float | None = Body(default=None),
    rank_by: str | None = Body(default=None),
    costs: dict | None = Body(default=None),
    order: str | None = Body(default=None),
    simulate: bool = Body(default=False),
    session=Depends(get_session),
    ctx: AccessCtx = Depends(get_access),
) -> JSONResponse:
    """What to improve on a repairable diagram (the one in the builder, saved
    or not): each lever — a block's mean life and repair time, its other
    model parameters, its maintenance intervals, durations and coverage, its
    standby group's, one more repair crew — with RePyability's derivative of
    the availability (and cost rate) and the effect of a ``step`` (0.1: 10%)
    in the direction that improves ``rank_by`` ("availability" or "cost").
    ``costs`` ({lever id: cost to make that change}) gives each its benefit
    per unit of cost; ``order`` "benefit" (the default) ranks by benefit
    alone, costs or not, and "benefit_per_cost" puts the costed levers first
    by benefit per unit spent, then the rest by benefit. ``window`` takes the mean over
    ``[0, window)`` from new instead of the long run. ``simulate`` runs the
    simulated route where the diagram needs it (Pro or credits)."""
    owners = ctx.read_owners
    rbd = None
    if rbd_id:
        rbd, _ = access_service.fetch_readable(session, "rbds", Rbd, rbd_id, ctx)
        if rbd is not None:
            owners = [*ctx.read_owners, rbd.owner_id]
    try:
        status, payload = sensitivity_payload(session, ctx, graph, rbd, owners, window=window, step=step,
                                              rank_by=rank_by, costs=costs, order=order, simulate=simulate)
    except AnalysisError as exc:
        return JSONResponse(status_code=422, content={"detail": str(exc)})
    except Exception:  # pragma: no cover - defensive
        logger.exception("What to improve failed")
        return JSONResponse(status_code=500, content={
            "detail": "Couldn't work out what to improve. The error has been logged."})
    if payload.get("basis") == "simulation" and payload.get("status") not in (
            "pro_required", "needs_simulation", "too_large"):
        usage_service.set_feature("rbd_sensitivity_sim")
    return JSONResponse(status_code=status, content=payload)
