"""Step 3 of a failure mode, Nov 2026: what an on-condition or failure-finding
check leads to (on_found, "Then, if found"), and one place for the notes.

on_found is a new optional key: on the single decision it rides in
failure_mode.analysed's open changes dict; on a combination it is a member's key
in failure_mode.outcomes_set. Left out of a decide, it is kept while the kind of
task stays. The decision's own notes (decision_notes) fold into the mode's notes
and rationale: the read merges them (mode_notes), the first save of the notes or
the one-off migration records failure_mode.decision_notes_merged, and
decision.notes on a decide is a deprecated alias that adds to the mode's notes.
Old events replay unchanged."""

import pytest

from backend.maintenance.service import PROJECTORS, Invalid, Maintenance, mode_notes
from backend.maintenance.store import GraphStore, new_id
from backend.tests.test_maintenance_mcp import _do, _get, _ok, _session
from backend.tests.test_maintenance_mcp import env  # noqa: F401
from backend.tests.test_maintenance_rcm_api import api  # noqa: F401

ORG = "user-found"
ON_CONDITION = {"outcome": "on_condition", "task": "Vibration check", "interval": 1, "interval_unit": "months",
                "on_found": "Replace the bearing within 2 weeks"}
COMBO = {"outcomes": [
    {"outcome": "on_condition", "task": "Vibration check", "interval": 1, "interval_unit": "months",
     "on_found": "Plan the bearing change"},
    {"outcome": "fixed_interval", "task": "Replace the bearing", "interval": 24, "interval_unit": "months"},
]}


@pytest.fixture()
def m():
    return Maintenance(GraphStore(":memory:", PROJECTORS), ORG, "tester")


def _mode(m, text="Bearing worn"):
    pump = m.create_position("Pump")
    return pump, m.add_failure_mode(pump["id"], text)


def _types(m):
    return [e["type"] for e in m.s.log.since(0, 10_000)]


def _rebuilds_the_same(m):
    before = m.s.snapshot()
    m.s.rebuild()
    assert m.s.snapshot() == before


def _legacy_notes(m, mode_id, notes="", decision_notes="Chosen after the 2025 vibration survey"):
    """A failure mode as the app wrote it before Nov 2026: decision notes of its own."""
    changes = {"decision_notes": decision_notes} | ({"notes": notes} if notes else {})
    m._emit("failure_mode.analysed", {"id": mode_id, "changes": changes})


# ---- on_found ---------------------------------------------------------------------

def test_on_found_on_a_single_decision_round_trips_and_is_kept_when_left_out(m):
    pump, fm = _mode(m)
    d = m.decide_failure_mode(fm["id"], "operational", ON_CONDITION)["decision"]
    assert d["on_found"] == "Replace the bearing within 2 weeks"
    ev = [e for e in m.s.log.since(0, 1000) if e["type"] == "failure_mode.analysed"][-2]
    assert ev["payload"]["changes"]["on_found"] == "Replace the bearing within 2 weeks"
    # Left out: kept (an older caller sending the decision back without it).
    again = {k: v for k, v in ON_CONDITION.items() if k != "on_found"} | {"interval": 2}
    assert m.decide_failure_mode(fm["id"], decision=again)["decision"]["on_found"].startswith("Replace")
    # The worksheet read too.
    [p] = m.rcm_worksheet(pump["id"], "this")["positions"]
    assert p["unassigned"][0]["decision"]["on_found"] == "Replace the bearing within 2 weeks"
    # "" clears it; another kind of task drops it.
    assert "on_found" not in m.decide_failure_mode(fm["id"], decision=again | {"on_found": ""})["decision"]
    m.decide_failure_mode(fm["id"], decision=ON_CONDITION)
    fixed = {"outcome": "fixed_interval", "task": "Replace the bearing", "interval": 24, "interval_unit": "months"}
    assert "on_found" not in m.decide_failure_mode(fm["id"], decision=fixed)["decision"]
    assert not m.s.node(ORG, fm["id"]).get("on_found")
    _rebuilds_the_same(m)


def test_on_found_only_goes_with_a_check(m):
    _, fm = _mode(m)
    with pytest.raises(Invalid, match="on_found .* goes with an on_condition or failure_finding task"):
        m.decide_failure_mode(fm["id"], "operational", {"outcome": "fixed_interval", "task": "Replace", "interval": 3,
                                                         "interval_unit": "months", "on_found": "Nothing"})
    with pytest.raises(Invalid, match="keep it to 500"):
        m.decide_failure_mode(fm["id"], "operational", ON_CONDITION | {"on_found": "x" * 501})
    assert m.rcm_mode(fm["id"])["decision"] is None


def test_on_found_on_a_combinations_members(m):
    _, fm = _mode(m)
    d = m.decide_failure_mode(fm["id"], "safety", COMBO)["decision"]
    assert [o.get("on_found") for o in d["outcomes"]] == ["Plan the bearing change", None]
    assert "on_found" not in d  # each member's, not the decision's
    [ev] = [e for e in m.s.log.since(0, 1000) if e["type"] == "failure_mode.outcomes_set"]
    assert ev["payload"]["outcomes"][0]["on_found"] == "Plan the bearing change"
    assert "on_found" not in ev["payload"]["outcomes"][1]
    # Sent back by task (as the app does) without on_found: kept per member.
    back = {"outcomes": [{"outcome": o["outcome"], "task_id": o["task_id"]} for o in d["outcomes"]]}
    count = len(_types(m))
    assert m.decide_failure_mode(fm["id"], decision=back)["decision"]["outcomes"][0]["on_found"] == \
        "Plan the bearing change"
    assert len(_types(m)) == count  # nothing changed, nothing written
    back["outcomes"][0]["on_found"] = "Replace it this shift"
    d = m.decide_failure_mode(fm["id"], decision=back)["decision"]
    assert d["outcomes"][0]["on_found"] == "Replace it this shift"
    # Back to one task of that kind: the member's on_found becomes the decision's.
    one = {"outcomes": [{"outcome": "on_condition", "task_id": d["outcomes"][0]["task_id"]}]}
    single = m.decide_failure_mode(fm["id"], decision=one)["decision"]
    assert single["on_found"] == "Replace it this shift" and "outcomes" not in single
    _rebuilds_the_same(m)


def test_a_copy_carries_on_found(m):
    pump, fm = _mode(m)
    m.decide_failure_mode(fm["id"], "operational", ON_CONDITION)
    other, combo = _mode(m, "Seal leaks")
    m.decide_failure_mode(combo["id"], "safety", COMBO)
    copy = m.copy_position(pump["id"], "Pump 2")
    [p] = m.rcm_worksheet(copy["id"], "this")["positions"]
    assert p["unassigned"][0]["decision"]["on_found"] == "Replace the bearing within 2 weeks"
    copy2 = m.copy_position(other["id"], "Pump 3")
    [p2] = m.rcm_worksheet(copy2["id"], "this")["positions"]
    assert p2["unassigned"][0]["decision"]["outcomes"][0]["on_found"] == "Plan the bearing change"
    _rebuilds_the_same(m)


# ---- one notes box ----------------------------------------------------------------

def test_the_read_merges_old_decision_notes_into_the_modes_notes(m):
    _, alone = _mode(m)
    _, both = _mode(m, "Seal leaks")
    m.decide_failure_mode(alone["id"], "operational", {"outcome": "rtf", "rtf_basis": "random"})
    m.decide_failure_mode(both["id"], "operational", {"outcome": "rtf", "rtf_basis": "random"})
    _legacy_notes(m, alone["id"])
    _legacy_notes(m, both["id"], notes="Seen on pumps 2 and 4")
    one = m.rcm_mode(alone["id"])
    assert one["notes"] == "Chosen after the 2025 vibration survey" == one["decision"]["notes"]
    two = m.rcm_mode(both["id"])
    assert two["notes"] == "Seen on pumps 2 and 4\n\nDecision\n\nChosen after the 2025 vibration survey"
    assert two["decision"]["notes"] == two["notes"]  # old readers of the decision read the merged text
    assert mode_notes("A", "") == "A" and mode_notes("", "") == "" and mode_notes(two["notes"], "Chosen after the "
                                                                                 "2025 vibration survey") == two["notes"]

    count = len(_types(m))
    m.update_failure_mode(both["id"], notes=two["notes"])  # saved as read: nothing to do
    assert len(_types(m)) == count
    m.update_failure_mode(both["id"], notes=two["notes"] + "\nChecked 2026.")
    assert _types(m)[-1] == "failure_mode.decision_notes_merged"
    node = m.s.node(ORG, both["id"])
    assert node["decision_notes"] == "" and node["notes"].endswith("Checked 2026.")
    assert m.rcm_mode(both["id"])["notes"] == node["notes"]
    m.update_failure_mode(both["id"], notes="Just this")  # from now on, plain notes
    assert _types(m)[-1] == "failure_mode.analysed" and m.rcm_mode(both["id"])["notes"] == "Just this"
    _rebuilds_the_same(m)


def test_decision_notes_is_an_alias_that_adds_to_the_modes_notes(m):
    _, fm = _mode(m)
    m.update_failure_mode(fm["id"], notes="Seen on pumps 2 and 4")
    rtf = {"outcome": "rtf", "rtf_basis": "random"}
    out = m.decide_failure_mode(fm["id"], "operational", rtf | {"notes": "Random: the model says so"})
    assert out["notes"] == "Seen on pumps 2 and 4\n\nRandom: the model says so" == out["decision"]["notes"]
    assert not m.s.node(ORG, fm["id"]).get("decision_notes")  # never written apart again
    count = len(_types(m))
    m.decide_failure_mode(fm["id"], decision=rtf | {"notes": out["decision"]["notes"]})  # the read sent back
    m.decide_failure_mode(fm["id"], decision=rtf)  # none: the notes stay
    assert len(_types(m)) == count and m.rcm_mode(fm["id"])["notes"] == out["notes"]
    # On a mode with old decision notes, the alias takes them in too.
    _, old = _mode(m, "Seal leaks")
    m.decide_failure_mode(old["id"], "operational", rtf)
    _legacy_notes(m, old["id"], notes="Why")
    m.decide_failure_mode(old["id"], decision=rtf | {"notes": "More"})
    assert _types(m)[-1] == "failure_mode.decision_notes_merged"
    assert m.rcm_mode(old["id"])["notes"] == "Why\n\nDecision\n\nChosen after the 2025 vibration survey\n\nMore"
    # A refused decision writes no notes.
    with pytest.raises(Invalid):
        m.decide_failure_mode(fm["id"], "safety", rtf | {"notes": "Never"})
    assert "Never" not in m.rcm_mode(fm["id"])["notes"]
    _rebuilds_the_same(m)


def test_the_migration_dry_run_then_apply(m):
    _, alone = _mode(m)
    _, both = _mode(m, "Seal leaks")
    _, plain = _mode(m, "Impeller worn")
    _, gone = _mode(m, "Old mode")
    _legacy_notes(m, alone["id"])
    _legacy_notes(m, both["id"], notes="Seen on pumps 2 and 4")
    _legacy_notes(m, gone["id"])
    m.retire_failure_mode(gone["id"])
    m.update_failure_mode(plain["id"], notes="Nothing to merge")
    reads = {i: m.rcm_mode(i)["notes"] for i in (alone["id"], both["id"])}
    count = len(_types(m))

    dry = m.merge_decision_notes()
    assert dry["dry_run"] is True and dry["modes"] == 2
    row = next(r for r in dry["merged"] if r["id"] == both["id"])
    assert row == {"id": both["id"], "text": "Seal leaks", "notes_chars": 21, "decision_notes_chars": 38,
                   "merged_chars": len(reads[both["id"]])}
    assert len(_types(m)) == count  # a dry run writes nothing

    done = m.merge_decision_notes(dry_run=False)
    assert done["modes"] == 2 and _types(m)[-2:] == ["failure_mode.decision_notes_merged"] * 2
    assert {i: m.rcm_mode(i)["notes"] for i in reads} == reads  # nothing a user sees changed
    assert all(m.s.node(ORG, i)["decision_notes"] == "" for i in reads)
    assert m.merge_decision_notes(dry_run=False)["modes"] == 0  # twice: nothing more
    _rebuilds_the_same(m)


def test_the_migration_script_per_organisation():
    from backend.scripts.merge_decision_notes import merge

    store = GraphStore(":memory:", PROJECTORS)
    for org in ("org-a", "org-b"):
        mm = Maintenance(store, org, "tester")
        fm = mm.add_failure_mode(mm.create_position("Pump")["id"], "Bearing worn")
        if org == "org-a":
            _legacy_notes(mm, fm["id"])
    dry = merge(store)
    assert dry["dry_run"] and dry["modes"] == 1 and list(dry["orgs"]) == ["org-a"]
    assert merge(store, "org-a", apply=True)["modes"] == 1
    assert merge(store)["modes"] == 0


def test_the_code_before_the_change_replays_the_new_events_harmlessly(m):
    """Old projectors: the new event type is skipped and the new keys are just fields."""
    _, fm = _mode(m)
    m.decide_failure_mode(fm["id"], "safety", COMBO)
    _legacy_notes(m, fm["id"], notes="Why")
    m.merge_decision_notes(dry_run=False)
    old = GraphStore(":memory:", {k: v for k, v in PROJECTORS.items() if k != "failure_mode.decision_notes_merged"})
    for e in m.s.log.since(0, 10_000):
        old.log.append({"id": new_id(), "org": e["org"], "type": e["type"], "at": "", "actor": None,
                        "payload": e["payload"]})
    old.sync()
    node = old.node(ORG, fm["id"])
    assert node["notes"] == "Why" and node["decision_notes"] == "Chosen after the 2025 vibration survey"


# ---- over the route and the tool --------------------------------------------------

def test_on_found_and_the_notes_alias_over_the_route(api):  # noqa: F811
    M = "/api/maintenance"
    pump = api.post(f"{M}/positions", json={"name": "Pump"}).json()
    mode = api.post(f"{M}/positions/{pump['id']}/failure-modes", json={"text": "Bearing worn"}).json()
    r = api.put(f"{M}/failure-modes/{mode['id']}/decision",
                json={"consequence": "operational", "decision": ON_CONDITION | {"notes": "Why"}})
    assert r.status_code == 200, r.text
    assert r.json()["decision"]["on_found"] == ON_CONDITION["on_found"] and r.json()["notes"] == "Why"
    r = api.put(f"{M}/failure-modes/{mode['id']}/decision", json={"consequence": "safety", "decision": COMBO})
    assert r.json()["decision"]["outcomes"][0]["on_found"] == "Plan the bearing change"
    bad = api.put(f"{M}/failure-modes/{mode['id']}/decision", json={"decision": {
        "outcome": "fixed_interval", "interval": 3, "interval_unit": "months", "on_found": "x"}})
    assert bad.status_code == 422 and "on_found" in bad.text


def test_on_found_over_mcp(env):  # noqa: F811
    async def flow(client):
        pid = _ok(await _do(client, "maintenance", "positions.create", name="Pump"))["id"]
        mode = _ok(await _do(client, "maintenance", "failure_modes.add", position_id=pid, text="Bearing worn"))
        out = _ok(await _do(client, "maintenance", "failure_modes.decide", failure_mode_id=mode["id"],
                            consequence="operational", decision=ON_CONDITION))
        combo = _ok(await _do(client, "maintenance", "failure_modes.decide", failure_mode_id=mode["id"],
                              consequence="safety", decision=COMBO | {"notes": "Neither alone is enough"}))
        return out, combo, _ok(await _get(client, "failure_mode", mode["id"]))

    out, combo, read = _session(env["token"], flow)
    assert out["decision"]["on_found"] == ON_CONDITION["on_found"]
    assert combo["decision"]["outcomes"][0]["on_found"] == "Plan the bearing change"
    assert combo["notes"] == "Neither alone is enough" == combo["decision"]["notes"]
    assert read["decision"]["outcomes"][0]["on_found"] == "Plan the bearing change"


# ---- the export and the import ----------------------------------------------------

def test_the_fmeca_export_writes_on_found_and_the_merged_notes_and_imports_them_again(m):
    from backend.maintenance import fmea_sheet, rcm_sheet

    pump = m.create_position("Pump")
    fn = m.add_function(pump["id"], "Pump 50 L/s")
    ff = m.add_functional_failure(fn["id"], "No flow")
    single = m.add_failure_mode(pump["id"], "Bearing worn", functional_failure_id=ff["id"])
    combo = m.add_failure_mode(pump["id"], "Seal leaks", functional_failure_id=ff["id"])
    m.decide_failure_mode(single["id"], "operational", ON_CONDITION)
    _legacy_notes(m, single["id"], notes="Seen on pumps 2 and 4")
    m.decide_failure_mode(combo["id"], "safety", COMBO)
    rows = fmea_sheet.rows(m.rcm_worksheet(pump["id"], "this"))
    header = rows[0]
    assert header[header.index("Interval unit") + 1] == "On found"
    by_mode = [dict(zip(header, r)) for r in rows[1:]]
    first = next(r for r in by_mode if r["Failure mode"] == "Bearing worn")
    assert first["On found"] == ON_CONDITION["on_found"]
    assert first["Failure mode notes"] == "Seen on pumps 2 and 4\n\nDecision\n\nChosen after the 2025 vibration survey"
    seal = [r for r in by_mode if r["Failure mode"] == "Seal leaks"]
    assert [r["On found"] for r in seal] == ["Plan the bearing change", ""]

    other = m.create_position("Pump 2")["id"]
    table = rcm_sheet.read_table(fmea_sheet.workbook(m.rcm_worksheet(pump["id"], "this")), "Pump FMECA.xlsx")
    opts = rcm_sheet.default_options(table)
    assert opts["mapping"]["on_found"] == "On found"
    out = rcm_sheet.run(m, other, table, opts, dry_run=False)
    assert out["ok"] and out["errors"] == [], out
    modes = {mo["text"]: mo for mo in m.rcm_worksheet(other, "this")["positions"][0]["functions"][0]["failures"][0]["modes"]}
    assert modes["Bearing worn"]["decision"]["on_found"] == ON_CONDITION["on_found"]
    assert modes["Bearing worn"]["notes"] == first["Failure mode notes"]
    assert [o.get("on_found") for o in modes["Seal leaks"]["decision"]["outcomes"]] == ["Plan the bearing change", None]
    _rebuilds_the_same(m)
