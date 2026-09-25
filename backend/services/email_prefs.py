"""Per-user email preferences: the product-update ("What's new") opt-out.

Stored on the ``users`` document:

    email_updates_opt_out      bool; absent = subscribed
    email_unsub_token          random hex, created lazily, unique — the
                               credential in every unsubscribe link, so a
                               recipient can opt out without signing in
    email_updates_changed_at   when the preference last changed
    email_updates_source       what changed it ("one_click", "link",
                               "settings", ...)

Transactional mail (team invites, share notifications) is not covered by
this preference.
"""

from __future__ import annotations

import hmac
import re
import secrets
from datetime import datetime, timezone

_TOKEN_RE = re.compile(r"^[0-9a-f]{32}$")


def is_subscribed(user_doc: dict | None) -> bool:
    """True unless the user has opted out of product-update emails."""
    return not bool((user_doc or {}).get("email_updates_opt_out"))


def token_for(db, uid: str) -> str:
    """The user's unsubscribe token, creating it on first use.

    The conditional update means two concurrent callers can't both write a
    token: the loser re-reads and returns the winner's.
    """
    doc = db.users.find_one({"_id": uid}, {"email_unsub_token": 1})
    if doc and doc.get("email_unsub_token"):
        return doc["email_unsub_token"]
    token = secrets.token_hex(16)
    db.users.update_one(
        {"_id": uid, "email_unsub_token": {"$exists": False}},
        {"$set": {"email_unsub_token": token}},
    )
    doc = db.users.find_one({"_id": uid}, {"email_unsub_token": 1}) or {}
    if not doc.get("email_unsub_token"):
        raise LookupError(f"no user {uid!r}")
    return doc["email_unsub_token"]


def user_by_token(db, token: str | None) -> dict | None:
    """The user an unsubscribe token belongs to, or None.

    Malformed tokens are rejected before touching the database (the literal
    ``test`` used by test sends is one), and the stored value is compared in
    constant time. Every failure looks the same to the caller.
    """
    token = (token or "").strip().lower()
    if not _TOKEN_RE.match(token):
        return None
    doc = db.users.find_one({"email_unsub_token": token})
    if not doc or not hmac.compare_digest(str(doc.get("email_unsub_token", "")), token):
        return None
    return doc


def set_opt_out(db, uid: str, opted_out: bool, source: str) -> None:
    """Record the user's choice. Idempotent: an unchanged choice keeps its
    original timestamp and source."""
    db.users.update_one(
        {"_id": uid, "email_updates_opt_out": {"$ne": bool(opted_out)}},
        {"$set": {
            "email_updates_opt_out": bool(opted_out),
            "email_updates_changed_at": datetime.now(timezone.utc),
            "email_updates_source": source,
        }},
    )


def mask_email(email: str | None) -> str:
    """``derryn@gmail.com`` -> ``d****n@gmail.com``.

    Enough for a recipient to recognise their own address on the
    unsubscribe page without the token URL disclosing it. The star count is
    fixed so the local part's length isn't leaked either.
    """
    email = (email or "").strip()
    if "@" not in email:
        return ""
    local, domain = email.rsplit("@", 1)
    if len(local) <= 2:
        masked = (local[:1] or "*") + "****"
    else:
        masked = f"{local[0]}****{local[-1]}"
    return f"{masked}@{domain}"
