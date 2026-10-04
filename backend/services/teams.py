"""Teams: shared workspaces whose artifacts every member can read and write.

A team's artifacts carry ``owner_id = "team:<team_id>"`` (see
``services/access.py``). Membership lives on the team doc; invites for
addresses without an account stage there too and activate on the invitee's
first ``/api/me`` call.
"""

from __future__ import annotations

import unicodedata
import uuid
from datetime import datetime, timezone

from backend import config
from backend.services import access
from backend.services import email as email_service
from backend.services import email_trust
from backend.services import rate_limit

ARTIFACT_COLLECTIONS = (
    "datasets", "models", "rbds", "degradation_models",
    "tracked_items", "tracked_fleets", "strategy_analyses", "rcm_studies", "fleets",
    "outage_logs",
)


MAX_NAME = 80

# Invites sent (added or staged) per window: per inviting user across all
# their teams, and per team.
INVITE_WINDOW_SECONDS = 3600
INVITES_PER_USER = 30
INVITES_PER_TEAM = 20
MAX_PENDING_INVITES = 100


class TeamError(ValueError):
    """Validation / permission failure with a user-facing message."""

    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status


def _now():
    return datetime.now(timezone.utc)


def _norm_email(email: str | None) -> str:
    return (email or "").strip().lower()


def clean_name(name, what: str = "team") -> str:
    """A team name as stored: control characters (newlines, tabs, …) become
    spaces, whitespace collapses, and it must be 1–80 characters."""
    text = "".join(" " if unicodedata.category(ch)[0] == "C" else ch for ch in str(name or ""))
    text = " ".join(text.split())
    if not text:
        raise TeamError(f"The {what} needs a name.", 422)
    if len(text) > MAX_NAME:
        raise TeamError(f"Keep the {what} name to {MAX_NAME} characters or fewer.", 422)
    return text


def _display_name(name) -> str | None:
    """A member's display name as stored (from their sign-in profile, which
    they control): control characters removed and at most 80 characters."""
    return email_service.clean_text(name, MAX_NAME) or None


def _email_trusted(db, user: dict) -> bool:
    """Whether the signed-in user's address proves who they are: the token's
    ``email_verified`` when it has one, else a lookup (email_trust)."""
    if config.AUTH_DISABLED:
        return True
    flag = user.get("email_verified")
    if flag is None:
        return email_trust.verified(db, user.get("uid"))
    return flag is True


def _member(user: dict, role: str) -> dict:
    return {
        "uid": user["uid"],
        "email": user.get("email"),
        "name": _display_name(user.get("name")),
        "role": role,
        "added_at": _now(),
    }


def create_team(db, name: str, user: dict) -> dict:
    name = clean_name(name)
    team = {
        "_id": uuid.uuid4().hex,
        "name": name,
        "owner_uid": user["uid"],
        "members": [_member(user, "owner")],
        "invites": [],
        "created_at": _now(),
        "updated_at": _now(),
    }
    db.teams.insert_one(team)
    return team


def get_team(db, team_id: str, uid: str) -> dict | None:
    """The team, but only for members."""
    return db.teams.find_one({"_id": team_id, "members.uid": uid})


def role_of(team: dict, uid: str) -> str | None:
    for m in team.get("members", []):
        if m["uid"] == uid:
            return m.get("role")
    return None


def rename_team(db, team: dict, name: str) -> dict:
    name = clean_name(name)
    db.teams.update_one({"_id": team["_id"]}, {"$set": {"name": name, "updated_at": _now()}})
    return {**team, "name": name}


def delete_team(db, team: dict) -> None:
    """Delete the team and every artifact in its workspace."""
    principal = access.team_principal(team["_id"])
    for coll in ARTIFACT_COLLECTIONS:
        db[coll].delete_many({"owner_id": principal})
    db.teams.delete_one({"_id": team["_id"]})


def add_member_or_invite(db, team: dict, email: str, inviter: dict | None = None) -> dict:
    """Add a registered user as member, or stage an invite for an unknown email.

    Only an account whose email address is verified is added straight away;
    for any other address the invite is staged and activates when an account
    with that address, verified, signs in. Either way the invitee gets an
    email (when SMTP is configured). Invites are rate-limited per inviting
    user and per team (429).
    """
    email_lc = _norm_email(email)
    if not email_lc or "@" not in email_lc:
        raise TeamError("Enter a valid email address.", 422)
    if any(_norm_email(m.get("email")) == email_lc for m in team.get("members", [])):
        raise TeamError("That person is already a member.", 409)
    if any(i.get("email") == email_lc for i in team.get("invites", [])):
        raise TeamError("That email has already been invited.", 409)
    if len(team.get("invites", [])) >= MAX_PENDING_INVITES:
        raise TeamError(f"This team has {MAX_PENDING_INVITES} pending invites — remove some first.", 409)
    _consume_invite(db, team, inviter)

    target = db.users.find_one({"$or": [{"email_lc": email_lc}, {"email": email_lc}]})
    note = None
    if target is not None:
        verification = email_trust.status(db, target["_id"], target.get("email_verified"))
        if verification != email_trust.VERIFIED:
            # An unproven address: stage the invite; it activates once an
            # account with this address signs in verified.
            target = None
            note = ("Reliafy couldn't confirm that account's email address just now, so the invite is "
                    "pending: they'll join when they next sign in with the address verified."
                    if verification == email_trust.UNKNOWN else
                    "That account hasn't verified its email address yet — they'll join once they do.")
    if target is not None:
        member = _member(
            {"uid": target["_id"], "email": target.get("email"), "name": target.get("name")},
            "member",
        )
        db.teams.update_one(
            {"_id": team["_id"]},
            {"$push": {"members": member}, "$set": {"updated_at": _now()}},
        )
        email_service.team_member_added(
            member.get("email"),
            (inviter or {}).get("name") or (inviter or {}).get("email") or "A teammate",
            team["name"],
        )
        return {"status": "added", "member": _public_member(member)}

    invite = {"email": email_lc, "invited_by": team["owner_uid"], "invited_at": _now()}
    db.teams.update_one(
        {"_id": team["_id"]},
        {"$push": {"invites": invite}, "$set": {"updated_at": _now()}},
    )
    email_service.team_invite_pending(
        email_lc,
        (inviter or {}).get("name") or (inviter or {}).get("email") or "A Reliafy user",
        team["name"],
    )
    out = {"status": "invited", "email": email_lc}
    if note:
        out["note"] = note
    return out


def _consume_invite(db, team: dict, inviter: dict | None) -> None:
    """Count one invite against the inviter and the team; 429 past either."""
    keys = [(f"invite:team:{team['_id']}", INVITES_PER_TEAM)]
    if inviter and inviter.get("uid"):
        keys.insert(0, (f"invite:user:{inviter['uid']}", INVITES_PER_USER))
    for key, limit in keys:
        if not rate_limit.consume(db, key, limit, INVITE_WINDOW_SECONDS):
            minutes = max(1, rate_limit.retry_after(INVITE_WINDOW_SECONDS) // 60)
            raise TeamError(f"That's a lot of invites in a short time — try again in {minutes} min.", 429)


def remove_member(db, team: dict, member_uid: str) -> None:
    if member_uid == team["owner_uid"]:
        raise TeamError("The team owner can't be removed — delete the team instead.")
    if role_of(team, member_uid) is None:
        raise TeamError("That person isn't a member.", 404)
    db.teams.update_one(
        {"_id": team["_id"]},
        {"$pull": {"members": {"uid": member_uid}}, "$set": {"updated_at": _now()}},
    )


def remove_invite(db, team: dict, email: str) -> None:
    db.teams.update_one(
        {"_id": team["_id"]},
        {"$pull": {"invites": {"email": _norm_email(email)}}, "$set": {"updated_at": _now()}},
    )


def leave_team(db, team: dict, uid: str) -> None:
    if uid == team["owner_uid"]:
        raise TeamError("The owner can't leave — delete the team instead.")
    remove_member(db, team, uid)


def activate_invites(db, user: dict) -> None:
    """Turn pending email invites into memberships on login (idempotent).

    Only for a verified address: anyone can create an account claiming any
    email, so an unverified one keeps its invites pending until verified."""
    email_lc = _norm_email(user.get("email"))
    if not email_lc or not _email_trusted(db, user):
        return
    for team in db.teams.find({"invites.email": email_lc}):
        if role_of(team, user["uid"]) is None:
            db.teams.update_one(
                {"_id": team["_id"]},
                {"$push": {"members": _member(user, "member")}, "$set": {"updated_at": _now()}},
            )
        db.teams.update_one(
            {"_id": team["_id"]},
            {"$pull": {"invites": {"email": email_lc}}},
        )


def _public_member(m: dict) -> dict:
    return {"uid": m["uid"], "email": m.get("email"), "name": m.get("name"), "role": m.get("role")}


def summary(db, team: dict, user: dict, billing_service) -> dict:
    return {
        "id": team["_id"],
        "name": team["name"],
        "role": role_of(team, user["uid"]),
        "frozen": access.team_frozen(db, team, billing_service),
        # Whether THIS member may edit in the team workspace (Pro/admin).
        "can_edit": access.member_can_edit(db, user, billing_service),
        "member_count": len(team.get("members", [])),
        "pending_invites": len(team.get("invites", [])),
    }


def detail(db, team: dict, user: dict, billing_service) -> dict:
    members = []
    for m in team.get("members", []):
        member_user = {"uid": m["uid"], "email": m.get("email"),
                       "email_verified": email_trust.profile_flag(db, m["uid"])}
        members.append({
            **_public_member(m),
            "can_edit": access.member_can_edit(db, member_user, billing_service),
        })
    return {
        **summary(db, team, user, billing_service),
        "members": members,
        "invites": [{"email": i["email"]} for i in team.get("invites", [])],
    }
