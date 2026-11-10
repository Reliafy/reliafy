"""The reliability data library over plain HTTP: public reads, no sign-in,
plus a signed-in user's own libraries.

The published library is reference data (every record cited, under a
licence that allows republishing), the same for everyone, so its reads need
no account and are cacheable. The same reads are the MCP ``list kind
library`` / ``get kind library_record`` actions, and so ``POST
/api/v1/...`` and ``reliafy list kind library`` for API tokens. A
per-address limit keeps one client from hammering them.

A signed-in request sees its own libraries (backend/library/user.py) merged
into the same reads: the sources list, the search and a record. Those
answers are private, so they aren't cached. The libraries themselves are
made and changed under ``/api/library/mine`` (sign-in required); the same
writes are the ``change`` tool's ``library_*`` actions.
"""

from __future__ import annotations

import os
from typing import Optional

from fastapi import APIRouter, Body, Depends, Header, Query, Request
from fastapi.responses import JSONResponse

from backend.auth import get_current_user
from backend.db import get_session
from backend.errors import client_message
from backend.library import service
from backend.library import user as user_lib
from backend.ratelimit import SlidingWindowLimiter
from backend.request_ip import client_ip
from backend.services import access as access_service
from backend.services import billing as billing_service
from backend.services import models as models_service
from backend.services.access import AccessCtx, get_access

router = APIRouter(prefix="/api/library")

# Per address a minute. The smoke suite (every library page from one address, several workers)
# raises it with LIBRARY_READS_PER_MINUTE, as Maintenance's writes have MAINTENANCE_WRITES_PER_MINUTE.
_LIMIT = SlidingWindowLimiter(int(os.environ.get("LIBRARY_READS_PER_MINUTE") or 120))
#: Try it asks again a moment after each change, so it has its own allowance.
_EVAL_LIMIT = SlidingWindowLimiter(600)
_CACHE = {"Cache-Control": "public, max-age=3600"}
_PRIVATE = {"Cache-Control": "private, no-store"}
NOT_FOUND = {"detail": "Library not found."}


def _limited(request: Request, limit: Optional[SlidingWindowLimiter] = None) -> Optional[JSONResponse]:
    if not (limit or _LIMIT).allow(client_ip(request) or "unknown"):
        return JSONResponse(status_code=429, content={"detail": "Too many requests. Try again in a minute."},
                            headers={"Retry-After": "60"})
    return None


def optional_access(request: Request, authorization: str | None = Header(default=None), session=Depends(get_session),
                    x_workspace_id: str | None = Header(default=None)) -> AccessCtx | None:
    """The caller's access context when the request is signed in, else None:
    the public reads stay public and add the caller's own libraries when
    there's a caller. Honours a test's override of ``get_current_user``."""
    who = request.app.dependency_overrides.get(get_current_user, get_current_user)
    try:
        user = who() if who is not get_current_user else get_current_user(authorization)
    except Exception:  # noqa: BLE001 - no or bad sign-in: a public read
        return None
    try:
        return get_access(user, session, x_workspace_id)
    except Exception:  # noqa: BLE001 - e.g. not a member of the workspace asked for
        return None


def _mine(session, ctx: AccessCtx | None) -> dict | None:
    """The caller's libraries for the merged reads (None when signed out)."""
    if ctx is None:
        return None
    return user_lib.mine(session, ctx.read_owners, ctx.hidden, lambda owner: access_service.can_write(ctx, owner))


@router.get("/sources")
def library_sources(request: Request, session=Depends(get_session),
                    ctx: AccessCtx | None = Depends(optional_access)) -> JSONResponse:
    """The library's sources, their licences and what each holds; a signed-in
    caller's own libraries first."""
    limited = _limited(request)
    if limited:
        return limited
    mine = _mine(session, ctx)
    return JSONResponse(content=service.sources(mine), headers=_PRIVATE if mine else _CACHE)


@router.get("/search")
def library_search(
    request: Request,
    q: Optional[str] = Query(default=None, max_length=200, description="Words to look for."),
    source: Optional[str] = None,
    equipment_type: Optional[str] = None,
    kind: Optional[str] = None,
    failure_mode: Optional[str] = Query(default=None, max_length=200, description="A failure mode's name (any case)."),
    facets: bool = Query(default=False, description="Add what each filter's choices would give with the others kept."),
    page: int = 1,
    page_size: int = service.DEFAULT_PAGE_SIZE,
    use: Optional[str] = Query(default=None, description=(
        "Only records usable as this on their own: model (an exponential at the rate) or prior.")),
    session=Depends(get_session),
    ctx: AccessCtx | None = Depends(optional_access),
) -> JSONResponse:
    """A page of matching records, best first, with counts (a signed-in
    caller's own libraries' records among them)."""
    limited = _limited(request)
    if limited:
        return limited
    mine = _mine(session, ctx)
    try:
        out = service.search(q, source=source, equipment_type=equipment_type, kind=kind, page=page,
                             page_size=page_size, use=use, mine=mine,
                             failure_mode=failure_mode, facets=facets)
    except ValueError as exc:
        return JSONResponse(status_code=422, content={"detail": client_message(exc)})
    return JSONResponse(content=out, headers=_PRIVATE if mine else _CACHE)


@router.get("/records/{record_id}")
def library_record(
    record_id: str,
    request: Request,
    environment: Optional[str] = Query(default=None, max_length=8, description=(
        "For a handbook rate: the environment the part works in, e.g. GF (ground, fixed).")),
    session=Depends(get_session),
    ctx: AccessCtx | None = Depends(optional_access),
) -> JSONResponse:
    """One record in full, with the model a block would use."""
    limited = _limited(request)
    if limited:
        return limited
    mine = _mine(session, ctx)
    try:
        link = None
        if mine and ":" in record_id and record_id.split(":", 1)[0] in mine["sources"]:
            rec = service.get(record_id, mine)
            link = user_lib.model_link(session, rec, ctx.read_owners)
        out = service.detail(record_id, environment=environment, mine=mine, model_link=link)
        return JSONResponse(content=out, headers=_PRIVATE if mine else _CACHE)
    except service.LibraryNotFound as exc:
        return JSONResponse(status_code=404, content={"detail": client_message(exc)})
    except ValueError as exc:
        return JSONResponse(status_code=422, content={"detail": client_message(exc)})


@router.post("/records/{record_id}/evaluate")
def library_evaluate(record_id: str, request: Request, covariates: Optional[dict] = Body(default=None, embed=True),
                     values: Optional[dict] = Body(default=None, embed=True),
                     time_unit: str = Body(default="hours", embed=True),
                     session=Depends(get_session), ctx: AccessCtx | None = Depends(optional_access)) -> JSONResponse:
    """A record's rate under its covariates, or a component's chance of failing over a period (the
    record page's Try it, the fix-covariates pane's preview; the same as get kind library_record with
    covariates): {ok, result, warnings} or {ok: false, problems, missing}, each problem saying what's
    needed (an NSWC-11 limit names the handbook's page). ``values`` is the old name of
    ``covariates``. Nothing is saved."""
    limited = _limited(request, _EVAL_LIMIT)
    if limited:
        return limited
    given = covariates if covariates is not None else values
    try:
        mine = _mine(session, ctx)
        return JSONResponse(content=service.evaluate(record_id, given, mine=mine, time_unit=time_unit),
                            headers=_PRIVATE)
    except service.LibraryNotFound as exc:
        return JSONResponse(status_code=404, content={"detail": client_message(exc)})
    except ValueError as exc:
        return JSONResponse(status_code=422, content={"detail": client_message(exc)})


@router.get("/components")
def library_components(request: Request, source: Optional[str] = None,
                       q: Optional[str] = Query(default=None, max_length=200)) -> JSONResponse:
    """The components (NRC/INL: an equipment type in one of the report's pooling groups, its failure
    modes together), of ``source``, matching ``q``."""
    limited = _limited(request)
    if limited:
        return limited
    try:
        return JSONResponse(content=service.components(source, q), headers=_CACHE)
    except ValueError as exc:
        return JSONResponse(status_code=422, content={"detail": client_message(exc)})


@router.get("/components/{component_id}")
def library_component(component_id: str, request: Request) -> JSONResponse:
    """One component: its failure modes (each a record, with what sets it off), its covariates
    (demands, running hours and calendar hours over a period) and how the modes combine."""
    limited = _limited(request)
    if limited:
        return limited
    try:
        return JSONResponse(content=service.component_detail(component_id), headers=_CACHE)
    except service.LibraryNotFound as exc:
        return JSONResponse(status_code=404, content={"detail": client_message(exc)})


# ---- A user's own libraries (sign-in required) ----------------------------------------------

def _denied(session, ctx: AccessCtx, cap: bool = False) -> JSONResponse | None:
    denied = access_service.workspace_write_denial(ctx)
    if denied is not None:
        status, payload = denied
        return JSONResponse(status_code=status, content=payload)
    if cap and (ctx.is_personal and not billing_service.is_admin_user(ctx.user)
                and billing_service.would_exceed_cap(session, ctx.uid, user_lib.COLLECTION)):
        return JSONResponse(status_code=402, content={
            "detail": billing_service.cap_message(session, ctx.uid, user_lib.COLLECTION), "code": "cap", "upgrade": True})
    return None


def _own_library(session, ctx: AccessCtx, library_id: str) -> tuple[dict | None, JSONResponse | None]:
    """The library when the caller may change it, else the response saying why not."""
    lib = user_lib.get_library(session, library_id, ctx.read_owners)
    if lib is None or lib["_id"] in ctx.hidden:
        return None, JSONResponse(status_code=404, content=NOT_FOUND)
    denial = access_service.write_denial(ctx, lib.get("owner_id"))
    if denial:
        status, payload = denial
        return None, JSONResponse(status_code=status, content=payload)
    return lib, None


@router.get("/mine")
def my_libraries(session=Depends(get_session), ctx: AccessCtx = Depends(get_access)) -> dict:
    """The caller's libraries (the workspace's), newest first, with their record counts."""
    rows = user_lib.list_libraries(session, ctx.list_owners, ctx.hidden)
    for row in rows:
        row["read_only"] = not access_service.can_write(ctx, row.get("owner_id"))
    return {"libraries": rows, "equipment_types": service.sources()["equipment_types"]}


@router.post("/mine")
def create_library(name: str = Body(...), description: str = Body(default=""), notes: str = Body(default=""),
                   session=Depends(get_session), ctx: AccessCtx = Depends(get_access)) -> JSONResponse:
    """A new, empty library. Counts as one saved item toward the Free plan's limit."""
    denied = _denied(session, ctx, cap=True)
    if denied is not None:
        return denied
    try:
        lib = user_lib.create(session, ctx.write_owner, name, description, notes)
        access_service.stamp_editor(session, user_lib.COLLECTION, lib["id"], ctx)
    except user_lib.LibraryError as exc:
        return JSONResponse(status_code=422, content={"detail": client_message(exc)})
    return JSONResponse(content=lib)


@router.patch("/mine/{library_id}")
def update_library(library_id: str, name: str | None = Body(default=None), description: str | None = Body(default=None),
                   notes: str | None = Body(default=None), session=Depends(get_session),
                   ctx: AccessCtx = Depends(get_access)) -> JSONResponse:
    """Rename a library, or change its description or notes."""
    lib, failed = _own_library(session, ctx, library_id)
    if failed is not None:
        return failed
    try:
        out = user_lib.update(session, library_id, lib["owner_id"], name=name, description=description, notes=notes)
        access_service.stamp_editor(session, user_lib.COLLECTION, library_id, ctx)
    except user_lib.LibraryNotFound:
        return JSONResponse(status_code=404, content=NOT_FOUND)
    except user_lib.LibraryError as exc:
        return JSONResponse(status_code=422, content={"detail": client_message(exc)})
    return JSONResponse(content=out)


@router.delete("/mine/{library_id}")
def delete_library(library_id: str, session=Depends(get_session), ctx: AccessCtx = Depends(get_access)) -> JSONResponse:
    """Delete a library and its records. The models the records came from stay."""
    lib, failed = _own_library(session, ctx, library_id)
    if failed is not None:
        return failed
    try:
        removed = user_lib.delete(session, library_id, lib["owner_id"])
    except user_lib.LibraryNotFound:
        return JSONResponse(status_code=404, content=NOT_FOUND)
    return JSONResponse(content={"ok": True, "records_removed": removed})


@router.post("/mine/{library_id}/records")
def add_model_record(library_id: str, model_id: str = Body(...), label: str | None = Body(default=None),
                     equipment_type: str = Body(default="other"), failure_mode: str = Body(default=""),
                     notes: str = Body(default=""), session=Depends(get_session),
                     ctx: AccessCtx = Depends(get_access)) -> JSONResponse:
    """Add one of the caller's saved life models to a library as a record: a snapshot of the model
    now (its distribution, parameters and bounds, unit, sample sizes and how it was fitted), with
    the model linked. A model that isn't a parametric life model is refused in words."""
    lib, failed = _own_library(session, ctx, library_id)
    if failed is not None:
        return failed
    model = models_service.get_model(session, str(model_id or ""), ctx.read_owners)
    if model is None or model.id in ctx.hidden:
        return JSONResponse(status_code=404, content={"detail": "Model not found."})
    try:
        rec = user_lib.add_model(session, library_id, lib["owner_id"], model, label=label,
                                 equipment_type=equipment_type, failure_mode=failure_mode, notes=notes)
        access_service.stamp_editor(session, user_lib.COLLECTION, library_id, ctx)
    except user_lib.LibraryNotFound:
        return JSONResponse(status_code=404, content=NOT_FOUND)
    except user_lib.LibraryError as exc:
        return JSONResponse(status_code=422, content={"detail": client_message(exc)})
    return JSONResponse(content={"record": rec, "library": user_lib.brief(lib)})


@router.delete("/mine/{library_id}/records/{record_id:path}")
def remove_model_record(library_id: str, record_id: str, session=Depends(get_session),
                        ctx: AccessCtx = Depends(get_access)) -> JSONResponse:
    """Take a record out of a library (the model it came from stays)."""
    lib, failed = _own_library(session, ctx, library_id)
    if failed is not None:
        return failed
    try:
        out = user_lib.remove_record(session, record_id, lib["owner_id"])
        access_service.stamp_editor(session, user_lib.COLLECTION, library_id, ctx)
    except user_lib.LibraryNotFound:
        return JSONResponse(status_code=404, content={"detail": "Record not found."})
    return JSONResponse(content=out)
