"""Public programmatic API (v1) — read models & reliability, create datasets
and fit, read fleet forecasts, and run strategy calculators.

Auth is the same personal API token (``Authorization: Bearer rlf_…``) or a
session, Pro-gated — reusing the ingest router's dependency. Everything is
scoped to the caller's own personal data (``owner_id == uid``); a token can
read and write the user's data but never touch the account, billing, tokens,
or team artifacts.
"""

from __future__ import annotations

import json
import logging

import numpy as np
from fastapi import APIRouter, Body, Depends, Request
from fastapi.responses import JSONResponse

from backend import config
from backend.db import get_session
from backend.fitting import FitError
from backend.routers.ingest import _rate_check, ingest_user
from backend.services import datasets as datasets_service
from backend.services import fleet as fleet_service
from backend.services import metrics as metrics_service
from backend.services import models as models_service
from backend.services import strategy_store

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1")


def _err(status: int, detail: str) -> JSONResponse:
    return JSONResponse(status_code=status, content={"detail": detail})


def _read_owners(uid: str) -> list[str]:
    """Reads see the caller's own artifacts plus the shared samples."""
    return [uid, config.SAMPLE_OWNER]


def _model_brief(m) -> dict:
    r = m.results or {}
    return {
        "id": m.id,
        "name": m.name,
        "kind": m.kind,
        "distribution": r.get("distribution", m.distribution_id),
        "n": r.get("n"),
        "unit": r.get("unit") or (m.spec or {}).get("unit", ""),
        "created_at": m.created_at.isoformat(),
        "url": f"/modelling/m/{m.id}",
    }


def _norm_params(params) -> list:
    out = []
    for p in params or []:
        if isinstance(p, dict):
            d = {"value": float(p["value"])}
            if "name" in p:
                d["name"] = p["name"]
            out.append(d)
        else:
            out.append({"value": float(p)})
    return out


# ---- models & reliability --------------------------------------------------

@router.get("/models")
def api_list_models(session=Depends(get_session), user: dict = Depends(ingest_user)) -> JSONResponse:
    """List the caller's saved models."""
    _rate_check(user["uid"])
    models = models_service.list_models(session, _read_owners(user["uid"]))
    return JSONResponse(content={"models": [_model_brief(m) for m in models]})


@router.get("/models/{model_id}")
def api_get_model(model_id: str, session=Depends(get_session), user: dict = Depends(ingest_user)) -> JSONResponse:
    """A model's fitted parameters (with CIs), life metrics, and goodness-of-fit."""
    _rate_check(user["uid"])
    m = models_service.get_model(session, model_id, _read_owners(user["uid"]))
    if m is None:
        return _err(404, "Model not found.")
    r = models_service.public_results(m)
    return JSONResponse(content={
        **_model_brief(m),
        "params": r.get("params", []),
        "coefficients": r.get("coefficients", []),
        "metrics": r.get("metrics"),
        "gof": r.get("gof", []),
    })


@router.post("/models/{model_id}/reliability")
def api_reliability(
    model_id: str,
    body: dict = Body(default={}),
    session=Depends(get_session),
    user: dict = Depends(ingest_user),
) -> JSONResponse:
    """Evaluate the model's reliability functions.

    Body: optional ``t`` (a time) and, for proportional-hazards models,
    ``covariates``. With ``t`` you get R/F/hazard/etc. at that time; without it
    you get the whole function grid.
    """
    _rate_check(user["uid"])
    m = models_service.get_model(session, model_id, _read_owners(user["uid"]))
    if m is None:
        return _err(404, "Model not found.")
    r = models_service.public_results(m)
    fns = r.get("functions") or {}
    if not fns.get("curves"):
        return _err(422, "This model has no reliability functions to evaluate.")

    covariates = body.get("covariates")
    try:
        if covariates and fns.get("model_id"):
            curves = models_service.evaluate(session, model_id, covariates, _read_owners(user["uid"]))["curves"]
        else:
            curves = fns["curves"]
    except (FitError, models_service.ModelNotFound) as exc:
        return _err(422, str(exc))

    out = {"model": m.name, "unit": r.get("unit", "")}
    t = body.get("t")
    if t is not None:
        x = np.asarray(curves["x"], dtype=float)

        def at(fn):
            y = curves.get(fn)
            if y is None:
                return None
            yv = np.array([np.nan if v is None else v for v in y], dtype=float)
            v = float(np.interp(float(t), x, yv))
            return v if np.isfinite(v) else None

        out["at"] = {
            "t": float(t),
            "reliability": at("sf"),
            "failure": at("ff"),
            "hazard": at("hf"),
            "cumulative_hazard": at("Hf"),
            "density": at("df"),
        }
    else:
        out["curves"] = curves
    return JSONResponse(content=out)


# ---- datasets & fitting ----------------------------------------------------

@router.post("/datasets")
async def api_create_dataset(
    request: Request,
    session=Depends(get_session),
    user: dict = Depends(ingest_user),
) -> JSONResponse:
    """Create a dataset from CSV text or column arrays.

    JSON body: ``name`` plus either ``csv`` (raw CSV text) or ``data``
    (``{"hours": [...], "failed": [...]}``).
    """
    _rate_check(user["uid"])
    import pandas as pd

    try:
        payload = json.loads(await request.body() or b"{}")
    except json.JSONDecodeError:
        return _err(422, "Body must be JSON.")
    name = str(payload.get("name") or "").strip()
    if not name:
        return _err(422, "A 'name' is required.")
    try:
        if payload.get("csv"):
            csv_bytes = datasets_service.normalize_pasted(payload["csv"])
        elif payload.get("data"):
            csv_bytes = pd.DataFrame(payload["data"]).to_csv(index=False).encode()
        else:
            return _err(422, "Provide 'csv' text or 'data' arrays.")
        ds = datasets_service.create_dataset(session, name, csv_bytes, user["uid"])
    except (FitError, ValueError) as exc:
        return _err(422, str(exc))
    metrics_service.record_event(session, name="api_dataset", path="/api/v1/datasets")
    return JSONResponse(content={
        "id": ds.id,
        "name": ds.name,
        "n_rows": ds.n_rows,
        "columns": [c["name"] for c in ds.columns],
        "url": f"/datasets/d/{ds.id}",
    })


@router.post("/fit")
def api_fit(
    body: dict = Body(default={}),
    session=Depends(get_session),
    user: dict = Depends(ingest_user),
) -> JSONResponse:
    """Fit and save a model from one of the caller's datasets.

    Body: ``name``, ``dataset_id``, ``distribution`` (e.g. ``weibull``,
    ``weibull_ph``), ``mapping`` (``{"x": "hours", "c": "failed"}``), optional
    ``unit``, ``covariates`` / ``formula`` for proportional-hazards models.
    """
    _rate_check(user["uid"])
    name = str(body.get("name") or "").strip()
    if not name:
        return _err(422, "A 'name' is required.")
    dataset = datasets_service.get_dataset(session, body.get("dataset_id", ""), user["uid"])
    if dataset is None:
        return _err(404, "Dataset not found.")
    try:
        model = models_service.save_model(
            session, name, dataset,
            body.get("distribution", "weibull"),
            body.get("mapping") or {},
            body.get("covariates"),
            body.get("formula"),
            body.get("unit"),
            owner_id=user["uid"],
        )
    except FitError as exc:
        return _err(422, str(exc))
    metrics_service.record_event(session, name="api_fit", path="/api/v1/fit")
    return JSONResponse(content=_model_brief(model))


# ---- fleet forecasts -------------------------------------------------------

@router.get("/fleets/{fleet_id}/forecast")
def api_fleet_forecast(
    fleet_id: str,
    session=Depends(get_session),
    user: dict = Depends(ingest_user),
) -> JSONResponse:
    """The live failure forecast for one of the caller's fleets."""
    _rate_check(user["uid"])
    fleet = fleet_service.get_fleet(session, fleet_id, _read_owners(user["uid"]))
    if fleet is None:
        return _err(404, "Fleet not found.")
    forecast = fleet_service.compute(session, fleet, [*_read_owners(user["uid"]), fleet.owner_id])
    return JSONResponse(content={
        "fleet": {"id": fleet.id, "name": fleet.name, "model_id": fleet.model_id},
        "forecast": forecast,
    })


# ---- strategy calculators --------------------------------------------------

def _strategy(kind: str, body: dict, uid: str) -> JSONResponse:
    _rate_check(uid)
    inputs = dict(body or {})
    inputs["params"] = _norm_params(inputs.get("params"))
    try:
        results = strategy_store.compute(kind, inputs)
    except (strategy_store.StrategyError, FitError, ValueError, KeyError) as exc:
        return _err(422, str(exc) or "Invalid inputs.")
    return JSONResponse(content=results)


@router.post("/strategy/optimal-replacement")
def api_optimal_replacement(
    body: dict = Body(default={}),
    user: dict = Depends(ingest_user),
) -> JSONResponse:
    """Cost-optimal preventive-replacement interval.

    Body: ``distribution_id``, ``params``, ``planned_cost``,
    ``unplanned_cost``, optional ``unit``.
    """
    return _strategy("optimal_replacement", body, user["uid"])


@router.post("/strategy/failure-finding")
def api_failure_finding(
    body: dict = Body(default={}),
    user: dict = Depends(ingest_user),
) -> JSONResponse:
    """Failure-finding inspection interval for a hidden (protective) function.

    Body: ``distribution_id``, ``params``, ``target_availability``, optional
    ``unit``.
    """
    return _strategy("failure_finding", body, user["uid"])
