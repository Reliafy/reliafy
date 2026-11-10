"""Reliafy Maintenance: one due date per work order, and one rule for overdue, in
every list and count (the task's row, the work order's page, the open work orders,
the tree and the assets)."""

from datetime import date

import pytest

from backend.maintenance import service
from backend.maintenance.service import PROJECTORS, Maintenance
from backend.maintenance.store import GraphStore


@pytest.fixture()
def today(monkeypatch):
    """The workspace's today, set by the test: today.set("2026-11-10")."""
    class Clock:
        day = date(2026, 11, 10)

        def set(self, text):
            self.day = date.fromisoformat(text)

    clock = Clock()
    monkeypatch.setattr(service.time_zones, "today", lambda name=None: clock.day)
    return clock


@pytest.fixture()
def m(today):
    return Maintenance(GraphStore(":memory:", PROJECTORS), "user-od", "tester")


def _same_after_rebuild(m):
    before = m.s.snapshot()
    m.s.rebuild()
    assert m.s.snapshot() == before


def _view(m, task_id):
    return m._task_view(m.s.node(m.org, task_id))


def test_a_task_is_due_when_its_open_work_order_is(m, today):
    today.set("2026-11-01")
    pump = m.create_position("Pump 1")["id"]
    task = m.create_task(pump, "Grease the bearings", 1, "weeks", start="2026-11-01")["id"]
    [wo] = m.generate_work_orders(30)
    assert wo["due"] == "2026-11-01" and not wo["overdue"]  # due today isn't overdue

    # The schedule moves on (its package's next visit is three weeks off), and the work
    # order raised for 1 Nov is still open: the task goes by the work order, everywhere.
    pkg = m.create_package("Weekly round", position_id=pump, every=1, unit="weeks", weekday="saturday",
                           anchor="2026-11-21", tasks=[task])
    today.set("2026-11-10")
    view = _view(m, task)
    assert view["scheduled_due"] == "2026-11-21" and view["package"]["id"] == pkg["id"]
    assert view["next_due"] == "2026-11-01" and view["overdue"] and view["due_by"] == "work_order"
    assert view["open_work_order"] == {"id": wo["id"], "number": wo["number"], "due": "2026-11-01", "overdue": True}
    [row] = m.due_tasks(30)
    assert (row["next_due"], row["overdue"], row["open_work_order"]["number"]) == ("2026-11-01", True, wo["number"])
    assert [t["id"] for t in m.due_tasks(0) if t["overdue"]] == [task]
    page = m.work_order(wo["id"])
    assert page["due"] == "2026-11-01" and page["overdue"]
    [listed] = m.work_orders("open")
    assert listed["due"] == "2026-11-01" and listed["overdue"]
    # The tree and the assets count it the same way.
    [top] = m.tree()
    assert top["status"]["overdue"] == 1 and top["status"]["next_due"] == "2026-11-01"
    rest = m.places()["not_placed"]
    assert (rest["due"], rest["overdue"], rest["next_due"]) == (1, 1, "2026-11-01")

    # A new due date on the work order is the task's too.
    m.update_work_order(wo["id"], due="2026-11-12")
    view = _view(m, task)
    assert view["next_due"] == "2026-11-12" and not view["overdue"]
    assert not view["open_work_order"]["overdue"] and not m.work_order(wo["id"])["overdue"]
    assert m.tree()[0]["status"]["overdue"] == 0
    # Closed: the task is back on its schedule, and a closed work order is never overdue.
    m.update_work_order(wo["id"], due="2026-11-01")
    m.close_work_order(wo["id"], [{"kind": "inspect", "finding": "ok"}])
    view = _view(m, task)
    assert view["open_work_order"] is None and view["next_due"] == view["scheduled_due"]
    assert view["due_by"] == "package" and not view["overdue"]
    assert not m.work_order(wo["id"])["overdue"]
    _same_after_rebuild(m)


def test_open_work_orders_are_listed_most_overdue_first(m, today):
    pump = m.create_position("Pump 1")["id"]
    late = m.open_work_order(pump, "Replace the seal", due="2026-11-05")
    undated = m.open_work_order(pump, "Look at the noise")
    oldest = m.open_work_order(pump, "Fix the leak", due="2026-10-20")
    soon = m.open_work_order(pump, "Paint the guard", due="2026-11-20")
    tied = m.open_work_order(pump, "Tighten the bolts", due="2026-11-05")
    today_due = m.open_work_order(pump, "Check the gauge", due="2026-11-10")
    done = m.open_work_order(pump, "Old job", due="2026-10-01")
    m.close_work_order(done["id"], [{"kind": "repair"}])
    m.set_work_status(tied["id"], "waiting", "parts on order")  # waiting is still open

    listed = m.work_orders("open")
    assert [w["number"] for w in listed] == [oldest["number"], late["number"], tied["number"],
                                             today_due["number"], soon["number"], undated["number"]]
    assert [w["overdue"] for w in listed] == [True, True, True, False, False, False]
    # Every other list keeps its order (newest first); a closed one is never overdue.
    everything = m.work_orders()
    assert [w["number"] for w in everything] == sorted((w["number"] for w in everything), reverse=True)
    assert [w["overdue"] for w in m.work_orders("closed")] == [False]
    _same_after_rebuild(m)


def test_a_work_package_visit_keeps_its_on_time_days(m, today):
    today.set("2026-11-02")
    pump = m.create_position("Pump 1")["id"]
    task = m.create_task(pump, "Walk the line", 1, "weeks")["id"]
    m.create_package("Weekly round", position_id=pump, every=1, unit="weeks", weekday="saturday",
                     anchor="2026-11-02", tolerance=2, tasks=[task])
    today.set("2026-11-07")
    [wo] = m.generate(7)["work_orders"]
    assert wo["due"] == wo["visit_on"] == "2026-11-07"
    # Two days after the visit it's still on time; on the third it's overdue, on its
    # row, its task's row and the tree alike.
    today.set("2026-11-09")
    assert not m.work_orders("open")[0]["overdue"] and not _view(m, task)["overdue"]
    assert m.tree()[0]["status"]["overdue"] == 0
    today.set("2026-11-10")
    [listed] = m.work_orders("open")
    view = _view(m, task)
    assert listed["overdue"] and listed["late"] and view["overdue"]
    assert view["next_due"] == "2026-11-07" and view["due_by"] == "package"
    assert view["open_work_order"]["overdue"] and m.tree()[0]["status"]["overdue"] == 1
    # A due date set by hand on it is the date that counts.
    m.update_work_order(wo["id"], due="2026-11-13")
    assert not m.work_orders("open")[0]["overdue"]
    view = _view(m, task)
    assert view["next_due"] == "2026-11-13" and not view["overdue"]
    _same_after_rebuild(m)


def test_assets_with_no_location_are_listed_by_their_top_position(m, today):
    site = m.create_location("Depot")["id"]
    m.create_position("Conveyor", location_id=site)
    station = m.create_position("Riverside pumping station", description="Raw water intake")["id"]
    pumps = [m.create_position(f"Pump {n}", parent_id=station)["id"] for n in (1, 2, 3)]
    motor = m.create_position("Motor", parent_id=pumps[0])["id"]
    spare = m.create_position("Borehole")["id"]
    m.fit(pumps[0], new_item={"name": "KSB pump", "serial": "K-1"})
    m.open_work_order(pumps[1], "Replace the seal", due="2026-11-01")
    m.open_work_order(station, "Paint the fence")
    m.create_task(motor, "Grease the motor", 1, "months", start="2026-10-20")  # overdue
    m.create_task(pumps[2], "Check the coupling", 1, "months", start="2026-11-20")  # due soon
    m.create_task(spare, "Dip the level", 1, "years", start="2027-06-01")  # not due yet

    rest = m.places()["not_placed"]
    assert set(rest["position_ids"]) == {station, *pumps, motor, spare}
    assert [r["name"] for r in rest["roots"]] == ["Borehole", "Riverside pumping station"]
    borehole, riverside = rest["roots"]
    assert riverside == {"id": station, "name": "Riverside pumping station", "tag": "",
                         "description": "Raw water intake", "positions": 5, "items": 1, "open_work_orders": 2,
                         "due": 2, "overdue": 1, "next_due": "2026-10-20"}
    assert {k: borehole[k] for k in ("positions", "items", "open_work_orders", "due", "overdue", "next_due")} == {
        "positions": 1, "items": 0, "open_work_orders": 0, "due": 0, "overdue": 0, "next_due": None}
    # Together they are the positions with no location.
    for key in ("positions", "items", "open_work_orders", "due", "overdue"):
        assert sum(r[key] for r in rest["roots"]) == rest[key]

    # Given a location, the station is no longer one of them: it's inside that asset.
    m.update_position(station, location_id=site)
    view = m.places()
    assert [r["name"] for r in view["not_placed"]["roots"]] == ["Borehole"]
    assert view["places"][0]["positions"] == 6
    _same_after_rebuild(m)
