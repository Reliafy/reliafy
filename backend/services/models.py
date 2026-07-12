"""Model persistence and re-fit-on-demand.

A saved Model stores only the recipe (dataset + fit spec) and a cache of the
computed results. Fitted SurPyval models can't be pickled, so when the
calculator needs a *live* model (to evaluate functions at covariate values) we
re-fit from the dataset + spec and cache the live model in memory, keyed by the
persistent model id.
"""

from __future__ import annotations

import uuid
from collections import OrderedDict
from datetime import datetime, timezone

import surpyval

from backend import fitting
from backend.services import access
from backend.db import from_doc, to_doc
from backend.schema import Model
from backend.services import datasets as datasets_service

# Maps a persistent model id -> the ephemeral fitting cache id of its live,
# re-fitted model. Bounded; entries are rebuilt on a miss.
_LIVE: "OrderedDict[str, str]" = OrderedDict()
_LIVE_MAX = 64



def _list_query(owner_id, shared=frozenset()):
    """Owner-scoped filter, optionally unioned with directly-shared ids."""
    query = {"owner_id": {"$in": access.owner_in(owner_id)}}
    if shared:
        return {"$or": [query, {"_id": {"$in": sorted(shared)}}]}
    return query

class ModelNotFound(KeyError):
    """Raised when a model id is unknown."""


def _spec(model: Model) -> dict:
    return model.spec or {}


def save_model(
    db,
    name: str,
    dataset,
    distribution_id: str,
    mapping: dict,
    covariates: list | None,
    formula: str | None,
    unit: str | None = None,
    owner_id: str = "",
    options: dict | None = None,
) -> Model:
    """Fit and persist a model. Raises ``fitting.FitError`` on a bad fit."""
    df = datasets_service.load_dataframe(dataset)
    result = fitting.fit(
        distribution_id, df, mapping, covariates, formula, unit, options=options
    )
    # "Best fit" resolves to a concrete winner at fit time: persist that, so
    # the saved model (and its refit-on-demand spec) is stable forever.
    resolved_id = result.get("distribution_id", distribution_id)

    model = Model(
        id=uuid.uuid4().hex,
        name=name,
        owner_id=owner_id or dataset.owner_id,
        dataset_id=dataset.id,
        kind=result.get("kind", "distribution"),
        distribution_id=resolved_id,
        spec={
            "distribution_id": resolved_id,
            "mapping": {k: v for k, v in mapping.items() if v},
            "covariates": list(covariates or []),
            "formula": formula or None,
            "unit": (unit or "").strip(),
            "options": result.get("options") or None,
        },
        results=result,
        surpyval_version=getattr(surpyval, "__version__", None),
        status="ready",
    )
    db.models.insert_one(to_doc(model))
    return model


def list_models(db, owner_id: str | list[str], hidden=frozenset(), shared=frozenset()) -> list[Model]:
    """The owner's models plus the shared samples, minus hidden samples."""
    return [
        from_doc(Model, m)
        for m in db.models.find(
            _list_query(owner_id, shared)
        ).sort("created_at", -1)
        if m["_id"] not in hidden
    ]


def get_model(db, model_id: str, owner_id: str | list[str] | None = None) -> Model | None:
    """Fetch a model by id. Shared sample models are visible to every owner."""
    query = {"_id": model_id}
    if owner_id is not None:
        query["owner_id"] = {"$in": access.owner_in(owner_id)}
    return from_doc(Model, db.models.find_one(query))


def update_fit(
    db,
    model_id: str,
    owner_id: str,
    distribution_id: str,
    mapping: dict,
    covariates: list | None,
    formula: str | None,
    unit: str | None,
    options: dict | None,
) -> Model:
    """Refit a saved model in place with a new fit spec (same dataset).

    The model keeps its id, so everything that references it — RCM evidence,
    RBD blocks, fleet forecasts — sees the updated fit live, exactly like the
    rest of the evidence-linking behaviour. Raises ``fitting.FitError`` on a
    bad fit (the stored model is untouched in that case).
    """
    model = get_model(db, model_id, owner_id)
    if model is None or model.owner_id != owner_id:
        raise ModelNotFound(model_id)
    dataset = datasets_service.get_dataset(db, model.dataset_id, owner_id=model.owner_id)
    if dataset is None:
        raise fitting.FitError(
            "The model's dataset no longer exists, so it can't be refit."
        )
    df = datasets_service.load_dataframe(dataset)
    result = fitting.fit(
        distribution_id, df, mapping, covariates, formula, unit, options=options
    )
    resolved_id = result.get("distribution_id", distribution_id)

    model.results = result
    model.kind = result.get("kind", "distribution")
    model.distribution_id = resolved_id
    model.spec = {
        "distribution_id": resolved_id,
        "mapping": {k: v for k, v in mapping.items() if v},
        "covariates": list(covariates or []),
        "formula": formula or None,
        "unit": (unit or "").strip(),
        "options": result.get("options") or None,
    }
    model.updated_at = datetime.now(timezone.utc)
    db.models.update_one(
        {"_id": model_id, "owner_id": owner_id},
        {"$set": {
            "results": result,
            "kind": model.kind,
            "distribution_id": resolved_id,
            "spec": model.spec,
            "surpyval_version": getattr(surpyval, "__version__", None),
            "updated_at": model.updated_at,
        }},
    )
    # The cached live model (refit-on-demand) is stale now.
    _LIVE.pop(model_id, None)
    return model


def rename_model(db, model_id: str, name: str, owner_id: str) -> Model:
    model = get_model(db, model_id, owner_id)
    if model is None or model.owner_id != owner_id:
        # Unknown, not owned, or a shared sample (read-only) -> not renamable.
        raise ModelNotFound(model_id)
    model.name = name
    model.updated_at = datetime.now(timezone.utc)
    db.models.update_one(
        {"_id": model_id, "owner_id": owner_id},
        {"$set": {"name": model.name, "updated_at": model.updated_at}},
    )
    return model


def delete_model(db, model_id: str, owner_id: str) -> None:
    result = db.models.delete_one({"_id": model_id, "owner_id": owner_id})
    if result.deleted_count == 0:
        raise ModelNotFound(model_id)
    _LIVE.pop(model_id, None)


def public_results(model: Model) -> dict:
    """Results shaped for the client, with the evaluate path pointed at this
    saved model (so the calculator re-evaluates via the persistent id)."""
    results = dict(model.results or {})
    functions = results.get("functions")
    if functions and functions.get("model_id"):
        functions = dict(functions)
        functions["model_id"] = model.id
        functions["evaluate_path"] = f"/api/models/{model.id}/evaluate"
        results["functions"] = functions
    return results


def evaluate(db, model_id: str, values: dict, owner_id: str) -> dict:
    """Evaluate the model's functions at covariate ``values``, re-fitting if the
    live model isn't cached."""
    model = get_model(db, model_id, owner_id)
    if model is None:
        raise ModelNotFound(model_id)

    cache_id = _LIVE.get(model_id)
    if cache_id is None or cache_id not in fitting._MODEL_STORE:
        cache_id = _refit(model)
        _LIVE[model_id] = cache_id
        while len(_LIVE) > _LIVE_MAX:
            _LIVE.popitem(last=False)

    return fitting.evaluate(cache_id, values)


def get_live_model(db, model_id: str, owner_id: str | list[str]) -> dict | None:
    """Return the live (re-fitted) model entry for a saved model id.

    The entry is the one cached by :mod:`backend.fitting`:
    ``{"model", "grid", "fields"}`` — used by the RBD analysis to evaluate a
    proportional-hazards node's reliability at chosen covariate values. Scoped
    to ``owner_id`` so a user can't embed another user's model id in their RBD
    graph and read it. Returns ``None`` if the model id is unknown/not owned,
    and raises ``fitting.FitError`` if the model has no covariate functions.
    """
    model = get_model(db, model_id, owner_id)
    if model is None:
        return None

    cache_id = _LIVE.get(model_id)
    if cache_id is None or cache_id not in fitting._MODEL_STORE:
        cache_id = _refit(model)
        _LIVE[model_id] = cache_id
        while len(_LIVE) > _LIVE_MAX:
            _LIVE.popitem(last=False)
    return fitting._MODEL_STORE.get(cache_id)


def _refit(model: Model) -> str:
    """Re-fit the model and return the ephemeral fitting cache id of the live
    model."""
    from backend.db import get_db  # local import to avoid a cycle

    dataset = datasets_service.get_dataset(
        get_db(), model.dataset_id, owner_id=model.owner_id
    )
    if dataset is None:
        raise ModelNotFound(model.id)

    df = datasets_service.load_dataframe(dataset)
    spec = _spec(model)
    result = fitting.fit(
        spec.get("distribution_id", model.distribution_id),
        df,
        spec.get("mapping", {}),
        spec.get("covariates", []),
        spec.get("formula"),
        spec.get("unit"),
        options=spec.get("options"),
    )
    functions = result.get("functions") or {}
    cache_id = functions.get("model_id")
    if cache_id is None:
        raise fitting.FitError("This model has no covariate functions to evaluate.")
    return cache_id
