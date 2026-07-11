"""Degradation models and tracked-item (RUL) API."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Body, Depends, File, Form, UploadFile
from fastapi.responses import JSONResponse

from backend import degradation as degradation_fit
from backend.auth import get_current_user
from backend.db import get_session
from backend.fitting import DISTRIBUTIONS, FitError
from backend.services import billing as billing_service
from backend.services import datasets as datasets_service
from backend.services import degradation as degradation_service
from backend.services import samples as samples_service

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api")

_CAP_MODELS = (
    "You've reached the free-plan limit of 1 degradation model. "
    "Upgrade to Pro for unlimited models."
)
_CAP_ITEMS = (
    "You've reached the free-plan limit of 3 tracked items. "
    "Upgrade to Pro to monitor your whole fleet."
)


def _model_summary(doc, n_items: int = 0) -> dict:
    results = doc.results or {}
    return {
        "id": doc.id,
        "name": doc.name,
        "kind": "degradation",
        "path_model": (results.get("path_model") or {}).get("name"),
        "threshold": results.get("threshold"),
        "n_units": results.get("n_units"),
        "unit": results.get("unit", ""),
        "measurement_unit": results.get("measurement_unit", ""),
        "n_items": n_items,
        "dataset_id": doc.dataset_id,
        "is_sample": samples_service.is_sample(doc.owner_id),
        "created_at": doc.created_at.isoformat(),
        "updated_at": doc.updated_at.isoformat(),
    }


def _item_summary(item) -> dict:
    last = item.measurements[-1] if item.measurements else {}
    return {
        "id": item.id,
        "model_id": item.model_id,
        "name": item.name,
        "meta": item.meta or {},
        "n_measurements": len(item.measurements),
        "last_t": last.get("t"),
        "last_y": last.get("y"),
        "measurements": item.measurements,
        "prediction": item.prediction,
        "is_sample": samples_service.is_sample(item.owner_id),
        "created_at": item.created_at.isoformat(),
        "updated_at": item.updated_at.isoformat(),
    }


@router.get("/degradation/options")
def degradation_options(user: dict = Depends(get_current_user)) -> dict:
    return {
        "paths": [
            {"id": "best", "name": "Best (auto-select by AICc)"},
            *degradation_fit.PATH_MODELS.values(),
        ],
        "distributions": [
            {"id": k, "name": v["name"]} for k, v in DISTRIBUTIONS.items()
        ],
        "population_methods": [
            {"id": "moments", "name": "Moments (Lu–Meeker)"},
            {"id": "reml", "name": "REML (linear paths, more robust)"},
        ],
    }


async def _resolve_dataset(session, user, dataset_id, file):
    """Dataset from an id or an uploaded CSV (stored, like the model save flow)."""
    if dataset_id:
        dataset = datasets_service.get_dataset(session, dataset_id, owner_id=user["uid"])
        if dataset is None:
            raise FitError("Dataset not found.")
        return dataset
    if file is not None:
        return datasets_service.create_dataset(
            session, file.filename or "dataset.csv", await file.read(), user["uid"]
        )
    raise FitError("Provide a CSV file or a dataset_id.")


def _spec_from_form(i, x, y, threshold, path, distribution, population_method, unit, measurement_unit) -> dict:
    return {
        "mapping": {"i": i, "x": x, "y": y},
        "threshold": threshold,
        "path": path or "best",
        "distribution_id": distribution or "weibull",
        "population_method": population_method or "moments",
        "unit": (unit or "").strip(),
        "measurement_unit": (measurement_unit or "").strip(),
    }


@router.post("/degradation/fit")
async def fit_preview(
    file: UploadFile | None = File(default=None),
    dataset_id: str | None = Form(default=None),
    i: str = Form(...),
    x: str = Form(...),
    y: str = Form(...),
    threshold: float = Form(...),
    path: str = Form(default="best"),
    distribution: str = Form(default="weibull"),
    population_method: str = Form(default="moments"),
    unit: str | None = Form(default=None),
    measurement_unit: str | None = Form(default=None),
    session=Depends(get_session),
    user: dict = Depends(get_current_user),
) -> JSONResponse:
    """Fit a degradation model for preview (nothing persisted except the
    uploaded dataset, which is content-addressed like the model-fit flow)."""
    try:
        dataset = await _resolve_dataset(session, user, dataset_id, file)
        spec = _spec_from_form(i, x, y, threshold, path, distribution, population_method, unit, measurement_unit)
        df = datasets_service.load_dataframe(dataset)
        payload, _ = degradation_fit.fit(
            df, spec["mapping"], spec["threshold"], spec["path"],
            spec["distribution_id"], spec["population_method"],
            spec["unit"], spec["measurement_unit"],
        )
    except FitError as exc:
        return JSONResponse(status_code=422, content={"detail": str(exc)})
    except Exception as exc:  # pragma: no cover - defensive
        logger.exception("Degradation fit failed")
        return JSONResponse(status_code=500, content={"detail": f"Fit failed: {exc}"})
    return JSONResponse(content={"dataset_id": dataset.id, "spec": spec, "results": payload})


@router.post("/degradation/models")
async def save_model(
    name: str = Form(...),
    file: UploadFile | None = File(default=None),
    dataset_id: str | None = Form(default=None),
    i: str = Form(...),
    x: str = Form(...),
    y: str = Form(...),
    threshold: float = Form(...),
    path: str = Form(default="best"),
    distribution: str = Form(default="weibull"),
    population_method: str = Form(default="moments"),
    unit: str | None = Form(default=None),
    measurement_unit: str | None = Form(default=None),
    session=Depends(get_session),
    user: dict = Depends(get_current_user),
) -> JSONResponse:
    if not billing_service.is_admin_user(user) and billing_service.would_exceed_cap(
        session, user["uid"], "degradation_models"
    ):
        return JSONResponse(status_code=402, content={"detail": _CAP_MODELS, "code": "cap", "upgrade": True})
    try:
        dataset = await _resolve_dataset(session, user, dataset_id, file)
        spec = _spec_from_form(i, x, y, threshold, path, distribution, population_method, unit, measurement_unit)
        doc = degradation_service.save_model(session, name, dataset, spec, user["uid"])
    except FitError as exc:
        return JSONResponse(status_code=422, content={"detail": str(exc)})
    except Exception as exc:  # pragma: no cover - defensive
        logger.exception("Failed to save degradation model")
        return JSONResponse(status_code=500, content={"detail": f"Failed to save: {exc}"})
    return JSONResponse(content={**_model_summary(doc), "spec": doc.spec, "results": doc.results})


@router.get("/degradation/models")
def list_models(session=Depends(get_session), user: dict = Depends(get_current_user)) -> dict:
    hidden = samples_service.hidden_sample_ids(session, user["uid"])
    models = degradation_service.list_models(session, user["uid"], hidden)
    counts: dict[str, int] = {}
    for m in models:
        counts[m.id] = len(degradation_service.list_items(session, m.id, user["uid"], hidden))
    return {"models": [_model_summary(m, counts.get(m.id, 0)) for m in models]}


@router.get("/degradation/models/{model_id}")
def get_model(
    model_id: str, session=Depends(get_session), user: dict = Depends(get_current_user)
) -> JSONResponse:
    hidden = samples_service.hidden_sample_ids(session, user["uid"])
    doc = degradation_service.get_model(session, model_id, user["uid"])
    if doc is None or doc.id in hidden:
        return JSONResponse(status_code=404, content={"detail": "Model not found."})
    items = degradation_service.list_items(session, model_id, user["uid"], hidden)
    return JSONResponse(content={
        **_model_summary(doc, len(items)),
        "spec": doc.spec,
        "results": doc.results,
        "items": [_item_summary(it) for it in items],
    })


@router.patch("/degradation/models/{model_id}")
def rename_model(
    model_id: str,
    name: str = Body(..., embed=True),
    session=Depends(get_session),
    user: dict = Depends(get_current_user),
) -> JSONResponse:
    existing = degradation_service.get_model(session, model_id, user["uid"])
    if existing is not None and samples_service.is_sample(existing.owner_id):
        return JSONResponse(status_code=403, content={"detail": "Sample models are read-only."})
    try:
        doc = degradation_service.rename_model(session, model_id, name, user["uid"])
    except degradation_service.ModelNotFound:
        return JSONResponse(status_code=404, content={"detail": "Model not found."})
    return JSONResponse(content=_model_summary(doc))


@router.delete("/degradation/models/{model_id}")
def delete_model(
    model_id: str, session=Depends(get_session), user: dict = Depends(get_current_user)
) -> JSONResponse:
    uid = user["uid"]
    hidden = samples_service.hidden_sample_ids(session, uid)
    doc = degradation_service.get_model(session, model_id, uid)
    if doc is None or doc.id in hidden:
        return JSONResponse(status_code=404, content={"detail": "Model not found."})
    if samples_service.is_sample(doc.owner_id):
        samples_service.hide_sample(session, uid, model_id)
        return JSONResponse(content={"ok": True})
    try:
        degradation_service.delete_model(session, model_id, uid)
    except degradation_service.ModelNotFound:
        return JSONResponse(status_code=404, content={"detail": "Model not found."})
    return JSONResponse(content={"ok": True})


# ---- Tracked items ----------------------------------------------------------

@router.post("/degradation/models/{model_id}/items")
def create_item(
    model_id: str,
    name: str = Body(...),
    measurements: list = Body(default=[]),
    meta: dict = Body(default={}),
    session=Depends(get_session),
    user: dict = Depends(get_current_user),
) -> JSONResponse:
    if not billing_service.is_admin_user(user) and billing_service.would_exceed_cap(
        session, user["uid"], "tracked_items"
    ):
        return JSONResponse(status_code=402, content={"detail": _CAP_ITEMS, "code": "cap", "upgrade": True})
    try:
        item = degradation_service.create_item(
            session, model_id, name, measurements, user["uid"], meta
        )
    except degradation_service.ModelNotFound:
        return JSONResponse(status_code=404, content={"detail": "Model not found."})
    except FitError as exc:
        return JSONResponse(status_code=422, content={"detail": str(exc)})
    return JSONResponse(content=_item_summary(item))


@router.get("/degradation/models/{model_id}/items")
def list_items(
    model_id: str, session=Depends(get_session), user: dict = Depends(get_current_user)
) -> JSONResponse:
    hidden = samples_service.hidden_sample_ids(session, user["uid"])
    if degradation_service.get_model(session, model_id, user["uid"]) is None:
        return JSONResponse(status_code=404, content={"detail": "Model not found."})
    items = degradation_service.list_items(session, model_id, user["uid"], hidden)
    return JSONResponse(content={"items": [_item_summary(it) for it in items]})


@router.get("/degradation/models/{model_id}/items/{item_id}")
def get_item(
    model_id: str,
    item_id: str,
    session=Depends(get_session),
    user: dict = Depends(get_current_user),
) -> JSONResponse:
    item = degradation_service.get_item(session, model_id, item_id, user["uid"])
    if item is None:
        return JSONResponse(status_code=404, content={"detail": "Item not found."})
    if not item.prediction or item.prediction.get("method") == "error":
        # A model refit may have fixed it (e.g. dataset was briefly missing).
        item = degradation_service.refresh_prediction(session, model_id, item, user["uid"])
    return JSONResponse(content=_item_summary(item))


@router.post("/degradation/models/{model_id}/items/{item_id}/measurements")
def add_measurement(
    model_id: str,
    item_id: str,
    t: float = Body(...),
    y: float = Body(...),
    session=Depends(get_session),
    user: dict = Depends(get_current_user),
) -> JSONResponse:
    existing = degradation_service.get_item(session, model_id, item_id, user["uid"])
    if existing is not None and samples_service.is_sample(existing.owner_id):
        return JSONResponse(status_code=403, content={"detail": "Sample items are read-only — register your own item to track measurements."})
    try:
        item = degradation_service.append_measurement(session, model_id, item_id, t, y, user["uid"])
    except degradation_service.ItemNotFound:
        return JSONResponse(status_code=404, content={"detail": "Item not found."})
    except FitError as exc:
        return JSONResponse(status_code=422, content={"detail": str(exc)})
    return JSONResponse(content=_item_summary(item))


@router.delete("/degradation/models/{model_id}/items/{item_id}")
def delete_item(
    model_id: str,
    item_id: str,
    session=Depends(get_session),
    user: dict = Depends(get_current_user),
) -> JSONResponse:
    uid = user["uid"]
    item = degradation_service.get_item(session, model_id, item_id, uid)
    if item is None:
        return JSONResponse(status_code=404, content={"detail": "Item not found."})
    if samples_service.is_sample(item.owner_id):
        samples_service.hide_sample(session, uid, item_id)
        return JSONResponse(content={"ok": True})
    try:
        degradation_service.delete_item(session, model_id, item_id, uid)
    except degradation_service.ItemNotFound:
        return JSONResponse(status_code=404, content={"detail": "Item not found."})
    return JSONResponse(content={"ok": True})
