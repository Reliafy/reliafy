"""Credits, plans, and AI cost accounting.

A user document carries a small ledger: ``credit_millicents`` (prepaid AI
balance in thousandths of a cent, so per-call metering never loses precision
to rounding), ``plan`` ('free'|'agent'|'pro') with ``plan_until``,
``stripe_customer_id`` and ``stripe_subscription_id``. Older documents carry
only ``credit_cents`` and are migrated lazily on first touch. The user-facing
balance is whole credits (1 credit == 1 cent), floored. Every grant/charge is
also appended to the ``credit_ledger`` collection for an audit trail.

Plans: ``free`` (default) and ``pro``. Using Reliafy from an AI agent over MCP
is part of Pro (:func:`mcp_plan`); Free gets a small monthly allowance of
tool calls to try it. ``agent`` is a retired plan
(US$2/month, MCP only, sold briefly in October 2026): it is no longer sold,
but existing subscribers keep it — MCP access, its storage caps and its daily
MCP tool-call quota — until their subscription ends. Those tool-call counters
(and Free's monthly allowance) live in the ``mcp_usage`` collection, one
document per user per UTC day (per UTC month for Free).

Everything here is dormant unless :data:`backend.config.BILLING_ENABLED` is set:
plan caps aren't enforced and AI calls aren't charged, so the app behaves
exactly as before until billing is turned on.
"""

from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone

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

    ``user`` is the authenticated ``{uid, email, name, email_verified}`` dict,
    so this works on every request without a DB lookup. The address must be
    verified: anyone can create an email/password account with any address.
    """
    email = (user.get("email") or "").strip().lower()
    return bool(email) and email in config.ADMIN_EMAILS and email_trusted(user)


def email_trusted(user: dict) -> bool:
    """Whether this account's email address may be trusted as its identity
    (invites, shares to an address, operator access): verified, or a
    single-user install with sign-in turned off."""
    return config.AUTH_DISABLED or user.get("email_verified") is True


PLANS = ("free", "agent", "pro")


def _plan_current(account: dict, plan: str) -> bool:
    """True if ``account`` is on ``plan`` and it hasn't lapsed (``plan_until``)."""
    if account.get("plan") != plan:
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


def is_pro(account: dict) -> bool:
    return _plan_current(account, "pro")


def is_agent(account: dict) -> bool:
    return _plan_current(account, "agent")


def active_plan(account: dict) -> str:
    """The plan in force: 'pro', 'agent' or 'free' (a lapsed plan is free)."""
    if is_pro(account):
        return "pro"
    if is_agent(account):
        return "agent"
    return "free"


def has_purchased_credits(db, uid: str) -> bool:
    """True if the user has ever *bought* AI credits (a one-time pack), as
    opposed to only the free starter grant. Purchases are ledgered with
    reason ``"purchase"`` (routers/billing.py checkout webhook); the starter
    grant uses ``"starter"``. Used to entitle non-Pro payers to premium AI
    features like the Reliability Agent."""
    return db.credit_ledger.find_one({"uid": uid, "kind": "grant", "reason": "purchase"}) is not None


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
        "stripe_subscription_id": doc.get("stripe_subscription_id"),
    }
    acct["is_pro"] = is_pro(acct)
    acct["is_agent"] = is_agent(acct)
    acct["active_plan"] = active_plan(acct)
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


def _grant_key(reason: str, ref: str) -> str:
    return f"grant:{reason}:{ref}"


def grant_credits_once(db, uid: str, cents: int, reason: str, ref: str) -> bool:
    """Add credit for an external event (a Stripe checkout session, a paid
    invoice) at most once per ``(reason, ref)``. True if credit was added.

    The ledger row is written first, under an ``_id`` derived from the reason
    and the reference, and the balance is only incremented when that insert
    succeeds — so a repeated delivery of the same event (a webhook retry or a
    replay, even two arriving at once) fails on the unique ``_id`` and adds
    nothing. Rows written before these keys existed are matched by
    ``(kind, reason, ref)``.
    """
    from pymongo.errors import DuplicateKeyError

    if not ref:
        raise ValueError("an idempotent grant needs a reference")
    mc = int(cents) * 1000
    if db.credit_ledger.find_one({"kind": "grant", "reason": reason, "ref": ref}) is not None:
        return False
    _ensure_millicents(db, uid)
    try:
        db.credit_ledger.insert_one({
            "_id": _grant_key(reason, ref), "uid": uid, "kind": "grant", "millicents": mc,
            "cents": round(mc / 1000, 3), "reason": reason, "ref": ref, "ts": _now(),
        })
    except DuplicateKeyError:
        return False
    db.users.update_one({"_id": uid}, {"$inc": {"credit_millicents": mc}}, upsert=True)
    return True


def grant_credits(db, uid: str, cents: int, reason: str, ref: str = "") -> int:
    """Add credit to a user (purchase/grant, always whole cents). Returns the
    new balance in cents. With a ``ref`` the grant happens at most once per
    ``(reason, ref)`` (see :func:`grant_credits_once`)."""
    if ref:
        grant_credits_once(db, uid, cents, reason, ref)
        return account(db, uid)["credit_cents"]
    _ensure_millicents(db, uid)
    _ledger(db, uid, "grant", int(cents) * 1000, reason, ref)
    db.users.update_one({"_id": uid}, {"$inc": {"credit_millicents": int(cents) * 1000}}, upsert=True)
    return account(db, uid)["credit_cents"]


def _floor_at_zero(db, uid: str) -> None:
    db.users.update_one({"_id": uid, "credit_millicents": {"$lt": 0}}, {"$set": {"credit_millicents": 0}})


def charge_millicents(db, uid: str, millicents: int, reason: str, ref: str = "") -> int:
    """Deduct usage at millicent precision. Floors at zero. Returns the new
    balance in cents (floored). Metered AI calls don't use this directly: they
    reserve a hold first (:func:`reserve_millicents`) and settle it
    (:func:`settle_hold`)."""
    millicents = int(millicents)
    if millicents <= 0:
        return account(db, uid)["credit_cents"]
    _ensure_millicents(db, uid)
    db.users.update_one({"_id": uid}, {"$inc": {"credit_millicents": -millicents}})
    _floor_at_zero(db, uid)
    _ledger(db, uid, "charge", millicents, reason, ref)
    return account(db, uid)["credit_cents"]


# ---- Credit holds for metered AI calls ------------------------------------
#
# A metered AI call reserves its maximum cost before it starts: one
# conditional update takes the hold from the balance only while the balance
# covers it, so concurrent calls can never together spend more than the user
# has. When the call ends — normally, with an error, or after the client went
# away — the hold is settled: the actual cost is charged and the rest is
# returned. Holds live in ``credit_holds`` (one document each, settled once)
# and every step is in the ledger: ``hold``, then ``charge`` (actual cost) and
# ``release`` (the unused part returned).

def reserve_millicents(db, uid: str, hold_mc: int, reason: str) -> str | None:
    """Take ``hold_mc`` from the balance if it's covered; the hold's id, or
    None when the balance is short."""
    import uuid

    hold_mc = max(1, int(hold_mc))
    _ensure_millicents(db, uid)
    res = db.users.update_one(
        {"_id": uid, "credit_millicents": {"$gte": hold_mc}},
        {"$inc": {"credit_millicents": -hold_mc}},
    )
    if not getattr(res, "modified_count", 0):
        return None
    hold_id = uuid.uuid4().hex
    db.credit_holds.insert_one({
        "_id": hold_id, "uid": uid, "millicents": hold_mc, "reason": reason,
        "settled": False, "created_at": _now(),
    })
    _ledger(db, uid, "hold", hold_mc, reason, hold_id)
    return hold_id


def reserve_up_to(db, uid: str, max_mc: int, min_mc: int, reason: str) -> tuple[str, int] | None:
    """Hold ``max_mc``, or the whole balance when that is smaller but still at
    least ``min_mc``. ``(hold_id, held)`` or None. For calls whose spend is
    capped by the caller at whatever was held (a Reliability Agent turn)."""
    for _ in range(3):  # a concurrent change between the read and the take: retry
        bal = account(db, uid)["credit_millicents"]
        want = min(int(max_mc), bal)
        if want < max(1, int(min_mc)):
            return None
        hold_id = reserve_millicents(db, uid, want, reason)
        if hold_id:
            return hold_id, want
    return None


def settle_hold(db, hold_id: str, cost_mc: int | None) -> int:
    """Settle a hold once: charge ``cost_mc`` and return the rest of the hold
    to the balance. ``None`` (the call produced no usage — a provider error)
    returns the whole hold. A cost above the hold takes the difference from
    the balance, floored at zero. Later calls for the same hold change
    nothing. Returns the balance in cents."""
    doc = db.credit_holds.find_one_and_update(
        {"_id": hold_id, "settled": False},
        {"$set": {"settled": True, "settled_at": _now(),
                  "cost_millicents": None if cost_mc is None else int(cost_mc)}},
    )
    if doc is None:
        held = db.credit_holds.find_one({"_id": hold_id}) or {}
        return account(db, held.get("uid", ""))["credit_cents"] if held else 0
    uid, held, reason = doc["uid"], int(doc["millicents"]), doc.get("reason", "")
    cost = max(0, int(cost_mc or 0))
    back = held - cost
    if back:
        db.users.update_one({"_id": uid}, {"$inc": {"credit_millicents": back}})
        if back < 0:
            _floor_at_zero(db, uid)
    if cost:
        _ledger(db, uid, "charge", cost, reason, hold_id)
    if back > 0:
        _ledger(db, uid, "release", back, reason, hold_id)
    return account(db, uid)["credit_cents"]


# ---- Concurrent AI requests per user --------------------------------------

AI_SLOT_SECONDS = {"assistant": 5 * 60, "reliability_agent": 60 * 60}


def acquire_ai_slot(db, uid: str, kind: str = "assistant") -> tuple[str, str] | None:
    """Take one of the user's :data:`config.AI_MAX_CONCURRENT` AI request
    slots; ``(slot_id, token)`` to release it with, or None when all are in
    use. A slot whose holder never released it (a crashed instance) frees
    itself after its expiry."""
    import time
    import uuid

    from pymongo.errors import DuplicateKeyError

    token = uuid.uuid4().hex
    now = time.time()
    ttl = AI_SLOT_SECONDS.get(kind, AI_SLOT_SECONDS["assistant"])
    fields = {"uid": uid, "token": token, "kind": kind, "expires_ts": now + ttl,
              "expires_at": datetime.fromtimestamp(now + ttl, timezone.utc)}
    for i in range(config.AI_MAX_CONCURRENT):
        slot_id = f"{uid}:{i}"
        try:
            db.ai_slots.insert_one({"_id": slot_id, **fields})
            return slot_id, token
        except DuplicateKeyError:
            res = db.ai_slots.update_one({"_id": slot_id, "expires_ts": {"$lt": now}}, {"$set": fields})
            if getattr(res, "modified_count", 0):
                return slot_id, token
    return None


def release_ai_slot(db, slot: tuple[str, str] | None) -> None:
    if slot:
        db.ai_slots.delete_one({"_id": slot[0], "token": slot[1]})


def charge_credits(db, uid: str, cents: int, reason: str, ref: str = "") -> int:
    """Whole-cent convenience wrapper around :func:`charge_millicents`."""
    return charge_millicents(db, uid, int(cents) * 1000, reason, ref)


def grant_monthly_pro_credits(
    db, customer_id: str | None, invoice_id: str | None, price_ids: set | None = None,
) -> bool:
    """Grant the Pro plan's included monthly AI credit for a paid subscription
    invoice. Idempotent per invoice (webhook retries / duplicate events can't
    double-grant). Returns True if a grant was made.

    Only Pro invoices qualify — an Agent subscription's invoice grants nothing.
    ``price_ids`` are the Stripe prices on the invoice's lines: when known they
    decide (the first invoice can arrive before checkout.session.completed has
    set the plan); when the invoice doesn't carry them, the user's plan does."""
    if not customer_id or not invoice_id or config.PRO_MONTHLY_CREDIT_CENTS <= 0:
        return False
    doc = db.users.find_one({"stripe_customer_id": customer_id})
    if doc is None:
        return False
    if price_ids:
        if not config.STRIPE_PRO_PRICE_ID or config.STRIPE_PRO_PRICE_ID not in price_ids:
            return False
    elif not account(db, doc["_id"])["is_pro"]:
        return False
    if db.credit_ledger.find_one({"ref": invoice_id, "kind": "grant"}) is not None:
        return False  # already granted for this invoice
    # Ledger row first, keyed by the invoice: a concurrent duplicate fails the
    # insert instead of adding the credit twice.
    return grant_credits_once(db, doc["_id"], config.PRO_MONTHLY_CREDIT_CENTS, "pro-monthly", invoice_id)


def set_plan(
    db, uid: str, plan: str, until=None, customer_id: str | None = None,
    subscription_id: str | None = None,
) -> None:
    fields = {"plan": plan, "plan_until": until}
    if customer_id:
        fields["stripe_customer_id"] = customer_id
    if subscription_id:
        fields["stripe_subscription_id"] = subscription_id
    before = db.users.find_one({"_id": uid}, {"plan": 1, "plan_until": 1}) or {}
    db.users.update_one({"_id": uid}, {"$set": fields}, upsert=True)
    # Usage logging: a move to Pro is a conversion (and, after an MCP plan
    # wall, the one the agent-plan question turns on).
    from backend.services import usage as usage_service

    usage_service.on_plan_change(db, uid, active_plan(before), active_plan(fields))


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


CAPPED_KINDS = ("datasets", "models", "rbds", "degradation_models", "tracked_items", "rcm_studies", "fleets",
                "outage_logs")


def plan_caps(plan: str) -> dict | None:
    """Storage caps per capped kind for ``plan``; None = unlimited (Pro)."""
    if plan == "pro":
        return None
    prefix = "AGENT_MAX_" if plan == "agent" else "FREE_MAX_"
    return {kind: getattr(config, prefix + kind.upper()) for kind in CAPPED_KINDS}


def cap_for(kind: str, plan: str = "free") -> int | None:
    """The cap on owned ``kind`` items under ``plan`` (None = unlimited)."""
    caps = plan_caps(plan)
    return None if caps is None else caps[kind]


# What each capped kind is called in a limit message: (one, many).
_CAP_NOUNS = {
    "datasets": ("saved dataset", "saved datasets"),
    "models": ("saved model", "saved models"),
    "rbds": ("saved RBD", "saved RBDs"),
    "degradation_models": ("degradation model", "degradation models"),
    "tracked_items": ("tracked item", "tracked items"),
    "rcm_studies": ("RCM study", "RCM studies"),
    "fleets": ("failure forecast", "failure forecasts"),
    "outage_logs": ("outage log", "outage logs"),
}


def cap_message(db, uid: str, kind: str) -> str:
    """The web app's "limit reached" message, with the cap of the user's own
    plan (an Agent user is told the Agent limit, not the free one)."""
    plan = account(db, uid)["active_plan"]
    cap = cap_for(kind, plan)
    one, many = _CAP_NOUNS[kind]
    which = "Agent plan" if plan == "agent" else "free-plan"
    return (
        f"You've reached the {which} limit of {cap} {one if cap == 1 else many}. "
        f"Upgrade to Pro for unlimited {many.removeprefix('saved ')}."
    )


def would_exceed_cap(db, uid: str, kind: str) -> bool:
    """True if creating one more `kind` (datasets|models|rbds|…) is not allowed
    under this user's plan caps. Always False when billing is off or the user
    is Pro."""
    if not config.BILLING_ENABLED:
        return False
    cap = cap_for(kind, account(db, uid)["active_plan"])
    if cap is None:
        return False
    return owned_count(db, uid, kind) >= cap


def api_access_allowed(db, user: dict) -> bool:
    """Whether this user may use the programmatic API (tokens + ingestion).

    A Pro-only feature on the cloud. Always allowed when billing is off
    (self-hosted single-user) or for operator accounts.
    """
    if not config.BILLING_ENABLED:
        return True
    if is_admin_user(user):
        return True
    return account(db, user["uid"])["is_pro"]


def mcp_plan(db, user: dict) -> str:
    """The plan that governs this user's MCP use: 'pro' (everyone with API
    access — Pro, operators, self-hosted installs with billing off: no MCP
    limits beyond the per-user rate limit), 'agent' (a grandfathered Agent
    subscriber: MCP within that plan's quota and caps) or 'free' (a small
    monthly allowance of tool calls, without the Pro-only tools)."""
    if api_access_allowed(db, user):
        return "pro"
    return "agent" if account(db, user["uid"])["is_agent"] else "free"


def premium_compute_allowed(db, user: dict) -> bool:
    """Whether this user may run the paid, CPU-heavy features (the Reliability
    Agent, the Monte-Carlo availability simulation).

    Entitled: operator accounts, every user when billing is off (self-hosted),
    Pro subscribers, and anyone who has *bought* AI credits. A purely
    free-tier user (only the starter grant, never paid) is not.
    """
    if is_admin_user(user):
        return True
    if not config.BILLING_ENABLED:
        return True
    uid = user.get("uid")
    if not uid:
        return False
    return account(db, uid)["is_pro"] or has_purchased_credits(db, uid)


# ---- MCP tool-call quotas (Free allowance, grandfathered Agent plan) -----
#
# Free: a small allowance per UTC calendar month, to try Reliafy from an AI
# agent. Agent (retired, grandfathered): a quota per UTC day. Pro: none.

def _day(now: datetime | None = None) -> str:
    return (now or _now()).strftime("%Y-%m-%d")


def _month(now: datetime | None = None) -> str:
    return (now or _now()).strftime("%Y-%m")


def next_day_start(now: datetime | None = None) -> datetime:
    """When today's (UTC) MCP tool-call quota resets."""
    now = now or _now()
    return datetime(now.year, now.month, now.day, tzinfo=timezone.utc) + timedelta(days=1)


def next_month_start(now: datetime | None = None) -> datetime:
    """When this month's (UTC) MCP tool-call allowance resets."""
    now = now or _now()
    year, month = (now.year + 1, 1) if now.month == 12 else (now.year, now.month + 1)
    return datetime(year, month, 1, tzinfo=timezone.utc)


def mcp_daily_quota(plan: str) -> int | None:
    """MCP tool calls allowed per UTC day on ``plan``: only the retired Agent
    plan has a daily quota."""
    return config.MCP_AGENT_DAILY_CALLS if plan == "agent" else None


def mcp_monthly_quota(plan: str) -> int | None:
    """MCP tool calls allowed per UTC calendar month on ``plan``: only Free's
    allowance to try it."""
    return config.MCP_FREE_MONTHLY_CALLS if plan == "free" else None


def mcp_quota(plan: str) -> tuple[int | None, str | None]:
    """``(quota, period)`` for ``plan``: (n, 'month') on Free, (n, 'day') on
    the Agent plan, (None, None) on Pro."""
    if (q := mcp_monthly_quota(plan)) is not None:
        return q, "month"
    if (q := mcp_daily_quota(plan)) is not None:
        return q, "day"
    return None, None


def mcp_quota_resets_at(plan: str, now: datetime | None = None) -> datetime | None:
    """When ``plan``'s current quota period ends (None: no quota)."""
    _, period = mcp_quota(plan)
    if period == "month":
        return next_month_start(now)
    if period == "day":
        return next_day_start(now)
    return None


def _calls_id(uid: str, period_key: str) -> str:
    # A day key (2026-10-03) and a month key (2026-10) never collide.
    return f"calls:{uid}:{period_key}"


def _period_key(plan: str, now: datetime | None = None) -> str | None:
    _, period = mcp_quota(plan)
    if period == "month":
        return _month(now)
    if period == "day":
        return _day(now)
    return None


def mcp_calls_used(db, uid: str, plan: str) -> int:
    """MCP tool calls counted in ``plan``'s current quota period."""
    key = _period_key(plan)
    if key is None:
        return 0
    doc = db.mcp_usage.find_one({"_id": _calls_id(uid, key)})
    return int((doc or {}).get("count", 0))


def mcp_calls_today(db, uid: str) -> int:
    """Today's counted calls on the (daily) Agent quota."""
    return mcp_calls_used(db, uid, "agent")


def consume_mcp_call(db, uid: str, plan: str) -> bool:
    """Count one MCP tool call against ``plan``'s quota for the current period;
    True if the call may run. Nothing is counted on a plan without a quota, or
    once the quota is reached. Atomic: the increment only matches while
    ``count`` is under the quota, so concurrent calls can't both take the last
    slot."""
    quota, _ = mcp_quota(plan)
    if quota is None:
        return True
    period_key = _period_key(plan)
    key = _calls_id(uid, period_key)
    db.mcp_usage.update_one(
        {"_id": key},
        # Kept a day past the reset (a month's allowance: ~32 days at most),
        # then the TTL index drops it.
        {"$setOnInsert": {"uid": uid, "period": period_key, "count": 0,
                          "expires_at": mcp_quota_resets_at(plan) + timedelta(days=1)}},
        upsert=True,
    )
    res = db.mcp_usage.update_one({"_id": key, "count": {"$lt": int(quota)}}, {"$inc": {"count": 1}})
    return bool(getattr(res, "modified_count", 0))


def refund_mcp_call(db, uid: str, plan: str) -> None:
    """Give back a call :func:`consume_mcp_call` counted when the tool then
    refused it (a storage cap, a Pro-only feature): refused calls don't count."""
    key = _period_key(plan)
    if key is None:
        return
    db.mcp_usage.update_one({"_id": _calls_id(uid, key), "count": {"$gt": 0}}, {"$inc": {"count": -1}})


def mcp_usage_summary(db, uid: str, plan: str) -> dict:
    """MCP tool calls in the current period against the plan's quota, for the
    billing page: ``calls_used`` of ``quota`` per ``period`` ('month' on Free,
    'day' on the Agent plan, None on Pro), resetting at ``calls_reset_at``.
    ``calls_today`` / ``daily_quota`` describe a daily quota only."""
    quota, period = mcp_quota(plan)
    used = mcp_calls_used(db, uid, plan)
    resets = mcp_quota_resets_at(plan) or next_day_start()
    return {
        "calls_today": used if period == "day" else 0,
        "daily_quota": quota if period == "day" else None,
        "calls_used": used,
        "quota": quota,
        "period": period,
        "calls_reset_at": resets.isoformat(),
    }


def usage_summary(db, uid: str, admin: bool = False) -> dict:
    """Plan, credit, caps and usage snapshot for GET /api/billing. ``admin``
    (operator accounts) reports MCP use without quotas, as they have none.
    ``mcp`` is the MCP tool-call quota: Free's monthly allowance or a
    grandfathered Agent subscriber's daily quota (``quota`` is None for Pro)."""
    acct = account(db, uid)
    plan = acct["active_plan"]
    return {
        "credit_cents": acct["credit_cents"],
        "plan": plan,
        "billing_enabled": config.BILLING_ENABLED,
        # Free-plan caps (the Free vs Pro comparison); ``plan_caps`` are the
        # ones that apply to this user (None = unlimited; a grandfathered
        # Agent subscriber's are the Agent caps).
        "caps": plan_caps("free"),
        "plan_caps": plan_caps(plan),
        "mcp": mcp_usage_summary(db, uid, "pro" if admin or not config.BILLING_ENABLED else plan),
        # Quoted on /billing (Free vs Pro comparison) so the page never
        # hardcodes a number the operator can change with an env var.
        "free_grant_cents": config.FREE_GRANT_CENTS,
        # Free's MCP allowance per UTC month, for the Free vs Pro comparison.
        "mcp_free_monthly_calls": config.MCP_FREE_MONTHLY_CALLS,
        "pro_monthly_credit_cents": config.PRO_MONTHLY_CREDIT_CENTS,
        "usage": {kind: owned_count(db, uid, kind) for kind in CAPPED_KINDS},
        "packs": config.CREDIT_PACKS,
    }
