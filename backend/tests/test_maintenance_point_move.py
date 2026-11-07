"""Moving a measurement point to another position (point.moved): its readings go
with it (they hang off the point), so does an open alarm work order it raised
(work_order.moved), and a task by use that counted it as its position's counter
is pinned to it in the event, so it counts the same readings after the move."""

import pytest

from backend.maintenance import apply
from backend.maintenance.service import PROJECTORS, Invalid, Maintenance, NotFound
from backend.maintenance.store import GraphStore

ORG = "user-a"


@pytest.fixture()
def m():
    return Maintenance(GraphStore(":memory:", PROJECTORS), ORG, "tester")


def _rebuilds_the_same(m):
    before = m.s.snapshot()
    m.s.rebuild()
    assert m.s.snapshot() == before


def _events(m, type):
    return [e for e in m.s.events(ORG, 1000) if e["type"] == type]


def _on(m, node_id):
    return m.s.out(ORG, node_id, "ON")[0]["id"]


def test_a_point_moves_with_its_readings(m):
    pool = m.create_position("Pool")
    water = m.create_position("Pool water", parent_id=pool["id"])
    chlor = m.create_position("Salt chlorinator", parent_id=pool["id"])
    point = m.add_point(chlor["id"], "Free chlorine", "condition", "ppm", alarm_below=0.5)
    m.record_reading(point["id"], 2.1, on="2026-11-01")
    m.record_reading(point["id"], 1.8, on="2026-11-02")
    out = m.move_point(point["id"], water["id"])
    assert out["from_position_id"] == chlor["id"] and out["tasks_pinned"] == [] and "note" not in out
    assert _on(m, point["id"]) == water["id"]
    [event] = _events(m, "point.moved")
    assert event["payload"] == {"id": point["id"], "position_id": water["id"], "from_position_id": chlor["id"],
                                "on": m.today()}
    assert sorted(r["value"] for r in m.point(point["id"])["readings"]) == [1.8, 2.1]
    _rebuilds_the_same(m)
    # A batch undoes it by moving it back.
    undo = apply._undo_for({"do": "measurements.move_point", "args": {"point_id": point["id"],
                                                                      "position_id": water["id"]}}, out)
    assert undo == {"do": "measurements.move_point", "args": {"point_id": point["id"], "position_id": chlor["id"]}}


def test_tasks_that_counted_it_keep_counting_it(m):
    a = m.create_position("Pump A")
    b = m.create_position("Pump B")
    hours = m.add_point(a["id"], "Run hours", "counter", "hours")
    m.record_reading(hours["id"], 100, on="2026-10-01")
    implicit = m.create_task(a["id"], "Grease", 500, "hours")
    named = m.create_task(a["id"], "Oil change", 2000, "hours", point_id=hours["id"])
    assert m.task_measurement(implicit["id"])["measurement"]["id"] == hours["id"]
    out = m.move_point(hours["id"], b["id"])
    assert out["tasks_pinned"] == [implicit["id"]]
    [event] = _events(m, "point.moved")
    assert event["payload"]["task_changes"] == {implicit["id"]: {"point_id": hours["id"]}}
    assert m.s.node(ORG, implicit["id"])["point_id"] == hours["id"]
    for t in (implicit, named):
        assert m.task_measurement(t["id"])["measurement"]["id"] == hours["id"]
    # Both now count a point away from their branch: named, and kept.
    assert "Grease, Oil change count it from a position that isn't above or below Pump B" in out["note"]
    _rebuilds_the_same(m)


def test_an_open_alarm_work_order_goes_with_it(m):
    a = m.create_position("Pump A")
    b = m.create_position("Pump B")
    vib = m.add_point(a["id"], "Vibration", "condition", "mm/s", alarm_above=7)
    m.record_reading(vib["id"], 9.5)
    [wo] = [w for w in m.s.inn(ORG, vib["id"], "ALARM_FOR")]
    assert _on(m, wo["id"]) == a["id"]
    out = m.move_point(vib["id"], b["id"])
    assert [w["id"] for w in out["work_orders_moved"]] == [wo["id"]] and "moved with it" in out["note"]
    assert _on(m, wo["id"]) == b["id"]
    [event] = _events(m, "work_order.moved")
    assert event["payload"]["point_id"] == vib["id"] and event["payload"]["from_position_id"] == a["id"]
    _rebuilds_the_same(m)


def test_refusals_say_what_to_do(m):
    a = m.create_position("Pump A")
    b = m.create_position("Pump B")
    point = m.add_point(a["id"], "Pressure", "condition", "kPa")
    with pytest.raises(Invalid, match="Say which position"):
        m.move_point(point["id"], "")
    with pytest.raises(Invalid, match="already on Pump A"):
        m.move_point(point["id"], a["id"])
    with pytest.raises(Invalid, match="no position with that id"):
        m.move_point(point["id"], "nope")
    m.retire_position(b["id"])
    with pytest.raises(Invalid, match="Pump B has been retired"):
        m.move_point(point["id"], b["id"])
    with pytest.raises(NotFound):
        m.move_point("nope", a["id"])
    item = m.create_item("Generator G-1")
    own = m.add_point(None, "Hours", "counter", "hours", item_id=item["id"])
    c = m.create_position("Pump C")
    with pytest.raises(Invalid, match="An item's point travels with the item"):
        m.move_point(own["id"], c["id"])
    m.retire_point(point["id"])
    with pytest.raises(Invalid, match="retired"):
        m.move_point(point["id"], c["id"])
    assert _events(m, "point.moved") == []
    # A point worked out from a signal channel stays with its channel.
    derived = m.add_point(a["id"], "Overall", "condition", "mm/s")
    m.s.patch_node(ORG, derived["id"], {"derived": True})
    with pytest.raises(Invalid, match="stays with its channel"):
        m.move_point(derived["id"], c["id"])
