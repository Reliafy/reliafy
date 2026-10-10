"""Simulation run history (#112): a diagram's availability simulations, read
from the job records (:mod:`backend.services.rbd_jobs`).

Every availability simulation is a record in ``rbd_jobs``: a job the
calculation service ran, or (with no queue configured, or for a diagram whose
saved models must be re-fitted) a run in the web app's own process, recorded
done at once. A record keeps the self-contained request (the diagram and the
run's options), the free exact figures it is shown with, the result (with its
bands and precision) and its timings, for ``RBD_RUN_TTL_DAYS`` after it
finishes (``RBD_JOB_TTL_DAYS`` unless set).

Fields added by #112 / #286, on records from then on only (older ones lack
them and read as "not recorded"):

* ``run_by`` ``{uid, name}`` and ``trigger`` ``{surface: app | mcp, client}``:
  who ran it, and from the app or which MCP connector;
* ``machine`` (``compute`` or ``web``) and ``quote``: the runtime predicted
  before it ran (:mod:`backend.services.runtime_quote`);
* ``runtime_s`` (the calculation's own seconds) and ``engines`` (the
  RePyability and SurPyval versions it ran on).

Who sees a run: the user who started it; on a team's diagram, every member
who can read the diagram.
"""

from __future__ import annotations

import csv
import io
import json
import logging
import time
from datetime import datetime, timedelta, timezone
from typing import Optional

from backend import config
from backend.services import runtime_quote

logger = logging.getLogger(__name__)

KIND = "availability"
MAX_COMPARE = 6
DEFAULT_LIMIT = 50
# A queued job of another kind, or from before quotes, counts this long.
_UNQUOTED_JOB_S = 20.0


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _aware(dt):
    from backend.services.rbd_jobs import _aware as aware

    return aware(dt)


def _iso(dt) -> Optional[str]:
    dt = _aware(dt)
    return dt.isoformat() if dt else None


def ttl_days() -> int:
    """How long finished runs are kept."""
    return int(getattr(config, "RBD_RUN_TTL_DAYS", None) or config.RBD_JOB_TTL_DAYS)


# ---- What a new run records ------------------------------------------------------------

def run_info(ctx, surface: str = "app") -> dict:
    """Who is running a simulation, and from where: ``{run_by, trigger}``."""
    from backend.services import usage as usage_service
    from backend.services.access import editor_of

    trigger = {"surface": "mcp" if surface == "mcp" else "app"}
    if trigger["surface"] == "mcp":
        trigger["client"] = usage_service.client_of(ctx.user or {})
    return {"run_by": editor_of(ctx), "trigger": trigger}


def _compact_quote(quote: Optional[dict]) -> Optional[dict]:
    if not quote or not quote.get("available"):
        return None
    keep = ("median_s", "p90_s", "cap_s", "capped", "mode", "replications", "machine", "factor", "text")
    return {k: quote.get(k) for k in keep}


def quote_request(db, request: dict, in_process: bool) -> Optional[dict]:
    """The quote for a request (``{graph, options}``) on the machine it will
    run on; None when there's none (never raises)."""
    try:
        machine = runtime_quote.machine_of(in_process)
        return _compact_quote(runtime_quote.quote_runtime(
            request.get("graph") or {}, request.get("options") or {}, machine=machine,
            factor=runtime_quote.current_factor(db, machine)))
    except Exception:  # noqa: BLE001 - a quote never stops a run
        logger.warning("Couldn't quote a run", exc_info=True)
        return None


def new_fields(db, request: dict, info: Optional[dict], in_process: bool) -> dict:
    """The #112 / #286 fields of a new availability record."""
    machine = runtime_quote.machine_of(in_process)
    out = {"machine": machine, "quote": quote_request(db, request, in_process),
           "expires_at": _now() + timedelta(days=ttl_days())}
    if info:
        out.update({k: info[k] for k in ("run_by", "trigger") if k in info})
    return out


def engines_here(result: Optional[dict] = None) -> dict:
    """The engine versions of a run in this process."""
    from backend.services.rbd_analysis import _repyability_version

    try:
        import surpyval

        sv_version = getattr(surpyval, "__version__", None)
    except Exception:  # noqa: BLE001
        sv_version = None
    return {"repyability": (result or {}).get("repyability_version") or _repyability_version(),
            "surpyval": sv_version}


def on_finished(db, job: dict, result: dict, timings: Optional[dict], engines: Optional[dict]) -> None:
    """A finished availability job: its runtime and engines, kept TTL days,
    and its time logged against the quote's model. Never raises."""
    try:
        runtime = (timings or {}).get("compute_s")
        engines = {k: v for k, v in (engines or {}).items() if v} or None
        if engines and not engines.get("repyability") and result.get("repyability_version"):
            engines["repyability"] = result["repyability_version"]
        db.rbd_jobs.update_one({"_id": job["_id"]}, {"$set": {
            "runtime_s": runtime, "engines": engines or {"repyability": result.get("repyability_version")},
            "expires_at": _now() + timedelta(days=ttl_days()),
        }})
        if job.get("machine"):
            request = job.get("request") or {}
            runtime_quote.log_run(db, machine=job["machine"], graph=request.get("graph") or {},
                                  options=request.get("options") or {},
                                  replications=result.get("n_simulations"), actual_s=runtime,
                                  quote=job.get("quote"))
    except Exception:  # noqa: BLE001 - the result itself already stands
        logger.warning("Couldn't record job %s's run details", job.get("_id"), exc_info=True)


def record_in_process(db, *, uid: str, graph: dict, options: dict, cache_key: str, rbd_id: Optional[str],
                      quick: bool, store: bool, result: dict, runtime_s: float, computed_at,
                      context: Optional[dict], owners, info: Optional[dict]) -> Optional[str]:
    """Record a run made in the web app's own process as a finished job, so
    it is in the history too, and log its time. Returns its id (None if it
    couldn't be recorded; the run's answer stands either way)."""
    from backend.services import compute_core, rbd_jobs

    try:
        request = {"graph": compute_core.inline_graph(graph),
                   "options": compute_core.availability_options(**options)}
        job = rbd_jobs.create(db, uid=uid, kind=KIND, request=request, cache_key=cache_key, rbd_id=rbd_id,
                              quick=quick, store=store, context=context, owners=owners,
                              extra=new_fields(db, request, info, in_process=True))
        now = _now()
        db.rbd_jobs.update_one({"_id": job["_id"]}, {"$set": {
            "status": "done", "started_at": job["created_at"], "finished_at": now,
            "result": json.loads(json.dumps(result or {}, default=float)), "computed_at": computed_at,
            "timings": {"compute_s": round(float(runtime_s), 3)}, "in_process": True,
        }})
        job = db.rbd_jobs.find_one({"_id": job["_id"]})
        on_finished(db, job, result or {}, job.get("timings"), engines_here(result))
        return job["_id"]
    except Exception:  # noqa: BLE001
        logger.warning("Couldn't record an in-process run", exc_info=True)
        return None


def timed(fn, *args, **kwargs):
    """``(result, seconds)``."""
    t0 = time.perf_counter()
    out = fn(*args, **kwargs)
    return out, time.perf_counter() - t0


# ---- Queue status ----------------------------------------------------------------------

def progress(db, job: dict) -> dict:
    """A queued or running job's quote and, while queued, roughly how long
    until it starts: the jobs ahead's remaining quoted medians, run
    ``COMPUTE_PARALLEL_JOBS`` at a time."""
    from backend.services import rbd_jobs

    quote = job.get("quote")
    out: dict = {"quote": {k: quote.get(k) for k in ("median_s", "p90_s", "text")} if quote else None}
    if job.get("status") != "queued":
        return out
    now = _now()
    ahead = db.rbd_jobs.find(
        {"status": {"$in": list(rbd_jobs.ACTIVE)},
         "created_at": {"$lt": job["created_at"], "$gte": rbd_jobs._stale_before()}},
        {"quote": 1, "status": 1, "started_at": 1},
    ).limit(200)
    left = 0.0
    n = 0
    for other in ahead:
        n += 1
        median = ((other.get("quote") or {}).get("median_s")) or _UNQUOTED_JOB_S
        if other.get("status") == "running" and other.get("started_at"):
            median = max(median - (now - _aware(other["started_at"])).total_seconds(), 0.0)
        left += float(median)
    if n:
        wait = left / max(int(getattr(config, "COMPUTE_PARALLEL_JOBS", 1) or 1), 1)
        out.update(wait_s=wait, wait_text=runtime_quote.wait_text(wait))
    else:
        out.update(wait_s=0.0, wait_text=None)
    return out


# ---- Who sees what -----------------------------------------------------------------------

def _team_diagram(db, ctx, rbd_id: Optional[str]) -> Optional[dict]:
    """The diagram, when it is a team's and the caller can read it."""
    from backend.services import access as access_service

    if not rbd_id:
        return None
    doc, _ = access_service.readable_raw(db, "rbds", rbd_id, ctx)
    if doc is not None and access_service.is_team_owner(doc.get("owner_id")):
        return doc
    return None


def can_see(db, ctx, job: Optional[dict]) -> bool:
    if job is None or job.get("kind") != KIND:
        return False
    if job.get("uid") == ctx.uid:
        return True
    return _team_diagram(db, ctx, job.get("rbd_id")) is not None


def get_visible(db, ctx, run_id: str) -> Optional[dict]:
    from backend.services import rbd_jobs

    job = rbd_jobs.get(db, run_id)
    return job if can_see(db, ctx, job) else None


# ---- Views ---------------------------------------------------------------------------------

_VIA = {"app": "App"}


def _via(job: dict) -> dict:
    trigger = job.get("trigger") or {}
    surface = trigger.get("surface")
    if surface == "mcp":
        client = trigger.get("client")
        named = client and client not in ("unknown", "other")
        label = f"{client} (MCP)" if named else "An MCP connector"
    elif surface:
        label = _VIA.get(surface, surface)
    else:
        label = None
    return {"surface": surface, "client": trigger.get("client"), "label": label}


def _method(job: dict) -> dict:
    result = job.get("result") or {}
    options = (job.get("request") or {}).get("options") or {}
    mode = (result.get("precision") or {}).get("mode")
    if mode is None:
        mode = "quick" if (job.get("quick") or options.get("time_budget_s")) else (
            "fixed" if options.get("n_simulations") else "tolerance")
    label = {"quick": "Quick estimate", "fixed": "Fixed replications", "tolerance": "Full"}.get(mode, "Full")
    from_now = bool(options.get("state"))
    return {"key": mode, "label": label + (", from now" if from_now else ""), "from_now": from_now}


def _runtime(job: dict) -> Optional[float]:
    if job.get("runtime_s") is not None:
        return float(job["runtime_s"])
    secs = (job.get("timings") or {}).get("compute_s")
    if secs is not None:
        return float(secs)
    started, finished = _aware(job.get("started_at")), _aware(job.get("finished_at"))
    if started and finished:
        return max((finished - started).total_seconds(), 0.0)
    return None


def _headline(result: dict) -> Optional[dict]:
    precision = result.get("precision") or {}
    value = precision.get("window_availability")
    if value is None:
        return None
    return {"value": value, "lower": precision.get("lower"), "upper": precision.get("upper"),
            "confidence": precision.get("confidence")}


def summary(job: dict, ctx_uid: str, names: Optional[dict] = None) -> dict:
    """One row of the runs list."""
    result = job.get("result") or {}
    request = job.get("request") or {}
    run_by = job.get("run_by") or {}
    mine = job.get("uid") == ctx_uid
    quote = job.get("quote")
    out = {
        "run_id": job["_id"],
        "rbd_id": job.get("rbd_id"),
        "rbd_name": (names or {}).get(job.get("rbd_id")),
        "status": job.get("status"),
        "created_at": _iso(job.get("created_at")),
        "started_at": _iso(job.get("started_at")),
        "finished_at": _iso(job.get("finished_at")),
        "by": {"you": mine, "name": run_by.get("name") if not mine else None},
        "via": _via(job),
        "method": _method(job),
        "where": {"compute": "Calculation service", "web": "In the app"}.get(
            job.get("machine") or ("web" if job.get("in_process") else "compute")),
        "runtime_s": _runtime(job),
        "replications": result.get("n_simulations"),
        "window": result.get("t_simulation") or (request.get("options") or {}).get("t_simulation"),
        "unit": (request.get("graph") or {}).get("unit") or result.get("unit") or "",
        "availability": _headline(result) if job.get("status") == "done" else None,
        "quote": {k: quote.get(k) for k in ("median_s", "p90_s", "text")} if quote else None,
    }
    if job.get("status") == "failed":
        out["error"] = job.get("error")
    return out


def _names(db, rbd_ids) -> dict:
    ids = [i for i in set(rbd_ids) if i]
    if not ids:
        return {}
    return {d["_id"]: d.get("name") for d in db.rbds.find({"_id": {"$in": ids}}, {"name": 1})}


def list_runs(db, ctx, rbd_id: Optional[str] = None, limit: int = DEFAULT_LIMIT,
              before: Optional[str] = None) -> dict:
    """The caller's runs, newest first; with ``rbd_id``, that diagram's (on a
    team's diagram, every member's). ``before`` (an ISO time) pages back."""
    from backend.services import rbd_jobs

    query: dict = {"kind": KIND}
    if rbd_id:
        query["rbd_id"] = rbd_id
        if _team_diagram(db, ctx, rbd_id) is None:
            query["uid"] = ctx.uid
    else:
        query["uid"] = ctx.uid
    if before:
        try:
            query["created_at"] = {"$lt": datetime.fromisoformat(before)}
        except ValueError:
            pass
    limit = max(1, min(int(limit or DEFAULT_LIMIT), 200))
    jobs = [rbd_jobs._expire_if_stale(db, j)
            for j in db.rbd_jobs.find(query, {"context": 0}).sort("created_at", -1).limit(limit + 1)]
    more = len(jobs) > limit
    jobs = jobs[:limit]
    names = _names(db, [j.get("rbd_id") for j in jobs])
    # The diagrams this list can be filtered by: the caller's runs' diagrams.
    return {
        "runs": [summary(j, ctx.uid, names) for j in jobs],
        "more": more,
        "kept_days": ttl_days(),
    }


def diagrams(db, ctx) -> list[dict]:
    """The diagrams the caller has runs of, for the filter."""
    ids = db.rbd_jobs.distinct("rbd_id", {"uid": ctx.uid, "kind": KIND})
    names = _names(db, ids)
    return sorted(({"rbd_id": i, "name": names.get(i) or "Deleted diagram"} for i in ids if i),
                  key=lambda d: (d["name"] or "").lower())


def _inputs(db, job: dict) -> dict:
    from backend.services import rbds as rbds_service

    request = job.get("request") or {}
    graph = request.get("graph") or {}
    options = request.get("options") or {}
    result = job.get("result") or {}
    blocks = sum(1 for n in graph.get("nodes") or [] if n.get("type") not in ("input", "output"))
    changed = None
    if job.get("rbd_id"):
        doc = db.rbds.find_one({"_id": job["rbd_id"]}, {"graph": 1})
        if doc is not None:
            def canon(g):
                return json.dumps(rbds_service.canonical_analysis_graph(g), sort_keys=True, default=str)
            try:
                changed = canon(graph) != canon(doc.get("graph") or {})
            except Exception:  # noqa: BLE001
                changed = None
    return {
        "blocks": blocks,
        "unit": graph.get("unit") or "",
        "window": result.get("t_simulation") or options.get("t_simulation"),
        "window_chosen": options.get("t_simulation") is not None,
        "window_shortened": bool(result.get("horizon_shortened")),
        "seed": result.get("seed") if result.get("seed") is not None else options.get("seed"),
        "replications": result.get("n_simulations"),
        "time_budget_s": options.get("time_budget_s"),
        "current_state": options.get("state"),
        "diagram_changed_since": changed,
    }


def detail(db, ctx, job: dict, entitled: bool) -> dict:
    """A run in full: its row, the stored results (the whole availability
    payload, bands and all) once done, the inputs and engine versions it ran
    on, and the precision it achieved."""
    from backend.services import rbd_jobs

    names = _names(db, [job.get("rbd_id")])
    out = summary(job, ctx.uid, names)
    result = job.get("result") or {}
    out["inputs"] = _inputs(db, job)
    engines = job.get("engines") or {}
    out["engines"] = {"repyability": engines.get("repyability") or result.get("repyability_version"),
                      "surpyval": engines.get("surpyval")}
    out["precision"] = result.get("precision")
    out["quote_full"] = job.get("quote")
    if job.get("status") == "done":
        out["result"] = rbd_jobs.job_payload(job, entitled)
    elif job.get("status") in rbd_jobs.ACTIVE:
        out.update(progress(db, job))
        out["queue_position"] = rbd_jobs.queue_position(db, job)
    return out


def compare(db, ctx, run_ids: list[str]) -> dict:
    """Several finished runs side by side: each one's row with its curve
    (A(t) and its band), long-run availability and window mean."""
    runs = []
    missing = []
    for rid in run_ids[:MAX_COMPARE]:
        job = get_visible(db, ctx, rid)
        if job is None or job.get("status") != "done":
            missing.append(rid)
            continue
        result = job.get("result") or {}
        row = summary(job, ctx.uid, _names(db, [job.get("rbd_id")]))
        curve = result.get("curve") or {}
        row.update(
            curve={k: curve.get(k) for k in ("t", "availability", "lower", "upper", "confidence")} if curve else None,
            steady_state_availability=result.get("steady_state_availability"),
            precision=result.get("precision"),
        )
        runs.append(row)
    return {"runs": runs, "missing": missing}


# ---- Export --------------------------------------------------------------------------------

def export_json(view: dict) -> str:
    return json.dumps(view, indent=2, default=str)


def export_csv(view: dict) -> str:
    """A run as one tidy table: ``quantity, block, time, value, lower,
    upper`` — the headline figures, A(t) with its band, and each block's
    share of the downtime."""
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["quantity", "block", "time", "value", "lower", "upper"])
    result = view.get("result") or {}
    precision = result.get("precision") or {}
    w.writerow(["window_availability", "", result.get("t_simulation"), precision.get("window_availability"),
                precision.get("lower"), precision.get("upper")])
    for key in ("steady_state_availability", "mean_up_time", "mean_down_time", "failure_frequency"):
        if result.get(key) is not None:
            w.writerow([key, "", "", result.get(key), "", ""])
    curve = result.get("curve") or {}
    t, a = curve.get("t") or [], curve.get("availability") or []
    lo, hi = curve.get("lower") or [], curve.get("upper") or []
    for i, ti in enumerate(t):
        w.writerow(["availability_at_t", "", ti, a[i] if i < len(a) else "",
                    lo[i] if i < len(lo) else "", hi[i] if i < len(hi) else ""])
    for row in result.get("per_node") or []:
        w.writerow(["downtime_share", row.get("label") or row.get("id"), "", row.get("share"), "", ""])
    return buf.getvalue()


def ensure_indexes(db) -> None:
    db.rbd_jobs.create_index([("rbd_id", 1), ("kind", 1), ("created_at", -1)])
    db.rbd_jobs.create_index([("uid", 1), ("kind", 1), ("created_at", -1)])
    runtime_quote.ensure_indexes(db)
