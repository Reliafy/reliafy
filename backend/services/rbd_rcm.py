"""Fill a repairable block's maintenance from an RCM study (#100).

An RCM study records, per failure mode, the chosen task (``decision``):
its outcome, a free-text task, and for scheduled tasks an interval and its
unit, with a link to the analysis that justifies it. Two outcomes are
schedules the availability simulation can run:

* **fixed-interval replacement** → the block's ``preventive`` schedule, as age
  replacement (what Reliafy's optimal-replacement analysis prices);
* **failure-finding** → its ``inspection`` (the failure is hidden and found
  only by the proof test).

A decision stores no cost and no duration, so only the interval comes from
the task — or, when the task has none, from the analysis it links (the
optimal replacement age, or the failure-finding interval). The linked
optimal-replacement analysis also carries the cost of a planned replacement,
which fills the preventive cost. Everything else stays as the user set it.

The other outcomes (on-condition, run-to-failure, redesign, accept) aren't
schedules; each comes back with the reason it can't fill anything. A task
whose interval is in another unit than the diagram's is refused rather than
converted (units are free text).

Access is the study's: a caller reads the tasks of a study it can read, and
the linked analyses resolve as the study's own evidence does
(:func:`backend.services.rcm.resolve`).
"""

from __future__ import annotations

import math
from typing import Any, Optional

from backend.services import rcm as rcm_service
from backend.services import strategy_store

OUTCOME_LABELS = {
    "fixed_interval": "Fixed-interval replacement",
    "failure_finding": "Failure-finding task",
    "on_condition": "On-condition (monitor)",
    "rtf": "Run-to-failure",
    "redesign": "Redesign",
    "accept": "Accept risk",
}

#: Why an outcome can't fill a block's schedule.
UNMAPPED = {
    "on_condition": (
        "Condition monitoring acts on a measured condition, not a fixed schedule — the "
        "availability simulation has no condition-based maintenance, so there's nothing to fill."
    ),
    "rtf": "Run-to-failure schedules nothing — leave the block's maintenance at None.",
    "redesign": "A redesign changes the design, not the maintenance — there's no task to schedule.",
    "accept": "Accepting the risk schedules no maintenance — there's nothing to fill.",
}

TARGETS = {"fixed_interval": "preventive", "failure_finding": "inspection"}
_ANALYSIS_KIND = {"fixed_interval": "optimal_replacement", "failure_finding": "failure_finding"}


def _positive(value) -> Optional[float]:
    try:
        x = float(value)
    except (TypeError, ValueError):
        return None
    return x if math.isfinite(x) and x > 0 else None


def _non_negative(value) -> Optional[float]:
    try:
        x = float(value)
    except (TypeError, ValueError):
        return None
    return x if math.isfinite(x) and x >= 0 else None


def _analysis(db, decision: dict, readers, hidden):
    """The strategy analysis a decision links, if the reader can see it."""
    evidence = decision.get("evidence") or {}
    if evidence.get("type") != "strategy_analysis" or not evidence.get("id"):
        return None
    if evidence["id"] in hidden:
        return None
    return strategy_store.get_analysis(db, evidence["id"], readers)


def map_decision(decision: Optional[dict], analysis, unit: str) -> dict:
    """What one RCM decision fills on a block of a diagram in ``unit``:
    ``{"target", "fill", "sources", "interval_unit"}``, or ``{"reason"}``
    when it can't fill anything."""
    if not decision:
        return {"reason": "No task has been decided for this failure mode yet."}
    outcome = decision.get("outcome")
    if outcome in UNMAPPED:
        return {"reason": UNMAPPED[outcome]}
    if outcome not in TARGETS:
        return {"reason": "This decision isn't a scheduled task."}
    if analysis is not None and analysis.kind != _ANALYSIS_KIND[outcome]:
        analysis = None  # linked to the wrong kind of analysis: take nothing from it
    results = (analysis.results or {}) if analysis is not None else {}
    inputs = (analysis.inputs or {}) if analysis is not None else {}

    fill: dict[str, Any] = {}
    sources: dict[str, str] = {}
    interval = _positive(decision.get("interval"))
    interval_unit = decision.get("interval_unit")
    if interval is not None:
        sources["interval"] = "task"
    else:
        if outcome == "fixed_interval" and results.get("beneficial"):
            interval = _positive(results.get("optimal_time"))
        elif outcome == "failure_finding":
            interval = _positive(results.get("interval"))
        if interval is not None:
            # A computed optimum, not a chosen schedule: 4 significant figures
            # (as the analysis itself quotes it), not float noise.
            interval = float(f"{interval:.4g}")
            sources["interval"] = "analysis"
            interval_unit = results.get("unit") or inputs.get("unit")
    if interval is None:
        return {"reason": "The task has no interval yet — set one in the study, or link an "
                          "analysis that computes it."}
    here, there = rcm_service._norm_unit(unit), rcm_service._norm_unit(interval_unit)
    if here and there and here != there:
        return {"reason": f"The task's interval is in {interval_unit} but this diagram is in "
                          f"{unit} — convert it and enter it by hand."}

    if outcome == "fixed_interval":
        fill["policy"] = "age"
    fill["interval"] = interval
    if outcome == "fixed_interval" and analysis is not None:
        cost = _non_negative(inputs.get("planned_cost"))
        if cost is not None:
            fill["cost"] = cost
            sources["cost"] = "analysis"
    out = {"target": TARGETS[outcome], "fill": fill, "sources": sources,
           "interval_unit": (str(interval_unit).strip() or None) if interval_unit else None}
    if analysis is not None and any(v == "analysis" for v in sources.values()):
        out["analysis_name"] = analysis.name
    return out


def maintenance_tasks(db, study, readers, hidden=frozenset(), unit: str = "") -> dict:
    """Every failure mode of ``study`` with what its task would fill on a
    block of a diagram in ``unit`` (or why it can't)."""
    tasks = []
    for fn in study.functions or []:
        for failure in fn.get("failures") or []:
            for mode in failure.get("modes") or []:
                decision = mode.get("decision")
                analysis = _analysis(db, decision, readers, hidden) if decision else None
                row = {
                    "mode_id": mode.get("id"),
                    "mode": mode.get("text"),
                    "function": fn.get("text"),
                    "failure": failure.get("text"),
                    "outcome": (decision or {}).get("outcome"),
                    "outcome_label": OUTCOME_LABELS.get((decision or {}).get("outcome")),
                    "task": (decision or {}).get("task"),
                    **map_decision(decision, analysis, unit),
                }
                tasks.append(row)
    return {
        "study_id": study.id,
        "study": study.name,
        "unit": (unit or "").strip(),
        "tasks": tasks,
        "mappable": sum(1 for t in tasks if t.get("target")),
    }
