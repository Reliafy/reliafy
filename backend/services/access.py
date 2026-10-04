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
    # Whether get-by-id may fall back to artifacts shared with ``uid``. Off for
    # contexts that act for someone else's view (public links) or that are
    # owner-scoped by design (MCP tools).
    share_fallback: bool = True

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
    "strategy_analyses", "rcm_studies", "fleets",
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


# Keys on an RBD node's data that hold a life/repair model, and the keys a
# model object uses for a saved model's id.
_GRAPH_MODEL_KEYS = ("model", "standbyModel", "repair")
_SAVED_MODEL_ID_KEYS = ("modelId", "model_id", "saved_model_id")

_EVIDENCE_COLLECTIONS = {
    "model": "models",
    "strategy_analysis": "strategy_analyses",
    "degradation_model": "degradation_models",
}


def _str_id(value) -> str | None:
    return value if isinstance(value, str) and value else None


def graph_refs(graph) -> list[tuple[str, str]]:
    """(collection, id) pairs an RBD graph references: saved models on its
    blocks (life, spare and repair models) and nested sub-system diagrams."""
    refs: list[tuple[str, str]] = []
    if not isinstance(graph, dict):
        return refs
    for node in graph.get("nodes") or []:
        if not isinstance(node, dict):
            continue
        data = node.get("data") or {}
        if not isinstance(data, dict):
            continue
        for key in _GRAPH_MODEL_KEYS:
            model = data.get(key)
            if isinstance(model, dict):
                for id_key in _SAVED_MODEL_ID_KEYS:
                    if mid := _str_id(model.get(id_key)):
                        refs.append(("models", mid))
        if mid := _str_id(data.get("model_id")):
            refs.append(("models", mid))
        if rid := _str_id(data.get("rbd_id")):
            refs.append(("rbds", rid))
        sub = data.get("rbd")
        if isinstance(sub, dict) and (rid := _str_id(sub.get("id"))):
            refs.append(("rbds", rid))
    return refs


def evidence_refs(functions) -> list[tuple[str, str]]:
    """(collection, id) pairs an RCM worksheet's decisions link as evidence."""
    refs: list[tuple[str, str]] = []
    for fn in functions or []:
        if not isinstance(fn, dict):
            continue
        for failure in fn.get("failures") or []:
            if not isinstance(failure, dict):
                continue
            for mode in failure.get("modes") or []:
                if not isinstance(mode, dict):
                    continue
                evidence = (mode.get("decision") or {}).get("evidence") or {}
                if not isinstance(evidence, dict):
                    continue
                coll = _EVIDENCE_COLLECTIONS.get(evidence.get("type"))
                if coll and (eid := _str_id(evidence.get("id"))):
                    refs.append((coll, eid))
    return refs


def refs_of(collection: str, doc: dict) -> list[tuple[str, str]]:
    """(collection, id) pairs this artifact references, from its raw doc."""
    refs: list[tuple[str, str]] = []
    if collection in ("models", "degradation_models") and _str_id(doc.get("dataset_id")):
        refs.append(("datasets", doc["dataset_id"]))
    elif collection == "fleets" and _str_id(doc.get("model_id")):
        refs.append(("models", doc["model_id"]))
    elif collection == "rcm_studies":
        refs.extend(evidence_refs(doc.get("functions")))
    elif collection == "rbds":
        refs.extend(graph_refs(doc.get("graph")))
    return refs


def _share_owners(grantor_uid: str | None) -> list[str]:
    """Whose artifacts a share from ``grantor_uid`` can open: the grantor's own
    (and the samples everyone sees). A reference into anyone else's data —
    a team's, or something shared *to* the grantor — is not followed."""
    return [grantor_uid, SAMPLE_OWNER] if grantor_uid else [SAMPLE_OWNER]


def _share_root(db, share: dict) -> dict | None:
    """The shared artifact itself, while the grantor still owns it."""
    if share.get("collection") not in SHARABLE_COLLECTIONS:
        return None
    return db[share["collection"]].find_one(
        {"_id": share["artifact_id"], "owner_id": {"$in": _share_owners(share.get("grantor_uid"))}}
    )


def reachable_via_shares(db, uid: str, collection: str) -> set[str]:
    """Ids in ``collection`` readable through shares — direct or referenced.

    Walks the reference graph from every artifact shared with the user
    (depth-capped), so e.g. a shared RCM study's evidence models and their
    datasets open for the recipient. Every step stays inside the grantor's
    own artifacts (plus samples): a reference to anything the grantor
    doesn't own is not followed. Computed fresh per request: revoking the
    root share instantly revokes the whole chain.
    """
    reachable: dict[str, set[str]] = {c: set() for c in SHARABLE_COLLECTIONS}
    frontier: list[tuple[str, str, str]] = []
    for share in db.shares.find({"recipient_uid": uid}):
        root = _share_root(db, share)
        if root is None:
            continue
        reachable[share["collection"]].add(root["_id"])
        frontier.extend((c, i, share["grantor_uid"]) for c, i in refs_of(share["collection"], root))
    seen: set[tuple[str, str, str]] = set()
    for _ in range(_REF_DEPTH):
        if not frontier:
            break
        next_frontier: list[tuple[str, str, str]] = []
        for coll, aid, grantor in frontier:
            if (coll, aid, grantor) in seen or coll not in reachable:
                continue
            seen.add((coll, aid, grantor))
            doc = db[coll].find_one({"_id": aid, "owner_id": {"$in": _share_owners(grantor)}})
            if doc is None:
                continue
            reachable[coll].add(aid)
            next_frontier.extend((c, i, grantor) for c, i in refs_of(coll, doc))
        frontier = next_frontier
    return reachable.get(collection, set())


def _shared_raw(db, collection: str, artifact_id: str, uid: str) -> dict | None:
    """The raw artifact when it's readable through a share, else None."""
    if collection not in SHARABLE_COLLECTIONS:
        return None
    direct = db.shares.find_one({"recipient_uid": uid, "collection": collection,
                                 "artifact_id": artifact_id})
    if direct is not None:
        root = _share_root(db, direct)
        if root is not None:
            return root
    if artifact_id not in reachable_via_shares(db, uid, collection):
        return None
    return db[collection].find_one({"_id": artifact_id})


def shared_doc(db, collection: str, cls, artifact_id: str, ctx: AccessCtx):
    """Fetch an artifact readable only through a share (or None).

    The fallback path for get-by-id after the normal owner-scoped fetch
    misses: direct shares first (cheap), then the transitive walk.
    """
    from backend.db import from_doc

    return from_doc(cls, _shared_raw(db, collection, artifact_id, ctx.uid))


def readable_raw(db, collection: str, artifact_id: str, ctx: AccessCtx) -> tuple[dict | None, bool]:
    """``(raw doc, via_share)`` for get-by-id across everything the user may
    read; ``(None, False)`` when they can't read it."""
    if not isinstance(artifact_id, str) or not artifact_id:
        return None, False
    doc = db[collection].find_one({"_id": artifact_id, "owner_id": {"$in": ctx.read_owners}})
    if doc is not None:
        return doc, False
    if not ctx.is_personal or not ctx.share_fallback:
        return None, False
    doc = _shared_raw(db, collection, artifact_id, ctx.uid)
    return doc, doc is not None


def fetch_readable(db, collection: str, cls, artifact_id: str, ctx: AccessCtx):
    """Get-by-id across everything the user may read.

    Owner-scoped fetch first (own + samples + teams), then — in the personal
    workspace — the share fallback (direct, then transitive references).
    Returns ``(doc, via_share)``.
    """
    from backend.db import from_doc

    doc, via_share = readable_raw(db, collection, artifact_id, ctx)
    return from_doc(cls, doc), via_share


# ---- References saved on an artifact -------------------------------------------

_REF_LABELS = {
    "models": "saved model",
    "datasets": "dataset",
    "rbds": "diagram",
    "strategy_analyses": "strategy analysis",
    "degradation_models": "degradation model",
}


class UnreadableReference(ValueError):
    """A save would link an artifact the writer can't open."""

    status = 422

    def __init__(self, collection: str, artifact_id: str):
        self.collection = collection
        self.artifact_id = artifact_id
        label = _REF_LABELS.get(collection, "item")
        super().__init__(
            f"This links a {label} you can't open (id {artifact_id}). Remove that link or pick "
            f"a {label} you have access to, then save again."
        )


def check_references(db, ctx: AccessCtx, refs, keep=()) -> None:
    """Refuse a save whose references point at artifacts the writer can't read.

    ``refs`` are ``(collection, id)`` pairs (:func:`graph_refs`,
    :func:`evidence_refs`, …), checked with :func:`readable_raw` — the same
    rule as opening the artifact. ``keep`` are the pairs the artifact already
    held before this save: they are left alone, so a document saved before
    this check stays editable (and the share walk never follows a reference
    outside its owner's data anyway). A reference to an id that no longer
    exists anywhere (a deleted model, say) is a stale link rather than
    someone else's data, and is allowed. Raises :class:`UnreadableReference`.
    """
    kept = set(keep)
    for coll, aid in dict.fromkeys(refs):
        if (coll, aid) in kept or not isinstance(aid, str):
            continue
        doc, _ = readable_raw(db, coll, aid, ctx)
        if doc is not None:
            continue
        if db[coll].find_one({"_id": aid}, {"_id": 1}) is None:
            continue
        raise UnreadableReference(coll, aid)


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
    owner_user = {"email": owner_doc.get("email"), "email_verified": owner_doc.get("email_verified")}
    if billing_service.is_admin_user(owner_user):
        return False
    return not billing_service.account(db, owner_uid)["is_pro"]
