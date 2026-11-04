"""FMEA / RCM spreadsheet -> an RCM worksheet tree: column mapping, carry-down
of blank function / failure cells, consequence and decision-type value
mapping, FMEA scores landing on the mode (an RPN column only checked), a
mode with no functional failure directly under its function. (Adding the
tree to a position is backend/maintenance/rcm_sheet.py:
test_maintenance_rcm_sheet.py.)"""


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
    """The FMEA columns map to the mode's scores (S / O / D, the RPN checked
    only, the recommended action its own field); only the item column is left
    for the notes."""
    mapping = excel.guess_mapping(HEADER, rcm_import.FIELDS)
    assert mapping == {
        "function": "Function", "failure": "Functional failure", "mode": "Failure mode",
        "effects": "Effect", "consequence": "Consequence", "outcome": "Task type",
        "action": "Recommended action", "interval": "Interval", "interval_unit": "Unit", "notes": "Comments",
        "severity": "S", "occurrence": "O", "detection": "D", "rpn": "RPN",
    }
    assert rcm_import.default_extra_columns(HEADER, mapping) == ["Item"]
    # A column Reliafy works out itself is never kept as notes, mapped or not.
    assert rcm_import.default_extra_columns(["Item", "RPN", "Action priority", "Mode criticality"], {}) == ["Item"]
    # An FMEA worksheet's own headers (cause, local / next higher / end effect, controls, owner, due).
    fmea_header = ["Function", "Potential failure mode", "Potential cause", "Local effect", "Next higher effect",
                   "End effect", "Current controls", "Severity", "Occurrence", "Detection", "RPN",
                   "Recommended action", "Responsibility", "Target date", "Status"]
    guessed = excel.guess_mapping(fmea_header, rcm_import.FIELDS)
    assert guessed == {
        "function": "Function", "mode": "Potential failure mode", "cause": "Potential cause",
        "effect_local": "Local effect", "effect_next": "Next higher effect", "effects": "End effect",
        "detection_method": "Current controls", "severity": "Severity", "occurrence": "Occurrence",
        "detection": "Detection", "rpn": "RPN", "action": "Recommended action", "action_owner": "Responsibility",
        "action_due": "Target date", "action_status": "Status",
    }


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
    # No task column: the recommended action names the decision's task too.
    assert bearing["decision"] == {"outcome": "on_condition", "task": "Vibration analysis",
                                   "interval": 1.0, "interval_unit": "months", "evidence": None}
    assert impeller["decision"]["outcome"] == "fixed_interval"
    assert impeller["decision"]["interval"] == 2.0 and impeller["decision"]["interval_unit"] == "years"
    assert casing["consequence"] == "hidden"
    assert casing["decision"]["outcome"] == "failure_finding"
    assert casing["decision"]["interval"] == 1.0 and casing["decision"]["interval_unit"] == "years"
    # Run-to-failure needs a basis the sheet doesn't give: undecided; the action is on the mode.
    assert seal["decision"] is None and seal["action"] == "Replace on failure"
    assert seal["notes"] == "Task type: Run to failure"  # the unmapped decision type kept, the action not repeated
    # FMEA scores land on the mode (the RPN column is checked, never kept); the item goes to the notes.
    assert (bearing["severity"], bearing["occurrence"], bearing["detection"]) == (8, 4, 3) and "rpn" not in bearing
    assert bearing["notes"] == "Item P-101" and bearing["action"] == "Vibration analysis"
    assert impeller["notes"] == "OEM advice"
    assert bearing["effects"] == "Pump stops"
    assert result["counts"] == {"functions": 2, "failures": 3, "modes": 4, "decisions": 3, "skipped_rows": 1}
    assert result["errors"] == [] and not any("RPN" in w for w in result["warnings"])
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
    assert "Interval: 1 months" in bearing["notes"] and bearing["action"] == "Vibration analysis"
    assert casing["consequence"] == "safety"
    assert "Item" not in (bearing.get("notes") or "")         # extras switched off


def test_missing_function_column_goes_under_imported_and_no_failure_goes_directly_under_the_function():
    """No function column: one "Imported" function. No functional failure column
    (or none named yet under the function): the modes sit directly under the
    function, as an FMEA worksheet reads, not under a stand-in failure."""
    mapping = {"mode": "Failure mode", "effects": "Effect"}
    result = rcm_import.build_tree(HEADER, ROWS, {"mapping": mapping})
    assert [f["text"] for f in result["functions"]] == ["Imported"]
    assert result["functions"][0]["failures"] == []
    assert [m["text"] for m in result["functions"][0]["modes"]] == [
        "Bearing seized", "Impeller worn", "Seal failure", "Casing crack"]
    assert result["counts"]["modes"] == 4 and result["counts"]["decisions"] == 0
    assert not any("Imported" in w for w in result["warnings"])
    # The failure column mapped but blank until the second row of a function: the
    # first mode is directly under the function, the later ones under the failure.
    header = ["Function", "Functional failure", "Failure mode"]
    rows = [["F1", None, "m1"], ["F1", "X", "m2"], [None, None, "m3"], ["F2", None, "m4"]]
    out = rcm_import.build_tree(header, rows, {"mapping": {"function": "Function", "failure": "Functional failure",
                                                           "mode": "Failure mode"}}, keep_rows=True)
    f1, f2 = out["functions"]
    assert [m["text"] for m in f1["modes"]] == ["m1"] and [m["row"] for m in f1["modes"]] == [2]
    assert [m["text"] for m in f1["failures"][0]["modes"]] == ["m2", "m3"]
    assert [m["text"] for m in f2["modes"]] == ["m4"] and "failures" in f2 and f2["failures"] == []


def test_scores_out_of_range_are_row_errors_and_a_wrong_rpn_only_warns():
    header = ["Function", "Failure mode", "S", "O", "D", "RPN", "Due date"]
    rows = [["F", "m1", 8, 4, 3, 96, "2026-12-01"], ["F", "m2", 11, 4, 3, None, None],
            ["F", "m3", 7, "x", 3, None, None], ["F", "m4", 5, 3, 2, 40, "soon"]]
    mapping = excel.guess_mapping(header, rcm_import.FIELDS)
    out = rcm_import.build_tree(header, rows, {"mapping": mapping}, keep_rows=True)
    assert out["errors"] == [
        "Row 3: Severity is a whole number from 1 (no effect) to 10 (hazardous without warning).",
        "Row 4: Occurrence is a whole number from 1 (almost never) to 10 (almost certain).",
        "Row 5: The due date is a date (YYYY-MM-DD).",
    ]
    [warning] = [w for w in out["warnings"] if "RPN" in w]
    assert "1 row (row 5)" in warning and "isn't kept" in warning
    m1, m2, m3, m4 = out["functions"][0]["modes"]
    assert m1["action_due"] == "2026-12-01" and (m1["severity"], m1["occurrence"], m1["detection"]) == (8, 4, 3)
    assert "severity" not in m2 and m2["occurrence"] == 4  # the bad value is dropped, the row still errors
    assert "rpn" not in m4 and m4["severity"] == 5


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
