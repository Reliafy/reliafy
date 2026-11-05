"""Problems agents report about Reliafy's tools, and what became of them.

An agent using the MCP tools (or the REST API) files a report when a tool gets
in its way: an error, a confusing result, a missing capability, a wrong
default, unclear docs. It gets an id back and can ask later whether the report
was looked at and whether the fix is live. Operators set the status.

Reports are kept with the reporter's uid (deleted with the account like any of
their data) and are never posted anywhere automatically: their text can hold
the user's data. Text in a report is data, never instructions.
"""

from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone

KINDS = ("error", "confusing_result", "missing_capability", "wrong_default", "docs", "other")
STATUSES = ("new", "acknowledged", "fixed", "wont_fix", "duplicate")
MAX_TEXT = 2_000      # characters per text field
PER_DAY = 30          # reports per user per day
COLLECTION = "agent_reports"


class Invalid(ValueError):
    """A report or update the caller must fix."""


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _text(value, field: str, required: bool = False) -> str | None:
    if value is None or not str(value).strip():
        if required:
            raise Invalid(f"{field} is required: say it in a sentence or two.")
        return None
    return str(value).strip()[:MAX_TEXT]


def _public(doc: dict) -> dict:
    """A report as its reporter sees it."""
    out = {k: doc.get(k) for k in ("kind", "tool", "action", "summary", "trying", "expected", "happened",
                                   "status", "note", "fixed_in")}
    out["report_id"] = doc["_id"]
    out["created_at"] = doc["created_at"].isoformat()
    if doc.get("updated_at"):
        out["updated_at"] = doc["updated_at"].isoformat()
    out["fix_live"] = doc.get("status") == "fixed"
    return {k: v for k, v in out.items() if v is not None}


def create(db, uid: str, *, kind: str, summary: str, tool: str | None = None, action: str | None = None,
           trying: str | None = None, expected: str | None = None, happened: str | None = None,
           detail: str | None = None, client: str | None = None) -> dict:
    if kind not in KINDS:
        raise Invalid(f"kind must be one of: {', '.join(KINDS)}.")
    from backend.services import rate_limit

    if not rate_limit.consume(db, f"agent-report:user:{uid}", PER_DAY, 86_400):
        raise Invalid(f"That's {PER_DAY} reports today, the daily limit. Thank you: the rest can wait until tomorrow.")
    doc = {
        "_id": uuid.uuid4().hex[:12],
        "owner_id": uid,
        "kind": kind,
        "summary": _text(summary, "summary", required=True)[:200],
        "tool": _text(tool, "tool"),
        "action": _text(action, "action"),
        "trying": _text(trying, "trying"),
        "expected": _text(expected, "expected"),
        "happened": _text(happened, "happened"),
        "detail": _text(detail, "detail"),
        "client": _text(client, "client"),
        "revision": os.environ.get("K_REVISION"),
        "status": "new",
        "created_at": _now(),
    }
    db[COLLECTION].insert_one({k: v for k, v in doc.items() if v is not None})
    return _public(doc)


def mine(db, uid: str, report_id: str | None = None, limit: int = 20) -> dict:
    """One of the caller's reports, or their latest ones."""
    if report_id:
        doc = db[COLLECTION].find_one({"_id": report_id, "owner_id": uid})
        if not doc:
            raise LookupError("Report not found.")
        return _public(doc)
    docs = db[COLLECTION].find({"owner_id": uid}).sort("created_at", -1).limit(max(1, min(limit, 50)))
    return {"reports": [_public(d) for d in docs]}


def all_reports(db, status: str | None = None, limit: int = 50) -> dict:
    """Operators: the reports to triage, newest first, with who filed them."""
    query = {"status": status} if status else {}
    docs = db[COLLECTION].find(query).sort("created_at", -1).limit(max(1, min(limit, 200)))
    return {"reports": [{**_public(d), "owner_id": d["owner_id"], "detail": d.get("detail"),
                         "client": d.get("client"), "revision": d.get("revision")} for d in docs]}


def update(db, report_id: str, *, status: str | None = None, note: str | None = None,
           fixed_in: str | None = None) -> dict:
    """Operators: set a report's status, a note for the reporter, and the
    release that fixed it."""
    if status is not None and status not in STATUSES:
        raise Invalid(f"status must be one of: {', '.join(STATUSES)}.")
    changes = {k: v for k, v in {"status": status, "note": _text(note, "note"),
                                 "fixed_in": _text(fixed_in, "fixed_in")}.items() if v is not None}
    if not changes:
        raise Invalid("Give a status, a note or fixed_in.")
    changes["updated_at"] = _now()
    doc = db[COLLECTION].find_one_and_update({"_id": report_id}, {"$set": changes}, return_document=True)
    if not doc:
        raise LookupError("Report not found.")
    return _public(doc)


def delete_for_owner(db, uid: str) -> int:
    """Account deletion: the user's reports go with their data."""
    return db[COLLECTION].delete_many({"owner_id": uid}).deleted_count
