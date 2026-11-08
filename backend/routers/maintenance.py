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
from backend.auth import get_current_user
from backend.db import get_db, get_session, is_simulated
from backend.maintenance.access import allowed
from backend.maintenance import documents as documents_mod
from backend.maintenance import photos as photos_mod
from backend.maintenance.service import PROJECTORS, Invalid, LimitReached, Maintenance, NeedsChoice, NotFound, summary
from backend.maintenance.store import new_id
from backend.maintenance.store import GraphStore, MongoEventLog
from backend.services import access as access_service
from backend.services import time_zones
from backend.services.access import AccessCtx, get_access
from backend.errors import client_message
from backend.services.strategy import StrategyError

router = APIRouter(prefix="/api/maintenance")
# The phone upload page and its posts: the link's token is the credential.
public_router = APIRouter()

_store: GraphStore | None = None
_photo_store = None
_document_store = None
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


def get_document_store():
    global _document_store
    with _store_lock:
        if _document_store is None:
            _document_store = (documents_mod.MongoDocumentStore(get_db()) if _use_mongo() else
                               documents_mod.FileDocumentStore(os.path.join(
                                   os.path.dirname(os.path.abspath(config.MAINTENANCE_DB_PATH)), "documents")))
        return _document_store


def ingest_document(m: Maintenance, raw: bytes, filename: str = "", title: str = "", kind: str = "other",
                    target_id: str | None = None, position_class: str | None = None) -> dict:
    """Check, store and record one PDF on an item, a position or a position
    class. Its bytes are kept as they came (see documents.py)."""
    import hashlib

    m.check_stored_document(len(raw or b""), kind, target_id, position_class)
    documents_mod.check_pdf(raw)
    m.check_limits()
    document_id = new_id()
    store = get_document_store()
    store.put(document_id, raw)
    try:
        return m.add_stored_document(document_id, documents_mod.file_name(filename), len(raw),
                                     hashlib.sha256(raw).hexdigest(), title, kind, target_id, position_class)
    except Exception:
        store.delete(document_id)
        raise


def remove_document(m: Maintenance, document_id: str) -> dict:
    """Remove a document; a stored PDF's bytes are deleted too (the history
    keeps that it was there)."""
    stored = bool(m.document(document_id).get("stored"))
    out = m.remove_document(document_id)
    if stored:
        get_document_store().delete(document_id)
    return out


def remove_function(m: Maintenance, function_id: str, cascade: bool = False, dry_run: bool = False) -> dict:
    """Delete a function (see Maintenance.remove_function); the kept PDFs on it
    go with it, bytes and all (the history keeps that they were there). With
    ``cascade`` (everything under it goes, and Undo brings it back) the bytes are
    kept, so the undo brings the PDFs back whole."""
    if cascade or dry_run:
        return m.remove_function(function_id, cascade=cascade, dry_run=dry_run)
    out = m.remove_function(function_id)
    store = None
    for document_id in out["documents_removed"]:
        if m.document(document_id).get("stored"):
            store = store or get_document_store()
            store.delete(document_id)
    return out


def served_document(m: Maintenance, document_id: str) -> tuple[dict, bytes] | None:
    """A stored PDF and its bytes, if it's in this workspace and hasn't been
    removed."""
    try:
        d = m.stored_document(document_id)
    except NotFound:
        return None
    data = get_document_store().get(d["id"])
    return (d, data) if data is not None else None


def document_links() -> documents_mod.DocumentLinks:
    return documents_mod.DocumentLinks(get_db())


def document_link(base: str, m: Maintenance, document_id: str) -> dict:
    """A stored PDF as a reader sees it, with links to open and download it
    that work for documents.LINK_MINUTES with no sign-in (for an agent)."""
    out = m.document(document_id)
    if out.get("removed") or not out.get("stored"):
        return out
    doc, token = document_links().create(m.org, document_id)
    url = f"{base.rstrip('/')}/api/maintenance/document-links/{doc['_id']}?t={token}"
    return {**out, "open_url": url, "download_url": url + "&download=1",
            "links_expire_at": doc["expires_at"].isoformat()}


async def _read_document_body(request: Request) -> bytes:
    declared = request.headers.get("content-length")
    if declared and declared.isdigit() and int(declared) > documents_mod.MAX_UPLOAD_BYTES:
        raise documents_mod.too_big()
    body = bytearray()
    async for chunk in request.stream():
        body.extend(chunk)
        if len(body) > documents_mod.MAX_UPLOAD_BYTES:
            raise documents_mod.too_big()
    return bytes(body)


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


def _make_store():
    """The graph store the config asks for (docs/maintenance-graph.md): the SQLite
    graph (with a Neo4j mirror when MAINTENANCE_GRAPH_MIRROR=neo4j), or Neo4j
    itself when MAINTENANCE_GRAPH=neo4j."""
    from backend.maintenance.series import MongoSeries
    from backend.maintenance.service import PROJECTION_VERSION
    from backend.maintenance.signals import MongoSnapshots

    if config.MAINTENANCE_GRAPH == "neo4j":
        from backend.maintenance.neo4j_store import Neo4jGraphStore, connect
        from backend.maintenance.store import SqliteEventLog, open_sqlite

        if _use_mongo():
            log, series = MongoEventLog(get_db()), MongoSeries(get_db())
            snapshots = MongoSnapshots(get_db())
        else:
            log, series = SqliteEventLog(open_sqlite(config.MAINTENANCE_DB_PATH)), None
            snapshots = None
        # A namespace per projection version: a new version builds its graph beside
        # the old one, which the processes still running the old version keep using.
        return Neo4jGraphStore(connect(), PROJECTORS, log, series=series, snapshots=snapshots,
                               version=PROJECTION_VERSION,
                               namespace=f"{config.MAINTENANCE_GRAPH_NAMESPACE}graph-v{PROJECTION_VERSION}")
    if _use_mongo():
        store = GraphStore(":memory:", PROJECTORS, MongoEventLog(get_db()), series=MongoSeries(get_db()),
                           snapshots=MongoSnapshots(get_db()), version=PROJECTION_VERSION)
    else:
        store = GraphStore(config.MAINTENANCE_DB_PATH, PROJECTORS, version=PROJECTION_VERSION)
    from backend.maintenance.mirror import attach_from_config

    attach_from_config(store)
    return store


def get_store() -> GraphStore:
    """The graph, caught up with the log (other processes may have written)."""
    global _store
    with _store_lock:
        if _store is None:
            _store = _make_store()
        store = _store
    store.sync()
    return store


def maintenance(ctx: AccessCtx = Depends(get_access)) -> Maintenance:
    if not allowed(ctx.user):
        raise HTTPException(status_code=404, detail="Not found.")
    return Maintenance(get_store(), ctx.write_owner, ctx.uid, time_zone=ctx.time_zone)


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
    """Whether the caller may use Reliafy Maintenance (the app shows it if so), and
    whether they have graph access (the Data model page)."""
    from backend.maintenance.access import graph_query_allowed

    return {"allowed": allowed(ctx.user), "graph": graph_query_allowed(ctx.user)}


def _run(fn, *args, **kwargs) -> JSONResponse:
    try:
        return JSONResponse(content=fn(*args, **kwargs))
    except NotFound:
        return JSONResponse(status_code=404, content={"detail": "Not found."})
    except NeedsChoice as err:
        # Not a refusal: the move goes ahead once the caller says what its tasks count there.
        return JSONResponse(status_code=409, content={"detail": client_message(err), "needs_choice": err.choice})
    except LimitReached as err:
        return JSONResponse(status_code=err.status, content={"detail": client_message(err)})
    except photos_mod.Busy as err:
        return JSONResponse(status_code=503, content={"detail": client_message(err)}, headers={"Retry-After": "30"})
    except (Invalid, photos_mod.BadPhoto) as err:
        return JSONResponse(status_code=422, content={"detail": client_message(err)})


# ---- overview ----------------------------------------------------------------------

@router.get("/overview")
def overview(m: Maintenance = Depends(maintenance)) -> JSONResponse:
    return _run(lambda: {
        "summary": summary(m), "time_zone": m.time_zone, "today": m.today(), "tree": m.tree(),
        "due": m.due_tasks(30), "open_work_orders": m.work_orders("open"), "proposals": m.proposals("pending"),
        "critical_spares": m.critical_spares_short(),
    })


@router.get("/tree")
def tree(m: Maintenance = Depends(maintenance)) -> JSONResponse:
    """The asset trees for the app's tree pane: every position once, flat, with what
    each row shows (status, and everything inside it rolled up), the locations, the
    spares placed at them and the items with no home."""
    return _run(lambda: {"summary": summary(m), **m.tree_rows()})


@router.get("/events")
def events(limit: int = 100, since: int | None = None, type: str | None = None,
           m: Maintenance = Depends(maintenance)) -> JSONResponse:
    """The workspace's recent events, newest first (each with its seq); since a
    seq reads forward from it; type keeps one event type."""
    return _run(lambda: {"events": m.s.events(m.org, max(1, min(limit, 500)), since, type or None)})


# ---- positions -----------------------------------------------------------------------

@router.post("/positions")
def create_position(body: dict = Body(...), m: Maintenance = Depends(maintenance_write)) -> JSONResponse:
    """A position; location_id (optional) says where it physically is, operating_context
    (optional) how it's used."""
    return _run(m.create_position, body.get("name"), body.get("tag", ""), body.get("parent_id"),
                body.get("position_class", ""), body.get("description", ""), body.get("location_id"),
                body.get("operating_context", ""))


@router.get("/positions/{position_id}")
def get_position(position_id: str, m: Maintenance = Depends(maintenance)) -> JSONResponse:
    return _run(m.position, position_id)


@router.patch("/positions/{position_id}")
def update_position(position_id: str, body: dict = Body(...),
                    m: Maintenance = Depends(maintenance_write)) -> JSONResponse:
    """Change a position; location_id sets where it is (null: it inherits its parent's)."""
    def go():
        m.update_position(position_id, **{k: body[k] for k in
                                          ("name", "tag", "position_class", "description", "operating_context",
                                           "parent_id", "location_id") if k in body})
        return m.position(position_id)
    return _run(go)


@router.post("/positions/{position_id}/fit")
def fit(position_id: str, body: dict = Body(...), m: Maintenance = Depends(maintenance_write)) -> JSONResponse:
    return _run(m.fit, position_id, body.get("item_id"), body.get("new_item"), body.get("on"),
                body.get("from_precision"))


@router.post("/positions/{position_id}/remove")
def remove(position_id: str, body: dict = Body(default={}), m: Maintenance = Depends(maintenance_write)) -> JSONResponse:
    """A failure names its mode by failure_mode_id, or in words (failure_mode_text)."""
    return _run(m.remove, position_id, body.get("on"), body.get("reason"), body.get("failure_mode_id"),
                body.get("failure_mode_text"), body.get("to_precision"))


@router.post("/positions/{position_id}/past-fitments")
def add_past_fitment(position_id: str, body: dict = Body(...), m: Maintenance = Depends(maintenance_write)) -> JSONResponse:
    """A past fitment into the position's history: start, end, reason, an item (item_id or new_item)."""
    return _run(m.add_past_fitment, position_id, body.get("start"), body.get("end"), body.get("reason"),
                body.get("item_id"), body.get("new_item"), body.get("failure_mode_id"), body.get("failure_mode_text"),
                body.get("from_precision"), body.get("to_precision"), body.get("note", ""))


def _create_task(m: Maintenance, body: dict, **subject) -> JSONResponse:
    return _run(m.create_task, subject.pop("position_id", None), body.get("name"), body.get("interval"),
                body.get("unit") or "months", body.get("outcome"), body.get("also_interval"), body.get("also_unit"),
                body.get("point_id"), body.get("instructions", ""), body.get("checklist"),
                body.get("source") or "manual", body.get("reference", ""), body.get("failure_mode_id"),
                body.get("last_done"), body.get("trade", ""), while_stored=body.get("while_stored"),
                include_positions=body.get("include_positions"), failure_mode_ids=body.get("failure_mode_ids"),
                trigger=body.get("trigger"), start=body.get("start"), **subject)


@router.post("/positions/{position_id}/tasks")
def create_task(position_id: str, body: dict = Body(...), m: Maintenance = Depends(maintenance_write)) -> JSONResponse:
    """A scheduled task added by hand (not from an RCM decision), on the position: it stays with the job."""
    return _create_task(m, body, position_id=position_id)


@router.post("/items/{item_id}/tasks")
def create_item_task(item_id: str, body: dict = Body(...), m: Maintenance = Depends(maintenance_write)) -> JSONResponse:
    """A task on an item: it follows the serial number wherever it goes (while_stored: run or pause)."""
    return _create_task(m, body, item_id=item_id)


@router.post("/locations/{location_id}/tasks")
def create_location_task(location_id: str, body: dict = Body(...),
                         m: Maintenance = Depends(maintenance_write)) -> JSONResponse:
    """A task on a location (a round, an area inspection), by the calendar; include_positions lists
    the positions there on its work orders."""
    return _create_task(m, body, location_id=location_id)


@router.post("/positions/{position_id}/failure-modes")
def add_failure_mode(position_id: str, body: dict = Body(...), m: Maintenance = Depends(maintenance_write)) -> JSONResponse:
    """A failure mode; functional_failure_id puts it under one of the position's functional failures,
    function_id (and no functional failure) directly under one of its functions."""
    return _run(m.add_failure_mode, position_id, body.get("text"), body.get("function", ""), body.get("failure", ""),
                body.get("consequence", ""), body.get("functional_failure_id"), body.get("function_id"))


@router.patch("/failure-modes/{mode_id}")
def update_failure_mode(mode_id: str, body: dict = Body(...), m: Maintenance = Depends(maintenance_write)) -> JSONResponse:
    """The mode's words and RCM analysis (text, function, failure, consequence, effects, notes) and its
    FME(C)A fields (fmea.FIELDS: severity, occurrence, detection, cause, the effects, the recommended
    action, the criticality figures; null clears one). With any FME(C)A field the answer carries rpn, ap
    and cm."""
    from backend.maintenance import fmea

    def go():
        words = {k: body[k] for k in ("text", "function", "failure", "consequence", "effects", "notes") if k in body}
        scores = {k: body[k] for k in fmea.FIELDS if k in body}
        out = m.update_failure_mode(mode_id, **words) if words or not scores else None
        if scores:
            scored = m.score_failure_mode(mode_id, scores)
            return {**(out or m._mode_view(m._get(mode_id, "FailureMode"))), **scored}
        return out
    return _run(go)


# ---- failure reports: what failed, and what was done about it ---------------------------

def _who(ctx: AccessCtx, body: dict | None = None) -> str:
    """Who makes a change on a failure report: as the body says, else the signed-in
    user's name or email."""
    given = (body or {}).get("by")
    user = ctx.user or {}
    return str(given) if given else (user.get("name") or user.get("email") or "")


@router.get("/failure-reports")
def list_failure_reports(position_id: str | None = None, below: str = "1", location_id: str | None = None,
                         item_id: str | None = None, status: str | None = None, consequence: str | None = None,
                         failure_mode_id: str | None = None, part_id: str | None = None, since: str | None = None,
                         until: str | None = None, q: str | None = None, sort: str = "newest", limit: int = 100,
                         offset: int = 0, m: Maintenance = Depends(maintenance)) -> JSONResponse:
    """The failure reports in a scope: a position (below=1: every position inside it too), a
    location, an item, or the whole workspace; filtered, sorted and paged, with counts by status."""
    return _run(m.failure_reports, position_id=position_id or None, below=below not in ("0", "false", "no", ""),
                location_id=location_id or None, item_id=item_id or None, status=status or None,
                consequence=consequence or None, failure_mode_id=failure_mode_id or None, part_id=part_id or None,
                since=since or None, until=until or None, q=q or None, sort=sort or "newest", limit=limit,
                offset=offset)


@router.post("/failure-reports")
def file_failure_report(body: dict = Body(...), ctx: AccessCtx = Depends(get_access),
                        m: Maintenance = Depends(maintenance_write)) -> JSONResponse:
    """A failure report at a position: title (what happened), description, occurred_on (default today),
    found_by, consequence, failure_mode_id or failure_mode_text, item_id (default: the item fitted there that day)."""
    return _run(m.file_failure_report, body.get("position_id"), body.get("title"), body.get("description", ""),
                body.get("occurred_on"), body.get("found_by", ""), body.get("consequence"),
                body.get("failure_mode_id"), body.get("failure_mode_text"), body.get("item_id"), by=_who(ctx, body))


@router.get("/failure-reports/{report_id}")
def get_failure_report(report_id: str, m: Maintenance = Depends(maintenance)) -> JSONResponse:
    """One report in full: facts, item snapshot, investigation, corrective actions, verification,
    repeat_check, history, photos and can.close."""
    return _run(m.failure_report, report_id)


@router.patch("/failure-reports/{report_id}")
def update_failure_report(report_id: str, body: dict = Body(...), ctx: AccessCtx = Depends(get_access),
                          m: Maintenance = Depends(maintenance_write)) -> JSONResponse:
    """Change a report's own fields (title, description, occurred_on, found_by, consequence,
    failure_mode_id / failure_mode_text, item_id) while it's open."""
    return _run(m.update_failure_report, report_id, by=_who(ctx, body),
                **{k: v for k, v in body.items() if k != "by"})


@router.post("/failure-reports/{report_id}/status")
def set_failure_report_status(report_id: str, body: dict = Body(...), ctx: AccessCtx = Depends(get_access),
                              m: Maintenance = Depends(maintenance_write)) -> JSONResponse:
    """Move it along: {status, note?, duplicate_of?}. closed needs a verification; rejected needs a note."""
    return _run(m.set_failure_report_status, report_id, body.get("status"), body.get("note", ""),
                body.get("duplicate_of"), by=_who(ctx, body))


@router.put("/failure-reports/{report_id}/investigation")
def investigate_failure_report(report_id: str, body: dict = Body(...), ctx: AccessCtx = Depends(get_access),
                               m: Maintenance = Depends(maintenance_write)) -> JSONResponse:
    """The investigation: {notes?, root_cause_category?, root_cause?, whys?} (a field left out keeps its value)."""
    return _run(m.investigate_failure_report, report_id, body.get("notes"), body.get("root_cause_category"),
                body.get("root_cause"), body.get("whys"), by=_who(ctx, body))


@router.post("/failure-reports/{report_id}/actions")
def add_corrective_action(report_id: str, body: dict = Body(...), ctx: AccessCtx = Depends(get_access),
                          m: Maintenance = Depends(maintenance_write)) -> JSONResponse:
    """A corrective action: {what, owner?, due?, work_order_id?, work_order_ref?}."""
    return _run(m.add_corrective_action, report_id, body.get("what"), body.get("owner", ""), body.get("due"),
                body.get("work_order_id"), body.get("work_order_ref", ""), by=_who(ctx, body))


@router.patch("/failure-reports/{report_id}/actions/{action_id}")
def update_corrective_action(report_id: str, action_id: str, body: dict = Body(...),
                             ctx: AccessCtx = Depends(get_access),
                             m: Maintenance = Depends(maintenance_write)) -> JSONResponse:
    """Change one corrective action: what, owner, due, status (open / done / dropped), done_on,
    work_order_id, work_order_ref."""
    return _run(m.update_corrective_action, report_id, action_id, by=_who(ctx, body),
                **{k: v for k, v in body.items() if k != "by"})


@router.put("/failure-reports/{report_id}/verification")
def verify_failure_report(report_id: str, body: dict = Body(...), ctx: AccessCtx = Depends(get_access),
                          m: Maintenance = Depends(maintenance_write)) -> JSONResponse:
    """Did it work? {result: worked | not_worked | unclear, notes?, verified_on?}."""
    return _run(m.verify_failure_report, report_id, body.get("result"), body.get("notes", ""),
                body.get("verified_on"), by=_who(ctx, body))


# ---- a position's RCM: functions, functional failures, decisions ------------------------

def _rcm_read(session, ctx: AccessCtx, fn, *args) -> JSONResponse:
    """A read of the RCM with the evidence checked as the reader sees it."""
    from backend.maintenance import rcm_graph

    def go():
        out = fn(*args)
        if "positions" in out:
            return rcm_graph.resolve(session, out, ctx.read_owners, ctx.hidden)
        return rcm_graph.mode_status(session, out, ctx.read_owners, ctx.hidden)
    return _run(go)


@router.get("/rcm")
def workspace_rcm(session=Depends(get_session), ctx: AccessCtx = Depends(get_access),
                  m: Maintenance = Depends(maintenance)) -> JSONResponse:
    """Every position's RCM (those with any), for the asset tree's RCM tab, with each
    decision's evidence check as the reader sees it."""
    return _rcm_read(session, ctx, m.rcm_all)


@router.get("/positions/{position_id}/rcm")
def position_rcm(position_id: str, scope: str = "below", session=Depends(get_session),
                 ctx: AccessCtx = Depends(get_access), m: Maintenance = Depends(maintenance)) -> JSONResponse:
    """The position's RCM from the graph (scope below: it and everything inside it; this: it alone):
    functions › functional failures › failure modes, each mode's decision, task and evidence check."""
    return _rcm_read(session, ctx, m.rcm_worksheet, position_id, scope)


@router.get("/positions/{position_id}/fmea.xlsx")
def position_fmea_xlsx(position_id: str, scope: str = "below", session=Depends(get_session),
                       ctx: AccessCtx = Depends(get_access), m: Maintenance = Depends(maintenance)) -> Response:
    """The position's FME(C)A as an Excel workbook (scope below: it and everything inside it; this:
    it alone): one row per failure mode with its scores, action priority and criticality, the
    columns named as the worksheet import reads them, so the file imports again."""
    from urllib.parse import quote

    from backend.maintenance import fmea_sheet, rcm_graph

    try:
        sheet = rcm_graph.resolve(session, m.rcm_worksheet(position_id, scope), ctx.read_owners, ctx.hidden)
    except NotFound:
        return JSONResponse(status_code=404, content={"detail": "Not found."})
    except Invalid as err:
        return JSONResponse(status_code=422, content={"detail": client_message(err)})
    name = fmea_sheet.filename(sheet["position"]["name"])
    ascii_name = name.encode("ascii", "ignore").decode() or "FMECA.xlsx"
    return Response(content=fmea_sheet.workbook(sheet), media_type=fmea_sheet.XLSX, headers={
        "Content-Disposition": f"attachment; filename=\"{ascii_name}\"; filename*=UTF-8''{quote(name)}",
        "Cache-Control": "no-store",
    })


@router.post("/positions/{position_id}/functions")
def add_function(position_id: str, body: dict = Body(...), m: Maintenance = Depends(maintenance_write)) -> JSONResponse:
    """A function with its performance standard and its notes and rationale (which hold
    the working behind the standard; standard_basis, deprecated, is added to them)."""
    return _run(m.add_function, position_id, body.get("text"), body.get("standard", ""),
                standard_basis=body.get("standard_basis", ""), notes=body.get("notes"))


@router.get("/functions/{function_id}")
def get_function(function_id: str, m: Maintenance = Depends(maintenance)) -> JSONResponse:
    """One function in full: its notes and rationale (with the working behind its standard) and documents."""
    return _run(m.function, function_id)


@router.patch("/functions/{function_id}")
def update_function(function_id: str, body: dict = Body(...),
                    m: Maintenance = Depends(maintenance_write)) -> JSONResponse:
    """text, standard or notes (its rationale and the working behind the standard; standard_basis,
    deprecated, is added to them); "" clears one."""
    return _run(m.update_function, function_id, body.get("text"), body.get("standard"),
                body.get("standard_basis"), notes=body.get("notes"))


@router.delete("/functions/{function_id}")
def delete_function(function_id: str, cascade: bool = False, dry_run: bool = False,
                    m: Maintenance = Depends(maintenance_write)) -> JSONResponse:
    """Delete a function and its functional failures (their failure modes stay, unassigned)
    and the documents on it. cascade: everything under it goes too (POST /rcm/{id}/restore
    undoes it); dry_run: only count what that would take."""
    return _run(remove_function, m, function_id, cascade, dry_run)


@router.post("/rcm/{root_id}/restore")
def restore_rcm(root_id: str, m: Maintenance = Depends(maintenance_write)) -> JSONResponse:
    """Undo the latest delete with cascade of a function, performance standard, functional failure
    or failure mode (root_id: the one deleted): everything it took comes back."""
    return _run(m.restore_rcm, root_id)


@router.post("/functions/{function_id}/failures")
def add_functional_failure(function_id: str, body: dict = Body(...),
                           m: Maintenance = Depends(maintenance_write)) -> JSONResponse:
    """standard_id: the function's standard it breaches (left out: the whole function);
    notes: its rationale."""
    return _run(m.add_functional_failure, function_id, body.get("text"), body.get("standard_id"),
                notes=body.get("notes"))


@router.patch("/functional-failures/{ff_id}")
def update_functional_failure(ff_id: str, body: dict = Body(...),
                              m: Maintenance = Depends(maintenance_write)) -> JSONResponse:
    """text, standard_id (null: the whole function) and/or notes ("" clears them)."""
    return _run(m.update_functional_failure, ff_id, body.get("text"),
                body["standard_id"] if "standard_id" in body else ..., notes=body.get("notes"))


# ---- a function's performance standards, as a list -----------------------------------------

_STANDARD_KEYS = ("text", "parameter", "comparator", "value", "unit", "when", "source", "notes")


@router.post("/functions/{function_id}/standards")
def add_standard(function_id: str, body: dict = Body(...), m: Maintenance = Depends(maintenance_write)) -> JSONResponse:
    """One performance standard: text (one parameter, one limit), and optionally parameter, comparator,
    value, unit, when, source. The function's old single text becomes the list's first item."""
    return _run(m.add_standard, function_id, **{k: body.get(k) for k in _STANDARD_KEYS})


@router.patch("/standards/{standard_id}")
def update_standard(standard_id: str, body: dict = Body(...), m: Maintenance = Depends(maintenance_write)) -> JSONResponse:
    return _run(m.update_standard, standard_id, **{k: body[k] for k in _STANDARD_KEYS if k in body})


@router.delete("/standards/{standard_id}")
def remove_standard(standard_id: str, cascade: bool = False, dry_run: bool = False,
                    m: Maintenance = Depends(maintenance_write)) -> JSONResponse:
    """cascade: the functional failures breaching it go too, with their modes and tasks."""
    return _run(m.remove_standard, standard_id, cascade, dry_run)


@router.put("/functions/{function_id}/standards/order")
def reorder_standards(function_id: str, body: dict = Body(...),
                      m: Maintenance = Depends(maintenance_write)) -> JSONResponse:
    """standard_ids: every one of the function's standards, in the order wanted."""
    return _run(m.reorder_standards, function_id, body.get("standard_ids"))


@router.post("/standards/{standard_id}/move")
def move_standard(standard_id: str, body: dict = Body(...), m: Maintenance = Depends(maintenance_write)) -> JSONResponse:
    """To another function (function_id), on the same position or another, alone: the functional
    failures that breached it stay with their function, under no performance standard. functional_failure_ids:
    failures of the new function that breach it from now on."""
    return _run(m.move_standard, standard_id, body.get("function_id"), body.get("functional_failure_ids"))


@router.post("/functions/{function_id}/standards/split")
def split_standard(function_id: str, body: dict | None = Body(None),
                   m: Maintenance = Depends(maintenance_write)) -> JSONResponse:
    """The function's single performance standard text as a list: proposed (dry_run true, the default, or no
    standards given), or written from standards [{text, when?, source?}] with dry_run false."""
    body = body or {}
    return _run(m.split_standard, function_id, body.get("standards"), bool(body.get("dry_run", True)))


@router.delete("/functional-failures/{ff_id}")
def remove_functional_failure(ff_id: str, cascade: bool = False, dry_run: bool = False,
                              m: Maintenance = Depends(maintenance_write)) -> JSONResponse:
    """cascade: its failure modes and their tasks go too."""
    return _run(m.remove_functional_failure, ff_id, cascade, dry_run)


@router.post("/functional-failures/{ff_id}/causes")
def link_functional_failure_cause(ff_id: str, body: dict = Body(...),
                                  m: Maintenance = Depends(maintenance_write)) -> JSONResponse:
    """It results from cause_id, a functional failure on a position inside its own; returns
    the functional failure with its causes and effects."""
    return _run(m.link_cause, ff_id, body.get("cause_id"))


@router.delete("/functional-failures/{ff_id}/causes/{cause_id}")
def unlink_functional_failure_cause(ff_id: str, cause_id: str,
                                    m: Maintenance = Depends(maintenance_write)) -> JSONResponse:
    return _run(m.unlink_cause, ff_id, cause_id)


@router.post("/failure-modes/{mode_id}/assign")
def assign_failure_mode(mode_id: str, body: dict = Body(...),
                        m: Maintenance = Depends(maintenance_write)) -> JSONResponse:
    """Under one of its position's functional failures (functional_failure_id), directly under one of its
    functions (function_id, no functional failure between), or none (both null)."""
    return _run(m.assign_failure_mode, mode_id, body.get("functional_failure_id"), body.get("function_id"))


@router.put("/failure-modes/{mode_id}/decision")
def decide_failure_mode(mode_id: str, body: dict = Body(...), session=Depends(get_session),
                        ctx: AccessCtx = Depends(get_access),
                        m: Maintenance = Depends(maintenance_write)) -> JSONResponse:
    """The mode's two answers (hidden: true when the failure can't be seen in normal operation; consequence:
    safety, environmental, operational or non_operational, "hidden" a deprecated alias for hidden true) and its
    decision ({outcome, rtf_basis, task, interval, interval_unit, on_found, evidence}; null clears it), checked by
    the RCM decision rules and diagram; the evidence must be one the writer can open.
    A combination of tasks: decision.outcomes [{outcome, task, interval, interval_unit, task_id, evidence,
    on_found}, ...] in place of outcome, task and interval, each scheduled member with a task of its own and
    checked against its own evidence, else the decision's.
    on_found: what's done when an on-condition or failure-finding check finds it ("" clears it; left out, it is
    kept while the kind of task stays). decision.notes is deprecated: it is added to the failure mode's notes
    and rationale (PATCH the failure mode's notes instead); reads return the mode's notes there."""
    from backend.maintenance import rcm_graph

    def go():
        if "decision" in body and body["decision"]:
            old = m.rcm_mode(mode_id).get("decision")
            access_service.check_references(session, ctx, rcm_graph.evidence_refs(body["decision"]),
                                            keep=rcm_graph.evidence_refs(old))
        return m.decide_failure_mode(mode_id, body["consequence"] if "consequence" in body else ...,
                                     body["decision"] if "decision" in body else ..., task_id=body.get("task_id"),
                                     hidden=body["hidden"] if "hidden" in body else ...)
    try:
        return _rcm_read(session, ctx, go)
    except access_service.UnreadableReference as exc:
        return JSONResponse(status_code=exc.status, content={"detail": client_message(exc), "code": "unreadable_reference"})


# ---- a failure mode's tasks: several may serve one mode, one may serve several ---------

@router.get("/failure-modes/{mode_id}/tasks")
def failure_mode_tasks(mode_id: str, m: Maintenance = Depends(maintenance)) -> JSONResponse:
    """The mode's live tasks (its decision's own first) and the tasks on its position, or on
    positions above it, that could serve it too (available)."""
    return _run(m.mode_tasks, mode_id)


@router.post("/failure-modes/{mode_id}/tasks")
def add_failure_mode_task(mode_id: str, body: dict = Body(...), m: Maintenance = Depends(maintenance_write)) -> JSONResponse:
    """Another task for the failure mode: name, interval, unit (default months), outcome (default: the
    decision's, when it schedules work), instructions, start (the date it first falls due; default one
    interval from today)."""
    return _run(m.add_mode_task, mode_id, body.get("name"), body.get("interval"), body.get("unit") or "months",
                body.get("outcome"), body.get("instructions", ""), start=body.get("start"))


@router.post("/tasks/{task_id}/failure-modes/{mode_id}")
def link_task_failure_mode(task_id: str, mode_id: str, m: Maintenance = Depends(maintenance_write)) -> JSONResponse:
    """The task also prevents that failure mode (on its position, or on a position inside it)."""
    return _run(m.link_task, task_id, mode_id)


@router.delete("/tasks/{task_id}/failure-modes/{mode_id}")
def unlink_task_failure_mode(task_id: str, mode_id: str, m: Maintenance = Depends(maintenance_write)) -> JSONResponse:
    """Take that one failure mode off the task (its other links stay)."""
    return _run(m.unlink_task, task_id, mode_id)


@router.delete("/failure-modes/{mode_id}")
def retire_failure_mode(mode_id: str, cascade: bool = False, dry_run: bool = False,
                        m: Maintenance = Depends(maintenance_write)) -> JSONResponse:
    """Delete it from the position's RCM, with its task (failures recorded against it keep it).
    cascade: recorded so POST /rcm/{id}/restore brings it back with its tasks and their links."""
    return _run(m.retire_failure_mode, mode_id, cascade, dry_run)


@router.post("/failure-modes/{mode_id}/move")
def move_failure_mode(mode_id: str, body: dict = Body(...),
                      m: Maintenance = Depends(maintenance_write)) -> JSONResponse:
    """To another position (position_id), with its decision and tasks, under one of that
    position's functional failures (functional_failure_id), directly under one of its functions
    (function_id) or none. measurement: what its tasks by use count there when what they count
    now doesn't fit (409 needs_choice asks)."""
    return _run(m.move_failure_mode, mode_id, body.get("position_id"), body.get("functional_failure_id"),
                body.get("function_id"), body.get("measurement"))


@router.post("/functions/{function_id}/move")
def move_function(function_id: str, body: dict = Body(...),
                  m: Maintenance = Depends(maintenance_write)) -> JSONResponse:
    """To another position (position_id), with its functional failures, their failure
    modes and those modes' tasks. measurement: as for a failure mode's move."""
    return _run(m.move_function, function_id, body.get("position_id"), body.get("measurement"))


@router.post("/functional-failures/{ff_id}/move")
def move_functional_failure(ff_id: str, body: dict = Body(...),
                            m: Maintenance = Depends(maintenance_write)) -> JSONResponse:
    """Under another function (function_id), on the same position or another, with its failure
    modes and their tasks; standard_id: one of that function's standards it breaches there.
    measurement: as for a failure mode's move."""
    return _run(m.move_functional_failure, ff_id, body.get("function_id"), body.get("standard_id"),
                body.get("measurement"))


@router.put("/rcm/order")
def reorder_rcm(body: dict = Body(...), m: Maintenance = Depends(maintenance_write)) -> JSONResponse:
    """ids: the children of parent_id (a position's functions, a function's functional failures or a
    functional failure's failure modes) in the order wanted, every live one named once."""
    return _run(m.reorder_rcm, body.get("parent_id"), body.get("ids"))


@router.post("/rcm/apply")
def rcm_apply(body: dict = Body(...), m: Maintenance = Depends(maintenance_write)) -> JSONResponse:
    """The RCM tab's drag and drop: operations [{do, args}] (the maintenance apply shape, arranging
    actions only: assign, move, move_function, move_functional_failure, update_functional_failure,
    reorder, reorder_standards, move_standard, tasks link / unlink / move) run as one batch. Every operation is
    first checked on a throwaway copy of the workspace: with any refusal nothing is written (422,
    detail says which operation and why). The answer is maintenance apply's: each operation's
    result, counts and undo (the operations that put everything back, newest first; send them here
    as a batch). dry_run true checks only."""
    from backend.maintenance import apply as apply_mod
    from backend.maintenance.store import scratch_copy

    try:
        ops = apply_mod.parse_arranging(body.get("operations"))
    except apply_mod.BatchRefused as err:
        return JSONResponse(status_code=422, content={"detail": client_message(err)})

    def call(area, action, args):
        return apply_mod.arrange(apply_mod.ACTIVE_M.get(), f"{area}.{action}", args)

    copy = Maintenance(scratch_copy(m.s, m.org), m.org, m.actor, time_zone=m.time_zone)
    rehearsal = apply_mod.run_pass(ops, call, copy, "stop", dry=True)
    if rehearsal["failed"]:
        out = apply_mod.summarise(ops, rehearsal, True, 0)
        if rehearsal["failed"].get("needs_choice"):
            # Not a refusal: say what its tasks count there (that operation's measurement) and send it again.
            out["detail"] = rehearsal["failed"]["error"].split(": ", 1)[-1]
            out["needs_choice"] = {**rehearsal["failed"]["needs_choice"], "op_index": rehearsal["failed"]["index"]}
            return JSONResponse(status_code=409, content=out)
        out["detail"] = f"Nothing was changed: {rehearsal['failed']['error']}"
        return JSONResponse(status_code=422, content=out)
    if body.get("dry_run"):
        return JSONResponse(content=apply_mod.summarise(ops, rehearsal, True, copy.s.event_count(m.org)))
    before = m.s.event_count(m.org)
    real = apply_mod.run_pass(ops, call, m, "stop", dry=False)
    out = apply_mod.summarise(ops, real, False, m.s.event_count(m.org) - before)
    if real["failed"]:
        out["detail"] = (f"Stopped at {real['failed']['error']} The operations before it were applied (undo lists "
                         "their reverse); the rest were skipped.")
    return JSONResponse(content=out)


@router.post("/failure-modes/{mode_id}/merge")
def merge_failure_mode(mode_id: str, body: dict = Body(...), m: Maintenance = Depends(maintenance_write)) -> JSONResponse:
    """Fold this mode into another on the same position (into_id)."""
    return _run(m.merge_failure_mode, mode_id, body.get("into_id"))


def _rcm_sheet(m: Maintenance, ctx: AccessCtx, position_id: str, file: UploadFile, sheet, header_row, options,
               dry_run: bool) -> JSONResponse:
    """Read the uploaded worksheet and add it to the position's RCM (or, with
    dry_run, say what it would add)."""
    import json

    from backend.maintenance import rcm_sheet
    from backend.routers import excel as excel_router
    from backend.services import excel

    try:
        opts = json.loads(options) if options else None
    except ValueError:
        return JSONResponse(status_code=422, content={"detail": "The import options aren't valid JSON."})
    if opts is not None and not isinstance(opts, dict):
        return JSONResponse(status_code=422, content={"detail": "The import options must be an object."})
    data = excel_router.read_upload(file)
    filename = file.filename or ""
    try:
        table = excel_router.guarded(ctx.uid, rcm_sheet.read_table, data, filename, sheet or None,
                                     excel_router.header_row_param(header_row))
    except Exception as exc:  # noqa: BLE001 - untrusted file: a 422 that says why, never a 500
        return excel_router.excel_error(exc, "rcm sheet", data, filename)
    if opts is None:
        opts = rcm_sheet.default_options(table)
    return _run(rcm_sheet.run, m, position_id, table, opts, dry_run)


@router.post("/positions/{position_id}/rcm/import/preview")
def preview_rcm_sheet(position_id: str, file: UploadFile = File(...), sheet: str | None = Form(None),
                      header_row: str | None = Form(None), options: str | None = Form(None),
                      ctx: AccessCtx = Depends(get_access), m: Maintenance = Depends(maintenance)) -> JSONResponse:
    """What an FMEA / RCM worksheet (Excel or CSV, one row per failure mode) would add to the position's RCM:
    functions, functional failures, failure modes and tasks, what's there already and rows skipped. Nothing is
    written. ``options`` is JSON ``{mapping, consequence_map, outcome_map, extra_columns}``
    (:func:`backend.services.rcm_import.build_tree`; left out: the mapping guessed from the header)."""
    return _rcm_sheet(m, ctx, position_id, file, sheet, header_row, options, dry_run=True)


@router.post("/positions/{position_id}/rcm/import")
def import_rcm_sheet(position_id: str, file: UploadFile = File(...), sheet: str | None = Form(None),
                     header_row: str | None = Form(None), options: str | None = Form(None),
                     ctx: AccessCtx = Depends(get_access),
                     m: Maintenance = Depends(maintenance_write)) -> JSONResponse:
    """Add the worksheet to the position's RCM, as the preview says. Only adds: a function or functional failure
    with the same text is used as it is, a failure mode already on the position is left as it is, so the same
    sheet imported again adds nothing. With any row in error nothing is written (``ok`` false)."""
    return _rcm_sheet(m, ctx, position_id, file, sheet, header_row, options, dry_run=False)


@router.get("/rcm/options")
def rcm_options(user: dict = Depends(get_current_user)) -> dict:
    """The RCM decision vocabulary with its hints (consequences, outcomes and
    run-to-failure bases), for the decision dialog, and the FME(C)A vocabulary
    (fmea: the action priority table and bands, the choice lists, the scale
    hints) for the FME(C)A tab."""
    from backend.maintenance import fmea, rcm_decisions

    return {**rcm_decisions.options(), "fmea": fmea.options()}


# ---- how often: the interval calculators on a failure mode's task card ---------------
# Exact calculations, free on every plan (no Pro gate). The fixed-interval one is the
# Strategy replacement calculator (POST /api/strategy/optimal-replacement).

def _interval(fn, body: dict, names: tuple) -> JSONResponse:
    from backend.services.rcm_intervals import IntervalError

    unknown = sorted(set(body) - set(names))
    if unknown:
        return JSONResponse(status_code=422, content={"detail": f"Unknown input: {', '.join(unknown)}. "
                                                                f"It takes {', '.join(names)}."})
    try:
        return JSONResponse(content=fn(**body))
    except IntervalError as exc:
        return JSONResponse(status_code=422, content={"detail": client_message(exc)})
    except StrategyError as exc:
        return JSONResponse(status_code=422, content={"detail": client_message(exc)})


@router.post("/rcm/interval/on-condition")
def rcm_interval_on_condition(body: dict = Body(...), user: dict = Depends(get_current_user)) -> JSONResponse:
    """How often to check for a warning that comes a P-F interval (pf_interval in pf_unit) before the
    failure: from the P-F interval alone, half of it, or the net P-F interval (less act_time, the time needed
    to act) when tighter. Costs are optional: with the cost of a check, of fixing a warning found (found_cost)
    and of a failure, and the onset rate (failures a year), cost_optimal adds the cheapest interval and whether
    the check pays. detection_probability: the chance a check finds the warning (default 1). With
    current_interval and current_unit, the task's numbers now too; unit: the unit to answer in."""
    from backend.services import rcm_intervals
    from backend.services.strategy_store import ON_CONDITION_INPUTS

    return _interval(rcm_intervals.on_condition_interval, body, ON_CONDITION_INPUTS)


@router.post("/rcm/interval/failure-finding")
def rcm_interval_failure_finding(body: dict = Body(...), session=Depends(get_session),
                                 ctx: AccessCtx = Depends(get_access)) -> JSONResponse:
    """How often to test a protective device whose failure is hidden: the longest interval that keeps its
    mean unavailability within target_unavailability, or without one the cheapest (test_cost, repair_cost,
    demand_rate a year, consequence_cost). The device: failure_rate (a year), a saved model (model_id) or
    distribution_id + params with model_unit. With current_interval and current_unit, the numbers at the
    task's interval now too."""
    from backend.services import models as models_service
    from backend.services import rcm_intervals
    from backend.services.strategy_store import FAILURE_FINDING_INPUTS

    body = dict(body)
    model_id = body.pop("model_id", None)
    if model_id:
        model = models_service.get_model(session, model_id, ctx.read_owners)
        if model is None or model.id in ctx.hidden:
            return JSONResponse(status_code=404, content={"detail": "Model not found."})
        try:
            given = rcm_intervals.model_inputs(model)
        except rcm_intervals.IntervalError as exc:
            return JSONResponse(status_code=422, content={"detail": client_message(exc)})
        body.update({"distribution_id": given["distribution_id"], "params": given["params"],
                     "extras": given["extras"], "model_unit": body.get("model_unit") or given["unit"]})
    return _interval(rcm_intervals.failure_finding_interval, body, FAILURE_FINDING_INPUTS)


@router.get("/failure-modes/{mode_id}/interval-inputs")
def failure_mode_interval_inputs(mode_id: str, session=Depends(get_session), ctx: AccessCtx = Depends(get_access),
                                 m: Maintenance = Depends(maintenance)) -> JSONResponse:
    """What the task card's interval calculators start from for this failure mode: its linked evidence
    (a non-repairable model, a saved analysis, a degradation model) and its position's failure history,
    each value with where it came from; null where the user has to type it."""
    from backend.maintenance import rcm_decisions
    from backend.services import rcm_intervals

    def go():
        mode = m.rcm_mode(mode_id)
        _, position = m._live_mode(mode_id)
        rows = m.life_data(position["id"]) if position else []
        fetch = rcm_decisions.evidence_fetcher(session, ctx.read_owners, ctx.hidden)
        return rcm_intervals.starting_inputs(mode, rows, fetch)
    return _run(go)


@router.post("/sample-product")
def add_sample_product(body: dict | None = Body(None), session=Depends(get_session),
                       m: Maintenance = Depends(maintenance_write)) -> JSONResponse:
    """Add the sample product: a quadcopter's design (its RCM, some decisions linked to sample evidence, and
    every failure mode scored as an FME(C)A), its part with
    a bill of materials, three items built from it with two failure reports, and a flight-critical RBD with
    placeholder failure rates. When a copy is there already nothing is added (added false) unless again is
    true."""
    from backend.maintenance import templates

    return _run(templates.add_sample_product, m, session, bool((body or {}).get("again")))


@router.patch("/tasks/{task_id}")
def update_task(task_id: str, body: dict = Body(...), m: Maintenance = Depends(maintenance_write)) -> JSONResponse:
    """Set when it was last done, and/or change its name, interval or unit, when it next falls due
    (start; null or '' goes back to one interval from last done), its trigger or what doing it
    needs (resources: its LSA record)."""
    def go():
        view = None
        if body.get("last_done"):
            view = m.set_last_done(task_id, body["last_done"])
        if any(k in body for k in ("name", "interval", "unit", "also_interval", "also_unit", "point_id",
                                   "instructions", "checklist", "failure_mode_id", "source", "reference",
                                   "outcome", "trade", "while_stored", "include_positions", "last_done_reading",
                                   "start")):
            view = m.update_task(task_id, body.get("name"), body.get("interval"), body.get("unit"),
                                 body.get("also_interval"), body.get("also_unit"), body.get("point_id"),
                                 body.get("instructions"), body.get("checklist"),
                                 ("" if body["failure_mode_id"] is None else body["failure_mode_id"])
                                 if "failure_mode_id" in body else None,
                                 body.get("source"), body.get("reference"),
                                 body["outcome"] if "outcome" in body else ..., body.get("trade"),
                                 body.get("while_stored"), body.get("include_positions"),
                                 body.get("last_done_reading"),
                                 start=("" if body["start"] is None else body["start"]) if "start" in body else None)
        if "trigger" in body:
            # What raises it besides (or instead of) its interval; null clears it.
            view = m.set_task_trigger(task_id, body["trigger"])
        if "resources" in body:
            # What doing it needs (its LSA record): each section given replaces that one.
            view = m.set_task_resources(task_id, body["resources"])
        if view is None:
            raise Invalid("Nothing to change.")
        return view
    return _run(go)


@router.get("/tasks/{task_id}/lsa")
def task_lsa(task_id: str, m: Maintenance = Depends(maintenance)) -> JSONResponse:
    """One task's LSA page: the task with its resources, the failure modes it serves,
    and the measuring points, channels and parts its lines can pick from."""
    return _run(m.task_lsa, task_id)


@router.get("/tasks/{task_id}/trigger-points")
def task_trigger_points(task_id: str, m: Maintenance = Depends(maintenance)) -> JSONResponse:
    """The condition points the task's trigger can watch: on what it's on, above it and
    inside its top position, nearest first."""
    return _run(lambda: {"points": m.task_trigger_points(task_id)})


@router.post("/positions/{position_id}/events")
def log_position_event(position_id: str, body: dict = Body(...),
                       m: Maintenance = Depends(maintenance_write)) -> JSONResponse:
    """Log something that happened at a position (event_type, note, when): tasks there or
    inside it triggered by that event raise their work orders (work_orders_raised)."""
    return _run(m.log_position_event, position_id, body.get("event_type"), body.get("note", ""), body.get("when"))


@router.post("/tasks/{task_id}/move")
def move_task(task_id: str, body: dict = Body(...), m: Maintenance = Depends(maintenance_write)) -> JSONResponse:
    """To another position (position_id): a position's task with no work done on it yet (its open
    work orders go with it). By use,
    it keeps counting what it counted while that fits there; otherwise measurement says what it
    counts there (keep, switch or calendar), and without it the answer is 409 with needs_choice."""
    return _run(m.move_task, task_id, body.get("position_id"), body.get("measurement"))


@router.post("/tasks/{task_id}/retire")
def retire_task(task_id: str, body: dict = Body(default={}), m: Maintenance = Depends(maintenance_write)) -> JSONResponse:
    return _run(lambda: (m.retire_task(task_id, body.get("reason", "")), {"retired": task_id})[1])


@router.post("/positions/{position_id}/retire")
def retire_position(position_id: str, body: dict = Body(default={}),
                    m: Maintenance = Depends(maintenance_write)) -> JSONResponse:
    # cascade: a delete (everything inside goes, nothing refuses); dry_run: only count what would go.
    return _run(m.retire_position, position_id, body.get("reason", ""), bool(body.get("cascade")),
                bool(body.get("dry_run")))


@router.post("/fitments/{fitment_id}/void")
def void_fitment(fitment_id: str, body: dict = Body(default={}), m: Maintenance = Depends(maintenance_write)) -> JSONResponse:
    return _run(lambda: (m.void_fitment(fitment_id, body.get("reason", "")), {"voided": fitment_id})[1])


@router.patch("/fitments/{fitment_id}")
def correct_fitment(fitment_id: str, body: dict = Body(...), m: Maintenance = Depends(maintenance_write)) -> JSONResponse:
    return _run(m.correct_fitment, fitment_id, body.get("start"), body.get("end"), body.get("from_precision"),
                body.get("to_precision"))


@router.get("/classes/one")
def get_class(position_class: str, m: Maintenance = Depends(maintenance)) -> JSONResponse:
    return _run(m.position_class, position_class)


@router.put("/classes/costs")
def set_class_costs(body: dict = Body(...), m: Maintenance = Depends(maintenance_write)) -> JSONResponse:
    return _run(m.set_class_costs, body.get("position_class"), body.get("planned_cost"), body.get("failure_cost"),
                body.get("availability_target"))


@router.put("/classes/replacement-cost")
def set_class_replacement_cost(body: dict = Body(...), m: Maintenance = Depends(maintenance_write)) -> JSONResponse:
    """A class's default replacement cost ({amount, currency, source, as_of}; null clears it)."""
    return _run(m.set_class_replacement_cost, body.get("position_class"), body.get("replacement_cost"))


@router.post("/documents")
def add_document(body: dict = Body(...), m: Maintenance = Depends(maintenance_write)) -> JSONResponse:
    """A link to a document on an item or position (target_id) or a class (position_class)."""
    return _run(m.add_document, body.get("url"), body.get("title", ""), body.get("kind") or "other",
                body.get("target_id"), body.get("position_class"))


@router.post("/documents/upload")
async def upload_document(request: Request, target_id: str | None = None, position_class: str | None = None,
                          title: str = "", kind: str = "other", filename: str = "",
                          m: Maintenance = Depends(maintenance_write)) -> JSONResponse:
    """Keep a PDF (the request body) on an item or position (target_id) or a
    class (position_class)."""
    try:
        raw = await _read_document_body(request)
    except documents_mod.BadDocument as err:
        return JSONResponse(status_code=413, content={"detail": client_message(err)})
    return await run_in_threadpool(_run, ingest_document, m, raw, filename, title, kind or "other",
                                   target_id or None, position_class or None)


@router.get("/documents/{document_id}/file")
def get_document_file(document_id: str, download: bool = False, m: Maintenance = Depends(maintenance)) -> Response:
    found = served_document(m, document_id)
    if found is None:
        return JSONResponse(status_code=404, content={"detail": "Not found."})
    d, data = found
    return Response(content=data, media_type=documents_mod.CONTENT_TYPE,
                    headers=documents_mod.headers(d.get("file_name") or "", download))


@router.delete("/documents/{document_id}")
def delete_document(document_id: str, m: Maintenance = Depends(maintenance_write)) -> JSONResponse:
    return _run(remove_document, m, document_id)


@router.post("/classes/fit")
def fit_class_model(body: dict = Body(...), session=Depends(get_session),
                    m: Maintenance = Depends(maintenance_write)) -> JSONResponse:
    from backend import fitting
    from backend.maintenance import loop

    try:
        return _run(loop.fit_class_model, m, session, str(body.get("position_class") or ""),
                    body.get("distribution") or "weibull")
    except fitting.FitError as err:
        return JSONResponse(status_code=422, content={"detail": f"The fit didn't work: {client_message(err)}"})


@router.get("/classes/economics")
def class_economics(position_class: str, interval: float | None = None, unit: str = "months",
                    horizon_years: float = 10, discount_rate: float = 0.07,
                    m: Maintenance = Depends(maintenance)) -> JSONResponse:
    from backend.maintenance import loop

    return _run(loop.economics, m, position_class, interval, unit, horizon_years, discount_rate)


@router.get("/classes/forecast")
def class_forecast(position_class: str, period: str = "month", periods: int = 12,
                   service_level: float | None = None, lead_time_days: float | None = None,
                   review_days: float | None = None, m: Maintenance = Depends(maintenance)) -> JSONResponse:
    """The class's failure forecast from the register (#407): expected failures per
    period with P10–P90, positions at risk, spares demand against stock and each
    spare's stock levels (#31: service_level and lead_time_days override every
    part's own), budget."""
    from backend.maintenance import forecast

    return _run(forecast.class_forecast, m, position_class, period, periods, service_level, lead_time_days,
                review_days)


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


@router.get("/tasks/{task_id}/measurement")
def task_measurement(task_id: str, position_id: str | None = None,
                     m: Maintenance = Depends(maintenance)) -> JSONResponse:
    """What a task by use counts and what it could count instead (in its unit); position_id:
    a position it would move to (does its measurement fit there, and the choices there)."""
    return _run(m.task_measurement, task_id, position_id)


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
        return JSONResponse(status_code=422, content={"detail": client_message(err)})
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
    """kind counter, condition or setting (a value someone sets: range_min / range_max optional)."""
    return _run(m.add_point, position_id, body.get("name", ""), body.get("kind") or "condition", body.get("unit", ""),
                body.get("source") or "manual", body.get("tag", ""), body.get("alarm_above"), body.get("alarm_below"),
                range_min=body.get("range_min"), range_max=body.get("range_max"))


@router.post("/items/{item_id}/points")
def add_item_point(item_id: str, body: dict = Body(...), m: Maintenance = Depends(maintenance_write)) -> JSONResponse:
    """A measurement point on an item (its own hour meter): it travels with the item."""
    return _run(m.add_point, None, body.get("name", ""), body.get("kind") or "condition", body.get("unit", ""),
                body.get("source") or "manual", body.get("tag", ""), body.get("alarm_above"), body.get("alarm_below"),
                item_id=item_id, range_min=body.get("range_min"), range_max=body.get("range_max"))


# ---- signal channels (rows of the Explorer's Measurements tab; their own pages) --------------------------------------
# The same operations as the maintenance tool's signals.* / signal_data.* actions.

@router.get("/signals/channels")
def signal_channels(position_id: str | None = None, item_id: str | None = None,
                    m: Maintenance = Depends(maintenance)) -> JSONResponse:
    return _run(m.signal_channels, position_id, item_id)


@router.post("/signals/channels")
def add_signal_channel(body: dict = Body(...), m: Maintenance = Depends(maintenance_write)) -> JSONResponse:
    return _run(m.add_signal_channel, body.get("position_id"), body.get("item_id"), body.get("name", ""),
                body.get("unit", ""), body.get("quantity", ""), body.get("sample_rate"), body.get("axes"),
                body.get("rpm"), body.get("tag", ""), body.get("mount", ""))


@router.get("/signals/channels/{channel_id}")
def signal_channel(channel_id: str, snapshots: int = 300, m: Maintenance = Depends(maintenance)) -> JSONResponse:
    return _run(m.signal_channel, channel_id, snapshots)


@router.patch("/signals/channels/{channel_id}")
def update_signal_channel(channel_id: str, body: dict = Body(...),
                          m: Maintenance = Depends(maintenance_write)) -> JSONResponse:
    kwargs = {k: body[k] for k in ("name", "rpm", "tag", "mount", "sample_rate", "speed_channel_id") if k in body}
    return _run(m.update_signal_channel, channel_id, **kwargs)


@router.post("/signals/snapshots")
def add_signal_snapshot(body: dict = Body(...), m: Maintenance = Depends(maintenance_write)) -> JSONResponse:
    """One snapshot, from a signed-in session (a device uses POST /api/ingest/maintenance/snapshots)."""
    known = ("channel_id", "tag", "axes", "samples", "sample_rate", "unit", "spectrum", "value", "values", "running",
             "rpm", "note")
    return _run(m.add_signal_snapshot, body.get("time"), **{k: body[k] for k in known if k in body})


@router.get("/signals/channels/{channel_id}/spectra")
def signal_spectra(channel_id: str, ids: str, axis: str | None = None, f_min: float | None = None,
                   f_max: float | None = None, max_points: int = 600,
                   m: Maintenance = Depends(maintenance)) -> JSONResponse:
    """Several snapshots' spectra for one axis (ids: snapshot ids, comma separated)."""
    return _run(m.signal_spectra, [i for i in ids.split(",") if i], axis, f_min, f_max, max_points)


@router.get("/signals/snapshots/{snapshot_id}")
def signal_snapshot(snapshot_id: str, axis: str | None = None, f_min: float | None = None,
                    f_max: float | None = None, max_points: int = 1500, raw: bool = False,
                    m: Maintenance = Depends(maintenance)) -> JSONResponse:
    return _run(m.signal_snapshot, snapshot_id, axis, f_min, f_max, max_points, raw)


@router.get("/signals/channels/{channel_id}/band-preview")
def preview_signal_band(channel_id: str, low: float, high: float, axis: str | None = None, unit: str = "Hz",
                        m: Maintenance = Depends(maintenance)) -> JSONResponse:
    return _run(m.preview_signal_band, channel_id, low, high, axis, unit)


@router.post("/signals/channels/{channel_id}/bands")
def add_signal_band(channel_id: str, body: dict = Body(...), m: Maintenance = Depends(maintenance_write)) -> JSONResponse:
    return _run(m.add_signal_band, channel_id, body.get("name", ""), body.get("low"), body.get("high"),
                body.get("axis"), body.get("unit") or "Hz", body.get("alarm_above"), body.get("alarm_below"),
                body.get("warn_above"), body.get("warn_below"))


@router.post("/signals/channels/{channel_id}/levels")
def add_signal_level(channel_id: str, body: dict = Body(...), m: Maintenance = Depends(maintenance_write)) -> JSONResponse:
    return _run(m.add_signal_level, channel_id, body.get("name", ""), body.get("stat"), body.get("axis"),
                body.get("alarm_above"), body.get("alarm_below"), body.get("warn_above"), body.get("warn_below"))


@router.patch("/signals/bands/{point_id}")
def update_signal_band(point_id: str, body: dict = Body(...), m: Maintenance = Depends(maintenance_write)) -> JSONResponse:
    """Change a band's name, limits or range (a new range starts a new version from now)."""
    keys = ("name", "low", "high", "axis", "unit", "alarm_above", "alarm_below", "warn_above", "warn_below")
    return _run(m.update_signal_band, point_id, **{k: body[k] for k in keys if k in body})


@router.get("/signals/storage")
def signal_storage(m: Maintenance = Depends(maintenance)) -> JSONResponse:
    return _run(m.signal_storage)


@router.put("/signals/storage-cap")
def set_signal_storage_cap(body: dict = Body(...), m: Maintenance = Depends(maintenance_write)) -> JSONResponse:
    return _run(m.set_signal_storage_cap, body.get("cap_mb"))


@router.post("/signals/bands/{point_id}/remove")
def remove_signal_band(point_id: str, m: Maintenance = Depends(maintenance_write)) -> JSONResponse:
    return _run(m.remove_signal_band, point_id)


@router.get("/points")
def points_at(position_ids: str = "", item_ids: str = "", m: Maintenance = Depends(maintenance)) -> JSONResponse:
    """The measurement points on several positions and items (comma-separated ids):
    the Explorer's Measurements tab reads a branch of the tree with it."""
    positions = [i.strip() for i in position_ids.split(",") if i.strip()]
    items = [i.strip() for i in item_ids.split(",") if i.strip()]
    return _run(m.points_at, positions, items)


@router.get("/points/{point_id}")
def get_point(point_id: str, m: Maintenance = Depends(maintenance)) -> JSONResponse:
    return _run(m.point, point_id)


@router.patch("/points/{point_id}")
def update_point(point_id: str, body: dict = Body(...), m: Maintenance = Depends(maintenance_write)) -> JSONResponse:
    return _run(m.update_point, point_id, **{k: body[k] for k in ("name", "alarm_above", "alarm_below", "tag", "kind",
                                                                  "range_min", "range_max") if k in body})


@router.post("/points/{point_id}/move")
def move_point(point_id: str, body: dict = Body(...), m: Maintenance = Depends(maintenance_write)) -> JSONResponse:
    """To another position (position_id): a position's measurement point, with its readings."""
    return _run(m.move_point, point_id, body.get("position_id"))


@router.post("/points/{point_id}/readings")
def record_reading(point_id: str, body: dict = Body(...), m: Maintenance = Depends(maintenance_write)) -> JSONResponse:
    return _run(m.record_reading, point_id, body.get("value"), body.get("on"), body.get("note", ""),
                body.get("at"), body.get("precision"), body.get("work_order_id"), body.get("task_id"))


@router.post("/readings/{reading_id}/void")
def void_reading(reading_id: str, body: dict = Body(default={}),
                 m: Maintenance = Depends(maintenance_write)) -> JSONResponse:
    """Strike out a manual reading, with the reason (required). Returns the point."""
    return _run(m.void_reading, reading_id, body.get("reason", ""))


@router.post("/readings/{reading_id}/correct")
def correct_reading(reading_id: str, body: dict = Body(...),
                    m: Maintenance = Depends(maintenance_write)) -> JSONResponse:
    """Correct a manual reading's value and/or date (``value``, ``on``), with the reason
    (required): the original is struck out and the corrected one recorded. Returns the point."""
    return _run(m.correct_reading, reading_id, body.get("value"), body.get("on"), body.get("reason", ""),
                body.get("at"), body.get("precision"), body.get("note"))


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
def retire_group(group_id: str, body: dict = Body(default={}), m: Maintenance = Depends(maintenance_write)) -> JSONResponse:
    return _run(lambda: (m.retire_group(group_id, body.get("reason", "")), {"retired": group_id})[1])


@router.get("/positions/{position_id}/impact")
def impact(position_id: str, m: Maintenance = Depends(maintenance)) -> JSONResponse:
    return _run(m.impact, position_id)


@router.post("/positions/{position_id}/rbd")
def generate_rbd(position_id: str, session=Depends(get_session), m: Maintenance = Depends(maintenance_write)) -> JSONResponse:
    from backend.maintenance import rbd_derive

    return _run(rbd_derive.save, m, session, position_id)


# ---- graph queries in Cypher (#423): owner-only ------------------------------------------
# 404 for everyone but graph_query_allowed, as if the routes weren't there.

def graph_access(ctx: AccessCtx = Depends(get_access)) -> AccessCtx:
    from backend.maintenance.access import graph_query_allowed

    if not graph_query_allowed(ctx.user):
        raise HTTPException(status_code=404, detail="Not found.")
    return ctx


def _graph(fn, *args) -> JSONResponse:
    from backend.maintenance.graph_cypher import GraphQueryError

    try:
        return JSONResponse(content=fn(*args))
    except GraphQueryError as err:
        return JSONResponse(status_code=err.status, content={"detail": client_message(err)})


def _readable(ctx: AccessCtx) -> list[str]:
    return [o for o in ctx.read_owners if o != config.SAMPLE_OWNER]


@router.post("/graph/query")
def graph_query(body: dict = Body(...), ctx: AccessCtx = Depends(graph_access)) -> JSONResponse:
    """Read-only Cypher on the workspace's graph in the Neo4j mirror: {cypher, params?,
    limit?, include_props?} (backend/maintenance/graph_cypher.py)."""
    from backend.maintenance import graph_cypher

    unknown = set(body) - {"cypher", "params", "limit", "include_props"}
    if unknown:
        return JSONResponse(status_code=422, content={"detail": f"Unknown fields: {', '.join(sorted(unknown))}."})
    return _graph(graph_cypher.run_query, get_store(), ctx.write_owner, body.get("cypher"), body.get("params"),
                  body.get("limit"), bool(body.get("include_props")), _readable(ctx))


@router.get("/graph/schema")
def graph_schema(ctx: AccessCtx = Depends(graph_access)) -> JSONResponse:
    """The workspace's graph as graph queries see it: labels, relationships, conventions,
    worked examples, limits and how current the mirror is."""
    from backend.maintenance import graph_cypher

    return _graph(graph_cypher.graph_schema, get_store(), ctx.write_owner, _readable(ctx))


@router.get("/graph/design")
def graph_design(ctx: AccessCtx = Depends(graph_access)) -> JSONResponse:
    """The intended shape of the graph, for the Data model page: the ``data_model``
    document in app_settings, checked ({available: false, reason} without one).
    Read only; nothing in the app writes it (backend/maintenance/graph_design.py)."""
    from backend.maintenance import graph_design as design

    return JSONResponse(content=design.load(get_db()))


# ---- products: design trees, and the items built from them ------------------------------

@router.get("/products")
def list_products(m: Maintenance = Depends(maintenance)) -> JSONResponse:
    """Every product (a design tree): its part, revision, positions, items built and their open reports."""
    return _run(m.products)


@router.post("/products")
def create_product(body: dict = Body(...), m: Maintenance = Depends(maintenance_write)) -> JSONResponse:
    """A product: its design's top position and its part (part_number: a new one; part_id: one in the
    catalogue), declared together."""
    return _run(m.create_product, body.get("name"), body.get("part_number", ""), body.get("rev", ""),
                body.get("description", ""), body.get("part_id"))


@router.get("/products/{product_id}")
def get_product(product_id: str, m: Maintenance = Depends(maintenance)) -> JSONResponse:
    return _run(m.product, product_id)


@router.get("/products/{product_id}/items")
def product_items(product_id: str, m: Maintenance = Depends(maintenance)) -> JSONResponse:
    """The items built from a product, by serial."""
    return _run(m.product_items, product_id)


@router.post("/products/{product_id}/build")
def build_item(product_id: str, body: dict = Body(...), m: Maintenance = Depends(maintenance_write)) -> JSONResponse:
    """Build an item from a product by serial (dry_run, the default, only says what it would make)."""
    return _run(m.build_item, product_id, body.get("serial"), body.get("rev"), body.get("name"),
                body.get("dry_run", True) is not False)


@router.post("/products/{product_id}/make-own")
def make_sample_own(product_id: str, m: Maintenance = Depends(maintenance_write)) -> JSONResponse:
    """Make a copy of the sample product your own, in place: "(sample)" goes from its name, nothing
    inside changes, and the sample is never added again beside it unless asked."""
    return _run(m.clear_sample, product_id)


@router.delete("/products/{product_id}/design")
def clear_design(product_id: str, m: Maintenance = Depends(maintenance_write)) -> JSONResponse:
    """The tree isn't a product's design any more."""
    return _run(m.clear_design, product_id)


@router.put("/positions/{position_id}/design")
def declare_design(position_id: str, body: dict = Body(default={}),
                   m: Maintenance = Depends(maintenance_write)) -> JSONResponse:
    """Make a top-level tree a product's design, or change its rev or part."""
    return _run(m.declare_design, position_id, body.get("part_id"), body.get("rev"))


@router.get("/positions/{position_id}/design-rollup")
def design_rollup(position_id: str, m: Maintenance = Depends(maintenance)) -> JSONResponse:
    """A design position across every item built from its product."""
    return _run(m.design_rollup, position_id)


# ---- items and locations ---------------------------------------------------------------

@router.get("/items/overview")
def items_overview(product_id: str | None = None, item_class_id: str | None = None, q: str | None = None,
                   limit: int = 100, offset: int = 0, m: Maintenance = Depends(maintenance)) -> JSONResponse:
    """Every item with its product, item class, position path, status and open failure reports;
    filtered and paged (before /items/{item_id})."""
    return _run(m.items_overview, product_id or None, item_class_id or None, q or None, limit, offset)


@router.get("/items")
def list_items(item_class_id: str | None = None, manufacturer_id: str | None = None,
               m: Maintenance = Depends(maintenance)) -> JSONResponse:
    """Items; item_class_id (with the classes inside it) and manufacturer_id filter them
    ("none": those with none)."""
    return _run(lambda: {"items": m.items(item_class_id, manufacturer_id)})


@router.post("/items")
def create_item(body: dict = Body(...), m: Maintenance = Depends(maintenance_write)) -> JSONResponse:
    return _run(lambda: m.item(m.create_item(body.get("name"), body.get("serial", ""), body.get("part_number", ""),
                                             body.get("manufacturer", ""), body.get("notes", ""),
                                             part_id=body.get("part_id"),
                                             **{k: body[k] for k in Maintenance.ITEM_DETAILS if k in body})["id"]))


@router.get("/items/{item_id}")
def get_item(item_id: str, m: Maintenance = Depends(maintenance)) -> JSONResponse:
    return _run(m.item, item_id)


@router.patch("/items/{item_id}")
def update_item(item_id: str, body: dict = Body(...), m: Maintenance = Depends(maintenance_write)) -> JSONResponse:
    return _run(m.update_item, item_id, body.get("nameplate"), body.get("append_note"),
                **{k: body[k] for k in (*Maintenance.ITEM_FIELDS, *Maintenance.ITEM_DETAILS) if k in body})


@router.put("/items/{item_id}/attributes")
def set_item_attributes(item_id: str, body: dict = Body(...), m: Maintenance = Depends(maintenance_write)) -> JSONResponse:
    """{values: {attribute name: value}}: checked against the item's class."""
    return _run(m.set_item_attributes, item_id, body.get("values"))


@router.put("/items/{item_id}/part")
def set_item_part(item_id: str, body: dict = Body(...), m: Maintenance = Depends(maintenance_write)) -> JSONResponse:
    """{part_id}: the catalogue part (make and model) the item is; null unlinks it."""
    return _run(m.set_item_part, item_id, body.get("part_id"))


@router.post("/items/{item_id}/move")
def move_item(item_id: str, body: dict = Body(...), m: Maintenance = Depends(maintenance_write)) -> JSONResponse:
    return _run(m.move_item, item_id, body.get("position_id"), body.get("on"))


@router.post("/items/{item_id}/place")
def place_item(item_id: str, body: dict = Body(...), m: Maintenance = Depends(maintenance_write)) -> JSONResponse:
    return _run(m.place_item, item_id, body.get("location_id"), body.get("on"))


@router.get("/locations")
def list_locations(of: str | None = None, m: Maintenance = Depends(maintenance)) -> JSONResponse:
    """The places you look after; of: a product's id (its design locations) or a built
    item's top position (the locations it carries) instead."""
    return _run(lambda: {"locations": m.locations(of), "tree": m.location_tree(of)})


@router.get("/places")
def list_places(m: Maintenance = Depends(maintenance)) -> JSONResponse:
    """The assets: each top-level location with the positions, items, open work orders
    and tasks due in 30 days anywhere inside it; not_placed: the positions with no
    location (and their ids)."""
    return _run(m.places)


@router.get("/locations/{location_id}")
def get_location(location_id: str, m: Maintenance = Depends(maintenance)) -> JSONResponse:
    return _run(m.location, location_id)


@router.post("/locations/adopt-placements")
def adopt_placements(body: dict = Body(default={}), m: Maintenance = Depends(maintenance_write)) -> JSONResponse:
    """Fitted items' placements as their positions' locations (a one-off tidy-up);
    dry_run (default true) only lists what would change."""
    return _run(m.adopt_placements, body.get("dry_run", True) is not False)


@router.patch("/locations/{location_id}")
def update_location(location_id: str, body: dict = Body(...), m: Maintenance = Depends(maintenance_write)) -> JSONResponse:
    kwargs = {k: body[k] for k in ("name", "description", "parent_id") if k in body}
    return _run(m.update_location, location_id, **kwargs)


@router.post("/locations")
def create_location(body: dict = Body(...), m: Maintenance = Depends(maintenance_write)) -> JSONResponse:
    return _run(m.create_location, body.get("name"), body.get("parent_id"), body.get("description", ""),
                body.get("design_of"))


# ---- work orders -------------------------------------------------------------------------

@router.get("/work-orders")
def list_work_orders(status: str | None = None, location_id: str | None = None,
                     m: Maintenance = Depends(maintenance)) -> JSONResponse:
    """Work orders, newest first; status 'open' for every one not yet done; location_id for
    the work in that area: on positions there, items there now, and the location itself (or
    locations inside it)."""
    return _run(lambda: {"work_orders": m.work_orders(status, location_id)})


@router.post("/work-orders")
def open_work_order(body: dict = Body(...), m: Maintenance = Depends(maintenance_write)) -> JSONResponse:
    """On a position, an item or a location (exactly one of position_id, item_id, location_id;
    from a task, the task's when none is given). include_positions: a location's work order
    lists the positions there on its checklist."""
    return _run(m.open_work_order, body.get("position_id"), body.get("title"), body.get("type", "corrective"),
                body.get("task_id"), body.get("due"), body.get("notes", ""), body.get("trade"),
                body.get("item_id"), body.get("location_id"), body.get("include_positions"))


@router.post("/work-orders/generate")
def generate_work_orders(horizon_days: int = Body(30, embed=True),
                         m: Maintenance = Depends(maintenance_write)) -> JSONResponse:
    return _run(m.generate, max(0, min(horizon_days, 366)))


@router.patch("/work-orders/{work_order_id}")
def update_work_order(work_order_id: str, body: dict = Body(...),
                      m: Maintenance = Depends(maintenance_write)) -> JSONResponse:
    return _run(m.update_work_order, work_order_id, body.get("title"), body.get("due") if "due" in body else None,
                body.get("notes"), body.get("type"), body.get("assignee"),
                body.get("planned_for") if "planned_for" in body else None, body.get("append_note"),
                body.get("trade"), body.get("readings"))


@router.post("/work-orders/{work_order_id}/readings")
def record_work_order_readings(work_order_id: str, body: dict = Body(...),
                               m: Maintenance = Depends(maintenance_write)) -> JSONResponse:
    """Readings and settings taken at the work order, recorded now (the page's Record):
    readings [{point_id, value, unit?, on?, task_id?, note?}]. Returns the work order."""
    return _run(m.record_work_order_readings, work_order_id, body.get("readings") or [])


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
def list_parts(item_class_id: str | None = None, manufacturer_id: str | None = None,
               m: Maintenance = Depends(maintenance)) -> JSONResponse:
    return _run(lambda: {"parts": m.parts(item_class_id, manufacturer_id)})


@router.post("/parts")
def create_part(body: dict = Body(...), m: Maintenance = Depends(maintenance_write)) -> JSONResponse:
    return _run(m.create_part, body.get("part_number"), body.get("name"), body.get("manufacturer", ""),
                body.get("unit", "each"), body.get("unit_cost"), body.get("notes", ""), body.get("item_class_id"),
                body.get("manufacturer_id"))


# ---- product structure: parts made of parts (#435) ---------------------------------------
# (Before /parts/{part_id}, so /parts/levels isn't read as a part id.)

@router.get("/parts/levels")
def part_levels(m: Maintenance = Depends(maintenance)) -> JSONResponse:
    """The indenture levels, top first, with how many parts are at each."""
    return _run(m.part_level_list)


@router.put("/parts/levels")
def set_part_levels(body: dict = Body(...), m: Maintenance = Depends(maintenance_write)) -> JSONResponse:
    """{levels: [names, top first], renamed: {old: new}}."""
    return _run(m.set_part_levels, body.get("levels"), body.get("renamed"))


@router.post("/parts/import-bom")
async def import_bom(file: UploadFile = File(...), dry_run: bool = Form(True), sheet: str | None = Form(None),
                     header_row: str | None = Form(None), mapping: str | None = Form(None),
                     levels_by_depth: bool = Form(False),
                     m: Maintenance = Depends(maintenance_write)) -> JSONResponse:
    """A BOM from CSV or Excel: one row per parent -> child line, or an indented BOM with
    a level on each row (see bom.py). sheet and header_row pick an Excel sheet's table
    (blank: the first sheet, its header guessed); mapping ({field: column}, JSON) overrides
    the guessed columns; levels_by_depth names an indented BOM's parts' indenture levels
    from the workspace's list, top first. A dry run (the default) only reports."""
    import json

    from backend.maintenance import bom
    from backend.routers.excel import header_row_param
    from backend.services import excel

    data = await file.read(10 * 1024 * 1024 + 1)
    if len(data) > 10 * 1024 * 1024:
        return JSONResponse(status_code=413, content={"detail": "The file is over 10 MB."})
    try:
        cols = json.loads(mapping) if mapping else None
        if cols is not None and not isinstance(cols, dict):
            raise ValueError
    except ValueError:
        return JSONResponse(status_code=422, content={"detail": "mapping is {field: column} as JSON."})
    try:
        header, rows = await run_in_threadpool(bom.table_from_file, data, file.filename or "", sheet or None,
                                               header_row_param(header_row))
    except (Invalid, excel.ExcelError) as err:
        return JSONResponse(status_code=422, content={"detail": client_message(err)})
    except Exception:  # noqa: BLE001 - an unreadable file
        return JSONResponse(status_code=422, content={"detail": "That file couldn't be read as CSV or Excel."})
    def go() -> JSONResponse:
        return _run(bom.run, m, header, rows, dry_run, cols, m.part_levels() if levels_by_depth else None)

    return await run_in_threadpool(go)


@router.get("/parts/{part_id}/structure")
def part_structure(part_id: str, m: Maintenance = Depends(maintenance)) -> JSONResponse:
    """The part's structure as a tree, and the quantities rolled up."""
    return _run(m.part_structure, part_id)


@router.post("/parts/{part_id}/structure")
def add_component(part_id: str, body: dict = Body(...), m: Maintenance = Depends(maintenance_write)) -> JSONResponse:
    """{child_id, quantity, ref}: returns the structure."""
    return _run(m.add_component, part_id, body.get("child_id"), body.get("quantity", 1), body.get("ref", ""))


@router.patch("/parts/{part_id}/structure/{child_id}")
def update_component(part_id: str, child_id: str, body: dict = Body(...),
                     m: Maintenance = Depends(maintenance_write)) -> JSONResponse:
    return _run(m.update_component, part_id, child_id, body.get("quantity"), body.get("ref"))


@router.delete("/parts/{part_id}/structure/{child_id}")
def remove_component(part_id: str, child_id: str, m: Maintenance = Depends(maintenance_write)) -> JSONResponse:
    return _run(m.remove_component, part_id, child_id)


@router.post("/parts/{part_id}/structure/positions")
def positions_from_structure(part_id: str, body: dict = Body(default={}),
                             m: Maintenance = Depends(maintenance_write)) -> JSONResponse:
    """{parent_id, levels (null: every part), dry_run (default true)}: positions made from the structure."""
    return _run(m.positions_from_structure, part_id, body.get("parent_id"), body.get("levels"),
                body.get("dry_run", True) is not False)


@router.get("/parts/{part_id}/where-used")
def where_used(part_id: str, m: Maintenance = Depends(maintenance)) -> JSONResponse:
    """The parts it's in, the positions listing it or fitted with one, and the items of it."""
    return _run(m.where_used, part_id)


@router.put("/parts/{part_id}/level")
def set_part_level(part_id: str, body: dict = Body(...), m: Maintenance = Depends(maintenance_write)) -> JSONResponse:
    """{level}: one of the indenture levels ('' clears it)."""
    return _run(m.set_part_level, part_id, body.get("level"))


@router.get("/parts/{part_id}")
def get_part(part_id: str, m: Maintenance = Depends(maintenance)) -> JSONResponse:
    return _run(m.part, part_id)


@router.patch("/parts/{part_id}")
def update_part(part_id: str, body: dict = Body(...), m: Maintenance = Depends(maintenance_write)) -> JSONResponse:
    return _run(m.update_part, part_id, **{k: body[k] for k in ("name", "manufacturer", "unit", "notes", "unit_cost",
                                                                "lead_time_days", "service_level", "repairable",
                                                                "turnaround_days")
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


# ---- item classes and manufacturers (optional) -------------------------------------------

@router.get("/item-classes")
def item_classes(m: Maintenance = Depends(maintenance)) -> JSONResponse:
    """The item class tree with counts, and every class flat by path (for pickers)."""
    return _run(lambda: {**m.item_class_tree(), "classes": m.item_classes()})


@router.post("/item-classes")
def create_item_class(body: dict = Body(...), m: Maintenance = Depends(maintenance_write)) -> JSONResponse:
    return _run(m.create_item_class, body.get("name"), body.get("parent_id"), body.get("code", ""),
                body.get("level", ""), body.get("description", ""), body.get("attributes"))


@router.get("/item-classes/export")
def export_item_classes(format: str = "json", m: Maintenance = Depends(maintenance)) -> Response:
    from backend.maintenance import taxonomy

    if format == "csv":
        return Response(taxonomy.export_csv(m), media_type="text/csv",
                        headers={"Content-Disposition": 'attachment; filename="item-classes.csv"'})
    out = _run(taxonomy.export_json, m)
    out.headers["Content-Disposition"] = 'attachment; filename="item-classes.json"'
    return out


@router.post("/item-classes/import")
def import_item_classes(body: dict = Body(...), m: Maintenance = Depends(maintenance_write)) -> JSONResponse:
    """A taxonomy as CSV or JSON text ({format: csv | json, text, dry_run, source}) or as
    {classes: [...]}. A dry run (the default) only reports."""
    from backend.maintenance import taxonomy

    def go():
        if body.get("classes") is not None:
            rows = taxonomy.rows_from_json(body["classes"])
        elif body.get("format") == "csv":
            rows = taxonomy.rows_from_csv(str(body.get("text") or ""))
        else:
            rows = taxonomy.rows_from_json(str(body.get("text") or ""))
        return taxonomy.run(m, rows, body.get("dry_run", True) is not False, body.get("source") or "imported")
    return _run(go)


@router.post("/item-classes/starter")
def load_starter_item_classes(body: dict = Body(default={}), m: Maintenance = Depends(maintenance_write)) -> JSONResponse:
    """The Reliafy starter taxonomy, only on request; {dry_run} (default true)."""
    from backend.maintenance import taxonomy

    return _run(taxonomy.load_starter, m, body.get("dry_run", True) is not False)


@router.post("/item-classes/assign")
def assign_item_class(body: dict = Body(...), m: Maintenance = Depends(maintenance_write)) -> JSONResponse:
    """{target_id: an item or part, item_class_id (null takes it away)}."""
    return _run(m.assign_item_class, body.get("target_id"), body.get("item_class_id"))


@router.get("/item-classes/{class_id}")
def get_item_class(class_id: str, m: Maintenance = Depends(maintenance)) -> JSONResponse:
    return _run(m.item_class, class_id)


@router.patch("/item-classes/{class_id}")
def update_item_class(class_id: str, body: dict = Body(...), m: Maintenance = Depends(maintenance_write)) -> JSONResponse:
    """name, code, level, description, attributes; parent_id moves it (null: to the top)."""
    return _run(m.update_item_class, class_id, **{k: body[k] for k in (
        "name", "code", "level", "description", "parent_id", "attributes") if k in body})


@router.post("/item-classes/{class_id}/retire")
def retire_item_class(class_id: str, body: dict = Body(default={}),
                      m: Maintenance = Depends(maintenance_write)) -> JSONResponse:
    return _run(lambda: (m.retire_item_class(class_id, body.get("reason", "")), {"retired": class_id})[1])


# ---- conditions: what things are exposed to (optional) -------------------------------------

@router.get("/conditions")
def list_conditions(m: Maintenance = Depends(maintenance)) -> JSONResponse:
    """The condition register as a tree with counts, and every condition flat by path (for pickers)."""
    return _run(lambda: {**m.condition_tree(), "conditions": m.conditions()})


@router.post("/conditions")
def create_condition(body: dict = Body(...), m: Maintenance = Depends(maintenance_write)) -> JSONResponse:
    return _run(m.create_condition, body.get("name"), body.get("parent_id"), body.get("kind"), body.get("unit", ""),
                body.get("code", ""), body.get("description", ""))


@router.get("/conditions/export")
def export_conditions(format: str = "json", m: Maintenance = Depends(maintenance)) -> Response:
    from backend.maintenance import conditions

    if format == "csv":
        return Response(conditions.export_csv(m), media_type="text/csv",
                        headers={"Content-Disposition": 'attachment; filename="conditions.csv"'})
    out = _run(conditions.export_json, m)
    out.headers["Content-Disposition"] = 'attachment; filename="conditions.json"'
    return out


@router.post("/conditions/import")
def import_conditions(body: dict = Body(...), m: Maintenance = Depends(maintenance_write)) -> JSONResponse:
    """A register as CSV or JSON text ({format: csv | json, text, dry_run, source}) or as
    {conditions: [...]}. A dry run (the default) only reports."""
    from backend.maintenance import conditions

    def go():
        if body.get("conditions") is not None:
            rows = conditions.rows_from_json(body["conditions"])
        elif body.get("format") == "csv":
            rows = conditions.rows_from_csv(str(body.get("text") or ""))
        else:
            rows = conditions.rows_from_json(str(body.get("text") or ""))
        return conditions.run(m, rows, body.get("dry_run", True) is not False, body.get("source") or "imported")
    return _run(go)


@router.get("/conditions/of/{target_id}")
def conditions_of(target_id: str, m: Maintenance = Depends(maintenance)) -> JSONResponse:
    """A location's, position's, item's or connection's conditions, with where each comes from."""
    return _run(m.conditions_of, target_id)


@router.post("/conditions/of/{target_id}")
def set_target_condition(target_id: str, body: dict = Body(...),
                         m: Maintenance = Depends(maintenance_write)) -> JSONResponse:
    """{condition_id, action: apply (value, note) | exclude (note) | remove}: returns the target's conditions."""
    action, condition_id = body.get("action") or "apply", body.get("condition_id")
    if action == "exclude":
        return _run(m.exclude_condition, target_id, condition_id, body.get("note", ""))
    if action == "remove":
        return _run(m.remove_condition, target_id, condition_id)
    if action != "apply":
        return JSONResponse(status_code=422, content={"detail": "The action is apply, exclude or remove."})
    return _run(m.apply_condition, target_id, condition_id, body.get("value"), body.get("note", ""))


@router.get("/conditions/{condition_id}")
def get_condition(condition_id: str, m: Maintenance = Depends(maintenance)) -> JSONResponse:
    return _run(m.condition, condition_id)


@router.patch("/conditions/{condition_id}")
def update_condition(condition_id: str, body: dict = Body(...),
                     m: Maintenance = Depends(maintenance_write)) -> JSONResponse:
    """name, kind, unit, code, description; parent_id moves it (null: to the top)."""
    return _run(m.update_condition, condition_id, **{k: body[k] for k in (
        "name", "kind", "unit", "code", "description", "parent_id") if k in body})


@router.post("/conditions/{condition_id}/retire")
def retire_condition(condition_id: str, body: dict = Body(default={}),
                     m: Maintenance = Depends(maintenance_write)) -> JSONResponse:
    return _run(lambda: (m.retire_condition(condition_id, body.get("reason", "")), {"retired": condition_id})[1])


@router.get("/manufacturers")
def list_manufacturers(m: Maintenance = Depends(maintenance)) -> JSONResponse:
    return _run(lambda: {"manufacturers": m.manufacturers()})


@router.post("/manufacturers")
def create_manufacturer(body: dict = Body(...), m: Maintenance = Depends(maintenance_write)) -> JSONResponse:
    return _run(m.create_manufacturer, body.get("name"), body.get("aliases") or [])


@router.get("/manufacturers/match")
def match_manufacturer(text: str, m: Maintenance = Depends(maintenance)) -> JSONResponse:
    return _run(m.match_manufacturer, text)


@router.post("/manufacturers/link")
def link_manufacturer(body: dict = Body(...), m: Maintenance = Depends(maintenance_write)) -> JSONResponse:
    """{target_id: an item or part, manufacturer_id (null unlinks it)}."""
    return _run(m.link_manufacturer, body.get("target_id"), body.get("manufacturer_id"))


@router.post("/manufacturers/link-by-name")
def link_manufacturers_by_name(body: dict = Body(default={}),
                               m: Maintenance = Depends(maintenance_write)) -> JSONResponse:
    return _run(m.link_manufacturers_by_name, body.get("dry_run", True) is not False)


@router.get("/manufacturers/{manufacturer_id}")
def get_manufacturer(manufacturer_id: str, m: Maintenance = Depends(maintenance)) -> JSONResponse:
    return _run(m.manufacturer, manufacturer_id)


@router.patch("/manufacturers/{manufacturer_id}")
def update_manufacturer(manufacturer_id: str, body: dict = Body(...),
                        m: Maintenance = Depends(maintenance_write)) -> JSONResponse:
    """name; add_aliases, remove_aliases."""
    return _run(m.update_manufacturer, manufacturer_id, body.get("name"), body.get("add_aliases") or [],
                body.get("remove_aliases") or [])


@router.post("/manufacturers/{manufacturer_id}/merge")
def merge_manufacturers(manufacturer_id: str, body: dict = Body(...),
                        m: Maintenance = Depends(maintenance_write)) -> JSONResponse:
    return _run(m.merge_manufacturers, manufacturer_id, body.get("into_id"))


# ---- a position's parts list, and where the spares fall short -----------------------------

@router.get("/positions/{position_id}/parts")
def position_parts(position_id: str, m: Maintenance = Depends(maintenance)) -> JSONResponse:
    return _run(m.position_parts, position_id)


@router.post("/positions/{position_id}/parts")
def add_position_part(position_id: str, body: dict = Body(...), m: Maintenance = Depends(maintenance_write)) -> JSONResponse:
    return _run(m.add_position_part, position_id, body.get("part_id"), body.get("role") or "component",
                body.get("quantity", 1), body.get("critical", False), body.get("min_on_hand"), body.get("notes", ""))


@router.patch("/position-parts/{listing_id}")
def update_position_part(listing_id: str, body: dict = Body(...),
                         m: Maintenance = Depends(maintenance_write)) -> JSONResponse:
    return _run(m.update_position_part, listing_id, body.get("role"), body.get("quantity"), body.get("critical"),
                body["min_on_hand"] if "min_on_hand" in body else ..., body.get("notes"))


@router.delete("/position-parts/{listing_id}")
def remove_position_part(listing_id: str, m: Maintenance = Depends(maintenance_write)) -> JSONResponse:
    return _run(m.remove_position_part, listing_id)


@router.get("/spares")
def spares_cover(include_unlisted: bool = False, m: Maintenance = Depends(maintenance)) -> JSONResponse:
    return _run(m.spares_cover, include_unlisted)


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
                body.get("readings") or [], body.get("not_done") or [])


@router.put("/work-orders/{work_order_id}/lines/{task_id}")
def mark_line(work_order_id: str, task_id: str, body: dict = Body(...),
              m: Maintenance = Depends(maintenance_write)) -> JSONResponse:
    """A work package's line marked during the visit, saved at once: state todo, done, not_done
    (reason) or problem (finding: an action recorded at the line's position when it closes)."""
    return _run(m.mark_line, work_order_id, task_id, body.get("state"), body.get("reason"), body.get("finding"))


# ---- work packages: tasks done on one visit, one work order per visit ---------------------

@router.get("/packages")
def list_packages(status: str | None = None, position_id: str | None = None, location_id: str | None = None,
                  m: Maintenance = Depends(maintenance)) -> JSONResponse:
    """Every work package (status active, paused, retired or all; default: not retired), with
    its next visit and open work order (late, days_late, visits_missed). position_id or
    location_id: those there or inside it, or holding a task there (the Explorer's Packages tab)."""
    return _run(m.packages, status, position_id, location_id)


@router.get("/task-table")
def task_table(position_id: str | None = None, location_id: str | None = None,
               m: Maintenance = Depends(maintenance)) -> JSONResponse:
    """Every task on a position or location and below it, one row each, for the Explorer's
    Packages tab: where, failure modes, kind, interval, trade, next due, package."""
    return _run(m.task_table, position_id, location_id)


@router.get("/packages/propose")
def propose_packages(position_id: str | None = None, location_id: str | None = None, weekday: str | None = None,
                     m: Maintenance = Depends(maintenance)) -> JSONResponse:
    """Drafts of packages from the tasks in none, by cadence, area and trade; weekday: visits on
    that day, the longer cadences as layers on the shortest. Saves nothing."""
    return _run(m.propose_packages, position_id, location_id, weekday)


@router.post("/packages/batch")
def create_packages(body: dict = Body(...), m: Maintenance = Depends(maintenance_write)) -> JSONResponse:
    """Several packages at once (Package the tasks…): packages [{ref?, ...a create's fields}], a
    layer's parent_id '@<an earlier one's ref>'. All or nothing."""
    return _run(m.create_packages, body.get("packages"))


@router.get("/packages/{package_id}")
def get_package(package_id: str, m: Maintenance = Depends(maintenance)) -> JSONResponse:
    return _run(m.package, package_id)


_PACKAGE_FIELDS = ("name", "timing", "every", "unit", "weekday", "nth", "day", "anchor", "tolerance", "tolerance_unit",
                   "trade", "notes", "tasks")


@router.post("/packages")
def create_package(body: dict = Body(...), m: Maintenance = Depends(maintenance_write)) -> JSONResponse:
    """On exactly one of position_id or location_id, or a layer on parent_id; tasks: task ids or
    {task_id, visit_rule, every_nth, suppresses}."""
    return _run(m.create_package, body.get("name"), body.get("position_id"), body.get("location_id"),
                body.get("parent_id"), body.get("timing") or "fixed", body.get("every", 1),
                body.get("unit") or "weeks", body.get("weekday"), body.get("nth"), body.get("day"),
                body.get("anchor"), body.get("tolerance"), body.get("tolerance_unit"), body.get("trade", ""),
                body.get("notes", ""), body.get("tasks"), body.get("season"))


@router.patch("/packages/{package_id}")
def update_package(package_id: str, body: dict = Body(...), m: Maintenance = Depends(maintenance_write)) -> JSONResponse:
    """Change its name, cadence, tolerance, trade, notes, or members' visit rules (tasks);
    clear_pattern true removes its pattern."""
    return _run(m.update_package, package_id, clear_pattern=bool(body.get("clear_pattern")),
                season=body["season"] if "season" in body else ..., **{k: body.get(k) for k in _PACKAGE_FIELDS})


@router.post("/{kind}/{target_id}/out-of-service")
def out_of_service(kind: str, target_id: str, body: dict = Body(...),
                   m: Maintenance = Depends(maintenance_write)) -> JSONResponse:
    """A position or an item (kind positions or items) out of service until a date (or
    open-ended), with a reason: its tasks aren't due or late meanwhile."""
    if kind not in ("positions", "items"):
        raise HTTPException(status_code=404, detail="Not found.")
    return _run(m.take_out_of_service, target_id, body.get("reason"), body.get("until"), body.get("start"))


@router.post("/{kind}/{target_id}/back-in-service")
def back_in_service(kind: str, target_id: str, m: Maintenance = Depends(maintenance_write)) -> JSONResponse:
    if kind not in ("positions", "items"):
        raise HTTPException(status_code=404, detail="Not found.")
    return _run(m.return_to_service, target_id)


@router.post("/packages/{package_id}/tasks")
def add_package_task(package_id: str, body: dict = Body(...), m: Maintenance = Depends(maintenance_write)) -> JSONResponse:
    return _run(m.add_package_task, package_id, body.get("task_id"), body.get("visit_rule"), body.get("every_nth"),
                body.get("suppresses"))


@router.delete("/packages/{package_id}/tasks/{task_id}")
def remove_package_task(package_id: str, task_id: str, m: Maintenance = Depends(maintenance_write)) -> JSONResponse:
    return _run(m.remove_package_task, package_id, task_id)


@router.post("/packages/{package_id}/{change}")
def change_package(package_id: str, change: str, body: dict = Body(default={}),
                   m: Maintenance = Depends(maintenance_write)) -> JSONResponse:
    """pause, resume, retire or restore."""
    if change == "pause":
        return _run(m.pause_package, package_id, body.get("reason", ""), body.get("until"), body.get("full_visit"))
    if change == "retire":
        return _run(m.retire_package, package_id, body.get("reason", ""))
    if change == "resume":
        return _run(m.resume_package, package_id, body.get("full_visit"))
    if change == "restore":
        return _run(m.restore_package, package_id)
    raise HTTPException(status_code=404, detail="Not found.")


# ---- photos and coordinates ----------------------------------------------------------------

@router.post("/photos")
async def add_photo(request: Request, target_id: str, caption: str = "",
                    m: Maintenance = Depends(maintenance_write)) -> JSONResponse:
    """Add a photo (the request body is the image) to a position, location,
    item or work order."""
    try:
        raw = await _read_body(request)
    except photos_mod.BadPhoto as err:
        return JSONResponse(status_code=422, content={"detail": client_message(err)})
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


@router.post("/photos/{photo_id}/link")
def link_photo(photo_id: str, body: dict = Body(...), m: Maintenance = Depends(maintenance_write)) -> JSONResponse:
    """{target_id}: show the photo on another position, location, item or work order too."""
    return _run(m.link_photo, photo_id, str(body.get("target_id") or ""))


@router.post("/photos/{photo_id}/unlink")
def unlink_photo(photo_id: str, body: dict = Body(...), m: Maintenance = Depends(maintenance_write)) -> JSONResponse:
    """{target_id}: take the photo off one place (never its last)."""
    return _run(m.unlink_photo, photo_id, str(body.get("target_id") or ""))


@router.post("/photos/{photo_id}/move")
def move_photo(photo_id: str, body: dict = Body(...), m: Maintenance = Depends(maintenance_write)) -> JSONResponse:
    """{target_id, from_id?}: move the photo off from_id (or off everywhere else) to target_id."""
    return _run(m.move_photo, photo_id, str(body.get("target_id") or ""), body.get("from_id") or None)


@router.post("/coordinates")
def set_coordinates(body: dict = Body(...), m: Maintenance = Depends(maintenance_write)) -> JSONResponse:
    return _run(m.set_coordinates, body.get("node_id"), body.get("lat"), body.get("lon"),
                body.get("source") or "manual")


@router.delete("/coordinates/{node_id}")
def clear_coordinates(node_id: str, m: Maintenance = Depends(maintenance_write)) -> JSONResponse:
    return _run(m.clear_coordinates, node_id)


# ---- retiring the rest of the tree, and restoring anything -------------------------------
# The same service methods the agent's tools call, so the app can offer them.

@router.post("/positions/{position_id}/restore")
def restore_position(position_id: str, body: dict = Body(default={}),
                     m: Maintenance = Depends(maintenance_write)) -> JSONResponse:
    # cascade: undo its latest delete, with everything that took.
    return _run(m.restore_position, position_id, bool((body or {}).get("cascade")))


@router.post("/locations/{location_id}/retire")
def retire_location(location_id: str, body: dict = Body(default={}),
                    m: Maintenance = Depends(maintenance_write)) -> JSONResponse:
    return _run(m.retire_location, location_id, body.get("reason", ""), bool(body.get("cascade")),
                bool(body.get("dry_run")))


@router.post("/locations/{location_id}/restore")
def restore_location(location_id: str, body: dict = Body(default={}),
                     m: Maintenance = Depends(maintenance_write)) -> JSONResponse:
    return _run(m.restore_location, location_id, bool((body or {}).get("cascade")))


@router.post("/items/{item_id}/retire")
def retire_item(item_id: str, body: dict = Body(default={}), m: Maintenance = Depends(maintenance_write)) -> JSONResponse:
    return _run(m.retire_item, item_id, body.get("reason", ""))


@router.post("/items/{item_id}/restore")
def restore_item(item_id: str, m: Maintenance = Depends(maintenance_write)) -> JSONResponse:
    return _run(m.restore_item, item_id)


@router.post("/tasks/{task_id}/restore")
def restore_task(task_id: str, m: Maintenance = Depends(maintenance_write)) -> JSONResponse:
    return _run(m.restore_task, task_id)


@router.post("/failure-modes/{mode_id}/restore")
def restore_failure_mode(mode_id: str, m: Maintenance = Depends(maintenance_write)) -> JSONResponse:
    return _run(m.restore_failure_mode, mode_id)


@router.post("/parts/{part_id}/retire")
def retire_part(part_id: str, body: dict = Body(default={}), m: Maintenance = Depends(maintenance_write)) -> JSONResponse:
    return _run(m.retire_part, part_id, body.get("reason", ""))


@router.post("/parts/{part_id}/restore")
def restore_part(part_id: str, m: Maintenance = Depends(maintenance_write)) -> JSONResponse:
    return _run(m.restore_part, part_id)


@router.post("/parts/{part_id}/unlink")
def unlink_parts(part_id: str, body: dict = Body(...), m: Maintenance = Depends(maintenance_write)) -> JSONResponse:
    """{other_part_id, relation?: superseded_by | interchangeable}: take a wrong link off."""
    return _run(m.unlink_parts, part_id, body.get("other_part_id"), body.get("relation") or "interchangeable")


@router.post("/points/{point_id}/retire")
def retire_point(point_id: str, body: dict = Body(default={}), m: Maintenance = Depends(maintenance_write)) -> JSONResponse:
    return _run(m.retire_point, point_id, body.get("reason", ""))


@router.post("/points/{point_id}/restore")
def restore_point(point_id: str, m: Maintenance = Depends(maintenance_write)) -> JSONResponse:
    return _run(m.restore_point, point_id)


@router.post("/item-classes/{class_id}/restore")
def restore_item_class(class_id: str, m: Maintenance = Depends(maintenance_write)) -> JSONResponse:
    return _run(m.restore_item_class, class_id)


@router.post("/conditions/{condition_id}/restore")
def restore_condition(condition_id: str, m: Maintenance = Depends(maintenance_write)) -> JSONResponse:
    return _run(m.restore_condition, condition_id)


@router.post("/manufacturers/{manufacturer_id}/retire")
def retire_manufacturer(manufacturer_id: str, body: dict = Body(default={}),
                        m: Maintenance = Depends(maintenance_write)) -> JSONResponse:
    return _run(m.retire_manufacturer, manufacturer_id, body.get("reason", ""))


@router.post("/manufacturers/{manufacturer_id}/restore")
def restore_manufacturer(manufacturer_id: str, m: Maintenance = Depends(maintenance_write)) -> JSONResponse:
    return _run(m.restore_manufacturer, manufacturer_id)


@router.patch("/interfaces/{interface_id}")
def update_interface(interface_id: str, body: dict = Body(...), m: Maintenance = Depends(maintenance_write)) -> JSONResponse:
    """{kind?, medium?, name?, rating?, realised_by?: a position id, or null to take it off}."""
    return _run(m.update_interface, interface_id, body.get("kind"), body.get("medium"), body.get("name"),
                body.get("rating"), body["realised_by"] if "realised_by" in body else ...)


@router.post("/interfaces/{interface_id}/restore")
def reconnect(interface_id: str, m: Maintenance = Depends(maintenance_write)) -> JSONResponse:
    return _run(m.reconnect, interface_id)


@router.post("/groups/{group_id}/restore")
def restore_group(group_id: str, m: Maintenance = Depends(maintenance_write)) -> JSONResponse:
    return _run(m.restore_group, group_id)


@router.patch("/documents/{document_id}")
def update_document(document_id: str, body: dict = Body(...), m: Maintenance = Depends(maintenance_write)) -> JSONResponse:
    return _run(m.update_document, document_id, body.get("title"), body.get("kind"))


@router.post("/documents/{document_id}/restore")
def restore_document(document_id: str, m: Maintenance = Depends(maintenance_write)) -> JSONResponse:
    return _run(m.restore_document, document_id)


@router.patch("/photos/{photo_id}")
def update_photo(photo_id: str, body: dict = Body(...), m: Maintenance = Depends(maintenance_write)) -> JSONResponse:
    return _run(m.update_photo, photo_id, body.get("caption"))


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


@public_router.get("/api/maintenance/document-links/{link_id}", include_in_schema=False)
def open_document_link(link_id: str, t: str = "", download: bool = False) -> Response:
    """A stored PDF through a download link (documents.DocumentLinks): the
    link's token is the credential. Anything wrong is the same 404."""
    missing = JSONResponse(status_code=404, content={"detail": "This link isn't valid or has expired (links last "
                                                               f"{documents_mod.LINK_MINUTES} minutes). Read the "
                                                               "document again for a new one."},
                           headers={"Cache-Control": "no-store", "Referrer-Policy": "no-referrer"})
    if not config.MAINTENANCE_ENABLED or not t or len(t) > 100:
        return missing
    link = document_links().get(link_id, t)
    if link is None:
        return missing
    found = served_document(Maintenance(get_store(), link["org"], None), link["document_id"])
    if found is None:
        return missing
    d, data = found
    return Response(content=data, media_type=documents_mod.CONTENT_TYPE,
                    headers=documents_mod.headers(d.get("file_name") or "", download, cache="no-store"))


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


def _by_link(doc: dict) -> Maintenance:
    """The workspace an upload link adds to, in its time zone."""
    return Maintenance(get_store(), doc["org"], doc["uid"], time_zone=time_zones.of_owner(get_db(), doc["org"]))


def _store_by_link(doc: dict, raw: bytes) -> JSONResponse:
    """Clean, store and record a photo sent through a link whose place is
    reserved; the place is given back if the photo isn't kept."""
    links = photo_links()
    try:
        m = _by_link(doc)
        result = ingest_photo(m, doc["target_id"], raw, doc.get("caption", ""), "link")
    except photos_mod.Busy as err:
        links.release(doc["_id"])
        return JSONResponse(status_code=503, content={"detail": client_message(err)}, headers={"Retry-After": "30"})
    except LimitReached as err:
        links.release(doc["_id"])
        return JSONResponse(status_code=err.status, content={"detail": client_message(err)})
    except (photos_mod.BadPhoto, Invalid) as err:
        links.release(doc["_id"])
        return JSONResponse(status_code=422, content={"detail": client_message(err)})
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
        return JSONResponse(status_code=422, content={"detail": client_message(err)})
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
        m = _by_link(doc)
        try:
            m.set_coordinates(doc["target_id"], offer["lat"], offer["lon"], "photo")
        except (Invalid, NotFound) as err:
            return JSONResponse(status_code=422, content={"detail": client_message(err)})
    return JSONResponse(content={"saved": save})


from backend.routers import maintenance_progression  # noqa: E402,F401  (adds its routes to the router)
