"""Direct artifact sharing: view-only grants to any registered user.

A share is (collection, artifact_id, recipient). Recipients see the artifact
inline in their lists with a "shared by" tag, read-only — like samples. They
can hide it (reusing ``users.hidden_samples``); the grantor can revoke.
Referenced artifacts resolve transitively at read time (services/access.py).
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone

from backend.services import access
from backend.services import email as email_service
from backend.services import email_trust
from backend.services import rate_limit
from backend.services import samples as samples_service

logger = logging.getLogger(__name__)

# Share requests per grantor, per hour and per day.
SHARES_PER_HOUR = 30
SHARES_PER_DAY = 100
MAX_EMAIL = 254
PENDING_PREFIX = "pending:"


_LINK_PATHS = {
    "datasets": "/data/{id}",
    "models": "/models/m/{id}",
    "rbds": "/systems/b/{id}",
    "degradation_models": "/models/degradation/{id}",
    "recurrent_models": "/models/recurrent/{id}",
    "strategy_analyses": "/strategy/analyses/{id}",
    "rcm_studies": "/maintenance/rcm/{id}",
}


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
    if not email_lc or "@" not in email_lc or len(email_lc) > MAX_EMAIL:
        raise ShareError("Enter a valid email address.", 422)
    if email_lc == (grantor.get("email") or "").strip().lower():
        raise ShareError("That's you — the artifact is already yours.")
    _consume_share(db, grantor)

    # The response is the same whether or not the address has a verified
    # account. Anyone can sign up claiming any address, so only an account
    # that has proven it owns this one gets the share now; otherwise it waits
    # (``recipient_uid`` "pending:<email>") and is claimed when an account
    # signs in with the address verified (``claim_pending``).
    recipient = db.users.find_one({"$or": [{"email_lc": email_lc}, {"email": email_lc}]})
    if recipient is not None:
        verification = email_trust.status(db, recipient["_id"], recipient.get("email_verified"))
        if verification != email_trust.VERIFIED:
            recipient = None
    recipient_uid = recipient["_id"] if recipient is not None else _pending_uid(email_lc)

    link_path = _LINK_PATHS.get(collection, "/models").format(id=artifact_id)
    existing = db.shares.find_one({"artifact_id": artifact_id, "recipient_uid": recipient_uid})
    if existing is None:
        share = {
            "_id": uuid.uuid4().hex,
            "collection": collection,
            "artifact_id": artifact_id,
            "grantor_uid": grantor["uid"],
            "recipient_uid": recipient_uid,
            "recipient_email": email_lc,
            "created_at": _now(),
        }
        db.shares.insert_one(share)
        if recipient is not None:
            # The notification never decides the request: the share is made.
            try:
                email_service.artifact_shared(
                    recipient.get("email") or email_lc,
                    grantor.get("name") or grantor.get("email") or "A Reliafy user",
                    doc.get("name") or "an analysis",
                    link_path,
                    sharer_email=grantor.get("email"),
                )
            except Exception:  # noqa: BLE001
                logger.exception("share notification failed share=%s", share["_id"])
    else:
        share = existing
    if recipient is not None:
        # Re-sharing un-hides: a recipient who dismissed it gets it back.
        db.users.update_one({"_id": recipient["_id"]}, {"$pull": {"hidden_samples": artifact_id}})
    return share


def _pending_uid(email_lc: str) -> str:
    """The placeholder recipient of a share waiting for a verified account."""
    return f"{PENDING_PREFIX}{email_lc}"


def _consume_share(db, grantor: dict) -> None:
    """Count one share request against the grantor; 429 past the hourly or
    daily limit."""
    for window, limit in ((3600, SHARES_PER_HOUR), (86400, SHARES_PER_DAY)):
        if not rate_limit.consume(db, f"share:user:{grantor['uid']}", limit, window):
            minutes = max(1, rate_limit.retry_after(window) // 60)
            raise ShareError(f"That's a lot of shares in a short time — try again in {minutes} min.", 429)


def claim_pending(db, user: dict) -> int:
    """Give a signed-in account the shares waiting for its address, once the
    address is verified. Returns how many were claimed (idempotent)."""
    email_lc = (user.get("email") or "").strip().lower()
    if not email_lc or not user.get("uid"):
        return 0
    from backend import config

    flag = user.get("email_verified")
    if config.AUTH_DISABLED:
        verified = True
    elif flag is None:
        verified = email_trust.verified(db, user["uid"])
    else:
        verified = flag is True
    if not verified:
        return 0
    claimed = 0
    for share in db.shares.find({"recipient_uid": _pending_uid(email_lc)}):
        if db.shares.find_one({"artifact_id": share["artifact_id"], "recipient_uid": user["uid"]}):
            db.shares.delete_one({"_id": share["_id"]})
            continue
        db.shares.update_one({"_id": share["_id"]}, {"$set": {"recipient_uid": user["uid"]}})
        claimed += 1
    return claimed


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
