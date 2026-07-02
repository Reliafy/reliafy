"""Credits, plans, and AI cost accounting.

A user document carries a small ledger: ``credit_cents`` (prepaid AI balance,
USD cents), ``plan`` ('free'|'pro') with ``plan_until``, and
``stripe_customer_id``. Every grant/charge is also appended to the
``credit_ledger`` collection for an audit trail.

Everything here is dormant unless :data:`backend.config.BILLING_ENABLED` is set:
plan caps aren't enforced and AI calls aren't charged, so the app behaves
exactly as before until billing is turned on.
"""

from __future__ import annotations

import math
from datetime import datetime, timezone

from backend import config
from backend.config import SAMPLE_OWNER


def _now():
    return datetime.now(timezone.utc)


def _ledger(db, uid: str, kind: str, cents: int, reason: str, ref: str = "") -> None:
    db.credit_ledger.insert_one(
        {"uid": uid, "kind": kind, "cents": cents, "reason": reason, "ref": ref, "ts": _now()}
    )


def is_admin_user(user: dict) -> bool:
    """Operator accounts (ADMIN_EMAILS env): full access regardless of payment.

    ``user`` is the authenticated ``{uid, email, name}`` dict, so this works on
    every request without a DB lookup.
    """
    email = (user.get("email") or "").strip().lower()
    return bool(email) and email in config.ADMIN_EMAILS


def is_pro(account: dict) -> bool:
    if account.get("plan") != "pro":
        return False
    until = account.get("plan_until")
    if until is None:
        return True
    if isinstance(until, str):
        try:
            until = datetime.fromisoformat(until)
        except ValueError:
            return True
    if until.tzinfo is None:
        until = until.replace(tzinfo=timezone.utc)
    return until > _now()


def account(db, uid: str) -> dict:
    """The user's billing snapshot (defaults when no doc/fields exist yet)."""
    doc = db.users.find_one({"_id": uid}) or {}
    acct = {
        "credit_cents": int(doc.get("credit_cents", 0) or 0),
        "plan": doc.get("plan", "free"),
        "plan_until": doc.get("plan_until"),
        "stripe_customer_id": doc.get("stripe_customer_id"),
    }
    acct["is_pro"] = is_pro(acct)
    return acct


def ensure_starter_grant(db, uid: str) -> None:
    """Grant the one-time free starter credit the first time we see a user."""
    if config.FREE_GRANT_CENTS <= 0:
        return
    # Make sure the user doc exists, then grant once (no upsert on the
    # conditional update, so a repeat call can't hit a duplicate-key insert).
    db.users.update_one({"_id": uid}, {"$setOnInsert": {"credit_cents": 0}}, upsert=True)
    res = db.users.update_one(
        {"_id": uid, "starter_granted": {"$ne": True}},
        {"$set": {"starter_granted": True}, "$inc": {"credit_cents": config.FREE_GRANT_CENTS}},
    )
    if getattr(res, "modified_count", 0):
        _ledger(db, uid, "grant", config.FREE_GRANT_CENTS, "starter")


def grant_credits(db, uid: str, cents: int, reason: str, ref: str = "") -> int:
    """Add credit to a user (purchase/grant). Returns the new balance."""
    db.users.update_one({"_id": uid}, {"$inc": {"credit_cents": int(cents)}}, upsert=True)
    _ledger(db, uid, "grant", int(cents), reason, ref)
    return account(db, uid)["credit_cents"]


def charge_credits(db, uid: str, cents: int, reason: str, ref: str = "") -> int:
    """Deduct AI usage. Floors at zero (a single call can't push below 0 by more
    than its own cost, since we require a positive balance to start). Returns the
    new balance."""
    cents = int(cents)
    if cents <= 0:
        return account(db, uid)["credit_cents"]
    db.users.update_one({"_id": uid}, {"$inc": {"credit_cents": -cents}})
    bal = account(db, uid)["credit_cents"]
    if bal < 0:
        db.users.update_one({"_id": uid}, {"$set": {"credit_cents": 0}})
        bal = 0
    _ledger(db, uid, "charge", cents, reason, ref)
    return bal


def set_plan(db, uid: str, plan: str, until=None, customer_id: str | None = None) -> None:
    fields = {"plan": plan, "plan_until": until}
    if customer_id:
        fields["stripe_customer_id"] = customer_id
    db.users.update_one({"_id": uid}, {"$set": fields}, upsert=True)


def set_customer(db, uid: str, customer_id: str) -> None:
    db.users.update_one({"_id": uid}, {"$set": {"stripe_customer_id": customer_id}}, upsert=True)


# ---- AI cost -------------------------------------------------------------

def ai_cost_cents(model: str, input_tokens: int, output_tokens: int) -> int:
    """Credit charge for one model call: provider token cost x markup, in cents,
    rounded up, with a 1-cent floor so every call costs something."""
    price = config.TOKEN_PRICES.get(model, config.TOKEN_PRICE_FALLBACK)
    usd = (input_tokens * price["in"] + output_tokens * price["out"]) / 1_000_000.0
    cents = usd * 100.0 * config.AI_MARKUP
    return max(1, math.ceil(cents))


# ---- Plan caps -----------------------------------------------------------

def owned_count(db, uid: str, collection: str) -> int:
    """Count items the user actually owns (shared samples don't count)."""
    return db[collection].count_documents({"owner_id": uid})


def cap_for(kind: str) -> int:
    return {
        "datasets": config.FREE_MAX_DATASETS,
        "models": config.FREE_MAX_MODELS,
        "rbds": config.FREE_MAX_RBDS,
    }[kind]


def would_exceed_cap(db, uid: str, kind: str) -> bool:
    """True if creating one more `kind` (datasets|models|rbds) is not allowed for
    this user. Always False when billing is off or the user is Pro."""
    if not config.BILLING_ENABLED:
        return False
    if account(db, uid)["is_pro"]:
        return False
    return owned_count(db, uid, kind) >= cap_for(kind)


def usage_summary(db, uid: str) -> dict:
    acct = account(db, uid)
    return {
        "credit_cents": acct["credit_cents"],
        "plan": "pro" if acct["is_pro"] else "free",
        "billing_enabled": config.BILLING_ENABLED,
        "caps": {
            "datasets": config.FREE_MAX_DATASETS,
            "models": config.FREE_MAX_MODELS,
            "rbds": config.FREE_MAX_RBDS,
        },
        "usage": {
            "datasets": owned_count(db, uid, "datasets"),
            "models": owned_count(db, uid, "models"),
            "rbds": owned_count(db, uid, "rbds"),
        },
        "packs": config.CREDIT_PACKS,
    }
