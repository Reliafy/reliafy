"""A forecast's details (forecast_details.py; Derryn, 23 Nov 2026): a task's, a package's or a level's
work and costs to come, by the calendar or by running hours, with or without a duty. Hours stay
hours without a duty: nothing by use is put on dates, and nothing on the calendar in hours."""

from datetime import date, datetime, timezone

import pytest

from backend.maintenance import forecast_details as fd
from backend.maintenance import position_forecast as pf
from backend.maintenance.service import PROJECTORS, Invalid, Maintenance
from backend.maintenance.store import GraphStore
from backend.tests.test_maintenance_rcm_api import UID, api  # noqa: F401

TODAY = "2026-12-01"


def _clock(monkeypatch, day: str = TODAY):
    from backend.services import time_zones

    monkeypatch.setattr(time_zones, "_now", lambda: datetime.fromisoformat(day).replace(hour=8, tzinfo=timezone.utc))


def _m(store=None, org="org-fc-details"):
    m = Maintenance(store or GraphStore(":memory:", PROJECTORS), org, "tester")
    m.today = lambda: TODAY
    return m


def _conveyor(m, duty: bool, rate: bool = True):
    """A conveyor with an hours meter (1,180 h today), a 250 h idler check (last done at 1,000 h)
    and a weekly belt walk ($40, 0.5 h); with a duty, 3 h a day. ``rate``: two readings (about
    2.95 h a day); else today's alone, so no rate."""
    cv = m.create_position("Conveyor CV-3")["id"]
    if duty:
        m.set_operating_plan(cv, {"background": {"kind": "rate", "amount": 3, "per": "day"}})
    hours = m.add_point(cv, "Hours run", kind="counter", unit="hours")["id"]
    if rate:
        m.record_reading(hours, 1000, on="2026-10-01")
    m.record_reading(hours, 1180, on="2026-12-01")
    idlers = m.create_task(cv, "Inspect idlers", 250, "hours", last_done="2026-10-01")["id"]
    walk = m.create_task(cv, "Belt walk", 1, "weeks", last_done="2026-11-30")["id"]
    return cv, idlers, walk


def _names(out):
    return {t["name"]: t for t in out["tasks"]}


# ---- the four cases: calendar or hours, with or without a duty ------------------------------------

def test_calendar_with_a_duty_dates_both_kinds(monkeypatch):
    _clock(monkeypatch)
    m = _m()
    cv, idlers, walk = _conveyor(m, duty=True)
    out = fd.forecast_details(m, cv, basis="calendar", period="month", end="2027-11-30")
    assert out["default_basis"] == "calendar" and out["duty"] is not None and out["assumed"] is None
    assert len(out["rows"]) == 12 and out["rows"][0]["start"] == "2026-12-01" and out["rows"][-1]["end"] == "2027-11-30"
    by = _names(out)
    # 250 h from 1,000 h is 1,250 h: 70 h on at 3 h a day, 24 Dec (the library's plan map).
    assert by["Inspect idlers"]["dates"][0] == "2026-12-24"
    assert by["Belt walk"]["count"] == 52
    assert out["not_placed"] == []
    # 12 months: this month and the next 11, so 12 rows by month.
    twelve = fd.forecast_details(m, cv, basis="calendar", period="month", months=12)
    assert len(twelve["rows"]) == 12 and twelve["end"] == "2027-11-30"
    assert sum(r["tasks"] for r in out["rows"]) == out["totals"]["tasks"] == by["Belt walk"]["count"] + by[
        "Inspect idlers"]["count"]


def test_no_duty_uses_the_readings_rate_and_agrees_with_next_due(monkeypatch):
    """No duty: the rate the running-hours readings give (Derryn, 23 Nov 2026: duty, then a measured
    rate, then 24 h a day), the same map as the task's next due, so the dates agree."""
    _clock(monkeypatch)
    m = _m()
    cv, idlers, walk = _conveyor(m, duty=False)
    out = fd.forecast_details(m, cv, basis="calendar", period="month", end="2027-11-30")
    by = _names(out)
    view = m._task_view(m.s.node(m.org, idlers))
    assert view["limits"][0]["basis"]["kind"] == "rate"
    # 180 h in 61 days is about 2.95 h a day: 70 h more is 23.7 days on, 24 Dec.
    assert by["Inspect idlers"]["dates"][0] == view["next_due"] == "2026-12-24"
    assert by["Inspect idlers"]["moments"][0] == view["limits"][0]["due_moment"]
    assert out["assumed"]["kind"] == "rate"
    assert out["assumed"]["text"] == "From its running-hours readings, about 2.95 h a day (no duty set). Set a duty in Operations."
    assert f"plan={cv}" in out["assumed"]["link"] and "tab=operations" in out["assumed"]["link"]
    # By running hours, the weekly walk goes through the same rate: about 20.7 h a week.
    hours = fd.forecast_details(m, cv, basis="hours", hours=1000, every=250)
    assert _names(hours)["Inspect idlers"]["hours"] == [70, 320, 570, 820]
    assert 47 <= _names(hours)["Belt walk"]["count"] <= 49
    # The plain forecast (MCP) agrees.
    plain = {t["name"]: t for t in pf.position_forecast(m, cv, periods=12)["tasks"]}
    assert plain["Inspect idlers"]["dates"][0] == "2026-12-24"


def test_calendar_with_no_duty_or_rate_assumes_it_runs_all_the_time(monkeypatch):
    """No duty and one reading: 24 h a day from it, said once with where to set a duty; next due agrees."""
    _clock(monkeypatch)
    m = _m()
    cv, idlers, walk = _conveyor(m, duty=False, rate=False)
    out = fd.forecast_details(m, cv, basis="calendar", period="month", end="2027-11-30")
    by = _names(out)
    view = m._task_view(m.s.node(m.org, idlers))
    # No reading when it was last done: counted from the first, 1,180 h on 1 Dec; 250 h on at 24 h a
    # day is 11 Dec at 10:00, then every 10 days 10 h.
    assert by["Inspect idlers"]["dates"][:2] == ["2026-12-11", "2026-12-21"]
    assert by["Inspect idlers"]["moments"][:2] == ["2026-12-11T10:00", "2026-12-21T20:00"]
    assert view["next_due"] == "2026-12-11" and view["limits"][0]["basis"]["kind"] == "continuous"
    assert out["not_placed"] == [] and out["assumed"]["kind"] == "continuous"
    assert out["assumed"]["text"] == "No duty or readings: assuming it runs all the time (24 h a day). Set a duty in Operations."
    assert out["totals"]["tasks"] == by["Belt walk"]["count"] + by["Inspect idlers"]["count"]


def test_hours_with_a_duty_places_both_kinds(monkeypatch):
    _clock(monkeypatch)
    m = _m()
    cv, idlers, walk = _conveyor(m, duty=True)
    out = fd.forecast_details(m, cv, basis="hours", hours=1000, every=100)
    assert len(out["rows"]) == 10 and out["rows"][0]["from_hours"] == 0 and out["rows"][-1]["to_hours"] == 1000
    assert out["reading"] == 1180 and out["rows"][0]["reading_from"] == 1180 and out["assumed"] is None
    by = _names(out)
    # 1,250, 1,500, ... 2,000 h: 70, 320, 570 and 820 h from now.
    assert by["Inspect idlers"]["hours"] == [70, 320, 570, 820]
    # The weekly walk through the duty: 21 h a week, so about 47 in 1,000 h.
    assert 46 <= by["Belt walk"]["count"] <= 48
    assert out["not_placed"] == []
    assert [r["tasks"] for r in out["rows"]][0] >= 5  # 100 h is about 4.8 weeks of walks, plus an idler check
    assert out["totals"]["planned_cost"] is not None


def test_hours_without_a_duty_converts_the_calendar_at_24_hours_a_day(monkeypatch):
    _clock(monkeypatch)
    m = _m()
    cv, idlers, walk = _conveyor(m, duty=False, rate=False)
    out = fd.forecast_details(m, cv, basis="hours", hours=1000, every=250)
    by = _names(out)
    assert by["Inspect idlers"]["hours"] == [250, 500, 750, 1000]
    # The weekly walk (last done 30 Nov) at 168 h a week: 7 Dec is 144 h on, then every 168 h.
    assert by["Belt walk"]["hours"] == [144, 312, 480, 648, 816, 984]
    assert out["not_placed"] == [] and out["assumed"]["kind"] == "continuous"
    # Each span takes what falls up to its end: 250 h is in "0 to 250 h".
    assert [r["tasks"] for r in out["rows"]] == [2, 3, 2, 3]
    first = out["occurrences"][0]
    assert first["hours"] == 144 and first["kind"] == "task" and first["name"] == "Belt walk"


def test_the_default_basis_follows_the_duty_and_the_tasks(monkeypatch):
    _clock(monkeypatch)
    m = _m()
    cv, idlers, walk = _conveyor(m, duty=False)
    # One by use, one on the calendar, no duty: the calendar.
    assert fd.forecast_details(m, cv)["default_basis"] == "calendar"
    m.create_task(cv, "Grease", 100, "hours", last_done="2026-10-01")
    assert fd.forecast_details(m, cv)["basis"] == "hours"
    # A task alone: its own kind.
    assert fd.forecast_details(m, cv, task_ids=[idlers])["default_basis"] == "hours"
    assert fd.forecast_details(m, cv, task_ids=[walk])["default_basis"] == "calendar"


# ---- grouping, horizon, one task, a package -------------------------------------------------------

def test_grouped_by_day_and_week(monkeypatch):
    _clock(monkeypatch)
    m = _m()
    cv, idlers, walk = _conveyor(m, duty=True)
    days = fd.forecast_details(m, cv, basis="calendar", period="day", end="2026-12-31", task_ids=[walk])
    assert len(days["rows"]) == 31 and sum(r["tasks"] for r in days["rows"]) == 4
    weeks = fd.forecast_details(m, cv, basis="calendar", period="week", end="2027-02-28", task_ids=[walk])
    # 1 Dec 2026 is a Tuesday: a part week, then whole Monday-to-Sunday weeks.
    assert weeks["rows"][0]["start"] == "2026-12-01" and weeks["rows"][1]["start"] == "2026-12-07"
    assert all(r["tasks"] == 1 for r in weeks["rows"][1:])
    with pytest.raises(Invalid, match="group by a longer period"):
        fd.forecast_details(m, cv, basis="calendar", period="day", end="2028-12-31")
    with pytest.raises(Invalid, match="ends before it starts"):
        fd.forecast_details(m, cv, basis="calendar", end="2026-11-01")


def test_one_task_counts_only_it(monkeypatch):
    _clock(monkeypatch)
    m = _m()
    cv, idlers, walk = _conveyor(m, duty=True)
    out = fd.forecast_details(m, cv, basis="calendar", end="2027-11-30", task_ids=[walk])
    assert out["subject"] == {"kind": "task", "id": walk, "name": "Belt walk"}
    assert [t["name"] for t in out["tasks"]] == ["Belt walk"]
    assert len(out["occurrences"]) == 52 and all(o["kind"] == "task" for o in out["occurrences"])
    assert out["occurrences"][0]["date"] == "2026-12-07"


def test_a_package_shows_which_tasks_ride_on_each_visit(monkeypatch):
    _clock(monkeypatch)
    m = _m()
    cv = m.create_position("Mower")["id"]
    hours = m.add_point(cv, "Hours", kind="counter", unit="hours")["id"]
    m.record_reading(hours, 0, on="2026-11-01")
    m.record_reading(hours, 20, on="2026-12-01")
    fifty = m.create_task(cv, "Grease deck", 50, "hours", last_done="2026-11-01")["id"]
    hundred = m.create_task(cv, "Change oil", 100, "hours", last_done="2026-11-01")["id"]
    pkg = m.create_package("50 h service", position_id=cv, every=50, unit="hours", anchor_reading=0)["id"]
    m.add_package_task(pkg, fifty)
    m.add_package_task(pkg, hundred, visit_rule="nth", every_nth=2)
    out = fd.forecast_details(m, cv, basis="hours", hours=200, every=50, package_id=pkg)
    visits = out["occurrences"]
    assert [v["hours"] for v in visits] == [30, 80, 130, 180]
    assert all(v["kind"] == "visit" and v["name"] == "50 h service" for v in visits)
    # The 100 h task on alternate 50 h visits.
    assert [[t["name"] for t in v["tasks"]] for v in visits] == [
        ["Grease deck"], ["Change oil", "Grease deck"], ["Grease deck"], ["Change oil", "Grease deck"]]
    assert out["subject"]["kind"] == "package"


def test_the_rest_route(api, monkeypatch):  # noqa: F811
    from backend.routers import maintenance as router

    _clock(monkeypatch)
    m = Maintenance(router._store, UID, "tester")
    cv = m.create_position("Conveyor R")["id"]
    walk = m.create_task(cv, "Belt walk", 1, "weeks", last_done="2026-11-30")["id"]
    r = api.get(f"/api/maintenance/positions/{cv}/forecast/details",
                params={"basis": "calendar", "period": "month", "end": "2027-11-30", "task_id": walk})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["basis"] == "calendar" and len(body["rows"]) == 12 and body["subject"]["kind"] == "task"
    r = api.get(f"/api/maintenance/positions/{cv}/forecast/details", params={"basis": "hours", "hours": 100,
                                                                           "every": 0})
    assert r.status_code in (400, 422) and "hours" in r.json()["detail"]
    r = api.get(f"/api/maintenance/positions/{cv}/forecast", params={"end": "2027-11-30", "strict": "true"})
    assert r.status_code == 200 and r.json()["end"] == "2027-11-30"
    assert date.fromisoformat(r.json()["start"]) <= date(2026, 12, 1)


@pytest.mark.parametrize("duty", [True, False])
def test_failures_from_a_life_in_hours_by_running_hours(monkeypatch, duty):
    """A wear ring's Weibull life in hours (alpha 9,000, beta 2.5), 5,200 h old: its failures in each
    500 h window are RePyability's cost_by_window, with or without a duty (hours are hours)."""
    import surpyval as surv
    from repyability import NonRepairable

    from backend.maintenance import position_models as pm
    from backend.tests.test_maintenance_forecast_engine import RING, _model_db

    _clock(monkeypatch)
    m = _m(org="org-fc-life")
    db = _model_db("org-fc-life")
    fetch = pm.fetcher(db, ["org-fc-life"])
    ring = m.create_position("Wear ring")["id"]
    m.update_position(ring, position_class="Rings")
    m.set_class_costs("Rings", planned_cost=100, failure_cost=4800)
    if duty:
        m.set_operating_plan(ring, {"background": {"kind": "rate", "amount": 16, "per": "day"}})
    hours = m.add_point(ring, "Ring hours", kind="counter", unit="hours")["id"]
    m.record_reading(hours, 7140, on="2026-03-01")
    m.fit(ring, new_item={"name": "Ring SN1"}, on="2026-03-01")
    m.record_reading(hours, 12340, on="2026-12-01")
    pm.link_saved(m, db, ["org-fc-life"], set(), ring, "model", RING["id"])
    out = fd.forecast_details(m, ring, basis="hours", hours=2000, every=500, fetch=fetch)
    part = NonRepairable(surv.Weibull.from_params([9000.0, 2.5]), unplanned_cost=4800.0)
    lib = part.cost_by_window([500.0, 1000.0, 1500.0, 2000.0], None, age=5200.0, levels=(5.0, 95.0))
    want = [w.expected_failures for w in lib.windows]
    assert [r["failures"] for r in out["rows"]] == [pytest.approx(w, rel=1e-3) for w in want]
    assert out["totals"]["failure_cost"] == pytest.approx(lib.total.mean, abs=0.01)
    assert out["totals"]["failures_range"] is not None and out["rows"][0]["failures_range"] is not None
    assert out["range"].startswith("90% range")
