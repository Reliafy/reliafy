"""Runtime configuration.

Persistence is MongoDB. In production point ``MONGODB_URI`` at a MongoDB Atlas
cluster; locally, if no URI is set or the cluster can't be reached, the app
falls back to an in-memory MongoDB simulator (see :mod:`backend.db`) so it runs
with no external dependencies. Everything is driven by environment variables.
"""

from __future__ import annotations

import os


def _mongo_uri() -> str | None:
    """Resolve the MongoDB connection string.

    Preference order:
    1. ``MONGODB_URI`` — a full connection string (the usual case).
    2. The legacy ``MDB_STRG`` template with ``MDB_USER`` / ``MDB_PASS`` filled
       in (kept so existing deployment env files keep working).
    """
    uri = os.environ.get("MONGODB_URI")
    if uri:
        return uri
    template = os.environ.get("MDB_STRG")
    if template:
        user = os.environ.get("MDB_USER", "")
        pw = os.environ.get("MDB_PASS", "")
        try:
            return template.format(user=user, pw=pw)
        except (KeyError, IndexError):
            return template
    return None


MONGODB_URI = _mongo_uri()
MONGODB_DB = os.environ.get("MONGODB_DB", "reliafy")
# Short server-selection timeout so the simulator fallback kicks in quickly
# when Atlas is unreachable, rather than hanging on startup.
MONGODB_TIMEOUT_MS = int(os.environ.get("MONGODB_TIMEOUT_MS", "3000"))


def _truthy(value: str | None) -> bool:
    return (value or "").strip().lower() in ("1", "true", "yes", "on")


# ---- Authentication --------------------------------------------------------
# When AUTH_DISABLED is set, the backend skips Firebase token verification and
# treats every request as one fixed user. This is "single-user mode" — the
# supported way to run a self-hosted instance (and local development) with zero
# external dependencies. Never enable it on a multi-user/cloud deployment.
AUTH_DISABLED = _truthy(os.environ.get("AUTH_DISABLED"))
DEV_USER_ID = os.environ.get("DEV_USER_ID", "dev-user")

# ---- Sample (starter) content ---------------------------------------------
# Seeded sample datasets/models are stored once under this synthetic owner and
# surfaced to every user (read-only) so a fresh account isn't empty. A user can
# "delete" a sample, which only hides it for them (recorded per-user) and never
# touches the shared copy other users still see. Set SEED_SAMPLES=false to skip
# seeding entirely.
SAMPLE_OWNER = "__samples__"
SEED_SAMPLES = _truthy(os.environ.get("SEED_SAMPLES", "true"))


# ---- Billing, plans, and AI credits ---------------------------------------
# All of this is inert until BILLING_ENABLED is set: no plan caps are enforced
# and the AI is free (no credit checks). Turn it on once Stripe + an AI key are
# configured and the billing UI is live. Money values are USD cents (ints).
def _int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default


BILLING_ENABLED = _truthy(os.environ.get("BILLING_ENABLED"))

# Free-tier caps (owned items, excluding shared samples). Pro lifts them.
FREE_MAX_DATASETS = _int("FREE_MAX_DATASETS", 3)
FREE_MAX_MODELS = _int("FREE_MAX_MODELS", 3)
FREE_MAX_RBDS = _int("FREE_MAX_RBDS", 1)

# One-time prepaid credit packs (Stripe Checkout, mode=payment). `grant_cents`
# is the credit added on success (>= price_cents builds in the bonus).
CREDIT_PACKS = [
    {"id": "p5", "label": "$5", "price_cents": 500, "grant_cents": 500},
    {"id": "p20", "label": "$20", "price_cents": 2000, "grant_cents": 2100},
    {"id": "p50", "label": "$50", "price_cents": 5000, "grant_cents": 5500},
]

# A small starter grant the first time we see a user (so the assistant is
# try-able without paying). USD cents.
FREE_GRANT_CENTS = _int("FREE_GRANT_CENTS", 25)

# ---- Stripe (names match the pre-existing env_variables.yaml entries) ------
STRIPE_API_KEY = os.environ.get("STRIPE__API_KEY") or os.environ.get("STRIPE_API_KEY")
STRIPE_WEBHOOK_SECRET = (
    os.environ.get("STRIPE__WEBHOOK_SECRET") or os.environ.get("STRIPE_WEBHOOK_SECRET")
)
# Recurring Price id for the Pro plan subscription.
STRIPE_PRO_PRICE_ID = (
    os.environ.get("STRIPE__PRICE_ID") or os.environ.get("STRIPE_PRO_PRICE_ID")
)

# ---- Operator AI provider (server-side metered assistant) ------------------
# The assistant runs on OUR key and is billed to users as credits. Pick the
# provider/model here; the matching key must be present for the AI to work.
AI_PROVIDER = (os.environ.get("AI_PROVIDER") or "anthropic").strip().lower()
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY")
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")
_DEFAULT_AI_MODEL = {"anthropic": "claude-sonnet-4-6", "openai": "gpt-4o-mini"}
AI_MODEL = os.environ.get("AI_MODEL") or _DEFAULT_AI_MODEL.get(AI_PROVIDER, "")

# Markup applied to the provider's token cost when charging credits.
try:
    AI_MARKUP = float(os.environ.get("AI_MARKUP", "1.30"))
except ValueError:
    AI_MARKUP = 1.30

# Approximate list prices, USD per 1M tokens (input, output). Used to convert
# token usage into a credit charge; the markup absorbs drift. Unknown models
# fall back to a deliberately not-too-cheap default so we never undercharge.
TOKEN_PRICES = {
    "claude-sonnet-4-6": {"in": 3.0, "out": 15.0},
    "claude-haiku-4-5-20251001": {"in": 0.8, "out": 4.0},
    "claude-opus-4-8": {"in": 15.0, "out": 75.0},
    "gpt-4o": {"in": 2.5, "out": 10.0},
    "gpt-4o-mini": {"in": 0.15, "out": 0.6},
}
TOKEN_PRICE_FALLBACK = {"in": 3.0, "out": 15.0}
# Firebase/GCP project whose ID tokens we accept. Cloud Run usually injects
# GOOGLE_CLOUD_PROJECT; FIREBASE_PROJECT_ID overrides it if the Firebase project
# differs from the GCP project.
FIREBASE_PROJECT_ID = (
    os.environ.get("FIREBASE_PROJECT_ID")
    or os.environ.get("GOOGLE_CLOUD_PROJECT")
    or None
)
