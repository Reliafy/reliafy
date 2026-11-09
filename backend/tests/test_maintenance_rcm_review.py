"""The RCM review's app-side fixes (Nov 2026): a position's rollup counts what's
inside it (a closed row still says what needs doing), a saved decision that
breaks the decision rules needs review and doesn't count as decided, a second
task joins the decision through the same rules, and an agent can use a
calculated interval the way the app's "Use" does."""

import pytest

from backend.maintenance import rcm_decisions, rcm_graph
from backend.maintenance.service import PROJECTORS, Invalid, Maintenance
from backend.maintenance.store import GraphStore
from backend.tests.test_maintenance_mcp import _do, _get, _list, _ok, _session, env  # noqa: F401

ORG = "user-a"


@pytest.fixture()
def m():
    return Maintenance(GraphStore(":memory:", PROJECTORS), ORG, "tester")


def _rebuilds_the_same(m):
    before = m.s.snapshot()
    m.s.rebuild()
    assert m.s.snapshot() == before


def _uav(m):
    """A drone with no RCM of its own: Propulsion (none either) holds two motors,
    each with a decided bearing mode, and one motor holds an ESC with an undecided
    mode; Airframe holds the landing gear with one undecided mode."""
    uav = m.create_position("UAV")
    prop = m.create_position("Propulsion", parent_id=uav["id"])
    ids = {"uav": uav["id"], "prop": prop["id"]}
    for key in ("m1", "m2"):
        motor = m.create_position(f"Motor {key[-1]}", parent_id=prop["id"])
        ids[key] = motor["id"]
        fn = m.add_function(motor["id"], "Turn the propeller")
        ff = m.add_functional_failure(fn["id"], "Doesn't turn")
        mode = m.add_failure_mode(motor["id"], "Bearing wears", functional_failure_id=ff["id"])
        ids[f"{key}_bearing"] = mode["id"]
        m.decide_failure_mode(mode["id"], "operational", {
            "outcome": "on_condition", "task": "Listen to the bearing", "interval": 50, "interval_unit": "hours"})
    esc = m.create_position("ESC 1", parent_id=ids["m1"])
    ids["esc"] = esc["id"]
    ids["esc_mode"] = m.add_failure_mode(esc["id"], "Capacitor dries out")["id"]
    air = m.create_position("Airframe", parent_id=uav["id"])
    gear = m.create_position("Landing gear", parent_id=air["id"])
    ids["air"], ids["gear"] = air["id"], gear["id"]
    ids["gear_mode"] = m.add_failure_mode(gear["id"], "Strut cracks")["id"]
    return ids


def _resolved(m, read):
    return rcm_graph.resolve(None, read, ORG)


# ---- a position's rollup counts what's inside it ---------------------------------------

def test_a_positions_rollup_counts_every_position_inside_it(m):
    ids = _uav(m)
    whole = _resolved(m, m.rcm_all())
    by = {p["id"]: p["rollup"] for p in whole["positions"]}
    # Motor 1 holds the ESC: its rollup counts both, its own only its bearing.
    assert (by[ids["m1"]]["modes"], by[ids["m1"]]["decided"], by[ids["m1"]]["undecided"]) == (2, 1, 1)
    assert by[ids["m1"]]["state"] == "to_decide"
    assert (by[ids["m1"]]["own"]["modes"], by[ids["m1"]]["own"]["undecided"]) == (1, 0)
    assert by[ids["m1"]]["own"]["state"] == "all_decided"
    assert by[ids["m2"]]["state"] == "all_decided"
    # The total counts each mode once.
    assert (whole["rollup"]["modes"], whole["rollup"]["undecided"]) == (4, 2)
    # The parents read with it reach the top, through positions with no RCM of their own.
    assert whole["parents"][ids["m1"]] == ids["prop"] and whole["parents"][ids["prop"]] == ids["uav"]
    assert whole["parents"][ids["uav"]] is None

    # The worksheet below a position (depth first) rolls up the same way, the top included.
    sheet = _resolved(m, m.rcm_worksheet(ids["uav"]))
    by = {p["id"]: p["rollup"] for p in sheet["positions"]}
    assert (by[ids["uav"]]["modes"], by[ids["uav"]]["undecided"], by[ids["uav"]]["own"]["modes"]) == (4, 2, 0)
    assert (by[ids["prop"]]["modes"], by[ids["prop"]]["decided"]) == (3, 2)
    assert (by[ids["air"]]["modes"], by[ids["air"]]["state"]) == (1, "to_decide")
    assert by[ids["esc"]]["modes"] == 1 and sheet["rollup"]["modes"] == 4


# ---- decisions that break the rules need review ---------------------------------------

def test_a_decision_with_no_consequence_needs_review(m):
    ids = _uav(m)
    m.decide_failure_mode(ids["gear_mode"], decision={
        "outcome": "on_condition", "task": "Look for cracks", "interval": 1, "interval_unit": "months"})
    mode = m.rcm_mode(ids["gear_mode"])
    assert mode["needs_review"] is True and "consequence isn't answered" in mode["advice"]
    by = {p["id"]: p["rollup"] for p in _resolved(m, m.rcm_worksheet(ids["air"]))["positions"]}
    assert (by[ids["gear"]]["decided"], by[ids["gear"]]["needs_review"], by[ids["gear"]]["state"]) == (1, 1, "needs_review")
    assert by[ids["air"]]["state"] == "needs_review"
    # Answered: it counts as decided.
    m.decide_failure_mode(ids["gear_mode"], "safety")
    assert "needs_review" not in m.rcm_mode(ids["gear_mode"])
    by = {p["id"]: p["rollup"] for p in _resolved(m, m.rcm_worksheet(ids["air"]))["positions"]}
    assert by[ids["air"]]["state"] == "all_decided"


def test_accept_with_a_task_needs_review_and_the_gaps_list_it(m):
    ids = _uav(m)
    mode = ids["gear_mode"]
    m.decide_failure_mode(mode, "operational", {"outcome": "accept"})
    # An import keeps a task the rules refuse (strict=False), loose; the read flags it.
    m.add_mode_task(mode, "Check freeboard", 120, "days", "on_condition", strict=False)
    read = m.rcm_mode(mode)
    assert read["needs_review"] is True and read["advice"].startswith("Accept stands alone, yet 1 task serves")
    sheet = _resolved(m, m.rcm_worksheet(ids["uav"]))
    gaps = rcm_graph.gaps(sheet)
    assert [r["id"] for r in gaps["needs_review"]] == [mode] and gaps["counts"]["needs_review"] == 1
    assert gaps["needs_review"][0]["advice"] == read["advice"]
    # A nudge (a combination on a cost consequence) is advice, not a fault.
    said, review = rcm_decisions.review("operational", "on_condition", ["on_condition", "fixed_interval"], hidden=False)
    assert "combination" in said and review is False


def test_review_words_for_each_rule():
    assert rcm_decisions.review("safety", "rtf", hidden=False)[1] is True
    assert rcm_decisions.review("operational", "failure_finding", hidden=False)[1] is True
    assert rcm_decisions.review(None, "rtf", hidden=None)[1] is True
    assert rcm_decisions.review("operational", "rtf", hidden=False, tasks=2)[0].startswith(
        "Run to failure stands alone, yet 2 tasks serve")
    assert rcm_decisions.review("operational", "redesign", hidden=False, tasks=1)[1] is True
    assert rcm_decisions.review("operational", "rtf", hidden=False) == (None, False)
    # A hidden mode with no category: words, but nothing to review until it's decided.
    assert rcm_decisions.review(None, None, hidden=True)[1] is False
    assert rcm_decisions.advice("operational", "rtf", hidden=False, tasks=1).startswith("Run to failure")


# ---- add_mode_task goes through the decision rules -----------------------------------------

def test_a_second_task_joins_the_decision_or_is_refused_in_decides_words(m):
    ids = _uav(m)
    bearing = ids["m1_bearing"]
    joined = m.add_mode_task(bearing, "Replace the bearing", 6, "months", "fixed_interval", instructions="Press it out.",
                             start="2027-01-15")
    assert m.s.node(ORG, joined["id"])["first_due"] == "2027-01-15"  # its start kept as it joins
    d = m.rcm_mode(bearing)["decision"]
    assert [o["outcome"] for o in d["outcomes"]] == ["on_condition", "fixed_interval"]
    assert d["outcomes"][0]["task"] == "Listen to the bearing" and d["outcomes"][1]["task"] == "Replace the bearing"
    assert d["tasks"][1]["instructions"] == "Press it out."
    # Failure finding on an evident failure: refused as decide refuses it.
    with pytest.raises(Invalid, match="Failure finding is for hidden failures only"):
        m.add_mode_task(bearing, "Test it", 1, "months", "failure_finding")
    # Accept stands alone: the combination rules' words.
    gear = ids["gear_mode"]
    m.decide_failure_mode(gear, "operational", {"outcome": "accept"})
    with pytest.raises(Invalid, match="rtf and accept stand alone"):
        m.add_mode_task(gear, "Look at the strut", 1, "months", "on_condition")
    with pytest.raises(Invalid, match="Say what kind of task"):
        m.add_mode_task(gear, "Look at the strut", 1, "months")
    assert m.rcm_mode(gear)["tasks"] == []
    # A redesign takes a task beside it (the interim measure).
    m.decide_failure_mode(gear, "operational", {"outcome": "redesign"})
    m.add_mode_task(gear, "Look at the strut", 1, "months", "on_condition")
    assert [o["outcome"] for o in m.rcm_mode(gear)["decision"]["outcomes"]] == ["on_condition", "redesign"]
    assert "needs_review" not in m.rcm_mode(gear)
    # Not decided yet: linked until the decision, as before.
    loose = m.add_mode_task(ids["esc_mode"], "Check the ripple", 6, "months", "on_condition")
    assert m.rcm_mode(ids["esc_mode"])["decision"] is None and m.rcm_mode(ids["esc_mode"])["tasks"][0]["id"] == loose["id"]
    _rebuilds_the_same(m)


# ---- an agent uses a calculated interval -----------------------------------------------------

def test_an_agent_saves_a_calculation_as_evidence(env):  # noqa: F811
    async def flow(client):
        pos = _ok(await _do(client, "maintenance", "positions.create", name="Pump"))["id"]
        mode = _ok(await _do(client, "maintenance", "failure_modes.add", position_id=pos, text="Bearing wears"))["id"]
        _ok(await _do(client, "maintenance", "failure_modes.decide", failure_mode_id=mode, consequence="operational",
                      decision={"outcome": "on_condition", "task": "Vibration check", "interval": 3,
                                "interval_unit": "months"}))
        plain = _ok(await _do(client, "maintenance", "rcm.pf_interval", pf_interval=8, pf_unit="weeks"))
        used = _ok(await _do(client, "maintenance", "rcm.pf_interval", pf_interval=8, pf_unit="weeks",
                             failure_mode_id=mode, save_evidence=True))
        no_mode = await _do(client, "maintenance", "rcm.pf_interval", pf_interval=8, pf_unit="weeks",
                            save_evidence=True)
        ff = await _do(client, "maintenance", "rcm.ff_interval", failure_rate=0.1,
                       target_unavailability=0.01, failure_mode_id=mode, save_evidence=True)
        read = _ok(await _get(client, "failure_mode", mode))
        return plain, used, no_mode, ff, read

    plain, used, no_mode, ff, read = _session(env["token"], flow)
    assert "saved" not in plain
    saved = used["saved"]
    assert (saved["interval"], saved["unit"]) == (4, "weeks") and saved["evidence_linked"] is True
    assert saved["notes_added"].startswith("Interval from the P-F calculator (")
    assert no_mode.is_error and "needs failure_mode_id" in no_mode.content[0].text
    assert ff.is_error and "no failure finding task" in ff.content[0].text
    rcm = read.get("rcm") or read
    decision = rcm["decision"]
    assert decision["evidence"] == {"type": "strategy_analysis", "id": saved["analysis"]["id"]}, decision
    assert decision["interval"] == 4 and decision["interval_unit"] == "weeks"
    assert saved["notes_added"] in rcm["notes"]
    doc = env["db"].strategy_analyses.find_one({"_id": saved["analysis"]["id"]})
    assert doc["kind"] == "on_condition_interval" and doc["inputs"]["pf_interval"] == 8
