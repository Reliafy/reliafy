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
from backend.errors import client_message

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
def active_job(rbd_id: str, kind: str = rbd_jobs_service.KIND_AVAILABILITY, session=Depends(get_session),
               ctx: AccessCtx = Depends(get_access)) -> JSONResponse:
    """The caller's newest in-flight job of ``kind`` (``availability`` or
    ``sensitivity``) for a diagram (``job`` null when none), so a reloaded
    page can pick up where it left off."""
    job = rbd_jobs_service.latest_active(session, ctx.uid, rbd_id, kind)
    if job is None:
        return JSONResponse(content={"job": None})
    entitled = billing_service.premium_compute_allowed(session, ctx.user)
    return JSONResponse(content={"job": rbd_jobs_service.view(session, job, entitled)})


@router.post("/api/rbd-jobs/{job_id}/cancel")
def cancel_job(job_id: str, session=Depends(get_session), ctx: AccessCtx = Depends(get_access)) -> JSONResponse:
    """Cancel the caller's job, queued or running: it is marked cancelled at
    once and its result, if the calculation still finishes, is discarded.
    Only the user who started it can cancel it (404 otherwise). A finished
    job is returned unchanged. ``job_id`` may instead be the ``run_token`` of
    a run computing in the app's own process (no queue): that run is then
    recorded as cancelled and keeps nothing when it finishes."""
    job = rbd_jobs_service.cancel(session, job_id, ctx.uid)
    if job is None:
        if session.rbd_jobs.find_one({"_id": job_id}, {"_id": 1}) is not None:
            return JSONResponse(status_code=404, content=JOB_NOT_FOUND)  # someone else's
        rbd_jobs_service.cancel_token(session, ctx.uid, job_id)
        return JSONResponse(content={"job_id": job_id, "status": rbd_jobs_service.CANCELLED,
                                     "error": rbd_jobs_service.CANCELLED_NOTE})
    entitled = billing_service.premium_compute_allowed(session, ctx.user)
    return JSONResponse(content=rbd_jobs_service.view(session, job, entitled))


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
        return JSONResponse(status_code=400, content={"detail": client_message(exc)})
    if payload.get("status") == "running" and rbd_jobs_service.is_cancelled(session, str(payload.get("job_id") or "")):
        # Cancelled while queued: tells the compute service to skip it.
        return JSONResponse(status_code=409, content={"ok": True, "applied": False, "cancelled": True})
    return JSONResponse(content={"ok": True, "applied": applied})
