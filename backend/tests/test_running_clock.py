"""A model's running hours meeting the calendar at a position (running_clock; Derryn, 21 Nov 2026):
through the position's duty where it has one (RePyability's DutyPlan), else running all the time,
24 h a day. Checked for the conversion itself, the RCM evidence check, the class proposals, a
Strategy calculation run from a position, the class forecast and the spares for the year."""

from __future__ import annotations

from datetime import date, timedelta
from types import SimpleNamespace

import pytest

from backend.maintenance import rcm_graph
from backend.maintenance.service import PROJECTORS, Maintenance, class_id
from backend.maintenance.store import GraphStore
from backend.services import running_clock as rc
from backend.services import strategy, strategy_calendar, strategy_store
from repyability.schedule import DutyPlan, Shifts

TODAY = date(2026, 11, 23)  # a Monday
EIGHT_A_DAY = {"background": {"kind": "shifts", "shifts": [
    {"days": ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"],
     "start": "08:00", "stop": "16:00"}]}}
WEEKDAYS_16 = {"background": {"kind": "shifts", "shifts": [
    {"days": ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"], "start": "06:00", "stop": "22:00"}]}}
WEIBULL_H = [{"name": "alpha", "value": 8000.0}, {"name": "beta", "value": 3.0}]


@pytest.fixture()
def db():
    import mongomock

    from backend.services import samples

    d = mongomock.MongoClient()["running_clock"]
    samples.seed_samples(d)
    return d


@pytest.fixture()
def m():
    out = Maintenance(GraphStore(":memory:", PROJECTORS), "user-clock", "tester")
    out.as_of = TODAY.isoformat()
    return out


# ---- the rule ----------------------------------------------------------------------------------

def test_eight_hours_a_day_gives_125_days_for_1000_running_hours():
    clock = rc.from_duty(DutyPlan(Shifts("Mon-Sun", "08:00", "16:00")), TODAY, "every day, 08:00 to 16:00")
    assert clock.basis == "duty" and clock.hours_per_day == pytest.approx(8.0) and clock.steady
    conv = rc.conversion("hours", "days", clock)
    assert 1000 * conv["factor"] == pytest.approx(125.0)
    assert rc.note(conv, 1000) == "1,000 h ≈ 125 days at this position's duty (8 h a day)"
    # And back: 125 days of the calendar are 1,000 running hours there.
    assert 125 * rc.conversion("days", "hours", clock)["factor"] == pytest.approx(1000.0)


def test_a_varying_duty_converts_at_repyabilitys_average_over_the_year():
    """16 h on weekdays and none at weekends: the hand calculation is RePyability's own share of the
    year running (DutyPlan.forecast(...).duty()), about 80 / 7 = 11.43 h a day."""
    plan = DutyPlan(Shifts("Mon-Fri", "06:00", "22:00"))
    by_hand = 24 * plan.forecast(TODAY, TODAY + timedelta(days=365)).duty()
    assert by_hand == pytest.approx(80 / 7, rel=2e-3)
    clock = rc.from_duty(plan, TODAY)
    assert clock.hours_per_day == pytest.approx(by_hand) and not clock.steady
    conv = rc.conversion("operating hours", "days", clock)
    assert 1000 * conv["factor"] == pytest.approx(1000 / by_hand)
    assert rc.note(conv, 1000) == f"1,000 h ≈ {strategy.fmt_num(1000 / by_hand)} days at this position's duty " \
                                  f"({strategy.fmt_num(by_hand)} h a day on average)"


def test_without_a_duty_it_runs_all_the_time():
    conv = rc.conversion("hours", "days", rc.CONTINUOUS)
    assert 1000 * conv["factor"] == pytest.approx(1000 / 24)
    assert rc.note(conv, 1000) == "1,000 h ≈ 41.7 days, assuming it runs all the time (no duty set for this position)"


def test_running_hours_units_and_units_that_arent_time():
    clock = rc.CONTINUOUS
    for unit in ("hours", "Hours", "hrs", "operating hours", "running hours", "flight hours", "FH"):
        assert rc.conversion(unit, "weeks", clock)["factor"] == pytest.approx(1 / (24 * 7)), unit
    # Cycles, km and starts have no rate to the calendar: never converted.
    for unit in ("cycles", "km", "starts", "landings"):
        assert rc.conversion(unit, "days", clock) is None
    assert rc.same_clock("flight hours", "hours")
    # No position (a stand-alone calculation): plain hours are calendar hours, as before, and say so;
    # flight hours don't convert.
    plain = rc.conversion("hours", "days", None)
    assert plain["factor"] == pytest.approx(1 / 24) and "clock" not in plain
    assert rc.note(plain, 1000, "task interval", "evidence").endswith("1 day = 24 hours (running all the time)")
    assert rc.conversion("flight hours", "days", None) is None


def test_a_position_runs_to_its_own_plan_or_the_one_above_else_all_the_time(m):
    station = m.create_position("Pump station")
    pump = m.create_position("Pump", parent_id=station["id"])
    other = m.create_position("Spare pump")
    m.set_operating_plan(station["id"], EIGHT_A_DAY, name="Day shift")
    m._memo.clear()
    own, below, none = (rc.for_position(m, p["id"]) for p in (station, pump, other))
    assert own.hours_per_day == pytest.approx(8) and own.inherited_from is None
    assert below.hours_per_day == pytest.approx(8) and below.inherited_from == "Pump station"
    assert rc.note(rc.conversion("hours", "days", below), 1000) == \
        "1,000 h ≈ 125 days at the duty it takes from Pump station (8 h a day)"
    assert none is rc.CONTINUOUS


# ---- the RCM evidence check --------------------------------------------------------------------

def _decided(m, name, unit):
    from backend.services.samples import SAMPLE_OWNER  # noqa: F401 - the sample analysis's owner

    pid = m.create_position(name)["id"]
    ff = m.add_functional_failure(m.add_function(pid, "Turn")["id"], "Seized")
    mode = m.add_failure_mode(pid, "Bearing fatigue", functional_failure_id=ff["id"])
    m.decide_failure_mode(mode["id"], "operational", {
        "outcome": "fixed_interval", "interval": 10, "interval_unit": unit,
        "evidence": {"type": "strategy_analysis", "id": "sample-strategy-bearing-replacement"}})
    return pid


def test_rcm_evidence_in_hours_meets_a_task_in_days_at_the_positions_duty(db):
    """The bearing sample's replacement analysis is in hours; the task is in days. On a position
    with an 8 h a day plan its hours are days at 8 a day, without one at 24 a day."""
    from backend.services.samples import SAMPLE_OWNER

    m = Maintenance(GraphStore(":memory:", PROJECTORS), "user-clock-rcm", "tester")
    owners = ["user-clock-rcm", SAMPLE_OWNER]
    duty = _decided(m, "Bearing on day shift", "days")
    m.set_operating_plan(duty, EIGHT_A_DAY)
    plain = _decided(m, "Bearing, no plan", "days")
    t = float(_sample_analysis(db)["results"]["optimal_time"])

    def got(pid):
        sheet = rcm_graph.resolve(db, m.rcm_worksheet(pid, "this"), owners, m=m)
        return sheet["positions"][0]["functions"][0]["failures"][0]["modes"][0]["decision"]

    on_duty, all_time = got(duty), got(plain)
    assert on_duty["status"] == "supported"
    assert on_duty["unit_conversion"] == f"{strategy.fmt_num(t)} h ≈ {strategy.fmt_num(t / 8)} days at this " \
                                         "position's duty (8 h a day)"
    assert f"about {strategy.fmt_num(t / 8)} days" in on_duty["summary"]
    assert all_time["unit_conversion"].endswith("assuming it runs all the time (no duty set for this position)")
    assert f"about {strategy.fmt_num(t / 24)} days" in all_time["summary"]
    # Off a position (an RCM study, or a read without the workspace): as before, 24 h a day, said so.
    bare = rcm_graph.resolve(db, m.rcm_worksheet(duty, "this"), owners)
    note = bare["positions"][0]["functions"][0]["failures"][0]["modes"][0]["decision"]["unit_conversion"]
    assert note == "evidence in hours, task interval in days: converted at 1 day = 24 hours (running all the time)"


def test_rcm_evidence_in_hours_and_a_task_in_flight_hours_are_one_clock_at_a_position(db):
    from backend.services.samples import SAMPLE_OWNER

    m = Maintenance(GraphStore(":memory:", PROJECTORS), "user-clock-fh", "tester")
    pid = _decided(m, "Actuator", "flight hours")
    sheet = rcm_graph.resolve(db, m.rcm_worksheet(pid, "this"), ["user-clock-fh", SAMPLE_OWNER], m=m)
    decision = sheet["positions"][0]["functions"][0]["failures"][0]["modes"][0]["decision"]
    assert decision["status"] != "inconclusive" and "Unit mismatch" not in str(decision)


def _sample_analysis(db):
    return db["strategy_analyses"].find_one({"_id": "sample-strategy-bearing-replacement"}) or \
        db["strategy_analyses"].find_one({"id": "sample-strategy-bearing-replacement"})


# ---- the class proposals -----------------------------------------------------------------------

def test_a_class_model_in_hours_proposes_a_task_in_days_at_each_positions_duty(m):
    from backend.maintenance import loop
    from backend.tests.rcm_tree import position_with_rcm

    def member(name, plan=None):
        functions = [{"id": "f", "text": "Pump", "failures": [{"id": "ff", "text": "Leaks", "modes": [
            {"id": "m1", "text": "Seal worn", "consequence": "operational",
             "decision": {"outcome": "fixed_interval", "interval": 30, "interval_unit": "days",
                          "task": "Replace seal"}}]}]}]
        pos = position_with_rcm(m, functions, name)["position"]
        m.update_position(pos["id"], name=name, position_class="Seal")
        if plan:
            m.set_operating_plan(pos["id"], plan)
        return pos["id"]

    day_shift, always = member("Pump A", EIGHT_A_DAY), member("Pump B")
    m.set_class_costs("Seal", planned_cost=400, failure_cost=4000)
    node = m.s.node(m.org, class_id(m.org, m._resolve_class("Seal")))
    m.s.patch_node(m.org, node["id"], {"model": {"distribution": "weibull", "unit": "hours", "failures": 8,
                                                 "suspensions": 2, "params": WEIBULL_H}})
    m._memo.clear()
    best = strategy.optimal_replacement("weibull", WEIBULL_H, 400, 4000, "hours")["optimal_time"]
    by_pos = {p["position"]["id"]: p for p in loop.propose(m, "Seal")}
    assert len(by_pos) == 2, by_pos
    a, b = by_pos[day_shift], by_pos[always]
    assert a["proposed"]["interval"] == loop._rounded(best / 8) and a["proposed"]["unit"] == "days"
    assert b["proposed"]["interval"] == loop._rounded(best / 24)
    assert "at this position's duty (8 h a day)" in a["reason"]
    assert "assuming it runs all the time" in b["reason"]


# ---- Strategy run from a position --------------------------------------------------------------

def test_optimal_replacement_from_a_position_gives_the_interval_on_its_calendar(m):
    pump = m.create_position("Pump")
    m.set_operating_plan(pump["id"], EIGHT_A_DAY)
    clock = rc.for_position(m, pump["id"])
    inputs = {"distribution_id": "weibull", "params": WEIBULL_H, "planned_cost": 400, "unplanned_cost": 4000,
              "unit": "hours"}
    plain = strategy_store.compute("optimal_replacement", inputs)
    out = strategy_store.compute("optimal_replacement", {**inputs, "hours_per_day": clock.hours_per_day,
                                                          "clock": clock.to_dict()})
    t = plain["optimal_time"]
    assert out["optimal_time"] == pytest.approx(t)  # the answer in the model's hours is unchanged
    assert out["calendar"]["value"] == pytest.approx(t / 8) and out["calendar"]["unit"] == "days"
    assert out["calendar"]["note"] == f"{strategy.fmt_num(t)} h ≈ {strategy.fmt_num(t / 8)} days at this " \
                                      "position's duty (8 h a day)"
    assert "calendar" not in plain


def test_the_strategy_routes_resolve_the_positions_clock(m, monkeypatch):
    from backend.maintenance import rbd_tree_plan
    from backend.routers import strategy as strategy_router

    pump = m.create_position("Pump")
    m.set_operating_plan(pump["id"], EIGHT_A_DAY)
    spare = m.create_position("Spare")
    monkeypatch.setattr(rbd_tree_plan, "maintenance_for", lambda ctx: m)
    got = strategy_router._position_clock(None, pump["id"], "hours")
    assert got["hours_per_day"] == pytest.approx(8) and got["clock"]["basis"] == "duty"
    assert strategy_router._position_clock(None, spare["id"], "flight hours")["hours_per_day"] == 24
    assert strategy_router._position_clock(None, pump["id"], "days") == {}  # a calendar model: nothing to do
    assert strategy_router._position_clock(None, None, "hours") == {}  # stand-alone: as before


def test_shutdown_replacement_from_a_position_meets_the_dates_at_its_duty():
    """A model in running hours at 8 h a day is the same life as one in days with an eighth of the
    scale: the shutdown calendar gives the same long-run cost a year for both."""
    shuts = [{"name": "Shut", "cost": 500, "every": 6, "every_unit": "months", "start": "2026-12-01"}]
    common = {"today": TODAY.isoformat(), "opportunities": shuts, "failure_cost": 5000, "horizon_months": 12}
    clock = rc.Clock(8.0, "duty")
    hours = strategy_calendar.calendar_replacement("weibull", WEIBULL_H, unit="hours", hours_per_day=8,
                                                   clock=clock.to_dict(), **common)
    days = strategy_calendar.calendar_replacement(
        "weibull", [{"name": "alpha", "value": 1000.0}, {"name": "beta", "value": 3.0}], unit="days", **common)
    assert hours["units_per_day"] == 8
    assert hours["cost_rate"] * 8 == pytest.approx(days["cost_rate"], rel=1e-6)
    assert hours["cost_per_year"] == pytest.approx(days["cost_per_year"], rel=1e-6)
    assert hours["convention"] == "Today is time 0. Dates become running hours at this position's duty (8 h a day)."
    assert hours["clock"]["basis"] == "duty"


# ---- the class forecast and the spares for the year --------------------------------------------

DIAPHRAGM = SimpleNamespace(kind="distribution", distribution_id="weibull", dataset_id="", spec={},
                            results={"distribution_id": "weibull", "unit": "hours", "params": WEIBULL_H})


def _pumps(m):
    """Two dosing pumps with a diaphragm life in running hours and no hours counter: one on an 8 h a
    day plan, one with none. Fitted 100 days ago."""
    m.as_of = (TODAY - timedelta(days=100)).isoformat()
    kit = m.create_part("DK-40", "Diaphragm kit", unit_cost=180)["id"]
    ids = {}
    for name, plan in (("Dosing pump A", EIGHT_A_DAY), ("Dosing pump B", None)):
        pid = m.create_position(name, position_class="Diaphragm")["id"]
        m.fit(pid, new_item={"name": f"{name} diaphragm"}, on=m.as_of)
        m.link_position_model(pid, "model", "diaphragm", name="Diaphragm life")
        m.add_position_part(pid, kit, quantity=1)
        if plan:
            m.set_operating_plan(pid, plan, from_=m.as_of)
        ids[name] = pid
    m.as_of = TODAY.isoformat()
    m._memo.clear()
    return ids


def test_the_spares_engine_ages_and_runs_a_life_in_hours_at_each_positions_duty(m):
    from backend.maintenance import spares_year as sy

    ids = _pumps(m)
    positions = [m.s.node(m.org, pid) for pid in ids.values()]
    fetch = lambda kind, mid: DIAPHRAGM if kind == "model" else None  # noqa: E731
    units, not_forecast, _ = sy._units(m, positions, root=None, horizon_days=365, fetch=fetch, class_only=False,
                                       leave_out=set())
    assert not_forecast == []
    by = {u["id"]: u for u in units}
    a, b = by[ids["Dosing pump A"]], by[ids["Dosing pump B"]]
    assert a["per_day"] == pytest.approx(8) and a["age"] == pytest.approx(800)
    assert b["per_day"] == pytest.approx(24) and b["age"] == pytest.approx(2400)
    assert a["clock"]["basis"] == "duty" and b["clock"]["basis"] == "continuous"


def test_the_class_forecast_uses_the_duty_without_an_hours_counter(m):
    from backend.maintenance import forecast

    ids = _pumps(m)
    fitment = m.current_fitment(ids["Dosing pump A"])
    use = forecast._use_age(m, ids["Dosing pump A"], fitment, "hours", 365)
    assert use["per_day"] == pytest.approx(8) and use["age"] == pytest.approx(800) and use["basis"] == "duty"
    assert use["note"] == "No hours counter: age 800 h ≈ 100 days at this position's duty (8 h a day) since it was fitted."
    none = forecast._use_age(m, ids["Dosing pump B"], m.current_fitment(ids["Dosing pump B"]), "hours", 365)
    assert none["per_day"] == 24 and none["basis"] == "continuous"
    # A unit of use that isn't time still needs its counter.
    assert "reason" in forecast._use_age(m, ids["Dosing pump B"], fitment, "cycles", 365)
