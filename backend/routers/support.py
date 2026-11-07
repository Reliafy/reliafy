"""Operator support replies over the API (see :mod:`backend.services.support_replies`).

    POST /api/v1/support/replies   send one reply (``write`` scope on a token)
    GET  /api/v1/support/replies   the last 50 sent (``read`` scope)

Operators only (``ADMIN_EMAILS``, verified address), with a personal API token
(``Authorization: Bearer rlf_…``) or a signed-in session; anyone else gets 403.
Not an MCP tool: it isn't a user feature. Mounted before the generic
``/api/v1/{tool}/{action}`` routes so those never answer it.
"""

from __future__ import annotations

from fastapi import APIRouter, Body, Depends, Header, HTTPException
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse

from backend.auth import get_current_user
from backend.db import get_session
from backend.services import billing as billing_service
from backend.services import support_replies as support_service
from backend.services import tokens as tokens_service

router = APIRouter(prefix="/api/v1/support")

_OPERATORS_ONLY = "Support replies are for Reliafy operators only."


def operator_user(scope: str):
    """A dependency: the caller from an API token or a session, who must be an
    operator (403 otherwise) and, with a token, hold ``scope``."""

    def dependency(authorization: str | None = Header(default=None), session=Depends(get_session)) -> dict:
        if authorization and authorization.startswith("Bearer rlf_"):
            user = tokens_service.verify(session, authorization.split(" ", 1)[1].strip())
            if user is None:
                raise HTTPException(status_code=401, detail="Invalid or revoked API token.")
        else:
            user = get_current_user(authorization)
        if not billing_service.is_admin_user(user):
            raise HTTPException(status_code=403, detail=_OPERATORS_ONLY)
        if not tokens_service.has_scope(user, scope):
            raise HTTPException(status_code=403, detail=tokens_service.scope_message(scope))
        return user

    return dependency


@router.post("/replies")
async def send_reply(
    body: dict = Body(...),
    session=Depends(get_session),
    user: dict = Depends(operator_user("write")),
) -> JSONResponse:
    """Send one reply as Reliafy support. Body: ``{to, subject, text,
    in_reply_to?, references?, html?}``."""
    try:
        # Off the event loop: the send waits on the SMTP server.
        reply = await run_in_threadpool(support_service.send_reply, session, user, body)
    except support_service.SupportError as exc:
        return JSONResponse(status_code=exc.status, content={"detail": str(exc)})
    return JSONResponse(content=reply)


@router.get("/replies")
def list_replies(session=Depends(get_session), user: dict = Depends(operator_user("read"))) -> dict:
    """The last 50 replies sent, newest first (subjects and short previews only)."""
    return {"replies": support_service.list_replies(session)}
