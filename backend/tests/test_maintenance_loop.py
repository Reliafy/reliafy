"""Reliafy Maintenance: the records refit a class's non-repairable model, and the model
proposes task intervals that someone accepts or rejects."""

from datetime import date, timedelta

import mongomock
import pytest

from backend.maintenance import loop
from backend.maintenance.service import PROJECTORS, Invalid, Maintenance
from backend.maintenance.store import GraphStore
from backend.tests.rcm_tree import position_with_rcm

ORG = "user-l"


def _ago(days: int) -> str:
    return (date.today() - timedelta(days=days)).isoformat()


class _Rcm:
    name = "Pump"
    functions = [{"id": "f", "text": "Pump water", "failures": [{"id": "ff", "text": "No flow", "modes": [
        {"id": "m1", "text": "Bearing worn", "consequence": "operational",
         "decision": {"outcome": "fixed_interval", "interval": 24, "interval_unit": "months",
                      "task": "Replace bearings"}}]}]}]


@pytest.fixture()
def setup():
    db = mongomock.MongoClient()["loop"]
    m = Maintenance(GraphStore(":memory:", PROJECTORS), ORG, "tester")
    # Three pumps of one class, each with a history of wear-out failures.
    lives = [[700, 760, 820], [690, 840, 780], [730, 800]]
    for i, history in enumerate(lives):
        pos = position_with_rcm(m, _Rcm.functions, _Rcm.name)["position"]
        m.update_position(pos["id"], name=f"Pump {i + 1}", position_class="Centrifugal pump")
        day = 3000
        fm = pos["failure_modes"][0]["id"]
        m.fit(pos["id"], new_item={"name": f"Pump {i + 1}.0"}, on=_ago(day))
        for n, life in enumerate(history):
            day -= life
            wo = m.open_work_order(pos["id"], "Seized")
            m.close_work_order(wo["id"], [{"kind": "replace", "failure_mode_id": fm,
                                           "new_item": {"name": f"Pump {i + 1}.{n + 1}"}}], on=_ago(day))
    return m, db


def test_fit_proposes_an_interval_and_accepting_applies_it(setup):
    m, db = setup
    with pytest.raises(Invalid):
        loop.propose(m, "Centrifugal pump")  # no model yet
    m.set_class_costs("Centrifugal pump", planned_cost=400, failure_cost=4000)
    out = loop.fit_class_model(m, db, "Centrifugal pump")
    assert out["model"]["failures"] == 8 and out["model"]["distribution"] == "weibull"
    assert db.models.find_one({"_id": out["model"]["model_id"]})  # a normal saved model
    assert len(out["proposals"]) == 3
    pr = out["proposals"][0]
    assert pr["kind"] == "interval" and pr["proposed"]["unit"] == "months"
    assert pr["proposed"]["interval"] < 24 and "wear-out" in pr["reason"]
    assert loop.propose(m, "Centrifugal pump") == []  # nothing new to propose
    accepted = m.decide_proposal(pr["id"], accept=True)
    assert accepted["status"] == "accepted"
    task = m.explain_task(pr["task"]["id"])
    assert task["task"]["interval"] == pr["proposed"]["interval"]
    assert any(h["type"] == "task.updated" for h in task["history"])
    with pytest.raises(Invalid):
        m.decide_proposal(pr["id"], accept=False)


def test_too_few_failures_and_bad_costs_are_refused(setup):
    m, db = setup
    with pytest.raises(Invalid):
        m.set_class_costs("Centrifugal pump", planned_cost=500, failure_cost=100)
    lone = m.create_position("Lonely pump", position_class="Spare pump")
    m.fit(lone["id"], new_item={"name": "P"}, on=_ago(100))
    with pytest.raises(Invalid):
        loop.fit_class_model(m, db, "Spare pump")


def test_refit_stale_runs_only_when_there_are_new_failures(setup):
    m, db = setup
    m.set_class_costs("Centrifugal pump", planned_cost=400, failure_cost=4000)
    loop.fit_class_model(m, db, "Centrifugal pump")
    assert loop.refit_stale(m, db) == []
    pos = next(p for p in m.tree() if p["name"] == "Pump 3")
    full = m.position(pos["id"])
    wo = m.open_work_order(pos["id"], "Seized again")
    m.close_work_order(wo["id"], [{"kind": "replace", "failure_mode_id": full["failure_modes"][0]["id"],
                                   "new_item": {"name": "Pump 3.9"}}])
    assert loop.refit_stale(m, db) == ["Centrifugal pump"]


def test_economics_compare_the_plan_best_and_run_to_failure(setup):
    m, db = setup
    with pytest.raises(Invalid):
        loop.economics(m, "Centrifugal pump")  # no model yet
    m.set_class_costs("Centrifugal pump", planned_cost=400, failure_cost=4000)
    loop.fit_class_model(m, db, "Centrifugal pump")
    out = loop.economics(m, "Centrifugal pump", interval=6, unit="months")
    plans = {o["plan"]: o for o in out["options"]}
    assert set(plans) == {"current plan", "best interval", "run to failure", "what if"}
    assert plans["best interval"]["per_year"] <= plans["current plan"]["per_year"] <= plans["run to failure"]["per_year"]
    assert out["cheapest"] == "best interval"
    assert plans["current plan"]["net_present_cost"] == pytest.approx(plans["current plan"]["per_year"] * 7.0236, rel=1e-3)


def test_one_failure_fits_an_exponential_but_nothing_with_two_parameters(setup):
    m, db = setup
    pos = m.create_position("Cooling pump", position_class="Single-failure pump")
    m.fit(pos["id"], new_item={"name": "P1"}, on=_ago(900))
    m.remove(pos["id"], on=_ago(300), failure_mode_text="Seal leaking")
    m.fit(pos["id"], new_item={"name": "P2"}, on=_ago(300))
    with pytest.raises(Invalid, match="fit distribution 'exponential'"):
        loop.fit_class_model(m, db, "Single-failure pump")  # weibull needs two
    out = loop.fit_class_model(m, db, "Single-failure pump", distribution="exponential")
    assert out["model"]["distribution"] == "exponential" and out["model"]["failures"] == 1
