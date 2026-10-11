"""Reports API (#30, #41): compose saved items into one shareable page, and
draft its notes with the assistant.

Saving a report publishes nothing. It is published like any other item,
with a public link (``POST /api/public-links`` with ``collection:
"reports"``), so the same passphrase, expiry and revoke apply.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Body, Depends
from fastapi.responses import JSONResponse

from backend.auth import get_current_user
from backend.db import get_session
from backend.services import assistant as assistant_service
from backend.services import report_draft
from backend.services import report_facts
from backend.services import report_view
from backend.services import reports as reports_service

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/reports")

_NOT_FOUND = {"detail": "Report not found."}


def _refuse(exc: reports_service.ReportError) -> JSONResponse:
    return JSONResponse(status_code=exc.status, content={"detail": str(exc)})


@router.get("")
def list_reports(session=Depends(get_session), user: dict = Depends(get_current_user)) -> dict:
    return {"reports": [reports_service.public(session, d)
                        for d in reports_service.list_reports(session, user["uid"])]}


@router.get("/items")
def pickable_items(session=Depends(get_session), user: dict = Depends(get_current_user)) -> dict:
    """What the user can add to a report: their own items, then the samples."""
    hidden = set((session.users.find_one({"_id": user["uid"]}, {"hidden_samples": 1}) or {})
                 .get("hidden_samples") or [])
    return {"items": reports_service.pickable_items(session, user["uid"], hidden),
            "max_sections": reports_service.MAX_SECTIONS}


@router.post("")
def create_report(body: dict = Body(...), session=Depends(get_session),
                  user: dict = Depends(get_current_user)) -> JSONResponse:
    try:
        doc = reports_service.create(session, user["uid"], body)
    except reports_service.ReportError as exc:
        return _refuse(exc)
    return JSONResponse(content=reports_service.public(session, doc))


@router.post("/draft")
def draft_notes(
    title: str = Body(default=""),
    sections: list = Body(...),
    session=Depends(get_session),
    user: dict = Depends(get_current_user),
) -> JSONResponse:
    """Draft the introduction and section notes from the items' stored
    results. Metered and gated exactly like an assistant step (AI configured,
    credits, one request at a time); returns the draft for the owner to
    edit — nothing is saved or published."""
    from backend.routers import assistant as assistant_router

    try:
        cleaned = reports_service.clean_sections(session, user["uid"], sections)
    except reports_service.ReportError as exc:
        return _refuse(exc)
    items = []
    for s in cleaned:
        payload = report_view.item_payload(session, s["collection"], s["artifact_id"], user["uid"])
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
            return JSONResponse(status_code=502, content={"detail": str(exc)})
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
               user: dict = Depends(get_current_user)) -> JSONResponse:
    doc = reports_service.get_owned(session, user["uid"], report_id)
    if doc is None:
        return JSONResponse(status_code=404, content=_NOT_FOUND)
    return JSONResponse(content=reports_service.public(session, doc))


@router.put("/{report_id}")
def update_report(report_id: str, body: dict = Body(...), session=Depends(get_session),
                  user: dict = Depends(get_current_user)) -> JSONResponse:
    try:
        doc = reports_service.update(session, user["uid"], report_id, body)
    except reports_service.ReportError as exc:
        return _refuse(exc)
    if doc is None:
        return JSONResponse(status_code=404, content=_NOT_FOUND)
    return JSONResponse(content=reports_service.public(session, doc))


@router.delete("/{report_id}")
def delete_report(report_id: str, session=Depends(get_session),
                  user: dict = Depends(get_current_user)) -> JSONResponse:
    if not reports_service.delete(session, user["uid"], report_id):
        return JSONResponse(status_code=404, content=_NOT_FOUND)
    return JSONResponse(content={"ok": True})
