"""One count of late work for Home, Orders and Assets (Nov 2026):
open work orders past due however they were raised (from a task, a package or by
hand), and tasks overdue with no work order open yet; and the tree's count of tasks
that can't be scheduled."""

from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient

from backend.maintenance.service import PROJECTORS, Maintenance
from backend.maintenance.store import GraphStore

ORG = "user-a"


@pytest.fixture()
def m():
    return Maintenance(GraphStore(":memory:", PROJECTORS), ORG, "tester")


def _ago(m, days):
    return (date.fromisoformat(m.today()) - timedelta(days=days)).isoformat()


def _house(m):
    """A house with a gate, a pump and a heater: a work order raised by hand 32 days late,
    a task's work order 5 days late, a task overdue with no work order, one due soon, and
    one hand-raised work order not due yet."""
    house = m.create_location("96 Example Street")
    gate = m.create_position("Gate", location_id=house["id"])
    pump = m.create_position("Pool pump", parent_id=gate["id"])
    heater = m.create_position("Heater", parent_id=gate["id"])
    by_hand = m.open_work_order(gate["id"], "Fix the gate latch", due=_ago(m, 32))
    m.open_work_order(gate["id"], "Paint the fence", due=_ago(m, -20))
    filt = m.create_task(pump["id"], "Swap the filter", 1, "months", last_done=_ago(m, 60))
    m.open_work_order(None, "Swap the filter", type="preventive", task_id=filt["id"], due=_ago(m, 5))
    m.create_task(heater["id"], "Test the relief valve", 1, "months", last_done=_ago(m, 45))
    m.create_task(heater["id"], "Flush the tank", 1, "months", last_done=_ago(m, 20))
    return house, by_hand


def test_late_counts_take_in_hand_raised_work_orders_and_count_a_raised_task_once(m):
    _, by_hand = _house(m)
    wos, due = m.work_orders("open"), m.due_tasks(30)
    assert any(w["id"] == by_hand["id"] and w["overdue"] for w in wos)
    # Two work orders late (by hand, and a task's); one task overdue with none raised.
    # The filter task is overdue too, but its work order counts it.
    assert m.late_counts(wos, due) == {"work_orders_late": 2, "tasks_overdue_without_work_order": 1}
    assert sum(1 for t in due if t["overdue"]) == 2


def test_assets_count_late_work_the_way_home_and_orders_do(m):
    house, _ = _house(m)
    row = next(p for p in m.places()["places"] if p["id"] == house["id"])
    assert row["late"] == {"work_orders_late": 2, "tasks_overdue_without_work_order": 1}
    assert row["late"] == m.late_counts(m.work_orders("open"), m.due_tasks(30))
    # The older counts stay for older readers.
    assert row["open_work_orders"] == 3 and row["overdue"] == 2
    assert m.places()["not_placed"]["late"] == {"work_orders_late": 0, "tasks_overdue_without_work_order": 0}


def test_the_tree_counts_tasks_that_cant_be_scheduled(m):
    pump = m.create_position("Pump")
    for i in range(5):
        m.create_task(pump["id"], f"Service {i}", 500, "hours")
    m.create_task(pump["id"], "Inspect", 1, "months")
    status = next(r for r in m.tree_rows()["positions"] if r["id"] == pump["id"])["status"]
    assert status["unscheduled"] == 5
    view = m.position(pump["id"])
    notes = [lim.get("note") for t in view["tasks"] for lim in t["limits"] if not t["next_due"]]
    assert notes == ["needs a hours counter on the position"] * 5


@pytest.fixture()
def client(monkeypatch):
    import mongomock

    from backend import config
    from backend import db as db_mod
    from backend.auth import get_current_user
    from backend.main import app
    from backend.routers import maintenance as router

    monkeypatch.setattr(db_mod, "_db", mongomock.MongoClient()["late_counts_rest"])
    monkeypatch.setattr(db_mod, "_simulated", True)
    monkeypatch.setattr(router, "_store", GraphStore(":memory:", PROJECTORS))
    monkeypatch.setattr(config, "MAINTENANCE_ENABLED", True)
    monkeypatch.setattr(config, "MAINTENANCE_EMAILS", {"a@x.com"})
    app.dependency_overrides[get_current_user] = lambda: {
        "uid": ORG, "email": "a@x.com", "name": "A", "email_verified": True}
    yield TestClient(app)
    app.dependency_overrides.pop(get_current_user, None)


def test_the_overview_carries_the_late_counts(client):
    gate = client.post("/api/maintenance/positions", json={"name": "Gate"}).json()
    today = date.fromisoformat(client.get("/api/maintenance/tree").json()["today"])
    late = client.post("/api/maintenance/work-orders", json={
        "position_id": gate["id"], "title": "Fix the latch", "due": (today - timedelta(days=32)).isoformat()})
    assert late.status_code == 200, late.text
    r = client.get("/api/maintenance/overview")
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["late"] == {"work_orders_late": 1, "tasks_overdue_without_work_order": 0}
    # The old fields stay.
    assert {"due", "open_work_orders", "proposals", "critical_spares", "today"} <= set(out)
