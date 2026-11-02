"""A workspace's currency symbol: what the app puts in front of costs.

Costs in Reliafy are plain numbers in whatever currency the user works in;
there's no conversion and no multi-currency. The symbol only labels them
("$255 a year", "€1,200"), so a cost never reads as a bare number. The
personal workspace's is on the user's profile (``users.currency_symbol``), a
team's on the team (``teams.currency_symbol``, set by its owner). Unset is
``"$"``.
"""

from __future__ import annotations

DEFAULT = "$"
MAX_LEN = 4


class BadCurrency(ValueError):
    """Not a symbol the app can show (HTTP 422)."""


def clean(value) -> str | None:
    """A symbol as stored: 1–4 visible characters ("$", "€", "A$", "AUD"), or
    None to clear it (the default, "$")."""
    if value is None:
        return None
    if not isinstance(value, str):
        raise BadCurrency("The currency symbol is a short text like $, € or AUD.")
    text = value.strip()
    if not text:
        return None
    if len(text) > MAX_LEN or any(not ch.isprintable() or ch.isspace() or ch in "<>\"'`" for ch in text):
        raise BadCurrency("Use a currency symbol of up to 4 characters, like $, €, £ or AUD.")
    return text


def symbol(stored) -> str:
    """The symbol to show: the stored one if usable, else the default."""
    try:
        return clean(stored) or DEFAULT
    except BadCurrency:
        return DEFAULT


def of_owner(db, owner: str | None) -> str:
    """The currency symbol of the workspace an ``owner_id`` names: a team's
    (``team:<id>``), else that user's."""
    if not owner or not isinstance(owner, str):
        return DEFAULT
    if owner.startswith("team:"):
        doc = db.teams.find_one({"_id": owner[len("team:"):]}, {"currency_symbol": 1})
    else:
        doc = db.users.find_one({"_id": owner}, {"currency_symbol": 1})
    return symbol((doc or {}).get("currency_symbol"))


def set_personal(db, uid: str, value) -> str:
    """Set (or clear, with None or "") the personal workspace's symbol."""
    name = clean(value)
    db.users.update_one({"_id": uid}, {"$set": {"currency_symbol": name}})
    return name or DEFAULT


def set_team(db, team_id: str, value) -> str:
    """Set (or clear) a team workspace's symbol. The caller checks who may."""
    name = clean(value)
    db.teams.update_one({"_id": team_id}, {"$set": {"currency_symbol": name}})
    return name or DEFAULT
