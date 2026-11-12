"""A dataset's modelling reading: which column is which, kept with the
dataset from upload, so building a model from it asks nothing about columns.

The reading names a column (or "") for each role SurPyval takes, and the
covariates:

    x     the value when a unit failed or was removed (hours, cycles, km…)
    xl/xr where x is blank, the range it lies in (read per row)
    c     failed or still running (0 = failed, 1 = still running, -1, 2)
    n     how many units a row stands for
    tl/tr observed only from / up to this value (truncation)
    i     which item each row belongs to
    m     a measured value (readings)
    e     the failure mode (the state entered, for multi-state data)
    s     the state the unit was in during the row (the from-state of
          multi-state data; unmapped, rows start from the one working state).
          Kept and shown only: no model in the app reads it yet.
    u     a column giving each row's time unit (converted to ``unit``)

plus ``c_invert`` / ``c_map`` (what the status values mean), ``all_failed``
(no status column: every row is a failure, said on purpose), ``unit`` (x's),
``m_unit``, ``z`` (the covariates: every column not used as something else,
less the ``not_used`` ones), ``z_units`` ({column: unit}, optional) and
``not_used``.

Each model kind takes what it needs from the reading (a plain life model
ignores z, a regression offers it). Models keep a copy of the reading they
were fitted with (``snapshot``) beside their own mapping, so a refit is
reproducible whatever the dataset's reading becomes later.

A dataset saved before readings existed is never rewritten: on read it is
given one from its newest model's mapping, or from ``guess`` (``for_dataset``),
and says which.

``guess`` reads the column facts of ``fitting.preview(distinct=True)`` and
follows the app's own first guess (frontend/src/lifeData.js ``guessMapping``
and frontend/src/datasetReading.js), so a reading guessed over the API is the
one the upload screen would have shown. The shared cases are in
frontend/src/readingGuessCases.json, checked by both test suites.
"""

from __future__ import annotations

import re
from typing import Any

from backend.services import datasets as datasets_service

ROLES = ("x", "xl", "xr", "c", "n", "tl", "tr", "i", "m", "e", "s", "u")
#: The roles in the order the summary line and the upload screen give them.
SHOWN = ("x", "c", "n", "tl", "tr", "i", "m", "e", "s")
SOURCES = ("saved", "last_model", "guessed")
_NAMES = {"e": "failure mode"}


class ReadingError(ValueError):
    """A reading that can't be kept, in words for the user."""


def empty() -> dict:
    return {**{r: "" for r in ROLES}, "c_invert": False, "c_map": None, "all_failed": False, "unit": "",
            "m_unit": "", "z": [], "z_units": {}, "not_used": []}


def _names(columns) -> list[str]:
    return [c.get("name") if isinstance(c, dict) else str(c) for c in columns or []]


def normalize_measurements(raw: dict | None, columns) -> dict | None:
    """The measurements part's reading (readings on the units: i, x the age,
    m the value, with x's and m's units), checked against its columns."""
    if not raw:
        return None
    names = _names(columns)
    out = {}
    for role in ("i", "x", "m"):
        col = str(raw.get(role) or "").strip()
        if col and col not in names:
            raise ReadingError(f"The measurements' {role} names “{col}”, which isn't one of their columns. "
                               f"Their columns: {', '.join(names)}.")
        out[role] = col
    if len({c for c in out.values() if c}) < len([c for c in out.values() if c]):
        raise ReadingError("A column of the measurements can have one role only.")
    out["unit"] = str(raw.get("unit") or "").strip()[:40]
    out["m_unit"] = str(raw.get("m_unit") or "").strip()[:40]
    return out


def normalize(raw: dict | None, columns, *, require_x: bool = True, measurement_columns=None) -> dict:
    """A reading checked against the dataset's ``columns``: every role names
    one of them (or nothing), no column takes two roles, and x (or its range)
    is there. Unknown keys are dropped. Raises ReadingError in plain words."""
    names = _names(columns)
    have = set(names)
    raw = dict(raw or {})
    out = empty()
    for role in ROLES:
        col = str(raw.get(role) or "").strip()
        if col and col not in have:
            label = _NAMES.get(role, role)
            raise ReadingError(f"{label} names “{col}”, which isn't a column of this dataset. "
                               f"Its columns: {', '.join(names)}.")
        out[role] = col
    taken: dict[str, str] = {}
    for role in ROLES:
        col = out[role]
        if not col:
            continue
        if col in taken:
            raise ReadingError(f"“{col}” is both {_NAMES.get(taken[col], taken[col])} and {_NAMES.get(role, role)}: "
                               "a column can have one role only.")
        taken[col] = role
    if bool(out["xl"]) != bool(out["xr"]):
        raise ReadingError("Give both ends of the range (xl and xr), or neither.")
    if require_x and not (out["x"] or out["xl"]):
        raise ReadingError("Say which column holds x: the value when each unit failed or was removed (hours, "
                           "cycles, km…). Every model is built on it.")
    out["c_invert"] = bool(raw.get("c_invert")) and bool(out["c"])
    c_map = raw.get("c_map") if out["c"] else None
    if c_map:
        if not isinstance(c_map, dict):
            raise ReadingError("c_map (what each status value means) must be an object such as "
                               "{\"Failed\": 0, \"Running\": 1}.")
        bad = [k for k, v in c_map.items() if _code(v) is None]
        if bad:
            raise ReadingError(f"c_map gives “{bad[0]}” a meaning other than 0 (failed), 1 (still running), "
                               "-1 (failed before) or 2 (interval).")
        out["c_map"] = {str(k): _code(v) for k, v in c_map.items()}
        out["c_invert"] = False
    out["all_failed"] = bool(raw.get("all_failed")) and not out["c"]
    out["unit"] = str(raw.get("unit") or "").strip()[:40]
    out["m_unit"] = str(raw.get("m_unit") or "").strip()[:40] if out["m"] else ""
    z = _column_list(raw.get("z"), have, "z")
    clash = [c for c in z if c in taken]
    if clash:
        raise ReadingError(f"“{clash[0]}” is {_NAMES.get(taken[clash[0]], taken[clash[0]])}, so it can't also be a "
                           "covariate (Z).")
    out["z"] = z
    units = raw.get("z_units") or {}
    if not isinstance(units, dict):
        raise ReadingError("z_units must be an object of covariate → unit, such as {\"Load\": \"kN\"}.")
    out["z_units"] = {c: str(u).strip()[:40] for c, u in units.items() if c in z and str(u or "").strip()}
    out["not_used"] = [c for c in _column_list(raw.get("not_used"), have, "not_used") if c not in taken and c not in z]
    if measurement_columns is not None and raw.get("measurements"):
        out["measurements"] = normalize_measurements(raw["measurements"], measurement_columns)
    return out


def _code(v) -> int | None:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return int(f) if f in (0, 1, -1, 2) else None


def _column_list(value, have: set, what: str) -> list[str]:
    if value in (None, ""):
        return []
    if isinstance(value, str):
        value = [value]
    out: list[str] = []
    for c in value:
        col = str(c or "").strip()
        if not col:
            continue
        if col not in have:
            raise ReadingError(f"{what} names “{col}”, which isn't a column of this dataset.")
        if col not in out:
            out.append(col)
    return out


def drop_column(reading: dict | None, column: str) -> dict | None:
    """The reading without ``column`` (a split's dataset column, left out of
    every part): its role cleared, out of Z and not used."""
    if not reading:
        return reading
    out = {**reading}
    for role in ROLES:
        if out.get(role) == column:
            out[role] = ""
    out["z"] = [c for c in out.get("z") or [] if c != column]
    out["z_units"] = {k: v for k, v in (out.get("z_units") or {}).items() if k != column}
    out["not_used"] = [c for c in out.get("not_used") or [] if c != column]
    return out


# ---- The guess: the app's own first reading of a sheet ------------------------

def _words(name) -> str:
    return re.sub(r"[_\-./()\[\]#:]+", " ", re.sub(r"([a-z])([A-Z])", r"\1 \2", str(name or ""))).strip()


_TIME_WORDS = re.compile(
    r"\b(hours?|hrs?|hr|time|times|age|cycles?|km|kms|kilomet(?:re|er)s?|miles?|mileage|odometer|days?|weeks?"
    r"|months?|years?|minutes?|mins?|starts?|operations?|landings?|shots?|runtime|duration|life|ttf|tbf|mtbf)\b",
    re.IGNORECASE)
_STATUS_WORDS = re.compile(
    r"\b(status|state|fail|failed|failure|failures|censor|censored|censoring|cens|event|events|suspend|suspended"
    r"|suspension|suspensions|running|outcome|survived|alive|dead)\b", re.IGNORECASE)
_NOT_STATUS = re.compile(
    r"\b(mode|modes|cause|causes|type|code|description|desc|reason|date|time|hours?|comment|comments|notes?)\b",
    re.IGNORECASE)
_ID_WORDS = re.compile(r"\b(id|ids|no|number|serial|sn|s n|tag|asset|unit|item|equipment|code|row|index)\b",
                       re.IGNORECASE)
_CENSOR_WORDS = re.compile(r"\b(censor|censored|censoring|cens)\b", re.IGNORECASE)
_CENSOR_RE = re.compile(r"^(c|cens|censor|censored|censoring|status|fail|failed|failure|failures|event|suspended"
                        r"|suspension|running)$", re.IGNORECASE)
_COUNT_NAMES = re.compile(r"^(n|count|counts|qty|quantity|units|number of units)$", re.IGNORECASE)
_LATE_ENTRY = re.compile(r"\b(entered|entry|enters|observed from|observation start|left truncat\w*|truncat\w*|tl)\b",
                         re.IGNORECASE)
_EARLIEST = re.compile(r"\b(xl|last ok|last good|passed|earliest|shortest|lower|left)\b", re.IGNORECASE)
_LATEST = re.compile(r"\b(xr|found failed|found|failed|latest|longest|upper|right)\b", re.IGNORECASE)
_MODE = re.compile(r"\b(mode|modes|cause|causes)\b", re.IGNORECASE)
_UNIT_NAMES = [
    (re.compile(r"\b(hours?|hrs?|hr|h)\b", re.I), "Hours"), (re.compile(r"\b(days?)\b", re.I), "Days"),
    (re.compile(r"\b(weeks?)\b", re.I), "Weeks"), (re.compile(r"\b(months?)\b", re.I), "Months"),
    (re.compile(r"\b(years?|yrs?)\b", re.I), "Years"), (re.compile(r"\b(cycles?)\b", re.I), "Cycles"),
    (re.compile(r"\b(km|kms|kilomet(?:re|er)s?)\b", re.I), "Kilometres"),
    (re.compile(r"\b(miles?|mileage)\b", re.I), "Miles"), (re.compile(r"\b(minutes?|mins?)\b", re.I), "Minutes"),
    (re.compile(r"\b(operations?)\b", re.I), "Operations"), (re.compile(r"\b(starts?)\b", re.I), "Starts"),
    (re.compile(r"\b(landings?)\b", re.I), "Landings"),
]
_CONVERTIBLE = ("Minutes", "Hours", "Days", "Weeks", "Months", "Years")
_SHORT_UNITS = {"d": "Days", "wk": "Weeks", "wks": "Weeks", "w": "Weeks", "mo": "Months", "mth": "Months",
                "mths": "Months", "y": "Years"}
# An item: the unit, pump or asset each row belongs to. Specific names first,
# a bare "ID" last (a row number as often as an item).
_ITEM_NAMES = re.compile(r"\b(tag|serial|sn|asset|equipment|unit|item|pump|motor|machine|vehicle|truck|engine"
                         r"|compressor|component|system|subject|specimen|sample|pad|position)\b", re.IGNORECASE)
# A class, site or make is a covariate, never the item, however it repeats.
_CATEGORY = re.compile(r"\b(class|classes|family|families|type|types|category|group|site|location|area|make|model"
                       r"|supplier|vendor|manufacturer|kind|service|duty)\b", re.IGNORECASE)
_BARE_ID = re.compile(r"\b(id|ids|no|number)\b", re.IGNORECASE)
_VALUE_NAMES = re.compile(r"\b(value|reading|readings|measure|measured|measurement|marker|vib|vibration|wear"
                          r"|thickness|depth|crack|debris|level|degradation|y)\b", re.IGNORECASE)
_FREE_TEXT_NAMES = re.compile(r"\b(notes?|remarks?|comments?|description|desc|details?|narrative|text)\b",
                              re.IGNORECASE)
_DATE_NAMES = re.compile(r"\b(date|dated|dates|timestamp|datetime|when|commissioned|installed on)\b", re.IGNORECASE)
_END_NAMES = re.compile(
    r"^(tr|t end)$|\b(observed to|observed until|observation end|end of (record|records|observation|test|trial"
    r"|history|data)|records? end|record end|records? to|trial end|test end|window end|last seen"
    r"|censor(ed)? (time|at)|cutoff|cut off|horizon)\b", re.IGNORECASE)
_STATUS_NAMES = re.compile(r"\b(status|state|fail|failed|failure|failures|censor|censored|censoring|cens|event"
                           r"|events|suspend|suspended|suspension|running|survived|alive|dead)\b", re.IGNORECASE)
_TIME_UNIT_VALUES = re.compile(r"^(min|mins|minutes?|h|hr|hrs|hours?|d|days?|wk|wks|w|weeks?|mo|mth|mths|months?"
                               r"|y|yr|yrs|years?)\.?$", re.IGNORECASE)
# Start and stop rows of items (tvcData.js): an item that repeats, a start and a stop column.
_TVC_ID = re.compile(r"\b(id|ids|item|unit|serial|sn|asset|tag|equipment|pump|motor|machine|vehicle|truck|engine"
                     r"|subject|system|no|number)\b")
_TVC_START = re.compile(r"\b(start|starts|from|begin|begins|entry|t0|tstart|xl)\b")
_TVC_STOP = re.compile(r"\b(stop|stops|end|ends|until|exit|t1|tstop|xr)\b|^to$")
_DATE_VALUE = re.compile(r"^\d{4}-\d{1,2}-\d{1,2}([ T]\d{1,2}:\d{2}.*)?$|^\d{1,2}[/.-]\d{1,2}[/.-]\d{2,4}$")


def guess_unit(name) -> str:
    w = _words(name)
    for rx, unit in _UNIT_NAMES:
        if rx.search(w):
            return unit
    return ""


def _time_unit_of(value) -> str:
    v = str(value if value is not None else "").strip().lower().rstrip(".")
    u = _SHORT_UNITS.get(v) or (guess_unit(v) if v else "")
    return u if u in _CONVERTIBLE and (v in _SHORT_UNITS or len(_words(v).split(" ")) == 1) else ""


def _numeric(dtype) -> bool:
    return bool(re.search(r"int|float", str(dtype or "")))


def facts_of(preview: dict) -> tuple[list[str], dict, int]:
    """``fitting.preview(distinct=True)``'s lists as {column: facts}."""
    columns = [str(c) for c in preview.get("columns") or []]
    n_rows = int(preview.get("n_rows") or 0) - int(preview.get("blank_rows") or 0)

    def at(key, i, default=None):
        values = preview.get(key)
        return values[i] if values is not None and i < len(values) else default

    facts = {c: {"name": c, "dtype": at("dtypes", i, "object"), "blanks": at("blanks", i, 0) or 0,
                 "values": at("values", i), "n_unique": at("n_unique", i), "whole": at("whole", i),
                 "sample": next((r[i] for r in preview.get("preview") or [] if i < len(r)
                                 and r[i] not in (None, "")), None)}
             for i, c in enumerate(columns)}
    return columns, facts, n_rows


def _status_meaning(value, column: str) -> int | None:
    """frontend ``guessStatusMeaning``: 0 failed, 1 still running, -1, 2, or None."""
    v = str(value if value is not None else "").strip()
    try:
        num = float(v) if v else None
    except ValueError:
        num = None
    if num in (0, 1):
        return int(1 - num) if datasets_service.one_means_failed(column) else int(num)
    if num in (-1, 2):
        return int(num)
    return datasets_service.status_code(v, column)


def _status_key(value) -> str:
    v = str(value if value is not None else "").strip()
    try:
        f = float(v)
        if f == int(f):
            return str(int(f))
    except ValueError:
        pass
    return v.lower()


def guess_status(column: str, facts: dict) -> dict:
    """frontend ``guessStatus`` + ``encodeStatus``: ``{c_invert, c_map}``."""
    if not column:
        return {"c_invert": False, "c_map": None}
    merged: dict[str, str] = {}
    for label in (facts.get(column, {}).get("values") or {}):
        merged.setdefault(_status_key(label), label)
    if not merged:
        return {"c_invert": False, "c_map": None}
    choices = [(label, _status_meaning(label, column)) for label in merged.values()]
    keys = {_status_key(label): m for label, m in choices}
    if all(k in ("0", "1", "-1", "2") for k in keys):
        fixed = all(k not in ("-1", "2") or m == int(k) for k, m in keys.items())
        zero, one = keys.get("0", "none"), keys.get("1", "none")
        if fixed and zero in ("none", 0) and one in ("none", 1):
            return {"c_invert": False, "c_map": None}
        if fixed and zero in ("none", 1) and one in ("none", 0):
            return {"c_invert": True, "c_map": None}
    return {"c_invert": False, "c_map": {label: m for label, m in choices if m is not None}}


def _looks_like_status(f: dict) -> bool:
    values = f.get("values")
    if not values:
        return False
    keys = list(values)
    if _numeric(f.get("dtype")):
        return all(str(v) in ("0", "1", "-1", "2") for v in keys)
    known = sum(1 for v in keys if _status_meaning(v, f["name"]) is not None)
    return known * 2 >= len(keys)


def _life_columns(cols: list[dict]) -> dict:
    """frontend ``guessLifeColumns``: x, c, n and x's unit."""
    status = (next((c for c in cols if _STATUS_WORDS.search(_words(c["name"]))
                    and not _NOT_STATUS.search(_words(c["name"])) and _looks_like_status(c)), None)
              or next((c for c in cols if _CENSOR_RE.match(str(c["name"]).strip()) and _looks_like_status(c)), None)
              or next((c for c in cols if _CENSOR_WORDS.search(_words(c["name"])) and _numeric(c.get("dtype"))
                       and _looks_like_status(c)), None))
    c = status["name"] if status else ""
    count = next((col for col in cols if col["name"] != c and _numeric(col.get("dtype")) and col.get("whole") is not False
                  and _COUNT_NAMES.match(str(col["name"]).strip())), None)
    n = count["name"] if count else ""
    numeric = [col for col in cols if _numeric(col.get("dtype")) and col["name"] not in (c, n)
               and not _LATE_ENTRY.search(_words(col["name"]))]
    x = (next((col for col in numeric if _TIME_WORDS.search(_words(col["name"])) and guess_unit(col["name"])), None)
         or next((col for col in numeric if _TIME_WORDS.search(_words(col["name"]))), None)
         or next((col for col in numeric if not _ID_WORDS.search(_words(col["name"]))), None)
         or (numeric[0] if numeric else None))
    return {"x": x["name"] if x else "", "c": c, "n": n, "unit": guess_unit(x["name"]) if x else ""}


def _interval_pair(cols: list[dict], exclude: list[str]) -> dict | None:
    numeric = [c for c in cols if _numeric(c.get("dtype")) and c["name"] not in exclude]
    for a in numeric:
        if not _EARLIEST.search(_words(a["name"])):
            continue
        b = next((col for col in numeric if col is not a and _LATEST.search(_words(col["name"]))
                  and not _EARLIEST.search(_words(col["name"]))), None)
        if b:
            return {"xl": a["name"], "xr": b["name"]}
    return None


def _unit_column(cols: list[dict], exclude: list[str]) -> dict | None:
    for c in cols:
        if c["name"] in exclude or _numeric(c.get("dtype")) or not c.get("values"):
            continue
        entries = [(v, n) for v, n in c["values"].items() if str(v).strip()]
        if not entries or any(not _time_unit_of(v) for v, _ in entries):
            continue
        counts: dict[str, int] = {}
        for v, n in entries:
            counts[_time_unit_of(v)] = counts.get(_time_unit_of(v), 0) + n
        if len(counts) < 2:
            continue
        return {"column": c["name"], "common": max(counts.items(), key=lambda kv: kv[1])[0]}
    return None


def _item_column(cols: list[dict], n_rows: int, used: set) -> str:
    """The item each row belongs to: a column named like one (a tag, serial,
    asset; a bare "ID" last), preferring one whose values repeat (several rows
    per item). Text or whole numbers only."""
    pool = [c for c in cols if c["name"] not in used and not _CATEGORY.search(_words(c["name"]))
            and (not _numeric(c.get("dtype")) or c.get("whole") is not False)]
    named = [c for c in pool if _ITEM_NAMES.search(_words(c["name"]))]
    bare = [c for c in pool if _BARE_ID.search(_words(c["name"])) and c not in named]

    def repeats(c):
        return c.get("n_unique") is not None and n_rows and 1 < c["n_unique"] < n_rows

    for group in (named, bare):
        hit = next((c for c in group if repeats(c)), None)
        if hit:
            return hit["name"]
    many = next((c for c in pool if not _numeric(c.get("dtype")) and repeats(c) and c.get("values") is None), None)
    hit = named[0] if named else bare[0] if bare else many
    return hit["name"] if hit else ""


def _tvc_words(name) -> str:
    return re.sub(r"[_\-.]+", " ", re.sub(r"([a-z])([A-Z])", r"\1 \2", str(name or ""))).lower()


def _tvc(columns: list[str], facts: dict, n_rows: int) -> dict | None:
    """tvcData.js ``guessTvc``: an item that repeats, a numeric start and stop column."""
    numeric = [c for c in columns if _numeric(facts[c].get("dtype"))]
    start = next((c for c in numeric if _TVC_START.search(_tvc_words(c))), None)
    stop = next((c for c in numeric if c != start and _TVC_STOP.search(_tvc_words(c))), None)

    def repeats(c):
        nu = facts[c].get("n_unique")
        return nu is not None and n_rows and nu < n_rows

    item = (next((c for c in columns if _TVC_ID.search(_tvc_words(c)) and repeats(c)), None)
            or next((c for c in columns if not _numeric(facts[c].get("dtype")) and repeats(c)
                     and facts[c].get("values") is None), None))
    if not start or not stop or not item:
        return None
    unit = guess_unit(_TVC_STOP.sub(" ", _TVC_START.sub(" ", _tvc_words(stop)))) or guess_unit(
        _TVC_STOP.sub(" ", _TVC_START.sub(" ", _tvc_words(start))))
    return {"i": item, "xl": start, "xr": stop, "unit": unit}


def not_used_reason(f: dict, n_rows: int) -> str | None:
    """Why a column left over isn't offered as a covariate by default ("one
    value", "a date", "an id", "free text"), or None: it's a covariate. The
    user can include any of them with one tap."""
    name = str(f.get("name") or "")
    words = _words(name)
    nu = f.get("n_unique")
    if nu is not None and nu <= 1:
        return "one value"
    dtype = str(f.get("dtype") or "")
    sample = f.get("sample")
    if re.search(r"date|time", dtype) or (_DATE_NAMES.search(words) and not _numeric(dtype)) or (
            not _numeric(dtype) and sample is not None and _DATE_VALUE.match(str(sample).strip())):
        return "a date"
    if ((_ITEM_NAMES.search(words) or _BARE_ID.search(words)) and not _CATEGORY.search(words)) or (
            not _numeric(dtype) and nu is not None and n_rows > 1 and nu >= n_rows):
        return "an id"
    if not _numeric(dtype) and (_FREE_TEXT_NAMES.search(words) or (
            nu is not None and n_rows >= 6 and nu * 2 > n_rows)):
        return "free text"
    vals = [str(v) for v in (f.get("values") or {}) if str(v).strip()]
    if _STATUS_NAMES.search(words) and not _MODE.search(words) and vals and all(v in ("0", "1", "-1", "2")
                                                                                for v in vals):
        return "a status"
    if _MODE.search(words) and not _numeric(dtype):
        return "a failure mode"
    if not _numeric(dtype) and vals and all(_TIME_UNIT_VALUES.match(v.strip()) for v in vals):
        return "units"
    return None


def default_z(columns: list[str], facts: dict, used, n_rows: int) -> tuple[list[str], list[str]]:
    """Z (every column not used as something else) and not used (the guarded
    ones: ``not_used_reason``)."""
    z, off = [], []
    for c in columns:
        if c in used:
            continue
        (off if not_used_reason(facts.get(c) or {"name": c}, n_rows) else z).append(c)
    return z, off


def guess(preview: dict) -> dict:
    """The app's first reading of a sheet (``fitting.preview(distinct=True)``):
    the life roles as frontend lifeData ``guessMapping`` makes them, an item
    column, a readings column for a table of readings, and Z by default."""
    columns, facts, n_rows = facts_of(preview)
    cols = [facts[c] for c in columns]
    g = _life_columns(cols)
    pair = _interval_pair(cols, [v for v in (g["c"], g["n"]) if v])
    times = {"x": "", **pair} if pair else {"x": g["x"]}
    # A column of per-row units belongs to another time column when x names its own unit.
    anothers = bool(g["x"] and guess_unit(g["x"])) and any(
        c["name"] != g["x"] and _numeric(c.get("dtype")) and _TIME_WORDS.search(_words(c["name"]))
        and not guess_unit(c["name"]) for c in cols)
    mixed = None if pair or anothers else _unit_column(cols, [v for v in (g["c"], g["n"], g["x"]) if v])
    mode = ""
    if not pair and g["c"]:
        mode = next((c["name"] for c in cols if _MODE.search(_words(c["name"])) and not _numeric(c.get("dtype"))
                     and c["name"] not in (g["c"], g["n"], g["x"])), "")
    tl = "" if mode else next((c["name"] for c in cols if _numeric(c.get("dtype")) and c["name"] not in
                               (g["c"], g["n"], times.get("x"), times.get("xl"), times.get("xr"))
                               and _LATE_ENTRY.search(_words(c["name"]))), "")
    out = empty()
    out.update(times)
    out.update({"c": g["c"], "n": g["n"], "e": mode, "u": mixed["column"] if mixed else "", "tl": tl,
                **guess_status(g["c"], facts)})
    out["unit"] = mixed["common"] if mixed else (guess_unit(pair["xl"]) or guess_unit(pair["xr"])) if pair else g["unit"]
    tvc = _tvc(columns, facts, n_rows)
    if tvc:
        out.update({"i": tvc["i"], "x": "", "xl": tvc["xl"], "xr": tvc["xr"], "n": "", "tl": "", "tr": "", "e": "",
                    "u": ""})
        out["unit"] = tvc["unit"] or out["unit"]
    used = {v for k, v in out.items() if k in ROLES and v}
    if not out["i"]:
        out["i"] = _item_column(cols, n_rows, used)
    if out["i"]:
        used.add(out["i"])
    reps = facts.get(out["i"], {}).get("n_unique")
    repeated = bool(out["i"]) and reps is not None and reps < n_rows
    if not tvc and not out["tr"]:
        out["tr"] = next((c["name"] for c in cols if c["name"] not in used and _numeric(c.get("dtype"))
                          and _END_NAMES.search(_words(c["name"]))), "")
        if out["tr"]:
            used.add(out["tr"])
    if not out["e"] and repeated:
        out["e"] = next((c["name"] for c in cols if c["name"] not in used and not _numeric(c.get("dtype"))
                         and _MODE.search(_words(c["name"]))), "")
        if out["e"]:
            used.add(out["e"])
    # A table of readings (an item measured again and again, no status): the measured value.
    if out["i"] and not out["c"] and reps is not None and reps < n_rows:
        m = next((c["name"] for c in cols if c["name"] not in used and _numeric(c.get("dtype"))
                  and _VALUE_NAMES.search(_words(c["name"]))), "")
        if m:
            out["m"] = m
            used.add(m)
    out["z"], out["not_used"] = default_z(columns, facts, used, n_rows)
    return out


def last_model_mapping(models: list, columns) -> dict | None:
    """How the newest model fitted from a dataset read its columns:
    ``{mapping, options, unit, model_name}``, or None. Only a mapping whose
    columns are all still in the dataset counts; options are the status
    reading only."""
    names = set(_names(columns))
    for m in models:
        spec = m.spec or {}
        mapping = {k: v for k, v in (spec.get("mapping") or {}).items() if v}
        if not (mapping.get("x") or mapping.get("xl")) or not set(mapping.values()) <= names:
            continue
        opts = spec.get("options") or {}
        return {"mapping": mapping, "unit": spec.get("unit") or (m.results or {}).get("unit") or "",
                "options": {k: opts[k] for k in ("c_map", "c_invert") if opts.get(k)},
                "model_name": m.name}
    return None


def for_dataset_db(db, dataset, owners, hidden=frozenset()) -> tuple[dict, str]:
    """``for_dataset`` with the dataset's newest model looked up."""
    models = datasets_service.models_for_dataset(db, dataset.id, owners, hidden) if not getattr(
        dataset, "reading", None) else []
    return for_dataset(dataset, last_model_mapping(models, dataset.columns))


def merged(base: dict, given: dict) -> dict:
    """``base`` (a guess, or the dataset's reading) with the roles and fields
    ``given`` names put over it: a column given a role leaves any other role
    the base gave it, and Z and not used."""
    out = {**empty(), **(base or {})}
    out.pop("guessed", None)
    for role in ROLES:
        if role not in given:
            continue
        col = given[role] or ""
        for other in ROLES:
            if col and other != role and out.get(other) == col:
                out[other] = ""
        out[role] = col
        if role == "c":
            out["c_invert"], out["c_map"] = False, None
    taken = {out[r] for r in ROLES if out.get(r)}
    for key in ("c_invert", "c_map", "all_failed", "unit", "m_unit", "z_units"):
        if key in given:
            out[key] = given[key]
    if "z" in given:
        out["z"] = list(given["z"] or [])
        out["not_used"] = [c for c in out.get("not_used") or [] if c not in out["z"]]
    if "not_used" in given:
        out["not_used"] = list(given["not_used"] or [])
        out["z"] = [c for c in out.get("z") or [] if c not in out["not_used"]]
    out["z"] = [c for c in out.get("z") or [] if c not in taken]
    out["not_used"] = [c for c in out.get("not_used") or [] if c not in taken]
    return out


def from_last_mapping(last: dict, columns: list[str], facts: dict, n_rows: int) -> dict:
    """A reading from the newest model's mapping (``last_mapping``): its roles,
    status meanings and unit; Z by default from what is left."""
    out = empty()
    mapping = last.get("mapping") or {}
    for role in ROLES:
        if mapping.get(role):
            out[role] = mapping[role]
    opts = last.get("options") or {}
    out["c_invert"] = bool(opts.get("c_invert"))
    out["c_map"] = opts.get("c_map") or None
    out["unit"] = last.get("unit") or ""
    used = {v for k, v in out.items() if k in ROLES and v}
    out["z"], out["not_used"] = default_z(columns, facts, used, n_rows)
    return out


def for_dataset(dataset, last_mapping: dict | None = None, preview: dict | None = None) -> tuple[dict, str]:
    """``(reading, source)``: the dataset's saved reading ("saved"), else one
    from its newest model ("last_model"), else the guess ("guessed"). The
    stored document is never changed here."""
    reading, source = _main_reading(dataset, last_mapping, preview)
    part = getattr(dataset, "measurements", None)
    if part is not None:
        kept = (getattr(dataset, "reading", None) or {}).get("measurements")
        sub = None
        if kept:
            try:
                sub = {**normalize_measurements(kept, part.columns), "source": "saved"}
            except ReadingError:
                sub = None
        if sub is None:
            try:
                g = guess(datasets_service.preview_measurements(dataset, distinct=True) or {})
                sub = {"i": g["i"], "x": g["x"] or g["xl"], "m": g["m"], "unit": g["unit"], "m_unit": "",
                       "source": "guessed"}
            except Exception:  # noqa: BLE001 - a part that can't be read has no reading
                sub = None
        if sub:
            reading = {**reading, "measurements": sub}
    return reading, source


def _main_reading(dataset, last_mapping, preview) -> tuple[dict, str]:
    names = _names(dataset.columns)
    stored = getattr(dataset, "reading", None)
    if stored:
        try:
            # A reading guessed over the API is kept, but still says "check it".
            return normalize(stored, names, require_x=False), "guessed" if stored.get("guessed") else "saved"
        except ReadingError:
            pass  # a reading naming columns the data no longer has: read afresh
    if preview is None:
        preview = datasets_service.preview_rows(dataset, distinct=True)
    if last_mapping:
        columns, facts, n_rows = facts_of(preview)
        return from_last_mapping(last_mapping, columns, facts, n_rows), "last_model"
    return guess(preview), "guessed"


def guess_for_bytes(csv_bytes: bytes) -> dict:
    from backend import fitting

    return guess(fitting.preview(csv_bytes, distinct=True))


def snapshot(dataset) -> dict | None:
    """The dataset's saved reading, kept in a model's spec when it is fitted
    (``spec["reading"]``): the record of how its columns were read then."""
    stored = getattr(dataset, "reading", None)
    return dict(stored) if stored else None


def with_reading(spec: dict, dataset) -> dict:
    """A model's spec with the reading its dataset had when it was fitted."""
    kept = snapshot(dataset)
    return {**spec, "reading": kept} if kept else spec


def summary(reading: dict) -> str:
    """"x = Age (Hours) · c = Status · i = Tag · failure mode = Mode · Z: Load, Site"."""
    if not reading:
        return ""
    parts = []
    if reading.get("x"):
        unit = f" ({reading['unit']})" if reading.get("unit") else ""
        parts.append(f"x = {reading['x']}{unit}")
    if reading.get("xl"):
        parts.append(f"range = {reading['xl']} to {reading['xr']}")
    if reading.get("c"):
        parts.append(f"c = {reading['c']}")
    elif reading.get("all_failed"):
        parts.append("c: every row failed")
    for role in ("n", "tl", "tr", "i", "m", "e", "s"):
        if reading.get(role):
            unit = f" ({reading['m_unit']})" if role == "m" and reading.get("m_unit") else ""
            parts.append(f"{_NAMES.get(role, role)} = {reading[role]}{unit}")
    z = reading.get("z") or []
    if z:
        parts.append(f"Z: {', '.join(z)}")
    if reading.get("not_used"):
        parts.append(f"not used: {', '.join(reading['not_used'])}")
    return " · ".join(parts)


def life_mapping(reading: dict) -> dict:
    """The life roles of a reading as a fit's mapping and options (MCP fits
    from a dataset with no columns named): ``(mapping, options)``."""
    mapping = {r: reading.get(r) for r in ("x", "xl", "xr", "c", "n", "tl", "tr") if reading.get(r)}
    options: dict[str, Any] = {}
    if reading.get("c_map"):
        options["c_map"] = reading["c_map"]
    elif reading.get("c_invert"):
        options["c_invert"] = True
    if reading.get("u"):
        options["u_col"] = reading["u"]
    return mapping, options
