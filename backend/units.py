"""One spelling per time unit (#265) — the single definition.

"hours", "Hours", "hrs" and "h" are one unit, but saved models, diagrams, the
samples and agents over MCP spell it every way. :func:`normalize_unit` gives
the comparable form ("hour"); :func:`canonical_unit` gives the one spelling a
known unit is stored and shown in — the app's unit pickers' ("Hours",
"Months", "Cycles", …: ColumnMapper/Units/RecurrentColumnMapper COMMON_UNITS,
RbdBuilder TIME_UNITS); anything else is kept as typed (trimmed), and a blank
unit stays blank. :func:`unit_in_text` is the form for running text ("in
hours", "per month"), so a sentence never reads "in Hours".

Models, datasets, fleets and the RBD analysis (``rbd_analysis``, ``rbds``,
``rbd_maintenance``, ``rbd_intervals``) all import from here; don't copy
these tables elsewhere.
"""

from __future__ import annotations

from typing import Optional

# Spellings of the same time unit, so "Hours", "hrs" and "h" compare equal.
UNIT_ALIASES = {
    "h": "hour", "hr": "hour", "hrs": "hour", "hours": "hour",
    "s": "second", "sec": "second", "secs": "second", "seconds": "second",
    "min": "minute", "mins": "minute", "minutes": "minute",
    "d": "day", "days": "day",
    "wk": "week", "wks": "week", "weeks": "week",
    "mo": "month", "mon": "month", "mth": "month", "mths": "month", "months": "month",
    "y": "year", "yr": "year", "yrs": "year", "years": "year",
    "cycles": "cycle", "kms": "km", "kilometre": "km", "kilometres": "km",
    "kilometer": "km", "kilometers": "km", "miles": "mile", "mi": "mile",
    "operations": "operation", "ops": "operation", "rounds": "round",
}

# The one spelling a known unit is stored and shown in: the app's pickers'.
CANONICAL_UNITS = {
    "second": "Seconds", "minute": "Minutes", "hour": "Hours", "day": "Days", "week": "Weeks",
    "month": "Months", "year": "Years", "cycle": "Cycles", "km": "Kilometres", "mile": "Miles",
    "operation": "Operations", "round": "Rounds",
}

_BLANK = ("-", "unit", "units", "unspecified", "none", "n/a")


def normalize_unit(unit) -> Optional[str]:
    """A comparable form of a time unit ("hour"), or None when it is blank or
    unspecified (unknown — never treated as a mismatch)."""
    key = str(unit or "").strip().lower().rstrip(".")
    if not key or key in _BLANK:
        return None
    return UNIT_ALIASES.get(key, key)


def canonical_unit(unit) -> str:
    """A time unit in its one stored and shown spelling: a known unit as the
    app's unit picker spells it ("hours", "hrs", "h" → "Hours"; "km" →
    "Kilometres"), anything else as typed (trimmed), blank as blank."""
    text = str(unit or "").strip()
    key = normalize_unit(text)
    return CANONICAL_UNITS.get(key, text) if key else text


def unit_in_text(unit) -> str:
    """A unit for running text — notes, verdicts, summaries, warnings: a
    known unit lower-case ("median life 77 hours", "fitted in months"),
    anything else as given (a typed "kWh" or "Flights" is left alone); blank
    as blank. Labels, headers and the ``unit`` field stay canonical."""
    text = str(unit or "").strip()
    return text.lower() if normalize_unit(text) in CANONICAL_UNITS else text


def canonical_results_unit(results):
    """Saved results with their ``unit`` in the canonical spelling (a read
    of a model saved before #265 shows "Hours", not "hours"). Anything that
    isn't a dict, or has no unit, comes back as it is."""
    if not isinstance(results, dict) or not isinstance(results.get("unit"), str):
        return results
    unit = canonical_unit(results["unit"])
    return results if unit == results["unit"] else {**results, "unit": unit}


def clean_label_unit(unit) -> str:
    """A stress or covariate unit ("K", "V", "°C", "kN"): trimmed and capped,
    case kept (K and k are different units); blank when not given."""
    return str(unit or "").strip()[:24]
