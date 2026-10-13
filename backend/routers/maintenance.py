"""Reliafy Maintenance API: positions, items, RCM tasks and work orders.

In development: every route answers 404 unless ``MAINTENANCE_ENABLED`` and the
caller is allowed (backend/maintenance/access.py), except ``/access``, which
says whether they are. Data belongs to the active workspace (personal, or a
team).
"""

from __future__ import annotations

import threading

import os

from fastapi import APIRouter, Body, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, Response
from starlette.concurrency import run_in_threadpool

from backend import config
from backend.db import get_db, get_session, is_simulated
from backend.maintenance.access import allowed
from backend.maintenance import photos as photos_mod
from backend.maintenance.service import PROJECTORS, Invalid, LimitReached, Maintenance, NotFound, summary
from backend.maintenance.store import new_id
from backend.maintenance.store import GraphStore, MongoEventLog
from backend.schema import RcmStudy
from backend.services import access as access_service
from backend.services.access import AccessCtx, get_access

router = APIRouter(prefix="/api/maintenance")
# The phone upload page and its posts: the link's token is the credential.
public_router = APIRouter()

_store: GraphStore | None = None
_photo_store = None
_store_lock = threading.Lock()


def _use_mongo() -> bool:
    mode = config.MAINTENANCE_STORE
    return mode == "mongo" or (mode == "auto" and not is_simulated())


def get_photo_store():
    global _photo_store
    with _store_lock:
        if _photo_store is None:
            _photo_store = (photos_mod.MongoPhotoStore(get_db()) if _use_mongo() else
                            photos_mod.FilePhotoStore(os.path.join(
                                os.path.dirname(os.path.abspath(config.MAINTENANCE_DB_PATH)), "photos")))
        return _photo_store


def photo_links() -> photos_mod.PhotoLinks:
    return photos_mod.PhotoLinks(get_db())


def ingest_photo(m: Maintenance, target_id: str, raw: bytes, caption: str = "", via: str = "app") -> dict:
    """Clean, store and record one photo. Returns the photo and any location
    it carried (offered, never stored on the photo). Blocks: call it off the
    event loop."""
    m.photo_target(target_id)
    m.check_limits()
    m.check_photo_quota()
    cleaned = photos_mod.clean(raw)
    photo_id = new_id()
    store = get_photo_store()
    store.put(photo_id, "full", cleaned["full"])
    store.put(photo_id, "thumb", cleaned["thumb"])
    try:
        photo = m.add_photo(photo_id, target_id, cleaned, caption, via)
    except Exception:
        store.delete(photo_id)
        raise
    return {"photo": photo, "location_offer": cleaned["gps"]}


def remove_photo(m: Maintenance, photo_id: str) -> dict:
    """Remove a photo from what it shows, and delete its stored bytes (the
    history keeps that it was there)."""
    m.remove_photo(photo_id)
    get_photo_store().delete(photo_id)
    return {"removed": photo_id}


def served_photo(m: Maintenance, photo_id: str, size: str) -> bytes | None:
    """A photo's bytes, if it's in this workspace and hasn't been removed."""
    try:
        if m.photo(photo_id).get("removed"):
            return None
    except NotFound:
        return None
    return get_photo_store().get(photo_id, "full" if size == "full" else "thumb")


async def _read_body(request: Request) -> bytes:
    declared = request.headers.get("content-length")
    if declared and declared.isdigit() and int(declared) > photos_mod.MAX_UPLOAD_BYTES:
        raise photos_mod.BadPhoto("The photo is over 20 MB.")
    body = bytearray()
    async for chunk in request.stream():
        body.extend(chunk)
        if len(body) > photos_mod.MAX_UPLOAD_BYTES:
            raise photos_mod.BadPhoto("The photo is over 20 MB.")
    return bytes(body)


def get_store() -> GraphStore:
    """The graph, caught up with the log (other processes may have written)."""
    global _store
    with _store_lock:
        if _store is None:
            from backend.maintenance.series import MongoSeries
            from backend.maintenance.service import PROJECTION_VERSION

            if _use_mongo():
                _store = GraphStore(":memory:", PROJECTORS, MongoEventLog(get_db()), series=MongoSeries(get_db()),
                                    version=PROJECTION_VERSION)
            else:
                _store = GraphStore(config.MAINTENANCE_DB_PATH, PROJECTORS, version=PROJECTION_VERSION)
        store = _store
    store.sync()
    return store


def maintenance(ctx: AccessCtx = Depends(get_access)) -> Maintenance:
    if not allowed(ctx.user):
        raise HTTPException(status_code=404, detail="Not found.")
    return Maintenance(get_store(), ctx.write_owner, ctx.uid)


class WriteDenied(Exception):
    """A write refused for the workspace (frozen team, view-only member):
    answered with the same body as the rest of the app's write refusals."""

    def __init__(self, status: int, payload: dict):
        super().__init__(payload.get("detail", ""))
        self.status, self.payload = status, payload


async def write_denied_handler(request: Request, exc: WriteDenied) -> JSONResponse:
    return JSONResponse(status_code=exc.status, content=exc.payload)


def maintenance_write(ctx: AccessCtx = Depends(get_access)) -> Maintenance:
    """For a route that changes the workspace: as :func:`maintenance`, and
    refused like any other write in a frozen team or to a team member who may
    only view."""
    m = maintenance(ctx)
    denied = access_service.workspace_write_denial(ctx)
    if denied is not None:
        raise WriteDenied(*denied)
    return m


@router.get("/access")
def access(ctx: AccessCtx = Depends(get_access)) -> dict:
    """Whether the caller may use Reliafy Maintenance (the app shows it if so)."""
    return {"allowed": allowed(ctx.user)}


def _run(fn, *args, **kwargs) -> JSONResponse:
    try:
        return JSONResponse(content=fn(*args, **kwargs))
    except NotFound:
        return JSONResponse(status_code=404, content={"detail": "Not found."})
    except LimitReached as err:
        return JSONResponse(status_code=err.status, content={"detail": str(err)})
    except photos_mod.Busy as err:
        return JSONResponse(status_code=503, content={"detail": str(err)}, headers={"Retry-After": "30"})
    except (Invalid, photos_mod.BadPhoto) as err:
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
        "open_work_orders": m.work_orders("open"), "proposals": m.proposals("pending"),
    })


@router.get("/events")
def events(limit: int = 100, m: Maintenance = Depends(maintenance)) -> JSONResponse:
    return _run(lambda: {"events": m.s.events(m.org, max(1, min(limit, 500)))})


# ---- positions -----------------------------------------------------------------------

@router.post("/positions")
def create_position(body: dict = Body(...), m: Maintenance = Depends(maintenance_write)) -> JSONResponse:
    return _run(m.create_position, body.get("name"), body.get("tag", ""), body.get("parent_id"),
                body.get("position_class", ""), body.get("description", ""))


@router.get("/positions/{position_id}")
def get_position(position_id: str, m: Maintenance = Depends(maintenance)) -> JSONResponse:
    return _run(m.position, position_id)


@router.patch("/positions/{position_id}")
def update_position(position_id: str, body: dict = Body(...),
                    m: Maintenance = Depends(maintenance_write)) -> JSONResponse:
    def go():
        m.update_position(position_id, **{k: body[k] for k in
                                          ("name", "tag", "position_class", "description", "parent_id") if k in body})
        return m.position(position_id)
    return _run(go)


@router.post("/positions/{position_id}/fit")
def fit(position_id: str, body: dict = Body(...), m: Maintenance = Depends(maintenance_write)) -> JSONResponse:
    return _run(m.fit, position_id, body.get("item_id"), body.get("new_item"), body.get("on"))


@router.post("/positions/{position_id}/remove")
def remove(position_id: str, body: dict = Body(default={}), m: Maintenance = Depends(maintenance_write)) -> JSONResponse:
    """A failure names its mode by failure_mode_id, or in words (failure_mode_text)."""
    return _run(m.remove, position_id, body.get("on"), body.get("reason"), body.get("failure_mode_id"),
                body.get("failure_mode_text"))


@router.post("/positions/{position_id}/past-fitments")
def add_past_fitment(position_id: str, body: dict = Body(...), m: Maintenance = Depends(maintenance_write)) -> JSONResponse:
    """A past fitment into the position's history: start, end, reason, an item (item_id or new_item)."""
    return _run(m.add_past_fitment, position_id, body.get("start"), body.get("end"), body.get("reason"),
                body.get("item_id"), body.get("new_item"), body.get("failure_mode_id"), body.get("failure_mode_text"),
                body.get("from_precision"), body.get("to_precision"), body.get("note", ""))


@router.post("/positions/{position_id}/tasks")
def create_task(position_id: str, body: dict = Body(...), m: Maintenance = Depends(maintenance_write)) -> JSONResponse:
    """A scheduled task added by hand (not from an RCM study)."""
    return _run(m.create_task, position_id, body.get("name"), body.get("interval"), body.get("unit") or "months",
                body.get("outcome"), body.get("also_interval"), body.get("also_unit"), body.get("point_id"),
                body.get("instructions", ""), body.get("checklist"), body.get("source") or "manual",
                body.get("reference", ""), body.get("failure_mode_id"), body.get("last_done"))


@router.post("/positions/{position_id}/failure-modes")
def add_failure_mode(position_id: str, body: dict = Body(...), m: Maintenance = Depends(maintenance_write)) -> JSONResponse:
    return _run(m.add_failure_mode, position_id, body.get("text"), body.get("function", ""), body.get("failure", ""),
                body.get("consequence", ""))


@router.patch("/failure-modes/{mode_id}")
def update_failure_mode(mode_id: str, body: dict = Body(...), m: Maintenance = Depends(maintenance_write)) -> JSONResponse:
    return _run(m.update_failure_mode, mode_id, **{k: body[k] for k in ("text", "function", "failure", "consequence")
                                                   if k in body})


@router.post("/failure-modes/{mode_id}/merge")
def merge_failure_mode(mode_id: str, body: dict = Body(...), m: Maintenance = Depends(maintenance_write)) -> JSONResponse:
    """Fold this mode into another on the same position (into_id)."""
    return _run(m.merge_failure_mode, mode_id, body.get("into_id"))


@router.post("/positions/{position_id}/apply-rcm")
def apply_rcm(position_id: str, study_id: str = Body(..., embed=True), session=Depends(get_session),
              ctx: AccessCtx = Depends(get_access), m: Maintenance = Depends(maintenance_write)) -> JSONResponse:
    study = _study(session, ctx, study_id)
    return _run(lambda: {**m.apply_rcm(position_id, study), "position": m.position(position_id)})


@router.post("/from-rcm")
def from_rcm(body: dict = Body(...), session=Depends(get_session), ctx: AccessCtx = Depends(get_access),
             m: Maintenance = Depends(maintenance_write)) -> JSONResponse:
    study = _study(session, ctx, str(body.get("study_id") or ""))
    return _run(m.position_from_rcm, study, body.get("parent_id"))


@router.patch("/tasks/{task_id}")
def update_task(task_id: str, body: dict = Body(...), m: Maintenance = Depends(maintenance_write)) -> JSONResponse:
    """Set when it was last done, and/or change its name, interval or unit."""
    def go():
        view = None
        if body.get("last_done"):
            view = m.set_last_done(task_id, body["last_done"])
        if any(k in body for k in ("name", "interval", "unit", "also_interval", "also_unit", "point_id",
                                   "instructions", "checklist", "failure_mode_id", "source", "reference",
                                   "outcome")):
            view = m.update_task(task_id, body.get("name"), body.get("interval"), body.get("unit"),
                                 body.get("also_interval"), body.get("also_unit"), body.get("point_id"),
                                 body.get("instructions"), body.get("checklist"),
                                 ("" if body["failure_mode_id"] is None else body["failure_mode_id"])
                                 if "failure_mode_id" in body else None,
                                 body.get("source"), body.get("reference"),
                                 body["outcome"] if "outcome" in body else ...)
        if view is None:
            raise Invalid("Nothing to change.")
        return view
    return _run(go)


@router.post("/tasks/{task_id}/retire")
def retire_task(task_id: str, body: dict = Body(default={}), m: Maintenance = Depends(maintenance_write)) -> JSONResponse:
    return _run(lambda: (m.retire_task(task_id, body.get("reason", "")), {"retired": task_id})[1])


@router.post("/positions/{position_id}/retire")
def retire_position(position_id: str, body: dict = Body(default={}),
                    m: Maintenance = Depends(maintenance_write)) -> JSONResponse:
    return _run(lambda: (m.retire_position(position_id, body.get("reason", "")), {"retired": position_id})[1])


@router.post("/fitments/{fitment_id}/void")
def void_fitment(fitment_id: str, body: dict = Body(default={}), m: Maintenance = Depends(maintenance_write)) -> JSONResponse:
    return _run(lambda: (m.void_fitment(fitment_id, body.get("reason", "")), {"voided": fitment_id})[1])


@router.patch("/fitments/{fitment_id}")
def correct_fitment(fitment_id: str, body: dict = Body(...), m: Maintenance = Depends(maintenance_write)) -> JSONResponse:
    return _run(m.correct_fitment, fitment_id, body.get("start"), body.get("end"))


@router.get("/classes/one")
def get_class(position_class: str, m: Maintenance = Depends(maintenance)) -> JSONResponse:
    return _run(m.position_class, position_class)


@router.put("/classes/costs")
def set_class_costs(body: dict = Body(...), m: Maintenance = Depends(maintenance_write)) -> JSONResponse:
    return _run(m.set_class_costs, body.get("position_class"), body.get("planned_cost"), body.get("failure_cost"),
                body.get("availability_target"))


@router.post("/classes/fit")
def fit_class_model(body: dict = Body(...), session=Depends(get_session),
                    m: Maintenance = Depends(maintenance_write)) -> JSONResponse:
    from backend import fitting
    from backend.maintenance import loop

    try:
        return _run(loop.fit_class_model, m, session, str(body.get("position_class") or ""),
                    body.get("distribution") or "weibull")
    except fitting.FitError as err:
        return JSONResponse(status_code=422, content={"detail": f"The fit didn't work: {err}"})


@router.get("/classes/economics")
def class_economics(position_class: str, interval: float | None = None, unit: str = "months",
                    horizon_years: float = 10, discount_rate: float = 0.07,
                    m: Maintenance = Depends(maintenance)) -> JSONResponse:
    from backend.maintenance import loop

    return _run(loop.economics, m, position_class, interval, unit, horizon_years, discount_rate)


@router.get("/proposals")
def list_proposals(status: str = "pending", m: Maintenance = Depends(maintenance)) -> JSONResponse:
    return _run(lambda: {"proposals": m.proposals(None if status == "all" else status)})


@router.post("/proposals/{proposal_id}/{decision}")
def decide_proposal(proposal_id: str, decision: str, body: dict = Body(default={}),
                    m: Maintenance = Depends(maintenance_write)) -> JSONResponse:
    if decision not in ("accept", "reject"):
        return JSONResponse(status_code=404, content={"detail": "Not found."})
    return _run(m.decide_proposal, proposal_id, decision == "accept", body.get("note", ""))


@router.get("/tasks/{task_id}/explain")
def explain_task(task_id: str, m: Maintenance = Depends(maintenance)) -> JSONResponse:
    return _run(m.explain_task, task_id)


@router.post("/import")
async def import_sheet(file: UploadFile = File(...), dry_run: bool = Form(False),
                       m: Maintenance = Depends(maintenance_write)) -> JSONResponse:
    """Positions, items and their history from a CSV or Excel sheet (see importer.py)."""
    from starlette.concurrency import run_in_threadpool

    from backend.maintenance import importer

    data = await file.read(10 * 1024 * 1024 + 1)
    if len(data) > 10 * 1024 * 1024:
        return JSONResponse(status_code=413, content={"detail": "The file is over 10 MB."})
    try:
        rows = await run_in_threadpool(importer.rows_from_file, data, file.filename or "")
    except Invalid as err:
        return JSONResponse(status_code=422, content={"detail": str(err)})
    except Exception:  # noqa: BLE001 - an unreadable file
        return JSONResponse(status_code=422, content={"detail": "That file couldn't be read as CSV or Excel."})
    return await run_in_threadpool(_run, importer.run, m, rows, dry_run)


@router.get("/classes")
def position_classes(m: Maintenance = Depends(maintenance)) -> JSONResponse:
    return _run(lambda: {"classes": m.position_classes()})


@router.get("/classes/life-data")
def class_life_data(position_class: str, m: Maintenance = Depends(maintenance)) -> JSONResponse:
    return _run(m.class_life_data, position_class)


@router.post("/positions/{position_id}/points")
def add_point(position_id: str, body: dict = Body(...), m: Maintenance = Depends(maintenance_write)) -> JSONResponse:
    return _run(m.add_point, position_id, body.get("name", ""), body.get("kind") or "condition", body.get("unit", ""),
                body.get("source") or "manual", body.get("tag", ""), body.get("alarm_above"), body.get("alarm_below"))


@router.get("/points/{point_id}")
def get_point(point_id: str, m: Maintenance = Depends(maintenance)) -> JSONResponse:
    return _run(m.point, point_id)


@router.patch("/points/{point_id}")
def update_point(point_id: str, body: dict = Body(...), m: Maintenance = Depends(maintenance_write)) -> JSONResponse:
    return _run(m.update_point, point_id, **{k: body[k] for k in ("name", "alarm_above", "alarm_below", "tag")
                                             if k in body})


@router.post("/points/{point_id}/readings")
def record_reading(point_id: str, body: dict = Body(...), m: Maintenance = Depends(maintenance_write)) -> JSONResponse:
    return _run(m.record_reading, point_id, body.get("value"), body.get("on"), body.get("note", ""))


@router.post("/readings/{reading_id}/void")
def void_reading(reading_id: str, m: Maintenance = Depends(maintenance_write)) -> JSONResponse:
    return _run(lambda: (m.void_reading(reading_id), {"voided": reading_id})[1])


@router.get("/settings")
def get_settings(session=Depends(get_session), ctx: AccessCtx = Depends(get_access),
                 m: Maintenance = Depends(maintenance)) -> dict:
    doc = session.users.find_one({"_id": ctx.uid}) or {}
    return {"digest": not doc.get("maintenance_digest_off")}


@router.patch("/settings")
def set_settings(body: dict = Body(...), session=Depends(get_session), ctx: AccessCtx = Depends(get_access),
                 m: Maintenance = Depends(maintenance)) -> dict:
    if "digest" in body:
        session.users.update_one({"_id": ctx.uid}, {"$set": {"maintenance_digest_off": not bool(body["digest"])}})
    return get_settings(session, ctx, m)


@router.post("/interfaces")
def connect(body: dict = Body(...), m: Maintenance = Depends(maintenance_write)) -> JSONResponse:
    return _run(m.connect, body.get("from_id"), body.get("to_id"), body.get("kind") or "flow",
                body.get("medium", ""), body.get("name", ""), body.get("rating", ""), body.get("realised_by"))


@router.post("/interfaces/{interface_id}/remove")
def disconnect(interface_id: str, m: Maintenance = Depends(maintenance_write)) -> JSONResponse:
    return _run(lambda: (m.disconnect(interface_id), {"removed": interface_id})[1])


@router.post("/groups")
def create_group(body: dict = Body(...), m: Maintenance = Depends(maintenance_write)) -> JSONResponse:
    return _run(m.create_group, body.get("name", ""), body.get("member_ids") or [], body.get("k", 1),
                body.get("mode") or "active", body.get("standby") or "cold")


@router.patch("/groups/{group_id}")
def update_group(group_id: str, body: dict = Body(...), m: Maintenance = Depends(maintenance_write)) -> JSONResponse:
    return _run(m.update_group, group_id, body.get("name"), body.get("k"), body.get("mode"), body.get("standby"),
                body.get("add") or [], body.get("remove") or [])


@router.post("/groups/{group_id}/duty")
def set_duty(group_id: str, body: dict = Body(...), m: Maintenance = Depends(maintenance_write)) -> JSONResponse:
    return _run(m.set_duty, group_id, body.get("position_id"))


@router.post("/groups/{group_id}/retire")
def retire_group(group_id: str, m: Maintenance = Depends(maintenance_write)) -> JSONResponse:
    return _run(lambda: (m.retire_group(group_id), {"retired": group_id})[1])


@router.get("/positions/{position_id}/impact")
def impact(position_id: str, m: Maintenance = Depends(maintenance)) -> JSONResponse:
    return _run(m.impact, position_id)


@router.post("/positions/{position_id}/rbd")
def generate_rbd(position_id: str, session=Depends(get_session), m: Maintenance = Depends(maintenance_write)) -> JSONResponse:
    from backend.maintenance import rbd_derive

    return _run(rbd_derive.save, m, session, position_id)


# ---- items and locations ---------------------------------------------------------------

@router.get("/items")
def list_items(m: Maintenance = Depends(maintenance)) -> JSONResponse:
    return _run(lambda: {"items": m.items()})


@router.post("/items")
def create_item(body: dict = Body(...), m: Maintenance = Depends(maintenance_write)) -> JSONResponse:
    return _run(lambda: m.item(m.create_item(body.get("name"), body.get("serial", ""), body.get("part_number", ""),
                                             body.get("manufacturer", ""), body.get("notes", ""))["id"]))


@router.get("/items/{item_id}")
def get_item(item_id: str, m: Maintenance = Depends(maintenance)) -> JSONResponse:
    return _run(m.item, item_id)


@router.patch("/items/{item_id}")
def update_item(item_id: str, body: dict = Body(...), m: Maintenance = Depends(maintenance_write)) -> JSONResponse:
    return _run(m.update_item, item_id, body.get("nameplate"),
                **{k: body[k] for k in Maintenance.ITEM_FIELDS if k in body})


@router.post("/items/{item_id}/move")
def move_item(item_id: str, body: dict = Body(...), m: Maintenance = Depends(maintenance_write)) -> JSONResponse:
    return _run(m.move_item, item_id, body.get("position_id"), body.get("on"))


@router.post("/items/{item_id}/place")
def place_item(item_id: str, body: dict = Body(...), m: Maintenance = Depends(maintenance_write)) -> JSONResponse:
    return _run(m.place_item, item_id, body.get("location_id"), body.get("on"))


@router.get("/locations")
def list_locations(m: Maintenance = Depends(maintenance)) -> JSONResponse:
    return _run(lambda: {"locations": m.locations(), "tree": m.location_tree()})


@router.get("/locations/{location_id}")
def get_location(location_id: str, m: Maintenance = Depends(maintenance)) -> JSONResponse:
    return _run(m.location, location_id)


@router.patch("/locations/{location_id}")
def update_location(location_id: str, body: dict = Body(...), m: Maintenance = Depends(maintenance_write)) -> JSONResponse:
    kwargs = {k: body[k] for k in ("name", "description", "parent_id") if k in body}
    return _run(m.update_location, location_id, **kwargs)


@router.post("/locations")
def create_location(body: dict = Body(...), m: Maintenance = Depends(maintenance_write)) -> JSONResponse:
    return _run(m.create_location, body.get("name"), body.get("parent_id"), body.get("description", ""))


# ---- work orders -------------------------------------------------------------------------

@router.get("/work-orders")
def list_work_orders(status: str | None = None, m: Maintenance = Depends(maintenance)) -> JSONResponse:
    return _run(lambda: {"work_orders": m.work_orders(status)})


@router.post("/work-orders")
def open_work_order(body: dict = Body(...), m: Maintenance = Depends(maintenance_write)) -> JSONResponse:
    return _run(m.open_work_order, body.get("position_id"), body.get("title"), body.get("type", "corrective"),
                body.get("task_id"), body.get("due"), body.get("notes", ""))


@router.post("/work-orders/generate")
def generate_work_orders(horizon_days: int = Body(30, embed=True),
                         m: Maintenance = Depends(maintenance_write)) -> JSONResponse:
    return _run(lambda: {"work_orders": m.generate_work_orders(max(0, min(horizon_days, 366)))})


@router.patch("/work-orders/{work_order_id}")
def update_work_order(work_order_id: str, body: dict = Body(...),
                      m: Maintenance = Depends(maintenance_write)) -> JSONResponse:
    return _run(m.update_work_order, work_order_id, body.get("title"), body.get("due") if "due" in body else None,
                body.get("notes"), body.get("type"), body.get("assignee"),
                body.get("planned_for") if "planned_for" in body else None)


@router.post("/work-orders/{work_order_id}/status")
def set_work_status(work_order_id: str, body: dict = Body(...), m: Maintenance = Depends(maintenance_write)) -> JSONResponse:
    return _run(m.set_work_status, work_order_id, body.get("status"), body.get("note", ""))


@router.post("/work-orders/{work_order_id}/labour")
def log_labour(work_order_id: str, body: dict = Body(...), m: Maintenance = Depends(maintenance_write)) -> JSONResponse:
    return _run(m.log_labour, work_order_id, body.get("hours"), body.get("who", ""), body.get("rate"),
                body.get("on"), body.get("note", ""))


@router.post("/work-orders/{work_order_id}/parts")
def add_part_used(work_order_id: str, body: dict = Body(...), m: Maintenance = Depends(maintenance_write)) -> JSONResponse:
    return _run(m.add_part_used, work_order_id, body.get("part"), body.get("quantity", 1), body.get("unit_cost"),
                body.get("part_number", ""), body.get("note", ""), body.get("part_id"), body.get("from_location_id"))


@router.get("/parts")
def list_parts(m: Maintenance = Depends(maintenance)) -> JSONResponse:
    return _run(lambda: {"parts": m.parts()})


@router.post("/parts")
def create_part(body: dict = Body(...), m: Maintenance = Depends(maintenance_write)) -> JSONResponse:
    return _run(m.create_part, body.get("part_number"), body.get("name"), body.get("manufacturer", ""),
                body.get("unit", "each"), body.get("unit_cost"), body.get("notes", ""))


@router.get("/parts/{part_id}")
def get_part(part_id: str, m: Maintenance = Depends(maintenance)) -> JSONResponse:
    return _run(m.part, part_id)


@router.patch("/parts/{part_id}")
def update_part(part_id: str, body: dict = Body(...), m: Maintenance = Depends(maintenance_write)) -> JSONResponse:
    return _run(m.update_part, part_id, **{k: body[k] for k in ("name", "manufacturer", "unit", "notes", "unit_cost")
                                           if k in body})


@router.post("/parts/{part_id}/stock")
def adjust_stock(part_id: str, body: dict = Body(...), m: Maintenance = Depends(maintenance_write)) -> JSONResponse:
    return _run(m.adjust_stock, part_id, body.get("location_id"), body.get("delta"), body.get("reason", ""),
                body.get("on"))


@router.post("/parts/{part_id}/reorder-point")
def set_reorder_point(part_id: str, body: dict = Body(...), m: Maintenance = Depends(maintenance_write)) -> JSONResponse:
    return _run(m.set_reorder_point, part_id, body.get("location_id"), body.get("reorder_point"))


@router.post("/parts/{part_id}/supersede")
def supersede_part(part_id: str, body: dict = Body(...), m: Maintenance = Depends(maintenance_write)) -> JSONResponse:
    return _run(m.supersede_part, part_id, body.get("by_part_id"))


@router.post("/parts/{part_id}/interchangeable")
def mark_interchangeable(part_id: str, body: dict = Body(...), m: Maintenance = Depends(maintenance_write)) -> JSONResponse:
    return _run(m.mark_interchangeable, part_id, body.get("other_part_id"))


@router.post("/work-orders/{work_order_id}/costs")
def add_cost(work_order_id: str, body: dict = Body(...), m: Maintenance = Depends(maintenance_write)) -> JSONResponse:
    return _run(m.add_cost, work_order_id, body.get("description"), body.get("amount"))


@router.post("/work-orders/{work_order_id}/checklist/{index}")
def check_item(work_order_id: str, index: int, body: dict = Body(default={}),
               m: Maintenance = Depends(maintenance_write)) -> JSONResponse:
    return _run(m.check_item, work_order_id, index, bool(body.get("done", True)))


@router.post("/work-entries/{entry_id}/remove")
def remove_entry(entry_id: str, m: Maintenance = Depends(maintenance_write)) -> JSONResponse:
    return _run(m.remove_entry, entry_id)


@router.post("/work-orders/{work_order_id}/cancel")
def cancel_work_order(work_order_id: str, body: dict = Body(default={}),
                      m: Maintenance = Depends(maintenance_write)) -> JSONResponse:
    return _run(m.cancel_work_order, work_order_id, body.get("reason", ""))


@router.get("/work-orders/{work_order_id}")
def get_work_order(work_order_id: str, m: Maintenance = Depends(maintenance)) -> JSONResponse:
    return _run(m.work_order, work_order_id)


@router.post("/work-orders/{work_order_id}/close")
def close_work_order(work_order_id: str, body: dict = Body(...),
                     m: Maintenance = Depends(maintenance_write)) -> JSONResponse:
    return _run(m.close_work_order, work_order_id, body.get("actions") or [], body.get("on"), body.get("notes", ""),
                body.get("readings") or [])


# ---- photos and coordinates ----------------------------------------------------------------

@router.post("/photos")
async def add_photo(request: Request, target_id: str, caption: str = "",
                    m: Maintenance = Depends(maintenance_write)) -> JSONResponse:
    """Add a photo (the request body is the image) to a position, location,
    item or work order."""
    try:
        raw = await _read_body(request)
    except photos_mod.BadPhoto as err:
        return JSONResponse(status_code=422, content={"detail": str(err)})
    # Decoding is CPU-bound: off the event loop (photos.clean limits how many at once).
    return await run_in_threadpool(_run, ingest_photo, m, target_id, raw, caption[:200], "app")


@router.get("/photos/{photo_id}")
def get_photo(photo_id: str, size: str = "thumb", m: Maintenance = Depends(maintenance)) -> Response:
    data = served_photo(m, photo_id, size)
    if data is None:
        return JSONResponse(status_code=404, content={"detail": "Not found."})
    return Response(content=data, media_type="image/jpeg", headers={"Cache-Control": "private, max-age=300"})


@router.delete("/photos/{photo_id}")
def delete_photo(photo_id: str, m: Maintenance = Depends(maintenance_write)) -> JSONResponse:
    return _run(remove_photo, m, photo_id)


@router.post("/coordinates")
def set_coordinates(body: dict = Body(...), m: Maintenance = Depends(maintenance_write)) -> JSONResponse:
    return _run(m.set_coordinates, body.get("node_id"), body.get("lat"), body.get("lon"),
                body.get("source") or "manual")


@router.post("/photo-links")
def create_photo_link(request: Request, body: dict = Body(...), m: Maintenance = Depends(maintenance_write)) -> JSONResponse:
    """A link for adding photos from a phone with no sign-in (see photos.py)."""
    def go():
        target = m.photo_target(str(body.get("target_id") or ""))
        return link_payload(request, m, target, str(body.get("caption") or "")[:200])
    return _run(go)


def link_payload(request_or_base, m: Maintenance, target: dict, caption: str = "") -> dict:
    m.check_limits()
    doc, token = photo_links().create(m.org, m.actor or m.org, target, caption)
    if isinstance(request_or_base, str):
        base = request_or_base
    else:
        base = config.PUBLIC_BASE_URL or str(request_or_base.base_url).rstrip("/")
    return {**photos_mod.PhotoLinks.public(doc), "url": f"{base}/photos/up/{doc['_id']}?t={token}",
            "max_photos": photos_mod.MAX_PER_LINK}


# ---- the phone upload page (public: the link's token is the credential) ---------------------

def _link_or_none(link_id: str, t: str) -> dict | None:
    """The link, if it exists and the token is its own. The id's form and the
    token are checked before the database is."""
    if not config.MAINTENANCE_ENABLED or not t or len(t) > 100 or not photos_mod.link_id_ok(link_id):
        return None
    return photo_links().get(link_id, token=t)


def _creator_may_write(doc: dict) -> bool:
    """Whether the person who made the link may still add to its workspace:
    still allowed Maintenance, and for a team, still a member who may edit in
    a team that isn't frozen."""
    from backend.services import billing as billing_service

    db = get_db()
    uid = doc["uid"]
    user = {**(db.users.find_one({"_id": uid}) or {}), "uid": uid}
    if not allowed(user):
        return False
    org = doc["org"]
    if org == uid:
        return True
    if not access_service.is_team_owner(org):
        return False
    team = next((t for t in access_service.user_teams(db, uid)
                 if access_service.team_principal(t["_id"]) == org), None)
    return (team is not None and not access_service.team_frozen(db, team, billing_service)
            and access_service.member_can_edit(db, user, billing_service))


def _open_link(link_id: str, t: str) -> tuple[dict | None, JSONResponse | None]:
    """The link for a post to it, or the response refusing it."""
    doc = _link_or_none(link_id, t)
    if doc is None:
        return None, JSONResponse(status_code=404, content={"detail": "This link isn't valid."})
    if photos_mod.PhotoLinks.expired(doc):
        return None, JSONResponse(status_code=410, content={"detail": "This link has expired. Ask for a new one."})
    if not _creator_may_write(doc):
        return None, JSONResponse(status_code=410, content={"detail": "This link can no longer add photos. "
                                                                         "Ask for a new one."})
    return doc, None


@public_router.get("/photos/up/{link_id}", include_in_schema=False)
def upload_page(link_id: str, t: str = "") -> HTMLResponse:
    from backend.maintenance.upload_page import render

    doc = _link_or_none(link_id, t)
    headers = {"Cache-Control": "no-store", "Referrer-Policy": "no-referrer", "X-Robots-Tag": "noindex"}
    if doc is None:
        return HTMLResponse(render(None, "This link isn't valid. Ask for a new one."), status_code=404, headers=headers)
    problem = photo_links().usable(doc)
    html, nonce = render(doc, problem, with_nonce=True)
    headers["Content-Security-Policy"] = (f"default-src 'none'; script-src 'nonce-{nonce}'; style-src 'unsafe-inline'; "
                                          "img-src blob:; connect-src 'self'; base-uri 'none'; form-action 'none'")
    return HTMLResponse(html, headers=headers)


def _reserve(link_id: str, t: str) -> tuple[dict | None, JSONResponse | None]:
    """Check the link and take one of its places for a photo (blocking: run it
    off the event loop)."""
    doc, refused = _open_link(link_id, t)
    if refused is not None:
        return None, refused
    links = photo_links()
    if not links.reserve(doc["_id"]):
        problem = links.usable(links.get(doc["_id"]) or doc) or "This link can't take another photo."
        return None, JSONResponse(status_code=410, content={"detail": problem})
    return doc, None


def _store_by_link(doc: dict, raw: bytes) -> JSONResponse:
    """Clean, store and record a photo sent through a link whose place is
    reserved; the place is given back if the photo isn't kept."""
    links = photo_links()
    try:
        m = Maintenance(get_store(), doc["org"], doc["uid"])
        result = ingest_photo(m, doc["target_id"], raw, doc.get("caption", ""), "link")
    except photos_mod.Busy as err:
        links.release(doc["_id"])
        return JSONResponse(status_code=503, content={"detail": str(err)}, headers={"Retry-After": "30"})
    except LimitReached as err:
        links.release(doc["_id"])
        return JSONResponse(status_code=err.status, content={"detail": str(err)})
    except (photos_mod.BadPhoto, Invalid) as err:
        links.release(doc["_id"])
        return JSONResponse(status_code=422, content={"detail": str(err)})
    except NotFound:
        links.release(doc["_id"])
        return JSONResponse(status_code=404, content={"detail": "What this link was for no longer exists."})
    except BaseException:
        links.release(doc["_id"])
        raise
    links.add_photo(doc["_id"], result["photo"]["id"], result["location_offer"])
    return JSONResponse(content={"photo_id": result["photo"]["id"], "location_offer": result["location_offer"],
                                 "target_name": doc["target_name"]})


@public_router.post("/photos/up/{link_id}", include_in_schema=False)
async def upload_by_link(link_id: str, request: Request, t: str = "") -> JSONResponse:
    if not config.MAINTENANCE_ENABLED or not t or not photos_mod.link_id_ok(link_id):
        return JSONResponse(status_code=404, content={"detail": "This link isn't valid."})
    # Database work and decoding block: both run off the event loop.
    doc, refused = await run_in_threadpool(_reserve, link_id, t)
    if refused is not None:
        return refused
    try:
        raw = await _read_body(request)
    except photos_mod.BadPhoto as err:
        await run_in_threadpool(lambda: photo_links().release(doc["_id"]))
        return JSONResponse(status_code=422, content={"detail": str(err)})
    except BaseException:
        await run_in_threadpool(lambda: photo_links().release(doc["_id"]))
        raise
    return await run_in_threadpool(_store_by_link, doc, raw)


@public_router.post("/photos/up/{link_id}/location", include_in_schema=False)
def answer_location(link_id: str, t: str = "", body: dict = Body(...)) -> JSONResponse:
    """The uploader's answer: save this photo's location as where the equipment is, or not."""
    doc, refused = _open_link(link_id, t)
    if refused is not None:
        return refused
    save = bool(body.get("save"))
    offer = photo_links().answer(doc["_id"], str(body.get("photo_id") or ""), "saved" if save else "declined")
    if offer is None:
        return JSONResponse(status_code=404, content={"detail": "No location to answer for that photo."})
    if save:
        m = Maintenance(get_store(), doc["org"], doc["uid"])
        try:
            m.set_coordinates(doc["target_id"], offer["lat"], offer["lon"], "photo")
        except (Invalid, NotFound) as err:
            return JSONResponse(status_code=422, content={"detail": str(err)})
    return JSONResponse(content={"saved": save})
