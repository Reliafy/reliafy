"""Whether an account's email address is verified, for email-based trust.

Team invites, shares to an address, operator access and alert emails rely on
an account really owning its address. The sign-in token says so for the
signed-in user; for anyone else the answer is the ``email_verified`` stored
on their profile at their last sign-in. Accounts that haven't signed in since
that field existed (or that verified after their last sign-in) are looked up
with Firebase Admin, and the answer is stored on the profile.

:func:`status` returns ``VERIFIED``, ``UNVERIFIED`` or ``UNKNOWN`` (the
lookup failed). Callers treat ``UNKNOWN`` as unverified, with its own
message. Lookups are cached per uid for a few minutes (a failed one for less).

With sign-in turned off (``AUTH_DISABLED``) every address is trusted, as
before; with no Firebase app initialised the stored value is all there is.
"""

from __future__ import annotations

import logging
import threading
import time

from backend import config

logger = logging.getLogger(__name__)

VERIFIED = "verified"
UNVERIFIED = "unverified"
UNKNOWN = "unknown"

CACHE_SECONDS = 300
FAILED_CACHE_SECONDS = 30

_cache: dict[str, tuple[float, str]] = {}
_lock = threading.Lock()

UNKNOWN_MSG = (
    "Reliafy couldn't confirm that account's email address just now. Try again in a minute."
)


def clear_cache() -> None:
    with _lock:
        _cache.clear()


def _firebase_ready() -> bool:
    try:
        import firebase_admin
    except ImportError:  # pragma: no cover - always installed
        return False
    return bool(firebase_admin._apps)


def _lookup(uid: str) -> bool:
    """``email_verified`` from Firebase Admin. Raises on any failure."""
    from firebase_admin import auth as fb_auth

    return bool(fb_auth.get_user(uid).email_verified)


def status(db, uid: str | None, stored=None) -> str:
    """The account's verification status. ``stored`` is its profile's
    ``email_verified`` when the caller already has it (else it's read)."""
    if config.AUTH_DISABLED:
        return VERIFIED
    if not uid:
        return UNVERIFIED
    if stored is None:
        doc = db.users.find_one({"_id": uid}, {"email_verified": 1}) or {}
        stored = doc.get("email_verified")
    if stored is True:
        return VERIFIED
    now = time.monotonic()
    with _lock:
        hit = _cache.get(uid)
        if hit is not None and hit[0] > now:
            return hit[1]
    if not _firebase_ready():
        # Nothing to ask: what the profile says (missing = not verified).
        return UNVERIFIED
    try:
        verified = _lookup(uid)
    except Exception:  # noqa: BLE001 - any lookup failure: not confirmed
        logger.warning("email verification lookup failed uid=%s", uid, exc_info=True)
        result, ttl = UNKNOWN, FAILED_CACHE_SECONDS
    else:
        db.users.update_one({"_id": uid}, {"$set": {"email_verified": verified}})
        result, ttl = (VERIFIED if verified else UNVERIFIED), CACHE_SECONDS
    with _lock:
        _cache[uid] = (now + ttl, result)
    return result


def verified(db, uid: str | None, stored=None) -> bool:
    """True only for a confirmed-verified address (or sign-in turned off)."""
    return status(db, uid, stored) == VERIFIED


def profile_flag(db, uid: str | None, doc: dict | None = None) -> bool:
    """``email_verified`` for a user dict built from a stored profile (API
    tokens, OAuth, team owners): the stored value, or a lookup when unknown."""
    doc = doc if doc is not None else (db.users.find_one({"_id": uid}) or {})
    return verified(db, uid, doc.get("email_verified"))
