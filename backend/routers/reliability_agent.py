"""Reliability Agent API (Anthropic Managed Agents).

Self-contained sibling of the metered assistant router: upload a CSV, then run
the managed agent and stream its work back over SSE. The agent proposes a plan
and, once the user approves, calls Reliafy-side tools to load datasets + life
models into the user's workspace. Charges the user's credit balance under its
own metering reason (``"reliability_agent"``).
"""

from __future__ import annotations

import json
import logging

from fastapi import APIRouter, Body, Depends, Request
from fastapi.responses import JSONResponse, StreamingResponse
from starlette.concurrency import run_in_threadpool
from starlette.datastructures import UploadFile as StarletteUploadFile

from backend import config
from backend.auth import get_current_user
from backend.db import get_session
from backend.services import ai_relay
from backend.services import billing as billing_service
from backend.services import reliability_agent as agent_service

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api")

REASON = "reliability_agent"
_MAX_CSV_BYTES = 8 * 1024 * 1024  # 8 MB — plenty for a fitting dataset
_MULTIPART_OVERHEAD = 64 * 1024  # boundaries and part headers around the file
_MAX_MESSAGE_CHARS = 100_000  # one chat message to the agent

# The Reliability Agent is a paid feature (its Opus sandbox runs cost far more
# than the metered assistant): a purely free-tier user — only the starter grant,
# never paid — can't spend credits here. Pro subscribers and anyone who has
# bought AI credits are entitled; the ordinary balance check still applies.
_PRO_MSG = (
    "The Reliability Agent is a paid feature. Subscribe to Pro or buy AI credits "
    "to build and save models with it."
)


def _agent_access(session, user):
    """``(allowed, admin, acct)`` for the Reliability Agent. When billing is on,
    a purely free-tier user (only the free starter grant, never paid) can't use
    it even with a balance. Entitled: admins, self-host (billing off), Pro
    subscribers, and anyone who has purchased AI credits."""
    uid = user["uid"]
    admin = billing_service.is_admin_user(user)
    acct = billing_service.account(session, uid)
    allowed = billing_service.premium_compute_allowed(session, user)
    return allowed, admin, acct


@router.get("/reliability-agent/info")
def agent_info(session=Depends(get_session), user: dict = Depends(get_current_user)) -> dict:
    allowed, admin, acct = _agent_access(session, user)
    return {
        **agent_service.info(),
        "billing_enabled": config.BILLING_ENABLED,
        "admin": admin,  # admins aren't charged
        "is_pro": acct["is_pro"],
        "allowed": allowed,  # False -> free tier: UI shows an upgrade prompt
        "upgrade_required": config.BILLING_ENABLED and not allowed,
        "credit_cents": acct["credit_cents"],
    }


@router.get("/reliability-agent/sessions")
def agent_sessions(session=Depends(get_session), user: dict = Depends(get_current_user)) -> dict:
    """The user's past agent runs (for the history list). Auth only — reading
    your own history isn't a metered action."""
    return {"sessions": agent_service.list_sessions(session, user["uid"])}


@router.get("/reliability-agent/sessions/{session_id}")
def agent_session_transcript(
    session_id: str, session=Depends(get_session), user: dict = Depends(get_current_user)
) -> JSONResponse:
    """Reopen a past run: its saved transcript in the chat's message shape."""
    if not agent_service.owns_session(session, user["uid"], session_id):
        return JSONResponse(status_code=404, content={"detail": "Session not found."})
    try:
        messages = agent_service.get_transcript(session, session_id)
    except Exception as exc:  # noqa: BLE001 - platform/SDK error
        logger.exception("Failed to load agent transcript")
        return JSONResponse(status_code=502, content={"detail": f"Couldn't load the transcript: {exc}"})
    return JSONResponse(content={"session_id": session_id, "messages": messages})


class _TooLarge(Exception):
    pass


async def _read_upload(request: Request) -> tuple[bytes, str] | JSONResponse:
    """The uploaded file's bytes and name, read with a size cap: a declared
    ``Content-Length`` over the cap is refused before anything is read, and
    the body is counted as it streams, so an oversized upload stops at the
    cap instead of being read in full first."""
    from starlette.formparsers import MultiPartException, MultiPartParser

    too_large = JSONResponse(status_code=413, content={"detail": "File too large (max 8 MB)."})
    limit = _MAX_CSV_BYTES + _MULTIPART_OVERHEAD
    declared = request.headers.get("content-length")
    if declared and declared.isdigit() and int(declared) > limit:
        return too_large
    if "multipart/form-data" not in (request.headers.get("content-type") or ""):
        return JSONResponse(status_code=400, content={"detail": "Send the file as multipart/form-data."})

    async def capped():
        size = 0
        async for piece in request.stream():
            size += len(piece)
            if size > limit:
                raise _TooLarge
            yield piece

    try:
        form = await MultiPartParser(request.headers, capped(), max_files=1, max_fields=4).parse()
    except _TooLarge:
        return too_large
    except MultiPartException as exc:
        return JSONResponse(status_code=400, content={"detail": str(exc)})
    try:
        upload = form.get("file")
        if not isinstance(upload, StarletteUploadFile):
            return JSONResponse(status_code=400, content={"detail": "No file in the upload."})
        data = await upload.read(_MAX_CSV_BYTES + 1)
        if len(data) > _MAX_CSV_BYTES:
            return too_large
        return data, upload.filename or "data.csv"
    finally:
        await form.close()


@router.post("/reliability-agent/upload")
async def agent_upload(
    request: Request,
    session=Depends(get_session),
    user: dict = Depends(get_current_user),
) -> JSONResponse:
    if not agent_service.enabled():
        return JSONResponse(status_code=503, content={"detail": "The Reliability Agent isn't configured yet."})
    allowed, _admin, _acct = await run_in_threadpool(_agent_access, session, user)
    if not allowed:
        return JSONResponse(status_code=403, content={"detail": _PRO_MSG, "code": "pro_required"})
    got = await _read_upload(request)
    if isinstance(got, JSONResponse):
        return got
    data, filename = got
    try:
        file_id = await run_in_threadpool(agent_service.upload_csv, data, filename)
    except agent_service.AgentError as exc:
        return JSONResponse(status_code=502, content={"detail": str(exc)})
    await run_in_threadpool(agent_service.record_upload, session, user["uid"], file_id, filename)
    return JSONResponse(content={"file_id": file_id, "filename": filename})


def _sse(payload: dict) -> str:
    return f"data: {json.dumps(payload)}\n\n"


def _cost(meter: dict) -> int:
    return agent_service.cost_millicents(
        meter.get("seconds", 0.0) or 0.0, meter.get("input_tokens", 0) or 0, meter.get("output_tokens", 0) or 0)


def start_run(session, user: dict, message: str, file_id: str | None, session_id: str | None,
              approved: bool) -> ai_relay.Relay | JSONResponse:
    """Check and start one agent turn: a :class:`ai_relay.Relay` streaming the
    turn's events, or the refusal.

    The turn holds credit up front — :data:`config.RELIABILITY_AGENT_TURN_MAX_CENTS`,
    or the whole balance if that's smaller — and is stopped once its metered
    cost reaches the hold. The turn and its settlement run on the relay's
    worker thread: a client that disconnects stops the turn, and is charged
    for what it used, with the rest of the hold returned."""
    if not agent_service.enabled():
        return JSONResponse(status_code=503, content={"detail": "The Reliability Agent isn't configured yet."})

    uid = user["uid"]
    allowed, admin, acct = _agent_access(session, user)  # operator/self-host aren't gated
    if not allowed:
        return JSONResponse(status_code=403, content={"detail": _PRO_MSG, "code": "pro_required"})
    if session_id and not agent_service.owns_session(session, uid, session_id):
        return JSONResponse(status_code=404, content={"detail": "Session not found."})
    if file_id and not agent_service.owns_file(session, uid, file_id):
        return JSONResponse(status_code=404, content={"detail": "Uploaded file not found. Attach it again."})

    metered = config.BILLING_ENABLED and not admin
    slot = billing_service.acquire_ai_slot(session, uid, "reliability_agent")
    if slot is None:
        return JSONResponse(status_code=429, content={
            "detail": "Another AI request is still running. Wait for it to finish, then try again.",
            "code": "busy"})
    hold_id, held = None, 0
    if metered:
        got = billing_service.reserve_up_to(
            session, uid, config.RELIABILITY_AGENT_TURN_MAX_CENTS * 1000,
            config.RELIABILITY_AGENT_TURN_MIN_CENTS * 1000, REASON)
        if got is None:
            billing_service.release_ai_slot(session, slot)
            have = billing_service.account(session, uid)["credit_cents"]
            return JSONResponse(status_code=402, content={
                "detail": ("You're out of AI credits. Top up to keep using the agent." if have <= 0 else
                           f"An agent turn needs at least {config.RELIABILITY_AGENT_TURN_MIN_CENTS} AI "
                           f"credits and you have {have}. Top up to keep using the agent."),
                "code": "no_credits"})
        hold_id, held = got

    meter: dict = {}
    state = {"settled": False, "balance": None, "over_budget": False}

    def settle() -> int:
        if not state["settled"]:
            state["settled"] = True
            try:
                if hold_id:
                    state["balance"] = billing_service.settle_hold(
                        session, hold_id, _cost(meter) if meter else None)
                else:
                    state["balance"] = billing_service.account(session, uid)["credit_cents"]
            finally:
                billing_service.release_ai_slot(session, slot)
        return state["balance"]

    def produce(emit, stopped) -> None:
        def should_stop() -> bool:
            if stopped.is_set():
                return True
            if hold_id and _cost(meter) >= held:
                state["over_budget"] = True
                return True
            return False

        try:
            for ev in agent_service.stream_run(session, uid, message, file_id, session_id, approved,
                                               meter=meter, should_stop=should_stop):
                if ev.get("type") == "_meter":
                    meter.update({k: v for k, v in ev.items() if k != "type"})
                    cost_mc = _cost(meter)
                    balance = settle()
                    if state["over_budget"]:
                        emit({"type": "error", "detail": (
                            f"This turn used the {held // 1000} credits it reserved and was paused. "
                            "Send a message to continue.")})
                    emit({
                        "type": "done",
                        "session_id": meter.get("session_id"),  # reuse for the next turn
                        "cost_millicents": cost_mc,
                        "cost_cents": max(1, -(-cost_mc // 1000)),
                        "credit_cents": balance,
                    })
                elif not emit(ev):
                    stopped.set()
        except agent_service.AgentError as exc:
            emit({"type": "error", "detail": str(exc)})
        except Exception as exc:  # noqa: BLE001
            logger.exception("reliability agent stream failed")
            emit({"type": "error", "detail": str(exc)})
        finally:
            settle()

    return ai_relay.Relay(produce).start()


@router.post("/reliability-agent/run", response_model=None)
async def agent_run(
    message: str = Body(..., max_length=_MAX_MESSAGE_CHARS),
    file_id: str | None = Body(default=None, max_length=200),
    session_id: str | None = Body(default=None, max_length=200),
    approved: bool = Body(default=False),
    session=Depends(get_session),
    user: dict = Depends(get_current_user),
) -> StreamingResponse | JSONResponse:
    """Run one agent turn, streaming events as Server-Sent Events. The final
    ``done`` event carries the metered cost and new credit balance."""
    relay = await run_in_threadpool(start_run, session, user, message, file_id, session_id, approved)
    if isinstance(relay, JSONResponse):
        return relay
    return StreamingResponse(
        (_sse(item) for item in relay.items()),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
