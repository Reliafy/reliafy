"""The Stripe Price behind the Agent plan, provisioned on first use.

Pro's Price is configured (``STRIPE_PRO_PRICE_ID``). The Agent plan's can be
too (``STRIPE_AGENT_PRICE_ID``); when it isn't, Reliafy creates it itself the
first time it's needed — a US$2/month recurring Price on a "Reliafy Agent"
product, under the lookup key ``AGENT_LOOKUP_KEY`` — and finds it again by
that key ever after, so each Stripe account gets exactly one. Two instances
racing to create it can't make a second: Stripe refuses a duplicate active
lookup key, and the loser's lookup then finds the winner's.
"""

from __future__ import annotations

import logging

from backend import config

logger = logging.getLogger(__name__)

AGENT_LOOKUP_KEY = "reliafy_agent_monthly_usd"
AGENT_UNIT_AMOUNT = 200  # US cents per month
AGENT_PRODUCT_NAME = "Reliafy Agent"

_cache: dict[str, str] = {}


def agent_price_id(stripe, *, create: bool = True) -> str | None:
    """The Agent plan's Price id: configured, cached, found by lookup key, or
    (``create``) created now. None without Stripe, or when it doesn't exist
    and ``create`` is False."""
    if config.STRIPE_AGENT_PRICE_ID:
        return config.STRIPE_AGENT_PRICE_ID
    if stripe is None:
        return None
    if "agent" not in _cache:
        price = _lookup(stripe) or (_create(stripe) if create else None)
        if price is None:
            return None
        _cache["agent"] = price
    return _cache["agent"]


def _lookup(stripe) -> str | None:
    found = stripe.Price.list(lookup_keys=[AGENT_LOOKUP_KEY], active=True, limit=1)
    data = found["data"] if found else []
    return data[0]["id"] if data else None


def _create(stripe) -> str:
    try:
        price = stripe.Price.create(
            currency="usd",
            unit_amount=AGENT_UNIT_AMOUNT,
            recurring={"interval": "month"},
            product_data={"name": AGENT_PRODUCT_NAME},
            lookup_key=AGENT_LOOKUP_KEY,
            nickname="Reliafy Agent — monthly",
        )
    except Exception:
        # Most likely a concurrent create won the lookup key: use theirs.
        existing = _lookup(stripe)
        if existing:
            return existing
        raise
    logger.info("Created the Stripe Price for the Agent plan (%s).", price["id"])
    return price["id"]


def reset_cache() -> None:
    """Forget the resolved id (tests, or after the Price is archived)."""
    _cache.clear()
