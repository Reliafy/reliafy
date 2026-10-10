"""Phased missions and undirected networks of an RBD (#160): the mission's
reliability phase by phase, and a network's two-terminal reliability."""

from __future__ import annotations

import logging
import math

from fastapi import APIRouter, Body, Depends
from fastapi.responses import JSONResponse

from backend.db import get_session
from backend.services import rbd_network, rbd_phases
from backend.services.access import AccessCtx, get_access
from backend.services.rbd_analysis import AnalysisError

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api")


def _time(value) -> float | None:
    """A finite time of at least 0, else None (the default)."""
    try:
        v = float(value)
    except (TypeError, ValueError):
        return None
    return v if math.isfinite(v) and v >= 0 else None


@router.post("/rbds/phases")
def phased_mission(
    graph: dict = Body(..., embed=True),
    covariates: dict = Body(default={}),
    session=Depends(get_session),
    ctx: AccessCtx = Depends(get_access),
) -> JSONResponse:
    """A non-repairable graph's phased mission (its ``phases``): the mission
    reliability, each phase's failure probability and the reliability at its
    end, and the riskiest phase. Exact, or simulated where the mission is too
    large (the result says which). Quick, so not plan-gated."""
    try:
        return JSONResponse(content=rbd_phases.analyze_for_owner(session, graph, ctx.read_owners,
                                                                 covariates=covariates or None))
    except AnalysisError as exc:
        return JSONResponse(status_code=422, content={"detail": str(exc)})
    except Exception:  # pragma: no cover - defensive
        logger.exception("Failed to analyse a phased mission")
        return JSONResponse(status_code=500, content={
            "detail": "Failed to analyse the phased mission. The error has been logged."})


@router.post("/rbds/network")
def network_reliability(
    graph: dict = Body(..., embed=True),
    t: float | None = Body(default=None),
    t_max: float | None = Body(default=None),
    covariates: dict = Body(default={}),
    session=Depends(get_session),
    ctx: AccessCtx = Depends(get_access),
) -> JSONResponse:
    """A network graph's two-terminal reliability: the chance its terminals
    stay connected over time, at ``t`` (default: where it falls to about
    90%), the mean time until they part, and each block's Birnbaum
    importance. Exact by decision diagram, or simulated where that is too
    large. Quick, so not plan-gated."""
    try:
        return JSONResponse(content=rbd_network.analyze_for_owner(
            session, graph, ctx.read_owners, t=_time(t), t_max=_time(t_max) or None,
            covariates=covariates or None))
    except AnalysisError as exc:
        return JSONResponse(status_code=422, content={"detail": str(exc)})
    except Exception:  # pragma: no cover - defensive
        logger.exception("Failed to analyse a network")
        return JSONResponse(status_code=500, content={
            "detail": "Failed to analyse the network. The error has been logged."})
