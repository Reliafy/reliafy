"""Every MCP tool over REST: ``POST /api/v1/{tool}/{action}`` (or
``POST /api/v1/{tool}`` for a tool without actions), plus the tool list
(``GET /api/v1/tools``) and an OpenAPI spec built from the MCP registry
(``GET /api/v1/openapi.json``).

One source of truth: nothing here describes a tool. A call is the MCP tool
call itself, run through the SDK's tool manager with the same arguments (the
tool's input schema; the action comes from the path), so it gets the same
validation, scope checks, Pro / Free-allowance / heavy-slot gating, usage log
(filed under the ``api`` channel) and result. A tool or action added to the
MCP server is on REST, in the spec and in the CLI with no change here.

Auth is the MCP model: an API token (``rlf_…``, read or write scope as the
tool needs), an OAuth access token, or the signed-in session. A token from an
account without API access is refused with 402, as on the rest of
``/api/v1``; a signed-in Free account gets the Free allowance, as over MCP.
Tools hidden from a caller over MCP (Reliafy Maintenance for anyone but its
users, graph queries for anyone not allowed them) answer 404 here and are
left out of their spec.

Long-running work answers as over MCP: a ``job_id`` with ``status``; poll
``POST /api/v1/get/job`` with ``{"id": job_id}``.

A few things only REST can do (binary files: MCP can't carry them) are listed
in :data:`REST_ONLY`, with no MCP twin.
"""

from __future__ import annotations

import copy
import logging
import re
from types import SimpleNamespace
from typing import Any

import anyio
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import ValidationError

from backend import config

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1")

API_VERSION = "1.1.0"
#: The server version that first answers these routes (clients check it).
TOOLS_API = 1

_PRO_REQUIRED = ("The programmatic API is a Pro feature. Upgrade to Pro to use API tokens; a signed-in Free "
                 "account gets the same monthly allowance of tool calls as over MCP.")

#: REST/CLI-only capabilities: files sent as bytes, which an MCP tool call
#: (JSON arguments) can't carry. They have no MCP twin, on purpose; the parity
#: check (backend/tests/test_api_tools.py) and the docs list them.
REST_ONLY = {
    "maintenance_photos.add": {
        "method": "POST", "path": "/api/v1/maintenance/photos",
        "summary": "Add a photo (JPEG, PNG, WebP or HEIC: the body, or multipart field 'file') to a position, item, "
                   "location or work order. Cleaned and stripped of EXIF; at most 20 MB.",
    },
    "uploads.put": {
        "method": "PUT", "path": "/api/uploads/{upload_id}",
        "summary": "Send a file's bytes to the single-use link from uploads create (the raw body; the link's t "
                   "query parameter is the credential), then import it with its upload_id.",
    },
}


# ---- the registry --------------------------------------------------------------

def _tables() -> dict[str, tuple[str, dict]]:
    """Each tool with actions: (its choosing argument, its action table)."""
    from backend import mcp_server

    out = dict(mcp_server.TABLES)
    if config.MAINTENANCE_ENABLED:
        from backend.maintenance import mcp_tools as maintenance_tools

        out.update({k: v for k, v in maintenance_tools.TABLES.items() if k in maintenance_tools.TOOL_NAMES})
    return out


def _choices(prop: dict) -> list[str]:
    """The values a choosing argument takes (a one-value Literal is a const)."""
    if prop.get("enum"):
        return list(prop["enum"])
    return [prop["const"]] if "const" in prop else []


def _selector_of(tool) -> str | None:
    """The argument choosing an action (``action`` or ``kind``), if any."""
    props = (tool.input_schema or {}).get("properties", {})
    for name in ("action", "kind"):
        p = props.get(name)
        if p and name in ((tool.input_schema or {}).get("required") or []) and _choices(p):
            return name
    return None


def actions_of(tool) -> dict[str, dict]:
    """``{action: {required, optional, doc}}`` for a tool (one entry keyed
    ``""`` for a tool without actions)."""
    schema = tool.input_schema or {}
    props = schema.get("properties", {})
    selector = _selector_of(tool)
    if selector is None:
        req = list(schema.get("required") or [])
        return {"": {"required": req, "optional": [p for p in props if p not in req],
                     "doc": tool.description or ""}}
    table = _tables().get(tool.name, (selector, {}))[1]
    out = {}
    for value in _choices(props[selector]):
        if value in table:
            required, optional, doc = table[value]
            out[value] = {"required": required.split(), "optional": optional.split(), "doc": " ".join(doc.split())}
        else:  # no table: every argument may be given
            out[value] = {"required": [], "optional": [p for p in props if p != selector], "doc": ""}
    return out


async def visible_tools(user: dict | None) -> list:
    """The tools this caller sees over MCP (``tools/list`` as they'd get it,
    Reliafy Maintenance's filtering included). ``None``: the core tools only."""
    from backend.mcp_server import mcp

    entry = mcp._lowlevel_server._request_handlers["tools/list"]
    ctx = SimpleNamespace(request=SimpleNamespace(state=SimpleNamespace(reliafy_user=user)))
    result = await entry.handler(ctx, None)
    return list(result.tools)


# ---- auth --------------------------------------------------------------------

def _db():
    from backend.db import get_db

    return get_db()


def authenticate(authorization: str | None) -> dict:
    """The caller, as the MCP layer's user dict (with ``mcp_plan``), or an
    HTTPException: 401 (no or bad credentials), 402 (a token without API
    access), 403 (an ingest-only token), 429 (the per-user rate limit)."""
    from backend import mcp_server
    from backend.routers.ingest import _rate_check
    from backend.services import billing as billing_service
    from backend.services import usage as usage_service

    db = _db()
    scheme, _, raw = (authorization or "").partition(" ")
    raw = raw.strip()
    if (not raw and config.AUTH_DISABLED and not config.BILLING_ENABLED) or raw.startswith(("rlf_", "rlfo_")):
        status, user, message = mcp_server.authenticate(db, authorization)
        if user is None:
            if status == 403 and message == mcp_server.MCP_PRO_REQUIRED:
                raise HTTPException(status_code=402, detail=_PRO_REQUIRED)
            if status == 403:
                message = ("This API token can only push data (ingest scope). Create a token with the read (and "
                           "write, for saving) scope under Settings > API access.")
            raise HTTPException(status_code=status, detail=message)
        if user.get("via_token"):
            usage_service.note_user(user, channel="api")
    else:
        if scheme.lower() != "bearer" or not raw:
            raise HTTPException(status_code=401, detail=(
                "Send 'Authorization: Bearer rlf_…' with an API token from Settings > API access."))
        from backend.auth import get_current_user

        user = get_current_user(authorization)  # a signed-in session (401 if not)
        user = {**user, "mcp_plan": billing_service.mcp_plan(db, user)}
    _rate_check(user["uid"])
    return {**user, "usage_channel": "api"}


async def _caller(request: Request) -> dict:
    return await anyio.to_thread.run_sync(authenticate, request.headers.get("authorization"))


# ---- calls -------------------------------------------------------------------

_PREFIX = re.compile(r"^Error executing tool [\w.-]+: ")


def _cause(exc: BaseException, kind) -> BaseException | None:
    seen = 0
    while exc is not None and seen < 10:
        if isinstance(exc, kind):
            return exc
        exc, seen = exc.__cause__ or exc.__context__, seen + 1
    return None


def _status_for(exc: BaseException, detail: str) -> int:
    """The HTTP status for a refused tool call."""
    from backend import mcp_server
    from backend.services import tokens as tokens_service

    refusal = _cause(exc, mcp_server.Refusal)
    if refusal is not None:
        return 402 if refusal.outcome == "pro_only" else 429
    if _cause(exc, ValidationError) is not None:
        return 422
    if detail in (tokens_service.scope_message("read"), tokens_service.scope_message("write")):
        return 403
    if detail == mcp_server.INSTANCE_BUSY_MESSAGE:
        return 503
    if detail.startswith("You already have ") and "running at once" in detail:
        return 429
    if re.search(r"\bnot found\b|isn't available on your account", detail, re.I):
        return 404
    return 422


def _content_json(content) -> Any:
    """A result without structured content (an image, plain text) as JSON."""
    out = []
    for block in content or []:
        kind = getattr(block, "type", "")
        if kind == "text":
            out.append({"type": "text", "text": block.text})
        elif kind == "image":
            out.append({"type": "image", "mime_type": block.mime_type, "data_base64": block.data})
        else:
            out.append(block.model_dump(mode="json", by_alias=True, exclude_none=True))
    return {"content": out}


async def call(request: Request, user: dict, tool: str, args: dict) -> JSONResponse:
    """Run one MCP tool call as ``user`` and answer it as REST."""
    from mcp.server.mcpserver import Context
    from mcp.server.mcpserver.exceptions import ToolError, UnexpectedToolError

    from backend.mcp_server import mcp

    request.state.reliafy_user = user
    ctx = Context(request_context=SimpleNamespace(request=request), mcp_server=mcp)
    result = None
    try:
        with anyio.move_on_after(config.MCP_REQUEST_TIMEOUT_S):
            result = await mcp.call_tool(tool, args, ctx)
    except UnexpectedToolError:
        logger.exception("REST tool call %s raised an unexpected exception", tool)
        return JSONResponse(status_code=500, content={"detail": f"Error executing tool {tool}."})
    except ToolError as exc:
        detail = _PREFIX.sub("", str(exc), count=1)
        invalid = exc.__cause__ if isinstance(exc.__cause__, ValidationError) else None
        if invalid is not None:  # the arguments against the tool's schema, said plainly
            detail = "; ".join(f"{'.'.join(str(x) for x in e.get('loc') or ()) or 'arguments'}: {e.get('msg')}"
                               for e in invalid.errors(include_url=False)[:5]) + "."
        return JSONResponse(status_code=_status_for(exc, detail), content={"detail": detail})
    if result is None:
        return JSONResponse(status_code=504, content={"detail": "The request took too long and was stopped."})
    if getattr(result, "is_error", False):
        text = result.content[0].text if result.content else "Error."
        return JSONResponse(status_code=422, content={"detail": text})
    body = result.structured_content if result.structured_content is not None else _content_json(result.content)
    return JSONResponse(content=body)


async def _body(request: Request) -> dict:
    raw = await request.body()
    if not raw.strip():
        return {}
    try:
        import json

        body = json.loads(raw)
    except ValueError:
        raise HTTPException(status_code=422, detail="The body must be a JSON object of the tool's arguments.")
    if not isinstance(body, dict):
        raise HTTPException(status_code=422, detail="The body must be a JSON object of the tool's arguments.")
    return body


async def _tool_for(user: dict, name: str):
    tool = next((t for t in await visible_tools(user) if t.name == name), None)
    if tool is None:
        raise HTTPException(status_code=404, detail=f"No tool '{name}'. GET /api/v1/tools lists them.")
    return tool


# ---- routes --------------------------------------------------------------------

@router.get("/tools")
async def list_tools(request: Request) -> JSONResponse:
    """The tools and actions this caller may call, each with its path."""
    user = await _caller(request)
    tools = []
    for t in await visible_tools(user):
        selector = _selector_of(t)
        acts = actions_of(t)
        tools.append({
            "name": t.name, "title": t.title, "selector": selector,
            "scope": "read" if (t.annotations and t.annotations.read_only_hint) else "write",
            "actions": [{"action": a or None, "path": _path(t.name, a), "required": v["required"],
                         "optional": v["optional"], "doc": v["doc"]} for a, v in acts.items()],
        })
    return JSONResponse(content={"api": TOOLS_API, "tools": tools,
                                 "rest_only": [{"name": k, **v} for k, v in REST_ONLY.items()]})


@router.get("/openapi.json")
async def openapi(request: Request) -> JSONResponse:
    """The OpenAPI spec of every tool and action. Without credentials it
    covers the core tools; with them, what that caller may call."""
    user = None
    if request.headers.get("authorization") or config.AUTH_DISABLED:
        try:
            user = await _caller(request)
        except HTTPException:
            user = None
    return JSONResponse(content=build_spec(await visible_tools(user)))


@router.post("/maintenance/photos")
async def add_photo(request: Request, target_id: str = "", caption: str = "") -> JSONResponse:
    """A photo for a position, item, location or work order: the twin of the
    app's ``POST /api/maintenance/photos`` for API tokens (write scope), on the
    same path through ``ingest_photo`` (decoded, cleaned, EXIF stripped, the
    same limits). The body is the image, or multipart with a ``file`` field."""
    from starlette.concurrency import run_in_threadpool

    from backend.maintenance import photos as photos_mod
    from backend.maintenance.access import allowed
    from backend.maintenance.service import Maintenance
    from backend.routers import maintenance as maintenance_router
    from backend.services import time_zones
    from backend.services import tokens as tokens_service
    from backend.services import usage as usage_service

    user = await _caller(request)
    if not allowed(user):
        raise HTTPException(status_code=404, detail="Not found.")
    if not tokens_service.has_scope(user, "write"):
        raise HTTPException(status_code=403, detail=tokens_service.scope_message("write"))
    if not target_id:
        raise HTTPException(status_code=422, detail="Say what the photo shows: ?target_id=<position, item, "
                                                    "location or work order id>.")
    usage_service.note_user(user, channel="api")
    usage_service.set_feature(usage_service.app_feature("POST", "/api/maintenance/photos") or "maintenance_create")
    try:
        if request.headers.get("content-type", "").lower().startswith("multipart/form-data"):
            raw = await _multipart_file(request, photos_mod)
        else:
            raw = await maintenance_router._read_body(request)
    except photos_mod.BadPhoto as err:
        status = 413 if "over" in str(err) else 422
        return JSONResponse(status_code=status, content={"detail": str(err)})
    if not raw:
        return JSONResponse(status_code=422, content={"detail": "The request had no image."})

    def ingest():
        m = Maintenance(maintenance_router.get_store(), user["uid"], user["uid"],
                        time_zone=time_zones.of_owner(_db(), user["uid"]))
        return maintenance_router._run(maintenance_router.ingest_photo, m, target_id, raw, caption[:200], "api")

    # Decoding is CPU-bound: off the event loop (photos.clean limits how many at once).
    return await run_in_threadpool(ingest)


async def _multipart_file(request: Request, photos_mod) -> bytes:
    """The ``file`` field of a multipart body, refused past the photo cap."""
    declared = request.headers.get("content-length")
    if declared and declared.isdigit() and int(declared) > photos_mod.MAX_UPLOAD_BYTES + 64 * 1024:
        raise photos_mod.BadPhoto("The photo is over 20 MB.")
    form = await request.form(max_files=1, max_fields=4, max_part_size=1024 * 1024)
    try:
        upload = form.get("file")
        if upload is None or not hasattr(upload, "read"):
            raise photos_mod.BadPhoto("Send the image in a multipart field named file.")
        data = await upload.read(photos_mod.MAX_UPLOAD_BYTES + 1)
        if len(data) > photos_mod.MAX_UPLOAD_BYTES:
            raise photos_mod.BadPhoto("The photo is over 20 MB.")
        return data
    finally:
        await form.close()


@router.post("/{tool}/{action}")
async def call_action(tool: str, action: str, request: Request) -> JSONResponse:
    user = await _caller(request)
    t = await _tool_for(user, tool)
    selector = _selector_of(t)
    if selector is None:
        raise HTTPException(status_code=404, detail=f"'{tool}' has no actions: POST /api/v1/{tool}.")
    acts = actions_of(t)
    if action not in acts:
        raise HTTPException(status_code=404, detail=(
            f"'{tool}' has no {selector} '{action}'. It has: {', '.join(acts)}."))
    args = await _body(request)
    if selector in args and args[selector] != action:
        raise HTTPException(status_code=422, detail=f"The {selector} is in the path; leave it out of the body.")
    return await call(request, user, tool, {**args, selector: action})


@router.post("/{tool}")
async def call_plain(tool: str, request: Request) -> JSONResponse:
    user = await _caller(request)
    t = await _tool_for(user, tool)
    selector = _selector_of(t)
    if selector is not None:
        raise HTTPException(status_code=404, detail=(
            f"'{tool}' takes a {selector}: POST /api/v1/{tool}/{{{selector}}}. GET /api/v1/tools lists them."))
    return await call(request, user, tool, await _body(request))


# ---- OpenAPI --------------------------------------------------------------------

def _path(tool: str, action: str) -> str:
    return f"/api/v1/{tool}/{action}" if action else f"/api/v1/{tool}"


def _schema_name(tool: str, name: str) -> str:
    return f"{tool}__{name}"


def _rewrite_refs(node, tool: str):
    """The tool schema's ``#/$defs/X`` references (``$ref`` and discriminator
    mappings) as the spec's ``#/components/schemas/{tool}__X``."""
    if isinstance(node, dict):
        return {k: _rewrite_refs(v, tool) for k, v in node.items()}
    if isinstance(node, list):
        return [_rewrite_refs(v, tool) for v in node]
    if isinstance(node, str) and node.startswith("#/$defs/"):
        return "#/components/schemas/" + _schema_name(tool, node[len("#/$defs/"):])
    return node


_ERROR = {"description": "Refused: see detail.", "content": {"application/json": {"schema": {
    "$ref": "#/components/schemas/Error"}}}}


def build_spec(tools: list) -> dict:
    """OpenAPI 3.1 for these tools: one POST operation per tool action."""
    from backend import mcp_server

    paths: dict[str, Any] = {}
    schemas: dict[str, Any] = {"Error": {"type": "object", "properties": {"detail": {"type": "string"}},
                                         "required": ["detail"]}}
    for t in tools:
        schema = copy.deepcopy(t.input_schema or {})
        for name, d in (schema.pop("$defs", None) or {}).items():
            schemas[_schema_name(t.name, name)] = _rewrite_refs(d, t.name)
        props = _rewrite_refs(schema.get("properties", {}), t.name)
        selector = _selector_of(t)
        scope = "read" if (t.annotations and t.annotations.read_only_hint) else "write"
        for action, spec in actions_of(t).items():
            names = [*spec["required"], *spec["optional"]]
            body = {"type": "object", "additionalProperties": False,
                    "properties": {n: props[n] for n in names if n in props}}
            if spec["required"]:
                body["required"] = spec["required"]
            key = f"{t.name}.{action}" if action else t.name
            doc = spec["doc"] or (t.description or "")
            paths[_path(t.name, action)] = {"post": {
                "operationId": key,
                "summary": doc.split(". ")[0][:200],
                "description": doc,
                "tags": [t.name],
                "requestBody": {"required": bool(spec["required"]),
                                "content": {"application/json": {"schema": body}}},
                "responses": {"200": {"description": "The tool's result (as over MCP).",
                                      "content": {"application/json": {"schema": {"type": "object"}}}},
                              "401": _ERROR, "402": _ERROR, "403": _ERROR, "404": _ERROR, "422": _ERROR,
                              "429": _ERROR},
                "x-reliafy-tool": t.name,
                "x-reliafy-selector": selector,
                "x-reliafy-action": action or None,
                "x-reliafy-scope": scope,
                "x-reliafy-pro-only": key in mcp_server.PRO_ONLY_TOOLS,
                "x-reliafy-heavy": key in mcp_server.HEAVY_TOOLS,
            }}
    paths["/api/v1/maintenance/photos"] = {"post": {
        "operationId": "maintenance_photos.add", "tags": ["rest_only"],
        "summary": REST_ONLY["maintenance_photos.add"]["summary"],
        "description": REST_ONLY["maintenance_photos.add"]["summary"] + " Reliafy Maintenance users only.",
        "parameters": [
            {"name": "target_id", "in": "query", "required": True, "schema": {"type": "string"}},
            {"name": "caption", "in": "query", "required": False, "schema": {"type": "string", "maxLength": 200}}],
        "requestBody": {"required": True, "content": {
            "image/*": {"schema": {"type": "string", "format": "binary"}},
            "application/octet-stream": {"schema": {"type": "string", "format": "binary"}},
            "multipart/form-data": {"schema": {"type": "object", "properties": {
                "file": {"type": "string", "format": "binary"}}, "required": ["file"]}}}},
        "responses": {"200": {"description": "The photo, and any location it carried (offered, never stored)."},
                      "401": _ERROR, "402": _ERROR, "403": _ERROR, "404": _ERROR, "413": _ERROR,
                      "422": _ERROR, "429": _ERROR},
        "x-reliafy-rest-only": True, "x-reliafy-scope": "write",
    }}
    paths["/api/uploads/{upload_id}"] = {"put": {
        "operationId": "uploads.put", "tags": ["rest_only"],
        "summary": REST_ONLY["uploads.put"]["summary"],
        "security": [],
        "parameters": [
            {"name": "upload_id", "in": "path", "required": True, "schema": {"type": "string"}},
            {"name": "t", "in": "query", "required": True, "schema": {"type": "string"}}],
        "requestBody": {"required": True, "content": {
            "application/octet-stream": {"schema": {"type": "string", "format": "binary"}}}},
        "responses": {"200": {"description": "Received: import it with its upload_id."},
                      "404": _ERROR, "409": _ERROR, "410": _ERROR, "413": _ERROR, "429": _ERROR},
        "x-reliafy-rest-only": True,
    }}
    return {
        "openapi": "3.1.0",
        "info": {
            "title": "Reliafy API",
            "version": API_VERSION,
            "description": (
                "Every Reliafy MCP tool action over REST: POST /api/v1/{tool}/{action} with the action's "
                "arguments as a JSON object (POST /api/v1/{tool} for a tool without actions). Results and "
                "refusals are the same as over MCP. Long-running calculations answer with a job_id: poll "
                "POST /api/v1/get/job with {\"id\": job_id}. Operations tagged rest_only have no MCP twin."),
        },
        "servers": [{"url": config.PUBLIC_BASE_URL or "https://reliafy.com"}],
        "components": {"schemas": schemas, "securitySchemes": {
            "bearer": {"type": "http", "scheme": "bearer",
                       "description": "An API token (rlf_…) from Settings > API access, or a session."}}},
        "security": [{"bearer": []}],
        "paths": paths,
    }
