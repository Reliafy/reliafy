"""Availability with repairs for any block diagram: the REST route and the payload the MCP tool
shares (see :mod:`backend.services.rbd_repair_availability`).

This side reads what the database and the asset tree hold for each block's repair time: the
outages recorded against the diagram (its outage history) and the maintainability prediction of
the position a block stands for (a diagram built from the tree, or a mission's diagram on a
position); and, for the achieved figure, the planned work on those positions' tasks. RePyability
does the maths. Exact and free for everyone, as the repairable Calculator's exact figures are.
"""

from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, Body, Depends
from fastapi.responses import JSONResponse

from backend.db import get_session
from backend.errors import client_message
from backend.schema import Rbd
from backend.services import access as access_service
from backend.services import models as models_service
from backend.services import rbd_repair_availability as rra
from backend.services import rbds as rbds_service
from backend.services.access import AccessCtx, get_access
from backend.services.rbd_analysis import AnalysisError, require_blocks
from backend.units import unit_factor
from backend.services import rbd_live_models

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api")


def recorded_repairs(session, rbd, graph: dict, owners) -> dict:
    """{block id: {mean (diagram unit), count, name}}: the mean of the finished unplanned outages
    in the diagram's latest outage history, per block (its units pooled)."""
    from backend.services import outage_logs

    if rbd is None:
        return {}
    try:
        log = outage_logs.latest_log(session, rbd.id, owners)
        if not log or not log.get("rows"):
            return {}
        data = outage_logs.fit_data(graph, log)
    except Exception:  # noqa: BLE001 - an unreadable history is no source, never a failed answer
        logger.exception("Couldn't read the outage history for repair times")
        return {}
    unit_f = unit_factor(log.get("unit") or "", graph.get("unit") or "") or 1.0
    out = {}
    for nid, row in data.items():
        xs, cs = row.get("repair") or ([], [])
        done = [float(x) for x, c in zip(xs, cs) if c == 0 and x > 0]
        if done:
            out[str(nid)] = {"mean": sum(done) / len(done) * unit_f, "count": len(done),
                             "name": log.get("name") or "the outage history"}
    return out


def _top_position(m, rbd, graph: dict) -> Optional[str]:
    """The position a diagram stands for: the one it's linked to (built from the tree), else the
    position whose mission it is."""
    from backend.maintenance import rbd_tree_plan

    if rbd is not None:
        linked = rbd_tree_plan.positions_of_rbd(m, rbd.id)
        if linked:
            return linked[0]["id"]
    owner = (graph or {}).get("mission_of") or ((getattr(rbd, "graph", None) or {}).get("mission_of") if rbd else None) or {}
    pid = owner.get("position_id") if isinstance(owner, dict) else None
    return pid if pid and m.s.node(m.org, pid, "Position") is not None else None


def tree_context(ctx, rbd, graph: dict):
    """(Maintenance, {block id: position}) for a diagram that stands for a position, or (None, {})."""
    from backend.maintenance import rbd_tree_plan

    m = rbd_tree_plan.maintenance_for(ctx) if ctx is not None else None
    if m is None:
        return None, {}
    try:
        top = _top_position(m, rbd, graph)
        if not top:
            return m, {}
        blocks = [{"id": b["id"], "label": b["label"]} for b in rra.blocks_of(graph)]
        return m, rbd_tree_plan.block_positions(m, top, blocks)
    except Exception:  # noqa: BLE001 - the tree never keeps a diagram from its answer
        logger.exception("Couldn't map an RBD's blocks to positions")
        return m, {}


def prediction_repairs(session, mapped: dict, owners) -> dict:
    """{block id: {hours, name, position}}: the newest maintainability prediction saved for the
    position each block stands for (its Mct)."""
    from backend.services import maintainability

    if not mapped:
        return {}
    by_position = {str(p["id"]): bid for bid, p in mapped.items()}
    docs = session[maintainability.COLLECTION].find(
        {"owner_id": {"$in": list(owners)}, "inputs.product_id": {"$in": sorted(by_position)}},
        {"name": 1, "inputs.product_id": 1, "results.mct_hours": 1, "created_at": 1}).sort("created_at", -1)
    out: dict = {}
    for d in docs:
        pid = str((d.get("inputs") or {}).get("product_id") or "")
        bid = by_position.get(pid)
        hours = (d.get("results") or {}).get("mct_hours")
        if bid and bid not in out and isinstance(hours, (int, float)) and hours > 0:
            out[bid] = {"hours": float(hours), "name": d.get("name") or "", "position": mapped[bid].get("name")}
    return out


def plan_reader(m, mapped: dict, unit: str):
    """The repairable graph with each tree-linked block's planned work read from its position's
    tasks (as the repairable Calculator reads it), or None where no block stands for a position."""
    from backend.maintenance import rbd_tree_plan

    if m is None or not mapped:
        return None

    def read(rgraph: dict) -> dict:
        can = rbd_tree_plan.supports()
        rows = {bid: rbd_tree_plan.position_plan(m, p, unit, can) for bid, p in mapped.items()}
        rows = {k: v for k, v in rows.items() if v.get("plan")}
        return rbd_tree_plan.apply(rgraph, {"blocks": rows, "supports": can}) if rows else rgraph

    return read


def availability_payload(session, ctx: Optional[AccessCtx], graph: dict, rbd, owners, *, repairs=None,
                         period=None, planned: bool = True) -> dict:
    """The answer (REST and MCP alike). Raises AnalysisError / RepairTimeError for bad input."""
    require_blocks(graph)
    graph, _ = rbds_service.bind_covariates(session, owners, graph)
    resolve_subsystem, _ = rbds_service.resolvers(session, owners)

    def resolve_model(model_id: str):
        return models_service.get_live_model(session, model_id, owners)

    typed = rra.parse_typed(repairs)
    m, mapped = tree_context(ctx, rbd, graph)
    rows = rra.repair_rows(graph, resolve_model, typed=typed, recorded=recorded_repairs(session, rbd, graph, owners),
                           predictions=prediction_repairs(session, mapped, owners))
    for row in rows:
        p = mapped.get(row["id"])
        if p is not None:
            row["position"] = {"id": p["id"], "name": p.get("name") or ""}
    if period is not None:
        try:
            period = float(period)
        except (TypeError, ValueError):
            raise AnalysisError("The period must be a number, in the diagram's time unit.") from None
    return rra.analyse(graph, rows, resolve_model, period=period, resolve_subsystem=resolve_subsystem,
                       plan_graph=plan_reader(m, mapped, graph.get("unit") or "") if planned else None)


@router.post("/rbds/repair-availability")
def repair_availability(
    graph: dict = Body(...),
    rbd_id: str | None = Body(default=None),
    repairs: dict | None = Body(default=None),
    period: float | None = Body(default=None),
    planned: bool = Body(default=True),
    session=Depends(get_session),
    ctx: AccessCtx = Depends(get_access),
) -> JSONResponse:
    """The availability of a block diagram (non-repairable included) with every block repaired
    after it fails: in the long run and over ``period`` (the diagram's unit; default a mission's
    length, else a year), with which blocks drive the downtime. Each block's mean time to repair
    comes from ``repairs`` ({block id: time}, in hours where the diagram's clock is a time), its
    own repair model, the diagram's outage history, or its position's maintainability prediction,
    and the answer says which; a block with none is listed and nothing is assumed. ``planned``
    (default true) adds the achieved figure with the planned work of the positions' tasks."""
    graph = rbd_live_models.refresh(session, graph, ctx.read_owners)  # linked blocks on their model's fit
    owners = ctx.read_owners
    rbd = None
    if rbd_id:
        rbd, _ = access_service.fetch_readable(session, "rbds", Rbd, rbd_id, ctx)
        owners = rbds_service.graph_owners(ctx.read_owners, rbd, graph)
    try:
        payload = availability_payload(session, ctx, graph, rbd, owners, repairs=repairs, period=period,
                                       planned=planned)
    except (AnalysisError, rra.RepairTimeError) as exc:
        return JSONResponse(status_code=422, content={"detail": client_message(exc)})
    except Exception:  # pragma: no cover - defensive
        logger.exception("Availability with repairs failed")
        return JSONResponse(status_code=500, content={
            "detail": "Couldn't work out the availability. The error has been logged."})
    return JSONResponse(content=payload)
