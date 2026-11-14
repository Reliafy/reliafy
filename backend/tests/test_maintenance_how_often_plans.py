"""How often (a task's or package's pattern: how_often.py) and operating plans (how a position
runs: operating_plan.py), Nov 2026. New events only (task.rule_set, operating_plan.set,
operating_plan.ended); a rebuilt graph equals the live one."""

from datetime import date

import pytest

from backend.maintenance import how_often
from backend.maintenance import operating_plan as op
from backend.maintenance.schedule import Cadence
from backend.maintenance.service import PROJECTORS, Invalid, Maintenance
from backend.maintenance.store import GraphStore
from backend.tests.test_maintenance_mcp import _do, _get, _ok, _session, env  # noqa: F401
from backend.tests.test_maintenance_rcm_api import api  # noqa: F401

ORG = "user-a"
M = "/api/maintenance"
TODAY = "2026-11-14"
FIRST_SATURDAY = {"kind": "monthly", "every": 1, "weekday": "Saturday", "nth": 1}
NOVEMBER_TUESDAY = {"kind": "yearly", "month": 11, "weekday": "Tuesday", "nth": 1}
WEEKDAYS_6_TO_22 = {"background": {"kind": "shifts", "shifts": [
    {"days": ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"], "start": "06:00", "stop": "22:00"}]}}


@pytest.fixture()
def m():
    out = Maintenance(GraphStore(":memory:", PROJECTORS), ORG, "tester")
    out.today = lambda: TODAY
    return out


def _rebuilds_the_same(m):
    before = m.s.snapshot()
    m.s.rebuild()
    assert m.s.snapshot() == before


def _events(m, type):
    return [e for e in m.s.events(ORG, 1000) if e["type"] == type]


# ---- the rule shape and its dates ------------------------------------------------------------

def test_yearly_and_fifth_weekday_dates_match_the_hand_worked_ones():
    yearly = Cadence(1, "years", TODAY, weekday="Tuesday", nth=1, month=11)
    assert [d.isoformat() for d in yearly.dates(TODAY, "2029-12-31")] == ["2027-11-02", "2028-11-07", "2029-11-06"]
    monthly = how_often.cadence(how_often.check_rule(FIRST_SATURDAY), TODAY)
    assert [d.isoformat() for d in monthly.dates(TODAY, "2027-03-31")] == [
        "2026-12-05", "2027-01-02", "2027-02-06", "2027-03-06"]
    fifth = Cadence(1, "months", "2027-01-01", weekday="Saturday", nth=5)
    assert [d.isoformat() for d in fifth.dates("2027-01-01", "2027-12-31")] == [
        "2027-01-30", "2027-05-29", "2027-07-31", "2027-10-30"]
    leap = Cadence(1, "years", "2027-01-01", day=29, month=2)
    assert [d.isoformat() for d in leap.dates("2027-01-01", "2028-12-31")] == ["2027-02-28", "2028-02-29"]


def test_rules_are_checked_and_said_in_words():
    assert how_often.check_rule({"kind": "weekly", "weekdays": ["sat"]})["weekdays"] == ["Saturday"]
    assert how_often.describe(how_often.check_rule(FIRST_SATURDAY)) == "the first Saturday of every month"
    assert how_often.describe(how_often.check_rule(NOVEMBER_TUESDAY)) == "the first Tuesday of November, every year"
    assert how_often.describe(how_often.check_rule({"kind": "monthly", "every": 3, "weekday": "Fri", "nth": -1})) \
        == "the last Friday of every 3 months"
    assert how_often.describe(how_often.check_rule({"kind": "yearly", "month": 7, "day": 1})) == "1 July, every year"
    for bad in ({"kind": "monthly", "weekday": "Saturday"}, {"kind": "yearly", "weekday": "Tuesday", "nth": 1},
                {"kind": "monthly", "day": 15, "weekday": "Monday", "nth": 1}, {"kind": "fortnightly"},
                {"kind": "monthly", "weekday": "Saturday", "nth": 0}, {"kind": "weekly", "weekdays": ["Mon", "Tue"]}):
        with pytest.raises(ValueError):
            how_often.check_rule(bad)


def test_a_packages_cadence_reads_into_the_same_shape():
    pkg = {"every": 1, "unit": "months", "pattern": {"weekday": "Saturday", "nth": 1}, "anchor": TODAY}
    assert how_often.rule_of_package(pkg) == {**FIRST_SATURDAY, "anchor": TODAY, "version": 1}
    assert how_often.rule_of_package({"every": 2, "unit": "weeks", "pattern": None, "anchor": TODAY})["kind"] == "every"


# ---- a task's rule ---------------------------------------------------------------------------

def test_a_task_on_the_first_saturday_falls_due_on_those_dates(m):
    pump = m.create_position("Pump")
    task = m.create_task(pump["id"], "Inspect", None, rule=FIRST_SATURDAY)
    assert (task["interval"], task["unit"]) == (1, "months")
    assert task["rule"]["weekday"] == "Saturday" and task["rule_text"] == "the first Saturday of every month"
    assert task["next_due"] == "2026-12-05"
    assert _events(m, "task.rule_set")[0]["payload"] == {"task_id": task["id"],
                                                            "rule": {**FIRST_SATURDAY, "version": 1, "anchor": TODAY}}
    done = m.set_last_done(task["id"], "2026-11-07")
    assert done["next_due"] == "2026-12-05"
    _rebuilds_the_same(m)


def test_a_yearly_rule_on_a_task_and_clearing_it(m):
    pump = m.create_position("Pump")
    task = m.create_task(pump["id"], "Shutdown overhaul", 12, "months")
    view = m.update_task(task["id"], rule=NOVEMBER_TUESDAY)
    assert (view["interval"], view["unit"], view["next_due"]) == (1, "years", "2027-11-02")
    # A new interval is its schedule now: the pattern goes.
    plain = m.update_task(task["id"], interval=6, unit="months")
    assert plain["rule"] is None and plain["next_due"] == "2027-05-14"
    m.update_task(task["id"], rule=FIRST_SATURDAY)
    cleared = m.update_task(task["id"], rule={})
    assert cleared["rule"] is None and (cleared["interval"], cleared["unit"]) == (1, "months")
    _rebuilds_the_same(m)


def test_a_rule_needs_a_calendar_task(m):
    pump = m.create_position("Pump")
    task = m.create_task(pump["id"], "Service", 2000, "hours")
    with pytest.raises(Invalid, match="goes by use"):
        m.set_task_rule(task["id"], FIRST_SATURDAY)
    with pytest.raises(Invalid, match="nth"):
        m.create_task(pump["id"], "Bad", None, rule={"kind": "monthly", "weekday": "Saturday"})


# ---- a package's yearly cadence ---------------------------------------------------------------

def test_a_package_on_the_first_tuesday_of_november(m):
    pump = m.create_position("Pump")
    t = m.create_task(pump["id"], "Overhaul", 12, "months")
    pkg = m.create_package("Annual shut", position_id=pump["id"], every=1, unit="years", weekday="Tuesday", nth=1,
                           month=11, tasks=[t["id"]])
    assert pkg["cadence"]["text"] == "the first Tuesday of November, every year"
    assert pkg["cadence"]["rule"]["kind"] == "yearly" and pkg["next_visit"] == "2027-11-02"
    back = m.update_package(pkg["id"], month=12, weekday="Tuesday", nth=1)
    assert back["next_visit"] == "2026-12-01"
    with pytest.raises(Invalid, match="month"):
        m.create_package("Bad", position_id=pump["id"], every=1, unit="months", day=3, month=4)
    _rebuilds_the_same(m)


# ---- operating plans: the arithmetic ----------------------------------------------------------

def test_specific_runs_hand_over_to_the_background_with_no_extra_hours():
    """Derryn's rule: where runs end (Tue 03:30) the background (3 h a day) counts only the time
    they don't cover, pro rata: Tue = 3.5 h of runs + 3 × 20.5 / 24; every day's total is its parts."""
    plan = op.check_plan({"background": {"kind": "rate", "amount": 3, "per": "day"},
                          "specific": [{"runs": [["2026-11-14T12:31", "2026-11-15T03:27"],
                                                 ["2026-11-16T12:30", "2026-11-17T03:30"]]}]})
    assert plan["specific"][0]["covers"] == ["2026-11-14T00:00", "2026-11-17T03:30"]
    days = {d["date"]: d for d in op.hours_by_day(plan, date(2026, 11, 13), 6)}
    assert days["2026-11-13"]["hours"] == pytest.approx(3.0)
    assert days["2026-11-14"]["hours"] == pytest.approx(11 + 29 / 60)       # runs only: 12:31 to midnight
    assert days["2026-11-15"]["hours"] == pytest.approx(3 + 27 / 60)        # runs only: no background inside
    assert days["2026-11-17"]["hours"] == pytest.approx(3.5 + 3 * 20.5 / 24)  # the handover day
    assert days["2026-11-17"]["spread"] == pytest.approx(3 * 20.5 / 24)
    assert days["2026-11-18"]["hours"] == pytest.approx(3.0)
    for d in days.values():
        assert d["hours"] == pytest.approx(sum(r["to"] - r["from"] for r in d["runs"]) + d["spread"])


def test_a_shift_background_is_clipped_where_runs_cover():
    plan = op.check_plan({**WEEKDAYS_6_TO_22, "specific": [{"runs": [["2026-11-16T08:00", "2026-11-16T12:00"]],
                                                           "covers": ["2026-11-16T00:00", "2026-11-16T12:00"]}]})
    monday = op.day_runs(plan, date(2026, 11, 16))
    assert [(r["from"], r["to"], r["layer"]) for r in monday["runs"]] == [(8, 12, "specific"), (12, 22, "background")]
    assert monday["hours"] == 14
    assert op.typical_week(plan) == 80 and op.describe(plan).startswith("Monday to Friday, 06:00 to 22:00")


def test_plans_are_checked():
    for bad, words in (({"background": {"kind": "rate", "amount": 30, "per": "day"}}, "number"),
                       ({"background": {"kind": "shifts", "shifts": [{"days": ["Mon"], "start": "06:00",
                                                                     "stop": "06:00"}]}}, "same"),
                       ({"background": {"kind": "continuous"},
                         "specific": [{"runs": [["2026-11-14T10:00", "2026-11-14T12:00"],
                                                ["2026-11-14T11:00", "2026-11-14T13:00"]]}]}, "overlap"),
                       ({"background": {"kind": "shifts", "shifts": [
                           {"days": ["Mon"], "start": "06:00", "stop": "14:00"},
                           {"days": ["Mon"], "start": "12:00", "stop": "20:00"}]}}, "overlap"),
                       ({"background": {"kind": "weekly"}}, "background")):
        with pytest.raises(op.PlanError, match=words):
            op.check_plan(bad)
    roster = op.check_plan({"background": {"kind": "roster", "on": 4, "off": 4, "anchor": "2026-11-16",
                                           "start": "07:00", "stop": "19:00"}})
    assert op.typical_week(roster) == pytest.approx(42)


# ---- operating plans: the records -------------------------------------------------------------

def test_a_plan_on_a_position_is_inherited_below_it_and_items_run_as_their_position(m):
    station = m.create_position("Pump station 1")
    pump = m.create_position("Pump P-101", parent_id=station["id"])
    seal = m.create_position("Seal", parent_id=pump["id"])
    out = m.set_operating_plan(station["id"], WEEKDAYS_6_TO_22, name="Day shifts")
    assert out["plan"]["hours_per_week"] == 80 and out["plan"]["status"] == "current" and out["inherited_from"] is None
    assert len(out["days"]) == 14 and out["days"][2]["hours"] == 16  # Mon 16 Nov
    below = m.operating_plan(seal["id"])
    assert below["inherited_from"] == {"id": station["id"], "name": "Pump station 1"} and below["own"] == []
    # Asset isolation: opened at the pump, the station's plan isn't looked for.
    assert m.operating_plan(seal["id"], root=pump["id"])["plan"] is None
    item = m.create_item("P-101 pump", serial="SN1")
    m.fit(pump["id"], item["id"])
    as_item = m.operating_plan(item["id"])
    assert as_item["plan"]["id"] == out["plan"]["id"] and as_item["inherited_from"]["id"] == station["id"]
    with pytest.raises(Invalid, match="position"):
        m.set_operating_plan(item["id"], WEEKDAYS_6_TO_22)
    # Its own plan overrides; ending it goes back to the one above.
    own = m.set_operating_plan(pump["id"], {"background": {"kind": "continuous"}})
    assert own["inherited_from"] is None and own["plan"]["hours_per_week"] == 168
    assert m.operating_plan(seal["id"])["inherited_from"]["id"] == pump["id"]
    ended = m.end_operating_plan(pump["id"])
    assert ended["inherited_from"]["id"] == station["id"] and ended["own"][0]["status"] == "ended"
    _rebuilds_the_same(m)


def test_a_new_plan_from_a_date_ends_the_one_before_and_the_past_stays(m):
    pump = m.create_position("Pump")
    first = m.set_operating_plan(pump["id"], WEEKDAYS_6_TO_22)
    later = m.set_operating_plan(pump["id"], {"background": {"kind": "rate", "amount": 15, "per": "month"}},
                                 from_="2027-03-01")
    assert later["plan"]["id"] == first["plan"]["id"]  # still today's
    assert [p["status"] for p in later["own"]] == ["current", "planned"]
    assert later["own"][0]["until"] == "2027-03-01"
    with pytest.raises(Invalid, match="starts later"):
        m.set_operating_plan(pump["id"], {"background": {"kind": "continuous"}}, from_="2027-01-01")
    with pytest.raises(Invalid, match="time zone"):
        m.set_operating_plan(pump["id"], {"background": {"kind": "continuous"}}, time_zone="Mars/Olympus")
    assert [e["payload"]["until"] for e in _events(m, "operating_plan.ended")] == ["2027-03-01"]
    _rebuilds_the_same(m)


def test_operating_plan_over_rest(api):
    pos = api.post(f"{M}/positions", json={"name": "Conveyor CV-3"}).json()
    r = api.put(f"{M}/positions/{pos['id']}/operating-plan",
                json={"plan": {"background": {"kind": "rate", "amount": 3, "per": "day"}}, "name": "About 3 h a day"})
    assert r.status_code == 200, r.text
    assert r.json()["plan"]["hours_per_week"] == 21 and r.json()["plan"]["text"] == "About 3 hours a day"
    assert api.get(f"{M}/positions/{pos['id']}/operating-plan").json()["plan"]["name"] == "About 3 h a day"
    assert api.put(f"{M}/positions/{pos['id']}/operating-plan", json={"plan": {}}).status_code == 422
    assert api.post(f"{M}/positions/{pos['id']}/operating-plan/end", json={}).json()["plan"] is None
    task = api.post(f"{M}/positions/{pos['id']}/tasks", json={"name": "Inspect", "rule": FIRST_SATURDAY}).json()
    assert task["rule_text"] == "the first Saturday of every month"
    r = api.patch(f"{M}/tasks/{task['id']}", json={"rule": None, "interval": 2, "unit": "weeks"})
    assert r.status_code == 200 and r.json()["rule"] is None


def test_operating_plan_and_rules_over_mcp(env):
    async def flow(client):
        pos = _ok(await _do(client, "maintenance", "positions.create", name="Generator"))["id"]
        set_ = _ok(await _do(client, "maintenance", "positions.update", position_id=pos, operating_plan={
            "plan": {"background": {"kind": "rate", "amount": 15, "per": "month"}}}))
        got = _ok(await _get(client, "operating_plan", pos))
        task = _ok(await _do(client, "maintenance", "tasks.create", position_id=pos, name="Overhaul",
                             rule=NOVEMBER_TUESDAY))
        pkg = _ok(await _do(client, "maintenance", "packages.create", name="Shut", position_id=pos, every=1,
                            unit="years", weekday="tuesday", nth=1, month=11, tasks=[task["id"]]))
        ended = _ok(await _do(client, "maintenance", "positions.update", position_id=pos, end_operating_plan=True))
        return set_, got, task, pkg, ended

    set_, got, task, pkg, ended = _session(env["token"], flow)
    assert set_["plan"]["text"] == "About 15 hours a month" and got["plan"]["id"] == set_["plan"]["id"]
    assert task["unit"] == "years" and task["rule_text"] == "the first Tuesday of November, every year"
    assert pkg["cadence"]["month"] == 11
    assert ended["plan"] is None
