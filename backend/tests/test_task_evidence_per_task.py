"""Each task keeps its own working (Nov 2026): a failure mode with an on-condition check and a
fixed-interval replacement, each interval worked out and used on its own task. Using the
replacement's answer never replaces the check's P-F working, the new task never reads the check's
working as its own, and the forecast counts both tasks: the check's detection and the
replacement's renewal."""

from backend.tests.test_maintenance_rcm_api import api  # noqa: F401 - fixture
from backend.tests.test_rcm_intervals import _decision_in, _mode

M = "/api/maintenance"
# A generator belt that wears out: Weibull, about 400 flight hours, shape 3.
BELT = [{"name": "alpha", "value": 400.0}, {"name": "beta", "value": 3.0}]


def _members(api, mode_id):
    position_id = api.get(f"{M}/failure-modes/{mode_id}/tasks").json()["position"]["id"]
    d = _decision_in(api.get(f"{M}/positions/{position_id}/rcm?scope=this").json(), mode_id)
    return d, {o["task_id"]: (o.get("evidence") or {}).get("id") for o in d.get("outcomes") or []}


def _belt(api):
    mode_id, decision = _mode(api, outcome="on_condition", task="Inspect generator belt", interval=25, unit="hours")
    check = decision["task_id"]
    position_id = api.get(f"{M}/failure-modes/{mode_id}/tasks").json()["position"]["id"]
    model = api.post("/api/models/from-params", json={"name": "Generator belt life", "distribution": "weibull",
                                                       "params": BELT, "unit": "hours"}).json()
    r = api.post(f"{M}/positions/{position_id}/models", json={"model_id": model["id"], "failure_mode_ids": [mode_id]})
    assert r.status_code == 200, r.text
    # A belt fitted new today, flying 20 hours a week (about 1,040 a year).
    r = api.post(f"{M}/positions/{position_id}/fit", json={"new_item": {"name": "Belt SN1"}})
    assert r.status_code == 200, r.text
    r = api.put(f"{M}/positions/{position_id}/operating-plan",
                json={"plan": {"background": {"kind": "rate", "amount": 20, "per": "week"}}})
    assert r.status_code == 200, r.text
    meter = api.post(f"{M}/positions/{position_id}/points", json={"name": "Flight hours", "kind": "counter",
                                                                 "unit": "hours"}).json()["id"]
    assert api.post(f"{M}/points/{meter}/readings", json={"value": 0}).status_code == 200
    return mode_id, check, position_id


def _failures(api, position_id):
    fc = api.get(f"{M}/positions/{position_id}/forecast?period=year&periods=3")
    assert fc.status_code == 200, fc.text
    fc = fc.json()
    row = next(r for r in fc["models"] if r["name"] == "Generator belt life")
    return row["expected_failures"], [t["task"]["name"] for t in row.get("tasks_counted") or []]


def test_use_on_each_task_keeps_both_workings_and_the_forecast_counts_both(api):
    mode_id, check, position_id = _belt(api)
    # The check's interval from its P-F interval: 120 h warning, so every 60 h.
    pf = api.post(f"{M}/tasks/{check}/optimise/use", json={"pf_interval": 120, "pf_unit": "hours"})
    assert pf.status_code == 200, pf.text
    pf = pf.json()
    assert pf["interval"] == 60 and pf["evidence_linked"]
    only_check, _ = _failures(api, position_id)

    # A replacement added to the same failure mode: it has no working of its own yet.
    r = api.post(f"{M}/failure-modes/{mode_id}/tasks",
                 json={"name": "Replace generator belt", "interval": 50, "unit": "hours", "outcome": "fixed_interval"})
    assert r.status_code == 200, r.text
    change = r.json()["id"]
    _, ev = _members(api, mode_id)
    assert ev == {check: pf["analysis"]["id"], change: None}
    got = api.get(f"{M}/failure-modes/{mode_id}/interval-inputs?task_id={change}").json()
    assert got["evidence"] is None  # never the check's P-F working
    assert api.get(f"{M}/failure-modes/{mode_id}/interval-inputs?task_id={check}").json()["evidence"]["id"] == \
        pf["analysis"]["id"]

    # The replacement's interval from the belt's life: $127.50 planned against $1,500 a failure.
    api.patch(f"{M}/tasks/{change}", json={"cost": 127.5})
    rep = api.post(f"{M}/tasks/{change}/optimise/use", json={"unplanned_cost": 1500})
    assert rep.status_code == 200, rep.text
    rep = rep.json()
    assert rep["evidence_linked"]
    _, ev = _members(api, mode_id)
    assert ev == {check: pf["analysis"]["id"], change: rep["analysis"]["id"]}  # each its own

    # The forecast counts both: the check still finds the warnings, so failures stay low.
    both, counted = _failures(api, position_id)
    assert set(counted) >= {"Inspect generator belt", "Replace generator belt"}
    assert both <= only_check + 1e-9

    # "Use" on the check again: the replacement's working stays.
    again = api.post(f"{M}/tasks/{check}/optimise/use", json={"pf_interval": 120, "pf_unit": "hours"}).json()
    _, ev = _members(api, mode_id)
    assert ev == {check: again["analysis"]["id"], change: rep["analysis"]["id"]}
    sheet = api.get(f"{M}/positions/{position_id}/rcm?scope=this").json()
    assert _decision_in(sheet, mode_id)["evidence"] is None


def test_an_older_record_with_the_working_on_the_decision_keeps_it_for_its_own_task(api):
    """A combination saved before each task kept its own: the check's P-F working on the decision.
    The check still reads it; the replacement doesn't; using the replacement's answer moves the
    check's onto the check instead of dropping it."""
    mode_id, check, position_id = _belt(api)
    pf = api.post(f"{M}/tasks/{check}/optimise/use", json={"pf_interval": 120, "pf_unit": "hours"}).json()
    ev = {"type": "strategy_analysis", "id": pf["analysis"]["id"]}
    r = api.put(f"{M}/failure-modes/{mode_id}/decision", json={"decision": {"evidence": ev, "outcomes": [
        {"outcome": "on_condition", "task_id": check},
        {"outcome": "fixed_interval", "task": "Replace generator belt", "interval": 50, "interval_unit": "hours"}]}})
    assert r.status_code == 200, r.text
    d, members = _members(api, mode_id)
    change = next(t for t in members if t != check)
    assert d["evidence"]["id"] == ev["id"] and members == {check: None, change: None}  # the older shape
    assert api.get(f"{M}/failure-modes/{mode_id}/interval-inputs?task_id={change}").json()["evidence"] is None
    assert api.get(f"{M}/failure-modes/{mode_id}/interval-inputs?task_id={check}").json()["evidence"]["id"] == ev["id"]
    api.patch(f"{M}/tasks/{change}", json={"cost": 127.5})
    rep = api.post(f"{M}/tasks/{change}/optimise/use", json={"unplanned_cost": 1500}).json()
    d, members = _members(api, mode_id)
    assert members == {check: ev["id"], change: rep["analysis"]["id"]} and not d.get("evidence")
    _, counted = _failures(api, position_id)
    assert set(counted) >= {"Inspect generator belt", "Replace generator belt"}


def test_the_mcp_save_evidence_links_the_new_tasks_own_working(api):
    """maintenance rcm.pf_interval with save_evidence (rcm_apply_interval) on a combination's second
    task: linked on that task, its own being none (the decision's working is the first task's), and
    the first task's kept."""
    from backend.maintenance import mcp_tools
    from backend.routers import maintenance as router
    from backend.services import rcm_intervals
    from backend.tests.test_maintenance_rcm_api import UID

    mode_id, check, _ = _belt(api)
    pf = api.post(f"{M}/tasks/{check}/optimise/use", json={"pf_interval": 120, "pf_unit": "hours"}).json()
    r = api.post(f"{M}/failure-modes/{mode_id}/tasks",
                 json={"name": "Inspect belt pulley side", "interval": 50, "unit": "hours", "outcome": "on_condition"})
    second = r.json()["id"]
    m = router.Maintenance(router.get_store(), UID, UID)
    inputs = {"pf_interval": 80, "pf_unit": "hours", "detection_probability": 0.9}
    out = rcm_intervals.on_condition_interval(**inputs)
    saved = mcp_tools.rcm_apply_interval(m, mode_id, second, "pf_interval", inputs, out, UID)
    assert saved["evidence_linked"] is True
    _, members = _members(api, mode_id)
    assert members[check] == pf["analysis"]["id"] and members[second] == saved["analysis"]["id"]
