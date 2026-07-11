"""Teams API: create/manage shared workspaces."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Body, Depends
from fastapi.responses import JSONResponse

from backend.auth import get_current_user
from backend.db import get_session
from backend.services import billing as billing_service
from backend.services import teams as teams_service

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/teams")

_PRO_MSG = "Creating a team requires a Pro plan."


def _team_or_404(session, team_id: str, uid: str):
    team = teams_service.get_team(session, team_id, uid)
    if team is None:
        return None, JSONResponse(status_code=404, content={"detail": "Team not found."})
    return team, None


def _owner_only(team, uid: str):
    if teams_service.role_of(team, uid) != "owner":
        return JSONResponse(status_code=403, content={"detail": "Only the team owner can do that."})
    return None


@router.post("")
def create_team(
    name: str = Body(..., embed=True),
    session=Depends(get_session),
    user: dict = Depends(get_current_user),
) -> JSONResponse:
    from backend import config

    if config.BILLING_ENABLED and not billing_service.is_admin_user(user):
        if not billing_service.account(session, user["uid"])["is_pro"]:
            return JSONResponse(
                status_code=402,
                content={"detail": _PRO_MSG, "code": "pro_required", "upgrade": True},
            )
    try:
        team = teams_service.create_team(session, name, user)
    except teams_service.TeamError as exc:
        return JSONResponse(status_code=exc.status, content={"detail": str(exc)})
    return JSONResponse(content=teams_service.summary(session, team, user["uid"], billing_service))


@router.get("")
def list_teams(session=Depends(get_session), user: dict = Depends(get_current_user)) -> dict:
    from backend.services import access

    return {
        "teams": [
            teams_service.summary(session, t, user["uid"], billing_service)
            for t in access.user_teams(session, user["uid"])
        ]
    }


@router.get("/{team_id}")
def get_team(
    team_id: str, session=Depends(get_session), user: dict = Depends(get_current_user)
) -> JSONResponse:
    team, err = _team_or_404(session, team_id, user["uid"])
    if err:
        return err
    return JSONResponse(content=teams_service.detail(session, team, user["uid"], billing_service))


@router.patch("/{team_id}")
def rename_team(
    team_id: str,
    name: str = Body(..., embed=True),
    session=Depends(get_session),
    user: dict = Depends(get_current_user),
) -> JSONResponse:
    team, err = _team_or_404(session, team_id, user["uid"])
    if err:
        return err
    if denied := _owner_only(team, user["uid"]):
        return denied
    try:
        team = teams_service.rename_team(session, team, name)
    except teams_service.TeamError as exc:
        return JSONResponse(status_code=exc.status, content={"detail": str(exc)})
    return JSONResponse(content=teams_service.summary(session, team, user["uid"], billing_service))


@router.delete("/{team_id}")
def delete_team(
    team_id: str, session=Depends(get_session), user: dict = Depends(get_current_user)
) -> JSONResponse:
    team, err = _team_or_404(session, team_id, user["uid"])
    if err:
        return err
    if denied := _owner_only(team, user["uid"]):
        return denied
    teams_service.delete_team(session, team)
    return JSONResponse(content={"ok": True})


@router.post("/{team_id}/members")
def add_member(
    team_id: str,
    email: str = Body(..., embed=True),
    session=Depends(get_session),
    user: dict = Depends(get_current_user),
) -> JSONResponse:
    team, err = _team_or_404(session, team_id, user["uid"])
    if err:
        return err
    if denied := _owner_only(team, user["uid"]):
        return denied
    if (email or "").strip().lower() == (user.get("email") or "").strip().lower():
        return JSONResponse(status_code=400, content={"detail": "You're already in the team."})
    try:
        result = teams_service.add_member_or_invite(session, team, email, inviter=user)
    except teams_service.TeamError as exc:
        return JSONResponse(status_code=exc.status, content={"detail": str(exc)})
    return JSONResponse(content=result)


@router.delete("/{team_id}/members/{member_uid}")
def remove_member(
    team_id: str,
    member_uid: str,
    session=Depends(get_session),
    user: dict = Depends(get_current_user),
) -> JSONResponse:
    team, err = _team_or_404(session, team_id, user["uid"])
    if err:
        return err
    if denied := _owner_only(team, user["uid"]):
        return denied
    try:
        teams_service.remove_member(session, team, member_uid)
    except teams_service.TeamError as exc:
        return JSONResponse(status_code=exc.status, content={"detail": str(exc)})
    return JSONResponse(content={"ok": True})


@router.delete("/{team_id}/invites/{email}")
def remove_invite(
    team_id: str,
    email: str,
    session=Depends(get_session),
    user: dict = Depends(get_current_user),
) -> JSONResponse:
    team, err = _team_or_404(session, team_id, user["uid"])
    if err:
        return err
    if denied := _owner_only(team, user["uid"]):
        return denied
    teams_service.remove_invite(session, team, email)
    return JSONResponse(content={"ok": True})


@router.post("/{team_id}/leave")
def leave_team(
    team_id: str, session=Depends(get_session), user: dict = Depends(get_current_user)
) -> JSONResponse:
    team, err = _team_or_404(session, team_id, user["uid"])
    if err:
        return err
    try:
        teams_service.leave_team(session, team, user["uid"])
    except teams_service.TeamError as exc:
        return JSONResponse(status_code=exc.status, content={"detail": str(exc)})
    return JSONResponse(content={"ok": True})
