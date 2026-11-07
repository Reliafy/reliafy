"""A combination of tasks checked against its evidence member by member: each
scheduled member needs evidence that supports its own outcome (a degradation
model for an on-condition task, a replacement analysis for a fixed-interval
one, a report or a function's notes for any). The decision's evidence counts
for every member it fits; a member may link its own (outcomes[i].evidence,
carried in failure_mode.outcomes_set's payload as an optional key). Then one
status for the whole: supported, linked, partly, unevidenced, or the worst
member's."""

from types import SimpleNamespace

import mongomock
import pytest

from backend.config import SAMPLE_OWNER
from backend.maintenance import rcm_decisions, rcm_graph
from backend.maintenance.service import PROJECTORS, Invalid, Maintenance
from backend.maintenance.store import GraphStore
from backend.services import access

ORG = "user-ce"

DEGRADATION = SimpleNamespace(id="dm1", name="Bearing vibration", status="ready",
                              results={"threshold": 7.1, "measurement_unit": "mm/s"})
REPLACEMENT = SimpleNamespace(id="sa1", name="Bearing replacement", kind="optimal_replacement",
                              results={"beneficial": True, "optimal_time": 20, "savings": 0.3, "unit": "months"})
NOT_WORTH_IT = SimpleNamespace(id="sa2", name="Not worth it", kind="optimal_replacement",
                               results={"beneficial": False, "unit": "months"})
FINDING = SimpleNamespace(id="sa3", name="Alarm test", kind="failure_finding",
                          results={"interval": 6, "unit": "months", "target_availability": 0.99})
ARTIFACTS = {("degradation_model", "dm1"): DEGRADATION, ("strategy_analysis", "sa1"): REPLACEMENT,
             ("strategy_analysis", "sa2"): NOT_WORTH_IT, ("strategy_analysis", "sa3"): FINDING,
             ("report", "r1"): SimpleNamespace(id="r1", name="Bearing case")}


def fetch(etype, eid):
    return ARTIFACTS.get((etype, eid))


OC = {"outcome": "on_condition", "task": "Vibration check", "interval": 1, "interval_unit": "months"}
FI = {"outcome": "fixed_interval", "task": "Replace the bearing", "interval": 24, "interval_unit": "months"}
DM = {"type": "degradation_model", "id": "dm1"}
SA = {"type": "strategy_analysis", "id": "sa1"}


def _check(outcomes, evidence=None):
    return rcm_decisions.resolve_decision({"outcome": outcomes[0]["outcome"], "evidence": evidence,
                                           "outcomes": outcomes}, fetch)


# ---- the check ------------------------------------------------------------------------------

def test_each_member_supported_is_supported():
    out = _check([{**OC, "evidence": DM}, {**FI, "evidence": SA}])
    assert out["status"] == "supported"
    assert [(o["outcome"], o["status"], o["evidence_from"]) for o in out["outcomes"]] == [
        ("on_condition", "supported", "own"), ("fixed_interval", "supported", "own")]
    assert out["summary"].startswith("Evidenced for each task.")


def test_one_piece_for_one_member_is_partly_evidenced_in_plain_words():
    # A degradation model fits the inspection, not the replacement: that one has none.
    out = _check([OC, FI], evidence=DM)
    assert out["status"] == "partly"
    assert out["reason"] == "Partly evidenced: the fixed-interval task has none."
    assert [o["status"] for o in out["outcomes"]] == ["supported", "unevidenced"]
    assert out["outcomes"][0]["evidence_from"] == "decision"
    assert "for another of its tasks" in out["outcomes"][1]["reason"]
    # The chip opens the evidence there is.
    assert out["artifact_name"] == "Bearing vibration"
    three = _check([OC, FI, {"outcome": "failure_finding", "interval": 6, "interval_unit": "months"}], evidence=DM)
    assert three["reason"] == "Partly evidenced: the fixed-interval and failure-finding tasks have none."


def test_per_member_evidence_with_the_decisions_as_the_fallback():
    out = _check([OC, {**FI, "evidence": SA}], evidence=DM)
    assert out["status"] == "supported"
    assert [o["evidence_from"] for o in out["outcomes"]] == ["decision", "own"]
    # A replacement analysis doesn't fit a failure-finding task, nor the reverse.
    ff = {"outcome": "failure_finding", "interval": 6, "interval_unit": "months"}
    assert _check([FI, ff], evidence=SA)["status"] == "partly"
    assert _check([FI, {**ff, "evidence": {"type": "strategy_analysis", "id": "sa3"}}], evidence=SA)["status"] == \
        "supported"


def test_a_report_or_notes_fit_every_member_and_read_as_linked():
    out = _check([OC, FI], evidence={"type": "report", "id": "r1"})
    assert out["status"] == "linked" and [o["status"] for o in out["outcomes"]] == ["linked", "linked"]
    # Checked and linked together: linked (only part of it is checked).
    assert _check([{**OC, "evidence": DM}, FI], evidence={"type": "report", "id": "r1"})["status"] == "linked"


def test_the_worst_member_decides_and_is_named():
    out = _check([{**OC, "evidence": DM}, {**FI, "evidence": {"type": "strategy_analysis", "id": "sa2"}}])
    assert out["status"] == "contradicted" and out["reason"].startswith("Fixed-interval task:")
    assert out["artifact_name"] == "Not worth it"
    gone = _check([{**OC, "evidence": {"type": "degradation_model", "id": "gone"}}, {**FI, "evidence": SA}])
    assert gone["status"] == "stale" and gone["reason"].startswith("On-condition task:")
    # A member's own evidence of the wrong kind is inconclusive (it was linked for it).
    wrong = _check([{**OC, "evidence": SA}, {**FI, "evidence": SA}])
    assert wrong["status"] == "inconclusive"


def test_nothing_linked_is_unevidenced_and_a_redesign_needs_none():
    assert _check([OC, FI])["status"] == "unevidenced"
    out = _check([OC, {"outcome": "redesign"}], evidence=DM)
    assert out["status"] == "supported" and out["outcomes"][1]["status"] is None


def test_a_plain_decision_is_checked_as_before():
    plain = {"outcome": "on_condition", "interval": 1, "interval_unit": "months", "evidence": DM}
    assert rcm_decisions.resolve_decision(plain, fetch)["status"] == "supported"
    assert "outcomes" not in rcm_decisions.resolve_decision(plain, fetch)


# ---- on the tree -----------------------------------------------------------------------------

@pytest.fixture()
def m():
    return Maintenance(GraphStore(":memory:", PROJECTORS), ORG, "tester")


@pytest.fixture()
def db():
    d = mongomock.MongoClient()["rcm_combination_evidence"]
    d.reports.insert_one({"_id": "r1", "owner_id": ORG, "name": "Bearing case"})
    return d


def _rebuilds_the_same(m):
    before = m.s.snapshot()
    m.s.rebuild()
    assert m.s.snapshot() == before


def _setup(m):
    pid = m.create_position("Pump")["id"]
    fn = m.add_function(pid, "Pump water", "50 L/s", notes="Vibration trend: 4 mm/s alarm, 7 mm/s trip.")
    mode = m.add_failure_mode(pid, "Bearing worn")
    return pid, fn, mode


def test_member_evidence_is_kept_read_back_checked_and_rebuilt(m, db):
    pid, fn, mode = _setup(m)
    working = {"type": "working", "id": fn["id"]}
    d = m.decide_failure_mode(mode["id"], "safety", {"outcomes": [
        {**OC, "evidence": working}, FI], "evidence": {"type": "report", "id": "r1"}})["decision"]
    assert d["outcomes"][0]["evidence"] == working and "evidence" not in d["outcomes"][1]
    assert d["evidence"] == {"type": "report", "id": "r1"}
    [ev] = [e for e in m.s.events(ORG, 500) if e["type"] == "failure_mode.outcomes_set"]
    assert ev["payload"]["outcomes"][0]["evidence"] == working and "evidence" not in ev["payload"]["outcomes"][1]
    # The read hands the member's working to the check.
    read = m.rcm_mode(mode["id"])["decision"]
    assert read["outcomes"][0]["working"]["id"] == fn["id"]
    out = rcm_graph.mode_status(db, m.rcm_mode(mode["id"]), [ORG, SAMPLE_OWNER])["decision"]
    assert out["status"] == "linked"
    assert [(o["evidence_kind"], o["evidence_from"]) for o in out["outcomes"]] == [("working", "own"),
                                                                                  ("report", "decision")]
    # Deciding the same again changes nothing; a member's evidence changing is one event.
    n = m.s.event_count(ORG)
    m.decide_failure_mode(mode["id"], "safety", {"outcomes": [{**OC, "evidence": working}, FI],
                                                 "evidence": {"type": "report", "id": "r1"}})
    assert m.s.event_count(ORG) == n
    m.decide_failure_mode(mode["id"], "safety", {"outcomes": [OC, FI], "evidence": {"type": "report", "id": "r1"}})
    assert m.s.event_count(ORG) == n + 1
    assert all("evidence" not in o for o in m.rcm_mode(mode["id"])["decision"]["outcomes"])
    _rebuilds_the_same(m)


def test_the_worksheet_rolls_up_a_partly_evidenced_combination(m, db):
    pid, fn, mode = _setup(m)
    m.decide_failure_mode(mode["id"], "safety", {"outcomes": [{**OC, "evidence": {"type": "report", "id": "r1"}},
                                                              FI]})
    sheet = rcm_graph.resolve(db, m.rcm_worksheet(pid, "this"), [ORG])
    [md] = sheet["positions"][0]["unassigned"]
    assert md["decision"]["status"] == "partly"
    assert md["decision"]["reason"] == "Partly evidenced: the fixed-interval task has none."
    assert sheet["rollup"]["partly"] == 1


def test_member_evidence_is_validated_and_access_checked(m):
    pid, fn, mode = _setup(m)
    with pytest.raises(Invalid, match="Unknown evidence type"):
        m.decide_failure_mode(mode["id"], "safety", {"outcomes": [{**OC, "evidence": {"type": "nope", "id": "x"}},
                                                                  FI]})
    bare = m.add_function(pid, "Seal the shaft")
    with pytest.raises(Invalid, match="no notes and rationale yet"):
        m.decide_failure_mode(mode["id"], "safety", {"outcomes": [OC, {**FI, "evidence": {"type": "working",
                                                                                          "id": bare["id"]}}]})
    # Every member's linked artifact is a reference the writer must be able to open.
    refs = access.refs_of_decision({"evidence": {"type": "model", "id": "m1"}, "outcomes": [
        {"outcome": "on_condition", "evidence": DM}, {"outcome": "fixed_interval", "evidence": SA},
        {"outcome": "failure_finding", "evidence": {"type": "model", "id": "m1"}}]})
    assert refs == [("models", "m1"), ("degradation_models", "dm1"), ("strategy_analyses", "sa1")]


def test_one_member_with_evidence_is_a_plain_decision_with_it(m):
    pid, fn, mode = _setup(m)
    d = m.decide_failure_mode(mode["id"], "safety", {"outcomes": [{**OC, "evidence": DM}]})["decision"]
    assert "outcomes" not in d and d["evidence"] == DM


def test_copying_a_position_keeps_member_evidence(m):
    pid, fn, mode = _setup(m)
    m.decide_failure_mode(mode["id"], "safety", {"outcomes": [OC, {**FI, "evidence": SA}]})
    copy = m.copy_position(pid, "Pump 2")
    [cm] = m.position(copy["id"])["failure_modes"]
    assert m.rcm_mode(cm["id"])["decision"]["outcomes"][1]["evidence"] == SA
    _rebuilds_the_same(m)
