"""RCM studies: worksheet persistence and live evidence validation.

The differentiator of Reliafy's RCM is that every maintenance decision links
to the quantitative analysis that justifies it, and the link is *checked* on
every read: an RTF-because-random decision whose life model now shows wear-out
is flagged **contradicted**, not silently trusted. Statuses are therefore never
stored — :func:`resolve` recomputes them from the linked artifacts each time a
study is loaded.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from backend.services import access
from backend.db import from_doc, to_doc
from backend.schema import RcmStudy
from backend.services import degradation as degradation_service
from backend.services import models as models_service
from backend.services import strategy_store


class StudyNotFound(KeyError):
    """Raised when a study id is unknown / not visible."""


class RcmValidationError(ValueError):
    """Raised when a worksheet tree fails validation (HTTP 422)."""


CONSEQUENCES = ("safety", "environmental", "operational", "non_operational", "hidden")
OUTCOMES = ("on_condition", "fixed_interval", "rtf", "failure_finding", "redesign", "accept")
RTF_BASES = ("random", "uneconomic")
EVIDENCE_TYPES = ("model", "strategy_analysis", "degradation_model")

# What each outcome expects as evidence (None = default action, no evidence).
EXPECTED_EVIDENCE = {
    "on_condition": "degradation_model",
    "fixed_interval": "strategy_analysis",
    "rtf": None,  # depends on rtf_basis: random -> model, uneconomic -> strategy_analysis
    "failure_finding": "strategy_analysis",
    "redesign": None,
    "accept": None,
}


def _now():
    return datetime.now(timezone.utc)


# ---- CRUD -------------------------------------------------------------------

def create_study(db, name: str, system: str, description: str, owner_id: str) -> RcmStudy:
    if not (name or "").strip():
        raise RcmValidationError("The study needs a name.")
    study = RcmStudy(
        id=uuid.uuid4().hex,
        name=name.strip(),
        system=(system or "").strip(),
        description=(description or "").strip(),
        owner_id=owner_id,
    )
    db.rcm_studies.insert_one(to_doc(study))
    return study


def list_studies(db, owner_id: str | list[str], hidden=frozenset()) -> list[RcmStudy]:
    return [
        from_doc(RcmStudy, d)
        for d in db.rcm_studies.find(
            {"owner_id": {"$in": access.owner_in(owner_id)}}
        ).sort("created_at", -1)
        if d["_id"] not in hidden
    ]


def get_study(db, study_id: str, owner_id: str | list[str] | None = None) -> RcmStudy | None:
    query = {"_id": study_id}
    if owner_id is not None:
        query["owner_id"] = {"$in": access.owner_in(owner_id)}
    return from_doc(RcmStudy, db.rcm_studies.find_one(query))


def rename_study(db, study_id: str, name: str, owner_id: str) -> RcmStudy:
    study = get_study(db, study_id, owner_id)
    if study is None or study.owner_id != owner_id:
        raise StudyNotFound(study_id)
    study.name = name
    study.updated_at = _now()
    db.rcm_studies.update_one(
        {"_id": study_id, "owner_id": owner_id},
        {"$set": {"name": name, "updated_at": study.updated_at}},
    )
    return study


def delete_study(db, study_id: str, owner_id: str) -> None:
    result = db.rcm_studies.delete_one({"_id": study_id, "owner_id": owner_id})
    if result.deleted_count == 0:
        raise StudyNotFound(study_id)


# ---- Tree write --------------------------------------------------------------

def _require_text(node: dict, what: str) -> str:
    text = str(node.get("text") or "").strip()
    if not text:
        raise RcmValidationError(f"Every {what} needs a description.")
    return text


def _node_id(node: dict) -> str:
    nid = node.get("id")
    return nid if isinstance(nid, str) and nid.strip() else uuid.uuid4().hex


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


def clean_tree(functions) -> list[dict]:
    """Validate and normalise a submitted worksheet tree."""
    if not isinstance(functions, list):
        raise RcmValidationError("functions must be a list.")
    out = []
    for fn in functions:
        cleaned_fn = {
            "id": _node_id(fn),
            "text": _require_text(fn, "function"),
            "failures": [],
        }
        standard = str(fn.get("standard") or "").strip()
        if standard:
            cleaned_fn["standard"] = standard
        for failure in fn.get("failures") or []:
            cleaned_failure = {
                "id": _node_id(failure),
                "text": _require_text(failure, "functional failure"),
                "modes": [],
            }
            for mode in failure.get("modes") or []:
                consequence = mode.get("consequence") or None
                if consequence is not None and consequence not in CONSEQUENCES:
                    raise RcmValidationError(f"Unknown consequence '{consequence}'.")
                cleaned_mode = {
                    "id": _node_id(mode),
                    "text": _require_text(mode, "failure mode"),
                    "consequence": consequence,
                    "decision": _clean_decision(mode.get("decision")),
                }
                effects = str(mode.get("effects") or "").strip()
                if effects:
                    cleaned_mode["effects"] = effects
                cleaned_failure["modes"].append(cleaned_mode)
            cleaned_fn["failures"].append(cleaned_failure)
        out.append(cleaned_fn)
    return out


def replace_tree(db, study_id: str, functions, owner_id: str) -> RcmStudy:
    study = get_study(db, study_id, owner_id)
    if study is None or study.owner_id != owner_id:
        raise StudyNotFound(study_id)
    study.functions = clean_tree(functions)
    study.updated_at = _now()
    db.rcm_studies.update_one(
        {"_id": study_id, "owner_id": owner_id},
        {"$set": {"functions": study.functions, "updated_at": study.updated_at}},
    )
    return study


# ---- Evidence resolution (live validation) -----------------------------------

def resolve(db, study: RcmStudy, owner_id: str, hidden=frozenset()) -> dict:
    """The study as a dict with per-decision evidence statuses and a rollup."""
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

    rollup = {"modes": 0, "decided": 0, "supported": 0, "contradicted": 0,
              "inconclusive": 0, "unevidenced": 0, "stale": 0}
    doc = {
        "id": study.id,
        "name": study.name,
        "system": study.system,
        "description": study.description,
        "functions": [],
    }
    for fn in study.functions or []:
        fn_out = {**fn, "failures": []}
        for failure in fn.get("failures") or []:
            f_out = {**failure, "modes": []}
            for mode in failure.get("modes") or []:
                m_out = dict(mode)
                rollup["modes"] += 1
                decision = mode.get("decision")
                if decision:
                    rollup["decided"] += 1
                    resolved = _resolve_decision(decision, fetch)
                    m_out["decision"] = {**decision, **resolved}
                    status = resolved.get("status")
                    if status in rollup:
                        rollup[status] += 1
                f_out["modes"].append(m_out)
            fn_out["failures"].append(f_out)
        doc["functions"].append(fn_out)
    doc["rollup"] = rollup
    return doc


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
        return {**base, **_check_replacement(artifact, want_beneficial=True)}
    if outcome == "on_condition":
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
        interval = r.get("interval")
        if interval is not None:
            unit = f" {r['unit']}" if r.get("unit") else ""
            return {**base, "status": "supported",
                    "summary": f"Check every ~{interval:,.0f}{unit} for {r.get('target_availability', 0):.0%} availability."}
        return {**base, "status": "inconclusive", "reason": "The analysis has no computed interval."}
    return {**base, "status": "inconclusive", "reason": "Unrecognised decision."}


def _check_randomness(model) -> dict:
    """Evidence check for RTF-because-random against a saved life model."""
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
    unit = f" {r['unit']}" if r.get("unit") else ""
    if beneficial and want_beneficial:
        t = r.get("optimal_time")
        savings = r.get("savings") or 0
        return {"status": "supported",
                "summary": f"Optimal interval ≈ {t:,.0f}{unit} ({savings:.0%} saving vs run-to-failure)."}
    if not beneficial and not want_beneficial:
        return {"status": "supported",
                "summary": "Preventive replacement shows no cost benefit — run-to-failure is optimal."}
    if beneficial and not want_beneficial:
        t = r.get("optimal_time")
        savings = r.get("savings") or 0
        return {"status": "contradicted",
                "summary": f"The analysis finds replacement at ~{t:,.0f}{unit} saves {savings:.0%} — run-to-failure is uneconomic."}
    return {"status": "contradicted",
            "summary": "The analysis finds no beneficial interval — fixed-interval replacement isn't justified."}


def _type_label(etype: str) -> str:
    return {
        "model": "life model",
        "strategy_analysis": "saved strategy analysis",
        "degradation_model": "degradation model",
    }.get(etype, etype)


def _link_path(etype: str, artifact_id: str) -> str:
    return {
        "model": f"/modelling/m/{artifact_id}",
        "strategy_analysis": f"/strategy/analyses/{artifact_id}",
        "degradation_model": f"/modelling/degradation/{artifact_id}",
    }[etype]
