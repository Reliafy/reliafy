"""What a task by use counts, through a move and when it's changed.

A measurement point belongs to the position (or item) it describes. A task that
moves keeps counting what it counted (an implicit counter is pinned in the move
event) while that measurement is on the new position, above or below it, or on
the item fitted there. When it isn't, the move needs a choice: keep it, switch
to a measurement there (with the last-done reading on it, given or worked out
from the date), or go by the calendar. Old move events replay as before."""

import pytest

from backend.maintenance.service import (
    PROJECTORS, Invalid, Maintenance, NeedsChoice, _estimate_reading,
)
from backend.maintenance.store import GraphStore
from backend.tests.test_maintenance_mcp import env  # noqa: F401
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


def _trucks(m):
    """Two trucks with an engine position each; each truck has an engine-hours
    counter with readings through the year. A task on Truck 12 counts its hours
    (no point chosen) and was last done on 1 March."""
    t12 = m.create_position("Truck 12")
    e12 = m.create_position("Engine", parent_id=t12["id"])
    t14 = m.create_position("Truck 14")
    e14 = m.create_position("Engine", parent_id=t14["id"])
    h12 = m.add_point(t12["id"], "Engine hours", kind="counter", unit="hours")
    h14 = m.add_point(t14["id"], "Engine hours", kind="counter", unit="hours")
    for on, v12, v14 in (("2026-01-01", 1000, 5000), ("2026-02-15", 1300, 5200), ("2026-03-15", 1900, 5600)):
        m.record_reading(h12["id"], v12, on=on)
        m.record_reading(h14["id"], v14, on=on)
    task = m.create_task(t12["id"], "Service", 500, "hours", last_done="2026-03-01")
    return t12, e12, t14, e14, h12, h14, task


# ---- working a reading out from the date -----------------------------------------------

def test_estimate_reading():
    rows = [{"on": "2026-01-01", "value": 100.0}, {"on": "2026-01-11", "value": 200.0}]
    assert _estimate_reading(rows, "2026-01-11") == (200.0, False)  # read that day
    assert _estimate_reading(rows, "2026-01-06") == (150.0, True)  # between two readings
    assert _estimate_reading(rows, "2026-01-21") == (300.0, True)  # on from the recent rate (10 a day)
    assert _estimate_reading(rows, "2025-12-27") == (50.0, True)  # back from the rate
    assert _estimate_reading(rows, "2025-01-01") == (0.0, True)  # never below 0
    assert _estimate_reading(rows[:1], "2026-02-01") == (100.0, True)  # one reading: no rate
    assert _estimate_reading([], "2026-02-01") == (None, True)


# ---- moves that fit: no question ------------------------------------------------------------

def test_an_implicit_counter_is_pinned_when_the_task_moves_below(m):
    t12, e12, t14, e14, h12, h14, task = _trucks(m)
    assert m._get(task["id"], "Task").get("point_id") is None
    reading = m._get(task["id"], "Task")["last_done_reading"]
    assert reading == 1600  # interpolated: 1 March, halfway between 15 Feb (1300) and 15 March (1900)
    m.add_point(e12["id"], "Engine ECU hours", kind="counter", unit="hours")  # the engine has its own too

    out = m.move_task(task["id"], e12["id"])
    moved = m._get(task["id"], "Task")
    # It still counts the truck's hours (above the engine), not the engine's own counter.
    assert moved["point_id"] == h12["id"] and moved["last_done_reading"] == reading
    assert out["measurement_changes"] == {task["id"]: {"point_id": h12["id"]}}
    assert out["undo_measurement"] == {task["id"]: {"choice": "restore", "point_id": None}}
    [event] = _events(m, "task.moved")
    assert event["payload"]["task_changes"] == {task["id"]: {"point_id": h12["id"]}}
    _rebuilds_the_same(m)


def test_a_task_moving_up_keeps_a_counter_now_below_it(m):
    t12, e12, t14, e14, h12, h14, task = _trucks(m)
    ecu = m.add_point(e12["id"], "ECU hours", kind="counter", unit="hours")
    m.record_reading(ecu["id"], 50, on="2026-01-01")
    on_engine = m.create_task(e12["id"], "Valve lash", 1000, "hours")
    m.move_task(on_engine["id"], t12["id"])  # the ECU counter is below Truck 12: it fits
    assert m._get(on_engine["id"], "Task")["point_id"] == ecu["id"]
    # An explicit point that fits needs no change at all.
    chosen = m.create_task(e12["id"], "Injectors", 2000, "hours", point_id=ecu["id"])
    out = m.move_task(chosen["id"], t12["id"])
    assert "measurement_changes" not in out and m._get(chosen["id"], "Task")["point_id"] == ecu["id"]
    _rebuilds_the_same(m)


def test_a_counter_on_the_fitted_item_fits(m):
    t12, e12, t14, e14, h12, h14, task = _trucks(m)
    engine = m.create_item("Engine", serial="E-77")
    m.fit(e12["id"], item_id=engine["id"], on="2026-01-01")
    own = m.add_point(None, "Engine meter", kind="counter", unit="hours", item_id=engine["id"])
    sample = m.create_task(e12["id"], "Oil sample", 250, "hours")
    m.update_task(sample["id"], point_id=own["id"])  # the engine fitted here
    assert m._point_fit(m._get(own["id"], "MeasurementPoint"), t12["id"]) == "fitted item"
    assert m._point_fit(m._get(own["id"], "MeasurementPoint"), t14["id"]) is None
    out = m.move_task(sample["id"], t12["id"])  # fitted below Truck 12: it fits
    assert "measurement_changes" not in out
    with pytest.raises(NeedsChoice):
        m.move_task(sample["id"], t14["id"])


def test_calendar_tasks_and_tasks_with_no_counter_move_as_before(m):
    t12, e12, t14, e14, h12, h14, task = _trucks(m)
    cal = m.create_task(t12["id"], "Wash", 1, "months")
    out = m.move_task(cal["id"], t14["id"])
    assert "measurement_changes" not in out and "task_changes" not in _events(m, "task.moved")[-1]["payload"]
    bare = m.create_position("Trailer")
    km = m.create_task(bare["id"], "Wheel bearings", 20000, "km")  # no km counter anywhere
    m.move_task(km["id"], t14["id"])


# ---- a move that doesn't fit asks ---------------------------------------------------------

def test_a_move_that_doesnt_fit_needs_a_choice(m):
    t12, e12, t14, e14, h12, h14, task = _trucks(m)
    events = m.s.event_count(ORG)
    with pytest.raises(NeedsChoice) as err:
        m.move_task(task["id"], t14["id"])
    assert m.s.event_count(ORG) == events  # nothing written
    assert "Service counts Engine hours on Truck 12, which isn't on Truck 14" in str(err.value)
    choice = err.value.choice
    assert choice["code"] == "measurement_choice" and choice["position"]["name"] == "Truck 14"
    [t] = choice["tasks"]
    assert t["task_id"] == task["id"] and t["unit"] == "hours" and t["fits"] is False
    assert t["measurement"]["id"] == h12["id"] and t["measurement"]["on"]["name"] == "Truck 12"
    assert t["last_done"] == "2026-03-01" and t["last_done_reading"] == 1600
    assert t["suggested_point_id"] == h14["id"]
    [c] = t["choices"]
    assert c["id"] == h14["id"] and c["relation"] == "here" and c["reading"] == 5600
    assert c["at_last_done"] == {"value": 5400.0, "estimated": True}
    # A function moving the task asks the same, before writing anything.
    mode = m.add_failure_mode(t12["id"], "Engine wears")
    m.update_task(task["id"], failure_mode_id=mode["id"])
    with pytest.raises(NeedsChoice):
        m.move_failure_mode(mode["id"], t14["id"])
    assert [p["id"] for p in m.s.inn(ORG, mode["id"], "CAN_FAIL_AS")] == [t12["id"]]


def test_keep_counts_the_old_measurement_anyway(m):
    t12, e12, t14, e14, h12, h14, task = _trucks(m)
    out = m.move_task(task["id"], t14["id"], {"choice": "keep"})
    moved = m._get(task["id"], "Task")
    assert moved["point_id"] == h12["id"] and moved["last_done_reading"] == 1600
    assert out["measurement_changes"] == {task["id"]: {"point_id": h12["id"]}}
    _rebuilds_the_same(m)


def test_switch_with_the_reading_given(m):
    t12, e12, t14, e14, h12, h14, task = _trucks(m)
    m.move_task(task["id"], t14["id"], {task["id"]: {"choice": "switch", "point_id": h14["id"],
                                                     "last_done_reading": 5410}})
    moved = m._get(task["id"], "Task")
    assert moved["point_id"] == h14["id"] and moved["last_done_reading"] == 5410
    assert not moved.get("last_done_reading_estimated")
    view = m._task_view(moved)
    assert view["limits"][0]["due_at_reading"] == 5910 and view["last_done_reading_estimated"] is False
    _rebuilds_the_same(m)


def test_switch_works_the_reading_out_from_the_date(m):
    t12, e12, t14, e14, h12, h14, task = _trucks(m)
    m.move_task(task["id"], t14["id"], {"choice": "switch", "point_id": h14["id"]})
    moved = m._get(task["id"], "Task")
    assert moved["last_done_reading"] == 5400 and moved["last_done_reading_estimated"] is True
    assert m._task_view(moved)["last_done_reading_estimated"] is True
    _rebuilds_the_same(m)
    # Done again: the reading is read, not worked out.
    m.set_last_done(task["id"], "2026-04-01")
    again = m._get(task["id"], "Task")
    assert again["last_done_reading"] == 5600 and again["last_done_reading_estimated"] is False


def test_switch_is_checked(m):
    t12, e12, t14, e14, h12, h14, task = _trucks(m)
    km = m.add_point(t14["id"], "Odometer", kind="counter", unit="km")
    with pytest.raises(Invalid, match="Odometer counts km, but Service goes by hours"):
        m.move_task(task["id"], t14["id"], {"choice": "switch", "point_id": km["id"]})
    elsewhere = m.create_position("Truck 20")
    h20 = m.add_point(elsewhere["id"], "Engine hours", kind="counter", unit="hours")
    with pytest.raises(Invalid, match="isn't on Truck 14, a position above or below it"):
        m.move_task(task["id"], t14["id"], {"choice": "switch", "point_id": h20["id"]})
    with pytest.raises(Invalid, match="Say which measurement"):
        m.move_task(task["id"], t14["id"], {"choice": "switch"})
    with pytest.raises(Invalid, match="A measurement choice is keep, switch"):
        m.move_task(task["id"], t14["id"], {"choice": "guess"})
    with pytest.raises(Invalid, match="isn't moving"):
        m.move_task(task["id"], t14["id"], {"nope": {"choice": "keep"}})


def test_switch_to_calendar_time(m):
    t12, e12, t14, e14, h12, h14, task = _trucks(m)
    with pytest.raises(Invalid, match="how often Service falls due"):
        m.move_task(task["id"], t14["id"], {"choice": "calendar"})
    with pytest.raises(Invalid, match="Calendar time is days"):
        m.move_task(task["id"], t14["id"], {"choice": "calendar", "interval": 5, "unit": "hours"})
    m.move_task(task["id"], t14["id"], {"choice": "calendar", "interval": 6, "unit": "months"})
    moved = m._get(task["id"], "Task")
    assert (moved["unit"], moved["interval"], moved.get("point_id"), moved["last_done_reading"]) == ("months", 6, None, None)
    assert m._task_view(moved)["next_due"] == "2026-09-01"
    _rebuilds_the_same(m)


def test_calendar_replaces_the_limit_by_use_and_keeps_a_calendar_one(m):
    t12, e12, t14, e14, h12, h14, task = _trucks(m)
    both = m.create_task(t12["id"], "Grease", 250, "hours", also_interval=3, also_unit="months")
    m.move_task(both["id"], t14["id"], {"choice": "calendar", "interval": 2, "unit": "months"})
    moved = m._get(both["id"], "Task")
    assert (moved["unit"], moved["interval"], moved["also_unit"], moved["also_interval"]) == ("months", 2, "months", 3)


def test_a_function_move_asks_for_each_task_and_takes_a_choice_each(m):
    t12, e12, t14, e14, h12, h14, task = _trucks(m)
    fn = m.add_function(t12["id"], "Haul ore")
    ff = m.add_functional_failure(fn["id"], "Won't move")
    mode = m.add_failure_mode(t12["id"], "Engine wears", functional_failure_id=ff["id"])
    m.update_task(task["id"], failure_mode_id=mode["id"])
    other = m.create_task(t12["id"], "Filters", 250, "hours")
    m.link_task(other["id"], mode["id"])
    with pytest.raises(NeedsChoice) as err:
        m.move_function(fn["id"], t14["id"])
    assert sorted(t["task_id"] for t in err.value.choice["tasks"]) == sorted([task["id"], other["id"]])
    assert "2 tasks count measurements that aren't on Truck 14" in str(err.value)
    out = m.move_function(fn["id"], t14["id"], {
        task["id"]: {"choice": "switch", "point_id": h14["id"]}, other["id"]: "keep"})
    assert out["measurement_changes"][other["id"]] == {"point_id": h12["id"]}
    assert m._get(task["id"], "Task")["point_id"] == h14["id"]
    [event] = _events(m, "function.moved")
    assert set(event["payload"]["task_changes"]) == {task["id"], other["id"]}
    _rebuilds_the_same(m)


# ---- the event log --------------------------------------------------------------------------

def test_old_move_events_replay_as_before(m):
    """A task.moved written before task_changes existed: re-points the task and
    nothing else, on replay too (as it did then, the task now counts its new
    position's counter)."""
    t12, e12, t14, e14, h12, h14, task = _trucks(m)
    m._emit("task.moved", {"id": task["id"], "position_id": t14["id"], "from_position_id": t12["id"],
                           "on": "2026-10-01"})
    before = m._get(task["id"], "Task")
    assert before.get("point_id") is None and before["last_done_reading"] == 1600
    _rebuilds_the_same(m)
    assert m._get(task["id"], "Task") == before


def test_undo_puts_the_measurement_back(m):
    from backend.maintenance import apply as apply_mod

    t12, e12, t14, e14, h12, h14, task = _trucks(m)
    out = m.move_task(task["id"], t14["id"], {"choice": "switch", "point_id": h14["id"]})
    undo = apply_mod.MOVES["tasks.move"]({"task_id": task["id"]}, out)
    assert undo["args"]["measurement"] == {task["id"]: {
        "choice": "restore", "point_id": None, "last_done_reading": 1600, "last_done_reading_estimated": None}}
    m.move_task(**undo["args"])
    back = m._get(task["id"], "Task")
    assert back.get("point_id") is None and back["last_done_reading"] == 1600
    assert not back.get("last_done_reading_estimated")
    _rebuilds_the_same(m)


# ---- seeing and changing what a task counts -------------------------------------------------

def test_task_measurement_reads_what_it_counts_and_the_choices(m):
    t12, e12, t14, e14, h12, h14, task = _trucks(m)
    ecu = m.add_point(e12["id"], "ECU hours", kind="counter", unit="hours")
    m.add_point(t12["id"], "Odometer", kind="counter", unit="km")
    view = m.task_measurement(task["id"])
    assert view["by_use"] and view["unit"] == "hours" and view["chosen"] is False and view["fits"] is True
    assert view["measurement"]["id"] == h12["id"] and view["measurement"]["reading"] == 1900
    assert [(c["id"], c["relation"]) for c in view["choices"]] == [(h12["id"], "here"), (ecu["id"], "below")]
    there = m.task_measurement(task["id"], t14["id"])
    assert there["fits"] is False and there["position"]["name"] == "Truck 14"
    assert [c["id"] for c in there["choices"]] == [h14["id"]]
    cal = m.create_task(t12["id"], "Wash", 1, "months")
    assert m.task_measurement(cal["id"])["by_use"] is False and m.task_measurement(cal["id"])["choices"] == []


def test_changing_the_measurement_takes_the_last_done_reading_on_the_new_one(m):
    t12, e12, t14, e14, h12, h14, task = _trucks(m)
    ecu = m.add_point(e12["id"], "ECU hours", kind="counter", unit="hours")
    m.record_reading(ecu["id"], 10, on="2026-01-01")
    m.record_reading(ecu["id"], 70, on="2026-03-02")
    m.update_task(task["id"], point_id=ecu["id"])
    t = m._get(task["id"], "Task")
    assert t["point_id"] == ecu["id"] and t["last_done_reading"] == 69 and t["last_done_reading_estimated"] is True
    m.update_task(task["id"], point_id=ecu["id"], last_done_reading=66)
    t = m._get(task["id"], "Task")
    assert t["last_done_reading"] == 66 and t["last_done_reading_estimated"] is False
    # Back to the position's own counter: read there that day.
    m.update_task(task["id"], point_id="")
    t = m._get(task["id"], "Task")
    assert t["point_id"] is None and t["last_done_reading"] == 1600
    with pytest.raises(Invalid, match="isn't on Truck 12, a position above or below it"):
        m.update_task(task["id"], point_id=h14["id"])
    with pytest.raises(Invalid, match="last_done_reading goes with point_id"):
        m.update_task(task["id"], last_done_reading=5)
    _rebuilds_the_same(m)


# ---- over the app's routes and MCP ----------------------------------------------------------

@pytest.fixture()
def api_m(api):  # noqa: F811
    from backend.routers import maintenance as router
    from backend.tests.test_maintenance_rcm_api import UID

    return api, Maintenance(router.get_store(), UID, UID)


def test_the_routes_ask_then_take_a_choice(api_m):
    api, mm = api_m
    t12, e12, t14, e14, h12, h14, task = _trucks(mm)
    r = api.post(f"{M}/tasks/{task['id']}/move", json={"position_id": t14["id"]})
    assert r.status_code == 409 and r.json()["needs_choice"]["tasks"][0]["suggested_point_id"] == h14["id"]
    r = api.get(f"{M}/tasks/{task['id']}/measurement", params={"position_id": t14["id"]})
    assert r.status_code == 200 and r.json()["fits"] is False

    # The RCM tab's batch: 409 with the operation to fill in, then sent again with it.
    ops = [{"do": "tasks.move", "args": {"task_id": task["id"], "position_id": t14["id"]}}]
    r = api.post(f"{M}/rcm/apply", json={"operations": ops, "dry_run": True})
    assert r.status_code == 409 and r.json()["needs_choice"]["op_index"] == 0
    assert r.json()["detail"].startswith("Service counts Engine hours on Truck 12")
    ops[0]["args"]["measurement"] = {"choice": "switch", "point_id": h14["id"], "last_done_reading": 5400}
    r = api.post(f"{M}/rcm/apply", json={"operations": ops})
    assert r.status_code == 200, r.text
    assert mm._get(task["id"], "Task")["point_id"] == h14["id"]
    undo = r.json()["undo"]
    assert undo[0]["args"]["measurement"][task["id"]]["choice"] == "restore"
    r = api.post(f"{M}/rcm/apply", json={"operations": undo})
    assert r.status_code == 200, r.text
    back = mm._get(task["id"], "Task")
    assert back.get("point_id") is None and back["last_done_reading"] == 1600

    r = api.patch(f"{M}/tasks/{task['id']}", json={"point_id": h12["id"], "last_done_reading": 1599})
    assert r.status_code == 200 and r.json()["last_done_reading"] == 1599


@pytest.mark.usefixtures("mcp_on")
def test_mcp_move_says_what_to_choose(env):  # noqa: F811
    from backend.tests.test_maintenance_mcp import _do, _ok, _session

    async def flow(client):
        t12 = _ok(await _do(client, "maintenance_positions", "create", name="Truck 12"))["id"]
        t14 = _ok(await _do(client, "maintenance_positions", "create", name="Truck 14"))["id"]
        await _do(client, "maintenance_measurements", "add_point", position_id=t12, name="Engine hours",
                  kind="counter", unit="hours")
        h14 = _ok(await _do(client, "maintenance_measurements", "add_point", position_id=t14, name="Engine hours",
                            kind="counter", unit="hours"))["id"]
        task = _ok(await _do(client, "maintenance_tasks", "create", position_id=t12, name="Service", interval=500,
                             unit="hours"))["id"]
        asked = await _do(client, "maintenance_tasks", "move", task_id=task, position_id=t14)
        moved = _ok(await _do(client, "maintenance_tasks", "move", task_id=task, position_id=t14,
                              measurement={"choice": "switch", "point_id": h14}))
        return asked, moved, h14

    asked, moved, h14 = _session(env["token"], flow)
    assert asked.is_error and "Say what to count there (measurement)" in asked.content[0].text
    assert h14 in asked.content[0].text
    assert moved["point_id"] == h14



def test_undo_of_a_switch_to_the_calendar_puts_the_limit_by_use_back(m):
    from backend.maintenance import apply as apply_mod

    t12, e12, t14, e14, h12, h14, task = _trucks(m)
    out = m.move_task(task["id"], t14["id"], {"choice": "calendar", "interval": 6, "unit": "months"})
    undo = apply_mod.MOVES["tasks.move"]({"task_id": task["id"]}, out)
    m.move_task(**undo["args"])
    back = m._get(task["id"], "Task")
    assert (back["unit"], back["interval"], back["last_done_reading"]) == ("hours", 500, 1600)
    assert m._task_view(back)["limits"][0]["counter"]["id"] == h12["id"]
    _rebuilds_the_same(m)
