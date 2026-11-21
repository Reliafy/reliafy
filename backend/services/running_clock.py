"""A model's running time meeting the calendar at a position: through its duty.

A model in running hours (``hours``, ``operating hours``, ``running hours``,
``flight hours``) counts the time the part runs, not the calendar's. Where it
meets a calendar interval *for a position* (an RCM decision's evidence, a task's
interval, a Strategy calculation run from the position, a forecast, the spares
for the year), the hours become days at the rate that position runs (Derryn, 21
Nov 2026: "it should assume continuous use unless there is a duty against that
position"):

* with an operating plan on the position (its own, or the one it inherits from
  the position above it, as ``Maintenance.duty_of`` resolves it): at the plan's
  hours a day over the next year, worked out by RePyability
  (``DutyPlan.forecast(...).duty()``: the share of the time it runs, outages and
  utilisation included). A plan of 8 hours a day gives 1,000 h ≈ 125 days;
* with none: all the time, 24 hours a day (1,000 h ≈ 41.7 days).

The rate is the average over the year ahead, so a plan that varies (16 h on
weekdays, none at weekends) converts at its mean (about 11.4 h a day); the dates
of a task by use still come from the plan itself (``Maintenance._usage_map``).
RePyability computes; this module only asks it and says which way it went.

Units of use that are not time (cycles, km, starts, landings) are never
converted to the calendar here: there's no rate between them and a day.

With no position at all (a stand-alone Strategy calculation, an RCM study, a
diagram), :mod:`backend.services.model_units` keeps today's rule: plain hours are
calendar hours (24 a day), and other running-hour units don't convert.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Optional

from backend.units import canonical_unit, normalize_unit, unit_in_text

#: Spellings of an hour of running (lower case, trimmed). Plain "hours" is one of them at a
#: position: a part's hours there are the hours it runs.
RUNNING_HOURS = frozenset({
    "hour", "operating hour", "operating hours", "op hr", "op hrs", "op hours", "operating hrs",
    "running hour", "running hours", "run hour", "run hours", "run hrs", "hours run",
    "flight hour", "flight hours", "fh", "engine hour", "engine hours", "service hour", "service hours",
})
#: Days in one of each calendar unit (the app's one convention: backend.units.DAYS_PER).
CALENDAR_DAYS = {"day": 1.0, "week": 7.0, "month": 365.25 / 12, "year": 365.25}
#: The span the duty's hours a day are averaged over, from today.
HORIZON_DAYS = 365


def _key(unit) -> str:
    text = str(unit or "").strip().lower().rstrip(".")
    return normalize_unit(text) or ""


def is_running_hours(unit) -> bool:
    """Whether ``unit`` is an hour of running ("hours", "operating hours", "flight hours")."""
    text = str(unit or "").strip().lower().rstrip(".")
    return bool(text) and (text in RUNNING_HOURS or _key(text) in RUNNING_HOURS)


def is_calendar(unit) -> bool:
    """Whether ``unit`` is a calendar unit of a day or more (days, weeks, months, years)."""
    return _key(unit) in CALENDAR_DAYS


def _fmt(value: float) -> str:
    from backend.services.strategy import fmt_num

    return fmt_num(value)


@dataclass(frozen=True)
class Clock:
    """How a position runs, as hours a day: ``basis`` "duty" (from its operating plan),
    "continuous" (no plan: all the time) or "idle" (its plan gives no running in the year
    ahead: nothing converts). ``steady``: the same hours every day."""

    hours_per_day: float
    basis: str
    steady: bool = True
    plan: str = ""
    inherited_from: Optional[str] = None

    @property
    def converts(self) -> bool:
        return self.hours_per_day > 0

    def rate_words(self) -> str:
        """"8 h a day", "11.4 h a day on average"."""
        words = f"{_fmt(self.hours_per_day)} h a day"
        return words if self.steady else f"{words} on average"

    def where(self) -> str:
        """How a conversion went, to follow a number: " at this position's duty (8 h a day)",
        ", assuming it runs all the time (no duty set for this position)"."""
        if self.basis == "continuous":
            return ", assuming it runs all the time (no duty set for this position)"
        if self.basis == "idle":
            return ": its operating plan gives no running in the year ahead"
        whose = f"the duty it takes from {self.inherited_from}" if self.inherited_from else "this position's duty"
        return f" at {whose} ({self.rate_words()})"

    def to_dict(self) -> dict:
        return {"hours_per_day": round(self.hours_per_day, 4), "basis": self.basis, "steady": self.steady,
                "plan": self.plan, "inherited_from": self.inherited_from, "text": self.where().lstrip(" ,:"),
                "where": self.where()}


    @classmethod
    def from_dict(cls, data) -> Optional["Clock"]:
        """A clock saved with an analysis's inputs (:meth:`to_dict`), or None."""
        if not isinstance(data, dict):
            return None
        try:
            hours = float(data.get("hours_per_day"))
        except (TypeError, ValueError):
            return None
        basis = data.get("basis") if data.get("basis") in ("duty", "continuous", "idle") else "duty"
        return cls(hours, basis, bool(data.get("steady", True)), str(data.get("plan") or ""),
                   data.get("inherited_from") or None)


CONTINUOUS = Clock(24.0, "continuous")


def from_duty(plan, start: date, plan_text: str = "", inherited_from: Optional[str] = None) -> Clock:
    """A position's clock from its duty plan (RePyability's ``DutyPlan``): its hours a day
    over the year from ``start``."""
    usage = plan.forecast(start, start + timedelta(days=HORIZON_DAYS))
    hours_per_day = 24.0 * float(usage.duty())
    daily = [float(h) for h in (usage.by_period("day").usage.get("hours") or ())]
    steady = bool(daily) and max(daily) - min(daily) < 1e-6
    if hours_per_day <= 1e-9:
        return Clock(0.0, "idle", True, plan_text, inherited_from)
    return Clock(hours_per_day, "duty", steady, plan_text, inherited_from)


def for_position(m, position_id: Optional[str], root: Optional[str] = None) -> Clock:
    """The clock ``position_id`` (a position, or the item on one) runs to: its duty, else
    continuous. Memoised per read on ``m`` (a Maintenance)."""
    if not position_id or m is None:
        return CONTINUOUS
    memo = m._memo.setdefault("running_clock", {})
    key = (position_id, root)
    if key in memo:
        return memo[key]
    try:
        duty = m.duty_of(position_id, root)
    except Exception:  # noqa: BLE001 - a position that's gone, or no plan to read: runs all the time
        duty = None
    if duty is None:
        clock = CONTINUOUS
    else:
        try:
            clock = from_duty(duty["plan"], date.fromisoformat(m.today()), duty.get("text") or "",
                              (duty.get("inherited_from") or {}).get("name"))
        except (ValueError, TypeError):
            clock = CONTINUOUS
    memo[key] = clock
    return clock


def days_in(unit, clock: Optional[Clock] = None) -> Optional[float]:
    """Days in one of ``unit``: a calendar unit's, an hour of running's at ``clock``. With
    no clock (no position), a plain hour is a calendar hour (1/24) and other running-hour
    units have none; None for units of use (cycles, km) and an idle clock."""
    key = _key(unit)
    if key in CALENDAR_DAYS:
        return CALENDAR_DAYS[key]
    if clock is None:
        return 1 / 24 if key == "hour" else None
    if is_running_hours(unit):
        return 1.0 / clock.hours_per_day if clock.converts else None
    return None


def conversion(from_unit, to_unit, clock: Optional[Clock]) -> Optional[dict]:
    """``{"from", "to", "factor", "clock"}`` (``factor``: ``to_unit`` per ``from_unit``) when
    one side is running hours and the other the calendar, at ``clock``; otherwise
    :func:`backend.services.model_units.conversion` (days to months, km to miles: no clock),
    or None. With ``clock`` None this is ``model_units``' rule exactly."""
    from backend.services import model_units

    if clock is not None and ((is_running_hours(from_unit) and is_calendar(to_unit))
                              or (is_calendar(from_unit) and is_running_hours(to_unit))):
        a, b = days_in(from_unit, clock), days_in(to_unit, clock)
        if a is None or b is None:
            return None
        return {"from": canonical_unit(from_unit), "to": canonical_unit(to_unit), "factor": a / b, "clock": clock}
    return model_units.conversion({"unit": from_unit}, to_unit)


def same_clock(a, b) -> bool:
    """Whether two units count the same thing: both hours of running ("flight hours" and
    "hours" at a position), or the same unit."""
    if is_running_hours(a) and is_running_hours(b):
        return True
    ka, kb = _key(a), _key(b)
    return bool(ka) and ka == kb


def _amount(value: float, unit) -> str:
    if is_running_hours(unit):
        return f"{_fmt(value)} h"
    from backend.units import with_unit

    return with_unit(_fmt(value), unit_in_text(canonical_unit(unit)))


def note(conv: dict, amount: Optional[float] = None, what: str = "answer", source: str = "model") -> str:
    """What a conversion did, in words. At a position: "1,000 h ≈ 125 days at this
    position's duty (8 h a day)" with ``amount`` (in the ``from`` unit), else "model in
    hours, answer in days: converted at this position's duty (8 h a day)". Without a
    clock, model_units' note ("… converted at 1 day = 24 hours, running all the time")."""
    clock = conv.get("clock")
    if clock is None:
        from backend.services import model_units

        return model_units.used_note(conv, what, source)
    if amount is not None:
        return f"{_amount(amount, conv['from'])} ≈ {_amount(amount * conv['factor'], conv['to'])}{clock.where()}"
    return (f"{source} in {unit_in_text(conv['from'])}, {what} in {unit_in_text(conv['to'])}: converted"
            f"{clock.where()}")


def public(conv: Optional[dict]) -> Optional[dict]:
    """A conversion for a JSON answer: its clock as a dict."""
    if not conv:
        return conv
    out = {k: v for k, v in conv.items() if k != "clock"}
    if conv.get("clock") is not None:
        out["clock"] = conv["clock"].to_dict()
    return out


def with_calendar(result: dict, key: str, unit, clock) -> dict:
    """A Strategy answer run from a position with its ``key`` (an interval in running hours)
    also on the calendar: ``calendar`` {value, unit: "days", note: "1,000 h ≈ 125 days at this
    position's duty (8 h a day)", clock}. ``clock``: a Clock or its dict; as it is otherwise."""
    clock = clock if isinstance(clock, Clock) else Clock.from_dict(clock)
    try:
        value = float(result.get(key))
    except (TypeError, ValueError):
        return result
    if clock is None or not is_running_hours(unit) or not clock.converts:
        return result
    conv = conversion(unit, "days", clock)
    if conv is None:
        return result
    return {**result, "calendar": {"value": value * conv["factor"], "unit": "days", "note": note(conv, value),
                                   "clock": clock.to_dict()}}
