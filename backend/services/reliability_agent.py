"""Reliability Agent — Anthropic Managed Agents.

Runs Claude on Anthropic's **Managed Agents** runtime in a managed cloud sandbox
we provision with ``surpyval`` + ``repyability``. The agent assesses the user's
task, builds the best solution in the sandbox (with those two libraries only),
proposes a plan, and — after the user approves — calls Reliafy-side tools to load
the results (datasets + life models) into the user's workspace.

Self-contained and independent of the metered assistant
(``backend.services.assistant``): its own module, its own metering reason
(``"reliability_agent"``), its own config.

BETA NOTE: the Managed Agents API is beta (``managed-agents-2026-04-01``). The
SDK calls are isolated in this one module. The ``anthropic`` SDK is imported
lazily so the app imports fine even where it isn't installed; only live calls
need it.
"""

from __future__ import annotations

import json
import time

from backend import config
from backend.services import billing as billing_service

SYSTEM_PROMPT = (
    "You are the Reliafy Reliability Agent. You help reliability engineers analyse "
    "life data and build reliability models. You work in a sandbox with Python "
    "where ONLY surpyval and repyability are available for the reliability maths — "
    "use them for all fitting/analysis (do NOT use lifelines, the `reliability` "
    "package, scipy.stats survival, statsmodels, etc.). You also have three tools "
    "that write results into the user's Reliafy workspace: create_dataset, "
    "create_life_model, and create_rbd. You may call them AS MANY TIMES as the "
    "task needs — a single plan can create several datasets, several life models "
    "(e.g. one dataset per failure mode or subgroup, and multiple candidate "
    "models on the same dataset), and one or more RBDs.\n\n"
    "WORKFLOW — follow this every time:\n"
    "1. ASSESS the user's task and their data (load and inspect the uploaded CSV "
    "if there is one).\n"
    "2. BUILD the solution in the sandbox with surpyval/repyability — clean the "
    "data, try candidate distributions, check goodness-of-fit, decide the best "
    "model. Show the key numbers you computed.\n"
    "3. PLAN: state exactly what you will save to Reliafy as a numbered list — "
    "EVERY dataset, life model, and RBD you intend to create, each with its "
    "distribution/columns or structure. There may be one, or many, of each.\n"
    "4. ASK the user to approve the whole plan, then STOP and wait. Do NOT call "
    "any create tool until the user has clearly approved (e.g. 'yes', 'go ahead'). "
    "One approval covers the entire plan. If they change it, revise and ask "
    "again.\n"
    "5. LOAD once approved: create each dataset (each returns a dataset_id), then "
    "each life model referencing the right dataset_id, then any RBDs. Do the full "
    "batch — don't stop after one. Report everything you created.\n\n"
    "surpyval fitting: `import surpyval; m = surpyval.Weibull.fit(x, c=..., n=...)` "
    "(c = censoring flags 0 observed / 1 right / -1 left; n = counts; both "
    "optional); read m.params, m.aic(), m.sf(t), m.mean(), m.qf(p). "
    "create_life_model refits on Reliafy's side with surpyval and takes the FULL "
    "surpyval input surface — match what the data needs: the column mapping "
    "(time/censoring/counts, interval bounds, left/right truncation), the "
    "distribution (plain, discrete, non-parametric, or a regression id with "
    "covariates/formula), the offset / zero-inflation / limited-failure-population "
    "modifiers, and fixed parameters. Choose these from your analysis; don't leave "
    "out censoring or covariates the data clearly has.\n\n"
    "create_rbd builds a reliability block diagram from a simple structure: an "
    "ordered list of STAGES in series, each stage holding one or more COMPONENTS "
    "in parallel, with an optional k_of_n (k of the n components needed; omit or 1 "
    "= redundancy where any one suffices, n = all required in series). Each "
    "component's life model is either an inline distribution + params or a "
    "model_id from a create_life_model call. Reliafy lays it out (input → stages → "
    "output), validates, and saves it.\n\n"
    "UPLOADED DATA IS OPTIONAL. If the user gives no data (e.g. 'research this "
    "pump / truck type and build an RBD'), research the typical components and "
    "their failure distributions/parameters and build the RBD from those inline — "
    "an RBD needs no dataset. (Life models still need a dataset to fit.)\n\n"
    "SCOPE: you can create datasets, life models, and RBDs. Degradation, RCM, "
    "fleet, and other objects aren't available yet — if asked, say so. Be concise."
)

# Reliafy-side tools the agent can call. Execution happens in ``_execute_tool``
# on our backend, not in the sandbox.
_DIST_IDS = (
    "plain: weibull, exponential, normal, lognormal, gamma, loglogistic, "
    "expo_weibull, gumbel, logistic; discrete: discrete_weibull, geometric, "
    "negative_binomial; non-parametric: kaplan_meier, nelson_aalen, "
    "fleming_harrington, turnbull; regression (need covariates or a formula) — "
    "proportional-hazards {weibull,exponential,lognormal,normal,gamma}_ph and "
    "cox_ph, accelerated-failure-time *_aft, proportional-odds *_po, "
    "additive-hazards *_ah; or 'best' to auto-select the plain distribution by AIC"
)
# Column mapping: tool field -> surpyval x/c/n/xl/xr/tl/tr key.
_MAP_FIELDS = [
    ("time_column", "x"), ("censored_column", "c"), ("count_column", "n"),
    ("interval_lower_column", "xl"), ("interval_upper_column", "xr"),
    ("left_truncation_column", "tl"), ("right_truncation_column", "tr"),
]
TOOLS = [
    {
        "type": "custom",
        "name": "create_dataset",
        "description": (
            "Save a dataset to the user's Reliafy workspace. Provide the full CSV "
            "content (header + rows). Returns a dataset_id to use with "
            "create_life_model. Only call after the user approves the plan."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "A short name for the dataset."},
                "csv": {"type": "string", "description": "The full CSV content (header row + data rows)."},
            },
            "required": ["name", "csv"],
        },
    },
    {
        "type": "custom",
        "name": "create_life_model",
        "description": (
            "Fit and save a life model to a dataset in the user's Reliafy "
            "workspace. Reliafy performs the fit with surpyval (probability plot, "
            "parameters, CIs, goodness-of-fit). Supports full surpyval inputs: "
            "exact/censored/interval data, counts, truncation, the offset / "
            "zero-inflation / limited-failure-population modifiers, fixed "
            "parameters, and covariates/formula for regression models. Use after "
            "create_dataset; only call after the user approves the plan."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "A short name for the model."},
                "dataset_id": {"type": "string", "description": "From a prior create_dataset call."},
                "distribution": {"type": "string", "description": f"A surpyval id — {_DIST_IDS}."},
                # x/c/n/xl/xr/tl/tr column mapping.
                "time_column": {"type": "string", "description": "Column of exact/censored times (surpyval x). Use this, OR the interval pair below."},
                "censored_column": {"type": "string", "description": "Optional censoring-flag column (surpyval c): 0 observed, 1 right, -1 left, 2 interval."},
                "count_column": {"type": "string", "description": "Optional counts/quantities column (surpyval n) — repeats per row."},
                "interval_lower_column": {"type": "string", "description": "Interval-censoring lower bound (surpyval xl); pair with interval_upper_column instead of time_column."},
                "interval_upper_column": {"type": "string", "description": "Interval-censoring upper bound (surpyval xr)."},
                "left_truncation_column": {"type": "string", "description": "Left-truncation bound (surpyval tl) — e.g. left-entry / staggered start."},
                "right_truncation_column": {"type": "string", "description": "Right-truncation bound (surpyval tr)."},
                # Regression (used only for _ph/_aft/_po/_ah/cox_ph distributions).
                "covariates": {"type": "array", "items": {"type": "string"}, "description": "Covariate column names for a regression model. Give these OR a formula, not both."},
                "formula": {"type": "string", "description": "A formulaic formula over the columns for a regression model (e.g. 'age + sex + age:temp'). Handles categoricals."},
                # Modifiers (plain distributions only).
                "offset": {"type": "boolean", "description": "3-parameter fit: a failure-free period γ before which nothing fails (half-line distributions)."},
                "zero_inflated": {"type": "boolean", "description": "Zero-inflation: a fraction f0 failed at t=0 (dead on arrival)."},
                "limited_failure_population": {"type": "boolean", "description": "Limited failure population: only a fraction p can ever fail (cure fraction)."},
                "fixed": {"type": "object", "description": "Pin parameters by name to fixed values, e.g. {\"beta\": 2}.", "additionalProperties": {"type": "number"}},
                "unit": {"type": "string", "description": "Optional time unit, e.g. hours."},
            },
            "required": ["name", "dataset_id", "distribution"],
        },
    },
    {
        "type": "custom",
        "name": "create_rbd",
        "description": (
            "Build and save a reliability block diagram (RBD) to the user's "
            "Reliafy workspace. Give a simple structure: an ordered list of STAGES "
            "in series, each stage holding one or more COMPONENTS in parallel "
            "(redundancy), with an optional k_of_n voting requirement. Reliafy lays "
            "it out (input → stages → output), validates it, and saves it. Each "
            "component needs a life model — either an inline distribution + params "
            "(e.g. researched/typical values; NO dataset required) or a model_id "
            "from create_life_model. Only call after the user approves the plan."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "A short name for the RBD."},
                "stages": {
                    "type": "array",
                    "description": "Stages in series order (left → right). Components within a stage are in parallel.",
                    "items": {
                        "type": "object",
                        "properties": {
                            "label": {"type": "string", "description": "Name of this stage/block."},
                            "k_of_n": {"type": "integer", "description": "Components required to keep the stage working (k of the n components). Omit or 1 = plain parallel redundancy (any one); equal to the component count = all required (series)."},
                            "components": {
                                "type": "array",
                                "description": "One or more parallel components in this stage.",
                                "items": {
                                    "type": "object",
                                    "properties": {
                                        "label": {"type": "string", "description": "Component name."},
                                        "distribution": {"type": "string", "description": "Inline life model: a plain surpyval distribution id — weibull, exponential, normal, lognormal, gamma, loglogistic, expo_weibull, gumbel, logistic. Pair with params. Give this OR model_id."},
                                        "params": {"type": "array", "description": "Distribution parameters by surpyval name, e.g. [{\"name\":\"alpha\",\"value\":900},{\"name\":\"beta\",\"value\":1.4}] for weibull.", "items": {"type": "object", "properties": {"name": {"type": "string"}, "value": {"type": "number"}}, "required": ["name", "value"]}},
                                        "model_id": {"type": "string", "description": "Alternatively, a saved plain life model id (from create_life_model) to use for this component instead of inline params."},
                                    },
                                    "required": ["label"],
                                },
                            },
                        },
                        "required": ["components"],
                    },
                },
            },
            "required": ["name", "stages"],
        },
    },
]

# Bound the agentic tool loop so a misbehaving turn can't run forever.
_MAX_TOOL_ROUNDS = 10
# Where an uploaded CSV is mounted inside the sandbox for the agent to read.
_UPLOAD_MOUNT = "/mnt/session/uploads/data.csv"


class AgentError(RuntimeError):
    pass


def enabled() -> bool:
    return bool(config.ANTHROPIC_API_KEY)


def info() -> dict:
    return {"enabled": enabled(), "model": config.RELIABILITY_AGENT_MODEL,
            "packages": config.RELIABILITY_AGENT_PIP}


# ---- SDK boundary (everything Managed-Agents-specific lives below) ----------

def _client():
    try:
        from anthropic import Anthropic
    except ImportError as exc:  # pragma: no cover - depends on the deploy image
        raise AgentError("The anthropic SDK isn't installed on the server.") from exc
    if not config.ANTHROPIC_API_KEY:
        raise AgentError("The Reliability Agent isn't configured (no ANTHROPIC_API_KEY).")
    return Anthropic(
        api_key=config.ANTHROPIC_API_KEY,
        default_headers={"anthropic-beta": config.MANAGED_AGENTS_BETA},
    )


# The Environment (sandbox + packages) and Agent (model + prompt + tools) are
# created once and reused across sessions. Cached in-process; set the *_ID env
# vars to pin pre-created ones.
_BOOTSTRAP: dict = {}


def _ensure_agent(client) -> tuple[str, str]:
    """Return ``(agent_id, environment_id)``, creating them once if needed."""
    if config.RELIABILITY_AGENT_AGENT_ID and config.RELIABILITY_AGENT_ENV_ID:
        return config.RELIABILITY_AGENT_AGENT_ID, config.RELIABILITY_AGENT_ENV_ID
    if "agent_id" in _BOOTSTRAP:
        return _BOOTSTRAP["agent_id"], _BOOTSTRAP["environment_id"]

    env = client.beta.environments.create(
        name="reliafy-reliability-agent",
        config={
            "type": "cloud",
            "packages": {"pip": list(config.RELIABILITY_AGENT_PIP)},
            "networking": {"type": "unrestricted"},
        },
    )
    agent = client.beta.agents.create(
        name="Reliafy Reliability Agent",
        model=config.RELIABILITY_AGENT_MODEL,
        system=SYSTEM_PROMPT,
        tools=[{"type": "agent_toolset_20260401"}, *TOOLS],
    )
    _BOOTSTRAP["agent_id"] = agent.id
    _BOOTSTRAP["environment_id"] = env.id
    return agent.id, env.id


def upload_csv(data: bytes, filename: str = "data.csv") -> str:
    """Upload a CSV via the Files API; returns a ``file_id`` to attach to a run."""
    client = _client()
    uploaded = client.beta.files.upload(file=(filename, data, "text/csv"))
    return uploaded.id


# ---- Reliafy-side tool execution --------------------------------------------

_RBD_COL_W = 220  # horizontal spacing between stages in the laid-out diagram


def _rbd_component_model(db, uid: str, comp: dict) -> dict:
    """Node ``data.model`` for one RBD component — either an inline distribution
    + params (researched/typical values, no dataset needed) or the fitted params
    of a saved plain life model referenced by ``model_id``."""
    from backend import fitting
    from backend.services import models as models_service

    mid = (comp.get("model_id") or "").strip()
    if mid:
        m = models_service.get_model(db, mid, owner_id=uid)
        if m is None:
            raise ValueError(f"model_id '{mid}' not found")
        if m.kind != "distribution":
            raise ValueError(
                f"model “{m.name}” is a {m.kind} model; RBD components need a plain "
                "distribution — give distribution + params inline instead")
        r = m.results or {}
        return {"source": "params", "distribution": r.get("distribution") or m.distribution_id,
                "distribution_id": m.distribution_id,
                "params": [{"name": p["name"], "value": p["value"]} for p in (r.get("params") or [])]}

    dist = (comp.get("distribution") or "").strip()
    if not dist:
        raise ValueError(f"component “{comp.get('label') or '?'}” needs distribution + params, or a model_id")
    try:
        dist_id = fitting.resolve_distribution_id(dist)
    except fitting.FitError:
        dist_id = dist.lower()
    if dist_id not in fitting.DISTRIBUTIONS:
        raise ValueError(f"unsupported distribution '{dist}' — use one of {', '.join(fitting.DISTRIBUTIONS)}")
    params = [{"name": p.get("name"), "value": float(p.get("value"))}
              for p in (comp.get("params") or []) if p.get("name") is not None and p.get("value") is not None]
    if not params:
        raise ValueError(f"component “{comp.get('label') or dist_id}” needs params [{{name, value}}]")
    return {"source": "params", "distribution": fitting.DISTRIBUTIONS[dist_id]["name"],
            "distribution_id": dist_id, "params": params}


def _build_rbd_graph(db, uid: str, stages: list) -> dict:
    """Expand the agent's series-of-parallel stage spec into a React-Flow graph
    (input → stages → output) the RBD builder and analysis understand. A stage
    with >1 component gets a single k-of-n voting node (k=1 → plain parallel) as
    its exit, so consecutive parallel stages converge cleanly instead of meshing."""
    nodes = [{"id": "input", "type": "input", "position": {"x": 0, "y": 160}, "data": {"label": "Input"}}]
    edges = []
    prev_exit = "input"
    for si, stage in enumerate(stages):
        comps = stage.get("components") or []
        if not comps:
            raise ValueError(f"stage {si + 1} ({stage.get('label') or 'unnamed'}) has no components")
        x = _RBD_COL_W * (si + 1)
        m = len(comps)
        comp_ids = []
        for ci, comp in enumerate(comps):
            cid = f"s{si}c{ci}"
            y = round(160 + (ci - (m - 1) / 2) * 120)
            nodes.append({"id": cid, "type": "component", "position": {"x": x, "y": y},
                          "data": {"label": comp.get("label") or f"Component {ci + 1}",
                                   "model": _rbd_component_model(db, uid, comp)}})
            edges.append({"id": f"e-{prev_exit}-{cid}", "source": prev_exit, "target": cid})
            comp_ids.append(cid)
        if m > 1:
            k = max(1, min(int(stage.get("k_of_n") or 1), m))
            kid = f"s{si}k"
            nodes.append({"id": kid, "type": "knode", "position": {"x": x + _RBD_COL_W // 2, "y": 160},
                          "data": {"label": stage.get("label") or f"Stage {si + 1}", "n": k, "k": m}})
            for cid in comp_ids:
                edges.append({"id": f"e-{cid}-{kid}", "source": cid, "target": kid})
            prev_exit = kid
        else:
            prev_exit = comp_ids[0]
    out_x = _RBD_COL_W * (len(stages) + 1)
    nodes.append({"id": "output", "type": "output", "position": {"x": out_x, "y": 160}, "data": {"label": "Output"}})
    edges.append({"id": f"e-{prev_exit}-output", "source": prev_exit, "target": "output"})
    return {"nodes": nodes, "edges": edges}


def _execute_tool(db, uid: str, name: str, inp: dict) -> dict:
    """Run a custom tool on the Reliafy side and return a small JSON-safe result
    (the ``summary`` is shown to the user; the rest is fed back to the agent)."""
    from backend.fitting import FitError  # local: avoid heavy import at module load
    from backend.services import datasets as datasets_service
    from backend.services import models as models_service

    inp = inp or {}
    try:
        if name == "create_dataset":
            csv = inp.get("csv") or ""
            if not csv.strip():
                return {"error": "empty CSV"}
            ds = datasets_service.create_dataset(
                db, (inp.get("name") or "dataset").strip() or "dataset", csv.encode(), uid)
            return {"ok": True, "dataset_id": ds.id, "name": ds.name, "n_rows": ds.n_rows,
                    "summary": f"Created dataset “{ds.name}” ({ds.n_rows} rows)."}

        if name == "create_life_model":
            ds = datasets_service.get_dataset(db, inp.get("dataset_id", ""), owner_id=uid)
            if ds is None:
                return {"error": "dataset not found — create it first"}
            mapping = {key: inp[field] for field, key in _MAP_FIELDS if inp.get(field)}
            if not mapping.get("x") and not (mapping.get("xl") and mapping.get("xr")):
                return {"error": "map time_column, or both interval_lower_column and interval_upper_column"}
            covariates = list(inp.get("covariates") or []) or None
            options = {
                "offset": bool(inp.get("offset")),
                "zi": bool(inp.get("zero_inflated")),
                "lfp": bool(inp.get("limited_failure_population")),
                "fixed": inp.get("fixed") or None,
            }
            model = models_service.save_model(
                db, (inp.get("name") or "model").strip() or "model", ds,
                inp.get("distribution") or "best", mapping, covariates,
                inp.get("formula") or None, inp.get("unit"), owner_id=uid,
                options=options,
            )
            r = model.results or {}
            params = [{"name": p["name"], "value": p["value"]} for p in (r.get("params") or [])]
            return {"ok": True, "model_id": model.id, "distribution": r.get("distribution"),
                    "params": params,
                    "summary": f"Created life model “{model.name}” — {r.get('distribution')}."}

        if name == "create_rbd":
            from backend.services import rbds as rbds_service
            stages = inp.get("stages") or []
            if not stages:
                return {"error": "provide at least one stage"}
            graph = _build_rbd_graph(db, uid, stages)  # ValueError -> clean error below
            check = rbds_service.validate_graph(db, graph, owner_id=uid)
            if not check.get("valid", False):
                return {"error": "invalid RBD structure: " + "; ".join(check.get("errors") or ["unknown"])}
            rbd = rbds_service.save_rbd(
                db, (inp.get("name") or "RBD").strip() or "RBD", graph, owner_id=uid)
            n_comp = sum(1 for n in graph["nodes"] if n["type"] == "component")
            return {"ok": True, "rbd_id": rbd.id, "name": rbd.name,
                    "n_stages": len(stages), "n_components": n_comp,
                    "analytic": check.get("analytic", True),
                    "warnings": check.get("warnings") or [],
                    "summary": f"Created RBD “{rbd.name}” — {len(stages)} stages, {n_comp} components."}

        return {"error": f"unknown tool {name}"}
    except FitError as exc:
        return {"error": str(exc)}
    except ValueError as exc:  # bad RBD spec -> clean message the agent can fix
        return {"error": str(exc)}
    except Exception as exc:  # noqa: BLE001 - surface a clean tool error to the agent
        return {"error": f"{type(exc).__name__}: {exc}"}


# ---- Event normalisation ----------------------------------------------------

def _etype(event):
    return getattr(event, "type", None) or (event.get("type") if isinstance(event, dict) else None)


def _get(obj, *names):
    for n in names:
        v = getattr(obj, n, None)
        if v is None and isinstance(obj, dict):
            v = obj.get(n)
        if v is not None:
            return v
    return None


def _flatten_text(value) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        out = []
        for b in value:
            t = getattr(b, "text", None) or (b.get("text") if isinstance(b, dict) else None)
            out.append(t if t is not None else str(b))
        return "".join(out)
    return str(value)


def _norm(event) -> list[dict]:
    """Map a Managed Agents stream event to zero or more small dicts the UI
    renders. Defensive — the exact event schema is beta."""
    etype = _etype(event)
    if not etype or etype.startswith("span."):
        return []

    if etype in ("agent.message", "agent.message.delta", "message"):
        text = _flatten_text(_get(event, "text", "content"))
        return [{"type": "text", "text": text}] if text else []
    if etype in ("agent.thinking", "agent.thinking.delta"):
        return [{"type": "status", "status": "thinking"}]
    if etype in ("agent.tool_use", "tool_use"):
        inp = _get(event, "input") or {}
        code = isinstance(inp, dict) and (inp.get("command") or inp.get("code") or inp.get("content"))
        return [{"type": "tool_use", "name": _get(event, "name"), "code": code or None}]
    if etype in ("agent.tool_result", "tool_result"):
        text = _flatten_text(_get(event, "content", "output", "stdout"))
        return [{"type": "tool_result", "output": text}] if text else []
    # The agent calling one of OUR Reliafy tools (create_dataset / create_life_model).
    if etype == "agent.custom_tool_use":
        return [{"type": "reliafy_tool", "name": _get(event, "name"), "input": _get(event, "input") or {}}]
    if "status" in etype:
        return [{"type": "status", "status": etype.rsplit(".", 1)[-1]}]
    return []


def _event_usage(event) -> tuple[int, int]:
    """(input_tokens, output_tokens) from ``model_usage`` on span.model_request_end."""
    usage = getattr(event, "model_usage", None) or getattr(event, "usage", None)
    if usage is None and isinstance(event, dict):
        usage = event.get("model_usage") or event.get("usage")
    if not usage:
        return (0, 0)

    def _f(name):
        v = getattr(usage, name, None)
        if v is None and isinstance(usage, dict):
            v = usage.get(name)
        return int(v or 0)

    return (_f("input_tokens"), _f("output_tokens"))


def _is_idle(event) -> bool:
    etype = _etype(event)
    return bool(etype) and ("idle" in etype or etype.endswith("completed"))


# ---- Agentic run ------------------------------------------------------------

def stream_run(db, uid: str, message: str, file_id: str | None = None,
               session_id: str | None = None, approved: bool = False):
    """Advance the conversation one turn, executing any Reliafy tools the agent
    calls, and yield normalised events. Ends with ``{"type": "_meter", ...}``
    (session runtime, token totals, session_id to reuse next turn). A generator
    the router streams as SSE.

    When the agent calls a custom tool the session goes idle 'requires action'.
    ``approved`` is the HARD gate: the create tools only run when the turn is
    approved (the user clicked 'Approve & run'). An un-approved tool call is
    blocked — we hand the agent an error so it presents its plan and waits — so
    nothing is created without an explicit greenlight, whatever the model does."""
    client = _client()
    text = message

    if session_id:
        if file_id:  # attach a new file mid-thread
            try:
                client.beta.sessions.resources.add(
                    session_id, file_id=file_id, type="file", mount_path=_UPLOAD_MOUNT)
                text = f"{message}\n\nThe uploaded CSV is at {_UPLOAD_MOUNT} in the sandbox."
            except Exception:  # noqa: BLE001 - non-fatal
                pass
    else:
        agent_id, env_id = _ensure_agent(client)
        resources = None
        if file_id:
            resources = [{"type": "file", "file_id": file_id, "mount_path": _UPLOAD_MOUNT}]
            text = f"{message}\n\nThe uploaded CSV is at {_UPLOAD_MOUNT} in the sandbox."
        session = (
            client.beta.sessions.create(agent=agent_id, environment_id=env_id, resources=resources)
            if resources
            else client.beta.sessions.create(agent=agent_id, environment_id=env_id)
        )
        session_id = session.id

    started = time.monotonic()
    in_tok = out_tok = 0
    try:
        client.beta.sessions.events.send(
            session_id, events=[{"type": "user.message", "content": [{"type": "text", "text": text}]}]
        )
        for _round in range(_MAX_TOOL_ROUNDS):
            pending: list[dict] = []
            with client.beta.sessions.events.stream(session_id) as stream:
                for event in stream:
                    di, do = _event_usage(event)
                    in_tok += di
                    out_tok += do
                    if _etype(event) == "agent.custom_tool_use":
                        pending.append({"id": _get(event, "id"), "name": _get(event, "name"),
                                        "input": _get(event, "input") or {}})
                    for norm in _norm(event):
                        yield norm
                    if _is_idle(event):
                        break
            if not pending:
                break  # normal end of turn

            # Execute the Reliafy tools (only when the turn is approved), stream a
            # result line each, and hand the outcomes back to the agent.
            results = []
            for call in pending:
                if not approved:
                    yield {"type": "reliafy_tool_blocked", "name": call["name"]}
                    res = {"error": "The user has NOT approved yet. Present your "
                           "plan clearly and ask them to approve — do not call any "
                           "create tool until the turn is approved."}
                else:
                    res = _execute_tool(db, uid, call["name"], call["input"])
                    yield {"type": "reliafy_tool_result", "name": call["name"],
                           "ok": "error" not in res,
                           "summary": res.get("summary") or res.get("error") or "done"}
                results.append({
                    "type": "user.custom_tool_result",
                    "custom_tool_use_id": call["id"],
                    "content": [{"type": "text", "text": json.dumps(res)}],
                    "is_error": "error" in res,
                })
            client.beta.sessions.events.send(session_id, events=results)
    except AgentError:
        raise
    except Exception as exc:  # noqa: BLE001 - surface a clean error to the stream
        yield {"type": "error", "detail": str(exc)}
    finally:
        yield {
            "type": "_meter",
            "session_id": session_id,
            "seconds": max(0.0, time.monotonic() - started),
            "input_tokens": in_tok,
            "output_tokens": out_tok,
        }


def cost_millicents(seconds: float, input_tokens: int, output_tokens: int) -> int:
    """Metered charge for one run: token cost (same pricing/markup as the
    assistant) plus the Managed Agents session-runtime charge (USD/hour)."""
    tokens_mc = billing_service.ai_cost_millicents(
        config.RELIABILITY_AGENT_MODEL, input_tokens, output_tokens
    )
    usd = (max(0.0, seconds) / 3600.0) * config.MANAGED_AGENT_USD_PER_HOUR
    session_mc = round(usd * 100_000.0 * config.AI_MARKUP)
    return tokens_mc + session_mc
