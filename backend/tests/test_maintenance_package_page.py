"""Reliafy Maintenance: the reads behind a package's own page. Its next six visits
(each with the tasks on it, by their visit rules) and its recent work orders with
what was done on each."""

from datetime import date

import pytest

from backend.maintenance import service
from backend.maintenance.service import PROJECTORS, Maintenance
from backend.maintenance.store import GraphStore


@pytest.fixture()
def today(monkeypatch):
    class Clock:
        day = date(2026, 11, 10)

        def set(self, text):
            self.day = date.fromisoformat(text)

    clock = Clock()
    monkeypatch.setattr(service.time_zones, "today", lambda name=None: clock.day)
    return clock


@pytest.fixture()
def m(today):
    return Maintenance(GraphStore(":memory:", PROJECTORS), "user-pp", "tester")


def _weekly(m):
    pump = m.create_position("Pump 1")["id"]
    check = m.create_task(pump, "Check seal", 1, "weeks", start="2026-11-14")["id"]
    grease = m.create_task(pump, "Grease bearings", 1, "months", start="2026-11-14")["id"]
    pkg = m.create_package("Saturday round", position_id=pump, every=1, unit="weeks", weekday="saturday",
                           anchor="2026-11-14", tasks=[check, {"task_id": grease, "visit_rule": "nth", "every_nth": 4}])
    return pkg, check, grease


def test_a_package_lists_its_next_six_visits_with_their_tasks(m):
    pkg, check, grease = _weekly(m)
    page = m.package(pkg["id"])
    visits = page["next_visits"]
    assert [v["on"] for v in visits] == ["2026-11-14", "2026-11-21", "2026-11-28", "2026-12-05", "2026-12-12",
                                         "2026-12-19"]
    # The every-4th task is on the first visit and every fourth after it.
    assert [grease in v["task_ids"] for v in visits] == [True, False, False, False, True, False]
    assert all(check in v["task_ids"] for v in visits)
    assert [v["tasks"] for v in visits] == [2, 1, 1, 1, 2, 1]
    # The rule shows on its task's row.
    rows = {t["task_id"]: t for t in page["tasks"]}
    assert (rows[grease]["visit_rule"], rows[grease]["every_nth"]) == ("nth", 4)


def test_a_paused_or_retired_package_has_no_next_visits(m):
    pkg, _, _ = _weekly(m)
    m.pause_package(pkg["id"], "Shut down", None)
    assert m.package(pkg["id"])["next_visits"] == []


def test_recent_work_orders_say_what_was_done(m, today):
    pkg, check, grease = _weekly(m)
    today.set("2026-11-14")
    m.generate(7)
    [wo] = m.package(pkg["id"])["work_orders"]
    assert wo["status"] == "open" and "done" not in wo
    for task_id in (check, grease):
        m.mark_line(wo["id"], task_id, "done")
    m.close_work_order(wo["id"], [{"kind": "inspect", "finding": "ok"}])
    [wo] = m.package(pkg["id"])["work_orders"]
    assert wo["status"] == "closed" and wo["done"] == [{"kind": "inspect", "finding": "ok"}]


def test_editing_visit_rules_and_timing_goes_through_the_update(m):
    pkg, check, grease = _weekly(m)
    page = m.update_package(pkg["id"], name="Saturday station round", tolerance=2, tolerance_unit="days",
                            trade="Fitter", notes="Bring the grease gun",
                            tasks=[{"task_id": grease, "visit_rule": "every"}])
    assert page["name"] == "Saturday station round" and page["trade"] == "Fitter"
    assert page["tolerance"]["amount"] == 2 and page["notes"] == "Bring the grease gun"
    assert {t["task_id"]: t["visit_rule"] for t in page["tasks"]}[grease] == "every"
    assert all(v["tasks"] == 2 for v in page["next_visits"])
    before = m.s.snapshot()
    m.s.rebuild()
    assert m.s.snapshot() == before


def test_with_a_visit_open_the_next_visits_still_carry_their_tasks(m, today):
    """A monthly package with every-visit, every-3rd and every-12th tasks and its current
    visit open: the open visit comes first, with its work order's tasks, and every later
    visit carries the every-visit task (it's on the open work order too), the others on
    their own visits."""
    today.set("2026-12-01")
    drone = m.create_position("Survey drone 3")["id"]
    failsafe = m.create_task(drone, "Failsafe tests", 1, "months", start="2026-12-07")["id"]
    battery = m.create_task(drone, "Battery storage check", 3, "months", start="2026-12-07")["id"]
    annual = m.create_task(drone, "Annual inspection", 1, "years", start="2026-12-07")["id"]
    pkg = m.create_package("Monthly maintenance visit", position_id=drone, every=1, unit="months", weekday="monday",
                           nth=1, anchor="2026-12-07",
                           tasks=[failsafe, {"task_id": battery, "visit_rule": "nth", "every_nth": 3},
                                  {"task_id": annual, "visit_rule": "nth", "every_nth": 12}])
    m.generate(10)
    [wo] = m.work_orders("open")
    assert wo["visit_on"] == "2026-12-07"

    visits = m.package(pkg["id"])["next_visits"]
    first, rest = visits[0], visits[1:]
    assert first["on"] == "2026-12-07" and first["open_work_order"]["number"] == wo["number"]
    assert set(first["task_ids"]) == {failsafe, battery, annual} and first["tasks"] == 3
    assert [v["on"] for v in rest] == ["2027-01-04", "2027-02-01", "2027-03-01", "2027-04-05", "2027-05-03",
                                       "2027-06-07"]
    assert all(failsafe in v["task_ids"] and v["tasks"] >= 1 for v in rest)
    # The every-3rd task on the 4th visit (1 Mar), the every-12th not within these.
    assert [battery in v["task_ids"] for v in rest] == [False, False, True, False, False, True]
    assert not any(annual in v["task_ids"] for v in rest)
    assert all("open_work_order" not in v for v in rest)
