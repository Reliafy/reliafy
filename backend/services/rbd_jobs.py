"""RBD analysis jobs (#146): availability simulations run off the web service.

With the compute queue configured (``COMPUTE_QUEUE``), a simulation becomes a
job: a record in ``rbd_jobs``, a Cloud Tasks task to the compute service, and
a callback that stores the result. Without it (self-hosted, dev, tests) the
simulation runs in-process and its result is returned directly — exactly the
behaviour before the queue existed.

A job record::

    {_id, uid, kind: "availability", rbd_id, cache_key, quick, store,
     request: {graph, options},       # self-contained (compute_core)
     context: {exact, current_state}, # what the finished payload is shown with
     status: queued | running | done | failed,
     created_at, started_at, finished_at, expires_at,
     result | error, timings, computed_at, free_sim_day}

``store`` says whether the result may be written to the diagram's saved
availability result (the requester could edit the diagram). ``cache_key``
identifies the inputs: the diagram's availability cache key, plus the current
state when the run starts from one (such a run is never stored). ``context``
holds the free part of the answer computed on the web (the exact figures,
#154), so a finished job's view is the whole availability payload, as an
in-process run returns it (:func:`availability_out`). ``expires_at``
drives a TTL index: finished jobs are kept ``RBD_JOB_TTL_DAYS``. A job still
queued or running after ``RBD_JOB_STALE_S`` was dropped by the queue (its
retries were spent) and is reported failed. The names follow #111 (``rbd_jobs``
/ ``get_job``), of which this is the first piece.
"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

from backend import config
from backend.services import compute_core, compute_queue, free_sims
from backend.services import rbds as rbds_service

logger = logging.getLogger(__name__)

KIND_AVAILABILITY = "availability"
# What to improve (#225): the levers ranked, when numerical, over a window,
# simulated or large (see rbd_sensitivity). Never stored on the diagram.
KIND_SENSITIVITY = "sensitivity"
# Maintenance and proof-test intervals (#228): a large proof-test search (see
# rbd_intervals). Never stored on the diagram.
KIND_INTERVALS = "intervals"
ACTIVE = ("queued", "running")
FINISHED = ("done", "failed")

QUEUE_UNAVAILABLE = "Couldn't start the calculation — try again in a moment."
STALE_ERROR = "The calculation didn't finish. Please run it again."
FAILED_ERROR = "The calculation failed. Check the diagram and try again."


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _aware(dt) -> Optional[datetime]:
    """Mongo hands datetimes back naive (UTC)."""
    if dt is None:
        return None
    if isinstance(dt, str):
        try:
            dt = datetime.fromisoformat(dt)
        except ValueError:
            return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _iso(dt) -> Optional[str]:
    dt = _aware(dt)
    return dt.isoformat() if dt else None


def _stale_before() -> datetime:
    return _now() - timedelta(seconds=int(config.RBD_JOB_STALE_S))


# ---- Records -------------------------------------------------------------------

def create(db, *, uid: str, kind: str, request: dict, cache_key: str, rbd_id: Optional[str],
           quick: bool, store: bool, free_sim_day: Optional[str] = None,
           context: Optional[dict] = None, owners=None) -> dict:
    now = _now()
    job = {
        "_id": uuid.uuid4().hex,
        "uid": uid,
        "kind": kind,
        "rbd_id": rbd_id,
        "cache_key": cache_key,
        "quick": bool(quick),
        "store": bool(store),
        "request": request,
        "context": json.loads(json.dumps(context or {}, default=float)),
        "status": "queued",
        "created_at": now,
        "started_at": None,
        "finished_at": None,
        # Dropped by the TTL index unless it finishes (which moves this on).
        "expires_at": now + timedelta(days=int(config.RBD_JOB_TTL_DAYS)),
        "free_sim_day": free_sim_day,
        # The read scope cache_key was built in, for the store guard (#92).
        "owners": list(owners) if isinstance(owners, (list, tuple, set, frozenset)) else owners,
    }
    db.rbd_jobs.insert_one(job)
    return job


def _expire_if_stale(db, job: Optional[dict]) -> Optional[dict]:
    """Mark a job the queue has given up on failed (and refund a free run)."""
    if job is None or job.get("status") not in ACTIVE:
        return job
    created = _aware(job.get("created_at"))
    if created is None or created >= _stale_before():
        return job
    finish(db, job["_id"], "failed", error=STALE_ERROR)
    return db.rbd_jobs.find_one({"_id": job["_id"]})


def get(db, job_id: str) -> Optional[dict]:
    return _expire_if_stale(db, db.rbd_jobs.find_one({"_id": job_id}))


def find_reusable(db, uid: str, cache_key: str, quick: bool, include_done: bool) -> Optional[dict]:
    """The caller's newest job for the same inputs that is still in flight
    (or, with ``include_done``, finished successfully and not yet expired)."""
    statuses = list(ACTIVE) + (["done"] if include_done else [])
    for job in db.rbd_jobs.find(
        {"uid": uid, "cache_key": cache_key, "quick": bool(quick), "status": {"$in": statuses}}
    ).sort("created_at", -1).limit(3):
        job = _expire_if_stale(db, job)
        if job and job.get("status") in statuses:
            return job
    return None


def latest_active(db, uid: str, rbd_id: str, kind: str = KIND_AVAILABILITY) -> Optional[dict]:
    """The caller's newest in-flight job of ``kind`` for a diagram (to resume
    polling)."""
    for job in db.rbd_jobs.find(
        {"uid": uid, "rbd_id": rbd_id, "kind": kind, "status": {"$in": list(ACTIVE)}}
    ).sort("created_at", -1).limit(3):
        job = _expire_if_stale(db, job)
        if job and job.get("status") in ACTIVE:
            return job
    return None


def queue_position(db, job: dict) -> Optional[int]:
    """How many jobs are ahead: queued or running, created earlier (and not
    abandoned). None once the job itself is running or finished."""
    if job.get("status") != "queued":
        return None
    return db.rbd_jobs.count_documents({
        "status": {"$in": list(ACTIVE)},
        "created_at": {"$lt": job["created_at"], "$gte": _stale_before()},
    })


def _store_result(db, job: dict, result: dict) -> Optional[str]:
    if not (job.get("store") and job.get("rbd_id")):
        return None
    return rbds_service.save_availability_result(
        db, job["rbd_id"], job["cache_key"], result, job.get("uid"), job.get("owners")
    )


def finish(db, job_id: str, status: str, *, result: Optional[dict] = None, error: Optional[str] = None,
           timings: Optional[dict] = None, started_at=None) -> bool:
    """Record a job's outcome, once: True if this call finished it (a repeat
    — e.g. a retried task's second callback — changes nothing). A successful
    result is stored on the diagram when the job may; a failed free run is
    given back."""
    now = _now()
    update = {
        "status": status,
        "finished_at": now,
        "expires_at": now + timedelta(days=int(config.RBD_JOB_TTL_DAYS)),
        "timings": timings or None,
    }
    if status == "done":
        update["result"] = json.loads(json.dumps(result or {}, default=float))
    else:
        update["error"] = error or FAILED_ERROR
    res = db.rbd_jobs.update_one({"_id": job_id, "status": {"$in": list(ACTIVE)}}, {"$set": update})
    if not getattr(res, "modified_count", 0):
        return False
    job = db.rbd_jobs.find_one({"_id": job_id}) or {}
    if started_at and not job.get("started_at"):
        db.rbd_jobs.update_one({"_id": job_id}, {"$set": {"started_at": _aware(started_at)}})
    if status == "done":
        try:
            computed_at = _store_result(db, job, update["result"])
        except Exception:  # noqa: BLE001 - the job's own result still stands
            logger.exception("Couldn't save job %s's result on RBD %s", job_id, job.get("rbd_id"))
            computed_at = None
        db.rbd_jobs.update_one({"_id": job_id}, {"$set": {"computed_at": computed_at}})
    elif job.get("quick"):
        free_sims.refund(db, job.get("uid"), job.get("free_sim_day"))
    return True


def apply_callback(db, payload: dict) -> bool:
    """Apply one callback from the compute service. Idempotent: a repeated or
    late callback for a finished job is ignored (and still acknowledged)."""
    job_id = str(payload.get("job_id") or "")
    status = payload.get("status")
    if not job_id or db.rbd_jobs.find_one({"_id": job_id}, {"_id": 1}) is None:
        return False
    if status == "running":
        res = db.rbd_jobs.update_one(
            {"_id": job_id, "status": "queued"},
            {"$set": {"status": "running", "started_at": _aware(payload.get("started_at")) or _now()}},
        )
        return bool(getattr(res, "modified_count", 0))
    if status == "done":
        result = payload.get("result")
        if not isinstance(result, dict):
            return finish(db, job_id, "failed", error=FAILED_ERROR, started_at=payload.get("started_at"))
        return finish(db, job_id, "done", result=result, timings=payload.get("timings"),
                      started_at=payload.get("started_at"))
    if status == "failed":
        return finish(db, job_id, "failed", error=str(payload.get("error") or FAILED_ERROR),
                      timings=payload.get("timings"), started_at=payload.get("started_at"))
    raise ValueError(f"Unknown job status {status!r}.")


# ---- Running a simulation ----------------------------------------------------------

def _result_payload(result: dict, computed_at, entitled: bool) -> dict:
    return {**result, "cached": False, "computed_at": computed_at, "can_recompute": entitled}


def availability_out(sim: Optional[dict], free: dict, *, status: dict, state: Optional[dict],
                     entitled: bool, graph: dict) -> dict:
    """The availability payload the app and MCP get (#154): the simulation's
    result (``sim``: a fresh run, a finished job or the saved one) with the
    exact figures beside it, or the exact figures alone (``free``), plus the
    simulation's ``status``, the current state it ran from, what the caller
    may do, the common-cause note (#185) and RePyability's reasons in
    Reliafy's words (#186)."""
    from backend.services import rbd_analysis, rbd_policies

    if sim is not None:
        out = {**sim, "exact": (free or {}).get("exact"), "has_simulation": True}
    else:
        out = {**(free or {}), "has_simulation": False, "cached": False, "computed_at": None}
    out.update(
        simulation_status=status,
        current_state=state,
        # ``can_simulate`` / ``can_recompute`` let the UI offer "Run simulation"
        # and "Re-run" to entitled users, and the Pro offer to the rest.
        can_simulate=entitled,
        can_recompute=entitled,
    )
    common_cause = rbd_policies.common_cause_note(graph, out)
    if common_cause is not None:
        out["common_cause"] = common_cause
    return rbd_analysis.plain_reasons(out)


def job_payload(job: dict, entitled: bool) -> dict:
    """A finished job's result as the whole availability payload (see
    :func:`availability_out`)."""
    context = job.get("context") or {}
    sim = _result_payload(job.get("result") or {}, job.get("computed_at"), entitled)
    graph = (job.get("request") or {}).get("graph") or {}
    state = ((job.get("request") or {}).get("options") or {}).get("state")
    return availability_out(sim, {"exact": context.get("exact")}, status={"state": "done"},
                            state=state, entitled=entitled, graph=graph)


def view(db, job: dict, entitled: bool) -> dict:
    """A job as the app and MCP see it (owner-only; checked by the caller)."""
    out = {
        "job_id": job["_id"],
        "kind": job.get("kind"),
        "rbd_id": job.get("rbd_id"),
        "status": job.get("status"),
        "quick": bool(job.get("quick")),
        "created_at": _iso(job.get("created_at")),
        "started_at": _iso(job.get("started_at")),
        "finished_at": _iso(job.get("finished_at")),
        "queue_position": queue_position(db, job),
    }
    if job.get("status") == "done":
        if job.get("kind") in (KIND_SENSITIVITY, KIND_INTERVALS):
            out["result"] = {**(job.get("result") or {}), "job_id": job["_id"]}
        else:
            out["result"] = job_payload(job, entitled)
    elif job.get("status") == "failed":
        out["error"] = job.get("error") or FAILED_ERROR
    return out


def _job_accepted(db, job: dict) -> tuple[int, dict]:
    return 202, {
        "kind": "repairable",
        "job": True,
        "job_id": job["_id"],
        "status": job["status"],
        "quick": bool(job.get("quick")),
        "queue_position": queue_position(db, job),
    }


def run_availability(
    db,
    *,
    uid: str,
    graph: dict,
    cache_key: str,
    t_max,
    resolve_owners,
    rbd_id: Optional[str],
    store: bool,
    entitled: bool,
    quick: bool,
    force: bool = False,
    state: Optional[dict] = None,
    context: Optional[dict] = None,
) -> tuple[int, dict]:
    """Run (or queue) an availability simulation the caller is allowed to run.
    ``quick`` is a free, time-capped run counted against the daily cap;
    ``state`` a canonical current state to start from; ``context`` what a
    finished job is shown with (see :func:`job_payload`).

    Returns ``(status, payload)``: 200 with the simulation's result
    (in-process, or a finished identical job), 202 with a job to poll, 429
    when the free cap is used up, 503 when the queue can't take the job."""
    options = {**(free_sims.options() if quick else {}), **({"state": state} if state else {})}
    if state:
        # The same diagram from another state is another calculation.
        cache_key = f"{cache_key}|state:{json.dumps(state, sort_keys=True, default=float)}"
    request = (
        compute_core.availability_request(graph, t_simulation=t_max, **options)
        if compute_queue.configured() else None
    )

    if request is not None:
        # Same inputs already queued or running: share that job. A finished
        # one is served too, unless the user asked to re-run.
        existing = find_reusable(db, uid, cache_key, quick, include_done=not force and not quick)
        if existing is not None:
            if existing["status"] == "done":
                return 200, _result_payload(existing.get("result") or {},
                                            existing.get("computed_at"), entitled)
            return _job_accepted(db, existing)

    free_day = None
    if quick:
        free_day = free_sims.consume(db, uid)
        if free_day is None:
            return 429, {"detail": free_sims.cap_message(), "code": "free_sim_cap", "upgrade": True,
                         "quick": free_sims.summary(db, uid)}

    if request is None:
        # In-process: no queue configured (self-hosted, dev, tests), or a
        # diagram that needs saved models re-fitted (see compute_core).
        try:
            result = rbds_service.analyze_graph(db, graph, resolve_owners, t_max=t_max, **options)
        except Exception:
            free_sims.refund(db, uid, free_day)
            raise
        computed_at = None
        if store and rbd_id:
            computed_at = rbds_service.save_availability_result(db, rbd_id, cache_key, result, uid,
                                                                resolve_owners)
        payload = _result_payload(result, computed_at, entitled)
        if quick:
            payload["free_sims"] = free_sims.summary(db, uid)
        return 200, payload

    job = create(db, uid=uid, kind=KIND_AVAILABILITY, request=request, cache_key=cache_key,
                 rbd_id=rbd_id, quick=quick, store=store, free_sim_day=free_day, context=context,
                 owners=resolve_owners)
    try:
        compute_queue.enqueue(job["_id"], KIND_AVAILABILITY, request)
    except compute_queue.QueueError as exc:
        finish(db, job["_id"], "failed", error=str(exc) or QUEUE_UNAVAILABLE)
        return 503, {"detail": QUEUE_UNAVAILABLE, "code": "compute_unavailable"}
    status, payload = _job_accepted(db, job)
    if quick:
        payload["free_sims"] = free_sims.summary(db, uid)
    return status, payload


# ---- What to improve (#225) ------------------------------------------------------

def run_sensitivity(db, *, uid: str, graph: dict, options: dict, cache_key: str, rbd_id: Optional[str],
                    resolve_model, resolve_owners=None) -> tuple[int, dict]:
    """Run (or queue) a what-to-improve analysis the caller may run.
    ``options`` are :func:`rbd_sensitivity.options`'; ``resolve_model``
    resolves saved models in-process. Returns ``(status, payload)``: 200 with
    the result (in-process, or a finished identical job), 202 with a job to
    poll, 503 when the queue can't take it. The result is never stored on the
    diagram."""
    from backend.services import rbd_sensitivity

    request = (compute_core.sensitivity_request(graph, **options)
               if compute_queue.configured() else None)
    if request is None:
        # In-process: no queue configured (self-hosted, dev, tests), or a
        # diagram that needs saved models re-fitted (see compute_core).
        return 200, rbd_sensitivity.analyze_sensitivity(graph, resolve_model, simulate=True, **options)
    existing = find_reusable(db, uid, cache_key, False, include_done=True)
    if existing is not None:
        if existing["status"] == "done":
            return 200, {**(existing.get("result") or {}), "job_id": existing["_id"]}
        return 202, _sensitivity_accepted(db, existing)
    job = create(db, uid=uid, kind=KIND_SENSITIVITY, request=request, cache_key=cache_key, rbd_id=rbd_id,
                 quick=False, store=False, owners=resolve_owners)
    try:
        compute_queue.enqueue(job["_id"], KIND_SENSITIVITY, request)
    except compute_queue.QueueError as exc:
        finish(db, job["_id"], "failed", error=str(exc) or QUEUE_UNAVAILABLE)
        return 503, {"detail": QUEUE_UNAVAILABLE, "code": "compute_unavailable"}
    return 202, _sensitivity_accepted(db, job)


def _sensitivity_accepted(db, job: dict) -> dict:
    return {
        "kind": "sensitivity",
        "status": job.get("status"),
        "job": {"job_id": job["_id"], "status": job["status"], "queue_position": queue_position(db, job),
                "kind": KIND_SENSITIVITY},
    }


# ---- Maintenance and proof-test intervals (#228) --------------------------------

def run_intervals(db, *, uid: str, graph: dict, options: dict, cache_key: str, rbd_id: Optional[str],
                  resolve_model, resolve_owners=None) -> tuple[int, dict]:
    """Run (or queue) an interval optimisation (``options`` as
    :func:`rbd_intervals.options` gives them). Returns ``(status,
    payload)``: 200 with the result (in-process, or a finished identical
    job), 202 with ``job`` to poll, 503 when the queue can't take it. Never
    stored on the diagram."""
    from backend.services import rbd_intervals

    request = (compute_core.intervals_request(graph, **options)
               if compute_queue.configured() else None)
    if request is None:
        return 200, rbd_intervals.optimise(graph, resolve_model, **options)
    existing = find_reusable(db, uid, cache_key, False, include_done=True)
    if existing is not None:
        if existing["status"] == "done":
            return 200, {**(existing.get("result") or {}), "job_id": existing["_id"]}
        return 202, _intervals_accepted(db, existing)
    job = create(db, uid=uid, kind=KIND_INTERVALS, request=request, cache_key=cache_key, rbd_id=rbd_id,
                 quick=False, store=False, owners=resolve_owners)
    try:
        compute_queue.enqueue(job["_id"], KIND_INTERVALS, request)
    except compute_queue.QueueError as exc:
        finish(db, job["_id"], "failed", error=str(exc) or QUEUE_UNAVAILABLE)
        return 503, {"detail": QUEUE_UNAVAILABLE, "code": "compute_unavailable"}
    return 202, _intervals_accepted(db, job)


def _intervals_accepted(db, job: dict) -> dict:
    return {
        "kind": "maintenance_intervals",
        "status": "pending",
        "job": {"job_id": job["_id"], "status": job["status"], "queue_position": queue_position(db, job),
                "kind": KIND_INTERVALS},
    }
