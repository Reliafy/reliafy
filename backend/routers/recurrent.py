"""Recurrent-event (repairable-system) models API."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Body, Depends, File, Form, UploadFile
from fastapi.responses import JSONResponse

from backend import recurrent as recurrent_fit
from backend.db import get_session
from backend.fitting import FitError
from backend.services import datasets as datasets_service
from backend.services import recurrent as recurrent_service
from backend.services import samples as samples_service
from backend.services import access as access_service
from backend.services import shares as shares_service
from backend.services.access import AccessCtx, get_access
from backend.schema import RecurrentModelDoc

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api")


def _spec_from_form(i, x, model, unit, *, c=None, n=None, tl=None, tr=None, t=None) -> dict:
    mapping = {"i": i, "x": x}
    # Optional modifiers (c/n/tl/tr); ``t`` is the legacy alias for ``tr``.
    for key, val in (("c", c), ("n", n), ("tl", tl), ("tr", tr or t)):
        if val:
            mapping[key] = val
    return {"mapping": mapping, "model_id": (model or "crow_amsaa"), "unit": (unit or "").strip()}


def _model_summary(doc, ctx: AccessCtx) -> dict:
    r = doc.results or {}
    return {
        "id": doc.id,
        "name": doc.name,
        "kind": "recurrent",
        "model": (r.get("model") or {}).get("name"),
        "n_systems": r.get("n_systems"),
        "n_events": r.get("n_events"),
        "beta": r.get("beta"),
        "growth": r.get("growth"),
        "unit": r.get("unit", ""),
        "dataset_id": doc.dataset_id,
        "is_sample": samples_service.is_sample(doc.owner_id),
        "read_only": not access_service.can_write(ctx, doc.owner_id),
        "updated_by": (doc.updated_by or {}).get("name"),
        "created_at": doc.created_at.isoformat(),
        "updated_at": doc.updated_at.isoformat(),
    }


async def _resolve_dataset(session, ctx: AccessCtx, dataset_id, file):
    if dataset_id:
        dataset = datasets_service.get_dataset(session, dataset_id, owner_id=ctx.write_owner)
        if dataset is None:
            raise FitError("Dataset not found.")
        return dataset
    if file is not None:
        return datasets_service.create_dataset(
            session, file.filename or "dataset.csv", await file.read(), ctx.write_owner
        )
    raise FitError("Provide a CSV file or a dataset_id.")


@router.get("/recurrent/options")
def recurrent_options(ctx: AccessCtx = Depends(get_access)) -> dict:
    return {"models": [{"id": k, "name": v["name"]} for k, v in recurrent_fit.MODELS.items()]}


@router.post("/recurrent/fit")
async def fit_preview(
    file: UploadFile | None = File(default=None),
    dataset_id: str | None = Form(default=None),
    i: str = Form(...),
    x: str = Form(...),
    c: str | None = Form(default=None),
    n: str | None = Form(default=None),
    tl: str | None = Form(default=None),
    tr: str | None = Form(default=None),
    t: str | None = Form(default=None),
    model: str = Form(default="crow_amsaa"),
    unit: str | None = Form(default=None),
    session=Depends(get_session),
    ctx: AccessCtx = Depends(get_access),
) -> JSONResponse:
    """Fit a recurrent model for preview (only the uploaded dataset is stored)."""
    try:
        dataset = await _resolve_dataset(session, ctx, dataset_id, file)
        spec = _spec_from_form(i, x, model, unit, c=c, n=n, tl=tl, tr=tr, t=t)
        df = datasets_service.load_dataframe(dataset)
        payload, _ = recurrent_fit.fit(df, spec["mapping"], spec["model_id"], spec["unit"])
    except FitError as exc:
        return JSONResponse(status_code=422, content={"detail": str(exc)})
    except Exception as exc:  # pragma: no cover - defensive
        logger.exception("Recurrent fit failed")
        return JSONResponse(status_code=500, content={"detail": f"Fit failed: {exc}"})
    return JSONResponse(content={"dataset_id": dataset.id, "spec": spec, "results": payload})


@router.post("/recurrent/models")
async def save_model(
    name: str = Form(...),
    file: UploadFile | None = File(default=None),
    dataset_id: str | None = Form(default=None),
    i: str = Form(...),
    x: str = Form(...),
    c: str | None = Form(default=None),
    n: str | None = Form(default=None),
    tl: str | None = Form(default=None),
    tr: str | None = Form(default=None),
    t: str | None = Form(default=None),
    model: str = Form(default="crow_amsaa"),
    unit: str | None = Form(default=None),
    session=Depends(get_session),
    ctx: AccessCtx = Depends(get_access),
) -> JSONResponse:
    denied = access_service.workspace_write_denial(ctx)
    if denied is not None:
        status, payload = denied
        return JSONResponse(status_code=status, content=payload)
    try:
        dataset = await _resolve_dataset(session, ctx, dataset_id, file)
        spec = _spec_from_form(i, x, model, unit, c=c, n=n, tl=tl, tr=tr, t=t)
        doc = recurrent_service.save_model(session, name, dataset, spec, ctx.write_owner)
        access_service.stamp_editor(session, "recurrent_models", doc.id, ctx)
    except FitError as exc:
        return JSONResponse(status_code=422, content={"detail": str(exc)})
    except Exception as exc:  # pragma: no cover - defensive
        logger.exception("Failed to save recurrent model")
        return JSONResponse(status_code=500, content={"detail": f"Failed to save: {exc}"})
    return JSONResponse(content={**_model_summary(doc, ctx), "spec": doc.spec, "results": doc.results})


@router.post("/recurrent/from-params")
def save_from_params(
    name: str = Form(...),
    model: str = Form(default="crow_amsaa"),
    alpha: float = Form(...),
    beta: float = Form(...),
    horizon: float = Form(...),
    unit: str | None = Form(default=None),
    session=Depends(get_session),
    ctx: AccessCtx = Depends(get_access),
) -> JSONResponse:
    """Build and save a recurrent model from known parameters — no dataset."""
    denied = access_service.workspace_write_denial(ctx)
    if denied is not None:
        status, payload = denied
        return JSONResponse(status_code=status, content=payload)
    try:
        params = [{"name": "alpha", "value": alpha}, {"name": "beta", "value": beta}]
        doc = recurrent_service.save_from_params(session, name, model, params, horizon, unit or "", ctx.write_owner)
        access_service.stamp_editor(session, "recurrent_models", doc.id, ctx)
    except FitError as exc:
        return JSONResponse(status_code=422, content={"detail": str(exc)})
    except Exception as exc:  # pragma: no cover - defensive
        logger.exception("Failed to save recurrent model from params")
        return JSONResponse(status_code=500, content={"detail": f"Failed to save: {exc}"})
    return JSONResponse(content={**_model_summary(doc, ctx), "spec": doc.spec, "results": doc.results})


@router.get("/recurrent/models")
def list_models(session=Depends(get_session), ctx: AccessCtx = Depends(get_access)) -> dict:
    shared_by = shares_service.shared_by_map(session, ctx.uid, "recurrent_models") if ctx.is_personal else {}
    models = recurrent_service.list_models(session, ctx.list_owners, ctx.hidden, shared=set(shared_by))
    return {"models": [
        {**_model_summary(m, ctx), **({"shared_by": shared_by[m.id]} if m.id in shared_by else {})}
        for m in models
    ]}


@router.get("/recurrent/models/{model_id}")
def get_model(model_id: str, session=Depends(get_session), ctx: AccessCtx = Depends(get_access)) -> JSONResponse:
    doc, _ = access_service.fetch_readable(session, "recurrent_models", RecurrentModelDoc, model_id, ctx)
    if doc is None or doc.id in ctx.hidden:
        return JSONResponse(status_code=404, content={"detail": "Model not found."})
    return JSONResponse(content={**_model_summary(doc, ctx), "spec": doc.spec, "results": doc.results})


@router.patch("/recurrent/models/{model_id}")
def rename_model(
    model_id: str, name: str = Body(..., embed=True),
    session=Depends(get_session), ctx: AccessCtx = Depends(get_access),
) -> JSONResponse:
    existing = recurrent_service.get_model(session, model_id, ctx.read_owners)
    if existing is not None:
        denial = access_service.write_denial(ctx, existing.owner_id)
        if denial:
            status, payload = denial
            return JSONResponse(status_code=status, content=payload)
    try:
        doc = recurrent_service.rename_model(session, model_id, name, ctx.write_owner)
        access_service.stamp_editor(session, "recurrent_models", doc.id, ctx)
    except recurrent_service.ModelNotFound:
        return JSONResponse(status_code=404, content={"detail": "Model not found."})
    return JSONResponse(content=_model_summary(doc, ctx))


@router.delete("/recurrent/models/{model_id}")
def delete_model(model_id: str, session=Depends(get_session), ctx: AccessCtx = Depends(get_access)) -> JSONResponse:
    doc, _ = access_service.fetch_readable(session, "recurrent_models", RecurrentModelDoc, model_id, ctx)
    if doc is None or doc.id in ctx.hidden:
        return JSONResponse(status_code=404, content={"detail": "Model not found."})
    if access_service.can_write(ctx, doc.owner_id):
        try:
            recurrent_service.delete_model(session, model_id, ctx.write_owner)
        except recurrent_service.ModelNotFound:
            return JSONResponse(status_code=404, content={"detail": "Model not found."})
    elif samples_service.is_sample(doc.owner_id) or access_service.is_shared_with(session, ctx.uid, model_id):
        samples_service.hide_sample(session, ctx.uid, model_id)
    else:
        status, payload = access_service.write_denial(ctx, doc.owner_id)
        return JSONResponse(status_code=status, content=payload)
    return JSONResponse(content={"ok": True})


@router.post("/recurrent/models/{model_id}/predict")
def predict(
    model_id: str, horizon: float = Body(..., embed=True),
    session=Depends(get_session), ctx: AccessCtx = Depends(get_access),
) -> JSONResponse:
    """Expected cumulative failures by a future time, from the saved model."""
    doc, _ = access_service.fetch_readable(session, "recurrent_models", RecurrentModelDoc, model_id, ctx)
    if doc is None:
        return JSONResponse(status_code=404, content={"detail": "Model not found."})
    try:
        live = recurrent_service.get_live_model(session, model_id, [*ctx.read_owners, doc.owner_id])
        return JSONResponse(content=recurrent_fit.predict(live, float(horizon)))
    except recurrent_service.ModelNotFound:
        return JSONResponse(status_code=404, content={"detail": "Model not found."})
    except (FitError, ValueError, TypeError) as exc:
        return JSONResponse(status_code=422, content={"detail": str(exc)})
