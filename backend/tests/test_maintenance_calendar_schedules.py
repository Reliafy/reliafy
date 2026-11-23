"""Calendar schedules on tasks and packages (Nov 2026): every N hours, every N days, weeks or
months, a calendar rule, or at each planned shutdown. The dates are RePyability's
(``repyability.schedule``) through how_often.py and schedule.py; nothing here does date maths
of its own. New rule kinds only (task.rule_set), so a rebuilt graph equals the live one."""


import pytest

from backend.maintenance import how_often
from backend.maintenance import position_forecast as pf
from backend.maintenance.service import PROJECTORS, Invalid, Maintenance
from backend.maintenance.shutdowns import shutdown_dates
from backend.maintenance.store import GraphStore
from backend.tests.test_maintenance_rcm_api import api  # noqa: F401 - fixture

ORG = "user-a"
TODAY = "2026-12-01"
FIRST_SATURDAY = {"kind": "monthly", "every": 1, "weekday": "Saturday", "nth": 1}


@pytest.fixture()
def m():
    out = Maintenance(GraphStore(":memory:", PROJECTORS), ORG, "tester")
    out.today = lambda: TODAY
    return out


def _dates(rule, start, end, anchor=None):
    checked = how_often.check_rule(rule)
    return [d.isoformat() for d in how_often.cadence(checked, anchor or start).dates(start, end)]


def _rebuilds_the_same(m):
    before = m.s.snapshot()
    m.s.rebuild()
    assert m.s.snapshot() == before


# ---- each type's dates -----------------------------------------------------------------------

def test_first_saturday_of_each_month_from_1_december_2026():
    assert _dates(FIRST_SATURDAY, "2026-12-01", "2027-02-28") == ["2026-12-05", "2027-01-02", "2027-02-06"]


def test_every_n_days_weeks_and_months():
    assert _dates({"kind": "every", "every": 10, "unit": "days"}, "2026-12-01", "2026-12-31") == [
        "2026-12-01", "2026-12-11", "2026-12-21", "2026-12-31"]
    assert _dates({"kind": "every", "every": 2, "unit": "weeks"}, "2026-12-01", "2026-12-31") == [
        "2026-12-01", "2026-12-15", "2026-12-29"]
    assert _dates({"kind": "every", "every": 1, "unit": "months"}, "2027-01-31", "2027-03-31") == [
        "2027-01-31", "2027-02-28", "2027-03-31"]


def test_every_second_tuesday():
    rule = {"kind": "weekly", "every": 2, "weekdays": ["Tuesday"], "anchor": "2026-12-01"}
    assert _dates(rule, "2026-12-01", "2027-01-15") == ["2026-12-01", "2026-12-15", "2026-12-29", "2027-01-12"]
    assert how_often.describe(how_often.check_rule(rule)) == "every 2 weeks on Tuesday"


def test_1_march_and_1_september_each_year():
    rule = {"kind": "monthly", "every": 6, "day": 1, "anchor": "2027-03-01"}
    assert _dates(rule, "2026-12-01", "2028-12-31") == ["2027-03-01", "2027-09-01", "2028-03-01", "2028-09-01"]
    assert how_often.describe(how_often.check_rule(rule)) == "the 1st of March and September"


def test_the_last_day_of_each_quarter():
    rule = {"kind": "monthly", "every": 3, "day": 31, "anchor": "2026-12-01"}
    assert _dates(rule, "2026-12-01", "2027-12-31") == ["2026-12-31", "2027-03-31", "2027-06-30", "2027-09-30",
                                                        "2027-12-31"]
    assert how_often.describe(how_often.check_rule(rule)) == \
        "the last day of March, June, September and December"
    assert how_often.describe(how_often.check_rule({"kind": "monthly", "every": 1, "day": 31})) == \
        "the last day of every month"


def test_a_shutdowns_rule_is_checked_and_said_in_words():
    rule = how_often.check_rule({"kind": "shutdowns", "every": 12, "unit": "months"})
    assert rule == {"kind": "shutdowns", "every": 12, "unit": "months", "version": 1}
    assert how_often.describe(rule) == "at the first planned shutdown 12 months after it was last done"
    assert how_often.interval_of(rule) == (12, "months")
    for bad in ({"kind": "shutdowns", "every": 12}, {"kind": "shutdowns", "every": 1, "unit": "hours"},
                {"kind": "shutdowns", "every": 1, "unit": "months", "weekday": "Monday"}):
        with pytest.raises(ValueError):
            how_often.check_rule(bad)
    with pytest.raises(ValueError, match="shutdowns"):
        how_often.cadence(rule, TODAY)


def test_nearest_rule_keeps_the_pattern():
    rule = how_often.check_rule({**FIRST_SATURDAY, "anchor": TODAY})
    near = how_often.nearest_rule(rule, 80, "days")
    assert near["every"] == 3 and near["weekday"] == "Saturday" and near["nth"] == 1
    assert how_often.nearest_rule(rule, 5, "days")["every"] == 1  # never less than every one
    weekly = how_often.check_rule({"kind": "weekly", "weekdays": ["Monday"]})
    assert how_often.nearest_rule(weekly, 1.2, "months")["every"] == 5
    assert how_often.nearest_rule({"kind": "every", "every": 1, "unit": "months"}, 3, "months") is None


# ---- on a task, and its forecast ------------------------------------------------------------

def _forecast_row(m, pos_id, task_id):
    out = pf.position_forecast(m, pos_id, root=pos_id, period="month", periods=12)
    return next(t for t in out["tasks"] if t["id"] == task_id), out


def test_a_forecast_over_12_months_counts_the_first_saturday_12_times(m):
    pump = m.create_position("Pump")
    task = m.create_task(pump["id"], "Inspect", None, rule=FIRST_SATURDAY)
    assert task["next_due"] == "2026-12-05"
    row, _ = _forecast_row(m, pump["id"], task["id"])
    assert row["count"] == 12
    assert row["dates"][:3] == ["2026-12-05", "2027-01-02", "2027-02-06"]


def test_a_quarterly_rule_counts_4_in_a_year(m):
    pump = m.create_position("Pump")
    task = m.create_task(pump["id"], "Quarterly check", None,
                         rule={"kind": "monthly", "every": 3, "day": 31, "anchor": "2026-12-01"})
    assert task["rule_text"] == "the last day of March, June, September and December"
    row, _ = _forecast_row(m, pump["id"], task["id"])
    assert row["count"] == 4


def _shutdown(m, pos_id, dates, scope=None):
    pkg = m.create_package("Annual shut", position_id=pos_id, every=1, unit="years", anchor=TODAY)
    m.set_package_shutdown(pkg["id"], {"duration_hours": 72, "dates": dates,
                                       **({"scope": scope} if scope else {})})
    return pkg


def test_a_task_at_shutdowns_waits_for_the_first_shut_after_its_interval(m):
    plant = m.create_position("Plant")
    pump = m.create_position("Pump", parent_id=plant["id"])
    _shutdown(m, plant["id"], ["2027-03-10", "2027-06-15", "2027-11-20", "2028-05-02"])
    # The plant's shutdowns reach the pump inside it.
    assert [x["on"] for x in shutdown_dates(m, pump["id"], TODAY, "2027-12-31")] == [
        "2027-03-10", "2027-06-15", "2027-11-20"]
    task = m.create_task(pump["id"], "Replace the seal", None,
                         rule={"kind": "shutdowns", "every": 6, "unit": "months"})
    assert task["rule_text"] == "at the first planned shutdown 6 months after it was last done"
    assert (task["interval"], task["unit"]) == (6, "months")
    # Made 1 Dec 2026: due from 1 Jun 2027, done at the 15 Jun shut.
    assert task["next_due"] == "2027-06-15"
    done = m.set_last_done(task["id"], "2026-11-01")
    assert done["next_due"] == "2027-06-15"
    row, _ = _forecast_row(m, pump["id"], task["id"])
    # 15 Jun 2027; then 6 months on is 15 Dec 2027, and the next shut is May 2028: past the year.
    assert row["count"] == 1
    _rebuilds_the_same(m)


def test_a_task_at_shutdowns_with_none_planned_says_so(m):
    pump = m.create_position("Pump")
    task = m.create_task(pump["id"], "Replace the seal", None,
                         rule={"kind": "shutdowns", "every": 12, "unit": "months"})
    assert task["next_due"] is None
    assert any("no planned shutdown" in (lim.get("note") or "") for lim in task["limits"])
    out = pf.position_forecast(m, pump["id"], root=pump["id"], period="month", periods=12)
    assert any("no planned shutdown" in x["reason"] for x in out["not_on_dates"])


def test_a_shutdown_scoped_to_another_position_doesnt_reach_this_one(m):
    plant = m.create_position("Plant")
    pump = m.create_position("Pump", parent_id=plant["id"])
    fan = m.create_position("Fan", parent_id=plant["id"])
    _shutdown(m, plant["id"], ["2027-03-10"], scope=[fan["id"]])
    assert shutdown_dates(m, pump["id"], TODAY, "2027-12-31") == []
    assert [x["on"] for x in shutdown_dates(m, fan["id"], TODAY, "2027-12-31")] == ["2027-03-10"]


def test_a_task_at_shutdowns_goes_on_a_position(m):
    store = m.create_location("Store")
    task = m.create_task(None, "Count", 12, "months", location_id=store["id"])
    with pytest.raises(Invalid, match="position"):
        m.set_task_rule(task["id"], {"kind": "shutdowns", "every": 12, "unit": "months"})


def test_the_preview_dates_for_each_type(m):
    plant = m.create_position("Plant")
    _shutdown(m, plant["id"], ["2027-03-10", "2027-06-15"])
    first = m.schedule_dates(FIRST_SATURDAY, start="2026-12-01", count=5)
    assert first["dates"] == ["2026-12-05", "2027-01-02", "2027-02-06", "2027-03-06", "2027-04-03"]
    assert first["words"] == "the first Saturday of every month"
    plain = m.schedule_dates({"kind": "every", "every": 3, "unit": "months"}, start="2026-12-01", count=2,
                             after=True)
    assert plain["dates"] == ["2027-03-01", "2027-06-01"]
    shut = m.schedule_dates({"kind": "shutdowns", "every": 2, "unit": "months"}, start="2026-12-01", count=5,
                            position_id=plant["id"])
    assert shut["dates"] == ["2027-03-10", "2027-06-15"]
    assert shut["shutdowns"][0]["package"]["name"] == "Annual shut"
    with pytest.raises(Invalid, match="position"):
        m.schedule_dates({"kind": "shutdowns", "every": 2, "unit": "months"}, start="2026-12-01")


def test_a_package_on_set_dates_counts_from_its_anchor(m):
    out = m.schedule_dates({"kind": "every", "every": 2, "unit": "weeks", "anchor": "2026-11-02"},
                           start="2026-11-14", count=3)
    assert out["dates"] == ["2026-11-16", "2026-11-30", "2026-12-14"]


def test_the_preview_route(api):
    r = api.post("/api/maintenance/schedule/dates", json={"rule": FIRST_SATURDAY, "start": "2026-12-01", "count": 3})
    assert r.status_code == 200, r.text
    assert r.json()["dates"] == ["2026-12-05", "2027-01-02", "2027-02-06"]
    bad = api.post("/api/maintenance/schedule/dates", json={"rule": {"kind": "monthly", "weekday": "Saturday"}})
    assert bad.status_code == 422 and "nth" in bad.json()["detail"]
