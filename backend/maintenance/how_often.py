"""How often: the one shape for "how often" a task or a work package falls due.

A task keeps its ``interval`` / ``unit`` (and ``also_interval`` / ``also_unit``,
whichever comes first). For a pattern an interval can't say, it also carries a
``rule``: a weekday every so many weeks, the nth weekday or a day of every so
many months, or the nth weekday or a day of a named month every so many years
(the first Tuesday of November). A work package's cadence (``every``, ``unit``,
``pattern``, ``anchor``) says the same things, so both read into one shape here
and the app edits both with one control.

The shape (saved inside ``task.rule_set`` events; ``version`` lets a later
reader take it unchanged)::

    {"kind": "every",   "every": 2, "unit": "weeks"}
    {"kind": "weekly",  "every": 1, "weekdays": ["Saturday"]}
    {"kind": "monthly", "every": 1, "weekday": "Saturday", "nth": 1}     # or "day": 15
    {"kind": "yearly",  "every": 1, "month": 11, "weekday": "Tuesday", "nth": 1}   # or "day": 1
    (each may carry "anchor": "2026-11-14", the date it counts from, and "version": 1)

The dates come from RePyability's ``Recurrence`` (through ``schedule.Cadence``):
``to_library`` writes a rule as the library saves one and ``from_library`` reads
it back, so a stored rule is never rewritten.
"""

from __future__ import annotations

from datetime import date

from backend.maintenance.schedule import Cadence, Recurrence

RULE_VERSION = 1
RULE_KINDS = ("every", "weekly", "monthly", "yearly")
WEEKDAYS = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")
MONTHS = ("January", "February", "March", "April", "May", "June", "July", "August", "September", "October",
          "November", "December")
UNIT_OF_KIND = {"weekly": "weeks", "monthly": "months", "yearly": "years"}
_ORDINALS = {1: "first", 2: "second", 3: "third", 4: "fourth", 5: "fifth", -1: "last", -2: "second last",
             -3: "third last", -4: "fourth last", -5: "fifth last"}


def _whole(value, name: str, lo: int, hi: int) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        raise ValueError(f"{name} is a whole number, {lo} to {hi}; got {value!r}.")
    try:
        n = float(value)
    except ValueError:
        raise ValueError(f"{name} is a whole number, {lo} to {hi}; got {value!r}.") from None
    if not n.is_integer() or not lo <= n <= hi:
        raise ValueError(f"{name} is a whole number, {lo} to {hi}; got {value!r}.")
    return int(n)


def _weekday(value) -> str:
    name = value.strip().capitalize() if isinstance(value, str) else None
    for day in WEEKDAYS:
        if name and (name == day or (len(name) >= 3 and day.startswith(name))):
            return day
    raise ValueError(f"A weekday is a day of the week, such as 'Saturday'; got {value!r}.")


def check_rule(rule) -> dict:
    """``rule`` checked and tidied (weekday names in full, numbers whole, the
    version added); ValueError, saying what to change, when it isn't one."""
    if not isinstance(rule, dict):
        raise ValueError("A rule is an object such as {kind: 'monthly', every: 1, weekday: 'Saturday', nth: 1}.")
    kind = rule.get("kind")
    if kind not in RULE_KINDS:
        raise ValueError(f"A rule's kind is one of {', '.join(RULE_KINDS)}; got {kind!r}.")
    known = {"kind", "every", "unit", "weekdays", "weekday", "nth", "day", "month", "anchor", "version"}
    extra = sorted(set(rule) - known)
    if extra:
        raise ValueError(f"A rule doesn't take {', '.join(extra)}.")
    out: dict = {"kind": kind, "every": _whole(rule.get("every", 1), "every", 1, 1000)}
    if kind == "every":
        unit = rule.get("unit")
        if unit not in ("days", "weeks", "months", "years"):
            raise ValueError("A rule of kind every has a unit: days, weeks, months or years.")
        out["unit"] = unit
        bad = [k for k in ("weekdays", "weekday", "nth", "day", "month") if rule.get(k) is not None]
        if bad:
            raise ValueError(f"A rule of kind every takes no {', '.join(bad)}: use weekly, monthly or yearly.")
    elif kind == "weekly":
        days = rule.get("weekdays")
        if days is None and rule.get("weekday") is not None:
            days = [rule["weekday"]]
        if not isinstance(days, list) or len(days) != 1:
            raise ValueError("A weekly rule names one weekday: {kind: 'weekly', weekdays: ['Saturday']}.")
        out["weekdays"] = [_weekday(days[0])]
        if any(rule.get(k) is not None for k in ("nth", "day", "month")):
            raise ValueError("A weekly rule takes a weekday only (nth, day and month go with monthly or yearly).")
    else:
        if kind == "yearly":
            out["month"] = _whole(rule.get("month"), "month", 1, 12)
        elif rule.get("month") is not None:
            raise ValueError("month goes with a yearly rule (the first Tuesday of November).")
        has_day, has_weekday = rule.get("day") is not None, rule.get("weekday") is not None
        if has_day == has_weekday:
            raise ValueError(f"A {kind} rule has a weekday with nth (the first Saturday) or a day (the 15th), "
                             "one of them.")
        if has_day:
            out["day"] = _whole(rule["day"], "day", 1, 31)
            if rule.get("nth") is not None:
                raise ValueError("nth goes with a weekday, not a day of the month.")
        else:
            out["weekday"] = _weekday(rule["weekday"])
            nth = _whole(rule.get("nth"), "nth", -5, 5)
            if nth == 0:
                raise ValueError("nth is 1 to 5 (the first to the fifth) or -1 to -5 (the last to the fifth from "
                                 "last).")
            out["nth"] = nth
    if rule.get("anchor") not in (None, ""):
        try:
            out["anchor"] = date.fromisoformat(str(rule["anchor"])[:10]).isoformat()
        except ValueError:
            raise ValueError(f"A rule's anchor is a date like 2026-11-14; got {rule['anchor']!r}.") from None
    out["version"] = RULE_VERSION
    cadence(out, out.get("anchor") or "2000-01-01")  # the dates themselves must work out
    return out


def interval_of(rule: dict) -> tuple[int, str]:
    """The (interval, unit) a rule steps by: what a task keeps beside it for older readers."""
    return rule["every"], rule.get("unit") or UNIT_OF_KIND[rule["kind"]]


def cadence(rule: dict, anchor) -> Cadence:
    """The rule's dates, counted from ``anchor`` (the rule's own anchor wins)."""
    every, unit = interval_of(rule)
    start = rule.get("anchor") or anchor
    weekday = (rule.get("weekdays") or [None])[0] if rule["kind"] == "weekly" else rule.get("weekday")
    return Cadence(every, unit, start, weekday=weekday, nth=rule.get("nth"), day=rule.get("day"),
                   month=rule.get("month"))


def rule_of_package(pkg: dict) -> dict:
    """A work package's cadence in the shared shape (packages keep their own fields)."""
    pattern = pkg.get("pattern") or {}
    every, unit = int(pkg["every"]), pkg["unit"]
    base = {"every": every, "anchor": pkg.get("anchor"), "version": RULE_VERSION}
    if pattern.get("month"):
        rest = {"weekday": pattern["weekday"], "nth": pattern["nth"]} if pattern.get("weekday") else \
            {"day": pattern["day"]}
        return {"kind": "yearly", "month": pattern["month"], **rest, **base}
    if pattern.get("weekday") and unit == "weeks":
        return {"kind": "weekly", "weekdays": [pattern["weekday"]], **base}
    if pattern.get("weekday"):
        return {"kind": "monthly", "weekday": pattern["weekday"], "nth": pattern["nth"], **base}
    if pattern.get("day"):
        return {"kind": "monthly", "day": pattern["day"], **base}
    return {"kind": "every", "unit": unit, **base}


def _ordinal_day(d: int) -> str:
    suffix = "th" if 10 <= d % 100 <= 20 else {1: "st", 2: "nd", 3: "rd"}.get(d % 10, "th")
    return f"{d}{suffix}"


def describe(rule: dict) -> str:
    """A rule in words: "the first Saturday of every month", "the first Tuesday of
    November, every year", "every 2 weeks on Saturday"."""
    n, kind = rule["every"], rule["kind"]
    if kind == "every":
        unit = rule["unit"]
        return f"every {unit[:-1]}" if n == 1 else f"every {n} {unit}"
    if kind == "weekly":
        day = rule["weekdays"][0]
        return f"every {day}" if n == 1 else f"every {n} weeks on {day}"
    which = (f"the {_ORDINALS[rule['nth']]} {rule['weekday']}" if rule.get("weekday")
             else f"the {_ordinal_day(rule['day'])}")
    if kind == "monthly":
        return f"{which} of every month" if n == 1 else f"{which} of every {n} months"
    month = MONTHS[rule["month"] - 1]
    if rule.get("day"):
        which = f"{rule['day']} {month}"
    else:
        which = f"{which} of {month}"
    return f"{which}, every year" if n == 1 else f"{which}, every {n} years"


def recurrence(rule: dict, anchor) -> Recurrence:
    """The rule as the library's ``Recurrence``, counted from ``anchor`` (the rule's own wins)."""
    return cadence(rule, anchor).recurrence


def to_library(rule: dict, anchor=None) -> dict:
    """The rule as RePyability saves a ``Recurrence`` (``to_dict``)."""
    return recurrence(rule, anchor or rule.get("anchor")).to_dict()


def from_library(data: dict) -> dict:
    """A library ``Recurrence`` dict (or the older package and task shapes it reads) in
    this module's shape, checked; ValueError for a rule this shape can't say (given
    dates, several weekdays, seasons or exclusions)."""
    rec = Recurrence.from_dict(data)
    if rec.rule == "on" or rec.season is not None or rec.excluding:
        raise ValueError("Given dates, seasons and excluded dates aren't in a task's rule yet.")
    out: dict = {"kind": rec.rule, "every": rec.every_n}
    if rec.rule == "every":
        out["unit"] = rec.unit
    elif rec.rule == "weekly":
        if len(rec.weekdays) != 1:
            raise ValueError("A task's weekly rule names one weekday.")
        out["weekdays"] = [WEEKDAYS[rec.weekdays[0]]]
    else:
        if rec.month is not None:
            out["month"] = rec.month
        if rec.day is not None:
            out["day"] = rec.day
        else:
            out["weekday"], out["nth"] = WEEKDAYS[rec.weekdays[0]], rec.nth
    if rec.anchor is not None:
        out["anchor"] = rec.anchor.isoformat()
    return check_rule(out)
