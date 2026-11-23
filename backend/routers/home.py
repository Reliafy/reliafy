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
from concurrent.futures import ThreadPoolExecutor

from fastapi import APIRouter, Depends

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


def _parts(session, ctx: AccessCtx, maintenance_on: bool) -> dict:
    """Each part's name and how to read it: the endpoint's own handler or payload function."""
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
        "changes": lambda: changes_router.changes_payload(session, ctx),
    }
    if maintenance_on:
        # A Maintenance of its own for each part, as two requests would have.
        parts["maintenance_overview"] = lambda: maintenance_router.overview_payload(
            maintenance_router.maintenance(ctx), tree=False)
        parts["rcm_rollup"] = lambda: maintenance_router.rcm_rollup(session, ctx, maintenance_router.maintenance(ctx))
    return parts


def build_summary(session, ctx: AccessCtx) -> dict:
    maintenance_on = allowed(ctx.user)
    parts = _parts(session, ctx, maintenance_on)
    sections: dict = {}
    errors: dict = {}
    with ThreadPoolExecutor(max_workers=WORKERS, thread_name_prefix="home") as pool:
        # Each part runs in a copy of this request's context, as it would in its own request.
        futures = {name: pool.submit(contextvars.copy_context().run, fn) for name, fn in parts.items()}
        for name, future in futures.items():
            try:
                sections[name] = future.result()
            except Exception:
                logger.exception("Home summary: %s failed", name)
                errors[name] = FAILED.get(name, "Couldn't load this list.")
    return {"maintenance": maintenance_on, "sections": sections, "errors": errors}


@router.get("/summary")
def home_summary(session=Depends(get_session), ctx: AccessCtx = Depends(get_access)) -> dict:
    return build_summary(session, ctx)
