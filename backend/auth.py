"""Authentication: verify Firebase ID tokens and identify the current user.

The React SPA signs users in with Firebase (email/password or Google) and sends
the resulting ID token as a ``Bearer`` token. Here we verify it with the
Firebase Admin SDK and expose ``get_current_user`` as a FastAPI dependency that
yields ``{"uid", "email", "name"}``. The ``uid`` becomes each record's
``owner_id`` so users only see their own data.

Token verification is offline (signature check against Google's cached public
certs); on Cloud Run the default service account's ADC plus the project id is
all that's needed — no service-account key file.

For local development, set ``AUTH_DISABLED=true`` to skip Firebase entirely and
treat every request as a fixed dev user (mirrors the mongomock fallback so the
app runs with zero external dependencies).
"""

from __future__ import annotations

import hashlib
import logging
import threading
import time
from collections import OrderedDict
from datetime import datetime, timezone

from fastapi import Depends, Header, HTTPException

from backend import config
from backend.db import get_session

logger = logging.getLogger(__name__)

_initialized = False


def _ensure_init() -> None:
    """Initialise firebase-admin once, lazily (import only when really used)."""
    global _initialized
    if _initialized:
        return
    import firebase_admin

    if not firebase_admin._apps:
        options = (
            {"projectId": config.FIREBASE_PROJECT_ID}
            if config.FIREBASE_PROJECT_ID
            else None
        )
        firebase_admin.initialize_app(options=options)
    _initialized = True


def get_current_user(authorization: str | None = Header(default=None)) -> dict:
    """FastAPI dependency: the authenticated user as ``{uid, email, name}``.

    Raises 401 (so the SPA redirects to /login) when the token is missing or
    invalid. Returns a fixed dev user when ``AUTH_DISABLED`` is set.
    """
    if config.AUTH_DISABLED:
        return _noted({"uid": config.DEV_USER_ID, "email": "dev@local", "name": "Dev User",
                       "email_verified": True})

    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing bearer token.")
    token = authorization.split(" ", 1)[1].strip()

    decoded = _verified_claims(token)
    return _noted({
        "uid": decoded["uid"],
        "email": decoded.get("email"),
        "name": decoded.get("name") or decoded.get("email"),
        # Email-based trust (team invites, shares to an address, operator
        # access) needs the address verified — Google sign-ins always are;
        # email/password accounts once the user follows Firebase's link.
        "email_verified": decoded.get("email_verified") is True,
    })


# Successful verifications are remembered briefly: ``check_revoked`` looks the
# account up at Firebase, and the SPA sends many requests per page. A revoked
# session or disabled account is refused within this window.
_REVOCATION_RECHECK_SECONDS = 60
_VERIFIED_CACHE_MAX = 2048
_verified_cache: "OrderedDict[str, tuple[float, dict]]" = OrderedDict()
_verified_lock = threading.Lock()


def _verified_claims(token: str) -> dict:
    """The decoded claims of a Firebase ID token, checked for revocation.
    Raises a 401 for an invalid, expired or revoked token or a disabled user."""
    key = hashlib.sha256(token.encode()).hexdigest()
    now = time.monotonic()
    with _verified_lock:
        hit = _verified_cache.get(key)
        if hit is not None and hit[0] > now:
            _verified_cache.move_to_end(key)
            return hit[1]

    _ensure_init()
    from firebase_admin import auth as fb_auth

    try:
        decoded = fb_auth.verify_id_token(token, check_revoked=True)
    except (fb_auth.RevokedIdTokenError, fb_auth.UserDisabledError):
        raise HTTPException(status_code=401, detail="This session has ended — sign in again.")
    except Exception:  # noqa: BLE001 - any verification failure is a 401
        raise HTTPException(status_code=401, detail="Invalid or expired token.")

    expires = min(now + _REVOCATION_RECHECK_SECONDS,
                  now + max(0.0, float(decoded.get("exp", 0)) - time.time()))
    with _verified_lock:
        _verified_cache[key] = (expires, decoded)
        _verified_cache.move_to_end(key)
        while len(_verified_cache) > _VERIFIED_CACHE_MAX:
            _verified_cache.popitem(last=False)
    return decoded


def _noted(user: dict) -> dict:
    """Tell product-usage logging who this request is for (no-op outside a
    request, and never raises)."""
    try:
        from backend.services import usage as usage_service

        usage_service.note_user(user)
    except Exception:  # noqa: BLE001
        logger.debug("usage note failed", exc_info=True)
    return user


def upsert_user(db, user: dict) -> dict:
    """Record/refresh the user's profile on first sight (and each login)."""
    now = datetime.now(timezone.utc)
    email = user.get("email")
    result = db.users.update_one(
        {"_id": user["uid"]},
        {
            "$set": {
                "email": email,
                # Lowercased copy for team-invite / share lookups by email.
                "email_lc": (email or "").strip().lower() or None,
                # Whether the address is proven — invites and shares look
                # accounts up by email only when it is.
                "email_verified": bool(user.get("email_verified")),
                "name": user.get("name"),
                "last_login": now,
            },
            "$setOnInsert": {"created_at": now},
        },
        upsert=True,
    )
    if result.upserted_id is not None:
        # First sight of this account — the conversion event the traffic
        # funnel needs. Server-side so it can't be missed or double-fired.
        from backend.services import metrics as metrics_service

        metrics_service.record_event(db, name="signup", path="/login")
        # Notify the operators (ADMIN_EMAILS) that a new account signed up.
        # Non-blocking (daemon thread) and never allowed to break login.
        try:
            from backend.services import email as email_service

            email_service.new_signup(email, user.get("name"))
        except Exception:  # noqa: BLE001 - notification must not fail signup
            logger.exception("new-signup notification failed")
    return user


def current_user_doc(user: dict = Depends(get_current_user), db=Depends(get_session)) -> dict:
    """Dependency that also upserts the profile and returns it — used by /api/me."""
    upsert_user(db, user)
    doc = db.users.find_one({"_id": user["uid"]}) or {}
    created = doc.get("created_at")
    return {
        "uid": user["uid"],
        "email": user.get("email"),
        "name": user.get("name"),
        "email_verified": bool(user.get("email_verified")),
        "created_at": created.isoformat() if hasattr(created, "isoformat") else None,
    }
