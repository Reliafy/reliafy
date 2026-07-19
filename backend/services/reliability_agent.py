"""Reliability Agent — Anthropic Managed Agents.

Runs Claude on Anthropic's **Managed Agents** runtime in a managed cloud sandbox
we provision with ``surpyval`` + the scientific stack, so it can fit real
reliability models on uploaded data and stream its work back over SSE.

Self-contained and independent of the metered assistant
(``backend.services.assistant``): its own module, its own metering reason
(``"reliability_agent"``), its own config. When it's ready to take over, the old
assistant can be deleted without touching this.

BETA NOTE: the Managed Agents API is beta (``managed-agents-2026-04-01``). The
SDK calls here follow the docs as of 2026-07 and *will* need adjusting as the
API firms up — they're deliberately isolated in this one module (``_client``,
``_ensure_agent``, ``upload_csv``, ``stream_run``) so that's a one-file change.
The ``anthropic`` SDK is imported lazily so this module (and the whole app)
imports fine even where the SDK isn't installed; only live calls need it.
"""

from __future__ import annotations

import time

from backend import config
from backend.services import billing as billing_service

SYSTEM_PROMPT = (
    "You are the Reliafy Reliability Agent. You help reliability engineers with "
    "life-data analysis, failure distributions, censoring/truncation, degradation, "
    "and maintenance decisions. You run in a sandbox with Python and surpyval "
    "installed. Prefer WRITING AND RUNNING CODE to do real work on the user's "
    "uploaded data — load and clean the CSV, fit models with surpyval, compute "
    "metrics, make plots — over describing what you would do. When you fit a "
    "model, report the distribution, parameters, and a goodness-of-fit summary. "
    "Be concise and show the numbers you actually computed."
)


class AgentError(RuntimeError):
    pass


def enabled() -> bool:
    return bool(config.ANTHROPIC_API_KEY)


def info() -> dict:
    return {
        "enabled": enabled(),
        "model": config.RELIABILITY_AGENT_MODEL,
        "packages": config.RELIABILITY_AGENT_PIP,
    }


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
        tools=[{"type": "agent_toolset_20260401"}],
    )
    _BOOTSTRAP["agent_id"] = agent.id
    _BOOTSTRAP["environment_id"] = env.id
    return agent.id, env.id


def upload_csv(data: bytes, filename: str = "data.csv") -> str:
    """Upload a CSV via the Files API; returns a ``file_id`` to attach to a run."""
    client = _client()
    uploaded = client.beta.files.upload(file=(filename, data, "text/csv"))
    return uploaded.id


def _norm(event) -> dict | None:
    """Best-effort map of a Managed Agents stream event to a small dict the UI
    renders. Unknown shapes are forwarded generically. Defensive on purpose —
    the exact event schema is beta."""
    etype = getattr(event, "type", None) or (event.get("type") if isinstance(event, dict) else None)
    if not etype:
        return None

    def _get(obj, *names):
        for n in names:
            v = getattr(obj, n, None)
            if v is None and isinstance(obj, dict):
                v = obj.get(n)
            if v is not None:
                return v
        return None

    # Assistant text.
    if etype in ("agent.message", "agent.message.delta", "message"):
        text = _get(event, "text", "content")
        return {"type": "text", "text": _flatten_text(text)}
    # The agent invoking a built-in tool (bash/read/write/…) — show the command/code.
    if etype in ("agent.tool_use", "tool_use"):
        inp = _get(event, "input") or {}
        return {"type": "tool_use", "name": _get(event, "name"),
                "code": (isinstance(inp, dict) and (inp.get("command") or inp.get("code") or inp.get("content"))) or None,
                "input": inp}
    # Tool output.
    if etype in ("agent.tool_result", "tool_result"):
        return {"type": "tool_result", "output": _flatten_text(_get(event, "content", "output", "stdout"))}
    # The agent calling one of *our* custom tools (e.g. save to Reliafy) — later.
    if etype in ("agent.custom_tool_use",):
        return {"type": "custom_tool_use", "name": _get(event, "name"), "input": _get(event, "input")}
    if etype.startswith("session.status"):
        return {"type": "status", "status": etype}
    return {"type": "raw", "event": etype}


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


def _event_usage(event) -> tuple[int, int]:
    """(input_tokens, output_tokens) from an event that carries usage, else (0,0)."""
    usage = getattr(event, "usage", None)
    if usage is None and isinstance(event, dict):
        usage = event.get("usage")
    if not usage:
        return (0, 0)
    def _f(name):
        v = getattr(usage, name, None)
        if v is None and isinstance(usage, dict):
            v = usage.get(name)
        return int(v or 0)
    return (_f("input_tokens"), _f("output_tokens"))


def _is_idle(event) -> bool:
    etype = getattr(event, "type", None) or (event.get("type") if isinstance(event, dict) else None)
    return etype in ("session.status_idle", "session.idle", "session.completed")


def stream_run(message: str, file_id: str | None = None):
    """Run one turn on a fresh session and yield normalised events as they
    arrive, then a final ``{"type": "_meter", ...}`` with the session runtime and
    token totals for billing. A generator so the router can stream it as SSE."""
    client = _client()
    agent_id, env_id = _ensure_agent(client)
    session = client.beta.sessions.create(agent=agent_id, environment_id=env_id)

    content: list = [{"type": "text", "text": message}]
    if file_id:
        content.append({"type": "container_upload", "file_id": file_id})

    started = time.monotonic()
    in_tok = out_tok = 0
    try:
        client.beta.sessions.events.send(
            session.id, events=[{"type": "user.message", "content": content}]
        )
        with client.beta.sessions.events.stream(session.id) as stream:
            for event in stream:
                di, do = _event_usage(event)
                in_tok += di
                out_tok += do
                norm = _norm(event)
                if norm:
                    yield norm
                if _is_idle(event):
                    break
    except AgentError:
        raise
    except Exception as exc:  # noqa: BLE001 - surface a clean error to the stream
        yield {"type": "error", "detail": str(exc)}
    finally:
        yield {
            "type": "_meter",
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
