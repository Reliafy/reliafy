"""Persistence and predictions for degradation models and tracked items.

A saved degradation model stores the fit recipe (dataset + column mapping +
threshold + path form) and cached results. The live SurPyval model can't be
pickled, so — exactly like :mod:`backend.services.models` — a bounded in-memory
map links persistent model ids to live fits, rebuilt on demand from the
dataset + spec.

Tracked items are the fleet-monitoring half: each holds an asset's measurement
history and a cached threshold-crossing prediction, recomputed whenever a
measurement is appended (never on reads, so listing a fleet is cheap).
"""

from __future__ import annotations

import uuid
from collections import OrderedDict
from datetime import datetime, timezone

import surpyval

from backend import degradation as degradation_fit
from backend.services import access
from backend.db import from_doc, to_doc
from backend.fitting import FitError
from backend.schema import DegradationModelDoc, TrackedItem
from backend.services import datasets as datasets_service

_LIVE: "OrderedDict[str, str]" = OrderedDict()
_LIVE_MAX = 64



def _list_query(owner_id, shared=frozenset()):
    """Owner-scoped filter, optionally unioned with directly-shared ids."""
    query = {"owner_id": {"$in": access.owner_in(owner_id)}}
    if shared:
        return {"$or": [query, {"_id": {"$in": sorted(shared)}}]}
    return query

class ModelNotFound(KeyError):
    """Raised when a degradation model id is unknown / not visible."""


class ItemNotFound(KeyError):
    """Raised when a tracked item id is unknown / not visible."""


def _now():
    return datetime.now(timezone.utc)


# ---- Models ----------------------------------------------------------------

def save_model(db, name: str, dataset, spec: dict, owner_id: str) -> DegradationModelDoc:
    """Fit and persist a degradation model. Raises ``FitError`` on a bad fit."""
    df = datasets_service.load_dataframe(dataset)
    payload, cache_id = degradation_fit.fit(
        df,
        spec.get("mapping", {}),
        spec.get("threshold"),
        path=spec.get("path", "best"),
        distribution_id=spec.get("distribution_id", "weibull"),
        population_method=spec.get("population_method", "moments"),
        unit=spec.get("unit", ""),
        measurement_unit=spec.get("measurement_unit", ""),
    )
    doc = DegradationModelDoc(
        id=uuid.uuid4().hex,
        name=name,
        owner_id=owner_id,
        dataset_id=dataset.id,
        spec=spec,
        results=payload,
        surpyval_version=getattr(surpyval, "__version__", None),
        status="ready",
    )
    db.degradation_models.insert_one(to_doc(doc))
    _remember_live(doc.id, cache_id)
    return doc


def list_models(db, owner_id: str | list[str], hidden=frozenset(), shared=frozenset()) -> list[DegradationModelDoc]:
    return [
        from_doc(DegradationModelDoc, d)
        for d in db.degradation_models.find(
            _list_query(owner_id, shared)
        ).sort("created_at", -1)
        if d["_id"] not in hidden
    ]


def get_model(db, model_id: str, owner_id: str | list[str] | None = None) -> DegradationModelDoc | None:
    query = {"_id": model_id}
    if owner_id is not None:
        query["owner_id"] = {"$in": access.owner_in(owner_id)}
    return from_doc(DegradationModelDoc, db.degradation_models.find_one(query))


def rename_model(db, model_id: str, name: str, owner_id: str) -> DegradationModelDoc:
    doc = get_model(db, model_id, owner_id)
    if doc is None or doc.owner_id != owner_id:
        raise ModelNotFound(model_id)  # unknown, not owned, or read-only sample
    doc.name = name
    doc.updated_at = _now()
    db.degradation_models.update_one(
        {"_id": model_id, "owner_id": owner_id},
        {"$set": {"name": name, "updated_at": doc.updated_at}},
    )
    return doc


def delete_model(db, model_id: str, owner_id: str) -> None:
    result = db.degradation_models.delete_one({"_id": model_id, "owner_id": owner_id})
    if result.deleted_count == 0:
        raise ModelNotFound(model_id)
    db.tracked_items.delete_many({"model_id": model_id, "owner_id": owner_id})
    _LIVE.pop(model_id, None)


def _remember_live(model_id: str, cache_id: str) -> None:
    _LIVE[model_id] = cache_id
    while len(_LIVE) > _LIVE_MAX:
        _LIVE.popitem(last=False)


def get_live_model(db, model_id: str, owner_id: str | list[str]):
    """The live (fitted) SurPyval model for a saved id, re-fitting on a miss."""
    doc = get_model(db, model_id, owner_id)
    if doc is None:
        raise ModelNotFound(model_id)

    cache_id = _LIVE.get(model_id)
    live = degradation_fit.get_live(cache_id) if cache_id else None
    if live is None:
        live = _refit(db, doc)
    return live


def _refit(db, doc: DegradationModelDoc):
    dataset = datasets_service.get_dataset(db, doc.dataset_id, owner_id=doc.owner_id)
    if dataset is None:
        raise ModelNotFound(doc.id)
    df = datasets_service.load_dataframe(dataset)
    spec = doc.spec or {}
    _, cache_id = degradation_fit.fit(
        df,
        spec.get("mapping", {}),
        spec.get("threshold"),
        path=spec.get("path", "best"),
        distribution_id=spec.get("distribution_id", "weibull"),
        population_method=spec.get("population_method", "moments"),
        unit=spec.get("unit", ""),
        measurement_unit=spec.get("measurement_unit", ""),
    )
    _remember_live(doc.id, cache_id)
    return degradation_fit.get_live(cache_id)


# ---- Tracked items ----------------------------------------------------------

def _clean_measurements(measurements) -> list[dict]:
    """Validate and normalise ``[{t, y}, …]``: numeric, sorted by t, exact-t
    duplicates collapsed (last value wins)."""
    cleaned: dict[float, float] = {}
    for m in measurements or []:
        try:
            t = float(m["t"])
            y = float(m["y"])
        except (KeyError, TypeError, ValueError):
            raise FitError("Each measurement needs numeric 't' (time) and 'y' (value).")
        if not (t >= 0):
            raise FitError("Measurement times must be non-negative numbers.")
        cleaned[t] = y
    if not cleaned:
        raise FitError("At least one measurement is required.")
    return [{"t": t, "y": cleaned[t]} for t in sorted(cleaned)]


def create_item(db, model_id: str, name: str, measurements, owner_id: str,
                meta: dict | None = None, fleet_id: str | None = None) -> TrackedItem:
    doc = get_model(db, model_id, owner_id)
    if doc is None:
        raise ModelNotFound(model_id)
    if not (name or "").strip():
        raise FitError("The item needs a name.")

    item = TrackedItem(
        id=uuid.uuid4().hex,
        model_id=model_id,
        fleet_id=fleet_id,
        name=name.strip(),
        owner_id=owner_id,
        meta=meta or {},
        measurements=_clean_measurements(measurements),
    )
    item.prediction = _predict(db, model_id, owner_id, item.measurements)
    db.tracked_items.insert_one(to_doc(item))
    return item


def list_items(db, model_id: str, owner_id: str | list[str], hidden=frozenset(),
               fleet_id: str | None = None) -> list[TrackedItem]:
    """The owner's items on this model, plus sample items, minus hidden ones."""
    query = {"model_id": model_id, "owner_id": {"$in": access.owner_in(owner_id)}}
    if fleet_id is not None:
        query["fleet_id"] = fleet_id
    return [
        from_doc(TrackedItem, d)
        for d in db.tracked_items.find(query).sort("created_at", -1)
        if d["_id"] not in hidden
    ]


def get_item(db, model_id: str, item_id: str, owner_id: str) -> TrackedItem | None:
    return from_doc(
        TrackedItem,
        db.tracked_items.find_one(
            {"_id": item_id, "model_id": model_id, "owner_id": {"$in": access.owner_in(owner_id)}}
        ),
    )


def append_measurement(db, model_id: str, item_id: str, t, y, owner_id: str) -> TrackedItem:
    item = get_item(db, model_id, item_id, owner_id)
    if item is None or item.owner_id != owner_id:
        raise ItemNotFound(item_id)  # unknown, not owned, or read-only sample
    try:
        t = float(t)
        y = float(y)
    except (TypeError, ValueError):
        raise FitError("Measurement needs numeric 't' (time) and 'y' (value).")
    last_t = item.measurements[-1]["t"] if item.measurements else -1.0
    if t <= last_t:
        raise FitError(f"Measurement time must be after the last one ({last_t:g}).")

    item.measurements = [*item.measurements, {"t": t, "y": y}]
    item.prediction = _predict(db, model_id, owner_id, item.measurements)
    item.updated_at = _now()
    db.tracked_items.update_one(
        {"_id": item_id, "owner_id": owner_id},
        {"$set": {
            "measurements": item.measurements,
            "prediction": item.prediction,
            "updated_at": item.updated_at,
        }},
    )
    return item


def delete_item(db, model_id: str, item_id: str, owner_id: str) -> None:
    result = db.tracked_items.delete_one(
        {"_id": item_id, "model_id": model_id, "owner_id": owner_id}
    )
    if result.deleted_count == 0:
        raise ItemNotFound(item_id)


def refresh_prediction(db, model_id: str, item: TrackedItem, owner_id: str) -> TrackedItem:
    """Recompute and persist a missing/error prediction (used on item reads)."""
    item.prediction = _predict(db, model_id, owner_id, item.measurements)
    db.tracked_items.update_one(
        {"_id": item.id}, {"$set": {"prediction": item.prediction}}
    )
    return item


def _predict(db, model_id: str, owner_id: str, measurements: list[dict]) -> dict:
    """Compute the prediction blob; fit problems become method="error" blobs so
    a measurement append never fails."""
    try:
        live = get_live_model(db, model_id, owner_id)
    except (ModelNotFound, FitError) as exc:
        return {
            "predicted_at": _now().isoformat(),
            "n_measurements": len(measurements),
            "method": "error",
            "detail": str(exc),
        }
    t = [m["t"] for m in measurements]
    y = [m["y"] for m in measurements]
    return degradation_fit.predict_item(live, t, y)


# ---- Tracked fleets ----------------------------------------------------------
#
# Named groups of tracked items against one model. Legacy items created
# before fleets existed carry no fleet_id; ``adopt_orphan_items`` folds them
# into an auto-created fleet per (owner, model) the first time fleets are
# listed, so nothing is ever stranded.

def create_tracked_fleet(db, name: str, model_id: str, owner_id: str) -> "TrackedFleet":
    from backend.schema import TrackedFleet

    if not (name or "").strip():
        raise FitError("The fleet needs a name.")
    if get_model(db, model_id, owner_id) is None:
        raise ModelNotFound(model_id)
    fleet = TrackedFleet(id=uuid.uuid4().hex, name=name.strip(),
                         owner_id=owner_id, model_id=model_id)
    db.tracked_fleets.insert_one(to_doc(fleet))
    return fleet


def adopt_orphan_items(db, owner_id: str) -> None:
    """Fold pre-fleet items into an auto-created fleet per (owner, model)."""
    orphans = list(db.tracked_items.find({
        "owner_id": owner_id,
        "$or": [{"fleet_id": None}, {"fleet_id": {"$exists": False}}],
    }))
    if not orphans:
        return
    from backend.schema import TrackedFleet

    for model_id in {o["model_id"] for o in orphans}:
        model = get_model(db, model_id, owner_id)
        existing = db.tracked_fleets.find_one({"owner_id": owner_id, "model_id": model_id})
        if existing is None:
            fleet = TrackedFleet(
                id=uuid.uuid4().hex,
                name=f"{model.name} — fleet" if model else "Tracked fleet",
                owner_id=owner_id, model_id=model_id,
            )
            db.tracked_fleets.insert_one(to_doc(fleet))
            fid = fleet.id
        else:
            fid = existing["_id"]
        db.tracked_items.update_many(
            {"owner_id": owner_id, "model_id": model_id,
             "$or": [{"fleet_id": None}, {"fleet_id": {"$exists": False}}]},
            {"$set": {"fleet_id": fid}},
        )


def list_tracked_fleets(db, owner_id, hidden=frozenset()) -> list:
    from backend.schema import TrackedFleet

    return [
        from_doc(TrackedFleet, d)
        for d in db.tracked_fleets.find(
            {"owner_id": {"$in": access.owner_in(owner_id)}}
        ).sort("created_at", -1)
        if d["_id"] not in hidden
    ]


def get_tracked_fleet(db, fleet_id: str, owner_id=None):
    from backend.schema import TrackedFleet

    query = {"_id": fleet_id}
    if owner_id is not None:
        query["owner_id"] = {"$in": access.owner_in(owner_id)}
    return from_doc(TrackedFleet, db.tracked_fleets.find_one(query))


def rename_tracked_fleet(db, fleet_id: str, name: str, owner_id: str):
    fleet = get_tracked_fleet(db, fleet_id, owner_id)
    if fleet is None or fleet.owner_id != owner_id:
        raise ModelNotFound(fleet_id)
    fleet.name = name
    fleet.updated_at = _now()
    db.tracked_fleets.update_one(
        {"_id": fleet_id, "owner_id": owner_id},
        {"$set": {"name": name, "updated_at": fleet.updated_at}},
    )
    return fleet


def delete_tracked_fleet(db, fleet_id: str, owner_id: str) -> None:
    result = db.tracked_fleets.delete_one({"_id": fleet_id, "owner_id": owner_id})
    if result.deleted_count == 0:
        raise ModelNotFound(fleet_id)
    db.tracked_items.delete_many({"fleet_id": fleet_id, "owner_id": owner_id})


def health_of(prediction: dict | None) -> str:
    """One item's health bucket — mirrors the frontend badge thresholds."""
    if not prediction or prediction.get("method") == "error":
        return "monitoring"
    if (prediction.get("prob_never_fails") or 0) > 0.5:
        return "monitoring"
    p = prediction.get("prob_failed")
    if p is None:
        return "monitoring"
    if p >= 0.5:
        return "replace"
    if p >= 0.05:
        return "plan"
    return "healthy"


def tracking_rollup(items) -> dict:
    """Fleet-health summary for a set of tracked items."""
    rollup = {"healthy": 0, "plan": 0, "replace": 0, "monitoring": 0}
    next_crossing = None
    for it in items:
        rollup[health_of(it.prediction)] += 1
        ft = (it.prediction or {}).get("failure_time")
        if ft is not None and (next_crossing is None or ft < next_crossing):
            next_crossing = ft
    return {**rollup, "next_crossing": next_crossing}


def list_fleet_items(db, fleet, owner_id, hidden=frozenset()) -> list[TrackedItem]:
    return list_items(db, fleet.model_id, owner_id, hidden, fleet_id=fleet.id)
