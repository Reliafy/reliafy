"""Phased missions and undirected networks of an RBD (#160): the mission's
reliability phase by phase, and a network's two-terminal reliability."""

from __future__ import annotations

import logging
import math

from typing import Any

from fastapi import APIRouter, Body, Depends
from fastapi.responses import JSONResponse

from backend.db import get_session
from backend.services import rbd_network, rbd_phases
from backend.services.access import AccessCtx, get_access
from backend.services.rbd_analysis import AnalysisError
from backend.errors import client_message
from backend.services import rbd_live_models

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api")


def _simulation(session, ctx: AccessCtx):
    """Leave to simulate a mission that can only be simulated (blocks on standby without constant
    rates, standby blocks set to be simulated): Pro, like every simulation."""
    from backend.routers.rbds import standby_simulation

    return standby_simulation(session, ctx)


def _pro_payload(exc: Exception) -> dict:
    """The 402 for a mission only a simulation can work out: what stops it, then what Pro adds."""
    from backend.routers.rbds import standby_pro_payload

    if client_message(exc) == rbd_phases.MISSION_PRO_MESSAGE:
        return {"detail": rbd_phases.MISSION_PRO_MESSAGE, "code": "pro_required", "upgrade": True}
    return standby_pro_payload(exc)


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
    current_state: dict | None = Body(default=None),
    session=Depends(get_session),
    ctx: AccessCtx = Depends(get_access),
) -> JSONResponse:
    """A non-repairable graph's phased mission (its ``phases``): the mission
    reliability, each phase's failure probability and the reliability at its
    end, and the riskiest phase. Exact, or simulated where the mission is too
    large (the result says which). Quick, so not plan-gated. ``current_state``:
    the blocks' states now (as the diagram's calculation takes them), so the
    mission flies from their ages. A mission only a simulation can work out (blocks on standby
    without constant failure rates) needs Pro: 402 with code ``pro_required`` otherwise."""
    graph = rbd_live_models.refresh(session, graph, ctx.read_owners)  # linked blocks on their model's fit
    from backend.services import rbd_standby

    try:
        with _simulation(session, ctx):
            return JSONResponse(content=rbd_phases.analyze_for_owner(session, graph, ctx.read_owners,
                                                                     covariates=covariates or None,
                                                                     current_state=current_state or None))
    except rbd_standby.SimulationNeedsPro as exc:
        return JSONResponse(status_code=402, content=_pro_payload(exc))
    except AnalysisError as exc:
        return JSONResponse(status_code=422, content={"detail": client_message(exc)})
    except Exception:  # pragma: no cover - defensive
        logger.exception("Failed to analyse a phased mission")
        return JSONResponse(status_code=500, content={
            "detail": "Failed to analyse the phased mission. The error has been logged."})


@router.post("/rbds/phases/covariates")
def phase_covariates(graph: dict = Body(..., embed=True), session=Depends(get_session),
                     ctx: AccessCtx = Depends(get_access)) -> JSONResponse:
    """Every covariate a phase of this (unsaved) diagram can set: one row per covariate a block's
    life model leaves open (bound NSWC-11, ALT and PH blocks, and saved regression models), with the
    blocks each feeds. The same list the Explorer's tree hangs under each phase (rbd_missions.gather)."""
    graph = rbd_live_models.refresh(session, graph, ctx.read_owners)  # linked blocks on their model's fit
    from backend.services import covariate_binding as cb
    from backend.services import rbd_missions

    got = rbd_missions.gather(graph or {}, rbd_missions._inputs_cache(lambda b: cb.inputs_of(b, session, ctx.read_owners)))
    return JSONResponse(content=got)


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
    graph = rbd_live_models.refresh(session, graph, ctx.read_owners)  # linked blocks on their model's fit
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
    if out["summary"].get("simple"):
        # A plain mission's editor: the fitted item's age now, so it can offer "Its age now".
        out["age_now"] = age_now_for(ctx.user, ctx.write_owner, ctx.uid, getattr(ctx, "time_zone", None), graph,
                                     any_start=True)
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
        name = rbd_missions.rbd_name_after(rbd.name, rbd.graph or {}, graph)
        saved = rbds_service.save_rbd(session, name, graph, ctx.write_owner, rbd_id=rbd.id,
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
                   start: Any = Body(default="unset"), setup: Any = Body(default="unset"),
                   session=Depends(get_session), ctx: AccessCtx = Depends(get_access)) -> JSONResponse:
    """Rename a mission or replace its phases (each with its duration, blocks not needed, vote
    counts, values and block values). ``start``: a mission on a life model with no covariates
    starts at this age ({"age": t} in the RBD's unit, "now" for the fitted item's age when it's
    worked out, or "new"). ``setup``: a mission with an RBD of its own: {start: "now" | date,
    calendar: {linked: true} | {hours_per_day, days_per_week}, from: "new" | "today"} (null clears
    it). ``expected_updated_at``: refuse if the diagram changed since."""
    from backend.services import rbd_missions

    extra = {} if start == "unset" else {"start": start}
    if setup != "unset":
        extra["setup"] = setup
    return _write(session, ctx, rbd_id, lambda g: rbd_missions.save(g, mission_id, name, phases, **extra),
                  expected_updated_at)


@router.delete("/rbds/{rbd_id}/missions/{mission_id}")
def delete_mission(rbd_id: str, mission_id: str, session=Depends(get_session),
                   ctx: AccessCtx = Depends(get_access)) -> JSONResponse:
    """Delete a mission (the diagram stays as it is). A mission with an RBD of its own (one built
    for it on its position) goes with that RBD."""
    from backend.services import access as access_service
    from backend.services import rbd_missions
    from backend.services import rbds as rbds_service

    rbd, err = _rbd_or_404(session, rbd_id, ctx)
    if err:
        return err
    if mission_id == rbd_missions.LEGACY_ID and rbd_missions.mission_of(rbd.graph or {}):
        denial = access_service.write_denial(ctx, rbd.owner_id)
        if denial:
            status, payload = denial
            return JSONResponse(status_code=status, content=payload)
        try:
            rbds_service.delete_rbd(session, rbd.id, ctx.write_owner)
        except rbds_service.RbdNotFound:
            return JSONResponse(status_code=404, content={"detail": "RBD not found."})
        return JSONResponse(content={"deleted": {"mission": mission_id, "rbd": rbd.id}})
    resp = _write(session, ctx, rbd_id, lambda g: (rbd_missions.remove(g, mission_id), None))
    if resp.status_code == 200:
        session.rbds.update_one({"_id": rbd_id}, {"$unset": {f"mission_results.{mission_id}": ""}})
    return resp


def _age_now(ctx: AccessCtx, graph: dict) -> dict | None:
    """The fitted item's age now at a plain mission's position (block_age), for a mission started
    "now"; None for any other mission, or where Maintenance isn't on for the caller."""
    return age_now_for(ctx.user, ctx.write_owner, ctx.uid, getattr(ctx, "time_zone", None), graph)


def age_now_for(user, org: str, actor: str, time_zone, graph: dict, any_start: bool = False) -> dict | None:
    """As :func:`_age_now`, for any caller (the MCP tools too). ``any_start``: whatever the mission
    starts at (the editor offers "Its age now" where an item is fitted)."""
    from backend import config
    from backend.services import rbd_missions

    start = rbd_missions.start_of(graph) or {}
    owner = rbd_missions.mission_of(graph)
    if not ((any_start or start.get("now")) and owner and rbd_missions.simple_block(graph) is not None):
        return None
    try:
        from backend.maintenance.access import allowed
        from backend.maintenance import rbd_tree_plan
        from backend.maintenance.service import Maintenance
        from backend.routers.maintenance import get_store

        if not (config.MAINTENANCE_ENABLED and allowed(user)):
            return {"reason": "Reliafy Maintenance isn't on for this account, so the item's age can't be read"}
        m = Maintenance(get_store(), org, actor, time_zone=time_zone)
        p = m.s.node(m.org, owner["position_id"])
        if p is None:
            return {"reason": "its position isn't there any more"}
        return rbd_tree_plan.block_age(m, p, graph.get("unit") or "")
    except Exception:  # noqa: BLE001 - said in words, worked out from new
        logger.exception("Couldn't read a mission's age now")
        return {"reason": "the item's age couldn't be read"}


@router.post("/rbds/{rbd_id}/missions/{mission_id}/calculate")
def calculate_mission(rbd_id: str, mission_id: str, phases: list | None = Body(default=None, embed=True),
                      current_state: dict | None = Body(default=None, embed=True),
                      start: Any = Body(default="unset", embed=True),
                      session=Depends(get_session), ctx: AccessCtx = Depends(get_access)) -> JSONResponse:
    """The chance of completing the mission, each phase's failure probability and reliability at
    its end, and each phase's weakest block. ``phases``: work out these (unsaved edits) instead of
    the saved ones; ``start``: a plain mission's starting age, unsaved (as PUT takes it: {"age": t}, "now" or "new").
    ``current_state``: the blocks' states now (``{node_id: {"failed": true} |
    {"age": t}}``, as ``POST /api/rbds/phases`` takes them), so the mission flies from their ages
    ("As of now" in the notes). A phase still missing a value waits; the result says which blocks
    need what. Exact answers are free; a mission only a simulation can work out (blocks on standby
    without constant failure rates) needs Pro (402, code ``pro_required``). A from-new result for
    the saved phases is kept for the lists; an as-of-now one isn't."""
    from backend.services import access as access_service
    from backend.services import rbd_missions, rbd_standby

    rbd, err = _rbd_or_404(session, rbd_id, ctx)
    if err:
        return err
    graph = rbd.graph or {}
    mission = rbd_missions.find(graph, mission_id)
    if mission is None:
        return JSONResponse(status_code=404, content={"detail": "That mission isn't on this RBD (deleted?)."})
    use = mission["phases"] if phases is None else phases
    saved_start = rbd_missions.start_of(graph)
    if start != "unset":  # an unsaved starting age (a plain mission's editor): worked out, not kept
        try:
            graph, _ = rbd_missions.save(graph, mission_id, start=start)
        except rbd_missions.MissionError as exc:
            return JSONResponse(status_code=422, content={"detail": client_message(exc)})
    age_now = _age_now(ctx, graph) if not current_state else None
    try:
        with _simulation(session, ctx):
            result = rbd_missions.analyze(session, ctx.read_owners, graph, use, current_state=current_state or None,
                                          age_now=age_now)
    except rbd_standby.SimulationNeedsPro as exc:
        return JSONResponse(status_code=402, content=_pro_payload(exc))
    except AnalysisError as exc:
        # Blocks a phase needs with no life model: named, so the pane can offer what to do.
        needs = {"needs_model": exc.blocks} if getattr(exc, "blocks", None) else {}
        return JSONResponse(status_code=422, content={"detail": client_message(exc), **needs})
    except Exception:  # pragma: no cover - defensive
        logger.exception("Failed to analyse a mission")
        return JSONResponse(status_code=500, content={
            "detail": "Failed to work out the mission. The error has been logged."})
    try:
        saved_phases = rbd_phases.parse_phases(mission["phases"])
        same = rbd_phases.parse_phases(use) == saved_phases
    except rbd_phases.PhaseError:
        same = False
    same = same and rbd_missions.start_of(graph) == saved_start
    if same and not current_state and access_service.can_write(ctx, rbd.owner_id):
        # A plain mission's result is kept with the age it flew from (its stored start, now included).
        record = rbd_missions.result_record(graph, saved_phases, result)
        session.rbds.update_one({"_id": rbd.id}, {"$set": {f"mission_results.{mission_id}": record}})
    return JSONResponse(content={"mission": {"id": mission["id"], "name": mission["name"]}, **result})


def maintenance_for(user, org: str, actor: str, time_zone):
    """The caller's Maintenance (for a mission's position: its duty, today's ages, its plan), or
    None where Maintenance isn't on for them."""
    from backend import config

    try:
        from backend.maintenance.access import allowed
        from backend.maintenance.service import Maintenance
        from backend.routers.maintenance import get_store

        if not (config.MAINTENANCE_ENABLED and allowed(user)):
            return None
        return Maintenance(get_store(), org, actor, time_zone=time_zone)
    except Exception:  # noqa: BLE001 - the answers say what they couldn't read
        logger.exception("Couldn't open Maintenance for a mission's answers")
        return None


def mission_answers_for(session, ctx: AccessCtx, rbd, mission_id: str) -> tuple[int, dict]:
    """(status, payload) of a mission's two answers: the REST route's and the MCP action's."""
    from backend.services import billing as billing_service
    from backend.services import mission_answers, rbd_missions, rbd_standby

    graph = rbd.graph or {}
    mission = rbd_missions.find(graph, mission_id)
    if mission is None:
        return 404, {"detail": "That mission isn't on this RBD (deleted?)."}
    owner = rbd_missions.mission_of(graph) or {}
    m = maintenance_for(ctx.user, ctx.write_owner, ctx.uid, getattr(ctx, "time_zone", None)) if owner else None
    simulate = billing_service.premium_compute_allowed(session, ctx.user)
    try:
        with _simulation(session, ctx):
            out = mission_answers.answers(session, ctx.read_owners, graph, mission, m=m,
                                          position_id=owner.get("position_id"),
                                          today=m.today() if m is not None else None, simulate=simulate,
                                          age_now=_age_now(ctx, graph))
    except rbd_standby.SimulationNeedsPro as exc:
        return 402, _pro_payload(exc)
    except AnalysisError as exc:
        needs = {"needs_model": exc.blocks} if getattr(exc, "blocks", None) else {}
        return 422, {"detail": client_message(exc), **needs}
    return 200, out


@router.post("/rbds/{rbd_id}/missions/{mission_id}/answers")
def mission_answers(rbd_id: str, mission_id: str, session=Depends(get_session),
                    ctx: AccessCtx = Depends(get_access)) -> JSONResponse:
    """A mission's two answers over its whole phased length: the chance of completing it (with its
    90% one-sided lower bound where one can be drawn) and the system failures to expect during it
    (failed blocks replaced at once, like new), with a 90% two-sided range of outcomes (simulated:
    Pro). With them: its calendar (start, end through its duty), its starting state, the current
    maintenance plan on its blocks (read only, not counted yet) and what it assumed. Blocks with no
    model, or a placeholder, stop both answers and are listed (``blocked``)."""
    rbd, err = _rbd_or_404(session, rbd_id, ctx)
    if err:
        return err
    status, out = mission_answers_for(session, ctx, rbd, mission_id)
    return JSONResponse(status_code=status, content=out)
