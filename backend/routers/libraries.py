"""Libraries over HTTP (backend/library/entries.py): shareable collections of
dataset and model snapshots, beside the built-in handbooks.

Reads take an optional sign-in: signed out, only public libraries (and the
built-in handbooks) are seen. Every write needs sign-in, and only a library's
owner changes it. Answers about a user's libraries are never cached.
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Body, Depends, Query, Request
from fastapi.responses import JSONResponse

from backend.db import get_session
from backend.errors import client_message
from backend.library import entries as lib_entries
from backend.routers.library import _limited, optional_access
from backend.services import access as access_service
from backend.services import billing as billing_service
from backend.services import datasets as datasets_service
from backend.services.access import AccessCtx, get_access

router = APIRouter(prefix="/api/libraries")

_PRIVATE = {"Cache-Control": "private, no-store"}
NOT_FOUND = {"detail": "Library not found."}
ENTRY_NOT_FOUND = {"detail": "That entry isn't in this library."}
READ_ONLY = {"detail": "Only the library's owner can change it. Use an entry to copy it into your workspace."}


def _json(content, status: int = 200) -> JSONResponse:
    return JSONResponse(status_code=status, content=content, headers=_PRIVATE)


def _principals(ctx: AccessCtx | None) -> list[str]:
    return list(ctx.read_owners) if ctx is not None else []


def _can_write(ctx: AccessCtx | None):
    return (lambda owner: access_service.can_write(ctx, owner)) if ctx is not None else None


def _visible(session, ctx: AccessCtx | None, library_id: str) -> Optional[dict]:
    lib = lib_entries.get_visible(session, library_id, _principals(ctx))
    if lib is None or (ctx is not None and lib["_id"] in ctx.hidden):
        return None
    return lib


def _out(session, ctx: AccessCtx | None, lib: dict) -> dict:
    can_edit = ctx is not None and access_service.can_write(ctx, lib.get("owner_id"))
    rel = lib_entries.relation(lib, ctx.write_owner if ctx else None, _principals(ctx))
    return lib_entries.library_out(session, lib, rel, can_edit, _principals(ctx))


def _owned(session, ctx: AccessCtx, library_id: str) -> tuple[Optional[dict], Optional[JSONResponse]]:
    """The library when the caller may change it, else the response saying why not."""
    if library_id in lib_entries.builtin_ids():
        return None, _json({"detail": "The built-in handbooks are read-only."}, 403)
    lib = _visible(session, ctx, library_id)
    if lib is None:
        return None, _json(NOT_FOUND, 404)
    denial = access_service.write_denial(ctx, lib.get("owner_id"))
    if denial:
        status, payload = denial
        return None, _json(READ_ONLY if status == 403 else payload, status)
    return lib, None


def _capped(session, ctx: AccessCtx, kinds: dict[str, int]) -> Optional[JSONResponse]:
    """402 when making these items would pass a Free storage cap (a library is one saved item; using an
    entry counts as the copy it makes)."""
    denied = access_service.workspace_write_denial(ctx)
    if denied is not None:
        status, payload = denied
        return _json(payload, status)
    if not ctx.is_personal or billing_service.is_admin_user(ctx.user):
        return None
    for kind, n in kinds.items():
        if n and billing_service.would_exceed_cap(session, ctx.uid, kind):
            return _json({"detail": billing_service.cap_message(session, ctx.uid, kind), "code": "cap",
                          "upgrade": True}, 402)
    return None


def _error(exc: Exception) -> JSONResponse:
    if isinstance(exc, lib_entries.LibraryNotFound):
        return _json(ENTRY_NOT_FOUND, 404)
    return _json({"detail": client_message(exc)}, 422)


# ---- reads -------------------------------------------------------------------------------------

@router.get("")
def list_libraries(request: Request, session=Depends(get_session),
                   ctx: AccessCtx | None = Depends(optional_access)) -> JSONResponse:
    """Every library the caller sees: theirs, those shared with them, and the public ones (others', then the
    built-in handbooks)."""
    limited = _limited(request)
    if limited:
        return limited
    rows = lib_entries.list_cards(session, _principals(ctx), ctx.write_owner if ctx else None, _can_write(ctx),
                                  ctx.hidden if ctx else frozenset())
    return _json({"libraries": rows, "signed_in": ctx is not None,
                  "workspace_id": lib_entries.workspace_id_of(ctx.write_owner) if ctx else None,
                  "licences": [{"id": k, "name": v} for k, v in lib_entries.LICENCES.items()]})


@router.get("/entries")
def list_entries(request: Request, type: str = Query(default="data", pattern="^(data|model)$"),
                 q: Optional[str] = Query(default=None, max_length=200), session=Depends(get_session),
                 ctx: AccessCtx | None = Depends(optional_access)) -> JSONResponse:
    """Every dataset (or model) in any library the caller sees (the built-in handbooks are listed apart)."""
    limited = _limited(request)
    if limited:
        return limited
    rows = lib_entries.all_entries(session, _principals(ctx), ctx.write_owner if ctx else None, type, q or "",
                                   ctx.hidden if ctx else frozenset())
    return _json({"entries": rows, "builtin": lib_entries.builtin_cards() if type == "model" else []})


@router.get("/{library_id}")
def get_library(library_id: str, request: Request, session=Depends(get_session),
                ctx: AccessCtx | None = Depends(optional_access)) -> JSONResponse:
    """One library with its entries (a built-in handbook: its card; its pages list the records)."""
    limited = _limited(request)
    if limited:
        return limited
    built = lib_entries.builtin_out(library_id)
    if built is not None:
        return _json(built)
    lib = _visible(session, ctx, library_id)
    if lib is None:
        return _json(NOT_FOUND, 404)
    return _json(_out(session, ctx, lib))


@router.get("/{library_id}/entries/{entry_id}")
def get_entry(library_id: str, entry_id: str, request: Request, session=Depends(get_session),
              ctx: AccessCtx | None = Depends(optional_access)) -> JSONResponse:
    """One entry in full: a dataset's first rows and reading, a model's parameters."""
    limited = _limited(request)
    if limited:
        return limited
    lib = _visible(session, ctx, library_id)
    if lib is None:
        return _json(NOT_FOUND, 404)
    owner_view = ctx is not None and access_service.can_write(ctx, lib.get("owner_id"))
    try:
        return _json(lib_entries.entry_detail(session, lib, entry_id, owner_view, _principals(ctx)))
    except lib_entries.LibraryNotFound:
        return _json(ENTRY_NOT_FOUND, 404)


# ---- writes (the owner's) ------------------------------------------------------------------------

@router.post("")
def create_library(name: str = Body(...), description: str = Body(default=""), notes: str = Body(default=""),
                   source: str = Body(default=""), citation: str = Body(default=""), session=Depends(get_session),
                   ctx: AccessCtx = Depends(get_access)) -> JSONResponse:
    """A new, private, empty library. Counts as one saved item toward the Free plan's limit."""
    capped = _capped(session, ctx, {"libraries": 1})
    if capped is not None:
        return capped
    try:
        lib = lib_entries.create(session, ctx.write_owner, name, description, notes, source, citation)
        access_service.stamp_editor(session, lib_entries.COLLECTION, lib["_id"], ctx)
    except lib_entries.LibraryError as exc:
        return _error(exc)
    return _json(_out(session, ctx, lib))


@router.patch("/{library_id}")
def update_library(library_id: str, name: Optional[str] = Body(default=None),
                   description: Optional[str] = Body(default=None), notes: Optional[str] = Body(default=None),
                   source: Optional[str] = Body(default=None), citation: Optional[str] = Body(default=None),
                   session=Depends(get_session), ctx: AccessCtx = Depends(get_access)) -> JSONResponse:
    """Rename a library, or change its purpose, notes, source or citation."""
    lib, failed = _owned(session, ctx, library_id)
    if failed is not None:
        return failed
    try:
        lib = lib_entries.update(session, lib, name=name, description=description, notes=notes, source=source,
                                 citation=citation)
        access_service.stamp_editor(session, lib_entries.COLLECTION, library_id, ctx)
    except lib_entries.LibraryError as exc:
        return _error(exc)
    return _json(_out(session, ctx, lib))


@router.put("/{library_id}/visibility")
def set_visibility(library_id: str, visibility: str = Body(...), workspaces: Optional[list[str]] = Body(default=None),
                   licence: Optional[str] = Body(default=None), source: Optional[str] = Body(default=None),
                   citation: Optional[str] = Body(default=None), rights_confirmed: Optional[bool] = Body(default=None),
                   session=Depends(get_session), ctx: AccessCtx = Depends(get_access)) -> JSONResponse:
    """Private, shared with workspaces (read-only for them) or public (needs a licence, a source or citation and
    rights_confirmed true)."""
    lib, failed = _owned(session, ctx, library_id)
    if failed is not None:
        return failed
    try:
        lib = lib_entries.set_visibility(session, lib, visibility, workspaces=workspaces, licence=licence,
                                         source=source, citation=citation, rights_confirmed=rights_confirmed)
        access_service.stamp_editor(session, lib_entries.COLLECTION, library_id, ctx)
    except lib_entries.LibraryError as exc:
        return _error(exc)
    return _json(_out(session, ctx, lib))


@router.delete("/{library_id}")
def delete_library(library_id: str, session=Depends(get_session), ctx: AccessCtx = Depends(get_access)) -> JSONResponse:
    """Delete a library and its entries. The datasets and models they were taken from stay, and so do copies."""
    lib, failed = _owned(session, ctx, library_id)
    if failed is not None:
        return failed
    return _json({"ok": True, "entries_removed": lib_entries.delete(session, lib)})


@router.post("/{library_id}/entries")
def add_entry(library_id: str, dataset_id: Optional[str] = Body(default=None), model_id: Optional[str] = Body(default=None),
              collection: str = Body(default="models"), source: str = Body(default=""),
              session=Depends(get_session), ctx: AccessCtx = Depends(get_access)) -> JSONResponse:
    """Add a snapshot of a dataset (dataset_id) or a saved model (model_id, with its collection: models,
    recurrent_models or alt_models). Later edits in the workspace don't change it."""
    lib, failed = _owned(session, ctx, library_id)
    if failed is not None:
        return failed
    if bool(dataset_id) == bool(model_id):
        return _json({"detail": "Give a dataset_id or a model_id (one of them)."}, 422)
    try:
        if dataset_id:
            ds = datasets_service.get_dataset(session, str(dataset_id), ctx.read_owners)
            if ds is None or ds.id in ctx.hidden:
                return _json({"detail": "Dataset not found."}, 404)
            doc = lib_entries.add_dataset(session, lib, ds, ctx.read_owners, ctx.hidden, source)
        else:
            if collection not in lib_entries.MODEL_KINDS:
                return _json({"detail": "collection is models, recurrent_models or alt_models."}, 422)
            mdoc = session[collection].find_one({"_id": str(model_id), "owner_id": {"$in": list(ctx.read_owners)}})
            if mdoc is None or mdoc["_id"] in ctx.hidden:
                return _json({"detail": "Model not found."}, 404)
            doc = lib_entries.add_model(session, lib, collection, mdoc, ctx.read_owners, source)
        access_service.stamp_editor(session, lib_entries.COLLECTION, library_id, ctx)
    except lib_entries.LibraryError as exc:
        return _error(exc)
    out = _out(session, ctx, lib)
    entry = next((e for e in out["entries"] if e["id"] == doc["_id"]), None)
    return _json({"entry": entry, "library": {k: v for k, v in out.items() if k != "entries"}})


@router.delete("/{library_id}/entries/{entry_id}")
def remove_entry(library_id: str, entry_id: str, session=Depends(get_session),
                 ctx: AccessCtx = Depends(get_access)) -> JSONResponse:
    """Take an entry out (the dataset or model it was taken from stays)."""
    lib, failed = _owned(session, ctx, library_id)
    if failed is not None:
        return failed
    try:
        lib_entries.remove(session, lib, entry_id)
    except lib_entries.LibraryNotFound:
        return _json(ENTRY_NOT_FOUND, 404)
    return _json({"removed": True, "entry_id": entry_id})


@router.post("/{library_id}/entries/{entry_id}/refresh")
def refresh_entry(library_id: str, entry_id: str, session=Depends(get_session),
                  ctx: AccessCtx = Depends(get_access)) -> JSONResponse:
    """Update from the original: a new snapshot of what the entry was taken from (its version one up)."""
    lib, failed = _owned(session, ctx, library_id)
    if failed is not None:
        return failed
    try:
        doc = lib_entries.refresh(session, lib, entry_id, ctx.read_owners, ctx.hidden)
    except (lib_entries.LibraryNotFound, lib_entries.LibraryError) as exc:
        return _error(exc)
    out = _out(session, ctx, lib)
    return _json({"entry": next((e for e in out["entries"] if e["id"] == doc["_id"]), None)})


@router.post("/{library_id}/entries/{entry_id}/use")
def use_entry(library_id: str, entry_id: str, name: Optional[str] = Body(default=None),
              with_dataset: bool = Body(default=False), session=Depends(get_session),
              ctx: AccessCtx = Depends(get_access)) -> JSONResponse:
    """Copy an entry into the caller's workspace: the dataset, or the model (and, with with_dataset, the
    dataset it was fitted on when that is in the library). Each copy says where it came from."""
    lib = _visible(session, ctx, library_id)
    if lib is None:
        return _json(NOT_FOUND, 404)
    try:
        doc = lib_entries.entry_doc(session, lib, entry_id)
    except lib_entries.LibraryNotFound:
        return _json(ENTRY_NOT_FOUND, 404)
    capped = _capped(session, ctx, lib_entries.what_use_makes(session, lib, doc, with_dataset))
    if capped is not None:
        return capped
    try:
        out = lib_entries.use(session, lib, entry_id, ctx.write_owner, name, with_dataset)
    except (lib_entries.LibraryNotFound, lib_entries.LibraryError) as exc:
        return _error(exc)
    for coll, made in (("datasets", out.get("dataset")), ((out.get("model") or {}).get("collection"), out.get("model"))):
        if made and not made.get("reused") and coll:
            access_service.stamp_editor(session, coll, made["id"], ctx)
    return _json(out)
