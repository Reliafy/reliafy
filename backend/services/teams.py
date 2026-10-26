"""Teams: shared workspaces whose artifacts every member can read and write.

A team's artifacts carry ``owner_id = "team:<team_id>"`` (see
``services/access.py``). Membership lives on the team doc. Adding someone
stages an invitation there; membership starts when the invitee, signed in
with that address verified, accepts it.
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
from backend.services import time_zones

# Every collection whose documents a team's workspace owns (``owner_id``),
# Maintenance aside: deleting the team deletes them.
ARTIFACT_COLLECTIONS = (
    "datasets", "models", "rbds", "degradation_models",
    "tracked_items", "tracked_fleets", "strategy_analyses", "fleets",
    "outage_logs", "recurrent_models", "alt_models", "model_refits",
)

# Records kept by the id of a team artifact rather than by owner: deleted
# with that artifact's team. ``{collection: (field, artifact collection)}``.
DEPENDENT_COLLECTIONS = {
    "rbd_jobs": ("rbd_id", "rbds"),
    "fleet_alerts": ("fleet_id", "fleets"),
    "fleet_forecasts": ("fleet_id", "fleets"),
    "fleet_alert_events": ("fleet_id", "fleets"),
}


MAX_NAME = 80
MAX_EMAIL = 254

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
    ids = {coll: [d["_id"] for d in db[coll].find({"owner_id": principal}, {"_id": 1})]
           for coll in {parent for _, parent in DEPENDENT_COLLECTIONS.values()}}
    for coll, (field, parent) in DEPENDENT_COLLECTIONS.items():
        if ids[parent]:
            db[coll].delete_many({field: {"$in": ids[parent]}})
    for coll in ARTIFACT_COLLECTIONS:
        db[coll].delete_many({"owner_id": principal})
    db.teams.delete_one({"_id": team["_id"]})


def add_member_or_invite(db, team: dict, email: str, inviter: dict | None = None) -> dict:
    """Stage an invitation to the team for an email address.

    Membership starts only when the invitee, signed in with that address
    verified, accepts (``accept_invite``). The response is the same whether
    or not the address has an account, and the owner sees only the address
    they typed until the invitee accepts. The invitee gets an email (when
    SMTP is configured). Invites are rate-limited per inviting user and per
    team (429).
    """
    email_lc = _norm_email(email)
    if not email_lc or "@" not in email_lc or len(email_lc) > MAX_EMAIL:
        raise TeamError("Enter a valid email address.", 422)
    if any(_norm_email(m.get("email")) == email_lc for m in team.get("members", [])):
        raise TeamError("That person is already a member.", 409)
    if any(i.get("email") == email_lc for i in team.get("invites", [])):
        raise TeamError("That email has already been invited.", 409)
    if len(team.get("invites", [])) >= MAX_PENDING_INVITES:
        raise TeamError(f"This team has {MAX_PENDING_INVITES} pending invites — remove some first.", 409)
    _consume_invite(db, team, inviter)

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
    return {"status": "invited", "email": email_lc}


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


def pending_invites(db, user: dict) -> list[dict]:
    """The teams that have invited this user's address and await an answer.

    Only for a verified address: anyone can create an account claiming any
    email, so an unverified one sees no invitations until it's verified."""
    email_lc = _norm_email(user.get("email"))
    if not email_lc or not _email_trusted(db, user):
        return []
    out = []
    for team in db.teams.find({"invites.email": email_lc}):
        if role_of(team, user["uid"]) is not None:
            continue
        invite = next((i for i in team.get("invites", []) if i.get("email") == email_lc), {})
        owner = next((m for m in team.get("members", []) if m.get("uid") == team.get("owner_uid")), {})
        invited_at = invite.get("invited_at")
        out.append({
            "team_id": team["_id"],
            "team_name": team.get("name"),
            "invited_by": _display_name(owner.get("name")) or owner.get("email"),
            "invited_at": invited_at.isoformat() if hasattr(invited_at, "isoformat") else None,
        })
    return out


def accept_invite(db, team_id: str, user: dict) -> dict:
    """Join a team that invited this user's (verified) address."""
    email_lc = _norm_email(user.get("email"))
    if not email_lc or not _email_trusted(db, user):
        raise TeamError("Verify your email address to accept team invitations.", 403)
    team = db.teams.find_one({"_id": str(team_id), "invites.email": email_lc})
    if team is None:
        raise TeamError("Invitation not found.", 404)
    if role_of(team, user["uid"]) is None:
        db.teams.update_one(
            {"_id": team["_id"], "members.uid": {"$ne": user["uid"]}},
            {"$push": {"members": _member(user, "member")}, "$set": {"updated_at": _now()}},
        )
    db.teams.update_one({"_id": team["_id"]}, {"$pull": {"invites": {"email": email_lc}}})
    return db.teams.find_one({"_id": team["_id"]})


def decline_invite(db, team_id: str, user: dict) -> None:
    """Turn down a team's invitation to this user's (verified) address."""
    email_lc = _norm_email(user.get("email"))
    if not email_lc or not _email_trusted(db, user):
        raise TeamError("Verify your email address to answer team invitations.", 403)
    result = db.teams.update_one(
        {"_id": str(team_id), "invites.email": email_lc},
        {"$pull": {"invites": {"email": email_lc}}, "$set": {"updated_at": _now()}},
    )
    if result.matched_count == 0:
        raise TeamError("Invitation not found.", 404)


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
        # The workspace's time zone (an IANA name), or None: UTC.
        "time_zone": time_zones.zone_name(team.get("time_zone")),
        "pending_invites": len(team.get("invites", [])),
    }


def detail(db, team: dict, user: dict, billing_service) -> dict:
    """The team as a member sees it. Whether a member may edit (their plan)
    is shown to the owner and to that member only; pending invitations are
    only the address the owner typed."""
    is_owner = role_of(team, user["uid"]) == "owner"
    members = []
    for m in team.get("members", []):
        entry = _public_member(m)
        if is_owner or m["uid"] == user["uid"]:
            member_user = {"uid": m["uid"], "email": m.get("email"),
                           "email_verified": email_trust.profile_flag(db, m["uid"])}
            entry["can_edit"] = access.member_can_edit(db, member_user, billing_service)
        members.append(entry)
    return {
        **summary(db, team, user, billing_service),
        "members": members,
        "invites": [
            {"email": i["email"], "status": "pending",
             "invited_at": i["invited_at"].isoformat() if hasattr(i.get("invited_at"), "isoformat") else None}
            for i in team.get("invites", [])
        ],
    }
