"""Reports (#30): several saved items composed into one public page.

A report is a small owned document — a title, an author/organisation line,
an introduction and an ordered list of sections, each pointing at one saved
item (a model, an analysis, a diagram, a fleet …) with an optional note. It
holds no results of its own: the public page renders each section through
the item's normal public view, live, so a report always shows the items as
they are now.

Publishing reuses the public share links unchanged (``public_links``): a
report is one more linkable collection, so it gets the same owner-only
creation, expiry, passphrase, revocation and noindex as any other share.
Nothing is published when a report is saved; a link is a separate, explicit
step.

Which items a report may hold: the owner's own personal items and the shared
samples (which every account can already see). Team items can't be linked
publicly yet, so they can't go in a report either. Ownership is checked when
the report is saved and again, per section, every time the page is opened:
a section whose item was deleted or moved shows as unavailable, never as
someone else's data.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from backend.config import SAMPLE_OWNER
from backend.services import access
from backend.services import samples as samples_service

COLLECTION = "reports"

# Items a report can hold: every kind with a public page, in the order the
# picker lists them.
ITEM_KINDS = {
    "models": "Non-repairable model",
    "recurrent_models": "Recurrent-event model",
    "degradation_models": "Degradation model",
    "rbds": "Block diagram",
    "strategy_analyses": "Strategy analysis",
    "fleets": "Fleet forecast",
    "rcm_studies": "RCM study",
    "datasets": "Dataset",
}

MAX_SECTIONS = 12
MAX_TITLE = 160
MAX_AUTHOR = 160
MAX_INTRO = 5000
MAX_NOTE = 3000
MAX_REPORTS = 200


class ReportError(ValueError):
    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status


def _now():
    return datetime.now(timezone.utc)


def _text(value, limit: int, what: str, *, one_line: bool = False) -> str:
    text = str(value or "").strip()
    if one_line:
        text = " ".join(text.split())
    if len(text) > limit:
        raise ReportError(f"Keep the {what} under {limit:,} characters.")
    return text


def item_allowed(doc: dict | None, uid: str) -> bool:
    """Whether an item may appear in ``uid``'s report: theirs, or a sample."""
    if doc is None:
        return False
    owner = doc.get("owner_id")
    return owner == uid or samples_service.is_sample(owner)


def clean_sections(db, uid: str, sections) -> list[dict]:
    if not isinstance(sections, list) or not sections:
        raise ReportError("Add at least one item to the report.")
    if len(sections) > MAX_SECTIONS:
        raise ReportError(f"A report can hold up to {MAX_SECTIONS} items.")
    out, seen = [], set()
    for raw in sections:
        if not isinstance(raw, dict):
            raise ReportError("Each section needs a collection and an artifact_id.")
        collection = raw.get("collection")
        artifact_id = str(raw.get("artifact_id") or "")
        if collection not in ITEM_KINDS:
            raise ReportError(f"'{collection}' can't go in a report.")
        if (collection, artifact_id) in seen:
            raise ReportError("Each item can appear in a report only once.")
        seen.add((collection, artifact_id))
        doc = db[collection].find_one({"_id": artifact_id}, {"owner_id": 1})
        if not item_allowed(doc, uid):
            if doc is not None and access.is_team_owner(doc.get("owner_id")):
                raise ReportError("Team items can't go in a report yet.")
            raise ReportError("One of the items wasn't found among your own.", 404)
        out.append({
            "collection": collection,
            "artifact_id": artifact_id,
            "note": _text(raw.get("note"), MAX_NOTE, "section note"),
        })
    return out


def _fields(db, uid: str, body: dict) -> dict:
    title = _text(body.get("title"), MAX_TITLE, "title", one_line=True)
    if not title:
        raise ReportError("Give the report a title.")
    return {
        "name": title,
        "author": _text(body.get("author"), MAX_AUTHOR, "author line", one_line=True),
        "introduction": _text(body.get("introduction"), MAX_INTRO, "introduction"),
        "sections": clean_sections(db, uid, body.get("sections")),
    }


def create(db, uid: str, body: dict) -> dict:
    fields = _fields(db, uid, body)
    if db[COLLECTION].count_documents({"owner_id": uid}) >= MAX_REPORTS:
        raise ReportError(f"You can keep up to {MAX_REPORTS} reports: delete one you no longer need.")
    now = _now()
    doc = {"_id": uuid.uuid4().hex, "owner_id": uid, "created_at": now, "updated_at": now, **fields}
    db[COLLECTION].insert_one(doc)
    return doc


def get_owned(db, uid: str, report_id: str) -> dict | None:
    doc = db[COLLECTION].find_one({"_id": report_id})
    return doc if doc is not None and doc.get("owner_id") == uid else None


def update(db, uid: str, report_id: str, body: dict) -> dict | None:
    if get_owned(db, uid, report_id) is None:
        return None
    fields = {**_fields(db, uid, body), "updated_at": _now()}
    db[COLLECTION].update_one({"_id": report_id, "owner_id": uid}, {"$set": fields})
    return get_owned(db, uid, report_id)


def delete(db, uid: str, report_id: str) -> bool:
    """Delete a report and every public link to it (they'd show nothing)."""
    result = db[COLLECTION].delete_one({"_id": report_id, "owner_id": uid})
    if not result.deleted_count:
        return False
    db.public_links.delete_many({"collection": COLLECTION, "artifact_id": report_id, "grantor_uid": uid})
    return True


def list_reports(db, uid: str) -> list[dict]:
    return list(db[COLLECTION].find({"owner_id": uid}).sort("updated_at", -1))


def _names(db, sections: list[dict]) -> dict:
    """(collection, id) -> item name, one query per collection."""
    by_coll: dict[str, list[str]] = {}
    for s in sections:
        by_coll.setdefault(s["collection"], []).append(s["artifact_id"])
    names = {}
    for coll, ids in by_coll.items():
        for doc in db[coll].find({"_id": {"$in": ids}}, {"name": 1}):
            names[(coll, doc["_id"])] = doc.get("name")
    return names


def _iso(value):
    if isinstance(value, datetime) and value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.isoformat() if hasattr(value, "isoformat") else value


def public(db, doc: dict) -> dict:
    """A report as its owner sees it in the app."""
    names = _names(db, doc.get("sections") or [])
    return {
        "id": doc["_id"],
        "title": doc.get("name") or "",
        "author": doc.get("author") or "",
        "introduction": doc.get("introduction") or "",
        "sections": [
            {
                "collection": s["collection"],
                "artifact_id": s["artifact_id"],
                "kind": ITEM_KINDS.get(s["collection"], ""),
                "name": names.get((s["collection"], s["artifact_id"])),
                "note": s.get("note") or "",
            }
            for s in doc.get("sections") or []
        ],
        "created_at": _iso(doc.get("created_at")),
        "updated_at": _iso(doc.get("updated_at")),
    }


def pickable_items(db, uid: str, hidden: set | None = None) -> list[dict]:
    """Everything the user could add to a report: their own items (newest
    first) and then the samples they haven't hidden."""
    hidden = hidden or set()
    own, samples = [], []
    for coll, kind in ITEM_KINDS.items():
        cursor = db[coll].find(
            {"owner_id": {"$in": [uid, SAMPLE_OWNER]}},
            {"name": 1, "owner_id": 1, "updated_at": 1, "created_at": 1},
        )
        for doc in cursor:
            sample = samples_service.is_sample(doc.get("owner_id"))
            if sample and doc["_id"] in hidden:
                continue
            row = {
                "collection": coll,
                "artifact_id": doc["_id"],
                "kind": kind,
                "name": doc.get("name") or "Untitled",
                "is_sample": sample,
                "updated_at": _iso(doc.get("updated_at") or doc.get("created_at")),
            }
            (samples if sample else own).append(row)
    own.sort(key=lambda r: str(r["updated_at"] or ""), reverse=True)
    return own + samples
