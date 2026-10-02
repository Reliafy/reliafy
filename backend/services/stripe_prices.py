"""The Stripe Price of the retired Agent plan, for recognising it in webhooks.

The Agent plan (US$2/month, MCP only) is no longer sold: MCP is part of Pro.
Its Price was configured (``STRIPE_AGENT_PRICE_ID``) or, when unset, created
by Reliafy under the lookup key ``AGENT_LOOKUP_KEY``. Nothing creates it any
more; this module only finds it again, so that a subscription event carrying
it (e.g. an existing subscriber switched back to it in Stripe's portal) is
still recognised as the Agent plan.
"""

from __future__ import annotations

from backend import config

AGENT_LOOKUP_KEY = "reliafy_agent_monthly_usd"

_cache: dict[str, str] = {}


def agent_price_id(stripe) -> str | None:
    """The Agent plan's Price id: configured, cached, or found by its lookup
    key. None without Stripe, or when it was never created."""
    if config.STRIPE_AGENT_PRICE_ID:
        return config.STRIPE_AGENT_PRICE_ID
    if stripe is None:
        return None
    if "agent" not in _cache:
        # Not filtered on ``active``: the Price may be archived in Stripe now
        # that the plan isn't sold, while existing subscriptions still use it.
        found = stripe.Price.list(lookup_keys=[AGENT_LOOKUP_KEY], limit=1)
        data = found["data"] if found else []
        if not data:
            return None
        _cache["agent"] = data[0]["id"]
    return _cache["agent"]


def reset_cache() -> None:
    """Forget the resolved id (tests, or after the Price is archived)."""
    _cache.clear()
