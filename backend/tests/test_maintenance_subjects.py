"""What a task (and the work orders it raises) is on: a position (the job: the default,
and every task from RCM), an item (it follows the serial number, into a store and to
another position) or a location (a round or an area inspection)."""

import json
import pathlib
from datetime import date, timedelta

import mongomock
import pytest

from backend.maintenance.service import PROJECTORS, Invalid, Maintenance
from backend.maintenance.store import GraphStore

ORG = "user-s"


@pytest.fixture()
def m():
    return Maintenance(GraphStore(":memory:", PROJECTORS), ORG, "tester")


def _ago(m, days: int) -> str:
    return (date.fromisoformat(m.today()) - timedelta(days=days)).isoformat()


def _hours(m, position_id, readings):
    point = m.add_point(position_id, "Hour meter", kind="counter", unit="hours")["id"]
    for days, value in readings:
        m.record_reading(point, value, _ago(m, days))
    return point


# ---- which subject -------------------------------------------------------------------

def test_a_task_is_on_exactly_one_subject(m):
    pid = m.create_position("Pump")["id"]
    iid = m.create_item("Gauge G1")["id"]
    lid = m.create_location("Area 1")["id"]
    for kwargs in ({}, {"position_id": pid, "item_id": iid}, {"item_id": iid, "location_id": lid}):
        with pytest.raises(Invalid, match="exactly one"):
            m.create_task(kwargs.pop("position_id", None), "Check", 1, "months", **kwargs)
    position_task = m.create_task(pid, "Lubricate", 1, "months")
    item_task = m.create_task(None, "Calibrate", 1, "years", item_id=iid, source="statutory")
    place_task = m.create_task(None, "Walk the area", 1, "weeks", location_id=lid)
    assert position_task["subject"] == {"kind": "position", "id": pid, "name": "Pump"}
    assert item_task["subject"] == {"kind": "item", "id": iid, "name": "Gauge G1"}
    assert item_task["while_stored"] == "run" and "while_stored" not in position_task
    assert place_task["subject"]["kind"] == "location" and place_task["include_positions"] is False
    assert [t["name"] for t in m.item(iid)["tasks"]] == ["Calibrate"]
    assert [t["name"] for t in m.location(lid)["tasks"]] == ["Walk the area"]
    assert [t["name"] for t in m.position(pid)["tasks"]] == ["Lubricate"]


def test_settings_that_belong_to_another_subject_are_refused(m):
    pid = m.create_position("Pump")["id"]
    mode = m.add_failure_mode(pid, "Bearing worn")["id"]
    iid = m.create_item("Motor M1")["id"]
    lid = m.create_location("Area 1")["id"]
    elsewhere = _hours(m, pid, [])
    with pytest.raises(Invalid, match="calendar"):
        m.create_task(None, "Walk", 100, "hours", location_id=lid)
    with pytest.raises(Invalid, match="calendar"):
        m.create_task(None, "Walk", 1, "months", location_id=lid, also_interval=100, also_unit="hours")
    with pytest.raises(Invalid, match="Failure modes are on positions"):
        m.create_task(None, "Walk", 1, "months", location_id=lid, failure_mode_id=mode)
    with pytest.raises(Invalid, match="while_stored is for an item"):
        m.create_task(pid, "Grease", 1, "months", while_stored="pause")
    with pytest.raises(Invalid, match="include_positions is for a location"):
        m.create_task(None, "Rotate shaft", 1, "months", item_id=iid, include_positions=True)
    with pytest.raises(Invalid, match="run .* or pause"):
        m.create_task(None, "Rotate shaft", 1, "months", item_id=iid, while_stored="sometimes")
    with pytest.raises(Invalid, match="same item"):
        m.create_task(None, "Overhaul", 1000, "hours", item_id=iid, point_id=elsewhere)
    walk = m.create_task(None, "Walk", 1, "months", location_id=lid)
    with pytest.raises(Invalid, match="calendar"):
        m.update_task(walk["id"], unit="hours")
    shaft = m.create_task(None, "Rotate shaft", 1, "months", item_id=iid)
    with pytest.raises(Invalid, match="Failure modes are on positions"):
        m.update_task(shaft["id"], failure_mode_id=mode)
    assert m.update_task(shaft["id"], while_stored="pause")["while_stored"] == "pause"
    assert m.update_task(walk["id"], include_positions=True)["include_positions"] is True


# ---- an item's task: it follows the item ------------------------------------------------

def test_an_items_use_is_summed_over_its_fitments_at_different_positions(m):
    """An engine overhauled every 1,000 hours, fitted to truck A then (after a spell in the
    store) truck B: its hours are what each truck's hour meter added while it was there."""
    a = m.create_position("Truck A")["id"]
    b = m.create_position("Truck B")["id"]
    store = m.create_location("Workshop store")["id"]
    meter_a = _hours(m, a, [(100, 1000), (60, 1400), (40, 1500)])
    meter_b = _hours(m, b, [(30, 5000), (0, 5300)])
    engine = m.create_item("Engine E1", serial="E1")["id"]
    m.fit(a, item_id=engine, on=_ago(m, 100))
    m.remove(a, on=_ago(m, 60))
    m.place_item(engine, store, on=_ago(m, 60))
    m.fit(b, item_id=engine, on=_ago(m, 30))
    overhaul = m.create_task(None, "Overhaul", 1000, "hours", item_id=engine, last_done=_ago(m, 110))

    used = m.item_usage(engine, "hours")
    assert used["points"] == {meter_a, meter_b} and used["rows"][-1] == {"on": m.today(), "value": 700}
    [limit] = overhaul["limits"]
    assert limit["counter"]["derived"] and limit["counter"]["reading"] == 700 and limit["due_at_reading"] == 1000
    # 700 hours in 100 days: the last 300 take about 43 more.
    assert limit["next_due"] == (date.fromisoformat(m.today()) + timedelta(days=43)).isoformat()

    # The position's own tasks know nothing of it; the position shows the fitted item's.
    assert m.position(b)["tasks"] == [] and [t["name"] for t in m.position(b)["item_tasks"]] == ["Overhaul"]
    assert m.position(a)["item_tasks"] == []

    # Its work order is on the item, at the truck it's in now.
    [wo] = [w for w in m.generate_work_orders(60) if w["subject"]["kind"] == "item"]
    assert wo["subject"] == {"kind": "item", "id": engine, "name": "Engine E1"}
    assert wo["position"] == {"id": b, "name": "Truck B"} and wo["item_at"]["how"] == "fitted"
    # Where it is rides along (truck B has no location set).
    assert wo["item"]["id"] == engine and wo["item"]["location"] is None and wo["can_replace"]
    m.close_work_order(wo["id"], [{"kind": "repair", "notes": "Overhauled"}])
    done = m.item(engine)["tasks"][0]
    # Last done is recorded as the item's use that day: 700 hours.
    assert done["last_done"] == m.today() and done["last_done_reading"] == 700
    assert done["limits"][0]["due_at_reading"] == 1700

    # A reading at truck B corrected later moves the reading it was done at too.
    latest = m.point(meter_b)["readings"][0]
    m.correct_reading(latest["id"], value=5350, reason="misread")
    assert m.item(engine)["tasks"][0]["last_done_reading"] == 750


def test_an_items_own_counter_wins_over_its_use_where_fitted(m):
    truck = m.create_position("Truck")["id"]
    _hours(m, truck, [(50, 100), (0, 600)])
    generator = m.create_item("Portable generator")["id"]
    m.fit(truck, item_id=generator, on=_ago(m, 50))
    own = m.add_point(None, "Generator hours", kind="counter", unit="hours", item_id=generator)
    assert own["item"] == {"id": generator, "name": "Portable generator"} and own["position"] is None
    m.record_reading(own["id"], 20, _ago(m, 40))
    m.record_reading(own["id"], 80, _ago(m, 10))
    task = m.create_task(None, "Oil change", 250, "hours", item_id=generator, last_done=_ago(m, 40))
    assert task["limits"][0]["counter"]["id"] == own["id"] and task["last_done_reading"] == 20
    assert task["limits"][0]["due_at_reading"] == 270
    assert [p["id"] for p in m.item(generator)["measurements"]] == [own["id"]]
    # A chosen counter must be the item's own.
    assert m.create_task(None, "Spark plug", 500, "hours", item_id=generator, point_id=own["id"])["point_id"] == own["id"]


def test_an_item_in_store_adds_no_use(m):
    truck = m.create_position("Truck")["id"]
    _hours(m, truck, [(100, 0), (50, 500)])
    engine = m.create_item("Engine")["id"]
    m.fit(truck, item_id=engine, on=_ago(m, 100))
    m.remove(truck, on=_ago(m, 50))
    task = m.create_task(None, "Overhaul", 1000, "hours", item_id=engine)
    [limit] = task["limits"]
    assert limit["counter"]["reading"] == 500 and limit["next_due"] is None
    assert "not fitted" in limit["note"]
    assert m.due_tasks(10_000) == []


def test_an_item_task_moves_with_the_item_and_isnt_renewed_by_a_fit(m):
    a = m.create_position("Crane hook A")["id"]
    b = m.create_position("Crane hook B")["id"]
    position_task = m.create_task(a, "Inspect hook", 3, "months", last_done=_ago(m, 80))
    sling = m.create_item("Sling S7")["id"]
    cert = m.create_task(None, "Certify the sling", 6, "months", item_id=sling, source="statutory",
                         last_done=_ago(m, 170))
    m.fit(a, item_id=sling, on=_ago(m, 20))
    # Both fall due on their own; the position's renewed with the new item, the item's didn't.
    assert m.position(a)["tasks"][0]["last_done"] == _ago(m, 20)
    assert m.item(sling)["tasks"][0]["last_done"] == _ago(m, 170)
    due = {t["name"]: t for t in m.due_tasks(30)}
    assert due["Certify the sling"]["at"]["position"] == {"id": a, "name": "Crane hook A"}
    assert "position" not in due["Certify the sling"] and position_task["id"] not in {t["id"] for t in due.values()}
    m.move_item(sling, b, on=_ago(m, 5))
    assert m.position(a)["item_tasks"] == [] and [t["id"] for t in m.position(b)["item_tasks"]] == [cert["id"]]
    made = m.generate_work_orders(30)
    assert [(w["subject"]["kind"], w["position"]["name"]) for w in made] == [("item", "Crane hook B")]


# ---- in store: run or pause ------------------------------------------------------------

def test_a_calendar_task_on_a_stored_item_runs_or_pauses(m):
    pump = m.create_position("Pump")["id"]
    store = m.create_location("Store")["id"]
    motor = m.create_item("Motor M1")["id"]
    m.fit(pump, item_id=motor, on=_ago(m, 100))
    paused = m.create_task(None, "Grease bearings", 60, "days", item_id=motor, while_stored="pause",
                           last_done=_ago(m, 100))
    running = m.create_task(None, "Rotate the shaft", 60, "days", item_id=motor, last_done=_ago(m, 100))
    m.remove(pump, on=_ago(m, 70))
    m.place_item(motor, store, on=_ago(m, 70))
    views = {t["name"]: t for t in m.item(motor)["tasks"]}
    assert views["Grease bearings"]["next_due"] is None and views["Grease bearings"]["limits"][0]["paused"]
    assert views["Rotate the shaft"]["next_due"] == _ago(m, 40) and views["Rotate the shaft"]["overdue"]
    # The running one raises its work order where the motor is: in the store.
    [wo] = m.generate_work_orders(0)
    assert wo["task"]["id"] == running["id"] and wo["position"] is None and not wo["can_replace"]
    assert wo["item_at"] == {"position": None, "how": "placed",
                             "location": {"id": store, "name": "Store", "display": "Store"}}
    assert wo["location"]["id"] == store
    with pytest.raises(Invalid, match="isn't fitted to a position"):
        m.close_work_order(wo["id"], [{"kind": "replace", "new_item": {"name": "Motor M2"}}])
    with pytest.raises(Invalid, match="isn't fitted to a position"):
        m.close_work_order(wo["id"], [{"kind": "inspect", "finding": "degraded", "failure_mode_text": "Rust"}])
    closed = m.close_work_order(wo["id"], [{"kind": "other", "notes": "Shaft turned 2.5 turns"}])
    assert closed["status"] == "closed" and closed["actions"][0]["kind"] == "other"
    # Fitted again 20 days ago: the 50 days it spent in the store don't count.
    m.fit(pump, item_id=motor, on=_ago(m, 20))
    grease = next(t for t in m.item(motor)["tasks"] if t["id"] == paused["id"])
    assert grease["limits"][0]["paused_days"] == 50
    assert grease["next_due"] == (date.fromisoformat(_ago(m, 40)) + timedelta(days=50)).isoformat()


# ---- a location's task: a round -----------------------------------------------------------

def test_a_location_round_lists_the_positions_there(m):
    site = m.create_location("Site")["id"]
    area = m.create_location("Area 1", parent_id=site)["id"]
    elsewhere = m.create_location("Area 2", parent_id=site)["id"]
    plant = m.create_position("Plant", location_id=area)["id"]
    m.create_position("Pump A", parent_id=plant)
    m.create_position("Pump B", parent_id=plant, location_id=elsewhere)
    m.create_position("Tank", location_id=area)
    walk = m.create_task(None, "Area walkdown", 1, "weeks", location_id=area, checklist=["Housekeeping"],
                         include_positions=True, last_done=_ago(m, 8))
    assert walk["overdue"] and walk["include_positions"]
    [wo] = m.generate_work_orders(0)
    assert wo["subject"] == {"kind": "location", "id": area, "name": "Area 1"}
    assert wo["position"] is None and wo["location"]["display"] == "Site › Area 1"
    assert [(c["text"], c.get("position_id") is not None) for c in wo["checklist"]] == [
        ("Housekeeping", False), ("Plant", True), ("Plant › Pump A", True), ("Tank", True)]
    assert m.location(area)["work_orders"][0]["id"] == wo["id"]
    # Work in the area includes the round; the site is above it.
    assert [w["id"] for w in m.work_orders("open", site)] == [wo["id"]]
    assert m.work_orders("open", elsewhere) == []
    m.check_item(wo["id"], 2)
    with pytest.raises(Invalid, match="is a location, not a position"):
        m.close_work_order(wo["id"], [{"kind": "replace", "new_item": {"name": "Pump"}}])
    with pytest.raises(Invalid, match="is a location"):
        m.close_work_order(wo["id"], [{"kind": "repair", "failure_mode_text": "Leak"}])
    closed = m.close_work_order(wo["id"], [{"kind": "inspect", "finding": "ok"}])
    assert closed["status"] == "closed" and closed["fitted"] is None and closed["failure_modes"] == []
    assert m.location(area)["tasks"][0]["last_done"] == m.today()
    # Opened by hand, a round lists them only when asked; a position's work order never does.
    plain = m.open_work_order(None, "Ex inspection", "inspection", location_id=area)
    assert plain["checklist"] == []
    asked = m.open_work_order(None, "Ex inspection", "inspection", location_id=area, include_positions=True)
    assert len(asked["checklist"]) == 3
    with pytest.raises(Invalid, match="Only a location's"):
        m.open_work_order(plant, "Fix", include_positions=True)


def test_work_by_area_includes_items_where_they_are_now(m):
    site = m.create_location("Site")["id"]
    workshop = m.create_location("Workshop", parent_id=site)["id"]
    field = m.create_location("Field")["id"]
    truck = m.create_position("Truck", location_id=field)["id"]
    gauge = m.create_item("Gauge")["id"]
    m.fit(truck, item_id=gauge)
    wo = m.open_work_order(None, "Calibrate", "preventive", item_id=gauge)
    assert [w["id"] for w in m.work_orders("open", field)] == [wo["id"]]
    m.remove(truck)
    m.place_item(gauge, workshop)
    assert m.work_orders("open", field) == []
    assert [w["id"] for w in m.work_orders("open", site)] == [wo["id"]]
    assert m.item(gauge)["work_orders"][0]["location"]["id"] == workshop


def test_a_condition_point_on_an_item_raises_its_alarm_on_the_item(m):
    item = m.create_item("Gearbox G1")["id"]
    point = m.add_point(None, "Oil temperature", kind="condition", unit="°C", alarm_above=90, item_id=item)
    m.record_reading(point["id"], 95)
    [wo] = m.work_orders("open")
    assert wo["subject"]["kind"] == "item" and wo["type"] == "inspection"


# ---- both apply ---------------------------------------------------------------------------

def test_a_position_task_and_its_items_task_fall_due_independently(m):
    pump = m.create_position("Pump")["id"]
    meter = m.create_item("Flow meter FM1")["id"]
    m.fit(pump, item_id=meter, on=_ago(m, 10))
    m.create_task(pump, "Lubricate", 1, "months", last_done=_ago(m, 40))
    m.create_task(None, "Calibrate", 1, "years", item_id=meter, last_done=_ago(m, 400))
    position = m.position(pump)
    assert [t["name"] for t in position["tasks"]] == ["Lubricate"]
    assert [(t["name"], t["subject"]["kind"]) for t in position["item_tasks"]] == [("Calibrate", "item")]
    made = m.generate_work_orders(0)
    assert sorted((w["subject"]["kind"], w["title"]) for w in made) == [("item", "Calibrate"),
                                                                         ("position", "Lubricate")]
    # Closing the item's renews only the item's.
    item_wo = next(w for w in made if w["subject"]["kind"] == "item")
    m.close_work_order(item_wo["id"], [{"kind": "inspect", "finding": "ok"}])
    tasks = m.position(pump)
    assert tasks["item_tasks"][0]["last_done"] == m.today() and tasks["tasks"][0]["last_done"] == _ago(m, 40)


def test_an_items_work_order_can_replace_it_where_it_is_fitted(m):
    pump = m.create_position("Pump")["id"]
    m.add_failure_mode(pump, "Seal leaking")
    seal = m.create_item("Seal kit S1")["id"]
    m.fit(pump, item_id=seal, on=_ago(m, 30))
    wo = m.open_work_order(None, "Seal weeping", item_id=seal)
    assert wo["failure_modes"][0]["text"] == "Seal leaking" and wo["fitted"]["item"]["id"] == seal
    closed = m.close_work_order(wo["id"], [{"kind": "replace", "failure_mode_text": "Seal leaking",
                                             "new_item": {"name": "Seal kit S2"}}])
    assert closed["actions"][0]["removed"]["id"] == seal
    assert m.position(pump)["life_data"][0]["status"] == "failed"


# ---- the log ---------------------------------------------------------------------------

def _props(snapshot):
    nodes, edges = snapshot
    return ([(r[0], r[1], r[2], json.loads(r[3])) for r in nodes],
            [(r[0], r[1], r[2], r[3], r[4], json.loads(r[5])) for r in edges])


def test_a_log_from_before_subjects_projects_the_same_graph():
    """A plant built before tasks had subjects (position tasks from RCM and by hand,
    counters and backdated readings, alarms, renewals, a copy), with the graph that
    code projected from it: the projectors now give exactly that graph."""
    fixture = json.loads((pathlib.Path(__file__).parent / "fixtures" / "maintenance_position_only_log.json").read_text())
    store = GraphStore(":memory:", PROJECTORS)
    for e in fixture["events"]:
        store.log.append({"id": f"e{store.log.count(fixture['org'])}", "org": fixture["org"], "type": e["type"],
                          "at": "2026-10-14T00:00:00+00:00", "actor": "tester", "payload": e["payload"]})
    store.sync()
    assert store.skipped() == []
    assert _props(store.snapshot()) == _props(fixture["snapshot"])
    m = Maintenance(store, fixture["org"], "tester")
    assert all(t["subject"]["kind"] == "position" for t in m.due_tasks(10_000))


def test_a_rebuild_gives_the_same_graph_with_every_subject(m):
    pump = m.create_position("Pump")["id"]
    _hours(m, pump, [(40, 0), (0, 400)])
    engine = m.create_item("Engine")["id"]
    m.fit(pump, item_id=engine, on=_ago(m, 40))
    area = m.create_location("Area")["id"]
    m.update_position(pump, location_id=area)
    m.create_task(None, "Overhaul", 300, "hours", item_id=engine)
    m.create_task(None, "Walk", 1, "days", location_id=area, include_positions=True, last_done=_ago(m, 3))
    for wo in m.generate_work_orders(400):
        m.close_work_order(wo["id"], [{"kind": "other"}])
    before = m.s.snapshot()
    m.s.rebuild()
    assert m.s.snapshot() == before


# ---- REST ------------------------------------------------------------------------------

def test_the_api_takes_item_and_location_tasks(monkeypatch):
    from fastapi.testclient import TestClient

    from backend import config, db
    from backend.auth import get_current_user
    from backend.main import app
    from backend.routers import maintenance as router

    monkeypatch.setattr(db, "_db", mongomock.MongoClient()["reliafy_subjects"])
    monkeypatch.setattr(db, "_simulated", True)
    monkeypatch.setattr(router, "_store", GraphStore(":memory:", PROJECTORS))
    monkeypatch.setattr(config, "MAINTENANCE_ENABLED", True)
    monkeypatch.setattr(config, "MAINTENANCE_EMAILS", {"s@x.com"})
    app.dependency_overrides[get_current_user] = lambda: {
        "uid": ORG, "email": "s@x.com", "name": "S", "email_verified": True}
    client = TestClient(app)
    try:
        item = client.post("/api/maintenance/items", json={"name": "Gauge"}).json()
        loc = client.post("/api/maintenance/locations", json={"name": "Area 1"}).json()
        point = client.post(f"/api/maintenance/items/{item['id']}/points",
                            json={"kind": "counter", "unit": "hours", "name": "Own hours"})
        assert point.status_code == 200 and point.json()["item"]["id"] == item["id"]
        task = client.post(f"/api/maintenance/items/{item['id']}/tasks",
                           json={"name": "Calibrate", "interval": 1, "unit": "years", "while_stored": "pause"})
        assert task.status_code == 200 and task.json()["while_stored"] == "pause"
        bad = client.post(f"/api/maintenance/locations/{loc['id']}/tasks",
                          json={"name": "Walk", "interval": 10, "unit": "hours"})
        assert bad.status_code == 422
        walk = client.post(f"/api/maintenance/locations/{loc['id']}/tasks",
                           json={"name": "Walk", "interval": 1, "unit": "weeks", "include_positions": True}).json()
        changed = client.patch(f"/api/maintenance/tasks/{walk['id']}", json={"include_positions": False})
        assert changed.json()["include_positions"] is False
        wo = client.post("/api/maintenance/work-orders", json={"title": "Walk", "task_id": walk["id"]}).json()
        assert wo["subject"]["kind"] == "location"
        assert client.get(f"/api/maintenance/items/{item['id']}").json()["tasks"][0]["name"] == "Calibrate"
        assert client.get(f"/api/maintenance/locations/{loc['id']}").json()["work_orders"][0]["id"] == wo["id"]
    finally:
        app.dependency_overrides.pop(get_current_user, None)
