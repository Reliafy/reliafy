"""Persistence for Accelerated Life Testing (ALT) models.

A saved ALT model stores the fit recipe (dataset + time/stress mapping +
distribution + life-stress relationship) and cached results. The live SurPyval
object is serialised (``to_dict``) so it can be rehydrated without a re-fit; a
bounded in-memory map links persistent ids to live fits as a fast path.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from collections import OrderedDict
from datetime import datetime, timezone

import numpy as np
import surpyval

from backend import alt as alt_fit
from backend.services import access
from backend.services import compute_core
from backend.services import rbd_jobs as rbd_jobs_service
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


def evaluate(db, model_id: str, use_stress: list, owner_id, ref_stress=None, *,
             mission_time=None, confidence=alt_fit.DEFAULT_CONFIDENCE) -> dict:
    """Reliability at a use-level stress for a saved ALT model, with its Wald
    confidence bounds (#231; :func:`bounds` gives the other methods)."""
    doc = get_model(db, model_id, owner_id)
    if doc is None:
        raise ModelNotFound(model_id)
    live = get_live_model(db, model_id, owner_id)
    life_model_id = (doc.spec or {}).get("life_model_id", "arrhenius")
    out = alt_fit.evaluate(live, use_stress, life_model_id, ref_stress=ref_stress,
                           mission_time=mission_time, confidence=alt_fit.check_confidence(confidence))
    # A fit with no finite maximum (#230) extrapolates nothing: the use-level
    # numbers travel with the warning, never without it.
    notice = (doc.results or {}).get("no_finite_maximum")
    if notice:
        out["no_finite_maximum"] = notice
    out["bounds_methods"] = (doc.results or {}).get("bounds_methods") or list(alt_fit.BOUND_METHODS)
    return out


BOOTSTRAP_PRO_PAYLOAD = {
    "detail": ("Bootstrap bounds refit the model hundreds of times, so they're a paid feature: subscribe to "
               "Pro or buy AI credits. Wald and likelihood-ratio bounds are free."),
    "code": "pro_required",
    "upgrade": True,
}


def _fit_inputs(db, doc: AltModelDoc) -> dict:
    """The saved model's data as :func:`backend.alt.build_inputs` reads it."""
    dataset = datasets_service.get_dataset(db, doc.dataset_id, owner_id=doc.owner_id)
    if dataset is None:
        raise FitError("The dataset this model was fitted to is no longer available.")
    spec = doc.spec or {}
    return alt_fit.build_inputs(datasets_service.load_dataframe(dataset), spec.get("mapping", {}),
                                spec.get("stress_cols", []))


def bounds(db, model_id: str, owner_id, *, uid: str, use_stress: list, method: str = "wald",
           confidence=alt_fit.DEFAULT_CONFIDENCE, mission_time=None, t_max=None,
           n_boot=alt_fit.DEFAULT_N_BOOT, entitled: bool = True) -> tuple[int, dict]:
    """Confidence bounds at a use stress for a saved ALT model (#231), by
    ``method``: Wald and likelihood ratio run here (free; the likelihood
    ratio refits the model from its data when the live one was rehydrated
    without it); the bootstrap is paid (``entitled``) and runs as a compute
    job when the queue is configured. Returns ``(status, payload)`` — 200
    with the bounds, 202 with a job to poll, 402 when not entitled."""
    doc = get_model(db, model_id, owner_id)
    if doc is None:
        raise ModelNotFound(model_id)
    method = alt_fit.check_method(method)
    confidence = alt_fit.check_confidence(confidence)
    spec = doc.spec or {}
    life_model_id = spec.get("life_model_id", "arrhenius")
    notice = (doc.results or {}).get("no_finite_maximum")

    def _done(payload: dict) -> dict:
        return {**payload, **({"no_finite_maximum": notice} if notice else {})}

    if method == "bootstrap":
        if not entitled:
            return 402, dict(BOOTSTRAP_PRO_PAYLOAD)
        n_boot = alt_fit.check_n_boot(n_boot)
        inputs = _fit_inputs(db, doc)
        if "bootstrap" not in alt_fit.bounds_methods(inputs):
            raise FitError("Bootstrap bounds aren't available for inspection (interval-censored) or "
                           "left-censored data. Use the Wald or likelihood-ratio method.")
        rows = int(np.shape(inputs["x"])[0])
        if rows > alt_fit.MAX_ROWS_BOOTSTRAP:
            raise FitError(f"Bootstrap bounds take up to {alt_fit.MAX_ROWS_BOOTSTRAP:,} data rows; this model "
                           f"has {rows:,}. With this much data the Wald bounds are reliable.")
        alt_fit._use_row(use_stress, life_model_id)  # checked before anything is queued
        request = compute_core.alt_bounds_request(
            inputs, distribution_id=spec.get("distribution_id", "weibull"), life_model_id=life_model_id,
            use_stress=use_stress, confidence=confidence, mission_time=mission_time, t_max=t_max,
            n_boot=n_boot, seed=alt_fit.BOOTSTRAP_SEED)
        key = "alt_bounds|" + model_id + "|" + hashlib.sha256(
            json.dumps(request, sort_keys=True, default=float).encode()).hexdigest()
        code, payload = rbd_jobs_service.run_alt_bounds(db, uid=uid, request=request, cache_key=key,
                                                        model_id=model_id)
        return code, (_done(payload) if code == 200 else payload)

    if method == "lr":
        # Checked before any refit: the search's cost grows with the rows.
        rows = int((doc.results or {}).get("n") or 0)
        if rows > alt_fit.MAX_ROWS_LR:
            raise FitError(f"Likelihood-ratio bounds take up to {alt_fit.MAX_ROWS_LR:,} data rows here; this "
                           f"model has {rows:,}. Use the Wald method, which suits this much data well.")
    live = get_live_model(db, model_id, owner_id)
    if method == "lr" and not alt_fit.has_data(live):
        live = _refit(db, doc)
    return 200, _done(alt_fit.use_level_bounds(
        live, use_stress, life_model_id, method=method, confidence=confidence, mission_time=mission_time,
        t_max=t_max))


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
