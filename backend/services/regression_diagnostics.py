"""A saved regression model's checks (#61): the proportional-hazards test,
robust standard errors, ties and strata — stored with the fit, or for a model
saved before them, computed by re-fitting it to its dataset and cached — and
its residuals, computed on request from the live model."""

from __future__ import annotations

from backend import fitting, regression_diagnostics as rd
from backend.schema import Model
from backend.services import datasets as datasets_service
from backend.services import models as models_service


def ensure_diagnostics(db, model: Model) -> dict | None:
    """The model's checks, as stored or now computed (and cached). ``None``
    for a model that isn't a regression."""
    if model.kind != "regression":
        return None
    cached = (model.results or {}).get("diagnostics")
    if cached:
        return cached
    dataset = (datasets_service.get_dataset(db, model.dataset_id, owner_id=model.owner_id)
               if model.dataset_id else None)
    if dataset is None:
        return {"ph_test": rd.unavailable(
            "Not available: the data this model was fitted to is no longer in Reliafy.")}
    try:
        result = models_service._refit_result(model, dataset)
    except fitting.FitError:
        diagnostics = {"ph_test": rd.unavailable("Not available: the model couldn't be re-fitted to its data.")}
    else:
        diagnostics = result.get("diagnostics") or {
            "ph_test": rd.unavailable("These checks couldn't be run for this model.")}
        models_service.keep_live(model.id, (result.get("functions") or {}).get("model_id"))
    db.models.update_one(
        {"_id": model.id, "results.diagnostics": {"$exists": False}},
        {"$set": {"results.diagnostics": diagnostics}},
    )
    model.results = {**(model.results or {}), "diagnostics": diagnostics}
    return diagnostics


def _source(model: Model) -> str:
    return "model" if (model.results or {}).get("distribution_id", model.distribution_id) == "cox_ph" else "cox"


def residuals(db, model: Model, owners) -> dict:
    """Residuals of a saved regression model's Cox fit (its own, or the one
    its proportional-hazards test ran on). Raises
    ``models_service.ModelNotFound`` when there's nothing to compute them
    from."""
    if model.kind != "regression":
        return rd.unavailable("Only regression models have residuals here.")
    cache_id = models_service._live_cache_id(db, model.id, owners)
    entry = fitting._MODEL_STORE.get(cache_id) or {}
    if "diag" not in entry:
        # A live model restored without its checks: re-fit it once.
        cache_id = models_service._refit(model)
        models_service.keep_live(model.id, cache_id, replace=True)
        entry = fitting._MODEL_STORE.get(cache_id) or {}
    diag = entry.get("diag")
    if diag is None:
        ph = ((model.results or {}).get("diagnostics") or {}).get("ph_test") or {}
        return rd.unavailable(ph.get("reason") or "No residuals for this model.")
    return rd.residuals(diag, _source(model))
