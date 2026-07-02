"""Billing API: plan/credit status, Stripe Checkout for credit packs and the Pro
subscription, the billing portal, and the Stripe webhook that fulfils them."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Body, Depends, Request
from fastapi.responses import JSONResponse

from backend import config
from backend.auth import get_current_user
from backend.db import get_session
from backend.services import assistant as assistant_service
from backend.services import billing as billing_service

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api")


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
    summary = billing_service.usage_summary(session, user["uid"])
    # Operator accounts keep their REAL plan (so they can still exercise the
    # purchase flows) and carry an explicit admin flag for the UI instead.
    summary["admin"] = billing_service.is_admin_user(user)
    summary["stripe_enabled"] = bool(config.STRIPE_API_KEY)
    summary["pro_available"] = bool(config.STRIPE_API_KEY and config.STRIPE_PRO_PRICE_ID)
    summary["pro_monthly_credit_cents"] = config.PRO_MONTHLY_CREDIT_CENTS
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

    base = str(request.base_url)
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


@router.post("/billing/subscribe")
def subscribe(
    request: Request,
    session=Depends(get_session),
    user: dict = Depends(get_current_user),
) -> JSONResponse:
    stripe = _stripe()
    if stripe is None or not config.STRIPE_PRO_PRICE_ID:
        return JSONResponse(status_code=503, content={"detail": "The Pro plan is not configured."})
    base = str(request.base_url)
    try:
        cs = stripe.checkout.Session.create(
            mode="subscription",
            customer=_customer(stripe, session, user),
            client_reference_id=user["uid"],
            line_items=[{"price": config.STRIPE_PRO_PRICE_ID, "quantity": 1}],
            metadata={"uid": user["uid"], "kind": "pro"},
            success_url=f"{base}billing?status=success",
            cancel_url=f"{base}billing?status=cancel",
        )
    except Exception as exc:  # noqa: BLE001
        logger.exception("Stripe subscribe failed")
        return JSONResponse(status_code=502, content={"detail": f"Stripe error: {exc}"})
    return JSONResponse(content={"url": cs.url})


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
            return_url=f"{str(request.base_url)}billing",
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
        elif meta.get("kind") == "pro":
            billing_service.set_plan(session, uid, "pro", until=None, customer_id=obj.get("customer"))

    elif etype == "invoice.paid":
        # Every paid subscription invoice (first and each renewal) grants the
        # Pro plan's included monthly AI credit — idempotent per invoice.
        billing_service.grant_monthly_pro_credits(session, obj.get("customer"), obj.get("id"))

    elif etype in ("customer.subscription.deleted",):
        _downgrade_by_customer(session, obj.get("customer"))
    elif etype == "customer.subscription.updated":
        status = obj.get("status")
        if status in ("canceled", "unpaid", "incomplete_expired"):
            _downgrade_by_customer(session, obj.get("customer"))


def _downgrade_by_customer(session, customer_id) -> None:
    if not customer_id:
        return
    doc = session.users.find_one({"stripe_customer_id": customer_id})
    if doc:
        billing_service.set_plan(session, doc["_id"], "free", until=None)
