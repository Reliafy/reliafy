"""What to improve, the other measures (#225, #325): importance over time,
shares of a change, joint importance, what's moving availability now, and
whose parameter uncertainty widens the answer. See
:mod:`backend.services.rbd_measures`.

Gating follows the rest of What to improve: the exact and numerical measures
are free for everyone, answered in the request. The heavy uncertainty runs —
the Sobol indices, and the availability over time over draws of the fitted
models — are Pro (or purchased credits), as the simulation is, and run as a
compute job (#149) to poll at ``GET /api/rbd-jobs/{job_id}``.
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
from backend.services import rbd_measures
from backend.services import rbds as rbds_service
from backend.services import usage as usage_service
from backend.services.access import AccessCtx, get_access
from backend.services.rbd_analysis import AnalysisError, require_blocks

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api")

PRO_MESSAGE = (
    "The Sobol indices and the availability over time over draws of the fitted models take thousands of "
    "evaluations of the diagram: that's part of Pro, or buy AI credits. The long-run interval and the "
    "delta method's shares are free."
)


def measures_payload(session, ctx: AccessCtx, graph: dict, rbd: Optional[Rbd], resolve_owners, **raw
                     ) -> tuple[int, dict]:
    """One measure, as ``(status, payload)``: 200 with the figures (or a
    ``status`` saying why there are none: ``refused``, ``no_uncertainty``,
    ``pro_required``, ``too_large``), 202 with a job to poll, 503 when the
    queue can't take it. Shared by the REST endpoint and the MCP server.
    Raises :class:`AnalysisError` for bad input or a diagram the availability
    analysis can't build."""
    require_blocks(graph)
    if not (graph or {}).get("repairable"):
        raise AnalysisError("These measures are for repairable (availability) diagrams — give the blocks "
                            "repair times and mark the diagram repairable.")
    opts = rbd_measures.options(**raw)

    def resolve_model(model_id: str):
        return models_service.get_live_model(session, model_id, resolve_owners)

    if not rbd_measures.heavy(opts):
        return 200, rbd_measures.analyze_measure(graph, resolve_model, **opts)
    head = {"kind": "measure", "measure": opts["measure"], "question": rbd_measures.QUESTIONS[opts["measure"]],
            "unit": (graph.get("unit") or "").strip()}
    if not billing_service.premium_compute_allowed(session, ctx.user):
        return 200, {**head, "status": "pro_required", "upgrade": True, "message": PRO_MESSAGE}
    fits, fixed = rbd_measures.fits_for(graph, resolve_model)
    models = rbds_service.model_fingerprints(session, graph, resolve_owners)
    key = ("measures|" + rbds_service.availability_cache_key(graph, None, models) + "|"
           + json.dumps(opts, sort_keys=True, default=float))
    code, payload = rbd_jobs_service.run_measures(
        session, uid=ctx.uid, graph=graph, options=opts, fits=fits, fixed=fixed, cache_key=key,
        rbd_id=rbd.id if rbd is not None else None, resolve_model=resolve_model, resolve_owners=resolve_owners)
    if code == 202:
        payload = {**head, **payload}
    return code, payload


@router.post("/rbds/measures")
def rbd_measures_endpoint(
    graph: dict = Body(...),
    rbd_id: str | None = Body(default=None),
    measure: str = Body(...),
    window: float | None = Body(default=None),
    group_by: str | None = Body(default=None),
    method: str | None = Body(default=None),
    times: list | None = Body(default=None),
    level: float | None = Body(default=None),
    session=Depends(get_session),
    ctx: AccessCtx = Depends(get_access),
) -> JSONResponse:
    """One of What to improve's other measures on a repairable diagram (the
    one in the builder, saved or not). ``measure``: ``over_time`` (each
    block's importance from new over ``window``, or the analysis horizon),
    ``shares`` (the shares of the gain from improving every lever by the same
    fraction, ``group_by`` "block" or "kind"; over ``window`` when given),
    ``joint`` (each pair's joint importance), ``rate`` (each block's part in
    how fast the availability changes over time, and its share of the
    system's failures) or ``uncertainty`` (the long-run availability's
    interval at ``level`` over draws of the fitted models and each input's
    share of its variance, ``method`` "delta" or "sobol"; with ``times``
    the availability at those times and the mean over ``[0, t]``, with
    intervals). Sobol and ``times`` are Pro, as a compute job."""
    owners = ctx.read_owners
    rbd = None
    if rbd_id:
        rbd, _ = access_service.fetch_readable(session, "rbds", Rbd, rbd_id, ctx)
        if rbd is not None:
            owners = [*ctx.read_owners, rbd.owner_id]
    try:
        status, payload = measures_payload(session, ctx, graph, rbd, owners, measure=measure, window=window,
                                           group_by=group_by, method=method, times=times, level=level)
    except AnalysisError as exc:
        return JSONResponse(status_code=422, content={"detail": str(exc)})
    except Exception:  # pragma: no cover - defensive
        logger.exception("What to improve (%s) failed", measure)
        return JSONResponse(status_code=500, content={
            "detail": "Couldn't work out this measure. The error has been logged."})
    if status in (200, 202) and payload.get("status") not in ("pro_required",) and rbd_measures.heavy(
            {"measure": measure, "method": method, "times": times}):
        usage_service.set_feature("rbd_measures_heavy")
    return JSONResponse(status_code=status, content=payload)
