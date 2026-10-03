"""Product-usage logging: which features and MCP tools accounts use, and how
those calls end — so we can see how Reliafy is used, and whether use from AI
agents (MCP) grows enough to deserve a plan of its own.

Privacy (the privacy policy's "usage analytics": first-party, never shared,
account-linked records kept no longer than 90 days):

* ``usage_events`` — one document per action by a signed-in account: the
  account id, the channel, a feature or tool *name*, the outcome, the plan,
  the MCP client's name, the duration. No IP, no user agent, nothing of what
  was analysed. A TTL index drops each event 90 days after it happened.
* ``usage_daily`` — identifier-free daily totals, kept indefinitely: counts
  per (day, channel, feature, outcome, plan, client), and per-day *numbers*
  of distinct accounts. ``usage_weekly`` holds the same distinct-account
  numbers per ISO week. Both are computed from ``usage_events`` by
  :func:`rollup` once a day (or week) is over, so no account id outlives the
  90 days.
* ``usage_rollups`` marks which days and weeks are rolled up.

There's no cron: :func:`rollup` runs lazily — on the operator's dashboard
request, and from :func:`record` at most every few minutes per instance (in a
background thread). It only rolls up periods not yet marked, and rewrites a
period's documents under deterministic ids, so running it twice (or on two
instances at once) gives the same result.

Channels: ``app`` (the web app's REST calls), ``mcp`` (tool calls, plus
``initialize`` / ``tools/list`` as connection events), ``api`` (``rlf_`` token
calls to ``/api/v1`` and ``/api/ingest``) and ``billing`` (server-side plan
changes: ``pro_upgrade``, ``upgrade_after_mcp_lock``).

Outcomes: ``ok``, ``error`` (the user's call failed), ``locked`` (refused for
the plan as a whole — a non-Pro API token at /mcp, a 403 in the app),
``limit`` (an allowance, quota or storage cap) and ``pro_only`` (a Pro-only
tool or feature refused on a plan without it).

Everything here is best-effort: a failure is logged and swallowed, never
raised into the request that triggered it. ``USAGE_LOGGING=false`` turns all
of it off.
"""

from __future__ import annotations

import contextvars
import logging
import re
import threading
import time
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta, timezone

from backend import config

logger = logging.getLogger(__name__)

RETENTION_DAYS = 90
CHANNELS = ("app", "mcp", "api")
OUTCOMES = ("ok", "error", "locked", "limit", "pro_only")
# MCP connection events, not tool calls: the protocol requests, and "connect"
# (a non-Pro API token refused at /mcp before any request is read).
MCP_PROTOCOL = ("initialize", "tools/list", "connect")
# The billing channel's events.
PRO_UPGRADE = "pro_upgrade"
UPGRADE_AFTER_LOCK = "upgrade_after_mcp_lock"
# Outcomes that are a plan wall, for "upgrade after hitting the wall".
WALL_OUTCOMES = ("locked", "limit", "pro_only")

# A finished day is rolled up once it has been over for this long (lets
# in-flight events for it land first).
_GRACE = timedelta(minutes=5)
# How often record() may kick off a background roll-up, per instance.
_ROLLUP_EVERY_S = 600
_next_rollup = 0.0
_rollup_lock = threading.Lock()


def enabled() -> bool:
    return bool(config.USAGE_LOGGING)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _clip(value, n: int = 64) -> str:
    return str(value or "")[:n]


def ensure_indexes(db) -> None:
    """TTL on events (the 90-day promise) and the lookups the reports use."""
    db.usage_events.create_index([("ts", 1)], expireAfterSeconds=RETENTION_DAYS * 24 * 3600)
    db.usage_events.create_index([("day", 1)])
    db.usage_events.create_index([("uid", 1), ("channel", 1), ("outcome", 1)])
    db.usage_daily.create_index([("day", 1)])
    db.usage_weekly.create_index([("week", 1)])
    db.usage_rollups.create_index([("kind", 1), ("key", 1)])


# ---------------------------------------------------------------------------
# Who, on which plan, from which client
# ---------------------------------------------------------------------------

# Plan lookups are cached per instance for a minute: one users read per
# account per minute, not one per request.
_PLAN_TTL_S = 60
_plan_cache: dict[str, tuple[float, str]] = {}


def plan_of(db, user: dict) -> str:
    """'admin' for operator accounts (so the reports can leave them out),
    else the account's plan in force: 'pro', 'agent' or 'free'."""
    from backend.services import billing

    if billing.is_admin_user(user):
        return "admin"
    uid = user.get("uid") or ""
    hit = _plan_cache.get(uid)
    now = time.monotonic()
    if hit and hit[0] > now:
        return hit[1]
    plan = billing.account(db, uid)["active_plan"]
    if len(_plan_cache) > 10_000:
        _plan_cache.clear()
    _plan_cache[uid] = (now + _PLAN_TTL_S, plan)
    return plan


def forget_plan(uid: str) -> None:
    _plan_cache.pop(uid, None)


_KNOWN_CLIENTS = (
    ("claude code", "Claude Code"),
    ("claude desktop", "Claude Desktop"),
    ("claude", "Claude"),
    ("chatgpt", "ChatGPT"),
    ("openai", "OpenAI"),
    ("cursor", "Cursor"),
    ("windsurf", "Windsurf"),
    ("visual studio code", "VS Code"),
    ("vscode", "VS Code"),
    ("vs code", "VS Code"),
    ("copilot", "GitHub Copilot"),
    ("cline", "Cline"),
    ("goose", "Goose"),
    ("zed", "Zed"),
    ("inspector", "MCP Inspector"),
    ("gemini", "Gemini"),
)


def normalise_client(name) -> str:
    """A short, safe label for an OAuth client's self-registered name:
    well-known clients by their usual name, anything else stripped to plain
    characters and clipped. Anything that looks like an address is 'other'."""
    raw = str(name or "")
    if not raw.strip():
        return "unknown"
    if "@" in raw or "://" in raw:
        return "other"
    low = re.sub(r"[-_]+", " ", raw.lower())
    for needle, label in _KNOWN_CLIENTS:
        if needle in low:
            return label
    clean = " ".join(re.sub(r"[^A-Za-z0-9 ._()+-]", " ", raw).split())[:32]
    return clean or "other"


def client_of(user: dict) -> str:
    """The MCP client: the OAuth client's name, or 'API token' for rlf_."""
    if user.get("oauth_client") or user.get("via_oauth"):
        return normalise_client(user.get("oauth_client"))
    if user.get("via_token"):
        return "API token"
    return "unknown"


# ---------------------------------------------------------------------------
# Recording
# ---------------------------------------------------------------------------

def record(
    db,
    *,
    uid: str,
    channel: str,
    feature: str,
    outcome: str = "ok",
    plan: str = "",
    client: str = "",
    ms: float | None = None,
) -> bool:
    """Store one usage event; never raises. False when off or it failed."""
    if not enabled() or not uid:
        return False
    try:
        now = _now()
        db.usage_events.insert_one({
            "ts": now,
            "day": now.strftime("%Y-%m-%d"),
            "uid": _clip(uid, 128),
            "channel": _clip(channel, 16),
            "feature": _clip(feature),
            "outcome": outcome if outcome in OUTCOMES else "error",
            "plan": _clip(plan, 16),
            "client": _clip(client, 32),
            "ms": int(ms) if ms is not None else None,
        })
    except Exception:  # noqa: BLE001 - analytics must never fail the caller
        logger.warning("could not record a usage event", exc_info=True)
        return False
    _maybe_rollup(db)
    return True


def record_for(db, user: dict, *, channel: str, feature: str, outcome: str = "ok",
               client: str = "", ms: float | None = None) -> bool:
    """:func:`record` for an authenticated user dict (looks up the plan)."""
    if not enabled() or not user or not user.get("uid"):
        return False
    try:
        plan = plan_of(db, user)
    except Exception:  # noqa: BLE001
        logger.warning("could not resolve the plan for a usage event", exc_info=True)
        plan = ""
    return record(db, uid=user["uid"], channel=channel, feature=feature, outcome=outcome,
                  plan=plan, client=client, ms=ms)


def _spawn(fn, *args) -> None:
    threading.Thread(target=fn, args=args, daemon=True, name="usage-rollup").start()


def _maybe_rollup(db) -> None:
    """Kick off a background roll-up at most every few minutes per instance —
    so a new day gets its predecessor rolled up without a cron."""
    global _next_rollup
    now = time.monotonic()
    if now < _next_rollup:
        return
    with _rollup_lock:
        if now < _next_rollup:
            return
        _next_rollup = now + _ROLLUP_EVERY_S
    _spawn(_safe_rollup, db)


def _safe_rollup(db) -> None:
    try:
        rollup(db)
    except Exception:  # noqa: BLE001
        logger.warning("usage roll-up failed", exc_info=True)


def on_plan_change(db, uid: str, old_plan: str, new_plan: str) -> None:
    """Conversions: a move to Pro records ``pro_upgrade`` and, when the
    account had met an MCP plan wall (locked / limit / pro_only, within the
    90 days events are kept), ``upgrade_after_mcp_lock``. Never raises."""
    forget_plan(uid)
    if not enabled() or new_plan != "pro" or old_plan == "pro":
        return
    try:
        record(db, uid=uid, channel="billing", feature=PRO_UPGRADE, plan="pro")
        walled = db.usage_events.find_one(
            {"uid": uid, "channel": "mcp", "outcome": {"$in": list(WALL_OUTCOMES)}}, {"_id": 1})
        if walled is not None:
            record(db, uid=uid, channel="billing", feature=UPGRADE_AFTER_LOCK, plan="pro")
    except Exception:  # noqa: BLE001
        logger.warning("could not record a plan change", exc_info=True)


# ---------------------------------------------------------------------------
# The app (REST) channel: route -> feature
# ---------------------------------------------------------------------------

# (method, path template, feature). Templates use {name} for one path
# segment. Checked in order; first match wins.
APP_ROUTES: tuple[tuple[str, str, str], ...] = (
    # Life data
    ("POST", "/api/fit/{d}", "fit"),
    ("POST", "/api/evaluate/{id}", "model_evaluate"),
    ("POST", "/api/confidence/{id}", "model_evaluate"),
    ("POST", "/api/datasets", "dataset_upload"),
    ("POST", "/api/datasets/paste", "dataset_upload"),
    ("DELETE", "/api/datasets/{id}", "dataset_delete"),
    ("POST", "/api/models", "model_save"),
    ("POST", "/api/models/from-params", "model_save"),
    ("POST", "/api/models/per-demand", "model_save"),
    ("PUT", "/api/models/{id}/fit", "model_refit"),
    ("POST", "/api/models/{id}/evaluate", "model_evaluate"),
    ("POST", "/api/models/{id}/confidence", "model_evaluate"),
    ("DELETE", "/api/models/{id}", "model_delete"),
    # RBDs (a repairable analysis is re-labelled availability_sim by the route)
    ("POST", "/api/rbds", "rbd_save"),
    ("POST", "/api/rbds/analyze", "rbd_analyze"),
    ("GET", "/api/rbds/{id}/analyze", "rbd_analyze"),
    ("GET", "/api/rbds/{id}/export.py", "export_python"),
    ("DELETE", "/api/rbds/{id}", "rbd_delete"),
    ("POST", "/api/rbds/import", "rbd_import"),
    ("POST", "/api/rbds/compare", "availability_compare"),
    ("POST", "/api/rbds/design/cheapest", "rbd_cheapest_design"),
    ("POST", "/api/rbds/design/apply", "rbd_design_apply"),
    ("POST", "/api/rbds/design", "rbd_design"),
    ("POST", "/api/rbds/fault-tree", "rbd_fault_tree"),
    # Maintenance strategy
    ("POST", "/api/strategy/optimal-replacement", "strategy_replacement"),
    ("POST", "/api/strategy/compare-two", "strategy_compare"),
    ("POST", "/api/strategy/failure-finding", "strategy_failure_finding"),
    ("POST", "/api/strategy/analyses", "strategy_save"),
    ("POST", "/api/recurrent/models/{id}/overhaul", "strategy_overhaul"),
    # Recurrent, degradation, ALT
    ("POST", "/api/recurrent/fit", "recurrent_fit"),
    ("POST", "/api/recurrent/models", "recurrent_save"),
    ("POST", "/api/recurrent/from-params", "recurrent_save"),
    ("POST", "/api/recurrent/models/{id}/predict", "recurrent_predict"),
    ("POST", "/api/degradation/fit", "degradation_fit"),
    ("POST", "/api/degradation/models", "degradation_save"),
    ("POST", "/api/degradation/models/{id}/items", "degradation_tracking"),
    ("POST", "/api/degradation/models/{id}/items/{iid}/measurements", "degradation_tracking"),
    ("POST", "/api/alt/fit", "alt_fit"),
    ("POST", "/api/alt/models", "alt_save"),
    ("POST", "/api/alt/models/{id}/evaluate", "alt_evaluate"),
    # RCM
    ("POST", "/api/rcm/studies", "rcm_create"),
    ("PUT", "/api/rcm/studies/{id}/tree", "rcm_edit"),
    ("POST", "/api/rcm/import/preview", "rcm_import_preview"),
    ("POST", "/api/rcm/import", "rcm_import"),
    # Excel (.xlsx) uploads: sheets read for a dataset, an RCM study or an RBD
    ("POST", "/api/excel/inspect", "excel_inspect"),
    ("POST", "/api/excel/table", "excel_import"),
    ("POST", "/api/excel/csv", "excel_import"),
    # Fleets
    ("POST", "/api/fleet/fleets", "fleet_create"),
    ("PUT", "/api/fleet/fleets/{id}/items", "fleet_items"),
    ("POST", "/api/fleet/fleets/{id}/alerts", "fleet_alert_create"),
    ("POST", "/api/fleet/tracked", "fleet_tracked_create"),
    # AI
    ("POST", "/api/assistant/step", "assistant"),
    ("POST", "/api/assistant/stream", "assistant"),
    ("POST", "/api/reliability-agent/run", "reliability_agent"),
    ("POST", "/api/reliability-agent/upload", "reliability_agent_upload"),
    # Sharing, teams, tokens, connected apps
    ("POST", "/api/shares", "share_user"),
    ("POST", "/api/public-links", "share_link"),
    ("POST", "/api/teams", "team_create"),
    ("POST", "/api/teams/{id}/members", "team_invite"),
    ("POST", "/api/tokens", "api_token_create"),
    ("DELETE", "/api/me/oauth-grants/{id}", "mcp_disconnect"),
    # Billing
    ("POST", "/api/billing/subscribe", "billing_subscribe"),
    ("POST", "/api/billing/checkout", "billing_credits"),
    ("POST", "/api/billing/portal", "billing_portal"),
    # Samples
    ("POST", "/api/samples/restore", "samples_restore"),
    ("POST", "/api/samples/remove", "samples_remove"),
    # Ingestion (an rlf_ token makes these the api channel)
    ("POST", "/api/ingest/fleets/{id}/usage", "fleet_ingest"),
    ("POST", "/api/ingest/tracking/{id}/measurements", "tracking_ingest"),
    ("POST", "/api/ingest/datasets/{id}/lives", "dataset_ingest"),
    ("POST", "/api/import/models", "model_import"),
    # Programmatic API (/api/v1: always an rlf_ token)
    ("GET", "/api/v1/models", "model_list"),
    ("GET", "/api/v1/models/{id}", "model_view"),
    ("POST", "/api/v1/models/{id}/reliability", "model_evaluate"),
    ("POST", "/api/v1/datasets", "dataset_upload"),
    ("POST", "/api/v1/fit", "fit"),
    ("GET", "/api/v1/fleets/{id}/forecast", "fleet_forecast"),
    ("POST", "/api/v1/strategy/optimal-replacement", "strategy_replacement"),
    ("POST", "/api/v1/strategy/failure-finding", "strategy_failure_finding"),
)

# Never logged: operator, telemetry, webhooks, previews and checks the UI
# fires as you type.
_SKIP_PREFIXES = (
    "/api/admin", "/api/metrics", "/api/client-error", "/api/stripe", "/api/email",
    "/api/me/email-preferences", "/api/columns", "/api/rbds/validate", "/api/health",
    "/api/config",
)
# Areas for the fallback name of an unmapped write: /api/<area>/… -> <name>.
_AREAS = {
    "models": "model", "rbds": "rbd", "datasets": "dataset", "strategy": "strategy",
    "rcm": "rcm", "fleet": "fleet", "degradation": "degradation", "recurrent": "recurrent",
    "alt": "alt", "teams": "team", "shares": "share", "public-links": "share_link",
    "tokens": "api_token", "assistant": "assistant", "reliability-agent": "reliability_agent",
    "ingest": "ingest", "import": "import", "billing": "billing", "samples": "samples",
    "me": "account", "v1": "api",
}
_VERBS = {"POST": "create", "PUT": "update", "PATCH": "update", "DELETE": "delete"}


def _compile(template: str) -> re.Pattern:
    parts = [("[^/]+" if p.startswith("{") else re.escape(p)) for p in template.split("/")]
    return re.compile("^" + "/".join(parts) + "$")


_COMPILED = tuple((m, _compile(t), f) for m, t, f in APP_ROUTES)


def app_feature(method: str, path: str) -> str | None:
    """The feature name for an authenticated /api request, or None to skip.

    Explicitly mapped routes first; any other write (POST/PUT/PATCH/DELETE)
    becomes ``<area>_<create|update|delete>``; other GETs (lists, item
    reads, options) aren't logged."""
    method = (method or "").upper()
    path = (path or "").rstrip("/") or "/"
    if not path.startswith("/api/") or path.startswith(_SKIP_PREFIXES):
        return None
    for m, rx, feature in _COMPILED:
        if m == method and rx.match(path):
            return feature
    verb = _VERBS.get(method)
    if verb is None:
        return None
    area = path.split("/")[2] if path.count("/") >= 2 else ""
    name = _AREAS.get(area)
    return f"{name}_{verb}" if name else None


def outcome_for_status(status: int) -> str:
    if status < 400:
        return "ok"
    if status in (402, 429):
        return "limit"
    if status == 403:
        return "locked"
    return "error"


# The current request's usage context (set by UsageMiddleware). A mutable
# dict, so writes from sync dependencies and endpoints — which FastAPI runs in
# a worker thread on a *copy* of the context — still reach the middleware.
_REQUEST: contextvars.ContextVar[dict | None] = contextvars.ContextVar("reliafy_usage_request", default=None)


def note_user(user: dict, channel: str | None = None) -> None:
    """Called where a request's user is resolved (auth.get_current_user, the
    ingest token check): who to attribute the request to, and, for an rlf_
    token, that it's the ``api`` channel."""
    state = _REQUEST.get()
    if state is not None and user:
        state["user"] = user
        if channel:
            state["channel"] = channel


def set_feature(feature: str) -> None:
    """Let a route re-label its request (e.g. a repairable RBD analysis is an
    ``availability_sim``)."""
    state = _REQUEST.get()
    if state is not None:
        state["feature"] = feature


class UsageMiddleware:
    """Pure ASGI middleware: after an authenticated /api request has been
    answered, record it as a feature event. The response is already sent when
    the insert runs (in a worker thread); any failure is swallowed."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or not enabled() or not scope.get("path", "").startswith("/api/"):
            await self.app(scope, receive, send)
            return
        state: dict = {}
        token = _REQUEST.set(state)
        status = {"code": 500}
        started = time.perf_counter()

        async def send_wrapper(message):
            if message["type"] == "http.response.start":
                status["code"] = message["status"]
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        except Exception:
            _REQUEST.reset(token)
            await self._log(scope, state, 500, started)
            raise
        _REQUEST.reset(token)
        await self._log(scope, state, status["code"], started)

    async def _log(self, scope, state: dict, status: int, started: float) -> None:
        try:
            user = state.get("user")
            if not user:
                return
            feature = state.get("feature") or app_feature(scope.get("method", ""), scope.get("path", ""))
            if not feature:
                return
            ms = (time.perf_counter() - started) * 1000
            channel = state.get("channel") or ("api" if scope["path"].startswith("/api/v1/") else "app")
            from anyio import to_thread

            from backend.db import get_db

            await to_thread.run_sync(lambda: record_for(
                get_db(), user, channel=channel, feature=feature,
                outcome=outcome_for_status(status), ms=ms))
        except Exception:  # noqa: BLE001 - never fail (or slow) the request
            logger.warning("could not log app usage", exc_info=True)


# ---------------------------------------------------------------------------
# Roll-up: events -> identifier-free daily / weekly totals
# ---------------------------------------------------------------------------

_EVENT_FIELDS = {"_id": 0, "uid": 1, "day": 1, "channel": 1, "feature": 1, "outcome": 1,
                 "plan": 1, "client": 1, "ms": 1}


def _is_action(e: dict) -> bool:
    """A user action: an app/api request or an MCP tool call (not a protocol
    request, not a billing event)."""
    ch = e.get("channel")
    return ch in ("app", "api") or (ch == "mcp" and e.get("feature") not in MCP_PROTOCOL)


def _segments(e: dict) -> list[str]:
    """Distinct-account segments an event puts its account in."""
    out = []
    ch = e.get("channel")
    if ch == "mcp":
        out.append("mcp_connect")  # anyone who reached the MCP server
    if _is_action(e):
        out += [ch, "any"]
        if ch == "mcp" and e.get("plan") in ("free", "agent"):
            if e.get("outcome") == "limit":
                out.append("wall_limit")
            elif e.get("outcome") == "pro_only":
                out.append("wall_pro_only")
            elif e.get("outcome") == "locked":
                out.append("wall_locked")
            if e.get("outcome") in WALL_OUTCOMES:
                out.append("wall_any")
    elif ch == "mcp" and e.get("outcome") == "locked" and e.get("plan") in ("free", "agent"):
        out += ["wall_locked", "wall_any"]  # a non-Pro API token refused at /mcp
    return out


def _day_docs(day: str, events) -> list[dict]:
    """Identifier-free documents for one day's events."""
    counts: dict[tuple, list] = {}
    accounts: dict[tuple, set] = defaultdict(set)
    for e in events:
        key = (e.get("channel") or "", e.get("feature") or "", e.get("outcome") or "",
               e.get("plan") or "", e.get("client") or "")
        c = counts.setdefault(key, [0, 0, 0])
        c[0] += 1
        if e.get("ms") is not None:
            c[1] += int(e["ms"])
            c[2] += 1
        for seg in _segments(e):
            accounts[(seg, e.get("plan") or "")].add(e.get("uid"))
    docs = [
        {"_id": f"c|{day}|{ch}|{feat}|{out}|{plan}|{client}", "kind": "count", "day": day,
         "channel": ch, "feature": feat, "outcome": out, "plan": plan, "client": client,
         "count": n, "ms_sum": ms_sum, "ms_n": ms_n}
        for (ch, feat, out, plan, client), (n, ms_sum, ms_n) in counts.items()
    ]
    docs += [
        {"_id": f"a|{day}|{seg}|{plan}", "kind": "accounts", "day": day, "segment": seg,
         "plan": plan, "accounts": len(uids)}
        for (seg, plan), uids in accounts.items()
    ]
    return docs


def _week_doc(week: str, events) -> dict:
    """Distinct accounts per segment for one ISO week (operator accounts
    left out), plus 'repeat' wall accounts: hit a wall on 2+ days."""
    accounts: dict[str, set] = defaultdict(set)
    wall_days: dict[str, set] = defaultdict(set)
    for e in events:
        if e.get("plan") == "admin":
            continue
        segs = _segments(e)
        for seg in segs:
            accounts[seg].add(e.get("uid"))
        if "wall_any" in segs:
            wall_days[e.get("uid")].add(e.get("day"))
    seg_counts = {seg: len(uids) for seg, uids in accounts.items()}
    seg_counts["wall_repeat"] = sum(1 for days in wall_days.values() if len(days) >= 2)
    return {"_id": f"w|{week}", "week": week, "segments": seg_counts}


def _days_between(start: date, end: date) -> list[str]:
    return [(start + timedelta(days=i)).strftime("%Y-%m-%d") for i in range((end - start).days + 1)]


def _week_start(d: date) -> date:
    return d - timedelta(days=d.weekday())  # Monday


def _events(db, days: list[str]):
    return db.usage_events.find({"day": {"$in": days}}, _EVENT_FIELDS)


def rollup(db, now: datetime | None = None, force: bool = False) -> dict:
    """Roll up every finished day (and ISO week) with events, still within
    the event retention, that isn't rolled up yet. Idempotent. ``force``
    re-rolls them all (the events must still exist). Returns what it rolled."""
    if not enabled():
        return {"days": [], "weeks": []}
    now = now or _now()
    today = now.date()
    first = today - timedelta(days=RETENTION_DAYS - 1)
    done_days, done_weeks = set(), set()
    if not force:
        for doc in db.usage_rollups.find({"key": {"$gte": first.strftime("%Y-%m-%d")}}, {"kind": 1, "key": 1}):
            (done_days if doc.get("kind") == "day" else done_weeks).add(doc.get("key"))

    # Only days that have events: an empty day needs no totals (the report
    # reads it as zero), so the first run after a deploy isn't 90 round trips.
    active = set(db.usage_events.distinct(
        "day", {"day": {"$gte": first.strftime("%Y-%m-%d"), "$lt": today.strftime("%Y-%m-%d")}}))
    rolled_days = []
    for day in sorted(active):
        end = datetime.fromisoformat(day).replace(tzinfo=timezone.utc) + timedelta(days=1)
        if day in done_days or now < end + _GRACE:
            continue
        docs = _day_docs(day, _events(db, [day]))
        for doc in docs:
            db.usage_daily.replace_one({"_id": doc["_id"]}, doc, upsert=True)
        db.usage_daily.delete_many({"day": day, "_id": {"$nin": [d["_id"] for d in docs]}})
        db.usage_rollups.replace_one({"_id": f"day:{day}"},
                                     {"kind": "day", "key": day, "rolled_at": now}, upsert=True)
        rolled_days.append(day)

    rolled_weeks = []
    monday = _week_start(first)
    if monday < first:
        monday += timedelta(days=7)  # only weeks whose every day is still kept
    while monday + timedelta(days=7) <= today:
        week = monday.strftime("%Y-%m-%d")
        end = datetime.combine(monday + timedelta(days=7), datetime.min.time(), tzinfo=timezone.utc)
        week_days = _days_between(monday, monday + timedelta(days=6))
        if week not in done_weeks and now >= end + _GRACE and active.intersection(week_days):
            doc = _week_doc(week, _events(db, week_days))
            db.usage_weekly.replace_one({"_id": doc["_id"]}, doc, upsert=True)
            db.usage_rollups.replace_one({"_id": f"week:{week}"},
                                         {"kind": "week", "key": week, "rolled_at": now}, upsert=True)
            rolled_weeks.append(week)
        monday += timedelta(days=7)
    return {"days": rolled_days, "weeks": rolled_weeks}


# ---------------------------------------------------------------------------
# The operator report
# ---------------------------------------------------------------------------

def _top(counter: Counter, n: int = 15) -> list[dict]:
    return [{"key": k, "count": v} for k, v in counter.most_common(n)]


def report(db, days: int = 30, include_admin: bool = False, now: datetime | None = None) -> dict:
    """Everything the admin dashboard's usage section shows, for the last
    ``days`` days (today included).

    Finished days come from the identifier-free daily totals; days not rolled
    up yet (today) are aggregated live from the events. Anything that needs
    account ids across days — repeat wall hits, upgrades, MCP vs app accounts
    over the period — can only look back 90 days (``window_days``).
    Operator accounts are left out unless ``include_admin``."""
    days = max(1, min(int(days or 30), 3660))
    now = now or _now()
    today = now.date()
    try:
        rollup(db, now=now)
    except Exception:  # noqa: BLE001 - a stale report beats none
        logger.warning("usage roll-up failed", exc_info=True)

    axis = _days_between(today - timedelta(days=days - 1), today)
    keep = (lambda plan: True) if include_admin else (lambda plan: plan != "admin")

    # Daily documents: stored for rolled-up days, computed for the rest.
    stored: dict[str, list[dict]] = defaultdict(list)
    for doc in db.usage_daily.find({"day": {"$gte": axis[0]}}, {"_id": 0}):
        stored[doc["day"]].append(doc)
    rolled = {d["key"] for d in db.usage_rollups.find({"kind": "day", "key": {"$gte": axis[0]}}, {"key": 1})}
    live_days = [d for d in axis if d not in rolled and d >= (today - timedelta(days=RETENTION_DAYS - 1)).isoformat()]
    if live_days:
        by_day: dict[str, list] = defaultdict(list)
        for e in _events(db, live_days):
            by_day[e["day"]].append(e)
        for d in live_days:
            stored[d] = [{k: v for k, v in doc.items() if k != "_id"} for doc in _day_docs(d, by_day.get(d, []))]

    daily = []
    tools: dict[str, Counter] = defaultdict(Counter)
    tool_ms: dict[str, list] = defaultdict(lambda: [0, 0])
    features: dict[str, dict[str, Counter]] = {"app": defaultdict(Counter), "api": defaultdict(Counter)}
    mcp_outcomes: Counter = Counter()
    clients: Counter = Counter()
    mcp_plans: Counter = Counter()
    connects: Counter = Counter()
    billing: Counter = Counter()
    totals: Counter = Counter()
    for d in axis:
        row = {"day": d, "app": 0, "mcp": 0, "api": 0, "mcp_connects": 0,
               "app_accounts": 0, "mcp_accounts": 0, "api_accounts": 0, "any_accounts": 0,
               "mcp_connect_accounts": 0, "wall_accounts": 0}
        for doc in stored.get(d, []):
            if not keep(doc.get("plan")):
                continue
            if doc.get("kind") == "accounts":
                seg = doc["segment"]
                if seg in ("app", "mcp", "api", "any", "mcp_connect"):
                    row[f"{seg}_accounts"] += doc["accounts"]
                elif seg == "wall_any":
                    row["wall_accounts"] += doc["accounts"]
                continue
            ch, feat, out, n = doc["channel"], doc["feature"], doc["outcome"], doc["count"]
            if ch == "billing":
                billing[feat] += n
                continue
            if ch == "mcp" and feat in MCP_PROTOCOL:
                row["mcp_connects"] += n if feat == "initialize" else 0
                connects[feat] += n
                continue
            row[ch] = row.get(ch, 0) + n
            totals[ch] += n
            if ch == "mcp":
                tools[feat][out] += n
                tool_ms[feat][0] += doc.get("ms_sum", 0)
                tool_ms[feat][1] += doc.get("ms_n", 0)
                mcp_outcomes[out] += n
                clients[doc.get("client") or "unknown"] += n
                mcp_plans[doc.get("plan") or "unknown"] += n
            elif ch in features:
                features[ch][feat][out] += n
        daily.append(row)

    def table(rows: dict[str, Counter], ms: dict | None = None, n: int = 25) -> list[dict]:
        out = []
        for key, c in rows.items():
            item = {"key": key, "count": sum(c.values()), **{o: c.get(o, 0) for o in OUTCOMES}}
            if ms is not None and ms[key][1]:
                item["avg_ms"] = round(ms[key][0] / ms[key][1])
            out.append(item)
        out.sort(key=lambda r: (-r["count"], r["key"]))
        return out[:n]

    weekly = _weekly(db, today, days, include_admin)
    window = _window_stats(db, today, min(days, RETENTION_DAYS), keep)
    all_actions = sum(totals.values())
    return {
        "days": days,
        "include_admin": include_admin,
        "retention_days": RETENTION_DAYS,
        "generated_at": now.isoformat(),
        "totals": {"app": totals["app"], "mcp": totals["mcp"], "api": totals["api"],
                   "mcp_connects": connects["initialize"], "mcp_tool_lists": connects["tools/list"]},
        "daily": daily,
        "weekly": weekly,
        "mcp_tools": table(tools, tool_ms),
        "app_features": table(features["app"]),
        "api_features": table(features["api"]),
        "mcp_outcomes": {o: mcp_outcomes.get(o, 0) for o in OUTCOMES},
        "mcp_clients": _top(clients),
        "mcp_plans": _top(mcp_plans),
        "share": {
            "mcp_actions": totals["mcp"], "app_actions": totals["app"], "api_actions": totals["api"],
            "mcp_share": round(totals["mcp"] / all_actions, 4) if all_actions else 0.0,
            **window["accounts"],
        },
        "pro_wall": {
            **window["wall"],
            "pro_upgrades": billing[PRO_UPGRADE],
            "upgrades_after_wall": billing[UPGRADE_AFTER_LOCK],
        },
        "window_days": window["window_days"],
    }


def _weekly(db, today: date, days: int, include_admin: bool) -> list[dict]:
    """Distinct accounts per ISO week: stored weeks, and the weeks not rolled
    up yet (the current one) computed from the events."""
    first = _week_start(today - timedelta(days=days - 1))
    weeks = []
    monday = first
    while monday <= today:
        weeks.append(monday)
        monday += timedelta(days=7)
    stored = {d["week"]: d for d in db.usage_weekly.find({"week": {"$gte": first.isoformat()}}, {"_id": 0})}
    oldest_kept = today - timedelta(days=RETENTION_DAYS - 1)
    out = []
    for monday in weeks:
        key = monday.isoformat()
        doc = stored.get(key) if not include_admin else None
        if doc is None and monday >= oldest_kept:
            evs = _events(db, _days_between(monday, min(monday + timedelta(days=6), today)))
            if include_admin:
                evs = [dict(e, plan=("pro" if e.get("plan") == "admin" else e.get("plan"))) for e in evs]
            doc = _week_doc(key, evs)
        segs = (doc or {}).get("segments", {})
        out.append({
            "week": key,
            "partial": monday + timedelta(days=6) >= today,
            "app": segs.get("app", 0), "mcp": segs.get("mcp", 0), "api": segs.get("api", 0),
            "any": segs.get("any", 0), "mcp_connect": segs.get("mcp_connect", 0),
            "wall_any": segs.get("wall_any", 0), "wall_limit": segs.get("wall_limit", 0),
            "wall_pro_only": segs.get("wall_pro_only", 0), "wall_locked": segs.get("wall_locked", 0),
            "wall_repeat": segs.get("wall_repeat", 0),
            "available": doc is not None,
        })
    return out


def _window_stats(db, today: date, window: int, keep) -> dict:
    """Account-level numbers over the last ``window`` (≤ 90) days, from the
    events: who used MCP vs the app, who hit the MCP plan wall (and how
    often), and how many of those then moved to Pro."""
    since = (today - timedelta(days=window - 1)).isoformat()
    by_seg: dict[str, set] = defaultdict(set)
    wall_days: dict[str, set] = defaultdict(set)
    upgraded: set = set()
    cursor = db.usage_events.find({"day": {"$gte": since}}, _EVENT_FIELDS)
    for e in cursor:
        if e.get("channel") == "billing":
            if e.get("feature") == UPGRADE_AFTER_LOCK:
                upgraded.add(e.get("uid"))
            continue
        if not keep(e.get("plan")):
            continue
        segs = _segments(e)
        for seg in segs:
            by_seg[seg].add(e.get("uid"))
        if "wall_any" in segs:
            wall_days[e.get("uid")].add(e.get("day"))
    walled = by_seg["wall_any"]
    return {
        "window_days": window,
        "accounts": {
            "mcp_accounts": len(by_seg["mcp"]),
            "app_accounts": len(by_seg["app"]),
            "api_accounts": len(by_seg["api"]),
            "any_accounts": len(by_seg["any"]),
            "mcp_and_app_accounts": len(by_seg["mcp"] & by_seg["app"]),
            "mcp_only_accounts": len(by_seg["mcp"] - by_seg["app"] - by_seg["api"]),
            "mcp_connect_accounts": len(by_seg["mcp_connect"]),
        },
        "wall": {
            "accounts": len(walled),
            "limit_accounts": len(by_seg["wall_limit"]),
            "pro_only_accounts": len(by_seg["wall_pro_only"]),
            "locked_accounts": len(by_seg["wall_locked"]),
            "repeat_accounts": sum(1 for d in wall_days.values() if len(d) >= 2),
            "upgraded_accounts": len(walled & upgraded),
        },
    }
