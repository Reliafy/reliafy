"""A workspace's time zone, and the calendar day it's in.

The server runs in UTC, so on its own "today" turns over at midnight UTC: 10:00
in Brisbane. A workspace can say where it is, as an IANA name such as
``"Australia/Brisbane"``: the personal workspace on the user's profile
(``users.time_zone``), a team's on the team (``teams.time_zone``, set by its
owner). Calendar days people see (a work order's date, "today" for a reading,
due and overdue) follow it. Unset is the server's own zone, exactly as before:
UTC in production. Timestamps (``created_at`` and the like) stay UTC.

:class:`~backend.services.access.AccessCtx` carries the active workspace's
zone; :func:`of_owner` finds it from an ``owner_id`` where there's no request
(the daily run, an upload link, the MCP tools).
"""

from __future__ import annotations

from datetime import date, datetime, timezone, tzinfo
from functools import lru_cache
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError, available_timezones

MAX_NAME = 64


class BadTimeZone(ValueError):
    """Not a time zone the server knows (HTTP 422)."""


@lru_cache(maxsize=1)
def _names() -> frozenset[str]:
    return frozenset(available_timezones())


def clean(value) -> str | None:
    """A time zone as stored: an IANA name (``"Australia/Brisbane"``), or None
    to clear it (the server's zone, UTC)."""
    if value is None:
        return None
    if not isinstance(value, str):
        raise BadTimeZone("The time zone is a name like Australia/Brisbane.")
    text = value.strip()
    if not text:
        return None
    if len(text) > MAX_NAME or text not in _names():
        raise BadTimeZone(f"{text[:40]!r} isn't a time zone: use a name like Australia/Brisbane, "
                          "Europe/London or America/New_York.")
    return text


@lru_cache(maxsize=1024)
def zone(name: str | None) -> tzinfo | None:
    """``name`` as a tzinfo; None (the server's own zone) when unset, or when a
    stored name is one the server no longer has."""
    if not name:
        return None
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError):
        return None


def _now() -> datetime:
    return datetime.now(timezone.utc)


def now(name: str | None = None) -> datetime:
    """The time now, in the zone (the server's when unset)."""
    return _now().astimezone(zone(name))


def today(name: str | None = None) -> date:
    """Today's date in the zone (the server's when unset)."""
    return now(name).date()


def day_of(t: datetime, tz: tzinfo | None = None) -> str:
    """The ISO day a moment falls on in ``tz`` (the server's when None). A naive
    moment is UTC."""
    if t.tzinfo is None:
        t = t.replace(tzinfo=timezone.utc)
    return t.astimezone(tz).date().isoformat()


def of_owner(db, owner: str | None) -> str | None:
    """The time zone of the workspace an ``owner_id`` names: a team's
    (``team:<id>``), else that user's. None when unset."""
    if not owner or not isinstance(owner, str):
        return None
    if owner.startswith("team:"):
        doc = db.teams.find_one({"_id": owner[len("team:"):]}, {"time_zone": 1})
    else:
        doc = db.users.find_one({"_id": owner}, {"time_zone": 1})
    return zone_name((doc or {}).get("time_zone"))


def zone_name(stored) -> str | None:
    """A stored zone, if it's one the server can use."""
    return stored if isinstance(stored, str) and zone(stored) is not None else None


def set_personal(db, uid: str, value) -> str | None:
    """Set (or clear, with None or "") the personal workspace's time zone."""
    name = clean(value)
    db.users.update_one({"_id": uid}, {"$set": {"time_zone": name}})
    return name


def set_team(db, team_id: str, value) -> str | None:
    """Set (or clear) a team workspace's time zone. The caller checks who may."""
    name = clean(value)
    db.teams.update_one({"_id": team_id}, {"$set": {"time_zone": name, "updated_at": _now()}})
    return name
