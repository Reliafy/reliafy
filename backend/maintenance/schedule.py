"""Maintenance scheduling: the app's seam with RePyability's ``repyability.schedule``.

RePyability computes; Reliafy records. The library works out which dates a rule
gives (``Recurrence``), how many operating hours a plan gives by when
(``DutyPlan`` and its ``UsageForecast``), when a task by use falls due on that
map, and a part's failures by calendar period through it. Reliafy keeps the
records (tasks, packages, operating plans, readings, fitments), decides what
"today" and the time zone are, and turns the answers into screens.

This module is the only place the app imports the library's schedule types. It
turns the shapes the app stores into the library's:

* a work package's cadence (``every``, ``unit``, ``anchor``, ``pattern``) and a
  task's "how often" rule (``how_often.py``) into a ``Recurrence``
  (:class:`Cadence` keeps the app's small interface over it);
* an operating plan's dict (``operating_plan.py``: a background and specific
  runs on top), with its dates and zone, into a ``DutyPlan``.

Nothing stored is rewritten: the stored dicts stay as they are and are read
through these adapters (round trips in ``test_maintenance_forecast_engine.py``).

TODO(RePyability 0.18): ``repyability.schedule`` first ships in RePyability 0.18.
Until the libraries pull request bumps the pins (requirements.txt, the lock, the
Dockerfile's RePyability commit and the ci / guide-screenshots / content-draft
workflows), this module needs RePyability from its ``dev`` branch.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from typing import Optional, Tuple

from repyability.schedule import (  # noqa: F401  (re-exported for the app)
    Continuous,
    DutyPlan,
    Rate,
    Recurrence,
    Roster,
    Runs,
    Season,
    Shifts,
    Usage,
    UsageForecast,
    failures_by_period,
    work_by_period,
)
from repyability.schedule import Task as LibraryTask  # noqa: F401

#: The units a work package's cadence counts in.
CADENCE_UNITS = ("days", "weeks", "months", "years")
#: The latest date a cadence gives (Reliafy's calendar ends in 2199).
_LAST_DAY = date(2199, 12, 31)
_WEEKDAYS = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")
#: nth weekday of a month: first to fifth, last to fifth from last (a month with no fifth is skipped).
_CADENCE_NTHS = (1, 2, 3, 4, 5, -1, -2, -3, -4, -5)


def _is_whole(value) -> bool:
    if isinstance(value, bool):
        return False
    try:
        return float(value).is_integer()
    except (TypeError, ValueError):
        return False


def _whole_number(value, name: str, minimum: int = 1) -> int:
    if not _is_whole(value) or int(float(value)) < minimum:
        raise ValueError(f"{name} must be a whole number, at least {minimum}; got {value!r}.")
    return int(float(value))


def _date(value, name: str) -> date:
    if isinstance(value, datetime):
        raise TypeError(f"{name} is a date (whole days), not a date and time; got {value!r}.")
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        try:
            return date.fromisoformat(value[:10])
        except ValueError:
            pass
    raise ValueError(f"{name} must be a date like 2026-07-15; got {value!r}.")


@dataclass(frozen=True, init=False)
class Cadence:
    """The dates a work package (or a task's pattern) falls on: every ``every``
    days, weeks, months or years from ``anchor``; or on a pattern inside that: a
    ``weekday`` every ``every`` weeks, the ``nth`` weekday or a ``day`` of every
    ``every`` th month, or of a named ``month`` every ``every`` years. No date
    comes before the anchor.

    The app's checks and wording stay here; the dates are the library's
    ``Recurrence`` (:attr:`recurrence`), so "due" means one thing everywhere.

    >>> yearly = Cadence(1, "years", "2026-11-14", weekday="Tuesday", nth=1, month=11)
    >>> [d.isoformat() for d in yearly.dates("2026-11-14", "2029-12-31")]
    ['2027-11-02', '2028-11-07', '2029-11-06']
    """

    every: int
    unit: str
    anchor: date
    weekday: Optional[str]
    nth: Optional[int]
    day: Optional[int]
    month: Optional[int] = None

    def __init__(self, every, unit, anchor, *, weekday=None, nth=None, day=None, month=None) -> None:
        every = _whole_number(every, "every")
        if unit not in CADENCE_UNITS:
            raise ValueError(f"unit must be one of {', '.join(CADENCE_UNITS)}; got {unit!r}.")
        anchor = _date(anchor, "anchor")
        if weekday is not None:
            name = weekday.capitalize() if isinstance(weekday, str) else None
            if name not in _WEEKDAYS:
                raise ValueError(f"weekday must be a day of the week, such as 'Saturday'; got {weekday!r}.")
            weekday = name
            if day is not None:
                raise ValueError("Give a weekday or a day of the month, not both.")
            if unit == "weeks":
                if nth is not None:
                    raise ValueError("nth goes with months (the first Saturday of the month), not weeks.")
            elif unit in ("months", "years"):
                if unit == "years" and month is None:
                    raise ValueError("A weekday every so many years goes in a month: give month (the first "
                                     "Tuesday of November: month 11).")
                if not _is_whole(nth) or int(nth) not in _CADENCE_NTHS:
                    raise ValueError("With a weekday in the month, nth says which: 1 to 5 (the first to the "
                                     f"fifth) or -1 to -5 (the last to the fifth from last); got {nth!r}.")
                nth = int(nth)
            else:
                raise ValueError("A weekday goes with weeks (every Saturday), months (the first Saturday of "
                                 "the month) or years (the first Tuesday of November).")
        elif nth is not None:
            raise ValueError("nth goes with a weekday (the first Saturday of the month).")
        if day is not None:
            if unit not in ("months", "years"):
                raise ValueError("A day of the month goes with months (the 15th of every month) or years "
                                 "(1 July).")
            if unit == "years" and month is None:
                raise ValueError("A day every so many years goes in a month: give month (1 July: month 7).")
            day = _whole_number(day, "day")
            if day > 31:
                raise ValueError(f"day must be 1 to 31; got {day!r}.")
        if month is not None:
            if unit != "years":
                raise ValueError("month goes with years (the first Tuesday of November, every year).")
            if weekday is None and day is None:
                raise ValueError("A month goes with a weekday and nth, or a day (1 July).")
            month = _whole_number(month, "month")
            if month > 12:
                raise ValueError(f"month must be 1 to 12; got {month!r}.")
        for k, v in (("every", every), ("unit", unit), ("anchor", anchor), ("weekday", weekday), ("nth", nth),
                     ("day", day), ("month", month)):
            object.__setattr__(self, k, v)
        object.__setattr__(self, "_rec", self._recurrence())

    def _recurrence(self) -> Recurrence:
        n, unit, anchor = self.every, self.unit, self.anchor
        if self.month is not None:
            return Recurrence.yearly(month=self.month, day=self.day, weekday=self.weekday, nth=self.nth, every=n,
                                     anchor=anchor)
        if unit == "weeks" and self.weekday is not None:
            return Recurrence.weekly(self.weekday, every=n, anchor=anchor)
        if unit == "months" and (self.weekday is not None or self.day is not None):
            return Recurrence.monthly(day=self.day, weekday=self.weekday, nth=self.nth, every=n, anchor=anchor)
        return Recurrence.every(n, unit, anchor)

    @property
    def recurrence(self) -> Recurrence:
        """The library's rule for these dates."""
        return self._rec

    def on_or_after(self, day) -> Optional[date]:
        """The first date on or after ``day`` (None past the calendar's end)."""
        day = max(_date(day, "day"), self.anchor)
        if day > _LAST_DAY:
            return None
        found = self._rec.on_or_after(day)
        return found if found is not None and found <= _LAST_DAY else None

    def after(self, day) -> Optional[date]:
        """The first date strictly after ``day``."""
        day = _date(day, "day")
        return None if day >= _LAST_DAY else self.on_or_after(day + timedelta(days=1))

    def includes(self, day) -> bool:
        """Whether it falls on ``day``."""
        day = _date(day, "day")
        return self.on_or_after(day) == day

    def dates(self, start, end, limit: int = 2000) -> Tuple[date, ...]:
        """The dates from ``start`` to ``end``, both included (at most ``limit``)."""
        start, end = _date(start, "start"), min(_date(end, "end"), _LAST_DAY)
        if end < start:
            return ()
        return tuple(self._rec.dates(max(start, self.anchor), end)[:limit]) if end >= self.anchor else ()

    def number(self, day) -> int:
        """How many dates there are from the anchor through ``day``: a visit's number,
        the first being 1 (0 before the first)."""
        day = _date(day, "day")
        return 0 if day < self.anchor else self._rec.number(day)


# ---- operating plans: the stored dict as a DutyPlan ------------------------------------------

def _wall(text: str) -> datetime:
    return datetime.fromisoformat(str(text).replace(" ", "T")[:16])


def _midnight(day: str) -> datetime:
    return datetime.combine(date.fromisoformat(str(day)[:10]), time())


def background_part(bg: dict, from_=None, until=None, utilisation=None):
    """A stored background (operating_plan.py's shape) as the library's part, applying
    from ``from_`` until ``until`` (wall-clock datetimes, or None: open), at the plan's
    ``utilisation`` (None: all of it)."""
    span = {"from_": from_, "until": until, "utilisation": utilisation}
    kind = bg["kind"]
    if kind == "continuous":
        return Continuous(**span)
    if kind == "shifts":
        return Shifts([(", ".join(sh["days"]), sh["start"], sh["stop"]) for sh in bg["shifts"]], **span)
    if kind == "roster":
        if not bg["off"]:  # no days off: every day, start to stop
            return Shifts("Mon-Sun", bg["start"], bg["stop"], **span)
        return Roster((bg["on"], bg["off"]), bg["anchor"], bg["start"], bg["stop"], **span)
    if kind == "rate":
        return Rate(bg["amount"], per=bg["per"], meter=bg.get("meter", "hours"), **span)
    if kind == "runs":
        runs = [(_wall(a), _wall(b)) for a, b in bg["runs"]]
        if from_ is not None or until is not None:
            lo, hi = from_ or runs[0][0], until or runs[-1][1]
            runs = [(max(a, lo), min(b, hi)) for a, b in runs if b > lo and a < hi]
            if not runs:
                return None
        return Runs(runs, **span)
    raise ValueError(f"An operating plan's background is one of continuous, shifts, roster, rate or runs; "
                     f"got {kind!r}.")


def specific_parts(plan: dict) -> list:
    """A stored plan's specific runs, each covering its own span."""
    return [Runs([(_wall(a), _wall(b)) for a, b in layer["runs"]], from_=_wall(layer["covers"][0]),
                 until=_wall(layer["covers"][1]))
            for layer in plan.get("specific") or []]


def duty_plan(plans: list[dict], time_zone: Optional[str] = None, outages=None) -> Optional[DutyPlan]:
    """The library's ``DutyPlan`` for a position's dated plans (the OperatingPlan records:
    ``{plan, from, until}``, oldest first). Each applies from its ``from`` date (00:00)
    to its ``until`` date (00:00, or open); with background runs only, nothing runs
    between its runs. ``outages`` are (start, end) moments with no running. None when
    no plan gives any part."""
    back, spec = [], []
    for rec in plans:
        start = _midnight(rec["from"])
        end = _midnight(rec["until"]) if rec.get("until") else None
        if end is not None and end <= start:
            continue
        part = background_part(rec["plan"]["background"], start, end, rec["plan"].get("utilisation"))
        if part is not None:
            back.append(part)
        for sp in specific_parts(rec["plan"]):
            a, b = sp.from_, sp.until
            if b <= start or (end is not None and a >= end):
                continue
            spec.append(sp)
    if not back and not spec:
        return None
    return DutyPlan(background=back or None, specific=spec or None, time_zone=time_zone, outages=outages or None)


def plan_to_library(plan: dict, time_zone: Optional[str] = None, from_: Optional[str] = None,
                    until: Optional[str] = None) -> dict:
    """A stored plan as the library saves a ``DutyPlan`` (``to_dict``): the shape a
    later release could store in its place."""
    dp = duty_plan([{"plan": plan, "from": from_ or "2000-01-01", "until": until}], time_zone)
    return dp.to_dict()


def plan_from_library(data: dict) -> dict:
    """A library ``DutyPlan`` dict read back into the app's stored shape (its version
    1): the background's first part and the specific runs. Raises ValueError for parts
    the app's plan has no shape for."""
    dp = DutyPlan.from_dict(data)
    if len(dp.background) != 1:
        raise ValueError("The app's plan has one background part.")
    part = dp.background[0]
    if isinstance(part, Continuous):
        bg = {"kind": "continuous"}
    elif isinstance(part, Shifts):
        bg = {"kind": "shifts", "shifts": [
            {"days": [_WEEKDAYS[d] for d in days], "start": f"{a:%H:%M}", "stop": f"{b:%H:%M}"}
            for days, a, b in part.windows]}
    elif isinstance(part, Roster):
        if len(part.pattern) != 2:
            raise ValueError("The app's roster is days on then days off.")
        bg = {"kind": "roster", "on": part.pattern[0], "off": part.pattern[1], "anchor": part.anchor.isoformat(),
              "start": f"{part.start:%H:%M}", "stop": f"{part.stop:%H:%M}"}
    elif isinstance(part, Rate):
        amount = part.amount
        bg = {"kind": "rate", "amount": int(amount) if float(amount).is_integer() else amount, "per": part.per,
              "meter": part.meter_name}
    else:
        bg = {"kind": "runs", "runs": [[f"{a:%Y-%m-%dT%H:%M}", f"{b:%Y-%m-%dT%H:%M}"] for a, b in part.runs]}
    specific = [{"kind": "runs", "runs": [[f"{a:%Y-%m-%dT%H:%M}", f"{b:%Y-%m-%dT%H:%M}"] for a, b in sp.runs],
                 "covers": [f"{sp.from_:%Y-%m-%dT%H:%M}", f"{sp.until:%Y-%m-%dT%H:%M}"]} for sp in dp.specific]
    out = {"version": 1, "background": bg, "specific": specific}
    if part.utilisation not in (None, 1.0):
        out["utilisation"] = part.utilisation
    return out
