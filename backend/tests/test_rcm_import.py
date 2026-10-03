"""FMEA / RCM spreadsheet -> RCM study worksheet: column mapping, carry-down
of blank function / failure cells, consequence and decision-type value
mapping, FMEA scores kept in the mode's notes, and the import endpoints (new
study vs existing, append vs replace, access and edit conflicts)."""

import io
import json

import mongomock
import pytest
from openpyxl import Workbook

from backend.services import excel, rcm, rcm_import

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
    assert rcm.clean_tree(tree)[0]["failures"][0]["modes"][0]["notes"] == "RPN 96"


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

A, B = "user-a", "user-b"
USERS = {A: {"uid": A, "email": "a@x.com", "name": "A"}, B: {"uid": B, "email": "b@x.com", "name": "B"}}
XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def _workbook() -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.title = "RCM worksheet"
    ws.append(["Conveyor RCM"])
    ws.append([])
    ws.append(HEADER)
    for r in ROWS:
        ws.append(r)
    ws.merge_cells("B4:B6")  # the function written once, merged down
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


@pytest.fixture()
def client(monkeypatch):
    from fastapi.testclient import TestClient

    from backend import config, db
    from backend.auth import get_current_user
    from backend.main import app

    monkeypatch.setattr(config, "AUTH_DISABLED", False)
    monkeypatch.setattr(config, "BILLING_ENABLED", False)
    test_db = mongomock.MongoClient()["reliafy_test"]
    monkeypatch.setattr(db, "_db", test_db)
    monkeypatch.setattr(db, "_simulated", True)
    who = {"uid": A}
    app.dependency_overrides[get_current_user] = lambda: USERS[who["uid"]]
    tc = TestClient(app)
    tc.db = test_db
    tc.who = who
    try:
        yield tc
    finally:
        app.dependency_overrides.clear()


def _form(**extra):
    opts = _options()
    return {"sheet": "RCM worksheet", "header_row": "3", "options": json.dumps(opts), **extra}


def _post(client, path, **extra):
    return client.post(path, files={"file": ("rcm.xlsx", _workbook(), XLSX)}, data=_form(**extra))


def test_preview_saves_nothing(client):
    r = _post(client, "/api/rcm/import/preview")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["counts"]["modes"] == 4
    assert {v["value"] for v in body["values"]["consequence"]} == {"Operational", "O", "Environmental", "Hidden"}
    assert client.db.rcm_studies.count_documents({}) == 0


def test_import_creates_a_study(client):
    r = _post(client, "/api/rcm/import", name="Conveyor", system="Line 2")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["name"] == "Conveyor" and body["system"] == "Line 2"
    assert body["rollup"]["modes"] == 4 and body["rollup"]["decided"] == 3
    assert body["imported"]["counts"]["modes"] == 4
    got = client.get(f"/api/rcm/studies/{body['id']}").json()
    assert got["functions"][0]["text"] == "Pump water at 100 L/min"


def test_import_new_study_needs_a_name_and_respects_the_cap(client, monkeypatch):
    assert _post(client, "/api/rcm/import").status_code == 422
    from backend.services import billing

    monkeypatch.setattr(billing, "would_exceed_cap", lambda *a, **k: True)
    r = _post(client, "/api/rcm/import", name="Over the cap")
    assert r.status_code == 402 and r.json()["code"] == "cap"
    assert client.db.rcm_studies.count_documents({}) == 0


def test_import_bad_mapping_creates_nothing(client):
    r = client.post("/api/rcm/import", files={"file": ("rcm.xlsx", _workbook(), XLSX)},
                    data={"sheet": "RCM worksheet", "header_row": "3", "name": "X",
                          "options": json.dumps({"mapping": {"function": "Function"}})})
    assert r.status_code == 422 and "Failure mode" in r.json()["detail"]
    assert client.db.rcm_studies.count_documents({}) == 0


def _existing(client):
    study = client.post("/api/rcm/studies", json={"name": "Existing"}).json()
    tree = [{"text": "Keep me", "failures": [{"text": "F", "modes": [{"text": "old mode"}]}]}]
    return client.put(f"/api/rcm/studies/{study['id']}/tree", json={"functions": tree}).json()


def test_append_keeps_the_existing_worksheet(client):
    study = _existing(client)
    r = _post(client, "/api/rcm/import", study_id=study["id"], mode="append",
              expected_updated_at=study["updated_at"])
    assert r.status_code == 200, r.text
    fns = r.json()["functions"]
    assert [f["text"] for f in fns] == ["Keep me", "Pump water at 100 L/min", "Contain fluid"]
    assert fns[0]["id"] == study["functions"][0]["id"]
    assert r.json()["rollup"]["modes"] == 5


def test_replace_swaps_the_worksheet(client):
    study = _existing(client)
    r = _post(client, "/api/rcm/import", study_id=study["id"], mode="replace",
              expected_updated_at=study["updated_at"])
    assert r.status_code == 200, r.text
    assert [f["text"] for f in r.json()["functions"]] == ["Pump water at 100 L/min", "Contain fluid"]


def test_import_detects_edit_conflicts(client):
    study = _existing(client)
    stale = "2000-01-01T00:00:00+00:00"
    r = _post(client, "/api/rcm/import", study_id=study["id"], mode="append", expected_updated_at=stale)
    assert r.status_code == 409 and r.json()["code"] == "conflict"
    assert len(client.get(f"/api/rcm/studies/{study['id']}").json()["functions"]) == 1


def test_import_into_someone_elses_study_is_refused(client):
    study = _existing(client)
    client.who["uid"] = B
    r = _post(client, "/api/rcm/import", study_id=study["id"], mode="replace")
    assert r.status_code == 404
    client.who["uid"] = A
    assert len(client.get(f"/api/rcm/studies/{study['id']}").json()["functions"]) == 1


def test_import_into_a_sample_is_refused(client):
    from backend.services import samples

    samples.seed_samples(client.db)
    sample = next(s for s in client.get("/api/rcm/studies").json()["studies"] if s["is_sample"])
    before = client.get(f"/api/rcm/studies/{sample['id']}").json()["functions"]
    r = _post(client, "/api/rcm/import", study_id=sample["id"], mode="append")
    assert r.status_code == 403
    assert client.get(f"/api/rcm/studies/{sample['id']}").json()["functions"] == before


def test_import_rejects_unknown_mode(client):
    assert _post(client, "/api/rcm/import", name="X", mode="merge").status_code == 422
