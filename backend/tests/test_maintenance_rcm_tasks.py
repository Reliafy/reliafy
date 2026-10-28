"""Several tasks for one failure mode, and one task for several: MITIGATES is
many-to-many. The decision's own task stays first; the task owns its interval;
a task on a position may serve modes on positions inside it; retiring, moving,
merging and copying keep a shared task where it belongs. New events only
(task.linked, task.unlinked, failure_mode_ids on task.added): every graph
rebuilds the same, and older code replays what it knows."""

import pytest

from backend.maintenance import rcm_sheet
from backend.maintenance.service import PROJECTORS, Invalid, Maintenance, NotFound, _task_added
from backend.maintenance.store import GraphStore
from backend.services import excel

ORG = "user-a"


@pytest.fixture()
def m():
    return Maintenance(GraphStore(":memory:", PROJECTORS), ORG, "tester")


def _rebuilds_the_same(m):
    before = m.s.snapshot()
    m.s.rebuild()
    assert m.s.snapshot() == before


def _events(m, type):
    return [e for e in m.s.events(ORG, 5000) if e["type"] == type]


def _decision(m, mode_id):
    return m.rcm_mode(mode_id)["decision"]


def _tasks(m, mode_id):
    return [t["name"] for t in (_decision(m, mode_id) or {}).get("tasks", [])]


def _pool(m):
    """A pool with a chlorinator inside it: two chemistry modes on the pool (one
    decided with a task), one on the chlorinator."""
    pool = m.create_position("Pool")
    cell = m.create_position("Chlorinator cell", parent_id=pool["id"])
    fn = m.add_function(pool["id"], "Keep the water balanced", "pH 7.2-7.8")
    ff = m.add_functional_failure(fn["id"], "pH above 7.8")
    acid = m.add_failure_mode(pool["id"], "Acid under-dosed", functional_failure_id=ff["id"])
    cya = m.add_failure_mode(pool["id"], "Stabiliser low", functional_failure_id=ff["id"])
    salt = m.add_failure_mode(cell["id"], "Salinity low")
    m.decide_failure_mode(acid["id"], "operational", {
        "outcome": "on_condition", "task": "Weekly pH check", "interval": 1, "interval_unit": "weeks"})
    return pool, cell, acid, cya, salt


# ---- several tasks for one mode -----------------------------------------------------

def test_a_mode_may_have_several_tasks_its_decisions_first(m):
    pool, cell, acid, cya, salt = _pool(m)
    own = _decision(m, acid["id"])["task_id"]
    second = m.add_mode_task(acid["id"], "Replace the acid pump at its rated life", 24, "months", "fixed_interval",
                             instructions="Swap the pump head.")
    assert second["source"] == "rcm" and second["failure_modes"] == [{"id": acid["id"], "text": "Acid under-dosed"}]
    d = _decision(m, acid["id"])
    assert d["task_id"] == own and d["task"] == "Weekly pH check" and d["interval"] == 1
    assert [(t["name"], t["interval"], t["unit"], t["outcome"], t["shared_with"]) for t in d["tasks"]] == [
        ("Weekly pH check", 1, "weeks", "on_condition", 0),
        ("Replace the acid pump at its rated life", 24, "months", "fixed_interval", 0)]
    assert d["tasks"][1]["instructions"] == "Swap the pump head."
    # The decision's own task is recorded on the mode, so a later task never takes its place.
    assert m.s.node(ORG, acid["id"])["task_id"] == own
    assert any(e["payload"]["changes"] == {"task_id": own} for e in _events(m, "failure_mode.analysed"))
    # The bulk read says the same.
    [p] = [p for p in m.rcm_all()["positions"] if p["id"] == pool["id"]]
    mode = p["functions"][0]["failures"][0]["modes"][0]
    assert [t["name"] for t in mode["decision"]["tasks"]] == ["Weekly pH check", "Replace the acid pump at its rated life"]
    # A mode not decided yet lists the tasks linked to it all the same.
    m.link_task(own, cya["id"])
    undecided = m.rcm_mode(cya["id"])
    assert undecided["decision"] is None and [t["name"] for t in undecided["tasks"]] == ["Weekly pH check"]
    assert undecided["tasks"][0]["shared_with"] == 1
    m.unlink_task(own, cya["id"])
    # Without an outcome of its own, the second task takes the decision's when that schedules work.
    third = m.add_mode_task(acid["id"], "Look at the dosing line", 1, "months")
    assert third["outcome"] == "on_condition"
    with pytest.raises(Invalid):
        m.add_mode_task(acid["id"], "", 1, "months")
    with pytest.raises(Invalid):
        m.add_mode_task(acid["id"], "x", 0, "months")
    with pytest.raises(Invalid):
        m.add_mode_task(acid["id"], "x", 1, "months", "sideways")
    _rebuilds_the_same(m)


def test_a_decision_that_schedules_nothing_drops_every_task_of_the_mode(m):
    pool, cell, acid, cya, salt = _pool(m)
    m.add_mode_task(acid["id"], "Replace the acid pump", 24, "months")
    shared = m.add_mode_task(cya["id"], "Monthly shop water test", 1, "months")
    m.link_task(shared["id"], acid["id"])
    out = m.decide_failure_mode(acid["id"], decision={"outcome": "rtf", "rtf_basis": "uneconomic", "task": "Fix on failure"})
    assert out["decision"]["task"] == "Fix on failure" and "tasks" not in out["decision"]
    names = {t["name"]: t for t in m.position(pool["id"])["tasks"]}
    assert set(names) == {"Monthly shop water test"}  # the shared task stays, serving the other mode
    assert names["Monthly shop water test"]["failure_modes"] == [{"id": cya["id"], "text": "Stabiliser low"}]
    assert len(_events(m, "task.unlinked")) == 1 and len(_events(m, "task.retired")) == 2
    _rebuilds_the_same(m)


# ---- one task for several modes -----------------------------------------------------

def test_one_task_serves_several_modes_and_keeps_its_own_interval(m):
    pool, cell, acid, cya, salt = _pool(m)
    task = m._mode_task(acid["id"])
    linked = m.link_task(task["id"], cya["id"])
    assert [x["text"] for x in linked["failure_modes"]] == ["Acid under-dosed", "Stabiliser low"]
    assert linked["failure_mode"]["text"] == "Acid under-dosed"
    assert m.link_task(task["id"], cya["id"]) == linked and len(_events(m, "task.linked")) == 1  # once
    assert _decision(m, acid["id"])["tasks"][0]["shared_with"] == 1
    # The mode it was linked to has no decision yet: deciding it with that task adopts it.
    out = m.decide_failure_mode(cya["id"], "operational", {"outcome": "on_condition"}, task_id=task["id"])
    assert out["decision"]["task_id"] == task["id"] and out["decision"]["interval"] == 1
    assert out["decision"]["interval_unit"] == "weeks" and out["decision"]["task"] == "Weekly pH check"
    # A shared task's interval and name change on the task, for every mode: not from one decision.
    with pytest.raises(Invalid, match="also serves 1 other failure mode"):
        m.decide_failure_mode(cya["id"], decision={"outcome": "on_condition", "task": "Weekly pH check",
                                                   "interval": 2, "interval_unit": "weeks"})
    with pytest.raises(Invalid, match="changed on the task itself"):
        m.decide_failure_mode(cya["id"], decision={"outcome": "on_condition", "task": "Fortnightly pH check",
                                                   "interval": 1, "interval_unit": "weeks"})
    # The same values, or another outcome: the decision changes, the task doesn't.
    before = len(_events(m, "task.updated"))
    out = m.decide_failure_mode(cya["id"], decision={"outcome": "fixed_interval", "task": "Weekly pH check",
                                                     "interval": 1, "interval_unit": "weeks"})
    assert out["decision"]["outcome"] == "fixed_interval" and len(_events(m, "task.updated")) == before
    assert m._get(task["id"], "Task")["outcome"] == "on_condition"
    m.update_task(task["id"], interval=2)
    assert _decision(m, acid["id"])["interval"] == 2 and _decision(m, cya["id"])["interval"] == 2
    # Taking one mode off: that mode keeps its decision, with no task to do it.
    m.unlink_task(task["id"], cya["id"])
    d = _decision(m, cya["id"])
    assert d["outcome"] == "fixed_interval" and "task_id" not in d and "tasks" not in d
    [p] = m.rcm_worksheet(pool["id"], "this")["positions"]
    assert p["functions"][0]["failures"][0]["covered"]  # both modes decided: a missing task is no gate
    _rebuilds_the_same(m)


def test_the_roll_up_counts_modes_with_a_task_and_scheduled_ones_without(m):
    pool, cell, acid, cya, salt = _pool(m)
    task = m._mode_task(acid["id"])
    m.decide_failure_mode(cya["id"], "operational", {"outcome": "on_condition"}, task_id=task["id"])
    [p] = m.rcm_worksheet(pool["id"], "this")["positions"]
    ff = p["functions"][0]["failures"][0]
    assert ff["covered"] and p["analysed"]
    m.unlink_task(task["id"], cya["id"])
    index = m._rcm_index()
    from backend.maintenance.service import _rcm_rollup

    roll = _rcm_rollup(index, {acid["id"], cya["id"]})
    assert roll["modes"] == 2 and roll["tasks"] == 1 and roll["scheduled_without_task"] == 1
    assert m.rcm_worksheet(pool["id"], "this")["positions"][0]["analysed"]  # shown, never a gate


def test_a_task_serves_modes_on_its_position_and_inside_it_never_above(m):
    pool, cell, acid, cya, salt = _pool(m)
    task = m._mode_task(acid["id"])
    # The pool's weekly check also covers the chlorinator's salinity (inside the pool).
    m.link_task(task["id"], salt["id"])
    assert [x["text"] for x in m._task_view(m._get(task["id"], "Task"))["failure_modes"]] == [
        "Acid under-dosed", "Salinity low"]
    choices = m.mode_tasks(salt["id"])
    assert [t["name"] for t in choices["tasks"]] == ["Weekly pH check"]
    other = m.create_task(pool["id"], "Backwash the filter", 1, "months")
    choices = m.mode_tasks(salt["id"])
    assert [(t["name"], t["position"]["name"], t["serves"]) for t in choices["available"]] == [("Backwash the filter", "Pool", 0)]
    # Not the other way round: a task on the cell can't serve the pool's modes.
    own = m.create_task(cell["id"], "Clean the cell", 3, "months")
    with pytest.raises(Invalid, match="on a position inside it"):
        m.link_task(own["id"], acid["id"])
    with pytest.raises(Invalid, match="on a position inside it"):
        m.create_task(cell["id"], "Another", 3, "months", failure_mode_ids=[acid["id"]])
    with pytest.raises(Invalid, match="on a position inside it"):
        m.decide_failure_mode(acid["id"], decision={"outcome": "on_condition"}, task_id=own["id"])
    # A sibling's task can't either; an item's or a location's task never prevents a mode.
    other_pool = m.create_position("Other pool")
    sib = m.create_task(other_pool["id"], "Other", 1, "months")
    with pytest.raises(Invalid):
        m.link_task(sib["id"], acid["id"])
    place = m.create_location("Plant room")
    walk = m.create_task(None, "Walk round", 1, "weeks", location_id=place["id"])
    with pytest.raises(Invalid, match="only a position's task"):
        m.link_task(walk["id"], acid["id"])
    with pytest.raises(NotFound):
        m.link_task(task["id"], "nope")
    with pytest.raises(Invalid):
        m.link_task(task["id"], None)
    m.retire_task(own["id"])
    with pytest.raises(Invalid, match="retired"):
        m.link_task(own["id"], salt["id"])
    _rebuilds_the_same(m)


def test_create_task_links_several_modes_and_update_sets_the_only_link(m):
    pool, cell, acid, cya, salt = _pool(m)
    made = m.create_task(pool["id"], "Monthly shop water test", 1, "months", failure_mode_ids=[cya["id"], salt["id"]],
                         failure_mode_id=acid["id"])
    assert [x["text"] for x in made["failure_modes"]] == ["Acid under-dosed", "Salinity low", "Stabiliser low"]
    [e] = [e for e in _events(m, "task.added") if e["payload"]["id"] == made["id"]]
    assert e["payload"]["failure_mode_id"] == acid["id"]
    assert e["payload"]["failure_mode_ids"] == [acid["id"], cya["id"], salt["id"]]
    # update's failure_mode_id is "the only link", as it always was.
    only = m.update_task(made["id"], failure_mode_id=cya["id"])
    assert only["failure_modes"] == [{"id": cya["id"], "text": "Stabiliser low"}]
    assert m.update_task(made["id"], failure_mode_id="")["failure_modes"] == []
    with pytest.raises(Invalid):
        m.create_task(pool["id"], "x", 1, "months", failure_mode_ids="not-a-list")
    with pytest.raises(Invalid):
        m.create_task(pool["id"], "x", 1, "months", failure_mode_ids=["nope"])
    _rebuilds_the_same(m)


# ---- retire, restore, merge --------------------------------------------------------

def test_retiring_a_mode_retires_its_own_tasks_and_unlinks_shared_ones(m):
    pool, cell, acid, cya, salt = _pool(m)
    own = m._mode_task(acid["id"])
    shared = m.add_mode_task(cya["id"], "Monthly shop water test", 1, "months")
    m.link_task(shared["id"], acid["id"])
    out = m.retire_failure_mode(acid["id"])
    assert out["task_retired"] == own["id"] and out["tasks_retired"] == [own["id"]]
    assert out["tasks_unlinked"] == [shared["id"]]
    live = {t["name"]: t for t in m.position(pool["id"])["tasks"]}
    assert set(live) == {"Monthly shop water test"}
    assert live["Monthly shop water test"]["failure_modes"] == [{"id": cya["id"], "text": "Stabiliser low"}]
    # Restored: its own task comes back; the shared one isn't linked again (it serves the other mode as before).
    back = m.restore_failure_mode(acid["id"])
    assert back["tasks_restored"] == [own["id"]] and _tasks(m, acid["id"]) == ["Weekly pH check"]
    _rebuilds_the_same(m)


def test_merging_moves_every_task_link_across(m):
    pool, cell, acid, cya, salt = _pool(m)
    shared = m.add_mode_task(cya["id"], "Monthly shop water test", 1, "months")
    m.link_task(shared["id"], acid["id"])
    m.merge_failure_mode(cya["id"], acid["id"])
    assert _tasks(m, acid["id"]) == ["Weekly pH check", "Monthly shop water test"]
    assert m._task_view(m._get(shared["id"], "Task"))["failure_modes"] == [{"id": acid["id"], "text": "Acid under-dosed"}]
    _rebuilds_the_same(m)


# ---- moving -------------------------------------------------------------------------

def test_moving_a_mode_takes_its_own_tasks_and_leaves_a_shared_one_where_it_can_still_reach(m):
    pool, cell, acid, cya, salt = _pool(m)
    own = m._mode_task(acid["id"])
    shared = m.add_mode_task(cya["id"], "Monthly shop water test", 1, "months")
    m.link_task(shared["id"], acid["id"])
    # Into the cell (inside the pool): the own task moves; the shared one stays on the pool and still serves it.
    out = m.move_failure_mode(acid["id"], cell["id"])
    assert out["tasks_moved"] == 1 and out["tasks_unlinked"] == [] and "note" not in out
    assert m._task_view(m._get(own["id"], "Task"))["subject"]["id"] == cell["id"]
    assert m._task_view(m._get(shared["id"], "Task"))["subject"]["id"] == pool["id"]
    assert _tasks(m, acid["id"]) == ["Weekly pH check", "Monthly shop water test"]
    # Out to another pool: the shared task can't reach it from here, so that link goes, and the move says so.
    other = m.create_position("Other pool")
    out = m.move_failure_mode(acid["id"], other["id"])
    assert out["tasks_moved"] == 1 and out["tasks_unlinked"] == [shared["id"]]
    assert "Monthly shop water test stays behind" in out["note"]
    assert _tasks(m, acid["id"]) == ["Weekly pH check"]
    assert m._task_view(m._get(shared["id"], "Task"))["failure_modes"] == [{"id": cya["id"], "text": "Stabiliser low"}]
    _rebuilds_the_same(m)


def test_moving_a_function_moves_tasks_that_serve_only_its_modes(m):
    pool, cell, acid, cya, salt = _pool(m)
    fn = m.rcm_worksheet(pool["id"], "this")["positions"][0]["functions"][0]
    shared = m.add_mode_task(cya["id"], "Monthly shop water test", 1, "months")
    m.link_task(shared["id"], acid["id"])
    m.link_task(shared["id"], salt["id"])  # the cell's mode too: it stays on the pool, not under the function
    other = m.create_position("Other pool")
    out = m.move_function(fn["id"], other["id"])
    assert out["failure_modes_moved"] == 2 and out["tasks_moved"] == 1 and out["tasks_unlinked"] == [shared["id"]]
    assert m._task_view(m._get(shared["id"], "Task"))["failure_modes"] == [{"id": salt["id"], "text": "Salinity low"}]
    assert _tasks(m, acid["id"]) == ["Weekly pH check"] and _tasks(m, cya["id"]) == []
    _rebuilds_the_same(m)


def test_a_task_moves_to_a_position_above_the_modes_it_serves(m):
    pool, cell, acid, cya, salt = _pool(m)
    task = m.create_task(cell["id"], "Clean the cell", 3, "months", failure_mode_ids=[salt["id"]])
    moved = m.move_task(task["id"], pool["id"])  # the pool is above the cell: the link stands
    assert moved["subject"]["id"] == pool["id"] and moved["failure_modes"] == [{"id": salt["id"], "text": "Salinity low"}]
    other = m.create_position("Other pool")
    with pytest.raises(Invalid, match="stays on Pool"):
        m.move_task(task["id"], other["id"])
    _rebuilds_the_same(m)


# ---- copying ------------------------------------------------------------------------

def test_copying_keeps_every_link_and_the_decisions_own_task(m):
    pool, cell, acid, cya, salt = _pool(m)
    own = m._mode_task(acid["id"])
    shared = m.add_mode_task(cya["id"], "Monthly shop water test", 1, "months")
    m.link_task(shared["id"], acid["id"])
    m.link_task(shared["id"], salt["id"])  # a mode on the cell, inside the pool
    copy = m.copy_position(pool["id"], "Pool B")
    [p] = m.rcm_worksheet(copy["id"], "this")["positions"]
    modes = {x["text"]: x for x in p["functions"][0]["failures"][0]["modes"]}
    acid2, cya2 = modes["Acid under-dosed"], modes["Stabiliser low"]
    assert [t["name"] for t in acid2["decision"]["tasks"]] == ["Weekly pH check", "Monthly shop water test"]
    assert acid2["decision"]["task_id"] != own["id"] and m.s.node(ORG, acid2["id"])["task_id"] == acid2["decision"]["task_id"]
    assert cya2["decision"] is None
    [shared2] = [t for t in m.position(copy["id"])["tasks"] if t["name"] == "Monthly shop water test"]
    assert sorted(x["text"] for x in shared2["failure_modes"]) == ["Acid under-dosed", "Salinity low", "Stabiliser low"]
    assert shared2["id"] != shared["id"]
    assert _events(m, "task.linked")[0]["payload"]["id"] == shared2["id"]  # newest: the cell's mode, made later
    _rebuilds_the_same(m)


# ---- older code ---------------------------------------------------------------------

def test_older_code_replays_the_one_link_it_knows_and_passes_over_the_rest(tmp_path):
    path = str(tmp_path / "g.sqlite")
    m = Maintenance(GraphStore(path, PROJECTORS), ORG, "tester")
    pool, cell, acid, cya, salt = _pool(m)
    task = m._mode_task(acid["id"])
    m.link_task(task["id"], cya["id"])
    made = m.create_task(pool["id"], "Monthly shop water test", 1, "months", failure_mode_ids=[cya["id"], salt["id"]])
    m.unlink_task(task["id"], acid["id"])

    def old_task_added(s, org, p):  # the projector before failure_mode_ids
        s.put_node(org, p["id"], "Task", {"name": p["name"], "outcome": p.get("outcome"), "interval": p["interval"],
                                          "unit": p["unit"], "start": p["start"], "last_done": None})
        s.put_edge(org, "ON", p["id"], p["position_id"])
        if p.get("failure_mode_id"):
            s.put_edge(org, "MITIGATES", p["id"], p["failure_mode_id"])
    older = {k: v for k, v in PROJECTORS.items() if k not in ("task.linked", "task.unlinked")}
    older["task.added"] = old_task_added
    m.s._conn.close()
    old = GraphStore(path, older)  # the same log, read by the code before these events
    old.rebuild()
    assert PROJECTORS["task.added"] is _task_added
    # The one link each task.added names, no more; the links and unlinks passed over.
    assert [x["id"] for x in old.out(ORG, task["id"], "MITIGATES")] == [acid["id"]]
    assert [x["id"] for x in old.out(ORG, made["id"], "MITIGATES")] == [cya["id"]]
    assert [x["why"] for x in old.skipped()] == ["UnknownEvent in task.linked", "UnknownEvent in task.unlinked"]


# ---- the worksheet ------------------------------------------------------------------

HEADER = ["Function", "Performance standard", "Functional failure", "Failure mode", "Consequence", "Decision",
          "Task", "Interval", "Interval unit"]
OPTIONS = {"mapping": {"function": "Function", "standard": "Performance standard", "failure": "Functional failure",
                       "mode": "Failure mode", "consequence": "Consequence", "outcome": "Decision", "task": "Task",
                       "interval": "Interval", "interval_unit": "Interval unit"}}


def _sheet(rows):
    text = ",".join(HEADER) + "\n" + "\n".join(",".join(r) for r in rows) + "\n"
    return excel.read_csv(text.encode(), "rcm.csv")


ROWS = [
    ["Keep the water balanced", "pH 7.2-7.8", "pH above 7.8", "Acid under-dosed", "Operational", "On-condition",
     "Weekly pH check", "1", "weeks"],
    ["", "", "", "Acid under-dosed", "", "Fixed interval", "Replace the acid pump", "24", "months"],
    ["", "", "", "Stabiliser low", "Operational", "On-condition", "Monthly shop water test", "1", "months"],
    ["", "", "pH below 7.2", "Chlorinator drives pH up", "Operational", "On-condition", "Monthly shop water test",
     "1", "months"],
]


def test_a_repeated_row_is_another_task_and_a_repeated_name_is_one_shared_task(m):
    pid = m.create_position("Pool")["id"]
    out = rcm_sheet.run(m, pid, _sheet(ROWS), OPTIONS, dry_run=True)
    assert out["ok"] and out["errors"] == [] and not any("repeat" in w for w in out["warnings"])
    assert (out["counts"]["modes"], out["counts"]["tasks"], out["counts"]["tasks_linked"]) == (3, 3, 1)
    assert m.s.event_count(ORG) == 1  # a dry run writes nothing
    out = rcm_sheet.run(m, pid, _sheet(ROWS), OPTIONS, dry_run=False)
    assert out["ok"]
    [p] = m.rcm_worksheet(pid, "this")["positions"]
    modes = {x["text"]: x for fail in p["functions"][0]["failures"] for x in fail["modes"]}
    assert [t["name"] for t in modes["Acid under-dosed"]["decision"]["tasks"]] == ["Weekly pH check", "Replace the acid pump"]
    assert modes["Acid under-dosed"]["decision"]["tasks"][1]["outcome"] == "fixed_interval"
    [shop] = [t for t in m.position(pid)["tasks"] if t["name"] == "Monthly shop water test"]
    assert sorted(x["text"] for x in shop["failure_modes"]) == ["Chlorinator drives pH up", "Stabiliser low"]
    assert modes["Chlorinator drives pH up"]["decision"]["task_id"] == shop["id"]
    assert len(m.position(pid)["tasks"]) == 3
    # Again: nothing added, nothing linked twice.
    events = m.s.event_count(ORG)
    again = rcm_sheet.run(m, pid, _sheet(ROWS), OPTIONS, dry_run=False)
    assert again["ok"] and m.s.event_count(ORG) == events and again["counts"]["tasks"] == 0
    _rebuilds_the_same(m)


def test_a_task_the_position_has_is_linked_not_made_again_and_keeps_its_interval(m):
    pid = m.create_position("Pool")["id"]
    have = m.create_task(pid, "Monthly shop water test", 1, "months")
    out = rcm_sheet.run(m, pid, _sheet(ROWS[2:]), OPTIONS, dry_run=False)
    assert out["ok"] and out["counts"]["tasks"] == 0 and out["counts"]["tasks_linked"] == 2
    assert len(m.position(pid)["tasks"]) == 1
    assert len(m._task_view(m._get(have["id"], "Task"))["failure_modes"]) == 2
    # Another interval for a shared task: a row error, nothing written.
    rows = [[*ROWS[2][:7], "2", "weeks"]]
    bad = rcm_sheet.run(m, m.create_position("Pool 2")["id"], _sheet(rows), OPTIONS, dry_run=False)
    assert bad["ok"]  # on Pool 2 there's no such task: it's made
    bad = rcm_sheet.run(m, pid, _sheet([["", "", "", "New mode", "Operational", "On-condition",
                                          "Monthly shop water test", "2", "weeks"]]), OPTIONS, dry_run=False)
    assert not bad["ok"] and "every 1 months; this row says every 2 weeks" in bad["errors"][0]
    rows = [ROWS[2], [*ROWS[3][:7], "3", "months"]]
    bad = rcm_sheet.run(m, m.create_position("Pool 3")["id"], _sheet(rows), OPTIONS, dry_run=False)
    assert not bad["ok"] and "the task row 2 makes" in bad["errors"][0]
    _rebuilds_the_same(m)
