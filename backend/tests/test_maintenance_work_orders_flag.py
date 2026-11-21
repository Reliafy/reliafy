"""Work orders turned off (MAINTENANCE_WORK_ORDERS) while the rest of Maintenance works.

Off: nothing raises a work order (by hand, the daily run, a task's trigger, an alarm), the
work-order routes and tool actions refuse saying what to do instead, and the work orders
already in the log are hidden, not deleted (turned back on, they show again). Work done is
recorded with Maintenance.record_work_done, which writes the events a work order's open and
close write, so tasks renew, fitments change and forecasts read it exactly as before."""

from datetime import date

import mongomock
import pytest

from backend import config
from backend.maintenance import position_forecast as pf
from backend.maintenance.service import PROJECTORS, Invalid, Maintenance, WorkOrdersOff
from backend.maintenance.store import GraphStore
from backend.tests.test_maintenance_mcp import _do, _get, _list, _ok, _session, env  # noqa: F401

ORG = "user-wo-off"
TODAY = "2026-11-20"


@pytest.fixture()
def off(monkeypatch):
    monkeypatch.setattr(config, "MAINTENANCE_WORK_ORDERS", False)


def _m(store=None) -> Maintenance:
    m = Maintenance(store or GraphStore(":memory:", PROJECTORS), ORG, "tester")
    m.today = lambda: TODAY
    return m


def _rebuilds_the_same(m):
    before = m.s.snapshot()
    m.s.rebuild()
    assert m.s.snapshot() == before


def _pump(m):
    pid = m.create_position("Pool pump")["id"]
    m.fit(pid, new_item={"name": "Pump", "serial": "A1"}, on="2024-01-01")
    mode = m.add_failure_mode(pid, "Bearing worn")["id"]
    task = m.create_task(pid, "Grease bearings", 3, "months", last_done="2026-06-01")
    return pid, mode, task["id"]


# ---- nothing raises a work order -------------------------------------------------------

def test_raising_and_changing_work_orders_refuse(off):
    m = _m()
    pid, _, task = _pump(m)
    for call in (lambda: m.open_work_order(pid, "Noisy"),
                 lambda: m.raise_package_visit("any"),
                 lambda: m.close_work_order("any"),
                 lambda: m.log_labour("any", 1),
                 lambda: m.cancel_work_order("any")):
        with pytest.raises(WorkOrdersOff) as err:
            call()
        assert str(err.value).startswith("Work orders are turned off for this workspace.")
        assert isinstance(err.value, Invalid) and err.value.status == 409
    # generate (what the daily run calls) raises none, and the task is still due.
    before = m.s.event_count(ORG)
    assert m.generate(30) == {"work_orders": [], "skipped": []}
    assert m.s.event_count(ORG) == before
    assert m._task_view(m._get(task, "Task"))["next_due"] == "2026-09-01"


def test_alarms_and_triggers_raise_nothing_but_the_reading_is_kept(off):
    m = _m()
    pid, _, task = _pump(m)
    point = m.add_point(pid, "Vibration", unit="mm/s", alarm_above=7.1)
    m.update_task(task, trigger={"kind": "reading", "point_id": point["id"], "above": 7})
    view = m.record_reading(point["id"], 7.4, on=TODAY)
    assert view["status"] == "high" and view["alarm_work_order"] is None
    assert not m.s.nodes(ORG, "WorkOrder")


def test_the_daily_run_raises_none(off, monkeypatch):
    from backend.maintenance import daily

    store = GraphStore(":memory:", PROJECTORS)
    m = Maintenance(store, ORG, "tester")
    m.create_task(m.create_position("Pool pump")["id"], "Grease", 1, "weeks", last_done="2020-01-01")
    db = mongomock.MongoClient()["wo_off_daily"]
    assert daily.run(db, store, today=date(2026, 11, 20), dry_run=True)["work_orders"] == 0
    result = daily.run(db, store, today=date(2026, 11, 20))
    assert result["work_orders"] == 0 and not store.nodes(ORG, "WorkOrder")


# ---- existing work orders: hidden, not deleted -----------------------------------------

def test_existing_work_orders_are_hidden_then_shown_again(monkeypatch):
    m = _m()
    pid, _, task = _pump(m)
    wo = m.open_work_order(None, None, "preventive", task_id=task)
    done = m.open_work_order(pid, "Earlier repair")
    m.close_work_order(done["id"], [{"kind": "repair"}], on="2026-10-01")
    events = m.s.event_count(ORG)

    monkeypatch.setattr(config, "MAINTENANCE_WORK_ORDERS", False)
    m._memo.clear()
    assert m._task_view(m._get(task, "Task"))["open_work_order"] is None
    # The position keeps its record of work done (the closed one), not the open one.
    assert [w["id"] for w in m.position(pid)["work_orders"]] == [done["id"]]
    assert m.s.event_count(ORG) == events  # nothing written, nothing deleted

    monkeypatch.setattr(config, "MAINTENANCE_WORK_ORDERS", True)
    m._memo.clear()
    assert m._task_view(m._get(task, "Task"))["open_work_order"]["id"] == wo["id"]
    assert {w["id"] for w in m.position(pid)["work_orders"]} == {wo["id"], done["id"]}


# ---- work done without a work order ----------------------------------------------------

def test_a_task_done_renews_like_closing_its_work_order(off):
    m = _m()
    _, _, task = _pump(m)
    out = m.record_work_done(task_id=task, on="2026-11-10", notes="Greased both ends")
    assert out["task"]["last_done"] == "2026-11-10" and out["task"]["next_due"] == "2027-02-10"
    _rebuilds_the_same(m)


def test_last_done_without_a_work_order_feeds_the_forecast_as_a_close_does(monkeypatch):
    """The same task done on the same day, once by closing its work order (on) and once
    recorded with work orders off: the forecast's dates and the graph's fitments match."""
    forecasts, fitments = {}, {}
    for flag in (True, False):
        monkeypatch.setattr(config, "MAINTENANCE_WORK_ORDERS", flag)
        m = _m()
        pid, mode, task = _pump(m)
        replace = [{"kind": "replace", "failure_mode_id": mode, "new_item": {"name": "Pump", "serial": "B2"}}]
        if flag:
            wo = m.open_work_order(None, None, "preventive", task_id=task)
            m.close_work_order(wo["id"], replace, on="2026-11-10")
        else:
            m.record_work_done(task_id=task, actions=replace, on="2026-11-10")
        m._memo.clear()
        forecasts[flag] = [t["dates"] for t in pf.position_forecast(m, pid, periods=12)["tasks"]]
        fitments[flag] = [(f["from"], f["to"], f.get("end_reason"), (f.get("failure_mode") or {}).get("text"), (f.get("item") or {}).get("serial"))
                          for f in m.position(pid)["fitments"]]
        _rebuilds_the_same(m)
    assert forecasts[True] == forecasts[False] and forecasts[False][0][0] == "2027-02-10"
    assert fitments[True] == fitments[False]
    assert ("2024-01-01", "2026-11-10", "failure", "Bearing worn", "A1") in fitments[False]


def test_a_repair_and_an_inspection_found_failed(off):
    m = _m()
    pid, mode, _ = _pump(m)
    m.record_work_done(position_id=pid, actions=[{"kind": "repair", "failure_mode_id": mode}], on="2026-10-01")
    m.record_work_done(position_id=pid, actions=[{"kind": "inspect", "finding": "found_failed"}], on="2026-11-01")
    kinds = [e["type"] for e in m.s.events(ORG, 500)["events"]] if isinstance(m.s.events(ORG, 500), dict) \
        else [e["type"] for e in m.s.events(ORG, 500)]
    assert "fitment.found_failed" in kinds and kinds.count("action.recorded") == 2
    # The fitted item is still the same one: a repair is a recurrent event, not a renewal.
    assert m.current_fitment(pid)["from"] == "2024-01-01"
    assert [w["type"] for w in m.position(pid)["work_orders"]] == ["inspection", "corrective"]
    _rebuilds_the_same(m)


def test_nothing_is_written_when_any_part_is_refused(off):
    m = _m()
    pid, _, _ = _pump(m)
    before = m.s.event_count(ORG)
    with pytest.raises(Invalid):
        m.record_work_done(position_id=pid, actions=[{"kind": "inspect", "finding": "nonsense"}])
    with pytest.raises(Invalid):
        m.record_work_done(position_id=pid, actions=[{"kind": "repair"}], on="2099-01-01")
    with pytest.raises(Invalid):
        m.record_work_done(actions=[{"kind": "repair"}])
    assert m.s.event_count(ORG) == before and not m.s.nodes(ORG, "WorkOrder")


def test_the_rest_still_works(off):
    """The plan side: tasks fall due, last done is set, the forecast and the due list read them."""
    m = _m()
    pid, _, task = _pump(m)
    m.set_last_done(task, "2026-10-01")
    assert m._task_view(m._get(task, "Task"))["next_due"] == "2027-01-01"
    assert [t["id"] for t in m.due_tasks(30)] == []
    assert pf.position_forecast(m, pid, periods=6)["tasks"][0]["dates"][0] == "2027-01-01"
    assert m.tree()[0]["open_work_orders"] == 0


# ---- the routes -------------------------------------------------------------------------

def test_the_routes_refuse_and_work_done_records(monkeypatch, off):
    from fastapi.testclient import TestClient

    from backend import db
    from backend.auth import get_current_user
    from backend.main import app
    from backend.routers import maintenance as router

    store = GraphStore(":memory:", PROJECTORS)
    monkeypatch.setattr(db, "_db", mongomock.MongoClient()["wo_off_routes"])
    monkeypatch.setattr(db, "_simulated", True)
    monkeypatch.setattr(router, "_store", store)
    monkeypatch.setattr(config, "MAINTENANCE_ENABLED", True)
    monkeypatch.setattr(config, "MAINTENANCE_EMAILS", {"w@x.com"})
    app.dependency_overrides[get_current_user] = lambda: {
        "uid": ORG, "email": "w@x.com", "name": "W", "email_verified": True}
    client = TestClient(app)
    try:
        assert client.get("/api/config").json()["maintenance_work_orders"] is False
        m = Maintenance(store, ORG, "tester")
        pid = m.create_position("Pool pump")["id"]
        task = m.create_task(pid, "Grease", 3, "months", last_done="2026-01-01")["id"]
        for method, path, body in (("get", "/api/maintenance/work-orders", None),
                                   ("post", "/api/maintenance/work-orders", {"position_id": pid, "title": "x"}),
                                   ("post", "/api/maintenance/work-orders/generate", {}),
                                   ("get", "/api/maintenance/work-orders/abc", None),
                                   ("post", "/api/maintenance/work-orders/abc/close", {}),
                                   ("post", "/api/maintenance/failure-reports/r/actions/a/work-order", {})):
            r = getattr(client, method)(path, **({"json": body} if body is not None else {}))
            assert r.status_code == 409 and r.json()["detail"].startswith("Work orders are turned off"), path
        r = client.post("/api/maintenance/work-done", json={"task_id": task, "on": "2026-02-01"})
        assert r.status_code == 200 and r.json()["task"]["last_done"] == "2026-02-01"
        overview = client.get("/api/maintenance/overview").json()
        assert overview["open_work_orders"] == [] and overview["summary"]["open_work_orders"] == 0
        # Turned back on, the recorded work shows as a closed work order.
        monkeypatch.setattr(config, "MAINTENANCE_WORK_ORDERS", True)
        closed = client.get("/api/maintenance/work-orders", params={"status": "done"}).json()["work_orders"]
        assert len(closed) == 1 and Maintenance.RECORDED_NOTE in closed[0].get("notes", Maintenance.RECORDED_NOTE)
    finally:
        app.dependency_overrides.pop(get_current_user, None)


# ---- MCP and REST -----------------------------------------------------------------------

def test_mcp_hides_and_refuses_work_orders(env, monkeypatch):  # noqa: F811
    from backend.maintenance import mcp_tools

    async def listed(client):
        return {t.name: t for t in (await client.list_tools()).tools}["maintenance"]

    on = _session(env["token"], listed)
    monkeypatch.setattr(config, "MAINTENANCE_WORK_ORDERS", False)
    off_ = _session(env["token"], listed)
    enum_on, enum_off = on.input_schema["properties"]["action"]["enum"], off_.input_schema["properties"]["action"]["enum"]
    assert any(a.startswith("work_orders.") for a in enum_on)
    assert not any(a.startswith("work_orders.") for a in enum_off)
    assert "fitments.record_work_done" in enum_on and "fitments.record_work_done" in enum_off
    assert "work_orders." not in off_.description and len(off_.description) < len(on.description)
    print(f"tools/list maintenance: description {len(on.description)} -> {len(off_.description)}, "
          f"enum {len(str(enum_on))} -> {len(str(enum_off))}")
    _, table = mcp_tools.TOOL_TABLES["maintenance"]
    assert "fitments.record_work_done" in table

    async def flow(client):
        pid = _ok(await _do(client, "maintenance", "positions.create", args={"name": "Pool pump"}))["id"]
        refused = await _do(client, "maintenance", "work_orders.open", args={"position_id": pid, "title": "x"})
        listed_wos = await _list(client, "work_orders")
        guide = _ok(await client.call_tool("maintenance", {"action": "guide", "args": {"topic": "run"}}))
        done = _ok(await _do(client, "maintenance", "fitments.record_work_done",
                             args={"position_id": pid, "actions": [{"kind": "repair"}], "notes": "Tightened"}))
        return refused, listed_wos, guide, done

    refused, listed_wos, guide, done = _session(env["token"], flow)
    assert refused.is_error and "Work orders are turned off" in refused.content[0].text
    assert "fitments.record_work_done" in refused.content[0].text
    assert listed_wos.is_error and "turned off" in listed_wos.content[0].text
    assert "record_work_done" in guide["guide"] and "work_orders.generate" not in guide["guide"]
    assert done["work_order_id"]


def test_rest_says_work_orders_are_off(env, monkeypatch):  # noqa: F811
    from fastapi.testclient import TestClient

    from backend.main import app

    monkeypatch.setattr(config, "MAINTENANCE_WORK_ORDERS", False)
    client = TestClient(app)
    r = client.post("/api/v1/maintenance/work_orders.open", json={"position_id": "p", "title": "x"},
                    headers={"Authorization": f"Bearer {env['token']}"})
    assert r.status_code == 409 and "turned off" in r.json()["detail"]


def test_retire_says_how_to_deal_with_hidden_open_work_orders(monkeypatch):
    m = _m()
    pid = m.create_position("Pool pump")["id"]
    wo = m.open_work_order(pid, "Noisy")
    monkeypatch.setattr(config, "MAINTENANCE_WORK_ORDERS", False)
    with pytest.raises(Invalid) as err:
        m.retire_position(pid)
    assert "before work orders were turned off" in str(err.value)
    with pytest.raises(WorkOrdersOff):
        m.photo_target(wo["id"])
