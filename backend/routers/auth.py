"""Authentication-related API routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from backend.auth import current_user_doc
from backend.db import get_session
from backend.services import access as access_service
from backend.services import billing as billing_service
from backend.services import samples as samples_service
from backend.services import teams as teams_service

router = APIRouter(prefix="/api")


@router.post("/samples/restore")
def restore_samples(user: dict = Depends(current_user_doc), session=Depends(get_session)) -> dict:
    """Un-hide every dismissed sample for this user (samples are shared and
    read-only, so restoring is just clearing the per-user hide list)."""
    session.users.update_one({"_id": user["uid"]}, {"$set": {"hidden_samples": []}})
    return {"ok": True}


@router.post("/samples/remove")
def remove_samples(user: dict = Depends(current_user_doc), session=Depends(get_session)) -> dict:
    """Hide every shared sample for this user (the inverse of restore). Only the
    per-user hide list is touched; the shared samples stay for everyone else."""
    hidden = samples_service.hide_all_samples(session, user["uid"])
    return {"ok": True, "hidden": hidden}


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
            teams_service.summary(session, t, user, billing_service)
            for t in access_service.user_teams(session, user["uid"])
        ],
    }
