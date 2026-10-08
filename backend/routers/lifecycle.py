"""Lifecycle emails' daily trigger (#272): private, called by Cloud Scheduler."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, Header
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse

from backend import config
from backend.db import get_session
from backend.services import lifecycle_emails
from backend.services import oidc

logger = logging.getLogger(__name__)
router = APIRouter()


@router.post("/internal/lifecycle/day3", include_in_schema=False)
async def day3(authorization: str | None = Header(default=None), session=Depends(get_session)):
    """Send the day-3 email to every eligible account that hasn't had it.

    Accepted only with a Google-signed ID token of ``LIFECYCLE_CRON_SA`` for
    ``LIFECYCLE_CRON_AUDIENCE`` (Cloud Scheduler's OIDC token). With
    ``LIFECYCLE_EMAILS`` off it answers ``enabled: false`` and sends nothing.
    Safe to repeat: the send log makes every email once-only."""
    try:
        oidc.verify(authorization, audience=config.LIFECYCLE_CRON_AUDIENCE,
                    service_account=config.LIFECYCLE_CRON_SA)
    except oidc.Rejected as exc:
        logger.warning("Rejected lifecycle trigger: %s", exc)
        return JSONResponse(status_code=401, content={"detail": "Unauthorized."})
    tally = await run_in_threadpool(lifecycle_emails.run_day3, session)
    return JSONResponse(content={"ok": True, **tally})
