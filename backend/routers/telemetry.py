"""First-party telemetry: client error reports and pageview events.

Both endpoints just write structured log lines. On Cloud Run those land in
Cloud Logging (errors additionally surface in Error Reporting), so there's
no third-party service, no cookies, and nothing stored in the app database.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Body, Header

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


@router.post("/metrics/event")
def metrics_event(
    name: str = Body(default="pageview"),
    path: str = Body(default=""),
    referrer: str = Body(default=""),
) -> dict:
    """Record a lightweight product event (pageview, signup, ...)."""
    logger.info(
        "event name=%s path=%s referrer=%s",
        _clip(name, 100), _clip(path, 300), _clip(referrer, 300),
    )
    return {"ok": True}
