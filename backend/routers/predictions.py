"""Reliability prediction (a parts count from handbook base rates): the
calculation, a product's parts list as lines, and the saved predictions.

Free for everyone: an exact calculation over published reference data. The
same calculation and the saved predictions are the ``analyse``, ``get``,
``list`` and ``change`` tool actions (backend/mcp_server.py), and so
``POST /api/v1/...`` and the CLI; these routes are the app's own.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Body, Depends
from fastapi.responses import JSONResponse

from backend.db import get_session
from backend.schema import ReliabilityPrediction
from backend.services import access as access_service
from backend.services import billing as billing_service
from backend.services import reliability_prediction as prediction_service
from backend.services import samples as samples_service
from backend.services.access import AccessCtx, get_access
from backend.services.reliability_prediction import PredictionError, PredictionNotFound
from backend.errors import client_message

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/predictions")

NOT_FOUND = {"detail": "Prediction not found."}


def _summary(doc: ReliabilityPrediction, ctx: AccessCtx) -> dict:
    return {
        **prediction_service.brief(doc),
        "is_sample": samples_service.is_sample(doc.owner_id),
        "read_only": not access_service.can_write(ctx, doc.owner_id),
    }


def _full(doc: ReliabilityPrediction, ctx: AccessCtx) -> dict:
    return {**_summary(doc, ctx), "inputs": doc.inputs, "results": doc.results}


@router.post("/compute")
def compute_prediction(
    lines: list = Body(default=[]),
    environment: str | None = Body(default=None),
    mission_time: float | None = Body(default=None),
    ctx: AccessCtx = Depends(get_access),
) -> JSONResponse:
    """The parts count for a parts list, saving nothing."""
    try:
        return JSONResponse(content=prediction_service.compute(
            lines, environment or prediction_service.DEFAULT_ENVIRONMENT,
            prediction_service.DEFAULT_MISSION_HOURS if mission_time is None else mission_time))
    except PredictionError as exc:
        return JSONResponse(status_code=422, content={"detail": client_message(exc)})


@router.get("/environments")
def prediction_environments() -> JSONResponse:
    """The handbook's use environments, with the defaults the page starts from."""
    return JSONResponse(content={
        "environments": prediction_service.environments(),
        "default_environment": prediction_service.DEFAULT_ENVIRONMENT,
        "default_mission_time": prediction_service.DEFAULT_MISSION_HOURS,
        "default_quality_factor": prediction_service.DEFAULT_QUALITY_FACTOR,
        "handbook_source": prediction_service.HANDBOOK_SOURCE,
    })


@router.get("/from-product/{product_id}")
def lines_from_product(product_id: str, ctx: AccessCtx = Depends(get_access)) -> JSONResponse:
    """A product's parts list (its part's bill of materials) as prediction
    lines, each lowest-level part under its assemblies. Reliafy Maintenance
    users only (products live there)."""
    from backend.maintenance.service import Invalid, NotFound
    from backend.routers.maintenance import maintenance

    m = maintenance(ctx)
    try:
        return JSONResponse(content=prediction_service.lines_from_product(m, product_id))
    except NotFound:
        return JSONResponse(status_code=404, content={"detail": "Not found."})
    except Invalid as exc:
        return JSONResponse(status_code=422, content={"detail": client_message(exc)})


@router.post("")
def save_prediction(
    name: str = Body(...),
    inputs: dict = Body(default={}),
    session=Depends(get_session),
    ctx: AccessCtx = Depends(get_access),
) -> JSONResponse:
    """Save a prediction. The results are computed here from the inputs;
    clients never supply them."""
    denied = access_service.workspace_write_denial(ctx)
    if denied is not None:
        status, payload = denied
        return JSONResponse(status_code=status, content=payload)
    if (ctx.is_personal and not billing_service.is_admin_user(ctx.user)
            and billing_service.would_exceed_cap(session, ctx.uid, prediction_service.COLLECTION)):
        return JSONResponse(status_code=402, content={
            "detail": billing_service.cap_message(session, ctx.uid, prediction_service.COLLECTION),
            "code": "cap", "upgrade": True})
    try:
        doc = prediction_service.save_prediction(session, name, inputs, ctx.write_owner)
        access_service.stamp_editor(session, prediction_service.COLLECTION, doc.id, ctx)
    except PredictionError as exc:
        return JSONResponse(status_code=422, content={"detail": client_message(exc)})
    return JSONResponse(content=_full(doc, ctx))


@router.get("")
def list_predictions(session=Depends(get_session), ctx: AccessCtx = Depends(get_access)) -> dict:
    return {"predictions": [_summary(d, ctx) for d in prediction_service.list_predictions(
        session, ctx.list_owners, ctx.hidden)]}


@router.get("/{prediction_id}")
def get_prediction(prediction_id: str, session=Depends(get_session),
                   ctx: AccessCtx = Depends(get_access)) -> JSONResponse:
    doc, _ = access_service.fetch_readable(session, prediction_service.COLLECTION, ReliabilityPrediction,
                                           prediction_id, ctx)
    if doc is None or doc.id in ctx.hidden:
        return JSONResponse(status_code=404, content=NOT_FOUND)
    return JSONResponse(content=_full(doc, ctx))


@router.patch("/{prediction_id}")
def update_prediction(
    prediction_id: str,
    name: str | None = Body(default=None),
    inputs: dict | None = Body(default=None),
    session=Depends(get_session),
    ctx: AccessCtx = Depends(get_access),
) -> JSONResponse:
    """Rename one of your own predictions, or replace its parts list and
    conditions (the results are computed again)."""
    existing, _ = access_service.fetch_readable(session, prediction_service.COLLECTION, ReliabilityPrediction,
                                                prediction_id, ctx)
    if existing is not None:
        denial = access_service.write_denial(ctx, existing.owner_id)
        if denial:
            status, payload = denial
            return JSONResponse(status_code=status, content=payload)
    try:
        doc = prediction_service.update_prediction(session, prediction_id, ctx.write_owner, name=name, inputs=inputs)
        access_service.stamp_editor(session, prediction_service.COLLECTION, doc.id, ctx)
    except PredictionNotFound:
        return JSONResponse(status_code=404, content=NOT_FOUND)
    except PredictionError as exc:
        return JSONResponse(status_code=422, content={"detail": client_message(exc)})
    return JSONResponse(content=_full(doc, ctx))


@router.delete("/{prediction_id}")
def delete_prediction(prediction_id: str, session=Depends(get_session),
                      ctx: AccessCtx = Depends(get_access)) -> JSONResponse:
    """Delete your own prediction; a shared sample is hidden from your view."""
    doc, _ = access_service.fetch_readable(session, prediction_service.COLLECTION, ReliabilityPrediction,
                                           prediction_id, ctx)
    if doc is None or doc.id in ctx.hidden:
        return JSONResponse(status_code=404, content=NOT_FOUND)
    if access_service.can_write(ctx, doc.owner_id):
        try:
            prediction_service.delete_prediction(session, prediction_id, ctx.write_owner)
        except PredictionNotFound:
            return JSONResponse(status_code=404, content=NOT_FOUND)
    elif samples_service.is_sample(doc.owner_id):
        samples_service.hide_sample(session, ctx.uid, prediction_id)
    else:
        status, payload = access_service.write_denial(ctx, doc.owner_id)
        return JSONResponse(status_code=status, content=payload)
    return JSONResponse(content={"ok": True})
