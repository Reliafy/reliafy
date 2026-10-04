"""Personal API tokens: programmatic access for scripts and AI agents.

A token is shown once at creation (``rlf_`` + urlsafe random); only its
sha256 hash is stored, alongside a short display prefix so users can tell
tokens apart. Tokens are never accepted by the normal session-auth paths, so
they can't touch the account, billing or tokens.

Each token carries scopes (:data:`SCOPES`) that decide what it may do:

* ``ingest`` — the ``/api/ingest`` endpoints and ``/api/import/models``
  (pushing usage, measurements and failure data);
* ``read`` — ``/api/v1`` reads and calculations, and the MCP tools marked
  read-only;
* ``write`` — ``/api/v1`` creates (datasets, fits) and every MCP tool that
  saves, changes, deletes or shares.

A token created before scopes existed has no ``scopes`` field and keeps every
scope (:func:`scopes_of`), so existing integrations carry on working.
"""

from __future__ import annotations

import hashlib
import secrets
import uuid
from datetime import datetime, timezone

from backend.services import email_trust

MAX_TOKENS_PER_USER = 10
_PREFIX = "rlf_"

SCOPES = ("ingest", "read", "write")


class TokenError(ValueError):
    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status


def _now():
    return datetime.now(timezone.utc)


def _hash(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


def clean_scopes(scopes) -> list[str]:
    """The requested scopes, validated, in canonical order. ``None`` (not
    given) means every scope; an empty or unknown selection is refused."""
    if scopes is None:
        return list(SCOPES)
    if isinstance(scopes, str):
        scopes = scopes.replace(",", " ").split()
    if not isinstance(scopes, (list, tuple)):
        raise TokenError("scopes must be a list of: " + ", ".join(SCOPES) + ".", 422)
    unknown = [s for s in scopes if s not in SCOPES]
    if unknown:
        raise TokenError(f"Unknown scope '{unknown[0]}' — use any of: " + ", ".join(SCOPES) + ".", 422)
    if not scopes:
        raise TokenError("Give the token at least one scope.", 422)
    return [s for s in SCOPES if s in scopes]


def scopes_of(record: dict) -> list[str]:
    """A stored token's scopes; one made before scopes existed has them all."""
    scopes = record.get("scopes")
    if scopes is None:
        return list(SCOPES)
    return [s for s in SCOPES if s in scopes]


def has_scope(user: dict, scope: str) -> bool:
    """Whether a request's user may act with ``scope``: an API-token user only
    with that scope on the token; a signed-in session or OAuth user always."""
    if not user.get("via_token"):
        return True
    return scope in (user.get("token_scopes") or ())


def scope_message(scope: str) -> str:
    labels = {"ingest": "push data (ingest)", "read": "read", "write": "write"}
    return (f"This API token doesn't have the '{scope}' scope, needed to {labels.get(scope, scope)} here. "
            "Create a token with that scope under Settings > API access.")


def create_token(db, uid: str, name: str, scopes=None) -> dict:
    """Mint a token for ``uid`` with ``scopes`` (default: all). Returns the
    public record plus, once only, the raw ``token`` value."""
    scopes = clean_scopes(scopes)
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
        "scopes": scopes,
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
    """Resolve a raw token to its user ({uid, email, name, token_scopes, …})
    or None."""
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
        "email_verified": email_trust.profile_flag(db, record["uid"], user),
        "via_token": record["_id"],
        "token_scopes": scopes_of(record),
    }


def public(record: dict) -> dict:
    iso = lambda v: v.isoformat() if hasattr(v, "isoformat") else v
    return {
        "id": record["_id"],
        "name": record["name"],
        "prefix": record["prefix"],
        "scopes": scopes_of(record),
        "created_at": iso(record["created_at"]),
        "last_used_at": iso(record.get("last_used_at")),
    }
