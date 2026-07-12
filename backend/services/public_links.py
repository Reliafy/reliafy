"""Public share links: read-only, unauthenticated access to one artifact.

A link is (token → collection, artifact_id, grantor). Anyone with the URL
can view the artifact — no account needed — through a *guest* access
context scoped to the grantor's ownership, so referenced artifacts (a
model's dataset, a study's evidence) resolve exactly as they do for the
owner, while every write path sees an owner that can never match.

Tokens are unguessable (secrets.token_urlsafe) and revocable; the link dies
with the artifact. Only personal artifacts you own can be linked (same rule
as direct shares).
"""

from __future__ import annotations

import secrets
from datetime import datetime, timezone

from backend.config import SAMPLE_OWNER
from backend.services import access
from backend.services import samples as samples_service

# Artifact types with a public renderer. RBDs are excluded until the canvas
# has a public read-only view.
PUBLIC_COLLECTIONS = {
    "models",
    "datasets",
    "degradation_models",
    "strategy_analyses",
    "rcm_studies",
    "fleets",
}

# Fields stripped (recursively) from public payloads: identities and
# account-relative flags that mean nothing to an anonymous viewer.
PRIVATE_KEYS = {"owner_id", "updated_by", "shared_by", "read_only", "recipient_email"}


class PublicLinkError(ValueError):
    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status


def _now():
    return datetime.now(timezone.utc)


def create_link(db, collection: str, artifact_id: str, user: dict) -> dict:
    """Create (or return the existing) public link for an owned artifact."""
    if collection not in PUBLIC_COLLECTIONS:
        raise PublicLinkError(f"'{collection}' can't be shared with a public link.")

    doc = db[collection].find_one({"_id": artifact_id})
    if doc is None or doc.get("owner_id") != user["uid"]:
        if doc is not None and samples_service.is_sample(doc.get("owner_id")):
            raise PublicLinkError("Samples are already visible to every account.")
        if doc is not None and access.is_team_owner(doc.get("owner_id")):
            raise PublicLinkError("Team artifacts can't be linked publicly yet.")
        raise PublicLinkError("Artifact not found.", 404)

    existing = db.public_links.find_one({"collection": collection, "artifact_id": artifact_id})
    if existing is not None:
        return existing

    link = {
        "_id": secrets.token_urlsafe(18),
        "collection": collection,
        "artifact_id": artifact_id,
        "grantor_uid": user["uid"],
        "created_at": _now(),
    }
    db.public_links.insert_one(link)
    return link


def get_for_artifact(db, collection: str, artifact_id: str, uid: str) -> dict | None:
    return db.public_links.find_one(
        {"collection": collection, "artifact_id": artifact_id, "grantor_uid": uid}
    )


def revoke(db, token: str, uid: str) -> bool:
    result = db.public_links.delete_one({"_id": token, "grantor_uid": uid})
    return result.deleted_count > 0


def resolve(db, token: str) -> dict | None:
    return db.public_links.find_one({"_id": token})


def guest_ctx(owner_id: str, grantor_uid: str) -> access.AccessCtx:
    """A read-only access context impersonating the grantor's *view* (their
    own artifacts, samples, and anything shared to them — the same set a
    logged-in share recipient resolves transitively) with a write principal
    that can never match, so every mutation path is denied."""
    return access.AccessCtx(
        user={"uid": grantor_uid, "email": None, "name": "Public link"},
        uid=grantor_uid,
        workspace="personal",
        write_owner="__public-link__",
        read_owners=[owner_id, SAMPLE_OWNER],
        list_owners=[owner_id, SAMPLE_OWNER],
        hidden=set(),
        member_view_only=True,
    )


def sanitize(value):
    """Recursively drop identity fields from a public payload."""
    if isinstance(value, dict):
        return {k: sanitize(v) for k, v in value.items() if k not in PRIVATE_KEYS}
    if isinstance(value, list):
        return [sanitize(v) for v in value]
    return value


def public(link: dict) -> dict:
    return {
        "token": link["_id"],
        "collection": link["collection"],
        "artifact_id": link["artifact_id"],
        "created_at": link["created_at"].isoformat()
        if hasattr(link["created_at"], "isoformat")
        else link["created_at"],
        "path": f"/p/{link['_id']}",
    }
