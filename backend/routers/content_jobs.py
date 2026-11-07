"""The content pipeline's scheduled trigger (#367): private, called by Cloud
Scheduler. See ``backend/services/content_jobs.py`` and ops/content-pipeline.md."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, Header
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse

from backend import config
from backend.db import get_session
from backend.services import content_jobs
from backend.services import oidc

logger = logging.getLogger(__name__)
router = APIRouter()


@router.post("/internal/content/run", include_in_schema=False)
async def content_run(dry_run: bool = False, authorization: str | None = Header(default=None),
                      session=Depends(get_session)):
    """Send what's due: an approved What's new's test copy or list send, and
    any steps installed extensions add.

    Accepted only with a Google-signed ID token of ``CONTENT_CRON_SA`` for
    ``CONTENT_CRON_AUDIENCE`` (Cloud Scheduler's OIDC token). Refuses (503)
    when email isn't configured, unless ``?dry_run=true``, which reports what
    it would do and sends and records nothing. Safe to repeat."""
    try:
        oidc.verify(authorization, audience=config.CONTENT_CRON_AUDIENCE,
                    service_account=config.CONTENT_CRON_SA)
    except oidc.Rejected as exc:
        logger.warning("Rejected content trigger: %s", exc)
        return JSONResponse(status_code=401, content={"detail": "Unauthorized."})
    try:
        result = await run_in_threadpool(content_jobs.run, session, dry_run=dry_run)
    except content_jobs.EmailNotConfigured as exc:
        logger.error("Content job refused: %s", exc)
        return JSONResponse(status_code=503, content={"ok": False, "detail": f"{exc} Nothing sent."})
    return JSONResponse(content=result)
