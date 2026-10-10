"""Allocation for RBDs: what each block needs to meet a system target (#53).

Free for everyone, like the redundancy design: the allocation is exact and
quick. Nothing is saved.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Body, Depends
from fastapi.responses import JSONResponse

from backend.db import get_session
from backend.services import rbd_allocation
from backend.services.access import AccessCtx, get_access

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api")


@router.post("/rbds/allocate")
def allocate_rbd(
    graph: dict = Body(...),
    target: float | None = Body(default=None),
    method: str = Body(default="equal"),
    t: float | None = Body(default=None),
    options: dict | None = Body(default=None),
    session=Depends(get_session),
    ctx: AccessCtx = Depends(get_access),
) -> JSONResponse:
    """Each block's reliability at ``t`` (non-repairable) or availability
    (repairable) for the system to meet ``target``, against what it has now.
    An unreachable target is a 422 with ``reachable``: the range the system
    can reach."""
    try:
        result = rbd_allocation.allocate_for_owner(
            session, graph, ctx.read_owners, target, method, t=t, options=options)
    except rbd_allocation.AllocationError as exc:
        body = {"detail": str(exc)}
        if exc.reachable is not None:
            body["reachable"] = exc.reachable
        return JSONResponse(status_code=422, content=body)
    except Exception:  # pragma: no cover - defensive
        logger.exception("Allocation failed")
        return JSONResponse(status_code=500, content={"detail": "Couldn't allocate the target for this diagram."})
    return JSONResponse(content=result)
