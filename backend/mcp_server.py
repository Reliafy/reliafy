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
  server (:mod:`backend.services.oauth`) — how Claude connectors sign in, on
  any plan.

Plans (:func:`billing.mcp_plan`, attached to the request as ``mcp_plan``):
Pro — and API tokens, operators and self-hosted installs — has every tool
with no quota. Free and Agent (US$2/month, MCP only) OAuth users get the
tools except fitting and fleets (Pro-only: agents fit locally with SurPyval
and save with ``save_model``), within a daily tool-call quota and their
plan's storage caps. Availability simulation keeps the app's own paid gate
(Pro or purchased credits) on every plan. Every refusal is a tool error that
says what the limit is, when it resets and how to upgrade — never a
transport failure — so Claude can tell the user plainly instead of showing
a broken connection.

Either way: the same per-user rate limit, and the same scope — the user's
personal data plus the shared samples (as ``/api/v1``). A missing or invalid
token gets a 401 whose ``WWW-Authenticate`` points at the protected-resource
metadata, which is what starts Claude's OAuth sign-in.

Tools call the service layer directly — never HTTP back into ourselves — and
turn user-facing failures (``FitError`` and friends) into MCP tool errors with
the message intact. Anything unexpected reaches the model only as "Error
executing tool …"; the traceback goes to the log.
"""

import functools
import logging
from contextlib import asynccontextmanager
from typing import Annotated, Any, Callable, Literal, Optional

import anyio
import numpy as np
import pandas as pd
from mcp.server.mcpserver import Context, MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.server.transport_security import TransportSecuritySettings
from mcp_types import ToolAnnotations
from pydantic import BaseModel, Field
from starlette.datastructures import Headers
from starlette.exceptions import HTTPException
from starlette.responses import JSONResponse

from backend import config
from backend import fitting
from backend import recurrent as recurrent_fit
from backend import storage
from backend.fitting import FitError
from backend.services import billing as billing_service
from backend.services import datasets as datasets_service
from backend.services import fleet as fleet_service
from backend.services import fleet_alerts as alerts_service
from backend.services import metrics as metrics_service
from backend.services import oauth as oauth_service
from backend.services import models as models_service
from backend.services import rbd_graph
from backend.services import rbds as rbds_service
from backend.services import recurrent as recurrent_service
from backend.services import samples as samples_service
from backend.services import strategy_store
from backend.services import tokens as tokens_service
from backend.services import rbd_analysis
from backend.services import rbd_export
from backend.services.rbd_analysis import AnalysisError
from backend.services.strategy import StrategyError

logger = logging.getLogger(__name__)

MCP_PRO_REQUIRED = (
    "MCP access with an API token is part of Reliafy Pro. Upgrade to Pro, or drop the token "
    "header and sign in to Reliafy from your MCP client (OAuth) to use the Free or Agent plan."
)


AGENT_PRICE = "US$2/month"
PRO_PRICE = "US$19/month"
_PLAN_NAMES = {"free": "Free", "agent": "Agent", "pro": "Pro"}


def _billing_url() -> str:
    return f"{config.PUBLIC_BASE_URL or 'https://reliafy.com'}/billing"


def _upgrade_path(plan: str, lead: str = "To lift it, upgrade") -> str:
    """How to lift a limit, for the caller's plan: Free users are offered both
    paid plans, Agent users the one above them."""
    link = " (or call upgrade_link for a direct payment link)"
    if plan == "agent":
        return f"{lead} to Reliafy Pro ({PRO_PRICE}) at {_billing_url()}{link}."
    return f"{lead} to Reliafy Agent ({AGENT_PRICE}, MCP) or Pro ({PRO_PRICE}) at {_billing_url()}{link}."


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
                f"{_billing_url()} (or call upgrade_link with plan=pro for a payment link) to fit here.")
    return (f"Fleet forecasts and fleet alerts are part of Reliafy Pro ({PRO_PRICE}) — they run on usage "
            f"pushed through the Pro API — and aren't included on this plan. Upgrade at {_billing_url()} "
            "(or call upgrade_link with plan=pro for a payment link).")


def _quota_message(plan: str, quota: int) -> str:
    reset = billing_service.next_day_start()
    return (f"You've used all {quota:,} Reliafy tool calls included per day on the {_PLAN_NAMES[plan]} "
            f"plan. The limit resets at 00:00 UTC ({_until(reset)}). " + _upgrade_path(plan))


def _simulation_message(plan: str) -> str:
    """Why analyze_rbd can't simulate for a Free/Agent MCP user, and the two
    ways forward: Pro, or run the same diagram locally for free."""
    return (f"Availability simulation isn't included on the {_PLAN_NAMES[plan]} plan: it needs Reliafy Pro "
            f"({PRO_PRICE}; purchased AI credits unlock it too) — upgrade at {_billing_url()} (or call "
            "upgrade_link with plan=pro for a payment link). It's free to run "
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
    the OAuth user's own plan, 'agent' or 'free', which :func:`_tool` gates
    tools and quotas on."""
    scheme, _, raw = (authorization or "").partition(" ")
    if scheme.lower() != "bearer" or not raw.strip():
        return 401, None, (
            "Sign in to Reliafy to use it from Claude (the client starts OAuth from this response), "
            "or send 'Authorization: Bearer rlf_…' with an API token from Settings > API access."
        )
    user = resolve_bearer(db, raw)
    if user is None:
        return 401, None, "Invalid, expired or revoked token."
    if not billing_service.api_access_allowed(db, user):
        if user.get("via_oauth"):
            return 200, {**user, "mcp_plan": billing_service.mcp_plan(db, user)}, ""
        return 403, None, MCP_PRO_REQUIRED
    return 200, {**user, "mcp_plan": "pro"}, ""


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
B-lives, importance; availability for repairable diagrams), export_rbd_python (a standalone script).
- Maintenance strategy: optimal_replacement, failure_finding_interval, optimal_overhaul (recurrent models), \
and fleet_forecast (list_fleets first); list_fleet_alerts / create_fleet_alert manage email alerts on a \
fleet's expected failures.
- Housekeeping: delete_model, delete_dataset and delete_rbd permanently delete the user's own artifacts \
(never shared samples; a dataset still used by a model, or a model a fleet runs on, can't be deleted). \
Only on the user's explicit \
request: confirm by name first, and relay anything the response lists as affected.
- Plans: upgrade_link gives the user a Stripe payment link for Reliafy Agent or Pro, to open themselves.

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
- Availability simulation for repairable RBDs is a paid feature; a saved result is served when one exists.
- Every artifact has a url; share it so the user can open the result in Reliafy.

Plans: fitting (fit_distribution, fit_and_save_model) and the fleet tools are Reliafy Pro. On the Free and \
Agent plans, fit locally with SurPyval (pip install surpyval; same 0 = failed, 1 = running convention) and \
save the parameters with save_model. Availability simulation needs Pro (or purchased credits); otherwise \
export_rbd_python runs it locally. Free and Agent also have a daily tool-call quota and storage limits. \
When a tool answers that a limit or plan stops it, tell the user plainly what it says — the limit, when it \
resets and how to upgrade — and don't retry it. If they want to upgrade, upgrade_link gives them a payment \
link to open themselves; nothing is charged until they complete it.
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


# Pro-only tools. Fitting runs server-side CPU the cheaper plans don't pay for
# (agents fit locally with SurPyval, then save_model); fleets depend on usage
# arriving through the Pro API.
_FIT_TOOLS = {"fit_distribution", "fit_and_save_model"}
_FLEET_TOOLS = {"list_fleets", "fleet_forecast", "list_fleet_alerts", "create_fleet_alert"}
PRO_ONLY_TOOLS = _FIT_TOOLS | _FLEET_TOOLS
# Never gated or counted: the way out of a limit must work when the limit is hit.
UNGATED_TOOLS = {"upgrade_link"}


def _gate(ctx: Context, name: str) -> None:
    """Plan gating for one tool call: Pro-only tools, then the daily quota
    (counted only for calls that pass the gate)."""
    user = _caller(ctx)
    plan = user.get("mcp_plan", "pro")
    if plan == "pro" or name in UNGATED_TOOLS:
        return
    if name in PRO_ONLY_TOOLS:
        raise ToolError(_pro_only_message(name))
    if not billing_service.consume_mcp_call(_db(), user["uid"], plan):
        raise ToolError(_quota_message(plan, billing_service.mcp_daily_quota(plan)))


def _tool(name: str, annotations: ToolAnnotations, title: str):
    """Register a tool, translating user-facing failures into tool errors."""

    def decorator(fn):
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            ctx = next((v for v in (*args, *kwargs.values()) if isinstance(v, Context)), None)
            if ctx is not None:
                _gate(ctx, name)
            try:
                return fn(*args, **kwargs)
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
    raise ToolError(
        f"You've reached the {_PLAN_NAMES[plan]} plan's limit of {cap} saved {label}. The limit doesn't "
        f"reset: delete {label} you no longer need in Reliafy to make room. "
        + _upgrade_path(plan, lead="Or, for more storage, upgrade"))


def _record(db, name: str, tool: str) -> None:
    try:
        metrics_service.record_event(db, name=name, path=f"/mcp/{tool}")
    except Exception:  # pragma: no cover - analytics must never fail a tool
        logger.warning("could not record MCP metrics event", exc_info=True)


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


def _fit_summary(result: dict) -> dict:
    """The parts of a fit payload worth handing to a model (no plot arrays).

    A fit the optimiser reported as failed leads with ``fit_ok: false`` and
    the warning, ahead of the numbers, so they aren't quoted as a result."""
    metrics = result.get("metrics") or _live_metrics((result.get("functions") or {}).get("model_id"))
    lead: dict[str, Any] = {}
    if result.get("fit_ok") is False or result.get("fit_warning"):
        lead = {"fit_ok": False, "warning": "The fit did NOT converge — the parameters and metrics below are "
                                            "not a valid result; don't quote them. " + (result.get("fit_warning") or "")}
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
    for key in ("extra_params", "coefficients", "randomness", "fit_warning", "options"):
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
        for key in ("coefficients", "extra_params", "randomness", "fit_warning", "options", "warnings"):
            if r.get(key):
                out[key] = r[key]
        if (r.get("functions") or {}).get("covariates"):
            out["covariates"] = r["functions"]["covariates"]
        if r.get("fit_ok") is False or r.get("fit_warning"):
            out = {"fit_ok": False, **out}  # lead with it, as the fit tools do
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
    _record(db, "mcp_fit", "fit_and_save_model")
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
    running (suspended); if the data marks failures with 1, pass c_invert=true. A fit that says every (or
    all but one) row is censored almost always means the flags are inverted. Weibull beta < 1 = infant
    mortality, ≈ 1 = random failures, > 1 = wear-out. Reliafy Pro only: on the Free and Agent plans, fit
    locally with SurPyval and save the parameters with save_model."""
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
    convention: 0 = failed, 1 = still running; c_invert=true when the data marks failures with 1. Reliafy
    Pro only (on other plans, fit locally with SurPyval and use save_model)."""
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
    _record(db, "mcp_model", "save_model")
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
    column should use 0 = failed, 1 = still running (or flag c_invert when fitting)."""
    user, db = _caller(ctx), _db()
    _cap(db, user, "datasets", "datasets")
    ds = datasets_service.create_dataset(db, name.strip(), datasets_service.normalize_pasted(csv), user["uid"])
    _record(db, "mcp_dataset", "upload_dataset")
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


class RbdNode(BaseModel):
    id: str = Field(description="Unique node id. The diagram needs exactly one 'input' and one 'output' node.")
    type: Literal["input", "output", "component", "series", "parallel", "knode", "standby", "subsystem"] = Field(
        description="component = one block; series/parallel = n identical blocks sharing one model; knode = "
                    "k-of-n voting gate (n = required, k = branches feeding it); standby = spare(s) idle until "
                    "the running unit fails; subsystem = embed a saved RBD.")
    label: Optional[str] = None
    model: Optional[BlockModel] = Field(None, description="Life model (component, series, parallel, standby).")
    repair: Optional[BlockModel] = Field(None, description="Repairable diagrams only: time-to-repair distribution.")
    n: Optional[int] = Field(None, description="series/parallel: number of identical units; knode: number REQUIRED to work.")
    k: Optional[int] = Field(None, description="knode: number of branches feeding the gate.")
    spares: Optional[int] = Field(None, description="standby: number of spares.")
    cold: Optional[bool] = Field(None, description="standby: true = cold (spares don't age while idle).")
    subsystem_rbd_id: Optional[str] = Field(None, description="subsystem: the saved RBD id to embed.")


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
    (stages form), e.g. a lognormal time to repair."""
    user, db = _caller(ctx), _db()
    uid = user["uid"]
    owners = _owners(uid)
    if (nodes is None) == (stages is None):
        raise ToolError("Give either nodes + edges (graph form) or stages (simple form) — exactly one.")
    if stages is not None and edges:
        raise ToolError("edges belong to the graph form (nodes + edges); the stages form is wired automatically. "
                        "Give exactly one form.")
    if stages is not None:
        graph = _stage_graph(db, uid, stages, repairable)
        graph["unit"] = unit
    else:
        graph = rbd_graph.normalize_graph(
            {"nodes": [n.model_dump(exclude_none=True) for n in nodes],
             "edges": [e.model_dump() for e in edges or []],
             "unit": unit, "repairable": repairable},
            resolve_saved_model=lambda mid: models_service.get_model(db, mid, owners),
        )
    check = rbds_service.validate_graph(db, graph, owners)
    if not check.get("valid", False):
        raise ToolError("Invalid RBD structure: " + "; ".join(check.get("errors") or ["unknown problem"]))
    _cap(db, user, "rbds", "RBDs")
    rbd = rbds_service.save_rbd(db, name.strip(), graph, uid)
    _record(db, "mcp_rbd", "create_rbd")
    return {**_rbd_brief(rbd), "analytic": check.get("analytic", True), "warnings": check.get("warnings") or [],
            "placeholders": rbd_graph.placeholder_labels(graph), "graph": rbd_graph.compact_graph(graph)}


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


def _availability_summary(result: dict) -> dict:
    keys = ("unit", "steady_state_availability", "unavailability", "mean_up_time", "mean_down_time",
            "failure_frequency", "figures_basis", "n_simulations", "t_simulation", "per_node", "importance",
            "criticality", "cached", "computed_at", "can_recompute")
    return {"kind": "repairable", **{k: result.get(k) for k in keys if k in result}}


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
) -> dict[str, Any]:
    """Analyse a saved RBD. Non-repairable diagrams: system reliability curve, MTTF, B-lives (B10/B50),
    component importance (Birnbaum, Fussell–Vesely, RAW/RRW) and minimal cut/path sets. Repairable
    diagrams: steady-state availability, mean up/down time, failure frequency and per-block downtime share.
    Availability simulation is a paid feature (Pro or purchased credits; not part of the Free or Agent plans):
    a saved result is always served; otherwise, without entitlement, this returns available=false with a
    message instead of results — relay it, and offer export_rbd_python to run the simulation locally."""
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
                        "(analysed for availability). Drop them — t_max sets the simulated horizon.")
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
            status, payload = availability_payload(db, actx, graph, t_max, rbd, recompute, owners)
            if status != 200:
                plan = user.get("mcp_plan", "pro")
                message = _simulation_message(plan) if plan != "pro" else payload.get("detail")
                return {**head, "kind": "repairable", "available": False, "code": payload.get("code"),
                        "message": message}
            return {**head, "available": True, **_availability_summary(payload)}

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
    _record(db, "mcp_fleet_alert", "create_fleet_alert")
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
    _record(db, "mcp_delete", "delete_model")
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
    _record(db, "mcp_delete", "delete_dataset")
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
    _record(db, "mcp_delete", "delete_rbd")
    out = {"deleted": True, "rbd_id": rbd.id, "name": rbd.name}
    if embedding:
        out["affected"] = {"rbds": embedding}
        out["note"] = "These diagrams embedded it as a sub-system and can no longer be analysed as they are."
    return out


# ---------------------------------------------------------------------------
# Plans
# ---------------------------------------------------------------------------

@_tool("upgrade_link", _LINK, "Get a link to upgrade")
def upgrade_link(
    ctx: Context,
    plan: Annotated[Literal["agent", "pro"], Field(
        description=f"agent = Reliafy Agent ({AGENT_PRICE}, MCP only: higher daily limits and storage); "
                    f"pro = Reliafy Pro ({PRO_PRICE}: everything, including fitting and simulation).")] = "agent",
) -> dict[str, Any]:
    """A link the user opens to subscribe to a paid Reliafy plan: Stripe's own checkout page, where they see
    the price and pay. Nothing is charged until they complete it there, so give them the link and let them
    decide; never say the upgrade has happened. Works even when the daily tool-call limit is used up. A user
    already on the other paid plan gets the billing page instead, to change plans there."""
    from backend.routers.billing import start_subscription  # local: routers import after this module

    user = _caller(ctx)
    base = f"{config.PUBLIC_BASE_URL or 'https://reliafy.com'}/"
    status, payload = start_subscription(_db(), user, plan, base, allow_switch=False)
    name, price = f"Reliafy {_PLAN_NAMES[plan]}", AGENT_PRICE if plan == "agent" else PRO_PRICE
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
        await self._manager.handle_request(scope, receive, send)


def _authenticate_request(authorization: str | None) -> tuple[int, dict | None, str]:
    return authenticate(_db(), authorization)


mcp_http_app = McpHttpApp(mcp)
