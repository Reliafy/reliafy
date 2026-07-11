"""Authentication-related API routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from backend.auth import current_user_doc
from backend.db import get_session
from backend.services import access as access_service
from backend.services import billing as billing_service
from backend.services import teams as teams_service

router = APIRouter(prefix="/api")


@router.get("/me")
def me(user: dict = Depends(current_user_doc), session=Depends(get_session)) -> dict:
    """Return the signed-in user's profile (and upsert it on first login).

    Also grants the one-time free starter credit, activates any pending team
    invites for this email, and attaches the plan/credit snapshot so the UI
    can show it immediately.
    """
    billing_service.ensure_starter_grant(session, user["uid"])
    teams_service.activate_invites(session, user)
    acct = billing_service.account(session, user["uid"])
    return {
        **user,
        "plan": "pro" if acct["is_pro"] else "free",
        "admin": billing_service.is_admin_user(user),
        "credit_cents": acct["credit_cents"],
        "teams": [
            teams_service.summary(session, t, user["uid"], billing_service)
            for t in access_service.user_teams(session, user["uid"])
        ],
    }
