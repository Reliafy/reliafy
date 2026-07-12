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

from datetime import datetime, timezone

from fastapi import Depends, Header, HTTPException

from backend import config
from backend.db import get_session

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
        return {"uid": config.DEV_USER_ID, "email": "dev@local", "name": "Dev User"}

    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing bearer token.")
    token = authorization.split(" ", 1)[1].strip()

    _ensure_init()
    from firebase_admin import auth as fb_auth

    try:
        decoded = fb_auth.verify_id_token(token)
    except Exception:  # noqa: BLE001 - any verification failure is a 401
        raise HTTPException(status_code=401, detail="Invalid or expired token.")

    return {
        "uid": decoded["uid"],
        "email": decoded.get("email"),
        "name": decoded.get("name") or decoded.get("email"),
    }


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
        "created_at": created.isoformat() if hasattr(created, "isoformat") else None,
    }
