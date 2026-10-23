"""Authentication-related API routes."""

from __future__ import annotations

from fastapi import APIRouter, Body, Depends
from fastapi.responses import JSONResponse

from backend.auth import current_user_doc
from backend.db import get_session
from backend.services import access as access_service
from backend.services import billing as billing_service
from backend.services import roles as roles_service
from backend.services import samples as samples_service
from backend.services import shares as shares_service
from backend.services import teams as teams_service
from backend.services import time_zones

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

    Also grants the one-time free starter credit, claims shares waiting for
    this (verified) address, lists team invitations awaiting this user's
    answer, and attaches the plan/credit snapshot so the UI can show it
    immediately.
    """
    billing_service.ensure_starter_grant(session, user["uid"])
    shares_service.claim_pending(session, user)
    acct = billing_service.account(session, user["uid"])
    profile = session.users.find_one({"_id": user["uid"]}, {"time_zone": 1}) or {}
    return {
        **user,
        "time_zone": time_zones.zone_name(profile.get("time_zone")),
        "plan": acct["active_plan"],
        "admin": billing_service.is_admin_user(user),
        "credit_cents": acct["credit_cents"],
        "teams": [
            teams_service.summary(session, t, user, billing_service)
            for t in access_service.user_teams(session, user["uid"])
        ],
        "team_invites": teams_service.pending_invites(session, user),
    }


@router.get("/me/time-zone")
def get_time_zone(user: dict = Depends(current_user_doc), session=Depends(get_session)) -> dict:
    """The personal workspace's time zone (an IANA name), or null: UTC."""
    doc = session.users.find_one({"_id": user["uid"]}, {"time_zone": 1}) or {}
    return {"time_zone": time_zones.zone_name(doc.get("time_zone"))}


@router.put("/me/time-zone")
def put_time_zone(time_zone: str | None = Body(default=None, embed=True),
                  user: dict = Depends(current_user_doc), session=Depends(get_session)):
    """Set the personal workspace's time zone ("Australia/Brisbane"); null or ""
    clears it. Calendar days (today, due, overdue) follow it."""
    try:
        return {"time_zone": time_zones.set_personal(session, user["uid"], time_zone)}
    except time_zones.BadTimeZone as err:
        return JSONResponse(status_code=422, content={"detail": str(err)})


@router.get("/me/roles")
def get_roles(user: dict = Depends(current_user_doc), session=Depends(get_session)) -> dict:
    """What the user does: ``{"roles": [...], "offer": bool}``. No roles is
    everything shown; ``offer`` says to ask (once, new users)."""
    return roles_service.of_user(session, user["uid"])


@router.put("/me/roles")
def put_roles(roles: list | None = Body(default=None, embed=True),
              user: dict = Depends(current_user_doc), session=Depends(get_session)):
    """Save the roles, in the order picked (the first is the primary role);
    ``[]`` shows everything."""
    try:
        return roles_service.save(session, user["uid"], roles)
    except roles_service.BadRoles as err:
        return JSONResponse(status_code=422, content={"detail": str(err)})


@router.post("/me/roles/dismiss")
def dismiss_roles_offer(user: dict = Depends(current_user_doc), session=Depends(get_session)) -> dict:
    """"Not now" to the one-time question: it isn't asked again."""
    return roles_service.dismiss_offer(session, user["uid"])
