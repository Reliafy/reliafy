"""Authentication-related API routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from backend.auth import current_user_doc
from backend.db import get_session
from backend.services import billing as billing_service

router = APIRouter(prefix="/api")


@router.get("/me")
def me(user: dict = Depends(current_user_doc), session=Depends(get_session)) -> dict:
    """Return the signed-in user's profile (and upsert it on first login).

    Also grants the one-time free starter credit and attaches the plan/credit
    snapshot so the UI can show it immediately.
    """
    billing_service.ensure_starter_grant(session, user["uid"])
    acct = billing_service.account(session, user["uid"])
    pro = acct["is_pro"] or billing_service.is_admin_user(user)
    return {**user, "plan": "pro" if pro else "free", "credit_cents": acct["credit_cents"]}
