"""A decision's evidence can be a report or the working behind a performance
standard, beside a model or a saved analysis. Those two are linked, not
checked: the evidence check says "linked" (with evidence_kind report or
working) while they're there to open and "stale" once they've gone, never
supported or contradicted. The event is the same failure_mode.analysed with
the same evidence {type, id}, so older events replay as before."""

import mongomock
import pytest

from backend.config import SAMPLE_OWNER

from backend.maintenance import fmea_sheet, rcm_decisions, rcm_graph
from backend.maintenance.service import PROJECTORS, Invalid, Maintenance
from backend.maintenance.store import GraphStore, new_id
from backend.services import access
from backend.tests.test_maintenance_mcp import UID, _do, _get, _list, _ok, _session, env  # noqa: F401
from backend.tests.test_maintenance_rcm_api import api  # noqa: F401 - fixture

ORG = "user-ev"
WORKING = "## Flow\n\n50 L/s = 180 m³/h at the duty point."


@pytest.fixture()
def m():
    return Maintenance(GraphStore(":memory:", PROJECTORS), ORG, "tester")


@pytest.fixture()
def db():
    from backend.services import samples

    d = mongomock.MongoClient()["rcm_evidence_kinds"]
    samples.seed_samples(d)
    d.reports.insert_one({"_id": "r1", "owner_id": ORG, "name": "Pump seal case"})
    d.reports.insert_one({"_id": "theirs", "owner_id": "someone-else", "name": "Not yours"})
    return d


def _pump(m):
    pid = m.create_position("Pump")["id"]
    fn = m.add_function(pid, "Pump water", "50 L/s", standard_basis=WORKING)
    ff = m.add_functional_failure(fn["id"], "No flow")
    modes = [m.add_failure_mode(pid, text, functional_failure_id=ff["id"])["id"] for text in ("Seal", "Bearing", "Impeller")]
    return pid, fn, modes


def _read(db, m, pid):
    sheet = rcm_graph.resolve(db, m.rcm_worksheet(pid, "this"), [ORG, SAMPLE_OWNER])
    return sheet, {md["text"]: md["decision"] for md in sheet["positions"][0]["functions"][0]["failures"][0]["modes"]}


def test_each_kind_decides_reads_and_replays(m, db):
    pid, fn, (seal, bearing, impeller) = _pump(m)
    m.decide_failure_mode(seal, consequence="operational", decision={
        "outcome": "fixed_interval", "interval": 6, "interval_unit": "months", "evidence": {"type": "report", "id": "r1"}})
    m.decide_failure_mode(bearing, decision={"outcome": "accept", "evidence": {"type": "working", "id": fn["id"]}})
    m.decide_failure_mode(impeller, decision={"outcome": "rtf", "rtf_basis": "random",
                                              "evidence": {"type": "model", "id": "sample-model-bearings-weibull"}})
    events = [e["payload"] for e in m.s.log.since(0, 1000) if e["type"] == "failure_mode.analysed"]
    # The same event and the same evidence shape as ever: only the type's vocabulary grew.
    assert {"type": "report", "id": "r1"} in [e["changes"].get("evidence") for e in events]

    owners = [ORG, SAMPLE_OWNER]
    sheet = rcm_graph.resolve(db, m.rcm_worksheet(pid, "this"), owners)
    got = {md["text"]: md["decision"] for md in sheet["positions"][0]["functions"][0]["failures"][0]["modes"]}
    assert got["Seal"]["status"] == "linked" and got["Seal"]["evidence_kind"] == "report"
    assert got["Seal"]["artifact_name"] == "Pump seal case" and got["Seal"]["artifact_link_path"] == "/reports?open=r1"
    assert "doesn't check a report" in got["Seal"]["summary"]
    # A working stands behind any decision, an accepted risk too.
    assert got["Bearing"]["status"] == "linked" and got["Bearing"]["evidence_kind"] == "working"
    assert got["Bearing"]["artifact_name"] == "Pump water"
    assert got["Bearing"]["artifact_link_path"] == f"/asset-register/explorer?tab=rcm&sel={fn['id']}"
    assert got["Bearing"]["working"] == {"id": fn["id"], "text": "Pump water", "position": {"id": pid, "name": "Pump"}}
    # A model keeps its computed verdict.
    assert got["Impeller"]["status"] == "contradicted" and got["Impeller"]["evidence_kind"] == "model"
    # The rollup counts the checked statuses only (a linked one is decided, not checked).
    assert sheet["rollup"]["contradicted"] == 1 and sheet["rollup"]["decided"] == 3 and "linked" not in sheet["rollup"]
    # The gaps' "evidence to check" ignores what's only linked.
    assert [r["text"] for r in rcm_graph.gaps(sheet)["evidence_to_check"]] == ["Impeller"]
    # The one-mode read says the same.
    assert rcm_graph.mode_status(db, m.rcm_mode(bearing), owners)["decision"]["status"] == "linked"

    before = m.s.snapshot()
    m.s.rebuild()
    assert m.s.snapshot() == before


def test_linked_evidence_goes_stale_when_it_goes(m, db):
    pid, fn, (seal, bearing, _) = _pump(m)
    m.decide_failure_mode(seal, decision={"outcome": "redesign", "evidence": {"type": "report", "id": "r1"}})
    m.decide_failure_mode(bearing, decision={"outcome": "redesign", "evidence": {"type": "working", "id": fn["id"]}})
    db.reports.delete_one({"_id": "r1"})
    m.update_function(fn["id"], notes="")  # the working is the function's notes and rationale now
    _, got = _read(db, m, pid)
    assert got["Seal"]["status"] == "stale" and got["Seal"]["reason"] == "The linked report no longer exists."
    assert got["Bearing"]["status"] == "stale" and "working" in got["Bearing"]["reason"]
    assert got["Bearing"]["working"] is None and got["Bearing"]["evidence_kind"] == "working"
    # Still linked, the same decision sent again (its interval changed, say) is kept.
    m.decide_failure_mode(bearing, decision={"outcome": "redesign", "notes": "Later",
                                             "evidence": {"type": "working", "id": fn["id"]}})
    # Someone else's report reads as gone: reports are their owner's only.
    m.decide_failure_mode(seal, decision={"outcome": "redesign", "evidence": {"type": "report", "id": "theirs"}})
    assert _read(db, m, pid)[1]["Seal"]["status"] == "stale"


def test_a_working_must_be_there_to_link(m):
    pid, fn, (seal, *_) = _pump(m)
    plain = m.add_function(pid, "Contain water")
    with pytest.raises(Invalid, match="no notes and rationale yet"):
        m.decide_failure_mode(seal, decision={"outcome": "accept", "evidence": {"type": "working", "id": plain["id"]}})
    with pytest.raises(Invalid, match="no such function here"):
        m.decide_failure_mode(seal, decision={"outcome": "accept", "evidence": {"type": "working", "id": "nope"}})


def test_the_rules_link_the_new_kinds_and_name_what_to_check():
    report = {"outcome": "redesign", "evidence": {"type": "report", "id": "r1"}}
    assert rcm_decisions.clean_decision(report)["evidence"] == {"type": "report", "id": "r1"}
    assert access.refs_of_decision(report) == [("reports", "r1")]
    # A working is on the graph: the tree checks it, not the collections.
    assert access.refs_of_decision({"evidence": {"type": "working", "id": "f1"}}) == []
    assert [rcm_decisions.evidence_kind(t) for t in rcm_decisions.EVIDENCE_TYPES] == [
        "model", "model", "model", "report", "working"]
    # Nothing linked: no kind.
    out = rcm_decisions.resolve_decision({"outcome": "rtf", "rtf_basis": "random"}, lambda *_: None)
    assert out["status"] == "unevidenced" and "evidence_kind" not in out


def test_the_fmea_workbook_names_the_kind(m, db):
    pid, fn, (seal, bearing, _) = _pump(m)
    m.decide_failure_mode(seal, decision={"outcome": "redesign", "evidence": {"type": "report", "id": "r1"}})
    m.decide_failure_mode(bearing, decision={"outcome": "redesign", "evidence": {"type": "working", "id": fn["id"]}})
    sheet, _ = _read(db, m, pid)
    cells = {c for row in fmea_sheet.rows(sheet) for c in row if isinstance(c, str)}
    assert {"Report linked", "Notes linked"} <= cells


def test_over_the_routes_a_report_links_and_someone_elses_is_refused(api):  # noqa: F811
    from backend import db

    from backend.tests.test_maintenance_rcm_api import UID as API_UID

    db._db.reports.insert_one({"_id": "mine", "owner_id": API_UID, "name": "Seal case"})
    db._db.reports.insert_one({"_id": "other", "owner_id": "someone-else", "name": "Theirs"})
    M = "/api/maintenance"
    pump = api.post(f"{M}/positions", json={"name": "Pump"}).json()
    fn = api.post(f"{M}/positions/{pump['id']}/functions",
                  json={"text": "Pump water", "standard": "50 L/s", "standard_basis": WORKING}).json()
    mode = api.post(f"{M}/positions/{pump['id']}/failure-modes", json={"text": "Seal"}).json()
    r = api.put(f"{M}/failure-modes/{mode['id']}/decision",
                json={"decision": {"outcome": "redesign", "evidence": {"type": "report", "id": "mine"}}})
    assert r.status_code == 200, r.text
    assert r.json()["decision"]["status"] == "linked" and r.json()["decision"]["evidence_kind"] == "report"
    bad = api.put(f"{M}/failure-modes/{mode['id']}/decision",
                  json={"decision": {"outcome": "redesign", "evidence": {"type": "report", "id": "other"}}})
    assert bad.status_code == 422 and bad.json()["code"] == "unreadable_reference"
    assert "report" in bad.json()["detail"]
    w = api.put(f"{M}/failure-modes/{mode['id']}/decision",
                json={"decision": {"outcome": "accept", "evidence": {"type": "working", "id": fn["id"]}}})
    assert w.status_code == 200 and w.json()["decision"]["artifact_name"] == "Pump water"
    every = api.get(f"{M}/rcm").json()
    assert every["positions"][0]["unassigned"][0]["decision"]["evidence_kind"] == "working"


def test_over_mcp_decide_takes_a_working_and_the_read_shows_it(env):  # noqa: F811
    env["db"].reports.insert_one({"_id": "rep", "owner_id": UID, "name": "Bearing case"})

    async def go(client):
        pump = _ok(await _do(client, "maintenance", "positions.create", name="Pump"))
        fn = _ok(await _do(client, "maintenance", "failure_modes.add_function", position_id=pump["id"],
                           text="Pump water", standard="50 L/s", standard_basis=WORKING))
        a = _ok(await _do(client, "maintenance", "failure_modes.add", position_id=pump["id"], text="Seal"))
        b = _ok(await _do(client, "maintenance", "failure_modes.add", position_id=pump["id"], text="Bearing"))
        by_working = _ok(await _do(client, "maintenance", "failure_modes.decide", failure_mode_id=a["id"],
                                   decision={"outcome": "accept", "evidence": {"type": "working", "id": fn["id"]}}))
        by_report = _ok(await _do(client, "maintenance", "failure_modes.decide", failure_mode_id=b["id"],
                                  decision={"outcome": "redesign", "evidence": {"type": "report", "id": "rep"}}))
        sheet = _ok(await _get(client, "rcm", pump["id"], scope="this"))
        gaps = _ok(await _list(client, "rcm_gaps"))
        return fn, by_working, by_report, sheet, gaps

    fn, by_working, by_report, sheet, gaps = _session(env["token"], go)
    assert by_working["decision"]["status"] == "linked" and by_working["decision"]["evidence_kind"] == "working"
    assert by_working["decision"]["working"]["id"] == fn["id"]
    assert by_report["decision"]["artifact_name"] == "Bearing case"
    assert {md["decision"]["evidence_kind"] for md in sheet["positions"][0]["unassigned"]} == {"working", "report"}
    assert sheet["rollup"]["decided"] == 2 and gaps["evidence_to_check"] == []


def test_an_old_working_link_still_resolves_and_notes_alone_can_be_linked(m, db):
    """A decision linking a function whose working was written before Nov 2026
    (standard_basis on function.added) resolves through the merged read, before
    and after the migration; a function with notes alone can be linked too."""
    pid = m.create_position("Pump")["id"]
    fid = new_id()
    m._emit("function.added", {"id": fid, "position_id": pid, "text": "Pump water", "standard": "50 L/s", "order": 0,
                               "standard_basis": WORKING, "on": "2026-10-01"})
    ff = m.add_functional_failure(fid, "No flow")
    seal = m.add_failure_mode(pid, "Seal", functional_failure_id=ff["id"])["id"]
    bearing = m.add_failure_mode(pid, "Bearing", functional_failure_id=ff["id"])["id"]
    m.decide_failure_mode(seal, decision={"outcome": "accept", "evidence": {"type": "working", "id": fid}})
    assert _read(db, m, pid)[1]["Seal"]["status"] == "linked"
    m.merge_workings(dry_run=False)
    assert _read(db, m, pid)[1]["Seal"]["status"] == "linked"
    noted = m.add_function(pid, "Contain water", notes="Rated 10 bar: the vendor's sheet")
    m.decide_failure_mode(bearing, decision={"outcome": "accept", "evidence": {"type": "working", "id": noted["id"]}})
    assert m.rcm_mode(bearing)["decision"]["working"]["id"] == noted["id"]
    before = m.s.snapshot()
    m.s.rebuild()
    assert m.s.snapshot() == before
