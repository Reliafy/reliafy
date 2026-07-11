"""Direct artifact sharing: view-only grants to any registered user.

A share is (collection, artifact_id, recipient). Recipients see the artifact
inline in their lists with a "shared by" tag, read-only — like samples. They
can hide it (reusing ``users.hidden_samples``); the grantor can revoke.
Referenced artifacts resolve transitively at read time (services/access.py).
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from backend.services import access
from backend.services import samples as samples_service


class ShareError(ValueError):
    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status


def _now():
    return datetime.now(timezone.utc)


def create_share(db, collection: str, artifact_id: str, email: str, grantor: dict) -> dict:
    if collection not in access.SHARABLE_COLLECTIONS:
        raise ShareError(f"'{collection}' can't be shared.")

    doc = db[collection].find_one({"_id": artifact_id})
    if doc is None or doc.get("owner_id") != grantor["uid"]:
        # Only personal artifacts you own are sharable (team artifacts are
        # already shared with the team; samples belong to everyone).
        if doc is not None and samples_service.is_sample(doc.get("owner_id")):
            raise ShareError("Samples are already visible to every account.")
        if doc is not None and access.is_team_owner(doc.get("owner_id")):
            raise ShareError("Team artifacts can't be shared individually yet — invite people to the team instead.")
        raise ShareError("Artifact not found.", 404)

    email_lc = (email or "").strip().lower()
    if not email_lc or "@" not in email_lc:
        raise ShareError("Enter a valid email address.", 422)
    if email_lc == (grantor.get("email") or "").strip().lower():
        raise ShareError("That's you — the artifact is already yours.")

    recipient = db.users.find_one({"$or": [{"email_lc": email_lc}, {"email": email_lc}]})
    if recipient is None:
        raise ShareError("No Reliafy account exists for that email address.", 404)

    existing = db.shares.find_one({"artifact_id": artifact_id, "recipient_uid": recipient["_id"]})
    if existing is None:
        share = {
            "_id": uuid.uuid4().hex,
            "collection": collection,
            "artifact_id": artifact_id,
            "grantor_uid": grantor["uid"],
            "recipient_uid": recipient["_id"],
            "recipient_email": recipient.get("email") or email_lc,
            "created_at": _now(),
        }
        db.shares.insert_one(share)
    else:
        share = existing
    # Re-sharing un-hides: a recipient who dismissed it gets it back.
    db.users.update_one({"_id": recipient["_id"]}, {"$pull": {"hidden_samples": artifact_id}})
    return share


def list_for_artifact(db, artifact_id: str, grantor_uid: str) -> list[dict]:
    return list(db.shares.find({"artifact_id": artifact_id, "grantor_uid": grantor_uid})
                .sort("created_at", -1))


def revoke(db, share_id: str, grantor_uid: str) -> bool:
    result = db.shares.delete_one({"_id": share_id, "grantor_uid": grantor_uid})
    return result.deleted_count > 0


def grantor_email(db, uid_to_email_cache: dict, grantor_uid: str) -> str | None:
    """Grantor's email for display, memoised per request."""
    if grantor_uid not in uid_to_email_cache:
        doc = db.users.find_one({"_id": grantor_uid}) or {}
        uid_to_email_cache[grantor_uid] = doc.get("email")
    return uid_to_email_cache[grantor_uid]


def shared_by_map(db, uid: str, collection: str) -> dict[str, str]:
    """artifact_id -> grantor email, for tagging list rows."""
    cache: dict = {}
    return {
        s["artifact_id"]: grantor_email(db, cache, s["grantor_uid"]) or "another user"
        for s in db.shares.find({"recipient_uid": uid, "collection": collection})
    }


def shared_by_for(db, uid: str, artifact_id: str) -> str | None:
    """Grantor email when this artifact is directly shared with the user."""
    share = db.shares.find_one({"recipient_uid": uid, "artifact_id": artifact_id})
    if share is None:
        return None
    return grantor_email(db, {}, share["grantor_uid"]) or "another user"


def public(share: dict) -> dict:
    return {
        "id": share["_id"],
        "email": share["recipient_email"],
        "created_at": share["created_at"].isoformat()
        if hasattr(share["created_at"], "isoformat") else share["created_at"],
    }
