"""Personal API tokens: programmatic access for the ingestion API.

A token is shown once at creation (``rlf_`` + urlsafe random); only its
sha256 hash is stored, alongside a short display prefix so users can tell
tokens apart. Tokens authenticate the ``/api/ingest`` endpoints only — they
are not accepted by the normal session-auth paths, so a leaked token can
push data but can never read analyses or touch the account.
"""

from __future__ import annotations

import hashlib
import secrets
import uuid
from datetime import datetime, timezone

MAX_TOKENS_PER_USER = 10
_PREFIX = "rlf_"


class TokenError(ValueError):
    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status


def _now():
    return datetime.now(timezone.utc)


def _hash(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


def create_token(db, uid: str, name: str) -> dict:
    """Mint a token for ``uid``. Returns the public record plus, once only,
    the raw ``token`` value."""
    name = (name or "").strip() or "API token"
    if db.api_tokens.count_documents({"uid": uid}) >= MAX_TOKENS_PER_USER:
        raise TokenError(
            f"Token limit reached ({MAX_TOKENS_PER_USER}). Revoke one you no longer use."
        )
    raw = _PREFIX + secrets.token_urlsafe(24)
    record = {
        "_id": uuid.uuid4().hex,
        "uid": uid,
        "name": name[:100],
        "prefix": raw[:9],
        "token_hash": _hash(raw),
        "created_at": _now(),
        "last_used_at": None,
    }
    db.api_tokens.insert_one(record)
    return {**public(record), "token": raw}


def list_tokens(db, uid: str) -> list[dict]:
    return [public(t) for t in db.api_tokens.find({"uid": uid}).sort("created_at", -1)]


def revoke_token(db, uid: str, token_id: str) -> bool:
    return db.api_tokens.delete_one({"_id": token_id, "uid": uid}).deleted_count > 0


def verify(db, raw: str) -> dict | None:
    """Resolve a raw token to its user ({uid, email, name}) or None."""
    if not raw or not raw.startswith(_PREFIX):
        return None
    record = db.api_tokens.find_one({"token_hash": _hash(raw)})
    if record is None:
        return None
    db.api_tokens.update_one({"_id": record["_id"]}, {"$set": {"last_used_at": _now()}})
    user = db.users.find_one({"_id": record["uid"]}) or {}
    return {
        "uid": record["uid"],
        "email": user.get("email"),
        "name": user.get("name"),
        "via_token": record["_id"],
    }


def public(record: dict) -> dict:
    iso = lambda v: v.isoformat() if hasattr(v, "isoformat") else v
    return {
        "id": record["_id"],
        "name": record["name"],
        "prefix": record["prefix"],
        "created_at": iso(record["created_at"]),
        "last_used_at": iso(record.get("last_used_at")),
    }
