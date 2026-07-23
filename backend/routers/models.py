"""Saved datasets and models API."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Body, Depends, File, Form, UploadFile
from fastapi.responses import JSONResponse

from backend.db import get_session
from backend.fitting import FitError, options_from_form
from backend import storage
from backend.services import billing as billing_service
from backend.services import datasets as datasets_service
from backend.services import models as models_service
from backend.services import samples as samples_service
from backend.services import shares as shares_service
from backend.services import access as access_service
from backend.services.access import AccessCtx, get_access
from backend.schema import Dataset, Model

_CAP_MSG = "You've reached the free-plan limit. Upgrade to Pro for unlimited saves."

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api")


def _creation_denied(session, ctx: AccessCtx, kind: str, cap_msg: str = _CAP_MSG) -> JSONResponse | None:
    """Frozen-team or free-plan-cap rejection for a create, or None."""
    denied = access_service.workspace_write_denial(ctx)
    if denied is not None:
        status, payload = denied
        return JSONResponse(status_code=status, content=payload)
    if (
        ctx.is_personal
        and not billing_service.is_admin_user(ctx.user)
        and billing_service.would_exceed_cap(session, ctx.uid, kind)
    ):
        return JSONResponse(status_code=402, content={"detail": cap_msg, "code": "cap", "upgrade": True})
    return None


def _model_summary(model, ctx: AccessCtx) -> dict:
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
        "read_only": not access_service.can_write(ctx, model.owner_id),
        "updated_by": (model.updated_by or {}).get("name"),
        # Randomness verdict (weibull beta CI / exponential), used when picking
        # RCM evidence for run-to-failure decisions.
        "randomness": results.get("randomness"),
    }


def _model_detail(model, ctx: AccessCtx) -> dict:
    return {
        **_model_summary(model, ctx),
        "updated_at": model.updated_at.isoformat(),
        "spec": model.spec,
        "results": models_service.public_results(model),
        "saved": True,
    }


def _dataset_summary(dataset, ctx: AccessCtx, n_models: int = 0) -> dict:
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
        "read_only": not access_service.can_write(ctx, dataset.owner_id),
    }


def _dataset_detail(dataset, session, ctx: AccessCtx) -> dict:
    models = datasets_service.models_for_dataset(session, dataset.id, ctx.read_owners, ctx.hidden)
    summary = _dataset_summary(dataset, ctx, n_models=len(models))
    try:
        preview = datasets_service.preview_rows(dataset)
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning("Failed to build dataset preview: %s", exc)
        preview = {"columns": [c["name"] for c in (dataset.columns or [])], "preview": [], "n_rows": dataset.n_rows}
    return {
        **summary,
        "preview": preview.get("preview", []),
        "preview_columns": preview.get("columns", []),
        "models": [_model_summary(m, ctx) for m in models],
    }


@router.get("/datasets")
def list_datasets(session=Depends(get_session), ctx: AccessCtx = Depends(get_access)) -> dict:
    shared_by = shares_service.shared_by_map(session, ctx.uid, "datasets") if ctx.is_personal else {}
    counts: dict[str, int] = {}
    for m in models_service.list_models(session, ctx.list_owners, ctx.hidden):
        counts[m.dataset_id] = counts.get(m.dataset_id, 0) + 1
    return {
        "datasets": [
            {**_dataset_summary(d, ctx, n_models=counts.get(d.id, 0)),
             **({"shared_by": shared_by[d.id]} if d.id in shared_by else {})}
            for d in datasets_service.list_datasets(session, ctx.list_owners, ctx.hidden, shared=set(shared_by))
        ]
    }


@router.post("/datasets")
async def upload_dataset(
    file: UploadFile = File(...),
    name: str | None = Form(default=None),
    no_header: bool = Form(default=False),
    session=Depends(get_session),
    ctx: AccessCtx = Depends(get_access),
) -> JSONResponse:
    """Store an uploaded CSV as a standalone dataset (no fit required)."""
    contents = await file.read()
    # Free-plan cap (new datasets only — re-uploading an existing file is fine).
    denied = _creation_denied(session, ctx, "datasets")
    if denied is not None:
        digest = storage.checksum(contents)
        if session.datasets.find_one({"checksum": digest, "owner_id": ctx.write_owner}) is None:
            return denied
    try:
        dataset = datasets_service.create_dataset(
            session, name or file.filename or "dataset.csv", contents, ctx.write_owner,
            no_header=no_header,
        )
    except FitError as exc:
        return JSONResponse(status_code=422, content={"detail": str(exc)})
    except Exception as exc:  # pragma: no cover - defensive
        logger.exception("Failed to store dataset")
        return JSONResponse(
            status_code=500, content={"detail": f"Failed to store dataset: {exc}"}
        )
    return JSONResponse(content=_dataset_detail(dataset, session, ctx))


@router.post("/datasets/paste")
def paste_dataset(
    name: str = Body(default=""),
    content: str = Body(default=""),
    no_header: bool = Body(default=False),
    session=Depends(get_session),
    ctx: AccessCtx = Depends(get_access),
) -> JSONResponse:
    """Create a dataset from pasted tabular text (CSV or TSV). Used by the
    paste-data form and the assistant."""
    try:
        csv_bytes = datasets_service.normalize_pasted(content)
    except FitError as exc:
        return JSONResponse(status_code=422, content={"detail": str(exc)})
    # Free-plan cap (skipped when the identical data already exists).
    denied = _creation_denied(session, ctx, "datasets")
    if denied is not None:
        digest = storage.checksum(csv_bytes)
        if session.datasets.find_one({"checksum": digest, "owner_id": ctx.write_owner}) is None:
            return denied
    try:
        dataset = datasets_service.create_dataset(
            session, (name or "").strip() or "Pasted data", csv_bytes, ctx.write_owner,
            no_header=no_header,
        )
    except FitError as exc:
        return JSONResponse(status_code=422, content={"detail": str(exc)})
    except Exception as exc:  # pragma: no cover - defensive
        logger.exception("Failed to store pasted dataset")
        return JSONResponse(status_code=500, content={"detail": f"Failed to store dataset: {exc}"})
    return JSONResponse(content=_dataset_detail(dataset, session, ctx))


@router.get("/datasets/{dataset_id}")
def get_dataset(
    dataset_id: str, session=Depends(get_session), ctx: AccessCtx = Depends(get_access)
) -> JSONResponse:
    dataset, _ = access_service.fetch_readable(session, "datasets", Dataset, dataset_id, ctx)
    if dataset is None or dataset.id in ctx.hidden:
        return JSONResponse(status_code=404, content={"detail": "Dataset not found."})
    return JSONResponse(content=_dataset_detail(dataset, session, ctx))


@router.delete("/datasets/{dataset_id}")
def delete_dataset(
    dataset_id: str, session=Depends(get_session), ctx: AccessCtx = Depends(get_access)
) -> JSONResponse:
    dataset, _ = access_service.fetch_readable(session, "datasets", Dataset, dataset_id, ctx)
    if dataset is None or dataset.id in ctx.hidden:
        return JSONResponse(status_code=404, content={"detail": "Dataset not found."})

    models = datasets_service.models_for_dataset(session, dataset_id, ctx.read_owners, ctx.hidden)
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

    if access_service.can_write(ctx, dataset.owner_id):
        if not datasets_service.delete_dataset(session, dataset_id, ctx.write_owner):
            return JSONResponse(status_code=404, content={"detail": "Dataset not found."})
    elif samples_service.is_sample(dataset.owner_id) or access_service.is_shared_with(session, ctx.uid, dataset_id):
        samples_service.hide_sample(session, ctx.uid, dataset_id)
    else:
        status, payload = access_service.write_denial(ctx, dataset.owner_id)
        return JSONResponse(status_code=status, content=payload)
    return JSONResponse(content={"ok": True})


@router.get("/models")
def list_models(session=Depends(get_session), ctx: AccessCtx = Depends(get_access)) -> dict:
    shared_by = shares_service.shared_by_map(session, ctx.uid, "models") if ctx.is_personal else {}
    return {
        "models": [
            {**_model_summary(m, ctx),
             **({"shared_by": shared_by[m.id]} if m.id in shared_by else {})}
            for m in models_service.list_models(session, ctx.list_owners, ctx.hidden, shared=set(shared_by))
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
    offset: str | None = Form(default=None),
    zi: str | None = Form(default=None),
    lfp: str | None = Form(default=None),
    fixed: str | None = Form(default=None),
    session=Depends(get_session),
    ctx: AccessCtx = Depends(get_access),
) -> JSONResponse:
    """Fit and persist a model from a fit spec and either an uploaded CSV
    (``file``) or an existing saved dataset (``dataset_id``)."""
    denied = _creation_denied(session, ctx, "models")
    if denied is not None:
        return denied
    mapping = {"x": x, "c": c, "n": n, "xl": xl, "xr": xr, "tl": tl, "tr": tr}
    try:
        if dataset_id:
            # Scope to the workspace principal (+samples) so the saved model
            # only ever references a dataset its own owner can re-fetch.
            dataset = datasets_service.get_dataset(session, dataset_id, owner_id=ctx.write_owner)
            if dataset is None:
                return JSONResponse(
                    status_code=404, content={"detail": "Dataset not found."}
                )
        elif file is not None:
            dataset = datasets_service.create_dataset(
                session, file.filename or "dataset.csv", await file.read(), ctx.write_owner
            )
        else:
            return JSONResponse(
                status_code=422,
                content={"detail": "Provide a CSV file or a dataset_id."},
            )
        model = models_service.save_model(
            session, name, dataset, distribution, mapping, z, formula, unit,
            owner_id=ctx.write_owner,
            options=options_from_form(offset, zi, lfp, fixed),
        )
        access_service.stamp_editor(session, "models", model.id, ctx)
    except FitError as exc:
        return JSONResponse(status_code=422, content={"detail": str(exc)})
    except Exception as exc:  # pragma: no cover - defensive
        logger.exception("Failed to save model")
        return JSONResponse(
            status_code=500, content={"detail": f"Failed to save model: {exc}"}
        )
    return JSONResponse(content=_model_detail(model, ctx))


@router.post("/models/from-params")
def create_from_params(
    name: str = Body(...),
    distribution: str = Body(...),
    params: list = Body(default=[]),
    unit: str | None = Body(default=None),
    extras: dict | None = Body(default=None),
    session=Depends(get_session),
    ctx: AccessCtx = Depends(get_access),
) -> JSONResponse:
    """Create a parameters-only model (no data) — reliability functions and
    life metrics, but no probability plot. Counts against the model cap."""
    denied = _creation_denied(session, ctx, "models")
    if denied is not None:
        return denied
    if not (name or "").strip():
        return JSONResponse(status_code=422, content={"detail": "A name is required."})
    try:
        model = models_service.import_model(
            session, ctx.write_owner, name.strip(),
            distribution=distribution, unit=unit, params=params, extras=extras,
        )
        access_service.stamp_editor(session, "models", model.id, ctx)
    except FitError as exc:
        return JSONResponse(status_code=422, content={"detail": str(exc)})
    return JSONResponse(content=_model_detail(model, ctx))


@router.post("/models/per-demand")
def create_per_demand(
    name: str = Body(...),
    demands: int = Body(...),
    failures: int = Body(...),
    confidence: float = Body(default=0.95),
    session=Depends(get_session),
    ctx: AccessCtx = Depends(get_access),
) -> JSONResponse:
    """Create a per-demand (Binomial) model from demands + failures counts.
    A one-shot / protective-device reliability. With zero failures it's a
    success-run demonstration test (``confidence`` sets the demonstrated
    reliability lower bound). Counts against the model cap."""
    denied = _creation_denied(session, ctx, "models")
    if denied is not None:
        return denied
    if not (name or "").strip():
        return JSONResponse(status_code=422, content={"detail": "A name is required."})
    try:
        model = models_service.create_per_demand(session, ctx.write_owner, name.strip(), demands, failures, confidence)
        access_service.stamp_editor(session, "models", model.id, ctx)
    except FitError as exc:
        return JSONResponse(status_code=422, content={"detail": str(exc)})
    return JSONResponse(content=_model_detail(model, ctx))


@router.get("/models/{model_id}")
def get_model(
    model_id: str, session=Depends(get_session), ctx: AccessCtx = Depends(get_access)
) -> JSONResponse:
    model, _ = access_service.fetch_readable(session, "models", Model, model_id, ctx)
    if model is None:
        return JSONResponse(status_code=404, content={"detail": "Model not found."})
    return JSONResponse(content=_model_detail(model, ctx))


@router.put("/models/{model_id}/fit")
def update_model_fit(
    model_id: str,
    distribution: str = Body(...),
    mapping: dict = Body(default={}),
    covariates: list[str] = Body(default=[]),
    formula: str | None = Body(default=None),
    unit: str | None = Body(default=None),
    offset: bool = Body(default=False),
    zi: bool = Body(default=False),
    lfp: bool = Body(default=False),
    fixed: dict | None = Body(default=None),
    session=Depends(get_session),
    ctx: AccessCtx = Depends(get_access),
) -> JSONResponse:
    """Refit a saved model in place with an edited fit spec (same dataset)."""
    existing, _ = access_service.fetch_readable(session, "models", Model, model_id, ctx)
    if existing is None:
        return JSONResponse(status_code=404, content={"detail": "Model not found."})
    denial = access_service.write_denial(ctx, existing.owner_id)
    if denial:
        status, payload = denial
        return JSONResponse(status_code=status, content=payload)
    options = {"offset": offset, "zi": zi, "lfp": lfp, "fixed": fixed or None}
    try:
        model = models_service.update_fit(
            session, model_id, existing.owner_id, distribution,
            {k: (v or None) for k, v in mapping.items()},
            covariates, formula, unit,
            options if any(options.values()) else None,
        )
        access_service.stamp_editor(session, "models", model.id, ctx)
    except FitError as exc:
        return JSONResponse(status_code=422, content={"detail": str(exc)})
    except models_service.ModelNotFound:
        return JSONResponse(status_code=404, content={"detail": "Model not found."})
    return JSONResponse(content=_model_detail(model, ctx))


@router.patch("/models/{model_id}")
def rename_model(
    model_id: str,
    name: str = Body(..., embed=True),
    session=Depends(get_session),
    ctx: AccessCtx = Depends(get_access),
) -> JSONResponse:
    existing, _ = access_service.fetch_readable(session, "models", Model, model_id, ctx)
    if existing is not None:
        denial = access_service.write_denial(ctx, existing.owner_id)
        if denial:
            status, payload = denial
            return JSONResponse(status_code=status, content=payload)
    try:
        model = models_service.rename_model(session, model_id, name, ctx.write_owner)
        access_service.stamp_editor(session, "models", model.id, ctx)
    except models_service.ModelNotFound:
        return JSONResponse(status_code=404, content={"detail": "Model not found."})
    return JSONResponse(content=_model_detail(model, ctx))


@router.delete("/models/{model_id}")
def delete_model(
    model_id: str, session=Depends(get_session), ctx: AccessCtx = Depends(get_access)
) -> JSONResponse:
    model, via_share = access_service.fetch_readable(session, "models", Model, model_id, ctx)
    if model is None or model.id in ctx.hidden:
        return JSONResponse(status_code=404, content={"detail": "Model not found."})

    if access_service.can_write(ctx, model.owner_id):
        try:
            models_service.delete_model(session, model_id, ctx.write_owner)
        except models_service.ModelNotFound:
            return JSONResponse(status_code=404, content={"detail": "Model not found."})
    elif samples_service.is_sample(model.owner_id) or access_service.is_shared_with(session, ctx.uid, model_id):
        # Samples and shared-with-me artifacts aren't really deleted — just
        # hidden for this user.
        samples_service.hide_sample(session, ctx.uid, model_id)
    else:
        status, payload = access_service.write_denial(ctx, model.owner_id)
        return JSONResponse(status_code=status, content=payload)
    return JSONResponse(content={"ok": True})


@router.post("/models/{model_id}/evaluate")
def evaluate_model(
    model_id: str,
    values: dict = Body(default={}),
    x_min: float | None = None,
    x_max: float | None = None,
    session=Depends(get_session),
    ctx: AccessCtx = Depends(get_access),
) -> JSONResponse:
    model, _ = access_service.fetch_readable(session, "models", Model, model_id, ctx)
    if model is None:
        return JSONResponse(status_code=404, content={"detail": "Model not found."})
    try:
        return JSONResponse(
            content=models_service.evaluate(
                session, model_id, values, [*ctx.read_owners, model.owner_id],
                x_min=x_min, x_max=x_max,
            )
        )
    except models_service.ModelNotFound:
        return JSONResponse(status_code=404, content={"detail": "Model not found."})
    except FitError as exc:
        return JSONResponse(status_code=422, content={"detail": str(exc)})


@router.post("/models/{model_id}/confidence")
def confidence_model(
    model_id: str,
    params: dict = Body(default={}),
    x_min: float | None = None,
    x_max: float | None = None,
    session=Depends(get_session),
    ctx: AccessCtx = Depends(get_access),
) -> JSONResponse:
    """Confidence bounds of a saved model's reliability function, at a
    configurable significance level and bound (two-sided / lower / upper)."""
    model, _ = access_service.fetch_readable(session, "models", Model, model_id, ctx)
    if model is None:
        return JSONResponse(status_code=404, content={"detail": "Model not found."})
    try:
        return JSONResponse(
            content=models_service.confidence(
                session, model_id, params, [*ctx.read_owners, model.owner_id],
                x_min=x_min, x_max=x_max,
            )
        )
    except models_service.ModelNotFound:
        return JSONResponse(status_code=404, content={"detail": "Model not found."})
    except (FitError, ValueError, TypeError) as exc:
        return JSONResponse(status_code=422, content={"detail": str(exc)})
