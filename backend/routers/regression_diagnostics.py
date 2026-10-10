"""Regression model checks (#61): the proportional-hazards test, robust
standard errors, ties and strata of a saved model, and the residuals behind
the test, for a saved model or a fit not yet saved."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

from backend import fitting, regression_diagnostics as rd
from backend.auth import get_current_user
from backend.db import get_session
from backend.fitting import FitError
from backend.schema import Model
from backend.services import access as access_service
from backend.services import models as models_service
from backend.services import regression_diagnostics as checks_service
from backend.services.access import AccessCtx, get_access

router = APIRouter(prefix="/api")


def _regression(model_id: str, session, ctx: AccessCtx):
    model, _ = access_service.fetch_readable(session, "models", Model, model_id, ctx)
    if model is None:
        return None, JSONResponse(status_code=404, content={"detail": "Model not found."})
    if model.kind != "regression":
        return None, JSONResponse(status_code=422, content={"detail": "Only regression models have these checks."})
    return model, None


@router.get("/models/{model_id}/diagnostics")
def model_diagnostics(model_id: str, session=Depends(get_session), ctx: AccessCtx = Depends(get_access)):
    """Does the model's assumption hold? The proportional-hazards test with
    a verdict, robust standard errors, ties and strata. Stored at fit time;
    for a model saved before them, computed now and cached."""
    model, error = _regression(model_id, session, ctx)
    if error is not None:
        return error
    return JSONResponse(content=checks_service.ensure_diagnostics(session, model))


@router.get("/models/{model_id}/residuals")
def model_residuals(model_id: str, session=Depends(get_session), ctx: AccessCtx = Depends(get_access)):
    """Scaled Schoenfeld, martingale and deviance residuals for plotting."""
    model, error = _regression(model_id, session, ctx)
    if error is not None:
        return error
    try:
        return JSONResponse(content=checks_service.residuals(session, model, [*ctx.read_owners, model.owner_id]))
    except (models_service.ModelNotFound, fitting.ModelNotFound):
        return JSONResponse(status_code=422, content={
            "detail": "This model's dataset is gone, so there's nothing to compute residuals from."})
    except FitError as exc:
        return JSONResponse(status_code=422, content={"detail": str(exc)})


@router.get("/residuals/{cache_id}")
def fit_residuals(cache_id: str, user: dict = Depends(get_current_user)):
    """The residuals of a fit not yet saved, served only to the account that
    fitted it (like the calculator's endpoints)."""
    try:
        entry = fitting._entry_for(cache_id, user["uid"])
    except fitting.ModelNotFound:
        return JSONResponse(status_code=404, content={"detail": "Model not found — re-fit to see residuals."})
    diag = entry.get("diag")
    if diag is None:
        return JSONResponse(content=rd.unavailable("No residuals for this model."))
    source = "model" if diag is getattr(entry.get("model"), "inner", entry.get("model")) else "cox"
    return JSONResponse(content=rd.residuals(diag, source))
