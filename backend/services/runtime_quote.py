"""How long will a repairable diagram's simulation take (#286)?

A run's wall time is a survival time, and a log-normal accelerated failure
time model fitted to timed runs predicts it from three things a quote can see
before anything runs (``tools/quote_bench``, whose pilot chose the form):

* **n**, the replications the run will make;
* **e**, the block failures one replication expects: each block's units times
  the window over its mean life;
* **b**, the blocks.

``ln T = intercept + a·ln n + c·ln(1 + e) + d·ln b``, with log-normal spread
``sigma``. The coefficients live in ``runtime_quote.json`` beside this
module. The quote is the median and the 90th percentile of that log-normal
(SurPyval's ``LogNormal``), scaled by the machine's factor and held to the
run's own time limit where it has one: a run to the precision target stops
at its time budget, and a quick run at its few seconds.

Machine factors. The pilot was timed on a dev laptop, so each machine
Reliafy simulates on gets one scalar (``compute``: the calculation service;
``web``: a run in the web app's own process), starting at 1. Every finished
run logs its prediction against its actual time (``rbd_runtime_log``:
features and seconds only, nothing that identifies a user), and
:func:`refit_factor` fits a log-normal to the actual-over-predicted ratios
with SurPyval, the spread held at the model's; its median is the new factor.
A refit is stored in ``runtime_quote_factors`` and wins over the JSON.
"""

from __future__ import annotations

import json
import math
import os
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from typing import Optional

from backend import config

# Blocks that hold units the simulation fails and repairs.
_BLOCK_TYPES = ("component", "parallel", "standby")
# Blocks the calculation service can't run, and a quote can't see into.
_OPAQUE_TYPES = ("subsystem", "loadshare")
# The fewest observed runs a machine factor is refitted from.
MIN_REFIT_RUNS = 10
# How long the calibration log is kept.
LOG_TTL_DAYS = 365

UNAVAILABLE_OPAQUE = "This diagram has sub-system or load-sharing blocks, so how long it takes can't be estimated."
UNAVAILABLE_MEAN = "Some blocks' mean life isn't known before the run, so how long it takes can't be estimated."
UNAVAILABLE_EMPTY = "This diagram has no blocks to simulate yet."


@lru_cache(maxsize=1)
def coefficients() -> dict:
    """The fitted model (``runtime_quote.json``)."""
    with open(os.path.join(os.path.dirname(__file__), "runtime_quote.json"), encoding="utf-8") as fh:
        return json.load(fh)


def machine_of(in_process: bool) -> str:
    """The machine type a run is on: the calculation service's
    (``COMPUTE_MACHINE``), or the web app's own process."""
    return "web" if in_process else (getattr(config, "COMPUTE_MACHINE", None) or "compute")


def current_factor(db, machine: str) -> float:
    """The machine's factor: a stored refit, else the JSON's (else 1)."""
    if db is not None:
        try:
            doc = db.runtime_quote_factors.find_one({"_id": machine})
        except Exception:  # noqa: BLE001 - a quote never fails on the store
            doc = None
        if doc and doc.get("factor"):
            return float(doc["factor"])
    return float((coefficients().get("machine_factors") or {}).get(machine, 1.0))


# ---- Features -------------------------------------------------------------------

def _units(node: dict) -> int:
    data = node.get("data") or {}
    try:
        if node.get("type") == "parallel":
            return max(int(data.get("n") or 1), 1)
        if node.get("type") == "standby":
            return 1 + max(int(data.get("spares") or 0), 0)
    except (TypeError, ValueError):
        return 1
    return 1


def _window(graph: dict, options: dict) -> tuple[float, bool]:
    """``(window, chosen)``: the window the run simulates, as the analysis
    sizes it, and whether the user chose it."""
    from backend.services import rbd_analysis

    chosen, _ = rbd_analysis.chosen_horizon(options.get("t_simulation"), graph)
    if chosen is not None:
        return float(chosen), True
    return float(rbd_analysis._availability_horizon(graph, options.get("state"))), False


def features(graph: dict, options: Optional[dict] = None) -> dict:
    """What the quote sees: ``{"available": True, "blocks", "events_per_replication",
    "window", "chosen_window"}``, or ``{"available": False, "reason"}`` when a
    block's mean life isn't known before the run (the replications are
    planned by the caller)."""
    from backend.services import rbd_analysis

    options = options or {}
    nodes = [n for n in (graph or {}).get("nodes") or [] if isinstance(n, dict)]
    if any(n.get("type") in _OPAQUE_TYPES for n in nodes):
        return {"available": False, "reason": UNAVAILABLE_OPAQUE}
    blocks = [n for n in nodes if n.get("type") in _BLOCK_TYPES and not (n.get("data") or {}).get("repeat_of")]
    if not blocks:
        return {"available": False, "reason": UNAVAILABLE_EMPTY}
    means = []
    for n in blocks:
        mean = rbd_analysis._spec_mean((n.get("data") or {}).get("model"))
        if mean is None:
            return {"available": False, "reason": UNAVAILABLE_MEAN}
        means.append((n, mean))
    try:
        window, chosen = _window(graph, options)
    except Exception:  # noqa: BLE001 - the run itself reports a broken diagram
        return {"available": False, "reason": UNAVAILABLE_MEAN}
    events = sum(_units(n) * window / mean for n, mean in means)
    return {"available": True, "blocks": len(blocks), "events_per_replication": float(events),
            "window": window, "chosen_window": chosen}


def log_median(replications: float, events: float, blocks: float) -> float:
    """The model's ln median runtime in seconds on the machine it was fitted
    on (factor 1): its linear predictor."""
    c = coefficients()
    k = c["coefficients"]
    return (c["intercept"] + k["log_replications"] * math.log(max(float(replications), 1.0))
            + k["log1p_events_per_replication"] * math.log1p(max(float(events), 0.0))
            + k["log_blocks"] * math.log(max(float(blocks), 1.0)))


def _distribution(log_med: float, factor: float):
    """The runtime's log-normal (SurPyval's), the machine factor applied."""
    import surpyval as sv

    return sv.LogNormal.from_params([log_med + math.log(max(factor, 1e-9)), float(coefficients()["sigma"])])


def _quantiles(log_med: float, factor: float) -> tuple[float, float]:
    import numpy as np

    q = np.asarray(_distribution(log_med, factor).qf([0.5, 0.9]), dtype=float).reshape(-1)
    return float(q[0]), float(q[1])


# ---- The quote --------------------------------------------------------------------------

def _plan(options: dict, chosen_window: bool, events: float, blocks: int, factor: float):
    """``(replications, cap_s, mode)``: what the run will do, as
    :func:`rbd_analysis.analyze_availability` plans it."""
    from backend.services import rbd_analysis as ra

    if options.get("time_budget_s"):
        n = int(options.get("max_replications") or ra._AVAIL_SIMS)
        return n, float(options["time_budget_s"]), "quick"
    if options.get("n_simulations"):
        return int(options["n_simulations"]), None, "fixed"
    # A run to the precision target: at most _AVAIL_SIMS replications within
    # the time budget. A window the user chose keeps a floor of
    # _AVAIL_MIN_SIMS replications even past the budget, up to a longer limit.
    if chosen_window:
        floor = int(ra._AVAIL_MIN_SIMS)
        median_floor, _ = _quantiles(log_median(floor, events, blocks), factor)
        if median_floor > ra._AVAIL_TIME_BUDGET:
            return floor, float(ra._AVAIL_USER_TIME_LIMIT), "tolerance"
    return int(ra._AVAIL_SIMS), float(ra._AVAIL_TIME_BUDGET), "tolerance"


def quote_runtime(graph: dict, options: Optional[dict] = None, *, machine: str = "compute",
                  factor: Optional[float] = None) -> dict:
    """How long a simulation of ``graph`` with ``options`` (those of
    :func:`compute_core.availability_options`) should take: ``median_s``
    (the estimate) and ``p90_s`` (the ceiling), each held to the run's time
    limit (``cap_s``), with ``text`` in words ("about 15 s, up to 40 s").
    ``factor`` defaults to the JSON's for ``machine`` (callers with a
    database pass :func:`current_factor`). ``{"available": False, "reason"}``
    when a block's mean life isn't known before the run."""
    options = options or {}
    f = features(graph, options)
    if not f["available"]:
        return f
    if factor is None:
        factor = float((coefficients().get("machine_factors") or {}).get(machine, 1.0))
    n, cap, mode = _plan(options, f["chosen_window"], f["events_per_replication"], f["blocks"], factor)
    log_med = log_median(n, f["events_per_replication"], f["blocks"])
    median, p90 = _quantiles(log_med, factor)
    capped = cap is not None and median >= cap
    if cap is not None:
        median, p90 = min(median, cap), min(p90, cap)
    return {
        "available": True,
        "median_s": median,
        "p90_s": p90,
        "cap_s": cap,
        "capped": bool(capped),
        "mode": mode,
        "replications": n,
        "events_per_replication": f["events_per_replication"],
        "blocks": f["blocks"],
        "window": f["window"],
        "machine": machine,
        "factor": factor,
        "text": quote_text(median, p90, capped),
    }


def seconds_words(s: float) -> str:
    """"under a second", "8 s", "about 2 minutes", "about 1.5 hours"."""
    s = float(s)
    if s < 1:
        return "under a second"
    if s < 59.5:
        return f"{int(round(s))} s"
    minutes = s / 60
    if minutes < 59.5:
        m = int(round(minutes))
        return "a minute" if m == 1 else f"{m} minutes"
    hours = minutes / 60
    h = round(hours, 1)
    return "an hour" if h == 1 else f"{h:g} hours"


def quote_text(median: float, p90: float, capped: bool = False) -> str:
    """"about 15 s, up to 40 s"; "about 20 s (its time limit)" when the run
    will stop at its limit."""
    if capped:
        return f"about {seconds_words(median)} (its time limit)"
    low, high = seconds_words(median), seconds_words(p90)
    lead = low if low == "under a second" else f"about {low}"
    if low == high:
        return lead
    return f"{lead}, up to {high}"


def wait_text(seconds: float) -> str:
    """How long until a queued run starts, in words."""
    words = seconds_words(seconds)
    return words if words == "under a second" else "about " + words


# ---- Calibration -------------------------------------------------------------------------

def log_run(db, *, machine: str, graph: dict, options: dict, replications: Optional[int],
            actual_s: Optional[float], quote: Optional[dict], censored: bool = False) -> bool:
    """Log one finished run's prediction against its actual time. The
    prediction is recomputed at the replications the run actually made (a run
    to the precision target stops early, or at its budget, with that many
    done), so each logged run is an observed time of its own features. Never
    raises; False when nothing was logged."""
    try:
        if actual_s is None or not replications or db is None:
            return False
        f = features(graph, options)
        if not f["available"]:
            return False
        base = log_median(replications, f["events_per_replication"], f["blocks"])
        now = datetime.now(timezone.utc)
        db.rbd_runtime_log.insert_one({
            "machine": machine,
            "created_at": now,
            "expires_at": now + timedelta(days=LOG_TTL_DAYS),
            "replications": int(replications),
            "events_per_replication": f["events_per_replication"],
            "blocks": f["blocks"],
            # ln of the model's median at factor 1, and the actual seconds.
            "log_median": base,
            "actual_s": float(actual_s),
            "censored": bool(censored),
            # What was quoted before the run (its plan, factor applied).
            "quoted_median_s": (quote or {}).get("median_s"),
            "quoted_p90_s": (quote or {}).get("p90_s"),
            "factor": (quote or {}).get("factor"),
        })
        return True
    except Exception:  # noqa: BLE001 - calibration must never fail a run
        import logging

        logging.getLogger(__name__).warning("Couldn't log a run's time", exc_info=True)
        return False


def calibration(db, machine: str) -> dict:
    """The logged runs of a machine: counts, the factor in use, and how the
    quotes did (the share of runs within their quoted ceiling)."""
    rows = list(db.rbd_runtime_log.find({"machine": machine}))
    quoted = [r for r in rows if r.get("quoted_p90_s") and not r.get("censored")]
    within = sum(1 for r in quoted if r["actual_s"] <= r["quoted_p90_s"] * 1.0001)
    return {
        "machine": machine,
        "factor": current_factor(db, machine),
        "runs": len(rows),
        "observed": sum(1 for r in rows if not r.get("censored")),
        "within_ceiling": (within / len(quoted)) if quoted else None,
        "stored": db.runtime_quote_factors.find_one({"_id": machine}),
    }


def refit_factor(db, machine: str, apply: bool = False) -> dict:
    """Refit a machine's factor from its logged runs: SurPyval's log-normal
    fitted to each run's actual time over the model's median at factor 1
    (right-censored where a run was cut off), its spread held at the model's.
    The factor is that log-normal's median. ``apply`` stores it."""
    import numpy as np
    import surpyval as sv

    rows = list(db.rbd_runtime_log.find({"machine": machine}))
    observed = sum(1 for r in rows if not r.get("censored"))
    if observed < MIN_REFIT_RUNS:
        return {"machine": machine, "refitted": False, "runs": len(rows), "observed": observed,
                "factor": current_factor(db, machine),
                "reason": f"Needs at least {MIN_REFIT_RUNS} finished runs on this machine; it has {observed}."}
    ratios = np.array([r["actual_s"] / math.exp(r["log_median"]) for r in rows], dtype=float)
    c = np.array([1 if r.get("censored") else 0 for r in rows], dtype=int)
    sigma = float(coefficients()["sigma"])
    try:
        model = sv.LogNormal.fit(x=np.maximum(ratios, 1e-9), c=c, fixed={"sigma": sigma})
    except ValueError as exc:  # e.g. every logged run took exactly as predicted
        return {"machine": machine, "refitted": False, "runs": len(rows), "observed": observed,
                "factor": current_factor(db, machine), "reason": f"The log-normal couldn't be fitted: {exc}"}
    factor = float(np.asarray(model.qf(0.5), dtype=float).reshape(-1)[0])
    out = {"machine": machine, "refitted": True, "runs": len(rows), "observed": observed,
           "previous_factor": current_factor(db, machine), "factor": factor, "applied": False}
    if apply:
        db.runtime_quote_factors.update_one(
            {"_id": machine},
            {"$set": {"factor": factor, "runs": len(rows), "refitted_at": datetime.now(timezone.utc)}},
            upsert=True)
        out["applied"] = True
    return out


def ensure_indexes(db) -> None:
    db.rbd_runtime_log.create_index([("machine", 1), ("created_at", -1)])
    db.rbd_runtime_log.create_index([("expires_at", 1)], expireAfterSeconds=0)
