"""Next due only when it's known (Derryn, 23 Nov 2026): a task's and a package's next occurrence is
given when it rests on a record (last done, a start set, a calendar rule, a work order, a duty or
measured readings), and is blank, saying why, when it would only come from "now" or from assuming an
hours counter runs 24 hours a day."""

from datetime import datetime, timezone

from backend.maintenance.service import PROJECTORS, Maintenance
from backend.maintenance.store import GraphStore

TODAY = "2026-12-01"


def _clock(monkeypatch, day: str = TODAY):
    from backend.services import time_zones

    monkeypatch.setattr(time_zones, "_now", lambda: datetime.fromisoformat(day).replace(hour=8, tzinfo=timezone.utc))


def _m():
    m = Maintenance(GraphStore(":memory:", PROJECTORS), "org-next-due", "tester")
    m.today = lambda: TODAY
    return m


def _row(m, root, task_id):
    return next(t for t in m.task_table(within=root)["tasks"] if t["id"] == task_id)


def test_a_calendar_task_with_no_record_is_blank_not_a_year_from_today(monkeypatch):
    _clock(monkeypatch)
    m = _m()
    pool = m.create_position("Pool")["id"]
    t = m.create_task(pool, "Service the pump", 12, "months")
    # The schedule still counts from the day it was made; the column doesn't show that as a fact.
    assert t["next_due"] == "2027-12-01"
    row = _row(m, pool, t["id"])
    assert row["next"]["on"] is None and row["next"]["why"] == "No record of when this was last done"
    assert row["next"]["overdue"] is False


def test_last_done_start_or_a_pattern_give_a_date(monkeypatch):
    _clock(monkeypatch)
    m = _m()
    pool = m.create_position("Pool")["id"]
    done = m.create_task(pool, "Backwash", 3, "months", last_done="2026-10-15")["id"]
    started = m.create_task(pool, "Acid dose", 12, "months", start="2027-10-01")["id"]
    ruled = m.create_task(pool, "Test the water", 1, "months")["id"]
    m.set_task_rule(ruled, {"kind": "monthly", "every": 1, "weekday": "Saturday", "nth": 1})
    assert _row(m, pool, done)["next"]["on"] == "2027-01-15"
    assert _row(m, pool, started)["next"] | {"basis": None} == {
        "on": "2027-10-01", "at_reading": None, "unit": None, "basis": None, "why": None, "overdue": False}
    assert _row(m, pool, ruled)["next"]["on"] == "2026-12-05"  # the first Saturday of December


def test_late_with_a_record_is_overdue(monkeypatch):
    _clock(monkeypatch)
    m = _m()
    pool = m.create_position("Pool")["id"]
    late = m.create_task(pool, "Backwash", 1, "months", last_done="2026-09-01")["id"]
    nxt = _row(m, pool, late)["next"]
    assert nxt["on"] == "2026-10-01" and nxt["overdue"] is True


def _conveyor(m, duty=False, rate=True, last_done=True):
    cv = m.create_position("Conveyor CV-3")["id"]
    if duty:
        m.set_operating_plan(cv, {"background": {"kind": "rate", "amount": 3, "per": "day"}})
    hours = m.add_point(cv, "Hours run", kind="counter", unit="hours")["id"]
    if rate:
        m.record_reading(hours, 1000, on="2026-10-01")
    m.record_reading(hours, 1180, on="2026-12-01")
    task = m.create_task(cv, "Inspect idlers", 250, "hours", **({"last_done": "2026-10-01"} if last_done else {}))
    return cv, task["id"]


def test_hours_with_measured_readings_give_the_reading_and_a_date(monkeypatch):
    _clock(monkeypatch)
    m = _m()
    cv, task = _conveyor(m, rate=True)
    nxt = _row(m, cv, task)["next"]
    assert nxt["at_reading"] == 1250 and nxt["unit"] == "hours" and nxt["on"] == "2026-12-24"
    assert "running-hours readings" in nxt["basis"]


def test_hours_with_a_duty_give_a_date_from_the_duty(monkeypatch):
    _clock(monkeypatch)
    m = _m()
    cv, task = _conveyor(m, duty=True)
    nxt = _row(m, cv, task)["next"]
    assert nxt["at_reading"] == 1250 and nxt["on"] == "2026-12-24" and "operating plan" in nxt["basis"]


def test_hours_with_no_duty_or_rate_give_the_reading_alone(monkeypatch):
    """No duty and a single reading: the schedule assumes 24 h a day; the column shows the hours only."""
    _clock(monkeypatch)
    m = _m()
    cv, task = _conveyor(m, rate=False)
    view = m._task_view(m.s.node(m.org, task))
    assert view["next_due"] is not None and view["limits"][0]["basis"]["kind"] == "continuous"
    nxt = _row(m, cv, task)["next"]
    assert nxt["on"] is None and nxt["at_reading"] == 1430
    assert nxt["why"] == "No duty or measured readings on the position to put a date on it"


def test_hours_with_no_record_are_blank(monkeypatch):
    _clock(monkeypatch)
    m = _m()
    cv, task = _conveyor(m, duty=True, last_done=False)
    nxt = _row(m, cv, task)["next"]
    assert nxt["on"] is None and nxt["at_reading"] is None
    assert nxt["why"] == "No record of when this was last done, or at what reading"


def test_a_calendar_package_has_its_next_visit(monkeypatch):
    _clock(monkeypatch)
    m = _m()
    pool = m.create_position("Pool")["id"]
    t = m.create_task(pool, "Skim the surface", 1, "weeks")["id"]
    pkg = m.create_package("Weekly pool check", position_id=pool, every=1, unit="weeks", anchor="2026-12-05", tasks=[t])
    listed = next(p for p in m.packages(position_id=pool)["packages"] if p["id"] == pkg["id"])
    assert listed["next"]["on"] == listed["next_visit"] == "2026-12-05"
    # A task in it is due on the package's visit.
    assert _row(m, pool, t)["next"]["on"] == "2026-12-05"
