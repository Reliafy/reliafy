"""Saved fault trees built by hand (System models › Fault trees): list, save,
analyse, open as an RBD, export to Open-PSA and import from Open-PSA / Galileo."""

from __future__ import annotations

import logging
import os

from fastapi import APIRouter, Body, Depends, File, Form, UploadFile
from fastapi.responses import JSONResponse, Response

from backend.db import get_session
from backend.routers import excel as excel_router
from backend.services import access as access_service
from backend.services import billing as billing_service
from backend.services import fault_trees as ft_service
from backend.services import import_guard
from backend.services import rbd_import
from backend.services import rbds as rbds_service
from backend.services import samples as samples_service
from backend.services.access import AccessCtx, get_access
from backend.services.rbd_analysis import AnalysisError
from backend.errors import client_message

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api")

NOT_FOUND = {"detail": "Fault tree not found."}


def _summary(doc, ctx: AccessCtx) -> dict:
    tree = doc.tree or {}
    return {
        "id": doc.id,
        "name": doc.name,
        **ft_service.counts(tree),
        "unit": tree.get("unit") or "",
        "rbd_id": doc.rbd_id,
        "placeholders": len(ft_service.placeholder_labels(tree)),
        "created_at": doc.created_at.isoformat(),
        "updated_at": doc.updated_at.isoformat(),
        "is_sample": samples_service.is_sample(doc.owner_id),
        "read_only": not access_service.can_write(ctx, doc.owner_id),
        "updated_by": (doc.updated_by or {}).get("name"),
    }


def tree_refs(tree: dict) -> list[tuple[str, str]]:
    """Saved models the tree's basic events use, as ``(collection, id)``."""
    out = []
    for n in (tree or {}).get("nodes") or []:
        model = n.get("model") if isinstance(n, dict) else None
        if isinstance(model, dict):
            for key in ("modelId", "model_id", "saved_model_id"):
                if isinstance(model.get(key), str) and model[key]:
                    out.append(("models", model[key]))
    return out


def resolvers(session, owners):
    from backend.services import models as models_service

    return lambda mid: models_service.get_model(session, mid, owners)


def _err(status: int, detail: str, **extra) -> JSONResponse:
    return JSONResponse(status_code=status, content={"detail": detail, **extra})


def _readable(session, tree_id: str, ctx: AccessCtx):
    doc, _ = access_service.fetch_readable(session, "fault_trees", ft_service.FaultTreeDoc, tree_id, ctx)
    if doc is None or doc.id in ctx.hidden:
        return None
    return doc


@router.get("/fault-trees")
def list_fault_trees(session=Depends(get_session), ctx: AccessCtx = Depends(get_access)) -> dict:
    return {"fault_trees": [_summary(d, ctx) for d in ft_service.list_trees(session, ctx.list_owners, ctx.hidden)]}


@router.post("/fault-trees")
def save_fault_tree(
    name: str = Body(...),
    tree: dict = Body(...),
    id: str | None = Body(default=None),
    expected_updated_at: str | None = Body(default=None),
    session=Depends(get_session),
    ctx: AccessCtx = Depends(get_access),
) -> JSONResponse:
    denied = access_service.workspace_write_denial(ctx)
    if denied is not None:
        status, payload = denied
        return JSONResponse(status_code=status, content=payload)
    try:
        clean = ft_service.normalize_tree(tree, resolvers(session, ctx.read_owners))
    except ft_service.FaultTreeError as exc:
        return _err(422, f"Can't save: {client_message(exc)}")
    existing = ft_service.get_tree(session, id, ctx.read_owners) if id else None
    creating = existing is None or existing.owner_id != ctx.write_owner
    if (creating and ctx.is_personal and not billing_service.is_admin_user(ctx.user)
            and billing_service.would_exceed_cap(session, ctx.uid, "fault_trees")):
        return _err(402, billing_service.cap_message(session, ctx.uid, "fault_trees"), code="cap", upgrade=True)
    kept = tree_refs(existing.tree) if not creating else ()
    try:
        access_service.check_references(session, ctx, tree_refs(clean), keep=kept)
    except access_service.UnreadableReference as exc:
        return _err(exc.status, client_message(exc), code="unreadable_reference")
    try:
        doc = ft_service.save_tree(session, name, clean, ctx.write_owner,
                                   tree_id=None if creating else id, expected_updated_at=expected_updated_at)
    except access_service.EditConflict:
        return _err(409, access_service.CONFLICT_MSG, code="conflict")
    access_service.stamp_editor(session, "fault_trees", doc.id, ctx)
    doc.updated_by = access_service.editor_of(ctx)
    return JSONResponse(content={**_summary(doc, ctx), "tree": doc.tree})


@router.post("/fault-trees/analyse")
def analyse_fault_tree(
    tree: dict = Body(..., embed=True),
    t: float | None = Body(default=None),
    t_max: float | None = Body(default=None),
    session=Depends(get_session),
    ctx: AccessCtx = Depends(get_access),
) -> JSONResponse:
    """The (unsaved) tree's top event, cut sets and importance. Exact and
    quick, so free on every plan."""
    try:
        clean = ft_service.normalize_tree(tree, resolvers(session, ctx.read_owners))
        return JSONResponse(content=ft_service.analyse_for_owner(session, clean, ctx.read_owners, t=t, t_max=t_max))
    except (ft_service.FaultTreeError, AnalysisError) as exc:
        return _err(422, client_message(exc))
    except Exception:  # pragma: no cover - defensive
        logger.exception("Fault tree analysis failed")
        return _err(500, "The fault tree couldn't be analysed. The error has been logged.")


@router.post("/fault-trees/export/openpsa")
def export_openpsa(
    tree: dict = Body(..., embed=True),
    name: str = Body(default="Fault tree"),
    t: float | None = Body(default=None),
    session=Depends(get_session),
    ctx: AccessCtx = Depends(get_access),
) -> Response:
    """The tree as Open-PSA MEF XML (a download)."""
    try:
        clean = ft_service.normalize_tree(tree, resolvers(session, ctx.read_owners))
        if t is None:
            try:
                t = ft_service.analyse_for_owner(session, clean, ctx.read_owners).get("t")
            except (ft_service.FaultTreeError, AnalysisError):
                t = None
        from backend.services import models as models_service

        xml, _ = ft_service.to_openpsa(
            name, clean, lambda mid: models_service.get_live_model(session, mid, ctx.read_owners), t=t)
    except (ft_service.FaultTreeError, AnalysisError) as exc:
        return _err(422, client_message(exc))
    safe = "".join(c if c.isalnum() or c in "-_ " else "_" for c in (name or "fault-tree"))[:60].strip() or "fault-tree"
    return Response(content=xml, media_type="application/xml",
                    headers={"Content-Disposition": f'attachment; filename="{safe}.xml"', "Cache-Control": "no-store"})


@router.post("/fault-trees/import")
def import_fault_tree_file(
    file: UploadFile = File(...),
    time_unit: str | None = Form(default=None),
    session=Depends(get_session),
    ctx: AccessCtx = Depends(get_access),
) -> JSONResponse:
    """Parse an Open-PSA or Galileo file into fault trees — nothing is saved.
    The editor opens the chosen one unsaved."""
    data = file.file.read(rbd_import.MAX_UPLOAD_BYTES + 1)
    ext = os.path.splitext(file.filename or "")[1].lower()[:12]
    fmt = None
    try:
        from backend.services.rbd_import import galileo, openpsa

        if openpsa.sniff(data, file.filename or ""):
            fmt = "openpsa"
        elif galileo.sniff(data, file.filename or ""):
            fmt = "galileo"
    except Exception:  # noqa: BLE001 - untrusted input; refused below
        fmt = None
    if fmt is None:
        return _err(422, "A fault tree imports from an Open-PSA XML file or a Galileo .dft file. Other formats "
                         "(BlockSim, Excel, RePyability JSON) import as RBDs, on the RBDs page.")
    try:
        diagrams = excel_router.guarded(
            ctx.uid, lambda: rbd_import.import_file(data, file.filename or "", format=fmt, time_unit=time_unit))
    except (import_guard.ImportBusy, import_guard.ImportBudgetExceeded) as exc:
        return excel_router.guard_error(exc)
    except rbd_import.RbdImportError as exc:
        logger.info("Fault tree import refused: ext=%s bytes=%d — %s", ext, len(data), exc)
        return _err(422, client_message(exc))
    except Exception:  # untrusted input: never 500 on a malformed file
        logger.exception("Fault tree import failed: ext=%s bytes=%d", ext, len(data))
        return _err(422, "Couldn't read this file — it may be damaged or from an unsupported version.")
    out = []
    for d in diagrams:
        row = {"name": d.name, "source_format": d.source_format}
        if not d.fault_tree:
            out.append({**row, "error": "This diagram has no fault tree to import."})
            continue
        gate_tree, fixed, notes = d.fault_tree
        unit = str(d.graph.get("unit") or "")
        try:
            raw, more = ft_service.from_imported(gate_tree, fixed, unit)
            tree = ft_service.normalize_tree(raw)
        except ft_service.FaultTreeError as exc:
            out.append({**row, "error": client_message(exc)})
            continue
        if not unit:
            more.insert(0, "The file doesn't state a time unit: set the tree's unit to the one its rates are per "
                           "(Open-PSA and Galileo rates are usually per hour).")
        out.append({**row, "tree": tree, "notes": list(notes) + more, **ft_service.counts(tree)})
    return JSONResponse(content={"trees": out})


@router.get("/fault-trees/{tree_id}")
def get_fault_tree(tree_id: str, session=Depends(get_session), ctx: AccessCtx = Depends(get_access)) -> JSONResponse:
    doc = _readable(session, tree_id, ctx)
    if doc is None:
        return JSONResponse(status_code=404, content=NOT_FOUND)
    return JSONResponse(content={**_summary(doc, ctx), "tree": doc.tree})


@router.patch("/fault-trees/{tree_id}")
def rename_fault_tree(
    tree_id: str,
    name: str = Body(..., embed=True),
    session=Depends(get_session),
    ctx: AccessCtx = Depends(get_access),
) -> JSONResponse:
    doc = _readable(session, tree_id, ctx)
    if doc is not None:
        denial = access_service.write_denial(ctx, doc.owner_id)
        if denial:
            status, payload = denial
            return JSONResponse(status_code=status, content=payload)
    try:
        doc = ft_service.rename_tree(session, tree_id, name, ctx.write_owner)
    except ft_service.FaultTreeNotFound:
        return JSONResponse(status_code=404, content=NOT_FOUND)
    access_service.stamp_editor(session, "fault_trees", doc.id, ctx)
    return JSONResponse(content=_summary(doc, ctx))


@router.delete("/fault-trees/{tree_id}")
def delete_fault_tree(tree_id: str, session=Depends(get_session), ctx: AccessCtx = Depends(get_access)) -> JSONResponse:
    doc = _readable(session, tree_id, ctx)
    if doc is None:
        return JSONResponse(status_code=404, content=NOT_FOUND)
    if access_service.can_write(ctx, doc.owner_id):
        try:
            ft_service.delete_tree(session, tree_id, ctx.write_owner)
        except ft_service.FaultTreeNotFound:
            return JSONResponse(status_code=404, content=NOT_FOUND)
    elif samples_service.is_sample(doc.owner_id):
        samples_service.hide_sample(session, ctx.uid, tree_id)  # a sample is hidden, not deleted
    else:
        status, payload = access_service.write_denial(ctx, doc.owner_id)
        return JSONResponse(status_code=status, content=payload)
    return JSONResponse(content={"ok": True})


@router.post("/fault-trees/{tree_id}/rbd")
def open_as_rbd(tree_id: str, session=Depends(get_session), ctx: AccessCtx = Depends(get_access)) -> JSONResponse:
    """Save the tree's RBD (the importers' conversion) as a new diagram and
    link it to the tree. A sample's tree gets the user's own diagram."""
    doc = _readable(session, tree_id, ctx)
    if doc is None:
        return JSONResponse(status_code=404, content=NOT_FOUND)
    denied = access_service.workspace_write_denial(ctx)
    if denied is not None:
        status, payload = denied
        return JSONResponse(status_code=status, content=payload)
    if (ctx.is_personal and not billing_service.is_admin_user(ctx.user)
            and billing_service.would_exceed_cap(session, ctx.uid, "rbds")):
        return _err(402, billing_service.cap_message(session, ctx.uid, "rbds"), code="cap", upgrade=True)
    try:
        graph, notes = ft_service.to_rbd_graph(doc.tree, resolvers(session, ctx.read_owners))
    except ft_service.FaultTreeError as exc:
        return _err(422, client_message(exc))
    rbd = rbds_service.save_rbd(session, f"{doc.name} (from fault tree)"[:200], graph, ctx.write_owner)
    access_service.stamp_editor(session, "rbds", rbd.id, ctx)
    if access_service.can_write(ctx, doc.owner_id):
        ft_service.link_rbd(session, doc.id, rbd.id, doc.owner_id)
    return JSONResponse(content={"rbd_id": rbd.id, "name": rbd.name, "notes": notes})
