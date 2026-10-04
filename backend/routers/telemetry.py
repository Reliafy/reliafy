"""First-party telemetry: client error reports and pageview events.

Both endpoints just write structured log lines. On Cloud Run those land in
Cloud Logging (errors additionally surface in Error Reporting), so there's
no third-party service, no cookies, and nothing stored in the app database.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Body, Depends, Header, Request
from fastapi.responses import JSONResponse, Response

from backend.db import get_session
from backend.log_redaction import redact_secrets
from backend.ratelimit import SlidingWindowLimiter
from backend.request_ip import client_ip
from backend.services import metrics as metrics_service

logger = logging.getLogger("reliafy.telemetry")

router = APIRouter(prefix="/api")

_MAX_FIELD = 4000

# Per-IP ceilings (per instance, per minute). Generous for a real browser: a
# pageview per navigation plus a handful of product events.
_ERROR_LIMIT = SlidingWindowLimiter(30)
_EVENT_LIMIT = SlidingWindowLimiter(120)
_CSP_LIMIT = SlidingWindowLimiter(30)

# Event names the frontend sends (frontend/src/telemetry.js trackEvent and
# api.js withEvent). Server-side events (signup, ingest, API calls) are
# recorded directly by the backend and never come through this endpoint.
CLIENT_EVENTS = frozenset({
    "pageview",
    "activated",
    "model_fit",
    "model_save",
    "dataset_upload",
    "rbd_save",
    "rbd_import",
    "rbd_design",
    "rbd_design_cheapest",
    "rbd_export_python",
    "rbd_export_json",
    "alt_save",
    "degradation_save",
    "rcm_create",
    "rcm_import",
    # First-run starts on an empty workspace (#194): frontend/src/components/FirstRun.jsx.
    "first_run_sample",
    "first_run_paste",
    "first_run_rbd",
    "first_run_agent",
})

# Re-exported for modules that import it from here.
_client_ip = client_ip


def _clip(value, limit=_MAX_FIELD) -> str:
    """``value`` as one bounded log-safe line: CR/LF escaped so a field can't
    start a new log record, and link tokens redacted."""
    return single_line(redact_secrets(str(value or "")[:limit]))


def single_line(text: str) -> str:
    return text.replace("\r", "\\r").replace("\n", "\\n")


def _too_many() -> JSONResponse:
    return JSONResponse(status_code=429, content={"detail": "Too many requests."},
                        headers={"Retry-After": "60"})


@router.post("/client-error")
def client_error(
    request: Request,
    message: str = Body(default=""),
    stack: str = Body(default=""),
    path: str = Body(default=""),
    user_agent: str | None = Header(default=None, alias="user-agent"),
):
    """Record a browser-side error (unhandled exception / render crash)."""
    if not _ERROR_LIMIT.allow(client_ip(request)):
        return _too_many()
    logger.error(
        "client-error path=%s ua=%s message=%s stack=%s",
        _clip(path, 300), _clip(user_agent, 300), _clip(message, 1000), _clip(stack),
    )
    return {"ok": True}


@router.post("/metrics/event")
def metrics_event(
    request: Request,
    name: str = Body(default="pageview"),
    path: str = Body(default=""),
    referrer: str = Body(default=""),
    utm_source: str = Body(default=""),
    utm_medium: str = Body(default=""),
    utm_campaign: str = Body(default=""),
    session=Depends(get_session),
):
    """Record a lightweight product event (pageview, signup, ...).

    Events are stored first-party in ``metrics_events`` (bot-filtered, daily
    salted visitor hash, 90-day TTL) and also logged for Cloud Logging.
    """
    ip = client_ip(request)
    if not _EVENT_LIMIT.allow(ip):
        return _too_many()
    if name not in CLIENT_EVENTS:
        return JSONResponse(status_code=422, content={"detail": "Unknown event."})
    stored = metrics_service.record_event(
        session,
        name=name,
        path=redact_secrets(str(path or "")),
        referrer=referrer,
        utm_source=utm_source,
        utm_medium=utm_medium,
        utm_campaign=utm_campaign,
        ip=ip,
        user_agent=request.headers.get("user-agent", ""),
    )
    logger.info(
        "event name=%s path=%s referrer=%s stored=%s",
        _clip(name, 100), _clip(path, 300), _clip(referrer, 300), stored,
    )
    return {"ok": True}


_CSP_MAX_BYTES = 16 * 1024


@router.post("/csp-report", include_in_schema=False)
async def csp_report(request: Request):
    """Content-Security-Policy violation reports (the policy is report-only;
    see backend/security_headers.py). Logged, clipped, never stored."""
    if not _CSP_LIMIT.allow(client_ip(request)):
        return _too_many()
    body = b""
    async for chunk in request.stream():
        body += chunk
        if len(body) > _CSP_MAX_BYTES:
            break
    logger.warning("csp-report %s", _clip(body[:_CSP_MAX_BYTES].decode("utf-8", "replace"), 2000))
    return Response(status_code=204)
