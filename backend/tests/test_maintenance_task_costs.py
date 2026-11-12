"""What a task costs each time it's done (Nov 2026, backend/maintenance/task_costs.py): typed on
the task (task.cost_set) or from its LSA record at the workspace's trade rates (trade.rate_set);
read on every task, on the Explorer's task table, by the RCM (each task's cost, and a word when a
saved calculation used another figure) and by the interval calculators."""

import pytest

from backend.maintenance.service import PROJECTORS, Invalid, Maintenance
from backend.maintenance.store import GraphStore
from backend.tests.test_maintenance_mcp import _do, _ok, _session, env  # noqa: F401
from backend.tests.test_maintenance_rcm_api import api  # noqa: F401
from backend.tests.test_rcm_intervals import _decision_in, _mode, _position_of

ORG = "user-a"
M = "/api/maintenance"


@pytest.fixture()
def m():
    return Maintenance(GraphStore(":memory:", PROJECTORS), ORG, "tester")


def _rebuilds_the_same(m):
    before = m.s.snapshot()
    m.s.rebuild()
    assert m.s.snapshot() == before


def _events(m, type):
    return [e for e in m.s.events(ORG, 1000) if e["type"] == type]


def _pump(m):
    pump = m.create_position("Pump")
    seal = m.create_part("SEAL-1", "Mechanical seal", unit_cost=120)
    task = m.create_task(pump["id"], "Replace the seal", 12, "months", trade="Fitter")
    return pump, seal, task


def test_no_cost_until_something_prices_it(m):
    _, _, task = _pump(m)
    cost = m.task_cost(task["id"])
    assert cost["amount"] is None and cost["source"] is None
    assert m._task_view(m.s.node(ORG, task["id"]))["cost"]["amount"] is None


def test_the_lsa_prices_it_at_trade_rates_and_says_what_it_could_not(m):
    _, seal, task = _pump(m)
    m.set_task_resources(task["id"], {
        "labour": [{"people": 2, "hours": 1.5}, {"trade": "Electrician", "people": 1, "hours": 0.5}],
        "spares": [{"part_id": seal["id"], "qty": 1}, {"name": "Gasket", "qty": 2}],
        "consumables": [{"name": "Grease", "qty": 0.1, "unit": "kg", "cost": 4.5}],
    })
    cost = m.task_cost(task["id"])
    # No rates yet: the parts and consumables alone, partial, naming what's missing.
    assert cost["source"] == "lsa" and cost["amount"] == 124.5
    assert cost["lsa"]["missing_rates"] == ["Fitter", "Electrician"]  # a line with no trade takes the task's
    assert cost["lsa"]["missing_prices"] == ["Gasket"] and cost["lsa"]["complete"] is False
    m.set_trade_rate("fitter", 90)  # matched case aside
    m.set_trade_rate("Electrician", 110)
    cost = m.task_cost(task["id"])
    assert cost["lsa"]["labour_cost"] == 2 * 1.5 * 90 + 0.5 * 110
    assert cost["amount"] == 270 + 55 + 124.5 and cost["lsa"]["missing_rates"] == []
    rates = {r["trade"]: r for r in m.trade_rates()}
    assert rates["fitter"]["rate"] == 90 and rates["Electrician"]["tasks"] == 1
    # The same rate again writes nothing; null clears it.
    m.set_trade_rate("Electrician", 110)
    assert len(_events(m, "trade.rate_set")) == 2
    m.set_trade_rate("Electrician", None)
    assert m.task_cost(task["id"])["lsa"]["missing_rates"] == ["Electrician"]
    assert {r["trade"]: r["rate"] for r in m.trade_rates()}["Electrician"] is None
    _rebuilds_the_same(m)


def test_a_typed_cost_stands_in_place_of_the_lsa_until_cleared(m):
    _, seal, task = _pump(m)
    m.set_task_resources(task["id"], {"spares": [{"part_id": seal["id"], "qty": 1}]})
    view = m.set_task_cost(task["id"], "180")
    assert view["cost"]["amount"] == 180 and view["cost"]["source"] == "typed"
    assert view["cost"]["lsa"]["amount"] == 120  # still shown beside it
    m.set_task_cost(task["id"], 180)  # the same: nothing written
    assert len(_events(m, "task.cost_set")) == 1
    _rebuilds_the_same(m)
    assert m.set_task_cost(task["id"], "")["cost"]["source"] == "lsa"
    with pytest.raises(Invalid):
        m.set_task_cost(task["id"], -5)
    with pytest.raises(Invalid):
        m.set_trade_rate("", 10)
    m.retire_task(task["id"])
    with pytest.raises(Invalid):
        m.set_task_cost(task["id"], 10)


def test_the_task_table_says_where_each_task_came_from_and_its_cost(m):
    pump = m.create_position("Pump")
    fm = m.add_failure_mode(pump["id"], "Seal leaks")
    direct = m.create_task(pump["id"], "Inspect the guard", 12, "months", source="statutory", reference="AS 4024")
    linked = m.create_task(pump["id"], "Check the seal", 1, "months", failure_mode_id=fm["id"])
    m.set_task_cost(direct["id"], 60)
    rows = {r["name"]: r for r in m.task_table(position_id=pump["id"])["tasks"]}
    assert rows["Inspect the guard"]["source"] == "statutory" and rows["Inspect the guard"]["reference"] == "AS 4024"
    assert rows["Inspect the guard"]["cost"]["amount"] == 60 and rows["Inspect the guard"]["modes"] == []
    assert rows["Check the seal"]["modes"][0]["id"] == fm["id"] and rows["Check the seal"]["cost"]["amount"] is None
    assert linked["id"] == rows["Check the seal"]["id"]


def test_the_rcm_reads_each_task_cost(m):
    pump = m.create_position("Pump")
    fm = m.add_failure_mode(pump["id"], "Seal leaks")
    task = m.create_task(pump["id"], "Check the seal", 1, "months", failure_mode_id=fm["id"])
    assert m.rcm_mode(fm["id"])["tasks"][0]["cost"] == {"amount": None, "source": None, "complete": False}
    m.set_task_cost(task["id"], 25)
    assert m.rcm_mode(fm["id"])["tasks"][0]["cost"] == {"amount": 25, "source": "typed", "complete": True}


def test_the_app_routes(api):
    site = api.post(f"{M}/positions", json={"name": "Pump"}).json()
    made = api.post(f"{M}/positions/{site['id']}/tasks", json={"name": "Grease", "interval": 3, "unit": "months",
                                                                "trade": "Fitter", "source": "oem"}).json()
    api.patch(f"{M}/tasks/{made['id']}", json={"resources": {"labour": [{"people": 1, "hours": 2}]}})
    r = api.put(f"{M}/trade-rates", json={"trade": "Fitter", "rate": 95})
    assert r.status_code == 200 and r.json() == {"trade": "Fitter", "rate": 95}
    assert api.get(f"{M}/trade-rates").json()["rates"] == [{"trade": "Fitter", "rate": 95, "tasks": 1}]
    r = api.patch(f"{M}/tasks/{made['id']}", json={"cost": 250})
    assert r.status_code == 200 and r.json()["cost"]["amount"] == 250 and r.json()["cost"]["lsa"]["amount"] == 190
    assert api.patch(f"{M}/tasks/{made['id']}", json={"cost": None}).json()["cost"]["source"] == "lsa"
    assert api.patch(f"{M}/tasks/{made['id']}", json={"cost": "lots"}).status_code == 422


def test_the_calculator_starts_from_the_task_cost_and_the_rcm_says_when_it_moved(api):
    mode_id, decision = _mode(api)
    task_id = decision["task_id"]
    api.patch(f"{M}/tasks/{task_id}", json={"cost": 40})
    got = api.get(f"{M}/failure-modes/{mode_id}/interval-inputs", params={"task_id": task_id}).json()
    assert got["task_cost"]["amount"] == 40 and got["task_cost"]["source"] == "typed"
    assert api.get(f"{M}/failure-modes/{mode_id}/interval-inputs").json()["task_cost"] is None
    inputs = {"pf_interval": 10, "pf_unit": "weeks", "onset_rate": 0.5, "inspection_cost": 40, "found_cost": 200,
              "failure_cost": 5000, "unit": "weeks"}
    saved = api.post("/api/strategy/analyses", json={"name": "Seal check", "kind": "on_condition_interval",
                                                     "inputs": inputs}).json()
    sheet = api.get(f"{M}/positions/{_position_of(api, mode_id)}/rcm?scope=this").json()
    current = _decision_in(sheet, mode_id)
    body = {"outcome": "on_condition", "task": current["task"], "interval": 5, "interval_unit": "weeks",
            "evidence": {"type": "strategy_analysis", "id": saved["id"]}}
    d = api.put(f"{M}/failure-modes/{mode_id}/decision", json={"decision": body}).json()["decision"]
    assert "cost_changed" not in d  # the calculation used the task's cost
    # The task's cost moves: the decision keeps its saved figures, and says the cost has changed since.
    api.patch(f"{M}/tasks/{task_id}", json={"cost": 65})
    d = _decision_in(api.get(f"{M}/positions/{_position_of(api, mode_id)}/rcm?scope=this").json(), mode_id)
    assert d["cost_changed"] == [{"task_id": task_id, "task": current["task"], "used": 40.0, "now": 65,
                                  "analysis_id": saved["id"]}]
    assert d["status"] == "supported"  # unchanged: nothing re-run silently


@pytest.mark.usefixtures("mcp_on")
def test_over_mcp(env):
    async def flow(client):
        pos = _ok(await _do(client, "maintenance", "positions.create", name="Pump"))
        task = _ok(await _do(client, "maintenance", "tasks.create", position_id=pos["id"], name="Grease",
                             interval=3, unit="months", trade="Fitter"))
        set_ = _ok(await _do(client, "maintenance", "tasks.set_resources", task_id=task["id"],
                             resources={"labour": [{"people": 1, "hours": 2}]}, trade_rates={"Fitter": 80}))
        typed = _ok(await _do(client, "maintenance", "tasks.update", task_id=task["id"], cost=300))
        cleared = _ok(await _do(client, "maintenance", "tasks.update", task_id=task["id"], clear_cost=True))
        calc = _ok(await _do(client, "maintenance", "rcm.pf_interval", pf_interval=10, pf_unit="weeks",
                             onset_rate=0.5, found_cost=200, failure_cost=5000, task_id=task["id"]))
        return set_, typed, cleared, calc

    set_, typed, cleared, calc = _session(env["token"], flow)
    assert set_["cost"]["amount"] == 160 and set_["cost"]["source"] == "lsa"
    assert typed["cost"]["amount"] == 300 and typed["cost"]["source"] == "typed"
    assert cleared["cost"]["amount"] == 160
    assert calc["task_cost_used"] == {"amount": 160, "source": "lsa"} and calc["inspection_cost"] == 160
