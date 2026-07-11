"""Access resolution: who can read and write which artifacts.

Every artifact carries a single ``owner_id`` string. Historically that was a
Firebase uid (personal) or ``SAMPLE_OWNER`` (shared read-only samples). Teams
add a third principal form, ``team:<team_id>`` — artifacts created in a team
workspace belong to the team and every member can read *and* write them.

Reads accept a *list* of principals; writes always use exactly one (the
active workspace's ``write_owner``), so mutation queries and their
``owner_id`` equality checks stay single-valued and safe.

``get_access`` is the FastAPI dependency that turns the request's
``X-Workspace-Id`` header into an :class:`AccessCtx`.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from fastapi import Depends, Header, HTTPException

from backend.auth import get_current_user
from backend.config import SAMPLE_OWNER
from backend.db import get_session

TEAM_PREFIX = "team:"
PERSONAL = "personal"


def team_principal(team_id: str) -> str:
    return f"{TEAM_PREFIX}{team_id}"


def is_team_owner(owner_id: str | None) -> bool:
    """True when a record belongs to a team (rather than a user or samples)."""
    return bool(owner_id) and owner_id.startswith(TEAM_PREFIX)


def owner_in(owner: str | list[str]) -> list[str]:
    """The ``$in`` principal list for read queries.

    A plain string keeps the historical behaviour (that owner + shared
    samples); a list is used verbatim — the caller has already decided
    whether samples belong in scope.
    """
    if isinstance(owner, str):
        return [owner, SAMPLE_OWNER]
    if isinstance(owner, list):
        return owner
    raise TypeError(f"owner must be str or list, got {type(owner)!r}")


def user_teams(db, uid: str) -> list[dict]:
    """Teams the user belongs to (raw docs), newest first."""
    return list(db.teams.find({"members.uid": uid}).sort("created_at", -1))


@dataclass
class AccessCtx:
    """Everything a router needs to scope reads, writes, and caps."""

    user: dict                      # {uid, email, name}
    uid: str
    workspace: str                  # "personal" | team id
    write_owner: str                # uid, or "team:<id>"
    read_owners: list[str]          # every principal the user may read as
    list_owners: str | list[str]    # what list endpoints scope to
    hidden: set[str] = field(default_factory=set)
    frozen: bool = False            # team workspace whose owner's Pro lapsed

    @property
    def is_personal(self) -> bool:
        return self.workspace == PERSONAL


def can_write(ctx: AccessCtx, owner_id: str | None) -> bool:
    """Whether the active workspace may mutate a record with this owner."""
    return owner_id == ctx.write_owner and not ctx.frozen


FROZEN_MSG = (
    "The team owner's Pro plan has lapsed — the team workspace is read-only "
    "until it's renewed."
)


def write_denial(ctx: AccessCtx, owner_id: str | None) -> tuple[int, dict] | None:
    """None when the workspace may mutate this record, else (status, payload).

    Distinguishes a frozen team (402, upgrade nudge) from plain read-only
    (samples, another workspace's artifact, shared-to-me: 403).
    """
    if can_write(ctx, owner_id):
        return None
    if ctx.frozen and owner_id == ctx.write_owner:
        return 402, {"detail": FROZEN_MSG, "code": "team_frozen", "upgrade": True}
    return 403, {"detail": "This item is read-only in your current workspace."}


def get_access(
    user: dict = Depends(get_current_user),
    session=Depends(get_session),
    x_workspace_id: str | None = Header(default=None),
) -> AccessCtx:
    """Resolve the request's workspace into an :class:`AccessCtx`.

    ``X-Workspace-Id`` absent or "personal" → personal workspace. A team id →
    that team's workspace (403 for non-members). ``read_owners`` always spans
    everything the user can see so get-by-id works across workspaces (e.g. a
    deep link to a team artifact opened from the personal workspace renders
    read-only rather than 404ing).
    """
    # Local import: billing imports config at module load; keep cycles away.
    from backend.services import billing as billing_service

    uid = user["uid"]
    teams = user_teams(session, uid)
    team_principals = [team_principal(t["_id"]) for t in teams]
    read_owners = [uid, SAMPLE_OWNER, *team_principals]
    doc = session.users.find_one({"_id": uid}) or {}
    hidden = set(doc.get("hidden_samples") or [])

    workspace = (x_workspace_id or PERSONAL).strip() or PERSONAL
    if workspace == PERSONAL:
        return AccessCtx(
            user=user, uid=uid, workspace=PERSONAL, write_owner=uid,
            read_owners=read_owners, list_owners=uid, hidden=hidden,
        )

    team = next((t for t in teams if t["_id"] == workspace), None)
    if team is None:
        raise HTTPException(status_code=403, detail="You're not a member of that team.")

    frozen = team_frozen(session, team, billing_service)
    return AccessCtx(
        user=user, uid=uid, workspace=workspace,
        write_owner=team_principal(workspace),
        read_owners=read_owners,
        list_owners=[team_principal(workspace)],  # team lists exclude samples
        hidden=hidden, frozen=frozen,
    )


def team_frozen(db, team: dict, billing_service) -> bool:
    """A team freezes (read-only) when its owner's Pro lapses.

    Admin owners never freeze; with billing disabled nothing freezes.
    """
    from backend import config

    if not config.BILLING_ENABLED:
        return False
    owner_uid = team.get("owner_uid")
    owner_doc = db.users.find_one({"_id": owner_uid}) or {}
    owner_user = {"email": owner_doc.get("email")}
    if billing_service.is_admin_user(owner_user):
        return False
    return not billing_service.account(db, owner_uid)["is_pro"]
