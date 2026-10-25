"""RCM on the maintenance positions: functions and functional failures as graph
nodes (PERFORMS, FAILS_AS, CAUSED_BY), decisions with their evidence on the
failure modes, the "not analysed" flag in the tree, the evidence check (the same
as a study's), and moving RCM studies onto the positions."""

import mongomock
import pytest

from backend.maintenance import rcm_graph, rcm_migrate
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


class _Study:
    def __init__(self, functions, system="Cooling pump", name="Pump RCM", id="study-1", description="",
                 owner_id=ORG, migrated_to=None):
        self.functions, self.system, self.name, self.id = functions, system, name, id
        self.description, self.owner_id, self.migrated_to = description, owner_id, migrated_to


def _pump(extra_mode=False):
    modes = [
        {"id": "m-bearing", "text": "Bearing seizes", "effects": "Pump stops", "consequence": "operational",
         "notes": "FMEA RPN 120",
         "decision": {"outcome": "fixed_interval", "task": "Replace bearings", "interval": 2000,
                      "interval_unit": "hours", "notes": "From the OEM manual",
                      "evidence": {"type": "strategy_analysis", "id": "sample-strategy-bearing-replacement"}}},
        {"id": "m-coupling", "text": "Coupling fails", "consequence": "non_operational",
         "decision": {"outcome": "rtf", "rtf_basis": "random", "task": "Replace on failure",
                      "evidence": {"type": "model", "id": "sample-model-bearings-weibull"}}},
    ]
    if extra_mode:
        modes.append({"id": "m-seal", "text": "Seal leaks", "consequence": "safety", "decision": None})
    return _Study([
        {"id": "fn-pump", "text": "Pump 50 L/s at 4 bar", "standard": "At least 50 L/s", "failures": [
            {"id": "ff-none", "text": "No flow", "modes": modes},
            {"id": "ff-low", "text": "Flow below 50 L/s", "modes": []},
        ]},
        {"id": "fn-contain", "text": "Contain the water", "failures": []},
    ], description="A long note about the pump and the site. " * 3)


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


# ---- studies applied and moved -----------------------------------------------------------

def test_apply_rcm_brings_the_decision_and_evidence(m):
    result = m.position_from_rcm(_pump())
    pid = result["position"]["id"]
    [p] = m.rcm_worksheet(pid, "this")["positions"]
    modes = {x["text"]: x for x in p["unassigned"]}  # not under functional failures until moved
    bearing = modes["Bearing seizes"]
    assert bearing["effects"] == "Pump stops" and bearing["notes"] == "FMEA RPN 120"
    assert bearing["decision"]["evidence"] == {"type": "strategy_analysis",
                                               "id": "sample-strategy-bearing-replacement"}
    assert bearing["decision"]["notes"] == "From the OEM manual"
    assert modes["Coupling fails"]["decision"]["task"] == "Replace on failure"
    before = m.s.event_count(ORG)
    assert m.apply_rcm(pid, _pump())["failure_modes_added"] == 0
    assert m.s.event_count(ORG) == before  # nothing new
    with pytest.raises(Invalid):
        m.apply_rcm(pid, _Study([], migrated_to=pid))


def test_a_study_mode_can_be_edited_once_it_is_on_the_spine(m):
    pid = m.position_from_rcm(_pump())["position"]["id"]
    mode = m.rcm_worksheet(pid, "this")["positions"][0]["unassigned"][0]
    with pytest.raises(Invalid):
        m.update_failure_mode(mode["id"], text="Bearing seized")
    ff = m.add_functional_failure(m.add_function(pid, "Pump")["id"], "No flow")
    m.assign_failure_mode(mode["id"], ff["id"])
    assert m.update_failure_mode(mode["id"], text="Bearing seized")["text"] == "Bearing seized"


def _studies(db, *studies):
    from backend.db import to_doc
    from backend.schema import RcmStudy

    for s in studies:
        db.rcm_studies.insert_one(to_doc(RcmStudy(id=s.id, name=s.name, system=s.system, description=s.description,
                                                   owner_id=s.owner_id, functions=s.functions)))


def test_migration_dry_run_writes_nothing_then_moves_and_is_idempotent(m, db):
    applied = _pump()
    pid = m.position_from_rcm(applied)["position"]["id"]
    later = _pump(extra_mode=True)  # the study gained a mode after it was applied
    never = _Study([{"id": "fn-x", "text": "Heat water", "failures": [
        {"id": "ff-x", "text": "No heat", "modes": [{"id": "m-x", "text": "Element burnt out",
                                                    "consequence": "operational", "decision": None}]}]}],
                   system="Hot water", name="HWS RCM", id="study-2")
    _studies(db, later, never)
    events = m.s.event_count(ORG)

    dry = rcm_migrate.migrate(db, m.s)
    assert m.s.event_count(ORG) == events  # the real log is untouched
    assert all(d.get("migrated_to") is None for d in db.rcm_studies.find({"owner_id": ORG}))
    by_id = {r["study_id"]: r for r in dry}
    types = [t for _, t, _ in by_id["study-1"]["events"]]
    assert types.count("function.added") == 2 and types.count("functional_failure.added") == 2
    assert types.count("failure_mode.added") == 1  # the mode added since
    assert types.count("failure_mode.assigned") == 3
    assert by_id["study-1"]["positions"] == [{"org": ORG, "id": pid, "name": "Cooling pump", "created": False}]
    assert by_id["study-2"]["positions"][0]["created"]
    text = rcm_migrate.report(dry, dry_run=True)
    assert "DRY RUN" in text and "+ function: Pump 50 L/s at 4 bar" in text

    real = rcm_migrate.migrate(db, m.s, dry_run=False)
    assert [t for _, t, _ in {r["study_id"]: r for r in real}["study-1"]["events"]] == types
    p = m.rcm_worksheet(pid, "this")["positions"][0]
    assert [f["text"] for f in p["functions"]] == ["Pump 50 L/s at 4 bar", "Contain the water"]
    assert [x["text"] for x in p["functions"][0]["failures"][0]["modes"]] == [
        "Bearing seizes", "Coupling fails", "Seal leaks"]
    assert p["unassigned"] == []
    # The study's description is the position's operating context (from_rcm put it there; the
    # migration matched it and added nothing), never appended to the description.
    assert m.position(pid)["operating_context"] == applied.description.strip()
    assert "A long note about the pump" not in m.position(pid)["description"]
    assert db.rcm_studies.find_one({"_id": "study-1"})["migrated_to"] == pid
    new = db.rcm_studies.find_one({"_id": "study-2"})["migrated_to"]
    assert m.position(new)["name"] == "Hot water"
    _rebuilds_the_same(m)

    # Twice: the studies are marked and skipped; the graph steps alone change nothing either.
    events = m.s.event_count(ORG)
    again = rcm_migrate.migrate(db, m.s, dry_run=False)
    assert all(r["skipped"] and not r["events"] for r in again if r["owner"] == ORG)
    assert m.s.event_count(ORG) == events
    index = rcm_migrate.applied_index(m.s)
    assert rcm_migrate.migrate_study(m.s, db, later, index)["events"] == []
    assert m.s.event_count(ORG) == events


def test_position_from_rcm_puts_the_study_description_in_the_operating_context(m):
    study = _pump()
    p = m.position_from_rcm(study)["position"]
    assert p["operating_context"] == study.description.strip()
    assert p["description"] == "From the RCM study “Pump RCM”."
    plain = _Study(_pump().functions, id="study-3", name="No context")
    assert m.position_from_rcm(plain)["position"]["operating_context"] == ""
    long = _Study(_pump().functions, id="study-4", description="Runs flat out in the dry season. " * 200)
    made = m.position_from_rcm(long)["position"]
    assert len(made["operating_context"]) <= 4000 and made["operating_context"].endswith("…")


def test_migration_puts_the_study_description_in_the_operating_context_once(m, db):
    study = _pump()
    first = m.create_position("Cooling pump A", description="Centrifugal pump, 50 L/s")
    second = m.create_position("Cooling pump B", description="Centrifugal pump, 50 L/s",
                               operating_context="Standby; started weekly.")
    third = m.create_position("Cooling pump C", description="Centrifugal pump, 50 L/s\n\n" + study.description)
    for p in (first, second, third):
        m.apply_rcm(p["id"], study)  # applying never touches the position's text
    assert m.position(first["id"])["operating_context"] == ""
    _studies(db, study)

    [dry] = rcm_migrate.migrate(db, m.s, study_id=study.id)
    assert [t for _, t, _ in dry["events"]].count("position.updated") == 2  # not the third: it's already there
    assert "position's operating context" in rcm_migrate.report([dry], dry_run=True)
    assert m.position(first["id"])["operating_context"] == ""  # a dry run writes nothing

    rcm_migrate.migrate(db, m.s, study_id=study.id, dry_run=False)
    said = study.description.strip()
    a, b, c = (m.position(p["id"]) for p in (first, second, third))
    assert a["operating_context"] == said and a["description"] == "Centrifugal pump, 50 L/s"
    assert b["operating_context"] == f"Standby; started weekly.\n\n{said}"  # after what was there
    assert c["operating_context"] == ""  # an earlier run put it in the description: matched, not repeated
    _rebuilds_the_same(m)

    # Again: nothing more, whether the study is marked or not.
    events = m.s.event_count(ORG)
    for p in (first, second, third):
        rcm_migrate._context(m, p["id"], study)
    assert m.s.event_count(ORG) == events


def test_a_long_study_description_is_shortened_and_matched_on_a_second_run(m):
    study = _Study(_pump().functions, description="Line one about the load.\nRuns in the heat. " * 120)
    pid = m.create_position("Pump", description="A pump")["id"]
    rcm_migrate._context(m, pid, study)
    got = m.position(pid)["operating_context"]
    assert len(got) <= 4000 and got.endswith("…")
    events = m.s.event_count(ORG)
    rcm_migrate._context(m, pid, study)
    assert m.s.event_count(ORG) == events
    assert rcm_migrate.present("", "anything") and not rcm_migrate.present("Runs at night", "Runs by day")


def test_migration_of_a_sample_applied_in_a_workspace(m, db):
    from backend.db import from_doc
    from backend.schema import RcmStudy

    sample = from_doc(RcmStudy, db.rcm_studies.find_one({"_id": "sample-rcm-truck"}))
    pid = m.position_from_rcm(sample)["position"]["id"]
    [r] = [x for x in rcm_migrate.migrate(db, m.s, dry_run=False) if x["study_id"] == sample.id]
    assert r["positions"][0]["id"] == pid and "marked" not in r
    assert db.rcm_studies.find_one({"_id": sample.id}).get("migrated_to") is None  # samples are never marked
    p = m.rcm_worksheet(pid, "this")["positions"][0]
    assert [f["text"] for f in p["functions"]] == [f["text"] for f in sample.functions]
    assert p["unassigned"] == []


def test_the_evidence_check_matches_the_study(m, db):
    """The same decision and evidence give the same status from a study and from
    its form on the positions (the sample study: supported, contradicted, a
    default action)."""
    from backend.db import from_doc
    from backend.schema import RcmStudy
    from backend.services import rcm as rcm_service
    from backend.services.samples import SAMPLE_OWNER

    owners = [ORG, SAMPLE_OWNER]
    for study in (from_doc(RcmStudy, db.rcm_studies.find_one({"_id": "sample-rcm-truck"})), _pump(True)):
        org_m = Maintenance(m.s, ORG, "tester")
        pid = org_m.position_from_rcm(study)["position"]["id"]
        rcm_migrate.migrate_study(m.s, db, study, rcm_migrate.applied_index(m.s))
        from_study = rcm_service.resolve(db, study, owners)
        graph = rcm_graph.resolve(db, m.rcm_worksheet(pid, "this"), owners)
        want = {mo["text"]: (mo.get("decision") or {}).get("status")
                for fn in from_study["functions"] for f in fn["failures"] for mo in f["modes"]}
        got = {mo["text"]: (mo.get("decision") or {}).get("status")
               for fn in graph["positions"][0]["functions"] for f in fn["failures"] for mo in f["modes"]}
        assert got == want
        assert graph["rollup"] == from_study["rollup"]
        assert {"supported", "contradicted"} <= set(got.values())


def test_the_sample_study_has_each_kind_of_check(m, db):
    from backend.db import from_doc
    from backend.schema import RcmStudy
    from backend.services.samples import SAMPLE_OWNER

    study = from_doc(RcmStudy, db.rcm_studies.find_one({"_id": "sample-rcm-truck"}))
    pid = m.position_from_rcm(study)["position"]["id"]
    rcm_migrate.migrate_study(m.s, db, study, rcm_migrate.applied_index(m.s))
    graph = rcm_graph.resolve(db, m.rcm_worksheet(pid, "this"), [ORG, SAMPLE_OWNER])
    statuses = {mo["decision"]["status"] for fn in graph["positions"][0]["functions"]
                for f in fn["failures"] for mo in f["modes"]}
    assert {"supported", "contradicted"} <= statuses


def test_an_interval_with_no_unit_is_checked_in_the_tasks_unit(m, db):
    """The one place the two differ, on purpose: a study's interval with no unit
    skips the unit check, but on the position the task runs in days (apply_rcm's
    default), so that's the unit checked against the evidence's."""
    from backend.services import rcm as rcm_service
    from backend.services.samples import SAMPLE_OWNER

    study = _Study([{"id": "f", "text": "Turn", "failures": [{"id": "x", "text": "Seized", "modes": [
        {"id": "mo", "text": "Bearing", "consequence": "operational", "decision": {
            "outcome": "fixed_interval", "interval": 580,
            "evidence": {"type": "strategy_analysis", "id": "sample-strategy-bearing-replacement"}}}]}]}])
    pid = m.position_from_rcm(study)["position"]["id"]
    rcm_migrate.migrate_study(m.s, db, study, rcm_migrate.applied_index(m.s))
    owners = [ORG, SAMPLE_OWNER]
    assert rcm_service.resolve(db, study, owners)["rollup"]["supported"] == 1
    graph = rcm_graph.resolve(db, m.rcm_worksheet(pid, "this"), owners)
    [mode] = graph["positions"][0]["functions"][0]["failures"][0]["modes"]
    assert mode["decision"]["interval_unit"] == "days"
    assert mode["decision"]["status"] == "inconclusive" and "Unit mismatch" in mode["decision"]["reason"]
