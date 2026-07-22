"""Metered AI assistant proxy.

Advances the assistant conversation one provider round-trip at a time on the
operator's key, charging the user's credit balance for the tokens used (when
billing is enabled). The client runs the tool loop and calls here per step.
"""

from __future__ import annotations

import json
import logging

from fastapi import APIRouter, Body, Depends
from fastapi.responses import JSONResponse, StreamingResponse

from backend import config
from backend.auth import get_current_user
from backend.db import get_session
from backend.services import assistant as assistant_service
from backend.services import billing as billing_service

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api")


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


@router.post("/assistant/step")
def assistant_step(
    system: str = Body(...),
    messages: list = Body(...),
    tools: list = Body(default=[]),
    session=Depends(get_session),
    user: dict = Depends(get_current_user),
) -> JSONResponse:
    if not assistant_service.enabled():
        return JSONResponse(status_code=503, content={"detail": "The AI assistant isn't configured yet."})

    uid = user["uid"]
    # Operator accounts aren't credit-checked or charged.
    admin = billing_service.is_admin_user(user)
    if config.BILLING_ENABLED and not admin:
        if billing_service.account(session, uid)["credit_cents"] <= 0:
            return JSONResponse(
                status_code=402,
                content={"detail": "You're out of AI credits. Top up to keep using the assistant.", "code": "no_credits"},
            )

    try:
        result = assistant_service.step(system, messages, tools)
    except assistant_service.AssistantError as exc:
        return JSONResponse(status_code=502, content={"detail": str(exc)})

    usage = result["usage"]
    # Metered at millicent precision, with cached prompt tokens billed at the
    # provider's cached rate — maps user charges tightly onto actual $ cost.
    cost_mc = billing_service.ai_cost_millicents(
        config.AI_MODEL,
        usage["input_tokens"],
        usage["output_tokens"],
        usage.get("cached_input_tokens", 0),
    )
    balance = billing_service.account(session, uid)["credit_cents"]
    if config.BILLING_ENABLED and not admin:
        balance = billing_service.charge_millicents(session, uid, cost_mc, "assistant")

    return JSONResponse(content={
        "message": result["message"],
        "stop_reason": result.get("stop_reason"),
        "usage": usage,
        "cost_millicents": cost_mc,
        "cost_cents": max(1, -(-cost_mc // 1000)),  # informational, whole credits
        "credit_cents": balance,
    })


def _no_credits(session, uid: str, admin: bool) -> bool:
    return (
        config.BILLING_ENABLED
        and not admin
        and billing_service.account(session, uid)["credit_cents"] <= 0
    )


@router.post("/assistant/stream")
def assistant_stream(
    system: str = Body(...),
    messages: list = Body(...),
    tools: list = Body(default=[]),
    session=Depends(get_session),
    user: dict = Depends(get_current_user),
):
    """Same as ``/assistant/step`` but streams the provider's output as SSE:
    ``{type:"delta", text}`` frames as the assistant writes, then a terminal
    ``{type:"final", message, stop_reason, usage, credit_cents}`` the client
    uses to continue the tool loop. Billing happens on the final frame."""
    if not assistant_service.enabled():
        return JSONResponse(status_code=503, content={"detail": "The AI assistant isn't configured yet."})

    uid = user["uid"]
    admin = billing_service.is_admin_user(user)  # operators aren't credit-checked/charged
    if _no_credits(session, uid, admin):
        return JSONResponse(
            status_code=402,
            content={"detail": "You're out of AI credits. Top up to keep using the assistant.", "code": "no_credits"},
        )

    def event_stream():
        try:
            for ev in assistant_service.stream(system, messages, tools):
                if ev["type"] == "delta":
                    yield _sse({"type": "delta", "text": ev["text"]})
                elif ev["type"] == "final":
                    usage = ev["usage"]
                    cost_mc = billing_service.ai_cost_millicents(
                        config.AI_MODEL,
                        usage["input_tokens"],
                        usage["output_tokens"],
                        usage.get("cached_input_tokens", 0),
                    )
                    balance = billing_service.account(session, uid)["credit_cents"]
                    if config.BILLING_ENABLED and not admin:
                        balance = billing_service.charge_millicents(session, uid, cost_mc, "assistant")
                    yield _sse({
                        "type": "final",
                        "message": ev["message"],
                        "stop_reason": ev.get("stop_reason"),
                        "usage": usage,
                        "cost_millicents": cost_mc,
                        "cost_cents": max(1, -(-cost_mc // 1000)),
                        "credit_cents": balance,
                    })
        except assistant_service.AssistantError as exc:
            yield _sse({"type": "error", "detail": str(exc)})
        except Exception as exc:  # noqa: BLE001
            logger.exception("assistant stream failed")
            yield _sse({"type": "error", "detail": str(exc)})

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
