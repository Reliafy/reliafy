"""The MCP connector's on/off switch.

When it's off, ``/mcp`` and the OAuth endpoints only connectors use
(registration, authorization, consent, token) refuse at once, before any
authentication, so no connector holds a request open or starts a sign-in.
The REST API, ``rlf_`` tokens on it, token revocation and the OAuth
discovery documents are unaffected: only MCP is switched.

The switch is one document in ``app_settings``::

    {_id: "mcp", enabled, changed_at, changed_by, reason}

set by an operator (:func:`set_enabled`), or turned on by itself when a
user newly subscribes to Pro (:func:`turn_on_for_first_pro`). With nothing
stored it is off on the cloud (billing on) and on for a self-hosted install,
so open-source users need no setup. ``MCP_ENABLED`` (config) overrides it
both ways.

Reads are cached for :data:`CACHE_SECONDS` per process, so ``/mcp`` doesn't
read the database on every request; a change made on this process clears
the cache, one made on another instance is seen within that time.
"""

from __future__ import annotations

import logging
import threading
import time
from datetime import datetime, timezone

from backend import config

logger = logging.getLogger(__name__)

SUPPORT_EMAIL = "hello@reliafy.com"
OFF_MESSAGE = f"Reliafy's MCP connector isn't switched on. Email {SUPPORT_EMAIL} to use it."

CACHE_SECONDS = 30.0
_ID = "mcp"
_cache: tuple[float, bool] | None = None  # (monotonic time read, enabled)
_lock = threading.Lock()


def forced() -> bool | None:
    """The ``MCP_ENABLED`` override: True / False, or None to use the switch."""
    return config.MCP_ENABLED


def default() -> bool:
    """With nothing stored: on for a self-hosted install, off on the cloud
    (the same test as :func:`billing.api_access_allowed`'s self-hosted case)."""
    return not config.BILLING_ENABLED


def clear_cache() -> None:
    global _cache
    with _lock:
        _cache = None


def cached() -> bool | None:
    """The switch without touching the database: the override, or a fresh
    cached read, else None."""
    if forced() is not None:
        return forced()
    hit = _cache
    if hit is not None and time.monotonic() - hit[0] < CACHE_SECONDS:
        return hit[1]
    return None


def _stored(db) -> dict | None:
    return db.app_settings.find_one({"_id": _ID})


def _value(doc: dict | None) -> bool:
    if doc is not None and isinstance(doc.get("enabled"), bool):
        return doc["enabled"]
    return default()


def enabled(db) -> bool:
    """Whether MCP is on now (cached; see the module docstring)."""
    global _cache
    hit = cached()
    if hit is not None:
        return hit
    try:
        on = _value(_stored(db))
    except Exception:  # noqa: BLE001 - a read failure falls back, uncached
        logger.warning("MCP switch: couldn't read the setting; using the default", exc_info=True)
        return default()
    with _lock:
        _cache = (time.monotonic(), on)
    return on


async def is_on() -> bool:
    """:func:`enabled` for the ASGI layer: the database read, when the cache
    can't answer, runs off the event loop."""
    hit = cached()
    if hit is not None:
        return hit
    import anyio

    from backend.db import get_db

    return await anyio.to_thread.run_sync(enabled, get_db())


def state(db) -> dict:
    """The effective value and where it comes from."""
    doc = _stored(db) or {}
    stored = doc.get("enabled") if isinstance(doc.get("enabled"), bool) else None
    changed_at = doc.get("changed_at")
    if isinstance(changed_at, datetime) and changed_at.tzinfo is None:
        changed_at = changed_at.replace(tzinfo=timezone.utc)
    return {
        "enabled": forced() if forced() is not None else (stored if stored is not None else default()),
        "stored": stored,
        "default": default(),
        "override": forced(),
        "changed_at": changed_at.isoformat() if isinstance(changed_at, datetime) else None,
        "changed_by": doc.get("changed_by"),
        "reason": doc.get("reason"),
    }


def set_enabled(db, on: bool, by: str, reason: str) -> dict:
    """Store the switch (the override, if set, still wins) and return :func:`state`."""
    db.app_settings.update_one(
        {"_id": _ID},
        {"$set": {"enabled": bool(on), "changed_at": datetime.now(timezone.utc),
                  "changed_by": by, "reason": reason}},
        upsert=True,
    )
    clear_cache()
    logger.info("MCP switch set %s (%s)", "on" if on else "off", reason)
    return state(db)


def turn_on_for_first_pro(db, uid: str) -> bool:
    """Turn MCP on for a user who has just become Pro through Stripe, if it's
    off and not forced off. Idempotent: once it's on (a replayed webhook, a
    second subscriber) nothing more happens. Returns whether it turned on.

    Alerts the operator by push — without the user's email."""
    if forced() is not None:
        return False
    if _value(_stored(db)):
        return False
    from pymongo.errors import DuplicateKeyError

    fields = {"enabled": True, "changed_at": datetime.now(timezone.utc),
              "changed_by": uid, "reason": "first Pro subscriber"}
    try:
        # Only the request that flips it reports it: one that finds it on
        # already matches nothing, and its upsert collides on the _id.
        res = db.app_settings.update_one({"_id": _ID, "enabled": {"$ne": True}},
                                         {"$set": fields}, upsert=True)
    except DuplicateKeyError:
        return False
    if not (res.modified_count or res.upserted_id is not None):
        return False
    clear_cache()
    logger.info("MCP switch turned on by a new Pro subscriber (uid %s)", uid)
    from backend.services import push as push_service

    push_service.send("MCP connector switched on", "MCP connector switched on: a new Pro subscriber")
    return True


def log_refusal(method: str, path: str) -> None:
    """One INFO line per refused request: method and path only (never the
    query string or headers, which can carry codes and tokens)."""
    logger.info("MCP connector is off: refused %s %s", method, path)
