"""Metered AI assistant proxy.

Advances the assistant conversation one provider round-trip at a time on the
operator's key, charging the user's credit balance for the tokens used (when
billing is enabled). The client runs the tool loop and calls here per step,
sending only the message history: the system prompt and the tool definitions
are the server's own (``backend.services.assistant_spec``).

Metering: before the provider is called, the step's maximum cost is held from
the balance (one conditional update — concurrent steps can't together spend
more than the user has); afterwards the hold is settled to the actual cost.
The streaming endpoint runs the provider call and the settlement on a worker
thread, so a client that disconnects mid-stream is still charged for what was
used and gets the rest of the hold back. Requests are capped in size and
message count, and a user may have only ``AI_MAX_CONCURRENT`` AI requests
running at once.
"""

from __future__ import annotations

import json
import logging

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse, StreamingResponse
from starlette.concurrency import run_in_threadpool

from backend import config
from backend.auth import get_current_user
from backend.db import get_session
from backend.services import ai_relay
from backend.services import assistant as assistant_service
from backend.services import billing as billing_service

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api")

REASON = "assistant"


def _sse(payload: dict) -> str:
    return f"data: {json.dumps(payload)}\n\n"


@router.get("/assistant/info")
def assistant_info(session=Depends(get_session), user: dict = Depends(get_current_user)) -> dict:
    acct = billing_service.account(session, user["uid"])
    info = assistant_service.info()
    return {
        **info,
        "billing_enabled": config.BILLING_ENABLED,
        "admin": billing_service.is_admin_user(user),  # admins aren't charged
        "credit_cents": acct["credit_cents"],
    }


class _Refused(Exception):
    def __init__(self, status: int, detail: str, code: str | None = None):
        self.response = JSONResponse(
            status_code=status, content={"detail": detail, **({"code": code} if code else {})})


async def _read_messages(request: Request) -> list:
    """The request's ``messages``, read with a size cap. Any ``system`` or
    ``tools`` in the body are ignored — the server supplies its own."""
    cap = config.AI_MAX_REQUEST_BYTES
    too_large = _Refused(413, "This conversation is too large to send. Start a new chat to continue.",
                         "too_large")
    declared = request.headers.get("content-length")
    if declared and declared.isdigit() and int(declared) > cap:
        raise too_large
    buf = bytearray()
    async for piece in request.stream():
        buf.extend(piece)
        if len(buf) > cap:
            raise too_large
    try:
        body = json.loads(bytes(buf) or b"null")
    except ValueError:
        raise _Refused(400, "The request body must be JSON.") from None
    messages = body.get("messages") if isinstance(body, dict) else None
    problem = assistant_service.check_messages(messages)
    if problem:
        raise _Refused(400, problem)
    return messages


def _cost_mc(usage: dict) -> int:
    # Metered at millicent precision, with cached prompt tokens billed at the
    # provider's cached rate — maps user charges tightly onto actual $ cost.
    return billing_service.ai_cost_millicents(
        config.AI_MODEL,
        usage["input_tokens"],
        usage["output_tokens"],
        usage.get("cached_input_tokens", 0),
    )


class _Metering:
    """The concurrency slot and credit hold of one assistant step. ``finish``
    is idempotent: it settles the hold (to the recorded cost, or returns all
    of it if the step produced no usage) and frees the slot."""

    def __init__(self, session, uid: str, metered: bool):
        self.session, self.uid, self.metered = session, uid, metered
        self.slot = None
        self.hold_id = None
        self.cost_mc: int | None = None

    def start(self, messages: list) -> None:
        self.slot = billing_service.acquire_ai_slot(self.session, self.uid, "assistant")
        if self.slot is None:
            raise _Refused(429, "Another AI request is still running. Wait for it to finish, then try again.",
                           "busy")
        if not self.metered:
            return
        hold = assistant_service.hold_millicents(messages)
        self.hold_id = billing_service.reserve_millicents(self.session, self.uid, hold, REASON)
        if self.hold_id is None:
            self.finish()
            have = billing_service.account(self.session, self.uid)["credit_cents"]
            need = -(-hold // 1000)
            raise _Refused(
                402,
                ("You're out of AI credits. Top up to keep using the assistant." if have <= 0 else
                 f"This step needs up to {need} AI credits and you have {have}. "
                 "Top up to keep using the assistant."),
                "no_credits",
            )

    def finish(self) -> int:
        try:
            if self.hold_id:
                hold_id, self.hold_id = self.hold_id, None
                return billing_service.settle_hold(self.session, hold_id, self.cost_mc)
            return billing_service.account(self.session, self.uid)["credit_cents"]
        finally:
            slot, self.slot = self.slot, None
            billing_service.release_ai_slot(self.session, slot)


def _begin(session, user: dict, messages: list) -> _Metering:
    """Concurrency slot + credit hold for one step (raises :class:`_Refused`)."""
    if not assistant_service.enabled():
        raise _Refused(503, "The AI assistant isn't configured yet.")
    # Operator accounts aren't credit-checked or charged.
    metered = config.BILLING_ENABLED and not billing_service.is_admin_user(user)
    meter = _Metering(session, user["uid"], metered)
    meter.start(messages)
    return meter


def _step(session, user: dict, messages: list) -> JSONResponse:
    try:
        meter = _begin(session, user, messages)
    except _Refused as refused:
        return refused.response
    system, tools = assistant_service.spec()
    try:
        try:
            result = assistant_service.step(system, messages, tools)
        except assistant_service.AssistantError as exc:
            return JSONResponse(status_code=502, content={"detail": str(exc)})
        usage = result["usage"]
        meter.cost_mc = _cost_mc(usage)
    finally:
        balance = meter.finish()
    cost_mc = meter.cost_mc
    return JSONResponse(content={
        "message": result["message"],
        "stop_reason": result.get("stop_reason"),
        "usage": usage,
        "cost_millicents": cost_mc,
        "cost_cents": max(1, -(-cost_mc // 1000)),  # informational, whole credits
        "credit_cents": balance,
    })


@router.post("/assistant/step")
async def assistant_step(
    request: Request,
    session=Depends(get_session),
    user: dict = Depends(get_current_user),
) -> JSONResponse:
    try:
        messages = await _read_messages(request)
    except _Refused as refused:
        return refused.response
    return await run_in_threadpool(_step, session, user, messages)


def stream_relay(session, user: dict, messages: list) -> ai_relay.Relay | JSONResponse:
    """Start a streamed step: a :class:`ai_relay.Relay` whose items are the
    SSE payloads, or the refusal. The provider call and the settlement run on
    the relay's worker thread, so they complete even if nobody reads."""
    try:
        meter = _begin(session, user, messages)
    except _Refused as refused:
        return refused.response
    system, tools = assistant_service.spec()

    def produce(emit, _stopped) -> None:
        try:
            for ev in assistant_service.stream(system, messages, tools):
                if ev["type"] == "delta":
                    emit({"type": "delta", "text": ev["text"]})
                elif ev["type"] == "final":
                    usage = ev["usage"]
                    meter.cost_mc = cost_mc = _cost_mc(usage)
                    balance = meter.finish()
                    emit({
                        "type": "final",
                        "message": ev["message"],
                        "stop_reason": ev.get("stop_reason"),
                        "usage": usage,
                        "cost_millicents": cost_mc,
                        "cost_cents": max(1, -(-cost_mc // 1000)),
                        "credit_cents": balance,
                    })
        except assistant_service.AssistantError as exc:
            emit({"type": "error", "detail": str(exc)})
        except Exception as exc:  # noqa: BLE001
            logger.exception("assistant stream failed")
            emit({"type": "error", "detail": str(exc)})
        finally:
            meter.finish()

    return ai_relay.Relay(produce).start()


@router.post("/assistant/stream")
async def assistant_stream(
    request: Request,
    session=Depends(get_session),
    user: dict = Depends(get_current_user),
):
    """Same as ``/assistant/step`` but streams the provider's output as SSE:
    ``{type:"delta", text}`` frames as the assistant writes, then a terminal
    ``{type:"final", message, stop_reason, usage, credit_cents}`` the client
    uses to continue the tool loop. The credit hold is settled when the
    provider call ends, whether or not the client is still connected."""
    try:
        messages = await _read_messages(request)
    except _Refused as refused:
        return refused.response
    relay = await run_in_threadpool(stream_relay, session, user, messages)
    if isinstance(relay, JSONResponse):
        return relay
    return StreamingResponse(
        (_sse(item) for item in relay.items()),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
