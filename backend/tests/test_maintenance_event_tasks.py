"""Tasks raised by an event (Nov 2026): a reading past a limit on a condition
point, or a named event logged on a position, opens the task's work order once.

A trigger is set by its own event (task.trigger_set) and cleared by setting it
to None; task.added keeps its shape. A task with a trigger and no interval
running waits for the event: never due on a date, never overdue."""

import pytest

from backend.maintenance.service import PROJECTORS, Invalid, Maintenance
from backend.maintenance.store import GraphStore
from backend.tests.test_maintenance_mcp import _do, _ok, _session, env  # noqa: F401
from backend.tests.test_maintenance_rcm_api import api  # noqa: F401

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


def _pool(m):
    """A site with a rain gauge (a condition point in mm) and a pool inside it with a
    chlorinator; a task on the pool, every month for now."""
    site = m.create_position("Aquatic centre")
    pool = m.create_position("Pool", parent_id=site["id"])
    chlor = m.create_position("Chlorinator", parent_id=pool["id"])
    rain = m.add_point(site["id"], "POOL-RAIN", kind="condition", unit="mm")
    task = m.create_task(pool["id"], "Test and re-dose the pool", 1, "months")
    return site, pool, chlor, rain, task


def _open_for(m, task_id):
    return [w for w in m.s.inn(ORG, task_id, "FOR") if w["status"] == "open"]


def test_a_trigger_is_set_projected_and_cleared(m):
    _, _, _, rain, task = _pool(m)
    assert task["trigger"] is None and not task["on_event"] and task["next_due"]
    view = m.set_task_trigger(task["id"], {"kind": "reading", "point_id": rain["id"], "above": 120})
    assert view["trigger"]["text"] == "120 mm on POOL-RAIN" and view["on_event"]
    assert view["next_due"] is None and view["overdue"] is False and view["limits"] == []
    assert view["status"] == "Waiting for the event"
    assert view["interval"] == 1 and view["unit"] == "months"  # kept, for when the trigger goes
    assert [t["id"] for t in m.s.inn(ORG, rain["id"], "WATCHES")] == [task["id"]]
    # The same again is no new event.
    m.set_task_trigger(task["id"], {"kind": "reading", "point_id": rain["id"], "above": 120})
    assert len(_events(m, "task.trigger_set")) == 1
    both = m.set_task_trigger(task["id"], {"kind": "event", "event_type": " Lightning  strike ",
                                           "with_interval": True})
    assert both["trigger"]["event_type"] == "Lightning strike" and not both["on_event"] and both["next_due"]
    assert m.s.inn(ORG, rain["id"], "WATCHES") == []
    cleared = m.set_task_trigger(task["id"], None)
    assert cleared["trigger"] is None and cleared["next_due"] == task["next_due"]
    assert _events(m, "task.added")[0]["payload"].get("trigger") is None  # task.added keeps its shape
    _rebuilds_the_same(m)


def test_trigger_checks(m):
    site, pool, _, rain, task = _pool(m)
    hours = m.add_point(site["id"], "Pump hours", kind="counter", unit="hours")
    for bad in ({"kind": "storm"}, {"kind": "reading", "point_id": rain["id"]},
                {"kind": "reading", "point_id": rain["id"], "above": 1, "below": 0},
                {"kind": "reading", "point_id": hours["id"], "above": 5},
                {"kind": "event", "event_type": ""}, {"kind": "event", "event_type": "x", "point_id": "y"},
                "rain"):
        with pytest.raises(Invalid):
            m.set_task_trigger(task["id"], bad)


def test_a_task_created_on_event_needs_no_interval(m):
    site, pool, _, rain, _ = _pool(m)
    t = m.create_task(pool["id"], "Check stabiliser", None, None,
                      trigger={"kind": "event", "event_type": "Overflow"})
    assert t["on_event"] and t["trigger"]["text"] == "Overflow" and t["next_due"] is None
    with pytest.raises(Invalid):
        m.create_task(pool["id"], "No interval, no trigger", None, None)
    # Not in the due list, nor counted overdue on the tree.
    assert t["id"] not in {d["id"] for d in m.due_tasks(3650)}
    _rebuilds_the_same(m)


def test_a_reading_over_the_limit_raises_one_work_order(m):
    _, pool, _, rain, task = _pool(m)
    m.update_task(task["id"], trigger={"kind": "reading", "point_id": rain["id"], "above": 120})
    m.record_reading(rain["id"], 40, on="2026-01-04")
    assert _open_for(m, task["id"]) == []
    m.record_reading(rain["id"], 128, on="2026-01-07")
    [wo] = _open_for(m, task["id"])
    assert wo["opened"] == "2026-01-07" and wo["due"] == "2026-01-07"  # the reading's day, not today
    assert "Raised by: 128 mm on POOL-RAIN, 7 Jan 2026 (at or over 120 mm)" in wo["notes"]
    assert wo["type"] == "preventive"
    m.record_reading(rain["id"], 150, on="2026-01-08")  # still open: no second one
    assert len(_open_for(m, task["id"])) == 1
    view = m._task_view(m._get(task["id"], "Task"))
    assert view["open_work_order"]["id"] == wo["id"] and "status" not in view
    # Closed, the next storm raises it again.
    m.close_work_order(wo["id"], [{"kind": "inspect", "finding": "ok"}], on="2026-01-09")
    m.record_reading(rain["id"], 130, on="2026-01-10")
    assert len(_open_for(m, task["id"])) == 1
    _rebuilds_the_same(m)


def test_a_below_limit_and_the_alarm_still_work(m):
    site, _, _, _, task = _pool(m)
    chlorine = m.add_point(site["id"], "Free chlorine", kind="condition", unit="ppm", alarm_below=0.5)
    m.set_task_trigger(task["id"], {"kind": "reading", "point_id": chlorine["id"], "below": 1})
    m.record_reading(chlorine["id"], 0.4, on="2026-02-01")
    assert len(_open_for(m, task["id"])) == 1
    assert len([w for w in m.s.inn(ORG, chlorine["id"], "ALARM_FOR")]) == 1  # the alarm as before


def test_a_logged_event_raises_tasks_there_and_inside(m):
    site, pool, chlor, _, task = _pool(m)
    inspect = m.create_task(chlor["id"], "Inspect the chlorinator", None,
                            trigger={"kind": "event", "event_type": "Lightning strike"})
    m.set_task_trigger(task["id"], {"kind": "event", "event_type": "Overflow"})
    out = m.log_position_event(pool["id"], "lightning STRIKE", note="Board tripped", when="2026-03-02")
    assert [w["task"]["id"] for w in out["work_orders_raised"]] == [inspect["id"]]
    [wo] = _open_for(m, inspect["id"])
    assert wo["opened"] == "2026-03-02"
    assert "Raised by: lightning STRIKE logged on Pool, 2 Mar 2026: Board tripped" in wo["notes"]
    again = m.log_position_event(pool["id"], "Lightning strike", when="2026-03-03")
    assert again["work_orders_raised"] == []  # one open already
    # Logged on a position inside the task's, it doesn't reach up.
    assert m.log_position_event(chlor["id"], "Overflow")["work_orders_raised"] == []
    assert len(m.log_position_event(site["id"], "Overflow")["work_orders_raised"]) == 1
    assert sorted(e["payload"]["event_type"] for e in _events(m, "position.event_logged")) == [
        "Lightning strike", "Overflow", "Overflow", "lightning STRIKE"]
    assert len(m.s.nodes(ORG, "LoggedEvent")) == 4
    with pytest.raises(Invalid):
        m.log_position_event(pool["id"], "")
    with pytest.raises(Invalid):
        m.log_position_event(pool["id"], "Storm", when="2999-01-01")
    _rebuilds_the_same(m)


def test_trigger_points_offer_the_sites_gauges(m):
    site, pool, chlor, rain, _ = _pool(m)
    m.add_point(chlor["id"], "Cell hours", kind="counter", unit="hours")
    task = m.create_task(chlor["id"], "Inspect", 1, "years")
    points = m.task_trigger_points(task["id"])
    assert [p["name"] for p in points] == ["POOL-RAIN"]
    assert points[0]["on"]["name"] == "Aquatic centre"


def test_the_worksheet_shows_the_trigger(m):
    site, pool, _, rain, _ = _pool(m)
    fm = m.add_failure_mode(pool["id"], "Water goes out of balance after heavy rain")
    m.decide_failure_mode(fm["id"], "operational", {"outcome": "on_condition", "task": "Test and re-dose",
                                                    "interval": 1, "interval_unit": "months"})
    task_id = m.rcm_mode(fm["id"])["decision"]["task_id"]
    m.set_task_trigger(task_id, {"kind": "reading", "point_id": rain["id"], "above": 120})
    mode = m.rcm_mode(fm["id"])
    assert mode["decision"]["trigger"]["text"] == "120 mm on POOL-RAIN"
    assert mode["tasks"][0]["trigger"]["text"] == "120 mm on POOL-RAIN"
    assert mode["decision"]["outcome"] == "on_condition"  # the decision stays as it is


# ---- the app's routes -------------------------------------------------------------------

def test_the_app_routes(api):
    site = api.post(f"{M}/positions", json={"name": "Site"}).json()
    pool = api.post(f"{M}/positions", json={"name": "Pool", "parent_id": site["id"]}).json()
    rain = api.post(f"{M}/positions/{site['id']}/points", json={"name": "POOL-RAIN", "kind": "condition",
                                                                "unit": "mm"}).json()
    task = api.post(f"{M}/positions/{pool['id']}/tasks", json={
        "name": "Re-dose", "trigger": {"kind": "event", "event_type": "Storm"}})
    assert task.status_code == 200, task.text
    task = task.json()
    assert task["on_event"]
    points = api.get(f"{M}/tasks/{task['id']}/trigger-points").json()["points"]
    assert [p["id"] for p in points] == [rain["id"]]
    r = api.patch(f"{M}/tasks/{task['id']}", json={"trigger": {"kind": "reading", "point_id": rain["id"],
                                                                "above": 120}})
    assert r.status_code == 200 and r.json()["trigger"]["text"] == "120 mm on POOL-RAIN"
    assert api.post(f"{M}/points/{rain['id']}/readings", json={"value": 128, "on": "2026-01-07"}).status_code == 200
    assert api.get(f"{M}/positions/{pool['id']}").json()["tasks"][0]["open_work_order"]
    r = api.patch(f"{M}/tasks/{task['id']}", json={"trigger": {"kind": "event", "event_type": "Storm"}})
    assert r.status_code == 200
    logged = api.post(f"{M}/positions/{site['id']}/events", json={"event_type": "Storm"}).json()
    assert logged["event"]["event_type"] == "Storm" and logged["work_orders_raised"] == []  # one is open
    assert api.post(f"{M}/positions/{site['id']}/events", json={}).status_code == 422
    r = api.patch(f"{M}/tasks/{task['id']}", json={"trigger": None})
    assert r.status_code == 200 and r.json()["trigger"] is None


# ---- the tool -----------------------------------------------------------------------------

def test_triggers_and_logged_events_over_mcp(env):
    async def flow(client):
        site = _ok(await _do(client, "maintenance", "positions.create", name="Site"))["id"]
        pool = _ok(await _do(client, "maintenance", "positions.create", name="Pool", parent_id=site))["id"]
        task = _ok(await _do(client, "maintenance", "tasks.create", position_id=pool, name="Inspect",
                             trigger={"kind": "event", "event_type": "Lightning strike"}))
        assert task["on_event"] and task["status"] == "Waiting for the event"
        none = await _do(client, "maintenance", "tasks.create", position_id=pool, name="Nothing")
        assert none.is_error
        out = _ok(await _do(client, "maintenance", "positions.log_event", position_id=site,
                            event_type="Lightning strike", note="Near the plant room"))
        assert len(out["work_orders_raised"]) == 1
        both = _ok(await _do(client, "maintenance", "tasks.update", task_id=task["id"],
                             trigger={"kind": "event", "event_type": "Lightning strike", "with_interval": True}))
        assert both["trigger"]["with_interval"] and not both["on_event"]
        cleared = _ok(await _do(client, "maintenance", "tasks.update", task_id=task["id"], clear_trigger=True))
        return cleared

    assert _session(env["token"], flow)["trigger"] is None


def test_the_excel_export_writes_on_event_in_the_interval_column(m):
    from backend.maintenance import fmea_sheet

    _, pool, _, rain, _ = _pool(m)
    fm = m.add_failure_mode(pool["id"], "Out of balance after rain")
    m.decide_failure_mode(fm["id"], "operational", {"outcome": "on_condition", "task": "Re-dose", "interval": 1,
                                                    "interval_unit": "months"})
    m.set_task_trigger(m.rcm_mode(fm["id"])["decision"]["task_id"],
                       {"kind": "reading", "point_id": rain["id"], "above": 120})
    rows = fmea_sheet.rows(m.rcm_worksheet(pool["id"]))
    header = rows[0] if "Interval" in rows[0] else next(r for r in rows if "Interval" in r)
    at = header.index("Interval")
    row = next(r for r in rows if "Out of balance after rain" in r)
    assert (row[at], row[at + 1]) == ("on event: 120 mm on POOL-RAIN", "")
