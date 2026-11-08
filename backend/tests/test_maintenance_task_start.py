"""A task's start date (Nov 2026): when it first falls due, then every interval
after. A 12-monthly summer task made in November can first fall due next October
instead of next November.

task.added may carry first_due (its start stays the day it was made); a start
changed later is its own event, task.rescheduled {id, first_due, on}. A date set
stands until the task is done on or after the day it was set."""

import pytest

from backend.maintenance.service import PROJECTORS, Invalid, Maintenance
from backend.maintenance.store import GraphStore
from backend.tests.test_maintenance_mcp import _do, _ok, _session, env  # noqa: F401
from backend.tests.test_maintenance_rcm_api import api  # noqa: F401

ORG = "user-a"
M = "/api/maintenance"
TODAY = "2026-11-09"


@pytest.fixture()
def m():
    out = Maintenance(GraphStore(":memory:", PROJECTORS), ORG, "tester")
    out.today = lambda: TODAY
    return out


def _rebuilds_the_same(m):
    before = m.s.snapshot()
    m.s.rebuild()
    assert m.s.snapshot() == before


def _events(m, type):
    return [e for e in m.s.events(ORG, 1000) if e["type"] == type]


def test_without_a_start_it_first_falls_due_one_interval_from_today(m):
    pool = m.create_position("Pool")
    task = m.create_task(pool["id"], "Raise the weekly acid dose for summer", 12, "months")
    assert task["next_due"] == "2027-11-09" and task["first_due"] is None
    assert "first_due" not in _events(m, "task.added")[0]["payload"]


def test_a_start_given_on_create_is_the_first_due_date_then_every_interval(m):
    pool = m.create_position("Pool")
    task = m.create_task(pool["id"], "Raise the weekly acid dose for summer", 12, "months", start="2027-10-01")
    assert task["next_due"] == "2027-10-01" and task["first_due"] == "2027-10-01" and not task["overdue"]
    payload = _events(m, "task.added")[0]["payload"]
    assert payload["start"] == TODAY and payload["first_due"] == "2027-10-01"
    # Not due within 30 days: no work order, not overdue.
    assert m.due_tasks(30) == [] and m.generate(30)["work_orders"] == []
    # The LSA table's Next due follows it.
    row = next(t for t in m.task_table(pool["id"])["tasks"] if t["id"] == task["id"])
    assert row["next_due"] == "2027-10-01"
    _rebuilds_the_same(m)
    # Done in October: the next one is a year after that.
    m.today = lambda: "2027-10-01"
    wo = m.generate(30)["work_orders"]
    assert len(wo) == 1
    m.close_work_order(wo[0]["id"], on="2027-10-03")
    after = m._task_view(m._get(task["id"], "Task"))
    assert after["last_done"] == "2027-10-03" and after["next_due"] == "2028-10-03" and after["first_due"] is None
    _rebuilds_the_same(m)


def test_rescheduling_moves_the_next_due_date_and_clearing_goes_back(m):
    pool = m.create_position("Pool")
    task = m.create_task(pool["id"], "Lower the acid dose for winter", 12, "months", last_done="2026-05-01")
    assert task["next_due"] == "2027-05-01"
    view = m.update_task(task["id"], start="2027-04-01")
    assert view["next_due"] == "2027-04-01" and view["first_due"] == "2027-04-01"
    ev = _events(m, "task.rescheduled")
    assert [e["payload"] for e in ev] == [{"id": task["id"], "first_due": "2027-04-01", "on": TODAY}]
    # The same date again is no new event; other changes alone don't reschedule.
    m.update_task(task["id"], start="2027-04-01")
    m.update_task(task["id"], name="Lower the acid dose")
    assert len(_events(m, "task.rescheduled")) == 1
    _rebuilds_the_same(m)
    cleared = m.update_task(task["id"], start="")
    assert cleared["next_due"] == "2027-05-01" and cleared["first_due"] is None
    _rebuilds_the_same(m)


def test_a_start_in_the_past_is_overdue_and_due_now(m):
    pool = m.create_position("Pool")
    task = m.create_task(pool["id"], "Backwash", 3, "months", start="2026-11-01")
    assert task["overdue"] and [t["id"] for t in m.due_tasks(0)] == [task["id"]]


def test_a_start_is_for_calendar_tasks(m):
    pump = m.create_position("Pump")
    m.add_point(pump["id"], "PUMP-HRS", unit="hours")
    with pytest.raises(Invalid, match="by the calendar"):
        m.create_task(pump["id"], "Grease", 500, "hours", start="2027-01-01")
    with pytest.raises(Invalid, match="date like"):
        m.create_task(pump["id"], "Inspect", 6, "months", start="October")
    # A second limit by the calendar may take one: the calendar limit falls due then.
    both = m.create_task(pump["id"], "Service", 500, "hours", also_interval=6, also_unit="months",
                         start="2027-02-01")
    cal = next(lim for lim in both["limits"] if lim["limit"] == "6 months")
    assert cal["next_due"] == "2027-02-01"


def test_a_failure_modes_new_task_takes_a_start_and_the_rcm_read_shows_it(m):
    pool = m.create_position("Pool")
    fm = m.add_failure_mode(pool["id"], "Algae bloom in summer")
    task = m.add_mode_task(fm["id"], "Raise the chlorine for summer", 12, "months", "fixed_interval",
                           start="2027-10-01")
    assert task["next_due"] == "2027-10-01"
    row = next(t for t in m.rcm_mode(fm["id"])["tasks"] if t["id"] == task["id"])
    assert row["next_due"] == "2027-10-01" and row["first_due"] == "2027-10-01"
    _rebuilds_the_same(m)


def test_start_over_rest(api):
    pool = api.post(f"{M}/positions", json={"name": "Pool"}).json()
    task = api.post(f"{M}/positions/{pool['id']}/tasks",
                    json={"name": "Summer dose", "interval": 12, "unit": "months", "start": "2027-10-01"}).json()
    assert task["next_due"] == "2027-10-01"
    r = api.patch(f"{M}/tasks/{task['id']}", json={"start": "2028-04-01"})
    assert r.status_code == 200 and r.json()["next_due"] == "2028-04-01"
    r = api.patch(f"{M}/tasks/{task['id']}", json={"start": None})
    assert r.status_code == 200 and r.json()["first_due"] is None
    fm = api.post(f"{M}/positions/{pool['id']}/failure-modes", json={"text": "Algae"}).json()
    r = api.post(f"{M}/failure-modes/{fm['id']}/tasks",
                 json={"name": "Shock dose", "interval": 12, "unit": "months", "start": "2027-12-01"})
    assert r.status_code == 200 and r.json()["next_due"] == "2027-12-01"


def test_start_over_mcp(env):
    async def flow(client):
        pool = _ok(await _do(client, "maintenance", "positions.create", name="Pool"))["id"]
        task = _ok(await _do(client, "maintenance", "tasks.create", position_id=pool, name="Summer dose",
                             interval=12, unit="months", start="2027-10-01"))
        assert task["next_due"] == "2027-10-01"
        moved = _ok(await _do(client, "maintenance", "tasks.update", task_id=task["id"], start="2028-04-01"))
        assert moved["next_due"] == "2028-04-01"
        fm = _ok(await _do(client, "maintenance", "failure_modes.add", position_id=pool, text="Algae"))
        return _ok(await _do(client, "maintenance", "failure_modes.add_task", failure_mode_id=fm["id"],
                             name="Shock dose", interval=12, unit="months", start="2027-12-01"))

    assert _session(env["token"], flow)["next_due"] == "2027-12-01"
