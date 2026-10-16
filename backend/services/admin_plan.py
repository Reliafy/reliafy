"""The operators' plan: one markdown document shown on the Admin page's Plan
tab, stored in the database (never in the repo or the bundle).

It is one document in ``app_settings``::

    {_id: "plan", markdown, source, updated_at, updated_by}

written by ``PUT /api/admin/plan`` or ``python -m backend.scripts.push_plan``
(both through :func:`store`) and read by ``GET /api/admin/plan``.

The markdown is private: nothing here logs it, only its size.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

_ID = "plan"
MAX_BYTES = 512 * 1024
MAX_SOURCE = 200

# A fenced ```mermaid block (the same rule as frontend/src/planMarkdown.js).
_MERMAID = re.compile(r"^ {0,3}(`{3,}|~{3,})[ \t]*mermaid\b[^\n]*\n", re.MULTILINE | re.IGNORECASE)


class PlanTooLarge(ValueError):
    """The markdown is over :data:`MAX_BYTES`."""


def size(markdown: str) -> int:
    return len(markdown.encode("utf-8"))


def mermaid_blocks(markdown: str) -> int:
    """How many fenced ``mermaid`` blocks the markdown has."""
    return len(_MERMAID.findall(markdown or ""))


def _aware(ts):
    if isinstance(ts, datetime) and ts.tzinfo is None:
        return ts.replace(tzinfo=timezone.utc)
    return ts


def _view(doc: dict) -> dict:
    ts = _aware(doc.get("updated_at"))
    return {
        "markdown": doc.get("markdown") or "",
        "updated_at": ts.isoformat() if isinstance(ts, datetime) else None,
        "updated_by": doc.get("updated_by"),
        "source": doc.get("source") or "",
    }


def get(db) -> dict | None:
    """The stored plan as the API returns it, or None when there is none."""
    doc = db.app_settings.find_one({"_id": _ID})
    if not doc or not isinstance(doc.get("markdown"), str):
        return None
    return _view(doc)


def store(db, markdown: str, source: str, by: str) -> dict:
    """Replace the plan and return it as :func:`get` does. Raises
    :class:`PlanTooLarge` over :data:`MAX_BYTES`."""
    n = size(markdown)
    if n > MAX_BYTES:
        raise PlanTooLarge(f"The plan is {n:,} bytes; the limit is {MAX_BYTES:,}.")
    now = datetime.now(timezone.utc)
    doc = {
        "markdown": markdown,
        "source": (source or "").strip()[:MAX_SOURCE],
        # Milliseconds, as Mongo keeps them, so the PUT answers what a GET will.
        "updated_at": now.replace(microsecond=now.microsecond // 1000 * 1000),
        "updated_by": by,
    }
    db.app_settings.update_one({"_id": _ID}, {"$set": doc}, upsert=True)
    logger.info("Plan stored (%d bytes, %d mermaid blocks)", n, mermaid_blocks(markdown))
    return _view(doc)
