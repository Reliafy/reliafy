"""Reliafy as a remote MCP (Model Context Protocol) server, at ``/mcp``.

AI assistants (Claude Code first) connect over Streamable HTTP and use
Reliafy on a user's behalf: fit life distributions, read saved models,
evaluate reliability, build and analyse RBDs, and run the maintenance
calculators.

Transport: stateless Streamable HTTP with plain JSON responses (no SSE). Every
POST is self-contained, so the server scales across Cloud Run instances and
survives CDN/proxy buffering that would stall an event stream.

Auth: a bearer token, mapped to a user by :func:`resolve_bearer`, which tries
each entry of :data:`BEARER_RESOLVERS` in turn:

* personal API tokens (``rlf_…``), with exactly the programmatic API's rules —
  Pro-only on the cloud (:func:`billing.api_access_allowed`, 403 otherwise),
  always allowed self-hosted;
* OAuth access tokens (``rlfo_…``) issued by Reliafy's own authorization
  server (:mod:`backend.services.oauth`) — how Claude connectors sign in.

Plans (:func:`billing.mcp_plan`, attached to the request as ``mcp_plan``):
using Reliafy over MCP is part of Pro — the same entitlement as the REST API
(:func:`billing.api_access_allowed`: Pro, operators, self-hosted installs) —
with every tool and no quota. A Free OAuth user gets a small allowance to try
it (``MCP_FREE_MONTHLY_CALLS`` tool calls per UTC calendar month, every tool
except the Pro-only ones — fitting and fleets — within the Free storage
caps); past it, each call answers with when the allowance resets and how to
upgrade.

Grandfathered: subscribers to the retired Agent plan (US$2/month, MCP only)
keep what they had until their subscription ends — every tool except fitting
and fleets (agents fit locally with SurPyval and save with ``save_model``),
within a daily tool-call quota and the Agent storage caps. Availability
simulation keeps the app's own paid gate (Pro or purchased credits). Every
refusal is a tool error that says what the limit is, when it resets and how
to upgrade — never a transport failure.

Either way: the same per-user rate limit, and the same scope — the user's
personal data plus the shared samples (as ``/api/v1``). A missing or invalid
token gets a 401 whose ``WWW-Authenticate`` points at the protected-resource
metadata, which is what starts Claude's OAuth sign-in.

Tools call the service layer directly — never HTTP back into ourselves — and
turn user-facing failures (``FitError`` and friends) into MCP tool errors with
the message intact. Anything unexpected reaches the model only as "Error
executing tool …"; the traceback goes to the log.

Usage logging (:mod:`backend.services.usage`): every tool call — refused ones
included — is one usage event with the tool, its outcome (ok / error / limit
/ pro_only), the plan, the OAuth client's name and the duration;
``initialize`` and ``tools/list`` are logged as connections, and a non-Pro
API token refused at the transport as ``connect`` / ``locked``.
"""

import contextvars
import copy
import functools
import logging
import math
import re
import time
from datetime import timedelta
from contextlib import asynccontextmanager
from typing import Annotated, Any, Callable, Literal, Optional, Union

import anyio
import numpy as np
import pandas as pd
from mcp.server.mcpserver import Context, MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.server.transport_security import TransportSecuritySettings
from mcp_types import ToolAnnotations
from pydantic import BaseModel, ConfigDict, Field
from starlette.datastructures import Headers
from starlette.exceptions import HTTPException
from starlette.responses import JSONResponse

from backend import config
from backend import fitting
from backend import recurrent as recurrent_fit
from backend import storage
from backend.fitting import FitError
from backend.services import access as access_service
from backend.services import billing as billing_service
from backend.services import datasets as datasets_service
from backend.services import fleet as fleet_service
from backend.services import fleet_alerts as alerts_service
from backend.services import oauth as oauth_service
from backend.services import outage_logs as outage_logs_service
from backend.services import models as models_service
from backend.services import rbd_edit
from backend.services import rbd_graph
from backend.services import rbds as rbds_service
from backend.services import recurrent as recurrent_service
from backend.services import samples as samples_service
from backend.services import strategy_store
from backend.services import tokens as tokens_service
from backend.services import usage as usage_service
from backend.services import rbd_analysis
from backend.services import rbd_export
from backend.services.rbd_analysis import AnalysisError
from backend.services.strategy import StrategyError

logger = logging.getLogger(__name__)

MCP_PRO_REQUIRED = (
    "MCP access with an API token is part of Reliafy Pro. Upgrade to Pro, then create an API "
    "token under Settings > API access (or sign in to Reliafy from your MCP client)."
)


PRO_PRICE = "US$19/month"
_PLAN_NAMES = {"free": "Free", "agent": "Agent", "pro": "Pro"}


def _billing_url() -> str:
    return f"{config.PUBLIC_BASE_URL or 'https://reliafy.com'}/billing"


def _upgrade_path(lead: str = "To lift it, upgrade") -> str:
    """How to lift a limit (Free's allowance, a grandfathered Agent quota): Pro."""
    return (f"{lead} to Reliafy Pro ({PRO_PRICE}) at {_billing_url()} "
            "(or call upgrade_link for a direct payment link).")


def _until(when) -> str:
    """'in 5 h 12 min' until a reset time, for limit messages."""
    minutes = max(1, int((when - billing_service._now()).total_seconds() // 60))
    hours, minutes = divmod(minutes, 60)
    return f"in {hours} h {minutes} min" if hours else f"in {minutes} min"


def _pro_only_message(tool: str) -> str:
    if tool in _FIT_TOOLS:
        return (f"Fitting in Reliafy is part of Reliafy Pro ({PRO_PRICE}) and isn't included on this plan. "
                "Fit the data locally with SurPyval instead (pip install surpyval; e.g. "
                "surpyval.Weibull.fit(x=times, c=censored) — 0 = failed, 1 = still running), then save the "
                "fitted parameters to Reliafy with save_model. Or upgrade to Pro at "
                f"{_billing_url()} (or call upgrade_link for a payment link) to fit here.")
    return (f"Fleet forecasts and fleet alerts are part of Reliafy Pro ({PRO_PRICE}) — they run on usage "
            f"pushed through the Pro API — and aren't included on this plan. Upgrade at {_billing_url()} "
            "(or call upgrade_link for a payment link).")


def _in_days(when) -> str:
    """'in 12 days' (or, under a day, 'in 5 h 12 min') until ``when``."""
    left = when - billing_service._now()
    if left < timedelta(days=1):
        return _until(when)
    days = math.ceil(left.total_seconds() / 86400)
    return f"in {days} day" + ("s" if days != 1 else "")


def _quota_message(plan: str, quota: int) -> str:
    if plan == "free":
        reset = billing_service.next_month_start()
        return (f"You've used this month's {quota:,} free Reliafy tool calls. They reset on "
                f"{reset.day} {reset:%B} (UTC) — {_in_days(reset)}. Using Reliafy from AI agents without a "
                f"limit is part of Reliafy Pro ({PRO_PRICE}) — upgrade at {_billing_url()}, or call "
                "upgrade_link for a payment link.")
    reset = billing_service.next_day_start()
    return (f"You've used all {quota:,} Reliafy tool calls included per day on the {_PLAN_NAMES[plan]} "
            f"plan. The limit resets at 00:00 UTC ({_until(reset)}). " + _upgrade_path())


def _simulation_message(plan: str) -> str:
    """Why analyze_rbd can't simulate for a Free or grandfathered Agent user, and the
    two ways forward: Pro, or run the same diagram locally for free."""
    return (f"Availability simulation isn't included on the {_PLAN_NAMES[plan]} plan: it needs Reliafy Pro "
            f"({PRO_PRICE}; purchased AI credits unlock it too) — upgrade at {_billing_url()} (or call "
            "upgrade_link for a payment link). It's free to run "
            "locally: export_rbd_python (Download as Python in the app) gives a standalone script that runs "
            "this diagram's simulation with RePyability, plus the exact install-and-run command. A saved "
            "result is served here whenever one exists.")


# ---------------------------------------------------------------------------
# Auth: bearer token -> user
# ---------------------------------------------------------------------------

BearerResolver = Callable[[Any, str], Optional[dict]]


def _api_token_user(db, raw: str) -> dict | None:
    """Personal API tokens (``rlf_…``). ``verify`` also stamps ``last_used_at``."""
    if not raw.startswith("rlf_"):
        return None
    return tokens_service.verify(db, raw)


def _oauth_access_user(db, raw: str) -> dict | None:
    """OAuth access tokens (``rlfo_…``) minted for this MCP resource."""
    return oauth_service.verify_access_token(db, raw)


# Tried in order; the first to return a user wins. Each gets the raw bearer
# value and returns ``{uid, email, name, …}`` or None.
BEARER_RESOLVERS: list[BearerResolver] = [_api_token_user, _oauth_access_user]


def resolve_bearer(db, raw: str) -> dict | None:
    """Map a raw bearer token to its user, or None if no resolver accepts it."""
    raw = (raw or "").strip()
    if not raw:
        return None
    for resolver in BEARER_RESOLVERS:
        user = resolver(db, raw)
        if user:
            return user
    return None


def authenticate(db, authorization: str | None) -> tuple[int, dict | None, str]:
    """``(status, user, message)`` for an MCP request's Authorization header:
    200 with the user, 401 (missing/invalid) or 403 (valid API token, not
    entitled).

    The user carries ``mcp_plan``: 'pro' for anyone with API access (Pro,
    operators, self-hosted — the only way an ``rlf_`` token gets in), else
    the OAuth user's own plan, 'agent' (grandfathered) or 'free' (the daily
    allowance), which :func:`_gate` gates tools and quotas on."""
    scheme, _, raw = (authorization or "").partition(" ")
    if scheme.lower() != "bearer" or not raw.strip():
        return 401, None, (
            "Sign in to Reliafy to use it from Claude (the client starts OAuth from this response), "
            "or send 'Authorization: Bearer rlf_…' with an API token from Settings > API access."
        )
    user = resolve_bearer(db, raw)
    if user is None:
        return 401, None, "Invalid, expired or revoked token."
    plan = billing_service.mcp_plan(db, user)
    if plan == "pro":
        return 200, {**user, "mcp_plan": "pro"}, ""
    if not user.get("via_oauth"):
        usage_service.record(db, uid=user["uid"], channel="mcp", feature="connect", outcome="locked",
                             plan=plan, client=usage_service.client_of(user))
        return 403, None, MCP_PRO_REQUIRED
    return 200, {**user, "mcp_plan": plan}, ""


# ---------------------------------------------------------------------------
# The server
# ---------------------------------------------------------------------------

INSTRUCTIONS = """\
Reliafy is a reliability-engineering workspace (built on SurPyval and RePyability). These tools act on the \
signed-in user's own Reliafy data plus the shared sample library.

What you can do:
- Life data: fit_distribution to failure times (inline data or a saved dataset), fit_and_save_model to keep \
it as a model, or save_model to save parameters fitted elsewhere; evaluate a saved model with reliability_at. \
list_models / get_model read what is saved; list_datasets / upload_dataset manage the data.
- Reliability block diagrams: list_rbds / get_rbd, create_rbd, analyze_rbd (system reliability, MTTF, \
B-lives, importance; availability for repairable diagrams), export_rbd_python (a standalone script). Edit, \
don't rebuild: to change a saved diagram, send edit_rbd one batch of ops (add/remove/update blocks and \
edges) rather than re-creating it; clone_rbd copies a sample or makes a variant to edit.
- Observed history: upload_outage_log saves a real outage log (asset, start, end; blank end = still down) \
against one of the user's diagrams; system_history then gives the system's actual availability over the \
window, its outages each attributed to the block that took it down, and the blocks ranked by downtime share.
- Maintenance strategy: optimal_replacement, failure_finding_interval, optimal_overhaul (recurrent models), \
and fleet_forecast (list_fleets first); list_fleet_alerts / create_fleet_alert manage email alerts on a \
fleet's expected failures.
- Test planning: plan_demonstration_test sizes a reliability demonstration test — units, test time per unit \
and allowed failures to show reliability R over a mission at confidence C (success run / binomial; a longer \
test per unit with a known Weibull shape; or an MTBF test). It needs no saved data.
- Housekeeping: delete_model, delete_dataset and delete_rbd permanently delete the user's own artifacts \
(never shared samples; a dataset still used by a model, or a model a fleet runs on, can't be deleted). \
Only on the user's explicit \
request: confirm by name first, and relay anything the response lists as affected.
- Plans: upgrade_link gives the user a Stripe payment link for Reliafy Pro, to open themselves.

Conventions — follow them exactly:
- Censoring: 0 = the unit FAILED at that time, 1 = it was still running (right-censored, a suspension); \
-1 = left-censored (found failed at that time, failed at some unknown earlier time). Spreadsheets are often \
the other way round (1 = failed); if so pass c_invert=true rather than rewriting the data. A fit that reports \
nearly every row censored almost always means the column is inverted.
- Units: parameters and times are in the model's (or diagram's) time unit. Always state the unit; ask if unsure.
- Params are lists of {name, value} using SurPyval names: weibull [alpha (scale), beta (shape)], exponential \
[failure_rate], normal/lognormal [mu, sigma], gamma [alpha, beta].
- RBDs: redundancy must be modelled as redundancy (parallel / k-of-n / standby) — never wire A/B, duplex or \
standby items in series. Never silently invent failure data: ask for MTBFs, or mark guessed values \
placeholder=true and say so.
- Repairable RBDs: analyze_rbd gives, on every plan, the exact availability over time A(t), the mission \
availability and the window's expected system failures, outages, downtime and cost (each labelled exact or \
numerical: deterministic, no simulation), plus the long-run figures — from new, or from now with \
current_state ({node_id: {"down": true, "since": <time into the repair>} or {"age": <time since new>}}), \
over t_max (e.g. the next 720 hours). The Monte-Carlo simulation adds only what it alone gives \
(distributions, P(no outage), percentiles, criticality indices) and is a paid feature; a saved result is \
served when one exists. When the response says the exact figures are simulation-only for a diagram (e.g. \
proof tests that take time), say so.
- Every artifact has a url; share it so the user can open the result in Reliafy.

Plans: using Reliafy from AI agents (these tools) is part of Reliafy Pro, which includes everything with \
no limit. The Free plan gets a few tool calls a month to try it (every tool except fitting and fleets, \
within the Free storage limits). When a tool answers that a limit or plan stops it, tell the user plainly \
what it says — the limit, when it resets and how to upgrade — and don't retry it. If they want to upgrade, upgrade_link gives them a payment link to open themselves; \
nothing is charged until they complete it.
"""

mcp = MCPServer(
    name="reliafy",
    title="Reliafy",
    description="Reliability engineering: life data analysis, RBDs and maintenance strategy.",
    instructions=INSTRUCTIONS,
    website_url="https://reliafy.com",
)

# Every tool carries a human-readable title plus either readOnlyHint=true
# (reads and calculations: Claude may run them without a per-call prompt) or
# destructiveHint=true (anything that writes to the user's workspace — the
# Connectors Directory asks for that on every tool that modifies data, so
# Claude always confirms a save).
_READ = ToolAnnotations(read_only_hint=True, destructive_hint=False, idempotent_hint=True, open_world_hint=False)
_WRITE = ToolAnnotations(read_only_hint=False, destructive_hint=True, idempotent_hint=False, open_world_hint=False)
# A payment link: changes nothing in Reliafy (the user pays, or not, on Stripe).
_LINK = ToolAnnotations(read_only_hint=True, destructive_hint=False, idempotent_hint=False, open_world_hint=True)


# Exceptions whose message is written for the user. Anything else is a bug and
# surfaces only as "Error executing tool …" (traceback logged).
_USER_ERRORS = (
    FitError, StrategyError, AnalysisError, rbd_graph.GraphError,
    fleet_service.FleetValidationError, ValueError, TypeError,
)


# Tools the Free allowance and a grandfathered Agent subscriber don't have.
# Fitting runs server-side CPU those plans don't pay for (agents fit
# locally with SurPyval, then save_model); fleets depend on usage arriving
# through the Pro API.
_FIT_TOOLS = {"fit_distribution", "fit_and_save_model"}
_FLEET_TOOLS = {"list_fleets", "fleet_forecast", "list_fleet_alerts", "create_fleet_alert"}
PRO_ONLY_TOOLS = _FIT_TOOLS | _FLEET_TOOLS
# Never gated or counted: the way to Pro must work when a limit is hit.
UNGATED_TOOLS = {"upgrade_link"}


class Refusal(ToolError):
    """A tool error that is a plan or limit refusing the call, not a mistake in
    it. ``outcome`` says which: 'limit' (a daily allowance or storage cap) or
    'pro_only' (a Pro-only tool or feature on a plan without it). A refused
    call is not counted against the daily allowance."""

    def __init__(self, message: str, outcome: str = "limit"):
        super().__init__(message)
        self.outcome = outcome


def _gate(ctx: Context, name: str) -> bool:
    """Plan gating for one tool call: a Free or grandfathered Agent user meets
    the Pro-only tools, then the daily quota (counted only for calls that pass
    the gate)."""
    user = _caller(ctx)
    if name in UNGATED_TOOLS:
        return False
    plan = user.get("mcp_plan", "pro")
    if plan == "pro":
        return False
    if name in PRO_ONLY_TOOLS:
        raise Refusal(_pro_only_message(name), "pro_only")
    quota, _ = billing_service.mcp_quota(plan)
    if not billing_service.consume_mcp_call(_db(), user["uid"], plan):
        raise Refusal(_quota_message(plan, quota), "limit")
    return quota is not None


# Per tool call: set by tools that answer normally but refuse the work (see
# :func:`_soft_refusal`).
_CALL: contextvars.ContextVar[dict | None] = contextvars.ContextVar("reliafy_mcp_call", default=None)


def _soft_refusal(outcome: str) -> None:
    """Mark the current call as refused by plan or limit although the tool
    answers normally (e.g. analyze_rbd's ``available: false`` when a plan has
    no availability simulation): it isn't counted against the allowance."""
    state = _CALL.get()
    if state is not None:
        state["refused"] = outcome


def _usage_plan(user: dict) -> str:
    """The plan a usage event is filed under: operators as 'admin' (the
    reports leave them out), everyone else by the plan governing their MCP."""
    return "admin" if billing_service.is_admin_user(user) else user.get("mcp_plan", "pro")


def _log_call(ctx: Context, name: str, outcome: str, started: float) -> None:
    """One usage event per tool call (backend/services/usage.py): the tool,
    how it ended, the plan, the client and the duration. Never raises."""
    try:
        user = _caller(ctx)
        usage_service.record(
            _db(), uid=user["uid"], channel="mcp", feature=name, outcome=outcome,
            plan=_usage_plan(user), client=usage_service.client_of(user),
            ms=(time.perf_counter() - started) * 1000)
    except Exception:  # noqa: BLE001 - logging must never fail a tool
        logger.warning("could not log an MCP tool call", exc_info=True)


def _refund(ctx: Context) -> None:
    user = _caller(ctx)
    billing_service.refund_mcp_call(_db(), user["uid"], user.get("mcp_plan", "pro"))


def _tool(name: str, annotations: ToolAnnotations, title: str):
    """Register a tool, translating user-facing failures into tool errors."""

    def decorator(fn):
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            ctx = next((v for v in (*args, *kwargs.values()) if isinstance(v, Context)), None)
            started = time.perf_counter()
            state: dict = {}
            token = _CALL.set(state)
            counted, outcome = False, "error"
            try:
                counted = _gate(ctx, name) if ctx is not None else False
                result = fn(*args, **kwargs)
                outcome = state.get("refused") or "ok"
                if counted and state.get("refused"):  # answered, but as a refusal
                    _refund(ctx)
                return result
            except Refusal as exc:
                outcome = exc.outcome
                if counted:  # refused calls don't count against the allowance
                    _refund(ctx)
                raise
            except ToolError:
                raise
            except (models_service.ModelNotFound, recurrent_service.ModelNotFound, fitting.ModelNotFound):
                raise ToolError("Model not found.") from None
            except rbds_service.RbdNotFound:
                raise ToolError("RBD not found.") from None
            except fleet_service.FleetNotFound:
                raise ToolError("Fleet not found.") from None
            except _USER_ERRORS as exc:
                raise ToolError(str(exc) or "Invalid input.") from exc
            finally:
                _CALL.reset(token)
                if ctx is not None:
                    _log_call(ctx, name, outcome, started)

        mcp.add_tool(wrapper, name=name, title=title, annotations=annotations,
                     description=(fn.__doc__ or "").strip())
        return wrapper

    return decorator


def _db():
    from backend.db import get_db

    return get_db()


def _caller(ctx: Context) -> dict:
    """The authenticated user the HTTP layer attached to this request."""
    request = ctx.request_context.request
    user = getattr(getattr(request, "state", None), "reliafy_user", None)
    if not user:
        raise ToolError("Not authenticated.")
    return user


def _owners(uid: str) -> list[str]:
    """Reads see the caller's own artifacts plus the shared samples (as /api/v1)."""
    return [uid, config.SAMPLE_OWNER]


def _url(path: str) -> str:
    return f"{config.PUBLIC_BASE_URL or 'https://reliafy.com'}{path}"


def _cap(db, user: dict, kind: str, label: str) -> None:
    """Refuse a save past the caller's plan storage cap (operators have none)."""
    if billing_service.is_admin_user(user) or not billing_service.would_exceed_cap(db, user["uid"], kind):
        return
    plan = billing_service.account(db, user["uid"])["active_plan"]
    cap = billing_service.cap_for(kind, plan)
    raise Refusal(
        f"You've reached the {_PLAN_NAMES[plan]} plan's limit of {cap} saved {label}. The limit doesn't "
        f"reset: delete {label} you no longer need in Reliafy to make room. "
        + _upgrade_path(lead="Or, for more storage, upgrade"))


def _finite(v):
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if np.isfinite(f) else None


# ---- shared shapes ----------------------------------------------------------

class Param(BaseModel):
    name: str = Field(description="SurPyval parameter name, e.g. alpha, beta, mu, sigma, failure_rate.")
    value: float


def _plain_params(results: dict) -> list[dict]:
    return [{"name": p.get("name"), "value": p.get("value")} for p in (results.get("params") or [])]


def _life_brief(m) -> dict:
    r = m.results or {}
    return {
        "id": m.id,
        "name": m.name,
        "kind": m.kind,
        "distribution": r.get("distribution", m.distribution_id),
        "distribution_id": r.get("distribution_id") or m.distribution_id,
        "params": _plain_params(r),
        "n": r.get("n"),
        "unit": r.get("unit") or (m.spec or {}).get("unit", ""),
        "is_sample": samples_service.is_sample(m.owner_id),
        "created_at": m.created_at.isoformat(),
        "url": _url(f"/modelling/m/{m.id}"),
    }


def _recurrent_brief(doc) -> dict:
    r = doc.results or {}
    return {
        "id": doc.id,
        "name": doc.name,
        "kind": "recurrent",
        "model": (r.get("model") or {}).get("name"),
        "beta": r.get("beta"),
        "growth": r.get("growth"),
        "n_systems": r.get("n_systems"),
        "n_events": r.get("n_events"),
        "unit": r.get("unit", ""),
        "is_sample": samples_service.is_sample(doc.owner_id),
        "created_at": doc.created_at.isoformat(),
        "url": _url(f"/modelling/recurrent/{doc.id}"),
    }


def _live_metrics(cache_id: str | None) -> dict | None:
    """Median / MTTF / B10 from a live fitted model, when it has them."""
    entry = fitting._MODEL_STORE.get(cache_id) if cache_id else None
    if not entry or entry.get("model") is None:
        return None
    try:
        return fitting._life_metrics(entry["model"])
    except Exception:  # noqa: BLE001 - regression models etc. have no plain metrics
        return None


def _fit_lead(summary: dict) -> dict:
    """The keys of a fit summary that must come first in the response."""
    return {k: summary[k] for k in ("fit_ok", "warning", "warnings") if k in summary}


def _fit_failure_warning(fit_warning: str | None) -> str:
    """The single "didn't converge" warning for MCP callers: SurPyval's reason
    without its Python-API advice (``init`` in ``fit()``), plus what an agent
    can actually do about it."""
    reason = re.sub(r"\s*The parameters below came back from a fit.*$", "", (fit_warning or "").strip(),
                    flags=re.S)
    sentences = [s for s in re.split(r"(?<=[.;])\s+", reason) if s and "init" not in s and "fit()" not in s]
    reason = " ".join(sentences).rstrip(" ;")
    return ("The fit did NOT converge — the parameters and metrics below are not a valid result; don't quote "
            "them." + (f" Optimiser: {reason}" if reason else "") + " Try rescaling the times (e.g. a "
            "larger unit), checking for extreme or mistyped values, or another distribution.")


def _fit_summary(result: dict) -> dict:
    """The parts of a fit payload worth handing to a model (no plot arrays).

    A fit the optimiser reported as failed leads with ``fit_ok: false`` and
    the warning, ahead of the numbers, so they aren't quoted as a result."""
    metrics = result.get("metrics") or _live_metrics((result.get("functions") or {}).get("model_id"))
    lead: dict[str, Any] = {}
    if result.get("fit_ok") is False or result.get("fit_warning"):
        lead = {"fit_ok": False, "warning": _fit_failure_warning(result.get("fit_warning"))}
    if result.get("warnings"):
        lead["warnings"] = result["warnings"]
    out = {
        **lead,
        "distribution": result.get("distribution"),
        "distribution_id": result.get("distribution_id"),
        "kind": result.get("kind"),
        "n": result.get("n"),
        "unit": result.get("unit", ""),
        "params": result.get("params", []),
        "gof": {g["id"]: g["value"] for g in result.get("gof") or []},
        "metrics": metrics,
    }
    for key in ("extra_params", "coefficients", "randomness", "options"):
        if result.get(key):
            out[key] = result[key]
    if result.get("selection"):
        out["selection"] = result["selection"]
    return out


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------

@_tool("list_models", _READ, "List saved models")
def list_models(
    ctx: Context,
    kind: Annotated[Literal["all", "life", "recurrent"], Field(
        description="life = life distributions (use with reliability_at, the calculators and RBDs); "
                    "recurrent = repairable-system (event history) models (use with optimal_overhaul).")] = "all",
) -> dict[str, Any]:
    """List the user's saved models (plus the shared samples, flagged is_sample): id, name, kind,
    distribution, fitted params and time unit. Call this before referring to a model by id."""
    user, db = _caller(ctx), _db()
    owners = _owners(user["uid"])
    out: dict[str, Any] = {}
    if kind in ("all", "life"):
        out["life_models"] = [_life_brief(m) for m in models_service.list_models(db, owners)]
    if kind in ("all", "recurrent"):
        out["recurrent_models"] = [_recurrent_brief(d) for d in recurrent_service.list_models(db, owners)]
    return out


@_tool("get_model", _READ, "Read a saved model")
def get_model(
    ctx: Context,
    model_id: Annotated[str, Field(description="A model id from list_models.")],
) -> dict[str, Any]:
    """Read one saved model in full: fitted parameters with 95% confidence intervals, goodness of fit
    (log-likelihood, AIC, BIC), life metrics (median, MTTF, B10), regression coefficients for
    proportional-hazards models, and the time unit. Works for life and recurrent models."""
    user, db = _caller(ctx), _db()
    owners = _owners(user["uid"])
    m = models_service.get_model(db, model_id, owners)
    if m is not None:
        r = models_service.public_results(m)
        metrics = r.get("metrics")
        if not metrics and m.kind == "distribution":
            try:
                metrics = _live_metrics(models_service._live_cache_id(db, m.id, owners))
            except Exception:  # noqa: BLE001 - metrics are a convenience
                metrics = None
        out = {**_life_brief(m), "params": r.get("params", []), "gof": {g["id"]: g["value"] for g in r.get("gof") or []},
               "metrics": metrics}
        for key in ("coefficients", "extra_params", "randomness", "options", "warnings"):
            if r.get(key):
                out[key] = r[key]
        if (r.get("functions") or {}).get("covariates"):
            out["covariates"] = r["functions"]["covariates"]
        if r.get("fit_ok") is False or r.get("fit_warning"):
            # Lead with it, as the fit tools do.
            out = {"fit_ok": False, "warning": _fit_failure_warning(r.get("fit_warning")), **out}
        return out
    doc = recurrent_service.get_model(db, model_id, owners)
    if doc is not None:
        r = doc.results or {}
        return {**_recurrent_brief(doc), "params": r.get("params"), "gof": r.get("gof"), "trend": r.get("trend")}
    raise ToolError("Model not found.")


_FitDistribution = Annotated[str, Field(
    description="A distribution id — weibull, exponential, normal, lognormal, gamma, loglogistic, "
                "expo_weibull, gumbel, logistic, … — or 'best' to fit every plain distribution and keep "
                "the lowest-AIC one. Regression ids (e.g. weibull_ph) need covariates and a dataset.")]
_FitData = Annotated[Optional[list[float]], Field(
    description="Inline failure/suspension times, one per unit. Give this OR dataset_id.")]
_FitCensored = Annotated[Optional[list[int]], Field(
    description="Censoring flag per time in `data`: 0 = FAILED at that time, 1 = still running "
                "(right-censored / suspended), -1 = left-censored (found failed at that time, having failed "
                "at some unknown earlier time). Omit when every time is a failure.")]
_FitCounts = Annotated[Optional[list[int]], Field(
    description="Optional count per row of `data` (identical units sharing that time and flag).")]
_FitInvert = Annotated[bool, Field(
    description="True when the censoring flags use the opposite convention (1 = failed, 0 = running); "
                "Reliafy flips the 0/1 flags before fitting (-1 is left as is).")]
_FitDataset = Annotated[Optional[str], Field(description="A saved dataset (list_datasets) instead of inline data.")]
_FitTimeCol = Annotated[Optional[str], Field(description="Dataset column holding the times (required with dataset_id).")]
_FitCensorCol = Annotated[Optional[str], Field(description="Dataset column holding the censoring flags (0 = failed, "
                                                             "1 = running, -1 = left-censored).")]
_FitCountCol = Annotated[Optional[str], Field(description="Dataset column holding counts.")]
_FitCovariates = Annotated[Optional[list[str]], Field(
    description="Dataset covariate columns — regression (proportional-hazards etc.) distributions only.")]
_FitUnit = Annotated[Optional[str], Field(description="Time unit of the data, e.g. 'hours', 'cycles', 'km'.")]


def _mcp_fit_error(exc: FitError, c_invert: bool) -> FitError:
    """A fitting error reworded for an MCP caller: the app's remedy ("tick
    'My censor column uses 1 = failed'") becomes the c_invert parameter."""
    hint = ("You passed c_invert=true, so the flags were flipped before fitting — if the data already uses "
            "0 = failed, drop c_invert." if c_invert else
            "If your flags mark failures with a 1, pass c_invert=true rather than rewriting the data.")
    text = str(exc).replace(fitting.CENSOR_INVERT_HINT, hint)
    text = text.replace("clear the 1 = failed option", "drop c_invert")
    if "Censoring value must only be one of" in text:
        # SurPyval's wording, for the single-time-column data these tools take.
        text = ("Censoring flags must each be 0 (failed at that time), 1 (still running: right-censored) or "
                "-1 (left-censored: failed at some unknown time before it); the data has other values.")
    return FitError(text)


def _fit(ctx: Context, *, distribution, data, censored, counts, c_invert, dataset_id, time_column,
         censor_column, count_column, covariates, unit, save: bool, name: str | None) -> dict[str, Any]:
    """Shared body of fit_distribution (report only) and fit_and_save_model."""
    try:
        return _fit_body(ctx, distribution=distribution, data=data, censored=censored, counts=counts,
                         c_invert=c_invert, dataset_id=dataset_id, time_column=time_column,
                         censor_column=censor_column, count_column=count_column, covariates=covariates,
                         unit=unit, save=save, name=name)
    except FitError as exc:
        raise _mcp_fit_error(exc, c_invert) from exc


def _fit_body(ctx: Context, *, distribution, data, censored, counts, c_invert, dataset_id, time_column,
              censor_column, count_column, covariates, unit, save: bool, name: str | None) -> dict[str, Any]:
    user, db = _caller(ctx), _db()
    uid = user["uid"]
    known = {fitting.BEST_ID, fitting.MIXTURE_ID, *fitting.DISTRIBUTIONS, *fitting.DISCRETE,
             *fitting.NONPARAMETRIC, *fitting.REGRESSION_MODELS}
    dist = (distribution or "weibull").strip()
    if dist not in known:
        dist = fitting.resolve_distribution_id(dist)  # FitError -> tool error listing the options

    if (data is None) == (dataset_id is None):
        raise ToolError("Give either inline `data` (a list of times) or a `dataset_id` — exactly one.")
    # Arguments that only apply to the other input form would be ignored:
    # refuse them rather than fit something the caller didn't mean.
    stray = ([k for k, v in (("time_column", time_column), ("censor_column", censor_column),
                             ("count_column", count_column)) if v] if data is not None
             else [k for k, v in (("censored", censored), ("counts", counts)) if v is not None])
    if stray:
        other = "dataset_id" if data is not None else "inline data"
        raise ToolError(f"{', '.join(stray)} only appl{'ies' if len(stray) == 1 else 'y'} with {other} — "
                        "drop it, or switch to that form.")

    dataset = None
    if data is not None:
        if not data:
            raise ToolError("`data` is empty.")
        cols: dict[str, list] = {"x": list(data)}
        mapping = {"x": "x"}
        for key, values, label in (("c", censored, "censored"), ("n", counts, "counts")):
            if values is not None:
                if len(values) != len(data):
                    raise ToolError(f"`{label}` must have one entry per time in `data` ({len(data)}).")
                cols[key] = list(values)
                mapping[key] = key
        if covariates:
            raise ToolError("Covariates need a dataset — upload one with upload_dataset and pass dataset_id.")
        df = pd.DataFrame(cols)
    else:
        dataset = datasets_service.get_dataset(db, dataset_id, uid)
        if dataset is None:
            raise ToolError("Dataset not found.")
        names = [c["name"] for c in dataset.columns]
        if not time_column:
            raise ToolError(f"Say which column holds the times (time_column). Columns: {', '.join(names)}.")
        mapping = {"x": time_column, "c": censor_column, "n": count_column}
        mapping = {k: v for k, v in mapping.items() if v}
        for col in [*mapping.values(), *(covariates or [])]:
            if col not in names:
                raise ToolError(f"Column '{col}' isn't in the dataset. Columns: {', '.join(names)}.")
        df = datasets_service.load_dataframe(dataset)

    options = None
    if c_invert:
        if "c" not in mapping:
            raise ToolError("c_invert flips censoring flags — pass `censored` (or censor_column) too.")
        options = {fitting.CENSOR_INVERT_KEY: True}

    if not save:
        result = fitting.fit(dist, df, mapping, covariates=covariates, unit=unit, options=options)
        summary = _fit_summary(result)
        return {**_fit_lead(summary), "saved": False, **summary}

    name = (name or "").strip()
    if not name:
        raise ToolError("A `name` is required to save the model.")
    _cap(db, user, "models", "models")
    created = None
    if dataset is None:
        csv_bytes = df.to_csv(index=False).encode()
        # Datasets are de-duplicated per owner by checksum: reuse an identical
        # one (never delete it below), otherwise this call creates it.
        reused = db.datasets.find_one({"checksum": storage.checksum(csv_bytes), "owner_id": uid})
        if reused is None:
            _cap(db, user, "datasets", "datasets")
        dataset = datasets_service.create_dataset(db, f"{name} (data)", csv_bytes, uid)
        created = None if reused is not None else dataset
    try:
        model = models_service.save_model(
            db, name, dataset, dist, mapping, covariates, None, unit, owner_id=uid, options=options,
        )
    except Exception:
        # A refused fit mustn't leave the dataset it just created behind.
        if created is not None:
            datasets_service.delete_dataset(db, created.id, uid)
        raise
    summary = _fit_summary(model.results or {})
    return {
        **_fit_lead(summary),
        "saved": True,
        "model_id": model.id,
        "name": model.name,
        "dataset_id": dataset.id,
        "url": _url(f"/modelling/m/{model.id}"),
        **summary,
    }


@_tool("fit_distribution", _READ, "Fit a life distribution")
def fit_distribution(
    ctx: Context,
    distribution: _FitDistribution = "weibull",
    data: _FitData = None,
    censored: _FitCensored = None,
    counts: _FitCounts = None,
    c_invert: _FitInvert = False,
    dataset_id: _FitDataset = None,
    time_column: _FitTimeCol = None,
    censor_column: _FitCensorCol = None,
    count_column: _FitCountCol = None,
    covariates: _FitCovariates = None,
    unit: _FitUnit = None,
) -> dict[str, Any]:
    """Fit a life distribution to failure data with SurPyval and report fitted parameters (with 95% CIs),
    goodness of fit (log-likelihood, AIC, BIC), and life metrics (median, MTTF, B10). Saves nothing — use
    fit_and_save_model to keep the model. Reliafy's censoring convention: 0 = the unit failed, 1 = still
    running (suspended), -1 = left-censored (found failed, at some unknown earlier time); if the data marks
    failures with 1, pass c_invert=true. A fit that says every (or
    all but one) row is censored almost always means the flags are inverted. Weibull beta < 1 = infant
    mortality, ≈ 1 = random failures, > 1 = wear-out."""
    return _fit(ctx, distribution=distribution, data=data, censored=censored, counts=counts, c_invert=c_invert,
                dataset_id=dataset_id, time_column=time_column, censor_column=censor_column,
                count_column=count_column, covariates=covariates, unit=unit, save=False, name=None)


@_tool("fit_and_save_model", _WRITE, "Fit and save a model")
def fit_and_save_model(
    ctx: Context,
    name: Annotated[str, Field(min_length=1, description="Name for the saved model.")],
    distribution: _FitDistribution = "weibull",
    data: _FitData = None,
    censored: _FitCensored = None,
    counts: _FitCounts = None,
    c_invert: _FitInvert = False,
    dataset_id: _FitDataset = None,
    time_column: _FitTimeCol = None,
    censor_column: _FitCensorCol = None,
    count_column: _FitCountCol = None,
    covariates: _FitCovariates = None,
    unit: _FitUnit = None,
) -> dict[str, Any]:
    """Fit a life distribution exactly as fit_distribution does, then save it as a model in the user's
    Reliafy workspace (inline data is saved as a dataset too) and return its id and url. Use it when the
    user wants to keep the model — for reliability_at, the calculators, or an RBD block. Same censoring
    convention: 0 = failed, 1 = still running, -1 = left-censored; c_invert=true when the data marks failures
    with 1."""
    return _fit(ctx, distribution=distribution, data=data, censored=censored, counts=counts, c_invert=c_invert,
                dataset_id=dataset_id, time_column=time_column, censor_column=censor_column,
                count_column=count_column, covariates=covariates, unit=unit, save=True, name=name)


_EXTRA_PARAMS = ("gamma", "p", "f0")  # offset, limited failure population, zero-inflation


@_tool("save_model", _WRITE, "Save a model from parameters")
def save_model(
    ctx: Context,
    name: Annotated[str, Field(min_length=1, description="Name for the saved model.")],
    distribution: Annotated[str, Field(description=(
        "Distribution id: weibull, exponential, normal, lognormal, gamma, loglogistic, expo_weibull, "
        "gumbel, gumbel_lev, logistic, rayleigh (SurPyval class names such as 'Weibull' work too)."))],
    params: Annotated[list[Param], Field(min_length=1, description=(
        "Every fitted parameter by SurPyval name: weibull [alpha (scale), beta (shape)], exponential "
        "[failure_rate], normal/lognormal [mu, sigma], gamma [alpha, beta], expo_weibull [alpha, beta, mu]. "
        "Optional extras from a SurPyval fit: gamma (offset / failure-free life), p (limited failure "
        "population), f0 (zero-inflation)."))],
    unit: _FitUnit = None,
    dataset_id: Annotated[Optional[str], Field(description=(
        "Optional: the saved dataset (list_datasets / upload_dataset) the parameters were fitted to, "
        "kept on the model as a reference."))] = None,
    notes: Annotated[Optional[str], Field(max_length=2000, description=(
        "Optional notes kept with the model, e.g. how it was fitted (method, censoring, SurPyval "
        "version)."))] = None,
) -> dict[str, Any]:
    """Save a life model from a distribution and parameters fitted elsewhere — typically locally with
    SurPyval (e.g. surpyval.Weibull.fit(x=times, c=censored), then model.params) — to the user's Reliafy
    workspace, and return its id and url. The saved model works everywhere a fitted one does:
    reliability_at, the maintenance calculators and RBD blocks. It stores the parameters only (no
    probability plot). Parameter names must be the distribution's SurPyval names; the time unit is the
    unit the parameters were fitted in."""
    user, db = _caller(ctx), _db()
    uid = user["uid"]
    dist_id = fitting.resolve_distribution_id(distribution)  # FitError -> tool error listing the options
    entry = fitting.DISTRIBUTIONS[dist_id]
    names = list(getattr(entry["dist"], "param_names", []) or [])

    given: dict[str, float] = {}
    for p in params:
        key = p.name.strip()
        if key in given:
            raise ToolError(f"Parameter '{key}' is given twice.")
        if not np.isfinite(p.value):
            raise ToolError(f"Parameter '{key}' must be a finite number.")
        given[key] = float(p.value)
    extras = {k: given.pop(k) for k in _EXTRA_PARAMS if k in given and k not in names}
    unknown, missing = sorted(set(given) - set(names)), [n for n in names if n not in given]
    if unknown or missing:
        problem = "; ".join(filter(None, (
            f"unknown: {', '.join(unknown)}" if unknown else "",
            f"missing: {', '.join(missing)}" if missing else "",
        )))
        raise ToolError(f"{entry['name']} takes the parameters {', '.join(names)} (plus optional extras "
                        f"{', '.join(_EXTRA_PARAMS)}) — {problem}.")
    if "gamma" in extras and not entry.get("offsetable"):
        raise ToolError(f"{entry['name']} doesn't take an offset (gamma) — its support is the whole real line.")

    if dataset_id and datasets_service.get_dataset(db, dataset_id, uid) is None:
        raise ToolError("Dataset not found.")
    _cap(db, user, "models", "models")
    model = models_service.import_model(
        db, uid, name.strip(), distribution=dist_id, unit=unit,
        params=[{"name": n, "value": given[n]} for n in names], extras=extras,
        notes=notes, source_dataset_id=dataset_id or None,
    )
    try:
        live = entry["dist"].from_params([given[n] for n in names], **extras)
        metrics = fitting._life_metrics(live)
    except Exception:  # noqa: BLE001 - metrics are a convenience
        metrics = None
    r = model.results or {}
    out = {
        "saved": True,
        "model_id": model.id,
        "name": model.name,
        "distribution": r.get("distribution"),
        "distribution_id": dist_id,
        "params": _plain_params(r),
        "unit": r.get("unit", ""),
        "metrics": metrics,
        "url": _url(f"/modelling/m/{model.id}"),
    }
    if r.get("extra_params"):
        out["extra_params"] = r["extra_params"]
    if dataset_id:
        out["dataset_id"] = dataset_id
    return out


@_tool("reliability_at", _READ, "Evaluate a model's reliability")
def reliability_at(
    ctx: Context,
    model_id: Annotated[str, Field(description="A saved life model id (list_models).")],
    times: Annotated[list[float], Field(min_length=1, max_length=200,
                                        description="Times to evaluate at, in the model's unit.")],
    conditional_age: Annotated[Optional[float], Field(
        description="Optional current age of a unit that is still working. Adds conditional_reliability = "
                    "R(age + t) / R(age): the chance it survives a FURTHER t.")] = None,
    covariates: Annotated[Optional[dict[str, Any]], Field(
        description="Proportional-hazards models only: covariate values by name (see get_model). Any not "
                    "given use the fit's default (the training-data mean); the response says which.")] = None,
) -> dict[str, Any]:
    """Evaluate a saved life model at given times: reliability R(t) (probability of surviving to t),
    failure probability F(t) = 1 − R(t), hazard rate h(t), cumulative hazard H(t) and density f(t).
    Optionally conditional on a unit already having survived to `conditional_age`. Parametric models are
    evaluated exactly from the distribution (method=exact); non-parametric and mixture models are
    interpolated on their stored curve (method=interpolated). Proportional-hazards models report the
    covariate values used (the fit's defaults for any not given)."""
    user, db = _caller(ctx), _db()
    owners = _owners(user["uid"])
    m = models_service.get_model(db, model_id, owners)
    if m is None:
        raise ToolError("Model not found.")
    for t in times:
        if not np.isfinite(t) or t < 0:
            raise ToolError(f"times must be finite and ≥ 0 (in the model's unit); got {t:g}.")
    if conditional_age is not None and (not np.isfinite(conditional_age) or conditional_age < 0):
        raise ToolError(f"conditional_age must be finite and ≥ 0; got {conditional_age:g}.")
    if covariates and m.kind != "regression":
        raise ToolError(f"“{m.name}” is a {m.kind} model with no covariates — drop `covariates`, or pick a "
                        "proportional-hazards model (get_model lists its covariates).")

    ts = [float(t) for t in times]
    later = [conditional_age + t for t in ts] if conditional_age is not None else []
    grid = ts + later + ([float(conditional_age)] if conditional_age is not None else [])
    ev = models_service.evaluate_at(db, m, grid, owners, covariates)
    vals = ev["values"]
    n = len(ts)
    exact = ev["method"] == "exact"
    x_max = ev.get("x_max")

    undefined = False
    points = []
    for i, t in enumerate(ts):
        p = {
            "t": t,
            "reliability": vals["sf"][i],
            "failure": vals["ff"][i],
            "hazard": vals["hf"][i],
            "cumulative_hazard": vals["Hf"][i],
            "density": vals["df"][i],
        }
        if conditional_age is not None:
            # R(a + t) / R(a), via the cumulative hazard where it's finite:
            # exp(-(H(a + t) - H(a))) stays accurate when both reliabilities
            # underflow to 0. Undefined only when R(a) is truly 0.
            h_age, h_later = vals["Hf"][-1], vals["Hf"][n + i]
            r_age, r_later = vals["sf"][-1], vals["sf"][n + i]
            if h_age is not None and h_later is not None:
                p["conditional_reliability"] = float(min(1.0, max(0.0, np.exp(-(h_later - h_age)))))
            elif r_age and r_later is not None:
                p["conditional_reliability"] = r_later / r_age
            else:
                p["conditional_reliability"] = None
                undefined = True
        if not exact and (t > x_max or (conditional_age is not None and conditional_age + t > x_max)):
            p["beyond_curve"] = True
        points.append(p)

    out = {"model": m.name, "model_id": m.id, "unit": (m.results or {}).get("unit", ""),
           "method": ev["method"], "points": points}
    notes = []
    if exact:
        notes.append("Evaluated exactly from the fitted distribution.")
    else:
        notes.append(f"This {m.kind} model has no closed form, so values are interpolated on its stored "
                     f"curve (0 to {x_max:g}).")
        if any(p.get("beyond_curve") for p in points):
            notes.append(f"Times beyond {x_max:g} are past that curve; values there are held at its end "
                         "(flagged beyond_curve).")
    if conditional_age is not None:
        out["conditional_age"] = float(conditional_age)
        if undefined:
            notes.append(f"conditional_reliability is null where it is undefined: the model gives "
                         f"R({conditional_age:g}) = 0, so no unit survives to that age.")
        elif vals["sf"][-1] == 0 and vals["Hf"][-1] is not None:
            # Not 0/0: R(age) is positive but below what a float can hold.
            notes.append(f"R({conditional_age:g}) = exp(-{vals['Hf'][-1]:.4g}) is too small to show "
                         "(it reads 0), but it isn't 0, so conditional_reliability is still defined: it's "
                         "computed exactly as exp(-(H(age + t) - H(age))). Values of 0 there are too small "
                         "to show, not impossible.")
    if ev.get("covariates") is not None:
        used = ev["covariates"]
        out["covariates_used"] = {c["name"]: c["value"] for c in used}
        defaulted = [c for c in used if c["source"] == "default"]
        if defaulted:
            shown = ", ".join(f"{c['name']} = {c['value']:g}" if isinstance(c["value"], float)
                              else f"{c['name']} = {c['value']}" for c in defaulted)
            out["covariate_defaults"] = [c["name"] for c in defaulted]
            notes.append(f"Proportional-hazards model evaluated at {shown} — the fit's default for each "
                         "covariate not given (the training-data mean; the most common level for a "
                         "categorical one). Pass `covariates` to evaluate other conditions.")
    out["note"] = " ".join(notes)
    return out


# ---------------------------------------------------------------------------
# Datasets
# ---------------------------------------------------------------------------

@_tool("list_datasets", _READ, "List datasets")
def list_datasets(ctx: Context) -> dict[str, Any]:
    """List the user's saved datasets with their columns and row counts. Use a dataset_id with
    fit_distribution (plus time_column / censor_column)."""
    user, db = _caller(ctx), _db()
    return {"datasets": [
        {"id": d.id, "name": d.name, "n_rows": d.n_rows, "columns": [c["name"] for c in d.columns],
         "created_at": d.created_at.isoformat(), "url": _url(f"/datasets/d/{d.id}")}
        for d in datasets_service.list_datasets(db, user["uid"])
    ]}


@_tool("upload_dataset", _WRITE, "Upload a dataset")
def upload_dataset(
    ctx: Context,
    name: Annotated[str, Field(min_length=1, description="A short name for the dataset.")],
    csv: Annotated[str, Field(min_length=1, description="The CSV text, header row first. Tab- or "
                                                        "semicolon-separated pastes are accepted too.")],
) -> dict[str, Any]:
    """Save a dataset (CSV text) to the user's workspace and return its id and columns. A censoring
    column should use 0 = failed, 1 = still running, -1 = left-censored (or flag c_invert when fitting)."""
    user, db = _caller(ctx), _db()
    _cap(db, user, "datasets", "datasets")
    ds = datasets_service.create_dataset(db, name.strip(), datasets_service.normalize_pasted(csv), user["uid"])
    return {"id": ds.id, "name": ds.name, "n_rows": ds.n_rows, "columns": [c["name"] for c in ds.columns],
            "preview": datasets_service.preview_rows(ds, 5), "url": _url(f"/datasets/d/{ds.id}")}


# ---------------------------------------------------------------------------
# RBDs
# ---------------------------------------------------------------------------

def _rbd_brief(rbd) -> dict:
    g = rbd.graph or {}
    return {
        "id": rbd.id,
        "name": rbd.name,
        "repairable": bool(g.get("repairable")),
        "unit": g.get("unit") or "",
        "n_blocks": sum(1 for n in g.get("nodes") or [] if n.get("type") not in ("input", "output")),
        "is_sample": samples_service.is_sample(rbd.owner_id),
        "updated_at": rbd.updated_at.isoformat(),
        "url": _url(f"/rbds/b/{rbd.id}"),
    }


def _get_rbd(db, uid: str, rbd_id: str):
    rbd = rbds_service.get_rbd(db, rbd_id, _owners(uid))
    if rbd is None:
        raise ToolError("RBD not found.")
    return rbd


@_tool("list_rbds", _READ, "List RBDs")
def list_rbds(ctx: Context) -> dict[str, Any]:
    """List the user's saved reliability block diagrams (plus shared samples): id, name, whether it is
    repairable (availability) or not (reliability), unit and block count."""
    user, db = _caller(ctx), _db()
    return {"rbds": [_rbd_brief(r) for r in rbds_service.list_rbds(db, _owners(user["uid"]))]}


@_tool("get_rbd", _READ, "Read an RBD")
def get_rbd(
    ctx: Context,
    rbd_id: Annotated[str, Field(description="An RBD id from list_rbds.")],
) -> dict[str, Any]:
    """Read a saved RBD's structure in the compact node format create_rbd accepts (nodes with their
    life models, edges, unit). Blocks whose model is a guessed placeholder are listed."""
    user, db = _caller(ctx), _db()
    rbd = _get_rbd(db, user["uid"], rbd_id)
    graph = rbd.graph or {}
    return {**_rbd_brief(rbd), "graph": rbd_graph.compact_graph(graph),
            "placeholders": rbd_graph.placeholder_labels(graph)}


class BlockModel(BaseModel):
    distribution_id: Optional[str] = Field(None, description=(
        "Inline distribution: weibull, exponential, normal, lognormal, gamma, loglogistic, expo_weibull, "
        "gumbel, logistic. Pair with params. Give this OR saved_model_id."))
    params: Optional[list[Param]] = Field(None, description=(
        "By SurPyval name: weibull [alpha (scale), beta (shape)], exponential [failure_rate], "
        "normal/lognormal [mu, sigma], gamma [alpha, beta]."))
    saved_model_id: Optional[str] = Field(None, description="A saved life model id (list_models) instead of inline params.")
    placeholder: bool = Field(False, description="True ONLY for a guessed starting-point value the user must replace.")


class CostRange(BaseModel):
    min: float = Field(ge=0)
    max: float = Field(ge=0)


Cost = Union[float, CostRange]


class BlockCosts(BaseModel):
    model_config = ConfigDict(extra="forbid")
    repair: Optional[Cost] = Field(None, description="Per failure (labour); a number or {min, max} drawn uniformly.")
    replace: Optional[Cost] = Field(None, description="Per failure (parts); a number or {min, max}.")
    downtime: Optional[float] = Field(None, ge=0, description="Per unit time THIS block is down.")
    acquisition: Optional[float] = Field(None, ge=0, description="Purchase price, once.")


class Preventive(BaseModel):
    model_config = ConfigDict(extra="forbid")
    policy: Literal["age", "block", "condition"] = Field("age", description=(
        "age = replaced at this age (a failure restarts the clock); block = at every multiple of the interval; "
        "condition = inspected every interval (in no time) and replaced when its chance of failing before the "
        "next inspection exceeds threshold."))
    interval: float = Field(gt=0, description="Replacement interval (age/block) or inspection interval (condition).")
    duration: Optional[float] = Field(None, ge=0, description="Time off-line per replacement; 0/omit = instant.")
    cost: Optional[Cost] = Field(None, description="Per replacement.")
    threshold: Optional[float] = Field(None, ge=0, le=1, description=(
        "condition only (required): the probability of failing before the next inspection above which it's "
        "replaced, e.g. 0.05."))
    inspection_cost: Optional[Cost] = Field(None, description="condition only: per condition inspection.")
    opportunity: Optional[float] = Field(None, ge=0, description=(
        "age only, with maintenance_group: renewed early at a stop of its group once at least this old "
        "(0 to interval)."))


class ProofTest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    interval: float = Field(gt=0, description="Proof-test interval.")
    duration: Optional[float] = Field(None, ge=0, description="Time off-line per test; 0/omit = instant (exact "
                                                              "values need instant tests and instant repair).")
    cost: Optional[Cost] = Field(None, description="Per test.")
    offset: Optional[float] = Field(None, ge=0, description=(
        "Time of the first test, 0 to < interval: stagger redundant channels' tests (e.g. interval/2)."))
    coverage: Optional[float] = Field(None, ge=0, le=1, description=(
        "Proof-test coverage: the fraction of failures a test finds (default 1). Below 1 needs full_test."))
    full_test: Optional[float] = Field(None, gt=0, description=(
        "With coverage < 1: the interval of the full test that finds every failure (a whole multiple of interval)."))


class MaintenanceGroup(BaseModel):
    model_config = ConfigDict(extra="forbid")
    setup_cost: Optional[float] = Field(None, ge=0, description="Charged once per group stop (shared mobilisation).")
    system_down: Optional[bool] = Field(None, description="Every system outage is also a stop of the group.")


class RbdNode(BaseModel):
    id: str = Field(description="Unique node id. The diagram needs exactly one 'input' and one 'output' node.")
    type: Literal["input", "output", "component", "series", "parallel", "knode", "standby", "subsystem"] = Field(
        description="component = one block; series/parallel = n identical blocks sharing one model; knode = "
                    "k-of-n voting gate (n = required, k = branches feeding it); standby = spare(s) idle until "
                    "the running unit fails (repairable: identical units, each repaired after it fails); "
                    "subsystem = embed a saved RBD. Repairable diagrams take component, standby and knode.")
    label: Optional[str] = None
    model: Optional[BlockModel] = Field(None, description="Life model (component, series, parallel, standby).")
    repair: Optional[BlockModel] = Field(None, description="Repairable diagrams only: time-to-repair distribution "
                                                           "(component, standby).")
    n: Optional[int] = Field(None, description="series/parallel: number of identical units; knode: number REQUIRED to work.")
    k: Optional[int] = Field(None, description="knode: number of branches feeding the gate.")
    spares: Optional[int] = Field(None, description="standby: number of spares.")
    cold: Optional[bool] = Field(None, description="standby: true = cold (spares don't age while idle).")
    dormancy: Optional[float] = Field(None, ge=0, le=1, description=(
        "standby: how fast an idle spare ages relative to a running one — 0 cold, 1 hot, "
        "in between warm (e.g. 0.2 for a spare kept warm and pressurised). Overrides `cold`."))
    subsystem_rbd_id: Optional[str] = Field(None, description="subsystem: the saved RBD id to embed.")
    # Repairable diagrams: a block's costs and maintenance (#99, #100, #156, #157).
    instant_repair: Optional[bool] = Field(None, description="Repairable component: repaired in zero time (still "
                                                             "fails and costs, never down); no repair model needed.")
    costs: Optional[BlockCosts] = Field(None, description="Repairable component or standby group: its costs.")
    preventive: Optional[Preventive] = Field(None, description=(
        "Repairable component: scheduled (age/block) or condition-based replacement. Not with inspection."))
    inspection: Optional[ProofTest] = Field(None, description=(
        "Repairable component: its failures are HIDDEN until a proof test finds them (any life model). "
        "Not with preventive."))
    maintenance_group: Optional[str] = Field(None, description=(
        "Repairable component: a maintenance group name — members share the group's set-up cost (create_rbd/"
        "set maintenance_groups) and, with preventive.opportunity, are renewed early at its stops."))
    crew_priority: Optional[float] = Field(None, description=(
        "Repairable component or standby group: place in the repair-crew queue, higher first (default 0)."))
    repair_one_at_a_time: Optional[bool] = Field(None, description=(
        "Repairable standby group: one repairer of its own, so its failed units are repaired one at a time "
        "(otherwise each failed unit is a job for the diagram's repair crews). No costs on such a group."))


class RbdEdge(BaseModel):
    source: str
    target: str


class StageComponent(BaseModel):
    label: str
    distribution: Optional[str] = Field(None, description="Inline distribution id (see params). Give this OR model_id.")
    params: Optional[list[Param]] = None
    model_id: Optional[str] = Field(None, description="A saved plain life model id instead of inline params.")
    repair_distribution: Optional[str] = Field(None, description="Repairable RBDs only: time-to-repair distribution id.")
    repair_params: Optional[list[Param]] = None
    placeholder: bool = Field(False, description="True ONLY for guessed starting-point values.")


class Stage(BaseModel):
    label: Optional[str] = None
    components: list[StageComponent] = Field(min_length=1, description="Components in PARALLEL within this stage.")
    k_of_n: Optional[int] = Field(None, description="Components required (k of n), 1 to the stage's component "
                                                     "count. Omit or 1 = any one suffices; = component count = all "
                                                     "required.")
    common_cause_beta: Optional[float] = Field(None, description="Non-repairable only, stages with 2+ components: "
                                                                  "beta-factor common-cause coupling for this stage's "
                                                                  "redundant components, 0 ≤ beta < 1 (typically "
                                                                  "0.01–0.2).")


def _stage_graph(db, uid: str, stages: list[Stage], repairable: bool) -> dict:
    from backend.services.reliability_agent import _build_rbd_graph

    graph = _build_rbd_graph(db, uid, [s.model_dump(exclude_none=True) for s in stages], repairable)
    for si, stage in enumerate(stages):
        for ci, comp in enumerate(stage.components):
            if comp.placeholder:
                node = next(n for n in graph["nodes"] if n["id"] == f"s{si}c{ci}")
                node["data"]["model"]["placeholder"] = True
    return graph


@_tool("create_rbd", _WRITE, "Create an RBD")
def create_rbd(
    ctx: Context,
    name: Annotated[str, Field(min_length=1, description="A short name for the diagram.")],
    unit: Annotated[str, Field(description="The diagram's time unit ('Hours', 'Days', 'Cycles', …); every "
                                           "model's parameters are read in it.")] = "Hours",
    repairable: Annotated[bool, Field(description="True = a repairable system analysed for AVAILABILITY (uptime); "
                                                  "every block then also needs a repair model. False = reliability "
                                                  "over time.")] = False,
    nodes: Annotated[Optional[list[RbdNode]], Field(description="Graph form: the blocks. Use with edges.")] = None,
    edges: Annotated[Optional[list[RbdEdge]], Field(description="Graph form: connections, input -> … -> output.")] = None,
    stages: Annotated[Optional[list[Stage]], Field(
        description="Simple form instead of nodes/edges: stages in SERIES (left to right), each holding one or "
                    "more components in PARALLEL, with optional k_of_n voting.")] = None,
    include_graph: Annotated[bool, Field(description=(
        "Also return the full compact graph. Default: just the node ids, types and labels."))] = False,
    repair_crews: Annotated[Optional[int], Field(ge=1, description=(
        "Repairable only: how many repair crews share ALL the blocks' repairs (omit = as many as needed). With "
        "fewer crews than repair jobs, a failed block can wait; order by each block's crew_priority."))] = None,
    maintenance_groups: Annotated[Optional[dict[str, MaintenanceGroup]], Field(description=(
        "Repairable only: options per maintenance group named by blocks' maintenance_group, e.g. "
        "{\"north pumps\": {\"setup_cost\": 2000}}."))] = None,
    safety_function: Annotated[bool, Field(description=(
        "Repairable only: the diagram is a (low-demand) safety function — analyze_rbd reports its PFDavg, "
        "with common cause, and its SIL band."))] = False,
    target_sil: Annotated[Optional[int], Field(ge=1, le=4, description="With safety_function: the SIL it must meet."
                                               )] = None,
) -> dict[str, Any]:
    """Build, validate and save a reliability block diagram to the user's workspace. Layout is automatic.

    Give EITHER the graph form (nodes + edges) or the simple stages form.
    Graph form: exactly one {id:"input", type:"input"} and one {id:"output", type:"output"} node; flow runs
    input -> blocks -> output. For two parallel blocks, fan out from the upstream node to each and from each
    to the downstream node. Example — controller in series with two redundant pumps: nodes input, ctl
    (component), p1, p2 (components), output; edges input->ctl, ctl->p1, ctl->p2, p1->output, p2->output.
    "2 of 3 pumps": three component nodes each feeding one knode with n=2, k=3.

    STRUCTURE RULES — a wrong structure is worse than a missing number:
    - Pure series is ONLY for items that must ALL work. Never wire a whole equipment list in series by default.
    - Redundancy MUST be modelled as redundancy: items named A/B, 1/2, duplex, dual, twin, x2, standby, spare,
      backup, redundant, 2 of 3, N+1 go in PARALLEL (or a standby node when the spare sits idle, or a knode for
      k-of-n voting). Wiring "Actuator A" -> "Actuator B" in series is always wrong.
    - State your structural assumptions to the user; if genuinely unclear, ask one question first.
    PLACEHOLDERS — never silently invent failure data: ask for rough MTBFs (or saved models) per class of
    block. Only if the user wants a starting point, use values that differ by block class, set
    placeholder=true on EVERY guessed model, and tell the user the numbers are placeholders.
    Repairable diagrams: every block needs `repair` (graph form) or repair_distribution + repair_params
    (stages form), e.g. a lognormal time to repair. Blocks may carry costs, preventive (age/block/condition-
    based replacement), inspection (hidden failures with proof tests: staggered via offset, imperfect via
    coverage + full_test), maintenance_group and crew_priority; the diagram repair_crews, maintenance_groups,
    safety_function and target_sil. Common-cause groups (edit_rbd add_ccf) enter a safety function's PFDavg.
    Returns the node ids (the stages form generates them); change the diagram later with edit_rbd."""
    user, db = _caller(ctx), _db()
    uid = user["uid"]
    owners = _owners(uid)
    if (nodes is None) == (stages is None):
        raise ToolError("Give either nodes + edges (graph form) or stages (simple form) — exactly one.")
    if stages is not None and edges:
        raise ToolError("edges belong to the graph form (nodes + edges); the stages form is wired automatically. "
                        "Give exactly one form.")
    settings = _diagram_settings(repair_crews, maintenance_groups, safety_function, target_sil)
    if settings and not repairable:
        raise ToolError(f"{', '.join(settings)} apply to repairable diagrams only — set repairable=true.")
    if stages is not None:
        graph = _stage_graph(db, uid, stages, repairable)
        graph["unit"] = unit
        graph.update(settings)
    else:
        graph = rbd_graph.normalize_graph(
            {"nodes": [n.model_dump(exclude_none=True) for n in nodes],
             "edges": [e.model_dump() for e in edges or []],
             "unit": unit, "repairable": repairable, **settings},
            resolve_saved_model=lambda mid: models_service.get_model(db, mid, owners),
        )
    check = rbds_service.validate_graph(db, graph, owners)
    if not check.get("valid", False):
        raise ToolError("Invalid RBD structure: " + "; ".join(check.get("errors") or ["unknown problem"]))
    _cap(db, user, "rbds", "RBDs")
    rbd = rbds_service.save_rbd(db, name.strip(), graph, uid)
    return {**_rbd_brief(rbd), "analytic": check.get("analytic", True), **_rbd_outline(graph, check, include_graph)}


def _diagram_settings(repair_crews, maintenance_groups, safety_function, target_sil) -> dict:
    """create_rbd's repairable-diagram settings (#156, #157) as graph keys,
    only those given."""
    out: dict[str, Any] = {}
    if repair_crews:
        out["repair_crews"] = {"crews": int(repair_crews)}
    if maintenance_groups:
        out["maintenance_groups"] = {name: g.model_dump(exclude_none=True)
                                     for name, g in maintenance_groups.items()}
    if safety_function:
        out["safety_function"] = True
    if target_sil:
        if not safety_function:
            raise ToolError("target_sil applies to a safety function — set safety_function=true too.")
        out["target_sil"] = int(target_sil)
    return out


def _rbd_outline(graph: dict, check: dict, include_graph: bool) -> dict:
    """What a write tool returns about a diagram: validation warnings,
    placeholders and a concise node list ({id, type, label}) — the full
    compact graph only on request (get_rbd reads it any time)."""
    out = {
        "warnings": check.get("warnings") or [],
        "placeholders": rbd_graph.placeholder_labels(graph),
        "nodes": [{"id": n.get("id"), "type": n.get("type"), "label": (n.get("data") or {}).get("label")}
                  for n in graph.get("nodes") or []],
    }
    if include_graph:
        out["graph"] = rbd_graph.compact_graph(graph)
    return out


# ---- token-efficient editing --------------------------------------------------
#
# edit_rbd changes a saved diagram with a batch of small ops instead of a whole
# new graph, so an agent never re-sends (or re-reads) a diagram to change one
# block. One tool with a discriminated union of ops, not one tool per op: every
# tool schema sits in the agent's context on every turn.

def _lean_schema(schema: dict) -> None:
    """Drop the auto-generated titles and null defaults from an op's JSON
    schema: they carry nothing for the agent but sit in its context."""
    for prop in (schema.get("properties") or {}).values():
        prop.pop("title", None)
        if "default" in prop and prop["default"] is None:
            del prop["default"]


class _Op(BaseModel):
    model_config = ConfigDict(extra="forbid", json_schema_extra=_lean_schema)


class AddNodeOp(_Op):
    op: Literal["add_node"]
    node: RbdNode = Field(description="The new block (compact node, as create_rbd). Its id must be new.")
    between: Optional[list[str]] = Field(None, min_length=2, max_length=2, description=(
        "[source, target]: splice into that existing edge (source -> new -> target)."))
    after: Optional[str] = Field(None, description="In series right after this node (takes over its outgoing edges).")
    before: Optional[str] = Field(None, description="In series right before this node (takes over its incoming edges).")
    parallel_to: Optional[str] = Field(None, description="In parallel with this block (copies its incoming and "
                                                         "outgoing edges).")


class RemoveNodeOp(_Op):
    op: Literal["remove_node"]
    id: str
    reconnect: Literal["auto", "none"] = Field("auto", description=(
        "auto = rejoin neighbours the removal disconnects (a series gap closes; removing one of parallel blocks "
        "adds nothing). none = just drop it and its edges."))


class UpdateNodeOp(_Op):
    op: Literal["update_node"]
    id: Optional[str] = None
    ids: Optional[list[str]] = Field(None, min_length=1, description="Apply the same change to several nodes.")
    label: Optional[str] = None
    model: Optional[BlockModel] = None
    repair: Optional[BlockModel] = None
    n: Optional[int] = None
    k: Optional[int] = None
    spares: Optional[int] = None
    cold: Optional[bool] = None
    subsystem_rbd_id: Optional[str] = None
    instant_repair: Optional[bool] = None
    costs: Optional[BlockCosts] = Field(None, description="Replaces the block's costs.")
    preventive: Optional[Preventive] = Field(None, description="Replaces the schedule (drops inspection).")
    inspection: Optional[ProofTest] = Field(None, description="Replaces the proof tests (drops preventive).")
    maintenance_group: Optional[str] = None
    crew_priority: Optional[float] = None
    repair_one_at_a_time: Optional[bool] = None
    clear: Optional[list[Literal["costs", "preventive", "inspection", "maintenance_group", "crew_priority",
                                 "instant_repair", "repair_one_at_a_time"]]] = Field(
        None, description="Remove these block settings.")


class EdgeOp(_Op):
    op: Literal["add_edge", "remove_edge"]
    source: str
    target: str


class SetOp(_Op):
    op: Literal["set"]
    name: Optional[str] = None
    unit: Optional[str] = Field(None, description="Relabels the unit; parameters are not rescaled.")
    repairable: Optional[bool] = None
    repair_crews: Optional[int] = Field(None, ge=0, description="Repair crews shared by all blocks; 0 = as many "
                                                                 "as needed.")
    maintenance_groups: Optional[dict[str, MaintenanceGroup]] = Field(None, description=(
        "Replaces the maintenance groups' options ({} clears them)."))
    safety_function: Optional[bool] = None
    target_sil: Optional[int] = Field(None, ge=0, le=4, description="0 clears it.")


class AddCcfOp(_Op):
    op: Literal["add_ccf"]
    members: list[str] = Field(min_length=2, description="2+ component block ids not already in a group.")
    beta: float = Field(description="Beta factor: shared-cause fraction of each member's failures, 0 < beta < 1.")
    id: Optional[str] = Field(None, description="Group id (default ccf-1, ccf-2, …).")


class RemoveCcfOp(_Op):
    op: Literal["remove_ccf"]
    id: str


EditOp = Annotated[Union[AddNodeOp, RemoveNodeOp, UpdateNodeOp, EdgeOp, SetOp, AddCcfOp, RemoveCcfOp],
                   Field(discriminator="op")]


def _op_dict(op: BaseModel) -> dict:
    """An op as the plain dict rbd_edit applies: only the fields the caller
    gave (update_node merges exactly those), nested models dumped."""
    out = {"op": op.op}
    for key in op.model_fields_set:
        value = getattr(op, key)
        if value is None:
            continue
        if isinstance(value, BaseModel):
            value = value.model_dump(exclude_none=True)
        elif isinstance(value, dict):
            value = {k: v.model_dump(exclude_none=True) if isinstance(v, BaseModel) else v
                     for k, v in value.items()}
        out[key] = value
    return out


def _resolver(db, owners):
    return lambda mid: models_service.get_model(db, mid, owners)


def _check_rbd(db, graph: dict, owners: list[str], lead: str) -> dict:
    check = rbds_service.validate_graph(db, graph, owners)
    if not check.get("valid", False):
        raise ToolError(lead + "; ".join(check.get("errors") or ["unknown problem"]))
    return check


@_tool("clone_rbd", _WRITE, "Copy an RBD")
def clone_rbd(
    ctx: Context,
    rbd_id: Annotated[str, Field(description="One of the user's RBDs or a shared sample (list_rbds).")],
    name: Annotated[Optional[str], Field(description="Name for the copy (default: “<name> (copy)”).")] = None,
) -> dict[str, Any]:
    """Copy a diagram — a shared sample or one of the user's own — into the user's workspace under a new id,
    to edit with edit_rbd (samples are read-only). Copies the diagram only: not saved availability results or
    share links. Returns the new id and its node ids."""
    user, db = _caller(ctx), _db()
    uid = user["uid"]
    owners = _owners(uid)
    src = _get_rbd(db, uid, rbd_id)
    new_name = (name or "").strip() or f"{src.name} (copy)"
    graph = copy.deepcopy(src.graph or {})
    check = rbds_service.validate_graph(db, graph, owners)
    _cap(db, user, "rbds", "RBDs")
    rbd = rbds_service.save_rbd(db, new_name, graph, uid)
    out = {**_rbd_brief(rbd), "cloned_from": src.id, **_rbd_outline(graph, check, False)}
    if not check.get("valid", False):
        # A draft saved unvalidated in the app copies as it is; say what to fix.
        out["errors"] = check.get("errors") or []
    return out


@_tool("edit_rbd", _WRITE, "Edit an RBD")
def edit_rbd(
    ctx: Context,
    rbd_id: Annotated[str, Field(description="One of the user's own RBD ids (clone_rbd a sample first).")],
    ops: Annotated[list[EditOp], Field(min_length=1, max_length=rbd_edit.MAX_OPS, description=(
        "Applied in order, all or nothing."))],
    if_updated_at: Annotated[Optional[str], Field(description=(
        "The updated_at you last saw: refuse if the diagram changed since (e.g. edited in the app)."))] = None,
    dry_run: Annotated[bool, Field(description="Validate and report without saving.")] = False,
    include_graph: Annotated[bool, Field(description="Also return the full compact graph.")] = False,
) -> dict[str, Any]:
    """Change a saved RBD with a batch of ops instead of re-creating it. Atomic: if any op fails, or the result
    isn't a valid diagram, nothing is saved and the error names the op (ops[i], 0-based) and why.

    Ops (field `op`):
    - add_node {node, between: [src, tgt] | after: id | before: id | parallel_to: id} — at most one placement;
      none leaves it unconnected for add_edge. node is a compact node as in create_rbd.
    - remove_node {id, reconnect: auto|none} — auto rejoins a series gap; removing one of two parallel
      blocks adds no bypass. Every edge added is reported. Input/output can't be removed.
    - update_node {id | ids, label?, model?, repair?, n?, k?, spares?, cold?, subsystem_rbd_id?,
      instant_repair?, costs?, preventive?, inspection?, maintenance_group?, crew_priority?,
      repair_one_at_a_time?, clear?: [field…]} — merges only the fields given (ids: same change to many
      nodes); clear removes block settings. A node's type can't change: remove and re-add.
    - add_edge / remove_edge {source, target}
    - set {name?, unit?, repairable?, repair_crews? (0 = as many as needed), maintenance_groups?,
      safety_function?, target_sil? (0 clears)}
    - add_ccf {members, beta, id?} / remove_ccf {id} — common-cause (beta-factor) groups; in a repairable
      diagram they enter a safety function's PFDavg.
    Removing a node drops it from its common-cause group (and the group if under 2 members remain).
    Changing connections re-lays out the diagram automatically. Returns one line per op, the validation
    warnings this edit introduced (warnings_unchanged counts the rest) and the node ids; read the full graph
    with get_rbd."""
    user, db = _caller(ctx), _db()
    uid = user["uid"]
    owners = _owners(uid)
    rbd = _get_rbd(db, uid, rbd_id)
    if samples_service.is_sample(rbd.owner_id) or rbd.owner_id != uid:
        raise ToolError(f"“{rbd.name}” is a shared sample: samples are read-only — clone_rbd it first, then "
                        "edit the copy.")
    if if_updated_at and not access_service.timestamps_match(rbd.updated_at, if_updated_at):
        raise ToolError(f"“{rbd.name}” has changed since {if_updated_at} (now updated_at "
                        f"{rbd.updated_at.isoformat()}), e.g. edited in the app. Nothing was saved: re-read it with "
                        "get_rbd and retry with the new updated_at.")
    try:
        result = rbd_edit.apply_ops(rbd.graph or {}, [_op_dict(op) for op in ops], rbd.name,
                                    resolve_saved_model=_resolver(db, owners), self_id=rbd.id)
    except rbd_edit.EditError as exc:
        raise ToolError(f"Nothing was saved — {exc}") from None
    graph = result.graph
    check = _check_rbd(db, graph, owners, f"Nothing was saved — after all {len(ops)} op(s) the diagram is "
                                          "invalid: ")
    out_rbd = rbd
    if not dry_run:
        try:
            out_rbd = rbds_service.save_rbd(db, result.name, graph, uid, rbd_id=rbd.id,
                                            expected_updated_at=rbd.updated_at.isoformat())
        except access_service.EditConflict:
            raise ToolError(f"“{rbd.name}” was saved by someone else while this edit ran. Nothing was saved: "
                            "re-read it with get_rbd and retry.") from None
    else:
        out_rbd = rbd.model_copy(update={"name": result.name, "graph": graph})
    out = {**_rbd_brief(out_rbd)}
    if dry_run:
        out["dry_run"] = True
        out["saved"] = False
    out["applied"] = result.applied
    out.update(_rbd_outline(graph, check, include_graph))
    # Only the warnings this edit introduced: the rest were reported when the
    # diagram was created, cloned or last edited, and repeating them on every
    # small edit would cost more tokens than the edit itself.
    try:
        known = set(rbds_service.validate_graph(db, rbd.graph or {}, owners).get("warnings") or [])
    except Exception:  # pragma: no cover - a malformed saved draft: report everything
        known = set()
    unchanged = [w for w in out["warnings"] if w in known]
    if unchanged:
        out["warnings"] = [w for w in out["warnings"] if w not in known]
        out["warnings_unchanged"] = len(unchanged)
    return out


def _downsample(xs, ys, n: int = 21) -> list[dict]:
    if not xs:
        return []
    idx = sorted({round(i * (len(xs) - 1) / (n - 1)) for i in range(n)})
    return [{"t": _finite(xs[i]), "reliability": _finite(ys[i])} for i in idx]


def _labelled(values: dict, labels: dict) -> dict:
    return {labels.get(k, k): v for k, v in (values or {}).items()}


def _reliability_summary(result: dict, graph: dict, times: list[float] | None) -> dict:
    t = result.get("time") or []
    sf = (result.get("system") or {}).get("sf") or []
    labels = {n.get("id"): (n.get("data") or {}).get("label") or n.get("id") for n in graph.get("nodes") or []}
    importance = result.get("importance") or {}
    out = {
        "kind": "non_repairable",
        "unit": result.get("unit", ""),
        "mttf": result.get("mttf"),
        "b_life": result.get("blife"),
        "curve": _downsample(t, sf),
        "importance": {
            **({"time": importance["time"]} if "time" in importance else {}),
            **{k: _labelled(v, labels) for k, v in importance.items() if isinstance(v, dict)},
        },
        "structure": result.get("structure"),
    }
    if times and result.get("at"):
        # Evaluated exactly at each time by the analysis (not read off the curve).
        at = result["at"]
        out["reliability_at"] = [{"t": x, "reliability": _finite(y)} for x, y in zip(at["t"], at["sf"])]
    if result.get("conditional_age"):
        out["conditional_age"] = result["conditional_age"]
    if result.get("ccf"):
        out["ccf"] = result["ccf"]
    return out


_EXACT_KEYS = ("status", "message", "from", "current_state", "window", "unit", "availability_start",
               "availability_end", "availability_min", "availability_min_at", "mission_availability",
               "expected_failures", "planned_outages", "expected_outages", "downtime", "cost", "cost_note",
               "method", "n_blocks", "cached")


def _exact_summary(exact: dict | None) -> dict | None:
    """The exact block for an agent: the figures and their methods, the A(t)
    curve at 21 points, the blocks with the most expected downtime, and each
    analysis's route (exact / numerical / simulated / refused) and why."""
    if not exact:
        return None
    out = {k: exact[k] for k in _EXACT_KEYS if k in exact}
    curve = exact.get("curve") or {}
    if curve.get("t"):
        out["curve"] = [{"t": p["t"], "availability": p["reliability"]}
                        for p in _downsample(curve["t"], curve.get("availability") or [])]
    if exact.get("per_node"):
        out["blocks_by_downtime"] = exact["per_node"][:10]
    if exact.get("routes"):
        out["routes"] = {k: {"route": r.get("route"), "reason": r.get("reason")}
                         for k, r in exact["routes"].items()}
    return out


def _availability_summary(result: dict) -> dict:
    keys = ("unit", "steady_state_availability", "unavailability", "mean_up_time", "mean_down_time",
            "failure_frequency", "figures_basis", "has_simulation", "n_simulations", "t_simulation", "precision",
            "per_node", "importance", "criticality", "cached", "computed_at", "can_recompute", "current_state",
            # How the long-run values were found, the repair crews, a safety
            # function's PFDavg and SIL band (#156, #157).
            "long_run_method", "repair_crews", "safety", "opportunistic_renewals")
    out = {"kind": "repairable", **{k: result.get(k) for k in keys if k in result}}
    if not result.get("has_simulation", True):
        # The simulation's own figures aren't there: don't list empty ones.
        for k in ("n_simulations", "precision", "per_node", "criticality", "cached", "computed_at"):
            out.pop(k, None)
    out["exact"] = _exact_summary(result.get("exact"))
    return out


class BlockState(BaseModel):
    down: Optional[bool] = Field(None, description="True: the block is down now (in a repair).")
    since: Optional[float] = Field(None, ge=0, description=(
        "With down: how long it has been down so far (diagram unit; 0 = just failed)."))
    age: Optional[float] = Field(None, ge=0, description=(
        "A running block: time since it was new or last renewed (diagram unit)."))


@_tool("analyze_rbd", _READ, "Analyse an RBD")
def analyze_rbd(
    ctx: Context,
    rbd_id: Annotated[str, Field(description="An RBD id from list_rbds or create_rbd.")],
    times: Annotated[Optional[list[float]], Field(max_length=200, description=(
        "Non-repairable: times (diagram unit) to report system reliability at."))] = None,
    t_max: Annotated[Optional[float], Field(description=(
        "Non-repairable: end of the time axis (default sized to the system). Repairable: the simulated "
        "horizon."))] = None,
    conditional_age: Annotated[Optional[float], Field(description=(
        "Non-repairable: condition on the system having already survived to this age."))] = None,
    recompute: Annotated[bool, Field(description=(
        "Repairable: re-run the simulation even when a saved result matches (paid feature)."))] = False,
    simulate: Annotated[bool, Field(description=(
        "Repairable: also run the Monte-Carlo simulation (paid: Pro or credits) for distributions, "
        "P(no outage), percentiles and criticality. False = the exact figures only (faster). Ignored "
        "without entitlement: the exact figures come anyway."))] = True,
    current_state: Annotated[Optional[dict[str, BlockState]], Field(description=(
        "Repairable: blocks' states now, keyed by node id — {down: true, since: <time into the repair>} or "
        "{age: <time since new>}; blocks left out are new. The figures then run from now over t_max "
        "(e.g. the next 720 hours). Never replaces the saved from-new result."))] = None,
    compute_exact: Annotated[bool, Field(description=(
        f"Repairable diagrams over {rbd_analysis.EXACT_AUTO_MAX_BLOCKS} blocks: compute the exact figures "
        "over time anyway (from several seconds to a minute or so)."))] = False,
) -> dict[str, Any]:
    """Analyse a saved RBD. Non-repairable diagrams: system reliability curve, MTTF, B-lives (B10/B50),
    component importance (Birnbaum, Fussell–Vesely, RAW/RRW) and minimal cut/path sets. Repairable
    diagrams, on every plan: the exact long-run availability, mean up/down time and failure frequency, how
    the long-run values were found (long_run_method: exact / numerical / simulated, e.g. the repair crews'
    Markov chain), the repair crews, for a safety function its PFDavg and SIL band (safety), and (in
    `exact`) the availability over time A(t), mission availability and the window's expected system
    failures, outages, downtime and cost — each with its method (exact / numerical; no simulation) — from
    new or from current_state. The Monte-Carlo simulation (distributions, criticality) is a paid feature
    (Pro or purchased credits): a saved result is always served; otherwise, without entitlement, the
    response carries `simulation: {available: false, message}` — relay it, and offer export_rbd_python to
    run the simulation locally. A diagram whose figures are simulation-only (exact.status
    'simulation_only', e.g. proof tests that take time) returns available=false without entitlement."""
    from backend.routers.rbds import availability_payload
    from backend.services.access import PERSONAL, AccessCtx

    user, db = _caller(ctx), _db()
    uid = user["uid"]
    rbd = _get_rbd(db, uid, rbd_id)
    graph = rbd.graph or {}
    owners = [*_owners(uid), rbd.owner_id]
    if t_max is not None and (not np.isfinite(t_max) or t_max <= 0):
        raise ToolError(f"t_max must be a positive time in the diagram's unit; got {t_max:g}. Omit it for the "
                        "automatic axis.")
    for t in times or []:
        if not np.isfinite(t) or t < 0:
            raise ToolError(f"times must be finite and ≥ 0 (in the diagram's unit); got {t:g}.")
    if conditional_age is not None and (not np.isfinite(conditional_age) or conditional_age < 0):
        raise ToolError(f"conditional_age must be finite and ≥ 0; got {conditional_age:g}.")
    if graph.get("repairable") and (times or conditional_age is not None):
        raise ToolError("times and conditional_age apply to non-repairable diagrams; this one is repairable "
                        "(analysed for availability). Drop them — t_max sets the window (and the simulated "
                        "horizon); current_state starts it from now.")
    if current_state and not graph.get("repairable"):
        raise ToolError("current_state applies to repairable (availability) diagrams; for a non-repairable one "
                        "use conditional_age.")
    placeholders = rbd_graph.placeholder_labels(graph)
    head = {"rbd_id": rbd.id, "name": rbd.name, "url": _url(f"/rbds/b/{rbd.id}")}
    if placeholders:
        head["placeholders"] = placeholders
        head["warning"] = "Some blocks use placeholder (guessed) models — results are illustrative until replaced."
    # Modelling warnings the analysis can't catch (e.g. a saved model fitted in
    # another time unit) — the same ones create_rbd and the app's Validate show.
    design = rbd_analysis.design_warnings(graph)
    if design:
        head["warnings"] = design

    try:
        if graph.get("repairable"):
            actx = AccessCtx(user=user, uid=uid, workspace=PERSONAL, write_owner=uid,
                             read_owners=_owners(uid), list_owners=uid)
            state = ({nid: v.model_dump(exclude_none=True) for nid, v in current_state.items()}
                     if current_state else None)
            plan = user.get("mcp_plan", "pro")
            status, payload = availability_payload(db, actx, graph, t_max, rbd, recompute, owners,
                                                   simulate=simulate or recompute, current_state=state,
                                                   exact=compute_exact)
            if status != 200:
                # A simulation-only diagram, without entitlement: nothing to give.
                if plan != "pro":
                    _soft_refusal("pro_only")
                message = _simulation_message(plan) if plan != "pro" else payload.get("detail")
                return {**head, "kind": "repairable", "available": False, "code": payload.get("code"),
                        "message": message}
            out = {**head, "available": True, **_availability_summary(payload)}
            sim_state = (payload.get("simulation_status") or {}).get("state")
            if sim_state == "pro_required" and (simulate or recompute):
                out["simulation"] = {
                    "available": False, "code": "pro_required",
                    "message": (_simulation_message(plan) if plan != "pro"
                                else (payload.get("simulation_status") or {}).get("message")),
                }
            else:
                out["simulation"] = {"available": bool(payload.get("has_simulation")), "state": sim_state}
            return out

        result = rbds_service.analyze_graph(db, graph, owners, t_max=t_max, conditional_age=conditional_age,
                                            at_times=times)
        return {**head, "available": True, **_reliability_summary(result, graph, times)}
    except (ToolError, *_USER_ERRORS, models_service.ModelNotFound, fitting.ModelNotFound,
            rbds_service.RbdNotFound):
        raise
    except Exception as exc:
        # Never a bare "Error executing tool" (e.g. an IndexError from a
        # malformed saved diagram): say what failed and what to check.
        logger.exception("analyze_rbd failed for %s", rbd.id)
        raise ToolError(f"Reliafy couldn't analyse “{rbd.name}” ({type(exc).__name__}). Check its structure "
                        "with get_rbd: exactly one input and one output node, every block on a path between "
                        "them, and a life model on every block.") from exc


@_tool("export_rbd_python", _READ, "Export an RBD as Python")
def export_rbd_python(
    ctx: Context,
    rbd_id: Annotated[str, Field(description="An RBD id from list_rbds.")],
) -> dict[str, Any]:
    """Export a saved RBD as a standalone Python script (SurPyval + RePyability) that rebuilds and
    analyses the same diagram offline. Returns the filename and the script text."""
    user, db = _caller(ctx), _db()
    rbd = _get_rbd(db, user["uid"], rbd_id)
    filename, source = rbds_service.export_python(db, rbd.name, rbd.graph or {}, [*_owners(user["uid"]), rbd.owner_id])
    # The same pinned installs the script's own header lists (git tags, and
    # RePyability with --no-deps) — PyPI's releases lag behind.
    return {"filename": filename, "script": source, "run": rbd_export.run_command(filename)}


# ---------------------------------------------------------------------------
# Strategy calculators
# ---------------------------------------------------------------------------

def _dist_inputs(db, uid: str, model_id: str | None, distribution_id: str | None,
                 params: list[Param] | None, unit: str | None) -> dict:
    """distribution_id + params, given inline or taken from a saved plain life model."""
    if model_id and (distribution_id or params):
        raise ToolError("Give exactly one of model_id or distribution_id + params, not both.")
    if model_id:
        m = models_service.get_model(db, model_id, _owners(uid))
        if m is None:
            raise ToolError("Model not found.")
        if m.kind != "distribution":
            raise ToolError(f"“{m.name}” is a {m.kind} model — the calculators need a plain life distribution.")
        r = m.results or {}
        return {"distribution_id": r.get("distribution_id") or m.distribution_id, "params": _plain_params(r),
                "unit": unit or r.get("unit") or ""}
    if not distribution_id or not params:
        raise ToolError("Give a model_id, or distribution_id + params.")
    # Params are checked by SurPyval name in the strategy service (an
    # unrecognised name is refused, never read by position).
    return {"distribution_id": fitting.resolve_distribution_id(distribution_id),
            "params": [p.model_dump() for p in params], "unit": unit or ""}


_MODEL_ID = Annotated[Optional[str], Field(description="A saved life model id (list_models). Give this OR "
                                                        "distribution_id + params.")]
_DIST_ID = Annotated[Optional[str], Field(description="Inline distribution id, e.g. weibull.")]
_PARAMS = Annotated[Optional[list[Param]], Field(description="Inline params, e.g. [{name: alpha, value: 1200}, "
                                                             "{name: beta, value: 2.1}].")]
_UNIT = Annotated[Optional[str], Field(description="Time unit for the answer, e.g. hours.")]
_INCLUDE_CURVE = Annotated[bool, Field(description="Also return the ~200-point cost-rate curve (for plotting). "
                                                   "Off by default to keep the answer small.")]


def _maybe_curve(result: dict, include: bool) -> dict:
    """Drop a calculator's plotting curve unless asked for (the app keeps it)."""
    if include or "curve" not in result:
        return result
    return {**{k: v for k, v in result.items() if k != "curve"},
            "curve_omitted": "Pass include_curve=true for the cost-rate curve."}


@_tool("optimal_replacement", _READ, "Optimal replacement interval")
def optimal_replacement(
    ctx: Context,
    planned_cost: Annotated[float, Field(gt=0, description="Cost of a planned (preventive) replacement.")],
    unplanned_cost: Annotated[float, Field(gt=0, description="Cost of an unplanned (failure) replacement.")],
    model_id: _MODEL_ID = None,
    distribution_id: _DIST_ID = None,
    params: _PARAMS = None,
    unit: _UNIT = None,
    include_curve: _INCLUDE_CURVE = False,
) -> dict[str, Any]:
    """Cost-optimal preventive (age) replacement interval for a component with a known life distribution.
    beneficial=false means run-to-failure is cheaper (e.g. no wear-out, or planned ≈ unplanned cost)."""
    user, db = _caller(ctx), _db()
    inputs = _dist_inputs(db, user["uid"], model_id, distribution_id, params, unit)
    out = strategy_store.compute("optimal_replacement", {
        **inputs, "planned_cost": planned_cost, "unplanned_cost": unplanned_cost})
    return _maybe_curve(out, include_curve)


@_tool("failure_finding_interval", _READ, "Failure-finding interval")
def failure_finding_interval(
    ctx: Context,
    target_availability: Annotated[float, Field(gt=0, lt=1, description="Required availability of the hidden "
                                                                        "function, e.g. 0.99.")],
    model_id: _MODEL_ID = None,
    distribution_id: _DIST_ID = None,
    params: _PARAMS = None,
    unit: _UNIT = None,
) -> dict[str, Any]:
    """Inspection (proof-test) interval that keeps a hidden, protective function — a relief valve,
    trip, alarm, standby unit — at the target availability."""
    user, db = _caller(ctx), _db()
    inputs = _dist_inputs(db, user["uid"], model_id, distribution_id, params, unit)
    return strategy_store.compute("failure_finding", {**inputs, "target_availability": target_availability})


def _lean_demonstration(out: dict) -> dict:
    """The demonstration plan without the app's plotting fields: the trade-off
    table as {row label: values by allowed failures}."""
    keep = ("method", "solve_for", "summary", "units", "test_time_per_unit", "total_test_time",
            "test_multiple", "failures", "unit", "consumer_risk", "pass_probability", "assumptions")
    lean = {k: out[k] for k in keep if out.get(k) is not None}
    t = out.get("tradeoff") or {}
    lean["tradeoff"] = {
        "cells": t.get("value_label"),
        "columns": f"allowed failures {', '.join(str(f) for f in t.get('failures', []))}",
        "rows": {row["label"]: [None if v is None else (v if isinstance(v, int) else float(f"{v:.4g}"))
                                for v in row["values"]] for row in t.get("rows", [])},
    }
    return lean


@_tool("plan_demonstration_test", _READ, "Plan a demonstration test")
def plan_demonstration_test(
    ctx: Context,
    reliability: Annotated[Optional[float], Field(gt=0, lt=1, description="Reliability to demonstrate over one "
                                                                         "mission, e.g. 0.95. Needed unless "
                                                                         "method='mtbf'.")] = None,
    confidence: Annotated[float, Field(gt=0, lt=1, description="Confidence level, e.g. 0.9 or 0.95.")] = 0.95,
    mission_time: Annotated[Optional[float], Field(gt=0, description="The mission (time, cycles) the "
                                                                     "reliability is over, e.g. 1000. Optional: "
                                                                     "without it the plan is in missions.")] = None,
    failures: Annotated[int, Field(ge=0, le=100, description="Failures the test may allow and still pass "
                                                             "(0 = success run).")] = 0,
    test_multiple: Annotated[float, Field(gt=0, le=100, description="Test each unit for this many missions "
                                                                     "(needs shape when not 1): test longer, "
                                                                     "fewer units.")] = 1.0,
    shape: Annotated[Optional[float], Field(gt=0, le=20, description="Weibull shape (beta) of the lifetime, "
                                                                     "assumed known — needed for test_multiple "
                                                                     "!= 1 or units.")] = None,
    units: Annotated[Optional[int], Field(ge=1, description="Units available: solve for the test time per unit "
                                                            "instead of the unit count (needs shape).")] = None,
    method: Annotated[Literal["attribute", "mtbf"], Field(description="'attribute' (binomial pass/fail, the "
                                                                      "default) or 'mtbf' (constant failure "
                                                                      "rate, total test time, chi-squared).")]
    = "attribute",
    mtbf: Annotated[Optional[float], Field(gt=0, description="MTBF to demonstrate (method='mtbf').")] = None,
    design_reliability: Annotated[Optional[float], Field(gt=0, lt=1, description="Optional: a design's true "
                                                                                 "reliability, to report its "
                                                                                 "chance of passing.")] = None,
    unit: _UNIT = None,
) -> dict[str, Any]:
    """Plan a reliability demonstration test: how many units to test, for how long, with how many failures
    allowed, to show reliability R over a mission at confidence C (success run / binomial; Weibayes with a
    known Weibull shape to trade test time for units; or an MTBF chi-squared test). Returns a one-line plan,
    the assumptions and a units-vs-failures(-vs-test-length) trade-off table."""
    _caller(ctx)
    out = strategy_store.compute("demonstration_test", {
        "method": method, "reliability": reliability, "confidence": confidence, "mission_time": mission_time,
        "failures": failures, "test_multiple": test_multiple, "shape": shape, "units": units, "mtbf": mtbf,
        "design_reliability": design_reliability, "unit": unit or ""})
    return _lean_demonstration(out)


@_tool("optimal_overhaul", _READ, "Optimal overhaul interval")
def optimal_overhaul(
    ctx: Context,
    model_id: Annotated[str, Field(description="A saved RECURRENT model id (list_models kind=recurrent).")],
    cost_repair: Annotated[float, Field(gt=0, description="Cost of one minimal repair (fix a failure, "
                                                          "'as bad as old').")],
    cost_overhaul: Annotated[float, Field(gt=0, description="Cost of an overhaul that restores the system to "
                                                            "'as good as new'. Must exceed cost_repair.")],
    t_max: Annotated[Optional[float], Field(description="Optional upper limit of the interval search.")] = None,
    include_curve: _INCLUDE_CURVE = False,
) -> dict[str, Any]:
    """Optimal overhaul interval for a repairable system (minimal repair between overhauls) from a saved
    recurrent-event model. Only a deteriorating system (growth shape beta > 1) has a finite optimum."""
    user, db = _caller(ctx), _db()
    owners = _owners(user["uid"])
    if t_max is not None and (not np.isfinite(t_max) or t_max <= 0):
        raise ToolError(f"t_max must be a positive time; got {t_max:g}. Omit it to search automatically.")
    if recurrent_service.get_model(db, model_id, owners) is None:
        raise ToolError("Recurrent model not found — optimal_overhaul needs a recurrent (repairable-system) "
                        "model id from list_models kind=recurrent.")
    live = recurrent_service.get_live_model(db, model_id, owners)
    return _maybe_curve(recurrent_fit.optimal_overhaul(live, cost_repair, cost_overhaul, t_max=t_max), include_curve)


# ---------------------------------------------------------------------------
# Fleets
# ---------------------------------------------------------------------------

@_tool("list_fleets", _READ, "List fleet forecasts")
def list_fleets(ctx: Context) -> dict[str, Any]:
    """List the user's fleet failure forecasts (in-service items run against one saved life model).
    Reliafy Pro only."""
    user, db = _caller(ctx), _db()
    return {"fleets": [
        {"id": f.id, "name": f.name, "model_id": f.model_id, "n_items": len(f.items or []),
         "settings": f.settings, "is_sample": samples_service.is_sample(f.owner_id),
         "url": _url(f"/fleet/forecasts/{f.id}")}
        for f in fleet_service.list_fleets(db, _owners(user["uid"]))
    ]}


_TOP_ITEMS = 20  # fleet_forecast lists this many items unless asked for all


@_tool("fleet_forecast", _READ, "Fleet failure forecast")
def fleet_forecast(
    ctx: Context,
    fleet_id: Annotated[str, Field(description="A fleet id from list_fleets.")],
    include_items: Annotated[bool, Field(description=(
        f"Return every item's forecast (up to 500). By default only the {_TOP_ITEMS} items with the most "
        "expected failures are listed."))] = False,
) -> dict[str, Any]:
    """The live failure forecast for a fleet: expected failures over the horizon with a P10–P90 range,
    plus per-period and per-item breakdowns (the top items by default)."""
    user, db = _caller(ctx), _db()
    owners = _owners(user["uid"])
    fleet = fleet_service.get_fleet(db, fleet_id, owners)
    if fleet is None:
        raise ToolError("Fleet not found.")
    forecast = fleet_service.compute(db, fleet, [*owners, fleet.owner_id])
    items = forecast.get("per_item") or []
    if not include_items and len(items) > _TOP_ITEMS:
        top = sorted(items, key=lambda r: -(r.get("expected") or 0.0))[:_TOP_ITEMS]
        forecast = {**forecast, "per_item": top,
                    "per_item_note": f"Top {_TOP_ITEMS} of {len(items)} items by expected failures; pass "
                                     "include_items=true for all of them."}
    return {"fleet": {"id": fleet.id, "name": fleet.name, "model_id": fleet.model_id,
                      "url": _url(f"/fleet/forecasts/{fleet.id}")},
            "headline": fleet_service.headline(fleet, forecast), "forecast": forecast}


def _alertable_fleet(db, uid: str, fleet_id: str):
    """A fleet the caller can read (own or sample), same scope as fleet_forecast."""
    fleet = fleet_service.get_fleet(db, fleet_id, _owners(uid))
    if fleet is None:
        raise ToolError("Fleet not found.")
    return fleet


@_tool("list_fleet_alerts", _READ, "List fleet alerts")
def list_fleet_alerts(
    ctx: Context,
    fleet_id: Annotated[str, Field(description="A fleet id from list_fleets.")],
) -> dict[str, Any]:
    """The email alert rules on one of the user's fleets, each with its current value: 'above' (expected
    failures over the horizon cross a threshold), 'change' (they move by a percentage) and 'within' (x or more
    failures now expected within y periods). Rules are checked whenever usage for the fleet arrives through the
    ingest API."""
    user, db = _caller(ctx), _db()
    fleet = _alertable_fleet(db, user["uid"], fleet_id)
    forecast = alerts_service.current_forecast(db, fleet, [*_owners(user["uid"]), fleet.owner_id])
    rules = alerts_service.list_alerts(db, fleet.id) if fleet.owner_id == user["uid"] else []
    return {"fleet": {"id": fleet.id, "name": fleet.name, "settings": fleet.settings,
                      "url": _url(f"/fleet/forecasts/{fleet.id}")},
            "expected_failures": (forecast or {}).get("expected"),
            "alerts": [alerts_service.public(d, user["uid"], fleet, forecast) for d in rules]}


@_tool("create_fleet_alert", _WRITE, "Create a fleet alert")
def create_fleet_alert(
    ctx: Context,
    fleet_id: Annotated[str, Field(description="A fleet id from list_fleets (one of the user's own fleets).")],
    kind: Annotated[Literal["above", "change", "within"], Field(
        description="'above' = email once each time expected failures over the horizon cross above `threshold`; "
                    "'change' = email when they move by `percent` % or more from the last alert (or today); "
                    "'within' = email once each time `x` or more failures become expected within the next "
                    "`y_periods` periods.")],
    threshold: Annotated[Optional[float], Field(ge=0, description="For 'above': expected failures over the "
                                                                   "fleet's horizon.")] = None,
    percent: Annotated[Optional[float], Field(gt=0, le=1000, description="For 'change': percent, e.g. 25.")] = None,
    x: Annotated[Optional[float], Field(gt=0, description="For 'within': failures, may be fractional (0.5).")] = None,
    y_periods: Annotated[Optional[float], Field(gt=0, description="For 'within': periods in the fleet's "
                                                                  "period_label (e.g. months), at most its "
                                                                  "horizon; fractional allowed.")] = None,
) -> dict[str, Any]:
    """Save an email alert rule on one of the user's fleet forecasts (see fleet_forecast for the numbers it
    watches). Rules are evaluated when usage arrives through the ingest API and email the user once per
    crossing; at most 10 per fleet."""
    user, db = _caller(ctx), _db()
    fleet = _alertable_fleet(db, user["uid"], fleet_id)
    if fleet.owner_id != user["uid"]:
        raise ToolError("Alerts can only be set on your own fleets, not samples.")
    wanted = {"above": {"threshold"}, "change": {"percent"}, "within": {"x", "y_periods"}}[kind]
    stray = [k for k, v in (("threshold", threshold), ("percent", percent), ("x", x), ("y_periods", y_periods))
             if v is not None and k not in wanted]
    if stray:
        raise ToolError(f"A '{kind}' alert takes {' and '.join(sorted(wanted))} only — {', '.join(stray)} "
                        "would be ignored. Drop it, or pick the kind that uses it.")
    try:
        doc = alerts_service.create_alert(
            db, fleet, user["uid"], [*_owners(user["uid"]), fleet.owner_id],
            kind=kind, threshold=threshold, percent=percent, x=x, y_periods=y_periods,
        )
    except (alerts_service.AlertValidationError, alerts_service.AlertLimitError) as exc:
        raise ToolError(str(exc)) from None
    return {"alert": alerts_service.public(doc, user["uid"], fleet),
            "url": _url(f"/fleet/forecasts/{fleet.id}#alerts")}


# ---------------------------------------------------------------------------
# Deleting
# ---------------------------------------------------------------------------
# Owner-only and never a shared sample (the app only hides those per user).
# Each reuses the app's delete service and its dependency rule, so the MCP
# can't delete anything the app wouldn't; where the app allows a deletion that
# leaves other artifacts pointing at nothing, the response names them.

def _sample_refusal(kind: str, name: str) -> ToolError:
    return ToolError(f"“{name}” is a shared sample {kind}, not yours — it can't be deleted. (In the app you can "
                     "hide samples from your lists.)")


def _rbds_referencing(db, uid: str, predicate) -> list[dict]:
    return [{"id": r.id, "name": r.name} for r in rbds_service.list_rbds(db, uid)
            if any(predicate(n.get("data") or {}) for n in (r.graph or {}).get("nodes") or [])]


@_tool("delete_model", _WRITE, "Delete a model")
def delete_model(
    ctx: Context,
    model_id: Annotated[str, Field(description="One of the user's own model ids (list_models) — life or recurrent.")],
) -> dict[str, Any]:
    """Permanently delete one of the user's own saved models (life or recurrent). Shared samples can't be
    deleted, and neither can a model a fleet forecast runs on: the answer names those fleets, which must be
    relinked or deleted in the app first. RBDs that used the model are listed in the response. Always confirm
    with the user first, naming the model — this can't be undone."""
    user, db = _caller(ctx), _db()
    uid = user["uid"]
    m = models_service.get_model(db, model_id, _owners(uid))
    if m is not None:
        if samples_service.is_sample(m.owner_id):
            raise _sample_refusal("model", m.name)
        # Stricter than the app: an agent mustn't leave a fleet forecast
        # running on nothing, so a model a fleet uses is refused outright.
        fleets = [f for f in fleet_service.list_fleets(db, uid) if f.model_id == m.id]
        if fleets:
            names = ", ".join(f"\u201c{f.name}\u201d ({_url(f'/fleet/forecasts/{f.id}')})" for f in fleets)
            raise ToolError(
                f"Model \u201c{m.name}\u201d can't be deleted: {len(fleets)} fleet forecast"
                f"{'s' if len(fleets) != 1 else ''} run{'' if len(fleets) != 1 else 's'} on it ({names}). "
                "Relink or delete those fleets in the app first, then delete the model.")
        affected = {
            "rbds": _rbds_referencing(db, uid, lambda d: isinstance(d.get("model"), dict)
                                      and (d["model"].get("modelId") or d["model"].get("model_id")) == m.id),
        }
        models_service.delete_model(db, m.id, uid)
        kind = "life"
    else:
        doc = recurrent_service.get_model(db, model_id, _owners(uid))
        if doc is None:
            raise ToolError("Model not found.")
        if samples_service.is_sample(doc.owner_id):
            raise _sample_refusal("model", doc.name)
        m, affected, kind = doc, {"rbds": []}, "recurrent"
        recurrent_service.delete_model(db, doc.id, uid)
    out = {"deleted": True, "model_id": m.id, "name": m.name, "kind": kind}
    affected = {k: v for k, v in affected.items() if v}
    if affected:
        out["affected"] = affected
        out["note"] = ("These referenced the deleted model. RBD blocks keep the parameters copied onto them, "
                       "but no longer track the model — and proportional-hazards or non-parametric blocks, "
                       "which re-read it, stop working.")
    return out


@_tool("delete_dataset", _WRITE, "Delete a dataset")
def delete_dataset(
    ctx: Context,
    dataset_id: Annotated[str, Field(description="One of the user's own dataset ids (list_datasets).")],
) -> dict[str, Any]:
    """Permanently delete one of the user's own datasets. As in the app, a dataset that saved models were
    fitted to can't be deleted until those models are — the error names them. Shared samples can't be
    deleted. Always confirm with the user first, naming the dataset — this can't be undone."""
    user, db = _caller(ctx), _db()
    uid = user["uid"]
    ds = datasets_service.get_dataset(db, dataset_id, _owners(uid))
    if ds is None:
        raise ToolError("Dataset not found.")
    if samples_service.is_sample(ds.owner_id):
        raise _sample_refusal("dataset", ds.name)
    models = datasets_service.models_for_dataset(db, ds.id, _owners(uid))
    if models:
        names = ", ".join(f"“{m.name}”" for m in models[:3])
        more = "" if len(models) <= 3 else f" and {len(models) - 3} more"
        raise ToolError(f"Dataset is used by {len(models)} model(s): {names}{more}. Delete those models first "
                        "(delete_model), or keep the dataset.")
    if not datasets_service.delete_dataset(db, ds.id, uid):
        raise ToolError("Dataset not found.")
    return {"deleted": True, "dataset_id": ds.id, "name": ds.name}


@_tool("delete_rbd", _WRITE, "Delete an RBD")
def delete_rbd(
    ctx: Context,
    rbd_id: Annotated[str, Field(description="One of the user's own RBD ids (list_rbds).")],
) -> dict[str, Any]:
    """Permanently delete one of the user's own reliability block diagrams (and any saved availability result
    on it). Shared samples can't be deleted. Diagrams that embed it as a sub-system stop working; the
    response lists them. Always confirm with the user first, naming the diagram — this can't be undone."""
    user, db = _caller(ctx), _db()
    uid = user["uid"]
    rbd = _get_rbd(db, uid, rbd_id)
    if samples_service.is_sample(rbd.owner_id):
        raise _sample_refusal("RBD", rbd.name)
    embedding = [r for r in _rbds_referencing(db, uid, lambda d: isinstance(d.get("rbd"), dict)
                                               and d["rbd"].get("id") == rbd.id) if r["id"] != rbd.id]
    rbds_service.delete_rbd(db, rbd.id, uid)
    out = {"deleted": True, "rbd_id": rbd.id, "name": rbd.name}
    if embedding:
        out["affected"] = {"rbds": embedding}
        out["note"] = "These diagrams embedded it as a sub-system and can no longer be analysed as they are."
    return out


# ---------------------------------------------------------------------------
# Outage history (an RBD's observed up/down record; issue #159)
# ---------------------------------------------------------------------------

class OutageColumns(BaseModel):
    model_config = ConfigDict(extra="forbid")
    asset: str = Field(description="Column naming the asset/block of each outage (a block's label or node id).")
    start: str = Field(description="Column with when the outage started.")
    end: Optional[str] = Field(default=None, description="Column with when it ended (blank cell = still down).")
    duration: Optional[str] = Field(default=None, description="Instead of end: a column with how long it lasted "
                                                              "(in `unit`).")
    reason: Optional[str] = Field(default=None, description="Optional column with the reason or failure mode.")
    planned: Optional[str] = Field(default=None, description="Optional column: yes/no (planned/unplanned, 1/0) "
                                                             "for planned maintenance outages.")


def _own_rbd(db, uid: str, rbd_id: str):
    rbd = _get_rbd(db, uid, rbd_id)
    if samples_service.is_sample(rbd.owner_id):
        raise ToolError(f"“{rbd.name}” is a shared sample diagram: outage logs go on the user's own diagrams. "
                        "Copy it with clone_rbd first, then upload the log to the copy.")
    return rbd


def _outages_url(rbd_id: str) -> str:
    return _url(f"/rbds/b/{rbd_id}?tab=outages")


@_tool("upload_outage_log", _WRITE, "Upload an outage log")
def upload_outage_log(
    ctx: Context,
    rbd_id: Annotated[str, Field(description="One of the user's own RBD ids (list_rbds) the log belongs to.")],
    csv: Annotated[str, Field(min_length=1, description=(
        "The outage log as CSV text, header row first (tab- or semicolon-separated also accepted): one row per "
        "outage with the asset, its start and its end (blank = still down)."))],
    columns: Annotated[Optional[OutageColumns], Field(description=(
        "Which column holds what. Omit to detect from the headers (asset/equipment, start/down, end/restored, "
        "duration, reason, planned)."))] = None,
    unit: Annotated[Optional[str], Field(description=(
        "The unit numeric times and durations are in (hours, days, …). Default: the diagram's unit. Dates and "
        "times (ISO or day/month/year) are converted to the diagram's unit."))] = None,
    window_start: Annotated[Optional[str], Field(description=(
        "When observation began (a date-time for a dated log, else a number). Default: the first outage start."
    ))] = None,
    window_end: Annotated[Optional[str], Field(description=(
        "When observation ended (e.g. now). Default: the last record. Open outages run to it."))] = None,
    date_order: Annotated[Literal["auto", "dmy", "mdy"], Field(description=(
        "How to read numeric dates like 03/04/2024: dmy (day first), mdy, or auto (detected; ambiguous -> dmy)."
    ))] = "auto",
    asset_map: Annotated[Optional[dict[str, str]], Field(description=(
        "Map asset names in the log to node ids where they don't match a block's label or id exactly "
        "(get_rbd lists the nodes)."))] = None,
    name: Annotated[Optional[str], Field(description="A name for the log.")] = None,
) -> dict[str, Any]:
    """Save a real outage log against one of the user's RBDs and return the system's observed history from it.
    Each block's outages become its up/down timeline; RePyability merges them through the diagram's structure
    into the system's history and attributes every system outage to the block that took it down. Overlapping
    outages of one asset are merged; assets that match no block are listed and left out. Returns the log id,
    import notes and the history (as system_history does)."""
    user, db = _caller(ctx), _db()
    uid = user["uid"]
    rbd = _own_rbd(db, uid, rbd_id)
    _cap(db, user, "outage_logs", "outage logs")
    mapping = columns.model_dump(exclude_none=True) if columns else None
    try:
        parsed = outage_logs_service.parse_log(
            csv, rbd.graph or {}, mapping, unit=unit, window_start=window_start, window_end=window_end,
            date_order=date_order, asset_map=asset_map)
    except outage_logs_service.OutageLogError as exc:
        raise ToolError(str(exc)) from exc
    log = outage_logs_service.create_log(db, rbd, parsed, uid, name or "")
    out = {
        "log_id": log["_id"], "name": log["name"], "rbd_id": rbd.id, "n_outages": len(parsed["rows"]),
        "columns": parsed["columns"], "unit": parsed["unit"],
        "asset_map": parsed["asset_map"], "unmapped": parsed["unmapped"],
        "url": _outages_url(rbd.id),
    }
    try:
        out["history"] = outage_logs_service.lean_history(
            outage_logs_service.system_history(rbd.graph or {}, log))
    except outage_logs_service.OutageLogError as exc:
        out["history_error"] = str(exc)
    return out


@_tool("system_history", _READ, "Observed system history")
def system_history(
    ctx: Context,
    rbd_id: Annotated[str, Field(description="One of the user's own RBD ids (list_rbds).")],
    log_id: Annotated[Optional[str], Field(description=(
        "An outage log id (from upload_outage_log). Default: the diagram's latest log."))] = None,
) -> dict[str, Any]:
    """A diagram's observed availability history from its outage log: KPIs over the observation window
    (availability, system outages, failures vs planned, total and mean downtime, observed MTBF), the 10
    longest system outages each with the block that caused it (the last to go down) and any others down with
    it, and the blocks ranked by their share of the system's downtime. Times are in the log's unit."""
    user, db = _caller(ctx), _db()
    uid = user["uid"]
    rbd = _own_rbd(db, uid, rbd_id)
    if log_id:
        log = outage_logs_service.get_log(db, log_id, [uid], rbd_id=rbd.id)
        if log is None:
            raise ToolError("Outage log not found for this diagram.")
    else:
        log = outage_logs_service.latest_log(db, rbd.id, [uid])
        if log is None:
            raise ToolError(f"“{rbd.name}” has no outage log yet — upload one with upload_outage_log.")
    try:
        result = outage_logs_service.system_history(rbd.graph or {}, log)
    except outage_logs_service.OutageLogError as exc:
        raise ToolError(str(exc)) from exc
    return {"rbd_id": rbd.id, "name": rbd.name, "log_id": log["_id"], "log_name": log.get("name"),
            **outage_logs_service.lean_history(result), "url": _outages_url(rbd.id)}


# ---------------------------------------------------------------------------
# Plans
# ---------------------------------------------------------------------------

@_tool("upgrade_link", _LINK, "Get a link to upgrade")
def upgrade_link(
    ctx: Context,
    plan: Annotated[Literal["pro"], Field(
        description=f"pro = Reliafy Pro ({PRO_PRICE}: everything, including use from AI agents over MCP, "
                    "fitting and simulation). The only plan on offer.")] = "pro",
) -> dict[str, Any]:
    """A link the user opens to subscribe to Reliafy Pro: Stripe's own checkout page, where they see the
    price and pay. Nothing is charged until they complete it there, so give them the link and let them
    decide; never say the upgrade has happened. Works without Pro and when a limit is used up. A user
    already on another paid plan gets the billing page instead, to change plans there."""
    from backend.routers.billing import start_subscription  # local: routers import after this module

    user = _caller(ctx)
    base = f"{config.PUBLIC_BASE_URL or 'https://reliafy.com'}/"
    status, payload = start_subscription(_db(), user, plan, base, allow_switch=False)
    name, price = f"Reliafy {_PLAN_NAMES[plan]}", PRO_PRICE
    if status == 200:
        return {"plan": plan, "price": price, "url": payload["url"],
                "note": f"Open this link to subscribe to {name} ({price}) on Stripe's checkout page. It's valid "
                        "for 24 hours, and nothing is charged until the checkout is completed."}
    if status == 409 and payload.get("url"):
        return {"plan": plan, "price": price, "url": payload["url"],
                "note": f"You're on another paid plan: change to {name} on the billing page."}
    raise ToolError(payload.get("detail") or "Couldn't create a payment link.")


# ---------------------------------------------------------------------------
# HTTP endpoint (ASGI): auth in front of the SDK's Streamable HTTP transport
# ---------------------------------------------------------------------------

class McpHttpApp:
    """The ``/mcp`` ASGI endpoint.

    Authenticates every request (401 / 403 / 429 before the MCP layer sees
    it), attaches the user to the request scope for the tools, and hands the
    request to the SDK's session manager, whose task group must be running —
    :meth:`lifespan` is entered from the FastAPI app's lifespan. A fresh
    manager is built per lifespan (the SDK allows one ``run()`` per manager).
    """

    def __init__(self, server: MCPServer):
        self.server = server
        self._manager = None

    @asynccontextmanager
    async def lifespan(self):
        self.server.streamable_http_app(
            stateless_http=True,
            json_response=True,
            # DNS-rebinding protection guards servers on localhost that trust
            # the browser. Every request here must carry a bearer token a
            # browser won't attach on its own, and the Host varies by
            # deployment (reliafy.com, Cloud Run, self-hosted), so it's off.
            transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False),
        )
        manager = self.server.session_manager
        async with manager.run():
            self._manager = manager
            try:
                yield
            finally:
                self._manager = None

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":  # pragma: no cover - mounted on an HTTP route
            return
        status, user, message = await anyio.to_thread.run_sync(
            _authenticate_request, Headers(scope=scope).get("authorization"))
        if user is None:
            # 401 carries the RFC 9728 pointer Claude needs to start OAuth
            # sign-in (and to refresh when an access token expires).
            headers = {"WWW-Authenticate": oauth_service.www_authenticate(
                "invalid_token" if message.startswith("Invalid") else None)} if status == 401 else None
            await JSONResponse({"detail": message}, status_code=status, headers=headers)(scope, receive, send)
            return
        try:
            from backend.routers.ingest import _rate_check

            _rate_check(user["uid"])
        except HTTPException as exc:
            await JSONResponse({"detail": exc.detail}, status_code=exc.status_code)(scope, receive, send)
            return
        if scope["method"] != "POST":
            # Stateless: no sessions to DELETE, and nothing will ever be pushed
            # on a standalone GET stream — which would otherwise hold an idle
            # connection open until the platform timeout. The spec lets a
            # server answer 405 here; clients then just POST.
            await JSONResponse({"detail": "Use POST — this MCP server is stateless."},
                               status_code=405, headers={"Allow": "POST"})(scope, receive, send)
            return
        if self._manager is None:
            await JSONResponse({"detail": "The MCP service is starting — retry shortly."},
                               status_code=503)(scope, receive, send)
            return
        scope = {**scope, "state": {**(scope.get("state") or {}), "reliafy_user": user}}
        if not usage_service.enabled():
            await self._manager.handle_request(scope, receive, send)
            return
        # Note initialize / tools/list (connections — tool calls are logged by
        # the tools themselves): keep the first few KB of the body as it
        # streams past, and read the JSON-RPC method once it's answered.
        body, done, status = bytearray(), [False], [0]

        async def receive_tap():
            message = await receive()
            if message["type"] == "http.request" and len(body) <= _SNIFF_BYTES:
                body.extend(message.get("body", b"")[: _SNIFF_BYTES + 1 - len(body)])
                done[0] = not message.get("more_body", False)
            return message

        async def send_tap(message):
            if message["type"] == "http.response.start":
                status[0] = message["status"]
            await send(message)

        await self._manager.handle_request(scope, receive_tap, send_tap)
        if done[0] and len(body) <= _SNIFF_BYTES:
            methods = _protocol_methods(bytes(body))
            if methods:
                await anyio.to_thread.run_sync(_log_protocol, user, methods, status[0])


_SNIFF_BYTES = 8192


def _protocol_methods(raw: bytes) -> list[str]:
    """The initialize / tools/list methods in a JSON-RPC body (or batch)."""
    import json

    try:
        msg = json.loads(raw or b"null")
    except ValueError:
        return []
    items = msg if isinstance(msg, list) else [msg]
    return [m["method"] for m in items
            if isinstance(m, dict) and m.get("method") in ("initialize", "tools/list")]


def _log_protocol(user: dict, methods: list[str], status: int) -> None:
    try:
        db = _db()
        for method in methods:
            usage_service.record(
                db, uid=user["uid"], channel="mcp", feature=method,
                outcome="ok" if 200 <= status < 300 else "error",
                plan=_usage_plan(user), client=usage_service.client_of(user))
    except Exception:  # noqa: BLE001
        logger.warning("could not log an MCP connection", exc_info=True)


def _authenticate_request(authorization: str | None) -> tuple[int, dict | None, str]:
    return authenticate(_db(), authorization)


mcp_http_app = McpHttpApp(mcp)
