"""Accelerated Life Testing (ALT) models API."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Body, Depends, File, Form, UploadFile
from fastapi.responses import JSONResponse

from backend import alt as alt_fit
from backend.db import get_session
from backend.fitting import FitError
from backend.services import datasets as datasets_service
from backend.services import alt as alt_service
from backend.services import samples as samples_service
from backend.services import access as access_service
from backend.services import shares as shares_service
from backend.services.access import AccessCtx, get_access
from backend.schema import AltModelDoc

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api")


def _spec_from_form(x, s1, s2, distribution, life_model, unit, *, c=None, n=None,
                    s1_label=None, s2_label=None) -> dict:
    mapping = {"x": x}
    for key, val in (("c", c), ("n", n)):
        if val:
            mapping[key] = val
    stress_cols = [s1] + ([s2] if s2 else [])
    stress_labels = [s1_label or s1] + ([s2_label or s2] if s2 else [])
    return {
        "mapping": mapping,
        "stress_cols": stress_cols,
        "stress_labels": stress_labels,
        "distribution_id": (distribution or "weibull"),
        "life_model_id": (life_model or "arrhenius"),
        "unit": (unit or "").strip(),
    }


def _model_summary(doc, ctx: AccessCtx) -> dict:
    r = doc.results or {}
    return {
        "id": doc.id,
        "name": doc.name,
        "kind": "alt",
        "distribution": r.get("distribution"),
        "life_model": r.get("life_model"),
        "n": r.get("n"),
        "n_stresses": len(r.get("stresses") or []),
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


@router.get("/alt/options")
def alt_options(ctx: AccessCtx = Depends(get_access)) -> dict:
    """Life-stress relationships (with stress count) and the distributions ALT
    supports — drives the New-model picker."""
    return {
        "life_models": [
            {"id": k, "name": v["name"], "n_stress": v["n_stress"], "desc": v["desc"]}
            for k, v in alt_fit.LIFE_MODELS.items()
        ],
        "distributions": [
            {"id": k, "name": alt_fit.DISTRIBUTIONS[k]["name"]}
            for k in alt_fit.ALT_DISTRIBUTIONS
        ],
    }


@router.post("/alt/fit")
async def fit_preview(
    file: UploadFile | None = File(default=None),
    dataset_id: str | None = Form(default=None),
    x: str = Form(...),
    s1: str = Form(...),
    s2: str | None = Form(default=None),
    s1_label: str | None = Form(default=None),
    s2_label: str | None = Form(default=None),
    c: str | None = Form(default=None),
    n: str | None = Form(default=None),
    distribution: str = Form(default="weibull"),
    life_model: str = Form(default="arrhenius"),
    unit: str | None = Form(default=None),
    session=Depends(get_session),
    ctx: AccessCtx = Depends(get_access),
) -> JSONResponse:
    """Fit an ALT model for preview (only the uploaded dataset is stored)."""
    try:
        dataset = await _resolve_dataset(session, ctx, dataset_id, file)
        spec = _spec_from_form(x, s1, s2, distribution, life_model, unit,
                               c=c, n=n, s1_label=s1_label, s2_label=s2_label)
        df = datasets_service.load_dataframe(dataset)
        payload, _ = alt_fit.fit(
            df, spec["mapping"], spec["stress_cols"],
            distribution_id=spec["distribution_id"], life_model_id=spec["life_model_id"],
            unit=spec["unit"], stress_labels=spec["stress_labels"],
        )
    except FitError as exc:
        return JSONResponse(status_code=422, content={"detail": str(exc)})
    except Exception as exc:  # pragma: no cover - defensive
        logger.exception("ALT fit failed")
        return JSONResponse(status_code=500, content={"detail": f"Fit failed: {exc}"})
    return JSONResponse(content={"dataset_id": dataset.id, "spec": spec, "results": payload})


@router.post("/alt/models")
async def save_model(
    name: str = Form(...),
    file: UploadFile | None = File(default=None),
    dataset_id: str | None = Form(default=None),
    x: str = Form(...),
    s1: str = Form(...),
    s2: str | None = Form(default=None),
    s1_label: str | None = Form(default=None),
    s2_label: str | None = Form(default=None),
    c: str | None = Form(default=None),
    n: str | None = Form(default=None),
    distribution: str = Form(default="weibull"),
    life_model: str = Form(default="arrhenius"),
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
        spec = _spec_from_form(x, s1, s2, distribution, life_model, unit,
                               c=c, n=n, s1_label=s1_label, s2_label=s2_label)
        doc = alt_service.save_model(session, name, dataset, spec, ctx.write_owner)
        access_service.stamp_editor(session, "alt_models", doc.id, ctx)
    except FitError as exc:
        return JSONResponse(status_code=422, content={"detail": str(exc)})
    except Exception as exc:  # pragma: no cover - defensive
        logger.exception("Failed to save ALT model")
        return JSONResponse(status_code=500, content={"detail": f"Failed to save: {exc}"})
    return JSONResponse(content={**_model_summary(doc, ctx), "spec": doc.spec, "results": doc.results})


@router.get("/alt/models")
def list_models(session=Depends(get_session), ctx: AccessCtx = Depends(get_access)) -> dict:
    shared_by = shares_service.shared_by_map(session, ctx.uid, "alt_models") if ctx.is_personal else {}
    models = alt_service.list_models(session, ctx.list_owners, ctx.hidden, shared=set(shared_by))
    return {"models": [
        {**_model_summary(m, ctx), **({"shared_by": shared_by[m.id]} if m.id in shared_by else {})}
        for m in models
    ]}


@router.get("/alt/models/{model_id}")
def get_model(model_id: str, session=Depends(get_session), ctx: AccessCtx = Depends(get_access)) -> JSONResponse:
    doc, _ = access_service.fetch_readable(session, "alt_models", AltModelDoc, model_id, ctx)
    if doc is None or doc.id in ctx.hidden:
        return JSONResponse(status_code=404, content={"detail": "Model not found."})
    return JSONResponse(content={**_model_summary(doc, ctx), "spec": doc.spec, "results": doc.results})


@router.patch("/alt/models/{model_id}")
def rename_model(
    model_id: str, name: str = Body(..., embed=True),
    session=Depends(get_session), ctx: AccessCtx = Depends(get_access),
) -> JSONResponse:
    existing = alt_service.get_model(session, model_id, ctx.read_owners)
    if existing is not None:
        denial = access_service.write_denial(ctx, existing.owner_id)
        if denial:
            status, payload = denial
            return JSONResponse(status_code=status, content=payload)
    try:
        doc = alt_service.rename_model(session, model_id, name, ctx.write_owner)
        access_service.stamp_editor(session, "alt_models", doc.id, ctx)
    except alt_service.ModelNotFound:
        return JSONResponse(status_code=404, content={"detail": "Model not found."})
    return JSONResponse(content=_model_summary(doc, ctx))


@router.delete("/alt/models/{model_id}")
def delete_model(model_id: str, session=Depends(get_session), ctx: AccessCtx = Depends(get_access)) -> JSONResponse:
    doc, _ = access_service.fetch_readable(session, "alt_models", AltModelDoc, model_id, ctx)
    if doc is None or doc.id in ctx.hidden:
        return JSONResponse(status_code=404, content={"detail": "Model not found."})
    if access_service.can_write(ctx, doc.owner_id):
        try:
            alt_service.delete_model(session, model_id, ctx.write_owner)
        except alt_service.ModelNotFound:
            return JSONResponse(status_code=404, content={"detail": "Model not found."})
    elif samples_service.is_sample(doc.owner_id) or access_service.is_shared_with(session, ctx.uid, model_id):
        samples_service.hide_sample(session, ctx.uid, model_id)
    else:
        status, payload = access_service.write_denial(ctx, doc.owner_id)
        return JSONResponse(status_code=status, content=payload)
    return JSONResponse(content={"ok": True})


@router.post("/alt/models/{model_id}/evaluate")
def evaluate(
    model_id: str,
    use_stress: list[float] = Body(..., embed=True),
    ref_stress: list[float] | None = Body(default=None, embed=True),
    session=Depends(get_session), ctx: AccessCtx = Depends(get_access),
) -> JSONResponse:
    """Reliability at a use-level stress (with optional acceleration factor vs a
    reference/test stress) for the saved ALT model."""
    doc, _ = access_service.fetch_readable(session, "alt_models", AltModelDoc, model_id, ctx)
    if doc is None:
        return JSONResponse(status_code=404, content={"detail": "Model not found."})
    try:
        result = alt_service.evaluate(
            session, model_id, list(use_stress), [*ctx.read_owners, doc.owner_id],
            ref_stress=list(ref_stress) if ref_stress else None,
        )
        return JSONResponse(content=result)
    except alt_service.ModelNotFound:
        return JSONResponse(status_code=404, content={"detail": "Model not found."})
    except (FitError, ValueError, TypeError) as exc:
        return JSONResponse(status_code=422, content={"detail": str(exc)})
