"""Persistence for saved strategy analyses.

A saved analysis is the pair (inputs, results) for one of the strategy
calculators — optimal replacement, two-model comparison, failure-finding
interval, or demonstration test plan. Results are ALWAYS recomputed server-side from the inputs at save
time (never taken from the client): saved analyses serve as evidence for RCM
decisions, so their integrity matters.

Owner-scoping and shared-sample semantics mirror the other stores
(:mod:`backend.services.models`, :mod:`backend.services.degradation`).
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from backend.services import access
from backend.db import from_doc, to_doc
from backend.schema import StrategyAnalysis
from backend.services import strategy as strategy_service
from backend.services.strategy import StrategyError
from backend.units import unit_in_text, with_unit

KINDS = ("optimal_replacement", "compare_two", "failure_finding", "demonstration_test",
         "on_condition_interval", "failure_finding_interval")

# The RCM interval calculators' inputs (backend/services/rcm_intervals.py), as saved.
ON_CONDITION_INPUTS = (
    "pf_interval", "pf_unit", "onset_rate", "inspection_cost", "found_cost", "failure_cost",
    "detection_probability", "unit", "current_interval", "current_unit",
)
FAILURE_FINDING_INPUTS = (
    "failure_rate", "distribution_id", "params", "model_unit", "extras", "target_unavailability", "test_cost",
    "repair_cost", "demand_rate", "consequence_cost", "unit", "current_interval", "current_unit",
)

# The demonstration-test calculator's inputs (the endpoint body shape).
DEMO_INPUTS = (
    "method", "reliability", "confidence", "mission_time", "failures", "test_multiple",
    "shape", "units", "mtbf", "design_reliability", "design_mtbf", "unit", "producer_risk",
    "b_life", "shape_interval", "shape_model", "failure_terminated",
)


def _list_query(owner_id, shared=frozenset()):
    """Owner-scoped filter, optionally unioned with directly-shared ids."""
    query = {"owner_id": {"$in": access.owner_in(owner_id)}}
    if shared:
        return {"$or": [query, {"_id": {"$in": sorted(shared)}}]}
    return query

class AnalysisNotFound(KeyError):
    """Raised when a saved analysis id is unknown / not visible."""


def _now():
    return datetime.now(timezone.utc)


def compute(kind: str, inputs: dict) -> dict:
    """Run the calculator for ``kind`` on ``inputs`` (the endpoint body shape,
    including a fitted model's ``extras`` — offset, LFP fraction, zero
    inflation — so a saved analysis matches what the calculator showed)."""
    if kind == "optimal_replacement":
        return strategy_service.optimal_replacement(
            inputs.get("distribution_id"),
            inputs.get("params") or [],
            inputs.get("planned_cost"),
            inputs.get("unplanned_cost"),
            unit=inputs.get("unit"),
            extras=inputs.get("extras"),
        )
    if kind == "compare_two":
        return strategy_service.compare_two(
            inputs.get("a") or {}, inputs.get("b") or {}, unit=inputs.get("unit")
        )
    if kind == "failure_finding":
        return strategy_service.failure_finding(
            inputs.get("distribution_id"),
            inputs.get("params") or [],
            inputs.get("target_availability"),
            unit=inputs.get("unit"),
            extras=inputs.get("extras"),
        )
    if kind == "on_condition_interval":
        from backend.services import rcm_intervals

        return rcm_intervals.on_condition_interval(**{k: inputs.get(k) for k in ON_CONDITION_INPUTS if k in inputs})
    if kind == "failure_finding_interval":
        from backend.services import rcm_intervals

        return rcm_intervals.failure_finding_interval(
            **{k: inputs.get(k) for k in FAILURE_FINDING_INPUTS if k in inputs})
    if kind == "demonstration_test":
        return strategy_service.demonstration_test(
            **{k: inputs[k] for k in DEMO_INPUTS if k in inputs}
        )
    raise StrategyError(f"Unknown analysis kind '{kind}'.")


def save_analysis(db, name: str, kind: str, inputs: dict, owner_id: str) -> StrategyAnalysis:
    if not (name or "").strip():
        raise StrategyError("The analysis needs a name.")
    if kind not in KINDS:
        raise StrategyError(f"kind must be one of: {', '.join(KINDS)}.")
    results = compute(kind, inputs or {})
    doc = StrategyAnalysis(
        id=uuid.uuid4().hex,
        name=name.strip(),
        owner_id=owner_id,
        kind=kind,
        inputs=inputs or {},
        results=results,
    )
    db.strategy_analyses.insert_one(to_doc(doc))
    return doc


def list_analyses(db, owner_id: str | list[str], hidden=frozenset(), shared=frozenset()) -> list[StrategyAnalysis]:
    return [
        from_doc(StrategyAnalysis, d)
        for d in db.strategy_analyses.find(
            _list_query(owner_id, shared)
        ).sort("created_at", -1)
        if d["_id"] not in hidden
    ]


def get_analysis(db, analysis_id: str, owner_id: str | list[str] | None = None) -> StrategyAnalysis | None:
    query = {"_id": analysis_id}
    if owner_id is not None:
        query["owner_id"] = {"$in": access.owner_in(owner_id)}
    return from_doc(StrategyAnalysis, db.strategy_analyses.find_one(query))


def rename_analysis(db, analysis_id: str, name: str, owner_id: str) -> StrategyAnalysis:
    doc = get_analysis(db, analysis_id, owner_id)
    if doc is None or doc.owner_id != owner_id:
        raise AnalysisNotFound(analysis_id)  # unknown, not owned, or sample
    doc.name = name
    doc.updated_at = _now()
    db.strategy_analyses.update_one(
        {"_id": analysis_id, "owner_id": owner_id},
        {"$set": {"name": name, "updated_at": doc.updated_at}},
    )
    return doc


def delete_analysis(db, analysis_id: str, owner_id: str) -> None:
    result = db.strategy_analyses.delete_one({"_id": analysis_id, "owner_id": owner_id})
    if result.deleted_count == 0:
        raise AnalysisNotFound(analysis_id)


def headline(doc: StrategyAnalysis) -> str:
    """One-line summary for list rows."""
    r = doc.results or {}
    if doc.kind == "optimal_replacement":
        if r.get("beneficial"):
            unit = f" {unit_in_text(r['unit'])}" if r.get("unit") else ""
            t = r.get("optimal_time")
            return f"Replace at ~{strategy_service.fmt_num(t)}{unit}" if t is not None else "Beneficial"
        return "Run-to-failure is optimal (no beneficial interval)"
    if doc.kind == "compare_two":
        return (r.get("verdict") or {}).get("text") or "Comparison"
    if doc.kind == "failure_finding":
        unit = f" {unit_in_text(r['unit'])}" if r.get("unit") else ""
        i = r.get("interval")
        return f"Check every ~{strategy_service.fmt_num(i)}{unit}" if i is not None else "Failure finding"
    if doc.kind == "demonstration_test":
        return demonstration_headline(r)
    if doc.kind in ("on_condition_interval", "failure_finding_interval"):
        rec = r.get("recommended")
        if not rec:
            return "Checking never pays"
        verb = "Check" if doc.kind == "on_condition_interval" else "Test"
        return f"{verb} every {strategy_service.fmt_num(rec['value'])} {unit_in_text(rec['unit'])}"
    return doc.kind


def demonstration_headline(r: dict) -> str:
    """'59 units × 1,000 hours, 0 failures' — the plan in a few words."""
    fmt = strategy_service.fmt_num
    unit = unit_in_text(r["unit"]) if r.get("unit") else ""
    failures = r.get("failures") or 0
    allowed = (
        f"≤{failures} failure{'s' if failures != 1 else ''}"
        if failures
        else "0 failures"
    )
    if r.get("method") == "mtbf":
        total = r.get("total_test_time")
        return (
            f"{with_unit(fmt(total), unit)} total test time, {allowed}"
            if total is not None
            else "MTBF test"
        )
    n = r.get("units")
    if n is None:
        return "Demonstration test"
    per_unit = r.get("test_time_per_unit")
    k = r.get("test_multiple") or 1
    length = (
        with_unit(fmt(per_unit), unit)
        if per_unit is not None
        else f"{fmt(k)} mission{'s' if k != 1 else ''}"
    )
    return f"{n:,} units × {length}, {allowed}"
