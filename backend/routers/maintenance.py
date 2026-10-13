"""Reliafy Maintenance API: positions, items, RCM tasks and work orders.

Local only for now: every route answers 404 unless ``MAINTENANCE_ENABLED``.
Data belongs to the active workspace (personal, or a team).
"""

from __future__ import annotations

import threading

from fastapi import APIRouter, Body, Depends, HTTPException
from fastapi.responses import JSONResponse

from backend import config
from backend.db import get_session
from backend.maintenance.service import PROJECTORS, Invalid, Maintenance, NotFound, summary
from backend.maintenance.store import GraphStore
from backend.schema import RcmStudy
from backend.services import access as access_service
from backend.services.access import AccessCtx, get_access

router = APIRouter(prefix="/api/maintenance")

_store: GraphStore | None = None
_store_lock = threading.Lock()


def get_store() -> GraphStore:
    global _store
    with _store_lock:
        if _store is None:
            _store = GraphStore(config.MAINTENANCE_DB_PATH, PROJECTORS)
        return _store


def maintenance(ctx: AccessCtx = Depends(get_access)) -> Maintenance:
    if not config.MAINTENANCE_ENABLED:
        raise HTTPException(status_code=404, detail="Not found.")
    return Maintenance(get_store(), ctx.write_owner, ctx.uid)


def _run(fn, *args, **kwargs) -> JSONResponse:
    try:
        return JSONResponse(content=fn(*args, **kwargs))
    except NotFound:
        return JSONResponse(status_code=404, content={"detail": "Not found."})
    except Invalid as err:
        return JSONResponse(status_code=422, content={"detail": str(err)})


def _study(session, ctx: AccessCtx, study_id: str) -> RcmStudy:
    study, _ = access_service.fetch_readable(session, "rcm_studies", RcmStudy, study_id, ctx)
    if study is None or study.id in ctx.hidden:
        raise HTTPException(status_code=404, detail="Study not found.")
    return study


# ---- overview ----------------------------------------------------------------------

@router.get("/overview")
def overview(m: Maintenance = Depends(maintenance)) -> JSONResponse:
    return _run(lambda: {
        "summary": summary(m), "tree": m.tree(), "due": m.due_tasks(30),
        "open_work_orders": m.work_orders("open"),
    })


@router.get("/events")
def events(limit: int = 100, m: Maintenance = Depends(maintenance)) -> JSONResponse:
    return _run(lambda: {"events": m.s.events(m.org, max(1, min(limit, 500)))})


# ---- positions -----------------------------------------------------------------------

@router.post("/positions")
def create_position(body: dict = Body(...), m: Maintenance = Depends(maintenance)) -> JSONResponse:
    return _run(m.create_position, body.get("name"), body.get("tag", ""), body.get("parent_id"),
                body.get("position_class", ""), body.get("description", ""))


@router.get("/positions/{position_id}")
def get_position(position_id: str, m: Maintenance = Depends(maintenance)) -> JSONResponse:
    return _run(m.position, position_id)


@router.patch("/positions/{position_id}")
def update_position(position_id: str, body: dict = Body(...),
                    m: Maintenance = Depends(maintenance)) -> JSONResponse:
    def go():
        m.update_position(position_id, **{k: body[k] for k in
                                          ("name", "tag", "position_class", "description", "parent_id") if k in body})
        return m.position(position_id)
    return _run(go)


@router.post("/positions/{position_id}/fit")
def fit(position_id: str, body: dict = Body(...), m: Maintenance = Depends(maintenance)) -> JSONResponse:
    return _run(m.fit, position_id, body.get("item_id"), body.get("new_item"), body.get("on"))


@router.post("/positions/{position_id}/remove")
def remove(position_id: str, body: dict = Body(default={}), m: Maintenance = Depends(maintenance)) -> JSONResponse:
    return _run(m.remove, position_id, body.get("on"), body.get("reason", "planned"), body.get("failure_mode_id"))


@router.post("/positions/{position_id}/apply-rcm")
def apply_rcm(position_id: str, study_id: str = Body(..., embed=True), session=Depends(get_session),
              ctx: AccessCtx = Depends(get_access), m: Maintenance = Depends(maintenance)) -> JSONResponse:
    study = _study(session, ctx, study_id)
    return _run(lambda: {**m.apply_rcm(position_id, study), "position": m.position(position_id)})


@router.post("/from-rcm")
def from_rcm(body: dict = Body(...), session=Depends(get_session), ctx: AccessCtx = Depends(get_access),
             m: Maintenance = Depends(maintenance)) -> JSONResponse:
    study = _study(session, ctx, str(body.get("study_id") or ""))
    return _run(m.position_from_rcm, study, body.get("parent_id"))


@router.patch("/tasks/{task_id}")
def update_task(task_id: str, body: dict = Body(...), m: Maintenance = Depends(maintenance)) -> JSONResponse:
    return _run(m.set_last_done, task_id, body.get("last_done"))


# ---- items and locations ---------------------------------------------------------------

@router.get("/items")
def list_items(m: Maintenance = Depends(maintenance)) -> JSONResponse:
    return _run(lambda: {"items": m.items()})


@router.post("/items")
def create_item(body: dict = Body(...), m: Maintenance = Depends(maintenance)) -> JSONResponse:
    return _run(lambda: m.item(m.create_item(body.get("name"), body.get("serial", ""), body.get("part_number", ""),
                                             body.get("manufacturer", ""), body.get("notes", ""))["id"]))


@router.post("/items/{item_id}/place")
def place_item(item_id: str, body: dict = Body(...), m: Maintenance = Depends(maintenance)) -> JSONResponse:
    return _run(m.place_item, item_id, body.get("location_id"), body.get("on"))


@router.get("/locations")
def list_locations(m: Maintenance = Depends(maintenance)) -> JSONResponse:
    return _run(lambda: {"locations": m.locations()})


@router.post("/locations")
def create_location(body: dict = Body(...), m: Maintenance = Depends(maintenance)) -> JSONResponse:
    return _run(m.create_location, body.get("name"), body.get("parent_id"), body.get("description", ""))


# ---- work orders -------------------------------------------------------------------------

@router.get("/work-orders")
def list_work_orders(status: str | None = None, m: Maintenance = Depends(maintenance)) -> JSONResponse:
    return _run(lambda: {"work_orders": m.work_orders(status)})


@router.post("/work-orders")
def open_work_order(body: dict = Body(...), m: Maintenance = Depends(maintenance)) -> JSONResponse:
    return _run(m.open_work_order, body.get("position_id"), body.get("title"), body.get("type", "corrective"),
                body.get("task_id"), body.get("due"), body.get("notes", ""))


@router.post("/work-orders/generate")
def generate_work_orders(horizon_days: int = Body(30, embed=True),
                         m: Maintenance = Depends(maintenance)) -> JSONResponse:
    return _run(lambda: {"work_orders": m.generate_work_orders(max(0, min(horizon_days, 366)))})


@router.get("/work-orders/{work_order_id}")
def get_work_order(work_order_id: str, m: Maintenance = Depends(maintenance)) -> JSONResponse:
    return _run(m.work_order, work_order_id)


@router.post("/work-orders/{work_order_id}/close")
def close_work_order(work_order_id: str, body: dict = Body(...),
                     m: Maintenance = Depends(maintenance)) -> JSONResponse:
    return _run(m.close_work_order, work_order_id, body.get("actions") or [], body.get("on"), body.get("notes", ""))
