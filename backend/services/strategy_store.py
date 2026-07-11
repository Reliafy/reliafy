"""Persistence for saved strategy analyses.

A saved analysis is the pair (inputs, results) for one of the strategy
calculators — optimal replacement, two-model comparison, or failure-finding
interval. Results are ALWAYS recomputed server-side from the inputs at save
time (never taken from the client): saved analyses serve as evidence for RCM
decisions, so their integrity matters.

Owner-scoping and shared-sample semantics mirror the other stores
(:mod:`backend.services.models`, :mod:`backend.services.degradation`).
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from backend.config import SAMPLE_OWNER
from backend.db import from_doc, to_doc
from backend.schema import StrategyAnalysis
from backend.services import strategy as strategy_service
from backend.services.strategy import StrategyError

KINDS = ("optimal_replacement", "compare_two", "failure_finding")


class AnalysisNotFound(KeyError):
    """Raised when a saved analysis id is unknown / not visible."""


def _now():
    return datetime.now(timezone.utc)


def compute(kind: str, inputs: dict) -> dict:
    """Run the calculator for ``kind`` on ``inputs`` (the endpoint body shape)."""
    if kind == "optimal_replacement":
        return strategy_service.optimal_replacement(
            inputs.get("distribution_id"),
            inputs.get("params") or [],
            inputs.get("planned_cost"),
            inputs.get("unplanned_cost"),
            unit=inputs.get("unit"),
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


def list_analyses(db, owner_id: str, hidden=frozenset()) -> list[StrategyAnalysis]:
    return [
        from_doc(StrategyAnalysis, d)
        for d in db.strategy_analyses.find(
            {"owner_id": {"$in": [owner_id, SAMPLE_OWNER]}}
        ).sort("created_at", -1)
        if d["_id"] not in hidden
    ]


def get_analysis(db, analysis_id: str, owner_id: str | None = None) -> StrategyAnalysis | None:
    query = {"_id": analysis_id}
    if owner_id is not None:
        query["owner_id"] = {"$in": [owner_id, SAMPLE_OWNER]}
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
            unit = f" {r['unit']}" if r.get("unit") else ""
            t = r.get("optimal_time")
            return f"Replace at ~{t:,.0f}{unit}" if t is not None else "Beneficial"
        return "Run-to-failure is optimal (no beneficial interval)"
    if doc.kind == "compare_two":
        return (r.get("verdict") or {}).get("text") or "Comparison"
    if doc.kind == "failure_finding":
        unit = f" {r['unit']}" if r.get("unit") else ""
        i = r.get("interval")
        return f"Check every ~{i:,.0f}{unit}" if i is not None else "Failure-finding interval"
    return doc.kind
