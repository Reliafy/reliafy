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
# Shape limits for a CSV read into a DataFrame (uploads and stored datasets).
# Life data is long and narrow; these sit far above any real dataset while
# keeping one parse's memory bounded.
MAX_CSV_ROWS = int(os.environ.get("MAX_CSV_ROWS", "500000"))
MAX_CSV_COLS = int(os.environ.get("MAX_CSV_COLS", "500"))
# Default ceiling on a request body. Routes that take larger files (Excel
# workbooks, diagram imports, upload links) have their own higher caps and
# CSV routes a lower one; see backend/http_limits.py.
MAX_REQUEST_BYTES = int(os.environ.get("MAX_REQUEST_BYTES", str(10 * 1024 * 1024)))

# Outbound transactional email (team invites, share notifications). Optional:
# unset -> sends are logged no-ops. Works with any SMTP provider (Gmail app
# password, Resend, Postmark, SES).
# Operator push notifications (Pushover). Unset -> logged no-op. Preferred over
# email for operator alerts: it reaches a phone in seconds. User-facing mail
# (invites, share notifications) still goes over SMTP below.
PUSHOVER_TOKEN = os.environ.get("PUSHOVER_TOKEN")
PUSHOVER_USER = os.environ.get("PUSHOVER_USER")
# Push an operator alert when the server hits an unexpected error. On by
# default wherever push is configured; set false to keep a dev machine quiet.
PUSH_ERROR_ALERTS = (os.environ.get("PUSH_ERROR_ALERTS", "true").strip().lower()
                     not in ("0", "false", "no", "off"))

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
# Cloud Run sets K_SERVICE in every container it runs. Single-user mode there
# would serve one shared account to the whole internet, so refuse to start.
if AUTH_DISABLED and os.environ.get("K_SERVICE"):
    raise RuntimeError(
        "AUTH_DISABLED is set on a Cloud Run service (K_SERVICE is present). "
        "Single-user mode is for local and self-hosted installs only; unset "
        "AUTH_DISABLED for this deployment."
    )

# ---- Client address ----------------------------------------------------------
# Rate limits and the visitor hash key on the client IP taken from
# X-Forwarded-For (see backend/request_ip.py). Set TRUST_X_FORWARDED_FOR=false
# when the app is reachable without a proxy in front, so the peer address is
# used instead. TRUSTED_PROXY_CIDRS lists further proxy ranges (comma-separated)
# whose entries are skipped when reading the header from the right.
TRUST_X_FORWARDED_FOR = _truthy(os.environ.get("TRUST_X_FORWARDED_FOR", "true"))
TRUSTED_PROXY_CIDRS = [
    c.strip() for c in os.environ.get("TRUSTED_PROXY_CIDRS", "").split(",") if c.strip()
]
# Treat Google's own front-end addresses (goog.json minus Google Cloud
# customer ranges; snapshot in backend/google_ip_ranges.json) as proxy
# hops: requests through Firebase Hosting reach Cloud Run from them.
TRUST_GOOGLE_FRONTENDS = _truthy(os.environ.get("TRUST_GOOGLE_FRONTENDS", "true"))

# ---- Response security headers ------------------------------------------------
# Extra sources for the Content-Security-Policy connect-src (space-separated):
# the cross-origin SSE stream host (VITE_STREAM_ORIGIN) in production.
CSP_CONNECT_EXTRA = os.environ.get("CSP_CONNECT_EXTRA", "https://*.run.app").split()
# Extra frame-src sources: the Firebase auth domain's sign-in iframe.
CSP_FRAME_EXTRA = os.environ.get(
    "CSP_FRAME_EXTRA", "https://reliafy-app.firebaseapp.com https://*.firebaseapp.com"
).split()

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

# Product-usage logging (backend/services/usage.py): which features and MCP
# tools signed-in accounts use, with outcomes. Account-linked events expire
# after 90 days; only identifier-free daily totals are kept longer. On by
# default (a self-hosted install logs into its own database); set
# USAGE_LOGGING=false to record nothing.
USAGE_LOGGING = _truthy(os.environ.get("USAGE_LOGGING", "true"))

# Free-tier caps (owned items, excluding shared samples). Pro lifts them.
FREE_MAX_DATASETS = _int("FREE_MAX_DATASETS", 3)
FREE_MAX_MODELS = _int("FREE_MAX_MODELS", 3)
FREE_MAX_RBDS = _int("FREE_MAX_RBDS", 1)
# Degradation/RUL is the flagship feature: free gets a taste, Pro gets fleets.
FREE_MAX_DEGRADATION_MODELS = _int("FREE_MAX_DEGRADATION_MODELS", 1)
FREE_MAX_TRACKED_ITEMS = _int("FREE_MAX_TRACKED_ITEMS", 3)
FREE_MAX_RCM_STUDIES = _int("FREE_MAX_RCM_STUDIES", 1)
FREE_MAX_FLEETS = _int("FREE_MAX_FLEETS", 1)
# Outage logs (an RBD's observed up/down history, issue #159).
FREE_MAX_OUTAGE_LOGS = _int("FREE_MAX_OUTAGE_LOGS", 1)

# Retired Agent plan (US$2/month, MCP only; sold briefly in October 2026, no
# longer offered — MCP is part of Pro). Existing subscribers keep these caps,
# and the daily MCP quota below, until their subscription ends.
AGENT_MAX_DATASETS = _int("AGENT_MAX_DATASETS", 50)
AGENT_MAX_MODELS = _int("AGENT_MAX_MODELS", 50)
AGENT_MAX_RBDS = _int("AGENT_MAX_RBDS", 25)
AGENT_MAX_DEGRADATION_MODELS = _int("AGENT_MAX_DEGRADATION_MODELS", 10)
AGENT_MAX_TRACKED_ITEMS = _int("AGENT_MAX_TRACKED_ITEMS", 50)
AGENT_MAX_RCM_STUDIES = _int("AGENT_MAX_RCM_STUDIES", 10)
AGENT_MAX_FLEETS = _int("AGENT_MAX_FLEETS", 5)
AGENT_MAX_OUTAGE_LOGS = _int("AGENT_MAX_OUTAGE_LOGS", 10)
# Availability (Monte-Carlo) simulation is not part of the Agent plan: it stays
# Pro / purchased credits (billing.premium_compute_allowed) on every surface.

# MCP tool calls (tools/list and initialize don't count): a small allowance
# per UTC calendar month so Free users can try Reliafy from their AI agent,
# and the grandfathered Agent subscribers' quota per UTC day. Pro has no
# quota, only the per-user rate limit every request gets.
MCP_FREE_MONTHLY_CALLS = _int("MCP_FREE_MONTHLY_CALLS", 20)
MCP_AGENT_DAILY_CALLS = _int("MCP_AGENT_DAILY_CALLS", 2000)

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
# Where MCP upload links point. reliafy.com sits behind Firebase Hosting, whose
# proxy to Cloud Run may cap request size and time; set this to the Cloud Run
# service URL so a 30 MB PUT goes straight to the app. Defaults to PUBLIC_BASE_URL.
UPLOAD_BASE_URL = (os.environ.get("UPLOAD_BASE_URL") or "").strip().rstrip("/") or None

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
# Recurring Price id of the retired Agent plan (US$2/month, MCP only). It is
# no longer sold; the id (or, unset, its Stripe lookup key — see
# services/stripe_prices.py) only lets webhooks recognise an existing Agent
# subscription's price.
STRIPE_AGENT_PRICE_ID = os.environ.get("STRIPE_AGENT_PRICE_ID") or None

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

# Reasoning effort for the OpenAI assistant on the Responses API
# (/v1/responses). gpt-5.x are reasoning models; 'medium' balances quality
# against latency/cost, and Responses preserves the reasoning across tool
# round-trips within a turn (unlike chat/completions). Values: minimal|low|
# medium|high. Blank it ("") to omit reasoning entirely (non-reasoning models).
OPENAI_REASONING_EFFORT = os.environ.get("OPENAI_REASONING_EFFORT", "medium").strip()

# Whether the OpenAI Responses API retains each response server-side (``store``).
# Off by default: the assistant is stateless and we keep no transcripts, which is
# what a self-hosted instance should do unless its operator decides otherwise.
# Turning it on lets the operator read conversations back in the OpenAI dashboard
# — useful for checking the assistant's prompt and answers against what users
# actually ask, but it means conversations (including anything a user pastes in)
# are retained by the provider and readable by whoever holds that account. Say so
# in your privacy policy before enabling it.
AI_STORE = (os.environ.get("AI_STORE", "false").strip().lower()
            in ("1", "true", "yes", "on"))

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

# ---- AI request limits and credit holds -------------------------------------
# Every metered AI call first reserves (holds) its maximum cost from the
# user's balance, then settles to the actual cost and returns the rest.
# Request size limits for /api/assistant/step|stream: the whole JSON body, and
# the number of items in the message history.
AI_MAX_REQUEST_BYTES = _int("AI_MAX_REQUEST_BYTES", 1024 * 1024)
AI_MAX_MESSAGES = _int("AI_MAX_MESSAGES", 400)
# Output-token ceiling per assistant step: the Anthropic request's
# ``max_tokens`` and the OpenAI request's ``max_output_tokens`` (reasoning
# tokens count towards it). The hold covers this many output tokens.
AI_MAX_OUTPUT_TOKENS = _int(
    "AI_MAX_OUTPUT_TOKENS", 1500 if AI_PROVIDER == "anthropic" else 8000)
# AI requests one user may have running at once (assistant steps and
# Reliability Agent turns together).
AI_MAX_CONCURRENT = max(1, _int("AI_MAX_CONCURRENT", 2))
# A Reliability Agent turn holds up to this many credits (or the whole balance,
# if smaller) and is stopped once its metered cost reaches the hold. A turn
# needs at least the minimum to start.
RELIABILITY_AGENT_TURN_MAX_CENTS = _int("RELIABILITY_AGENT_TURN_MAX_CENTS", 500)
RELIABILITY_AGENT_TURN_MIN_CENTS = max(1, _int("RELIABILITY_AGENT_TURN_MIN_CENTS", 5))
# Firebase/GCP project whose ID tokens we accept. Cloud Run usually injects
# GOOGLE_CLOUD_PROJECT; FIREBASE_PROJECT_ID overrides it if the Firebase project
# differs from the GCP project.
FIREBASE_PROJECT_ID = (
    os.environ.get("FIREBASE_PROJECT_ID")
    or os.environ.get("GOOGLE_CLOUD_PROJECT")
    or None
)


def _float(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default


# ---- Compute service and its queue (#146) ----------------------------------
# Heavy analyses (availability simulations) run on a second Cloud Run service,
# ``reliafy-compute`` (same image, ``uvicorn backend.compute_app:app``), behind
# a Cloud Tasks queue. The web app records a job (``rbd_jobs``), pushes a task
# to the queue, and the compute service posts the result back to the web app's
# callback. With COMPUTE_QUEUE unset (self-hosted, local dev, tests) everything
# runs in-process, synchronously, exactly as before. See ops/compute-service.md.
#
# The compute service's base URL (the task target and the OIDC audience).
COMPUTE_URL = (os.environ.get("COMPUTE_URL") or "").strip().rstrip("/") or None
# The Cloud Tasks queue: projects/<project>/locations/<region>/queues/<name>.
COMPUTE_QUEUE = (os.environ.get("COMPUTE_QUEUE") or "").strip() or None
# Where the compute service posts results: the web service's
# /internal/compute/callback, by its run.app URL. Also the audience of the
# compute service's ID token, which the web verifies.
COMPUTE_CALLBACK_URL = (os.environ.get("COMPUTE_CALLBACK_URL") or "").strip() or None
# The service account Cloud Tasks signs the task's OIDC token as (the web
# service's own account; it needs run.invoker on reliafy-compute).
COMPUTE_INVOKER_SA = (os.environ.get("COMPUTE_INVOKER_SA") or "").strip() or None
# The compute service's own service account: the only identity whose callback
# the web accepts.
COMPUTE_SA = (os.environ.get("COMPUTE_SA") or "").strip() or None
# Compute side: simulations run in this many worker processes (each with its
# own random-number state, so concurrent jobs stay reproducible). 0 runs them
# in the request thread, one at a time.
COMPUTE_WORKERS = _int("COMPUTE_WORKERS", 0)
# How long Cloud Tasks waits for /compute/run (keep under the compute
# service's --timeout).
COMPUTE_DISPATCH_DEADLINE_S = _int("COMPUTE_DISPATCH_DEADLINE_S", 290)
# A job still queued or running after this long has been dropped by the queue
# (its retries are spent): it is reported failed.
RBD_JOB_STALE_S = _int("RBD_JOB_STALE_S", 40 * 60)
# Finished jobs (and their results) are kept this long, then the TTL index
# drops them.
RBD_JOB_TTL_DAYS = _int("RBD_JOB_TTL_DAYS", 7)
# MCP analyze_rbd waits this long for a queued simulation before answering
# with the job id (the agent then calls get_job).
MCP_JOB_WAIT_S = _float("MCP_JOB_WAIT_S", 20.0)

# ---- Free quick availability simulations (#147) ----------------------------
# Users without premium compute (billing.premium_compute_allowed) may run a
# quick availability simulation in the app: a timed pilot block of 50
# replications, then one run of the whole blocks that fit FREE_SIM_SECONDS
# (never more than FREE_SIM_MAX_REPLICATIONS; rbd_analysis._quick_simulation),
# FREE_SIMS_PER_DAY per user per UTC day.
FREE_SIM_SECONDS = _float("FREE_SIM_SECONDS", 3.0)
FREE_SIMS_PER_DAY = _int("FREE_SIMS_PER_DAY", 50)
FREE_SIM_MAX_REPLICATIONS = _int("FREE_SIM_MAX_REPLICATIONS", 2000)
# Quick simulations on the Free / Agent MCP plans. Off: those plans get no
# simulations over MCP (Derryn, 29 Sep / 3 Oct); switch on to extend them.
MCP_FREE_QUICK_SIMS = _truthy(os.environ.get("MCP_FREE_QUICK_SIMS", "false"))
