"""Reliafy Maintenance for a device that works offline: the changes it queued,
pushed in a batch and recorded once each (``backend/maintenance/sync.py``).

REST only, on purpose (listed in ``api_tools.REST_ONLY``): a push is a batch
of the maintenance tool's own actions with what a device adds to them (an id
per change, its clock, what it saw), and a photo is bytes. An agent has the
actions themselves.

Auth is the ``/api/v1`` model (an API token with the write scope, an OAuth
access token, or the signed-in session), for Reliafy Maintenance's users.
"""

from __future__ import annotations

import json

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool

from backend.errors import client_message

router = APIRouter(prefix="/api/v1/maintenance/sync")

#: These routes as api_tools lists them (REST only, for Reliafy Maintenance's users).
REST_ONLY = {
    "maintenance_sync.push": {
        "method": "POST", "path": "/api/v1/maintenance/sync/push",
        "summary": "Send up to 50 changes a device queued while offline, in the order it made them. Each has an "
                   "id the device made, so one sent twice is recorded once; each is answered applied, duplicate, "
                   "held, needs_decision, retry or refused.",
    },
    "maintenance_sync.photo": {
        "method": "POST", "path": "/api/v1/maintenance/sync/photo",
        "summary": "Send one photo a device queued while offline (the image as the body, its op as JSON in the "
                   "op query parameter). Sent twice, it is stored and recorded once.",
    },
    "maintenance_sync.pack": {
        "method": "POST", "path": "/api/v1/maintenance/sync/pack",
        "summary": "Everything a device needs to work with no connection, in one answer: the open work orders in "
                   "full (or the ones named), their list rows and the parts catalogue. Read scope.",
    },
}


def spec_paths(_ERROR: dict) -> dict:
    """These routes in the OpenAPI spec (api_tools.build_spec)."""
    op = {"type": "object", "required": ["op_id", "device_seq", "command", "device_time"], "properties": {
        "op_id": {"type": "string", "description": "A UUID the device makes for each change."},
        "device_seq": {"type": "integer", "description": "The change's number on the device: 1, 2, 3, …"},
        "command": {"type": "string", "description": "A maintenance action: work_orders.status, .update "
                    "(append_note), .check, .mark, .labour, .part_used, .close, or measurements.record."},
        "args": {"type": "object", "description": "The action's arguments."},
        "expects": {"type": "object", "description": "What the device saw: work_order_status (a list), "
                    "fitment_id, checklist_length, last_reading {point_id, value}."},
        "device_time": {"type": "string", "description": "The device's clock when the change was made (ISO, Z)."},
        "clock_offset_ms": {"type": ["number", "null"], "description": "Server clock minus device clock, if known."},
        "depends_on": {"type": "array", "items": {"type": "string"}, "description": "Earlier op ids it follows."}}}
    answer = {"type": "object", "properties": {
        "op_id": {"type": "string"},
        "status": {"type": "string", "enum": ["applied", "duplicate", "held", "needs_decision", "retry", "refused"]},
        "reason": {"type": "string"}, "message": {"type": "string"}, "waiting_on": {"type": "string"},
        "work_order_id": {"type": "string"}, "point_id": {"type": "string"}}}
    errors = {"401": _ERROR, "402": _ERROR, "403": _ERROR, "404": _ERROR, "422": _ERROR, "429": _ERROR}
    return {
        "/api/v1/maintenance/sync/push": {"post": {
            "operationId": "maintenance_sync.push", "tags": ["rest_only"],
            "summary": REST_ONLY["maintenance_sync.push"]["summary"],
            "requestBody": {"required": True, "content": {"application/json": {"schema": {
                "type": "object", "required": ["ops"], "properties": {
                    "device_id": {"type": "string"}, "device_tz": {"type": "string"},
                    "ops": {"type": "array", "maxItems": 50, "items": op}}}}}},
            "responses": {"200": {"description": "Each op's answer, and what they touched as it is now.",
                                  "content": {"application/json": {"schema": {"type": "object", "properties": {
                                      "ops": {"type": "array", "items": answer},
                                      "work_orders": {"type": "object"}, "points": {"type": "object"},
                                      "server_time": {"type": "string"}, "today": {"type": "string"},
                                      "time_zone": {"type": ["string", "null"]}}}}}}, **errors},
            "x-reliafy-rest-only": True, "x-reliafy-scope": "write"}},
        "/api/v1/maintenance/sync/photo": {"post": {
            "operationId": "maintenance_sync.photo", "tags": ["rest_only"],
            "summary": REST_ONLY["maintenance_sync.photo"]["summary"],
            "parameters": [{"name": "op", "in": "query", "required": True, "schema": {"type": "string"},
                            "description": "The op as JSON: command photos.add, args {target_id, caption?}."}],
            "requestBody": {"required": True, "content": {
                "image/*": {"schema": {"type": "string", "format": "binary"}},
                "multipart/form-data": {"schema": {"type": "object", "properties": {
                    "file": {"type": "string", "format": "binary"}}, "required": ["file"]}}}},
            "responses": {"200": {"description": "The op's answer and the photo."}, "413": _ERROR, **errors},
            "x-reliafy-rest-only": True, "x-reliafy-scope": "write"}},
        "/api/v1/maintenance/sync/pack": {"post": {
            "operationId": "maintenance_sync.pack", "tags": ["rest_only"],
            "summary": REST_ONLY["maintenance_sync.pack"]["summary"],
            "requestBody": {"required": False, "content": {"application/json": {"schema": {
                "type": "object", "properties": {
                    "work_order_ids": {"type": "array", "maxItems": 200, "items": {"type": "string"}},
                    "if_mark": {"type": "integer", "description": "The mark of the pack the device has."}}}}}},
            "responses": {"200": {"description": "{unchanged, briefs, work_orders, gone, more, parts, mark, "
                                                 "server_time, today, time_zone}."}, **errors},
            "x-reliafy-rest-only": True, "x-reliafy-scope": "read"}},
    }


async def _maintenance(request: Request, scope: str = "write"):
    """The caller's Maintenance; 401/402/403/404/429 as on /api/v1."""
    from backend.maintenance.access import allowed
    from backend.maintenance.service import Maintenance
    from backend.routers import api_tools
    from backend.routers import maintenance as maintenance_router
    from backend.services import time_zones
    from backend.services import tokens as tokens_service
    from backend.services import usage as usage_service

    user = await api_tools._caller(request)
    if not allowed(user):
        raise HTTPException(status_code=404, detail="Not found.")
    if not tokens_service.has_scope(user, scope):
        raise HTTPException(status_code=403, detail=tokens_service.scope_message(scope))
    usage_service.note_user(user, channel="api")

    def make():
        return Maintenance(maintenance_router.get_store(), user["uid"], user["uid"],
                           time_zone=time_zones.of_owner(api_tools._db(), user["uid"]))

    return await run_in_threadpool(make)


@router.post("/push")
async def push(request: Request) -> JSONResponse:
    """Up to 50 queued changes, applied in the order the device made them. Each is
    answered applied, duplicate (sent before: nothing recorded twice), held (waits
    on an earlier one), needs_decision (refused, with why), retry or refused."""
    from backend.maintenance import sync
    from backend.maintenance.service import Invalid
    from backend.routers import api_tools
    from backend.services import usage as usage_service

    m = await _maintenance(request)
    usage_service.set_feature("maintenance_create")
    body = await api_tools._body(request)

    def run():
        try:
            return JSONResponse(content=sync.push(m, body))
        except Invalid as err:
            return JSONResponse(status_code=422, content={"detail": client_message(err)})

    return await run_in_threadpool(run)


@router.post("/pack")
async def pack(request: Request) -> JSONResponse:
    """What a device needs to work with no signal: every open work order in full (or
    the ones named), their list rows and the parts catalogue, in one answer. With
    if_mark (the mark of the pack it has), {unchanged: true} when nothing has changed."""
    from backend.maintenance import sync
    from backend.maintenance.service import Invalid
    from backend.routers import api_tools

    m = await _maintenance(request, "read")
    body = await api_tools._body(request)

    def run():
        try:
            return JSONResponse(content=sync.pack(m, body))
        except Invalid as err:
            return JSONResponse(status_code=422, content={"detail": client_message(err)})

    return await run_in_threadpool(run)


@router.post("/photo")
async def push_photo(request: Request, op: str = "") -> JSONResponse:
    """One queued photo: the image as the body (or multipart field ``file``), its op
    as JSON in the ``op`` query parameter ({op_id, device_seq, command: "photos.add",
    args: {target_id, caption?}, device_time, …}; device_id and device_tz beside
    them). Sent twice, it is stored and recorded once."""
    from backend.maintenance import photos as photos_mod
    from backend.maintenance import sync
    from backend.maintenance.service import Invalid, NotFound
    from backend.routers import api_tools
    from backend.routers import maintenance as maintenance_router
    from backend.services import usage as usage_service

    m = await _maintenance(request)
    usage_service.set_feature("maintenance_create")
    try:
        raw_op = json.loads(op) if op else None
    except ValueError:
        raw_op = None
    if not isinstance(raw_op, dict):
        raise HTTPException(status_code=422, detail="Send the op as JSON in the op query parameter.")
    try:
        if request.headers.get("content-type", "").lower().startswith("multipart/form-data"):
            raw = await api_tools._multipart_file(request, photos_mod)
        else:
            raw = await maintenance_router._read_body(request)
    except photos_mod.BadPhoto as err:
        return JSONResponse(status_code=413 if "over" in str(err) else 422, content={"detail": client_message(err)})

    def run():
        device = {"device_id": raw_op.get("device_id"), "device_tz": raw_op.get("device_tz")}
        op_id = raw_op.get("op_id")
        # Sent before: answer from the record, without decoding the image again.
        if isinstance(op_id, str) and sync._OP_ID.match(op_id) and sync.applied(m, op_id):
            return JSONResponse(content=sync.push_photo(m, raw_op, {}, **device))
        if not raw:
            return JSONResponse(status_code=422, content={"detail": "The request had no image."})
        try:
            parsed = sync.read_op(raw_op, photo=True)
        except sync.Malformed as err:
            return JSONResponse(status_code=422, content={"detail": str(err)})
        try:
            m.photo_target(str(parsed["args"]["target_id"]))
            cleaned = photos_mod.clean(raw)
        except NotFound:
            cleaned = None  # the thing it shows is gone: the op's answer says so
        except photos_mod.Busy as err:
            return JSONResponse(status_code=503, content={"detail": client_message(err)},
                                headers={"Retry-After": "30"})
        except (Invalid, photos_mod.BadPhoto) as err:
            return JSONResponse(status_code=422, content={"detail": client_message(err)})
        store = maintenance_router.get_photo_store()
        photo_id = sync.photo_id_for(m.org, parsed["op_id"])
        if cleaned:
            store.put(photo_id, "full", cleaned["full"])
            store.put(photo_id, "thumb", cleaned["thumb"])
        out = sync.push_photo(m, raw_op, cleaned or {}, **device)
        if out["op"]["status"] not in ("applied", "duplicate") and cleaned and not sync.applied(m, parsed["op_id"]):
            store.delete(photo_id)  # not recorded: don't keep its bytes
        return JSONResponse(content=out)

    return await run_in_threadpool(run)
