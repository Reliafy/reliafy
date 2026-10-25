"""RCM studies: worksheet persistence and live evidence validation.

The differentiator of Reliafy's RCM is that every maintenance decision links
to the quantitative analysis that justifies it, and the link is *checked* on
every read: an RTF-because-random decision whose non-repairable model now shows wear-out
is flagged **contradicted**, not silently trusted. Statuses are therefore never
stored — :func:`resolve` recomputes them from the linked artifacts each time a
study is loaded.
"""

from __future__ import annotations

import uuid

from backend.services import access
from backend.db import from_doc, to_doc
from backend.schema import RcmStudy
# The decision rules live with the maintenance tree; studies use the same copy.
from backend.maintenance.rcm_decisions import (  # noqa: F401  (re-exported for older callers)
    CONSEQUENCES,
    EVIDENCE_TYPES,
    EXPECTED_EVIDENCE,
    OUTCOMES,
    RTF_BASES,
    RcmValidationError,
    _UNIT_ALIASES,
    _check_randomness,
    _check_replacement,
    _clean_decision,
    _link_path,
    _norm_unit,
    _resolve_decision,
    _type_label,
    _unit_mismatch,
    blank_rollup,
    evidence_fetcher,
    resolve_decision,
)


def _list_query(owner_id, shared=frozenset()):
    """Owner-scoped filter, optionally unioned with directly-shared ids."""
    query = {"owner_id": {"$in": access.owner_in(owner_id)}}
    if shared:
        return {"$or": [query, {"_id": {"$in": sorted(shared)}}]}
    return query

class StudyNotFound(KeyError):
    """Raised when a study id is unknown / not visible."""


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


def list_studies(db, owner_id: str | list[str], hidden=frozenset(), shared=frozenset()) -> list[RcmStudy]:
    return [
        from_doc(RcmStudy, d)
        for d in db.rcm_studies.find(
            _list_query(owner_id, shared)
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
    study.updated_at = access.next_updated_at(study.updated_at)
    db.rcm_studies.update_one(
        {"_id": study_id, "owner_id": owner_id},
        {"$set": {"name": name, "updated_at": study.updated_at}},
    )
    return study


def update_details(db, study_id: str, owner_id: str, name: str | None = None, system: str | None = None,
                   description: str | None = None) -> RcmStudy:
    """Change a study's name, system or description (``None`` leaves one as
    it is); the worksheet is untouched."""
    study = get_study(db, study_id, owner_id)
    if study is None or study.owner_id != owner_id:
        raise StudyNotFound(study_id)
    changes = {}
    if name is not None:
        if not name.strip():
            raise RcmValidationError("The study needs a name.")
        changes["name"] = name.strip()
    if system is not None:
        changes["system"] = system.strip()
    if description is not None:
        changes["description"] = description.strip()
    if not changes:
        return study
    study = study.model_copy(update=changes)
    study.updated_at = access.next_updated_at(study.updated_at)
    db.rcm_studies.update_one(
        {"_id": study_id, "owner_id": owner_id},
        {"$set": {**changes, "updated_at": study.updated_at}},
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
                # Free-text notes on the mode itself (e.g. FMEA scores kept
                # from a spreadsheet import); a decision's notes live on it.
                notes = str(mode.get("notes") or "").strip()
                if notes:
                    cleaned_mode["notes"] = notes
                cleaned_failure["modes"].append(cleaned_mode)
            cleaned_fn["failures"].append(cleaned_failure)
        out.append(cleaned_fn)
    return out


def replace_tree(db, study_id: str, functions, owner_id: str,
                 expected_updated_at: str | None = None,
                 reader: "access.AccessCtx | None" = None) -> RcmStudy:
    """Swap a study's worksheet. With ``reader`` (the writer's access
    context), every newly linked evidence item must be one the writer can
    open — :class:`access.UnreadableReference` otherwise; links the study
    already had are kept as they are."""
    study = get_study(db, study_id, owner_id)
    if study is None or study.owner_id != owner_id:
        raise StudyNotFound(study_id)
    if study.migrated_to:
        raise RcmValidationError("This study has moved onto its position in the asset tree: change its RCM there.")
    query = {"_id": study_id, "owner_id": owner_id}
    if expected_updated_at and study.updated_at is not None:
        if not access.timestamps_match(study.updated_at, expected_updated_at):
            raise access.EditConflict()
        # Conditional on the stamp checked: a save racing in between conflicts.
        query["updated_at"] = study.updated_at
    cleaned = clean_tree(functions)
    if reader is not None:
        access.check_references(db, reader, access.evidence_refs(cleaned),
                                keep=access.evidence_refs(study.functions))
    study.functions = cleaned
    study.updated_at = access.next_updated_at(study.updated_at)
    result = db.rcm_studies.update_one(
        query, {"$set": {"functions": study.functions, "updated_at": study.updated_at}},
    )
    if result.matched_count == 0:
        raise access.EditConflict()
    return study


# ---- Evidence resolution (live validation) -----------------------------------

def resolve(db, study: RcmStudy, owner_id: str, hidden=frozenset()) -> dict:
    """The study as a dict with per-decision evidence statuses and a rollup."""
    fetch = evidence_fetcher(db, owner_id, hidden)
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
