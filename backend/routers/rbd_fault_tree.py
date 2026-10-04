"""Fault-tree view of an RBD (#101): the diagram's failure logic as gates over
basic events, with the top event probability and ranked cut sets."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Body, Depends
from fastapi.responses import JSONResponse

from backend.db import get_session
from backend.services import rbd_fault_tree
from backend.services.access import AccessCtx, get_access
from backend.services.rbd_analysis import AnalysisError

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api")


@router.post("/rbds/fault-tree")
def fault_tree(
    graph: dict = Body(..., embed=True),
    t: float | None = Body(default=None),
    t_max: float | None = Body(default=None),
    covariates: dict = Body(default={}),
    session=Depends(get_session),
    ctx: AccessCtx = Depends(get_access),
) -> JSONResponse:
    """The fault tree of an (unsaved) RBD graph, evaluated at time ``t``.

    ``t`` defaults to the calculator's importance time (``t_max`` is the
    calculator's axis limit, if set). Repairable graphs are evaluated at
    steady state. Exact and quick, so not plan-gated.
    """
    try:
        return JSONResponse(
            content=rbd_fault_tree.fault_tree_for_owner(
                session, graph, ctx.read_owners, t=t, t_max=t_max, covariates=covariates
            )
        )
    except AnalysisError as exc:
        return JSONResponse(status_code=422, content={"detail": str(exc)})
    except Exception:  # pragma: no cover - defensive
        logger.exception("Failed to build the fault tree of an RBD graph")
        return JSONResponse(
            status_code=500, content={"detail": "Failed to build the fault tree. The error has been logged."}
        )
