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
    # Persist the fitted model itself so the calculator/confidence bounds
    # rehydrate it directly instead of re-fitting from the dataset on demand.
    # Skip regression models: surpyval's from_dict doesn't restore the formula /
    # design-matrix transformer, so those still refit on demand (#59 follow-up).
    fcache = (result.get("functions") or {}).get("model_id")
    serialized = fitting.serialize_live(fcache) if (fcache and result.get("kind") != "regression") else None

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
        serialized=serialized,
        surpyval_version=getattr(surpyval, "__version__", None),
        status="ready",
    )
    db.models.insert_one(to_doc(model))
    return model


def import_model(
    db,
    uid: str,
    name: str,
    distribution: str,
    unit: str | None = None,
    data: dict | None = None,
    params: list | None = None,
    options: dict | None = None,
    extras: dict | None = None,
) -> Model:
    """Create a model from an external fit (e.g. a SurPyval notebook).

    Two modes:

    * **with data** — ``data`` holds arrays (``x`` required, optional ``c``/``n``).
      A dataset is created from them and the model is fit through the normal
      path, so the result is identical to an in-app fit (probability plot,
      bounds, goodness-of-fit) and stays editable/refittable.
    * **params-only** — no data, just ``params`` (+ optional ``options`` extras).
      Reliability functions and life metrics are available; there's no plot.

    Raises ``fitting.FitError`` on a bad distribution/params/data.
    """
    import pandas as pd

    distribution_id = fitting.resolve_distribution_id(distribution)

    if data and data.get("x"):
        x = list(data["x"])
        cols = {"x": x}
        mapping = {"x": "x"}
        c = data.get("c")
        if c is not None and any(int(v) != 0 for v in c):
            cols["c"] = list(c)
            mapping["c"] = "c"
        n = data.get("n")
        if n is not None and any(int(v) != 1 for v in n):
            cols["n"] = list(n)
            mapping["n"] = "n"
        lengths = {len(v) for v in cols.values()}
        if len(lengths) != 1:
            raise fitting.FitError("data arrays x/c/n must all be the same length.")
        csv_bytes = pd.DataFrame(cols).to_csv(index=False).encode()
        dataset = datasets_service.create_dataset(db, f"{name} (imported)", csv_bytes, uid)
        return save_model(
            db, name, dataset, distribution_id, mapping, [], None, unit, uid, options=options
        )

    # Params-only: extras carry actual fitted values (gamma/p/f0). Drop the
    # no-op defaults (offset 0, lfp 1, zi 0) so a plain model stays plain.
    clean = {}
    for key, default in (("gamma", 0.0), ("p", 1.0), ("f0", 0.0)):
        v = (extras or {}).get(key)
        if v is not None and float(v) != default:
            clean[key] = float(v)
    result = fitting.result_from_params(distribution_id, params, clean or None, unit)
    model = Model(
        id=uuid.uuid4().hex,
        name=name,
        owner_id=uid,
        dataset_id="",
        kind="distribution",
        distribution_id=distribution_id,
        spec={"distribution_id": distribution_id, "unit": (unit or "").strip(),
              "params_only": True, "options": result.get("options") or None},
        results=result,
        surpyval_version=getattr(surpyval, "__version__", None),
        status="ready",
    )
    db.models.insert_one(to_doc(model))
    return model


def create_per_demand(db, uid: str, name: str, demands, failures, confidence: float = 0.95) -> Model:
    """Create a per-demand (Binomial) model from a demands/failures count.

    With zero failures this is a success-run reliability-demonstration test;
    ``confidence`` sets the demonstrated lower-bound level (default 95%)."""
    result = fitting.result_per_demand(demands, failures, confidence)
    model = Model(
        id=uuid.uuid4().hex,
        name=name,
        owner_id=uid,
        dataset_id="",
        kind="per_demand",
        distribution_id="binomial",
        spec={"distribution_id": "binomial", "params_only": True,
              "per_demand": {"demands": int(demands), "failures": int(failures),
                             "confidence": float(confidence)}},
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
    fcache = (result.get("functions") or {}).get("model_id")
    model.serialized = fitting.serialize_live(fcache) if (fcache and result.get("kind") != "regression") else None
    db.models.update_one(
        {"_id": model_id, "owner_id": owner_id},
        {"$set": {
            "results": result,
            "kind": model.kind,
            "distribution_id": resolved_id,
            "spec": model.spec,
            "serialized": model.serialized,
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
    """Results shaped for the client, with the evaluate / confidence paths
    pointed at this saved model (so the calculator re-evaluates and recomputes
    confidence bounds via the persistent id)."""
    results = dict(model.results or {})
    functions = results.get("functions")
    if functions and functions.get("model_id"):
        functions = dict(functions)
        functions["model_id"] = model.id
        functions["evaluate_path"] = f"/api/models/{model.id}/evaluate"
        # Confidence bounds aren't available for regression models.
        if model.kind in ("distribution", "discrete", "nonparametric"):
            functions["confidence_path"] = f"/api/models/{model.id}/confidence"
        results["functions"] = functions
    return results


def _live_cache_id(db, model_id: str, owner_id: str | list[str]) -> str:
    """Resolve a saved model to its live fitting-cache id, re-fitting on demand.

    Raises ``ModelNotFound`` if the model is unknown/not owned.
    """
    model = get_model(db, model_id, owner_id)
    if model is None:
        raise ModelNotFound(model_id)

    cache_id = _LIVE.get(model_id)
    if cache_id is None or cache_id not in fitting._MODEL_STORE:
        # Prefer rehydrating the persisted fit; only re-fit from the dataset if
        # there's no serialised model (older docs / per-demand) or it won't load.
        cache_id = None
        if model.serialized:
            try:
                cache_id = fitting.restore_live(model.serialized)
            except Exception:  # noqa: BLE001 - fall back to a fresh fit
                cache_id = None
        if cache_id is None:
            cache_id = _refit(model)
        _LIVE[model_id] = cache_id
        while len(_LIVE) > _LIVE_MAX:
            _LIVE.popitem(last=False)
    return cache_id


def evaluate(db, model_id: str, values: dict, owner_id: str, x_min=None, x_max=None) -> dict:
    """Evaluate the model's functions at covariate ``values``, re-fitting if the
    live model isn't cached. ``x_min``/``x_max`` recompute over a custom grid."""
    return fitting.evaluate(
        _live_cache_id(db, model_id, owner_id), values, x_min=x_min, x_max=x_max
    )


def confidence(db, model_id: str, params: dict, owner_id: str, x_min=None, x_max=None) -> dict:
    """Confidence bounds of a saved model's function (configurable level /
    bound), re-fitting on demand if the live model isn't cached."""
    return fitting.confidence_bounds(
        _live_cache_id(db, model_id, owner_id),
        on=params.get("on", "sf"),
        alpha_ci=float(params.get("alpha_ci", 0.05)),
        bound=params.get("bound", "two-sided"),
        x_min=x_min,
        x_max=x_max,
    )


def get_live_model(db, model_id: str, owner_id: str | list[str]) -> dict | None:
    """Return the live (re-fitted) model entry for a saved model id.

    The entry is the one cached by :mod:`backend.fitting`:
    ``{"model", "grid", "fields"}`` — used by the RBD analysis to evaluate a
    proportional-hazards node's reliability at chosen covariate values. Scoped
    to ``owner_id`` so a user can't embed another user's model id in their RBD
    graph and read it. Returns ``None`` if the model id is unknown/not owned,
    and raises ``fitting.FitError`` if the model has no covariate functions.
    """
    if get_model(db, model_id, owner_id) is None:
        return None
    return fitting._MODEL_STORE.get(_live_cache_id(db, model_id, owner_id))


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
