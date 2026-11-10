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
from backend.errors import client_message

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
        return JSONResponse(status_code=422, content={"detail": client_message(exc)})
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
        return JSONResponse(status_code=422, content={"detail": client_message(exc)})
    except Exception:  # pragma: no cover - defensive
        logger.exception("Failed to analyse a network")
        return JSONResponse(status_code=500, content={
            "detail": "Failed to analyse the network. The error has been logged."})


# ---- missions on a saved RBD (rbd_missions.py): list, open, create, change, delete, calculate ----

def _rbd_or_404(session, rbd_id: str, ctx: AccessCtx):
    from backend.schema import Rbd
    from backend.services import access as access_service

    rbd, _ = access_service.fetch_readable(session, "rbds", Rbd, rbd_id, ctx)
    if rbd is None or rbd.id in ctx.hidden:
        return None, JSONResponse(status_code=404, content={"detail": "RBD not found."})
    return rbd, None


def _results(session, rbd_id: str) -> dict:
    doc = session.rbds.find_one({"_id": rbd_id}, {"mission_results": 1}) or {}
    return doc.get("mission_results") or {}


def _rbd_brief(rbd, ctx: AccessCtx) -> dict:
    from backend.services import access as access_service

    return {"id": rbd.id, "name": rbd.name, "unit": (rbd.graph or {}).get("unit") or "",
            "repairable": bool((rbd.graph or {}).get("repairable")),
            "read_only": not access_service.can_write(ctx, rbd.owner_id),
            "updated_at": rbd.updated_at.isoformat() if rbd.updated_at else None}


@router.get("/rbds/{rbd_id}/missions")
def list_missions(rbd_id: str, session=Depends(get_session), ctx: AccessCtx = Depends(get_access)) -> JSONResponse:
    """A diagram's missions (its own phases first, as one mission), each with how many phases, its
    length and its last result while that still holds."""
    from backend.services import rbd_missions

    rbd, err = _rbd_or_404(session, rbd_id, ctx)
    if err:
        return err
    results = _results(session, rbd_id)
    return JSONResponse(content={"rbd": _rbd_brief(rbd, ctx), "missions": [
        rbd_missions.summary(rbd.graph or {}, m, results) for m in rbd_missions.missions_of(rbd.graph or {})]})


@router.get("/rbds/{rbd_id}/missions/{mission_id}")
def get_mission(rbd_id: str, mission_id: str, session=Depends(get_session),
                ctx: AccessCtx = Depends(get_access)) -> JSONResponse:
    """One mission in full: its phases, the blocks a phase can do without, the vote nodes, and
    every Use and Environment covariate its phases can set (with the blocks each feeds and, per
    phase, the value each block uses and where it comes from)."""
    from backend.services import rbd_missions

    rbd, err = _rbd_or_404(session, rbd_id, ctx)
    if err:
        return err
    graph = rbd.graph or {}
    mission = rbd_missions.find(graph, mission_id)
    if mission is None:
        return JSONResponse(status_code=404, content={"detail": "That mission isn't on this RBD (deleted?)."})
    out = rbd_missions.detail(session, ctx.read_owners, graph, mission)
    out["summary"] = rbd_missions.summary(graph, mission, _results(session, rbd_id))
    return JSONResponse(content={"rbd": _rbd_brief(rbd, ctx), **out})


def _write(session, ctx: AccessCtx, rbd_id: str, change, expected_updated_at: str | None = None):
    """Apply ``change(graph) -> (graph, mission | None)`` to an RBD the caller may edit and save it."""
    from backend.services import access as access_service
    from backend.services import rbd_missions
    from backend.services import rbds as rbds_service
    from backend.services.rbd_graph import GraphError, check_limits

    rbd, err = _rbd_or_404(session, rbd_id, ctx)
    if err:
        return err
    denial = access_service.write_denial(ctx, rbd.owner_id)
    if denial:
        status, payload = denial
        return JSONResponse(status_code=status, content=payload)
    try:
        graph, mission = change(dict(rbd.graph or {}))
        check_limits(graph)
    except (rbd_missions.MissionError, GraphError) as exc:
        return JSONResponse(status_code=422, content={"detail": client_message(exc)})
    try:
        saved = rbds_service.save_rbd(session, rbd.name, graph, ctx.write_owner, rbd_id=rbd.id,
                                      expected_updated_at=expected_updated_at)
    except access_service.EditConflict:
        return JSONResponse(status_code=409, content={"detail": access_service.CONFLICT_MSG, "code": "conflict"})
    access_service.stamp_editor(session, "rbds", rbd.id, ctx)
    out = {"rbd": _rbd_brief(saved, ctx)}
    if mission is not None:
        out["mission"] = rbd_missions.summary(graph, mission, _results(session, rbd_id))
    return JSONResponse(content=out)


@router.post("/rbds/{rbd_id}/missions")
def create_mission(rbd_id: str, name: str | None = Body(default=None), phases: list | None = Body(default=None),
                   session=Depends(get_session), ctx: AccessCtx = Depends(get_access)) -> JSONResponse:
    """A new mission on the diagram ("Mission N" unless named; phases optional)."""
    from backend.services import rbd_missions

    return _write(session, ctx, rbd_id, lambda g: rbd_missions.save(g, None, name, phases))


@router.put("/rbds/{rbd_id}/missions/{mission_id}")
def update_mission(rbd_id: str, mission_id: str, name: str | None = Body(default=None),
                   phases: list | None = Body(default=None), expected_updated_at: str | None = Body(default=None),
                   session=Depends(get_session), ctx: AccessCtx = Depends(get_access)) -> JSONResponse:
    """Rename a mission or replace its phases (each with its duration, blocks not needed, vote
    counts, values and block values). ``expected_updated_at``: refuse if the diagram changed since."""
    from backend.services import rbd_missions

    return _write(session, ctx, rbd_id, lambda g: rbd_missions.save(g, mission_id, name, phases),
                  expected_updated_at)


@router.delete("/rbds/{rbd_id}/missions/{mission_id}")
def delete_mission(rbd_id: str, mission_id: str, session=Depends(get_session),
                   ctx: AccessCtx = Depends(get_access)) -> JSONResponse:
    """Delete a mission (the diagram stays as it is)."""
    from backend.services import rbd_missions

    resp = _write(session, ctx, rbd_id, lambda g: (rbd_missions.remove(g, mission_id), None))
    if resp.status_code == 200:
        session.rbds.update_one({"_id": rbd_id}, {"$unset": {f"mission_results.{mission_id}": ""}})
    return resp


@router.post("/rbds/{rbd_id}/missions/{mission_id}/calculate")
def calculate_mission(rbd_id: str, mission_id: str, phases: list | None = Body(default=None, embed=True),
                      session=Depends(get_session), ctx: AccessCtx = Depends(get_access)) -> JSONResponse:
    """The chance of completing the mission, each phase's failure probability and reliability at
    its end, and each phase's weakest block. ``phases``: work out these (unsaved edits) instead of
    the saved ones. A phase still missing a value waits; the result says which blocks need what.
    Quick, so not plan-gated. A result for the saved phases is kept for the lists."""
    from backend.services import access as access_service
    from backend.services import rbd_missions

    rbd, err = _rbd_or_404(session, rbd_id, ctx)
    if err:
        return err
    graph = rbd.graph or {}
    mission = rbd_missions.find(graph, mission_id)
    if mission is None:
        return JSONResponse(status_code=404, content={"detail": "That mission isn't on this RBD (deleted?)."})
    use = mission["phases"] if phases is None else phases
    try:
        result = rbd_missions.analyze(session, ctx.read_owners, graph, use)
    except AnalysisError as exc:
        return JSONResponse(status_code=422, content={"detail": client_message(exc)})
    except Exception:  # pragma: no cover - defensive
        logger.exception("Failed to analyse a mission")
        return JSONResponse(status_code=500, content={
            "detail": "Failed to work out the mission. The error has been logged."})
    try:
        saved_phases = rbd_phases.parse_phases(mission["phases"])
        same = rbd_phases.parse_phases(use) == saved_phases
    except rbd_phases.PhaseError:
        same = False
    if same and access_service.can_write(ctx, rbd.owner_id):
        record = rbd_missions.result_record(graph, saved_phases, result)
        session.rbds.update_one({"_id": rbd.id}, {"$set": {f"mission_results.{mission_id}": record}})
    return JSONResponse(content={"mission": {"id": mission["id"], "name": mission["name"]}, **result})
