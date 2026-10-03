"""Redundancy design for RBDs: how many copies of each block (#98).

Free for everyone: the allocation is exact and cheap (a dynamic program, or an
exhaustive search the library caps at a size that runs in seconds), unlike
the Monte-Carlo availability simulation, which is a paid feature. Nothing is
saved — the builder writes a chosen design onto the canvas for the user to
review and save.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Body, Depends
from fastapi.responses import JSONResponse

from backend.db import get_session
from backend.services import models as models_service
from backend.services import rbd_design
from backend.services import rbds as rbds_service
from backend.services.access import AccessCtx, get_access

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api")


def _resolvers(session, owners):
    """Saved models and sub-systems resolve as the diagram's analysis does."""

    def resolve_subsystem(sub_id: str):
        sub = rbds_service.get_rbd(session, sub_id, owners)
        return sub.graph if sub is not None else None

    def resolve_model(model_id: str):
        return models_service.get_live_model(session, model_id, owners)

    return resolve_model, resolve_subsystem


@router.post("/rbds/design")
def design_rbd(
    graph: dict = Body(...),
    t: float | None = Body(default=None),
    blocks: list = Body(default=[]),
    budget: dict | None = Body(default=None),
    target: float | None = Body(default=None),
    mixing: bool = Body(default=True),
    session=Depends(get_session),
    ctx: AccessCtx = Depends(get_access),
) -> JSONResponse:
    """The most reliable design within a budget (or the cheapest reaching a
    target reliability at ``t``), and the cost–reliability trade-off."""
    resolve_model, resolve_subsystem = _resolvers(session, ctx.read_owners)
    try:
        result = rbd_design.design_redundancy(
            graph, t, blocks, budget=budget, target=target, mixing=mixing,
            resolve_model=resolve_model, resolve_subsystem=resolve_subsystem,
        )
    except rbd_design.DesignError as exc:
        return JSONResponse(status_code=422, content={"detail": str(exc)})
    except Exception:  # pragma: no cover - defensive
        logger.exception("Redundancy design failed")
        return JSONResponse(
            status_code=500, content={"detail": "Couldn't find a design for this diagram."}
        )
    return JSONResponse(content=result)


@router.post("/rbds/design/apply")
def apply_rbd_design(
    graph: dict = Body(...),
    blocks: list = Body(default=[]),
    design: list = Body(default=[]),
    t: float | None = Body(default=None),
    session=Depends(get_session),
    ctx: AccessCtx = Depends(get_access),
) -> JSONResponse:
    """The diagram with a design drawn on it (not saved), and its R(t)."""
    resolve_model, resolve_subsystem = _resolvers(session, ctx.read_owners)
    try:
        out = rbd_design.apply_design(graph, blocks, design)
        reliability = (
            rbd_design.applied_reliability(out, t, resolve_model, resolve_subsystem)
            if t is not None else None
        )
    except rbd_design.DesignError as exc:
        return JSONResponse(status_code=422, content={"detail": str(exc)})
    except Exception:  # pragma: no cover - defensive
        logger.exception("Applying a redundancy design failed")
        return JSONResponse(
            status_code=500, content={"detail": "Couldn't draw this design on the diagram."}
        )
    return JSONResponse(content={"graph": out, "reliability": reliability})
