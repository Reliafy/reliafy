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


class EditConflict(Exception):
    """A whole-document write raced another editor (optimistic-lock miss)."""


def timestamps_match(stored, expected_iso: str) -> bool:
    """Whether a stored timestamp is the one the client loaded.

    MongoDB truncates datetimes to millisecond precision and drops tzinfo on
    the round-trip, so exact string equality would always miss — compare
    tz-normalised with a 1ms tolerance instead.
    """
    from datetime import datetime, timezone

    try:
        expected = datetime.fromisoformat(str(expected_iso))
        actual = stored if hasattr(stored, "isoformat") else datetime.fromisoformat(str(stored))
    except (ValueError, TypeError):
        return False
    if expected.tzinfo is None:
        expected = expected.replace(tzinfo=timezone.utc)
    if actual.tzinfo is None:
        actual = actual.replace(tzinfo=timezone.utc)
    return abs((actual - expected).total_seconds()) < 0.001


CONFLICT_MSG = (
    "Someone saved changes to this while you were editing — reload to see "
    "their version, then re-apply yours."
)


def editor_of(ctx: "AccessCtx") -> dict:
    """Who is making this change, for updated_by stamping."""
    return {
        "uid": ctx.uid,
        "name": ctx.user.get("name") or ctx.user.get("email") or "unknown",
    }


def stamp_editor(db, collection: str, artifact_id: str, ctx: "AccessCtx") -> None:
    """Record who last touched an artifact (best-effort, after a mutation)."""
    db[collection].update_one(
        {"_id": artifact_id}, {"$set": {"updated_by": editor_of(ctx)}}
    )


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
    member_view_only: bool = False  # team workspace, but this member isn't Pro

    @property
    def is_personal(self) -> bool:
        return self.workspace == PERSONAL


def can_write(ctx: AccessCtx, owner_id: str | None) -> bool:
    """Whether the active workspace may mutate a record with this owner."""
    return (
        owner_id == ctx.write_owner
        and not ctx.frozen
        and not ctx.member_view_only
    )


FROZEN_MSG = (
    "The team owner's Pro plan has lapsed — the team workspace is read-only "
    "until it's renewed."
)

MEMBER_PRO_MSG = (
    "Editing in a team workspace requires a Pro plan — you can view "
    "everything, and upgrade to edit."
)


def write_denial(ctx: AccessCtx, owner_id: str | None) -> tuple[int, dict] | None:
    """None when the workspace may mutate this record, else (status, payload).

    Distinguishes a frozen team and a non-Pro member (402, upgrade nudge)
    from plain read-only (samples, another workspace's artifact,
    shared-to-me: 403).
    """
    if can_write(ctx, owner_id):
        return None
    if owner_id == ctx.write_owner and ctx.frozen:
        return 402, {"detail": FROZEN_MSG, "code": "team_frozen", "upgrade": True}
    if owner_id == ctx.write_owner and ctx.member_view_only:
        return 402, {"detail": MEMBER_PRO_MSG, "code": "member_pro_required", "upgrade": True}
    return 403, {"detail": "This item is read-only in your current workspace."}


def workspace_write_denial(ctx: AccessCtx) -> tuple[int, dict] | None:
    """Denials that block ANY write in the active workspace (incl. creates)."""
    if ctx.frozen:
        return 402, {"detail": FROZEN_MSG, "code": "team_frozen", "upgrade": True}
    if ctx.member_view_only:
        return 402, {"detail": MEMBER_PRO_MSG, "code": "member_pro_required", "upgrade": True}
    return None


def member_can_edit(db, user: dict, billing_service) -> bool:
    """Whether this member may edit in a team workspace: Pro or admin.

    Free accounts can join teams and view everything; editing is a Pro
    capability. With billing disabled (self-host) everyone can edit.
    """
    from backend import config

    if not config.BILLING_ENABLED:
        return True
    if billing_service.is_admin_user(user):
        return True
    return billing_service.account(db, user["uid"])["is_pro"]


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
        member_view_only=not member_can_edit(session, user, billing_service),
    )


# ---- Direct shares (view-only) ------------------------------------------------
#
# A share grants one user read access to one artifact. Referenced artifacts
# (a shared model's dataset, a shared study's evidence) become readable
# *transitively* — resolved live per request, never materialised, so the grant
# follows later edits to the root artifact.

SHARABLE_COLLECTIONS = (
    "datasets", "models", "rbds", "degradation_models",
    "strategy_analyses", "rcm_studies",
)

# How much of the reference graph a share can pull in: an RCM study links
# evidence (depth 1) whose models link datasets (depth 2).
_REF_DEPTH = 2


def shared_ids(db, uid: str, collection: str) -> set[str]:
    """Artifact ids in this collection shared directly with the user."""
    return {
        s["artifact_id"]
        for s in db.shares.find({"recipient_uid": uid, "collection": collection})
    }


def refs_of(collection: str, doc: dict) -> list[tuple[str, str]]:
    """(collection, id) pairs this artifact references, from its raw doc."""
    refs: list[tuple[str, str]] = []
    if collection in ("models", "degradation_models") and doc.get("dataset_id"):
        refs.append(("datasets", doc["dataset_id"]))
    elif collection == "rcm_studies":
        type_to_coll = {
            "model": "models",
            "strategy_analysis": "strategy_analyses",
            "degradation_model": "degradation_models",
        }
        for fn in doc.get("functions") or []:
            for failure in fn.get("failures") or []:
                for mode in failure.get("modes") or []:
                    evidence = (mode.get("decision") or {}).get("evidence") or {}
                    coll = type_to_coll.get(evidence.get("type"))
                    if coll and evidence.get("id"):
                        refs.append((coll, evidence["id"]))
    elif collection == "rbds":
        for node in (doc.get("graph") or {}).get("nodes") or []:
            data = node.get("data") or {}
            if data.get("model_id"):
                refs.append(("models", data["model_id"]))
            if data.get("rbd_id"):
                refs.append(("rbds", data["rbd_id"]))
    return refs


def reachable_via_shares(db, uid: str, collection: str) -> set[str]:
    """Ids in ``collection`` readable through shares — direct or referenced.

    Walks the reference graph from every artifact shared with the user
    (depth-capped), so e.g. a shared RCM study's evidence models and their
    datasets open for the recipient. Computed fresh per request: revoking the
    root share instantly revokes the whole chain.
    """
    reachable: dict[str, set[str]] = {c: set() for c in SHARABLE_COLLECTIONS}
    frontier: list[tuple[str, str]] = [
        (s["collection"], s["artifact_id"]) for s in db.shares.find({"recipient_uid": uid})
    ]
    seen: set[tuple[str, str]] = set()
    for _ in range(_REF_DEPTH + 1):
        next_frontier: list[tuple[str, str]] = []
        for coll, aid in frontier:
            if (coll, aid) in seen or coll not in reachable:
                continue
            seen.add((coll, aid))
            reachable[coll].add(aid)
            doc = db[coll].find_one({"_id": aid})
            if doc is not None:
                next_frontier.extend(refs_of(coll, doc))
        if not next_frontier:
            break
        frontier = next_frontier
    return reachable.get(collection, set())


def shared_doc(db, collection: str, cls, artifact_id: str, ctx: AccessCtx):
    """Fetch an artifact readable only through a share (or None).

    The fallback path for get-by-id after the normal owner-scoped fetch
    misses: direct shares first (cheap), then the transitive walk.
    """
    from backend.db import from_doc

    if collection not in SHARABLE_COLLECTIONS:
        return None
    direct = db.shares.find_one({"recipient_uid": ctx.uid, "collection": collection,
                                 "artifact_id": artifact_id})
    if direct is None and artifact_id not in reachable_via_shares(db, ctx.uid, collection):
        return None
    return from_doc(cls, db[collection].find_one({"_id": artifact_id}))


def fetch_readable(db, collection: str, cls, artifact_id: str, ctx: AccessCtx):
    """Get-by-id across everything the user may read.

    Owner-scoped fetch first (own + samples + teams), then — in the personal
    workspace — the share fallback (direct, then transitive references).
    Returns ``(doc, via_share)``.
    """
    from backend.db import from_doc

    doc = from_doc(cls, db[collection].find_one(
        {"_id": artifact_id, "owner_id": {"$in": ctx.read_owners}}
    ))
    if doc is not None:
        return doc, False
    if not ctx.is_personal:
        return None, False
    doc = shared_doc(db, collection, cls, artifact_id, ctx)
    return doc, doc is not None


def is_shared_with(db, uid: str, artifact_id: str) -> bool:
    """Whether this artifact was shared directly with the user (hide vs 403)."""
    return db.shares.find_one({"recipient_uid": uid, "artifact_id": artifact_id}) is not None


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
