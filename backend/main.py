"""Reliafy backend.

A small FastAPI application that fits parametric reliability models with
SurPyval and serves the React single-page app. The frontend is served from the
same process so the whole thing runs on a single port:

    uvicorn backend.main:app --reload

In production, build the frontend first (``npm run build`` in ``frontend/``)
so that ``frontend/dist`` exists and can be served as static files.
"""

from __future__ import annotations

import logging
from pathlib import Path

from fastapi import Body, Depends, FastAPI, File, Form, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from backend.db import get_session, init_db
from backend.fitting import (
    DISCRETE,
    DISTRIBUTIONS,
    NONPARAMETRIC,
    REGRESSION_MODELS,
    FitError,
    ModelNotFound,
    confidence_bounds,
    evaluate,
    fit,
    options_from_form,
    preview,
    read_dataframe,
)
from backend.auth import get_current_user
from backend.routers import auth as auth_router
from backend.routers import models as models_router
from backend.routers import rbds as rbds_router
from backend.routers import strategy as strategy_router
from backend.routers import billing as billing_router
from backend.routers import assistant as assistant_router
from backend.routers import degradation as degradation_router
from backend.routers import rcm as rcm_router
from backend.routers import teams as teams_router
from backend.routers import shares as shares_router
from backend.routers import telemetry as telemetry_router
from backend.routers import admin as admin_router
from backend.routers import fleet as fleet_router
from backend.routers import public as public_router
from backend.routers import ingest as ingest_router
from backend.routers import public_api as public_api_router
from backend.services import datasets as datasets_service

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="Reliafy", version="0.1.0")


@app.on_event("startup")
def _startup() -> None:
    init_db()
    from backend.db import get_db
    from backend.services.samples import seed_samples

    seed_samples(get_db())


app.include_router(auth_router.router)
app.include_router(models_router.router)
app.include_router(rbds_router.router)
app.include_router(strategy_router.router)
app.include_router(billing_router.router)
app.include_router(assistant_router.router)
app.include_router(degradation_router.router)
app.include_router(rcm_router.router)
app.include_router(teams_router.router)
app.include_router(shares_router.router)
app.include_router(telemetry_router.router)
app.include_router(admin_router.router)
app.include_router(fleet_router.router)
app.include_router(public_router.router)
app.include_router(ingest_router.router)
app.include_router(public_api_router.router)

# ---------------------------------------------------------------------------
# API routes
# ---------------------------------------------------------------------------


@app.get("/api/health")
def health() -> dict:
    from backend import db

    return {
        "status": "ok",
        "storage": "simulator" if db.is_simulated() else "mongodb",
    }


@app.get("/api/config")
def app_config() -> dict:
    """Which optional capabilities this deployment has (public, unauthenticated).

    The frontend uses this to hide affordances that can't work here: the AI
    assistant (needs an operator provider key) and billing (needs Stripe /
    BILLING_ENABLED). ``auth`` is false in single-user (self-hosted) mode.
    """
    from backend import config
    from backend.services import assistant as assistant_service

    return {
        "auth": not config.AUTH_DISABLED,
        "ai": assistant_service.enabled(),
        "billing": bool(config.BILLING_ENABLED or config.STRIPE_API_KEY),
    }


@app.post("/api/columns")
async def columns_endpoint(
    file: UploadFile = File(...),
    user: dict = Depends(get_current_user),
) -> JSONResponse:
    """Return the column names and a sample of rows from an uploaded CSV.

    Used by the frontend to populate the x/c/n/xl/xr/tl/tr column selectors.
    """
    contents = await file.read()
    try:
        return JSONResponse(content=preview(contents))
    except FitError as exc:
        return JSONResponse(status_code=422, content={"detail": str(exc)})


@app.get("/api/distributions")
def distributions_endpoint() -> dict:
    """List the models available to fit.

    ``covariates`` flags proportional-hazards models, which require covariate
    columns or a formula; the frontend uses it to filter the model list by the
    data that was entered.
    """
    plain = [
        {
            "id": "best",
            "name": "Best fit (auto)",
            "covariates": False,
            "params": [],
            "offsetable": True,
        },
        *(
            {
                "id": key,
                "name": entry["name"],
                "covariates": False,
                "params": list(getattr(entry["dist"], "param_names", [])),
                "offsetable": bool(entry.get("offsetable")),
            }
            for key, entry in DISTRIBUTIONS.items()
        ),
    ]
    discrete = [
        {"id": key, "name": entry["name"], "covariates": False,
         "discrete": True, "params": list(getattr(entry["dist"], "param_names", []))}
        for key, entry in DISCRETE.items()
    ]
    nonparametric = [
        {"id": key, "name": entry["name"], "covariates": False,
         "nonparametric": True, "params": []}
        for key, entry in NONPARAMETRIC.items()
    ]
    regression = [
        {"id": key, "name": entry["name"], "covariates": True, "params": [],
         "effect": entry.get("effect")}
        for key, entry in REGRESSION_MODELS.items()
    ]
    return {"distributions": plain + discrete + nonparametric + regression}


@app.post("/api/fit/{distribution}")
async def fit_endpoint(
    distribution: str,
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
    user: dict = Depends(get_current_user),
) -> JSONResponse:
    """Fit ``distribution`` from a CSV (uploaded ``file`` or a saved
    ``dataset_id``) and a column mapping.

    Each of ``x/c/n/xl/xr/tl/tr`` is an optional CSV column name. For
    proportional-hazards models, ``z`` lists covariate columns (or ``formula``
    gives a formulaic formula). ``unit`` labels the ``x`` axis.
    """
    mapping = {"x": x, "c": c, "n": n, "xl": xl, "xr": xr, "tl": tl, "tr": tr}
    try:
        if dataset_id:
            dataset = datasets_service.get_dataset(session, dataset_id, owner_id=user["uid"])
            if dataset is None:
                return JSONResponse(
                    status_code=404, content={"detail": "Dataset not found."}
                )
            df = datasets_service.load_dataframe(dataset)
        elif file is not None:
            df = read_dataframe(await file.read())
        else:
            return JSONResponse(
                status_code=422,
                content={"detail": "Provide a CSV file or a dataset_id."},
            )
        options = options_from_form(offset, zi, lfp, fixed)
        result = fit(
            distribution, df, mapping, covariates=z, formula=formula, unit=unit,
            options=options,
        )
    except FitError as exc:
        return JSONResponse(status_code=422, content={"detail": str(exc)})
    except Exception as exc:  # pragma: no cover - defensive
        logger.exception("Unexpected error fitting %s model", distribution)
        return JSONResponse(
            status_code=500, content={"detail": f"Failed to fit model: {exc}"}
        )
    # Point the (unsaved) calculator at the in-memory evaluate / confidence
    # endpoints. Confidence bounds aren't available for regression models.
    functions = result.get("functions")
    if functions and functions.get("model_id"):
        functions["evaluate_path"] = f"/api/evaluate/{functions['model_id']}"
        if result.get("kind") in ("distribution", "discrete", "nonparametric"):
            functions["confidence_path"] = f"/api/confidence/{functions['model_id']}"
    return JSONResponse(content=result)


@app.post("/api/evaluate/{model_id}")
def evaluate_endpoint(model_id: str, values: dict = Body(default={})) -> JSONResponse:
    """Re-evaluate a fitted regression model's functions at covariate values."""
    try:
        return JSONResponse(content=evaluate(model_id, values))
    except ModelNotFound:
        return JSONResponse(
            status_code=404,
            content={"detail": "Model not found — re-fit to use the calculator."},
        )
    except FitError as exc:
        return JSONResponse(status_code=422, content={"detail": str(exc)})


@app.post("/api/confidence/{model_id}")
def confidence_endpoint(model_id: str, body: dict = Body(default={})) -> JSONResponse:
    """Confidence bounds of a freshly-fitted model's function (configurable
    significance / bound), for the modelling-page calculator."""
    try:
        return JSONResponse(content=confidence_bounds(
            model_id,
            on=body.get("on", "sf"),
            alpha_ci=float(body.get("alpha_ci", 0.05)),
            bound=body.get("bound", "two-sided"),
        ))
    except ModelNotFound:
        return JSONResponse(
            status_code=404,
            content={"detail": "Model not found — re-fit to compute confidence bounds."},
        )
    except (FitError, ValueError, TypeError) as exc:
        return JSONResponse(status_code=422, content={"detail": str(exc)})


# ---------------------------------------------------------------------------
# Frontend (single-port hosting)
# ---------------------------------------------------------------------------

FRONTEND_DIST = Path(__file__).resolve().parent.parent / "frontend" / "dist"

if FRONTEND_DIST.is_dir():
    # Serve hashed assets (JS/CSS/images) from the Vite build.
    app.mount(
        "/assets",
        StaticFiles(directory=FRONTEND_DIST / "assets"),
        name="assets",
    )

    @app.get("/{full_path:path}")
    async def serve_spa(full_path: str) -> FileResponse:
        """Serve static files, falling back to index.html for SPA routing.

        Marketing pages (landing, blog, terms/privacy) may have prerendered
        HTML under ``dist/static/<route>/index.html`` — generated at build
        time for search indexing — which wins over the SPA shell there.
        """
        prerendered = FRONTEND_DIST / "static" / (full_path or ".") / "index.html"
        if prerendered.is_file():
            return FileResponse(prerendered)
        candidate = FRONTEND_DIST / full_path
        if full_path and candidate.is_file():
            return FileResponse(candidate)
        return FileResponse(FRONTEND_DIST / "index.html")

else:  # pragma: no cover - only hit before the frontend is built

    @app.get("/")
    def frontend_not_built() -> JSONResponse:
        return JSONResponse(
            status_code=503,
            content={
                "detail": (
                    "Frontend has not been built. Run 'npm install && npm run "
                    "build' in the frontend/ directory."
                )
            },
        )
