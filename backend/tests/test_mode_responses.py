"""A failure mode's corrective response ("If it fails anyway"; forecast plan step 3, Nov 2026): a task
raised by the failure, whose labour, spares and cost feed the forecast's failure lines, and whose cost
each time is the mode's cost of a failure unless one is typed on the mode (an override)."""

import pytest

from backend.maintenance.service import Invalid
from backend.tests.test_maintenance_forecast_engine import _m, _rebuilds_the_same
from backend.tests.test_maintenance_rcm_api import api  # noqa: F401


def _pump(m):
    pump = m.create_position("Pump")["id"]
    seal = m.add_failure_mode(pump, "Seal leaks")["id"]
    return pump, seal


def test_a_response_is_a_task_raised_by_the_failure():
    m = _m("org-responses")
    pump, seal = _pump(m)
    assert m.mode_responses(seal) == {"failure": None, "found": None}
    got = m.set_mode_response(seal, "failure", name="Replace the seal",
                              labour=[{"trade": "Fitter", "people": 2, "hours": 3}], cost=650,
                              spares=[{"name": "Seal kit", "qty": 1}])
    assert got["name"] == "Replace the seal" and got["hours_each"] == 6 and got["cost_each"] == 650
    assert got["spares"] == [{"name": "Seal kit", "part_id": None, "qty": 1.0}] and got["gaps"] == []
    task = m._get(got["id"], "Task")
    assert task["trigger"] == {"kind": "failure", "failure_mode_id": seal}
    view = m._task_view(task)
    assert view["trigger"]["text"] == "if Seal leaks fails"
    # Changing it changes the same task; what's left out is kept.
    again = m.set_mode_response(seal, "failure", cost=700)
    assert again["id"] == got["id"] and again["cost_each"] == 700 and again["hours_each"] == 6
    # The cost of a failure comes from it; a typed figure on the mode overrides it.
    used = m.mode_costs(seal)["used"]
    assert used["failure_cost"] == 700 and used["sources"]["failure_cost"] == "its corrective response's (Replace the seal)"
    m.set_mode_costs(seal, failure_cost=900)
    used = m.mode_costs(seal)["used"]
    assert used["failure_cost"] == 900 and "typed over" in used["sources"]["failure_cost"]
    assert m.mode_costs(seal)["responses"]["failure"]["id"] == got["id"]
    # Cleared: the task is retired, and the mode's own figure stays.
    assert m.clear_mode_response(seal, "failure")["failure"] is None
    assert m.mode_costs(seal)["used"]["failure_cost"] == 900
    _rebuilds_the_same(m)


def test_a_response_with_no_cost_says_so_and_names_from_the_note():
    m = _m("org-responses-2")
    _pump_id, seal = _pump(m)
    m.decide_failure_mode(seal, "operational", {"outcome": "rtf", "rtf_basis": "uneconomic",
                                                "task": "Swap in the spare pump"})
    got = m.set_mode_response(seal, "failure")
    assert got["name"] == "Swap in the spare pump"
    assert got["gaps"] == ["no labour in it, so its hours are unknown", "no cost each time"]
    assert m.mode_costs(seal)["used"]["per_failure"] is None
    with pytest.raises(Invalid, match="failure"):
        m.set_mode_response(seal, "later")
    with pytest.raises(Invalid, match="only failure_mode_id"):
        m.create_task(_pump_id, "x", None, trigger={"kind": "failure", "failure_mode_id": seal, "note": "y"})


def test_the_routes(api):  # noqa: F811
    M = "/api/maintenance"
    pump = api.post(f"{M}/positions", json={"name": "Pump"}).json()
    mode = api.post(f"{M}/positions/{pump['id']}/failure-modes", json={"text": "Seal leaks"}).json()
    r = api.put(f"{M}/failure-modes/{mode['id']}/response/failure",
                json={"name": "Replace the seal", "labour": [{"trade": "Fitter", "people": 1, "hours": 4}], "cost": 650})
    assert r.status_code == 200, r.text
    assert r.json()["hours_each"] == 4
    costs = api.get(f"{M}/failure-modes/{mode['id']}/costs").json()
    assert costs["used"]["failure_cost"] == 650 and costs["responses"]["failure"]["name"] == "Replace the seal"
    # The same over the task routes (the MCP and CLI twin: maintenance tasks.create with the trigger).
    t = api.post(f"{M}/positions/{pump['id']}/tasks",
                 json={"name": "Act on the find", "trigger": {"kind": "found", "failure_mode_id": mode["id"]}})
    assert t.status_code == 200, t.text
    assert api.get(f"{M}/failure-modes/{mode['id']}/costs").json()["responses"]["found"]["name"] == "Act on the find"
    assert api.delete(f"{M}/failure-modes/{mode['id']}/response/failure").json()["failure"] is None
    assert api.put(f"{M}/failure-modes/{mode['id']}/response/other", json={}).status_code >= 400
