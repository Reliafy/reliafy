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
    "and maintenance decisions. You run in a sandbox with Python, surpyval and "
    "repyability installed. Prefer WRITING AND RUNNING CODE to do real work on the "
    "user's uploaded data — load and clean the CSV, fit models with surpyval, "
    "compute metrics, make plots — over describing what you would do. "
    "surpyval basics: fit with `import surpyval; m = surpyval.Weibull.fit(x, c=..., n=...)` "
    "(c = censoring flags 0/1/-1, n = counts, both optional); read results from "
    "`m.params`, `m.aic()`, `m.bic()`, and the functions `m.sf(t)`, `m.ff(t)`, "
    "`m.hf(t)`, `m.mean()`, `m.qf(p)`. When you fit a model, report the "
    "distribution, parameters, and a goodness-of-fit summary. Be concise and show "
    "the numbers you actually computed.\n\n"
    "DISPLAYING CHARTS — CRITICAL: the user CANNOT see the sandbox filesystem, so "
    "saving a PNG is NOT enough — a saved plot is invisible to them. There are two "
    "ways to show a chart:\n"
    "1) PREFERRED — if the conversation gives you a chart upload URL, save the PNG "
    "(dpi=90, bbox_inches='tight') and run:  curl -s -F \"file=@/tmp/c.png\" \"<that url>\"\n"
    "   The command prints a small placement marker — that's all that's needed. Do "
    "NOT print base64 when an upload URL is available.\n"
    "2) FALLBACK — only when NO upload URL was provided, print the image as base64 "
    "in the SAME python script that builds the plot:\n"
    "    fig.savefig('/tmp/c.png', dpi=90, bbox_inches='tight')\n"
    "    import base64, sys\n"
    "    sys.stdout.write('<<RELIAFY_IMG>>' + base64.b64encode(open('/tmp/c.png','rb').read()).decode() + '<<END_IMG>>')\n"
    "Do one of these for every chart, immediately. Never just say 'the chart is "
    "saved'."
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


import re
import uuid
from datetime import datetime, timedelta, timezone

# Two chart channels (see the system prompt). Preferred: the agent curls the
# PNG to our artifact endpoint (the sandbox has unrestricted egress), which
# responds with a tiny placement marker — no image bytes ride through the model.
# Fallback (local dev, where the sandbox can't reach localhost): inline base64.
_IMG_RE = re.compile(r"<<RELIAFY_IMG>>(.*?)<<END_IMG>>", re.DOTALL)
_ARTIFACT_RE = re.compile(r"<<RELIAFY_ARTIFACT:([A-Za-z0-9_-]+)>>")

# Artifact upload limits (per run token / per file).
_ARTIFACT_TOKEN_TTL = timedelta(minutes=30)
_ARTIFACT_MAX_USES = 12
_ARTIFACT_MAX_BYTES = 3 * 1024 * 1024
_PNG_MAGIC = b"\x89PNG\r\n\x1a\n"


def _extract_images(text: str) -> tuple[str, list[dict]]:
    """Pull chart references out of agent output. Returns the text with markers
    removed and image events — ``{"type": "image", "url": …}`` for uploaded
    artifacts, ``{"type": "image", "data": …}`` for inline base64."""
    if not text or ("<<RELIAFY" not in text):
        return text, []
    images: list[dict] = []
    for aid in _ARTIFACT_RE.findall(text):
        images.append({"type": "image", "url": f"/api/reliability-agent/artifacts/{aid}"})
    for m in _IMG_RE.findall(text):
        b64 = "".join(m.split())  # strip whitespace/newlines the shell may add
        if b64:
            images.append({"type": "image", "data": f"data:image/png;base64,{b64}"})
    cleaned = _ARTIFACT_RE.sub("", _IMG_RE.sub("", text)).strip()
    return cleaned, images


# ---- Chart artifacts (sandbox -> backend uploads) ---------------------------

def mint_artifact_token(db, uid: str) -> str:
    """A short-lived, single-run token the sandbox uses to POST charts back."""
    token = uuid.uuid4().hex
    db.agent_artifact_tokens.insert_one({
        "_id": token, "uid": uid, "uses": 0,
        "expires_at": datetime.now(timezone.utc) + _ARTIFACT_TOKEN_TTL,
    })
    return token


def save_artifact(db, token: str, data: bytes) -> str:
    """Validate the token + PNG payload and store the chart; returns its id.
    Raises ``AgentError`` with a short reason on any failure."""
    doc = db.agent_artifact_tokens.find_one({"_id": token})
    now = datetime.now(timezone.utc)
    expires = doc.get("expires_at") if doc else None
    if expires is not None and expires.tzinfo is None:  # mongo returns naive UTC
        expires = expires.replace(tzinfo=timezone.utc)
    if doc is None or expires is None or expires < now:
        raise AgentError("invalid or expired upload token")
    if doc.get("uses", 0) >= _ARTIFACT_MAX_USES:
        raise AgentError("upload limit reached for this run")
    if len(data) > _ARTIFACT_MAX_BYTES:
        raise AgentError("file too large")
    if not data.startswith(_PNG_MAGIC):
        raise AgentError("only PNG charts are accepted")
    artifact_id = uuid.uuid4().hex
    db.agent_artifacts.insert_one({
        "_id": artifact_id, "uid": doc["uid"], "data": data,
        "mime": "image/png", "created_at": now,
    })
    db.agent_artifact_tokens.update_one({"_id": token}, {"$inc": {"uses": 1}})
    return artifact_id


def get_artifact(db, uid: str, artifact_id: str) -> bytes | None:
    """The chart bytes, scoped to its owner. None when unknown/not yours."""
    doc = db.agent_artifacts.find_one({"_id": artifact_id, "uid": uid})
    return bytes(doc["data"]) if doc else None


def _norm(event) -> list[dict]:
    """Map a Managed Agents stream event to zero or more small dicts the UI
    renders. Defensive on purpose — the exact event schema is beta."""
    etype = getattr(event, "type", None) or (event.get("type") if isinstance(event, dict) else None)
    if not etype:
        return []

    def _get(obj, *names):
        for n in names:
            v = getattr(obj, n, None)
            if v is None and isinstance(obj, dict):
                v = obj.get(n)
            if v is not None:
                return v
        return None

    # Internal spans (model request start/end) carry no user-facing content.
    if etype.startswith("span."):
        return []

    # Assistant text — the model may echo a placement marker in its prose, so
    # extract/strip chart markers here too (the UI dedupes repeats).
    if etype in ("agent.message", "agent.message.delta", "message"):
        text, images = _extract_images(_flatten_text(_get(event, "text", "content")))
        out = [{"type": "text", "text": text}] if text else []
        out.extend(images)
        return out
    # Extended thinking — surfaced as a subtle status, not full content.
    if etype in ("agent.thinking", "agent.thinking.delta"):
        return [{"type": "status", "status": "thinking"}]
    # The agent invoking a built-in tool (bash/read/write/…) — show the command/code.
    if etype in ("agent.tool_use", "tool_use"):
        inp = _get(event, "input") or {}
        return [{"type": "tool_use", "name": _get(event, "name"),
                 "code": (isinstance(inp, dict) and (inp.get("command") or inp.get("code") or inp.get("content"))) or None}]
    # Tool output — split out any chart marker(s): uploaded-artifact refs and/or
    # inline base64.
    if etype in ("agent.tool_result", "tool_result"):
        text, images = _extract_images(_flatten_text(_get(event, "content", "output", "stdout")))
        out = []
        if text:
            out.append({"type": "tool_result", "output": text})
        out.extend(images)
        return out
    # The agent calling one of *our* custom tools (e.g. save to Reliafy) — later.
    if etype in ("agent.custom_tool_use",):
        return [{"type": "custom_tool_use", "name": _get(event, "name"), "input": _get(event, "input")}]
    # Session-level status transitions (…thread_status_idle / …status_running).
    if "status" in etype:
        return [{"type": "status", "status": etype.rsplit(".", 1)[-1]}]
    return []  # user.message echo, unknown internal events — nothing to render


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
    """(input_tokens, output_tokens) from an event that carries usage, else (0,0).

    Managed Agents reports per-model-request usage as ``model_usage`` on
    ``span.model_request_end`` events (there's no top-level ``usage``)."""
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
    etype = getattr(event, "type", None) or (event.get("type") if isinstance(event, dict) else None)
    # e.g. session.thread_status_idle / session.status_idle.
    return bool(etype) and ("idle" in etype or etype.endswith("completed"))


# Where an uploaded CSV is mounted inside the sandbox for the agent to read.
_UPLOAD_MOUNT = "/mnt/session/uploads/data.csv"


def stream_run(message: str, file_id: str | None = None, session_id: str | None = None,
               artifact_url: str | None = None):
    """Advance the conversation one turn and yield normalised events as they
    arrive, then a final ``{"type": "_meter", ...}`` (with the session runtime,
    token totals, and the ``session_id`` to reuse for the next turn). A generator
    so the router can stream it as SSE.

    Multi-turn: pass ``session_id`` to continue an existing conversation (its
    history + sandbox state persist server-side); omit it to start a new one. An
    uploaded ``file_id`` is mounted into the sandbox as a file the agent reads
    with pandas (Managed Agents mounts files as session *resources*).
    ``artifact_url`` is the signed endpoint the sandbox curls charts to (the
    preferred channel — no image bytes through the model); when absent the agent
    falls back to inline base64 markers."""
    client = _client()
    text = message
    if artifact_url:
        text = (
            f"{message}\n\n"
            f"[chart uploads for this conversation: after saving each chart PNG run "
            f"`curl -s -F \"file=@/tmp/c.png\" \"{artifact_url}\"` — it prints the "
            f"placement marker. Do NOT print base64.]"
        )
        message = text  # the file-mount appendix below builds on this

    if session_id:
        # Continue the conversation; attach a new file mid-thread if given.
        if file_id:
            try:
                client.beta.sessions.resources.add(
                    session_id, file_id=file_id, type="file", mount_path=_UPLOAD_MOUNT)
                text = f"{message}\n\nThe uploaded CSV is available in the sandbox at {_UPLOAD_MOUNT}."
            except Exception:  # noqa: BLE001 - non-fatal; carry on without the mount
                pass
    else:
        agent_id, env_id = _ensure_agent(client)
        resources = None
        if file_id:
            resources = [{"type": "file", "file_id": file_id, "mount_path": _UPLOAD_MOUNT}]
            text = f"{message}\n\nThe uploaded CSV is available in the sandbox at {_UPLOAD_MOUNT}."
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
        with client.beta.sessions.events.stream(session_id) as stream:
            for event in stream:
                di, do = _event_usage(event)
                in_tok += di
                out_tok += do
                for norm in _norm(event):
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
