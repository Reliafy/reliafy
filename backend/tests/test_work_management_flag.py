"""Work management turned off (WORK_MANAGEMENT; MAINTENANCE_WORK_ORDERS is its old name).

Off, Reliafy is reliability software: the tree, RCM and its tasks, maintenance plans as
hypothetical plans, forecasts, spares, readings, history and FRACAS all work. Everything
about executing work is refused and hidden: work orders (raising, closing, labour, parts),
package visits, alarms and triggers raising work, the to-do list of what's due. Nothing
in the log is deleted: work orders already there are hidden and show again when it's back
on. A task's "last done" is a plan input set directly on the task: it moves the forecast
and writes nothing else (no work done, no fitment, no work order)."""

from datetime import date

import mongomock
import pytest

from backend import config
from backend.maintenance import position_forecast as pf
from backend.maintenance.service import PROJECTORS, Invalid, Maintenance, WorkManagementOff
from backend.maintenance.store import GraphStore
from backend.tests.test_maintenance_mcp import _do, _list, _ok, _session, env  # noqa: F401

ORG = "user-wm-off"
TODAY = "2026-11-20"
OFF_TEXT = "Work management is turned off: Reliafy is set up as reliability software here"


@pytest.fixture()
def off(monkeypatch):
    monkeypatch.setattr(config, "WORK_MANAGEMENT", False)


def _m(store=None) -> Maintenance:
    m = Maintenance(store or GraphStore(":memory:", PROJECTORS), ORG, "tester")
    m.today = lambda: TODAY
    return m


def _rebuilds_the_same(m):
    before = m.s.snapshot()
    m.s.rebuild()
    assert m.s.snapshot() == before


def _pump(m, last_done="2026-06-01"):
    pid = m.create_position("Pool pump")["id"]
    m.fit(pid, new_item={"name": "Pump", "serial": "A1"}, on="2024-01-01")
    mode = m.add_failure_mode(pid, "Bearing worn")["id"]
    task = m.create_task(pid, "Grease bearings", 3, "months", last_done=last_done)
    return pid, mode, task["id"]


def _types(m):
    got = m.s.events(ORG, 5000)
    return [e["type"] for e in (got["events"] if isinstance(got, dict) else got)]


# ---- the flag ----------------------------------------------------------------------------

@pytest.mark.parametrize("env_, on", [
    ({}, True), ({"WORK_MANAGEMENT": "off"}, False), ({"WORK_MANAGEMENT": "on"}, True),
    ({"MAINTENANCE_WORK_ORDERS": "off"}, False),  # the deprecated name still works
    ({"WORK_MANAGEMENT": "on", "MAINTENANCE_WORK_ORDERS": "off"}, True),  # the new name wins
    ({"WORK_MANAGEMENT": "FALSE"}, False), ({"WORK_MANAGEMENT": "0"}, False),
])
def test_the_flag_and_its_old_name(env_, on):
    assert config.work_management_from(env_) is on


# ---- nothing executes work ---------------------------------------------------------------

def test_work_management_refuses_saying_so(off):
    m = _m()
    pid, _, task = _pump(m)
    for call in (lambda: m.open_work_order(pid, "Noisy"),
                 lambda: m.raise_package_visit("any"),
                 lambda: m.close_work_order("any"),
                 lambda: m.log_labour("any", 1),
                 lambda: m.add_part_used("any", "Grease"),
                 lambda: m.cancel_work_order("any")):
        with pytest.raises(WorkManagementOff) as err:
            call()
        assert str(err.value).startswith(OFF_TEXT)
        assert isinstance(err.value, Invalid) and err.value.status == 409
        # FRACAS corrective actions stay available: the refusal never says otherwise.
        assert "corrective actions aren't" not in str(err.value)
        assert "failure reports (with their corrective actions) work as before" in str(err.value)
    assert not hasattr(m, "record_work_done")  # work done is never recorded with it off
    before = m.s.event_count(ORG)
    assert m.generate(30) == {"work_orders": [], "skipped": []}
    assert m.s.event_count(ORG) == before


def test_alarms_and_triggers_raise_nothing_but_the_reading_is_kept(off):
    m = _m()
    pid, _, task = _pump(m)
    point = m.add_point(pid, "Vibration", unit="mm/s", alarm_above=7.1)
    m.update_task(task, trigger={"kind": "reading", "point_id": point["id"], "above": 7})
    view = m.record_reading(point["id"], 7.4, on=TODAY)
    assert view["status"] == "high" and view["alarm_work_order"] is None
    assert not m.s.nodes(ORG, "WorkOrder")


def test_the_daily_run_raises_none_and_sends_no_to_do(off):
    from backend.maintenance import daily

    store = GraphStore(":memory:", PROJECTORS)
    m = Maintenance(store, ORG, "tester")
    m.create_task(m.create_position("Pool pump")["id"], "Grease", 1, "weeks", last_done="2020-01-01")
    db = mongomock.MongoClient()["wm_off_daily"]
    assert daily.run(db, store, today=date(2026, 11, 20), dry_run=True)["work_orders"] == 0
    result = daily.run(db, store, today=date(2026, 11, 20))
    assert result["work_orders"] == 0 and not store.nodes(ORG, "WorkOrder")


def test_nothing_on_the_tree_is_overdue(off):
    m = _m()
    _pump(m, last_done="2020-01-01")
    assert m.tree()[0]["open_work_orders"] == 0
    assert all(not (n.get("status") or {}).get("overdue") for n in m.tree())


# ---- existing work orders: hidden, not deleted -------------------------------------------

def test_existing_work_orders_are_hidden_then_shown_again(monkeypatch):
    m = _m()
    pid, _, task = _pump(m)
    wo = m.open_work_order(None, None, "preventive", task_id=task)
    done = m.open_work_order(pid, "Earlier repair")
    m.close_work_order(done["id"], [{"kind": "repair"}], on="2026-10-01")
    events = m.s.event_count(ORG)

    monkeypatch.setattr(config, "WORK_MANAGEMENT", False)
    m._memo.clear()
    assert m._task_view(m._get(task, "Task"))["open_work_order"] is None
    # The closed one stays history (its repair is still a recurrent event in the data).
    assert [w["id"] for w in m.position(pid)["work_orders"]] == [done["id"]]
    assert m.s.event_count(ORG) == events

    monkeypatch.setattr(config, "WORK_MANAGEMENT", True)
    m._memo.clear()
    assert m._task_view(m._get(task, "Task"))["open_work_order"]["id"] == wo["id"]


# ---- last done: a plan input -------------------------------------------------------------

def test_last_done_moves_the_forecast_and_writes_nothing_else(off):
    m = _m()
    pid, _, task = _pump(m)
    first = pf.position_forecast(m, pid, periods=12)["tasks"][0]["dates"]
    fitments = m.position(pid)["fitments"]
    before = m.s.event_count(ORG)
    view = m.set_last_done(task, "2026-10-01")
    assert view["last_done"] == "2026-10-01" and view["next_due"] == "2027-01-01"
    # One event, a plan parameter: no work done, no work order, no fitment, no reading.
    assert m.s.event_count(ORG) == before + 1 and _types(m)[0] == "task.updated"  # newest first
    assert not m.s.nodes(ORG, "WorkOrder")
    assert m.position(pid)["fitments"] == fitments
    m._memo.clear()
    moved = pf.position_forecast(m, pid, periods=12)["tasks"][0]["dates"]
    assert first[0] == TODAY and moved[0] == "2027-01-01"  # overdue before: counted from today
    _rebuilds_the_same(m)


def test_last_done_is_optional_and_clears_to_the_default(off):
    m = _m()
    pid, _, task = _pump(m, last_done=None)
    # The default: counted from the day the task was added, then from each new item fitted.
    default = m._task_view(m._get(task, "Task"))
    assert default["last_done"] is None and default["next_due"] == "2027-02-20"
    m.set_last_done(task, "2026-10-01")
    view = m.set_last_done(task, "none")
    assert view["last_done"] is None and view["next_due"] == default["next_due"]
    m.remove(pid, on="2026-11-01")
    m.fit(pid, new_item={"name": "Pump", "serial": "B2"}, on="2026-11-02")
    assert m._task_view(m._get(task, "Task"))["last_done"] == "2026-11-02"
    assert "last fitted" in Maintenance.LAST_DONE_DEFAULT
    _rebuilds_the_same(m)
    with pytest.raises(Invalid):
        m.set_last_done(task, "2099-01-01")
    with pytest.raises(Invalid):
        m.set_last_done(task, "2026-01-01", reading=10)  # a calendar task takes no reading


def test_last_done_reading_on_a_task_by_use(off):
    m = _m()
    pid = m.create_position("Compressor")["id"]
    point = m.add_point(pid, "Hours run", unit="hours", kind="counter")
    m.record_reading(point["id"], 1000, on="2026-01-01")
    task = m.create_task(pid, "Oil change", 500, "hours", point_id=point["id"])["id"]
    view = m.set_last_done(task, "2026-06-01", reading=1200)
    assert view["last_done"] == "2026-06-01" and view["last_done_reading"] == 1200
    _rebuilds_the_same(m)


# ---- FRACAS stays whole ------------------------------------------------------------------

def test_fracas_works_in_full_without_work_orders(off):
    """A failure report raised, analysed, given a corrective action that changes the RCM
    task, the action done, verified and the report closed: all with work management off.
    Only linking or raising a work order from the action is refused."""
    m = _m()
    pid, mode, task = _pump(m)
    r = m.file_failure_report(pid, "Bearing seized", occurred_on="2026-11-01", failure_mode_id=mode)
    rid = r["id"]
    m.investigate_failure_report(rid, notes="Dry bearing", root_cause_category="maintenance",
                                 root_cause="Grease interval too long")
    r = m.add_corrective_action(rid, "Grease every 2 months", owner="Planner")
    aid = r["actions"][0]["id"]
    with pytest.raises(WorkManagementOff):
        m.raise_action_work_order(rid, aid)
    with pytest.raises(WorkManagementOff):
        m.add_corrective_action(rid, "Also this", work_order_id="any")
    m.update_task(task, interval=2)  # the corrective action changes the plan
    m.update_corrective_action(rid, aid, status="done")
    m.verify_failure_report(rid, "worked", notes="No repeat")
    r = m.set_failure_report_status(rid, "closed", note="Signed off")
    assert r["status"] == "closed" and r["actions"][0]["status"] == "done"
    assert m._task_view(m._get(task, "Task"))["interval"] == 2
    assert not m.s.nodes(ORG, "WorkOrder")
    _rebuilds_the_same(m)


# ---- the routes --------------------------------------------------------------------------

def test_the_routes_refuse_and_last_done_is_set_on_the_task(monkeypatch, off):
    from fastapi.testclient import TestClient

    from backend import db
    from backend.auth import get_current_user
    from backend.main import app
    from backend.routers import maintenance as router

    store = GraphStore(":memory:", PROJECTORS)
    monkeypatch.setattr(db, "_db", mongomock.MongoClient()["wm_off_routes"])
    monkeypatch.setattr(db, "_simulated", True)
    monkeypatch.setattr(router, "_store", store)
    monkeypatch.setattr(config, "MAINTENANCE_ENABLED", True)
    monkeypatch.setattr(config, "MAINTENANCE_EMAILS", {"w@x.com"})
    app.dependency_overrides[get_current_user] = lambda: {
        "uid": ORG, "email": "w@x.com", "name": "W", "email_verified": True}
    client = TestClient(app)
    try:
        served = client.get("/api/config").json()
        assert served["work_management"] is False and served["maintenance_work_orders"] is False
        m = Maintenance(store, ORG, "tester")
        pid = m.create_position("Pool pump")["id"]
        task = m.create_task(pid, "Grease", 3, "months", last_done="2026-01-01")["id"]
        for method, path, body in (("get", "/api/maintenance/work-orders", None),
                                   ("post", "/api/maintenance/work-orders", {"position_id": pid, "title": "x"}),
                                   ("post", "/api/maintenance/work-orders/generate", {}),
                                   ("get", "/api/maintenance/work-orders/abc", None),
                                   ("post", "/api/maintenance/work-orders/abc/close", {}),
                                   ("post", "/api/maintenance/work-orders/abc/labour", {"hours": 1}),
                                   ("get", "/api/maintenance/due", None),
                                   ("post", "/api/maintenance/failure-reports/r/actions/a/work-order", {})):
            r = getattr(client, method)(path, **({"json": body} if body is not None else {}))
            assert r.status_code == 409 and r.json()["detail"].startswith(OFF_TEXT), path
        # Work done isn't recorded at all: the route is gone.
        assert client.post("/api/maintenance/work-done", json={"task_id": task}).status_code in (404, 405)
        r = client.patch(f"/api/maintenance/tasks/{task}", json={"last_done": "2026-02-01"})
        assert r.status_code == 200 and r.json()["last_done"] == "2026-02-01"
        assert not store.nodes(ORG, "WorkOrder")
        overview = client.get("/api/maintenance/overview").json()
        assert overview["open_work_orders"] == [] and overview["due"] == [] and overview["work_management"] is False
        assert overview["late"] == {"work_orders_late": 0, "tasks_overdue_without_work_order": 0}
    finally:
        app.dependency_overrides.pop(get_current_user, None)


# ---- MCP and REST ------------------------------------------------------------------------

def test_mcp_hides_and_refuses_work_management(env, monkeypatch):  # noqa: F811
    async def listed(client):
        return {t.name: t for t in (await client.list_tools()).tools}["maintenance"]

    on = _session(env["token"], listed)
    monkeypatch.setattr(config, "WORK_MANAGEMENT", False)
    off_ = _session(env["token"], listed)
    enum_on, enum_off = on.input_schema["properties"]["action"]["enum"], off_.input_schema["properties"]["action"]["enum"]
    hidden = set(enum_on) - set(enum_off)
    assert hidden == {a for a in enum_on if a.startswith("work_orders.")} | {"get.work_order", "list.work_orders"}
    assert "fitments.record_work_done" not in enum_on + enum_off
    assert {"tasks.set_last_done", "failure_reports.add_action", "failure_reports.verify"} <= set(enum_off)
    print(f"tools/list maintenance: description {len(on.description)} -> {len(off_.description)} chars, "
          f"action enum {len(enum_on)} -> {len(enum_off)} actions")

    async def flow(client):
        pid = _ok(await _do(client, "maintenance", "positions.create", args={"name": "Pool pump"}))["id"]
        task = _ok(await _do(client, "maintenance", "tasks.create",
                             args={"position_id": pid, "name": "Grease", "interval": 3, "unit": "months"}))["id"]
        refused = await _do(client, "maintenance", "work_orders.open", args={"position_id": pid, "title": "x"})
        listed_wos = await _list(client, "work_orders")
        guide = await client.call_tool("maintenance", {"action": "guide", "args": {"topic": "run"}})
        plan = _ok(await client.call_tool("maintenance", {"action": "guide", "args": {"topic": "plan"}}))
        last = _ok(await _do(client, "maintenance", "tasks.set_last_done", args={"task_id": task, "on": "2026-10-01"}))
        return refused, listed_wos, guide, plan, last

    refused, listed_wos, guide, plan, last = _session(env["token"], flow)
    for r in (refused, listed_wos, guide):
        assert r.is_error and OFF_TEXT in r.content[0].text
    assert "tasks.set_last_done" in refused.content[0].text
    assert "hypothetical" in plan["guide"] and "run" not in plan["topics"]
    assert last["last_done"] == "2026-10-01"


def test_rest_says_work_management_is_off(env, monkeypatch):  # noqa: F811
    from fastapi.testclient import TestClient

    from backend.main import app

    monkeypatch.setattr(config, "WORK_MANAGEMENT", False)
    client = TestClient(app)
    headers = {"Authorization": f"Bearer {env['token']}"}
    for action in ("work_orders.open", "list.work_orders", "get.work_order"):
        r = client.post(f"/api/v1/maintenance/{action}", json={}, headers=headers)
        assert r.status_code == 409 and OFF_TEXT in r.json()["detail"], action


def test_retire_says_how_to_deal_with_hidden_open_work_orders(monkeypatch):
    m = _m()
    pid = m.create_position("Pool pump")["id"]
    wo = m.open_work_order(pid, "Noisy")
    monkeypatch.setattr(config, "WORK_MANAGEMENT", False)
    with pytest.raises(Invalid) as err:
        m.retire_position(pid)
    assert "before work management was turned off" in str(err.value)
    with pytest.raises(WorkManagementOff):
        m.photo_target(wo["id"])
