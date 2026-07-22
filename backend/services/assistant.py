"""Server-side AI assistant transport.

The assistant runs on the operator's provider key (never the user's), so usage
can be metered and billed as credits. This module advances the conversation by
exactly one provider round-trip: the client sends the system prompt, the native
message history, and the neutral tool list; we call the configured provider once
and return its assistant message plus the token usage. The client keeps running
the tool loop (tools execute in the browser), calling here again for each step.
"""

from __future__ import annotations

import json

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
    # Responses API function-tool shape is flat (name/description/parameters at
    # the top level), unlike chat/completions' nested {"function": {...}}.
    return [
        {"type": "function", "name": t["name"], "description": t.get("description", ""), "parameters": t["parameters"]}
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


# OpenAI Responses API (/v1/responses). `messages` is the running list of
# Responses *input items* the client maintains — user turns plus the raw
# `output` items from each prior step (assistant messages, function_call, and
# reasoning items) with function_call_output items spliced in after each tool
# runs. We resend the whole list every step (store=False, stateless), and
# request reasoning.encrypted_content so reasoning carries across the tool loop
# within a turn.
def _openai_body(system, messages, tools, *, stream: bool):
    body = {
        "model": config.AI_MODEL,
        "input": messages,
        "tools": _openai_tools(tools),
        "tool_choice": "auto",
        "store": False,
        "stream": stream,
    }
    if system:
        body["instructions"] = system
    if config.OPENAI_REASONING_EFFORT:
        body["reasoning"] = {"effort": config.OPENAI_REASONING_EFFORT}
        body["include"] = ["reasoning.encrypted_content"]
    return body


_OPENAI_HEADERS = {"content-type": "application/json"}


def _openai_result(output, usage):
    # input_tokens INCLUDES cached tokens; split them out so input_tokens is the
    # full-rate count (normalised contract). output_tokens already includes
    # reasoning tokens, which is what we bill. The client appends every output
    # item to its history verbatim and resends them next step (llm.js:runOpenAI).
    output = output or []
    usage = usage or {}
    cached = int((usage.get("input_tokens_details") or {}).get("cached_tokens", 0) or 0)
    prompt = int(usage.get("input_tokens", 0))
    has_calls = any(it.get("type") == "function_call" for it in output)
    return {
        "message": output,
        "stop_reason": "tool_use" if has_calls else "completed",
        "usage": {
            "input_tokens": max(0, prompt - cached),
            "cached_input_tokens": min(cached, prompt),
            "output_tokens": int(usage.get("output_tokens", 0)),
        },
    }


def _openai(system, messages, tools):
    body = _openai_body(system, messages, tools, stream=False)
    try:
        r = httpx.post(
            "https://api.openai.com/v1/responses",
            headers={"Authorization": f"Bearer {config.OPENAI_API_KEY}", **_OPENAI_HEADERS},
            json=body,
            timeout=120.0,
        )
    except httpx.HTTPError as exc:
        raise AssistantError(f"Could not reach OpenAI: {exc}") from exc
    if r.status_code >= 400:
        raise AssistantError(_err(r, "OpenAI"))
    data = r.json()
    return _openai_result(data.get("output", []), data.get("usage", {}))


def stream(system: str, messages: list, tools: list):
    """One provider round-trip, streamed. Yields dicts:
    ``{"type": "delta", "text": ...}`` for incremental assistant text, then a
    single terminal ``{"type": "final", "message", "stop_reason", "usage"}``
    (same shape :func:`step` returns) the client uses to run the tool loop.
    Raises :class:`AssistantError` on transport/provider failure."""
    if not enabled():
        raise AssistantError("AI is not configured on the server.")
    if config.AI_PROVIDER == "anthropic":
        # Anthropic path isn't wired for token streaming yet: emit the whole
        # message as one delta so the stream endpoint still works if flipped.
        res = _anthropic(system, messages, tools)
        text = "".join(
            c.get("text", "") for c in res["message"].get("content", []) if c.get("type") == "text"
        )
        if text:
            yield {"type": "delta", "text": text}
        yield {"type": "final", **res}
        return
    yield from _openai_stream(system, messages, tools)


def _openai_stream(system, messages, tools):
    body = _openai_body(system, messages, tools, stream=True)
    try:
        with httpx.stream(
            "POST",
            "https://api.openai.com/v1/responses",
            headers={"Authorization": f"Bearer {config.OPENAI_API_KEY}", **_OPENAI_HEADERS},
            json=body,
            timeout=httpx.Timeout(120.0, read=None),
        ) as r:
            if r.status_code >= 400:
                r.read()
                raise AssistantError(_err(r, "OpenAI"))
            for line in r.iter_lines():
                if not line or not line.startswith("data:"):
                    continue
                data = line[5:].strip()
                if not data:
                    continue
                try:
                    ev = json.loads(data)
                except ValueError:
                    continue
                etype = ev.get("type")
                if etype == "response.output_text.delta":
                    delta = ev.get("delta") or ""
                    if delta:
                        yield {"type": "delta", "text": delta}
                elif etype == "response.completed":
                    resp = ev.get("response", {}) or {}
                    yield {"type": "final", **_openai_result(resp.get("output", []), resp.get("usage", {}))}
                elif etype in ("response.failed", "response.incomplete", "error"):
                    resp = ev.get("response", {}) or {}
                    err = resp.get("error") or resp.get("incomplete_details") or ev.get("error") or {}
                    detail = err.get("message") if isinstance(err, dict) else str(err)
                    raise AssistantError(f"OpenAI stream error: {detail or etype}")
    except httpx.HTTPError as exc:
        raise AssistantError(f"Could not reach OpenAI: {exc}") from exc


def _err(resp, label):
    try:
        body = resp.json()
        detail = body.get("error", {}).get("message") or body.get("message") or resp.text
    except Exception:  # noqa: BLE001
        detail = resp.text
    return f"{label} error ({resp.status_code}): {detail}"
