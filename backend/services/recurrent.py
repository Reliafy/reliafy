"""Persistence for recurrent-event (repairable-system) models.

A saved recurrent model stores the fit recipe (dataset + column mapping + model
form) and cached results. The live SurPyval object can't be pickled, so — like
the degradation models — a bounded in-memory map links persistent ids to live
fits, rebuilt on demand from the dataset + spec.
"""

from __future__ import annotations

import uuid
from collections import OrderedDict
from datetime import datetime, timezone

import surpyval

from backend import recurrent as recurrent_fit
from backend.services import access
from backend.db import from_doc, to_doc
from backend.fitting import FitError
from backend.schema import RecurrentModelDoc
from backend.services import datasets as datasets_service

_LIVE: "OrderedDict[str, str]" = OrderedDict()
_LIVE_MAX = 64


class ModelNotFound(KeyError):
    """Raised when a recurrent model id is unknown / not visible."""


def _now():
    return datetime.now(timezone.utc)


def _list_query(owner_id, shared=frozenset()):
    query = {"owner_id": {"$in": access.owner_in(owner_id)}}
    if shared:
        return {"$or": [query, {"_id": {"$in": sorted(shared)}}]}
    return query


def save_model(db, name: str, dataset, spec: dict, owner_id: str) -> RecurrentModelDoc:
    """Fit and persist a recurrent model. Raises ``FitError`` on a bad fit."""
    df = datasets_service.load_dataframe(dataset)
    payload, cache_id = recurrent_fit.fit(
        df,
        spec.get("mapping", {}),
        model_id=spec.get("model_id", "crow_amsaa"),
        unit=spec.get("unit", ""),
    )
    doc = RecurrentModelDoc(
        id=uuid.uuid4().hex,
        name=name,
        owner_id=owner_id,
        dataset_id=dataset.id,
        spec=spec,
        results=payload,
        surpyval_version=getattr(surpyval, "__version__", None),
        status="ready",
    )
    db.recurrent_models.insert_one(to_doc(doc))
    _remember_live(doc.id, cache_id)
    return doc


def list_models(db, owner_id, hidden=frozenset(), shared=frozenset()) -> list[RecurrentModelDoc]:
    return [
        from_doc(RecurrentModelDoc, d)
        for d in db.recurrent_models.find(_list_query(owner_id, shared)).sort("created_at", -1)
        if d["_id"] not in hidden
    ]


def get_model(db, model_id: str, owner_id=None) -> RecurrentModelDoc | None:
    query = {"_id": model_id}
    if owner_id is not None:
        query["owner_id"] = {"$in": access.owner_in(owner_id)}
    return from_doc(RecurrentModelDoc, db.recurrent_models.find_one(query))


def rename_model(db, model_id: str, name: str, owner_id: str) -> RecurrentModelDoc:
    doc = get_model(db, model_id, owner_id)
    if doc is None or doc.owner_id != owner_id:
        raise ModelNotFound(model_id)
    doc.name = name
    doc.updated_at = _now()
    db.recurrent_models.update_one(
        {"_id": model_id, "owner_id": owner_id},
        {"$set": {"name": name, "updated_at": doc.updated_at}},
    )
    return doc


def delete_model(db, model_id: str, owner_id: str) -> None:
    result = db.recurrent_models.delete_one({"_id": model_id, "owner_id": owner_id})
    if result.deleted_count == 0:
        raise ModelNotFound(model_id)
    _LIVE.pop(model_id, None)


def _remember_live(model_id: str, cache_id: str) -> None:
    _LIVE[model_id] = cache_id
    while len(_LIVE) > _LIVE_MAX:
        _LIVE.popitem(last=False)


def get_live_model(db, model_id: str, owner_id):
    """The live (fitted) parametric model for a saved id, re-fitting on a miss."""
    doc = get_model(db, model_id, owner_id)
    if doc is None:
        raise ModelNotFound(model_id)
    cache_id = _LIVE.get(model_id)
    live = recurrent_fit.get_live(cache_id) if cache_id else None
    if live is None:
        live = _refit(db, doc)
    return live


def _refit(db, doc: RecurrentModelDoc):
    dataset = datasets_service.get_dataset(db, doc.dataset_id, owner_id=doc.owner_id)
    if dataset is None:
        raise ModelNotFound(doc.id)
    df = datasets_service.load_dataframe(dataset)
    spec = doc.spec or {}
    _, cache_id = recurrent_fit.fit(
        df, spec.get("mapping", {}),
        model_id=spec.get("model_id", "crow_amsaa"),
        unit=spec.get("unit", ""),
    )
    _remember_live(doc.id, cache_id)
    return recurrent_fit.get_live(cache_id)
