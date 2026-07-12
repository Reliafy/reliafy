"""First-party telemetry: client error reports and pageview events.

Both endpoints just write structured log lines. On Cloud Run those land in
Cloud Logging (errors additionally surface in Error Reporting), so there's
no third-party service, no cookies, and nothing stored in the app database.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Body, Depends, Header, Request

from backend.db import get_session
from backend.services import metrics as metrics_service

logger = logging.getLogger("reliafy.telemetry")

router = APIRouter(prefix="/api")

_MAX_FIELD = 4000


def _clip(value, limit=_MAX_FIELD) -> str:
    return str(value or "")[:limit]


@router.post("/client-error")
def client_error(
    message: str = Body(default=""),
    stack: str = Body(default=""),
    path: str = Body(default=""),
    user_agent: str | None = Header(default=None, alias="user-agent"),
) -> dict:
    """Record a browser-side error (unhandled exception / render crash)."""
    logger.error(
        "client-error path=%s ua=%s message=%s stack=%s",
        _clip(path, 300), _clip(user_agent, 300), _clip(message, 1000), _clip(stack),
    )
    return {"ok": True}


def _client_ip(request: Request) -> str:
    """Original client IP. On Cloud Run the proxy appends to X-Forwarded-For;
    the first entry is the caller. Only ever hashed, never stored."""
    fwd = request.headers.get("x-forwarded-for", "")
    if fwd:
        return fwd.split(",")[0].strip()
    return request.client.host if request.client else ""


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
) -> dict:
    """Record a lightweight product event (pageview, signup, ...).

    Events are stored first-party in ``metrics_events`` (bot-filtered, daily
    salted visitor hash, 90-day TTL) and also logged for Cloud Logging.
    """
    stored = metrics_service.record_event(
        session,
        name=name,
        path=path,
        referrer=referrer,
        utm_source=utm_source,
        utm_medium=utm_medium,
        utm_campaign=utm_campaign,
        ip=_client_ip(request),
        user_agent=request.headers.get("user-agent", ""),
    )
    logger.info(
        "event name=%s path=%s referrer=%s stored=%s",
        _clip(name, 100), _clip(path, 300), _clip(referrer, 300), stored,
    )
    return {"ok": True}
