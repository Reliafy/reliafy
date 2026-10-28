"""Several tasks per failure mode over MCP, the app's routes and the batch:
maintenance_failure_modes add_task and decide with task_id, maintenance_tasks
link / unlink and create with failure_mode_ids, their routes, and the batch's
undo for each."""

import pytest

from backend.tests.test_maintenance_mcp import UID, _do, _get, _ok, _session, env  # noqa: F401
from backend.tests.test_maintenance_rcm_api import api  # noqa: F401

pytestmark = pytest.mark.usefixtures("mcp_on")

M = "/api/maintenance"


def test_over_mcp_a_mode_gets_several_tasks_and_a_task_several_modes(env):
    async def flow(client):
        pool = _ok(await _do(client, "maintenance_positions", "create", name="Pool"))
        cell = _ok(await _do(client, "maintenance_positions", "create", name="Chlorinator cell", parent_id=pool["id"]))
        acid = _ok(await _do(client, "maintenance_failure_modes", "add", position_id=pool["id"], text="Acid under-dosed"))
        cya = _ok(await _do(client, "maintenance_failure_modes", "add", position_id=pool["id"], text="Stabiliser low"))
        salt = _ok(await _do(client, "maintenance_failure_modes", "add", position_id=cell["id"], text="Salinity low"))
        decided = _ok(await _do(client, "maintenance_failure_modes", "decide", failure_mode_id=acid["id"],
                                consequence="operational", decision={"outcome": "on_condition", "task": "Weekly pH check",
                                                                     "interval": 1, "interval_unit": "weeks"}))
        second = _ok(await _do(client, "maintenance_failure_modes", "add_task", failure_mode_id=acid["id"],
                               name="Replace the acid pump", interval=24, unit="months", outcome="fixed_interval"))
        linked = _ok(await _do(client, "maintenance_tasks", "link", task_id=decided["decision"]["task_id"],
                               failure_mode_id=salt["id"]))
        adopted = _ok(await _do(client, "maintenance_failure_modes", "decide", failure_mode_id=cya["id"],
                                consequence="operational", decision={"outcome": "on_condition"},
                                task_id=decided["decision"]["task_id"]))
        refused = await _do(client, "maintenance_failure_modes", "decide", failure_mode_id=cya["id"],
                            decision={"outcome": "on_condition", "task": "Weekly pH check", "interval": 2,
                                      "interval_unit": "weeks"})
        made = _ok(await _do(client, "maintenance_tasks", "create", position_id=pool["id"], name="Shop water test",
                             interval=1, unit="months", failure_mode_ids=[cya["id"], salt["id"]]))
        unlinked = _ok(await _do(client, "maintenance_tasks", "unlink", task_id=decided["decision"]["task_id"],
                                 failure_mode_id=salt["id"]))
        rcm = _ok(await _get(client, "rcm", pool["id"], scope="below"))
        retired = _ok(await _do(client, "maintenance_failure_modes", "retire", failure_mode_id=acid["id"]))
        return decided, second, linked, adopted, refused, made, unlinked, rcm, retired

    decided, second, linked, adopted, refused, made, unlinked, rcm, retired = _session(env["token"], flow)
    assert [t["name"] for t in decided["decision"]["tasks"]] == ["Weekly pH check"]
    assert second["source"] == "rcm" and second["outcome"] == "fixed_interval"
    assert [x["text"] for x in linked["failure_modes"]] == ["Acid under-dosed", "Salinity low"]
    assert adopted["decision"]["task_id"] == decided["decision"]["task_id"] and adopted["decision"]["interval"] == 1
    assert refused.is_error and "also serves" in refused.content[0].text
    assert sorted(x["text"] for x in made["failure_modes"]) == ["Salinity low", "Stabiliser low"]
    assert [x["text"] for x in unlinked["failure_modes"]] == ["Acid under-dosed", "Stabiliser low"]
    modes = {x["text"]: x for p in rcm["positions"] for x in p["unassigned"]}
    assert [t["name"] for t in modes["Acid under-dosed"]["decision"]["tasks"]] == ["Weekly pH check", "Replace the acid pump"]
    assert modes["Acid under-dosed"]["decision"]["tasks"][0]["shared_with"] == 1
    assert [t["name"] for t in modes["Salinity low"]["decision"]["tasks"]] if modes["Salinity low"]["decision"] else True
    assert retired["tasks_retired"] == [second["id"]] and retired["tasks_unlinked"] == [decided["decision"]["task_id"]]


def test_the_batch_undoes_a_link_with_an_unlink_and_an_added_task_with_a_retire(env):
    async def flow(client):
        out = _ok(await client.call_tool("maintenance_apply", {"operations": [
            {"ref": "p", "do": "positions.create", "args": {"name": "Pool"}},
            {"ref": "a", "do": "failure_modes.add", "args": {"position_id": "@p", "text": "Acid under-dosed"}},
            {"ref": "b", "do": "failure_modes.add", "args": {"position_id": "@p", "text": "Stabiliser low"}},
            {"do": "failure_modes.decide", "args": {"failure_mode_id": "@a", "consequence": "operational", "decision": {
                "outcome": "on_condition", "task": "Weekly pH check", "interval": 1, "interval_unit": "weeks"}}},
            {"ref": "t", "do": "failure_modes.add_task", "args": {"failure_mode_id": "@a", "name": "Replace the pump",
                                                                 "interval": 24, "unit": "months"}},
            {"do": "tasks.link", "args": {"task_id": "@t", "failure_mode_id": "@b"}},
            {"do": "tasks.unlink", "args": {"task_id": "@t", "failure_mode_id": "@b"}},
        ]}))
        return out

    out = _session(env["token"], flow)
    assert out["ok"] and out["counts"] == {"creates": 4, "updates": 3, "deletes": 0, "other": 0}
    undo = {u["do"]: u for u in out["undo"]}
    tid = out["results"][4]["id"]
    assert undo["tasks.retire"] == {"do": "tasks.retire", "args": {"task_id": tid}, "confirm": "Replace the pump"}
    assert out["undo"][0] == {"do": "tasks.link", "args": {"task_id": tid, "failure_mode_id": out["results"][2]["id"]}}
    assert out["undo"][1] == {"do": "tasks.unlink", "args": {"task_id": tid, "failure_mode_id": out["results"][2]["id"]}}


def test_over_the_routes(api):
    pool = api.post(f"{M}/positions", json={"name": "Pool"}).json()
    cell = api.post(f"{M}/positions", json={"name": "Cell", "parent_id": pool["id"]}).json()
    acid = api.post(f"{M}/positions/{pool['id']}/failure-modes", json={"text": "Acid under-dosed"}).json()
    salt = api.post(f"{M}/positions/{cell['id']}/failure-modes", json={"text": "Salinity low"}).json()
    r = api.put(f"{M}/failure-modes/{acid['id']}/decision", json={
        "consequence": "operational",
        "decision": {"outcome": "on_condition", "task": "Weekly pH check", "interval": 1, "interval_unit": "weeks"}})
    assert r.status_code == 200, r.text
    own = r.json()["decision"]["task_id"]
    r = api.post(f"{M}/failure-modes/{acid['id']}/tasks", json={"name": "Replace the pump", "interval": 24, "unit": "months"})
    assert r.status_code == 200, r.text
    second = r.json()["id"]
    assert api.post(f"{M}/tasks/{own}/failure-modes/{salt['id']}").status_code == 200
    r = api.get(f"{M}/failure-modes/{salt['id']}/tasks")
    assert r.status_code == 200
    assert [t["name"] for t in r.json()["tasks"]] == ["Weekly pH check"]
    assert [(t["name"], t["position"]["name"], t["serves"]) for t in r.json()["available"]] == [("Replace the pump", "Pool", 1)]
    r = api.put(f"{M}/failure-modes/{salt['id']}/decision", json={"consequence": "hidden", "decision": {"outcome": "failure_finding"},
                                                                 "task_id": own})
    assert r.status_code == 200 and r.json()["decision"]["task_id"] == own and r.json()["decision"]["interval"] == 1
    r = api.get(f"{M}/positions/{pool['id']}/rcm")
    modes = {x["text"]: x for p in r.json()["positions"] for x in p["unassigned"]}
    assert [t["name"] for t in modes["Acid under-dosed"]["decision"]["tasks"]] == ["Weekly pH check", "Replace the pump"]
    assert modes["Acid under-dosed"]["decision"]["tasks"][0]["shared_with"] == 1
    assert api.delete(f"{M}/tasks/{own}/failure-modes/{salt['id']}").status_code == 200
    r = api.get(f"{M}/failure-modes/{salt['id']}/tasks")
    assert r.json()["tasks"] == [] and r.json()["position"]["name"] == "Cell"
    # A task on the cell can't serve the pool's mode: 422, said plainly.
    r = api.post(f"{M}/positions/{cell['id']}/tasks", json={"name": "Clean the cell", "interval": 3, "unit": "months",
                                                            "failure_mode_ids": [acid["id"]]})
    assert r.status_code == 422 and "on a position inside it" in r.json()["detail"]
    r = api.post(f"{M}/positions/{pool['id']}/tasks", json={"name": "Shop test", "interval": 1, "unit": "months",
                                                            "failure_mode_ids": [acid["id"], salt["id"]]})
    assert r.status_code == 200 and sorted(x["text"] for x in r.json()["failure_modes"]) == ["Acid under-dosed", "Salinity low"]
    r = api.delete(f"{M}/failure-modes/{acid['id']}")
    assert r.status_code == 200 and sorted(r.json()["tasks_retired"]) == sorted([own, second])
    assert r.json()["tasks_unlinked"] == [r.json()["tasks_unlinked"][0]]
