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

from fastapi import Body, Depends, FastAPI, File, Form, HTTPException, UploadFile, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from backend.db import get_session, init_db
from backend.fitting import (
    DISCRETE,
    DISTRIBUTIONS,
    MIXTURE_ID,
    FIT_METHODS,
    distribution_capabilities,
    NONPARAMETRIC,
    REGRESSION_MODELS,
    FitError,
    ModelNotFound,
    bind_owner,
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
from backend.routers import rbd_jobs as rbd_jobs_router
from backend.routers import rbd_compare as rbd_compare_router
from backend.routers import rbd_fault_tree as rbd_fault_tree_router
from backend.routers import rbd_design as rbd_design_router
from backend.routers import rbd_costs as rbd_costs_router
from backend.routers import rbd_sensitivity as rbd_sensitivity_router
from backend.routers import rbd_intervals as rbd_intervals_router
from backend.routers import strategy as strategy_router
from backend.routers import billing as billing_router
from backend.routers import assistant as assistant_router
from backend.routers import reliability_agent as reliability_agent_router
from backend.routers import degradation as degradation_router
from backend.routers import recurrent as recurrent_router
from backend.routers import alt as alt_router
from backend.routers import rcm as rcm_router
from backend.routers import excel as excel_router
from backend.routers import teams as teams_router
from backend.routers import shares as shares_router
from backend.routers import telemetry as telemetry_router
from backend.routers import admin as admin_router
from backend.routers import fleet as fleet_router
from backend.routers import public as public_router
from backend.routers import ingest as ingest_router
from backend.routers import public_api as public_api_router
from backend.routers import email_prefs as email_prefs_router
from backend.routers import feeds as feeds_router
from backend.routers import oauth as oauth_router
from backend.routers import outage_logs as outage_logs_router
from backend.routers import uploads as uploads_router
from backend.routers import compare_groups as compare_groups_router
from backend.services import datasets as datasets_service

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


from backend.log_redaction import has_secret as _has_secret  # noqa: E402
from backend.log_redaction import redact_secrets  # noqa: E402


class _RedactUploadTokens(logging.Filter):
    """Keep link tokens out of uvicorn's access log: upload links
    (``/api/uploads/<id>?t=…``, see backend/services/uploads.py), share-link
    unlock tokens (``?unlock=…``) and public share paths
    (``/api/public/<token>``, ``/p/<token>``) are each their link's only
    credential. Rewrites the logged path; never drops a line."""

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            if isinstance(record.args, tuple) and any(isinstance(a, str) and _has_secret(a) for a in record.args):
                record.args = tuple(redact_secrets(a) if isinstance(a, str) else a for a in record.args)
            if isinstance(record.msg, str) and _has_secret(record.msg):
                record.msg = redact_secrets(record.msg)
        except Exception:  # noqa: BLE001 - a log filter must never fail a request
            pass
        return True


logging.getLogger("uvicorn.access").addFilter(_RedactUploadTokens())

from contextlib import asynccontextmanager  # noqa: E402

from backend.mcp_server import mcp_http_app  # noqa: E402


@asynccontextmanager
async def _lifespan(_app: FastAPI):
    """Startup, plus the MCP server's Streamable HTTP session manager, whose
    task group must run for the app's lifetime (see backend/mcp_server.py)."""
    _startup()
    async with mcp_http_app.lifespan():
        yield


app = FastAPI(title="Reliafy", version="0.1.0", lifespan=_lifespan)

# CORS — normally the frontend is same-origin, but SSE streaming (the metered
# assistant) is served straight from Cloud Run to bypass Firebase Hosting's CDN,
# which buffers Server-Sent Events. Those requests are cross-origin (from the
# public site to the run.app host), so allow them explicitly. Auth is a Bearer
# ID token (no cookies), so credentials aren't needed.
from fastapi.middleware.cors import CORSMiddleware  # noqa: E402

from backend import config as _config  # noqa: E402

_CORS_ORIGINS = sorted({
    o for o in (_config.PUBLIC_BASE_URL, "https://reliafy.com", "https://www.reliafy.com") if o
})
app.add_middleware(
    CORSMiddleware,
    allow_origins=_CORS_ORIGINS,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "X-Workspace-Id"],
    max_age=3600,
)
# Open CORS on the OAuth discovery/token/registration endpoints only (outermost,
# so it answers their preflights before the app-wide policy above).
app.add_middleware(oauth_router.OAuthCorsMiddleware)

# Product-usage logging (backend/services/usage.py): records each signed-in
# /api request as a feature event once it has been answered. Never fails or
# delays a request; USAGE_LOGGING=false turns it off.
from backend.services.usage import UsageMiddleware  # noqa: E402

app.add_middleware(UsageMiddleware)

# Outermost: security headers on every response, and request-body caps before
# anything parses a body (backend/security_headers.py, backend/http_limits.py).
from backend.http_limits import BodySizeLimitMiddleware, read_upload  # noqa: E402
from backend.security_headers import SecurityHeadersMiddleware  # noqa: E402

app.add_middleware(BodySizeLimitMiddleware)
app.add_middleware(SecurityHeadersMiddleware)


def _startup() -> None:
    init_db()
    from backend.db import get_db
    from backend.services.samples import seed_samples
    from backend.services import push as push_service

    seed_samples(get_db())
    # Operator crash alerts. A no-op unless Pushover is configured, so
    # self-hosted and dev instances are unaffected.
    push_service.install_error_alerts()


@app.exception_handler(Exception)
async def _unhandled(request: Request, exc: Exception) -> JSONResponse:
    """Last resort: an exception that escaped every route handler.

    Logged with exc_info so it reaches the operator alert handler like any
    other crash, and answered with a generic 500 — the detail goes to the
    logs, not to the user.
    """
    logger.exception("unhandled error on %s %s", request.method, request.url.path)
    return JSONResponse(
        status_code=500,
        content={"detail": "Something went wrong. The error has been logged."},
    )


app.include_router(auth_router.router)
app.include_router(models_router.router)
app.include_router(rbds_router.router)
# Analysis jobs (#146): polling, and the compute service's callback.
app.include_router(rbd_jobs_router.router)
app.include_router(rbd_compare_router.router)
app.include_router(rbd_fault_tree_router.router)
app.include_router(rbd_design_router.router)
app.include_router(rbd_costs_router.router)
app.include_router(rbd_sensitivity_router.router)
app.include_router(rbd_intervals_router.router)
app.include_router(strategy_router.router)
app.include_router(compare_groups_router.router)
app.include_router(billing_router.router)
app.include_router(assistant_router.router)
app.include_router(reliability_agent_router.router)
app.include_router(degradation_router.router)
app.include_router(recurrent_router.router)
app.include_router(alt_router.router)
app.include_router(rcm_router.router)
app.include_router(excel_router.router)
app.include_router(teams_router.router)
app.include_router(shares_router.router)
app.include_router(telemetry_router.router)
app.include_router(admin_router.router)
app.include_router(fleet_router.router)
app.include_router(public_router.router)
app.include_router(ingest_router.router)
app.include_router(public_api_router.router)
app.include_router(email_prefs_router.router)
app.include_router(outage_logs_router.router)
# MCP file uploads: PUT /api/uploads/{id}?t=… (token-authed, see services/uploads.py).
app.include_router(uploads_router.router)
# RSS: served (date-filtered) before the SPA catch-all below.
app.include_router(feeds_router.router)

# MCP (Model Context Protocol) server for AI assistants — token-authed, and
# registered before the SPA catch-all so GET/POST/DELETE /mcp reach it.
# OAuth 2.1 for the MCP server (Claude connectors): discovery documents, the
# authorization/consent/token endpoints and Settings > Connected apps.
app.include_router(oauth_router.router)
app.router.add_route("/mcp", mcp_http_app, methods=["GET", "POST", "DELETE"], include_in_schema=False)

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
        "reliability_agent": bool(config.RELIABILITY_AGENT_ENABLED),
    }


@app.post("/api/columns")
def columns_endpoint(
    file: UploadFile = File(...),
    user: dict = Depends(get_current_user),
) -> JSONResponse:
    """Return the column names and a sample of rows from an uploaded CSV.

    Used by the frontend to populate the x/c/n/xl/xr/tl/tr column selectors.
    """
    contents = read_upload(file)
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
            "zi": True,
            "lfp": True,
            # It fits every candidate, so only methods they all support.
            "methods": sorted(
                set.intersection(*(set(distribution_capabilities(k)["methods"])
                                   for k in DISTRIBUTIONS)),
                key=[m["id"] for m in FIT_METHODS].index,
            ),
        },
        {
            "id": MIXTURE_ID,
            "name": "Mixture model",
            "covariates": False,
            "mixture": True,
            "params": [],
            # Which distribution to mix, offered in the advanced options.
            "mixture_distributions": [
                {"id": k, "name": v["name"]} for k, v in DISTRIBUTIONS.items()
            ],
        },
        *(
            {
                "id": key,
                "name": entry["name"],
                "covariates": False,
                "params": list(getattr(entry["dist"], "parameter_names", [])),
                # Derived from SurPyval, not hand-listed: which fit methods and
                # which model adjustments this distribution actually supports.
                **distribution_capabilities(key),
            }
            for key, entry in DISTRIBUTIONS.items()
        ),
    ]
    discrete = [
        {"id": key, "name": entry["name"], "covariates": False,
         "discrete": True, "params": list(getattr(entry["dist"], "parameter_names", []))}
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
    return {"distributions": plain + discrete + nonparametric + regression,
            "fit_methods": FIT_METHODS}


@app.post("/api/fit/{distribution}")
def fit_endpoint(
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
    mixture: str | None = Form(default=None),
    mixture_distribution: str | None = Form(default=None),
    how: str | None = Form(default=None),
    c_invert: str | None = Form(default=None),
    session=Depends(get_session),
    user: dict = Depends(get_current_user),
) -> JSONResponse:
    """Fit ``distribution`` from a CSV (uploaded ``file`` or a saved
    ``dataset_id``) and a column mapping.

    Each of ``x/c/n/xl/xr/tl/tr`` is an optional CSV column name. For
    proportional-hazards models, ``z`` lists covariate columns (or ``formula``
    gives a formulaic formula). ``unit`` labels the ``x`` axis. ``c_invert``
    ("1"/"0") says the ``c`` column uses 1 = failed and must be flipped.

    A plain (sync) handler: FastAPI runs it in its threadpool, so a slow fit
    never holds up other requests.
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
            df = read_dataframe(read_upload(file))
        else:
            return JSONResponse(
                status_code=422,
                content={"detail": "Provide a CSV file or a dataset_id."},
            )
        options = options_from_form(
            offset, zi, lfp, fixed, mixture, mixture_distribution, how, c_invert=c_invert,
        )
        result = fit(
            distribution, df, mapping, covariates=z, formula=formula, unit=unit,
            options=options,
        )
    except FitError as exc:
        # The message goes to the user; log it too, or the most informative
        # moment of a session (a fit that refused) leaves only a 422 in the
        # request log. Column names and the covariate list are the only
        # user-supplied content here — no data values.
        logger.warning(
            "Fit refused: distribution=%s covariates=%s mapping=%s — %s",
            distribution, list(z or []), {k: v for k, v in mapping.items() if v}, exc,
        )
        return JSONResponse(status_code=422, content={"detail": str(exc)})
    except HTTPException:
        raise
    except Exception:  # pragma: no cover - defensive
        logger.exception("Unexpected error fitting %s model", distribution)
        return JSONResponse(
            status_code=500,
            content={"detail": "Failed to fit the model. The error has been logged."},
        )
    # Point the (unsaved) calculator at the in-memory evaluate / confidence
    # endpoints. Confidence bounds aren't available for regression models.
    functions = result.get("functions")
    if functions and functions.get("model_id"):
        # The calculator endpoints only serve this fit back to its own account.
        bind_owner(functions["model_id"], user["uid"])
        functions["evaluate_path"] = f"/api/evaluate/{functions['model_id']}"
        if result.get("kind") in ("distribution", "discrete", "nonparametric"):
            functions["confidence_path"] = f"/api/confidence/{functions['model_id']}"
    return JSONResponse(content=result)


@app.post("/api/evaluate/{model_id}")
def evaluate_endpoint(
    model_id: str,
    values: dict = Body(default={}),
    user: dict = Depends(get_current_user),
) -> JSONResponse:
    """Re-evaluate a fitted regression model's functions at covariate values.

    ``model_id`` is an unsaved fit's in-memory id, served only to the account
    that fitted it (saved models have their own routes under /api/models)."""
    try:
        return JSONResponse(content=evaluate(model_id, values, owner=user["uid"]))
    except ModelNotFound:
        return JSONResponse(
            status_code=404,
            content={"detail": "Model not found — re-fit to use the calculator."},
        )
    except FitError as exc:
        return JSONResponse(status_code=422, content={"detail": str(exc)})


@app.post("/api/confidence/{model_id}")
def confidence_endpoint(
    model_id: str,
    body: dict = Body(default={}),
    user: dict = Depends(get_current_user),
) -> JSONResponse:
    """Confidence bounds of a freshly-fitted model's function (configurable
    significance / bound), for the modelling-page calculator. Same access rule
    as :func:`evaluate_endpoint`."""
    try:
        return JSONResponse(content=confidence_bounds(
            model_id,
            on=body.get("on", "sf"),
            alpha_ci=float(body.get("alpha_ci", 0.05)),
            bound=body.get("bound", "two-sided"),
            owner=user["uid"],
        ))
    except ModelNotFound:
        return JSONResponse(
            status_code=404,
            content={"detail": "Model not found — re-fit to compute confidence bounds."},
        )
    except FitError as exc:
        return JSONResponse(status_code=422, content={"detail": str(exc)})
    except (ValueError, TypeError):
        return JSONResponse(status_code=422, content={"detail": "Invalid confidence settings."})


# ---------------------------------------------------------------------------
# Frontend (single-port hosting)
# ---------------------------------------------------------------------------

FRONTEND_DIST = Path(__file__).resolve().parent.parent / "frontend" / "dist"


def contained_path(path: Path, root: Path) -> Path | None:
    """``path`` resolved, or None if it resolves outside ``root``."""
    try:
        resolved = path.resolve()
    except (OSError, RuntimeError, ValueError):
        return None
    return resolved if resolved.is_relative_to(root.resolve()) else None


if FRONTEND_DIST.is_dir():
    # Hashed assets (JS/CSS/images) from the Vite build. Their names change
    # whenever their content does, so they can be cached forever; HTML must not
    # be (see _NO_CACHE below).
    class _ImmutableAssets(StaticFiles):
        async def get_response(self, path, scope):
            response = await super().get_response(path, scope)
            if response.status_code == 200:
                response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
            return response

    app.mount(
        "/assets",
        _ImmutableAssets(directory=FRONTEND_DIST / "assets"),
        name="assets",
    )

    # HTML is always revalidated: a stale page references hashed chunks a later
    # deploy has deleted, and the app then crashes on load. (main.jsx also
    # reloads once on vite:preloadError, for pages already open or cached.)
    _NO_CACHE = {"Cache-Control": "no-cache"}
    _DIST_ROOT = FRONTEND_DIST.resolve()

    def _within_dist(path: Path) -> Path | None:
        return contained_path(path, _DIST_ROOT)

    @app.get("/{full_path:path}")
    async def serve_spa(full_path: str) -> FileResponse:
        """Serve static files, falling back to index.html for SPA routing.

        Marketing pages (landing, blog, terms/privacy) may have prerendered
        HTML under ``dist/static/<route>/index.html`` — generated at build
        time for search indexing — which wins over the SPA shell there.
        """
        prerendered = _within_dist(
            FRONTEND_DIST / "static" / (full_path or ".") / "index.html"
        )
        if prerendered is not None and prerendered.is_file():
            return FileResponse(prerendered, headers=_NO_CACHE)
        candidate = _within_dist(FRONTEND_DIST / full_path)
        if full_path and candidate is not None and candidate.is_file():
            headers = _NO_CACHE if candidate.suffix == ".html" else None
            return FileResponse(candidate, headers=headers)
        return FileResponse(FRONTEND_DIST / "index.html", headers=_NO_CACHE)

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
