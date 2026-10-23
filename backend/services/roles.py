"""What a user does: the roles that shape which menu entries they see
first and what their Home leads with.

Roles are a lens over one menu, not separate menus: the frontend
(``frontend/src/navigation.js``) holds which entries each role uses; the
server only keeps the user's picks, on their profile (``users.roles``), in the
order they were picked (the first is the primary role). No roles saved is
everything shown, which is what every existing user has.

A new user is asked once, on Home: answering, or saying "not now", records
``users.roles_offered`` and the question doesn't come back (Settings keeps
the picker).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

# Keep in step with ROLES in frontend/src/navigation.js.
ROLE_IDS = ("analyst", "design", "planner", "technician", "fleet", "logistics", "manager")

# "New" for the one-time question: an account this young.
OFFER_DAYS = 14


class BadRoles(ValueError):
    """Not a list of known roles (HTTP 422)."""


def _now() -> datetime:
    return datetime.now(timezone.utc)


def clean(value) -> list[str]:
    """Roles as stored: known ids, each once, in the order given."""
    if not isinstance(value, list):
        raise BadRoles("Roles are a list, like [\"analyst\", \"planner\"].")
    out: list[str] = []
    for role in value:
        if role not in ROLE_IDS:
            raise BadRoles(f"{str(role)[:40]!r} isn't a role: use any of {', '.join(ROLE_IDS)}.")
        if role not in out:
            out.append(role)
    return out


def _is_new(created) -> bool:
    if not isinstance(created, datetime):
        return False
    if created.tzinfo is None:
        created = created.replace(tzinfo=timezone.utc)
    return _now() - created <= timedelta(days=OFFER_DAYS)


def of_user(db, uid: str) -> dict:
    """``{"roles": [...], "offer": bool}``: the saved roles (empty: everything
    shown), and whether to ask this user what they do (once, new users only)."""
    doc = db.users.find_one({"_id": uid}, {"roles": 1, "roles_offered": 1, "created_at": 1}) or {}
    roles = [r for r in (doc.get("roles") or []) if r in ROLE_IDS]
    offer = "roles" not in doc and not doc.get("roles_offered") and _is_new(doc.get("created_at"))
    return {"roles": roles, "offer": offer}


def save(db, uid: str, roles) -> dict:
    """Save the user's roles (``[]``: everything shown); the question is answered."""
    cleaned = clean(roles)
    db.users.update_one({"_id": uid}, {"$set": {"roles": cleaned, "roles_offered": True}})
    return {"roles": cleaned, "offer": False}


def dismiss_offer(db, uid: str) -> dict:
    """"Not now": don't ask again; the roles stay as they are."""
    db.users.update_one({"_id": uid}, {"$set": {"roles_offered": True}})
    return of_user(db, uid)
