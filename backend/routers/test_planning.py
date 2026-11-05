"""Test planning API: sequential tests, life tests, accelerated test plans and
comparisons (SurPyval's ``test_planning``; the demonstration test stays at
``/api/strategy/demonstration-test``). Every plan is exact or numerical, so
free; checking a plan by simulation (``/simulate``) refits hundreds of
simulated tests, so it is Pro and runs as a compute job."""

from __future__ import annotations

import hashlib
import json
import logging

from fastapi import APIRouter, Body, Depends
from fastapi.responses import JSONResponse

from backend.auth import get_current_user
from backend.db import get_session
from backend.services import billing as billing_service
from backend.services import compute_queue
from backend.services import rbd_jobs as rbd_jobs_service
from backend.services import test_planning as tp_service
from backend.services.access import AccessCtx, get_access
from backend.services.strategy import StrategyError

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/test-planning")

SIMULATION_PRO_PAYLOAD = {
    "detail": ("Checking a plan by simulation fits the model to hundreds of simulated tests, so it's part of Pro. "
               "Every plan on this page is free."),
    "code": "pro_required",
    "upgrade": True,
}

_FIELDS = {
    "sequential": ("method", "mtbf", "good_mtbf", "reliability", "good_reliability", "confidence", "producer_risk",
                   "unit", "failures_seen", "time_seen", "units_seen"),
    "life": tp_service._SIM_INPUTS["life"],
    "accelerated": tp_service._SIM_INPUTS["accelerated"],
    "comparison": ("kind", "solve_for", "hazard_ratio", "event_probability", "units_per_group", "allocation_ratio",
                   "power", "confidence", "one_sided", "failures_before", "exposure_before", "exposure_after",
                   "rate_ratio", "unit"),
}
_RUN = {
    "sequential": tp_service.sequential_test,
    "life": tp_service.life_test,
    "accelerated": tp_service.accelerated_test,
    "comparison": tp_service.comparison,
}


def _answer(name: str, body: dict) -> JSONResponse:
    if not isinstance(body, dict):
        return JSONResponse(status_code=422, content={"detail": "The body must be a JSON object."})
    unknown = sorted(set(body) - set(_FIELDS[name]))
    if unknown:
        return JSONResponse(status_code=422, content={
            "detail": f"Unknown field{'s' if len(unknown) > 1 else ''}: {', '.join(unknown)}."})
    try:
        return JSONResponse(content=_RUN[name](**body))
    except StrategyError as exc:
        return JSONResponse(status_code=422, content={"detail": str(exc)})
    except (TypeError, ValueError) as exc:
        return JSONResponse(status_code=422, content={"detail": str(exc) or "Invalid inputs."})
    except Exception:  # pragma: no cover - defensive
        logger.exception("Test planning (%s) failed", name)
        return JSONResponse(status_code=500, content={"detail": "Calculation failed. The error has been logged."})


@router.post("/sequential")
def sequential(body: dict = Body(default={}), user: dict = Depends(get_current_user)) -> JSONResponse:
    """A truncated sequential test of an MTBF or a reliability: accept/reject
    lines, the operating characteristic and the average test length."""
    return _answer("sequential", body)


@router.post("/life")
def life(body: dict = Body(default={}), user: dict = Depends(get_current_user)) -> JSONResponse:
    """A life test's precision for a B-life or the mean, or the units or test
    length for a precision."""
    return _answer("life", body)


@router.post("/accelerated")
def accelerated(body: dict = Body(default={}), user: dict = Depends(get_current_user)) -> JSONResponse:
    """An accelerated life test plan: stresses, units at each, expected
    failures and the precision at the use stress."""
    return _answer("accelerated", body)


@router.post("/comparison")
def comparison(body: dict = Body(default={}), user: dict = Depends(get_current_user)) -> JSONResponse:
    """Did the change work? A log-rank test's units and power, or a
    before/after failure-rate comparison's exposure and detectable change."""
    return _answer("comparison", body)


@router.post("/simulate")
def simulate(
    kind: str = Body(..., embed=True),
    inputs: dict = Body(..., embed=True),
    n_sim: int | None = Body(default=None, embed=True),
    session=Depends(get_session),
    ctx: AccessCtx = Depends(get_access),
) -> JSONResponse:
    """Check a life or accelerated test plan by simulating it (Pro): 200 with
    the result (in-process when no compute queue is configured, or an
    identical finished job), 202 with a ``job`` to poll at
    ``/api/rbd-jobs/{id}``, 402 when not entitled."""
    if not billing_service.premium_compute_allowed(session, ctx.user):
        return JSONResponse(status_code=402, content=dict(SIMULATION_PRO_PAYLOAD))
    try:
        request = tp_service.simulation_request(kind, inputs, n_sim=n_sim)
    except StrategyError as exc:
        return JSONResponse(status_code=422, content={"detail": str(exc)})
    if not compute_queue.configured():
        try:
            return JSONResponse(content=tp_service.simulate_precision(request))
        except StrategyError as exc:
            return JSONResponse(status_code=422, content={"detail": str(exc)})
    key = "test_precision|" + hashlib.sha256(json.dumps(request, sort_keys=True, default=float).encode()).hexdigest()
    kind_ = rbd_jobs_service.KIND_TEST_PRECISION
    existing = rbd_jobs_service.find_reusable(session, ctx.uid, key, False, include_done=True)
    if existing is not None:
        if existing["status"] == "done":
            return JSONResponse(content={**(existing.get("result") or {}), "job_id": existing["_id"]})
        job = existing
    else:
        job = rbd_jobs_service.create(session, uid=ctx.uid, kind=kind_, request=request, cache_key=key,
                                      rbd_id=None, quick=False, store=False)
        try:
            compute_queue.enqueue(job["_id"], kind_, request)
        except compute_queue.QueueError as exc:
            rbd_jobs_service.finish(session, job["_id"], "failed", error=str(exc) or rbd_jobs_service.QUEUE_UNAVAILABLE)
            return JSONResponse(status_code=503, content={"detail": rbd_jobs_service.QUEUE_UNAVAILABLE,
                                                          "code": "compute_unavailable"})
    return JSONResponse(status_code=202, content={
        "kind": kind_,
        "status": job.get("status"),
        "job": {"job_id": job["_id"], "status": job["status"],
                "queue_position": rbd_jobs_service.queue_position(session, job), "kind": kind_},
    })
