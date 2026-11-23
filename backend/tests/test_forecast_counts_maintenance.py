"""The forecast's expected failures count the maintenance (Nov 2026): a replacement at an interval
takes failures off, an on-condition check takes off the failures whose warning it finds (its P-F
interval), a task that restores nothing leaves them as they are.

The worked case: a ride-on mower, 12 operating hours a week (about 600 h a year), on the maker's
25 h plan and on a 50 h plan. Hand check, a year of 600 h in the long run:

* spark plugs (Weibull scale 345.8 h, shape 2.581): inspected only, no warning to act on, so they
  run to failure: 600 / mean life (306.9 h) = 1.954 a year; replaced every 100 h: about 0.24;
* drive belt (Weibull scale 700.9 h, shape 1.188): cracking shows 127 h before it breaks, so a check
  every 25 h or 50 h finds every warning: 0 failures;
* three deck spindle bearings (Weibull scale 1,537 h, shape 3.04), the same life greased at 25 h or
  50 h: 3 x 600 / 1,372 h = 1.311 a year either way.

Breakdowns: about 3.3 a year on the 25 h plan, 1.55 on the 50 h plan.
"""

import math
from datetime import datetime

import mongomock
import pytest

from backend.maintenance import position_forecast as pf, position_models as pm
from backend.tests.test_maintenance_forecast_engine import _clock, _m, _rebuilds_the_same

ORG = "org-forecast-tasks"
TODAY = "2026-11-22"
PLUG = (345.8092446733276, 2.5808620343628226)
BELT = (700.8901065749543, 1.1884968004024286)
SPINDLE = (1536.7783816057677, 3.0383434806650134)


def _life(db, mid, name, alpha, beta):
    db.models.insert_one({"_id": mid, "id": mid, "name": name, "kind": "distribution", "distribution_id": "weibull",
                          "dataset_id": f"ds-{mid}", "spec": {"unit": "hours"}, "status": "ready", "owner_id": ORG,
                          "created_at": datetime(2026, 1, 1), "updated_at": datetime(2026, 1, 1),
                          "results": {"distribution_id": "weibull", "distribution": "Weibull", "unit": "hours",
                                      "params": [{"name": "alpha", "value": alpha}, {"name": "beta", "value": beta}]}})


def _db():
    db = mongomock.MongoClient()["forecast_tasks"]
    _life(db, "plug", "Spark plug life", *PLUG)
    _life(db, "belt", "Drive belt life", *BELT)
    _life(db, "spindle", "Spindle bearing life", *SPINDLE)
    db.strategy_analyses.insert_one({"_id": "belt-pf", "id": "belt-pf", "name": "Drive belt check interval (P-F)",
                                     "owner_id": ORG, "kind": "on_condition_interval",
                                     "inputs": {"pf_interval": 127, "pf_unit": "hours", "unit": "hours"},
                                     "results": {}})
    return db


def _mower(m, db, name, plan: int):
    """A mower on the 25 h plan (plan=25) or the 50 h plan (plan=50)."""
    top = m.create_position(name)["id"]
    m.fit(top, new_item={"name": f"{name} SN1"}, on=TODAY)
    m.set_operating_plan(top, {"background": {"kind": "rate", "amount": 12, "per": "week"}}, from_=TODAY)
    meter = m.add_point(top, "Hour meter", kind="counter", unit="hours")["id"]
    m.record_reading(meter, 0, on=TODAY)
    plug = m.add_failure_mode(top, "Spark plug electrode worn")["id"]
    belt = m.add_failure_mode(top, "Drive belt cracked and breaks")["id"]
    grease = m.add_failure_mode(top, "Spindle bearing worn out")["id"]
    if plan == 25:
        m.decide_failure_mode(plug, "operational", {"outcome": "on_condition", "task": "Inspect spark plug",
                                                    "interval": 25, "interval_unit": "hours"})
    else:
        m.decide_failure_mode(plug, "operational", {"outcome": "fixed_interval", "task": "Replace spark plugs",
                                                    "interval": 100, "interval_unit": "hours"})
    m.decide_failure_mode(belt, "operational", {"outcome": "on_condition", "task": "Check drive belt",
                                                "interval": plan, "interval_unit": "hours",
                                                "evidence": {"type": "strategy_analysis", "id": "belt-pf"}})
    # Greasing doesn't renew a bearing: it restores none of its age.
    m.decide_failure_mode(grease, "operational", {"outcome": "fixed_interval", "task": "Grease deck spindles",
                                                  "interval": plan, "interval_unit": "hours",
                                                  "restoration": {"kind": "kijima1", "restores": 0}})
    pm.link_saved(m, db, [ORG], set(), top, "model", "plug", [plug])
    pm.link_saved(m, db, [ORG], set(), top, "model", "belt", [belt])
    pm.link_saved(m, db, [ORG], set(), top, "model", "spindle", [grease])
    # Three bearings: two more, each its own position under the mower.
    for k in (2, 3):
        pos = m.create_position(f"Spindle {k}", parent_id=top)["id"]
        m.fit(pos, new_item={"name": f"Spindle {k} SN1"}, on=TODAY)
        pm.link_saved(m, db, [ORG], set(), pos, "model", "spindle")
    return top


def _per_600(fc, years=slice(4, 10)):
    """Failures a 600 operating hours in the long run: the later years of a ten-year forecast."""
    rows = fc["rows"][years]
    hours = sum(r["hours"] for r in rows)
    return sum(r["failures"] for r in rows) / hours * 600


@pytest.fixture
def setting(monkeypatch):
    _clock(monkeypatch, TODAY)
    m = _m(ORG)
    m.today = lambda: TODAY
    db = _db()
    return m, db, pm.fetcher(db, [ORG])


def test_the_25_h_and_50_h_plans_breakdowns_match_the_hand_check(setting):
    m, db, fetch = setting
    a = _mower(m, db, "Mower on the 25 h plan", 25)
    b = _mower(m, db, "Mower on the 50 h plan", 50)
    fa = pf.position_forecast(m, a, root=a, period="year", periods=10, fetch=fetch)
    fb = pf.position_forecast(m, b, root=b, period="year", periods=10, fetch=fetch)
    assert len(fa["models"]) == len(fb["models"]) == 5
    assert _per_600(fa) == pytest.approx(3.265, rel=0.03)
    assert _per_600(fb) == pytest.approx(1.553, rel=0.04)
    # Each life says which tasks it counts and which it doesn't.
    rows = {r["name"]: r for r in fb["models"] if r["position"]["id"] == b}
    assert [t["task"]["name"] for t in rows["Spark plug life"]["tasks_counted"]] == ["Replace spark plugs"]
    assert "planned replacement every 100 hours" in rows["Spark plug life"]["rests_on"]
    assert "finds 100% of warnings" in rows["Drive belt life"]["rests_on"]
    assert "restores none" in rows["Spindle bearing life"]["tasks_not_counted"][0]["reason"]
    plain = {r["name"]: r for r in fa["models"] if r["position"]["id"] == a}
    assert "no P-F interval linked" in plain["Spark plug life"]["tasks_not_counted"][0]["reason"]
    _rebuilds_the_same(m)


def test_a_replacement_takes_the_failures_off_by_the_library(setting):
    """The 50 h plan's spark plugs against RePyability called directly, every 100 h: age replacement by
    default (a task on its own restarts when the plug is replaced, Nov 2026), block replacement when the
    task keeps its schedule."""
    import surpyval as surv
    from repyability import NonRepairable
    from repyability.schedule import DutyPlan, Rate, failures_by_period

    m, db, fetch = setting
    b = _mower(m, db, "Mower", 50)
    fc = pf.position_forecast(m, b, root=b, period="year", periods=2, fetch=fetch)
    row = next(r for r in fc["models"] if r["name"] == "Spark plug life")
    usage = DutyPlan(Rate(12, per="week")).forecast(fc["start"], "2029-01-01", readings={"hours": 0})
    part = NonRepairable(surv.Weibull.from_params(list(PLUG)), unplanned_cost=1.0, planned_cost=0.0)
    age_repl = failures_by_period(part, usage, "year", age=0.0, unit="hours", every=100.0, resets=True)
    assert row["replacing_task"]["resets"] is True
    assert row["expected_failures"] == pytest.approx(age_repl.total["expected_failures"], rel=1e-3)
    plugs = next(t for t in m._tasks_on(b) if t["name"] == "Replace spark plugs")
    m.set_task_on_replace(plugs["id"], "keep")
    fc = pf.position_forecast(m, b, root=b, period="year", periods=2, fetch=fetch)
    row = next(r for r in fc["models"] if r["name"] == "Spark plug life")
    direct = failures_by_period(part, usage, "year", age=0.0, unit="hours", every=100.0,
                                resets=False, since_renewal=0.0)
    assert row["expected_failures"] == pytest.approx(direct.total["expected_failures"], rel=1e-3)
    run_to_failure = failures_by_period(NonRepairable(surv.Weibull.from_params(list(PLUG))), usage, "year", age=0.0,
                                        unit="hours")
    assert row["expected_failures"] < run_to_failure.total["expected_failures"] / 4


def test_a_check_missing_some_warnings_leaves_those_failures(setting):
    m, db, fetch = setting
    top = _mower(m, db, "Mower", 50)
    belt = next(fm for fm in m._modes_on(top) if fm["text"].startswith("Drive belt"))
    task = next(t for t in m.s.inn(m.org, belt["id"], "MITIGATES") if t.get("label") == "Task")
    m.update_task(task["id"], interval=254, unit="hours")  # twice the P-F interval: half the warnings missed
    fc = pf.position_forecast(m, top, root=top, period="year", periods=3, fetch=fetch)
    row = next(r for r in fc["models"] if r["name"] == "Drive belt life")
    m.update_task(task["id"], interval=50, unit="hours")
    m.decide_failure_mode(belt["id"], "operational", {"outcome": "rtf", "rtf_basis": "random"})
    rtf = next(r for r in pf.position_forecast(m, top, root=top, period="year", periods=3, fetch=fetch)["models"]
               if r["name"] == "Drive belt life")
    assert row["expected_failures"] == pytest.approx(rtf["expected_failures"] * 0.5, rel=1e-3)
    assert row["failures_range"] == [None, None] and rtf["tasks_counted"] == []
    assert math.isfinite(rtf["expected_failures"]) and rtf["expected_failures"] > 0


def test_a_whole_position_model_gives_way_to_lives_for_its_modes(setting):
    m, db, fetch = setting
    top = m.create_position("Pump")["id"]
    m.fit(top, new_item={"name": "Pump SN1"}, on=TODAY)
    mode = m.add_failure_mode(top, "Seal leaks")["id"]
    pm.link_saved(m, db, [ORG], set(), top, "model", "plug", [mode])
    whole = pm.link_saved(m, db, [ORG], set(), top, "model", "belt")
    m.use_position_model(top, whole["id"])  # the whole position's life, in use
    fc = pf.position_forecast(m, top, root=top, fetch=fetch)
    assert [r["name"] for r in fc["models"]] == ["Spark plug life"]
    assert any("lives of their own" in x["reason"] for x in fc["not_forecast"])
