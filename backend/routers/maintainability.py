"""Maintainability prediction: the calculator (saves nothing), saved
predictions, and a product's parts list as prediction lines.

The same calculation is the MCP action ``analyse maintainability`` (with its
REST twin ``POST /api/v1/analyse/maintainability`` and the CLI); these are the
app's own routes, scoped by workspace like the strategy analyses'."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Body, Depends
from fastapi.responses import JSONResponse

from backend import config
from backend.db import get_session
from backend.schema import MaintainabilityPrediction
from backend.services import access as access_service
from backend.services import billing as billing_service
from backend.services import maintainability as service
from backend.services import samples as samples_service
from backend.services.access import AccessCtx, get_access
from backend.services.maintainability import MaintainabilityError, PredictionNotFound
from backend.errors import client_message

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/maintainability")

COLLECTION = service.COLLECTION


def _summary(doc: MaintainabilityPrediction, ctx: AccessCtx) -> dict:
    r = doc.results or {}
    return {
        "id": doc.id,
        "name": doc.name,
        "headline": service.headline(doc),
        "product": r.get("product"),
        "lines": (r.get("counts") or {}).get("lines"),
        "is_sample": samples_service.is_sample(doc.owner_id),
        "read_only": not access_service.can_write(ctx, doc.owner_id),
        "updated_by": (doc.updated_by or {}).get("name"),
        "created_at": doc.created_at.isoformat(),
        "updated_at": doc.updated_at.isoformat(),
    }


def _full(doc: MaintainabilityPrediction, ctx: AccessCtx) -> dict:
    return {**_summary(doc, ctx), "inputs": doc.inputs, "results": doc.results}


def _rates_for(session, ctx: AccessCtx, inputs: dict) -> dict | None:
    return service.prediction_rates(session, (inputs or {}).get("product_id"), ctx.read_owners)


@router.post("/analyse")
def analyse(inputs: dict = Body(default={}), session=Depends(get_session), ctx: AccessCtx = Depends(get_access),
            ) -> JSONResponse:
    """The prediction for these inputs, saving nothing."""
    try:
        return JSONResponse(content=service.compute(inputs, _rates_for(session, ctx, inputs)))
    except MaintainabilityError as exc:
        return JSONResponse(status_code=422, content={"detail": client_message(exc)})
    except Exception:  # pragma: no cover - defensive
        logger.exception("Maintainability prediction failed")
        return JSONResponse(status_code=500, content={"detail": "Calculation failed. The error has been logged."})


@router.get("/products/{product_id}/lines")
def product_lines(product_id: str, session=Depends(get_session), ctx: AccessCtx = Depends(get_access)) -> JSONResponse:
    """A product's parts list as lines to fill in (Reliafy Maintenance), with
    the failure rates of a saved reliability prediction for it, if any."""
    if not config.MAINTENANCE_ENABLED:
        return JSONResponse(status_code=404, content={"detail": "Products need Reliafy Maintenance."})
    from backend.maintenance.service import Invalid, NotFound
    from backend.routers.maintenance import maintenance

    try:
        m = maintenance(ctx)
        out = service.product_lines(m, product_id)
    except NotFound:
        return JSONResponse(status_code=404, content={"detail": "Product not found."})
    except Invalid as exc:
        return JSONResponse(status_code=422, content={"detail": client_message(exc)})
    rates = service.prediction_rates(session, product_id, ctx.read_owners)
    found = 0
    if rates:
        for line in out["lines"]:
            for key in (line.get("ref"), line.get("name")):
                hit = rates["rates"].get(str(key or "").lower()) if key else None
                if hit is not None:
                    line["failure_rate"] = hit
                    found += 1
                    break
    out["rates"] = ({"source": "reliability_prediction", "prediction": {"id": rates["id"], "name": rates["name"]},
                     "unit": rates.get("unit"), "matched": found} if rates and found else {"source": None})
    return JSONResponse(content=out)


@router.post("/predictions")
def save_prediction(name: str = Body(...), inputs: dict = Body(default={}), session=Depends(get_session),
                    ctx: AccessCtx = Depends(get_access)) -> JSONResponse:
    """Save a prediction. Its results are computed on the server from the inputs."""
    denied = access_service.workspace_write_denial(ctx)
    if denied is not None:
        status, payload = denied
        return JSONResponse(status_code=status, content=payload)
    if (ctx.is_personal and not billing_service.is_admin_user(ctx.user)
            and billing_service.would_exceed_cap(session, ctx.uid, COLLECTION)):
        return JSONResponse(status_code=402, content={
            "detail": billing_service.cap_message(session, ctx.uid, COLLECTION), "code": "cap", "upgrade": True})
    try:
        doc = service.save_prediction(session, name, inputs, ctx.write_owner, _rates_for(session, ctx, inputs))
        access_service.stamp_editor(session, COLLECTION, doc.id, ctx)
    except MaintainabilityError as exc:
        return JSONResponse(status_code=422, content={"detail": client_message(exc)})
    return JSONResponse(content=_full(doc, ctx))


@router.get("/predictions")
def list_predictions(session=Depends(get_session), ctx: AccessCtx = Depends(get_access)) -> dict:
    return {"predictions": [_summary(d, ctx)
                            for d in service.list_predictions(session, ctx.list_owners, ctx.hidden)]}


@router.get("/predictions/{prediction_id}")
def get_prediction(prediction_id: str, session=Depends(get_session), ctx: AccessCtx = Depends(get_access),
                   ) -> JSONResponse:
    doc, _ = access_service.fetch_readable(session, COLLECTION, MaintainabilityPrediction, prediction_id, ctx)
    if doc is None or doc.id in ctx.hidden:
        return JSONResponse(status_code=404, content={"detail": "Prediction not found."})
    return JSONResponse(content=_full(doc, ctx))


@router.patch("/predictions/{prediction_id}")
def update_prediction(prediction_id: str, name: str | None = Body(default=None),
                      inputs: dict | None = Body(default=None), session=Depends(get_session),
                      ctx: AccessCtx = Depends(get_access)) -> JSONResponse:
    """Rename a prediction, or replace its inputs (the results are recomputed)."""
    existing, _ = access_service.fetch_readable(session, COLLECTION, MaintainabilityPrediction, prediction_id, ctx)
    if existing is not None:
        denial = access_service.write_denial(ctx, existing.owner_id)
        if denial:
            status, payload = denial
            return JSONResponse(status_code=status, content=payload)
    try:
        doc = service.update_prediction(session, prediction_id, ctx.write_owner, name=name, inputs=inputs,
                                        prediction=_rates_for(session, ctx, inputs) if inputs else None)
        access_service.stamp_editor(session, COLLECTION, doc.id, ctx)
    except PredictionNotFound:
        return JSONResponse(status_code=404, content={"detail": "Prediction not found."})
    except MaintainabilityError as exc:
        return JSONResponse(status_code=422, content={"detail": client_message(exc)})
    return JSONResponse(content=_full(doc, ctx))


@router.delete("/predictions/{prediction_id}")
def delete_prediction(prediction_id: str, session=Depends(get_session), ctx: AccessCtx = Depends(get_access),
                      ) -> JSONResponse:
    doc, _ = access_service.fetch_readable(session, COLLECTION, MaintainabilityPrediction, prediction_id, ctx)
    if doc is None or doc.id in ctx.hidden:
        return JSONResponse(status_code=404, content={"detail": "Prediction not found."})
    if access_service.can_write(ctx, doc.owner_id):
        try:
            service.delete_prediction(session, prediction_id, ctx.write_owner)
        except PredictionNotFound:
            return JSONResponse(status_code=404, content={"detail": "Prediction not found."})
    elif samples_service.is_sample(doc.owner_id) or access_service.is_shared_with(session, ctx.uid, prediction_id):
        samples_service.hide_sample(session, ctx.uid, prediction_id)
    else:
        status, payload = access_service.write_denial(ctx, doc.owner_id)
        return JSONResponse(status_code=status, content=payload)
    return JSONResponse(content={"ok": True})
