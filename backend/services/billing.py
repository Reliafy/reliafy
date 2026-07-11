"""Credits, plans, and AI cost accounting.

A user document carries a small ledger: ``credit_millicents`` (prepaid AI
balance in thousandths of a cent, so per-call metering never loses precision
to rounding), ``plan`` ('free'|'pro') with ``plan_until``, and
``stripe_customer_id``. Older documents carry only ``credit_cents`` and are
migrated lazily on first touch. The user-facing balance is whole credits
(1 credit == 1 cent), floored. Every grant/charge is also appended to the
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


def _ledger(db, uid: str, kind: str, millicents: int, reason: str, ref: str = "") -> None:
    db.credit_ledger.insert_one(
        {
            "uid": uid,
            "kind": kind,
            "millicents": int(millicents),
            "cents": round(millicents / 1000, 3),  # convenience for eyeballing
            "reason": reason,
            "ref": ref,
            "ts": _now(),
        }
    )


def _ensure_millicents(db, uid: str) -> None:
    """Lazily migrate a user doc to the millicent balance field.

    Older docs hold only ``credit_cents``; $inc on a missing field would start
    from 0 and silently drop that balance, so convert it exactly once first.
    The ``$exists: False`` filter makes the migration race-safe (one writer
    wins; the other's set is a no-op).
    """
    doc = db.users.find_one({"_id": uid})
    if doc is None:
        db.users.update_one({"_id": uid}, {"$setOnInsert": {"credit_millicents": 0}}, upsert=True)
    elif "credit_millicents" not in doc:
        db.users.update_one(
            {"_id": uid, "credit_millicents": {"$exists": False}},
            {"$set": {"credit_millicents": int(doc.get("credit_cents", 0) or 0) * 1000}},
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
    """The user's billing snapshot (defaults when no doc/fields exist yet).

    ``credit_cents`` (the user-visible credit count) is derived from the
    millicent balance, floored — sub-cent remainders stay in the ledger.
    """
    doc = db.users.find_one({"_id": uid}) or {}
    mc = doc.get("credit_millicents")
    if mc is None:
        mc = int(doc.get("credit_cents", 0) or 0) * 1000
    mc = int(mc)
    acct = {
        "credit_millicents": mc,
        "credit_cents": mc // 1000,
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
    _ensure_millicents(db, uid)
    res = db.users.update_one(
        {"_id": uid, "starter_granted": {"$ne": True}},
        {"$set": {"starter_granted": True}, "$inc": {"credit_millicents": config.FREE_GRANT_CENTS * 1000}},
    )
    if getattr(res, "modified_count", 0):
        _ledger(db, uid, "grant", config.FREE_GRANT_CENTS * 1000, "starter")


def grant_credits(db, uid: str, cents: int, reason: str, ref: str = "") -> int:
    """Add credit to a user (purchase/grant, always whole cents). Returns the
    new balance in cents."""
    _ensure_millicents(db, uid)
    db.users.update_one({"_id": uid}, {"$inc": {"credit_millicents": int(cents) * 1000}}, upsert=True)
    _ledger(db, uid, "grant", int(cents) * 1000, reason, ref)
    return account(db, uid)["credit_cents"]


def charge_millicents(db, uid: str, millicents: int, reason: str, ref: str = "") -> int:
    """Deduct metered AI usage at millicent precision. Floors at zero (a single
    call can't push below 0 by more than its own cost, since a positive balance
    is required to start). Returns the new balance in cents (floored)."""
    millicents = int(millicents)
    if millicents <= 0:
        return account(db, uid)["credit_cents"]
    _ensure_millicents(db, uid)
    db.users.update_one({"_id": uid}, {"$inc": {"credit_millicents": -millicents}})
    acct = account(db, uid)
    if acct["credit_millicents"] < 0:
        db.users.update_one({"_id": uid}, {"$set": {"credit_millicents": 0}})
        acct = account(db, uid)
    _ledger(db, uid, "charge", millicents, reason, ref)
    return acct["credit_cents"]


def charge_credits(db, uid: str, cents: int, reason: str, ref: str = "") -> int:
    """Whole-cent convenience wrapper around :func:`charge_millicents`."""
    return charge_millicents(db, uid, int(cents) * 1000, reason, ref)


def grant_monthly_pro_credits(db, customer_id: str | None, invoice_id: str | None) -> bool:
    """Grant the Pro plan's included monthly AI credit for a paid subscription
    invoice. Idempotent per invoice (webhook retries / duplicate events can't
    double-grant). Returns True if a grant was made."""
    if not customer_id or not invoice_id or config.PRO_MONTHLY_CREDIT_CENTS <= 0:
        return False
    doc = db.users.find_one({"stripe_customer_id": customer_id})
    if doc is None:
        return False
    if db.credit_ledger.find_one({"ref": invoice_id, "kind": "grant"}) is not None:
        return False  # already granted for this invoice
    grant_credits(db, doc["_id"], config.PRO_MONTHLY_CREDIT_CENTS, "pro-monthly", invoice_id)
    return True


def set_plan(db, uid: str, plan: str, until=None, customer_id: str | None = None) -> None:
    fields = {"plan": plan, "plan_until": until}
    if customer_id:
        fields["stripe_customer_id"] = customer_id
    db.users.update_one({"_id": uid}, {"$set": fields}, upsert=True)


def set_customer(db, uid: str, customer_id: str) -> None:
    db.users.update_one({"_id": uid}, {"$set": {"stripe_customer_id": customer_id}}, upsert=True)


# ---- AI cost -------------------------------------------------------------

def ai_cost_millicents(
    model: str,
    input_tokens: int,
    output_tokens: int,
    cached_input_tokens: int = 0,
) -> int:
    """Metered charge for one model call, in millicents (1/1000 cent).

    Provider token cost x markup, rounded up at millicent precision — so the
    per-call rounding overhead is at most 0.001 credits instead of a whole
    credit. ``input_tokens`` are full-rate; ``cached_input_tokens`` are billed
    at the provider's cached rate (models without a ``cached_in`` price bill
    them at the full rate, so unknown models are never undercharged).
    """
    price = config.TOKEN_PRICES.get(model, config.TOKEN_PRICE_FALLBACK)
    cached_rate = price.get("cached_in", price["in"])
    usd = (
        input_tokens * price["in"]
        + cached_input_tokens * cached_rate
        + output_tokens * price["out"]
    ) / 1_000_000.0
    millicents = usd * 100_000.0 * config.AI_MARKUP
    return max(1, math.ceil(millicents))


def ai_cost_cents(model: str, input_tokens: int, output_tokens: int) -> int:
    """Whole-cent view of :func:`ai_cost_millicents` (no cached tokens)."""
    return max(1, math.ceil(ai_cost_millicents(model, input_tokens, output_tokens) / 1000))


# ---- Plan caps -----------------------------------------------------------

def owned_count(db, uid: str, collection: str) -> int:
    """Count items the user actually owns (shared samples don't count)."""
    return db[collection].count_documents({"owner_id": uid})


def cap_for(kind: str) -> int:
    return {
        "datasets": config.FREE_MAX_DATASETS,
        "models": config.FREE_MAX_MODELS,
        "rbds": config.FREE_MAX_RBDS,
        "degradation_models": config.FREE_MAX_DEGRADATION_MODELS,
        "tracked_items": config.FREE_MAX_TRACKED_ITEMS,
        "rcm_studies": config.FREE_MAX_RCM_STUDIES,
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
            "degradation_models": config.FREE_MAX_DEGRADATION_MODELS,
            "tracked_items": config.FREE_MAX_TRACKED_ITEMS,
            "rcm_studies": config.FREE_MAX_RCM_STUDIES,
        },
        "usage": {
            "datasets": owned_count(db, uid, "datasets"),
            "models": owned_count(db, uid, "models"),
            "rbds": owned_count(db, uid, "rbds"),
            "degradation_models": owned_count(db, uid, "degradation_models"),
            "tracked_items": owned_count(db, uid, "tracked_items"),
            "rcm_studies": owned_count(db, uid, "rcm_studies"),
        },
        "packs": config.CREDIT_PACKS,
    }
