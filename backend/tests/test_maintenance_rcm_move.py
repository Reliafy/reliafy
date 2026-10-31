"""Moving RCM between positions: a function (with its functional failures, their
failure modes and those modes' tasks), one failure mode, or one task. The events
re-point PERFORMS, CAN_FAIL_AS and ON, replay to the same graph, and a move that
would split history (failures, findings, work done) is refused, saying what to do."""

import pytest

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


def _rcm(m, position_id):
    return m.rcm_worksheet(position_id, "this")["positions"][0]


def _pump(m, name="Pump A"):
    """A position with a function, two functional failures, a decided mode with a
    task under one, and a mode under none."""
    pump = m.create_position(name)
    fn = m.add_function(pump["id"], "Pump 50 L/s", "At least 50 L/s")
    ff = m.add_functional_failure(fn["id"], "No flow")
    m.add_functional_failure(fn["id"], "Flow below 50 L/s")
    mode = m.add_failure_mode(pump["id"], "Bearing seizes", functional_failure_id=ff["id"])
    m.update_failure_mode(mode["id"], effects="Pump stops", notes="RPN 120")
    m.decide_failure_mode(mode["id"], "operational", {
        "outcome": "fixed_interval", "task": "Replace bearings", "interval": 90, "interval_unit": "days",
        "notes": "From the manual", "evidence": {"type": "model", "id": "some-model"}})
    loose = m.add_failure_mode(pump["id"], "Motor overheats")
    task = m._mode_task(mode["id"])
    return pump, fn, ff, mode, loose, task


# ---- function.moved -----------------------------------------------------------------

def test_a_function_moves_with_its_failures_modes_and_tasks(m):
    pump, fn, ff, mode, loose, task = _pump(m)
    m.set_last_done(task["id"], "2026-01-10")
    other = m.create_position("Pump B")
    m.add_function(other["id"], "Contain the water")
    before = m.rcm_mode(mode["id"])

    out = m.move_function(fn["id"], other["id"])
    assert out["failure_modes_moved"] == 1 and out["tasks_moved"] == 1
    assert out["from_position_id"] == pump["id"] and out["position_id"] == other["id"]

    assert [f["id"] for f in m.s.inn(ORG, fn["id"], "PERFORMS")] == [other["id"]]
    assert [p["id"] for p in m.s.inn(ORG, mode["id"], "CAN_FAIL_AS")] == [other["id"]]
    assert [p["id"] for p in m.s.out(ORG, task["id"], "ON")] == [other["id"]]
    # Ids, the decision with its evidence, effects, notes and the task's dates stay.
    after = m.rcm_mode(mode["id"])
    assert after == before
    assert after["effects"] == "Pump stops" and after["decision"]["evidence"] == {"type": "model", "id": "some-model"}
    moved_task = m._get(task["id"], "Task")
    assert moved_task["last_done"] == "2026-01-10" and moved_task["start"] == task["start"]
    # The function goes after the target's own; the loose mode stays where it was.
    target = _rcm(m, other["id"])
    assert [f["text"] for f in target["functions"]] == ["Contain the water", "Pump 50 L/s"]
    assert [x["text"] for x in target["functions"][1]["failures"]] == ["No flow", "Flow below 50 L/s"]
    assert target["functions"][1]["failures"][0]["modes"][0]["id"] == mode["id"]
    source = _rcm(m, pump["id"])
    assert source["functions"] == [] and [x["id"] for x in source["unassigned"]] == [loose["id"]]

    [event] = _events(m, "function.moved")
    p = event["payload"]
    assert p["failure_mode_ids"] == [mode["id"]] and p["task_ids"] == [task["id"]] and p["on"] == m.today()
    assert event["actor"] == "tester" and event["at"]
    _rebuilds_the_same(m)


def test_a_deleted_mode_under_a_moved_function_stays_behind(m):
    pump, fn, ff, mode, loose, task = _pump(m)
    gone = m.add_failure_mode(pump["id"], "Casing cracks", functional_failure_id=ff["id"])
    m.retire_failure_mode(gone["id"])
    other = m.create_position("Pump B")
    m.move_function(fn["id"], other["id"])
    assert [p["id"] for p in m.s.inn(ORG, gone["id"], "CAN_FAIL_AS")] == [pump["id"]]
    assert m.s.inn(ORG, gone["id"], "CAUSED_BY") == []  # no edge crosses positions
    _rebuilds_the_same(m)


def _again(m, type):
    """Project the latest event of ``type`` a second time: nothing changes."""
    before = m.s.snapshot()
    m.s._conn.execute("BEGIN")
    PROJECTORS[type](m.s, ORG, _events(m, type)[0]["payload"])
    m.s._conn.execute("COMMIT")
    assert m.s.snapshot() == before


@pytest.mark.sqlite_only
def test_the_projectors_are_idempotent(m):
    pump, fn, ff, mode, loose, task = _pump(m)
    other = m.create_position("Pump B")
    m.move_function(fn["id"], other["id"])
    _again(m, "function.moved")
    third = m.create_position("Pump C")
    fn_c = m.add_function(third["id"], "Pump")
    ff_c = m.add_functional_failure(fn_c["id"], "No flow")
    m.move_failure_mode(mode["id"], third["id"], ff_c["id"])
    _again(m, "failure_mode.moved")
    spare = m.create_task(pump["id"], "Check guard", 1, "months")
    m.move_task(spare["id"], other["id"])
    _again(m, "task.moved")
    _rebuilds_the_same(m)


# ---- failure_mode.moved ---------------------------------------------------------------

def test_a_mode_moves_under_a_functional_failure_there_and_a_failure_can_be_closed_against_it(m):
    pump, fn, ff, mode, loose, task = _pump(m)
    other = m.create_position("Pump B")
    fn_b = m.add_function(other["id"], "Pump 20 L/s")
    ff_b = m.add_functional_failure(fn_b["id"], "No flow")
    out = m.move_failure_mode(mode["id"], other["id"], ff_b["id"])
    assert out["position_id"] == other["id"] and out["tasks_moved"] == 1
    assert out["decision"]["task_id"] == task["id"] and out["decision"]["evidence"]["id"] == "some-model"
    assert [x["id"] for x in m.s.inn(ORG, mode["id"], "CAUSED_BY")] == [ff_b["id"]]
    assert [p["id"] for p in m.s.out(ORG, task["id"], "ON")] == [other["id"]]
    assert _rcm(m, pump["id"])["functions"][0]["failures"][0]["modes"] == []

    # A failure closed on the new position names the moved mode.
    m.fit(other["id"], new_item={"name": "P-7"})
    wo = m.open_work_order(other["id"], "Bearing gone", "corrective")
    m.close_work_order(wo["id"], [{"kind": "replace", "failure_mode_id": mode["id"], "new_item": {"name": "P-8"}}])
    ended = [f for f in m.s.inn(ORG, other["id"], "AT") if f["label"] == "Fitment" and f.get("failure_mode_id")]
    assert [f["failure_mode_id"] for f in ended] == [mode["id"]]
    # ...and naming it on the old position says where it went.
    m.fit(pump["id"], new_item={"name": "P-1"})
    with pytest.raises(Invalid, match="That failure mode is on Pump B, not this position"):
        m.remove(pump["id"], reason="failure", failure_mode_id=mode["id"])
    # A task on the new position links to it.
    linked = m.create_task(other["id"], "Listen to bearing", 1, "weeks", failure_mode_id=mode["id"])
    assert m.s.out(ORG, linked["id"], "MITIGATES")[0]["id"] == mode["id"]
    _rebuilds_the_same(m)


def test_a_mode_moves_unassigned(m):
    pump, fn, ff, mode, loose, task = _pump(m)
    other = m.create_position("Pump B")
    m.move_failure_mode(loose["id"], other["id"])
    m.move_failure_mode(mode["id"], other["id"])
    assert m.s.inn(ORG, mode["id"], "CAUSED_BY") == []
    assert {x["id"] for x in _rcm(m, other["id"])["unassigned"]} == {mode["id"], loose["id"]}
    [second, first] = _events(m, "failure_mode.moved")  # newest first
    assert first["payload"]["task_ids"] == [] and second["payload"]["task_ids"] == [task["id"]]
    assert second["payload"]["functional_failure_id"] is None and "order" not in second["payload"]
    _rebuilds_the_same(m)


# ---- task.moved -----------------------------------------------------------------------

def test_a_task_moves(m):
    pump = m.create_position("Pump A")
    other = m.create_position("Pump B")
    task = m.create_task(pump["id"], "Grease", 3, "months", last_done="2026-02-01")
    view = m.move_task(task["id"], other["id"])
    assert view["id"] == task["id"]
    assert [p["id"] for p in m.s.out(ORG, task["id"], "ON")] == [other["id"]]
    assert m._get(task["id"], "Task")["last_done"] == "2026-02-01"
    # Back again is fine too.
    m.move_task(task["id"], pump["id"])
    assert len(_events(m, "task.moved")) == 2
    _rebuilds_the_same(m)


def test_a_task_keeps_its_link_only_when_the_mode_is_on_the_target(m):
    pump = m.create_position("Pump A")
    other = m.create_position("Pump B")
    mode = m.add_failure_mode(pump["id"], "Seal leaks")
    task = m.create_task(pump["id"], "Check seal", 1, "months", failure_mode_id=mode["id"])
    m.retire_task(task["id"])
    m.move_failure_mode(mode["id"], other["id"])
    assert [p["id"] for p in m.s.out(ORG, task["id"], "ON")] == [pump["id"]]  # retired: stays
    late = m.create_task(other["id"], "Look at seal", 1, "weeks", failure_mode_id=mode["id"])
    with pytest.raises(Invalid, match="Look at seal prevents the failure mode Seal leaks, which stays on Pump B"):
        m.move_task(late["id"], pump["id"])
    _rebuilds_the_same(m)


@pytest.mark.sqlite_only
def test_a_task_left_pointing_at_a_mode_on_the_target_keeps_the_link(m):
    pump = m.create_position("Pump A")
    other = m.create_position("Pump B")
    mode = m.add_failure_mode(other["id"], "Seal leaks")
    task = m.create_task(pump["id"], "Check seal", 1, "months")
    m.s.put_edge(ORG, "MITIGATES", task["id"], mode["id"])  # as data from before moves could leave it
    m.move_task(task["id"], other["id"])
    assert m.s.out(ORG, task["id"], "MITIGATES")[0]["id"] == mode["id"]


# ---- every refusal --------------------------------------------------------------------

def test_the_target_must_be_a_live_other_position_here(m):
    pump, fn, ff, mode, loose, task = _pump(m)
    retired = m.create_position("Old pump")
    m.retire_position(retired["id"])
    elsewhere = Maintenance(m.s, "user-b", "b").create_position("Their pump")
    for move, thing in ((m.move_function, fn["id"]), (m.move_failure_mode, mode["id"]), (m.move_task, task["id"])):
        with pytest.raises(Invalid, match="Say which position"):
            move(thing, None)
        with pytest.raises(Invalid, match="no position with that id in this workspace"):
            move(thing, "nope")
        with pytest.raises(Invalid, match="no position with that id in this workspace"):
            move(thing, elsewhere["id"])
        with pytest.raises(Invalid, match="Old pump has been retired"):
            move(thing, retired["id"])
        with pytest.raises(Invalid, match="already on Pump A"):
            move(thing, pump["id"])
    assert not any(_events(m, t) for t in ("function.moved", "failure_mode.moved", "task.moved"))


def test_the_thing_must_be_live(m):
    pump, fn, ff, mode, loose, task = _pump(m)
    other = m.create_position("Pump B")
    dup = m.add_failure_mode(pump["id"], "Seal leaks")
    m.merge_failure_mode(dup["id"], loose["id"])
    with pytest.raises(Invalid, match="merged into another"):
        m.move_failure_mode(dup["id"], other["id"])
    m.retire_failure_mode(mode["id"])  # retires its task too
    with pytest.raises(Invalid, match="was deleted"):
        m.move_failure_mode(mode["id"], other["id"])
    with pytest.raises(Invalid, match="task has been retired"):
        m.move_task(task["id"], other["id"])
    m.remove_function(fn["id"])
    with pytest.raises(Invalid, match="function was deleted"):
        m.move_function(fn["id"], other["id"])
    with pytest.raises(NotFound):
        m.move_task("nope", other["id"])


def test_a_mode_with_failures_findings_or_merges_stays(m):
    pump, fn, ff, mode, loose, task = _pump(m)
    other = m.create_position("Pump B")
    # A failure recorded against it.
    m.fit(pump["id"], new_item={"name": "P-1"})
    m.remove(pump["id"], reason="failure", failure_mode_id=mode["id"])
    with pytest.raises(Invalid, match="1 failure at Pump A is recorded against Bearing seizes.*add the failure "
                                      "mode on Pump B instead"):
        m.move_failure_mode(mode["id"], other["id"])
    with pytest.raises(Invalid, match="recorded against Bearing seizes"):
        m.move_function(fn["id"], other["id"])
    # Voided, it no longer counts.
    [fitment] = [f for f in m.s.inn(ORG, pump["id"], "AT") if f["label"] == "Fitment"]
    m.void_fitment(fitment["id"], "wrong pump")
    # An inspection's finding.
    seal = m.add_failure_mode(pump["id"], "Seal leaks")
    m.fit(pump["id"], new_item={"name": "P-2"})
    wo = m.open_work_order(pump["id"], "Look at it", "inspection")
    m.close_work_order(wo["id"], [{"kind": "inspect", "finding": "degraded", "failure_mode_id": seal["id"]}])
    with pytest.raises(Invalid, match="Inspections at Pump A found Seal leaks"):
        m.move_failure_mode(seal["id"], other["id"])
    # Another mode merged into it.
    dup = m.add_failure_mode(pump["id"], "Motor too hot")
    m.merge_failure_mode(dup["id"], loose["id"])
    with pytest.raises(Invalid, match="were merged into Motor overheats"):
        m.move_failure_mode(loose["id"], other["id"])
    # The voided failure no longer holds the decided mode back.
    m.move_failure_mode(mode["id"], other["id"])
    _rebuilds_the_same(m)


def test_a_mode_the_target_already_has_stays(m):
    pump, fn, ff, mode, loose, task = _pump(m)
    other = m.create_position("Pump B")
    m.add_failure_mode(other["id"], "bearing  SEIZES")
    with pytest.raises(Invalid, match="Pump B already has the failure mode bearing  SEIZES: rename one"):
        m.move_failure_mode(mode["id"], other["id"])
    with pytest.raises(Invalid, match="already has the failure mode"):
        m.move_function(fn["id"], other["id"])


def test_the_functional_failure_must_be_on_the_target(m):
    pump, fn, ff, mode, loose, task = _pump(m)
    other = m.create_position("Pump B")
    with pytest.raises(Invalid, match="That functional failure is on Pump A, not Pump B"):
        m.move_failure_mode(loose["id"], other["id"], ff["id"])
    m.remove_functional_failure(ff["id"])
    with pytest.raises(Invalid, match="functional failure was deleted"):
        m.move_failure_mode(loose["id"], other["id"], ff["id"])


def test_a_task_with_work_stays(m):
    pump = m.create_position("Pump A")
    other = m.create_position("Pump B")
    task = m.create_task(pump["id"], "Grease", 3, "months")
    wo = m.open_work_order(pump["id"], "Grease it", "preventive", task_id=task["id"])
    with pytest.raises(Invalid, match=r"Grease has an open work order \(#\d+\): close or cancel it first"):
        m.move_task(task["id"], other["id"])
    m.cancel_work_order(wo["id"], "Not needed")
    m.move_task(task["id"], other["id"])  # a cancelled work order is no history
    done = m.open_work_order(other["id"], "Grease it", "preventive", task_id=task["id"])
    m.close_work_order(done["id"], [])
    with pytest.raises(Invalid, match="Work has been done on Grease at Pump B .*Retire it and add a new task on "
                                      "Pump A instead"):
        m.move_task(task["id"], pump["id"])


def test_a_mode_whose_task_has_work_stays(m):
    pump, fn, ff, mode, loose, task = _pump(m)
    other = m.create_position("Pump B")
    m.open_work_order(pump["id"], "Replace bearings", "preventive", task_id=task["id"])
    with pytest.raises(Invalid, match="open work order"):
        m.move_failure_mode(mode["id"], other["id"])
    with pytest.raises(Invalid, match="open work order"):
        m.move_function(fn["id"], other["id"])


# What a task by use counts through a move: test_maintenance_task_measurement.py.


def test_a_task_for_a_mode_staying_behind_is_refused_not_unlinked(m):
    pump = m.create_position("Pump A")
    other = m.create_position("Pump B")
    mode = m.add_failure_mode(pump["id"], "Seal leaks")
    task = m.create_task(pump["id"], "Check seal", 1, "months", failure_mode_id=mode["id"])
    with pytest.raises(Invalid, match="Check seal prevents the failure mode Seal leaks, which stays on Pump A: move "
                                      "the failure mode instead"):
        m.move_task(task["id"], other["id"])
    m.update_task(task["id"], failure_mode_id="")
    m.move_task(task["id"], other["id"])
    assert m.s.out(ORG, task["id"], "MITIGATES") == []


def test_only_a_positions_task_moves(m):
    other = m.create_position("Pump B")
    item = m.create_item("Hoist", serial="H1")
    on_item = m.create_task(None, "Certify", 12, "months", item_id=item["id"])
    with pytest.raises(Invalid, match="Only a position's task moves"):
        m.move_task(on_item["id"], other["id"])
