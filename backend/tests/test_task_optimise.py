"""Optimise… on a maintenance task (backend/maintenance/task_optimise.py): how often to do it from
the life model of the failure mode it prevents, the answer used (the task's interval, the saved
analysis as the mode's evidence, supported), both places (the model's row says which task it sets,
the task says which model it rests on), a refit flagged without changing the interval, and the
MCP action."""

from backend.tests.test_maintenance_rcm_api import api  # noqa: F401 - fixture
from backend.tests.test_rcm_intervals import _decision_in, _mode

M = "/api/maintenance"
# The TR-48 mower's spark plug: 24 plug lives, Weibull, $49 a planned change, $900 a failure.
PLUG = [{"name": "alpha", "value": 345.8092446733276}, {"name": "beta", "value": 2.5808620343628226}]


def _plug(api, outcome="fixed_interval", task="Replace spark plugs", interval=100, unit="hours"):
    mode_id, decision = _mode(api, outcome=outcome, task=task, interval=interval, unit=unit)
    pos = api.get(f"{M}/failure-modes/{mode_id}/tasks").json()
    position_id = (pos.get("position") or {}).get("id") or api.get(f"{M}/positions").json()["positions"][-1]["id"]
    model = api.post("/api/models/from-params", json={"name": "Spark plug life", "distribution": "weibull",
                                                       "params": PLUG, "unit": "hours"}).json()
    r = api.post(f"{M}/positions/{position_id}/models", json={"model_id": model["id"], "failure_mode_ids": [mode_id]})
    assert r.status_code == 200, r.text
    api.patch(f"{M}/tasks/{decision['task_id']}", json={"cost": 49})
    return mode_id, decision["task_id"], position_id, model["id"]


def test_the_plug_is_optimised_at_96_hours_and_used_as_supported_evidence(api):
    mode_id, task_id, position_id, model_id = _plug(api)
    r = api.post(f"{M}/tasks/{task_id}/optimise", json={})
    assert r.status_code == 200, r.text
    row = r.json()["modes"][0]
    assert row["calculator"] == "replacement" and row["model"]["id"] == model_id and row["model"]["source"] == "position"
    assert row["inputs"]["planned_cost"] == {"value": 49.0, "source": "task", "text": row["inputs"]["planned_cost"]["text"]}
    assert row["inputs"]["unplanned_cost"]["value"] is None  # nothing saved before: the user types it
    assert "what a failure costs" in row["problem"]
    r = api.post(f"{M}/tasks/{task_id}/optimise", json={"unplanned_cost": 900})
    row = r.json()["modes"][0]
    assert row["use"] == {"value": 96, "unit": "hours"}
    assert row["words"].startswith("Replace every 96 hours")
    # Use every 96 h: the task's interval, the analysis saved and linked, the check reads supported.
    used = api.post(f"{M}/tasks/{task_id}/optimise/use", json={"unplanned_cost": 900})
    assert used.status_code == 200, used.text
    u = used.json()
    assert (u["interval"], u["unit"], u["evidence_linked"], u["evidence_status"]) == (96, "hours", True, "supported")
    sheet = api.get(f"{M}/positions/{position_id}/rcm?scope=this").json()
    d = _decision_in(sheet, mode_id)
    assert d["interval"] == 96 and d["status"] == "supported"
    assert d["evidence"] == {"type": "strategy_analysis", "id": u["analysis"]["id"]}
    # Saved analyses appear in Strategy's list too.
    names = [a["name"] for a in api.get("/api/strategy/analyses").json()["analyses"]]
    assert "Seal leaks: replacement interval" in names
    # Both places: the model's row says which task it sets; the task says which model it rests on.
    links = api.get(f"{M}/position-models?position_ids={position_id}").json()["links"]
    sets = next(x for x in links if x["model_id"] == model_id)["used_by"]["tasks"]
    assert [(t["task_id"], t["interval"], t["moved"]) for t in sets] == [(task_id, 96, False)]
    assert api.get(f"{M}/model-tasks?model_ids={model_id}").json()["tasks"][model_id][0]["task_id"] == task_id
    basis = api.get(f"{M}/tasks/{task_id}/interval-basis").json()["rests_on"]
    assert basis[0]["model"]["id"] == model_id and basis[0]["moved"] is False
    # Optimise again starts from what it used: the same model and the failure cost saved.
    again = api.post(f"{M}/tasks/{task_id}/optimise", json={}).json()["modes"][0]
    assert again["model"]["source"] == "optimised" and again["inputs"]["unplanned_cost"]["source"] == "analysis"
    assert again["use"] == {"value": 96, "unit": "hours"}

    # The model refitted: flagged as moved everywhere, the interval left as it was.
    refit = api.put(f"/api/models/{model_id}/params", json={
        "distribution": "weibull", "unit": "hours",
        "params": [{"name": "alpha", "value": 420.0}, {"name": "beta", "value": 2.58}]})
    assert refit.status_code == 200, refit.text
    d = _decision_in(api.get(f"{M}/positions/{position_id}/rcm?scope=this").json(), mode_id)
    assert d["interval"] == 96 and "optimum may have moved" in d["summary"] and d["refitted"]
    assert api.get(f"{M}/tasks/{task_id}/interval-basis").json()["rests_on"][0]["moved"] is True
    assert api.post(f"{M}/tasks/{task_id}/optimise", json={}).json()["modes"][0]["moved"] is True


def test_a_check_takes_half_the_pf_interval(api):
    mode_id, decision = _mode(api, outcome="on_condition", task="Check the belt", interval=50, unit="hours")
    r = api.post(f"{M}/tasks/{decision['task_id']}/optimise", json={})
    row = r.json()["modes"][0]
    assert row["calculator"] == "pf" and "P-F interval" in row["problem"]
    row = api.post(f"{M}/tasks/{decision['task_id']}/optimise", json={"pf_interval": 127, "pf_unit": "hours"}).json()["modes"][0]
    assert row["use"] == {"value": 63, "unit": "hours"} and row["range"] is None
    u = api.post(f"{M}/tasks/{decision['task_id']}/optimise/use", json={"pf_interval": 127, "pf_unit": "hours"}).json()
    assert u["interval"] == 63 and u["evidence_status"] == "supported"
    # Optimise again starts from the P-F interval saved.
    again = api.post(f"{M}/tasks/{decision['task_id']}/optimise", json={}).json()["modes"][0]
    assert again["inputs"]["pf_interval"]["value"] == 127 and again["use"]["value"] == 63


def test_no_model_says_so_and_routine_work_has_nothing_to_optimise(api):
    mode_id, decision = _mode(api, outcome="fixed_interval", task="Replace the seal", interval=6, unit="months")
    row = api.post(f"{M}/tasks/{decision['task_id']}/optimise", json={}).json()["modes"][0]
    assert row["model"] is None and "No life model is linked" in row["no_model"]
    assert row["choices"] == []
    # A model chosen from the user's models: a calendar task takes it through the duty (here none: all the time).
    model = api.post("/api/models/from-params", json={"name": "Seal life", "distribution": "weibull",
                                                       "params": [{"name": "alpha", "value": 8760}, {"name": "beta", "value": 3}],
                                                       "unit": "hours"}).json()
    row = api.post(f"{M}/tasks/{decision['task_id']}/optimise", json={
        "model_type": "model", "model_id": model["id"], "planned_cost": 100, "unplanned_cost": 2000}).json()["modes"][0]
    assert row["model"]["source"] == "chosen" and row["use"]["unit"] == "months" and row["converted"]
    assert 0 < row["use"]["value"] < 12
    bad = api.post(f"{M}/tasks/{decision['task_id']}/optimise", json={"nope": 1})
    assert bad.status_code == 422 and "Unknown input: nope" in bad.json()["detail"]
    routine = api.post(f"{M}/positions", json={"name": "Hut"}).json()
    task = api.post(f"{M}/tasks", json={"subject": {"kind": "position", "id": routine["id"]}, "name": "Sweep",
                                        "interval": 1, "unit": "weeks"})
    if task.status_code == 200:
        body = api.post(f"{M}/tasks/{task.json()['id']}/optimise", json={}).json()
        assert body["modes"] == []


def test_round_down_matches_the_apps_use():
    from backend.maintenance.task_optimise import round_down

    assert [round_down(v) for v in (96.00008, 101.02, 63.5, 14885, 4.27, 0)] == [96, 101, 63, 14800, 4.2, None]


def test_mcp_optimise_task_action(api):
    from backend.maintenance import mcp_tools

    mcp_tools.register()
    try:
        assert "rcm.optimise" in mcp_tools.TOOL_TABLES["maintenance"][1]
    finally:
        mcp_tools.unregister()


def test_an_lsa_with_an_unpriced_trade_is_never_the_whole_planned_cost(api):
    mode_id, task_id, position_id, model_id = _plug(api)
    api.patch(f"{M}/tasks/{task_id}", json={"cost": None, "resources": {
        "labour": [{"trade": "Unpriced fitter", "people": 1, "hours": 0.3}],
        "consumables": [{"name": "Spark plug", "qty": 2, "unit": "each", "cost": 11}]}})
    row = api.post(f"{M}/tasks/{task_id}/optimise", json={"unplanned_cost": 900}).json()["modes"][0]
    planned = row["inputs"]["planned_cost"]
    assert planned["source"] == "task_partial" and "Unpriced fitter" in planned["text"]


def test_the_failure_modes_own_failure_cost_is_what_optimise_reads(api):
    """The failure cost entered on the mode (failure_costs.py), with its downtime at the cost of an hour
    down, is the unplanned cost Optimise starts from: the same figure the forecast charges."""
    mode_id, task_id, _position_id, _model_id = _plug(api)
    api.patch(f"{M}/failure-modes/{mode_id}", json={"failure_cost": 800, "downtime_hours": 4, "downtime_rate": 25})
    row = api.post(f"{M}/tasks/{task_id}/optimise", json={}).json()["modes"][0]
    assert row["inputs"]["unplanned_cost"]["value"] == 900 and row["inputs"]["unplanned_cost"]["source"] == "mode"
    assert row["use"] == {"value": 96, "unit": "hours"}


def test_a_task_on_a_calendar_rule_can_keep_it_at_the_nearest_step(api):
    mode_id, decision = _mode(api, outcome="on_condition", task="Check the belt", interval=1, unit="months")
    task_id = decision["task_id"]
    r = api.patch(f"{M}/tasks/{task_id}", json={"rule": {"kind": "weekly", "weekdays": ["Monday"]}})
    assert r.status_code == 200, r.text
    body = {"pf_interval": 120, "pf_unit": "days"}
    out = api.post(f"{M}/tasks/{task_id}/optimise", json=body).json()
    row = out["modes"][0]
    assert out["task"]["rule_text"] == "every Monday"
    # Half of 120 days, in the task's own unit, rounded down: 8 weeks; as a rule, every 8 weeks on Monday.
    assert row["use"] == {"value": 8, "unit": "weeks"}
    assert row["use_rule"]["words"] == "every 8 weeks on Monday"
    u = api.post(f"{M}/tasks/{task_id}/optimise/use", json={**body, "as_rule": True}).json()
    assert u["rule_text"] == "every 8 weeks on Monday"
    task = api.get(f"{M}/tasks/{task_id}/lsa").json()["task"]
    assert task["rule"]["every"] == 8 and (task["interval"], task["unit"]) == (8, "weeks")
