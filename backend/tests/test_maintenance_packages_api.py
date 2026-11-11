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
        marked = _ok(await client.call_tool("maintenance", {"action": "apply", "operations": [
            {"do": "work_orders.mark", "args": {"work_order_id": wo_id, "task_id": wo["lines"][1]["task_id"],
                                                "state": "not_done", "reason": "rain"}},
            {"do": "work_orders.mark", "args": {"work_order_id": wo_id, "task_id": wo["lines"][0]["task_id"],
                                                "state": "problem", "finding": {"kind": "inspect",
                                                                                "finding": "degraded"}}}]}))
        closed = _ok(await _do(client, "maintenance", "work_orders.close", work_order_id=wo_id,
                               not_done=[{"task_id": line["task_id"], "reason": "rain"} for line in wo["lines"][2:]],
                               actions=[{"kind": "inspect", "finding": "ok", "position_id": pump["id"]}]))
        package = _ok(await _get(client, "package", package_id))
        listed = _ok(await client.call_tool("maintenance", {"action": "list.packages"}))
        guide = _ok(await client.call_tool("maintenance", {"action": "guide", "topic": "plan"}))
        return draft, dry, listed_dry, real, made, wo, refused, closed, package, listed, guide, marked

    draft, dry, listed_dry, real, made, wo, refused, closed, package, listed, guide, marked = _session(env["token"], flow)
    assert draft["cadence"] == "weekly" and len(draft["tasks"]) == 3
    assert dry["dry_run"] and listed_dry["packages"] == []
    undo = [u["do"] for u in real["undo"]]
    assert undo == ["packages.remove_task", "packages.add_task", "packages.retire"]
    assert len(made["work_orders"]) == 1 and made["packages"][0]["lines"] == 3
    assert len(wo["lines"]) == 3 and wo["package"]["name"] == draft["name"]
    assert refused.is_error and "Say whether each line" in refused.content[0].text
    assert closed["status"] == "closed" and len(closed["released"]) == 2
    assert [a["finding"] for a in closed["actions"]] == ["ok", "degraded"]
    assert [u["do"] for u in marked["undo"]] == ["work_orders.mark", "work_orders.mark"]
    assert marked["undo"][0]["args"]["state"] == "done"  # line 0 was ticked before
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
    wo = api.post(f"{M}/work-orders/generate", json={"horizon_days": 30}).json()["work_orders"][0]
    marked = api.put(f"{M}/work-orders/{wo['id']}/lines/{task['id']}", json={"state": "not_done", "reason": "rain"})
    assert marked.status_code == 200, marked.text
    assert marked.json()["lines"][0]["state"] == "not_done"
    assert api.put(f"{M}/work-orders/{wo['id']}/lines/{task['id']}", json={"state": "nope"}).status_code == 422
    closed = api.post(f"{M}/work-orders/{wo['id']}/close", json={})
    assert closed.status_code == 200 and closed.json()["released"][0]["reason"] == "rain"
    assert api.post(f"{M}/packages/{pid}/retire").json()["retired"] == pid
    assert api.get(f"{M}/packages", params={"status": "retired"}).json()["packages"][0]["status"] == "retired"
    assert api.post(f"{M}/packages/{pid}/restore").json()["status"] == "active"


def test_pause_season_and_out_of_service_over_mcp(env):
    async def flow(client):
        site = _ok(await _do(client, "maintenance", "positions.create", name="Spa"))
        task = _ok(await _do(client, "maintenance", "tasks.create", position_id=site["id"], name="Test water",
                             interval=1, unit="weeks"))
        made = _ok(await client.call_tool("maintenance", {"action": "apply", "operations": [
            {"ref": "p", "do": "packages.create", "args": {
                "name": "Spa check", "position_id": site["id"], "weekday": "saturday", "tasks": [task["id"]],
                "season": {"months": [10, 11, 12, 1, 2, 3]}}},
            {"do": "packages.pause", "args": {"package_id": "@p", "reason": "heater broken", "until": "2099-01-01"}},
            {"do": "positions.out_of_service", "args": {"position_id": site["id"], "reason": "resurfacing",
                                                        "until": "2099-02-01"}}]}))
        dry = _ok(await client.call_tool("maintenance", {"action": "apply", "dry_run": True, "operations": [
            {"do": "positions.back_in_service", "args": {"position_id": site["id"]}}]}))
        package = _ok(await _get(client, "package", made["results"][0]["result"]["id"]))
        position = _ok(await _get(client, "position", site["id"]))
        return made, dry, package, position

    made, dry, package, position = _session(env["token"], flow)
    assert [u["do"] for u in made["undo"]] == ["positions.back_in_service", "packages.resume", "packages.retire"]
    assert dry["dry_run"] and dry["ok"]
    assert package["status"] == "paused" and package["pause"]["until"] == "2099-01-01"
    assert package["season"]["months"] == [1, 2, 3, 10, 11, 12]
    assert position["out_of_service"]["reason"] == "resurfacing"


def test_out_of_service_routes(api):
    pos = api.post(f"{M}/positions", json={"name": "Pump"}).json()
    out = api.post(f"{M}/positions/{pos['id']}/out-of-service", json={"reason": "rebuild", "until": "2099-01-01"})
    assert out.status_code == 200, out.text
    assert out.json()["out_of_service"]["now"]
    assert api.post(f"{M}/positions/{pos['id']}/back-in-service").json()["out_of_service"] is None
    assert api.post(f"{M}/positions/{pos['id']}/back-in-service").status_code == 422
    assert api.post(f"{M}/widgets/{pos['id']}/out-of-service", json={}).status_code == 404


def test_package_the_tasks_routes(api):
    """The Explorer's Packages tab: a layered proposal on a weekday, made in one batch, then
    read for the branch."""
    site = api.post(f"{M}/positions", json={"name": "Pool"}).json()
    pump = api.post(f"{M}/positions", json={"name": "Pump", "parent_id": site["id"]}).json()
    for name, interval, unit in (("Skim", 1, "weeks"), ("Test water", 1, "weeks"), ("Clean cell", 1, "months")):
        api.post(f"{M}/positions/{pump['id']}/tasks", json={"name": name, "interval": interval, "unit": unit})
    proposed = api.get(f"{M}/packages/propose", params={"position_id": site["id"], "weekday": "saturday"})
    assert proposed.status_code == 200, proposed.text
    drafts = proposed.json()["drafts"]
    assert [d["layer_of"] is None for d in drafts] == [True, False]
    assert api.get(f"{M}/packages/propose", params={"weekday": "funday"}).status_code == 422
    batch = [{"ref": d["ref"], **d["create"]} for d in drafts]
    assert api.post(f"{M}/packages/batch", json={"packages": []}).status_code == 422
    made = api.post(f"{M}/packages/batch", json={"packages": batch})
    assert made.status_code == 200, made.text
    assert [c["layer_of"] for c in made.json()["created"]] == [None, f"@{drafts[0]['ref']}"]
    here = api.get(f"{M}/packages", params={"position_id": pump["id"]}).json()["packages"]
    assert {p["name"] for p in here} == {d["name"] for d in drafts}
    elsewhere = api.post(f"{M}/positions", json={"name": "Shed"}).json()
    assert api.get(f"{M}/packages", params={"position_id": elsewhere["id"]}).json()["packages"] == []


def test_make_packages_from_drafts_whose_tasks_are_on_different_positions(api):
    """Package the tasks…, then Make: a visit's first task on one position and its layer's on
    another are both made, by the batch the page sends."""
    top = api.post(f"{M}/positions", json={"name": "Generator set"}).json()
    battery = api.post(f"{M}/positions", json={"name": "Battery", "parent_id": top["id"]}).json()
    alternator = api.post(f"{M}/positions", json={"name": "Alternator", "parent_id": top["id"]}).json()
    for pos, name, interval in ((battery, "Test battery", 3), (alternator, "Load bank test", 6)):
        made = api.post(f"{M}/positions/{pos['id']}/tasks",
                        json={"name": name, "interval": interval, "unit": "months", "trade": "Electrician"})
        assert made.status_code == 200, made.text
    drafts = api.get(f"{M}/packages/propose", params={"position_id": top["id"], "weekday": "monday"}).json()["drafts"]
    assert [d["layer_of"] is None for d in drafts] == [True, False]
    batch = [{"ref": d["ref"], **d["create"], **({} if d["layer_of"] else {"tolerance": 1, "tolerance_unit": "days"})}
             for d in drafts]
    made = api.post(f"{M}/packages/batch", json={"packages": batch})
    assert made.status_code == 200, made.text
    assert [c["name"] for c in made.json()["created"]] == [d["name"] for d in drafts]
    listed = api.get(f"{M}/packages", params={"position_id": top["id"]}).json()["packages"]
    assert {p["name"] for p in listed} == {d["name"] for d in drafts}
    for pos in (battery, alternator):
        here = api.get(f"{M}/packages", params={"position_id": pos["id"]}).json()["packages"]
        assert len(here) >= 1
    again = api.get(f"{M}/packages/propose", params={"position_id": top["id"], "weekday": "monday"}).json()
    assert again["drafts"] == [] and again["already_in_packages"] == 2


def test_task_table_route(api):
    site = api.post(f"{M}/positions", json={"name": "Pool"}).json()
    pump = api.post(f"{M}/positions", json={"name": "Pump", "parent_id": site["id"]}).json()
    api.post(f"{M}/positions/{pump['id']}/tasks", json={"name": "Skim", "interval": 1, "unit": "weeks"})
    got = api.get(f"{M}/task-table", params={"position_id": site["id"]})
    assert got.status_code == 200, got.text
    [row] = got.json()["tasks"]
    assert row["name"] == "Skim" and row["subject"]["name"] == "Pump" and row["package"] is None
    assert api.get(f"{M}/task-table").status_code == 422
