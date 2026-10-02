"""RBD analysis jobs (#146): polling for the app, and the compute callback."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Body, Depends, Header
from fastapi.responses import JSONResponse

from backend.db import get_session
from backend.services import billing as billing_service
from backend.services import compute_queue
from backend.services import rbd_jobs as rbd_jobs_service
from backend.services.access import AccessCtx, get_access

logger = logging.getLogger(__name__)
router = APIRouter()

JOB_NOT_FOUND = {"detail": "Job not found."}


@router.get("/api/rbd-jobs/{job_id}")
def get_job(job_id: str, session=Depends(get_session), ctx: AccessCtx = Depends(get_access)) -> JSONResponse:
    """A job's status, queue position, and its result once done. Only the
    user who started a job can see it."""
    job = rbd_jobs_service.get(session, job_id)
    if job is None or job.get("uid") != ctx.uid:
        return JSONResponse(status_code=404, content=JOB_NOT_FOUND)
    entitled = billing_service.premium_compute_allowed(session, ctx.user)
    return JSONResponse(content=rbd_jobs_service.view(session, job, entitled))


@router.get("/api/rbd-jobs")
def active_job(rbd_id: str, session=Depends(get_session), ctx: AccessCtx = Depends(get_access)) -> JSONResponse:
    """The caller's newest in-flight job for a diagram (``job`` null when
    none), so a reloaded page can pick up where it left off."""
    job = rbd_jobs_service.latest_active(session, ctx.uid, rbd_id)
    if job is None:
        return JSONResponse(content={"job": None})
    entitled = billing_service.premium_compute_allowed(session, ctx.user)
    return JSONResponse(content={"job": rbd_jobs_service.view(session, job, entitled)})


@router.post("/internal/compute/callback")
def compute_callback(
    payload: dict = Body(...),
    authorization: str | None = Header(default=None),
    session=Depends(get_session),
) -> JSONResponse:
    """The compute service reports a job (``running``, ``done`` or
    ``failed``). Accepted only with a Google-signed ID token of the compute
    service's account for this URL. Idempotent: a repeat is acknowledged and
    changes nothing, so Cloud Tasks retries are safe."""
    try:
        compute_queue.verify_callback(authorization)
    except compute_queue.CallbackRejected as exc:
        logger.warning("Rejected compute callback: %s", exc)
        return JSONResponse(status_code=401, content={"detail": "Unauthorized."})
    try:
        applied = rbd_jobs_service.apply_callback(session, payload)
    except ValueError as exc:
        return JSONResponse(status_code=400, content={"detail": str(exc)})
    return JSONResponse(content={"ok": True, "applied": applied})
