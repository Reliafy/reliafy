"""FME(C)A on the failure modes of the maintenance tree (backend/maintenance/fmea.py
and the service): the arithmetic by hand (RPN, action priority, criticality),
the field checks, the failure_mode.scored and failure_mode.placed events (a mode
directly under a function, no functional failure between) and what the RCM read,
the gaps, the import, the samples, the routes, MCP and the Excel export make of
them."""

import io

import pytest

from backend.maintenance import fmea, fmea_sheet, rcm_graph, rcm_sheet, templates
from backend.maintenance.service import PROJECTORS, Invalid, Maintenance
from backend.maintenance.store import GraphStore
from backend.tests.test_maintenance_mcp import _do, _get, _list, _ok, _session
from backend.tests.test_maintenance_mcp import env  # noqa: F401
from backend.tests.test_maintenance_rcm_api import api  # noqa: F401

ORG = "user-a"
M = "/api/maintenance"

SCORES = {"severity": 9, "occurrence": 4, "detection": 6, "cause": "Bearing wear from dust", "effect_local": "Stalls",
          "effect_next": "Thrust lost on one arm", "detection_method": "Current trend", "action": "Sealed bearings",
          "action_owner": "Propulsion lead", "action_due": "2026-11-30", "action_status": "open",
          "failure_rate": 2e-5, "time_unit": "hours", "rate_source": "entered", "mode_ratio": 0.6,
          "loss_probability": 1.0, "operating_time": 100, "severity_class": "I"}


@pytest.fixture()
def m():
    return Maintenance(GraphStore(":memory:", PROJECTORS), ORG, "tester")


def _rebuilds_the_same(m):
    before = m.s.snapshot()
    m.s.rebuild()
    assert m.s.snapshot() == before


def _pump(m):
    """A pump with one function and one functional failure."""
    pump = m.create_position("Pump A")
    fn = m.add_function(pump["id"], "Pump 50 L/s")
    ff = m.add_functional_failure(fn["id"], "No flow")
    return pump, fn, ff


def _all_modes(sheet) -> list[dict]:
    return [mo for p in sheet["positions"] for fn in p["functions"]
            for mo in [*fn["modes"], *(x for f in fn["failures"] for x in f["modes"])]] + \
           [mo for p in sheet["positions"] for mo in p["unassigned"]]


# ---- the arithmetic, by hand ------------------------------------------------------------

def test_rpn_action_priority_and_criticality_by_hand():
    assert fmea.rpn(10, 10, 10) == 1000 and fmea.rpn(9, 4, 6) == 216 and fmea.rpn(1, 1, 1) == 1
    assert fmea.rpn(9, None, 6) is None
    cases = {(10, 10, 10): "H", (9, 4, 1): "M", (9, 2, 5): "M", (9, 2, 3): "L", (9, 1, 10): "L", (8, 6, 1): "M",
             (7, 4, 5): "M", (7, 2, 7): "M", (7, 2, 2): "L", (6, 8, 4): "M", (5, 6, 1): "L", (4, 4, 7): "M",
             (3, 8, 6): "M", (3, 8, 2): "L", (2, 6, 10): "L", (1, 10, 10): "L"}
    assert {k: fmea.action_priority(*k) for k in cases} == cases
    assert fmea.action_priority(9, 4, None) is None
    # Every band pair has a row with a priority for every detection band.
    assert all(set(row) == {"d7", "d5", "d2", "d1"} and set(row.values()) <= {"H", "M", "L"}
               for row in fmea.AP_TABLE.values()) and len(fmea.AP_TABLE) == 25
    assert fmea.mode_criticality(1.0, 0.6, 2e-5, 100) == pytest.approx(1.2e-3)
    assert fmea.mode_criticality(0.3, 0.4, 5e-5, 100) == pytest.approx(6e-4)
    assert fmea.mode_criticality(None, 0.4, 5e-5, 100) is None
    assert fmea.item_criticality([1.2e-3, 6e-4, None]) == pytest.approx(1.8e-3) and fmea.item_criticality([]) is None
    options = fmea.options()
    assert options["ap_table"]["s9"]["o2"] == {"d7": "H", "d5": "M", "d2": "L", "d1": "L"}
    assert [b["id"] for b in options["ap_bands"]["severity"]] == ["s1", "s2", "s4", "s7", "s9"]
    assert all(len(options["scales"][k]) == 10 for k in ("severity", "occurrence", "detection"))
    assert options["scales"]["detection"][9] == "Cannot detect" and options["scales"]["severity"][0] == "No effect"
    assert [s["id"] for s in options["severity_classes"]] == ["I", "II", "III", "IV"]
    assert [s["id"] for s in options["action_statuses"]] == ["open", "in_progress", "done"]
    assert [s["id"] for s in options["rate_sources"]] == ["entered", "model", "data"]


def test_the_field_checks_say_what_is_wrong():
    def refused(changes):
        with pytest.raises(fmea.FmeaError) as err:
            fmea.validate_changes(changes)
        return str(err.value)

    assert refused({"severity": 0}) == "Severity is a whole number from 1 (no effect) to 10 (hazardous without warning)."
    assert refused({"occurrence": 2.5}) == "Occurrence is a whole number from 1 (almost never) to 10 (almost certain)."
    assert refused({"detection": "ten"}) == \
        "Detection is a whole number from 1 (almost certain to detect) to 10 (cannot detect)."
    assert refused({"detection": True}).startswith("Detection is a whole number")
    assert refused({"action_due": "soon"}) == "The due date is a date (YYYY-MM-DD)."
    assert refused({"action_status": "pending"}) == "Action status is open, in_progress or done."
    assert refused({"rate_source": "guess"}) == "Rate source is entered, model or data."
    assert refused({"severity_class": "V"}) == "Severity class is I, II, III or IV."
    assert "0 or more" in refused({"failure_rate": -1})
    assert "from 0 to 1" in refused({"mode_ratio": 1.5}) and "from 0 to 1" in refused({"loss_probability": -0.1})
    assert "greater than 0" in refused({"operating_time": 0})
    assert refused({"rpn": 96}).startswith("Unknown FME(C)A field 'rpn'")
    assert "is at most 4000 characters" in refused({"cause": "x" * 4001})
    # Values come back normalised; None or "" clears.
    assert fmea.validate_changes({"severity": "7", "occurrence": 3.0, "action_status": "In progress",
                                  "severity_class": "ii", "action_due": "2026-12-15T00:00", "cause": "  dust ",
                                  "detection": None, "action": ""}) == {
        "severity": 7, "occurrence": 3, "action_status": "in_progress", "severity_class": "II",
        "action_due": "2026-12-15", "cause": "dust", "detection": None, "action": None}


# ---- the events ---------------------------------------------------------------------------

def test_scores_are_one_event_each_and_rebuild_the_same(m):
    pump, fn, ff = _pump(m)
    mode = m.add_failure_mode(pump["id"], "Bearing seizure", functional_failure_id=ff["id"])
    events = m.s.event_count(ORG)
    out = m.score_failure_mode(mode["id"], SCORES)
    assert m.s.event_count(ORG) == events + 1
    assert (out["rpn"], out["ap"], out["cm"]) == (216, "H", pytest.approx(1.2e-3))
    assert {k: out[k] for k in SCORES} == {**SCORES, "operating_time": 100.0}
    # The same again: nothing written. A change: only what changed. None clears.
    m.score_failure_mode(mode["id"], SCORES)
    assert m.s.event_count(ORG) == events + 1
    m.score_failure_mode(mode["id"], {"detection": 2, "action_status": ""})
    node = m.s.node(ORG, mode["id"])
    assert node["detection"] == 2 and node["action_status"] is None and node["severity"] == 9
    read = m.rcm_mode(mode["id"])
    assert read["rpn"] == 72 and read["ap"] == "H" and read["action_status"] is None  # s9, o4, d2 is still H
    m.score_failure_mode(mode["id"], {"mode_ratio": None})
    assert m.rcm_mode(mode["id"])["cm"] is None
    with pytest.raises(Invalid, match="Severity is a whole number"):
        m.score_failure_mode(mode["id"], {"severity": 11})
    with pytest.raises(Invalid, match="Unknown FME"):
        m.score_failure_mode(mode["id"], {"rpn": 1})
    # The RCM read carries the fields (null when not set) and the position's summary.
    other = m.add_failure_mode(pump["id"], "Seal leaks")
    p = m.rcm_worksheet(pump["id"], "this")["positions"][0]
    [seal] = p["unassigned"]
    assert seal["id"] == other["id"] and seal["severity"] is None and seal["rpn"] is None and seal["cm"] is None
    assert p["fmea"] == {"modes": 2, "scored": 1, "high": 1, "medium": 0, "low": 0, "max_rpn": 72, "cr": None,
                         "cr_by_class": {}}
    _rebuilds_the_same(m)


def test_a_position_summary_sums_criticality_by_class(m):
    pump, fn, ff = _pump(m)
    a = m.add_failure_mode(pump["id"], "Worn", functional_failure_id=ff["id"])
    b = m.add_failure_mode(pump["id"], "Cracked", functional_failure_id=ff["id"])
    m.score_failure_mode(a["id"], {"loss_probability": 1.0, "mode_ratio": 0.6, "failure_rate": 2e-5,
                                   "operating_time": 100, "severity_class": "I", "severity": 9, "occurrence": 4,
                                   "detection": 6})
    m.score_failure_mode(b["id"], {"loss_probability": 0.3, "mode_ratio": 0.4, "failure_rate": 5e-5,
                                   "operating_time": 100, "severity_class": "III"})
    summary = m.rcm_worksheet(pump["id"], "this")["positions"][0]["fmea"]
    assert summary["cr"] == pytest.approx(1.8e-3) and summary["cr_by_class"] == {
        "I": pytest.approx(1.2e-3), "III": pytest.approx(6e-4)}
    assert (summary["scored"], summary["high"], summary["max_rpn"]) == (1, 1, 216)


def test_a_mode_directly_under_a_function_both_ways(m):
    pump = m.create_position("Pump A")
    fn = m.add_function(pump["id"], "Pump 50 L/s")
    b = m.create_position("Pump B")
    elsewhere = m.add_function(b["id"], "Pump too")
    with pytest.raises(Invalid, match="another position"):
        m.add_failure_mode(pump["id"], "Impeller worn", function_id=elsewhere["id"])
    mode = m.add_failure_mode(pump["id"], "Impeller worn", function_id=fn["id"])
    m.score_failure_mode(mode["id"], SCORES)
    assert m.s.out(ORG, fn["id"], "FAILS_DIRECTLY_AS")[0]["id"] == mode["id"]
    assert m.s.inn(ORG, mode["id"], "CAUSED_BY") == []

    p = m.rcm_worksheet(pump["id"], "this")["positions"][0]
    [got] = p["functions"][0]["modes"]
    assert got["id"] == mode["id"] and got["rpn"] == 216 and p["unassigned"] == []
    assert p["functions"][0]["failures"] == []
    assert p["analysed"] is False
    where = m.failure_mode_rcm(mode["id"])
    assert where["function"]["id"] == fn["id"] and where["functional_failure"] is None
    # The gaps name it: an FMEA row with no functional failure yet.
    resolved = rcm_graph.resolve(None, m.rcm_worksheet(pump["id"], "this"), [ORG])
    assert resolved["rollup"]["modes"] == 1
    gaps = rcm_graph.gaps(resolved)
    assert [(g["id"], g["function"]["id"]) for g in gaps["no_functional_failure"]] == [(mode["id"], fn["id"])]
    assert gaps["counts"]["no_functional_failure"] == 1 and [g["id"] for g in gaps["undecided"]] == [mode["id"]]
    # A decided mode directly under a function with no functional failure still leaves the position unanalysed.
    m.decide_failure_mode(mode["id"], "operational", {"outcome": "accept", "notes": "fine"})
    assert m.rcm_worksheet(pump["id"], "this")["positions"][0]["analysed"] is False

    # Assigned to a functional failure: the same id, the scores intact, the direct edge gone, and analysed.
    ff = m.add_functional_failure(fn["id"], "No flow")
    with pytest.raises(Invalid, match="not both"):
        m.add_failure_mode(pump["id"], "Seal leaks", functional_failure_id=ff["id"], function_id=fn["id"])
    out = m.assign_failure_mode(mode["id"], ff["id"])
    assert out["from_function_id"] == fn["id"] and out["from_functional_failure_id"] is None
    assert m.s.out(ORG, fn["id"], "FAILS_DIRECTLY_AS") == []
    p = m.rcm_worksheet(pump["id"], "this")["positions"][0]
    [under] = p["functions"][0]["failures"][0]["modes"]
    assert under["id"] == mode["id"] and under["severity"] == 9 and under["cm"] == pytest.approx(1.2e-3)
    assert p["functions"][0]["modes"] == [] and p["analysed"] is True
    # Back under the function, then under none, then under the function again.
    back = m.assign_failure_mode(mode["id"], None, function_id=fn["id"])
    assert back["from_functional_failure_id"] == ff["id"] and m.s.inn(ORG, mode["id"], "CAUSED_BY") == []
    assert m.rcm_worksheet(pump["id"], "this")["positions"][0]["functions"][0]["modes"][0]["id"] == mode["id"]
    assert m.assign_failure_mode(mode["id"], None, function_id=fn["id"])["from_function_id"] == fn["id"]  # no change
    m.assign_failure_mode(mode["id"], None)
    assert [x["id"] for x in m.rcm_worksheet(pump["id"], "this")["positions"][0]["unassigned"]] == [mode["id"]]
    m.assign_failure_mode(mode["id"], None, function_id=fn["id"])
    with pytest.raises(Invalid, match="not both"):
        m.assign_failure_mode(mode["id"], ff["id"], function_id=fn["id"])
    with pytest.raises(Invalid, match="another position"):
        m.assign_failure_mode(mode["id"], None, function_id=elsewhere["id"])

    # Removing the function sends its direct modes to unassigned, counted.
    removed = m.remove_function(fn["id"])
    assert removed["failure_modes_unassigned"] == 1
    p = m.rcm_worksheet(pump["id"], "this")["positions"][0]
    assert [x["id"] for x in p["unassigned"]] == [mode["id"]] and p["unassigned"][0]["rpn"] == 216
    assert m.failure_mode_rcm(mode["id"])["function"] is None
    _rebuilds_the_same(m)


def test_direct_modes_move_copy_restore_and_reorder(m):
    pump, fn, ff = _pump(m)
    first = m.add_failure_mode(pump["id"], "Impeller worn", function_id=fn["id"])
    second = m.add_failure_mode(pump["id"], "Seal leaks", function_id=fn["id"])
    m.score_failure_mode(first["id"], SCORES)
    # Reorder: a function's children are its functional failures, or, named instead, its direct modes.
    out = m.reorder_rcm(fn["id"], [second["id"], first["id"]])
    assert out["kind"] == "failure_modes" and out["previous_ids"] == [first["id"], second["id"]]
    assert [x["id"] for x in m.rcm_worksheet(pump["id"], "this")["positions"][0]["functions"][0]["modes"]] == [
        second["id"], first["id"]]
    assert m.reorder_rcm(fn["id"], [ff["id"]])["kind"] == "functional_failures"
    with pytest.raises(Invalid, match="failure modes directly under it"):
        m.reorder_rcm(fn["id"], [first["id"]])

    # A copy carries the placements and the scores.
    copy = m.copy_position(pump["id"], "Pump A copy")
    p = m.rcm_worksheet(copy["id"], "this")["positions"][0]
    copied = p["functions"][0]["modes"]
    assert [x["text"] for x in copied] == ["Seal leaks", "Impeller worn"] and copied[1]["rpn"] == 216
    assert copied[1]["id"] != first["id"] and p["fmea"]["scored"] == 1

    # A deleted direct mode comes back under its function; one whose function went comes back unassigned.
    m.retire_failure_mode(second["id"])
    m.restore_failure_mode(second["id"])
    assert [x["id"] for x in m.rcm_worksheet(pump["id"], "this")["positions"][0]["functions"][0]["modes"]] == [
        second["id"], first["id"]]

    # The function moves with its direct modes; a retired one stays behind, taken from under it.
    m.retire_failure_mode(second["id"])
    b = m.create_position("Pump B")
    moved = m.move_function(fn["id"], b["id"])
    assert moved["failure_modes_moved"] == 1
    assert m.s.inn(ORG, first["id"], "CAN_FAIL_AS")[0]["id"] == b["id"]
    assert [x["id"] for x in m.s.out(ORG, fn["id"], "FAILS_DIRECTLY_AS")] == [first["id"]]
    m.restore_failure_mode(second["id"])
    assert [x["id"] for x in m.rcm_worksheet(pump["id"], "this")["positions"][0]["unassigned"]] == [second["id"]]
    assert m.rcm_worksheet(b["id"], "this")["positions"][0]["functions"][0]["modes"][0]["id"] == first["id"]

    # One mode moves to another position's function, or away from one (the edge never crosses positions).
    there = m.add_function(pump["id"], "Keep the dust down")
    result = m.move_failure_mode(first["id"], pump["id"], function_id=there["id"])
    assert result["from_function_id"] == fn["id"] and result["rpn"] == 216
    assert [x["id"] for x in m.s.out(ORG, there["id"], "FAILS_DIRECTLY_AS")] == [first["id"]]
    assert m.s.out(ORG, fn["id"], "FAILS_DIRECTLY_AS") == []
    with pytest.raises(Invalid, match="not both"):
        m.move_failure_mode(first["id"], b["id"], functional_failure_id=ff["id"], function_id=fn["id"])
    with pytest.raises(Invalid, match="pick one of"):
        m.move_failure_mode(first["id"], b["id"], function_id=there["id"])
    m.move_failure_mode(first["id"], b["id"])
    assert m.s.inn(ORG, first["id"], "FAILS_DIRECTLY_AS") == []
    assert [x["id"] for x in m.rcm_worksheet(b["id"], "this")["positions"][0]["unassigned"]] == [first["id"]]
    _rebuilds_the_same(m)


# ---- the samples ----------------------------------------------------------------------------

def test_the_sample_uav_is_scored_with_three_modes_directly_under_a_function(m):
    out = templates.add_sample_uav(m)
    assert out["added"] and out["position"]["name"] == "Quadcopter UAV (sample)"
    assert {k: out[k] for k in ("positions", "functions", "failure_modes", "scored", "direct")} == {
        "positions": 15, "functions": 11, "failure_modes": 16, "scored": 16, "direct": 3}
    assert "16 failure modes, every one scored" in out["message"] and "3 of them sit directly" in out["message"]
    sheet = m.rcm_worksheet(out["position"]["id"], "below")
    modes = _all_modes(sheet)
    assert len(modes) == 16 and all(mo["rpn"] is not None for mo in modes)
    summaries = [p["fmea"] for p in sheet["positions"]]
    assert sum(s["high"] for s in summaries) == 3 and sum(s["medium"] for s in summaries) == 7
    assert sum(s["low"] for s in summaries) == 6 and max(s["max_rpn"] or 0 for s in summaries) == 216
    assert sum(len(fn["modes"]) for p in sheet["positions"] for fn in p["functions"]) == 3
    assert sum(len(p["unassigned"]) for p in sheet["positions"]) == 0
    motor = next(p for p in sheet["positions"] if p["name"] == "Motor")
    assert motor["fmea"]["cr"] == pytest.approx(6.4e-3) and motor["fmea"]["cr_by_class"] == {"I": pytest.approx(6.4e-3)}
    assert motor["analysed"] is False  # the winding mode has no decision on purpose
    gps = next(p for p in sheet["positions"] if p["name"] == "GPS receiver")
    [direct] = gps["functions"][0]["modes"]
    assert direct["text"] == "Antenna connector works loose" and direct["ap"] == "L" and gps["functions"][0]["failures"] == []
    assert all(mo["operating_time"] == 100 and mo["time_unit"] == "hours" for mo in modes)
    by_text = {mo["text"]: mo for mo in modes}
    assert by_text["Bearing seizure"]["rpn"] == 216 and by_text["Bearing seizure"]["ap"] == "H"
    assert by_text["Bearing seizure"]["decision"]["outcome"] == "on_condition"
    assert by_text["Gimbal motor stalls on a snagged cable"]["consequence"] == "non_operational"
    assert by_text["Gimbal motor stalls on a snagged cable"]["decision"] is None

    # Once only unless asked again; another workspace is untouched.
    twice = templates.add_sample_uav(m)
    assert twice["added"] is False and "already in your tree" in twice["message"]
    again = templates.add_sample_uav(m, again=True)
    assert again["added"] and again["position"]["name"] == "Quadcopter UAV (sample 2)"
    assert templates.add_sample_truck(m)["added"]  # the truck's counter is its own
    assert templates.sample_uav_modes() == templates.SAMPLE_UAV_MODES
    assert templates.sample_uav_modes() is not templates.SAMPLE_UAV_MODES
    _rebuilds_the_same(m)


def test_the_sample_truck_is_scored(m):
    out = templates.add_sample_truck(m)
    sheet = m.rcm_worksheet(out["position"]["id"], "this")
    by_text = {mo["text"]: mo for mo in _all_modes(sheet)}
    legacy = by_text["Wheel-bearing failure — legacy run-to-failure plan"]
    assert (legacy["severity"], legacy["occurrence"], legacy["detection"], legacy["rpn"], legacy["ap"]) == (7, 5, 10, 350, "H")
    assert legacy["cm"] == pytest.approx(0.6 * 0.4 * 1.5e-4 * 1000) and legacy["severity_class"] == "II"
    pads = by_text["Brake pad wear beyond the 8 mm limit"]
    assert pads["rpn"] == 96 and pads["action"] == "Fit wear-indicator pads" and pads["action_due"] == "2026-12-01"
    assert pads["cause"] == "Normal friction wear, faster with heavy loads" and pads["rate_source"] == "entered"
    assert by_text["Chassis cracking at the spring hanger"]["ap"] == "M"
    summary = sheet["positions"][0]["fmea"]
    assert summary["scored"] == 5 and summary["max_rpn"] == 350 and summary["cr"] == pytest.approx(
        0.2 * 0.7 * 2e-4 * 1000 + 0.5 * 0.3 * 5e-5 * 1000 + 0.6 * 0.6 * 1.5e-4 * 1000 + 0.6 * 0.4 * 1.5e-4 * 1000
        + 1.0 * 1.0 * 1e-5 * 1000)


# ---- the worksheet import ------------------------------------------------------------------

FMEA_HEADER = ["Function", "Failure mode", "Cause", "Local effect", "End effect", "Current controls", "Severity",
               "Occurrence", "Detection", "RPN", "Recommended action", "Responsibility", "Target date"]
FMEA_ROWS = [
    ["Turn the propeller", "Bearing seizure", "Dust", "Stalls", "Uncontrolled descent", "Spin check", 9, 4, 6, 216,
     "Sealed bearings", "Propulsion lead", "2026-11-30"],
    [None, "Winding breaks down", "Overload", "Phase shorts", "Uncontrolled descent", "Temperature alarm", 9, 2, 4, 70,
     "Derate above 35 °C", None, None],
    ["Give position", "Connector works loose", "Vibration", "Fix lost", "Fly-away", "Satellite count", 8, 3, 2, 48,
     None, None, None],
]


def _xlsx(header, rows) -> bytes:
    from openpyxl import Workbook

    wb = Workbook()
    ws = wb.active
    ws.append(header)
    for r in rows:
        ws.append(r)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def test_an_fmea_sheet_imports_with_its_scores(m):
    pid = m.create_position("Motor")["id"]
    table = rcm_sheet.read_table(_xlsx(FMEA_HEADER, FMEA_ROWS), "fmea.xlsx")
    opts = rcm_sheet.default_options(table)
    assert opts["mapping"]["severity"] == "Severity" and opts["mapping"]["cause"] == "Cause"
    assert opts["mapping"]["effects"] == "End effect" and opts["mapping"]["action"] == "Recommended action"
    assert "failure" not in opts["mapping"] and opts["extra_columns"] == []
    out = rcm_sheet.run(m, pid, table, opts, dry_run=False)
    assert out["ok"] and out["errors"] == [], out
    assert (out["counts"]["functions"], out["counts"]["failures"], out["counts"]["modes"], out["counts"]["scored"]) == (
        2, 0, 3, 3)
    # No functional failure column: the modes sit directly under their functions, never under "Imported".
    p = m.rcm_worksheet(pid, "this")["positions"][0]
    assert [fn["text"] for fn in p["functions"]] == ["Turn the propeller", "Give position"]
    assert all(fn["failures"] == [] for fn in p["functions"]) and p["unassigned"] == []
    bearing, winding = p["functions"][0]["modes"]
    assert (bearing["severity"], bearing["occurrence"], bearing["detection"], bearing["rpn"], bearing["ap"]) == (9, 4, 6, 216, "H")
    assert bearing["cause"] == "Dust" and bearing["effect_local"] == "Stalls" and bearing["effects"] == "Uncontrolled descent"
    assert bearing["detection_method"] == "Spin check" and bearing["action"] == "Sealed bearings"
    assert bearing["action_owner"] == "Propulsion lead" and bearing["action_due"] == "2026-11-30"
    assert bearing["notes"] == "" and winding["rpn"] == 72  # the sheet's 70 is only compared
    [warning] = [w for w in out["warnings"] if "RPN" in w]
    assert "row 3" in warning
    assert p["fmea"] == {"modes": 3, "scored": 3, "high": 1, "medium": 0, "low": 2, "max_rpn": 216, "cr": None,
                         "cr_by_class": {}}
    # The same sheet again adds nothing.
    again = rcm_sheet.run(m, pid, table, opts, dry_run=False)
    assert again["counts"]["modes"] == 0 and again["counts"]["modes_existing"] == 3

    # A score out of range: a row error, and nothing is written.
    fresh = m.create_position("Motor 2")["id"]
    rows = [list(r) for r in FMEA_ROWS]
    rows[1][6] = 11
    events = m.s.event_count(ORG)
    bad = rcm_sheet.run(m, fresh, rcm_sheet.read_table(_xlsx(FMEA_HEADER, rows), "fmea.xlsx"), opts, dry_run=False)
    assert not bad["ok"] and bad["errors"] == [
        "Row 3: Severity is a whole number from 1 (no effect) to 10 (hazardous without warning)."]
    assert m.s.event_count(ORG) == events
    _rebuilds_the_same(m)


# ---- the routes, MCP and the Excel export --------------------------------------------------

def test_over_the_routes_with_the_excel_export(api):  # noqa: F811
    from openpyxl import load_workbook

    plant = api.post(f"{M}/positions", json={"name": "Plant"}).json()
    fn = api.post(f"{M}/positions/{plant['id']}/functions", json={"text": "Pump water"}).json()
    ff = api.post(f"{M}/functions/{fn['id']}/failures", json={"text": "No flow"}).json()
    r = api.post(f"{M}/positions/{plant['id']}/failure-modes", json={"text": "Bearing seizes", "function_id": fn["id"]})
    assert r.status_code == 200, r.text
    mode = r.json()
    both = api.post(f"{M}/positions/{plant['id']}/failure-modes",
                    json={"text": "Seal", "function_id": fn["id"], "functional_failure_id": ff["id"]})
    assert both.status_code == 422 and "not both" in both.json()["detail"]

    # PATCH takes the FME(C)A keys beside the RCM ones; the answer carries rpn, ap and cm.
    r = api.patch(f"{M}/failure-modes/{mode['id']}", json={"effects": "Pump stops", **SCORES})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["rpn"] == 216 and body["ap"] == "H" and body["cm"] == pytest.approx(1.2e-3)
    assert body["effects"] == "Pump stops" and body["text"] == "Bearing seizes" and body["cause"] == SCORES["cause"]
    r = api.patch(f"{M}/failure-modes/{mode['id']}", json={"detection": None, "action_owner": None})
    assert r.status_code == 200 and r.json()["rpn"] is None and r.json()["action_owner"] is None
    bad = api.patch(f"{M}/failure-modes/{mode['id']}", json={"occurrence": 0})
    assert bad.status_code == 422 and bad.json()["detail"].startswith("Occurrence is a whole number")
    assert api.patch(f"{M}/failure-modes/{mode['id']}", json={"text": "Bearing seizure"}).json()["text"] == "Bearing seizure"

    sheet = api.get(f"{M}/positions/{plant['id']}/rcm?scope=this").json()
    p = sheet["positions"][0]
    assert [x["id"] for x in p["functions"][0]["modes"]] == [mode["id"]] and p["unassigned"] == []
    assert p["fmea"]["scored"] == 0 and p["fmea"]["modes"] == 1 and p["functions"][0]["modes"][0]["severity"] == 9
    assert p["rollup"]["modes"] == 1
    assert api.post(f"{M}/failure-modes/{mode['id']}/assign", json={"functional_failure_id": ff["id"]}).status_code == 200
    assert api.post(f"{M}/failure-modes/{mode['id']}/assign", json={"function_id": fn["id"]}).status_code == 200
    p = api.get(f"{M}/positions/{plant['id']}/rcm?scope=this").json()["positions"][0]
    assert [x["id"] for x in p["functions"][0]["modes"]] == [mode["id"]]

    options = api.get(f"{M}/rcm/options").json()
    assert options["fmea"]["ap_table"]["s9"]["o4"]["d5"] == "H" and len(options["fmea"]["scales"]["occurrence"]) == 10
    assert options["consequences"] and options["fmea"]["ap_bands"]["detection"][0]["id"] == "d1"

    # The Excel export opens, has the header frozen and the mode's row.
    api.patch(f"{M}/failure-modes/{mode['id']}", json={"detection": 6})
    r = api.get(f"{M}/positions/{plant['id']}/fmea.xlsx")
    assert r.status_code == 200 and r.headers["content-type"].startswith(fmea_sheet.XLSX)
    assert 'filename="Plant FMECA.xlsx"' in r.headers["content-disposition"]
    wb = load_workbook(io.BytesIO(r.content))
    ws = wb["FMECA"]
    assert ws.freeze_panes == "A2"
    header = [c.value for c in ws[1]]
    assert header == fmea_sheet.HEADER and ws[1][0].font.bold
    row = dict(zip(header, [c.value for c in ws[2]]))
    assert row["Failure mode"] == "Bearing seizure" and row["Functional failure"] is None  # directly under the function
    assert (row["Severity"], row["Occurrence"], row["Detection"], row["RPN"], row["Action priority"]) == (9, 4, 6, 216, "High")
    assert row["Mode criticality"] == pytest.approx(1.2e-3) and row["Severity class"] == "I" and row["Effects"] == "Pump stops"
    assert api.get(f"{M}/positions/nope/fmea.xlsx").status_code == 404
    assert api.get(f"{M}/positions/{plant['id']}/fmea.xlsx?scope=nope").status_code == 422

    # The sample UAV over its route: once, then again.
    made = api.post(f"{M}/sample-uav").json()
    assert made["added"] and made["failure_modes"] == 16 and made["direct"] == 3
    assert api.post(f"{M}/sample-uav", json={}).json()["added"] is False
    assert api.post(f"{M}/sample-uav", json={"again": True}).json()["position"]["name"] == "Quadcopter UAV (sample 2)"
    uav = api.get(f"{M}/positions/{made['position']['id']}/fmea.xlsx").content
    ws = load_workbook(io.BytesIO(uav))["FMECA"]
    assert ws.max_row == 1 + 16  # the header and one row per mode (positions with no functions add none)
    assert 'filename="Quadcopter UAV (sample) FMECA.xlsx"' in \
        api.get(f"{M}/positions/{made['position']['id']}/fmea.xlsx").headers["content-disposition"]


def test_over_mcp(env):  # noqa: F811
    async def flow(client):
        pid = _ok(await _do(client, "maintenance", "positions.create", name="Pump A"))["id"]
        fn = _ok(await _do(client, "maintenance", "failure_modes.add_function", position_id=pid, text="Pump water"))
        ff = _ok(await _do(client, "maintenance", "failure_modes.add_functional_failure", function_id=fn["id"],
                           text="No flow"))
        mode = _ok(await _do(client, "maintenance", "failure_modes.add", position_id=pid, text="Bearing seizes",
                             function_id=fn["id"]))
        both = await _do(client, "maintenance", "failure_modes.add", position_id=pid, text="Seal",
                         function_id=fn["id"], functional_failure_id=ff["id"])
        scored = _ok(await _do(client, "maintenance", "failure_modes.score", failure_mode_id=mode["id"],
                               severity=9, occurrence=4, detection=6, cause="Dust", effects="Pump stops",
                               recommended_action="Sealed bearings", action_due="2026-11-30",
                               action_status="open", failure_rate=2e-5, mode_ratio=0.6, loss_probability=1.0,
                               operating_time=100, severity_class="I"))
        bad = await _do(client, "maintenance", "failure_modes.score", failure_mode_id=mode["id"], severity=11)
        wrong_clear = await _do(client, "maintenance", "failure_modes.score", failure_mode_id=mode["id"],
                                clear=["rpn"])
        cleared = _ok(await _do(client, "maintenance", "failure_modes.score", failure_mode_id=mode["id"],
                                clear=["detection", "recommended_action"]))
        read = _ok(await _get(client, "failure_mode", mode["id"]))
        rcm = _ok(await _get(client, "rcm", pid, scope="this"))
        gaps = _ok(await _list(client, "rcm_gaps", target_id=pid))
        assigned = _ok(await _do(client, "maintenance", "failure_modes.assign", failure_mode_id=mode["id"],
                                 functional_failure_id=ff["id"]))
        back = _ok(await _do(client, "maintenance", "failure_modes.assign", failure_mode_id=mode["id"],
                             function_id=fn["id"]))
        uav = _ok(await _do(client, "maintenance", "positions.add_sample_uav"))
        twice = _ok(await _do(client, "maintenance", "positions.add_sample_uav"))
        return mode, both, scored, bad, wrong_clear, cleared, read, rcm, gaps, assigned, back, uav, twice

    mode, both, scored, bad, wrong_clear, cleared, read, rcm, gaps, assigned, back, uav, twice = _session(env["token"], flow)
    assert both.is_error and "not both" in both.content[0].text
    assert scored["rpn"] == 216 and scored["ap"] == "H" and scored["cm"] == pytest.approx(1.2e-3)
    assert scored["action"] == "Sealed bearings" and scored["effects"] == "Pump stops"
    assert bad.is_error and "Severity is a whole number" in bad.content[0].text
    assert wrong_clear.is_error and "'rpn' isn't one" in wrong_clear.content[0].text
    assert cleared["rpn"] is None and cleared["action"] is None and cleared["severity"] == 9
    assert read["function"]["id"] and read["functional_failure"] is None and read["cause"] == "Dust"
    fn_read = rcm["positions"][0]["functions"][0]
    assert [x["id"] for x in fn_read["modes"]] == [mode["id"]] and fn_read["failures"][0]["modes"] == []
    assert rcm["positions"][0]["fmea"]["modes"] == 1 and rcm["positions"][0]["analysed"] is False
    assert [g["id"] for g in gaps["no_functional_failure"]] == [mode["id"]] and gaps["counts"]["no_functional_failure"] == 1
    assert assigned["from_function_id"] == fn_read["id"] and back["from_functional_failure_id"] == fn_read["failures"][0]["id"]
    assert uav["added"] and uav["failure_modes"] == 16 and twice["added"] is False
