"""``analyse schedule``: a rule or an operating plan worked out, nothing saved.

For an agent (or the API) checking "is this the rule you mean?" before saving it: a
"how often" rule in, its dates out (with the rule in words); an operating plan and a
meter reading in, the operating hours by date out (and, with ``due_at``, the moment
the meter reaches a value, with the stop after it). The rule and plan take the shapes
a task's ``rule`` and a position's operating plan are saved in
(``backend/maintenance/how_often.py``, ``operating_plan.py``); the arithmetic is
RePyability's (``repyability.schedule``) through ``backend/maintenance/schedule.py``.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta

from backend.maintenance import how_often, schedule
from backend.maintenance import operating_plan as op
from backend.services import time_zones

MAX_DATES = 500
MAX_DAYS = 3 * 366 + 1  # an operating plan's hours: three years at most
PERIODS = ("day", "week", "month")


class ScheduleError(ValueError):
    """A rule or plan that can't be worked out; the message says what to change."""


def _day(value, name: str, default: date) -> date:
    if value in (None, ""):
        return default
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        raise ScheduleError(f"{name} is a date like 2026-11-14; got {value!r}.") from None


def _rule_dates(rule: dict, start: date, end: date) -> dict:
    try:
        checked = how_often.check_rule(rule) if rule.get("kind") != "recurrence" else how_often.from_library(rule)
    except ValueError as err:
        raise ScheduleError(str(err)) from None
    anchor = checked.get("anchor") or start.isoformat()
    cad = how_often.cadence(checked, anchor)
    dates = cad.dates(start, end, limit=MAX_DATES)
    return {"rule": checked, "words": how_often.describe(checked), "anchor": anchor,
            "dates": [d.isoformat() for d in dates], "count": len(dates), "truncated": len(dates) >= MAX_DATES,
            "library": cad.recurrence.to_dict()}


def _plan_hours(plan: dict, start: date, end: date, zone: str | None, reading, read_at, period: str,
                due_at) -> dict:
    try:
        checked = op.check_plan(plan)
    except op.PlanError as err:
        raise ScheduleError(str(err)) from None
    if (end - start).days > MAX_DAYS:
        raise ScheduleError("An operating plan's hours are worked out for three years at most: give a nearer end.")
    if period not in PERIODS:
        raise ScheduleError(f"period is one of {', '.join(PERIODS)}.")
    dp = schedule.duty_plan([{"plan": checked, "from": start.isoformat(), "until": None}], zone)
    readings = None
    if reading not in (None, ""):
        try:
            readings = {"hours": float(reading)}
        except (TypeError, ValueError):
            raise ScheduleError(f"reading is the hours meter's reading, a number; got {reading!r}.") from None
    at = None
    if read_at not in (None, ""):
        try:
            at = datetime.fromisoformat(str(read_at).replace(" ", "T")[:16])
        except ValueError:
            raise ScheduleError(f"read_at is a date (and time) like 2026-11-16T06:00; got {read_at!r}.") from None
    try:
        usage = dp.forecast(start, end + timedelta(days=1), readings=readings, read_at=at)
    except (ValueError, TypeError) as err:
        raise ScheduleError(str(err)) from None
    found = usage.by_period(period)
    rows = [{"start": (s.date() if isinstance(s, datetime) else s).isoformat(),
             "hours": round(float(h), 2), "reading_at_end": round(float(r), 2)}
            for s, h, r in zip(found.starts, found.usage.get("hours", ()), found.at_end.get("hours", ()))]
    out = {"plan": checked, "words": op.describe(checked), "time_zone": zone, "period": period, "rows": rows,
           "hours": round(sum(r["hours"] for r in rows), 2), "describe": usage.describe(),
           "exact": not any(isinstance(p, schedule.Rate) for p in dp.background),
           "hours_per_week": (lambda h: None if h is None else round(h, 1))(op.typical_week(checked)),
           "library": dp.to_dict(), "notes": list(getattr(usage, "notes", ()) or ())}
    if due_at not in (None, ""):
        try:
            target = float(due_at)
        except (TypeError, ValueError):
            raise ScheduleError(f"due_at is a meter reading, a number; got {due_at!r}.") from None
        c = usage.when(hours=target)
        fmt = (lambda x: x.strftime("%Y-%m-%dT%H:%M") if x else None)
        out["due"] = {"reading": target, "moment": fmt(c.moment), "stop_after": fmt(c.next_stop_after),
                      "already_reached": bool(c.already_reached),
                      "note": None if c.moment or c.already_reached else "not reached by the end given"}
    return out


def compute(rule=None, plan=None, start=None, end=None, reading=None, read_at=None, period="day", due_at=None,
            time_zone=None) -> dict:
    """A rule's dates (``rule``), or a plan's hours by date (``plan``, with a meter
    ``reading`` at ``read_at`` and optionally ``due_at``), from ``start`` (default
    today) to ``end`` (default a year on for a rule, 28 days for a plan)."""
    if (rule is None) == (plan is None):
        raise ScheduleError("Give a rule (its dates) or a plan (its hours by date), one of them.")
    zone = time_zones.zone_name(time_zone) if time_zone not in (None, "") else None
    if time_zone not in (None, "") and zone is None:
        raise ScheduleError(f"{str(time_zone)[:60]!r} isn't a time zone: give one like Australia/Brisbane.")
    today = time_zones.today(zone).isoformat() if zone else time_zones.today().isoformat()
    first = _day(start, "start", date.fromisoformat(today))
    if rule is not None:
        if not isinstance(rule, dict):
            raise ScheduleError("rule is an object such as {kind: 'monthly', every: 1, weekday: 'Saturday', nth: 1}.")
        last = _day(end, "end", first + timedelta(days=366))
        if last < first:
            raise ScheduleError("end is before start.")
        return {"saved": False, "start": first.isoformat(), "end": last.isoformat(), **_rule_dates(rule, first, last)}
    if not isinstance(plan, dict):
        raise ScheduleError("plan is an object such as {background: {kind: 'rate', amount: 3, per: 'day'}}.")
    last = _day(end, "end", first + timedelta(days=27))
    if last < first:
        raise ScheduleError("end is before start.")
    return {"saved": False, "start": first.isoformat(), "end": last.isoformat(),
            **_plan_hours(plan, first, last, zone, reading, read_at, period or "day", due_at)}
