"""The public page of a report (#30): each section rendered as its item's own
share page would be.

Every section replays the item's normal detail handler under the same guest
access context a single-item share link uses (``public_links.guest_ctx``),
so a report shows exactly what sharing each item alone would show — no more.
Each item is checked again here, not only when the report was saved: one that
was deleted, or no longer belongs to the report's owner, renders as an
unavailable section with a plain reason.
"""

from __future__ import annotations

import json
import logging

from backend.services import public_links as links_service
from backend.services import reports as reports_service

logger = logging.getLogger(__name__)

UNAVAILABLE = "This item is no longer available."


def item_payload(session, collection: str, artifact_id: str, grantor_uid: str) -> dict | None:
    """One item's public payload, read as ``grantor_uid``'s share link would
    read it; None when the grantor can't publish it (any more)."""
    from backend.routers import public as public_router

    doc = session[collection].find_one({"_id": artifact_id})
    if not reports_service.item_allowed(doc, grantor_uid):
        return None
    ctx = links_service.guest_ctx(doc["owner_id"], grantor_uid)
    try:
        response = public_router._detail_handler(collection)(artifact_id, session, ctx)
    except Exception:  # pragma: no cover - defensive: one bad section mustn't sink the page
        logger.exception("Report section %s/%s failed", collection, artifact_id)
        return None
    if getattr(response, "status_code", 200) != 200:
        return None
    payload = json.loads(response.body)
    if collection == "rbds":
        payload = public_router._with_rbd_analysis(session, payload, artifact_id, doc["owner_id"], ctx)
    return links_service.sanitize(payload)


def build(session, report: dict, grantor_uid: str) -> dict:
    """The report's public payload: the header fields and one entry per
    section, each carrying its item's public payload or why it's missing."""
    sections = []
    for s in report.get("sections") or []:
        payload = item_payload(session, s["collection"], s["artifact_id"], grantor_uid)
        sections.append({
            "collection": s["collection"],
            "kind": reports_service.ITEM_KINDS.get(s["collection"], ""),
            "name": (payload or {}).get("name"),
            "note": s.get("note") or "",
            "artifact": payload,
            "unavailable": None if payload is not None else UNAVAILABLE,
        })
    updated = report.get("updated_at") or report.get("created_at")
    return {
        "name": report.get("name") or "",
        "author": report.get("author") or "",
        "introduction": report.get("introduction") or "",
        "date": reports_service._iso(updated),
        "sections": sections,
    }
