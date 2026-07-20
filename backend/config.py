"""Runtime configuration.

Persistence is MongoDB. In production point ``MONGODB_URI`` at a MongoDB Atlas
cluster; locally, if no URI is set or the cluster can't be reached, the app
falls back to an in-memory MongoDB simulator (see :mod:`backend.db`) so it runs
with no external dependencies. Everything is driven by environment variables.
"""

from __future__ import annotations

import os


MONGODB_URI = os.environ.get("MONGODB_URI")
MONGODB_DB = os.environ.get("MONGODB_DB", "reliafy")
# Short server-selection timeout so the simulator fallback kicks in quickly
# when Atlas is unreachable, rather than hanging on startup.
MONGODB_TIMEOUT_MS = int(os.environ.get("MONGODB_TIMEOUT_MS", "3000"))

# Upload ceiling for CSV datasets. Raw bytes are stored inside the Mongo
# document, whose hard limit is 16MB — stay well under it.
MAX_UPLOAD_BYTES = int(os.environ.get("MAX_UPLOAD_BYTES", str(5 * 1024 * 1024)))

# Outbound transactional email (team invites, share notifications). Optional:
# unset -> sends are logged no-ops. Works with any SMTP provider (Gmail app
# password, Resend, Postmark, SES).
SMTP_HOST = os.environ.get("SMTP_HOST")
SMTP_PORT = int(os.environ.get("SMTP_PORT", "587"))
SMTP_USER = os.environ.get("SMTP_USER")
SMTP_PASS = os.environ.get("SMTP_PASS")
EMAIL_FROM = os.environ.get("EMAIL_FROM")


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

# Operator/admin accounts: comma-separated emails with full access regardless
# of payment — plan caps don't apply and AI usage isn't credit-checked/charged.
ADMIN_EMAILS = {
    e.strip().lower()
    for e in os.environ.get("ADMIN_EMAILS", "").split(",")
    if e.strip()
}

# Salt for the daily visitor hash in first-party analytics. Any stable value
# works; setting a private one in prod stops anyone recomputing hashes from
# guessed (day, ip, ua) tuples.
METRICS_SALT = os.environ.get("METRICS_SALT", "reliafy-metrics")

# Free-tier caps (owned items, excluding shared samples). Pro lifts them.
FREE_MAX_DATASETS = _int("FREE_MAX_DATASETS", 3)
FREE_MAX_MODELS = _int("FREE_MAX_MODELS", 3)
FREE_MAX_RBDS = _int("FREE_MAX_RBDS", 1)
# Degradation/RUL is the flagship feature: free gets a taste, Pro gets fleets.
FREE_MAX_DEGRADATION_MODELS = _int("FREE_MAX_DEGRADATION_MODELS", 1)
FREE_MAX_TRACKED_ITEMS = _int("FREE_MAX_TRACKED_ITEMS", 3)
FREE_MAX_RCM_STUDIES = _int("FREE_MAX_RCM_STUDIES", 1)
FREE_MAX_FLEETS = _int("FREE_MAX_FLEETS", 1)

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

# AI credit included with each month of the Pro subscription (granted on every
# paid subscription invoice, idempotently per invoice). Internally stored in
# cents; users only ever see "credits" (1 credit == 1 cent, never shown as $).
PRO_MONTHLY_CREDIT_CENTS = _int("PRO_MONTHLY_CREDIT_CENTS", 1000)

# The site's public origin (e.g. https://reliafy.com). Used for Stripe
# redirect/return URLs so they don't depend on the Host header seen behind a
# proxy (Firebase Hosting forwards to Cloud Run with the service host). Unset =
# fall back to the request's own base URL.
PUBLIC_BASE_URL = (os.environ.get("PUBLIC_BASE_URL") or "").strip().rstrip("/") or None

# ---- Stripe -----------------------------------------------------------------
# The double-underscore names are kept for continuity with older deploy config;
# the single-underscore forms work too.
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
# The metered assistant runs a cost-efficient model — it handles transactions
# and app operation (heavy model-building goes to the Reliability Agent on Opus).
_DEFAULT_AI_MODEL = {"anthropic": "claude-sonnet-4-6", "openai": "gpt-5.6-luna"}
AI_MODEL = os.environ.get("AI_MODEL") or _DEFAULT_AI_MODEL.get(AI_PROVIDER, "")

# Markup applied to the provider's token cost when charging credits.
try:
    AI_MARKUP = float(os.environ.get("AI_MARKUP", "1.30"))
except ValueError:
    AI_MARKUP = 1.30

# Approximate list prices, USD per 1M tokens (input, output). Used to convert
# token usage into a credit charge; the markup absorbs drift. Unknown models
# fall back to a deliberately not-too-cheap default so we never undercharge.
# ``cached_in`` is the provider's discounted rate for cached/repeated prompt
# tokens (OpenAI prompt caching / Anthropic cache reads). Models without a
# cached_in entry bill cached tokens at the full input rate (never undercharge).
TOKEN_PRICES = {
    "gpt-5.6-luna": {"in": 1.0, "cached_in": 0.1, "out": 6.0},  # metered assistant
    "gpt-5.5": {"in": 5.0, "cached_in": 0.5, "out": 30.0},
    "claude-sonnet-4-6": {"in": 3.0, "cached_in": 0.3, "out": 15.0},
    "claude-haiku-4-5-20251001": {"in": 0.8, "cached_in": 0.08, "out": 4.0},
    "claude-opus-4-8": {"in": 15.0, "cached_in": 1.5, "out": 75.0},
    "gpt-4o": {"in": 2.5, "cached_in": 1.25, "out": 10.0},
    "gpt-4o-mini": {"in": 0.15, "cached_in": 0.075, "out": 0.6},
}
TOKEN_PRICE_FALLBACK = {"in": 5.0, "out": 30.0}

# ---- Reliability Agent (Anthropic Managed Agents) --------------------------
# A separate, self-contained agent on Anthropic's Managed Agents runtime: Claude
# runs in a managed cloud sandbox we provision with surpyval + the scientific
# stack, so it can fit real models on uploaded data and stream its work back.
# Kept apart from the metered assistant (its own module + metering reason) so it
# can be proven out and the old assistant retired cleanly. Runs on the shared
# ANTHROPIC_API_KEY.
# Feature flag: show the Reliability Agent surface at all. Off by default so the
# in-progress POC stays hidden in production until it's ready (and a funded
# Anthropic account is in place); flip on per environment.
RELIABILITY_AGENT_ENABLED = (os.environ.get("RELIABILITY_AGENT_ENABLED") or "").strip().lower() in ("1", "true", "yes", "on")
RELIABILITY_AGENT_MODEL = os.environ.get("RELIABILITY_AGENT_MODEL") or "claude-opus-4-8"
# Managed Agents beta header (the SDK usually sets this; kept overridable).
MANAGED_AGENTS_BETA = os.environ.get("MANAGED_AGENTS_BETA") or "managed-agents-2026-04-01"
# Pre-created Environment / Agent ids. If unset, they're created on first use
# and cached in-process (fine for a single instance / POC).
RELIABILITY_AGENT_ENV_ID = os.environ.get("RELIABILITY_AGENT_ENV_ID") or None
RELIABILITY_AGENT_AGENT_ID = os.environ.get("RELIABILITY_AGENT_AGENT_ID") or None
# Packages pre-installed into the sandbox (space-separated env override).
# Defaults match the app's stack — surpyval from the same git pin as
# requirements.txt so the agent's models match production.
RELIABILITY_AGENT_PIP = (os.environ.get("RELIABILITY_AGENT_PIP") or "").split() or [
    "surpyval", "repyability",
    "numpy", "scipy", "pandas", "matplotlib",
]
# Managed Agents session runtime price (USD per session-hour), for metering.
try:
    MANAGED_AGENT_USD_PER_HOUR = float(os.environ.get("MANAGED_AGENT_USD_PER_HOUR", "0.08"))
except ValueError:
    MANAGED_AGENT_USD_PER_HOUR = 0.08
# Firebase/GCP project whose ID tokens we accept. Cloud Run usually injects
# GOOGLE_CLOUD_PROJECT; FIREBASE_PROJECT_ID overrides it if the Firebase project
# differs from the GCP project.
FIREBASE_PROJECT_ID = (
    os.environ.get("FIREBASE_PROJECT_ID")
    or os.environ.get("GOOGLE_CLOUD_PROJECT")
    or None
)
