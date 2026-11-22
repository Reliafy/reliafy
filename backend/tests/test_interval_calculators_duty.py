"""The task card's P-F and failure-finding calculators, and the MCP analyse calculators, on a position:
running hours meet the calendar at its duty, else 24 h a day (running_clock; Derryn, 21 Nov 2026)."""

from __future__ import annotations

import pytest

from backend.maintenance.service import PROJECTORS, Maintenance
from backend.maintenance.store import GraphStore
from backend.services import rcm_intervals
from backend.services import running_clock as rc
from backend.tests.test_mcp import A, _call, _ok, env  # noqa: F401 - env is a fixture

EIGHT = rc.Clock(8.0, "duty").to_dict()
EIGHT_A_DAY = {"background": {"kind": "shifts", "shifts": [
    {"days": ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"],
     "start": "08:00", "stop": "16:00"}]}}


@pytest.fixture()
def m():
    out = Maintenance(GraphStore(":memory:", PROJECTORS), "user-ivc-km", "tester")
    out.as_of = "2026-11-23"
    return out


def test_a_pf_interval_in_running_hours_is_days_at_the_duty():
    on_duty = rcm_intervals.on_condition_interval(pf_interval=200, pf_unit="hours", clock=EIGHT)
    in_days = rcm_intervals.on_condition_interval(pf_interval=25, pf_unit="days")
    assert on_duty["recommended"] == in_days["recommended"] and on_duty["interval"] == pytest.approx(in_days["interval"])
    assert on_duty["unit_conversion"] == "200 h ≈ 25 days at this position's duty (8 h a day)"
    assert on_duty["summary"].endswith("(200 h ≈ 25 days at this position's duty (8 h a day).)")
    # No duty on the position: asked on the calendar, all the time (24 h a day).
    always = rcm_intervals.on_condition_interval(pf_interval=200, pf_unit="flight hours", unit="days",
                                                 clock=rc.CONTINUOUS.to_dict())
    assert always["unit_conversion"] == "200 h ≈ 8.33 days, assuming it runs all the time (no duty set for this position)"
    assert always["recommended"] == {"value": 4, "unit": "days"}
    # Nothing asked on the calendar and no duty: hours stay hours, never "every 4 days".
    hours = rcm_intervals.on_condition_interval(pf_interval=200, pf_unit="flight hours", clock=rc.CONTINUOUS.to_dict())
    assert "unit_conversion" not in hours and hours["recommended"] == {"value": 100, "unit": "flight hours"}
    # Stand-alone: an hours P-F interval answers in hours too.
    plain = rcm_intervals.on_condition_interval(pf_interval=200, pf_unit="hours")
    assert "unit_conversion" not in plain and plain["recommended"] == {"value": 100, "unit": "hours"}


def test_a_check_by_the_hour_meter_with_no_duty_stays_in_hours():
    """The P-F calculator in hours for a task in hours, on a position with no duty: every 63 hours
    (half of 127 h), not "every 2 days"."""
    out = rcm_intervals.on_condition_interval(pf_interval=127, pf_unit="hours", current_interval=50,
                                              current_unit="hours", clock=rc.CONTINUOUS.to_dict())
    assert out["recommended"] == {"value": 63, "unit": "hours"} and "unit_conversion" not in out
    assert out["summary"].startswith("Check every 63 hours") and out["current"]["within"] is True
    stand_alone = rcm_intervals.on_condition_interval(pf_interval=127, pf_unit="hours", current_interval=50,
                                                      current_unit="hours")
    assert stand_alone["recommended"] == {"value": 63, "unit": "hours"}


def test_the_task_now_in_running_hours_is_compared_at_the_duty():
    out = rcm_intervals.on_condition_interval(pf_interval=200, pf_unit="hours", current_interval=80,
                                              current_unit="hours", unit="days", clock=EIGHT)
    assert out["current"]["unit"] == "days" and out["current"]["value"] == pytest.approx(10)


def test_answered_in_running_hours_nothing_converts():
    asked = rcm_intervals.on_condition_interval(pf_interval=200, pf_unit="hours", unit="hours", clock=EIGHT)
    assert "unit_conversion" not in asked and asked["recommended"] == {"value": 100, "unit": "hours"}


def test_a_devices_model_in_running_hours_is_days_at_the_duty():
    weib = lambda a: [{"name": "alpha", "value": a}, {"name": "beta", "value": 1.5}]  # noqa: E731
    on_duty = rcm_intervals.failure_finding_interval(distribution_id="weibull", params=weib(8000.0),
                                                     model_unit="hours", target_unavailability=0.01, clock=EIGHT)
    in_days = rcm_intervals.failure_finding_interval(distribution_id="weibull", params=weib(1000.0),
                                                     model_unit="days", target_unavailability=0.01)
    assert on_duty["recommended"] == in_days["recommended"]
    assert on_duty["interval"] == pytest.approx(in_days["interval"], rel=1e-9)
    assert on_duty["unit_conversion"] == ("device's model in hours, answer in days: converted at this position's "
                                          "duty (8 h a day)")
    assert on_duty["clock"]["hours_per_day"] == 8
    plain = rcm_intervals.failure_finding_interval(distribution_id="weibull", params=weib(8000.0),
                                                   model_unit="hours", target_unavailability=0.01)
    assert "unit_conversion" not in plain and plain["recommended"] != on_duty["recommended"]


def test_a_saved_calculation_recomputes_at_the_duty_it_was_run_at():
    from backend.services import strategy_store

    inputs = {"pf_interval": 200, "pf_unit": "hours", "unit": "days", "hours_per_day": 8, "clock": EIGHT}
    assert strategy_store.compute("on_condition_interval", inputs)["recommended"] == {"value": 12, "unit": "days"}


def _pump(m):
    pid = m.create_position("Dosing pump")["id"]
    ff = m.add_functional_failure(m.add_function(pid, "Dose")["id"], "No flow")
    mode = m.add_failure_mode(pid, "Diaphragm torn", functional_failure_id=ff["id"])
    m.set_operating_plan(pid, EIGHT_A_DAY)
    m._memo.clear()
    return pid, mode["id"]


def test_the_task_cards_route_and_the_mcp_action_take_the_failure_modes_position(monkeypatch):
    from backend.maintenance import mcp_tools, rbd_tree_plan
    from backend.routers import maintenance as router

    m = Maintenance(GraphStore(":memory:", PROJECTORS), "user-ivc", "tester")
    pid, mode_id = _pump(m)
    monkeypatch.setattr(rbd_tree_plan, "maintenance_for", lambda ctx: m)
    body = router._interval_clock(None, {"pf_interval": 200, "pf_unit": "hours", "failure_mode_id": mode_id},
                                  "pf_unit")
    assert body["hours_per_day"] == pytest.approx(8) and "failure_mode_id" not in body
    assert rcm_intervals.on_condition_interval(**body)["unit_conversion"].startswith("200 h ≈ 25 days")
    # A P-F interval on the calendar needs nothing.
    assert router._interval_clock(None, {"pf_unit": "days", "failure_mode_id": mode_id}, "pf_unit") == {"pf_unit": "days"}
    assert mcp_tools._mode_clock(m, mode_id, "operating hours")["clock"]["basis"] == "duty"
    assert mcp_tools._mode_clock(m, None, "hours") == {}


def test_mcp_analyse_calculators_take_a_position(env, monkeypatch):
    """analyse optimal_replacement and failure_finding_interval with position_id: the answer on the
    calendar at its duty (the route's resolution, routers.strategy._position_clock)."""
    from backend.routers import strategy as strategy_router

    seen = []

    def clock(ctx, position_id, unit):
        seen.append((position_id, unit))
        return {"hours_per_day": 8.0, "clock": EIGHT} if rc.is_running_hours(unit) else {}

    monkeypatch.setattr(strategy_router, "_position_clock", clock)
    token = env.token[A]
    params = [{"name": "alpha", "value": 8000.0}, {"name": "beta", "value": 3.0}]
    out = _ok(_call(token, "analyse", {"action": "optimal_replacement", "distribution_id": "weibull", "params": params,
                                       "unit": "hours", "planned_cost": 400, "unplanned_cost": 4000,
                                       "position_id": "pos-1"}))
    assert out["calendar"]["value"] == pytest.approx(out["optimal_time"] / 8)
    assert out["calendar"]["note"].endswith("at this position's duty (8 h a day)")
    ff = _ok(_call(token, "analyse", {"action": "failure_finding_interval", "distribution_id": "weibull",
                                      "params": params, "unit": "hours", "target_availability": 0.99,
                                      "position_id": "pos-1"}))
    assert ff["calendar"]["value"] == pytest.approx(ff["interval"] / 8)
    without = _ok(_call(token, "analyse", {"action": "optimal_replacement", "distribution_id": "weibull",
                                           "params": params, "unit": "hours", "planned_cost": 400,
                                           "unplanned_cost": 4000}))
    assert "calendar" not in without
    assert seen == [("pos-1", "hours"), ("pos-1", "hours")]


# ---- use that isn't time: km through the duty's km a day, else a plain refusal -----------------

KM_REFUSAL = ("This model is in km, so it can't be read against days without knowing how far it goes. "
              "Set a duty in km per day for this position.")
HAUL = {"background": {"kind": "continuous"}, "meters": [{"meter": "km", "amount": 400, "per": "day"}]}
KM_CLOCK = rc.Clock(24.0, "duty", meters=(("km", 400.0),)).to_dict()
WEIB_KM = [{"name": "alpha", "value": 60000.0}, {"name": "beta", "value": 3.0}]


def _trucks(m):
    """Two haul trucks fitted 100 days ago, a tyre life in km and no km counter: one on a plan of
    400 km a day, one with no plan."""
    m.as_of = "2026-08-15"
    ids = {}
    for name, plan in (("Truck 1", HAUL), ("Truck 2", None)):
        pid = m.create_position(name, position_class="Haul tyre")["id"]
        m.fit(pid, new_item={"name": f"{name} tyre"}, on=m.as_of)
        if plan:
            m.set_operating_plan(pid, plan, from_=m.as_of)
        ids[name] = pid
    m.as_of = "2026-11-23"
    m._memo.clear()
    return ids


def test_a_plan_holds_km_a_day_and_the_clock_reads_it_through_repyability():
    from backend.maintenance import operating_plan as op
    from backend.maintenance import schedule

    plan = op.check_plan(HAUL)
    assert plan["meters"] == [{"meter": "km", "amount": 400, "per": "day"}]
    assert op.describe(plan) == "All the time; about 400 km a day"
    dp = schedule.duty_plan([{"plan": plan, "from": "2026-01-01", "until": None}])
    assert "km" in dp.meters() and schedule.plan_from_library(dp.to_dict())["meters"] == plan["meters"]
    from datetime import date

    clock = rc.from_duty(dp, date(2026, 11, 23))
    assert dict(clock.meters)["km"] == pytest.approx(400)
    conv = rc.conversion("km", "days", clock)
    assert 20000 * conv["factor"] == pytest.approx(50)
    assert rc.note(conv, 20000) == "20,000 km ≈ 50 days at this position's duty (400 km a day)"
    with pytest.raises(op.PlanError, match="come from how it runs"):
        op.check_plan({**HAUL, "meters": [{"meter": "starts", "amount": 4, "per": "day"}]})


def test_km_with_no_duty_refuses_and_hours_still_default_to_all_the_time():
    assert rc.refusal("km", "days", rc.CONTINUOUS) == KM_REFUSAL
    assert rc.refusal("Kilometres", "days", rc.CONTINUOUS) == KM_REFUSAL
    assert rc.refusal("hours", "days", rc.CONTINUOUS) is None
    assert rc.conversion("hours", "days", rc.CONTINUOUS)["factor"] == pytest.approx(1 / 24)
    # Off a position: as before (no conversion, no refusal).
    assert rc.refusal("km", "days", None) is None and rc.conversion("km", "days", None) is None


def test_rcm_evidence_in_km(monkeypatch):
    from types import SimpleNamespace

    from backend.maintenance import rcm_decisions

    analysis = SimpleNamespace(id="a1", name="Tyre replacement", kind="optimal_replacement", status="ready",
                               results={"unit": "km", "optimal_time": 20000.0, "beneficial": True, "savings": 0.3})
    decision = {"outcome": "fixed_interval", "interval": 40, "interval_unit": "days",
                "evidence": {"type": "strategy_analysis", "id": "a1"}}
    fetch = lambda kind, i: analysis  # noqa: E731
    on_duty = rcm_decisions.resolve_decision(decision, fetch, rc.Clock.from_dict(KM_CLOCK))
    assert on_duty["status"] == "supported" and "about 50 days" in on_duty["summary"]
    assert on_duty["unit_conversion"] == "20,000 km ≈ 50 days at this position's duty (400 km a day)"
    none = rcm_decisions.resolve_decision(decision, fetch, rc.CONTINUOUS)
    assert none["status"] == "inconclusive"
    assert none["reason"] == KM_REFUSAL.replace("This model", "This evidence")


def test_class_proposals_in_km(m):
    from backend.maintenance import loop
    from backend.maintenance.service import class_id
    from backend.tests.rcm_tree import position_with_rcm

    def member(name, plan):
        functions = [{"id": "f", "text": "Haul", "failures": [{"id": "ff", "text": "Flat", "modes": [
            {"id": "m1", "text": "Tyre worn", "consequence": "operational",
             "decision": {"outcome": "fixed_interval", "interval": 30, "interval_unit": "days",
                          "task": "Replace tyres"}}]}]}]
        pos = position_with_rcm(m, functions, name)["position"]
        m.update_position(pos["id"], name=name, position_class="Haul tyre")
        if plan:
            m.set_operating_plan(pos["id"], plan)
        return pos["id"]

    on_duty, none = member("Truck 1", HAUL), member("Truck 2", None)
    m.set_class_costs("Haul tyre", planned_cost=400, failure_cost=4000)
    node = m.s.node(m.org, class_id(m.org, m._resolve_class("Haul tyre")))
    m.s.patch_node(m.org, node["id"], {"model": {"distribution": "weibull", "unit": "km", "failures": 8,
                                                 "suspensions": 2, "params": WEIB_KM}})
    m._memo.clear()
    from backend.services import strategy

    best = strategy.optimal_replacement("weibull", WEIB_KM, 400, 4000, "km")["optimal_time"]
    refused: list = []
    made = {p["position"]["id"]: p for p in loop.propose(m, "Haul tyre", refused)}
    assert list(made) == [on_duty] and made[on_duty]["proposed"]["interval"] == loop._rounded(best / 400)
    assert "at this position's duty (400 km a day)" in made[on_duty]["reason"]
    assert refused == [{"position": {"id": none, "name": "Truck 2"}, "task": refused[0]["task"], "reason": KM_REFUSAL}]


def test_strategy_from_a_position_in_km():
    from backend.services import strategy_calendar, strategy_store
    from backend.services.strategy import StrategyError

    inputs = {"distribution_id": "weibull", "params": WEIB_KM, "planned_cost": 400, "unplanned_cost": 4000,
              "unit": "km"}
    on_duty = strategy_store.compute("optimal_replacement", {**inputs, "hours_per_day": 400, "clock": KM_CLOCK})
    assert on_duty["calendar"]["value"] == pytest.approx(on_duty["optimal_time"] / 400)
    none = strategy_store.compute("optimal_replacement", {**inputs, "clock": rc.CONTINUOUS.to_dict()})
    assert none["calendar"]["refused"] and none["calendar"]["note"] == KM_REFUSAL
    shuts = {"today": "2026-11-23", "failure_cost": 5000, "horizon_months": 12,
             "opportunities": [{"name": "Shut", "cost": 500, "every": 6, "every_unit": "months", "start": "2026-12-01"}]}
    out = strategy_calendar.calendar_replacement("weibull", WEIB_KM, unit="km", hours_per_day=400, clock=KM_CLOCK,
                                                 **shuts)
    assert out["units_per_day"] == 400
    assert out["convention"] == "Today is time 0. Dates become km at this position's duty (400 km a day)."
    with pytest.raises(StrategyError, match="Set a duty in km per day"):
        strategy_calendar.calendar_replacement("weibull", WEIB_KM, unit="km", clock=rc.CONTINUOUS.to_dict(), **shuts)


def test_forecast_and_spares_in_km(m):
    from types import SimpleNamespace

    from backend.maintenance import forecast
    from backend.maintenance import spares_year as sy

    ids = _trucks(m)
    use = forecast._use_age(m, ids["Truck 1"], m.current_fitment(ids["Truck 1"]), "km", 365)
    assert use["per_day"] == pytest.approx(400) and use["age"] == pytest.approx(100 * 400)
    none = forecast._use_age(m, ids["Truck 2"], m.current_fitment(ids["Truck 2"]), "km", 365)
    assert none["reason"] == f"no km counter here. {KM_REFUSAL}"
    tyre = SimpleNamespace(kind="distribution", distribution_id="weibull", dataset_id="", spec={},
                           results={"distribution_id": "weibull", "unit": "km", "params": WEIB_KM})
    kit = m.create_part("TY-1", "Haul tyre", unit_cost=9000)["id"]
    for pid in ids.values():
        m.link_position_model(pid, "model", "tyre", name="Tyre life")
        m.add_position_part(pid, kit, quantity=1)
    m._memo.clear()
    units, not_forecast, _ = sy._units(m, [m.s.node(m.org, p) for p in ids.values()], root=None, horizon_days=365,
                                       fetch=lambda k, i: tyre if k == "model" else None, class_only=False,
                                       leave_out=set())
    assert [u["id"] for u in units] == [ids["Truck 1"]] and units[0]["per_day"] == pytest.approx(400)
    assert not_forecast == [{"position": {"id": ids["Truck 2"], "name": "Truck 2"},
                             "reason": f"no km counter here. {KM_REFUSAL}"}]


def test_task_card_calculators_in_km():
    km = rc.Clock.from_dict(KM_CLOCK).to_dict()
    on_duty = rcm_intervals.on_condition_interval(pf_interval=2000, pf_unit="km", unit="days", clock=km)
    assert on_duty["recommended"] == rcm_intervals.on_condition_interval(pf_interval=5, pf_unit="days",
                                                                         unit="days")["recommended"]
    assert on_duty["unit_conversion"] == "2,000 km ≈ 5 days at this position's duty (400 km a day)"
    with pytest.raises(rcm_intervals.IntervalError) as err:
        rcm_intervals.on_condition_interval(pf_interval=2000, pf_unit="km", unit="days", clock=rc.CONTINUOUS.to_dict())
    assert str(err.value) == KM_REFUSAL.replace("This model", "This P-F interval")
    # Answered in km, nothing meets the calendar: as before.
    assert rcm_intervals.on_condition_interval(pf_interval=2000, pf_unit="km",
                                               clock=rc.CONTINUOUS.to_dict())["recommended"]["unit"] == "km"
    ff = rcm_intervals.failure_finding_interval(distribution_id="weibull", params=WEIB_KM, model_unit="km",
                                                target_unavailability=0.01, unit="days", clock=km)
    assert ff["unit_conversion"].endswith("at this position's duty (400 km a day)")
    with pytest.raises(rcm_intervals.IntervalError, match="Set a duty in km per day"):
        rcm_intervals.failure_finding_interval(distribution_id="weibull", params=WEIB_KM, model_unit="km",
                                               target_unavailability=0.01, unit="days", clock=rc.CONTINUOUS.to_dict())


def test_mcp_analyse_in_km_says_why_with_no_km_duty(env, monkeypatch):
    from backend.routers import strategy as strategy_router

    monkeypatch.setattr(strategy_router, "_position_clock", lambda ctx, pid, unit: {"clock": rc.CONTINUOUS.to_dict()})
    out = _ok(_call(env.token[A], "analyse", {"action": "optimal_replacement", "distribution_id": "weibull",
                                              "params": WEIB_KM, "unit": "km", "planned_cost": 400,
                                              "unplanned_cost": 4000, "position_id": "pos-1"}))
    assert out["calendar"]["note"] == KM_REFUSAL and out["optimal_time"] > 0
