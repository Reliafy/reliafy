"""Maintenance and proof-test intervals chosen together (#172, #228): see
:mod:`backend.services.rbd_intervals`.

Free for everyone, as the exact availability figures are: every candidate
plan is scored by RePyability's exact (or numerical) long-run values. A
proof-test search over more than ``rbd_intervals.INLINE_EVALUATIONS``
candidate plans runs as a compute job (#149) to poll at
``GET /api/rbd-jobs/{job_id}``; the rest answers in the request. With the
diagram's repair crews limited the intervals are chosen as if every repair
started at once (``assume_unlimited_crews``); what the waiting costs comes
from simulating the plan with the crews, which is the (paid) availability
simulation of the diagram with the plan on it.
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
from backend.services import models as models_service
from backend.services import rbd_intervals
from backend.services import rbd_jobs as rbd_jobs_service
from backend.services import rbds as rbds_service
from backend.services.access import AccessCtx, get_access
from backend.services.rbd_analysis import AnalysisError

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api")


def intervals_payload(session, ctx: AccessCtx, graph: dict, rbd: Optional[Rbd], resolve_owners,
                      **raw) -> tuple[int, dict]:
    """The intervals, as ``(status, payload)``: 200 with the plan (or
    ``status: "crews_limited"``), 202 with a job to poll, 503 when the queue
    can't take it. Shared by the REST endpoint and the MCP server. Raises
    :class:`AnalysisError` for bad input or a diagram that can't be built."""
    if not (graph or {}).get("repairable"):
        raise AnalysisError("Interval optimisation is for repairable (availability) diagrams — give the blocks "
                            "repair times and mark the diagram repairable.")
    opts = rbd_intervals.options(**raw)

    def resolve_model(model_id: str):
        return models_service.get_live_model(session, model_id, resolve_owners)

    plan = rbd_intervals.plan(graph, **opts)
    if plan["inline"]:
        return 200, rbd_intervals.optimise(graph, resolve_model, **opts)
    models = rbds_service.model_fingerprints(session, graph, resolve_owners)
    key = ("intervals|" + rbds_service.availability_cache_key(graph, None, models) + "|"
           + json.dumps(opts, sort_keys=True, default=float))
    code, payload = rbd_jobs_service.run_intervals(
        session, uid=ctx.uid, graph=graph, options=opts, cache_key=key,
        rbd_id=rbd.id if rbd is not None else None, resolve_model=resolve_model, resolve_owners=resolve_owners)
    if code == 202:
        payload = {**payload, "schedule": plan["schedule"], "n_blocks": plan["n_blocks"],
                   "evaluations": plan["evaluations"], "unit": (graph.get("unit") or "").strip()}
    return code, payload


@router.post("/rbds/intervals")
def rbd_intervals_endpoint(
    graph: dict = Body(...),
    rbd_id: str | None = Body(default=None),
    schedule: str | None = Body(default=None),
    blocks: list | None = Body(default=None),
    min_availability: float | None = Body(default=None),
    max_cost_rate: float | None = Body(default=None),
    max_pfd: float | None = Body(default=None),
    target_sil: int | None = Body(default=None),
    allowed: list | dict | None = Body(default=None),
    stagger: bool = Body(default=False),
    assume_unlimited_crews: bool = Body(default=False),
    session=Depends(get_session),
    ctx: AccessCtx = Depends(get_access),
) -> JSONResponse:
    """Choose the age-replacement (``schedule`` "replacement") or proof-test
    ("proof_test") intervals of a repairable diagram's blocks together: the
    lowest long-run cost rate, optionally keeping the availability at least
    ``min_availability`` (a safety function: a PFDavg of at most ``max_pfd``,
    or within ``target_sil``), or the highest availability within
    ``max_cost_rate``. Proof tests choose from ``allowed`` (a list for every
    block, or one per block id; default a monthly-to-four-yearly calendar in
    the diagram's unit); ``stagger`` chooses the first tests' times too.
    ``assume_unlimited_crews`` is needed when the diagram's repair crews are
    limited. Nothing is saved."""
    owners = ctx.read_owners
    rbd = None
    if rbd_id:
        rbd, _ = access_service.fetch_readable(session, "rbds", Rbd, rbd_id, ctx)
        if rbd is not None:
            owners = [*ctx.read_owners, rbd.owner_id]
    try:
        status, payload = intervals_payload(
            session, ctx, graph, rbd, owners, schedule=schedule, blocks=blocks, min_availability=min_availability,
            max_cost_rate=max_cost_rate, max_pfd=max_pfd, target_sil=target_sil, allowed=allowed,
            stagger=stagger, assume_unlimited_crews=assume_unlimited_crews)
    except AnalysisError as exc:
        return JSONResponse(status_code=422, content={"detail": str(exc)})
    except Exception:  # pragma: no cover - defensive
        logger.exception("Interval optimisation failed")
        return JSONResponse(status_code=500, content={
            "detail": "Couldn't choose the intervals. The error has been logged."})
    return JSONResponse(status_code=status, content=payload)
