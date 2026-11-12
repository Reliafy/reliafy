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
from backend.units import canonical_unit
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
    from backend.services import dataset_reading

    spec = dataset_reading.with_reading(spec, dataset)
    df = datasets_service.load_dataframe(dataset)
    payload, cache_id = recurrent_fit.fit_spec(df, spec)
    doc = RecurrentModelDoc(
        id=uuid.uuid4().hex,
        name=name,
        owner_id=owner_id,
        dataset_id=dataset.id,
        spec=spec,
        results=payload,
        serialized=recurrent_fit.serialize_live(cache_id),
        surpyval_version=getattr(surpyval, "__version__", None),
        status="ready",
    )
    db.recurrent_models.insert_one(to_doc(doc))
    _remember_live(doc.id, cache_id)
    return doc


def save_from_params(db, name: str, model_id: str, params: list, horizon, unit: str, owner_id: str) -> RecurrentModelDoc:
    """Fit and persist a recurrent model from known parameters (no dataset)."""
    payload, cache_id = recurrent_fit.fit_from_params(model_id, params, horizon, unit)
    doc = RecurrentModelDoc(
        id=uuid.uuid4().hex,
        name=name,
        owner_id=owner_id,
        dataset_id="",
        spec={
            "params_only": True,
            "model_id": model_id,
            "params": [{"name": p["name"], "value": float(p["value"])} for p in params],
            "horizon": float(horizon),
            "unit": canonical_unit(unit),
        },
        results=payload,
        serialized=recurrent_fit.serialize_live(cache_id),
        surpyval_version=getattr(surpyval, "__version__", None),
        status="ready",
    )
    db.recurrent_models.insert_one(to_doc(doc))
    _remember_live(doc.id, cache_id)
    return doc


_MAPPING_KEYS = ("i", "x", "c", "n", "tl", "tr", "mode", "ws", "we")


def last_mapping(db, dataset_id: str, owner_id, hidden=frozenset(), columns=None) -> dict | None:
    """How the newest repairable model fitted from a dataset read its
    columns, so a new repairable fit from the dataset starts there (the end
    of record, the unit, covariates) rather than from a fresh guess:
    ``{mapping, unit, model_name}``, or None. Only a mapping whose columns
    are all still in the dataset counts."""
    names = {c.get("name") if isinstance(c, dict) else str(c) for c in columns or []}
    query = {"dataset_id": dataset_id, "owner_id": {"$in": access.owner_in(owner_id)}}
    for d in db.recurrent_models.find(query, {"spec": 1, "name": 1, "results.unit": 1}).sort("created_at", -1):
        if d["_id"] in hidden:
            continue
        spec = d.get("spec") or {}
        raw = spec.get("mapping") or {}
        mapping = {k: raw[k] for k in _MAPPING_KEYS if isinstance(raw.get(k), str) and raw.get(k)}
        z = [str(c) for c in (raw.get("z") or []) if c]
        if not (mapping.get("i") and mapping.get("x")):
            continue
        if names and not (set(mapping.values()) | set(z)) <= names:
            continue
        return {"mapping": {**mapping, **({"z": z} if z else {})},
                "unit": spec.get("unit") or (d.get("results") or {}).get("unit") or "",
                "model_name": d.get("name") or ""}
    return None


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


def set_notes(db, model_id: str, notes: str, owner_id: str) -> RecurrentModelDoc:
    """Set (or, with ``""``, clear) an owned recurrent model's notes (in its
    spec, as for non-repairable models). Never touches the fit."""
    doc = get_model(db, model_id, owner_id)
    if doc is None or doc.owner_id != owner_id:
        raise ModelNotFound(model_id)
    doc.updated_at = _now()
    update = {"$set": {"updated_at": doc.updated_at}}
    if notes:
        update["$set"]["spec.notes"] = notes
        doc.spec = {**(doc.spec or {}), "notes": notes}
    else:
        update["$unset"] = {"spec.notes": ""}
        doc.spec = {k: v for k, v in (doc.spec or {}).items() if k != "notes"}
    db.recurrent_models.update_one({"_id": model_id, "owner_id": owner_id}, update)
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
        # Prefer rehydrating the persisted fit; only re-fit if there's no
        # serialised model (older docs) or it fails to load.
        if doc.serialized:
            try:
                cid = recurrent_fit.restore_live(doc.serialized)
                _remember_live(doc.id, cid)
                return recurrent_fit.get_live(cid)
            except Exception:  # noqa: BLE001 - fall back to a fresh fit
                pass
        live = _refit(db, doc)
    return live


def shape_interval(db, doc: RecurrentModelDoc) -> dict | None:
    """``{"beta", "alpha", "ci"}``: a data-fitted Crow-AMSAA model's growth
    shape β, its scale and β's interval (90%; 95% for a fit saved before the rule) — as stored with the fit, or for
    a model saved before intervals were, from a fresh fit of its dataset
    (then stored on the model). None for a model built from parameters,
    another model family, or one whose dataset is gone."""
    spec = doc.spec or {}
    if spec.get("params_only") or spec.get("model_id", "crow_amsaa") != "crow_amsaa":
        return None
    params = list((doc.results or {}).get("params") or [])
    by_name = {p.get("name"): p for p in params}
    if "beta" not in by_name or "alpha" not in by_name:
        return None
    ci = by_name["beta"].get("ci")
    if not ci:
        try:
            live = _refit(db, doc)
        except Exception:  # noqa: BLE001 - dataset gone or no longer fits: no interval
            return None
        cis = recurrent_fit.param_intervals("crow_amsaa", live)
        if "beta" not in cis:
            return None
        params = [{**p, "ci": cis[p["name"]]} if p.get("name") in cis else p for p in params]
        db.recurrent_models.update_one({"_id": doc.id}, {"$set": {"results.params": params}})
        ci = cis["beta"]
    return {"beta": float(by_name["beta"]["value"]), "alpha": float(by_name["alpha"]["value"]),
            "ci": [float(ci[0]), float(ci[1])]}


def ensure_diagnostics(db, doc: RecurrentModelDoc) -> RecurrentModelDoc:
    """A data-fitted model saved before #81 (no ``trend_tests`` in its
    results): re-fit it from its dataset once to add the growth verdict from
    β's interval, the ROCOF / MTBF bounds, the demonstrated MTBF, both trend
    tests and the goodness-of-fit test, and store them with the model. Saved
    results the fit doesn't produce (a growth projection) are kept. The doc
    comes back unchanged for a model built from parameters, one already
    current, or one whose dataset is gone. A model with a cause column saved
    before #65 is re-fitted once the same way, to add the MCF of each cause."""
    spec = doc.spec or {}
    results = doc.results or {}
    stale_marks = bool((spec.get("mapping") or {}).get("mode")) and "by_cause" not in results
    if spec.get("params_only") or ("trend_tests" in results and not stale_marks) or not doc.dataset_id:
        return doc
    try:
        dataset = datasets_service.get_dataset(db, doc.dataset_id, owner_id=doc.owner_id)
        if dataset is None:
            return doc
        payload, cache_id = recurrent_fit.fit_spec(datasets_service.load_dataframe(dataset), spec)
    except Exception:  # noqa: BLE001 - the data no longer fits: leave the model as saved
        return doc
    fresh = {**results, **payload}
    db.recurrent_models.update_one({"_id": doc.id}, {"$set": {"results": fresh}})
    _remember_live(doc.id, cache_id)
    doc.results = fresh
    return doc


# ---- Results at today's rules, on read -------------------------------------------

_CURRENT: "OrderedDict[tuple, dict]" = OrderedDict()
_CURRENT_MAX = 64


def _stale_results(doc: RecurrentModelDoc) -> bool:
    """A data-fitted model whose stored results predate today's rules: its
    intervals at 95% (saved before the 90% rule: no ``ci_level``), or an
    imperfect-repair verdict from before it followed the restoration
    interval."""
    spec = doc.spec or {}
    results = doc.results or {}
    if spec.get("params_only") or not doc.dataset_id:
        return False
    if results.get("ci_level") != recurrent_fit.CI_LEVEL:
        return True
    return results.get("family") == "renewal" and "ci_method" not in (results.get("restoration") or {})


def current_results(db, doc: RecurrentModelDoc) -> RecurrentModelDoc:
    """The model with its results at today's rules. A model saved before
    them is re-fitted from its saved data on read (no goodness-of-fit
    bootstrap: its stored test is kept, a p-value doesn't depend on the
    interval level) and the fresh numbers shown; nothing is written back, so
    the saved document is unchanged, and the result is kept in memory only
    (per process, by the model's last update). A model whose data is gone
    keeps its stored numbers."""
    if not _stale_results(doc):
        return doc
    key = (doc.id, str(doc.updated_at))
    fresh = _CURRENT.get(key)
    if fresh is None:
        try:
            dataset = datasets_service.get_dataset(db, doc.dataset_id, owner_id=doc.owner_id)
            if dataset is None:
                return doc
            payload, cache_id = recurrent_fit.fit_spec(datasets_service.load_dataframe(dataset), doc.spec or {},
                                                       gof_test=False)
        except Exception:  # noqa: BLE001 - the data no longer fits: the stored numbers stand
            return doc
        stored = doc.results or {}
        fresh = {**stored, **payload, "gof_test": stored.get("gof_test", payload.get("gof_test")),
                 "recomputed_on_read": True}
        _CURRENT[key] = fresh
        while len(_CURRENT) > _CURRENT_MAX:
            _CURRENT.popitem(last=False)
        _remember_live(doc.id, cache_id)
    doc.results = fresh
    return doc


# ---- Reliability growth projection (#232) ---------------------------------------

def _dataset_frame(db, doc: RecurrentModelDoc):
    """The model's event data, or a FitError when it has none (built from
    parameters) or its dataset is gone."""
    if (doc.spec or {}).get("params_only") or not doc.dataset_id:
        raise FitError("A growth projection needs the test's failure data: this model was built from "
                       "parameters. Fit a model to event data with a failure-mode column.")
    dataset = datasets_service.get_dataset(db, doc.dataset_id, owner_id=doc.owner_id)
    if dataset is None:
        raise FitError("This model's dataset is gone, so there's no failure data to project from.")
    return datasets_service.load_dataframe(dataset)


def _projection_mapping(doc: RecurrentModelDoc, mode_column: str | None) -> dict:
    spec = doc.spec or {}
    mapping = dict(spec.get("mapping") or {})
    chosen = mode_column or (spec.get("projection") or {}).get("mode_column") or mapping.get("mode")
    if chosen:
        mapping["mode"] = chosen
    else:
        mapping.pop("mode", None)
    return mapping


def projection_view(db, doc: RecurrentModelDoc, mode_column: str | None = None) -> dict:
    """What the Projection panel needs before (or after) a run: the dataset's
    columns, the failure-mode column in use, its modes, and the saved
    settings and result."""
    spec = doc.spec or {}
    saved = spec.get("projection")
    out = {"available": False, "columns": [], "mode_column": None, "modes": [],
           "settings": saved, "result": (doc.results or {}).get("projection"),
           "default_fef": recurrent_fit.DEFAULT_FEF, **recurrent_fit.projection_basis(saved_model_kind(doc))}
    try:
        df = _dataset_frame(db, doc)
    except FitError as exc:
        return {**out, "reason": str(exc)}
    mapping = _projection_mapping(doc, mode_column)
    used = {mapping.get(k) for k in ("i", "x", "c", "n", "tl", "tr", "t", "ws", "we")} | set(mapping.get("z") or [])
    out["columns"] = [str(c) for c in df.columns if c not in used]
    if not mapping.get("mode"):
        return {**out, "available": True, "reason": "Choose the column that holds each failure's mode."}
    try:
        out["modes"] = recurrent_fit.failure_modes(df, mapping)
    except FitError as exc:
        return {**out, "available": True, "mode_column": mapping["mode"], "reason": str(exc)}
    return {**out, "available": True, "mode_column": mapping["mode"]}


def run_projection(db, doc: RecurrentModelDoc, *, fef, bc=None, test_end=None,
                   mode_column: str | None = None) -> dict:
    df = _dataset_frame(db, doc)
    mapping = _projection_mapping(doc, mode_column)
    unit = (doc.results or {}).get("unit") or (doc.spec or {}).get("unit", "")
    return recurrent_fit.growth_projection(df, mapping, fef, bc=bc, test_end=test_end, unit=unit,
                                           saved_model=saved_model_kind(doc))


def saved_model_kind(doc: RecurrentModelDoc) -> str:
    """The saved model's kind: crow_amsaa, duane or hpp."""
    return (doc.spec or {}).get("model_id") or ((doc.results or {}).get("model") or {}).get("id") or "crow_amsaa"


def save_projection(db, doc: RecurrentModelDoc, payload: dict, mode_column: str | None, owner_id: str) -> None:
    """Keep the projection's settings (in the spec) and result with the model."""
    settings = {"mode_column": _projection_mapping(doc, mode_column).get("mode"),
                "fef": payload.get("fef") or {}, "bc": payload.get("bc") or [],
                "test_end": payload.get("test_end")}
    now = _now()
    db.recurrent_models.update_one(
        {"_id": doc.id, "owner_id": owner_id},
        {"$set": {"spec.projection": settings, "results.projection": payload, "updated_at": now}},
    )
    doc.spec = {**(doc.spec or {}), "projection": settings}
    doc.results = {**(doc.results or {}), "projection": payload}
    doc.updated_at = now


def _refit(db, doc: RecurrentModelDoc):
    spec = doc.spec or {}
    if spec.get("params_only"):
        _, cache_id = recurrent_fit.fit_from_params(
            spec.get("model_id", "crow_amsaa"),
            spec.get("params", []),
            spec.get("horizon", 1.0),
            spec.get("unit", ""),
        )
        _remember_live(doc.id, cache_id)
        return recurrent_fit.get_live(cache_id)
    dataset = datasets_service.get_dataset(db, doc.dataset_id, owner_id=doc.owner_id)
    if dataset is None:
        raise ModelNotFound(doc.id)
    df = datasets_service.load_dataframe(dataset)
    # Only the live model is wanted: no goodness-of-fit bootstrap.
    _, cache_id = recurrent_fit.fit_spec(df, doc.spec or {}, gof_test=False)
    _remember_live(doc.id, cache_id)
    return recurrent_fit.get_live(cache_id)
