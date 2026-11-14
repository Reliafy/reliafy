"""Maintenance forecasting on RePyability's schedule module (Nov 2026): the app's stored rule and
plan shapes read through the library, usage tasks put on dates through a position's operating
plan, and the forecast on a position (Example A, B and C of the forecasting plan, worked by hand
and checked against the library called directly), with inheritance, asset isolation, plan
against actual and the states the screen shows."""

import json
from datetime import date, datetime, timezone

import mongomock
import pytest

from backend.maintenance import how_often, position_forecast as pf, position_models as pm, schedule
from backend.maintenance import operating_plan as op
from backend.maintenance.service import PROJECTORS, Maintenance
from backend.maintenance.store import GraphStore
from backend.tests.test_maintenance_mcp import _do, _get, _ok, _session, env  # noqa: F401
from backend.tests.test_maintenance_rcm_api import UID, api  # noqa: F401

ORG = "org-forecast"
M = "/api/maintenance"
WEEKDAYS_6_TO_22 = {"background": {"kind": "shifts", "shifts": [
    {"days": ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"], "start": "06:00", "stop": "22:00"}]}}
RING = {"_id": "ring-model", "id": "ring-model", "name": "Wear ring life", "kind": "distribution",
        "distribution_id": "weibull", "dataset_id": "ds-ring", "spec": {"unit": "hours"}, "status": "ready",
        "results": {"distribution_id": "weibull", "distribution": "Weibull", "unit": "hours",
                    "params": [{"name": "alpha", "value": 9000.0}, {"name": "beta", "value": 2.5}]}}


def _clock(monkeypatch, day: str):
    """Today is ``day`` (readings on it aren't "in the future")."""
    from backend.services import time_zones

    monkeypatch.setattr(time_zones, "_now", lambda: datetime.fromisoformat(day).replace(hour=8, tzinfo=timezone.utc))


def _m(org=ORG, store=None):
    return Maintenance(store or GraphStore(":memory:", PROJECTORS), org, "tester")


def _model_db(owner):
    db = mongomock.MongoClient()["forecast_engine"]
    db.models.insert_one({**RING, "owner_id": owner, "created_at": datetime(2026, 1, 1),
                          "updated_at": datetime(2026, 1, 1)})
    return db


def _rebuilds_the_same(m):
    before = m.s.snapshot()
    m.s.rebuild()
    assert m.s.snapshot() == before


# ---- stored shapes read through the library ---------------------------------------------------

#: Rules as tasks store them (task.rule_set, Nov 2026) and package cadences (packages keep their own).
STORED_RULES = [
    {"kind": "monthly", "every": 1, "weekday": "Saturday", "nth": 1, "anchor": "2026-11-14", "version": 1},
    {"kind": "yearly", "every": 1, "month": 11, "weekday": "Tuesday", "nth": 1, "anchor": "2026-11-14", "version": 1},
    {"kind": "weekly", "every": 2, "weekdays": ["Monday"], "anchor": "2026-11-16", "version": 1},
    {"kind": "monthly", "every": 3, "day": 30, "anchor": "2027-01-01", "version": 1},
    {"kind": "yearly", "every": 1, "month": 2, "day": 29, "anchor": "2027-01-01", "version": 1},
    {"kind": "monthly", "every": 1, "weekday": "Saturday", "nth": 5, "anchor": "2027-01-01", "version": 1},
    {"kind": "every", "every": 2, "unit": "weeks", "anchor": "2026-07-15", "version": 1},
]
STORED_PACKAGES = [
    {"every": 1, "unit": "weeks", "anchor": "2026-11-02", "pattern": {"weekday": "Saturday"}},
    {"every": 1, "unit": "months", "anchor": "2026-11-01", "pattern": {"weekday": "Saturday", "nth": 1}},
    {"every": 3, "unit": "months", "anchor": "2026-12-01", "pattern": {"weekday": "Saturday", "nth": 1}},
    {"every": 1, "unit": "years", "anchor": "2026-11-14", "pattern": {"weekday": "Tuesday", "nth": 1, "month": 11}},
    {"every": 1, "unit": "months", "anchor": "2027-01-31", "pattern": None},
    {"every": 10, "unit": "days", "anchor": "2026-11-01", "pattern": None},
]
STORED_PLANS = [
    WEEKDAYS_6_TO_22,
    {"background": {"kind": "continuous"}},
    {"background": {"kind": "roster", "on": 4, "off": 4, "anchor": "2026-11-16", "start": "07:00", "stop": "19:00"}},
    {"background": {"kind": "rate", "amount": 3, "per": "day"}},
    {"background": {"kind": "rate", "amount": 15, "per": "month"}, "utilisation": 0.8},
    {"background": {"kind": "runs", "runs": [["2026-11-14T12:31", "2026-11-15T03:27"]]}},
    {"background": {"kind": "rate", "amount": 3, "per": "day"},
     "specific": [{"runs": [["2026-11-14T12:31", "2026-11-15T03:27"], ["2026-11-15T12:30", "2026-11-16T03:30"]],
                   "covers": ["2026-11-14T00:00", "2026-11-16T03:30"]}]},
    {"background": {"kind": "shifts", "shifts": [{"days": ["Monday", "Friday"], "start": "06:00", "stop": "14:00"},
                                                 {"days": ["Saturday"], "start": "22:00", "stop": "06:00"}]}},
]


@pytest.mark.parametrize("rule", STORED_RULES)
def test_a_stored_rule_round_trips_through_the_librarys_shape(rule):
    checked = how_often.check_rule(rule)
    saved = how_often.to_library(checked)
    assert saved["kind"] == "recurrence" and saved["version"] == 1
    assert how_often.from_library(saved) == checked
    # The same dates from the stored shape and from the library's.
    cad = how_often.cadence(checked, checked["anchor"])
    assert cad.dates("2026-11-01", "2029-12-31") == schedule.Recurrence.from_dict(saved).dates(
        max("2026-11-01", checked["anchor"]), "2029-12-31")


@pytest.mark.parametrize("pkg", STORED_PACKAGES)
def test_a_stored_package_cadence_gives_the_same_dates_as_the_librarys_rule(pkg):
    from backend.maintenance.service import Maintenance as Ms

    cad = Ms._cadence(pkg)
    rule = how_often.rule_of_package({**pkg, "pattern": pkg["pattern"] or {}})
    lib = schedule.Recurrence.from_dict(how_often.to_library(rule, pkg["anchor"]))
    assert cad.dates(pkg["anchor"], "2029-12-31") == lib.dates(pkg["anchor"], "2029-12-31")
    if not (pkg["pattern"] or {}).get("month"):  # the library reads a package's own cadence too
        assert lib.dates(pkg["anchor"], "2029-12-31") == schedule.Recurrence.from_dict(
            {k: v for k, v in pkg.items() if v is not None}).dates(pkg["anchor"], "2029-12-31")


@pytest.mark.parametrize("plan", STORED_PLANS)
def test_a_stored_plan_round_trips_through_the_librarys_shape(plan):
    checked = op.check_plan(plan)
    saved = schedule.plan_to_library(checked, "Australia/Brisbane", "2026-11-14")
    assert saved["kind"] == "duty_plan" and saved["time_zone"] == "Australia/Brisbane"
    back = schedule.plan_from_library(saved)
    if checked["background"]["kind"] == "runs":  # a background of runs only is dated by its runs already
        assert back["background"]["runs"] == checked["background"]["runs"]
    else:
        assert back == checked
    # And the library reads its own dict back to the same plan.
    assert schedule.DutyPlan.from_dict(saved).to_dict() == saved


def test_the_hand_worked_dates_come_from_the_library():
    """UC-2 and UC-4, and the new rules (plan 8): through the app's adapters."""
    weekly = schedule.Cadence(1, "weeks", "2026-07-15")
    assert len(weekly.dates("2026-10-11", "2026-12-31")) == 12
    assert [d.isoformat() for d in schedule.Cadence(1, "months", "2026-10-01", weekday="Tuesday", nth=1).dates(
        "2026-10-11", "2026-12-31")] == ["2026-11-03", "2026-12-01"]
    assert [d.isoformat() for d in schedule.Cadence(1, "months", "2026-10-01", day=30).dates(
        "2026-10-11", "2027-02-28")] == ["2026-10-30", "2026-11-30", "2026-12-30", "2027-01-30", "2027-02-28"]
    assert [d.isoformat() for d in schedule.Cadence(1, "months", "2027-01-01", weekday="Saturday", nth=5).dates(
        "2027-01-01", "2027-12-31")] == ["2027-01-30", "2027-05-29", "2027-07-31", "2027-10-30"]
    assert [d.isoformat() for d in schedule.Cadence(1, "years", "2026-11-14", weekday="Tuesday", nth=1,
                                                    month=11).dates("2026-11-14", "2029-12-31")] == [
        "2027-11-02", "2028-11-07", "2029-11-06"]


def test_the_hours_summary_is_the_librarys():
    plan = op.check_plan({"background": {"kind": "rate", "amount": 3, "per": "day"}, "specific": [
        {"runs": [["2026-11-14T12:31", "2026-11-15T03:27"], ["2026-11-15T12:30", "2026-11-16T03:30"]]}]})
    assert op.typical_week(op.check_plan(WEEKDAYS_6_TO_22)) == 80
    assert op.typical_week(op.check_plan({"background": {"kind": "rate", "amount": 3, "per": "day"},
                                          "utilisation": 0.5})) == pytest.approx(10.5)
    usage = schedule.duty_plan([{"plan": plan, "from": "2026-11-14", "until": None}]).forecast(
        "2026-11-14", "2026-11-17")
    # Pro-rata handover: the runs give 16 Nov 3.5 h to 03:30, the rate 3 x 20.5/24 for the rest of the day.
    assert usage.by_period("day").usage["hours"][2] == pytest.approx(6.0625)


# ---- Example A: a pump position with three tasks and a wear ring --------------------------------

def _example_a(m, db_owner_models=True):
    pump = m.create_position("Pump P-101")["id"]
    m.update_position(pump, position_class="Pumps")
    m.set_class_costs("Pumps", planned_cost=100, failure_cost=4800)
    ring = m.create_position("Wear ring", parent_id=pump)["id"]
    m.update_position(ring, position_class="Pumps")
    m.set_operating_plan(pump, WEEKDAYS_6_TO_22, name="Day shifts")
    hours = m.add_point(pump, "Hour meter", kind="counter", unit="hours")["id"]
    m.record_reading(hours, 12000, on="2026-06-01")
    m.record_reading(hours, 12340, on="2026-11-16")
    ring_hours = m.add_point(ring, "Ring hours", kind="counter", unit="hours")["id"]
    m.record_reading(ring_hours, 7140, on="2026-03-01")
    m.fit(ring, new_item={"name": "Ring SN1"}, on="2026-03-01")
    m.record_reading(ring_hours, 12340, on="2026-11-16")
    tasks = {
        "inspect": m.create_task(pump, "Inspect", 1, "weeks", rule={"kind": "weekly", "weekdays": ["Monday"]},
                                 last_done="2026-11-09")["id"],
        "service": m.create_task(pump, "Service", 2000, "hours", last_done="2026-06-01")["id"],
        "overhaul": m.create_task(pump, "Shutdown overhaul", 1, "years",
                                  rule={"kind": "yearly", "month": 11, "weekday": "Tuesday", "nth": 1})["id"],
    }
    return pump, ring, tasks


def _library_example_a():
    """Example A worked by the library alone (no app): the numbers the app must match."""
    from repyability import NonRepairable
    import surpyval as surv

    usage = schedule.DutyPlan(schedule.Shifts("Mon-Fri", "06:00", "22:00")).forecast(
        "2026-11-16", "2027-12-01", readings={"hours": 12_340})
    ring = NonRepairable(surv.Weibull.from_params([9000.0, 2.5]), unplanned_cost=4800.0)
    return usage, schedule.failures_by_period(ring, usage, "month", age=5200.0)


def test_example_a_end_to_end_through_the_api(api, monkeypatch):  # noqa: F811
    from backend import db as db_mod
    from backend.routers import maintenance as router

    _clock(monkeypatch, "2026-11-16")
    m = _m(UID, router._store)
    pump, ring, tasks = _example_a(m)
    db_mod.get_db().models.insert_one({**RING, "owner_id": UID, "created_at": datetime(2026, 1, 1),
                                       "updated_at": datetime(2026, 1, 1)})
    assert api.post(f"{M}/positions/{ring}/models", json={"model_type": "model", "model_id": "ring-model"}
                    ).status_code in (200, 201)

    # Due dates by use come through the plan: the moment the meter crosses 14,000 h, mid-run.
    service = api.get(f"{M}/tasks/{tasks['service']}/explain").json()["task"]
    limit = service["limits"][0]
    assert (service["next_due"], limit["due_moment"], limit["stop_after"]) == (
        "2027-04-08", "2027-04-08T18:00", "2027-04-08T22:00")
    assert limit["basis"]["kind"] == "plan" and "12,340 h on 16 Nov 2026" in limit["basis"]["text"]

    r = api.get(f"{M}/positions/{pump}/forecast")
    assert r.status_code == 200, r.text
    fc = r.json()
    usage, ring_fc = _library_example_a()
    months = usage.by_period("month")
    assert (fc["start"], fc["end"]) == ("2026-11-16", "2027-11-30") and len(fc["rows"]) == 13
    # Hours per month: the hand-worked 176, 368, 336, ... (and the library's own).
    assert [r["hours"] for r in fc["rows"]][:6] == [176, 368, 336, 320, 368, 352]
    assert [r["hours"] for r in fc["rows"]] == [round(h, 4) for h in months.usage["hours"]]
    by_name = {t["name"]: t for t in fc["tasks"]}
    assert by_name["Service"]["dates"] == ["2027-04-08", "2027-09-30"]
    assert by_name["Service"]["moments"] == ["2027-04-08T18:00", "2027-09-30T18:00"]
    assert by_name["Shutdown overhaul"]["dates"] == ["2027-11-02"]
    inspections = by_name["Inspect"]["dates"]
    assert len([d for d in inspections if d <= "2027-11-15"]) == 53 == len(
        schedule.Recurrence.weekly("Mon").dates("2026-11-16", "2027-11-15"))
    assert [r["tasks"] for r in fc["rows"]][:3] == [3, 4, 4]
    # Failures: 0.622 expected, 59.6% chance of at least one, about $2,988; the range 0 to 1 ($0 to $4,800).
    t = fc["totals"]
    assert t["failures"] == pytest.approx(0.622, abs=5e-4) and t["probability"] == pytest.approx(0.596, abs=5e-4)
    assert t["failure_cost"] == pytest.approx(ring_fc.total["expected_cost"], abs=0.01)
    assert round(t["failure_cost"]) == 2988 and t["failures_range"] == [0, 1] and t["cost_range"] == [0, 4800]
    assert [round(r["failure_cost"]) for r in fc["rows"][:3]] == [105, 227, 217]
    assert fc["answer"].startswith("To 30 Nov 2027: 58 tasks") and "0.62 failures expected (0 to 1, 90% range)" in \
        fc["answer"]
    # Each number says what it rests on.
    assert fc["hours_source"] == "plan" and "Monday to Friday, 06:00 to 22:00" in fc["hours_basis"]
    (model,) = fc["models"]
    assert model["age"] == 5200 and not model["placeholder"]
    assert "from Pump P-101" in model["rests_on"] and "Pumps class's failure cost" in model["rests_on"]
    assert fc["range"].startswith("90% range")
    _rebuilds_the_same(m)


def test_example_a_over_mcp(env, monkeypatch):  # noqa: F811
    """maintenance get.forecast and analyse schedule over MCP."""
    _clock(monkeypatch, "2026-11-16")

    async def flow(client):
        pos = _ok(await _do(client, "maintenance", "positions.create", name="Conveyor CV-3"))["id"]
        _ok(await _do(client, "maintenance", "positions.update", position_id=pos, operating_plan={
            "plan": {"background": {"kind": "rate", "amount": 3, "per": "day"}}}))
        fc = _ok(await _get(client, "forecast", pos))
        quarters = _ok(await client.call_tool("maintenance", {"action": "get.forecast", "args": {
            "id": pos, "period": "quarter", "periods": 4}}))
        dates = _ok(await client.call_tool("analyse", {"action": "schedule", "args": {
            "rule": {"kind": "monthly", "weekday": "Saturday", "nth": 1}, "start": "2026-11-14", "end": "2027-03-31"}}))
        hours = _ok(await client.call_tool("analyse", {"action": "schedule", "args": {
            "plan": {"background": {"kind": "runs", "runs": [["2026-11-14T12:31", "2026-11-15T03:27"]]}},
            "start": "2026-11-14", "end": "2026-11-15", "reading": 486.2, "read_at": "2026-11-14", "due_at": 500}}))
        return fc, quarters, dates, hours

    fc, quarters, dates, hours = _session(env["token"], flow)
    assert fc["period"] == "month" and fc["hours_source"] == "plan" and fc["totals"]["tasks"] == 0
    assert quarters["period"] == "quarter" and quarters["end"] == "2027-12-31"
    assert dates["dates"] == ["2026-12-05", "2027-01-02", "2027-02-06", "2027-03-06"]
    assert dates["words"] == "the first Saturday of every month" and dates["saved"] is False
    # Example D: 14 h 56 min; 486.2 h -> 501.13 h; 500 h crossed at 02:19 on Sunday, the stop at 03:27.
    assert hours["hours"] == pytest.approx(14.93, abs=0.01)
    assert hours["rows"][-1]["reading_at_end"] == pytest.approx(501.13, abs=0.01)
    assert (hours["due"]["moment"], hours["due"]["stop_after"]) == ("2026-11-15T02:19", "2026-11-15T03:27")


def test_analyse_schedule_refuses_what_it_cannot_work_out():
    from backend.services import schedule_calc as sc

    with pytest.raises(sc.ScheduleError, match="one of them"):
        sc.compute()
    with pytest.raises(sc.ScheduleError, match="kind"):
        sc.compute(rule={"kind": "fortnightly"})
    with pytest.raises(sc.ScheduleError, match="three years"):
        sc.compute(plan={"background": {"kind": "continuous"}}, start="2026-01-01", end="2030-01-01")
    with pytest.raises(sc.ScheduleError, match="time zone"):
        sc.compute(plan={"background": {"kind": "continuous"}}, time_zone="Mars/Olympus")
    # A zone counts real hours: a Saturday night shift in Sydney is 7 h the night the clocks go forward.
    night = {"background": {"kind": "shifts", "shifts": [{"days": ["Saturday"], "start": "22:00", "stop": "06:00"}]}}
    assert sc.compute(plan=night, start="2026-10-03", end="2026-10-04", time_zone="Australia/Sydney")["hours"] == 7
    assert sc.compute(plan=night, start="2026-10-03", end="2026-10-04", time_zone="Australia/Brisbane")["hours"] == 8


# ---- Example B: a conveyor on a general rate ------------------------------------------------------

def test_example_b_a_conveyor_on_a_rate(monkeypatch):
    _clock(monkeypatch, "2026-12-01")
    m = _m()
    m.today = lambda: "2026-12-01"
    cv = m.create_position("Conveyor CV-3")["id"]
    m.set_operating_plan(cv, {"background": {"kind": "rate", "amount": 3, "per": "day"}})
    hours = m.add_point(cv, "Hours run", kind="counter", unit="hours")["id"]
    m.record_reading(hours, 1000, on="2026-10-01")
    m.record_reading(hours, 1180, on="2026-12-01")
    idlers = m.create_task(cv, "Inspect idlers", 250, "hours", last_done="2026-10-01")
    view = m._task_view(m._get(idlers["id"], "Task"))
    assert view["next_due"] == "2026-12-24" and view["limits"][0]["due_moment"] == "2026-12-24T08:00"
    assert view["limits"][0]["basis"]["exact"] is False  # a rate is an assumption
    fc = pf.position_forecast(m, cv, periods=6)
    (task,) = fc["tasks"]
    assert task["dates"][:2] == ["2026-12-24", "2027-03-17"]
    # One every 83 days after that (250 h at 3 h a day = 83 1/3 days).
    assert (date.fromisoformat(task["dates"][2]) - date.fromisoformat(task["dates"][1])).days in (83, 84) \
        if len(task["dates"]) > 2 else True
    assert fc["hours_source"] == "plan" and fc["rows"][0]["hours"] == 93  # December: 31 days at 3 h


# ---- Example C: a standby generator, two limits ----------------------------------------------------

def test_example_c_the_calendar_limit_comes_first_and_says_so(monkeypatch):
    _clock(monkeypatch, "2026-11-16")
    m = _m()
    m.today = lambda: "2026-11-16"
    gen = m.create_position("Standby generator")["id"]
    m.set_operating_plan(gen, {"background": {"kind": "rate", "amount": 15, "per": "month"}}, from_="2026-11-14")
    hours = m.add_point(gen, "Hour meter", kind="counter", unit="hours")["id"]
    m.record_reading(hours, 400, on="2026-11-14")
    m.record_reading(hours, 401, on="2026-11-16")
    oil = m.create_task(gen, "Oil change", 250, "hours", also_interval=12, also_unit="months",
                        last_done="2026-11-14")
    view = m._task_view(m._get(oil["id"], "Task"))
    assert view["next_due"] == "2027-11-14"
    fc = pf.position_forecast(m, gen, periods=12)
    (task,) = fc["tasks"]
    assert task["dates"] == ["2027-11-14"] and task["limits"] == ["also"]
    assert any("set none of the dates" in n for n in task["notes"])


# ---- inheritance, asset isolation, plan against actual, states --------------------------------------

def test_a_child_runs_to_the_plan_above_and_isolation_stops_at_the_asset(monkeypatch):
    _clock(monkeypatch, "2026-11-16")
    m = _m()
    m.today = lambda: "2026-11-16"
    station = m.create_position("Pump station 1")["id"]
    pump = m.create_position("Pump P-101", parent_id=station)["id"]
    m.set_operating_plan(station, WEEKDAYS_6_TO_22, name="Day shifts")
    hours = m.add_point(pump, "Hour meter", kind="counter", unit="hours")["id"]
    m.record_reading(hours, 12000, on="2026-06-01")
    m.record_reading(hours, 12340, on="2026-11-16")
    task = m.create_task(pump, "Service", 2000, "hours", last_done="2026-06-01")
    view = m._task_view(m._get(task["id"], "Task"))
    assert view["next_due"] == "2027-04-08"
    assert view["limits"][0]["basis"]["inherited_from"] == {"id": station, "name": "Pump station 1"}
    fc = pf.position_forecast(m, station)
    assert fc["tasks"][0]["dates"] == ["2027-04-08", "2027-09-30"] and "from Pump station 1" in fc["tasks"][0]["rests_on"]
    # Opened at the pump: the station's plan isn't used; the pump's own readings give the recent rate.
    alone = pf.position_forecast(m, pump, root=pump)
    assert alone["hours_source"] == "rate" and "Pump station 1" not in json.dumps(alone)
    _rebuilds_the_same(m)


def test_two_assets_the_other_never_appears(monkeypatch):
    _clock(monkeypatch, "2026-11-16")
    m = _m()
    m.today = lambda: "2026-11-16"
    a = m.create_position("Site A")["id"]
    pump_a = m.create_position("Pump A", parent_id=a)["id"]
    b = m.create_position("Site B")["id"]
    pump_b = m.create_position("Pump B", parent_id=b)["id"]
    m.set_operating_plan(b, {"background": {"kind": "continuous"}})
    for pos in (pump_a, pump_b):
        m.create_task(pos, f"Inspect {pos[:4]}", 1, "months", last_done="2026-11-01")
    fc = pf.position_forecast(m, a, root=a)
    text = json.dumps(fc)
    assert pump_b not in text and b not in text and "Site B" not in text and "Pump B" not in text
    assert {t["position"]["id"] for t in fc["tasks"]} == {pump_a}
    with pytest.raises(Exception, match="inside the asset"):
        pf.position_forecast(m, pump_b, root=a)


def test_plan_against_actual_is_offered_as_utilisation_never_applied(monkeypatch):
    _clock(monkeypatch, "2026-11-16")
    m = _m()
    m.today = lambda: "2026-11-16"
    pump = m.create_position("Pump P-101")["id"]
    m.set_operating_plan(pump, WEEKDAYS_6_TO_22, from_="2026-08-01")
    hours = m.add_point(pump, "Hour meter", kind="counter", unit="hours")["id"]
    # The last 90 days: 18 Aug (Tue) to 16 Nov, 64 weekdays of the plan = 1,024 h; the meter (interpolated
    # to 18 Aug) ran 843.6 h of them: 82%.
    m.record_reading(hours, 10000, on="2026-08-17")
    m.record_reading(hours, 10853, on="2026-11-16")
    out = m.operating_plan(pump)
    aa = out["against_actual"]
    assert aa["from"] == "2026-08-18" and aa["planned_hours"] == 1024 and aa["actual_hours"] == pytest.approx(843.6, abs=0.1)
    assert aa["share"] == pytest.approx(0.824, abs=0.001)
    assert aa["proposal"]["utilisation"] == 0.82 and "Ran 82% of the plan" in aa["text"]
    assert out["plan"]["hours_per_week"] == 80  # nothing applied
    applied = m.set_operating_plan(pump, {**WEEKDAYS_6_TO_22, "utilisation": aa["proposal"]["utilisation"]})
    assert applied["plan"]["hours_per_week"] == pytest.approx(65.6) and "82% utilisation" in applied["plan"]["text"]
    assert applied["against_actual"]["proposal"] is None or applied["against_actual"]["proposal"]["utilisation"] != 0.82
    _rebuilds_the_same(m)


def test_the_states_the_screen_shows(monkeypatch):
    _clock(monkeypatch, "2026-11-16")
    m = _m()
    m.today = lambda: "2026-11-16"
    db = _model_db(ORG)
    db.models.insert_one({**RING, "_id": "typed", "id": "typed", "dataset_id": "", "owner_id": ORG,
                          "name": "Typed-in life"})
    db.models.insert_one({**RING, "_id": "cycles", "id": "cycles", "owner_id": ORG, "name": "Cycles life",
                          "results": {**RING["results"], "unit": "cycles"}})
    fetch = pm.fetcher(db, [ORG])
    site = m.create_position("Site")["id"]
    # No plan and no readings: a task by use can't go on dates.
    bare = m.create_position("Fan", parent_id=site)["id"]
    m.create_task(bare, "Grease", 500, "hours")
    # A life in cycles, with no cycles counter here.
    press = m.create_position("Press", parent_id=site)["id"]
    m.fit(press, new_item={"name": "Press SN1"}, on="2026-01-01")
    pm.link_saved(m, db, [ORG], set(), press, "model", "cycles")
    # A typed-in life: a placeholder, flagged.
    motor = m.create_position("Motor", parent_id=site)["id"]
    m.fit(motor, new_item={"name": "Motor SN1"}, on="2026-01-01")
    m.update_position(motor, position_class="Motors")
    m.set_operating_plan(motor, {"background": {"kind": "continuous"}}, from_="2026-01-01")
    meter = m.add_point(motor, "Hours", kind="counter", unit="hours")["id"]
    m.record_reading(meter, 0, on="2026-01-01")
    m.record_reading(meter, 7656, on="2026-11-16")
    pm.link_saved(m, db, [ORG], set(), motor, "model", "typed")
    fc = pf.position_forecast(m, site, fetch=fetch)
    kinds = {s["kind"] for s in fc["states"]}
    assert {"no_plan_no_readings", "unit_not_measured", "placeholder"} <= kinds
    assert [x["position"]["name"] for x in fc["not_on_dates"]] == ["Fan"]
    (model,) = fc["models"]
    assert model["placeholder"] and model["cost_per_failure"] is None and "no failure cost" in model["rests_on"]
    assert fc["totals"]["failure_cost"] is None and fc["totals"]["failures"] > 0
    # An ended plan: nothing runs after it.
    m.end_operating_plan(motor, until="2026-11-16")
    ended = pf.position_forecast(m, motor, fetch=fetch)
    assert "plan_ended" in {s["kind"] for s in ended["states"]} and ended["rows"][1]["hours"] == 0
    # Nothing is written as a reading.
    assert len(m.s.inn(m.org, meter, "OF")) == 2
