"""Reliafy Maintenance: the event-sourced graph store, RCM to tasks, work
orders, fitments and the life data they give."""

from datetime import date, timedelta

import mongomock
import pytest

from backend.maintenance.service import PROJECTORS, Invalid, Maintenance, add_interval
from backend.maintenance.store import GraphStore

ORG = "user-a"


@pytest.fixture()
def m():
    return Maintenance(GraphStore(":memory:", PROJECTORS), ORG, "tester")


class _Study:
    """The parts of an RcmStudy that maintenance reads."""

    def __init__(self, functions, system="Hot water system", name="Hot water RCM", id="study-1"):
        self.functions, self.system, self.name, self.id = functions, system, name, id


def _study(interval=6, unit="months", outcome="fixed_interval"):
    return _Study([{
        "id": "fn1", "text": "Supply hot water at 60 °C", "failures": [{
            "id": "ff1", "text": "No hot water", "modes": [
                {"id": "m-anode", "text": "Anode depleted", "consequence": "operational",
                 "decision": {"outcome": outcome, "interval": interval, "interval_unit": unit,
                              "task": "Replace sacrificial anode"}},
                {"id": "m-element", "text": "Element burnt out", "consequence": "operational",
                 "decision": {"outcome": "rtf", "rtf_basis": "random"}},
            ]}]}])


def test_add_interval_calendar_units_and_use():
    assert add_interval("2026-01-31", 1, "months") == "2026-02-28"
    assert add_interval("2026-01-01", 2, "weeks") == "2026-01-15"
    assert add_interval("2026-01-01", 1, "yr") == "2027-01-01"
    assert add_interval("2026-01-01", 10, "days") == "2026-01-11"
    assert add_interval("2026-01-01", 500, "hours") is None  # by use: needs a meter


def test_hierarchy_and_tree(m):
    house = m.create_position("House")
    hws = m.create_position("Hot water system", parent_id=house["id"], tag="=H.HWS")
    m.create_position("Pool pump", parent_id=house["id"])
    tree = m.tree()
    assert [t["name"] for t in tree] == ["House"]
    assert [c["name"] for c in tree[0]["children"]] == ["Hot water system", "Pool pump"]
    detail = m.position(hws["id"])
    assert detail["path"] == [{"id": house["id"], "name": "House"}]
    with pytest.raises(Invalid):
        m.update_position(house["id"], parent_id=hws["id"])  # no cycles


def test_rcm_gives_failure_modes_and_tasks_and_reapplies_cleanly(m):
    result = m.position_from_rcm(_study())
    pos = result["position"]
    assert pos["name"] == "Hot water system"
    assert result["failure_modes_added"] == 2 and result["tasks_added"] == 1
    [task] = pos["tasks"]
    assert task["name"] == "Replace sacrificial anode"
    assert task["next_due"] == add_interval(date.today().isoformat(), 6, "months")

    done = m.set_last_done(task["id"], "2025-01-15")
    assert done["last_done"] == "2025-01-15" and done["next_due"] == "2025-07-15"
    with pytest.raises(Invalid):
        m.set_last_done(task["id"], (date.today() + timedelta(days=3)).isoformat())

    again = m.apply_rcm(pos["id"], _study())
    assert again == {"position_id": pos["id"], "failure_modes_added": 0, "tasks_added": 0, "tasks_updated": 0}
    changed = m.apply_rcm(pos["id"], _study(interval=12))
    assert changed["tasks_updated"] == 1
    assert m.position(pos["id"])["tasks"][0]["interval"] == 12


def test_work_orders_replace_items_and_give_life_data(m):
    pos = m.position_from_rcm(_study(interval=1, unit="days"))["position"]
    pid = pos["id"]
    start = (date.today() - timedelta(days=400)).isoformat()
    m.fit(pid, new_item={"name": "Rheem 315 L", "serial": "A1"}, on=start)
    with pytest.raises(Invalid):
        m.fit(pid, new_item={"name": "Another"})  # already fitted

    anode = next(f for f in m.position(pid)["failure_modes"] if f["text"] == "Anode depleted")
    # A corrective work order: the tank failed and was replaced.
    wo = m.open_work_order(pid, "Tank leaking", type="corrective")
    failed_on = (date.today() - timedelta(days=100)).isoformat()
    closed = m.close_work_order(wo["id"], [
        {"kind": "replace", "failure_mode_id": anode["id"], "new_item": {"name": "Rheem 315 L", "serial": "B2"}},
    ], on=failed_on)
    assert closed["status"] == "closed" and closed["opened"] == failed_on  # back-dated
    # The new tank renewed the position's task: it counts from the replacement.
    assert m.position(pid)["tasks"][0]["last_done"] == failed_on
    assert closed["actions"][0]["removed"]["serial"] == "A1"
    assert closed["actions"][0]["fitted"]["serial"] == "B2"

    rows = m.life_data(pid)
    assert [(r["x"], r["c"], r["status"]) for r in rows] == [(300, 0, "failed"), (100, 1, "still fitted")]
    assert rows[0]["failure_mode"] == "Anode depleted"

    # The daily task is due: generating makes one preventive work order, once.
    made = m.generate_work_orders(30)
    assert len(made) == 1 and made[0]["type"] == "preventive"
    assert m.generate_work_orders(30) == []
    # Closing it (a planned replacement) moves the task on and suspends the item.
    m.close_work_order(made[0]["id"], [{"kind": "replace", "new_item": {"name": "Rheem 315 L", "serial": "C3"}}])
    task = m.position(pid)["tasks"][0]
    assert task["last_done"] == date.today().isoformat()
    statuses = [r["status"] for r in m.life_data(pid)]
    assert statuses == ["failed", "removed", "still fitted"]


def test_inspection_needs_a_finding_and_nothing_is_written_on_error(m):
    pid = m.create_position("Smoke alarm, hallway")["id"]
    wo = m.open_work_order(pid, "Test alarm", type="inspection")
    before = len(m.s.events(ORG, 500))
    with pytest.raises(Invalid):
        m.close_work_order(wo["id"], [{"kind": "inspect"}])
    assert len(m.s.events(ORG, 500)) == before
    done = m.close_work_order(wo["id"], [{"kind": "inspect", "finding": "ok"}])
    assert done["actions"][0]["finding"] == "ok"


def test_rebuild_from_the_log_gives_the_same_graph(m):
    pos = m.position_from_rcm(_study(interval=1, unit="days"))["position"]
    loc = m.create_location("Garage")
    m.fit(pos["id"], new_item={"name": "Tank"}, on="2025-01-01")
    spare = m.create_item("Spare anode")
    m.place_item(spare["id"], loc["id"])
    for wo in m.generate_work_orders(30):
        m.close_work_order(wo["id"], [{"kind": "repair", "notes": "flushed"}])
    before = m.s.snapshot()
    replayed = m.s.rebuild()
    assert replayed > 5
    assert m.s.snapshot() == before


def test_organisations_are_separate():
    store = GraphStore(":memory:", PROJECTORS)
    a, b = Maintenance(store, "org-a"), Maintenance(store, "org-b")
    pid = a.create_position("Pump")["id"]
    assert b.tree() == []
    with pytest.raises(KeyError):
        b.position(pid)


def test_api_is_off_unless_enabled_and_works_when_on(monkeypatch):
    from fastapi.testclient import TestClient

    from backend import config, db
    from backend.auth import get_current_user
    from backend.main import app
    from backend.routers import maintenance as router

    test_db = mongomock.MongoClient()["reliafy_test"]
    monkeypatch.setattr(db, "_db", test_db)
    monkeypatch.setattr(db, "_simulated", True)
    monkeypatch.setattr(router, "_store", GraphStore(":memory:", PROJECTORS))
    client = TestClient(app)
    app.dependency_overrides[get_current_user] = lambda: {
        "uid": ORG, "email": "a@x.com", "name": "A", "email_verified": True}
    try:
        monkeypatch.setattr(config, "MAINTENANCE_ENABLED", False)
        assert client.get("/api/maintenance/overview").status_code == 404
        assert client.get("/api/config").json()["maintenance"] is False

        monkeypatch.setattr(config, "MAINTENANCE_ENABLED", True)
        assert client.get("/api/maintenance/access").json() == {"allowed": False}
        assert client.get("/api/maintenance/overview").status_code == 404  # not on the list
        monkeypatch.setattr(config, "MAINTENANCE_EMAILS", {"a@x.com"})
        assert client.get("/api/maintenance/access").json() == {"allowed": True}
        study = client.post("/api/rcm/studies", json={"name": "Pool", "system": "Pool pump"}).json()
        client.put(f"/api/rcm/studies/{study['id']}/tree", json={"functions": [
            {"text": "Circulate water", "failures": [{"text": "No flow", "modes": [
                {"text": "Basket blocked", "consequence": "operational",
                 "decision": {"outcome": "on_condition", "interval": 1, "interval_unit": "weeks",
                              "task": "Empty the pump basket"}}]}]}]})
        made = client.post("/api/maintenance/from-rcm", json={"study_id": study["id"]})
        assert made.status_code == 200, made.text
        pid = made.json()["position"]["id"]
        assert made.json()["position"]["tasks"][0]["name"] == "Empty the pump basket"

        assert client.post(f"/api/maintenance/positions/{pid}/fit",
                           json={"new_item": {"name": "Astral CTX"}}).status_code == 200
        wo = client.post("/api/maintenance/work-orders",
                         json={"position_id": pid, "title": "Noisy", "type": "corrective"}).json()
        bad = client.post(f"/api/maintenance/work-orders/{wo['id']}/close", json={"actions": [{"kind": "explode"}]})
        assert bad.status_code == 422
        ok = client.post(f"/api/maintenance/work-orders/{wo['id']}/close",
                         json={"actions": [{"kind": "repair", "notes": "new bearings"}]})
        assert ok.status_code == 200 and ok.json()["status"] == "closed"
        overview = client.get("/api/maintenance/overview").json()
        assert overview["summary"]["positions"] == 1 and overview["tree"][0]["item"]["name"] == "Astral CTX"
        assert client.get("/api/maintenance/positions/nope").status_code == 404
    finally:
        app.dependency_overrides.pop(get_current_user, None)


def test_a_shared_mongo_log_keeps_every_process_in_step():
    """Two processes (two graph copies in memory) on one MongoDB log: each sees
    the other's writes after a sync, and a rebuild gives the same graph."""
    from backend.maintenance.store import MongoEventLog

    mongo = mongomock.MongoClient()["maint_log"]
    a = Maintenance(GraphStore(":memory:", PROJECTORS, MongoEventLog(mongo)), ORG)
    b = Maintenance(GraphStore(":memory:", PROJECTORS, MongoEventLog(mongo)), ORG)
    pos = a.position_from_rcm(_study())["position"]
    b.s.sync()
    assert b.position(pos["id"])["tasks"][0]["name"] == "Replace sacrificial anode"
    b.fit(pos["id"], new_item={"name": "Tank"}, on="2024-02-01")
    a.s.sync()
    assert a.position(pos["id"])["fitted"]["item"]["name"] == "Tank"
    assert a.s.snapshot() == b.s.snapshot()
    before = a.s.snapshot()
    a.s.rebuild()
    assert a.s.snapshot() == before
    # A fresh process (a new Cloud Run instance) starts empty and catches up.
    c = GraphStore(":memory:", PROJECTORS, MongoEventLog(mongo))
    c.sync()
    assert c.snapshot() == before


def test_access_rule(monkeypatch):
    from backend import config
    from backend.maintenance.access import allowed

    admin = {"uid": "u1", "email": "boss@x.com", "email_verified": True}
    tester = {"uid": "u2", "email": "tester@x.com", "email_verified": True}
    other = {"uid": "u3", "email": "someone@x.com", "email_verified": True}
    monkeypatch.setattr(config, "AUTH_DISABLED", False)
    monkeypatch.setattr(config, "ADMIN_EMAILS", {"boss@x.com"})
    monkeypatch.setattr(config, "MAINTENANCE_EMAILS", {"tester@x.com"})
    monkeypatch.setattr(config, "MAINTENANCE_ENABLED", False)
    assert not allowed(admin)
    monkeypatch.setattr(config, "MAINTENANCE_ENABLED", True)
    assert allowed(admin) and allowed(tester) and not allowed(other)
    assert not allowed({**tester, "email_verified": False})
    monkeypatch.setattr(config, "AUTH_DISABLED", True)
    assert allowed(other)


def test_many_threads_reading_at_once_all_see_the_graph(m):
    """Requests run on several threads against one SQLite connection: reads at
    the same moment must not cut each other off."""
    from concurrent.futures import ThreadPoolExecutor

    ids = [m.create_position(f"Pump {i}")["id"] for i in range(30)]

    def read(pid):
        return m.position(pid)["name"]

    with ThreadPoolExecutor(max_workers=12) as pool:
        names = list(pool.map(read, ids * 10))
    assert names == [f"Pump {i}" for i in range(30)] * 10
