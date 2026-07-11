"""Saved datasets and models API."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Body, Depends, File, Form, UploadFile
from fastapi.responses import JSONResponse

from backend.auth import get_current_user
from backend.db import get_session
from backend.fitting import FitError
from backend import storage
from backend.services import billing as billing_service
from backend.services import datasets as datasets_service
from backend.services import models as models_service
from backend.services import samples as samples_service

_CAP_MSG = "You've reached the free-plan limit. Upgrade to Pro for unlimited saves."

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api")


def _model_summary(model) -> dict:
    results = model.results or {}
    return {
        "id": model.id,
        "name": model.name,
        "kind": model.kind,
        "distribution": results.get("distribution", model.distribution_id),
        "n": results.get("n"),
        "unit": results.get("unit", (model.spec or {}).get("unit", "")),
        "surpyval_version": model.surpyval_version,
        "created_at": model.created_at.isoformat(),
        "dataset_id": model.dataset_id,
        "is_sample": samples_service.is_sample(model.owner_id),
        # Randomness verdict (weibull beta CI / exponential), used when picking
        # RCM evidence for run-to-failure decisions.
        "randomness": results.get("randomness"),
    }


def _model_detail(model) -> dict:
    return {
        **_model_summary(model),
        "updated_at": model.updated_at.isoformat(),
        "spec": model.spec,
        "results": models_service.public_results(model),
        "saved": True,
    }


def _dataset_summary(dataset, n_models: int = 0) -> dict:
    return {
        "id": dataset.id,
        "name": dataset.name,
        "n_rows": dataset.n_rows,
        "columns": dataset.columns,
        "n_columns": len(dataset.columns or []),
        "n_models": n_models,
        "checksum": dataset.checksum,
        "created_at": dataset.created_at.isoformat(),
        "is_sample": samples_service.is_sample(dataset.owner_id),
    }


def _dataset_detail(dataset, session, owner_id, hidden=frozenset()) -> dict:
    models = datasets_service.models_for_dataset(session, dataset.id, owner_id, hidden)
    summary = _dataset_summary(dataset, n_models=len(models))
    try:
        preview = datasets_service.preview_rows(dataset)
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning("Failed to build dataset preview: %s", exc)
        preview = {"columns": [c["name"] for c in (dataset.columns or [])], "preview": [], "n_rows": dataset.n_rows}
    return {
        **summary,
        "preview": preview.get("preview", []),
        "preview_columns": preview.get("columns", []),
        "models": [_model_summary(m) for m in models],
    }


@router.get("/datasets")
def list_datasets(session=Depends(get_session), user: dict = Depends(get_current_user)) -> dict:
    hidden = samples_service.hidden_sample_ids(session, user["uid"])
    counts: dict[str, int] = {}
    for m in models_service.list_models(session, user["uid"], hidden):
        counts[m.dataset_id] = counts.get(m.dataset_id, 0) + 1
    return {
        "datasets": [
            _dataset_summary(d, n_models=counts.get(d.id, 0))
            for d in datasets_service.list_datasets(session, user["uid"], hidden)
        ]
    }


@router.post("/datasets")
async def upload_dataset(
    file: UploadFile = File(...),
    name: str | None = Form(default=None),
    session=Depends(get_session),
    user: dict = Depends(get_current_user),
) -> JSONResponse:
    """Store an uploaded CSV as a standalone dataset (no fit required)."""
    contents = await file.read()
    # Free-plan cap (new datasets only — re-uploading an existing file is fine).
    if not billing_service.is_admin_user(user) and billing_service.would_exceed_cap(session, user["uid"], "datasets"):
        digest = storage.checksum(contents)
        if session.datasets.find_one({"checksum": digest, "owner_id": user["uid"]}) is None:
            return JSONResponse(status_code=402, content={"detail": _CAP_MSG, "code": "cap", "upgrade": True})
    try:
        dataset = datasets_service.create_dataset(
            session, name or file.filename or "dataset.csv", contents, user["uid"]
        )
    except FitError as exc:
        return JSONResponse(status_code=422, content={"detail": str(exc)})
    except Exception as exc:  # pragma: no cover - defensive
        logger.exception("Failed to store dataset")
        return JSONResponse(
            status_code=500, content={"detail": f"Failed to store dataset: {exc}"}
        )
    return JSONResponse(content=_dataset_detail(dataset, session, user["uid"]))


@router.get("/datasets/{dataset_id}")
def get_dataset(
    dataset_id: str, session=Depends(get_session), user: dict = Depends(get_current_user)
) -> JSONResponse:
    hidden = samples_service.hidden_sample_ids(session, user["uid"])
    dataset = datasets_service.get_dataset(session, dataset_id, owner_id=user["uid"])
    if dataset is None or dataset.id in hidden:
        return JSONResponse(status_code=404, content={"detail": "Dataset not found."})
    return JSONResponse(content=_dataset_detail(dataset, session, user["uid"], hidden))


@router.delete("/datasets/{dataset_id}")
def delete_dataset(
    dataset_id: str, session=Depends(get_session), user: dict = Depends(get_current_user)
) -> JSONResponse:
    uid = user["uid"]
    hidden = samples_service.hidden_sample_ids(session, uid)
    dataset = datasets_service.get_dataset(session, dataset_id, owner_id=uid)
    if dataset is None or dataset.id in hidden:
        return JSONResponse(status_code=404, content={"detail": "Dataset not found."})

    models = datasets_service.models_for_dataset(session, dataset_id, uid, hidden)
    if models:
        names = ", ".join(m.name for m in models[:3])
        more = "" if len(models) <= 3 else f" and {len(models) - 3} more"
        return JSONResponse(
            status_code=409,
            content={
                "detail": (
                    f"Dataset is used by {len(models)} model(s): {names}{more}. "
                    "Delete those models first."
                ),
                "model_count": len(models),
            },
        )

    # A shared sample isn't really deleted — just hidden for this user.
    if samples_service.is_sample(dataset.owner_id):
        samples_service.hide_sample(session, uid, dataset_id)
    elif not datasets_service.delete_dataset(session, dataset_id, uid):
        return JSONResponse(status_code=404, content={"detail": "Dataset not found."})
    return JSONResponse(content={"ok": True})


@router.get("/models")
def list_models(session=Depends(get_session), user: dict = Depends(get_current_user)) -> dict:
    hidden = samples_service.hidden_sample_ids(session, user["uid"])
    return {
        "models": [
            _model_summary(m)
            for m in models_service.list_models(session, user["uid"], hidden)
        ]
    }


@router.post("/models")
async def save_model(
    name: str = Form(...),
    distribution: str = Form(...),
    file: UploadFile | None = File(default=None),
    dataset_id: str | None = Form(default=None),
    x: str | None = Form(default=None),
    c: str | None = Form(default=None),
    n: str | None = Form(default=None),
    xl: str | None = Form(default=None),
    xr: str | None = Form(default=None),
    tl: str | None = Form(default=None),
    tr: str | None = Form(default=None),
    z: list[str] = Form(default=[]),
    formula: str | None = Form(default=None),
    unit: str | None = Form(default=None),
    session=Depends(get_session),
    user: dict = Depends(get_current_user),
) -> JSONResponse:
    """Fit and persist a model from a fit spec and either an uploaded CSV
    (``file``) or an existing saved dataset (``dataset_id``)."""
    if not billing_service.is_admin_user(user) and billing_service.would_exceed_cap(session, user["uid"], "models"):
        return JSONResponse(status_code=402, content={"detail": _CAP_MSG, "code": "cap", "upgrade": True})
    mapping = {"x": x, "c": c, "n": n, "xl": xl, "xr": xr, "tl": tl, "tr": tr}
    try:
        if dataset_id:
            dataset = datasets_service.get_dataset(session, dataset_id, owner_id=user["uid"])
            if dataset is None:
                return JSONResponse(
                    status_code=404, content={"detail": "Dataset not found."}
                )
        elif file is not None:
            dataset = datasets_service.create_dataset(
                session, file.filename or "dataset.csv", await file.read(), user["uid"]
            )
        else:
            return JSONResponse(
                status_code=422,
                content={"detail": "Provide a CSV file or a dataset_id."},
            )
        model = models_service.save_model(
            session, name, dataset, distribution, mapping, z, formula, unit,
            owner_id=user["uid"],
        )
    except FitError as exc:
        return JSONResponse(status_code=422, content={"detail": str(exc)})
    except Exception as exc:  # pragma: no cover - defensive
        logger.exception("Failed to save model")
        return JSONResponse(
            status_code=500, content={"detail": f"Failed to save model: {exc}"}
        )
    return JSONResponse(content=_model_detail(model))


@router.get("/models/{model_id}")
def get_model(
    model_id: str, session=Depends(get_session), user: dict = Depends(get_current_user)
) -> JSONResponse:
    model = models_service.get_model(session, model_id, user["uid"])
    if model is None:
        return JSONResponse(status_code=404, content={"detail": "Model not found."})
    return JSONResponse(content=_model_detail(model))


@router.patch("/models/{model_id}")
def rename_model(
    model_id: str,
    name: str = Body(..., embed=True),
    session=Depends(get_session),
    user: dict = Depends(get_current_user),
) -> JSONResponse:
    existing = models_service.get_model(session, model_id, user["uid"])
    if existing is not None and samples_service.is_sample(existing.owner_id):
        return JSONResponse(
            status_code=403,
            content={"detail": "Sample models are read-only and can't be renamed."},
        )
    try:
        model = models_service.rename_model(session, model_id, name, user["uid"])
    except models_service.ModelNotFound:
        return JSONResponse(status_code=404, content={"detail": "Model not found."})
    return JSONResponse(content=_model_detail(model))


@router.delete("/models/{model_id}")
def delete_model(
    model_id: str, session=Depends(get_session), user: dict = Depends(get_current_user)
) -> JSONResponse:
    uid = user["uid"]
    hidden = samples_service.hidden_sample_ids(session, uid)
    model = models_service.get_model(session, model_id, uid)
    if model is None or model.id in hidden:
        return JSONResponse(status_code=404, content={"detail": "Model not found."})

    # A shared sample isn't really deleted — just hidden for this user.
    if samples_service.is_sample(model.owner_id):
        samples_service.hide_sample(session, uid, model_id)
        return JSONResponse(content={"ok": True})
    try:
        models_service.delete_model(session, model_id, uid)
    except models_service.ModelNotFound:
        return JSONResponse(status_code=404, content={"detail": "Model not found."})
    return JSONResponse(content={"ok": True})


@router.post("/models/{model_id}/evaluate")
def evaluate_model(
    model_id: str,
    values: dict = Body(default={}),
    session=Depends(get_session),
    user: dict = Depends(get_current_user),
) -> JSONResponse:
    try:
        return JSONResponse(
            content=models_service.evaluate(session, model_id, values, user["uid"])
        )
    except models_service.ModelNotFound:
        return JSONResponse(status_code=404, content={"detail": "Model not found."})
    except FitError as exc:
        return JSONResponse(status_code=422, content={"detail": str(exc)})
