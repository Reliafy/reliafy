"""Reports API (#30, #41): compose saved items into one shareable page, and
draft its notes with the assistant.

Saving a report publishes nothing. It is published like any other item,
with a public link (``POST /api/public-links`` with ``collection:
"reports"``), so the same passphrase, expiry and revoke apply.

Reports belong to the active workspace (``X-Workspace-Id``), like every other
saved item: every member of a team reads and (with edit rights) changes the
team's reports, and nobody sees another workspace's.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Body, Depends
from fastapi.responses import JSONResponse

from backend.db import get_session
from backend.services import assistant as assistant_service
from backend.services import report_draft
from backend.services import report_facts
from backend.services import report_view
from backend.services import reports as reports_service
from backend.services import access as access_service
from backend.services.access import AccessCtx, get_access
from backend.errors import client_message

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/reports")

_NOT_FOUND = {"detail": "Report not found."}


def _refuse(exc: reports_service.ReportError) -> JSONResponse:
    return JSONResponse(status_code=exc.status, content={"detail": client_message(exc)})


def _write_denied(ctx: AccessCtx) -> JSONResponse | None:
    """A frozen team or a member without edit rights can read reports, not change them."""
    denial = access_service.workspace_write_denial(ctx)
    if denial is None:
        return None
    status, payload = denial
    return JSONResponse(status_code=status, content=payload)


def _with_access(ctx: AccessCtx, payload: dict) -> dict:
    """A report as the app shows it, with whether this member may change it."""
    return {**payload, "read_only": access_service.workspace_write_denial(ctx) is not None}


@router.get("")
def list_reports(session=Depends(get_session), ctx: AccessCtx = Depends(get_access)) -> dict:
    """The active workspace's reports, newest first."""
    return {"reports": [_with_access(ctx, reports_service.public(session, d))
                        for d in reports_service.list_reports(session, ctx.write_owner)]}


@router.get("/items")
def pickable_items(session=Depends(get_session), ctx: AccessCtx = Depends(get_access)) -> dict:
    """What can go in this workspace's reports: its own items, then the samples."""
    return {"items": reports_service.pickable_items(session, ctx.write_owner, ctx.hidden),
            "max_sections": reports_service.MAX_SECTIONS}


@router.post("")
def create_report(body: dict = Body(...), session=Depends(get_session),
                  ctx: AccessCtx = Depends(get_access)) -> JSONResponse:
    if (denied := _write_denied(ctx)) is not None:
        return denied
    try:
        doc = reports_service.create(session, ctx.write_owner, body)
    except reports_service.ReportError as exc:
        return _refuse(exc)
    access_service.stamp_editor(session, reports_service.COLLECTION, doc["_id"], ctx)
    return JSONResponse(content=_with_access(ctx, reports_service.public(session, doc)))


@router.post("/draft")
def draft_notes(
    title: str = Body(default=""),
    sections: list = Body(...),
    session=Depends(get_session),
    ctx: AccessCtx = Depends(get_access),
) -> JSONResponse:
    """Draft the introduction and section notes from the items' stored
    results. Metered and gated exactly like an assistant step (AI configured,
    credits, one request at a time); returns the draft for the owner to
    edit — nothing is saved or published."""
    from backend.routers import assistant as assistant_router

    user = ctx.user
    try:
        cleaned = reports_service.clean_sections(session, ctx.write_owner, sections)
    except reports_service.ReportError as exc:
        return _refuse(exc)
    items = []
    for s in cleaned:
        payload = report_view.item_payload(session, s["collection"], s["artifact_id"], ctx.write_owner)
        items.append({
            "kind": reports_service.ITEM_KINDS.get(s["collection"]),
            "name": (payload or {}).get("name"),
            "facts": report_facts.facts(s["collection"], payload),
        })
    messages = report_draft.messages(title, items)
    try:
        meter = assistant_router._begin(session, user, messages)
    except assistant_router._Refused as refused:
        return refused.response
    try:
        try:
            result = assistant_service.step(report_draft.SYSTEM_PROMPT, messages, report_draft.TOOLS)
        except assistant_service.AssistantError as exc:
            return JSONResponse(status_code=502, content={"detail": client_message(exc)})
        meter.cost_mc = assistant_router._cost_mc(result["usage"])
    finally:
        balance = meter.finish()
    draft = report_draft.parse(result.get("message"), len(items))
    return JSONResponse(content={
        **draft,
        "unverified": report_draft.check(draft, title, items),
        "credit_cents": balance,
    })


@router.get("/{report_id}")
def get_report(report_id: str, session=Depends(get_session),
               ctx: AccessCtx = Depends(get_access)) -> JSONResponse:
    doc = reports_service.get_owned(session, ctx.write_owner, report_id)
    if doc is None:
        return JSONResponse(status_code=404, content=_NOT_FOUND)
    return JSONResponse(content=_with_access(ctx, reports_service.public(session, doc)))


@router.get("/{report_id}/view")
def view_report(report_id: str, session=Depends(get_session),
                ctx: AccessCtx = Depends(get_access)) -> JSONResponse:
    """The report as its readers see it, inside the app (Reports › a report ›
    View): each section rendered from its item exactly as the report's share
    page renders it, read in this workspace. A team's report is read here by
    its members, since team items have no public link yet."""
    doc = reports_service.get_owned(session, ctx.write_owner, report_id)
    if doc is None:
        return JSONResponse(status_code=404, content=_NOT_FOUND)
    return JSONResponse(content=_with_access(ctx, report_view.build(session, doc, ctx.write_owner)))


@router.put("/{report_id}")
def update_report(report_id: str, body: dict = Body(...), session=Depends(get_session),
                  ctx: AccessCtx = Depends(get_access)) -> JSONResponse:
    if reports_service.get_owned(session, ctx.write_owner, report_id) is None:
        return JSONResponse(status_code=404, content=_NOT_FOUND)
    if (denied := _write_denied(ctx)) is not None:
        return denied
    try:
        doc = reports_service.update(session, ctx.write_owner, report_id, body)
    except reports_service.ReportError as exc:
        return _refuse(exc)
    if doc is None:
        return JSONResponse(status_code=404, content=_NOT_FOUND)
    access_service.stamp_editor(session, reports_service.COLLECTION, report_id, ctx)
    return JSONResponse(content=_with_access(ctx, reports_service.public(session, doc)))


@router.delete("/{report_id}")
def delete_report(report_id: str, session=Depends(get_session),
                  ctx: AccessCtx = Depends(get_access)) -> JSONResponse:
    if reports_service.get_owned(session, ctx.write_owner, report_id) is None:
        return JSONResponse(status_code=404, content=_NOT_FOUND)
    if (denied := _write_denied(ctx)) is not None:
        return denied
    reports_service.delete(session, ctx.write_owner, report_id)
    return JSONResponse(content={"ok": True})
