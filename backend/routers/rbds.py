"""Saved RBD (reliability block diagram) API."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Body, Depends
from fastapi.responses import JSONResponse

from backend.auth import get_current_user
from backend.db import get_session
from backend.services import billing as billing_service
from backend.services import rbds as rbds_service
from backend.services import samples as samples_service
from backend.services.rbd_analysis import AnalysisError

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api")


def _summary(rbd) -> dict:
    graph = rbd.graph or {}
    return {
        "id": rbd.id,
        "name": rbd.name,
        "n_nodes": len(graph.get("nodes", [])),
        "n_edges": len(graph.get("edges", [])),
        "created_at": rbd.created_at.isoformat(),
        "updated_at": rbd.updated_at.isoformat(),
        "is_sample": samples_service.is_sample(rbd.owner_id),
    }


@router.get("/rbds")
def list_rbds(session=Depends(get_session), user: dict = Depends(get_current_user)) -> dict:
    hidden = samples_service.hidden_sample_ids(session, user["uid"])
    return {
        "rbds": [_summary(r) for r in rbds_service.list_rbds(session, user["uid"], hidden)]
    }


@router.post("/rbds")
def save_rbd(
    name: str = Body(...),
    graph: dict = Body(...),
    id: str | None = Body(default=None),
    session=Depends(get_session),
    user: dict = Depends(get_current_user),
) -> JSONResponse:
    # Free-plan cap applies only when creating a new diagram (updating one you
    # own, or forking a sample, is checked by whether you already own it).
    existing = rbds_service.get_rbd(session, id, user["uid"]) if id else None
    creating = existing is None or existing.owner_id != user["uid"]
    if creating and billing_service.would_exceed_cap(session, user["uid"], "rbds"):
        return JSONResponse(
            status_code=402,
            content={"detail": "You've reached the free-plan limit of 1 saved RBD. Upgrade to Pro for unlimited diagrams.", "code": "cap", "upgrade": True},
        )
    rbd = rbds_service.save_rbd(session, name, graph, user["uid"], rbd_id=id)
    return JSONResponse(content=_summary(rbd))


@router.get("/rbds/{rbd_id}")
def get_rbd(
    rbd_id: str, session=Depends(get_session), user: dict = Depends(get_current_user)
) -> JSONResponse:
    hidden = samples_service.hidden_sample_ids(session, user["uid"])
    rbd = rbds_service.get_rbd(session, rbd_id, user["uid"])
    if rbd is None or rbd.id in hidden:
        return JSONResponse(status_code=404, content={"detail": "RBD not found."})
    return JSONResponse(content={**_summary(rbd), "graph": rbd.graph})


@router.delete("/rbds/{rbd_id}")
def delete_rbd(
    rbd_id: str, session=Depends(get_session), user: dict = Depends(get_current_user)
) -> JSONResponse:
    uid = user["uid"]
    hidden = samples_service.hidden_sample_ids(session, uid)
    rbd = rbds_service.get_rbd(session, rbd_id, uid)
    if rbd is None or rbd.id in hidden:
        return JSONResponse(status_code=404, content={"detail": "RBD not found."})

    # A shared sample isn't really deleted — just hidden for this user.
    if samples_service.is_sample(rbd.owner_id):
        samples_service.hide_sample(session, uid, rbd_id)
        return JSONResponse(content={"ok": True})
    try:
        rbds_service.delete_rbd(session, rbd_id, uid)
    except rbds_service.RbdNotFound:
        return JSONResponse(status_code=404, content={"detail": "RBD not found."})
    return JSONResponse(content={"ok": True})


@router.post("/rbds/analyze")
def analyze_graph(
    graph: dict = Body(..., embed=True),
    t_max: float | None = Body(default=None),
    covariates: dict = Body(default={}),
    conditional_age: float | None = Body(default=None),
    session=Depends(get_session),
    user: dict = Depends(get_current_user),
) -> JSONResponse:
    """Analyse an (unsaved) RBD graph with RePyability and return the results.

    ``t_max`` is the upper limit of the time axis to compute over.
    ``covariates`` maps node id -> covariate values for proportional-hazards
    nodes. ``conditional_age`` conditions the curves on having already survived
    to that age (so the result is the conditional survival).
    """
    try:
        return JSONResponse(
            content=rbds_service.analyze_graph(
                session,
                graph,
                user["uid"],
                t_max=t_max,
                covariates=covariates,
                conditional_age=conditional_age,
            )
        )
    except AnalysisError as exc:
        return JSONResponse(status_code=422, content={"detail": str(exc)})
    except Exception as exc:  # pragma: no cover - defensive
        logger.exception("Failed to analyse RBD graph")
        return JSONResponse(
            status_code=500, content={"detail": f"Failed to analyse RBD: {exc}"}
        )


@router.get("/rbds/{rbd_id}/analyze")
def analyze_rbd(
    rbd_id: str,
    t_max: float | None = None,
    session=Depends(get_session),
    user: dict = Depends(get_current_user),
) -> JSONResponse:
    """Analyse a saved RBD with RePyability and return the results."""
    try:
        return JSONResponse(
            content=rbds_service.analyze_rbd(session, rbd_id, user["uid"], t_max=t_max)
        )
    except rbds_service.RbdNotFound:
        return JSONResponse(status_code=404, content={"detail": "RBD not found."})
    except AnalysisError as exc:
        return JSONResponse(status_code=422, content={"detail": str(exc)})
    except Exception as exc:  # pragma: no cover - defensive
        logger.exception("Failed to analyse RBD %s", rbd_id)
        return JSONResponse(
            status_code=500, content={"detail": f"Failed to analyse RBD: {exc}"}
        )


@router.post("/rbds/validate")
def validate_graph(
    graph: dict = Body(..., embed=True),
    session=Depends(get_session),
    user: dict = Depends(get_current_user),
) -> JSONResponse:
    """Check whether an (unsaved) graph is a valid, analytically solvable RBD."""
    return JSONResponse(content=rbds_service.validate_graph(session, graph, user["uid"]))


@router.get("/rbds/{rbd_id}/validate")
def validate_rbd(
    rbd_id: str, session=Depends(get_session), user: dict = Depends(get_current_user)
) -> JSONResponse:
    """Check whether a saved RBD is valid and analytically solvable."""
    try:
        return JSONResponse(content=rbds_service.validate_rbd(session, rbd_id, user["uid"]))
    except rbds_service.RbdNotFound:
        return JSONResponse(status_code=404, content={"detail": "RBD not found."})
