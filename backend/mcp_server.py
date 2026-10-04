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
import json
import logging
import math
import re
import shlex
import time
from datetime import timedelta
from contextlib import asynccontextmanager, contextmanager
from typing import Annotated, Any, Callable, Literal, Optional, Union
from urllib.parse import quote

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
from backend.services import availability_answer
from backend.services import billing as billing_service
from backend.services import compare_groups as compare_groups_service
from backend.services import datasets as datasets_service
from backend.services import fleet as fleet_service
from backend.services import fleet_alerts as alerts_service
from backend.services import import_guard
from backend.services import oauth as oauth_service
from backend.services import outage_logs as outage_logs_service
from backend.services import models as models_service
from backend.services import public_links as links_service
from backend.services import rbd_edit
from backend.services import rbd_graph
from backend.services import rbd_import
from backend.services import rbd_jobs as rbd_jobs_service
from backend.services import rbd_repeats
from backend.services.rbd_import import structure as rbd_structure
from backend.services import rbds as rbds_service
from backend.services import recurrent as recurrent_service
from backend.services import samples as samples_service
from backend.services import strategy_store
from backend.services import tokens as tokens_service
from backend.services import uploads as uploads_service
from backend.services import usage as usage_service
from backend.services import rbd_analysis
from backend.services import rbd_costs
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
    if not (tokens_service.has_scope(user, "read") or tokens_service.has_scope(user, "write")):
        return 403, None, (
            "This API token can only push data (ingest scope). To use Reliafy over MCP, create a token "
            "with the read (and write, for saving) scope under Settings > API access.")
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
- Datasets: get_dataset reads a dataset's columns, row count and rows, a page at a time (offset / limit).
- Comparing groups: compare_groups answers "is A better than B?" — it splits life data by a column \
(supplier, site, design revision) and gives the log-rank test, each group's average life over a common window \
(RMST) with the difference and its CI, Gray's test per failure mode, and a verdict sentence. Nothing is fitted.
- Confidence: reliability_at with confidence (e.g. 0.95) adds lower/upper bounds on R(t) and F(t); quote them \
with the point values. Bounds are null, with bounds_note saying why, where a model has none — never invent them.
- Reliability block diagrams: list_rbds / get_rbd, create_rbd, analyze_rbd (system reliability, MTTF, \
B-lives, importance; availability for repairable diagrams), export_rbd_python (a standalone script), \
export_rbd_json (RePyability's JSON: rbd_from_json loads it; import_rbd takes it back). A long \
availability simulation may come back as a job_id still queued or running: call get_job with it every few \
seconds until it is done. Edit, \
don't rebuild: to change a saved diagram, send edit_rbd one batch of ops (add/remove/update blocks and \
edges) rather than re-creating it; clone_rbd copies a sample or makes a variant to edit. cheapest_design \
finds a repairable diagram's redundancy with the lowest total cost of ownership; a discount_rate (percent a \
year: 7 = 7%) makes its totals, and analyze_rbd's, present values.
- Observed history: upload_outage_log saves a real outage log (asset, start, end; blank end = still down) \
against one of the user's diagrams; system_history then gives the system's actual availability over the \
window, its outages each attributed to the block that took it down, and the blocks ranked by downtime share.
- Files: never read a file into your context to paste it. For any file (a BlockSim / Open-PSA / Galileo / RePyability \
diagram, an Excel workbook, a CSV of failure times or outages): create_upload, then send the file with the \
curl PUT it returns, inspect_upload if you need its sheets, columns or diagrams, then import_rbd / \
import_excel / upload_dataset / upload_outage_log with the upload_id. Paste only small text formats \
(import_rbd's content, upload_dataset's csv). If the PUT can't reach Reliafy from your environment (a \
proxy 403, no network), follow create_upload's fallback: paste a small text file (at most 200 KB) instead, \
or ask the user to upload the file in the app. Relay the import notes: they say what was approximated.
- Maintenance strategy: optimal_replacement, failure_finding_interval, optimal_overhaul (recurrent models), \
and fleet_forecast (list_fleets first); list_fleet_alerts / create_fleet_alert manage email alerts on a \
fleet's expected failures.
- Test planning: plan_demonstration_test sizes a reliability demonstration test — units, test time per unit \
and allowed failures to show reliability R over a mission at confidence C (success run / binomial; a longer \
test per unit with a known Weibull shape; or an MTBF test); with producer_risk and a good design it keeps both \
risks. It needs no saved data.
- Housekeeping: delete_model, delete_dataset and delete_rbd permanently delete the user's own artifacts \
(never shared samples; a dataset still used by a model, or a model a fleet runs on, can't be deleted). \
Only on the user's explicit \
request: confirm by name first, and relay anything the response lists as affected.
- Tidying: update_model / update_dataset rename the user's own models and datasets or set their notes (never \
the data or the fit; never shared samples).
- Sharing: share_link publishes a read-only page of one of the user's own items (model, dataset, RBD, \
strategy analysis, RCM study, fleet) that anyone with the URL can open without a Reliafy account, optionally \
password-protected (password=true: Reliafy generates a passphrase and returns it once — tell the user to send \
the link and the passphrase to the recipient separately) and expiring (expires_in_days). An item can have \
several links, each with a label; list_share_links shows them and revoke_share_link ends one at once. Share \
only when the user asks to.
- Plans: upgrade_link gives the user a Stripe payment link for Reliafy Pro, to open themselves.
- Account: get_account shows the plan, on Free the tool calls used and left this month (and the date they \
reset; Pro is unlimited), storage used against the limits and whether simulation is included; it's never \
counted, even past the allowance.

Conventions — follow them exactly:
- Censoring: 0 = the unit FAILED at that time, 1 = it was still running (right-censored, a suspension); \
-1 = left-censored (found failed at that time, failed at some unknown earlier time); 2 = interval-censored \
(failed between two times: the upper bound goes in data_right / time_right_column). Delayed entry (units in \
service before records began) is truncation — trunc_left / trunc_left_column — not a flag. Spreadsheets are often \
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
(distributions, P(no outage), percentiles, criticality indices; from current_state, next_failure: the time \
to the next system failure, its mean residual life and likely cause) and is a paid feature; a saved result is \
served when one exists. When the response says the exact figures are simulation-only for a diagram (e.g. \
one repair crew for wear-out lives), say so.
- Non-repairable RBDs: analyze_rbd's current_state ({node_id: {"failed": true} or {"age": <time run>}}) \
gives the remaining life from now (mean_residual_life, exact); target_reliability gives the design life \
(e.g. R ≥ 90% until t).
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
# Never gated or counted: the way to Pro, and seeing where the allowance
# stands, must work when a limit is hit.
UNGATED_TOOLS = {"upgrade_link", "get_account"}


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


def _tool_scope(annotations: ToolAnnotations) -> str:
    """The API-token scope a tool needs: ``write`` for anything that changes
    the workspace (the destructive-hint tools), ``read`` for the rest —
    reads, calculations, ``upgrade_link`` and ``get_account``."""
    return "read" if annotations.read_only_hint else "write"


def _require_scope(ctx: Context, scope: str) -> None:
    """Refuse a tool an API token's scopes don't cover (sessions via OAuth have
    every scope)."""
    if not tokens_service.has_scope(_caller(ctx), scope):
        raise ToolError(tokens_service.scope_message(scope))


def _tool(name: str, annotations: ToolAnnotations, title: str):
    """Register a tool, translating user-facing failures into tool errors.
    An API token needs the tool's scope (:func:`_tool_scope`)."""
    scope = _tool_scope(annotations)

    def decorator(fn):
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            ctx = next((v for v in (*args, *kwargs.values()) if isinstance(v, Context)), None)
            started = time.perf_counter()
            state: dict = {}
            token = _CALL.set(state)
            counted, outcome = False, "error"
            try:
                if ctx is not None:
                    _require_scope(ctx, scope)
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


def _reader(user: dict) -> "access_service.AccessCtx":
    """The caller's access context for MCP: personal workspace, reads scoped to
    :func:`_owners` (no team or shared-to-me fallback)."""
    uid = user["uid"]
    return access_service.AccessCtx(
        user=user, uid=uid, workspace=access_service.PERSONAL, write_owner=uid,
        read_owners=_owners(uid), list_owners=uid, share_fallback=False,
    )


def _check_graph_refs(db, user: dict, graph: dict, keep_graph: dict | None = None) -> None:
    """Saved models and sub-system diagrams on a graph's blocks must be the
    caller's own or samples (links an existing diagram already had are kept)."""
    access_service.check_references(
        db, _reader(user), access_service.graph_refs(graph),
        keep=access_service.graph_refs(keep_graph) if keep_graph else ())


def _url(path: str) -> str:
    return f"{config.PUBLIC_BASE_URL or 'https://reliafy.com'}{path}"


def _cap(db, user: dict, kind: str, label: str, n: int = 1) -> None:
    """Refuse a save past the caller's plan storage cap (operators have none).
    ``n`` > 1 checks room for that many new items at once (an import saving
    several diagrams is all or nothing)."""
    if billing_service.is_admin_user(user):
        return
    if n <= 1:
        if not billing_service.would_exceed_cap(db, user["uid"], kind):
            return
    elif not config.BILLING_ENABLED:
        return
    plan = billing_service.account(db, user["uid"])["active_plan"]
    cap = billing_service.cap_for(kind, plan)
    if cap is None:
        return
    if n > 1:
        owned = billing_service.owned_count(db, user["uid"], kind)
        if owned + n <= cap:
            return
        raise Refusal(
            f"This would save {n} {label}, but the {_PLAN_NAMES[plan]} plan allows {cap} and you have {owned} — "
            f"nothing was saved. Import fewer (pick them by name), or delete {label} you no longer need. "
            + _upgrade_path(lead="Or, for more storage, upgrade"))
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


class DemandBatch(BaseModel):
    demands: int = Field(ge=1, description="Demands (trials) in this batch: proof tests, starts, activations.")
    failures: int = Field(ge=0, description="Failures among those demands (0 to demands).")
    label: Optional[str] = Field(default=None, max_length=80,
                                 description="Optional name for the batch, e.g. a site, lot or test campaign.")


_DemandBatches = Annotated[Optional[list[DemandBatch]], Field(
    min_length=1, max_length=fitting.PER_DEMAND_MAX_BATCHES, description=(
        "Per-demand (one-shot) data: one {demands, failures, label?} per batch of demands — several sites, "
        "lots of different sizes or test campaigns are pooled into one failure probability per demand, "
        "with exact bounds."))]
_DemandConfidence = Annotated[float, Field(
    gt=0, lt=1, description="Confidence level of the exact bounds, e.g. 0.9 or 0.95 (default).")]


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
        # #230: a fit whose numbers aren't estimates is flagged in the list too.
        **({"maximum": "no finite maximum"} if r.get("no_finite_maximum") else {}),
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
    lead = ["fit_ok", "warning", "warnings"]
    if summary.get("maximum") == "no finite maximum":  # #230: say it first
        lead.insert(1, "maximum")
    return {k: summary[k] for k in lead if k in summary}


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
    no_max = result.get("no_finite_maximum")  # #230: SurPyval 0.23 says so
    failed = bool(no_max) or result.get("fit_ok") is False or bool(result.get("fit_warning"))
    metrics = None if failed else (
        result.get("metrics") or _live_metrics((result.get("functions") or {}).get("model_id")))
    lead: dict[str, Any] = {}
    if no_max:
        lead = {"fit_ok": False, "maximum": "no finite maximum",
                "warning": f"{no_max['message']} {no_max['suggestion']} Don't quote the parameters "
                           "or metrics below as a result."}
    elif failed:
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
    if result.get("maximum") and "maximum" not in out:
        out["maximum"] = result["maximum"]
    if no_max:
        out["metrics_omitted"] = "The fit has no finite maximum, so no life metrics are given."
    elif failed:
        # #215: a median of 7.7e19 from a fit that didn't converge isn't a result.
        out["metrics_omitted"] = "The fit didn't converge, so no life metrics are given."
    for key in ("extra_params", "coefficients", "randomness", "options", "validation", "gof_note"):
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
    proportional-hazards models, and the time unit. Works for life and recurrent models.
    Regression models also report `validation` (how good is this model?): Harrell's C with a plain
    reading (0.5 = coin toss, 1 = perfect ranking), the integrated Brier score against one
    Kaplan-Meier curve for every unit (lower is better), and the time-dependent AUC at the failure-time
    quartiles — or `available: false` with the reason."""
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
        if m.kind == "regression":
            out["validation"] = models_service.ensure_validation(db, m)
        if (m.spec or {}).get("notes"):
            out["notes"] = m.spec["notes"]
        for key in ("maximum", "gof_note"):
            if r.get(key):
                out[key] = r[key]
        no_max = r.get("no_finite_maximum")
        if no_max:
            # #230: lead with it, as the fit tools do.
            out = {"fit_ok": False, "maximum": "no finite maximum",
                   "warning": f"{no_max['message']} {no_max['suggestion']}", **out}
        elif r.get("fit_ok") is False or r.get("fit_warning"):
            # Lead with it, as the fit tools do.
            out = {"fit_ok": False, "warning": _fit_failure_warning(r.get("fit_warning")), **out}
        return out
    doc = recurrent_service.get_model(db, model_id, owners)
    if doc is not None:
        r = doc.results or {}
        out = {**_recurrent_brief(doc), "params": r.get("params"), "gof": r.get("gof"), "trend": r.get("trend")}
        if (doc.spec or {}).get("notes"):
            out["notes"] = doc.spec["notes"]
        return out
    raise ToolError("Model not found.")


_FitDistribution = Annotated[str, Field(
    description="A distribution id — weibull, exponential, normal, lognormal, gamma, loglogistic, "
                "expo_weibull, gumbel, logistic, … — or 'best' to fit every plain distribution and keep "
                "the lowest-AIC one. Regression ids (e.g. weibull_ph) need covariates and a dataset.")]
_FitData = Annotated[Optional[list[float]], Field(
    description="Inline failure/suspension times, one per unit (the interval's lower bound when data_right is "
                "given). Give this OR dataset_id.")]
_FitCensored = Annotated[Optional[list[int]], Field(
    description="Censoring flag per time in `data`: 0 = FAILED at that time, 1 = still running "
                "(right-censored / suspended), -1 = left-censored (found failed at that time, having failed "
                "at some unknown earlier time), 2 = interval-censored (failed somewhere between data and "
                "data_right). Omit when every time is a failure.")]
_FitDataRight = Annotated[Optional[list[float]], Field(
    description="Interval censoring: each row's upper bound, with `data` as the lower bound — e.g. the "
                "inspection that found it failed, with `data` the last one it passed. Interval rows take flag "
                "2; other rows repeat their time here. Without `censored`, equal bounds read as failures and "
                "unequal ones as intervals.")]
_FitTruncLeft = Annotated[Optional[Union[float, list[Optional[float]]]], Field(
    description="Left truncation (delayed entry): the age at which a unit came under observation, e.g. units "
                "already in service when records began. One number for every row, or one per row (null = not "
                "truncated). The fit conditions on survival to that age instead of treating the unit as new.")]
_FitTruncRight = Annotated[Optional[Union[float, list[Optional[float]]]], Field(
    description="Right truncation: the age beyond which a unit couldn't have been observed (a later failure "
                "would never have been recorded). One number for every row, or one per row (null = not "
                "truncated).")]
_FitMethod = Annotated[Optional[Literal["MLE", "MPS", "MPP", "MSE", "MOM"]], Field(
    description="Fit method (default MLE, maximum likelihood): MPP = probability-plot (median-rank) "
                "regression, MPS = maximum product spacing, MSE = least squares against the empirical CDF, "
                "MOM = method of moments. MOM takes no censoring or truncation, MSE no truncation, and "
                "interval-censored data needs MLE or MSE.")]
_FitCounts = Annotated[Optional[list[int]], Field(
    description="Optional count per row of `data` (identical units sharing that time and flag).")]
_FitInvert = Annotated[bool, Field(
    description="True when the censoring flags use the opposite convention (1 = failed, 0 = running); "
                "Reliafy flips the 0/1 flags before fitting (-1 and 2 are left as is).")]
_FitDataset = Annotated[Optional[str], Field(description="A saved dataset (list_datasets) instead of inline data.")]
_FitTimeCol = Annotated[Optional[str], Field(description="Dataset column holding the times (required with dataset_id).")]
_FitCensorCol = Annotated[Optional[str], Field(description="Dataset column holding the censoring flags (0 = failed, "
                                                             "1 = running, -1 = left-censored, 2 = "
                                                             "interval-censored).")]
_FitCountCol = Annotated[Optional[str], Field(description="Dataset column holding counts.")]
_FitTimeRightCol = Annotated[Optional[str], Field(
    description="Interval censoring: the column holding each row's upper bound, with time_column as the lower "
                "bound. Interval rows take flag 2; other rows repeat their time in both columns.")]
_FitTruncLeftCol = Annotated[Optional[str], Field(
    description="Column holding each row's left-truncation age (delayed entry: the age it came under "
                "observation; blank = not truncated).")]
_FitTruncRightCol = Annotated[Optional[str], Field(
    description="Column holding each row's right-truncation age (blank = not truncated).")]
_FitCovariates = Annotated[Optional[list[str]], Field(
    description="Dataset covariate columns — regression (proportional-hazards etc.) distributions only.")]
_FitUnit = Annotated[Optional[str], Field(description="Time unit of the data, e.g. 'hours', 'cycles', 'km'.")]


def _mcp_fit_error(exc: FitError, c_invert: bool) -> FitError:
    """A fitting error reworded for an MCP caller: the app's remedy ("tick
    'My censor column uses 1 = failed'") becomes the c_invert parameter, and
    SurPyval's interval-censoring complaints name these tools' inputs."""
    hint = ("You passed c_invert=true, so the flags were flipped before fitting — if the data already uses "
            "0 = failed, drop c_invert." if c_invert else
            "If your flags mark failures with a 1, pass c_invert=true rather than rewriting the data.")
    text = str(exc).replace(fitting.CENSOR_INVERT_HINT, hint)
    text = text.replace("clear the 1 = failed option", "drop c_invert")
    if "Censoring value must only be one of" in text:
        text = ("Censoring flags must each be 0 (failed at that time), 1 (still running: right-censored), "
                "-1 (left-censored: failed at some unknown time before it) or 2 (interval-censored: failed "
                "between two times — give the upper bound in data_right, or time_right_column with a "
                "dataset); the data has other values. Units that came under observation late (delayed "
                "entry) are truncation, not a flag: use trunc_left / trunc_right (or trunc_left_column / "
                "trunc_right_column).")
    elif "not interval censored but has interval window" in text:
        text = ("A row's two times differ (an interval) but its censoring flag isn't 2. Flag interval rows 2; "
                "failed, right- and left-censored rows repeat their time as the upper bound.")
    elif "interval censored but only has one failure time" in text:
        text = ("A row is flagged 2 (interval-censored) but its upper bound equals its lower bound — an "
                "interval row needs data_right (or time_right_column) above data (or time_column).")
    elif "only works with Turnbull heuristic" in text:
        text = "MPP can't fit left- or interval-censored data; use MLE (the default) or MSE."
    return FitError(text)


# A censor column named like a failure flag ("failed", "is_failure", "Status")
# usually holds 1 = failed — the opposite of Reliafy's convention (#190).
_FAILURE_FLAG_WORDS = {"fail", "failed", "fails", "failure", "failures", "failing", "event", "events", "status",
                       "broken", "broke", "dead", "death", "died", "fault", "faulted", "faulty", "defect",
                       "defective", "rejected", "reject"}
_CENSOR_WORDS = {"censor", "censored", "censoring", "cens", "suspended", "suspension", "suspensions", "running",
                 "survived", "survival", "alive", "right", "rc"}


def _sounds_like_failure_flag(column: str) -> bool:
    """Whether a column name reads as "1 = failed" (and not as a censoring flag)."""
    spaced = re.sub(r"([a-z])([A-Z])", r"\1 \2", column or "").lower()
    words = set(re.findall(r"[a-z]+", spaced))
    return bool(words & _FAILURE_FLAG_WORDS or "fail" in spaced) and not words & _CENSOR_WORDS


def _censor_counts(df: pd.DataFrame, mapping: dict, invert: bool) -> Optional[dict]:
    """The failures and censored units a fit used (after any c_invert), so
    the caller can check them against what the user described (#190)."""
    if "c" not in mapping:
        return None
    try:
        c = pd.to_numeric(df[mapping["c"]], errors="coerce")
        n = pd.to_numeric(df[mapping["n"]], errors="coerce") if "n" in mapping else pd.Series(1, index=df.index)
        if invert:
            c = c.map({0: 1, 1: 0}).fillna(c)
        out = {"n_failed": int(n[c == 0].sum()), "n_right_censored": int(n[c == 1].sum()),
               "n_left_censored": int(n[c == -1].sum())}
        if (c == 2).any():
            out["n_interval_censored"] = int(n[c == 2].sum())
        return out
    except (KeyError, TypeError, ValueError):
        return None


def _censor_checks(df: pd.DataFrame, mapping: dict, c_invert: bool, censor_column: Optional[str]) -> dict:
    """``censoring`` counts plus, when the censor column is named like a
    failure flag and c_invert isn't set, a non-blocking warning."""
    out: dict[str, Any] = {}
    counts = _censor_counts(df, mapping, c_invert)
    if counts is not None:
        out["censoring"] = counts
    if censor_column and not c_invert and _sounds_like_failure_flag(censor_column):
        used = (f" This fit used {counts['n_failed']} failures and {counts['n_right_censored']} still running."
                if counts else "")
        out["warning"] = (
            f"The censor column “{censor_column}” sounds like 1 = failed, but Reliafy reads 1 as still running "
            f"(0 = failed).{used} If 1 marks failures in this column, refit with c_invert=true.")
    return out


def _censoring(checks: dict) -> dict:
    return {"censoring": checks["censoring"]} if "censoring" in checks else {}


def _with_censor_checks(summary: dict, checks: dict) -> dict:
    """The fit summary with the censor warning among its warnings."""
    if checks.get("warning"):
        summary = {**summary, "warnings": [*(summary.get("warnings") or []), checks["warning"]]}
    return summary


def _fit(ctx: Context, **inputs) -> dict[str, Any]:
    """Shared body of fit_distribution (report only) and fit_and_save_model."""
    try:
        return _fit_body(ctx, **inputs)
    except FitError as exc:
        raise _mcp_fit_error(exc, inputs["c_invert"]) from exc


def _per_row(values, n: int, label: str) -> list:
    """An inline per-row input as a list of ``n``; a single number (allowed
    for truncation) applies to every row."""
    if not isinstance(values, list):
        return [values] * n
    if len(values) != n:
        raise ToolError(f"`{label}` must have one entry per time in `data` ({n}).")
    return list(values)


def _fit_body(ctx: Context, *, distribution, data, censored, counts, c_invert, dataset_id, time_column,
              censor_column, count_column, covariates, unit, data_right, trunc_left, trunc_right,
              time_right_column, trunc_left_column, trunc_right_column, method,
              save: bool, name: str | None) -> dict[str, Any]:
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
                             ("count_column", count_column), ("time_right_column", time_right_column),
                             ("trunc_left_column", trunc_left_column),
                             ("trunc_right_column", trunc_right_column)) if v] if data is not None
             else [k for k, v in (("censored", censored), ("counts", counts), ("data_right", data_right),
                                  ("trunc_left", trunc_left), ("trunc_right", trunc_right)) if v is not None])
    if stray:
        other = "dataset_id" if data is not None else "inline data"
        raise ToolError(f"{', '.join(stray)} only appl{'ies' if len(stray) == 1 else 'y'} with {other} — "
                        "drop it, or switch to that form.")

    dataset = None
    if data is not None:
        if not data:
            raise ToolError("`data` is empty.")
        # The app's x (or xl + xr) / c / n / tl / tr columns, so a saved
        # model's dataset reopens in the UI with the same mapping.
        cols: dict[str, list] = ({"xl": list(data), "xr": _per_row(data_right, len(data), "data_right")}
                                 if data_right is not None else {"x": list(data)})
        for key, values, label in (("c", censored, "censored"), ("n", counts, "counts"),
                                   ("tl", trunc_left, "trunc_left"), ("tr", trunc_right, "trunc_right")):
            if values is not None:
                cols[key] = _per_row(values, len(data), label)
        mapping = {k: k for k in cols}
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
        times = {"xl": time_column, "xr": time_right_column} if time_right_column else {"x": time_column}
        mapping = {**times, "c": censor_column, "n": count_column, "tl": trunc_left_column,
                   "tr": trunc_right_column}
        mapping = {k: v for k, v in mapping.items() if v}
        for col in [*mapping.values(), *(covariates or [])]:
            if col not in names:
                raise ToolError(f"Column '{col}' isn't in the dataset. Columns: {', '.join(names)}.")
        df = datasets_service.load_dataframe(dataset)
    if "xl" in mapping and dist in fitting.REGRESSION_MODELS:
        raise ToolError("Regression models take one time per row — interval censoring (data_right / "
                        "time_right_column) needs a plain distribution.")

    options: dict[str, Any] = {}
    if c_invert:
        if "c" not in mapping:
            raise ToolError("c_invert flips censoring flags — pass `censored` (or censor_column) too.")
        options[fitting.CENSOR_INVERT_KEY] = True
    if method:
        # The app greys these out from the mapping alone; say why here.
        ruled_out = fitting.methods_for_data(mapping)
        if method in ruled_out:
            raise ToolError(f"{ruled_out[method]} Use MLE (the default) or another method.")
        options["how"] = method
    options = options or None

    checks = _censor_checks(df, mapping, c_invert, censor_column)
    if not save:
        result = fitting.fit(dist, df, mapping, covariates=covariates, unit=unit, options=options)
        summary = _with_censor_checks(_fit_summary(result), checks)
        return {**_fit_lead(summary), "saved": False, **_censoring(checks), **summary}

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
    summary = _with_censor_checks(_fit_summary(model.results or {}), checks)
    return {
        **_fit_lead(summary),
        **_censoring(checks),
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
    data_right: _FitDataRight = None,
    censored: _FitCensored = None,
    counts: _FitCounts = None,
    trunc_left: _FitTruncLeft = None,
    trunc_right: _FitTruncRight = None,
    c_invert: _FitInvert = False,
    dataset_id: _FitDataset = None,
    time_column: _FitTimeCol = None,
    time_right_column: _FitTimeRightCol = None,
    censor_column: _FitCensorCol = None,
    count_column: _FitCountCol = None,
    trunc_left_column: _FitTruncLeftCol = None,
    trunc_right_column: _FitTruncRightCol = None,
    covariates: _FitCovariates = None,
    method: _FitMethod = None,
    unit: _FitUnit = None,
) -> dict[str, Any]:
    """Fit a life distribution to failure data with SurPyval and report fitted parameters (with 95% CIs),
    goodness of fit (log-likelihood, AIC, BIC), and life metrics (median, MTTF, B10). Saves nothing — use
    fit_and_save_model to keep the model. Reliafy's censoring convention: 0 = the unit failed, 1 = still
    running (suspended), -1 = left-censored (found failed, at some unknown earlier time), 2 = interval-censored
    (failed between two inspections: the upper bound goes in data_right / time_right_column); if the data marks
    failures with 1, pass c_invert=true. Units already in service when records began are left-truncated:
    give their entry age in trunc_left (trunc_left_column) rather than fitting them as new. A fit that says
    every (or all but one) row is censored almost always means the flags are inverted; censoring gives the failures
    and censored units the fit used — check them against what the user said. Weibull beta < 1 = infant
    mortality, ≈ 1 = random failures, > 1 = wear-out. Regression fits also report `validation`: how good
    the model is (Harrell's C, Brier score against no covariates, time-dependent AUC; see get_model)."""
    return _fit(ctx, distribution=distribution, data=data, data_right=data_right, censored=censored,
                counts=counts, trunc_left=trunc_left, trunc_right=trunc_right, c_invert=c_invert,
                dataset_id=dataset_id, time_column=time_column, time_right_column=time_right_column,
                censor_column=censor_column, count_column=count_column, trunc_left_column=trunc_left_column,
                trunc_right_column=trunc_right_column, covariates=covariates, method=method, unit=unit,
                save=False, name=None)


@_tool("fit_and_save_model", _WRITE, "Fit and save a model")
def fit_and_save_model(
    ctx: Context,
    name: Annotated[str, Field(min_length=1, description="Name for the saved model.")],
    distribution: _FitDistribution = "weibull",
    data: _FitData = None,
    data_right: _FitDataRight = None,
    censored: _FitCensored = None,
    counts: _FitCounts = None,
    trunc_left: _FitTruncLeft = None,
    trunc_right: _FitTruncRight = None,
    c_invert: _FitInvert = False,
    dataset_id: _FitDataset = None,
    time_column: _FitTimeCol = None,
    time_right_column: _FitTimeRightCol = None,
    censor_column: _FitCensorCol = None,
    count_column: _FitCountCol = None,
    trunc_left_column: _FitTruncLeftCol = None,
    trunc_right_column: _FitTruncRightCol = None,
    covariates: _FitCovariates = None,
    method: _FitMethod = None,
    unit: _FitUnit = None,
    demand_batches: Annotated[Optional[list[DemandBatch]], Field(
        min_length=1, description=(
            "Save a per-demand (one-shot) model instead of a life distribution: one {demands, failures, "
            "label?} per batch, as fit_per_demand takes them. Give only name (and demand_confidence) "
            "with it."))] = None,
    demand_confidence: Annotated[float, Field(
        gt=0, lt=1, description="Confidence of a per-demand model's exact bounds (default 0.95).")] = 0.95,
) -> dict[str, Any]:
    """Fit a life distribution exactly as fit_distribution does, then save it as a model in the user's
    Reliafy workspace (inline data is saved as a dataset too) and return its id and url. Use it when the
    user wants to keep the model — for reliability_at, the calculators, or an RBD block. Same censoring
    convention: 0 = failed, 1 = still running, -1 = left-censored, 2 = interval-censored (with data_right /
    time_right_column); c_invert=true when the data marks failures with 1. Delayed entry goes in trunc_left
    (trunc_left_column). With demand_batches it saves a per-demand (one-shot) model instead, as fit_per_demand reports
    it."""
    if demand_batches is not None:
        stray = [k for k, v in (("data", data), ("data_right", data_right), ("censored", censored),
                                ("counts", counts), ("trunc_left", trunc_left), ("trunc_right", trunc_right),
                                ("dataset_id", dataset_id), ("time_column", time_column),
                                ("time_right_column", time_right_column), ("censor_column", censor_column),
                                ("count_column", count_column), ("trunc_left_column", trunc_left_column),
                                ("trunc_right_column", trunc_right_column), ("covariates", covariates),
                                ("method", method)) if v is not None]
        if stray:
            raise ToolError(f"{', '.join(stray)} don't apply to a per-demand model — drop them.")
        return _save_per_demand(ctx, name, demand_batches, demand_confidence)
    return _fit(ctx, distribution=distribution, data=data, data_right=data_right, censored=censored,
                counts=counts, trunc_left=trunc_left, trunc_right=trunc_right, c_invert=c_invert,
                dataset_id=dataset_id, time_column=time_column, time_right_column=time_right_column,
                censor_column=censor_column, count_column=count_column, trunc_left_column=trunc_left_column,
                trunc_right_column=trunc_right_column, covariates=covariates, method=method, unit=unit,
                save=True, name=name)


def _per_demand_summary(result: dict) -> dict:
    """A per-demand result for an MCP caller (#233)."""
    d = result.get("per_demand") or {}
    c = d.get("confidence", 0.95)
    out = {
        "kind": "per_demand",
        "demands": d.get("demands"),
        "failures": d.get("failures"),
        "p": d.get("p"),
        "reliability": d.get("reliability"),
        "confidence": c,
        "bounds_method": "exact (Clopper-Pearson)",
        "p_interval": d.get("ci"),
        "reliability_interval": d.get("reliability_ci"),
        "p_upper_one_sided": d.get("p_upper"),
        "reliability_lower_one_sided": d.get("reliability_lower"),
        "note": (f"p is the failure probability per demand, pooled over every batch (assumes one p for all). "
                 f"The intervals are two-sided at {c:.0%}; the one-sided bounds are at {c:.0%} too, "
                 f"e.g. reliability per demand is at least {d.get('reliability_lower', 0):.4g} with "
                 f"{c:.0%} confidence."),
    }
    if d.get("batches"):
        out["batches"] = d["batches"]
    if d.get("success_run"):
        out["success_run"] = {**d["success_run"], "note": (
            "Zero failures: a success-run demonstration. reliability_lower is the demonstrated reliability "
            "per demand, R >= (1 - C)^(1/n).")}
    return out


def _demand_rows(batches, dataset_id, demands_column, failures_column, batch_column, uid) -> list[dict]:
    if (batches is None) == (dataset_id is None):
        raise ToolError("Give either `batches` (a list of {demands, failures}) or a `dataset_id` — exactly one.")
    if batches is not None:
        if demands_column or failures_column or batch_column:
            raise ToolError("The *_column arguments only apply with dataset_id — drop them, or switch to it.")
        return [b.model_dump() for b in batches]
    dataset = datasets_service.get_dataset(_db(), dataset_id, uid)
    if dataset is None:
        raise ToolError("Dataset not found.")
    names = [c["name"] for c in dataset.columns]
    if not (demands_column and failures_column):
        raise ToolError("Say which columns hold the demands and the failures (demands_column, "
                        f"failures_column). Columns: {', '.join(names)}.")
    for col in (demands_column, failures_column, batch_column):
        if col and col not in names:
            raise ToolError(f"Column '{col}' isn't in the dataset. Columns: {', '.join(names)}.")
    return fitting.per_demand_batches_from_df(
        datasets_service.load_dataframe(dataset), demands_column, failures_column, batch_column)


@_tool("fit_per_demand", _READ, "Per-demand reliability")
def fit_per_demand(
    ctx: Context,
    batches: _DemandBatches = None,
    dataset_id: Annotated[Optional[str], Field(
        description="A saved dataset with one row per batch, instead of `batches`.")] = None,
    demands_column: Annotated[Optional[str], Field(description="Dataset column of demands per batch.")] = None,
    failures_column: Annotated[Optional[str], Field(description="Dataset column of failures per batch.")] = None,
    batch_column: Annotated[Optional[str], Field(description="Optional dataset column naming each batch.")] = None,
    confidence: _DemandConfidence = 0.95,
) -> dict[str, Any]:
    """Per-demand (one-shot) reliability — a relief valve that must open, an igniter, a standby start — from
    one or several batches of demands and failures (sites, lots of different sizes, test campaigns). Reports
    the failure probability per demand p and the reliability per demand 1 - p, pooled over every batch, with
    EXACT (Clopper-Pearson) bounds at `confidence`: the two-sided interval and the one-sided bound. With zero
    failures the one-sided bound is the success-run demonstration (59 clean demands show 95% reliability at
    95% confidence). Saves nothing — to keep it, call fit_and_save_model with demand_batches."""
    uid = _caller(ctx)["uid"]
    rows = _demand_rows(batches, dataset_id, demands_column, failures_column, batch_column, uid)
    result = fitting.result_per_demand(confidence=confidence, batches=rows)
    return {"saved": False, **_per_demand_summary(result)}


def _save_per_demand(ctx: Context, name: str, batches: list, confidence: float) -> dict[str, Any]:
    user, db = _caller(ctx), _db()
    name = (name or "").strip()
    if not name:
        raise ToolError("A `name` is required to save the model.")
    _cap(db, user, "models", "models")
    model = models_service.create_per_demand(db, user["uid"], name, confidence=confidence,
                                             batches=[b.model_dump() for b in batches])
    return {"saved": True, "model_id": model.id, "name": model.name,
            "url": _url(f"/modelling/m/{model.id}"), **_per_demand_summary(model.results or {})}


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
    names = list(getattr(entry["dist"], "parameter_names", []) or [])

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
        live = entry["dist"].from_params([given[n] for n in names], **fitting.surpyval_extras(extras))
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


# ---- confidence bounds for reliability_at (#134) -------------------------------
# The app's band (POST /api/models/{id}/confidence) is SurPyval's ``model.cb``
# on the live fit — Fisher-matrix (Wald / delta-method) bounds. The same call
# here, but at the requested times themselves rather than on the plot grid, so
# nothing is interpolated. Where there's no covariance to propagate, no bounds:
# never invented ones.

def _cb_pairs(cb) -> list:
    arr = np.asarray(cb, dtype=float).reshape(-1, 2)
    return [[_finite(lo), _finite(hi)] for lo, hi in arr]


def _reliability_bounds(db, m, ts: list[float], owners, ev: dict, confidence: float):
    """``(reliability_bounds, failure_bounds, note)`` at ``ts`` — both lists of
    ``[lower, upper]``, or both None with the note saying why."""
    level = f"{confidence * 100:g}%"
    results = m.results or {}
    dist_id = results.get("distribution_id") or m.distribution_id
    if dist_id == fitting.MIXTURE_ID:
        return None, None, f"No {level} bounds: a mixture fit has no covariance matrix to base them on."
    if m.kind == "nonparametric":
        return None, None, (f"No {level} bounds: this is a non-parametric model, whose values here are "
                            "interpolated on its stored curve, so bounds at exactly these times wouldn't match "
                            "them. The app's calculator draws its pointwise band.")
    if (m.spec or {}).get("params_only"):
        return None, None, (f"No {level} bounds: this model was saved from parameters alone, without the data "
                            "they were fitted to, so there's no covariance matrix to base them on. Save it "
                            "with its data (or fit it in Reliafy) for bounds.")
    if m.kind not in ("distribution", "discrete", "regression") or ev["method"] != "exact":
        return None, None, f"No {level} bounds: confidence bounds aren't available for this {m.kind} model."
    try:
        entry = fitting._MODEL_STORE.get(models_service._live_cache_id(db, m.id, owners))
    except (models_service.ModelNotFound, fitting.ModelNotFound, FitError):
        entry = None
    live = (entry or {}).get("model")
    if live is None:
        return None, None, (f"No {level} bounds: the data this model was fitted to is no longer available, "
                            "so its covariance can't be recovered.")
    if not hasattr(live, "cb"):
        return None, None, (f"No {level} bounds: this model type ({results.get('distribution') or dist_id}) "
                            "doesn't provide covariance-based confidence bounds.")
    t = np.asarray(ts, dtype=float)
    alpha = 1.0 - confidence
    args = (t,)
    if m.kind == "regression":
        args = (t, pd.DataFrame({c["name"]: [c["value"]] for c in ev.get("covariates") or []}))
    try:
        with np.errstate(all="ignore"):
            r = _cb_pairs(live.cb(*args, on="sf", alpha_ci=alpha, bound="two-sided"))
            f = _cb_pairs(live.cb(*args, on="ff", alpha_ci=alpha, bound="two-sided"))
    except Exception as exc:  # noqa: BLE001 - e.g. no covariance (singular fit), non-MLE fit
        reason = str(exc).strip() or type(exc).__name__
        return None, None, f"No {level} bounds: SurPyval can't compute them for this fit ({reason})."
    note = (f"reliability_bounds / failure_bounds are two-sided {level} Fisher-matrix (Wald / delta-method) "
            "confidence bounds from the fit's covariance — the same method as the app's confidence band — "
            "computed at exactly these times.")
    if m.kind == "regression":
        note += (" For this proportional-hazards model they're at the covariate values used; the app's "
                 "calculator doesn't draw a band for these models.")
    return r, f, note


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
    confidence: Annotated[Optional[float], Field(
        gt=0, lt=1, description="Optional two-sided confidence level, e.g. 0.9 or 0.95. Adds reliability_bounds "
                                "and failure_bounds [lower, upper] at each time (the app's Fisher-matrix "
                                "confidence bounds); null, with bounds_note saying why, where the model has "
                                "none.")] = None,
) -> dict[str, Any]:
    """Evaluate a saved life model at given times: reliability R(t) (probability of surviving to t),
    failure probability F(t) = 1 − R(t), hazard rate h(t), cumulative hazard H(t) and density f(t).
    Optionally conditional on a unit already having survived to `conditional_age`. Parametric models are
    evaluated exactly from the distribution (method=exact); non-parametric and mixture models are
    interpolated on their stored curve (method=interpolated). Proportional-hazards models report the
    covariate values used (the fit's defaults for any not given). With `confidence` (e.g. 0.95), each
    time also gets two-sided confidence bounds on R(t) and F(t) — quote those alongside the point values;
    models without a covariance (non-parametric, mixtures, parameters saved without data) get null bounds
    and a bounds_note saying why."""
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
    if confidence is not None:
        r_bounds, f_bounds, bounds_note = _reliability_bounds(
            db, m, ts, owners, ev, float(confidence))
        for i, p in enumerate(points):
            p["reliability_bounds"] = r_bounds[i] if r_bounds else None
            p["failure_bounds"] = f_bounds[i] if f_bounds else None
        out["confidence"] = float(confidence)
        out["bounds_note"] = bounds_note
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
    csv: Annotated[Optional[str], Field(min_length=1, description=(
        "The CSV text, header row first. Tab- or semicolon-separated pastes are accepted too. For a file, "
        "use upload_id instead."))] = None,
    upload_id: Annotated[Optional[str], Field(description=(
        "Instead of csv: a file sent through create_upload (CSV/TSV, or an .xlsx workbook with sheet)."))] = None,
    sheet: Annotated[Optional[str], Field(description=(
        "With an .xlsx upload_id: the sheet to read (needed when the workbook has several; inspect_upload "
        "lists them)."))] = None,
) -> dict[str, Any]:
    """Save a dataset to the user's workspace and return its id and columns: CSV text in csv, or a file
    uploaded with create_upload in upload_id. A censoring column should use 0 = failed, 1 = still running,
    -1 = left-censored (or flag c_invert when fitting)."""
    user, db = _caller(ctx), _db()
    if (csv is None) == (upload_id is None):
        raise ToolError("Give either csv (text) or upload_id (a file sent through create_upload) — exactly one.")
    _cap(db, user, "datasets", "datasets")
    upload = None
    if upload_id is not None:
        upload, text = _upload_table_text(db, user["uid"], upload_id, sheet)
    else:
        text = csv
    ds = datasets_service.create_dataset(db, name.strip(), datasets_service.normalize_pasted(text), user["uid"])
    if upload is not None:
        uploads_service.delete(db, upload["_id"])
    return {"id": ds.id, "name": ds.name, "n_rows": ds.n_rows, "columns": [c["name"] for c in ds.columns],
            "preview": datasets_service.preview_rows(ds, 5), "url": _url(f"/datasets/d/{ds.id}")}


# ---- get_dataset (#135): a dataset's rows, a page at a time --------------------

_DATASET_PAGE_MAX = 500


def _cell(v):
    """One dataset value as plain JSON: numbers as numbers, blanks as null."""
    if v is None or (isinstance(v, float) and not np.isfinite(v)):
        return None
    if isinstance(v, (bool, np.bool_)):
        return bool(v)
    if isinstance(v, (int, np.integer)):
        return int(v)
    if isinstance(v, (float, np.floating)):
        return _finite(v)
    try:
        if pd.isna(v):
            return None
    except (TypeError, ValueError):
        pass
    return str(v)


@_tool("get_dataset", _READ, "Read a dataset")
def get_dataset(
    ctx: Context,
    dataset_id: Annotated[str, Field(description="A dataset id (list_datasets) — the user's own or a shared sample.")],
    offset: Annotated[int, Field(ge=0, description="First row to return (0-based).")] = 0,
    limit: Annotated[int, Field(ge=1, le=_DATASET_PAGE_MAX,
                                description=f"Rows to return, at most {_DATASET_PAGE_MAX}.")] = 50,
) -> dict[str, Any]:
    """Read a saved dataset: its name and notes, columns with their types, the total row_count, and a slice
    of rows (`offset`, `limit` ≤ 500) as lists in column order. Page through a large dataset with
    next_offset; summarise rather than reading every row when you don't need them all."""
    user, db = _caller(ctx), _db()
    ds = datasets_service.get_dataset(db, dataset_id, _owners(user["uid"]))
    if ds is None:
        raise ToolError("Dataset not found.")
    df = datasets_service.load_dataframe(ds)
    total = int(df.shape[0])
    page = df.iloc[offset:offset + limit]
    rows = [[_cell(v) for v in row] for row in page.itertuples(index=False, name=None)]
    end = offset + len(rows)
    out = {
        "id": ds.id,
        "name": ds.name,
        "is_sample": samples_service.is_sample(ds.owner_id),
        "columns": [{"name": str(c), "dtype": str(df[c].dtype)} for c in df.columns],
        "row_count": total,
        "offset": offset,
        "rows": rows,
        "next_offset": end if end < total else None,
        "url": _url(f"/datasets/d/{ds.id}"),
    }
    if ds.notes:
        out["notes"] = ds.notes
    if offset >= total and total:
        out["note"] = f"offset {offset} is past the last row (the dataset has {total} rows)."
    return out


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
    saved_model_id: Optional[str] = Field(None, description=(
        "A saved life model id (list_models) instead of inline params: a parametric (or proportional-hazards) "
        "model, not a non-parametric one (Kaplan-Meier etc.), which RBD blocks don't take."))
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


class DiagramCosts(BaseModel):
    """A repairable diagram's own costs (#99, #219); 0 clears a field."""
    model_config = ConfigDict(extra="forbid")
    downtime_rate: Optional[float] = Field(None, ge=0, description=(
        "Cost per unit time (diagram unit) the WHOLE system is down: lost production."))
    horizon: Optional[float] = Field(None, ge=0, description=(
        "How long the system is owned (diagram unit), for the total cost of ownership; e.g. 87600 h = 10 years."))
    discount_rate: Optional[float] = Field(None, ge=0, le=100, description=(
        "Percent a year, e.g. 7 for 7% (not 0.07): the total cost of ownership is then a present value. Needs a "
        "calendar time unit (hours … years)."))


class RbdNode(BaseModel):
    id: str = Field(description="Unique node id. The diagram needs exactly one 'input' and one 'output' node.")
    type: Literal["input", "output", "component", "series", "parallel", "knode", "standby", "subsystem"] = Field(
        description="component = one block; series/parallel = n identical blocks sharing one model; knode = "
                    "k-of-n voting gate (n = required, k = branches feeding it); standby = spare(s) idle until "
                    "the running unit fails (repairable: identical units, each repaired after it fails); "
                    "subsystem = embed a saved RBD. Repairable diagrams take component, standby and knode (a vote "
                    "can sit anywhere, e.g. two 2-of-3 stages in series).")
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
    common_cause_basis: Optional[Literal["rate", "probability"]] = Field(None, description=(
        "With common_cause_beta: what beta is a fraction of. 'rate' (default) splits each member's failure rate "
        "and holds over the whole life; 'probability' is the PRA basic-event split, only for small failure "
        "probabilities (a short mission or proof-test interval) — over a lifetime it overstates the group's "
        "reliability and analyze_rbd gives no MTTF."))


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
    _check_graph_refs(db, user, graph)
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
    costs: Optional[DiagramCosts] = Field(None, description=(
        "Repairable: the diagram's downtime cost, ownership horizon and discount rate; fields left out are kept."))


class AddCcfOp(_Op):
    op: Literal["add_ccf"]
    members: list[str] = Field(min_length=2, description="2+ component block ids not already in a group.")
    beta: float = Field(description="Beta factor: shared-cause fraction of each member's failures, 0 < beta < 1.")
    basis: Optional[Literal["rate", "probability"]] = Field(None, description=(
        "What beta is a fraction of: 'rate' (default) splits each member's failure rate and holds over the whole "
        "life; 'probability' is the PRA basic-event split, for small failure probabilities only (a short mission "
        "or proof-test interval) — over a lifetime it overstates the group's reliability and gives no MTTF."))
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
    _check_graph_refs(db, user, graph)
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
      safety_function?, target_sil? (0 clears), costs? {downtime_rate?, horizon?, discount_rate? (% a year); 0
      clears}}
    - add_ccf {members, beta, basis?, id?} / remove_ccf {id} — common-cause (beta-factor) groups (basis 'rate',
      the default, for lifetime analysis); in a repairable diagram they enter a safety function's PFDavg.
    Removing a node drops it from its common-cause group (and the group if under 2 members remain).
    Changing connections re-lays out the diagram automatically. Returns one line per op, the validation
    warnings this edit introduced (warnings_unchanged counts the rest), the node ids, and simulation_note when
    the edit puts the diagram's saved availability simulation out of date; read the full graph with get_rbd."""
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
    try:
        _check_graph_refs(db, user, graph, keep_graph=rbd.graph or {})
    except access_service.UnreadableReference as exc:
        raise ToolError(f"Nothing was saved — {exc}") from None
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
    # A saved availability simulation that matched the diagram before this
    # edit no longer does: say so once, briefly.
    saved_sim = db.rbds.find_one({"_id": rbd.id}, {"availability_cache": 1})
    if rbds_service.availability_outdated_by(saved_sim, rbd.graph or {}, graph, db, owners):
        out["simulation_note"] = (
            ("Saving this edit would put" if dry_run else "This edit puts")
            + " the saved availability simulation out of date; analyze_rbd gives the exact figures, "
            "simulate=true re-runs it.")
    return out


def _downsample(xs, ys, n: int = 21) -> list[dict]:
    if not xs:
        return []
    idx = sorted({round(i * (len(xs) - 1) / (n - 1)) for i in range(n)})
    return [{"t": _finite(xs[i]), "reliability": _finite(ys[i])} for i in idx]


def _labelled(values: dict, labels: dict) -> dict:
    return {labels.get(k, k): v for k, v in (values or {}).items()}


def _ccf_summary(result: dict, include_curves: bool) -> dict:
    """The common-cause impact for an agent (#214): the groups and the
    reliability with and without them at the importance time; the curve
    without them, as {t, reliability} at the times of `curve`, only on
    request (the app's result carries it as bare values)."""
    ccf = {k: v for k, v in result["ccf"].items() if k != "baseline_sf"}
    if include_curves:
        ccf["curve_without"] = _downsample(result.get("time") or [], result["ccf"].get("baseline_sf") or [])
    else:
        ccf["curve_omitted"] = "Pass include_curves=true for the reliability curve without common cause."
    return ccf


def _reliability_summary(result: dict, graph: dict, times: list[float] | None,
                         include_curves: bool = False) -> dict:
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
        out["ccf"] = _ccf_summary(result, include_curves)
    out.update(_as_of_now_summary(result, labels))
    return out


def _as_of_now_summary(result: dict, labels: dict) -> dict:
    """A non-repairable result's as-of-now and design-life parts (#173): the
    state it ran from (with block labels), the reliability now, the design
    life and, when asked for, the confidence intervals from the fitted blocks."""
    out: dict = {}
    if result.get("current_state"):
        out["current_state"] = {
            nid: {**v, "label": labels.get(nid, nid)} for nid, v in result["current_state"].items()}
        out["reliability_now"] = result.get("reliability_now")
        out["from"] = "now"
        if result.get("mean_residual_life"):
            # The mean remaining life from now (#221), exact where RePyability gives it.
            out["mean_residual_life"] = result["mean_residual_life"]
    if result.get("design_life"):
        out["design_life"] = result["design_life"]
    band = result.get("band")
    if band:
        out["confidence"] = {
            "level": band.get("level"), "n_draws": band.get("n_draws"),
            "mttf": band.get("mttf"), "b_life": band.get("blife"),
            **({"design_life": band["design_life"]} if "design_life" in band else {}),
            "uncertain_blocks": [b.get("label") for b in band.get("uncertain") or []],
            "fixed_blocks": [{"label": b.get("label"), "reason": b.get("reason")}
                             for b in band.get("fixed") or []],
        }
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
            "failure_frequency", "figures_basis", "has_simulation", "n_simulations", "t_simulation", "quick",
            "precision",
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
    if result.get("next_failure") and result.get("has_simulation", True):
        out.update(_next_failure_summary(result["next_failure"]))
    costs = _costs_summary(result.get("costs"))
    if costs:
        out["costs"] = costs
    return out


_COST_KEYS = ("cost_rate", "cost_rate_basis", "downtime_cost_rate", "by_category", "acquisition_cost", "horizon",
              "horizon_basis", "running_cost", "total_cost", "discount_rate", "discount_rate_per_unit",
              "undiscounted_total_cost")


def _costs_summary(costs: dict | None) -> dict | None:
    """The cost of ownership for an agent (#99, #219): the long-run cost rate
    and its categories, the total over the horizon — a present value when
    discounted — the ten costliest blocks, and the window's cost."""
    if not costs:
        return None
    out = {k: costs[k] for k in _COST_KEYS if costs.get(k) is not None}
    out["present_value"] = bool(costs.get("discount_rate"))
    if out.get("by_category"):
        out["by_category"] = {k: v for k, v in out["by_category"].items() if v}
    blocks = [{k: b.get(k) for k in ("id", "label", "rate", "cost_share", "acquisition")}
              for b in costs.get("blocks") or []]
    if blocks:
        out["blocks"] = blocks[:10]
    sim = costs.get("simulated")
    if sim:
        out["window_cost"] = {k: sim.get(k) for k in ("mean", "mean_basis", "t_simulation", "percentiles")}
    return out


def _next_failure_summary(nf: dict) -> dict:
    """As of now with the simulation (#220, #221): the time to the next
    system failure from the blocks' states — its mean (the mean residual
    life), percentiles, P(failure) at 21 times and the blocks that cause it."""
    curve = nf.get("curve") or {}
    points = _downsample(curve.get("t") or [], curve.get("cdf") or [])
    keys = ("window", "n_simulations", "down_now", "failed_share", "mean", "mean_is_lower_bound", "mean_lower",
            "mean_upper", "confidence", "percentiles", "time_limited")
    out = {"method": "simulated", **{k: nf.get(k) for k in keys if k in nf},
           "p_failed_by": [{"t": p["t"], "p": p["reliability"]} for p in points],
           "causes": [{k: c.get(k) for k in ("label", "count", "share")} for c in nf.get("causes") or []]}
    mrl = {"value": nf.get("mean"), "method": "simulated", "lower": nf.get("mean_lower"),
           "upper": nf.get("mean_upper"), "lower_bound": bool(nf.get("mean_is_lower_bound"))}
    return {"next_failure": out, "mean_residual_life": mrl}


class BlockState(BaseModel):
    failed: Optional[bool] = Field(None, description=(
        "Non-repairable: true if the block has failed (it stays failed)."))
    down: Optional[bool] = Field(None, description="True: the block is down now (in a repair).")
    since: Optional[float] = Field(None, ge=0, description=(
        "With down: how long it has been down so far (diagram unit; 0 = just failed)."))
    age: Optional[float] = Field(None, ge=0, description=(
        "A running block: time since it was new or last renewed (diagram unit)."))


def _await_job(db, job_id: str, wait_s: float) -> Optional[dict]:
    """Poll a queued job's record until it finishes or ``wait_s`` passes."""
    deadline = time.monotonic() + max(float(wait_s), 0.0)
    delay = 0.5
    while True:
        job = rbd_jobs_service.get(db, job_id)
        if job is None or job.get("status") in rbd_jobs_service.FINISHED:
            return job
        left = deadline - time.monotonic()
        if left <= 0:
            return job
        time.sleep(min(delay, left))
        delay = min(delay * 1.5, 2.0)


def _job_pending(db, job: dict) -> dict:
    return {
        "job_id": job["_id"],
        "status": job.get("status"),
        "queue_position": rbd_jobs_service.queue_position(db, job),
        "note": "The simulation is queued or running on Reliafy's calculation service. Call get_job with "
                "this job_id in a few seconds for the result.",
    }


@_tool("analyze_rbd", _READ, "Analyse an RBD")
def analyze_rbd(
    ctx: Context,
    rbd_id: Annotated[str, Field(description="An RBD id from list_rbds or create_rbd.")],
    times: Annotated[Optional[list[float]], Field(max_length=200, description=(
        "Non-repairable: times (diagram unit) to report system reliability at."))] = None,
    t_max: Annotated[Optional[float], Field(description=(
        "Non-repairable: end of the time axis (default sized to the system; with current_state, to its "
        "remaining life). Repairable: the window and simulated horizon (default long enough to settle; with "
        "current_state, sized to the blocks' remaining life)."))] = None,
    conditional_age: Annotated[Optional[float], Field(description=(
        "Non-repairable: condition on the system having already survived to this age."))] = None,
    recompute: Annotated[bool, Field(description=(
        "Repairable: re-run the simulation even when a saved result matches (paid feature)."))] = False,
    simulate: Annotated[bool, Field(description=(
        "Repairable: also run the Monte-Carlo simulation (paid: Pro or credits) for distributions, "
        "P(no outage), percentiles and criticality. False = the exact figures only (faster). Ignored "
        "without entitlement: the exact figures come anyway."))] = True,
    current_state: Annotated[Optional[dict[str, BlockState]], Field(description=(
        "Blocks' states now, keyed by node id; blocks left out are new. Repairable: {down: true, since: "
        "<time into the repair>} or {age: <time since new>}; the figures then run from now over t_max "
        "(e.g. the next 720 hours); with the simulation, next_failure gives the time to the next system "
        "failure from now (its mean is mean_residual_life) and the blocks that cause it. Never replaces the "
        "saved from-new result. Non-repairable: {failed: "
        "true} or {age: <time it has run>} on component blocks; the reliability curve, MTTF, B-lives and "
        "design life are then the remaining life from now (mean_residual_life: exact)."))] = None,
    compute_exact: Annotated[bool, Field(description=(
        f"Repairable diagrams over {rbd_analysis.EXACT_AUTO_MAX_BLOCKS} blocks: compute the exact figures "
        "over time anyway (from several seconds to a minute or so)."))] = False,
    target_reliability: Annotated[Optional[float], Field(gt=0, lt=1, description=(
        "Non-repairable: the design life at this reliability, e.g. 0.9 — the time the system reliability "
        "falls to it (from now with current_state)."))] = None,
    confidence: Annotated[Optional[float], Field(ge=0.5, lt=1, description=(
        "Non-repairable: also give confidence intervals at this level (e.g. 0.9) on the MTTF, B-lives and "
        "design life, from the parameter uncertainty of blocks that use saved fitted models."))] = None,
    include_curves: Annotated[bool, Field(description=(
        "Non-repairable with common-cause groups: also return ccf.curve_without, the system reliability without "
        "the groups at the times of `curve`. Off by default to keep the answer small."))] = False,
    discount_rate: Annotated[Optional[float], Field(ge=0, le=100, description=(
        "Repairable with costs: price costs.total_cost as a present value at this percent a year (7 = 7%; 0 = "
        "undiscounted) instead of the diagram's own discount rate. Nothing is saved or re-run."))] = None,
) -> dict[str, Any]:
    """Analyse a saved RBD. Non-repairable diagrams: system reliability curve, MTTF, B-lives (B10/B50),
    component importance (Birnbaum, Fussell–Vesely, RAW/RRW) and minimal cut/path sets — from new, or from
    now with current_state (failed and aged blocks: the remaining life); target_reliability adds the design
    life (the time to that reliability) and confidence adds intervals from fitted blocks. Repairable
    diagrams, on every plan: the exact long-run availability, mean up/down time and failure frequency, how
    the long-run values were found (long_run_method: exact / numerical / simulated, e.g. the repair crews'
    Markov chain), the repair crews, for a safety function its PFDavg and SIL band (safety), and (in
    `exact`) the availability over time A(t), mission availability and the window's expected system
    failures, outages, downtime and cost — each with its method (exact / numerical; no simulation) — from
    new or from current_state. A priced diagram adds `costs`: the long-run cost rate, and the total cost of
    ownership over its horizon (a present value when discounted: discount_rate, or the diagram's own, set
    with edit_rbd's set costs). The Monte-Carlo simulation (distributions, criticality; from current_state,
    next_failure and mean_residual_life: the time to the next system failure and its cause) is a paid feature
    (Pro or purchased credits): a saved result is always served; otherwise, without entitlement, the
    response carries `simulation: {available: false, message}` — relay it, and offer export_rbd_python to
    run the simulation locally. A diagram whose figures are simulation-only (exact.status
    'simulation_only', e.g. limited repair crews for wear-out lives) returns available=false without entitlement; asked
    with simulate=false (and no saved result matching the diagram as it is now) it returns available=false,
    needs_simulation=true, code 'needs_simulation' and a reason naming what needs the simulation, with no
    figure fields — call again with simulate=true (Pro or credits) or offer export_rbd_python."""
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
    if graph.get("repairable") and (target_reliability is not None or confidence is not None):
        raise ToolError("target_reliability and confidence apply to non-repairable diagrams; this one is "
                        "repairable (analysed for availability).")
    if discount_rate is not None and not graph.get("repairable"):
        raise ToolError("discount_rate prices a repairable diagram's total cost of ownership; this diagram is "
                        "non-repairable (analysed for reliability) and has no costs.")
    if current_state and conditional_age and not graph.get("repairable"):
        raise ToolError("Give either conditional_age (the whole system's age) or current_state (each block's "
                        "state now), not both.")
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
                             read_owners=_owners(uid), list_owners=uid, share_fallback=False)
            state = ({nid: v.model_dump(exclude_none=True) for nid, v in current_state.items()}
                     if current_state else None)
            plan = user.get("mcp_plan", "pro")
            # quick=True: where the plan allows only quick runs (Free with
            # MCP_FREE_QUICK_SIMS on; off in production), an agent can't click
            # "Run quick simulation", so asking for the simulation is the click.
            # Entitled users get full runs.
            status, payload = availability_payload(db, actx, graph, t_max, rbd, recompute, owners,
                                                   simulate=simulate or recompute, current_state=state,
                                                   exact=compute_exact, quick=simulate or recompute,
                                                   surface="mcp")
            pending = None
            if status == 202:
                # Queued on the calculation service: wait a little, then hand
                # back a job id (the exact figures come now either way).
                job = _await_job(db, payload["job"]["job_id"], config.MCP_JOB_WAIT_S)
                if job is None:
                    raise ToolError("The simulation job was lost. Run analyze_rbd again.")
                if job.get("status") == "failed":
                    raise ToolError(job.get("error") or rbd_jobs_service.FAILED_ERROR)
                if job.get("status") == "done":
                    payload = rbd_jobs_service.view(db, job, billing_service.premium_compute_allowed(db, user))[
                        "result"]
                else:
                    pending = _job_pending(db, job)
                status = 200
            if status == 503:
                raise ToolError(payload.get("detail") or rbd_jobs_service.QUEUE_UNAVAILABLE)
            if status != 200:
                # A simulation-only diagram, without entitlement: nothing to give.
                if plan != "pro":
                    _soft_refusal("pro_only")
                message = _simulation_message(plan) if plan != "pro" else payload.get("detail")
                return {**head, "kind": "repairable", "available": False, "code": payload.get("code"),
                        "message": message}
            if pending is not None and not availability_answer.has_figures(payload):
                # Simulation-only diagram: nothing to show until the job is done.
                return {**head, "kind": "repairable", "available": False, **pending}
            if discount_rate is not None and payload.get("costs"):
                payload = {**payload, "costs": rbd_costs.with_discount(payload["costs"], graph, discount_rate)}
            out = {**head, "available": True, **_availability_summary(payload)}
            sim_state = (payload.get("simulation_status") or {}).get("state")
            if pending is not None:
                out["simulation"] = {"available": False, "state": pending["status"], **pending}
            elif sim_state == "pro_required" and (simulate or recompute):
                out["simulation"] = {
                    "available": False, "code": "pro_required",
                    "message": (_simulation_message(plan) if plan != "pro"
                                else (payload.get("simulation_status") or {}).get("message")),
                }
            else:
                out["simulation"] = {"available": bool(payload.get("has_simulation")), "state": sim_state}
            return availability_answer.finish(out, payload)

        state = ({nid: v.model_dump(exclude_none=True) for nid, v in current_state.items()}
                 if current_state else None)
        result = rbds_service.analyze_graph(db, graph, owners, t_max=t_max, conditional_age=conditional_age,
                                            at_times=times, current_state=state,
                                            target_reliability=target_reliability,
                                            band={"level": confidence} if confidence is not None else None)
        out = {**head, "available": True, **_reliability_summary(result, graph, times, include_curves)}
        if result.get("warnings"):
            # RePyability's common-cause warnings, and why the MTTF is missing (#210).
            out["warnings"] = list(dict.fromkeys([*(head.get("warnings") or []), *result["warnings"]]))
        return out
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


@_tool("get_job", _READ, "Check an analysis job")
def get_job(
    ctx: Context,
    job_id: Annotated[str, Field(description="A job_id returned by analyze_rbd.")],
) -> dict[str, Any]:
    """Check an analysis job that analyze_rbd queued (a long availability simulation runs on Reliafy's
    calculation service). status is queued (with queue_position: jobs ahead of it), running, done (with the
    same availability results analyze_rbd returns) or failed (with the reason in message). Call it every few
    seconds until done; jobs and their results are kept for a week."""
    user, db = _caller(ctx), _db()
    job = rbd_jobs_service.get(db, job_id)
    if job is None or job.get("uid") != user["uid"]:
        raise ToolError("Job not found.")
    out: dict[str, Any] = {"job_id": job["_id"], "status": job.get("status"), "kind": job.get("kind")}
    if job.get("rbd_id"):
        out["rbd_id"] = job["rbd_id"]
        out["url"] = _url(f"/rbds/b/{job['rbd_id']}")
    if job.get("status") == "done":
        view = rbd_jobs_service.view(db, job, billing_service.premium_compute_allowed(db, user))
        payload = view["result"]
        done = {**out, "available": True, **_availability_summary(payload),
                "simulation": {"available": True, "state": "done"}}
        return availability_answer.finish(done, payload)
    if job.get("status") == "failed":
        return {**out, "available": False, "message": job.get("error") or rbd_jobs_service.FAILED_ERROR}
    return {**out, "available": False, **_job_pending(db, job)}


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


@_tool("export_rbd_json", _READ, "Export an RBD as RePyability JSON")
def export_rbd_json(
    ctx: Context,
    rbd_id: Annotated[str, Field(description="An RBD id from list_rbds.")],
) -> dict[str, Any]:
    """Export a saved RBD in RePyability's JSON format: repyability.rbd.serialisation.rbd_from_json (or
    rbd_from_dict on the parsed JSON) rebuilds the RBD Reliafy analyses, to run or change in code, and
    import_rbd takes the file back without loss. Returns the filename, the JSON text (`json`) and what the
    RePyability part doesn't hold (`notes`: it rides in the file's "reliafy" part). Blocks on a fitted
    proportional-hazards, non-parametric or load-sharing model can't be exported — use export_rbd_python."""
    from backend.services import rbd_json

    user, db = _caller(ctx), _db()
    rbd = _get_rbd(db, user["uid"], rbd_id)
    try:
        filename, text = rbds_service.export_json(db, rbd.name, rbd.graph or {},
                                                  [*_owners(user["uid"]), rbd.owner_id])
    except rbd_json.ExportError as exc:
        raise ToolError(str(exc)) from None
    return {"filename": filename, "json": text, "notes": list(rbd_json.EXPORT_NOTES),
            "load": ("from repyability.rbd.serialisation import rbd_from_json; "
                     f"rbd = rbd_from_json(open({filename!r}).read())")}


@_tool("cheapest_design", _READ, "Cheapest redundancy of a repairable RBD")
def cheapest_design(
    ctx: Context,
    rbd_id: Annotated[str, Field(description="A repairable RBD id from list_rbds.")],
    horizon: Annotated[Optional[float], Field(gt=0, description=(
        "How long the system is owned (diagram unit); default the diagram's own horizon."))] = None,
    min_availability: Annotated[Optional[float], Field(gt=0, lt=1, description=(
        "Only designs at least this available in the long run, e.g. 0.9995."))] = None,
    blocks: Annotated[Optional[list[str]], Field(max_length=rbd_costs.MAX_BLOCKS, description=(
        "Component block ids that may be given copies; default every block with a purchase price."))] = None,
    discount_rate: Annotated[Optional[float], Field(ge=0, le=100, description=(
        "Percent a year (7 = 7%; 0 = undiscounted): the totals are present values and the design with the "
        "lowest is chosen. Default the diagram's own discount rate."))] = None,
) -> dict[str, Any]:
    """The redundancy that owns a repairable diagram at the lowest total cost (RePyability's
    allocate_redundancy, scored exactly): how many active, independently repaired copies of each priced block
    to fit, weighing each copy's purchase price and running costs against the system downtime (lost
    production) it saves, optionally keeping the long-run availability at least min_availability. Returns the
    design as drawn and the cheapest side by side (total cost, purchase, running cost rate, availability), the
    copies per block and the saving; the totals are present values when discounted. Needs block purchase prices
    and the diagram's downtime cost (edit_rbd: update_node costs.acquisition, set costs). Nothing is saved:
    add the copies with edit_rbd (add_node parallel_to), or open the diagram's Design tab to draw them. Pro
    (or purchased credits), as in the app."""
    user, db = _caller(ctx), _db()
    uid = user["uid"]
    rbd = _get_rbd(db, uid, rbd_id)
    graph = rbd.graph or {}
    head = {"rbd_id": rbd.id, "name": rbd.name, "url": _url(f"/rbds/b/{rbd.id}")}
    if not graph.get("repairable"):
        raise ToolError(f"“{rbd.name}” is non-repairable (analysed for reliability): the cheapest design prices "
                        "a repairable diagram's ownership. Its redundancy for reliability is the app's Design tab.")
    if not billing_service.premium_compute_allowed(db, user):
        _soft_refusal("pro_only")
        return {**head, "available": False, "code": "pro_required",
                "message": (f"The cheapest design is part of Reliafy Pro ({PRO_PRICE}; purchased AI credits "
                            f"unlock it too), as in the app — upgrade at {_billing_url()} (or call upgrade_link). "
                            "analyze_rbd's exact availability and cost figures stay free.")}
    owners = [*_owners(uid), rbd.owner_id]
    result = rbd_costs.cheapest_design(
        graph, lambda mid: models_service.get_live_model(db, mid, owners), horizon=horizon,
        min_availability=min_availability, blocks=blocks, discount_rate=discount_rate)
    keep = ("unit", "horizon", "min_availability", "discount_rate", "method", "max_copies", "current", "saving",
            "changed", "note")
    out = {**head, "available": True, **{k: result[k] for k in keep}}
    out["present_value"] = result["discount_rate"] is not None
    out["design"] = {k: v for k, v in result["design"].items() if k != "units"}
    return out


# ---------------------------------------------------------------------------
# Strategy calculators
# ---------------------------------------------------------------------------

def _dist_inputs(db, uid: str, model_id: str | None, distribution_id: str | None,
                 params: list[Param] | None, unit: str | None) -> dict:
    """distribution_id + params (+ the fit's extras), given inline or taken from a saved plain life model."""
    if model_id and (distribution_id or params):
        raise ToolError("Give exactly one of model_id or distribution_id + params, not both.")
    if model_id:
        m = models_service.get_model(db, model_id, _owners(uid))
        if m is None:
            raise ToolError("Model not found.")
        if m.kind != "distribution":
            raise ToolError(f"“{m.name}” is a {m.kind} model — the calculators need a plain life distribution.")
        r = m.results or {}
        # The fit's offset / LFP fraction / zero inflation, as the app's
        # calculators pass them: without them the answer is for another model.
        return {"distribution_id": r.get("distribution_id") or m.distribution_id, "params": _plain_params(r),
                "extras": r.get("extras") or None, "unit": unit or r.get("unit") or ""}
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


def _sig(x: Optional[float]) -> Optional[float]:
    return None if x is None else float(f"{x:.4g}")


def _weibull_beta_ci(db, uid: str, model_id: Optional[str], inputs: dict) -> Optional[tuple[float, float, float]]:
    """``(beta, lower, upper)``: a saved Weibull model's shape and its fit's 95%
    interval — None for inline params, another distribution, or a fit that
    gave β no interval."""
    if not model_id or inputs.get("distribution_id") != "weibull":
        return None
    m = models_service.get_model(db, model_id, _owners(uid))
    beta = next((p for p in ((m.results or {}).get("params") or []) if p.get("name") == "beta"), None) if m else None
    ci = (beta or {}).get("ci")
    if not ci or len(ci) != 2 or not all(isinstance(v, (int, float)) and math.isfinite(v) for v in ci):
        return None
    return float(beta["value"]), float(ci[0]), float(ci[1])


def _shape_uncertainty(db, uid: str, model_id: Optional[str], inputs: dict, costs: dict, point: dict) -> dict:
    """How far the replacement answer moves across a fitted Weibull's shape
    interval (#189): the optimum at each end of β's 95% CI, α held at its
    estimate. A point estimate can read as firm wear-out when the data only
    weakly show it — at β ≈ 1 preventive replacement doesn't pay. Only for a
    saved Weibull model whose fit gave β an interval; {} otherwise."""
    found = _weibull_beta_ci(db, uid, model_id, inputs)
    if found is None:
        return {}
    beta_hat, lo, hi = found

    def at(b: float) -> Optional[dict]:
        if b <= 0:
            return None
        params = [{**p, "value": b} if p["name"] == "beta" else p for p in inputs["params"]]
        try:
            r = strategy_store.compute("optimal_replacement", {**inputs, "params": params, **costs})
        except (StrategyError, ValueError):
            return None
        return {"beta": _sig(b), "beneficial": r["beneficial"], "optimal_time": _sig(r["optimal_time"]),
                "savings": _sig(r["savings"])}

    low, high = at(lo), at(hi)
    block = {"beta": _sig(beta_hat), "beta_ci_95": [_sig(lo), _sig(hi)],
             "held_fixed": "alpha at its estimate", "at_beta_lower": low, "at_beta_upper": high}
    out: dict[str, Any] = {"shape_uncertainty": block}
    if not point.get("beneficial"):
        return out
    if lo <= 1:
        out["uncertainty_note"] = (
            f"The shape's 95% interval [{lo:.3g}, {hi:.3g}] includes 1: the data don't clearly show wear-out. "
            "If failures are close to random, preventive replacement saves little or nothing — treat this "
            "recommendation as tentative and say so.")
    elif low is not None and (not low["beneficial"] or (low["savings"] or 0) < 0.5 * point["savings"]):
        saving = f"saves {low['savings']:.0%}" if low["beneficial"] else "doesn't pay"
        out["uncertainty_note"] = (
            f"The shape's 95% interval reaches down to {lo:.3g}: the data only weakly show wear-out. At that "
            f"end preventive replacement {saving} (vs {point['savings']:.0%} at the estimate), so the "
            "recommendation is less firm than the point estimate suggests — say so.")
    return out


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
    beneficial=false means run-to-failure is cheaper (e.g. no wear-out, or planned ≈ unplanned cost). For a
    saved Weibull model fitted to data, shape_uncertainty gives the answer at each end of the shape's 95%
    interval; relay uncertainty_note when present — the recommendation is then less firm than it reads."""
    user, db = _caller(ctx), _db()
    inputs = _dist_inputs(db, user["uid"], model_id, distribution_id, params, unit)
    costs = {"planned_cost": planned_cost, "unplanned_cost": unplanned_cost}
    out = strategy_store.compute("optimal_replacement", {**inputs, **costs})
    out.update(_shape_uncertainty(db, user["uid"], model_id, inputs, costs, out))
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
    trip, alarm, standby unit — at the target availability. For a saved Weibull model fitted to data,
    shape_uncertainty gives the interval at each end of the shape's 95% interval; relay uncertainty_note
    when present — the interval is then less certain than it reads, and the shorter one is the safe side."""
    user, db = _caller(ctx), _db()
    inputs = _dist_inputs(db, user["uid"], model_id, distribution_id, params, unit)
    target = {"target_availability": target_availability}
    out = strategy_store.compute("failure_finding", {**inputs, **target})
    out.update(_ffi_shape_uncertainty(db, user["uid"], model_id, inputs, target, out))
    return out


#: The failure-finding note: an end of the shape's interval asks for an
#: interval this much shorter than the estimate's (or more).
_FFI_SHORTER = 0.8


def _ffi_shape_uncertainty(db, uid: str, model_id: Optional[str], inputs: dict, target: dict,
                           point: dict) -> dict:
    """``optimal_replacement``'s shape treatment (#189) for the failure-finding
    interval: the interval at each end of a fitted Weibull's β 95% CI, α held
    at its estimate, and a note when either end asks for a test interval at
    least 20% shorter than the estimate's — testing less often than needed is
    the unsafe side for a hidden protective function. {} for inline params or
    a fit that gave β no interval."""
    found = _weibull_beta_ci(db, uid, model_id, inputs)
    if found is None:
        return {}
    beta_hat, lo, hi = found

    def at(b: float) -> Optional[dict]:
        if b <= 0:
            return None
        params = [{**p, "value": b} if p["name"] == "beta" else p for p in inputs["params"]]
        try:
            r = strategy_store.compute("failure_finding", {**inputs, "params": params, **target})
        except (StrategyError, ValueError):
            return None
        return {"beta": _sig(b), "interval": _sig(r["interval"]), "mttf": _sig(r["mttf"])}

    low, high = at(lo), at(hi)
    block = {"beta": _sig(beta_hat), "beta_ci_95": [_sig(lo), _sig(hi)],
             "held_fixed": "alpha at its estimate", "at_beta_lower": low, "at_beta_upper": high}
    out: dict[str, Any] = {"shape_uncertainty": block}
    ends = [e for e in (low, high) if e is not None and e["interval"] is not None]
    shortest = min(ends, key=lambda e: e["interval"], default=None)
    if shortest is not None and point.get("interval") and shortest["interval"] < _FFI_SHORTER * point["interval"]:
        u = f" {point['unit']}" if point.get("unit") else ""
        out["uncertainty_note"] = (
            f"Across the shape's 95% interval [{lo:.3g}, {hi:.3g}] the interval could need to be as short as "
            f"{shortest['interval']:.3g}{u} (β = {shortest['beta']:.3g}) vs {point['interval']:.3g}{u} at the "
            "estimate. For a protective function, testing too rarely is the unsafe side: say the interval is "
            "uncertain and consider the shorter one.")
    return out


def _lean_demonstration(out: dict) -> dict:
    """The demonstration plan without the app's plotting fields: the trade-off
    table as {row label: values by allowed failures}."""
    keep = ("method", "solve_for", "summary", "units", "test_time_per_unit", "total_test_time",
            "test_multiple", "failures", "unit", "consumer_risk", "pass_probability", "producer_risk",
            "producer_risk_target", "design_reliability", "design_mtbf", "assumptions")
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
    design_reliability: Annotated[Optional[float], Field(gt=0, lt=1, description="Optional: a good design's "
                                                                                 "true reliability, to report "
                                                                                 "its chance of passing (needed "
                                                                                 "with producer_risk).")] = None,
    unit: _UNIT = None,
    design_mtbf: Annotated[Optional[float], Field(gt=0, description="method='mtbf': a good design's true MTBF "
                                                                    "(needed with producer_risk).")] = None,
    producer_risk: Annotated[Optional[float], Field(gt=0, lt=1, description=(
        "Optional, e.g. 0.2: the most chance of FAILING the good design (design_reliability / design_mtbf). "
        "Plans the smallest test keeping BOTH risks (consumer's <= 1 - confidence, producer's <= this) and "
        "chooses the failures allowed itself (failures is ignored)."))] = None,
) -> dict[str, Any]:
    """Plan a reliability demonstration test: how many units to test, for how long, with how many failures
    allowed, to show reliability R over a mission at confidence C (success run / binomial; Weibayes with a
    known Weibull shape to trade test time for units; or an MTBF chi-squared test). With producer_risk and a
    good design's reliability (or MTBF), the plan keeps both the consumer's and the producer's risk (a
    success run alone often fails a good design). Returns a one-line plan, both risks, the assumptions and a
    units-vs-failures(-vs-test-length) trade-off table."""
    _caller(ctx)
    out = strategy_store.compute("demonstration_test", {
        "method": method, "reliability": reliability, "confidence": confidence, "mission_time": mission_time,
        "failures": failures, "test_multiple": test_multiple, "shape": shape, "units": units, "mtbf": mtbf,
        "design_reliability": design_reliability, "design_mtbf": design_mtbf, "producer_risk": producer_risk,
        "unit": unit or ""})
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
    recurrent-event model. Only a deteriorating system (growth shape beta > 1) has a finite optimum. For a
    Crow-AMSAA model fitted to data, shape_uncertainty gives the answer at each end of beta's 95% interval;
    relay uncertainty_note when present — the recommendation is then less firm than it reads."""
    user, db = _caller(ctx), _db()
    owners = _owners(user["uid"])
    if t_max is not None and (not np.isfinite(t_max) or t_max <= 0):
        raise ToolError(f"t_max must be a positive time; got {t_max:g}. Omit it to search automatically.")
    doc = recurrent_service.get_model(db, model_id, owners)
    if doc is None:
        raise ToolError("Recurrent model not found — optimal_overhaul needs a recurrent (repairable-system) "
                        "model id from list_models kind=recurrent.")
    live = recurrent_service.get_live_model(db, model_id, owners)
    out = recurrent_fit.optimal_overhaul(live, cost_repair, cost_overhaul, t_max=t_max)
    out.update(_overhaul_shape_uncertainty(db, doc, cost_repair, cost_overhaul, t_max, out))
    return _maybe_curve(out, include_curve)


def _overhaul_shape_uncertainty(db, doc, cost_repair: float, cost_overhaul: float, t_max: Optional[float],
                                point: dict) -> dict:
    """``optimal_replacement``'s shape treatment (#189) for the overhaul
    interval: the optimum at each end of a Crow-AMSAA fit's β 95% interval,
    α held at its estimate, and a note when the interval includes 1 (the data
    don't clearly show deterioration, and without it an overhaul never pays)
    or the saving at the lower end is under half the estimate's. Each end is
    the tool's own answer for that β — its saving against never overhauling
    over that end's horizon (``t_max``, else 3× its own interval), as the
    estimate's is. Never overhauling has no finite long-run cost when β > 1,
    so one shared horizon would favour whichever β it suits. {} for a model
    built from parameters or another model family."""
    found = recurrent_service.shape_interval(db, doc)
    if found is None:
        return {}
    alpha, (lo, hi) = found["alpha"], found["ci"]

    def at(b: float) -> Optional[dict]:
        if b <= 0:
            return None
        try:
            r = recurrent_fit.optimal_overhaul({"model_id": "crow_amsaa", "params": [alpha, b]}, cost_repair,
                                               cost_overhaul, t_max=t_max)
        except (fitting.FitError, ValueError):
            return None
        opt = r.get("optimal")
        return {"beta": _sig(b), "pays": opt is not None,
                "optimal_interval": _sig(opt["interval"]) if opt else None,
                "saving_pct": _sig(r.get("saving_pct")) if opt else None,
                "horizon": _sig((r.get("never_overhaul") or {}).get("horizon")) if opt else None}

    low, high = at(lo), at(hi)
    block = {"beta": _sig(found["beta"]), "beta_ci_95": [_sig(lo), _sig(hi)],
             "held_fixed": "alpha at its estimate", "at_beta_lower": low, "at_beta_upper": high}
    out: dict[str, Any] = {"shape_uncertainty": block}
    saving = point.get("saving_pct")
    if not point.get("optimal"):
        return out
    if lo <= 1:
        out["uncertainty_note"] = (
            f"The growth shape's 95% interval [{lo:.3g}, {hi:.3g}] includes 1: the data don't clearly show the "
            "system deteriorating. If its failure rate isn't rising, an overhaul doesn't pay — treat this "
            "interval as tentative and say so.")
    elif low is not None and saving and (not low["pays"] or (low["saving_pct"] or 0) < 0.5 * saving):
        what = f"saves {low['saving_pct']:.3g}%" if low["pays"] else "doesn't pay"
        out["uncertainty_note"] = (
            f"The growth shape's 95% interval reaches down to {lo:.3g}: the data only weakly show deterioration. "
            f"At that end overhauling {what} (vs {saving:.3g}% at the estimate), so the recommendation is less "
            "firm than the point estimate suggests — say so.")
    return out


@_tool("compare_groups", _READ, "Compare groups of life data")
def compare_groups(
    ctx: Context,
    dataset_id: _FitDataset = None,
    time_column: _FitTimeCol = None,
    group_column: Annotated[Optional[str], Field(description="Dataset column to split by (supplier, site, design "
                                                            "revision…); required with dataset_id.")] = None,
    censor_column: Annotated[Optional[str], Field(description="Dataset column of censoring flags: 0 = failed, "
                                                              "1 = still running (right-censored only: these "
                                                              "tests don't take -1).")] = None,
    count_column: _FitCountCol = None,
    cause_column: Annotated[Optional[str], Field(description="Optional dataset column naming each failure's "
                                                             "mode: adds Gray's test per mode (competing "
                                                             "risks).")] = None,
    data: _FitData = None,
    group: Annotated[Optional[list[str]], Field(description="Inline: the group label of each time in `data`.")] = None,
    censored: Annotated[Optional[list[int]], Field(description="Inline: 0 = failed, 1 = still running, per time "
                                                               "in `data` (right-censored only: these tests "
                                                               "don't take -1).")] = None,
    counts: _FitCounts = None,
    cause: Annotated[Optional[list[Optional[str]]], Field(description="Inline: each failure's mode (null for a "
                                                                      "unit still running), for Gray's "
                                                                      "test.")] = None,
    c_invert: Annotated[bool, Field(description=(
        "True when the censoring flags use the opposite convention (1 = failed, 0 = running); Reliafy flips "
        "them before the tests."))] = False,
    groups: Annotated[Optional[list[str]], Field(description="Only these groups, in this order (default: "
                                                             "all, at most 12).")] = None,
    reference: Annotated[Optional[str], Field(description="Group the RMST differences are measured from "
                                                          "(default: the first).")] = None,
    tau: Annotated[Optional[float], Field(gt=0, description="Horizon for the restricted mean survival time "
                                                            "(default and most: the shortest group's longest "
                                                            "time; a longer one is capped there).")] = None,
    unit: _FitUnit = None,
    include_curves: Annotated[bool, Field(description="Return each group's Kaplan–Meier curve too.")] = False,
) -> dict[str, Any]:
    """Is A better than B? Split life data by a column (or give a group per time) and compare the groups
    without fitting anything: the k-sample log-rank test (Gehan–Wilcoxon and Tarone–Ware alongside), each
    group's restricted mean survival time (average life over the first `tau`) with its 95% CI and the
    difference from the reference group, Gray's test per failure mode when cause_column (or `cause`) is
    given, and a one-sentence verdict to relay. Right-censored data only: 0 = failed, 1 = still running;
    c_invert=true when the data marks failures with 1. A small log-rank p (< 0.05) means the groups' lives
    differ."""
    user, db = _caller(ctx), _db()
    if (data is None) == (dataset_id is None):
        raise ToolError("Give either inline `data` (with `group`) or a `dataset_id` — exactly one.")
    url = None
    if data is not None:
        stray = [k for k, v in (("time_column", time_column), ("group_column", group_column),
                                ("censor_column", censor_column), ("count_column", count_column),
                                ("cause_column", cause_column)) if v]
        if stray:
            raise ToolError(f"{', '.join(stray)} only appl{'ies' if len(stray) == 1 else 'y'} with dataset_id.")
        if not data:
            raise ToolError("`data` is empty.")
        cols: dict[str, list] = {"x": list(data)}
        for key, values, label in (("g", group, "group"), ("c", censored, "censored"), ("n", counts, "counts"),
                                   ("e", cause, "cause")):
            if values is not None:
                if len(values) != len(data):
                    raise ToolError(f"`{label}` must have one entry per time in `data` ({len(data)}).")
                cols[key] = list(values)
        if "g" not in cols:
            raise ToolError("Give `group`: the group label of each time in `data`.")
        df = pd.DataFrame(cols)
        time_column, group_column = "x", "g"
        censor_column = "c" if censored is not None else None
        count_column = "n" if counts is not None else None
        cause_column = "e" if cause is not None else None
        label = None
    else:
        stray = [k for k, v in (("group", group), ("censored", censored), ("counts", counts), ("cause", cause))
                 if v is not None]
        if stray:
            raise ToolError(f"{', '.join(stray)} only appl{'ies' if len(stray) == 1 else 'y'} with inline data.")
        dataset = datasets_service.get_dataset(db, dataset_id, _owners(user["uid"]))
        if dataset is None:
            raise ToolError("Dataset not found.")
        names = [c["name"] for c in dataset.columns]
        if not time_column or not group_column:
            raise ToolError("Say which column holds the times (time_column) and which to split by "
                            f"(group_column). Columns: {', '.join(names)}.")
        df = datasets_service.load_dataframe(dataset)
        label = group_column
        url = _url(f"/datasets/d/{dataset.id}?compare={quote(group_column)}")
    prepared = compare_groups_service.prepare(
        df, time_column=time_column, group_column=group_column, censor_column=censor_column,
        count_column=count_column, cause_column=cause_column, c_invert=c_invert,
        # Inline data: errors name the arguments, not the frame's columns (#211).
        names={"c": "`censored`", "n": "`counts`"} if data is not None else None)
    result = compare_groups_service.compare_groups(
        prepared, groups=groups, reference=reference, tau=tau, unit=unit, group_column=label)
    verdict = result["verdict"]
    out = {"verdict": verdict["text"], "significant": verdict["significant"], "longest_lasting": verdict["better"],
           **{k: v for k, v in compare_groups_service.lean(result, include_curves).items() if k != "verdict"}}
    if url:
        out["url"] = url
    return out


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
    csv: Annotated[Optional[str], Field(min_length=1, description=(
        "The outage log as CSV text, header row first (tab- or semicolon-separated also accepted): one row per "
        "outage with the asset, its start and its end (blank = still down). For a file, use upload_id."))] = None,
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
        "(get_rbd lists the nodes). Several assets may map to one standby, parallel/series count or "
        "load-sharing block: each is one of its units, and the block is down only while too few units are up. "
        "Pick a unit with 'node#2' (an asset that replaced another shares its unit), or 'node#all' for an "
        "asset that stands for the whole block."))] = None,
    name: Annotated[Optional[str], Field(description="A name for the log.")] = None,
    upload_id: Annotated[Optional[str], Field(description=(
        "Instead of csv: a file sent through create_upload (CSV/TSV, or an .xlsx workbook with sheet)."))] = None,
    sheet: Annotated[Optional[str], Field(description=(
        "With an .xlsx upload_id: the sheet holding the log (needed when the workbook has several)."))] = None,
) -> dict[str, Any]:
    """Save a real outage log against one of the user's RBDs and return the system's observed history from it.
    Give the log as CSV text (csv) or as a file uploaded with create_upload (upload_id).
    Each block's outages become its up/down timeline; RePyability merges them through the diagram's structure
    into the system's history and attributes every system outage to the block that took it down. Overlapping
    outages of one asset are merged; assets that match no block are listed and left out. Returns the log id,
    import notes and the history (as system_history does)."""
    user, db = _caller(ctx), _db()
    uid = user["uid"]
    if (csv is None) == (upload_id is None):
        raise ToolError("Give either csv (text) or upload_id (a file sent through create_upload) — exactly one.")
    rbd = _own_rbd(db, uid, rbd_id)
    _cap(db, user, "outage_logs", "outage logs")
    upload = None
    if upload_id is not None:
        upload, csv = _upload_table_text(db, uid, upload_id, sheet)
    mapping = columns.model_dump(exclude_none=True) if columns else None
    try:
        parsed = outage_logs_service.parse_log(
            csv, rbd.graph or {}, mapping, unit=unit, window_start=window_start, window_end=window_end,
            date_order=date_order, asset_map=asset_map)
    except outage_logs_service.OutageLogError as exc:
        raise ToolError(str(exc)) from exc
    log = outage_logs_service.create_log(db, rbd, parsed, uid, name or "")
    if upload is not None:
        uploads_service.delete(db, upload["_id"])
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
# Files: upload links, inspection and imports (#141)
# ---------------------------------------------------------------------------
# A file never passes through the agent's context: create_upload gives a
# single-use URL the agent PUTs the bytes to (curl), and the import tools take
# the upload_id. backend/services/uploads.py has the design, the storage and
# the security review. Small text formats can still be pasted inline
# (import_rbd's content). Every tool here counts like any other; an upload
# counts towards no storage cap and is deleted once its import is saved.

_UPLOAD_NOTE = (
    "Send the file with an HTTP PUT to this URL (it's single-use and expires in 15 minutes). Then call "
    "import_rbd / import_excel / upload_dataset / upload_outage_log with upload_id. Don't paste the file's "
    "contents into a tool call.")
# #191: sandboxed agents often can't reach the upload host (an egress proxy's
# 403, no network). The fallback is a path that already exists: paste a small
# text file into the tool that takes it, or have the user upload in the app.
_UPLOAD_FALLBACK = (
    "If the PUT can't reach this URL from your environment (a proxy 403, CONNECT refused, no network), don't "
    "retry it: a small text file (at most 200 KB) can be passed as text instead — upload_dataset csv, "
    "upload_outage_log csv, import_rbd content (Open-PSA XML or Galileo .dft). Anything else (an .xlsx "
    "workbook, a BlockSim project, a larger file): ask the user to upload it in the Reliafy app ({app}).")
_UPLOAD_APP_PAGES = {"rbd_import": ("/rbds/list", "RBDs › Import"), "dataset": ("/datasets/list", "Datasets"),
                     "excel": ("/datasets/list", "Datasets, RCM or RBDs › Import"),
                     "outage_log": ("/rbds/list", "the diagram's Outage history tab")}
# Inline content (import_rbd): small text formats only — anything larger goes
# through create_upload rather than the agent's context.
INLINE_MAX_BYTES = 200 * 1024
_OUTLINE_NODES = 100    # node list per imported diagram
_IMPORT_NOTES = 30      # import notes per diagram
_RCM_VALUES = 20        # unmapped consequence / decision values listed

_Purpose = Literal["rbd_import", "excel", "dataset", "outage_log"]
_RbdFormat = Literal["blocksim", "openpsa", "galileo", "excel", "repyability"]
_UPLOAD_ID = Annotated[str, Field(min_length=1, max_length=64, description="An upload_id from create_upload.")]


@contextmanager
def _untrusted_file(uid: str):
    """Parsing an uploaded file: one at a time per user, within the import
    budget (:mod:`backend.services.import_guard`). The importers' own errors
    reach the agent as they are; anything else (a malformed file tripping a
    parser) is a plain "couldn't read" — never a traceback, never "Error
    executing tool"."""
    try:
        with import_guard.guard(_db(), uid):
            yield
    except (import_guard.ImportBusy, import_guard.ImportBudgetExceeded) as exc:
        raise ToolError(str(exc)) from None
    except (ToolError, ValueError, TypeError):
        raise
    except Exception:  # noqa: BLE001 - untrusted input
        logger.warning("MCP import: couldn't read an uploaded file", exc_info=True)
        raise ToolError("Couldn't read this file — it may be damaged or from an unsupported version.") from None


def _sheet_list(data: bytes, filename: str, limit: int = 10) -> str:
    """'Sheets: “Data” (120 rows: Time, Status); …' for an error message."""
    from backend.services import excel

    sheets = excel.inspect(data, filename)["sheets"]
    parts = []
    for s in sheets[:limit]:
        if not s["rows"]:
            continue
        try:
            cols = excel.read_table(data, s["name"], None, filename, max_rows=1).header
        except ValueError:
            cols = []
        shown = ", ".join(cols[:15]) + (", …" if len(cols) > 15 else "")
        parts.append(f"“{s['name']}” ({s['rows']} rows: {shown})")
    more = f"; and {len(sheets) - limit} more" if len(sheets) > limit else ""
    return "Sheets: " + "; ".join(parts) + more + "."


def _workbook_table(data: bytes, filename: str, sheet: Optional[str], header_row: Optional[int] = None):
    """One sheet as a table. ``sheet`` may be omitted when only one sheet
    holds data; otherwise the error lists the sheets and their columns."""
    from backend.services import excel

    if not sheet:
        filled = [s for s in excel.inspect(data, filename)["sheets"] if s["rows"]]
        if len(filled) > 1:
            raise ToolError("This workbook has several sheets — say which one with sheet. "
                            + _sheet_list(data, filename))
        sheet = filled[0]["name"] if filled else None
    return excel.read_table(data, sheet, header_row, filename)


def _upload_table_text(db, uid: str, upload_id: str, sheet: Optional[str]) -> tuple[dict, str]:
    """An upload for upload_dataset / upload_outage_log as CSV text: a CSV /
    TSV file as it is, a workbook's sheet converted (as the app's Excel
    import does)."""
    from backend.services import excel

    doc, data = uploads_service.read(db, upload_id, uid)
    with _untrusted_file(uid):
        if uploads_service.is_excel(doc):
            return doc, excel.to_csv(_workbook_table(data, doc["filename"], sheet)).decode("utf-8")
    if doc.get("detected_format") not in ("csv", "text"):
        raise ToolError(f"This upload is a {doc.get('detected_format')} file, not a table: upload CSV / TSV text "
                        "or an .xlsx workbook. (Diagram files go to import_rbd.)")
    return doc, uploads_service.as_text(data)


def _upload_fallback(purpose: str) -> str:
    path, where = _UPLOAD_APP_PAGES[purpose]
    return _UPLOAD_FALLBACK.format(app=f"{where}: {_url(path)}")


@_tool("create_upload", _WRITE, "Get a file upload link")
def create_upload(
    ctx: Context,
    purpose: Annotated[_Purpose, Field(description=(
        "What the file is for: rbd_import (a BlockSim .rsgz / .rsr, Open-PSA XML, Galileo .dft or RePyability "
        ".json diagram file, "
        "then import_rbd); excel (an .xlsx workbook — a data sheet, an RCM/FMEA worksheet or Reliafy's RBD "
        "template — then import_excel); dataset (CSV or .xlsx life data, then upload_dataset); outage_log (CSV "
        "or .xlsx, then upload_outage_log)."))],
    filename: Annotated[str, Field(min_length=1, max_length=255, description=(
        "The file's name with its extension, e.g. pump-skid.rsgz or fmea.xlsx."))],
    size_bytes: Annotated[Optional[int], Field(ge=1, description=(
        "The file's size if known — refused here at once if it's over the limit."))] = None,
) -> dict[str, Any]:
    """Get a single-use URL to send a file to Reliafy without pasting it into a tool call. Run the returned
    curl command (or any HTTP PUT of the raw bytes) from a shell that can read the file, then call the import
    tool with upload_id: import_rbd (diagram files), import_excel (workbooks), upload_dataset or
    upload_outage_log. inspect_upload shows a workbook's sheets and columns, or a diagram file's diagrams,
    before importing. The URL expires in 15 minutes and works once; the file is deleted after its import, or
    after an hour. Never read a file into your context to paste it: use this. If your environment can't reach
    the URL (a proxy 403, no network), don't retry: pass a small text file (at most 200 KB) as text instead
    (upload_dataset / upload_outage_log csv, import_rbd content), and ask the user to upload anything else in
    the Reliafy app — the response's fallback says where."""
    user, db = _caller(ctx), _db()
    doc, token = uploads_service.create(
        db, user["uid"], purpose, filename, size_bytes,
        plan=_usage_plan(user), client=usage_service.client_of(user))
    path = f"/api/uploads/{doc['_id']}?t={token}"
    url = f"{config.UPLOAD_BASE_URL}{path}" if config.UPLOAD_BASE_URL else _url(path)
    return {
        "upload_id": doc["_id"],
        "url": url,
        "method": "PUT",
        "headers": {"Content-Type": "application/octet-stream"},
        "max_bytes": doc["max_bytes"],
        "expires_at": doc["expires_at"].isoformat(),
        "curl": (f"curl -sS -X PUT --data-binary @{shlex.quote(doc['filename'])} "
                 f"-H \"Content-Type: application/octet-stream\" \"{url}\""),
        "note": _UPLOAD_NOTE + " Replace the @file in curl with the file's path.",
        "fallback": _upload_fallback(purpose),
    }


@_tool("inspect_upload", _READ, "Inspect an uploaded file")
def inspect_upload(ctx: Context, upload_id: _UPLOAD_ID) -> dict[str, Any]:
    """Look inside a file sent through create_upload before importing it. A workbook: each sheet's header
    row, columns, row count, a few sample rows and what it looks like (looks_like.rcm / looks_like.rbd_blocks:
    a guessed column mapping) — use them to pick import_excel's target, sheet and mapping. A diagram file
    (BlockSim, Open-PSA, Galileo, RePyability JSON): the diagrams it holds with their block counts. CSV text: its columns and
    row count. Only the user's own uploads."""
    user, db = _caller(ctx), _db()
    doc, data = uploads_service.read(db, upload_id, user["uid"])
    with _untrusted_file(user["uid"]):
        details = uploads_service.inspect(doc, data)
    return {**uploads_service.brief(doc), **details}


def _lean_outline(graph: dict, check: dict) -> dict:
    """create_rbd's lean outline, with the node list capped for big imports."""
    out = _rbd_outline(graph, check, False)
    if len(out["nodes"]) > _OUTLINE_NODES:
        out["n_nodes"] = len(out["nodes"])
        out["nodes"] = out["nodes"][:_OUTLINE_NODES]
        out["nodes_truncated"] = True
    return out


# Blocks that carry a life model of their own (not junctions, sub-systems or
# repeated copies).
_MODEL_FREE_TYPES = ("input", "output", "knode", "subsystem")
_STAND_IN_MODEL = {"source": "params", "distribution": "Exponential", "distribution_id": "exponential",
                   "params": [{"name": "failure_rate", "value": 1.0}]}
_PREVIEW_EDGES = 200    # edges listed per previewed diagram
_UNIT_ASK = ("The file doesn't state a time unit, so the diagram's unit is blank. Ask the user what the rates "
             "and times are per, then import with time_unit (e.g. 'Hours') — or set it later with edit_rbd "
             "{op: 'set', unit}. Don't assume one.")


def _modelless_blocks(graph: dict) -> list[dict]:
    """Imported blocks with no life model (a BlockSim block Reliafy can't
    represent, an Open-PSA or Galileo fixed-probability event): the user sets one."""
    return [n for n in graph.get("nodes") or []
            if n.get("type") not in _MODEL_FREE_TYPES and not (n.get("data") or {}).get("model")
            and rbd_repeats.repeat_of(n) is None]


def _check_import(db, graph: dict, owners) -> dict:
    """validate_graph for an imported diagram. One whose only problem is
    blocks still needing a life model is importable — it's checked with a
    stand-in model on each (never saved) and comes back with ``needs_model``."""
    check = rbds_service.validate_graph(db, graph, owners)
    if check.get("valid", False):
        return check
    missing = _modelless_blocks(graph)
    if not missing:
        return check
    ids = {n["id"] for n in missing}
    stand_in = copy.deepcopy(graph)
    for n in stand_in["nodes"]:
        if n["id"] in ids:
            n.setdefault("data", {})["model"] = dict(_STAND_IN_MODEL)
    check_in = rbds_service.validate_graph(db, stand_in, owners)
    if not check_in.get("valid", False):
        return check
    return {**check_in, "needs_model": [(n.get("data") or {}).get("label") or n["id"] for n in missing]}


def _save_imported(db, user: dict, diagrams, *, name: Optional[str], save: bool, only: Optional[list[str]],
                   upload: Optional[dict], rbd_id: Optional[str] = None, replace: bool = False) -> dict:
    """Validate imported diagrams and (``save``) save them — all or nothing
    against the RBD cap. Returns each diagram's brief, import notes, its time
    unit, a one-line structure and a concise node list (never the whole
    graph) — a preview adds its edges and minimal cut sets, to check the
    conversion before saving (#187). Deletes the upload once saved.

    With ``rbd_id`` the one imported diagram is saved as a new copy of that
    diagram (named “<its name> (copy)”), which is left as it was — as the
    app's import always opens a new diagram — or, with ``replace``, over it."""
    uid = user["uid"]
    owners = _owners(uid)
    if only:
        wanted = {o.strip().lower() for o in only if o and o.strip()}
        picked = [d for d in diagrams if d.name.strip().lower() in wanted]
        if not picked:
            raise ToolError("None of the diagrams named in only are in this file. It holds: "
                            + "; ".join(f"“{d.name}”" for d in diagrams[:50]) + ".")
        diagrams = picked
    ready, skipped = [], []
    for d in diagrams:
        try:
            graph = rbd_graph.normalize_graph(d.graph, resolve_saved_model=_resolver(db, owners))
        except rbd_graph.GraphError as exc:
            skipped.append({"name": d.name, "error": str(exc)})
            continue
        check = _check_import(db, graph, owners)
        if not check.get("valid", False):
            skipped.append({"name": d.name, "error": "; ".join(check.get("errors") or ["invalid structure"])})
            continue
        ready.append((d, graph, check))
    if not ready:
        raise ToolError("Nothing in this file could be imported: "
                        + "; ".join(f"{s['name']}: {s['error']}" for s in skipped[:10]))
    target = None
    if rbd_id:
        if len(ready) != 1:
            raise ToolError("rbd_id takes one diagram, but this import holds several.")
        target = _get_rbd(db, uid, rbd_id)
        if replace and samples_service.is_sample(target.owner_id):
            raise ToolError(f"“{target.name}” is a shared sample diagram, so it can't be overwritten. Leave "
                            "replace off to save the import as a copy of it.")
    overwrite = target is not None and replace

    def title(d) -> str:
        if target is not None and not (name and name.strip()):
            return target.name if overwrite else f"{target.name} (copy)"
        if name and name.strip():
            return name.strip() if len(ready) == 1 else f"{name.strip()} — {d.name}"
        return d.name

    saved = []
    if save:
        for _, graph, _ in ready:
            _check_graph_refs(db, user, graph)
        if not overwrite:
            _cap(db, user, "rbds", "RBDs", n=len(ready))
        for d, graph, _ in ready:
            saved.append(rbds_service.save_rbd(db, title(d)[:200], graph, uid,
                                               rbd_id=target.id if overwrite else None))
        if upload is not None:
            uploads_service.delete(db, upload["_id"])
    items = []
    for i, (d, graph, check) in enumerate(ready):
        item = {"name": title(d), "source_format": d.source_format}
        if saved:
            item.update(_rbd_brief(saved[i]))
        else:
            item["n_blocks"] = sum(1 for n in graph["nodes"] if n.get("type") not in ("input", "output"))
        item["unit"] = graph.get("unit") or ""
        if not item["unit"]:
            item["unit_warning"] = _UNIT_ASK
        item["analytic"] = check.get("analytic", True)
        if check.get("needs_model"):
            item["analysable"] = False
            item["needs_model"] = check["needs_model"][:_OUTLINE_NODES]
            item["needs_model_note"] = (
                "These blocks have no life model (the import notes say why), so the diagram can't be analysed "
                "until each gets one: edit_rbd with the user's data, or the user sets them in the builder. "
                "Don't invent values.")
        item["import_notes"] = d.warnings[:_IMPORT_NOTES]
        if len(d.warnings) > _IMPORT_NOTES:
            item["more_import_notes"] = len(d.warnings) - _IMPORT_NOTES
        shape = rbd_structure.describe(graph)
        item["structure"] = shape["structure"]
        if not save:
            if shape["cut_sets"] is not None:
                item["minimal_cut_sets"] = shape["cut_sets"]
                item["n_cut_sets"] = shape["n_cut_sets"]
            edges = graph.get("edges") or []
            item["edges"] = [f"{e['source']} -> {e['target']}" for e in edges[:_PREVIEW_EDGES]]
            if len(edges) > _PREVIEW_EDGES:
                item["n_edges"] = len(edges)
        item.update(_lean_outline(graph, check))
        items.append(item)
    out: dict[str, Any] = {"saved": bool(saved), "diagrams": items}
    if target is not None and saved:
        if overwrite:
            out.update(action="replaced", replaced=target.id, id=target.id,
                       note=f"Replaced the contents of “{target.name}” (id {target.id}) with the import.")
        else:
            out.update(action="copied", id=saved[0].id, copy_of=target.id,
                       note=(f"Saved as a new diagram “{saved[0].name}” (id {saved[0].id}); “{target.name}” "
                             "is unchanged. Pass replace=true to overwrite it instead."))
    if skipped:
        out["skipped"] = skipped
    if not save:
        out["note"] = ("Preview only — nothing saved. Call again with save=true (only=[names] picks diagrams)"
                       + ("; the upload is kept for an hour." if upload is not None else "."))
    return out


def _excel_mapping_error(exc: Exception, data: bytes, filename: str) -> ToolError:
    from backend.services.rbd_import import excel as rbd_excel

    fields = ", ".join(f["id"] for f in rbd_excel.BLOCK_FIELDS)
    return ToolError(
        f"{exc} Call import_excel with target=rbd_template and mapping — {{field: column}} plus sheet for the "
        "blocks sheet, or the full form {\"blocks\": {\"sheet\", \"header_row\", \"mapping\": {field: column}}, "
        "\"connections\": {\"sheet\", \"mapping\": {\"from\": column, \"to\": column}}}. Block fields: "
        f"{fields}. " + _sheet_list(data, filename))


@_tool("import_rbd", _WRITE, "Import RBDs from a file")
def import_rbd(
    ctx: Context,
    upload_id: Annotated[Optional[str], Field(max_length=64, description=(
        "A file sent through create_upload (purpose rbd_import): ReliaSoft BlockSim (.rsgz / .rsr), Open-PSA "
        "XML, Galileo .dft, RePyability JSON (rbd.to_json(), or export_rbd_json), or an .xlsx in Reliafy's RBD "
        "template layout."))] = None,
    # A JSON file's text arrives parsed (the MCP layer pre-parses JSON strings), so an object is accepted too.
    content: Annotated[Optional[Union[str, dict[str, Any]]], Field(description=(
        "Instead of upload_id, for SMALL text files only (Open-PSA XML, Galileo DFT text or JSON, RePyability "
        "JSON), at most 200 KB. Anything else or larger: create_upload."))] = None,
    format: Annotated[Optional[_RbdFormat], Field(description=(
        "Parse as this format. Omit to detect it from the content."))] = None,
    name: Annotated[Optional[str], Field(max_length=200, description=(
        "A name for the diagram (a prefix when the file holds several). Default: the file's own names."))] = None,
    save: Annotated[bool, Field(description="False = preview what would be imported, saving nothing.")] = True,
    only: Annotated[Optional[list[str]], Field(description=(
        "Import just these diagrams, by name (a BlockSim project can hold many; preview with save=false or "
        "inspect_upload)."))] = None,
    time_unit: Annotated[Optional[str], Field(max_length=40, description=(
        "What the file's rates and times are per ('Hours', 'Cycles', …), used only when the file doesn't "
        "state a unit itself (Galileo never does). Ask the user rather than guess; parameters are never "
        "rescaled."))] = None,
) -> dict[str, Any]:
    """Import reliability block diagrams from another tool's file — BlockSim, Open-PSA, Galileo, RePyability
    JSON, or Reliafy's Excel RBD template — and save each as an RBD in the user's workspace (all or nothing against the plan's
    RBD limit). Send files with create_upload and pass upload_id; paste only small text formats into content.
    Returns, per diagram, its id and url, its time unit (unit_warning when the file states none), a one-line
    structure, the import notes (what was approximated — tell the user), needs_model (blocks imported
    without a life model, e.g. fixed-probability events — they must get one before analysis) and a concise
    node list; get_rbd reads the full graph, edit_rbd changes it. save=false previews, adding the edges and
    minimal cut sets so the conversion can be checked before saving."""
    user, db = _caller(ctx), _db()
    if (upload_id is None) == (content is None):
        raise ToolError("Give either upload_id (a file sent through create_upload) or content (small text) — "
                        "exactly one.")
    upload = None
    if content is not None:
        data = (json.dumps(content) if isinstance(content, dict) else content).encode("utf-8")
        if len(data) > INLINE_MAX_BYTES:
            raise ToolError(
                f"content is {len(data) // 1024} KB; inline content is limited to {INLINE_MAX_BYTES // 1024} KB. "
                "Call create_upload(purpose='rbd_import', filename=…) and send the file with the curl command it "
                "gives, then import_rbd(upload_id=…).")
        if format in ("blocksim", "excel"):
            raise ToolError(f"{format} files are binary — send them with create_upload, not as content.")
        filename = {"openpsa": "inline.xml", "galileo": "inline.dft",
                    "repyability": "inline.json"}.get(format or "", "inline.txt")
    else:
        upload, data = uploads_service.read(db, upload_id, user["uid"])
        filename = upload["filename"]
    with _untrusted_file(user["uid"]):
        try:
            diagrams = rbd_import.import_file(data, filename, format=format, time_unit=time_unit)
        except rbd_import.RbdImportError as exc:
            if getattr(exc, "code", None) == "excel_mapping":
                raise _excel_mapping_error(exc, data, filename) from None
            raise
        # RePyability JSON from Reliafy: links back to the saved models and diagrams this user can open.
        owners = _owners(user["uid"])
        rbd_import.link_references(diagrams, _resolver(db, owners),
                                   lambda rid: rbds_service.get_rbd(db, rid, owners))
        return _save_imported(db, user, diagrams, name=name, save=save, only=only, upload=upload)


def _excel_dataset(db, user, doc, data, sheet, mapping, name, header_row) -> dict:
    from backend.services import excel

    filename = doc["filename"]
    table = _workbook_table(data, filename, sheet, header_row)
    if mapping:
        missing = [str(src) for src in mapping.values() if not isinstance(src, str) or src not in table.header]
        if missing:
            raise ToolError(f"Sheet “{table.sheet}” has no column “{missing[0]}”. Its columns: "
                            + ", ".join(table.header) + ".")
        idx = [table.header.index(src) for src in mapping.values()]
        table = excel.Table(sheet=table.sheet, header=[str(k) for k in mapping],
                            rows=[[r[i] for i in idx] for r in table.rows], row_numbers=table.row_numbers,
                            header_row=table.header_row, notes=table.notes)
    _cap(db, user, "datasets", "datasets")
    text = excel.to_csv(table).decode("utf-8")
    default = excel.csv_filename(filename, table.sheet, 2).rsplit(".", 1)[0]
    ds = datasets_service.create_dataset(db, (name or default).strip()[:200],
                                         datasets_service.normalize_pasted(text), user["uid"])
    uploads_service.delete(db, doc["_id"])
    out = {"target": "dataset", "sheet": table.sheet, "header_row": table.header_row,
           "id": ds.id, "name": ds.name, "n_rows": ds.n_rows, "columns": [c["name"] for c in ds.columns],
           "preview": datasets_service.preview_rows(ds, 5), "url": _url(f"/datasets/d/{ds.id}")}
    if table.notes:
        out["notes"] = table.notes
    return out


def _excel_rcm(db, user, doc, data, sheet, mapping, name, header_row, study_id) -> dict:
    from backend.services import excel, rcm_import
    from backend.services import rcm as rcm_service

    uid = user["uid"]
    filename = doc["filename"]
    table = _workbook_table(data, filename, sheet, header_row)
    if mapping and isinstance(mapping.get("mapping"), dict):
        options = dict(mapping)
    elif mapping:
        options = {"mapping": dict(mapping)}
    else:
        guess = excel.guess_mapping(table.header, rcm_import.FIELDS)
        if "mode" not in guess:
            raise ToolError(
                f"Couldn't tell which column of “{table.sheet}” holds the failure modes. Give mapping: "
                f"{{field: column}} with fields {', '.join(rcm_import.FIELD_IDS)} (mode is required). Its "
                "columns: " + ", ".join(table.header) + ".")
        options = {"mapping": guess}
    options.setdefault("extra_columns", rcm_import.default_extra_columns(table.header, options["mapping"]))
    result = rcm_import.build_tree(table.header, table.rows, options, table.row_numbers)
    imported = result["functions"]
    if study_id:
        study = rcm_service.get_study(db, study_id, [uid])
        if study is None:
            raise ToolError("RCM study not found (only the user's own studies can be imported into).")
        study = rcm_service.replace_tree(db, study.id, [*(study.functions or []), *imported], uid,
                                         reader=_reader(user))
    else:
        _cap(db, user, "rcm_studies", "RCM studies")
        stem = excel.csv_filename(filename, table.sheet).rsplit(".", 1)[0]
        study = rcm_service.create_study(db, (name or stem).strip()[:200], "", "", uid)
        study = rcm_service.replace_tree(db, study.id, imported, uid, reader=_reader(user))
    uploads_service.delete(db, doc["_id"])
    unmapped = {k: [v for v in vals if v.get("guess") is None][:_RCM_VALUES]
                for k, vals in (result.get("values") or {}).items()}
    out = {
        "target": "rcm", "study_id": study.id, "name": study.name, "appended": bool(study_id),
        "sheet": table.sheet, "header_row": table.header_row,
        "mapping": options["mapping"], "extra_columns": options.get("extra_columns") or [],
        "counts": result["counts"], "warnings": (result.get("warnings") or [])[:_IMPORT_NOTES],
        "url": _url(f"/rcm/studies/{study.id}"),
    }
    if any(unmapped.values()):
        out["unmapped_values"] = {k: v for k, v in unmapped.items() if v}
        out["unmapped_note"] = ("These consequence / decision values weren't recognised and were left unset. To "
                                "set them, import again with mapping {mapping: {...}, consequence_map: {value: "
                                "category}, outcome_map: {value: decision}}.")
    if table.notes:
        out["notes"] = table.notes
    return out


def _excel_rbd(db, user, doc, data, sheet, mapping, name, header_row, rbd_id, replace=False) -> dict:
    filename = doc["filename"]
    excel_mapping = mapping
    if mapping and "blocks" not in mapping:
        if not sheet:
            raise ToolError("A flat {field: column} mapping needs sheet (the blocks sheet).")
        excel_mapping = {"blocks": {"sheet": sheet, "header_row": header_row, "mapping": mapping}}
    try:
        diagrams = rbd_import.import_file(data, filename, excel_mapping=excel_mapping, format="excel")
    except rbd_import.RbdImportError as exc:
        if getattr(exc, "code", None) == "excel_mapping":
            raise _excel_mapping_error(exc, data, filename) from None
        raise
    return {"target": "rbd_template",
            **_save_imported(db, user, diagrams, name=name, save=True, only=None, upload=doc, rbd_id=rbd_id,
                             replace=replace)}


@_tool("import_excel", _WRITE, "Import from an Excel workbook")
def import_excel(
    ctx: Context,
    upload_id: _UPLOAD_ID,
    target: Annotated[Literal["dataset", "rcm", "rbd_template"], Field(description=(
        "dataset: one sheet saved as a dataset; rcm: an FMEA / RCM worksheet (one row per failure mode) into an "
        "RCM study; rbd_template: Reliafy's Excel RBD template (Blocks + Connections sheets) saved as an RBD."))],
    sheet: Annotated[Optional[str], Field(description=(
        "The sheet to read. Needed when the workbook has several sheets with data (inspect_upload lists them)."
    ))] = None,
    mapping: Annotated[Optional[dict[str, Any]], Field(description=(
        "dataset: optional {dataset column: sheet column} to keep (and rename) only those columns. rcm: "
        "{field: column} with fields function, standard, failure, mode (required), effects, consequence, "
        "outcome, task, interval, interval_unit, notes — omit to use the guess from the headers; or "
        "{mapping, consequence_map, outcome_map, extra_columns}. rbd_template: omit for the template layout; "
        "else {field: column} for the blocks sheet (with sheet) or {blocks: {sheet, header_row, mapping}, "
        "connections: {sheet, mapping: {from, to}}}."))] = None,
    name: Annotated[Optional[str], Field(max_length=200, description=(
        "A name for the new dataset, study or diagram. Default: from the file and sheet."))] = None,
    rbd_id: Annotated[Optional[str], Field(description=(
        "rbd_template only: an existing diagram of the user's. The import is saved as a new copy of it "
        "(“<name> (copy)”, or name), leaving it unchanged — unless replace=true, which overwrites its contents. "
        "The result's action says which (copied / replaced) and id is the diagram saved."
    ))] = None,
    replace: Annotated[bool, Field(description=(
        "rbd_template with rbd_id only: overwrite that diagram instead of saving a copy. Only when the user "
        "asked to replace it."))] = False,
    study_id: Annotated[Optional[str], Field(description=(
        "rcm only: append the imported functions to this existing study of the user's instead of creating one."
    ))] = None,
    header_row: Annotated[Optional[int], Field(ge=0, description=(
        "The sheet row holding the column names (1-based; 0 = no header row). Default: guessed."))] = None,
) -> dict[str, Any]:
    """Import an .xlsx workbook sent through create_upload: a sheet as a dataset (the same columns
    upload_dataset returns), an FMEA / RCM worksheet into a new or existing RCM study, or Reliafy's Excel
    RBD template as an RBD — a new one; with rbd_id, a new copy of that diagram (it stays unchanged) unless
    replace=true overwrites it. Call inspect_upload first to see the sheets, their columns and a guessed mapping.
    Formulas are read as the values Excel last saved; nothing is ever evaluated."""
    user, db = _caller(ctx), _db()
    doc, data = uploads_service.read(db, upload_id, user["uid"])
    if not uploads_service.is_excel(doc):
        raise ToolError(f"This upload isn't an Excel workbook (it's {doc.get('detected_format')}). CSV goes to "
                        "upload_dataset / upload_outage_log with upload_id; diagram files to import_rbd.")
    if rbd_id and target != "rbd_template":
        raise ToolError("rbd_id applies to target rbd_template.")
    if replace and not rbd_id:
        raise ToolError("replace applies with rbd_id (the diagram to overwrite).")
    if study_id and target != "rcm":
        raise ToolError("study_id applies to target rcm.")
    with _untrusted_file(user["uid"]):
        if target == "dataset":
            return _excel_dataset(db, user, doc, data, sheet, mapping, name, header_row)
        if target == "rcm":
            return _excel_rcm(db, user, doc, data, sheet, mapping, name, header_row, study_id)
        return _excel_rbd(db, user, doc, data, sheet, mapping, name, header_row, rbd_id, replace)


# ---------------------------------------------------------------------------
# Share links: a read-only page anyone with the URL can open, no account needed
# ---------------------------------------------------------------------------
# The app's public links (backend/services/public_links.py), same rules:
# owner-only, never a shared sample, only the kinds with a public page. Every
# plan; on Free each call counts against the monthly allowance like any other.

_SHARE_KINDS = {
    "model": "models",
    "dataset": "datasets",
    "rbd": "rbds",
    "degradation_model": "degradation_models",
    "strategy_analysis": "strategy_analyses",
    "rcm_study": "rcm_studies",
    "fleet": "fleets",
    "recurrent_model": "recurrent_models",
}
_KIND_OF = {collection: kind for kind, collection in _SHARE_KINDS.items()}
_ShareKind = Literal["model", "dataset", "rbd", "degradation_model", "strategy_analysis", "rcm_study", "fleet",
                     "recurrent_model"]


def _share_brief(db, link: dict) -> dict:
    doc = db[link["collection"]].find_one({"_id": link["artifact_id"]}, {"name": 1}) or {}
    out = links_service.public(link)
    return {
        "url": _url(out["path"]),
        "token": out["token"],
        "kind": _KIND_OF.get(link["collection"], link["collection"]),
        "id": link["artifact_id"],
        "name": doc.get("name"),
        "label": out["label"],
        "protected": out["protected"],
        "expires_at": out["expires_at"],
        "created_at": out["created_at"],
    }


@_tool("share_link", _WRITE, "Create a share link")
def share_link(
    ctx: Context,
    kind: Annotated[_ShareKind, Field(description="What to share: model (a fitted life model), dataset, rbd, "
                                                  "degradation_model, strategy_analysis, rcm_study, fleet "
                                                  "or recurrent_model (a repairable-system model).")],
    id: Annotated[str, Field(description="The id of one of the user's own items of that kind (e.g. from "
                                         "list_models or list_rbds). Shared samples can't be shared.")],
    password: Annotated[bool, Field(description="Protect the link with a passphrase Reliafy generates. It is "
                                                "returned once, in this response only.")] = False,
    expires_in_days: Annotated[Optional[int], Field(ge=1, le=365, description="Days until the link stops "
                                                    "working (1–365). Omit for a link that lasts until revoked."
                                                    )] = None,
    label: Annotated[Optional[str], Field(max_length=80, description="Who or what the link is for, e.g. "
                                                                     "'for the client'. Shown only to the "
                                                                     "user.")] = None,
) -> dict[str, Any]:
    """Publish a read-only page of one of the user's own items — anyone with the URL can open it, no Reliafy
    account needed — and return the URL. Each call makes a new link (an item can have several, e.g. one per
    recipient, each revocable with revoke_share_link). An RBD's page shows the diagram and its results and
    offers Download as Python; a repairable RBD shows availability only if a result is saved. Linked
    analyses an item relies on are included read-only. With password=true the response carries a generated
    passphrase: this is the only time it's shown (only its hash is stored). Give the user the link and the
    passphrase, and tell them to send the two to the recipient separately (e.g. the link by email, the
    passphrase by message or phone). Confirm with the user before sharing anything publicly."""
    user, db = _caller(ctx), _db()
    collection = _SHARE_KINDS[kind]
    doc = db[collection].find_one({"_id": id}, {"owner_id": 1, "name": 1})
    if doc is not None and samples_service.is_sample(doc.get("owner_id")):
        hint = " Copy it first with clone_rbd, then share the copy." if kind == "rbd" else ""
        raise ToolError(f"“{doc.get('name')}” is a shared sample, not one of the user's own items — it can't be "
                        f"shared with a link.{hint}")
    try:
        link = links_service.create_link(db, collection, id, user, label=label, expires_in_days=expires_in_days,
                                         generate_password=password, via="mcp")
    except links_service.PublicLinkError as exc:
        if exc.status == 404:
            raise ToolError(f"No {kind.replace('_', ' ')} with that id among the user's own items.") from None
        raise ToolError(str(exc)) from None
    out = _share_brief(db, link)
    if link.get("passphrase"):
        out["passphrase"] = link["passphrase"]
        out["note"] = ("Shown once: Reliafy keeps only a hash. Give the user the URL and the passphrase and tell "
                       "them to send the two to the recipient separately (the link one way, the passphrase "
                       "another). A lost passphrase can't be recovered: revoke the link and share again. The "
                       "user can rotate it from the Share dialog in the app.")
    else:
        out["note"] = "Anyone with this URL can view it, without an account, until it's revoked" + (
            " or expires." if link.get("expires_at") else ".")
    return out


@_tool("list_share_links", _READ, "List share links")
def list_share_links(
    ctx: Context,
    kind: Annotated[Optional[_ShareKind], Field(description="Only links to items of this kind.")] = None,
    id: Annotated[Optional[str], Field(description="Only links to this item (give kind too).")] = None,
) -> dict[str, Any]:
    """The user's live share links (newest first), optionally for one kind or one item: URL, item, label,
    whether it's password-protected and when it expires. Expired and revoked links aren't listed. Passphrases
    are never shown again."""
    user, db = _caller(ctx), _db()
    links = links_service.list_links(db, user["uid"], _SHARE_KINDS[kind] if kind else None, id)
    return {"links": [_share_brief(db, link) for link in links], "count": len(links)}


@_tool("revoke_share_link", _WRITE, "Revoke a share link")
def revoke_share_link(
    ctx: Context,
    token: Annotated[str, Field(description="The link's token (list_share_links), or its full URL.")],
) -> dict[str, Any]:
    """Revoke one of the user's share links: it stops working at once, for everyone (other links to the same
    item keep working). Can't be undone — share again for a new link."""
    user, db = _caller(ctx), _db()
    token = (token or "").strip().rstrip("/").rsplit("/p/", 1)[-1]
    link = links_service.resolve(db, token)
    if not token or not links_service.revoke(db, token, user["uid"]):
        raise ToolError("Share link not found among the user's links (list_share_links shows them).")
    return {"revoked": True, "token": token, **({"id": link["artifact_id"],
                                                  "kind": _KIND_OF.get(link["collection"])} if link else {})}


# ---------------------------------------------------------------------------
# Metadata: rename / annotate (#135)
# ---------------------------------------------------------------------------
# Name and notes only — never the data or the fit — and, like the deletes,
# owner-only and never a shared sample.

_NAME_MAX, _NOTES_MAX = 200, 5000
_NewName = Annotated[Optional[str], Field(max_length=_NAME_MAX, description="A new name (omit to keep it).")]
_NewNotes = Annotated[Optional[str], Field(max_length=_NOTES_MAX,
                                           description="New notes, replacing any there are; \"\" clears them. "
                                                       "Omit to keep them.")]


def _details(name: str | None, notes: str | None) -> tuple[str | None, str | None]:
    """Validated (name, notes): at least one given, and a name isn't blank."""
    if name is None and notes is None:
        raise ToolError("Nothing to change: give a new name, notes, or both.")
    if name is not None:
        name = name.strip()
        if not name:
            raise ToolError("name can't be blank.")
    return name, (notes.strip() if notes is not None else None)


def _changed(name: str | None, notes: str | None) -> list[str]:
    return [k for k, v in (("name", name), ("notes", notes)) if v is not None]


@_tool("update_model", _WRITE, "Rename or annotate a model")
def update_model(
    ctx: Context,
    model_id: Annotated[str, Field(description="One of the user's own model ids (list_models) — life or recurrent.")],
    name: _NewName = None,
    notes: _NewNotes = None,
) -> dict[str, Any]:
    """Rename one of the user's own saved models (life or recurrent) and/or set its notes. Only the name and
    notes change — never the fit, parameters or data. Shared samples can't be changed."""
    user, db = _caller(ctx), _db()
    uid = user["uid"]
    name, notes = _details(name, notes)
    m = models_service.get_model(db, model_id, _owners(uid))
    service, kind = models_service, "life"
    if m is None:
        m, service, kind = recurrent_service.get_model(db, model_id, _owners(uid)), recurrent_service, "recurrent"
    if m is None:
        raise ToolError("Model not found.")
    if samples_service.is_sample(m.owner_id):
        raise ToolError(f"“{m.name}” is a shared sample model, not yours — it can't be renamed or annotated.")
    if name is not None:
        m = service.rename_model(db, m.id, name, uid)
    if notes is not None:
        m = service.set_notes(db, m.id, notes, uid)
    return {"updated": _changed(name, notes), "model_id": m.id, "kind": kind, "name": m.name,
            "notes": (m.spec or {}).get("notes"),
            "url": _url(f"/modelling/m/{m.id}" if kind == "life" else f"/modelling/recurrent/{m.id}")}


@_tool("update_dataset", _WRITE, "Rename or annotate a dataset")
def update_dataset(
    ctx: Context,
    dataset_id: Annotated[str, Field(description="One of the user's own dataset ids (list_datasets).")],
    name: _NewName = None,
    notes: _NewNotes = None,
) -> dict[str, Any]:
    """Rename one of the user's own datasets and/or set its notes. Only the name and notes change — never the
    data. Shared samples can't be changed."""
    user, db = _caller(ctx), _db()
    uid = user["uid"]
    name, notes = _details(name, notes)
    ds = datasets_service.get_dataset(db, dataset_id, _owners(uid))
    if ds is None:
        raise ToolError("Dataset not found.")
    if samples_service.is_sample(ds.owner_id):
        raise ToolError(f"“{ds.name}” is a shared sample dataset, not yours — it can't be renamed or annotated.")
    ds = datasets_service.update_details(db, ds.id, uid, name=name, notes=notes)
    if ds is None:
        raise ToolError("Dataset not found.")
    return {"updated": _changed(name, notes), "dataset_id": ds.id, "name": ds.name, "notes": ds.notes,
            "url": _url(f"/datasets/d/{ds.id}")}


# ---------------------------------------------------------------------------
# Plans
# ---------------------------------------------------------------------------

# ---- get_account (#133): the caller's plan and what's left on it -------------
# Ungated like upgrade_link: an agent asks "what's left?" most when nothing is.

@_tool("get_account", _READ, "Your plan and usage")
def get_account(ctx: Context) -> dict[str, Any]:
    """The user's Reliafy plan and what's left on it. Free: the tool calls used and left this month (a small
    allowance to try Reliafy from an agent), with the date they reset (the 1st, 00:00 UTC). Pro: unlimited.
    A subscriber to the retired Agent plan (grandfathered): the calls used and left today, resetting at
    00:00 UTC. Also saved items per kind against the plan's storage limits (limit null = unlimited), whether
    availability simulation is included, and how to upgrade. Never counted against the allowance, and works
    when it's used up — check it before a long job, or to explain a limit to the user."""
    user, db = _caller(ctx), _db()
    admin = billing_service.is_admin_user(user)
    unlimited = admin or not config.BILLING_ENABLED
    # The plan governing MCP use: free / pro / agent (grandfathered). Operators
    # and self-hosted installs have Pro's access.
    plan = "pro" if unlimited else (user.get("mcp_plan") or billing_service.mcp_plan(db, user))
    summary = billing_service.usage_summary(db, user["uid"], admin=admin)
    quota, period = billing_service.mcp_quota(plan)
    if quota is None:
        calls = {"unlimited": True, "period": None, "used": None, "limit": None, "left": None,
                 "resets_at": None, "resets_in": None}
    else:
        used = min(billing_service.mcp_calls_used(db, user["uid"], plan), quota)
        reset = billing_service.mcp_quota_resets_at(plan)
        calls = {"unlimited": False, "period": period, "used": used, "limit": quota, "left": quota - used,
                 "resets_at": reset.isoformat(), "resets_in": _in_days(reset).removeprefix("in ")}
        if period == "month":
            calls["resets_on"] = f"{reset.day} {reset:%B %Y} (UTC)"
    caps = None if unlimited or plan == "pro" else summary["plan_caps"]
    storage = {kind: {"used": n, "limit": None if caps is None else caps[kind]}
               for kind, n in summary["usage"].items()}
    if admin:
        note = "Operator account: no tool-call limit and no storage limits."
    elif not config.BILLING_ENABLED:
        note = "Self-hosted install: no plan limits."
    elif plan == "pro":
        note = "Reliafy Pro: unlimited tool calls and storage."
    elif plan == "free":
        note = (f"Reliafy Free: {quota:,} tool calls a month to try Reliafy from an AI agent (get_account and "
                "upgrade_link aren't counted), within the storage limits shown. Fitting and fleets are Pro-only.")
    else:
        note = (f"Reliafy Agent (a retired plan, kept until the subscription ends): {quota:,} tool calls a day "
                "(get_account and upgrade_link aren't counted) and the storage limits shown. Fitting and fleets "
                "are Pro-only.")
    return {
        "plan": plan,
        "plan_name": _PLAN_NAMES[plan],
        "grandfathered": plan == "agent",
        "operator": admin,
        "tool_calls": calls,
        "storage": storage,
        "simulation_available": billing_service.premium_compute_allowed(db, user),
        "upgrade": None if plan == "pro" else _upgrade_path(lead="To lift these limits, upgrade"),
        "note": note,
    }


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
