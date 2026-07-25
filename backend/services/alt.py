"""Persistence for Accelerated Life Testing (ALT) models.

A saved ALT model stores the fit recipe (dataset + time/stress mapping +
distribution + life-stress relationship) and cached results. The live SurPyval
object is serialised (``to_dict``) so it can be rehydrated without a re-fit; a
bounded in-memory map links persistent ids to live fits as a fast path.
"""

from __future__ import annotations

import uuid
from collections import OrderedDict
from datetime import datetime, timezone

import surpyval

from backend import alt as alt_fit
from backend.services import access
from backend.db import from_doc, to_doc
from backend.fitting import FitError
from backend.schema import AltModelDoc
from backend.services import datasets as datasets_service

_LIVE: "OrderedDict[str, str]" = OrderedDict()
_LIVE_MAX = 64


class ModelNotFound(KeyError):
    """Raised when an ALT model id is unknown / not visible."""


def _now():
    return datetime.now(timezone.utc)


def _list_query(owner_id, shared=frozenset()):
    query = {"owner_id": {"$in": access.owner_in(owner_id)}}
    if shared:
        return {"$or": [query, {"_id": {"$in": sorted(shared)}}]}
    return query


def _with_evaluate_path(results: dict, model_id: str) -> dict:
    """Point the results at the use-stress evaluate endpoint for this model."""
    fns = dict(results.get("functions") or {})
    fns["evaluate_path"] = f"/api/alt/models/{model_id}/evaluate"
    results = dict(results)
    results["functions"] = fns
    return results


def save_model(db, name: str, dataset, spec: dict, owner_id: str) -> AltModelDoc:
    """Fit and persist an ALT model. Raises ``FitError`` on a bad fit."""
    df = datasets_service.load_dataframe(dataset)
    payload, cache_id = alt_fit.fit(
        df,
        spec.get("mapping", {}),
        spec.get("stress_cols", []),
        distribution_id=spec.get("distribution_id", "weibull"),
        life_model_id=spec.get("life_model_id", "arrhenius"),
        unit=spec.get("unit", ""),
        stress_labels=spec.get("stress_labels"),
    )
    model_id = uuid.uuid4().hex
    doc = AltModelDoc(
        id=model_id,
        name=name,
        owner_id=owner_id,
        dataset_id=dataset.id,
        spec=spec,
        results=_with_evaluate_path(payload, model_id),
        serialized=alt_fit.serialize_live(cache_id),
        surpyval_version=getattr(surpyval, "__version__", None),
        status="ready",
    )
    db.alt_models.insert_one(to_doc(doc))
    _remember_live(doc.id, cache_id)
    return doc


def list_models(db, owner_id, hidden=frozenset(), shared=frozenset()) -> list[AltModelDoc]:
    return [
        from_doc(AltModelDoc, d)
        for d in db.alt_models.find(_list_query(owner_id, shared)).sort("created_at", -1)
        if d["_id"] not in hidden
    ]


def get_model(db, model_id: str, owner_id=None) -> AltModelDoc | None:
    query = {"_id": model_id}
    if owner_id is not None:
        query["owner_id"] = {"$in": access.owner_in(owner_id)}
    return from_doc(AltModelDoc, db.alt_models.find_one(query))


def rename_model(db, model_id: str, name: str, owner_id: str) -> AltModelDoc:
    doc = get_model(db, model_id, owner_id)
    if doc is None or doc.owner_id != owner_id:
        raise ModelNotFound(model_id)
    doc.name = name
    doc.updated_at = _now()
    db.alt_models.update_one(
        {"_id": model_id, "owner_id": owner_id},
        {"$set": {"name": name, "updated_at": doc.updated_at}},
    )
    return doc


def delete_model(db, model_id: str, owner_id: str) -> None:
    result = db.alt_models.delete_one({"_id": model_id, "owner_id": owner_id})
    if result.deleted_count == 0:
        raise ModelNotFound(model_id)
    _LIVE.pop(model_id, None)


def evaluate(db, model_id: str, use_stress: list, owner_id, ref_stress=None) -> dict:
    """Reliability at a use-level stress for a saved ALT model."""
    doc = get_model(db, model_id, owner_id)
    if doc is None:
        raise ModelNotFound(model_id)
    live = get_live_model(db, model_id, owner_id)
    life_model_id = (doc.spec or {}).get("life_model_id", "arrhenius")
    return alt_fit.evaluate(live, use_stress, life_model_id, ref_stress=ref_stress)


def _remember_live(model_id: str, cache_id: str) -> None:
    _LIVE[model_id] = cache_id
    while len(_LIVE) > _LIVE_MAX:
        _LIVE.popitem(last=False)


def get_live_model(db, model_id: str, owner_id):
    """The live (fitted) ALT model for a saved id, rehydrating or re-fitting."""
    doc = get_model(db, model_id, owner_id)
    if doc is None:
        raise ModelNotFound(model_id)
    cache_id = _LIVE.get(model_id)
    live = alt_fit.get_live(cache_id) if cache_id else None
    if live is None:
        if doc.serialized:
            try:
                cid = alt_fit.restore_live(doc.serialized)
                _remember_live(doc.id, cid)
                return alt_fit.get_live(cid)
            except Exception:  # noqa: BLE001 - fall back to a fresh fit
                pass
        live = _refit(db, doc)
    return live


def _refit(db, doc: AltModelDoc):
    dataset = datasets_service.get_dataset(db, doc.dataset_id, owner_id=doc.owner_id)
    if dataset is None:
        raise ModelNotFound(doc.id)
    df = datasets_service.load_dataframe(dataset)
    spec = doc.spec or {}
    _, cache_id = alt_fit.fit(
        df,
        spec.get("mapping", {}),
        spec.get("stress_cols", []),
        distribution_id=spec.get("distribution_id", "weibull"),
        life_model_id=spec.get("life_model_id", "arrhenius"),
        unit=spec.get("unit", ""),
        stress_labels=spec.get("stress_labels"),
    )
    _remember_live(doc.id, cache_id)
    return alt_fit.get_live(cache_id)
