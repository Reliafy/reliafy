"""Metered AI assistant proxy.

Advances the assistant conversation one provider round-trip at a time on the
operator's key, charging the user's credit balance for the tokens used (when
billing is enabled). The client runs the tool loop and calls here per step.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Body, Depends
from fastapi.responses import JSONResponse

from backend import config
from backend.auth import get_current_user
from backend.db import get_session
from backend.services import assistant as assistant_service
from backend.services import billing as billing_service

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api")


@router.get("/assistant/info")
def assistant_info(session=Depends(get_session), user: dict = Depends(get_current_user)) -> dict:
    acct = billing_service.account(session, user["uid"])
    info = assistant_service.info()
    return {
        **info,
        "billing_enabled": config.BILLING_ENABLED,
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
    if config.BILLING_ENABLED:
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
    cost = billing_service.ai_cost_cents(config.AI_MODEL, usage["input_tokens"], usage["output_tokens"])
    balance = billing_service.account(session, uid)["credit_cents"]
    if config.BILLING_ENABLED:
        balance = billing_service.charge_credits(session, uid, cost, "assistant")

    return JSONResponse(content={
        "message": result["message"],
        "stop_reason": result.get("stop_reason"),
        "usage": usage,
        "cost_cents": cost,
        "credit_cents": balance,
    })
