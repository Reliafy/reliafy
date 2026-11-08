"""The interval calculators on an RCM task card (backend/services/rcm_intervals.py):
each a thin wrapper around RePyability's maintenance decision functions, worked
examples with known answers (RePyability's own docstring examples), the same
numbers as RePyability called directly where the installed release has the
functions, plain refusals, the routes, the MCP actions, and a saved calculation
standing as a decision's evidence."""

import math

import pytest

from backend.services import rcm_intervals as ri
from backend.services.rcm_intervals import IntervalError, nice_interval
from backend.tests.test_maintenance_rcm_api import api  # noqa: F401 - fixture

M = "/api/maintenance"
ONSET_400_DAYS = 365.25 / 400  # one failure in 400 days, a year


def _repy_has(name):
    from repyability import maintenance

    return getattr(maintenance, name, None)


# ---- rounding to a unit people schedule in ---------------------------------------------

@pytest.mark.parametrize("days, value, unit", [
    (30.0, 4, "weeks"), (70.0, 2, "months"), (13.0, 13, "days"), (1.5, 36, "hours"),
    (2.1 * 365.25, 2, "years"), (2.6 * 365.25, 2.5, "years"), (7.9 * 365.25, 7, "years"), (0.01, 1, "hours"),
])
def test_nice_interval_rounds_down_into_a_scheduling_unit(days, value, unit):
    got = nice_interval(days)
    assert (got["value"], got["unit"]) == (value, unit)
    assert got["days"] <= days or unit == "hours" and days < 1 / 24


# ---- on condition (the P-F calculator) -----------------------------------------------

def test_on_condition_worked_example():
    """RePyability's example: a warning 30 days before failure, one failure in 400 days, a
    check $20, a fix in time $300, a failure $5,000: the cheapest interval is the P-F interval."""
    r = ri.on_condition_interval(30, "days", ONSET_400_DAYS, 20, 300, 5000)
    assert r["recommended"] == {"value": 4, "unit": "weeks"}
    assert r["interval"] * 7 == pytest.approx(30.0, rel=1e-6)
    assert r["detection_probability_at_best"] == pytest.approx(1.0)
    # The cost a year at the best: checks every 30 days plus the planned fixes.
    assert r["cost_rate"] == pytest.approx(20 / 30 * 365.25 + ONSET_400_DAYS * 300, rel=1e-6)
    assert r["run_to_failure_cost_rate"] == pytest.approx(ONSET_400_DAYS * 5000)
    assert r["worth_it"] is True
    assert "half P-F interval, 15 days" in r["rule_of_thumb"]["text"]
    assert r["summary"].startswith("Check every 4 weeks")
    assert r["explanation"].startswith("A failure gives a warning")


def test_on_condition_matches_repyability_called_directly():
    fn = _repy_has("optimal_on_condition_interval")
    if fn is None:
        pytest.skip("this RePyability doesn't have optimal_on_condition_interval yet (the port runs)")
    for pf, unit, onset, costs, p in [(10, "weeks", 0.5, (20, 200, 2000), 1.0), (6, "months", 2.0, (150, 400, 9000), 0.8)]:
        mine = ri.on_condition_interval(pf, unit, onset, *costs, detection_probability=p)
        theirs = fn(pf * ri.DAYS_IN[unit[:-1]], onset_rate=onset / 365.25, inspection_cost=costs[0],
                    found_cost=costs[1], failure_cost=costs[2], detection_probability=p)
        assert mine["interval"] * ri.DAYS_IN[mine["unit"][:-1]] == pytest.approx(theirs.interval, rel=1e-6)
        assert mine["cost_rate"] == pytest.approx(theirs.cost_rate * 365.25, rel=1e-6)


def test_on_condition_port_gives_the_same_numbers(monkeypatch):
    """The app's port (for the pinned RePyability without the functions) and whatever is installed agree."""
    args = (10, "weeks", 0.5, 20, 200, 2000)
    live = ri.on_condition_interval(*args, current_interval=1, current_unit="months")
    monkeypatch.setattr(ri, "_repy_maintenance", None)
    port = ri.on_condition_interval(*args, current_interval=1, current_unit="months")
    assert port["interval"] == pytest.approx(live["interval"], rel=1e-6)
    assert port["current"]["cost_rate"] == pytest.approx(live["current"]["cost_rate"], rel=1e-9)


def test_on_condition_current_interval_and_an_unworthy_check():
    r = ri.on_condition_interval(10, "weeks", 0.5, 20, 200, 2000, current_interval=1, current_unit="months")
    assert r["current"]["detection_probability"] == pytest.approx(1.0)
    assert r["current"]["cost_rate"] == pytest.approx(20 * 12 + 0.5 * 200, rel=1e-9)
    # Checks dearer than the failures they prevent: never pays.
    never = ri.on_condition_interval(1, "days", 0.01, 500, 10, 20)
    assert never["recommended"] is None and never["worth_it"] is False
    assert "never pays" in never["summary"]


@pytest.mark.parametrize("kwargs, words", [
    ({"failure_cost": 100, "found_cost": 200}, "more than the cost of fixing a warning"),
    ({"pf_unit": "cycles"}, "needs a time unit"),
    ({"detection_probability": 1.5}, "at most 1"),
    ({"onset_rate": 0}, "more than 0"),
    ({"pf_interval": "ten"}, "must be a number"),
    ({"inspection_cost": None}, "Enter the cost of a check"),
])
def test_on_condition_refusals_say_what_to_change(kwargs, words):
    base = {"pf_interval": 10, "pf_unit": "weeks", "onset_rate": 0.5, "inspection_cost": 20, "found_cost": 200,
            "failure_cost": 2000}
    with pytest.raises(IntervalError, match=words):
        ri.on_condition_interval(**{**base, **kwargs})


# ---- failure finding -----------------------------------------------------------------

def test_failure_finding_worked_example():
    """RePyability's example: a valve failing hidden at 0.001 a year, a 0.1% target: test every 2 years."""
    r = ri.failure_finding_interval(failure_rate=0.001, target_unavailability=0.001, demand_rate=0.02,
                                    current_interval=2, current_unit="years")
    assert r["basis"] == "target" and r["recommended"] == {"value": 2, "unit": "years"}
    assert r["interval"] == pytest.approx(2.0, abs=0.01)
    assert r["current"]["mean_unavailability"] == pytest.approx(0.000999, abs=5e-7)
    assert r["current"]["multiple_failures_per_year"] * 1e5 == pytest.approx(1.999, abs=1e-3)
    assert r["current"]["meets_target"] is True


def test_failure_finding_yours_against_the_longest_that_meets_the_target():
    r = ri.failure_finding_interval(failure_rate=0.1, target_unavailability=0.01, current_interval=6,
                                    current_unit="months")
    exact = 1 - (1 - math.exp(-0.05)) / 0.05  # an exponential life tested every half year
    assert r["current"]["mean_unavailability"] == pytest.approx(exact, rel=1e-9)
    assert r["current"]["meets_target"] is False
    assert r["recommended"] == {"value": 2, "unit": "months"} and r["at_recommended"]["mean_unavailability"] < 0.01
    assert "within the 1% target" in r["summary"]


def test_failure_finding_matches_repyability_called_directly():
    fn = _repy_has("optimal_failure_finding_interval")
    if fn is None:
        pytest.skip("this RePyability doesn't have optimal_failure_finding_interval yet (the port runs)")
    import surpyval as surv
    from repyability.non_repairable import NonRepairable

    mine = ri.failure_finding_interval(failure_rate=0.1, test_cost=50, demand_rate=0.5, consequence_cost=100_000)
    theirs = fn(NonRepairable(surv.Exponential.from_params([0.1])), test_cost=50, demand_rate=0.5,
                consequence_cost=100_000)
    assert mine["basis"] == "cost"
    assert mine["interval"] * ri.DAYS_IN[mine["unit"][:-1]] / 365.25 == pytest.approx(theirs.interval, rel=1e-5)
    assert mine["cost_rate"] == pytest.approx(theirs.cost_rate, rel=1e-6)


def test_failure_finding_with_a_wearing_device_and_the_port(monkeypatch):
    """A Weibull device with a target: RePyability's search gives up on a non-constant rate (it
    starts too fine), so the app's search takes over, each point still RePyability's."""
    weibull = {"distribution_id": "weibull", "params": [{"name": "alpha", "value": 20}, {"name": "beta", "value": 1.5}],
               "model_unit": "years", "target_unavailability": 0.01}
    live = ri.failure_finding_interval(**weibull)
    assert live["recommended"] == {"value": 4, "unit": "months"}
    assert live["at_recommended"]["mean_unavailability"] <= 0.01
    monkeypatch.setattr(ri, "_repy_maintenance", None)
    assert ri.failure_finding_interval(**weibull)["interval"] == pytest.approx(live["interval"], rel=1e-6)


@pytest.mark.parametrize("kwargs, words", [
    ({}, "Give a target unavailability"),
    ({"target_unavailability": 1.5}, "less than 1"),
    ({"target_unavailability": 0.01, "consequence_cost": 10}, "needs the demand rate"),
    ({"target_unavailability": 0.01, "failure_rate": None}, "Enter the device's failure rate"),
    ({"target_unavailability": 0.01, "failure_rate": None, "distribution_id": "weibull",
      "params": [{"name": "alpha", "value": 5}, {"name": "beta", "value": 2}], "model_unit": "cycles"}, "time unit"),
])
def test_failure_finding_refusals_say_what_to_change(kwargs, words):
    with pytest.raises(IntervalError, match=words):
        ri.failure_finding_interval(**{"failure_rate": 0.1, **kwargs})


def test_history_rate_prefers_the_modes_own_failures():
    rows = [{"x": 365.25, "c": 0, "failure_mode": "Seal leaks"}, {"x": 365.25, "c": 0, "failure_mode": "Bearing"},
            {"x": 730.5, "c": 1}]
    assert ri.history_rate(rows, "seal leaks")["rate"] == pytest.approx(0.25)
    assert ri.history_rate(rows, "Impeller")["rate"] == pytest.approx(0.5)
    assert "2 failures of any kind in 4 years" in ri.history_rate(rows, "Impeller")["text"]
    assert ri.history_rate([{"x": 100, "c": 1}]) is None


# ---- the routes, the evidence and the notes ----------------------------------------------

def _mode(api, outcome="on_condition", task="Check the seal for weeping", interval=1, unit="months", hidden=False,
          consequence="operational"):
    pump = api.post(f"{M}/positions", json={"name": "Pump"}).json()
    fn = api.post(f"{M}/positions/{pump['id']}/functions", json={"text": "Pump water", "standard": "50 L/s"}).json()
    ff = api.post(f"{M}/functions/{fn['id']}/failures", json={"text": "No flow"}).json()
    mode = api.post(f"{M}/positions/{pump['id']}/failure-modes",
                    json={"text": "Seal leaks", "functional_failure_id": ff["id"]}).json()
    r = api.put(f"{M}/failure-modes/{mode['id']}/decision", json={
        "consequence": consequence, "hidden": hidden,
        "decision": {"outcome": outcome, "task": task, "interval": interval, "interval_unit": unit}})
    assert r.status_code == 200, r.text
    return mode["id"], r.json()["decision"]


def test_on_condition_route_and_its_refusal(api):
    r = api.post(f"{M}/rcm/interval/on-condition", json={
        "pf_interval": 10, "pf_unit": "weeks", "onset_rate": 0.5, "inspection_cost": 20, "found_cost": 200,
        "failure_cost": 2000})
    assert r.status_code == 200, r.text
    assert r.json()["recommended"] == {"value": 2, "unit": "months"}
    bad = api.post(f"{M}/rcm/interval/on-condition", json={
        "pf_interval": 10, "pf_unit": "weeks", "onset_rate": 0.5, "inspection_cost": 20, "found_cost": 200,
        "failure_cost": 100})
    assert bad.status_code == 422 and "more than the cost of fixing a warning" in bad.json()["detail"]
    empty = api.post(f"{M}/rcm/interval/on-condition", json={})
    assert empty.status_code == 422 and empty.json()["detail"] == "Enter the P-F interval."
    odd = api.post(f"{M}/rcm/interval/on-condition", json={"pf": 10})
    assert odd.status_code == 422 and "Unknown input: pf" in odd.json()["detail"]


def test_failure_finding_route_with_a_saved_model(api):
    r = api.post(f"{M}/rcm/interval/failure-finding", json={
        "model_id": "sample-model-bearings-weibull", "target_unavailability": 0.01})
    assert r.status_code == 200, r.text
    assert r.json()["device"]["source"] == "model" and r.json()["recommended"]
    cycles = api.post(f"{M}/rcm/interval/failure-finding", json={
        "model_id": "sample-model-bearings-weibull", "model_unit": "cycles", "target_unavailability": 0.01})
    assert cycles.status_code == 422 and "time unit" in cycles.json()["detail"]
    assert api.post(f"{M}/rcm/interval/failure-finding", json={"model_id": "nope", "target_unavailability": 0.01}
                    ).status_code == 404


def test_a_saved_calculation_evidences_the_decision_and_the_notes_keep_the_rationale(api):
    mode_id, decision = _mode(api)
    assert decision["status"] == "unevidenced"
    inputs = {"pf_interval": 10, "pf_unit": "weeks", "onset_rate": 0.5, "inspection_cost": 20, "found_cost": 200,
              "failure_cost": 2000}
    calc = api.post(f"{M}/rcm/interval/on-condition", json=inputs).json()
    rec = calc["recommended"]
    # Use 2 months: the task's interval, the saved calculation in the same unit, linked as evidence.
    api.patch(f"{M}/tasks/{decision['task_id']}", json={"interval": rec["value"], "unit": rec["unit"]})
    saved = api.post("/api/strategy/analyses", json={"name": "Seal leaks: check interval", "kind": "on_condition_interval",
                                                     "inputs": {**inputs, "unit": rec["unit"]}}).json()
    assert saved["headline"] == "Check every 2 months"
    assert saved["results"]["recommended"] == rec  # recomputed on the server, never the client's
    mode = api.get(f"{M}/positions/{_position_of(api, mode_id)}/rcm?scope=this").json()
    current = _decision_in(mode, mode_id)
    body = {"outcome": "on_condition", "task": current["task"], "interval": rec["value"], "interval_unit": rec["unit"],
            "evidence": {"type": "strategy_analysis", "id": saved["id"]}}
    r = api.put(f"{M}/failure-modes/{mode_id}/decision", json={"decision": body})
    assert r.status_code == 200, r.text
    d = r.json()["decision"]
    assert d["status"] == "supported" and d["summary"].startswith("Check every 2 months")
    assert d["artifact_link_path"] == f"/strategy/analyses/{saved['id']}"
    # A task further apart than the P-F interval is contradicted by the same calculation.
    api.patch(f"{M}/tasks/{decision['task_id']}", json={"interval": 4, "unit": "months"})
    later = _decision_in(api.get(f"{M}/positions/{_position_of(api, mode_id)}/rcm?scope=this").json(), mode_id)
    assert later["status"] == "contradicted" and "longer than the P-F interval" in later["summary"]
    # The rationale paragraph appended to the mode's notes and rationale.
    api.patch(f"{M}/failure-modes/{mode_id}", json={"notes": "Seal weeps first."})
    line = "Interval from the P-F calculator (9 Nov 2026): P-F 10 weeks, onset 0.5/year → 2 months."
    r = api.patch(f"{M}/failure-modes/{mode_id}", json={"notes": f"Seal weeps first.\n\n{line}"})
    assert r.status_code == 200, r.text
    again = _decision_in(api.get(f"{M}/positions/{_position_of(api, mode_id)}/rcm?scope=this").json(), mode_id,
                         whole=True)
    assert again["notes"].endswith(line) and again["notes"].startswith("Seal weeps first.")


def test_a_failure_finding_calculation_evidences_a_failure_finding_task(api):
    mode_id, decision = _mode(api, outcome="failure_finding", task="Test the trip", interval=6, unit="months",
                              hidden=True, consequence="safety")
    inputs = {"failure_rate": 0.1, "target_unavailability": 0.01}
    saved = api.post("/api/strategy/analyses", json={"name": "Trip test", "kind": "failure_finding_interval",
                                                     "inputs": {**inputs, "unit": "months"}}).json()
    body = {"outcome": "failure_finding", "task": "Test the trip", "interval": 6, "interval_unit": "months",
            "evidence": {"type": "strategy_analysis", "id": saved["id"]}}
    d = api.put(f"{M}/failure-modes/{mode_id}/decision", json={"decision": body}).json()["decision"]
    # Six months is longer than the longest interval that meets 1% (about 2.4 months).
    assert d["status"] == "contradicted" and "longest that meets the target" in d["summary"]
    api.patch(f"{M}/tasks/{decision['task_id']}", json={"interval": 2, "unit": "months"})
    d = _decision_in(api.get(f"{M}/positions/{_position_of(api, mode_id)}/rcm?scope=this").json(), mode_id)
    assert d["status"] == "supported" and d["summary"].startswith("Test every 2 months")


def test_interval_inputs_start_from_the_linked_model(api):
    mode_id, _ = _mode(api, outcome="fixed_interval", task="Replace the seal", interval=6, unit="months")
    r = api.get(f"{M}/failure-modes/{mode_id}/interval-inputs")
    assert r.status_code == 200, r.text
    assert r.json()["onset_rate"] is None and r.json()["life_model"] is None  # nothing to start from: typed
    body = {"outcome": "fixed_interval", "task": "Replace the seal", "interval": 6, "interval_unit": "months",
            "evidence": {"type": "model", "id": "sample-model-bearings-weibull"}}
    assert api.put(f"{M}/failure-modes/{mode_id}/decision", json={"decision": body}).status_code == 200
    got = api.get(f"{M}/failure-modes/{mode_id}/interval-inputs").json()
    assert got["life_model"]["distribution_id"] == "weibull" and got["life_model"]["model_id"]
    assert got["evidence"]["type"] == "model"


def _position_of(api, mode_id):
    return api.get(f"{M}/failure-modes/{mode_id}/tasks").json().get("position", {}).get("id") or _find_position(api)


def _find_position(api):
    return api.get(f"{M}/positions").json()["positions"][-1]["id"]


def _decision_in(sheet, mode_id, whole=False):
    for pos in sheet["positions"]:
        for fn in pos["functions"]:
            for ff in fn["failures"]:
                for md in ff["modes"]:
                    if md["id"] == mode_id:
                        return md if whole else md["decision"]
    raise AssertionError("mode not found")


# ---- the MCP actions, over REST as over MCP ----------------------------------------------

def test_mcp_rcm_actions(api):
    """maintenance rcm.interval_on_condition and rcm.interval_failure_finding, called as the
    one maintenance tool's actions."""
    from backend.maintenance import mcp_tools

    mcp_tools.register()
    assert {"rcm.interval_on_condition", "rcm.interval_failure_finding"} <= set(mcp_tools.TOOL_TABLES["maintenance"][1])
    assert mcp_tools.scope_of("maintenance_rcm.interval_on_condition") == "read"
