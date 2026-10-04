"""Public share links: read-only, unauthenticated access to one artifact.

A link is (token → collection, artifact_id, grantor). Anyone with the URL
can view the artifact — no account needed — through a *guest* access
context scoped to the grantor's ownership, so referenced artifacts (a
model's dataset, a study's evidence) resolve exactly as they do for the
owner, while every write path sees an owner that can never match.

Tokens are unguessable (secrets.token_urlsafe) and revocable; the link dies
with the artifact. Only personal artifacts you own can be linked (same rule
as direct shares).

An artifact can carry several links, each with an optional label, expiry and
password, so each can be revoked on its own:

* **Expiry** (``expires_at``): an expired link resolves to nothing, exactly
  like a revoked one (a TTL index then deletes it).
* **Password**: a salted ``hashlib.scrypt`` hash plus a ``password_version``.
  The viewer trades the password for a short-lived *unlock token* — an
  HMAC-SHA256 over link id + password version + expiry — keyed with a random
  per-link ``unlock_key`` that lives only in the link document. Setting,
  rotating or removing the password bumps the version and replaces the key,
  so every earlier unlock stops working at once. Unlock attempts are
  rate-limited per link and per client IP in Mongo (:func:`consume_attempt`).

Links created before passwords and expiry existed have none of those fields
and keep working as open, non-expiring links.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import time
from datetime import datetime, timedelta, timezone

from pymongo import ReturnDocument

from backend import config
from backend.config import SAMPLE_OWNER
from backend.services import access
from backend.services import passphrase
from backend.services import samples as samples_service

# Artifact types with a public renderer at /p/:token.
PUBLIC_COLLECTIONS = {
    "models",
    "datasets",
    "degradation_models",
    "strategy_analyses",
    "rcm_studies",
    "fleets",
    "rbds",
    "recurrent_models",
}

# Fields stripped (recursively) from public payloads: identities and
# account-relative flags that mean nothing to an anonymous viewer.
PRIVATE_KEYS = {"owner_id", "updated_by", "shared_by", "read_only", "recipient_email"}

# ---- limits ------------------------------------------------------------------

MAX_LABEL = 80
MAX_EXPIRY_DAYS = 365
MIN_PASSWORD = 8
MAX_PASSWORD = 200
MAX_LINKS_PER_ARTIFACT = 25

# An unlock lasts this long; then the viewer enters the password again.
UNLOCK_TTL = timedelta(hours=12)

# Unlock attempts allowed per fixed window, counted *before* the password is
# checked (so parallel guesses can't race past the limit). Kept in Mongo, so
# the limit holds across Cloud Run instances.
ATTEMPT_WINDOW_SECONDS = 15 * 60
LINK_ATTEMPTS = 10
IP_ATTEMPTS = 30

# scrypt cost: 16 MiB per check (stdlib, no new dependency).
_SCRYPT = {"n": 2**14, "r": 8, "p": 1, "dklen": 32}


class PublicLinkError(ValueError):
    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status


def _now():
    return datetime.now(timezone.utc)


def _aware(dt):
    """Mongo hands datetimes back naive (UTC); compare them as aware."""
    if isinstance(dt, datetime) and dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


# ---- creating and managing links ----------------------------------------------

def owned_artifact(db, collection: str, artifact_id: str, uid: str) -> dict:
    """The artifact, when ``uid`` may link it publicly; else a PublicLinkError."""
    if collection not in PUBLIC_COLLECTIONS:
        raise PublicLinkError(f"'{collection}' can't be shared with a public link.")

    doc = db[collection].find_one({"_id": artifact_id})
    if doc is None or doc.get("owner_id") != uid:
        if doc is not None and samples_service.is_sample(doc.get("owner_id")):
            raise PublicLinkError("Samples are already visible to every account.")
        if doc is not None and access.is_team_owner(doc.get("owner_id")):
            raise PublicLinkError("Team artifacts can't be linked publicly yet.")
        raise PublicLinkError("Artifact not found.", 404)
    return doc


def _clean_label(label) -> str | None:
    label = " ".join(str(label or "").split())
    if len(label) > MAX_LABEL:
        raise PublicLinkError(f"Keep the label under {MAX_LABEL} characters.")
    return label or None


def _expiry(expires_in_days) -> datetime | None:
    if expires_in_days in (None, "", 0):
        return None
    try:
        days = int(expires_in_days)
    except (TypeError, ValueError):
        raise PublicLinkError("Expiry must be a whole number of days.") from None
    if not 1 <= days <= MAX_EXPIRY_DAYS:
        raise PublicLinkError(f"Expiry must be between 1 and {MAX_EXPIRY_DAYS} days.")
    return _now() + timedelta(days=days)


def _password_fields(password: str, version: int) -> dict:
    """Salted scrypt hash, a bumped version and a fresh unlock-signing key —
    together they make every earlier unlock token invalid."""
    if not MIN_PASSWORD <= len(password) <= MAX_PASSWORD:
        raise PublicLinkError(f"Use a password of {MIN_PASSWORD} to {MAX_PASSWORD} characters.")
    salt = secrets.token_bytes(16)
    return {
        "password_hash": hashlib.scrypt(password.encode(), salt=salt, **_SCRYPT).hex(),
        "password_salt": salt.hex(),
        "password_version": version + 1,
        "unlock_key": secrets.token_hex(32),
    }


def _no_password_fields(version: int) -> dict:
    return {
        "password_hash": None,
        "password_salt": None,
        "password_version": version + 1,
        "unlock_key": secrets.token_hex(32),
    }


def _resolve_password(password: str | None, generate: bool) -> tuple[str | None, str | None]:
    """``(password to store, passphrase to hand back once)``. A generated
    passphrase is returned to the caller exactly once; a password the owner
    typed is never echoed back."""
    if generate:
        phrase = passphrase.generate()
        return phrase, phrase
    if password:
        return password, None
    return None, None


def create_link(
    db,
    collection: str,
    artifact_id: str,
    user: dict,
    *,
    label: str | None = None,
    expires_in_days: int | None = None,
    password: str | None = None,
    generate_password: bool = False,
    via: str = "app",
) -> dict:
    """Create a new public link for an owned artifact.

    With ``generate_password`` the returned link carries the passphrase under
    ``passphrase`` — the only time it is ever available; only its hash is
    stored."""
    owned_artifact(db, collection, artifact_id, user["uid"])
    label = _clean_label(label)
    expires_at = _expiry(expires_in_days)
    stored, phrase = _resolve_password(password, generate_password)
    existing = db.public_links.count_documents(
        {"collection": collection, "artifact_id": artifact_id, "grantor_uid": user["uid"]}
    )
    if existing >= MAX_LINKS_PER_ARTIFACT:
        raise PublicLinkError(
            f"An item can have at most {MAX_LINKS_PER_ARTIFACT} links: revoke one you no longer need."
        )

    link = {
        "_id": secrets.token_urlsafe(18),
        "collection": collection,
        "artifact_id": artifact_id,
        "grantor_uid": user["uid"],
        "created_at": _now(),
        "label": label,
        "expires_at": expires_at,
        "via": via,
        **(_password_fields(stored, 0) if stored else _no_password_fields(0)),
    }
    db.public_links.insert_one(link)
    if phrase:
        link = {**link, "passphrase": phrase}
    return link


def update_link(
    db,
    token: str,
    uid: str,
    *,
    label: str | None = None,
    set_label: bool = False,
    password: str | None = None,
    generate_password: bool = False,
    remove_password: bool = False,
) -> dict | None:
    """Relabel a link, or set / rotate / remove its password. Any password
    change bumps the version and the signing key, so earlier unlocks stop
    working at once. None when it isn't the caller's live link."""
    link = resolve(db, token)
    if link is None or link.get("grantor_uid") != uid:
        return None
    changes: dict = {}
    if set_label:
        changes["label"] = _clean_label(label)
    version = int(link.get("password_version") or 0)
    stored, phrase = _resolve_password(password, generate_password)
    if stored:
        changes.update(_password_fields(stored, version))
    elif remove_password:
        changes.update(_no_password_fields(version))
    if changes:
        db.public_links.update_one({"_id": token}, {"$set": changes})
        link = {**link, **changes}
    if phrase:
        link = {**link, "passphrase": phrase}
    return link


def _expired(link: dict, now: datetime | None = None) -> bool:
    expires_at = _aware(link.get("expires_at"))
    return expires_at is not None and expires_at <= (now or _now())


def list_links(db, uid: str, collection: str | None = None, artifact_id: str | None = None) -> list[dict]:
    """The caller's live links, newest first, optionally for one artifact.
    Expired links are left out: they no longer open."""
    query: dict = {"grantor_uid": uid}
    if collection:
        query["collection"] = collection
    if artifact_id:
        query["artifact_id"] = artifact_id
    now = _now()
    return [link for link in db.public_links.find(query).sort("created_at", -1) if not _expired(link, now)]


def get_for_artifact(db, collection: str, artifact_id: str, uid: str) -> dict | None:
    """The newest live link for an artifact."""
    links = list_links(db, uid, collection, artifact_id)
    return links[0] if links else None


def revoke(db, token: str, uid: str) -> bool:
    result = db.public_links.delete_one({"_id": token, "grantor_uid": uid})
    return result.deleted_count > 0


def resolve(db, token: str) -> dict | None:
    """The live link for a token: None when it doesn't exist, was revoked or
    has expired (all three look the same to a viewer)."""
    link = db.public_links.find_one({"_id": token})
    if link is None or _expired(link):
        return None
    return link


# ---- passwords and unlocks -----------------------------------------------------

def is_protected(link: dict) -> bool:
    return bool(link.get("password_hash"))


def check_password(link: dict, password: str) -> bool:
    """Constant-time check of a password against the link's scrypt hash."""
    if not is_protected(link) or not password or len(password) > MAX_PASSWORD:
        return False
    digest = hashlib.scrypt(password.encode(), salt=bytes.fromhex(link["password_salt"]), **_SCRYPT)
    return hmac.compare_digest(digest.hex(), link["password_hash"])


def _signature(link: dict, version: int, exp: int) -> str:
    """HMAC-SHA256 over link id + password version + expiry, keyed with the
    link's own random signing key (server-side only, replaced on every
    password change)."""
    message = f"{link['_id']}|{version}|{exp}".encode()
    mac = hmac.new(bytes.fromhex(link["unlock_key"]), message, hashlib.sha256).digest()
    return base64.urlsafe_b64encode(mac).decode().rstrip("=")


def issue_unlock(link: dict) -> dict:
    """A short-lived unlock token for a protected link: ``version.exp.sig``."""
    version = int(link.get("password_version") or 0)
    expires = _now() + UNLOCK_TTL
    exp = int(expires.timestamp())
    return {
        "unlock_token": f"{version}.{exp}.{_signature(link, version, exp)}",
        "expires_at": expires.isoformat(),
    }


def verify_unlock(link: dict, unlock_token: str | None) -> bool:
    """True when ``unlock_token`` was issued for this link's current password
    and hasn't expired."""
    if not unlock_token or not link.get("unlock_key"):
        return False
    try:
        version_s, exp_s, sig = unlock_token.split(".", 2)
        version, exp = int(version_s), int(exp_s)
    except ValueError:
        return False
    if version != int(link.get("password_version") or 0) or exp <= _now().timestamp():
        return False
    return hmac.compare_digest(sig, _signature(link, version, exp))


def can_view(link: dict, unlock_token: str | None) -> bool:
    """Open links always; protected ones only with a valid unlock token."""
    return not is_protected(link) or verify_unlock(link, unlock_token)


def ip_key(ip: str) -> str:
    """The rate-limit key for a client IP: a salted hash, never the IP."""
    return "ip:" + hashlib.sha256(f"{config.METRICS_SALT}|unlock|{ip}".encode()).hexdigest()[:24]


def consume_attempt(db, key: str, limit: int) -> bool:
    """Count one unlock attempt against ``key`` in the current fixed window;
    False once the window's ``limit`` is used up. One atomic upsert, so it
    holds under concurrent requests and across instances; a TTL index drops
    finished windows."""
    bucket = int(time.time() // ATTEMPT_WINDOW_SECONDS)
    doc = db.public_link_attempts.find_one_and_update(
        {"_id": f"{key}:{bucket}"},
        {
            "$inc": {"n": 1},
            "$setOnInsert": {
                "expires_at": datetime.fromtimestamp((bucket + 1) * ATTEMPT_WINDOW_SECONDS, timezone.utc)
            },
        },
        upsert=True,
        return_document=ReturnDocument.AFTER,
    )
    return int(doc["n"]) <= limit


def retry_after_seconds() -> int:
    """Seconds until the current attempt window ends."""
    return int(ATTEMPT_WINDOW_SECONDS - time.time() % ATTEMPT_WINDOW_SECONDS) + 1


# ---- viewing -------------------------------------------------------------------

def guest_ctx(owner_id: str, grantor_uid: str) -> access.AccessCtx:
    """A read-only access context for a public link: the grantor's own
    artifacts plus the samples — nothing shared *to* the grantor, and nothing
    the grantor doesn't own — with a write principal that can never match, so
    every mutation path is denied. ``owner_id`` must be the grantor (links are
    only made on artifacts their creator owns); anything else reads nothing
    but samples."""
    readers = [grantor_uid, SAMPLE_OWNER] if owner_id == grantor_uid else [SAMPLE_OWNER]
    return access.AccessCtx(
        user={"uid": grantor_uid, "email": None, "name": "Public link"},
        uid=grantor_uid,
        workspace="personal",
        write_owner="__public-link__",
        read_owners=readers,
        list_owners=list(readers),
        hidden=set(),
        member_view_only=True,
        share_fallback=False,
    )


def sanitize(value):
    """Recursively drop identity fields from a public payload."""
    if isinstance(value, dict):
        return {k: sanitize(v) for k, v in value.items() if k not in PRIVATE_KEYS}
    if isinstance(value, list):
        return [sanitize(v) for v in value]
    return value


def _iso(value):
    value = _aware(value)
    return value.isoformat() if hasattr(value, "isoformat") else value


def public(link: dict) -> dict:
    """A link as its owner sees it: never the hash, salt or signing key, and
    the passphrase only straight after it was generated."""
    out = {
        "token": link["_id"],
        "collection": link["collection"],
        "artifact_id": link["artifact_id"],
        "created_at": _iso(link["created_at"]),
        "path": f"/p/{link['_id']}",
        "label": link.get("label"),
        "expires_at": _iso(link.get("expires_at")),
        "protected": is_protected(link),
    }
    if link.get("passphrase"):
        out["passphrase"] = link["passphrase"]
    return out
