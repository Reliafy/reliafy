"""Reliafy Maintenance: corrections (all as events), moving items, item
positions, locations and position classes."""

from datetime import date, timedelta

import pytest

from backend.maintenance.service import PROJECTORS, Invalid, Maintenance
from backend.maintenance.store import GraphStore


@pytest.fixture()
def m():
    return Maintenance(GraphStore(":memory:", PROJECTORS), "org-e", "tester")


def _ago(days: int) -> str:
    return (date.today() - timedelta(days=days)).isoformat()


def test_nameplate_fields_merge_and_clear(m):
    pid = m.create_position("Hot water system")["id"]
    m.fit(pid, new_item={"name": "Hot water unit"})
    item_id = m.position(pid)["fitted"]["item"]["id"]
    item = m.update_item(item_id, manufacturer="Rheem", model="491315", serial="R1903-4411",
                         nameplate={"Capacity": "315 L", "Element": "3.6 kW", "Pressure": "850 kPa"})
    assert (item["manufacturer"], item["model"], item["serial"]) == ("Rheem", "491315", "R1903-4411")
    assert item["nameplate"]["Element"] == "3.6 kW"
    item = m.update_item(item_id, nameplate={"Element": "", "Year": "2019"})
    assert item["nameplate"] == {"Capacity": "315 L", "Pressure": "850 kPa", "Year": "2019"}
    with pytest.raises(Invalid):
        m.update_item(item_id, name="")


def test_a_rotable_moves_and_keeps_one_history(m):
    a = m.create_position("Pump A", position_class="Pool pump")["id"]
    b = m.create_position("Pump B", position_class="Pool pump")["id"]
    m.fit(a, new_item={"name": "Astral CTX", "serial": "P1"}, on=_ago(300))
    pump = m.position(a)["fitted"]["item"]["id"]
    with pytest.raises(Invalid):
        m.move_item(pump, a)
    moved = m.move_item(pump, b, on=_ago(100))
    assert moved["fitted_to"]["id"] == b
    assert [h["position"]["name"] for h in moved["history"]] == ["Pump B", "Pump A"]
    assert m.position(a)["fitted"] is None
    pooled = m.class_life_data("Pool pump")
    assert [(r["position"], r["x"], r["c"]) for r in pooled["rows"]] == [("Pump A", 200, 1), ("Pump B", 100, 1)]
    assert m.position_classes() == [{"position_class": "Pool pump", "positions": 2, "fitments": 2, "failures": 0}]


def test_mistakes_are_struck_out_or_corrected(m):
    pid = m.create_position("Smoke alarm")["id"]
    m.fit(pid, new_item={"name": "Wrong alarm"}, on=_ago(10))
    wrong = m.position(pid)["fitted"]["id"]
    m.void_fitment(wrong, "fitted to the wrong position")
    assert m.position(pid)["fitted"] is None and m.life_data(pid) == []
    m.fit(pid, new_item={"name": "Quell 240V"}, on=_ago(50))
    right = m.position(pid)["fitted"]["id"]
    fixed = m.correct_fitment(right, start=_ago(60))
    assert fixed["from"] == _ago(60)
    with pytest.raises(Invalid):
        m.correct_fitment(right, end=_ago(5))  # still fitted
    wo = m.open_work_order(pid, "Test alarm", type="inspection")
    m.update_work_order(wo["id"], title="Test alarm (monthly)", due=_ago(-7))
    assert m.work_order(wo["id"])["title"] == "Test alarm (monthly)"
    assert m.cancel_work_order(wo["id"], "duplicate")["status"] == "cancelled"
    with pytest.raises(Invalid):
        m.close_work_order(wo["id"], [])


def test_tasks_edit_and_retire_and_positions_retire(m):
    class Study:
        id, name, system = "s1", "Alarm RCM", "Smoke alarms"
        functions = [{"id": "f", "text": "Detect smoke", "failures": [{"id": "ff", "text": "No alarm", "modes": [
            {"id": "m1", "text": "Battery flat", "consequence": "hidden",
             "decision": {"outcome": "failure_finding", "interval": 1, "interval_unit": "months",
                          "task": "Press test"}}]}]}]

    pos = m.position_from_rcm(Study())["position"]
    task = pos["tasks"][0]
    edited = m.update_task(task["id"], name="Press the test button", interval=3, unit="mo")
    assert (edited["name"], edited["interval"], edited["unit"]) == ("Press the test button", 3, "months")
    m.retire_task(task["id"])
    assert m.position(pos["id"])["tasks"] == [] and m.due_tasks(400) == []
    m.fit(pos["id"], new_item={"name": "Alarm"})
    with pytest.raises(Invalid):
        m.retire_position(pos["id"])  # something's fitted
    m.remove(pos["id"])
    m.retire_position(pos["id"], "alarms replaced by a hard-wired system")
    assert m.tree() == []


def test_item_positions_move_with_their_item(m):
    truck = m.create_position("Truck 14")["id"]
    m.fit(truck, new_item={"name": "Engine", "serial": "E123"})
    engine = m.position(truck)["fitted"]["item"]["id"]
    turbo = m.create_position("Turbo 1", parent_id=engine)["id"]
    m.fit(turbo, new_item={"name": "Turbocharger", "serial": "T9"})
    assert [p["name"] for p in m._position_path(turbo)] == ["Truck 14", "Engine"]
    assert m.item(engine)["positions"][0]["item"]["serial"] == "T9"
    assert "Turbo 1" not in {t["name"] for t in m.tree()}  # item positions aren't plant positions
    truck22 = m.create_position("Truck 22")["id"]
    m.remove(truck)
    m.move_item(engine, truck22)
    assert [p["name"] for p in m._position_path(turbo)] == ["Truck 22", "Engine"]


def test_locations_tree_and_what_is_where(m):
    house = m.create_location("House")["id"]
    garage = m.create_location("Garage", parent_id=house)["id"]
    spare = m.create_item("Spare anode")
    m.place_item(spare["id"], garage)
    assert m.location_tree() == [{"id": house, "name": "House", "items": 0,
                                  "children": [{"id": garage, "name": "Garage", "items": 1, "children": []}]}]
    shed = m.update_location(garage, name="Shed")
    assert shed["name"] == "Shed" and shed["items"][0]["name"] == "Spare anode" and shed["path"][0]["name"] == "House"
    with pytest.raises(Invalid):
        m.update_location(house, parent_id=garage)


def test_rebuild_still_matches_after_corrections(m):
    test_mistakes_are_struck_out_or_corrected(m)
    test_item_positions_move_with_their_item(m)
    before = m.s.snapshot()
    m.s.rebuild()
    assert m.s.snapshot() == before
