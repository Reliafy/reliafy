"""Server-side AI assistant transport.

The assistant runs on the operator's provider key (never the user's), so usage
can be metered and billed as credits. This module advances the conversation by
exactly one provider round-trip: the client sends the system prompt, the native
message history, and the neutral tool list; we call the configured provider once
and return its assistant message plus the token usage. The client keeps running
the tool loop (tools execute in the browser), calling here again for each step.
"""

from __future__ import annotations

import httpx

from backend import config


class AssistantError(RuntimeError):
    pass


def enabled() -> bool:
    return bool(_api_key())


def info() -> dict:
    return {"enabled": enabled(), "provider": config.AI_PROVIDER, "model": config.AI_MODEL}


def _api_key():
    return config.ANTHROPIC_API_KEY if config.AI_PROVIDER == "anthropic" else config.OPENAI_API_KEY


def _anthropic_tools(tools):
    return [
        {"name": t["name"], "description": t.get("description", ""), "input_schema": t["parameters"]}
        for t in (tools or [])
    ]


def _openai_tools(tools):
    return [
        {"type": "function", "function": {"name": t["name"], "description": t.get("description", ""), "parameters": t["parameters"]}}
        for t in (tools or [])
    ]


def step(system: str, messages: list, tools: list) -> dict:
    """One provider round-trip. Returns
    ``{message, stop_reason, usage:{input_tokens, output_tokens}}`` where
    ``message`` is the provider-native assistant message the client appends."""
    if not enabled():
        raise AssistantError("AI is not configured on the server.")
    if config.AI_PROVIDER == "anthropic":
        return _anthropic(system, messages, tools)
    return _openai(system, messages, tools)


def _anthropic(system, messages, tools):
    try:
        r = httpx.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": config.ANTHROPIC_API_KEY,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json={
                "model": config.AI_MODEL,
                "max_tokens": 1500,
                "system": system,
                "tools": _anthropic_tools(tools),
                "messages": messages,
            },
            timeout=90.0,
        )
    except httpx.HTTPError as exc:
        raise AssistantError(f"Could not reach Anthropic: {exc}") from exc
    if r.status_code >= 400:
        raise AssistantError(_err(r, "Anthropic"))
    data = r.json()
    usage = data.get("usage", {})
    # Normalised usage contract: input_tokens = FULL-RATE input; cached reads
    # reported separately. Anthropic already reports cache reads outside
    # input_tokens, so the fields map straight across.
    return {
        "message": {"role": "assistant", "content": data.get("content", [])},
        "stop_reason": data.get("stop_reason"),
        "usage": {
            "input_tokens": int(usage.get("input_tokens", 0)),
            "cached_input_tokens": int(usage.get("cache_read_input_tokens", 0) or 0),
            "output_tokens": int(usage.get("output_tokens", 0)),
        },
    }


def _openai(system, messages, tools):
    try:
        r = httpx.post(
            "https://api.openai.com/v1/chat/completions",
            headers={"Authorization": f"Bearer {config.OPENAI_API_KEY}", "content-type": "application/json"},
            json={
                "model": config.AI_MODEL,
                "messages": [{"role": "system", "content": system}, *messages],
                "tools": _openai_tools(tools),
                "tool_choice": "auto",
            },
            timeout=90.0,
        )
    except httpx.HTTPError as exc:
        raise AssistantError(f"Could not reach OpenAI: {exc}") from exc
    if r.status_code >= 400:
        raise AssistantError(_err(r, "OpenAI"))
    data = r.json()
    usage = data.get("usage", {})
    # OpenAI's prompt_tokens INCLUDES cached tokens; split them out so
    # input_tokens is the full-rate count (normalised contract).
    details = usage.get("prompt_tokens_details") or {}
    cached = int(details.get("cached_tokens", 0) or 0)
    prompt = int(usage.get("prompt_tokens", 0))
    return {
        "message": data["choices"][0]["message"],
        "stop_reason": data["choices"][0].get("finish_reason"),
        "usage": {
            "input_tokens": max(0, prompt - cached),
            "cached_input_tokens": min(cached, prompt),
            "output_tokens": int(usage.get("completion_tokens", 0)),
        },
    }


def _err(resp, label):
    try:
        body = resp.json()
        detail = body.get("error", {}).get("message") or body.get("message") or resp.text
    except Exception:  # noqa: BLE001
        detail = resp.text
    return f"{label} error ({resp.status_code}): {detail}"
