"""Reliability along a covariate schedule (#60).

A regression model evaluated with its covariates following a step path —
the calculator of a fit with covariates that change over time. Two routes,
as for the other calculator endpoints: an unsaved fit's in-memory id (served
only to the account that fitted it) and a saved model (re-fitted on demand).

Body: ``{"schedule": [{"t": 0, "values": {"load_pct": 60}}, ...],
"on": "sf" | "ff" | "Hf", "alpha_ci": 0.1, "bound": "lower" | "upper" |
"two-sided", "x_max": 9000}``. ``alpha_ci`` omitted (or null) gives no
bounds; ``x_max`` extends (or shortens) the time axis.
"""

from __future__ import annotations

from fastapi import APIRouter, Body, Depends
from fastapi.responses import JSONResponse

from backend import fitting, tvc
from backend.auth import get_current_user
from backend.db import get_session
from backend.schema import Model
from backend.services import access as access_service
from backend.services import models as models_service
from backend.services.access import AccessCtx, get_access

router = APIRouter(prefix="/api")


def _answer(entry: dict, body: dict) -> dict:
    x_max = body.get("x_max")
    grid = fitting._custom_grid(entry["grid"], None, float(x_max) if x_max not in (None, "") else None)
    alpha = body.get("alpha_ci")
    return tvc.evaluate(
        entry["model"], entry.get("fields") or [], body.get("schedule"), grid,
        on=body.get("on") or "sf",
        alpha_ci=None if alpha in (None, "") else float(alpha),
        bound=body.get("bound") or "lower",
    )


@router.post("/tvc/{fit_id}")
def schedule_fit(fit_id: str, body: dict = Body(default={}), user: dict = Depends(get_current_user)) -> JSONResponse:
    """An unsaved fit along a covariate schedule."""
    try:
        return JSONResponse(content=_answer(fitting._entry_for(fit_id, user["uid"]), body))
    except fitting.ModelNotFound:
        return JSONResponse(status_code=404, content={"detail": "Model not found — re-fit to use the calculator."})
    except (fitting.FitError, ValueError, TypeError) as exc:
        return JSONResponse(status_code=422, content={"detail": str(exc) or "Invalid schedule."})


@router.post("/models/{model_id}/tvc")
def schedule_model(
    model_id: str,
    body: dict = Body(default={}),
    session=Depends(get_session),
    ctx: AccessCtx = Depends(get_access),
) -> JSONResponse:
    """A saved regression model along a covariate schedule."""
    model, _ = access_service.fetch_readable(session, "models", Model, model_id, ctx)
    if model is None:
        return JSONResponse(status_code=404, content={"detail": "Model not found."})
    if model.kind != "regression":
        return JSONResponse(status_code=422, content={"detail": "Only a regression model has covariates to schedule."})
    try:
        entry = models_service.get_live_model(session, model_id, [*ctx.read_owners, model.owner_id])
        if entry is None:
            raise models_service.ModelNotFound(model_id)
        return JSONResponse(content=_answer(entry, body))
    except models_service.ModelNotFound:
        return JSONResponse(status_code=404, content={"detail": "Model not found."})
    except (fitting.FitError, ValueError, TypeError) as exc:
        return JSONResponse(status_code=422, content={"detail": str(exc) or "Invalid schedule."})
