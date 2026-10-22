"""Condition monitoring models (joint models of readings and failures) API.

Saved in ``models`` with ``kind: "joint"`` (see ``backend.services.joint``).
The fit is Pro and heavy: with the compute queue configured it answers 202
with a job to poll at ``/api/rbd-jobs/{job_id}``, whose result names the
saved model."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Body, Depends
from fastapi.responses import JSONResponse, Response

from backend import joint
from backend.db import get_session
from backend.fitting import FitError
from backend.schema import Model
from backend.services import access as access_service
from backend.services import billing as billing_service
from backend.services import joint as joint_service
from backend.services import models as models_service
from backend.services import samples as samples_service
from backend.services import shares as shares_service
from backend.services.access import AccessCtx, get_access

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api")

NOT_FOUND = {"detail": "Model not found."}


def _summary(model: Model, ctx: AccessCtx) -> dict:
    return {
        **joint_service.summary(model),
        "is_sample": samples_service.is_sample(model.owner_id),
        "read_only": not access_service.can_write(ctx, model.owner_id),
        "updated_by": (model.updated_by or {}).get("name"),
    }


def _readable(session, model_id: str, ctx: AccessCtx) -> Model | None:
    doc, _ = access_service.fetch_readable(session, "models", Model, model_id, ctx)
    if doc is None or doc.id in ctx.hidden or doc.kind != joint_service.KIND:
        return None
    return doc


def _detail(model: Model, ctx: AccessCtx) -> dict:
    spec = dict(model.spec or {})
    return {
        **_summary(model, ctx),
        "updated_at": model.updated_at.isoformat(),
        "spec": spec,
        "notes": spec.get("notes") or "",
        "results": model.results or {},
        "running_units": joint_service.running_units(model),
        "surpyval_version": model.surpyval_version,
    }


@router.get("/joint/options")
def options(ctx: AccessCtx = Depends(get_access)) -> dict:
    """The path models and limits the new-model form offers."""
    return joint.options()


@router.post("/joint/check")
def check(body: dict = Body(...), session=Depends(get_session), ctx: AccessCtx = Depends(get_access)) -> JSONResponse:
    """Read the two tables as a fit would and say what it would take: units,
    failures, running units, readings, and any readings that match no unit.
    Free, quick and saves nothing."""
    try:
        return JSONResponse(content=joint_service.check(session, body, ctx.write_owner))
    except FitError as exc:
        return JSONResponse(status_code=422, content={"detail": str(exc)})


@router.post("/joint/models")
def fit_model(body: dict = Body(...), session=Depends(get_session), ctx: AccessCtx = Depends(get_access)) -> JSONResponse:
    """Fit and save a condition monitoring model (Pro). ``body``:
    ``name``, ``lifetimes_dataset_id``, ``readings_dataset_id``, ``mapping``
    ``{id, x | xl+xr, c, tl?}``, ``readings_mapping`` ``{id, age, value}``,
    ``covariates``, ``hazard_covariates?``, ``path_covariates?`` (a list, or
    ``{path parameter: [...]}``), ``path_model``, ``unit``, ``marker?``,
    ``marker_unit?``, ``c_invert?``. Answers 200 ``{model_id, model}`` when
    it ran here, 202 ``{job}`` to poll, 402 for a plan without it."""
    denied = access_service.workspace_write_denial(ctx)
    if denied is not None:
        status, payload = denied
        return JSONResponse(status_code=status, content=payload)
    if not billing_service.premium_compute_allowed(session, ctx.user):
        return JSONResponse(status_code=402, content=dict(joint_service.PRO_PAYLOAD))
    if (ctx.is_personal and not billing_service.is_admin_user(ctx.user)
            and billing_service.would_exceed_cap(session, ctx.uid, "models")):
        return JSONResponse(status_code=402, content={
            "detail": billing_service.cap_message(session, ctx.uid, "models"), "code": "cap", "upgrade": True})
    try:
        status, payload = joint_service.start_fit(session, uid=ctx.uid, owners=ctx.write_owner, body=body,
                                                  save=True, owner_id=ctx.write_owner)
    except FitError as exc:
        return JSONResponse(status_code=422, content={"detail": str(exc)})
    except Exception:  # pragma: no cover - defensive
        logger.exception("Joint model fit failed")
        return JSONResponse(status_code=500, content={"detail": "The fit failed. The error has been logged."})
    if status == 200 and payload.get("model_id"):
        access_service.stamp_editor(session, "models", payload["model_id"], ctx)
        model = models_service.get_model(session, payload["model_id"])
        payload = {"model_id": model.id, "model": _detail(model, ctx)}
    return JSONResponse(status_code=status, content=payload)


@router.get("/joint/models")
def list_models(session=Depends(get_session), ctx: AccessCtx = Depends(get_access)) -> dict:
    shared_by = shares_service.shared_by_map(session, ctx.uid, "models") if ctx.is_personal else {}
    models = joint_service.list_models(session, ctx.list_owners, ctx.hidden, shared=set(shared_by))
    return {"models": [
        {**_summary(m, ctx), **({"shared_by": shared_by[m.id]} if m.id in shared_by else {})}
        for m in models
    ]}


@router.get("/joint/models/{model_id}")
def get_model(model_id: str, session=Depends(get_session), ctx: AccessCtx = Depends(get_access)) -> JSONResponse:
    model = _readable(session, model_id, ctx)
    if model is None:
        return JSONResponse(status_code=404, content=NOT_FOUND)
    return JSONResponse(content=_detail(model, ctx))


@router.patch("/joint/models/{model_id}")
def update_model(model_id: str, body: dict = Body(...), session=Depends(get_session),
                 ctx: AccessCtx = Depends(get_access)) -> JSONResponse:
    """Rename a model or set its notes."""
    model = _readable(session, model_id, ctx)
    if model is None:
        return JSONResponse(status_code=404, content=NOT_FOUND)
    denial = access_service.write_denial(ctx, model.owner_id)
    if denial:
        status, payload = denial
        return JSONResponse(status_code=status, content=payload)
    try:
        if body.get("name") is not None:
            model = models_service.rename_model(session, model_id, str(body["name"]), model.owner_id)
        if body.get("notes") is not None:
            model = models_service.set_notes(session, model_id, str(body["notes"]), model.owner_id)
        access_service.stamp_editor(session, "models", model_id, ctx)
    except models_service.ModelNotFound:
        return JSONResponse(status_code=404, content=NOT_FOUND)
    except ValueError as exc:
        return JSONResponse(status_code=422, content={"detail": str(exc)})
    return JSONResponse(content=_detail(models_service.get_model(session, model_id), ctx))


@router.delete("/joint/models/{model_id}")
def delete_model(model_id: str, session=Depends(get_session), ctx: AccessCtx = Depends(get_access)) -> JSONResponse:
    model = _readable(session, model_id, ctx)
    if model is None:
        return JSONResponse(status_code=404, content=NOT_FOUND)
    if access_service.can_write(ctx, model.owner_id):
        try:
            models_service.delete_model(session, model_id, model.owner_id)
        except models_service.ModelNotFound:
            return JSONResponse(status_code=404, content=NOT_FOUND)
    elif samples_service.is_sample(model.owner_id) or access_service.is_shared_with(session, ctx.uid, model_id):
        samples_service.hide_sample(session, ctx.uid, model_id)
    else:
        status, payload = access_service.write_denial(ctx, model.owner_id)
        return JSONResponse(status_code=status, content=payload)
    return JSONResponse(content={"ok": True})


@router.get("/joint/models/{model_id}/units/{unit_id}")
def unit_view(model_id: str, unit_id: str, session=Depends(get_session),
              ctx: AccessCtx = Depends(get_access)) -> JSONResponse:
    """A fitted running unit's updating prediction: its survival from its
    age now (with 95% bounds), remaining-life quantiles, and its reading's
    smoothed and projected path with an interval."""
    model = _readable(session, model_id, ctx)
    if model is None:
        return JSONResponse(status_code=404, content=NOT_FOUND)
    try:
        return JSONResponse(content=joint_service.unit_view(model, unit_id))
    except FitError as exc:
        return JSONResponse(status_code=422, content={"detail": str(exc)})


@router.post("/joint/models/{model_id}/predict")
def predict(model_id: str, body: dict = Body(...), session=Depends(get_session),
            ctx: AccessCtx = Depends(get_access)) -> JSONResponse:
    """The same for a unit given by its values: ``{age, markers: [[age,
    value], ...], covariates: {name: value}}``, ages since new."""
    model = _readable(session, model_id, ctx)
    if model is None:
        return JSONResponse(status_code=404, content=NOT_FOUND)
    try:
        return JSONResponse(content=joint_service.predict(model, body))
    except FitError as exc:
        return JSONResponse(status_code=422, content={"detail": str(exc)})


@router.get("/joint/models/{model_id}/export.py")
def export_python(model_id: str, session=Depends(get_session), ctx: AccessCtx = Depends(get_access)) -> Response:
    """Download as Python: a script that refits the model with SurPyval's
    ``fit_from_df`` from the data it was fitted to (embedded). Free for
    anyone who can view the model."""
    from backend.routers.rbds import python_download

    model = _readable(session, model_id, ctx)
    if model is None:
        return JSONResponse(status_code=404, content=NOT_FOUND)
    try:
        filename, source = joint_service.export_python(session, model, [*ctx.read_owners, model.owner_id])
    except FitError as exc:
        return JSONResponse(status_code=422, content={"detail": str(exc)})
    return python_download(filename, source)
