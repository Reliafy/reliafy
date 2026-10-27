"""FMEA / RCM spreadsheet -> an RCM worksheet tree: column mapping, carry-down
of blank function / failure cells, consequence and decision-type value
mapping, FMEA scores kept in the mode's notes. (Adding the tree to a position
is backend/maintenance/rcm_sheet.py: test_maintenance_rcm_sheet.py.)"""


import pytest

from backend.maintenance import rcm_decisions
from backend.services import excel, rcm_import

HEADER = ["Item", "Function", "Functional failure", "Failure mode", "Effect", "S", "O", "D", "RPN",
          "Consequence", "Task type", "Recommended action", "Interval", "Unit", "Comments"]
ROWS = [
    ["P-101", "Pump water at 100 L/min", "No flow", "Bearing seized", "Pump stops", 8, 4, 3, 96,
     "Operational", "On-condition", "Vibration analysis", 1, "months", None],
    [None, None, None, "Impeller worn", "Low flow", 5, 3, 2, 30,
     "O", "Scheduled replacement", "Replace impeller", "every 2 years", None, "OEM advice"],
    [None, None, "Leaks", "Seal failure", "Spill", 7, 2, 4, 56,
     "Environmental", "Run to failure", "Replace on failure", None, None, None],
    [None, None, None, None, None, None, None, None, None, None, None, None, None, None, None],
    [None, None, None, None, "orphan effect", None, None, None, None, None, None, None, None, None, None],
    ["P-102", "Contain fluid", "Casing leaks", "Casing crack", "Leak", 9, 1, 5, 45,
     "Hidden", "Failure finding", "Pressure test", "Annually", None, None],
]


def _options(**extra):
    mapping = excel.guess_mapping(HEADER, rcm_import.FIELDS)
    return {"mapping": mapping, "extra_columns": rcm_import.default_extra_columns(HEADER, mapping), **extra}


def _modes(result):
    return [(fn["text"], f["text"], m) for fn in result["functions"] for f in fn["failures"] for m in f["modes"]]


def test_guess_maps_typical_fmea_headers():
    mapping = excel.guess_mapping(HEADER, rcm_import.FIELDS)
    assert mapping == {
        "function": "Function", "failure": "Functional failure", "mode": "Failure mode",
        "effects": "Effect", "consequence": "Consequence", "outcome": "Task type",
        "task": "Recommended action", "interval": "Interval", "interval_unit": "Unit", "notes": "Comments",
    }
    assert rcm_import.default_extra_columns(HEADER, mapping) == ["Item", "S", "O", "D", "RPN"]


def test_build_tree_carries_down_and_maps_values():
    result = rcm_import.build_tree(HEADER, ROWS, _options())
    modes = _modes(result)
    assert [(fn, f, m["text"]) for fn, f, m in modes] == [
        ("Pump water at 100 L/min", "No flow", "Bearing seized"),
        ("Pump water at 100 L/min", "No flow", "Impeller worn"),      # both carried down
        ("Pump water at 100 L/min", "Leaks", "Seal failure"),         # function carried down
        ("Contain fluid", "Casing leaks", "Casing crack"),
    ]
    bearing, impeller, seal, casing = (m for _, _, m in modes)
    assert bearing["consequence"] == "operational" and impeller["consequence"] == "operational"  # "O"
    assert bearing["decision"] == {"outcome": "on_condition", "task": "Vibration analysis",
                                   "interval": 1.0, "interval_unit": "months", "evidence": None}
    assert impeller["decision"]["outcome"] == "fixed_interval"
    assert impeller["decision"]["interval"] == 2.0 and impeller["decision"]["interval_unit"] == "years"
    assert casing["consequence"] == "hidden"
    assert casing["decision"]["outcome"] == "failure_finding"
    assert casing["decision"]["interval"] == 1.0 and casing["decision"]["interval_unit"] == "years"
    # Run-to-failure needs a basis the sheet doesn't give: undecided, task kept in notes.
    assert seal["decision"] is None
    assert "Task: Replace on failure" in seal["notes"]
    # FMEA scores (and the item) appended to the notes; mapped notes first.
    assert bearing["notes"] == "Item P-101 · S 8 · O 4 · D 3 · RPN 96"
    assert impeller["notes"] == "OEM advice\nS 5 · O 3 · D 2 · RPN 30"
    assert bearing["effects"] == "Pump stops"
    assert result["counts"] == {"functions": 2, "failures": 3, "modes": 4, "decisions": 3, "skipped_rows": 1}
    assert any("1 row with no failure mode was skipped" in w for w in result["warnings"])
    rtf = next(v for v in result["values"]["outcome"] if v["value"] == "Run to failure")
    assert rtf["guess"] is None and "basis" in rtf["hint"]


def test_explicit_value_maps_override_guesses():
    result = rcm_import.build_tree(HEADER, ROWS, _options(
        outcome_map={"Run to failure": "rtf:uneconomic", "On-condition": ""},
        consequence_map={"Hidden": "safety"},
        extra_columns=[],
    ))
    bearing, _, seal, casing = (m for _, _, m in _modes(result))
    assert seal["decision"]["outcome"] == "rtf" and seal["decision"]["rtf_basis"] == "uneconomic"
    assert seal["decision"]["task"] == "Replace on failure"
    assert bearing["decision"] is None                        # mapped to "leave unset"
    assert "Task: Vibration analysis · Interval: 1 months" in bearing["notes"]
    assert casing["consequence"] == "safety"
    assert "S 8" not in (bearing.get("notes") or "")          # extras switched off


def test_missing_function_and_failure_columns_go_under_imported():
    mapping = {"mode": "Failure mode", "effects": "Effect"}
    result = rcm_import.build_tree(HEADER, ROWS, {"mapping": mapping})
    assert [f["text"] for f in result["functions"]] == ["Imported"]
    assert [f["text"] for f in result["functions"][0]["failures"]] == ["Imported"]
    assert result["counts"]["modes"] == 4 and result["counts"]["decisions"] == 0


def test_same_function_later_in_the_sheet_merges():
    header = ["Function", "Failure", "Mode"]
    rows = [["F1", "X", "m1"], ["F2", "Y", "m2"], ["f1", "X", "m3"]]
    result = rcm_import.build_tree(header, rows, {"mapping": {"function": "Function", "failure": "Failure", "mode": "Mode"}})
    assert [f["text"] for f in result["functions"]] == ["F1", "F2"]
    assert [m["text"] for m in result["functions"][0]["failures"][0]["modes"]] == ["m1", "m3"]


def test_value_guesses():
    g = rcm_import.guess_consequence
    assert [g("S"), g("E"), g("Non-operational"), g("Hidden safety"), g("Production loss")] == [
        "safety", "environmental", "non_operational", "hidden", "operational"]
    assert g("Safety / environmental") is None and g("High") is None and g(3) is None
    o = rcm_import.guess_outcome
    assert [o("CBM"), o("Time-based"), o("Proof test"), o("Redesign"), o("No scheduled maintenance")] == [
        "on_condition", "fixed_interval", "failure_finding", "redesign", "accept"]
    assert o("Run to failure") is None and o("Replace bearing") is None and o("PM") is None


def test_parse_interval():
    p = rcm_import.parse_interval
    assert p(500) == (500.0, None)
    assert p("every 6 months") == (6.0, "months")
    assert p("8,760 h") == (8760.0, "h")
    assert p("Quarterly") == (3.0, "months")
    assert p("as required") == (None, None) and p(0) == (None, None)


def test_errors():
    with pytest.raises(rcm_import.RcmImportError, match="Failure mode"):
        rcm_import.build_tree(HEADER, ROWS, {"mapping": {"function": "Function"}})
    with pytest.raises(rcm_import.RcmImportError, match="no column"):
        rcm_import.build_tree(HEADER, ROWS, {"mapping": {"mode": "Nope"}})
    with pytest.raises(rcm_import.RcmImportError, match="No failure modes"):
        rcm_import.build_tree(HEADER, [[None] * len(HEADER)], {"mapping": {"mode": "Failure mode"}})
    with pytest.raises(rcm_import.RcmImportError, match="Unknown decision type"):
        rcm_import.build_tree(HEADER, ROWS, {"mapping": {"mode": "Failure mode"}, "outcome_map": {"x": "bogus"}})


def test_mode_notes_are_kept_by_clean_tree():
    tree = [{"text": "F", "failures": [{"text": "X", "modes": [{"text": "m", "notes": " RPN 96 "}]}]}]
    assert rcm_decisions.clean_tree(tree)[0]["failures"][0]["modes"][0]["notes"] == "RPN 96"
