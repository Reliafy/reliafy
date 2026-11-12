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

from backend.errors import client_message
from backend.services import public_links as links_service
from backend.services import reports as reports_service

logger = logging.getLogger(__name__)

UNAVAILABLE = "This item is no longer available."


def item_payload(session, collection: str, artifact_id: str, grantor: str) -> dict | None:
    """One item's public payload, read as a share link of ``grantor`` (the
    report's workspace: a uid, or ``team:<id>`` for the notes' draft in a
    team) would read it; None when the item isn't the grantor's (any more)."""
    from backend.routers import public as public_router

    doc = session[collection].find_one({"_id": artifact_id})
    if not reports_service.item_allowed(doc, grantor):
        return None
    ctx = links_service.guest_ctx(doc["owner_id"], grantor)
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
    if collection == "fault_trees":
        payload = _with_fault_tree_analysis(session, payload, doc["owner_id"], ctx)
    return links_service.sanitize(payload)


def _with_fault_tree_analysis(session, payload: dict, owner_id: str, ctx) -> dict:
    """A fault tree's section: its top event, drawn tree and cut sets, worked
    out now (exact and quick, as the editor's own analysis), with saved models
    resolved in the grantor's scope. A tree that can't be analysed yet (an
    event with no data) says why instead."""
    from backend.services import fault_trees as ft_service
    from backend.services.rbd_analysis import AnalysisError

    tree = payload.pop("tree", None) or {}
    try:
        analysis, error = ft_service.analyse_for_owner(session, tree, [*ctx.read_owners, owner_id]), None
    except (ft_service.FaultTreeError, AnalysisError) as exc:
        analysis, error = None, client_message(exc)
    except Exception:  # pragma: no cover - defensive: one bad section mustn't sink the page
        logger.exception("Fault tree section failed")
        analysis, error = None, "This fault tree couldn't be analysed."
    return {**payload, "analysis": analysis, "analysis_error": error}


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
