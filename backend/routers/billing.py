"""Billing API: plan/credit status, Stripe Checkout for credit packs and the
Pro subscription, the billing portal, and the Stripe webhook that fulfils
them.

The Agent plan (US$2/month, MCP only) is retired — MCP is part of Pro — and
can't be bought any more. Existing Agent subscriptions are still honoured:
their webhook events (checkout completion, price changes, cancellation) are
handled as before, and an Agent subscriber can move up to Pro in place."""

from __future__ import annotations

import json
import logging

from fastapi import APIRouter, Body, Depends, Request
from fastapi.responses import JSONResponse

from backend import config
from backend.auth import get_current_user
from backend.db import get_session
from backend.services import assistant as assistant_service
from backend.services import billing as billing_service
from backend.services import stripe_prices

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api")


def _public_base(request: Request) -> str:
    """The site origin for Stripe redirect URLs, with a trailing slash.

    PUBLIC_BASE_URL wins (required behind the Firebase Hosting proxy, where the
    request's own Host is the Cloud Run service, not the custom domain).
    """
    if config.PUBLIC_BASE_URL:
        return config.PUBLIC_BASE_URL + "/"
    return str(request.base_url)


def _stripe():
    """Return the configured stripe module, or None if no key is set."""
    if not config.STRIPE_API_KEY:
        return None
    import stripe

    stripe.api_key = config.STRIPE_API_KEY
    return stripe


def _pack(pack_id: str):
    return next((p for p in config.CREDIT_PACKS if p["id"] == pack_id), None)


def _customer(stripe, session, user) -> str:
    """Reuse or create the user's Stripe customer id."""
    acct = billing_service.account(session, user["uid"])
    if acct.get("stripe_customer_id"):
        return acct["stripe_customer_id"]
    # Only pass an email Stripe will accept (e.g. the single-user mode's
    # "dev@local" has no domain dot) — an odd email shouldn't block checkout.
    email = user.get("email") or None
    if email and ("@" not in email or "." not in email.split("@")[-1]):
        email = None
    cust = stripe.Customer.create(
        email=email,
        metadata={"uid": user["uid"]},
    )
    billing_service.set_customer(session, user["uid"], cust.id)
    return cust.id


@router.get("/billing")
def billing_status(session=Depends(get_session), user: dict = Depends(get_current_user)) -> dict:
    admin = billing_service.is_admin_user(user)
    summary = billing_service.usage_summary(session, user["uid"], admin=admin)
    # Operator accounts keep their REAL plan (so they can still exercise the
    # purchase flows) and carry an explicit admin flag for the UI instead.
    summary["admin"] = admin
    summary["stripe_enabled"] = bool(config.STRIPE_API_KEY)
    summary["pro_available"] = bool(config.STRIPE_API_KEY and config.STRIPE_PRO_PRICE_ID)
    summary["ai"] = assistant_service.info()
    return summary


@router.post("/billing/checkout")
def checkout(
    request: Request,
    pack_id: str = Body(..., embed=True),
    session=Depends(get_session),
    user: dict = Depends(get_current_user),
) -> JSONResponse:
    stripe = _stripe()
    if stripe is None:
        return JSONResponse(status_code=503, content={"detail": "Payments are not configured."})
    pack = _pack(pack_id)
    if pack is None:
        return JSONResponse(status_code=400, content={"detail": "Unknown credit pack."})

    base = _public_base(request)
    try:
        cs = stripe.checkout.Session.create(
            mode="payment",
            customer=_customer(stripe, session, user),
            client_reference_id=user["uid"],
            line_items=[{
                "price_data": {
                    "currency": "usd",
                    "unit_amount": pack["price_cents"],
                    "product_data": {"name": f"Reliafy AI credits ({pack['label']})"},
                },
                "quantity": 1,
            }],
            metadata={"uid": user["uid"], "kind": "pack", "grant_cents": str(pack["grant_cents"])},
            success_url=f"{base}billing?status=success",
            cancel_url=f"{base}billing?status=cancel",
        )
    except Exception as exc:  # noqa: BLE001
        logger.exception("Stripe checkout failed")
        return JSONResponse(status_code=502, content={"detail": f"Stripe error: {exc}"})
    return JSONResponse(content={"url": cs.url})


# Paid plans a subscription can be on (the retired Agent plan included, so
# existing subscriptions keep working) vs the ones that can be bought.
_PLAN_NAMES = {"pro": "Pro", "agent": "Agent"}
_SOLD_PLANS = {"pro"}
AGENT_RETIRED = "The Agent plan has been retired; MCP is now part of Pro."


def _plan_for_prices(price_ids: set) -> str | None:
    """Which paid plan a set of Stripe prices is (Pro wins if both appear)."""
    if config.STRIPE_PRO_PRICE_ID and config.STRIPE_PRO_PRICE_ID in price_ids:
        return "pro"
    if not price_ids:
        return None
    try:
        agent = stripe_prices.agent_price_id(_stripe())
    except Exception:  # noqa: BLE001 - a Stripe hiccup mustn't fail the webhook
        logger.exception("Couldn't look up the Agent plan's Stripe Price")
        agent = None
    return "agent" if agent and agent in price_ids else None


def _price_ids(lines: dict | None) -> set:
    """Price ids on a Stripe list of invoice lines or subscription items.

    Tolerates the shapes Stripe API versions use: ``price`` (an object or an
    id), the newer ``pricing.price_details.price``, and the legacy ``plan``.
    """
    out = set()
    for line in (lines or {}).get("data") or []:
        for ref in (
            line.get("price"),
            ((line.get("pricing") or {}).get("price_details") or {}).get("price"),
            line.get("plan"),
        ):
            pid = ref.get("id") if isinstance(ref, dict) else ref
            if isinstance(pid, str) and pid:
                out.add(pid)
    return out


@router.post("/billing/subscribe")
def subscribe(
    request: Request,
    plan: str = Body("pro", embed=True),
    session=Depends(get_session),
    user: dict = Depends(get_current_user),
) -> JSONResponse:
    """Start a Pro subscription (``plan`` 'pro', the default).

    ``plan=agent`` answers 410: the Agent plan is retired. A grandfathered
    Agent subscriber is moved to Pro in place (the existing subscription's
    price is swapped, prorated) rather than sold a second subscription.
    """
    status, payload = start_subscription(session, user, plan, _public_base(request))
    return JSONResponse(status_code=status, content=payload)


def start_subscription(session, user: dict, plan: str, base: str, *, allow_switch: bool = True) -> tuple[int, dict]:
    """(status, payload) for subscribing ``user`` to ``plan`` (only 'pro' is
    sold): a Stripe Checkout ``url`` for someone not yet on a paid plan, or —
    with ``allow_switch`` — an in-place switch for a grandfathered Agent
    subscriber.

    Without ``allow_switch`` (the MCP ``upgrade_link`` tool: an agent must
    never move a paying subscriber by itself) a switch answers 409 with the
    billing page, where the person confirms it."""
    plan = (plan or "pro").strip().lower()
    if plan == "agent":
        return 410, {"detail": AGENT_RETIRED}
    if plan not in _SOLD_PLANS:
        return 400, {"detail": "Unknown plan."}
    stripe = _stripe()
    price = config.STRIPE_PRO_PRICE_ID
    if stripe is None or not price:
        return 503, {"detail": f"The {_PLAN_NAMES[plan]} plan is not configured."}
    acct = billing_service.account(session, user["uid"])
    if acct["active_plan"] == plan:
        return 409, {"detail": f"You're already on {_PLAN_NAMES[plan]}."}
    if acct["active_plan"] in _PLAN_NAMES:
        if not allow_switch:
            return 409, {"detail": f"Change plans on the billing page: {base}billing", "url": f"{base}billing"}
        response = _switch_plan(stripe, session, user, acct, plan, price, base)
        return response.status_code, json.loads(response.body)
    try:
        cs = stripe.checkout.Session.create(
            mode="subscription",
            customer=_customer(stripe, session, user),
            client_reference_id=user["uid"],
            line_items=[{"price": price, "quantity": 1}],
            metadata={"uid": user["uid"], "kind": plan},
            success_url=f"{base}billing?status=success",
            cancel_url=f"{base}billing?status=cancel",
        )
    except Exception as exc:  # noqa: BLE001
        logger.exception("Stripe subscribe failed")
        return 502, {"detail": f"Stripe error: {exc}"}
    return 200, {"url": cs.url}


def _switch_plan(stripe, session, user, acct, plan: str, price: str, base: str) -> JSONResponse:
    """Move a grandfathered Agent subscriber to Pro on their existing subscription."""
    sub_id = acct.get("stripe_subscription_id")
    if not sub_id:
        # Subscribed before subscription ids were recorded: let Stripe's portal
        # do the switch rather than guess which subscription to change.
        return JSONResponse(status_code=409, content={
            "detail": "Change plans from Manage subscription on the billing page."})
    try:
        sub = stripe.Subscription.retrieve(sub_id)
        item_id = sub["items"]["data"][0]["id"]
        stripe.Subscription.modify(
            sub_id,
            items=[{"id": item_id, "price": price}],
            proration_behavior="create_prorations",
            metadata={"uid": user["uid"], "kind": plan},
        )
    except Exception as exc:  # noqa: BLE001
        logger.exception("Stripe plan switch failed")
        return JSONResponse(status_code=502, content={"detail": f"Stripe error: {exc}"})
    # The customer.subscription.updated webhook confirms this; set it now so
    # the page the user returns to already shows the new plan.
    billing_service.set_plan(session, user["uid"], plan, until=None, subscription_id=sub_id)
    return JSONResponse(content={"url": f"{base}billing?status=success", "switched": True})


@router.post("/billing/portal")
def portal(
    request: Request,
    session=Depends(get_session),
    user: dict = Depends(get_current_user),
) -> JSONResponse:
    stripe = _stripe()
    if stripe is None:
        return JSONResponse(status_code=503, content={"detail": "Payments are not configured."})
    acct = billing_service.account(session, user["uid"])
    if not acct.get("stripe_customer_id"):
        return JSONResponse(status_code=400, content={"detail": "No billing account yet."})
    try:
        ps = stripe.billing_portal.Session.create(
            customer=acct["stripe_customer_id"],
            return_url=f"{_public_base(request)}billing",
        )
    except Exception as exc:  # noqa: BLE001
        return JSONResponse(status_code=502, content={"detail": f"Stripe error: {exc}"})
    return JSONResponse(content={"url": ps.url})


@router.post("/stripe/webhook")
async def stripe_webhook(request: Request, session=Depends(get_session)) -> JSONResponse:
    """Fulfil completed purchases. Public, but the payload is verified against the
    Stripe signature when a webhook secret is configured."""
    payload = await request.body()
    event = None
    if config.STRIPE_WEBHOOK_SECRET:
        import json

        import stripe

        sig = request.headers.get("stripe-signature", "")
        try:
            # construct_event is used purely to VERIFY the signature; its return
            # type varies across stripe-python versions (Event object vs dict),
            # so once verified we parse the raw payload ourselves.
            stripe.Webhook.construct_event(payload, sig, config.STRIPE_WEBHOOK_SECRET)
            event = json.loads(payload)
        except Exception as exc:  # noqa: BLE001 - bad signature / parse
            logger.warning("Stripe webhook verification failed: %s", exc)
            return JSONResponse(status_code=400, content={"detail": "Invalid signature."})
    else:
        import json

        try:
            event = json.loads(payload)
        except Exception:  # noqa: BLE001
            return JSONResponse(status_code=400, content={"detail": "Bad payload."})

    _handle_event(session, event)
    return JSONResponse(content={"received": True})


def _handle_event(session, event) -> None:
    etype = event.get("type")
    obj = (event.get("data") or {}).get("object") or {}

    if etype == "checkout.session.completed":
        meta = obj.get("metadata") or {}
        uid = meta.get("uid") or obj.get("client_reference_id")
        if not uid:
            return
        if meta.get("kind") == "pack":
            grant = int(meta.get("grant_cents") or 0)
            if grant:
                billing_service.grant_credits(session, uid, grant, "purchase", obj.get("id", ""))
        elif meta.get("kind") in _PLAN_NAMES:
            # kind=agent still lands: an Agent checkout opened before the plan
            # was retired can complete for up to 24 h, and that user paid.
            billing_service.set_plan(session, uid, meta["kind"], until=None, customer_id=obj.get("customer"),
                                     subscription_id=obj.get("subscription"))

    elif etype == "invoice.paid":
        # A paid Pro invoice (first and each renewal) grants the Pro plan's
        # included monthly AI credit — idempotent per invoice. (Grandfathered)
        # Agent invoices grant nothing.
        billing_service.grant_monthly_pro_credits(
            session, obj.get("customer"), obj.get("id"), _price_ids(obj.get("lines")))

    elif etype in ("customer.subscription.deleted",):
        _downgrade_by_customer(session, obj.get("customer"), obj.get("id"))
    elif etype == "customer.subscription.updated":
        status = obj.get("status")
        if status in ("canceled", "unpaid", "incomplete_expired"):
            _downgrade_by_customer(session, obj.get("customer"), obj.get("id"))
        elif status in ("active", "trialing"):
            # A plan switch (ours, or made in the Stripe portal) changes the
            # subscription's price: follow it.
            plan = _plan_for_prices(_price_ids(obj.get("items")))
            doc = _subscriber(session, obj.get("customer"), obj.get("id"))
            if plan and doc:
                billing_service.set_plan(session, doc["_id"], plan, until=None, subscription_id=obj.get("id"))


def _subscriber(session, customer_id, subscription_id):
    """The user a subscription event is about, or None — including when the
    user's recorded subscription is a different one (e.g. an old subscription
    ending after they moved to a new one must not touch the new plan)."""
    if not customer_id:
        return None
    doc = session.users.find_one({"stripe_customer_id": customer_id})
    if doc is None:
        return None
    current = doc.get("stripe_subscription_id")
    if current and subscription_id and current != subscription_id:
        return None
    return doc


def _downgrade_by_customer(session, customer_id, subscription_id=None) -> None:
    doc = _subscriber(session, customer_id, subscription_id)
    if doc:
        billing_service.set_plan(session, doc["_id"], "free", until=None)
        session.users.update_one({"_id": doc["_id"]}, {"$unset": {"stripe_subscription_id": ""}})
