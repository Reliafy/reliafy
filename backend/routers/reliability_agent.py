"""Reliability Agent API (Anthropic Managed Agents).

Self-contained sibling of the metered assistant router: upload a CSV, then run
the managed agent and stream its work back over SSE. Charges the user's credit
balance under its own metering reason (``"reliability_agent"``) — token cost plus
the Managed Agents session-runtime charge — so usage is tracked separately and
the old assistant can be retired without disturbing this.
"""

from __future__ import annotations

import json
import logging

from fastapi import APIRouter, Body, Depends, File, UploadFile
from fastapi.responses import JSONResponse, StreamingResponse

from backend import config
from backend.auth import get_current_user
from backend.db import get_session
from backend.services import billing as billing_service
from backend.services import reliability_agent as agent_service

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api")

_MAX_CSV_BYTES = 8 * 1024 * 1024  # 8 MB — plenty for a fitting dataset


@router.get("/reliability-agent/info")
def agent_info(session=Depends(get_session), user: dict = Depends(get_current_user)) -> dict:
    acct = billing_service.account(session, user["uid"])
    return {
        **agent_service.info(),
        "billing_enabled": config.BILLING_ENABLED,
        "admin": billing_service.is_admin_user(user),  # admins aren't charged
        "credit_cents": acct["credit_cents"],
    }


@router.post("/reliability-agent/upload")
async def agent_upload(
    file: UploadFile = File(...),
    session=Depends(get_session),
    user: dict = Depends(get_current_user),
) -> JSONResponse:
    if not agent_service.enabled():
        return JSONResponse(status_code=503, content={"detail": "The Reliability Agent isn't configured yet."})
    data = await file.read()
    if len(data) > _MAX_CSV_BYTES:
        return JSONResponse(status_code=413, content={"detail": "File too large (max 8 MB)."})
    try:
        file_id = agent_service.upload_csv(data, file.filename or "data.csv")
    except agent_service.AgentError as exc:
        return JSONResponse(status_code=502, content={"detail": str(exc)})
    return JSONResponse(content={"file_id": file_id, "filename": file.filename})


def _sse(payload: dict) -> str:
    return f"data: {json.dumps(payload)}\n\n"


@router.post("/reliability-agent/run", response_model=None)
def agent_run(
    message: str = Body(...),
    file_id: str | None = Body(default=None),
    session_id: str | None = Body(default=None),
    session=Depends(get_session),
    user: dict = Depends(get_current_user),
) -> StreamingResponse | JSONResponse:
    """Run one agent turn, streaming events as Server-Sent Events. The final
    ``done`` event carries the metered cost and new credit balance."""
    if not agent_service.enabled():
        return JSONResponse(status_code=503, content={"detail": "The Reliability Agent isn't configured yet."})

    uid = user["uid"]
    admin = billing_service.is_admin_user(user)  # operator accounts aren't charged
    if config.BILLING_ENABLED and not admin:
        if billing_service.account(session, uid)["credit_cents"] <= 0:
            return JSONResponse(
                status_code=402,
                content={"detail": "You're out of AI credits. Top up to keep using the agent.", "code": "no_credits"},
            )

    def event_stream():
        try:
            for ev in agent_service.stream_run(message, file_id, session_id):
                if ev.get("type") == "_meter":
                    cost_mc = agent_service.cost_millicents(
                        ev.get("seconds", 0.0), ev.get("input_tokens", 0), ev.get("output_tokens", 0)
                    )
                    balance = billing_service.account(session, uid)["credit_cents"]
                    if config.BILLING_ENABLED and not admin:
                        balance = billing_service.charge_millicents(session, uid, cost_mc, "reliability_agent")
                    yield _sse({
                        "type": "done",
                        "session_id": ev.get("session_id"),  # reuse for the next turn
                        "cost_millicents": cost_mc,
                        "cost_cents": max(1, -(-cost_mc // 1000)),
                        "credit_cents": balance,
                    })
                else:
                    yield _sse(ev)
        except agent_service.AgentError as exc:
            yield _sse({"type": "error", "detail": str(exc)})
        except Exception as exc:  # noqa: BLE001
            logger.exception("reliability agent stream failed")
            yield _sse({"type": "error", "detail": str(exc)})

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
