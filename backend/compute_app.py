"""Reliafy compute service (#146): the CPU-heavy analyses, off the web service.

The same image as the web app, started with a different command::

    uvicorn backend.compute_app:app --host 0.0.0.0 --port 8080

It is stateless and has no database: no Mongo credentials and no user data
beyond the self-contained request it is given (see
:mod:`backend.services.compute_core`). It is deployed private
(``--no-allow-unauthenticated``); Cloud Run checks that each caller holds
``roles/run.invoker`` — only the web service's account does — before a request
reaches this code.

Endpoints:

* ``POST /compute/run`` — the Cloud Tasks target. Runs one job and POSTs the
  outcome to the web app's callback with a Google-signed ID token of this
  service's own account. If the callback can't be delivered it answers 5xx, so
  Cloud Tasks retries the task; re-running is safe (results are seeded and the
  callback is idempotent).
* ``POST /compute/availability`` — the same analysis, answered directly (for
  checks and debugging).
* ``GET /health`` — liveness and the RePyability version. Cloud Run reserves
  paths ending in "z" (its front end answers ``/healthz`` itself, with a 404),
  so this is the one to call in production; ``GET /healthz`` stays for local
  use.
"""

from __future__ import annotations

import logging
import threading
import time
from datetime import datetime, timezone
from typing import Optional

from fastapi import Body, FastAPI
from fastapi.responses import JSONResponse

from backend import config
from backend.services import compute_core
from backend.services.rbd_analysis import AnalysisError, _repyability_version

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("reliafy.compute")

app = FastAPI(title="Reliafy compute", version="0.1.0", docs_url=None, redoc_url=None)

# A failed analysis is the user's diagram, not this service: say what's wrong
# in their terms. Anything else is reported generically (the detail is logged).
GENERIC_FAILURE = "The calculation failed. Check the diagram and try again."


# ---- Execution ----------------------------------------------------------------
# Since RePyability 0.12 a seeded run draws from streams of its own, but a
# model whose draws can't be streamed still uses numpy's *global* RNG, so two
# simulations in one process at once could draw from each other's. With
# COMPUTE_WORKERS set, each job runs in a worker process of its own (true
# parallelism on the service's 2 vCPU too); otherwise jobs run one at a time
# in the request thread.

_lock = threading.Lock()
_executor = None
_executor_lock = threading.Lock()


def _pool():
    global _executor
    with _executor_lock:
        if _executor is None:
            import multiprocessing
            from concurrent.futures import ProcessPoolExecutor

            # forkserver: workers fork from a clean server process that has
            # already imported the analysis stack (fast, and no fork of a
            # threaded uvicorn process).
            ctx = multiprocessing.get_context("forkserver")
            ctx.set_forkserver_preload(["backend.services.compute_core"])
            _executor = ProcessPoolExecutor(max_workers=config.COMPUTE_WORKERS, mp_context=ctx)
        return _executor


def execute(kind: str, request: dict) -> dict:
    """Run one request: in a worker process when COMPUTE_WORKERS > 0, else
    here, serialised."""
    if config.COMPUTE_WORKERS > 0:
        return _pool().submit(compute_core.run, kind, request).result()
    with _lock:
        return compute_core.run(kind, request)


# ---- Callback to the web app ---------------------------------------------------

_token_cache: dict[str, tuple[str, float]] = {}
_TOKEN_MARGIN_S = 300  # refresh this long before the token expires


def _id_token(audience: str) -> str:
    """A Google-signed ID token of this service's account for ``audience``,
    cached until shortly before it expires."""
    cached = _token_cache.get(audience)
    now = time.time()
    if cached and cached[1] - _TOKEN_MARGIN_S > now:
        return cached[0]
    import google.auth.transport.requests
    from google.auth import jwt
    from google.oauth2 import id_token

    token = id_token.fetch_id_token(google.auth.transport.requests.Request(), audience)
    try:
        exp = float(jwt.decode(token, verify=False).get("exp") or 0)
    except Exception:  # noqa: BLE001 - unknown expiry: cache briefly
        exp = now + _TOKEN_MARGIN_S + 60
    _token_cache[audience] = (token, exp)
    return token


def _post(url: str, payload: dict, timeout: float) -> int:
    import requests

    r = requests.post(
        url,
        json=payload,
        headers={"Authorization": f"Bearer {_id_token(url)}"},
        timeout=timeout,
    )
    return r.status_code


def post_callback(url: str, payload: dict, timeout: float = 30.0) -> bool:
    """Deliver one callback; True on a 2xx answer."""
    try:
        status = _post(url, payload, timeout)
    except Exception as exc:  # noqa: BLE001 - network, token: the task retries
        logger.warning("Callback for job %s failed: %s", payload.get("job_id"), exc)
        return False
    if not 200 <= status < 300:
        logger.warning("Callback for job %s answered %s", payload.get("job_id"), status)
        return False
    return True


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _surpyval_version():
    try:
        import surpyval

        return getattr(surpyval, "__version__", None)
    except Exception:  # noqa: BLE001
        return None


def run_job(job_id: str, kind: str, request: dict, callback_url: str) -> bool:
    """Run one job and report it. Returns whether the final callback landed."""
    started = _now()
    # Best effort: lets the app show "Running…". A lost one doesn't matter.
    post_callback(callback_url, {"job_id": job_id, "status": "running", "started_at": started},
                  timeout=10.0)
    t0 = time.perf_counter()
    status, result, error = "done", None, None
    try:
        result = execute(kind, request)
    except AnalysisError as exc:
        status, error = "failed", str(exc) or GENERIC_FAILURE
    except compute_core.InvalidRequest as exc:
        status, error = "failed", f"Invalid calculation request: {exc}"
    except Exception:  # noqa: BLE001 - deterministic: retrying won't help
        logger.exception("Job %s (%s) failed", job_id, kind)
        status, error = "failed", GENERIC_FAILURE
    payload = {
        "job_id": job_id,
        "status": status,
        "result": result,
        "error": error,
        "started_at": started,
        "finished_at": _now(),
        "timings": {"compute_s": round(time.perf_counter() - t0, 3)},
        "repyability_version": _repyability_version(),
        # The engines a run's history shows it ran on (#112).
        "surpyval_version": _surpyval_version(),
    }
    return post_callback(callback_url, payload)


# ---- Routes ---------------------------------------------------------------------

@app.get("/health")
def health() -> dict:
    return {"ok": True, "repyability_version": _repyability_version()}


@app.get("/healthz")
def healthz() -> dict:
    """``/health`` for local use: unreachable on Cloud Run, which reserves
    paths ending in "z"."""
    return health()


@app.post("/compute/availability")
def compute_availability(
    graph: dict = Body(...),
    options: dict = Body(default={}),
) -> JSONResponse:
    """The availability analysis of a self-contained repairable graph.
    ``options``: ``t_simulation``, ``n_simulations``, ``time_budget_s`` (a
    quick run), ``seed``, ``max_replications``."""
    try:
        result = execute("availability", {"graph": graph, "options": options})
    except AnalysisError as exc:
        return JSONResponse(status_code=422, content={"detail": str(exc)})
    except compute_core.InvalidRequest as exc:
        return JSONResponse(status_code=400, content={"detail": str(exc)})
    return JSONResponse(content=result)


@app.post("/compute/run")
def compute_run(
    job_id: str = Body(...),
    kind: str = Body(...),
    request: dict = Body(...),
    callback_url: Optional[str] = Body(default=None),
) -> JSONResponse:
    """Cloud Tasks target: run the job, then report it to the web app.
    A 5xx answer makes Cloud Tasks retry the task."""
    url = config.COMPUTE_CALLBACK_URL or callback_url
    if not url:
        logger.error("Job %s: no callback URL (set COMPUTE_CALLBACK_URL)", job_id)
        return JSONResponse(status_code=500, content={"detail": "No callback URL configured."})
    if kind not in compute_core.KINDS:
        # Reported, not retried: an unknown kind won't become known.
        delivered = post_callback(url, {"job_id": job_id, "status": "failed",
                                        "error": f"Unknown job kind {kind!r}.", "finished_at": _now()})
        return JSONResponse(status_code=200 if delivered else 502, content={"ok": delivered})
    if not run_job(job_id, kind, request, url):
        return JSONResponse(status_code=502, content={"detail": "Callback failed; retry."})
    return JSONResponse(content={"ok": True})

