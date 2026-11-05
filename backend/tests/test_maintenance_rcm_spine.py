"""RCM on the maintenance positions: functions and functional failures as graph
nodes (PERFORMS, FAILS_AS, CAUSED_BY), decisions with their evidence on the
failure modes, the "not analysed" flag in the tree, and the evidence check."""

import mongomock
import pytest

from backend.maintenance import rcm_graph
from backend.maintenance.service import PROJECTORS, Invalid, Maintenance
from backend.maintenance.store import GraphStore

ORG = "user-a"


@pytest.fixture()
def m():
    return Maintenance(GraphStore(":memory:", PROJECTORS), ORG, "tester")


@pytest.fixture()
def db():
    from backend.services import samples

    d = mongomock.MongoClient()["rcm_spine"]
    samples.seed_samples(d)
    return d


def _rebuilds_the_same(m):
    before = m.s.snapshot()
    m.s.rebuild()
    assert m.s.snapshot() == before


# ---- the nodes and events --------------------------------------------------------------

def test_functions_failures_and_modes_hang_off_the_position(m):
    pump = m.create_position("Pump A")
    fn = m.add_function(pump["id"], "Pump 50 L/s", "At least 50 L/s at 4 bar")
    ff = m.add_functional_failure(fn["id"], "No flow")
    mode = m.add_failure_mode(pump["id"], "Impeller worn", functional_failure_id=ff["id"])
    loose = m.add_failure_mode(pump["id"], "Motor overheats")
    assert m.s.out(ORG, pump["id"], "PERFORMS")[0]["id"] == fn["id"]
    assert m.s.out(ORG, fn["id"], "FAILS_AS")[0]["id"] == ff["id"]
    assert m.s.out(ORG, ff["id"], "CAUSED_BY")[0]["id"] == mode["id"]

    ws = m.rcm_worksheet(pump["id"], "this")
    [p] = ws["positions"]
    assert [f["text"] for f in p["functions"]] == ["Pump 50 L/s"]
    assert p["functions"][0]["standard"] == "At least 50 L/s at 4 bar"
    assert [x["text"] for x in p["functions"][0]["failures"][0]["modes"]] == ["Impeller worn"]
    assert [x["id"] for x in p["unassigned"]] == [loose["id"]]
    assert p["analysed"] is False  # two modes with no decision

    m.assign_failure_mode(loose["id"], ff["id"])
    assert [x["text"] for x in m.rcm_worksheet(pump["id"], "this")["positions"][0]["functions"][0]["failures"][0]
            ["modes"]] == ["Impeller worn", "Motor overheats"]  # in the order put there
    m.update_function(fn["id"], text="Pump 60 L/s")
    m.update_functional_failure(ff["id"], "No flow at all")
    _rebuilds_the_same(m)


def test_a_functional_failure_or_mode_must_be_on_the_same_position(m):
    a, b = m.create_position("Pump A"), m.create_position("Pump B")
    ff = m.add_functional_failure(m.add_function(a["id"], "Pump")["id"], "No flow")
    with pytest.raises(Invalid):
        m.add_failure_mode(b["id"], "Seal", functional_failure_id=ff["id"])
    mode = m.add_failure_mode(b["id"], "Seal")
    with pytest.raises(Invalid):
        m.assign_failure_mode(mode["id"], ff["id"])
    with pytest.raises(Invalid):
        m.add_function(a["id"], "  ")


def test_decisions_write_tasks_and_keep_the_evidence(m):
    pump = m.create_position("Pump A")
    mode = m.add_failure_mode(pump["id"], "Bearing seizes")
    ev = {"type": "strategy_analysis", "id": "an-1"}
    out = m.decide_failure_mode(mode["id"], "operational", {
        "outcome": "fixed_interval", "task": "Replace bearings", "interval": 6, "interval_unit": "months",
        "notes": "OEM", "evidence": ev})
    d = out["decision"]
    assert d["outcome"] == "fixed_interval" and d["interval"] == 6 and d["interval_unit"] == "months"
    assert d["evidence"] == ev and d["notes"] == "OEM" and out["consequence"] == "operational"
    [task] = m.position(pump["id"])["tasks"]
    assert task["name"] == "Replace bearings" and task["failure_mode"]["id"] == mode["id"]

    # Same decision again: nothing written. A new interval changes the task.
    before = m.s.event_count(ORG)
    m.decide_failure_mode(mode["id"], "operational", {
        "outcome": "fixed_interval", "task": "Replace bearings", "interval": 6, "interval_unit": "months",
        "notes": "OEM", "evidence": ev})
    assert m.s.event_count(ORG) == before
    m.decide_failure_mode(mode["id"], decision={"outcome": "fixed_interval", "task": "Replace bearings",
                                                "interval": 12, "interval_unit": "months", "evidence": ev})
    assert m.position(pump["id"])["tasks"][0]["interval"] == 12

    # Run to failure schedules nothing: the task is retired, the action kept on the mode.
    out = m.decide_failure_mode(mode["id"], decision={"outcome": "rtf", "rtf_basis": "uneconomic",
                                                      "task": "Replace on failure"})
    assert out["decision"]["task"] == "Replace on failure" and out["decision"]["rtf_basis"] == "uneconomic"
    assert m.position(pump["id"])["tasks"] == []
    with pytest.raises(Invalid):
        m.decide_failure_mode(mode["id"], decision={"outcome": "rtf"})  # needs its basis
    with pytest.raises(Invalid):
        m.decide_failure_mode(mode["id"], "explosive")
    assert m.decide_failure_mode(mode["id"], decision=None)["decision"] is None
    _rebuilds_the_same(m)


def test_deleting_keeps_failure_modes_and_their_history(m):
    pump = m.create_position("Pump A")
    fn = m.add_function(pump["id"], "Pump")
    ff = m.add_functional_failure(fn["id"], "No flow")
    mode = m.add_failure_mode(pump["id"], "Impeller worn", functional_failure_id=ff["id"])
    m.decide_failure_mode(mode["id"], "operational", {"outcome": "fixed_interval", "interval": 1,
                                                       "interval_unit": "years"})
    gone = m.remove_function(fn["id"])
    assert gone["failure_modes_unassigned"] == 1
    p = m.rcm_worksheet(pump["id"], "this")["positions"][0]
    assert p["functions"] == [] and [x["id"] for x in p["unassigned"]] == [mode["id"]]
    assert len(m.position(pump["id"])["tasks"]) == 1  # the task stays with its mode

    out = m.retire_failure_mode(mode["id"])
    assert out["task_retired"]
    assert m.position(pump["id"])["failure_modes"] == [] and m.position(pump["id"])["tasks"] == []
    with pytest.raises(Invalid):
        m.update_failure_mode(mode["id"], text="x")
    _rebuilds_the_same(m)


def test_not_analysed_in_the_tree(m):
    plant = m.create_position("Plant")
    pump = m.create_position("Pump", parent_id=plant["id"])
    rows = {r["name"]: r for r in m.tree_rows()["positions"]}
    assert rows["Plant"]["not_analysed"] and rows["Pump"]["not_analysed"]
    pump_row = lambda: {r["name"]: r for r in m.tree_rows()["positions"]}["Pump"]  # noqa: E731
    fn = m.add_function(pump["id"], "Pump water")
    assert pump_row()["not_analysed"]  # a function alone isn't an analysis
    leaks = m.add_functional_failure(fn["id"], "Leaks")
    assert pump_row()["not_analysed"]  # a functional failure with no failure mode
    mode = m.add_failure_mode(pump["id"], "Seal", functional_failure_id=leaks["id"])
    assert pump_row()["not_analysed"]  # a failure mode with no decision
    m.decide_failure_mode(mode["id"], "operational", {"outcome": "redesign"})
    assert "not_analysed" not in pump_row()
    # Every functional failure needs a failure mode, and every failure mode a decision.
    stops = m.add_functional_failure(fn["id"], "Stops")
    assert pump_row()["not_analysed"]
    other = m.add_failure_mode(pump["id"], "Motor trips", functional_failure_id=stops["id"])
    m.decide_failure_mode(other["id"], "operational", {"outcome": "redesign"})
    assert "not_analysed" not in pump_row()
    loose = m.add_failure_mode(pump["id"], "Corrosion")  # under no functional failure
    assert pump_row()["not_analysed"]
    m.decide_failure_mode(loose["id"], "non_operational", {"outcome": "accept"})
    assert "not_analysed" not in pump_row()
    # Plant has no function of its own: still not analysed, whatever is inside it.
    assert {r["name"]: r for r in m.tree_rows()["positions"]}["Plant"]["not_analysed"]


def test_scope_below_walks_the_tree(m):
    plant = m.create_position("Plant")
    pump = m.create_position("Pump", parent_id=plant["id"])
    m.create_position("Motor", parent_id=pump["id"])
    m.add_function(pump["id"], "Pump water")
    ws = m.rcm_worksheet(plant["id"])
    assert [(p["name"], p["depth"]) for p in ws["positions"]] == [("Plant", 0), ("Pump", 1), ("Motor", 2)]
    assert ws["scope"] == "below" and not ws["truncated"]
    assert [p["name"] for p in m.rcm_worksheet(plant["id"], "this")["positions"]] == ["Plant"]
    assert m.rcm_worksheet(plant["id"], limit=2)["truncated"]
    with pytest.raises(Invalid):
        m.rcm_worksheet(plant["id"], "sideways")


def test_copying_a_position_copies_its_rcm(m):
    pump = m.create_position("Pump A")
    ff = m.add_functional_failure(m.add_function(pump["id"], "Pump")["id"], "No flow")
    mode = m.add_failure_mode(pump["id"], "Impeller worn", functional_failure_id=ff["id"])
    m.update_failure_mode(mode["id"], effects="Low flow")
    m.decide_failure_mode(mode["id"], "operational", {"outcome": "rtf", "rtf_basis": "random",
                                                       "evidence": {"type": "model", "id": "m1"}})
    copy = m.copy_position(pump["id"], "Pump B")
    [p] = m.rcm_worksheet(copy["id"], "this")["positions"]
    [cmode] = p["functions"][0]["failures"][0]["modes"]
    assert cmode["text"] == "Impeller worn" and cmode["effects"] == "Low flow"
    assert cmode["decision"]["evidence"] == {"type": "model", "id": "m1"} and cmode["id"] != mode["id"]
    _rebuilds_the_same(m)


# ---- the evidence check on a position ---------------------------------------------------

def test_an_interval_with_no_unit_is_checked_in_the_tasks_unit(m, db):
    """A decision's interval with no unit schedules its task in days (the
    default), so days is the unit checked against the evidence's."""
    from backend.services.samples import SAMPLE_OWNER

    owners = [ORG, SAMPLE_OWNER]
    pid = m.create_position("Bearing")["id"]
    ff = m.add_functional_failure(m.add_function(pid, "Turn")["id"], "Seized")
    mode = m.add_failure_mode(pid, "Bearing fatigue", functional_failure_id=ff["id"])
    decision = {"outcome": "fixed_interval", "interval": 580,
                "evidence": {"type": "strategy_analysis", "id": "sample-strategy-bearing-replacement"}}
    m.decide_failure_mode(mode["id"], "operational", decision)
    graph = rcm_graph.resolve(db, m.rcm_worksheet(pid, "this"), owners)
    [got] = graph["positions"][0]["functions"][0]["failures"][0]["modes"]
    assert got["decision"]["interval_unit"] == "days"
    assert got["decision"]["status"] == "inconclusive" and "Unit mismatch" in got["decision"]["reason"]
    # In the analysis's unit the decision is supported.
    m.decide_failure_mode(mode["id"], decision={**decision, "interval_unit": "hours"})
    graph = rcm_graph.resolve(db, m.rcm_worksheet(pid, "this"), owners)
    [got] = graph["positions"][0]["functions"][0]["failures"][0]["modes"]
    assert got["decision"]["status"] == "supported" and graph["rollup"]["supported"] == 1
    _rebuilds_the_same(m)
