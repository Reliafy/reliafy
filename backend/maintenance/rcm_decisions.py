"""RCM decisions: the rules every RCM decision on the asset tree follows.

The vocabulary (consequences, outcomes, run-to-failure bases, evidence
types), the validation of a decision (outcome, interval and its unit,
evidence link) and the live evidence check: a decision links the saved model
or analysis that justifies it, and the link is *checked* on every read. A
run-to-failure-because-random decision whose non-repairable model now shows
wear-out is flagged **contradicted**, not silently trusted. Statuses are
therefore never stored; they are recomputed from the linked artifacts each
time the RCM is read.

The maintenance tree (``backend/maintenance/service.py`` and
``rcm_graph.py``) owns these rules. The older RCM study service
(``backend/services/rcm.py``) imports them from here, so there is one copy.
"""

from __future__ import annotations

from backend.services import degradation as degradation_service
from backend.services import models as models_service
from backend.services import strategy_store
from backend.services.strategy import fmt_num
from backend.units import unit_in_text


class RcmValidationError(ValueError):
    """Raised when a worksheet tree fails validation (HTTP 422)."""


CONSEQUENCES = ("safety", "environmental", "operational", "non_operational", "hidden")
OUTCOMES = ("on_condition", "fixed_interval", "rtf", "failure_finding", "redesign", "accept")
RTF_BASES = ("random", "uneconomic")
EVIDENCE_TYPES = ("model", "strategy_analysis", "degradation_model")

# Common aliases so "hr", "hrs" and "hours" agree. Unmapped units compare
# case-insensitively as-is.
_UNIT_ALIASES = {
    "h": "hours", "hr": "hours", "hrs": "hours", "hour": "hours",
    "d": "days", "day": "days",
    "wk": "weeks", "wks": "weeks", "week": "weeks",
    "mo": "months", "month": "months",
    "y": "years", "yr": "years", "yrs": "years", "year": "years",
    "cycle": "cycles", "cyc": "cycles",
    "kilometre": "km", "kilometres": "km", "kilometer": "km", "kilometers": "km",
    "mile": "miles", "mi": "miles",
    "operating hours": "hours", "op hrs": "hours",
}


def _norm_unit(unit) -> str:
    u = str(unit or "").strip().lower()
    return _UNIT_ALIASES.get(u, u)


def _unit_mismatch(decision: dict, evidence_unit) -> dict | None:
    """Inconclusive result when the task interval's unit contradicts the
    evidence's time unit. Units are free text, so only a definite
    disagreement (both present, different after normalisation) trips this —
    a missing unit on either side passes.
    """
    task_unit = _norm_unit(decision.get("interval_unit"))
    ev_unit = _norm_unit(evidence_unit)
    if task_unit and ev_unit and task_unit != ev_unit:
        return {
            "status": "inconclusive",
            "reason": (
                f"Unit mismatch: the task interval is in {unit_in_text(decision.get('interval_unit'))} "
                f"but the linked analysis is in {unit_in_text(evidence_unit)}. Align the units to validate "
                "this decision."
            ),
        }
    return None


# What each outcome expects as evidence (None = default action, no evidence).
EXPECTED_EVIDENCE = {
    "on_condition": "degradation_model",
    "fixed_interval": "strategy_analysis",
    "rtf": None,  # depends on rtf_basis: random -> model, uneconomic -> strategy_analysis
    "failure_finding": "strategy_analysis",
    "redesign": None,
    "accept": None,
}


def _clean_decision(decision) -> dict | None:
    if decision is None:
        return None
    outcome = decision.get("outcome")
    if outcome not in OUTCOMES:
        raise RcmValidationError(f"Unknown outcome '{outcome}'.")
    cleaned = {"outcome": outcome}

    if outcome == "rtf":
        basis = decision.get("rtf_basis")
        if basis not in RTF_BASES:
            raise RcmValidationError(
                "A run-to-failure decision needs its basis: 'random' or 'uneconomic'."
            )
        cleaned["rtf_basis"] = basis

    interval = decision.get("interval")
    if interval is not None and interval != "":
        try:
            interval = float(interval)
        except (TypeError, ValueError):
            raise RcmValidationError("The task interval must be a number.")
        if interval <= 0:
            raise RcmValidationError("The task interval must be positive.")
        cleaned["interval"] = interval
        unit = str(decision.get("interval_unit") or "").strip()
        if unit:
            cleaned["interval_unit"] = unit

    for key in ("task", "notes"):
        value = str(decision.get(key) or "").strip()
        if value:
            cleaned[key] = value

    evidence = decision.get("evidence")
    if evidence:
        etype = evidence.get("type")
        eid = evidence.get("id")
        if etype not in EVIDENCE_TYPES:
            raise RcmValidationError(f"Unknown evidence type '{etype}'.")
        if not isinstance(eid, str) or not eid.strip():
            raise RcmValidationError("Evidence needs the linked artifact's id.")
        # A type that doesn't match the outcome is allowed at write time and
        # resolves to 'inconclusive' at read — users can link first, fix later.
        cleaned["evidence"] = {"type": etype, "id": eid.strip()}
    else:
        cleaned["evidence"] = None
    return cleaned


# ---- Evidence resolution (live validation) -----------------------------------

def evidence_fetcher(db, owner_id, hidden=frozenset()):
    """fetch(type, id): the linked model or analysis a reader (``owner_id``) can
    open, or None; each looked up once. Shared by studies and the RCM on the
    maintenance positions (backend/maintenance/rcm_graph.py), so both check
    evidence the same way."""
    memo: dict = {}

    def fetch(etype: str, eid: str):
        key = (etype, eid)
        if key not in memo:
            if eid in hidden:
                memo[key] = None
            elif etype == "model":
                memo[key] = models_service.get_model(db, eid, owner_id)
            elif etype == "strategy_analysis":
                memo[key] = strategy_store.get_analysis(db, eid, owner_id)
            elif etype == "degradation_model":
                memo[key] = degradation_service.get_model(db, eid, owner_id)
            else:
                memo[key] = None
        return memo[key]

    return fetch


def blank_rollup() -> dict:
    return {"modes": 0, "decided": 0, "supported": 0, "contradicted": 0,
            "inconclusive": 0, "unevidenced": 0, "stale": 0}


def resolve_decision(decision: dict, fetch) -> dict:
    """A decision's evidence status ({status, reason or summary, artifact_name,
    artifact_link_path, expected_evidence}) against what ``fetch`` finds."""
    return _resolve_decision(decision, fetch)


def _resolve_decision(decision: dict, fetch) -> dict:
    outcome = decision["outcome"]
    evidence = decision.get("evidence")

    if outcome in ("redesign", "accept"):
        return {"status": None, "reason": "Default action — no supporting analysis required."}

    expected = EXPECTED_EVIDENCE[outcome]
    if outcome == "rtf":
        expected = "model" if decision.get("rtf_basis") == "random" else "strategy_analysis"

    if not evidence:
        return {
            "status": "unevidenced",
            "reason": "No supporting analysis linked yet.",
            "expected_evidence": expected,
        }

    artifact = fetch(evidence["type"], evidence["id"])
    if artifact is None:
        return {"status": "stale", "reason": "The linked analysis no longer exists."}

    if evidence["type"] != expected:
        return {
            "status": "inconclusive",
            "reason": f"Linked evidence is a {_type_label(evidence['type'])} — this decision needs a {_type_label(expected)}.",
            "artifact_name": artifact.name,
            "artifact_link_path": _link_path(evidence["type"], artifact.id),
        }

    base = {
        "artifact_name": artifact.name,
        "artifact_link_path": _link_path(evidence["type"], artifact.id),
    }
    if outcome == "rtf" and decision.get("rtf_basis") == "random":
        return {**base, **_check_randomness(artifact)}
    if outcome == "rtf":  # uneconomic
        return {**base, **_check_replacement(artifact, want_beneficial=False)}
    if outcome == "fixed_interval":
        mismatch = _unit_mismatch(decision, (artifact.results or {}).get("unit"))
        if mismatch:
            return {**base, **mismatch}
        return {**base, **_check_replacement(artifact, want_beneficial=True)}
    if outcome == "on_condition":
        mismatch = _unit_mismatch(decision, (artifact.results or {}).get("unit"))
        if mismatch:
            return {**base, **mismatch}
        if artifact.status == "ready":
            r = artifact.results or {}
            unit = f" {r['measurement_unit']}" if r.get("measurement_unit") else ""
            return {**base, "status": "supported",
                    "summary": f"Degradation model (threshold {r.get('threshold')}{unit}) supports condition monitoring."}
        return {**base, "status": "inconclusive", "reason": "The degradation model isn't ready."}
    if outcome == "failure_finding":
        if artifact.kind != "failure_finding":
            return {**base, "status": "inconclusive",
                    "reason": "The linked analysis isn't a failure-finding interval."}
        r = artifact.results or {}
        mismatch = _unit_mismatch(decision, r.get("unit"))
        if mismatch:
            return {**base, **mismatch}
        interval = r.get("interval")
        if interval is not None:
            unit = f" {unit_in_text(r['unit'])}" if r.get("unit") else ""
            return {**base, "status": "supported",
                    "summary": f"Check every ~{fmt_num(interval)}{unit} for {r.get('target_availability', 0):.0%} availability."}
        return {**base, "status": "inconclusive", "reason": "The analysis has no computed interval."}
    return {**base, "status": "inconclusive", "reason": "Unrecognised decision."}


def _check_randomness(model) -> dict:
    """Evidence check for RTF-because-random against a saved non-repairable model."""
    results = model.results or {}
    if results.get("kind") == "regression":
        return {"status": "inconclusive",
                "reason": "A regression model can't establish randomness — fit a Weibull or Exponential."}
    randomness = results.get("randomness")
    if randomness is None:
        if results.get("distribution_id") in ("weibull", "exponential"):
            return {"status": "inconclusive",
                    "reason": "No confidence interval on this fit — re-save the model to compute it."}
        return {"status": "inconclusive",
                "reason": "This distribution can't establish randomness — fit a Weibull or Exponential."}
    verdict = randomness.get("verdict")
    if randomness.get("basis") == "memoryless":
        return {"status": "supported", "summary": "Exponential fit — memoryless: failures are random."}

    beta = randomness.get("beta")
    ci = randomness.get("beta_ci")
    ci_s = f" [{ci[0]:.2f}, {ci[1]:.2f}]" if ci else ""
    beta_s = f"β = {beta:.2f}{ci_s}" if beta is not None else ""
    if verdict == "random":
        return {"status": "supported", "summary": f"{beta_s} — consistent with random (constant-rate) failure."}
    if verdict == "wear_out":
        return {"status": "contradicted",
                "summary": f"{beta_s} — the CI excludes 1: this is wear-out. Run-to-failure is not justified by this model."}
    if verdict == "infant_mortality":
        return {"status": "contradicted",
                "summary": f"{beta_s} — infant mortality, not random failure."}
    return {"status": "inconclusive",
            "reason": "No confidence interval on β — re-save the model to compute it."}


def _check_replacement(analysis, want_beneficial: bool) -> dict:
    """Evidence check against a saved optimal-replacement analysis."""
    if analysis.kind != "optimal_replacement":
        return {"status": "inconclusive",
                "reason": "The linked analysis isn't an optimal-replacement calculation."}
    r = analysis.results or {}
    beneficial = bool(r.get("beneficial"))
    unit = f" {unit_in_text(r['unit'])}" if r.get("unit") else ""
    if beneficial and want_beneficial:
        t = r.get("optimal_time")
        savings = r.get("savings") or 0
        return {"status": "supported",
                "summary": f"Optimal interval ≈ {fmt_num(t)}{unit} ({savings:.0%} saving vs run-to-failure)."}
    if not beneficial and not want_beneficial:
        return {"status": "supported",
                "summary": "Preventive replacement shows no cost benefit — run-to-failure is optimal."}
    if beneficial and not want_beneficial:
        t = r.get("optimal_time")
        savings = r.get("savings") or 0
        return {"status": "contradicted",
                "summary": f"The analysis finds replacement at ~{fmt_num(t)}{unit} saves {savings:.0%} — run-to-failure is uneconomic."}
    return {"status": "contradicted",
            "summary": "The analysis finds no beneficial interval — fixed-interval replacement isn't justified."}


def _type_label(etype: str) -> str:
    return {
        "model": "non-repairable model",
        "strategy_analysis": "saved strategy analysis",
        "degradation_model": "degradation model",
    }.get(etype, etype)


def _link_path(etype: str, artifact_id: str) -> str:
    return {
        "model": f"/models/m/{artifact_id}",
        "strategy_analysis": f"/strategy/analyses/{artifact_id}",
        "degradation_model": f"/models/degradation/{artifact_id}",
    }[etype]


# Public names for the tree's callers; the underscored names stay for the
# older study service and its tests.
norm_unit = _norm_unit
clean_decision = _clean_decision
