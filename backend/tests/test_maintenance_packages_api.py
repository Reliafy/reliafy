"""Work packages over MCP (maintenance packages.…, inside maintenance apply with
its dry run and undo, work_orders.close with not_done and position_id) and the
app's own routes."""

import pytest

from backend.tests.test_maintenance_mcp import _do, _get, _ok, _session, env  # noqa: F401
from backend.tests.test_maintenance_rcm_api import api  # noqa: F401

pytestmark = pytest.mark.usefixtures("mcp_on")

M = "/api/maintenance"


def test_over_mcp_propose_create_generate_and_close(env):
    async def flow(client):
        site = _ok(await _do(client, "maintenance", "positions.create", name="Reservoir"))
        pump = _ok(await _do(client, "maintenance", "positions.create", name="Intake pump", parent_id=site["id"]))
        tasks = [_ok(await _do(client, "maintenance", "tasks.create", position_id=pump["id"], name=f"Look {k}",
                               interval=1, unit="weeks")) for k in range(3)]
        proposed = _ok(await _do(client, "maintenance", "packages.propose", position_id=site["id"]))
        draft = proposed["drafts"][0]
        dry = _ok(await client.call_tool("maintenance", {"action": "apply", "dry_run": True, "operations": [
            {"ref": "w", "do": "packages.create", "args": {**draft["create"], "weekday": "saturday",
                                                           "tolerance": 1}}]}))
        listed_dry = _ok(await client.call_tool("maintenance", {"action": "list.packages"}))
        real = _ok(await client.call_tool("maintenance", {"action": "apply", "operations": [
            {"ref": "w", "do": "packages.create", "args": {**draft["create"], "weekday": "saturday",
                                                           "tolerance": 1}},
            {"do": "packages.remove_task", "args": {"package_id": "@w", "task_id": tasks[2]["id"]}},
            {"do": "packages.add_task", "args": {"package_id": "@w", "task_id": tasks[2]["id"],
                                                 "visit_rule": "nth", "every_nth": 2}}]}))
        package_id = real["results"][0]["result"]["id"]
        made = _ok(await _do(client, "maintenance", "work_orders.generate", horizon_days=14))
        wo_id = made["work_orders"][0]["id"]
        wo = _ok(await _get(client, "work_order", wo_id))
        for line in wo["lines"][:1]:
            _ok(await _do(client, "maintenance", "work_orders.check", work_order_id=wo_id, index=line["index"]))
        refused = await _do(client, "maintenance", "work_orders.close", work_order_id=wo_id)
        closed = _ok(await _do(client, "maintenance", "work_orders.close", work_order_id=wo_id,
                               not_done=[{"task_id": line["task_id"], "reason": "rain"} for line in wo["lines"][1:]],
                               actions=[{"kind": "inspect", "finding": "ok", "position_id": pump["id"]}]))
        package = _ok(await _get(client, "package", package_id))
        listed = _ok(await client.call_tool("maintenance", {"action": "list.packages"}))
        guide = _ok(await client.call_tool("maintenance", {"action": "guide", "topic": "plan"}))
        return draft, dry, listed_dry, real, made, wo, refused, closed, package, listed, guide, tasks

    draft, dry, listed_dry, real, made, wo, refused, closed, package, listed, guide, tasks = _session(env["token"], flow)
    assert draft["cadence"] == "weekly" and len(draft["tasks"]) == 3
    assert dry["dry_run"] and listed_dry["packages"] == []
    undo = [u["do"] for u in real["undo"]]
    assert undo == ["packages.remove_task", "packages.add_task", "packages.retire"]
    assert len(made["work_orders"]) == 1 and made["packages"][0]["lines"] == 3
    assert len(wo["lines"]) == 3 and wo["package"]["name"] == draft["name"]
    assert refused.is_error and "Say whether each line" in refused.content[0].text
    assert closed["status"] == "closed" and len(closed["released"]) == 2
    assert closed["actions"][0]["kind"] == "inspect"
    assert package["tasks"][-1]["visit_rule"] == "nth" and package["status"] == "active"
    assert listed["packages"][0]["id"] == package["id"] and listed["late"] == 0
    assert "Work packages" in guide["guide"]


def test_app_routes(api):
    site = api.post(f"{M}/positions", json={"name": "Reservoir"}).json()
    task = api.post(f"{M}/positions/{site['id']}/tasks", json={"name": "Look", "interval": 1, "unit": "weeks"}).json()
    other = api.post(f"{M}/positions/{site['id']}/tasks", json={"name": "Fence", "interval": 1, "unit": "weeks"}).json()
    proposed = api.get(f"{M}/packages/propose", params={"position_id": site["id"]})
    assert proposed.status_code == 200 and proposed.json()["drafts"][0]["cadence"] == "weekly"
    made = api.post(f"{M}/packages", json={"name": "Reservoir weekly", "position_id": site["id"], "unit": "weeks",
                                           "weekday": "saturday", "tolerance": 1, "tasks": [task["id"]]})
    assert made.status_code == 200, made.text
    pid = made.json()["id"]
    assert api.post(f"{M}/packages/{pid}/tasks", json={"task_id": other["id"]}).json()["task_count"] == 2
    assert api.delete(f"{M}/packages/{pid}/tasks/{other['id']}").json()["task_count"] == 1
    changed = api.patch(f"{M}/packages/{pid}", json={"name": "Reservoir walk", "every": 2})
    assert changed.status_code == 200, changed.text
    assert changed.json()["cadence"]["text"] == "every 2 weeks on Saturday"
    assert api.post(f"{M}/packages/{pid}/pause", json={"reason": "drained"}).json()["status"] == "paused"
    assert api.post(f"{M}/packages/{pid}/resume").json()["status"] == "active"
    assert api.post(f"{M}/packages/{pid}/frobnicate").status_code == 404
    listed = api.get(f"{M}/packages").json()
    assert [p["name"] for p in listed["packages"]] == ["Reservoir walk"]
    assert api.get(f"{M}/packages/{pid}").json()["tasks"][0]["task_id"] == task["id"]
    assert api.post(f"{M}/packages", json={"name": "Nowhere"}).status_code == 422
    assert api.post(f"{M}/packages/{pid}/retire").json()["retired"] == pid
    assert api.get(f"{M}/packages", params={"status": "retired"}).json()["packages"][0]["status"] == "retired"
    assert api.post(f"{M}/packages/{pid}/restore").json()["status"] == "active"
