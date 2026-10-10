"""Simulation run history (#112) and runtime quotes (#286).

* ``POST /api/rbds/quote`` — how long a simulation of a diagram should take,
  before it is run.
* ``GET /api/rbd-runs`` — the caller's runs (``rbd_id`` filters by diagram),
  ``/diagrams`` the diagrams they have runs of, ``/compare?ids=`` several
  finished runs side by side, ``/{id}`` one run in full, ``/{id}/export``
  as CSV or JSON, and ``POST /{id}/rerun`` the same inputs again.
* ``GET /api/admin/runtime-quote`` and ``POST …/refit`` — the quote's
  machine factors and their refit from logged runs (operators only).
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timezone

from fastapi import APIRouter, Body, Depends
from fastapi.responses import JSONResponse, Response

from backend.auth import get_current_user
from backend.db import get_session
from backend.schema import Rbd
from backend.services import access as access_service
from backend.services import billing as billing_service
from backend.services import compute_core, compute_queue, free_sims
from backend.services import rbd_runs
from backend.services import runtime_quote
from backend.services import usage as usage_service
from backend.services.access import AccessCtx, get_access
from backend.services.rbd_analysis import AnalysisError

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api")

RUN_NOT_FOUND = {"detail": "Run not found."}


def quote_for(session, graph: dict, t_max=None, quick: bool = False, current_state=None) -> dict:
    """The quote for a simulation of ``graph`` as the app would run it: on
    the calculation service when it's configured and the diagram can go
    there, else in-process."""
    from backend.services import rbd_analysis

    state = rbd_analysis.parse_current_state(graph, current_state) if current_state else None
    options = compute_core.availability_options(
        t_simulation=t_max, state=state, **(free_sims.options() if quick else {}))
    in_process = not compute_queue.configured() or bool(compute_core.needs_saved_models(graph))
    machine = runtime_quote.machine_of(in_process)
    return runtime_quote.quote_runtime(graph, options, machine=machine,
                                       factor=runtime_quote.current_factor(session, machine))


@router.post("/rbds/quote")
def quote_simulation(
    graph: dict = Body(..., embed=True),
    t_max: float | None = Body(default=None),
    quick: bool = Body(default=False),
    current_state: dict | None = Body(default=None),
    session=Depends(get_session),
    ctx: AccessCtx = Depends(get_access),
) -> JSONResponse:
    """How long a repairable diagram's simulation should take (#286):
    ``median_s`` (about), ``p90_s`` (up to) and ``text`` in words — or
    ``available: false`` with the reason. Nothing is run."""
    if not graph.get("repairable"):
        return JSONResponse(content={"available": False, "reason": "Only repairable diagrams are simulated."})
    try:
        return JSONResponse(content=quote_for(session, graph, t_max, quick, current_state))
    except AnalysisError as exc:
        return JSONResponse(status_code=422, content={"detail": str(exc)})


@router.get("/rbd-runs")
def list_runs(rbd_id: str | None = None, limit: int = rbd_runs.DEFAULT_LIMIT, before: str | None = None,
              session=Depends(get_session), ctx: AccessCtx = Depends(get_access)) -> JSONResponse:
    """The caller's availability simulations, newest first (``rbd_id``: that
    diagram's; a team's diagram shows every member's)."""
    return JSONResponse(content=rbd_runs.list_runs(session, ctx, rbd_id, limit, before))


@router.get("/rbd-runs/diagrams")
def run_diagrams(session=Depends(get_session), ctx: AccessCtx = Depends(get_access)) -> JSONResponse:
    """The diagrams the caller has runs of (for the filter)."""
    return JSONResponse(content={"diagrams": rbd_runs.diagrams(session, ctx)})


@router.get("/rbd-runs/compare")
def compare_runs(ids: str, session=Depends(get_session), ctx: AccessCtx = Depends(get_access)) -> JSONResponse:
    """Finished runs side by side (``ids`` comma-separated, at most
    :data:`rbd_runs.MAX_COMPARE`): each one's curve and band."""
    run_ids = [i for i in (ids or "").split(",") if i.strip()]
    if len(run_ids) < 2:
        return JSONResponse(status_code=422, content={"detail": "Pick at least two runs to compare."})
    return JSONResponse(content=rbd_runs.compare(session, ctx, [i.strip() for i in run_ids]))


def _visible(session, ctx, run_id):
    return rbd_runs.get_visible(session, ctx, run_id)


@router.get("/rbd-runs/{run_id}")
def get_run(run_id: str, session=Depends(get_session), ctx: AccessCtx = Depends(get_access)) -> JSONResponse:
    """One run: its stored results with their bands, the inputs and engine
    versions it ran on, and the precision it achieved."""
    job = _visible(session, ctx, run_id)
    if job is None:
        return JSONResponse(status_code=404, content=RUN_NOT_FOUND)
    entitled = billing_service.premium_compute_allowed(session, ctx.user)
    return JSONResponse(content=rbd_runs.detail(session, ctx, job, entitled))


def _filename(view: dict, ext: str) -> str:
    stem = re.sub(r"[^A-Za-z0-9]+", "-", (view.get("rbd_name") or "diagram")).strip("-").lower() or "diagram"
    when = (view.get("created_at") or "")[:10]
    return f"{stem}-run-{when}.{ext}"


@router.get("/rbd-runs/{run_id}/export")
def export_run(run_id: str, format: str = "csv", session=Depends(get_session),
               ctx: AccessCtx = Depends(get_access)) -> Response:
    """A finished run as CSV (the headline figures, A(t) with its band, each
    block's downtime share) or JSON (the whole run, inputs included)."""
    job = _visible(session, ctx, run_id)
    if job is None:
        return JSONResponse(status_code=404, content=RUN_NOT_FOUND)
    if job.get("status") != "done":
        return JSONResponse(status_code=409, content={"detail": "Only a finished run can be exported."})
    entitled = billing_service.premium_compute_allowed(session, ctx.user)
    view = rbd_runs.detail(session, ctx, job, entitled)
    if format == "json":
        view["inputs"]["graph"] = (job.get("request") or {}).get("graph")
        view["inputs"]["options"] = (job.get("request") or {}).get("options")
        body, media, ext = rbd_runs.export_json(view), "application/json; charset=utf-8", "json"
    elif format == "csv":
        body, media, ext = rbd_runs.export_csv(view), "text/csv; charset=utf-8", "csv"
    else:
        return JSONResponse(status_code=422, content={"detail": "format is csv or json."})
    return Response(content=body, media_type=media, headers={
        "Content-Disposition": f'attachment; filename="{_filename(view, ext)}"', "Cache-Control": "no-store"})


@router.post("/rbd-runs/{run_id}/rerun")
def rerun(run_id: str, session=Depends(get_session), ctx: AccessCtx = Depends(get_access)) -> JSONResponse:
    """Run the same inputs again (the diagram as it was then, its window and
    any current state), paid-gated as Run simulation is: a user without Pro
    gets a free quick run where they have one. Answers ``{run_id, status}``
    of the new run."""
    from backend.routers.rbds import availability_payload

    job = _visible(session, ctx, run_id)
    if job is None:
        return JSONResponse(status_code=404, content=RUN_NOT_FOUND)
    request = job.get("request") or {}
    graph, options = request.get("graph") or {}, request.get("options") or {}
    if not graph.get("nodes"):
        return JSONResponse(status_code=409, content={"detail": "This run's inputs weren't kept."})
    rbd = None
    if job.get("rbd_id"):
        rbd, _ = access_service.fetch_readable(session, "rbds", Rbd, job["rbd_id"], ctx)
    owners = [*ctx.read_owners, rbd.owner_id] if rbd is not None else ctx.read_owners
    entitled = billing_service.premium_compute_allowed(session, ctx.user)
    started = datetime.now(timezone.utc)
    usage_service.set_feature("availability_sim")
    try:
        status, payload = availability_payload(
            session, ctx, graph, options.get("t_simulation"), rbd, True, owners, simulate=True,
            current_state=options.get("state"), quick=not entitled, surface="app")
    except AnalysisError as exc:
        return JSONResponse(status_code=422, content={"detail": str(exc)})
    if status not in (200, 202):
        return JSONResponse(status_code=status, content=payload)
    if status == 202:
        return JSONResponse(status_code=202, content={"run_id": payload["job"]["job_id"],
                                                      "status": payload["job"]["status"]})
    new = session.rbd_jobs.find_one({"uid": ctx.uid, "kind": rbd_runs.KIND, "created_at": {"$gte": started}},
                                    sort=[("created_at", -1)])
    if new is None:
        return JSONResponse(status_code=409, content={"detail": "Nothing new was run."})
    return JSONResponse(content={"run_id": new["_id"], "status": new.get("status")})


# ---- Operators: the quote's calibration --------------------------------------------------

def _plain(doc):
    if isinstance(doc, dict):
        return {k: _plain(v) for k, v in doc.items()}
    if isinstance(doc, datetime):
        return doc.isoformat()
    return doc


def _machines(session) -> list[str]:
    known = set((runtime_quote.coefficients().get("machine_factors") or {}).keys())
    try:
        known |= set(session.rbd_runtime_log.distinct("machine"))
    except Exception:  # noqa: BLE001
        pass
    return sorted(m for m in known if m)


@router.get("/admin/runtime-quote")
def runtime_quote_status(session=Depends(get_session), user: dict = Depends(get_current_user)) -> JSONResponse:
    """Each machine's factor, its logged runs and how often a run finished
    within its quoted ceiling."""
    if not billing_service.is_admin_user(user):
        return JSONResponse(status_code=403, content={"detail": "Operator accounts only."})
    coeffs = runtime_quote.coefficients()
    return JSONResponse(content={
        "model": {k: coeffs.get(k) for k in ("model", "intercept", "sigma", "coefficients", "fitted_on")},
        "machines": [_plain(runtime_quote.calibration(session, m)) for m in _machines(session)],
        "min_runs": runtime_quote.MIN_REFIT_RUNS,
    })


@router.post("/admin/runtime-quote/refit")
def runtime_quote_refit(machine: str = Body(..., embed=True), apply: bool = Body(default=False),
                        session=Depends(get_session), user: dict = Depends(get_current_user)) -> JSONResponse:
    """Refit a machine's factor from its logged runs; ``apply`` stores it."""
    if not billing_service.is_admin_user(user):
        return JSONResponse(status_code=403, content={"detail": "Operator accounts only."})
    return JSONResponse(content=_plain(runtime_quote.refit_factor(session, machine, apply=apply)))
