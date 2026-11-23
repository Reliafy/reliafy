"""``GET /api/home/summary`` — everything Home shows, in one request.

Home used to read fourteen lists on load (every kind of model, the datasets,
diagrams, forecasts, strategy analyses, tracked fleets, what changed, and
Maintenance's access, overview and RCM rollup). On a slow server they queued
behind each other. This answers them all at once, each part exactly what its
own endpoint answers (the same handler or payload function, so the numbers
can't drift), read side by side in a few threads.

``sections`` holds each part that was read; ``errors`` names each part that
failed, with a sentence, so Home shows that card's error (with Try again) and
draws the rest: one part failing is never a 500. ``maintenance`` says whether
this viewer has Reliafy Maintenance (the menu's check); without it the
Maintenance parts aren't read at all.
"""

from __future__ import annotations

import contextvars
import logging
import time
from concurrent.futures import ThreadPoolExecutor

from fastapi import APIRouter, Depends, Response

from backend.db import get_session
from backend.maintenance.access import allowed
from backend.routers import alt, degradation, fleet, joint, models, rbds, recurrent, strategy
from backend.routers import maintenance as maintenance_router
from backend.routers import workspace_changes as changes_router
from backend.services.access import AccessCtx, get_access

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/home")

# Parts read side by side. Few: the server is small, and each part already
# makes several database reads of its own.
WORKERS = 4

# What a failed part says (Home shows it in that section's error card).
FAILED = {
    "changes": "Couldn't load what changed.",
    "maintenance_overview": "Couldn't load your maintenance work.",
    "rcm_rollup": "Couldn't load the RCM.",
}


def _parts(session, ctx: AccessCtx, maintenance_on: bool, rcm=None) -> dict:
    """Each part's name and how to read it: the endpoint's own handler or payload
    function. ``rcm``: a future of the workspace's RCM (Maintenance.rcm_all), read
    once for the RCM rollup and What changed, which both need all of it."""
    rcm_read = (lambda: rcm.result()) if rcm is not None else (lambda: None)
    parts = {
        "models": lambda: models.list_models(session=session, ctx=ctx),
        "alt_models": lambda: alt.list_models(session=session, ctx=ctx),
        "recurrent_models": lambda: recurrent.list_models(session=session, ctx=ctx),
        "degradation_models": lambda: degradation.list_models(session=session, ctx=ctx),
        "joint_models": lambda: joint.list_models(session=session, ctx=ctx),
        "datasets": lambda: models.list_datasets(session=session, ctx=ctx),
        "rbds": lambda: rbds.list_rbds(session=session, ctx=ctx),
        "fleets": lambda: fleet.list_fleets(session=session, ctx=ctx),
        "strategy_analyses": lambda: strategy.list_analyses(session=session, ctx=ctx),
        "tracked_fleets": lambda: fleet.list_tracked_fleets(session=session, ctx=ctx),
        "changes": lambda: changes_router.changes_payload(session, ctx, rcm_all=_shared(ctx, rcm)),
    }
    if maintenance_on:
        # A Maintenance of its own for each part, as two requests would have.
        parts["maintenance_overview"] = lambda: maintenance_router.overview_payload(
            maintenance_router.maintenance(ctx), tree=False)
        parts["rcm_rollup"] = lambda: maintenance_router.rcm_rollup(
            session, ctx, maintenance_router.maintenance(ctx), rcm=rcm_read())
    return parts


def _shared(ctx: AccessCtx, rcm) -> dict | None:
    """The RCM read once, as What changed takes it ({organisation: it}); None (it reads
    its own) without Maintenance or when the read failed."""
    if rcm is None:
        return None
    try:
        return {ctx.write_owner: rcm.result()}
    except Exception:
        return None


def _timed(fn, took: dict, name: str):
    def run():
        start = time.perf_counter()
        try:
            return fn()
        finally:
            took[name] = time.perf_counter() - start
    return run


def build_summary(session, ctx: AccessCtx, took: dict | None = None) -> dict:
    """``took`` (optional): filled with each part's seconds, for the Server-Timing header."""
    maintenance_on = allowed(ctx.user)
    sections: dict = {}
    errors: dict = {}
    took = {} if took is None else took
    with ThreadPoolExecutor(max_workers=WORKERS, thread_name_prefix="home") as pool:
        # The RCM first, so the parts waiting on it never wait on a free thread.
        rcm = pool.submit(contextvars.copy_context().run, _timed(
            lambda: maintenance_router.maintenance(ctx).rcm_all(), took, "rcm")) if maintenance_on else None
        parts = _parts(session, ctx, maintenance_on, rcm)
        # Each part runs in a copy of this request's context, as it would in its own request.
        futures = {name: pool.submit(contextvars.copy_context().run, _timed(fn, took, name))
                   for name, fn in parts.items()}
        for name, future in futures.items():
            try:
                sections[name] = future.result()
            except Exception:
                logger.exception("Home summary: %s failed", name)
                errors[name] = FAILED.get(name, "Couldn't load this list.")
    return {"maintenance": maintenance_on, "sections": sections, "errors": errors}


@router.get("/summary")
def home_summary(response: Response, session=Depends(get_session), ctx: AccessCtx = Depends(get_access)) -> dict:
    took: dict = {}
    out = build_summary(session, ctx, took)
    # What each part took (the browser's network panel shows it), for finding the slow one.
    response.headers["Server-Timing"] = ", ".join(
        f"{name.replace('_', '-')};dur={1000 * sec:.0f}" for name, sec in sorted(took.items()))
    return out
