"""An FMEA / RCM worksheet (Excel or CSV) added to a position's RCM
(backend/maintenance/rcm_sheet.py): read and mapped as the study import reads
it, written only through the service's methods, only ever adding, checked
first and all or nothing; over REST (preview and import) and MCP (uploads
import_excel target=rcm position_id). Invented worksheets only."""

import io

import mongomock
import pytest

from backend.maintenance import photos, rcm_sheet
from backend.maintenance.service import PROJECTORS, Invalid, Maintenance, NotFound
from backend.maintenance.store import GraphStore
from backend.services import excel, rcm_import

ORG = "user-r"

HEADER = ["Function", "Performance standard", "Functional failure", "Failure mode", "Effect", "Consequence",
          "Task type", "Proposed task", "Interval", "Unit", "Severity"]
ROWS = [
    ["Move grain from the pit to the silo", "At least 40 t/h", "Moves no grain", "Belt torn", "Line stops",
     "Operational", "On-condition", "Walk the belt and look for damage", 1, "weeks", 7],
    [None, None, None, "Head pulley bearing seizes", "Line stops, belt may burn", "Safety", "Fixed interval",
     "Replace head pulley bearings", 12, "months", 9],
    [None, None, "Moves less than 40 t/h", "Belt slips on the drive drum", "Slower filling", "Non-operational",
     "Run to failure", "Re-tension when it slips", None, None, 3],
    ["Stop the belt when someone pulls the lanyard", None, "Doesn't stop the belt", "Pull-wire switch stuck",
     "Belt keeps running", "Hidden", "Failure finding", "Test the pull-wire switch", 3, "months", 10],
    [None, None, None, None, None, None, None, None, None, None, None],
    [None, None, None, None, "an effect with no failure mode", None, None, None, None, None, None],
]
MAPPING = {"function": "Function", "standard": "Performance standard", "failure": "Functional failure",
           "mode": "Failure mode", "effects": "Effect", "consequence": "Consequence", "outcome": "Task type",
           "task": "Proposed task", "interval": "Interval", "interval_unit": "Unit"}
OPTIONS = {"mapping": MAPPING, "outcome_map": {"Run to failure": "rtf:uneconomic"}, "extra_columns": ["Severity"]}


def _xlsx(header=HEADER, rows=ROWS) -> bytes:
    from openpyxl import Workbook

    wb = Workbook()
    ws = wb.active
    ws.title = "FMEA"
    ws.append(["Conveyor C-2 FMEA (invented example)"])
    ws.append(header)
    for r in rows:
        ws.append(r)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _csv(header=HEADER, rows=ROWS) -> bytes:
    import csv

    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(header)
    for r in rows:
        w.writerow(["" if v is None else v for v in r])
    return buf.getvalue().encode()


@pytest.fixture()
def m():
    return Maintenance(GraphStore(":memory:", PROJECTORS), ORG, "tester")


def _table(data=None, filename="conveyor.xlsx"):
    return rcm_sheet.read_table(data if data is not None else _xlsx(), filename, None, 2 if filename.endswith("x") else None)


def _rebuilds_the_same(m):
    before = m.s.snapshot()
    m.s.rebuild()
    assert m.s.snapshot() == before


def _rcm(m, pid):
    return m.rcm_worksheet(pid, "this")["positions"][0]


# ---- reading and mapping: the study import's parser ---------------------------------------

def test_the_study_parser_says_each_modes_row_only_when_asked():
    table = _table()
    plain = rcm_import.build_tree(table.header, table.rows, OPTIONS, table.row_numbers)
    rows = rcm_import.build_tree(table.header, table.rows, OPTIONS, table.row_numbers, keep_rows=True)
    modes = [mo for f in plain["functions"] for x in f["failures"] for mo in x["modes"]]
    assert all("row" not in mo and "_row" not in mo for mo in modes)  # the study import is as it was
    assert [mo["row"] for f in rows["functions"] for x in f["failures"] for mo in x["modes"]] == [3, 4, 5, 6]


def test_csv_reads_as_the_same_table_as_the_sheet():
    sheet, text = _table(), _table(_csv(), "conveyor.csv")
    assert text.header == sheet.header and len(text.rows) == len(sheet.rows) == 5
    assert text.rows[0][3] == "Belt torn" and text.rows[0][8] == "1" and text.row_numbers[0] == 2
    with pytest.raises(excel.ExcelError, match="no data"):
        excel.read_csv(b"Failure mode\n\n", "x.csv")
    dup = excel.read_csv(b"Mode,Mode,\nA,B,C\n", "x.csv")
    assert dup.header == ["Mode", "Mode (2)", "col 3"]


# ---- what it adds, and how it groups --------------------------------------------------------

def test_rows_group_into_functions_failures_and_modes_with_decisions_and_tasks(m):
    pid = m.create_position("Conveyor C-2")["id"]
    out = rcm_sheet.run(m, pid, _table(), OPTIONS, dry_run=False)
    assert out["ok"] and not out["dry_run"] and out["errors"] == []
    want = {"functions": 2, "failures": 3, "modes": 4, "decisions": 4, "tasks": 3, "functions_existing": 0,
            "modes_existing": 0, "skipped_rows": 1, "rows": 5, "errors": 0}
    assert {k: out["counts"][k] for k in want} == want
    p = _rcm(m, pid)
    [move, stop] = p["functions"]
    assert move["text"] == "Move grain from the pit to the silo" and move["standard"] == "At least 40 t/h"
    assert [f["text"] for f in move["failures"]] == ["Moves no grain", "Moves less than 40 t/h"]
    torn, bearing = move["failures"][0]["modes"]
    assert torn["text"] == "Belt torn" and torn["effects"] == "Line stops" and torn["consequence"] == "operational"
    assert torn["notes"] == "Severity 7"
    assert torn["decision"]["outcome"] == "on_condition" and torn["decision"]["interval"] == 1
    assert torn["decision"]["interval_unit"] == "weeks"
    assert bearing["decision"]["outcome"] == "fixed_interval" and bearing["consequence"] == "safety"
    slip = move["failures"][1]["modes"][0]
    assert slip["decision"]["outcome"] == "rtf" and slip["decision"]["rtf_basis"] == "uneconomic"
    assert slip["decision"].get("task_id") is None
    switch = stop["failures"][0]["modes"][0]
    assert switch["consequence"] == "hidden" and switch["decision"]["outcome"] == "failure_finding"
    tasks = m._tasks_on(pid)
    assert sorted(t["name"] for t in tasks) == ["Replace head pulley bearings", "Test the pull-wire switch",
                                               "Walk the belt and look for damage"]
    assert {t["unit"] for t in tasks} == {"weeks", "months"}
    assert any("row 8" in w for w in out["warnings"])  # the row with an effect but no failure mode
    _rebuilds_the_same(m)


def test_importing_the_same_sheet_again_adds_nothing(m):
    pid = m.create_position("Conveyor C-2")["id"]
    rcm_sheet.run(m, pid, _table(), OPTIONS, dry_run=False)
    events = m.s.event_count(ORG)
    again = rcm_sheet.run(m, pid, _table(_csv(), "same.csv"), OPTIONS, dry_run=False)
    assert again["ok"] and m.s.event_count(ORG) == events
    c = again["counts"]
    assert (c["functions"], c["failures"], c["modes"], c["tasks"]) == (0, 0, 0, 0)
    assert (c["functions_existing"], c["failures_existing"], c["modes_existing"]) == (2, 3, 4)
    assert "4 failure modes are on Conveyor C-2 already" in again["warnings"][-1]


def test_it_only_adds_reusing_what_matches_and_changing_nothing(m):
    pid = m.create_position("Conveyor C-2")["id"]
    fn = m.add_function(pid, "move grain from the PIT to the silo", "At least 30 t/h")  # case and spacing aside
    ff = m.add_functional_failure(fn["id"], "Moves no grain")
    torn = m.add_failure_mode(pid, "Belt torn", functional_failure_id=ff["id"])
    m.decide_failure_mode(torn["id"], "safety", {"outcome": "redesign", "notes": "Our own decision"})
    loose = m.add_failure_mode(pid, "Pull-wire switch stuck")  # on the position, under no functional failure
    out = rcm_sheet.run(m, pid, _table(), OPTIONS, dry_run=False)
    assert out["counts"]["functions"] == 1 and out["counts"]["functions_existing"] == 1  # "Stop the belt…" is new
    assert out["counts"]["failures"] == 2 and out["counts"]["failures_existing"] == 1
    assert out["counts"]["modes"] == 2 and out["counts"]["modes_existing"] == 2
    assert any("another performance standard" in w for w in out["warnings"])
    p = _rcm(m, pid)
    move = p["functions"][0]
    assert move["id"] == fn["id"] and move["standard"] == "At least 30 t/h"  # left as it was
    assert [x["text"] for x in move["failures"][0]["modes"]] == ["Belt torn", "Head pulley bearing seizes"]
    kept = move["failures"][0]["modes"][0]
    assert kept["consequence"] == "safety" and kept["decision"]["outcome"] == "redesign"
    assert [mo["id"] for mo in p["unassigned"]] == [loose["id"]]  # not moved under the sheet's failure
    stop = p["functions"][1]
    assert stop["failures"][0]["text"] == "Doesn't stop the belt" and stop["failures"][0]["modes"] == []
    _rebuilds_the_same(m)


def test_the_preview_writes_nothing_and_says_what_the_import_does(m):
    pid = m.create_position("Conveyor C-2")["id"]
    events = m.s.event_count(ORG)
    preview = rcm_sheet.run(m, pid, _table(), OPTIONS, dry_run=True)
    assert preview["dry_run"] and m.s.event_count(ORG) == events and _rcm(m, pid)["functions"] == []
    done = rcm_sheet.run(m, pid, _table(), OPTIONS, dry_run=False)
    assert {k: v for k, v in preview.items() if k != "dry_run"} == {k: v for k, v in done.items() if k != "dry_run"}
    assert preview["functions"][0] == {"text": "Move grain from the pit to the silo", "new": True, "failures": [
        {"text": "Moves no grain", "new": True, "modes": 2}, {"text": "Moves less than 40 t/h", "new": True, "modes": 1}]}
    assert preview["values"]["consequence"][0] == {"value": "Operational", "count": 1, "guess": "operational"}


# ---- limits, errors and warnings -------------------------------------------------------------

def test_a_row_in_error_stops_the_whole_import(m):
    pid = m.create_position("Conveyor C-2")["id"]
    rows = [list(r) for r in ROWS]
    rows[1][8], rows[1][9] = 200, "years"
    out = rcm_sheet.run(m, pid, _table(_xlsx(rows=rows)), OPTIONS, dry_run=False)
    assert not out["ok"] and out["dry_run"]
    assert out["errors"] == ["Row 4: The interval is at most 100 years. Change it in the sheet and try again."]
    assert _rcm(m, pid)["functions"] == [] and m._tasks_on(pid) == []


def test_long_text_repeats_and_missing_units_are_warned_about(m):
    pid = m.create_position("Conveyor C-2")["id"]
    long_mode = "Belt torn " + "by a sharp rock falling from the feed chute " * 6
    rows = [list(r) for r in ROWS[:4]]
    rows[0][3] = long_mode
    rows[0][9] = None
    rows.append([None, None, None, "Head pulley bearing seizes", None, None, None, None, None, None, None])
    out = rcm_sheet.run(m, pid, _table(_xlsx(rows=rows)), OPTIONS, dry_run=False)
    assert out["ok"] and out["counts"]["modes"] == 4
    text = " ".join(out["warnings"])
    assert "1 failure mode is over 200 characters" in text and "(row 3)" in text
    assert "1 row repeats a failure mode from earlier in the sheet; only the first is added (row 7)" in text
    assert "1 interval has no unit, so its task is in days (row 3)" in text
    torn = _rcm(m, pid)["functions"][0]["failures"][0]["modes"][0]
    assert len(torn["text"]) <= 200 and torn["text"].endswith("…")
    assert torn["notes"].startswith("Failure mode in full: " + long_mode.strip())
    assert torn["decision"]["interval_unit"] == "days"


def test_sheets_too_big_or_unmapped_are_refused(m, monkeypatch):
    pid = m.create_position("Conveyor C-2")["id"]
    monkeypatch.setattr(rcm_sheet, "MAX_MODES", 3)
    with pytest.raises(Invalid, match="would add 4 failure modes; one import adds at most 3"):
        rcm_sheet.run(m, pid, _table(), OPTIONS)
    monkeypatch.setattr(rcm_sheet, "MAX_ROWS", 3)
    with pytest.raises(excel.ExcelError, match="more than 3 rows"):
        _table()
    with pytest.raises(Invalid, match="Map a column to Failure mode"):
        rcm_sheet.run(m, pid, excel.read_csv(_csv(), "x.csv"), {"mapping": {"function": "Function"}})
    with pytest.raises(Invalid, match="no column “Mode”"):
        rcm_sheet.run(m, pid, excel.read_csv(_csv(), "x.csv"), {"mapping": {"mode": "Mode"}})


def test_only_a_live_position_in_this_workspace(m):
    with pytest.raises(NotFound):
        rcm_sheet.run(m, "nope", _table(), OPTIONS)
    other = Maintenance(m.s, "someone-else", "them")
    theirs = other.create_position("Their conveyor")["id"]
    with pytest.raises(NotFound):
        rcm_sheet.run(m, theirs, _table(), OPTIONS)
    pid = m.create_position("Old conveyor")["id"]
    m.retire_position(pid)
    with pytest.raises(Invalid, match="has been retired"):
        rcm_sheet.run(m, pid, _table(), OPTIONS)


def test_the_guessed_mapping_imports_a_typical_sheet(m):
    pid = m.create_position("Conveyor C-2")["id"]
    table = _table()
    opts = rcm_sheet.default_options(table)
    assert opts["mapping"]["mode"] == "Failure mode" and opts["extra_columns"] == ["Severity"]
    out = rcm_sheet.run(m, pid, table, opts, dry_run=False)
    assert out["ok"] and out["counts"]["modes"] == 4


# ---- REST ---------------------------------------------------------------------------------------

UID, OTHER = "user-r", "user-s"


@pytest.fixture()
def api(monkeypatch, tmp_path):
    from fastapi.testclient import TestClient

    from backend import config, db
    from backend.auth import get_current_user
    from backend.main import app
    from backend.routers import maintenance as router

    monkeypatch.setattr(config, "AUTH_DISABLED", False)
    monkeypatch.setattr(config, "BILLING_ENABLED", False)
    monkeypatch.setattr(config, "MAINTENANCE_ENABLED", True)
    monkeypatch.setattr(config, "MAINTENANCE_EMAILS", {"r@example.org", "s@example.org"})
    test_db = mongomock.MongoClient()["maint_rcm_sheet"]
    monkeypatch.setattr(db, "_db", test_db)
    monkeypatch.setattr(db, "_simulated", True)
    monkeypatch.setattr(router, "_store", GraphStore(":memory:", PROJECTORS))
    monkeypatch.setattr(router, "_photo_store", photos.FilePhotoStore(str(tmp_path)))
    users = {UID: {"uid": UID, "email": "r@example.org", "name": "R", "email_verified": True},
             OTHER: {"uid": OTHER, "email": "s@example.org", "name": "S", "email_verified": True},
             "user-t": {"uid": "user-t", "email": "t@example.org", "name": "T", "email_verified": True}}
    for u in users.values():
        test_db.users.insert_one({"_id": u["uid"], **{k: v for k, v in u.items() if k != "uid"}})
    who = {"uid": UID}
    app.dependency_overrides[get_current_user] = lambda: users[who["uid"]]
    try:
        yield {"client": TestClient(app), "who": who, "app": app, "router": router}
    finally:
        app.dependency_overrides.clear()


def _post(client, pid, path="rcm/import", data=None, filename="c2.xlsx", options=OPTIONS, **form):
    import json

    body = {"header_row": "2" if filename.endswith("x") else "", **form}
    if options is not None:
        body["options"] = json.dumps(options)
    return client.post(f"/api/maintenance/positions/{pid}/{path}",
                       files={"file": (filename, data if data is not None else _xlsx())}, data=body)


def test_rest_preview_then_import_and_again(api):
    c = api["client"]
    pid = c.post("/api/maintenance/positions", json={"name": "Conveyor C-2"}).json()["id"]
    preview = _post(c, pid, "rcm/import/preview")
    assert preview.status_code == 200, preview.text
    assert preview.json()["dry_run"] and preview.json()["counts"]["modes"] == 4
    assert c.get(f"/api/maintenance/positions/{pid}/rcm?scope=this").json()["positions"][0]["functions"] == []
    done = _post(c, pid)
    assert done.status_code == 200 and not done.json()["dry_run"] and done.json()["counts"]["tasks"] == 3
    rcm = c.get(f"/api/maintenance/positions/{pid}/rcm?scope=this").json()["positions"][0]
    assert len(rcm["functions"]) == 2 and rcm["functions"][0]["failures"][0]["modes"][0]["text"] == "Belt torn"
    again = _post(c, pid, data=_csv(), filename="c2.csv")  # the same rows as CSV
    assert again.status_code == 200 and again.json()["counts"]["modes"] == 0
    assert again.json()["counts"]["modes_existing"] == 4
    guessed = _post(c, pid, "rcm/import/preview", options=None)  # no options: the guessed mapping
    assert guessed.status_code == 200 and guessed.json()["counts"]["modes_existing"] == 4


def test_rest_refusals_are_plain(api):
    c = api["client"]
    pid = c.post("/api/maintenance/positions", json={"name": "Conveyor C-2"}).json()["id"]
    r = c.post(f"/api/maintenance/positions/{pid}/rcm/import", files={"file": ("c2.xlsx", _xlsx())},
               data={"options": "{nope"})
    assert r.status_code == 422 and r.json()["detail"] == "The import options aren't valid JSON."
    r = _post(c, pid, data=b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\0" * 64, filename="old.xls")
    assert r.status_code == 422 and "xlsx" in r.json()["detail"].lower()
    r = _post(c, pid, options={"mapping": {"function": "Function"}})
    assert r.status_code == 422 and "Failure mode" in r.json()["detail"]
    assert _post(c, "nope").status_code == 404
    rows = [list(x) for x in ROWS]
    rows[0][8], rows[0][9] = "every 300 years", None  # the unit from the text
    r = _post(c, pid, data=_xlsx(rows=rows))
    assert r.status_code == 200 and not r.json()["ok"] and r.json()["dry_run"]
    assert r.json()["errors"][0].startswith("Row 3: The interval is at most 100 years.")


def test_rest_is_scoped_to_the_workspace_and_its_writers(api):
    from backend.services.access import AccessCtx, get_access

    c, who, app = api["client"], api["who"], api["app"]
    pid = c.post("/api/maintenance/positions", json={"name": "Conveyor C-2"}).json()["id"]
    who["uid"] = OTHER  # another workspace: no such position there
    assert _post(c, pid, "rcm/import/preview").status_code == 404
    assert _post(c, pid).status_code == 404
    who["uid"] = "user-t"  # Maintenance isn't on for them
    assert _post(c, pid, "rcm/import/preview").status_code == 404
    who["uid"] = UID

    def view_only():
        return AccessCtx(user={"uid": UID, "email": "r@example.org", "email_verified": True}, uid=UID,
                         workspace="t1", write_owner="team:t1", read_owners=[UID, "team:t1"],
                         list_owners=["team:t1"], member_view_only=True)
    app.dependency_overrides[get_access] = view_only
    try:
        assert _post(c, pid).status_code == 402
    finally:
        app.dependency_overrides.pop(get_access)


def test_the_column_mapper_reads_csv_too(api):
    r = api["client"].post("/api/excel/table", files={"file": ("c2.csv", _csv())}, data={"target": "rcm"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["columns"] == HEADER and body["guess"]["mode"] == "Failure mode"
    assert body["extra_columns"] == ["Severity"] and body["n_rows"] == 5


def test_the_routes_take_a_workbooks_size():
    from backend import http_limits

    assert http_limits.body_limit("/api/maintenance/positions/abc/rcm/import") > 20 * 1024 * 1024
    assert http_limits.body_limit("/api/maintenance/positions/abc/rcm/import/preview") > 20 * 1024 * 1024
    assert http_limits.body_limit("/api/maintenance/positions/abc/rcm/importx") < 20 * 1024 * 1024


def test_usage_names_the_import():
    from backend.services import usage

    assert usage.app_feature("POST", "/api/maintenance/positions/p1/rcm/import") == "rcm_import"
    assert usage.app_feature("POST", "/api/maintenance/positions/p1/rcm/import/preview") == "rcm_import_preview"


# ---- MCP: uploads import_excel target=rcm position_id ------------------------------------------

@pytest.fixture()
def mcp(monkeypatch, mcp_on):
    from backend import config
    from backend.routers import maintenance as router
    from backend.tests import test_mcp_uploads as up

    env = up.env.__wrapped__(monkeypatch)
    env.db.users.update_many({}, {"$set": {"email_verified": True}})  # Maintenance needs a verified address
    monkeypatch.setattr(config, "MAINTENANCE_ENABLED", True)
    monkeypatch.setattr(config, "MAINTENANCE_EMAILS", {f"{up.A}@example.org"})
    store = GraphStore(":memory:", PROJECTORS)
    monkeypatch.setattr(router, "_store", store)
    env.store, env.up = store, up
    return env


def test_mcp_adds_a_worksheet_to_a_position_once(mcp):
    from backend.tests.test_mcp import _err, _ok

    up = mcp.up
    m = Maintenance(mcp.store, up.A, up.A)
    pid = m.create_position("Conveyor C-2")["id"]
    link, _ = up._upload(mcp, _xlsx(), "c2.xlsx", purpose="excel")
    out = _ok(up._call(mcp.token[up.A], "uploads", {"action": "import_excel", "upload_id": link["upload_id"],
                                                     "target": "rcm", "position_id": pid, "header_row": 2}))
    assert out["ok"] and out["written"] and out["position_id"] == pid
    assert out["counts"]["modes"] == 4 and out["counts"]["tasks"] == 3
    assert out["mapping"]["mode"] == "Failure mode" and out["extra_columns"] == ["Severity"]
    assert out["url"].endswith(f"/asset-register/explorer?arrange=positions&tab=rcm&sel={pid}")
    assert up._no_uploads_left(mcp.db)
    assert len(m.rcm_worksheet(pid, "this")["positions"][0]["functions"]) == 2
    assert mcp.db.rcm_studies.count_documents({}) == 0  # not a study

    # The same rows again, as CSV: nothing more.
    link2, _ = up._upload(mcp, _csv(), "c2.csv", purpose="excel")
    again = _ok(up._call(mcp.token[up.A], "uploads", {"action": "import_excel", "upload_id": link2["upload_id"],
                                                       "target": "rcm", "position_id": pid}))
    assert again["counts"]["modes"] == 0 and again["counts"]["modes_existing"] == 4

    # A row in error: nothing written, the upload kept to try again.
    fresh = m.create_position("Conveyor C-3")["id"]
    rows = [list(r) for r in ROWS]
    rows[0][8], rows[0][9] = 101, "years"
    link3, _ = up._upload(mcp, _xlsx(rows=rows), "bad.xlsx", purpose="excel")
    bad = _ok(up._call(mcp.token[up.A], "uploads", {"action": "import_excel", "upload_id": link3["upload_id"],
                                                     "target": "rcm", "position_id": fresh, "header_row": 2}))
    assert not bad["ok"] and not bad["written"] and "Nothing was added" in bad["note"]
    assert bad["errors"] == ["Row 3: The interval is at most 100 years. Change it in the sheet and try again."]
    assert mcp.db.uploads.count_documents({"_id": link3["upload_id"]}) == 1
    assert m.rcm_worksheet(fresh, "this")["positions"][0]["functions"] == []

    # Arguments that don't go together, a position that isn't there, someone without Maintenance.
    msg = _err(up._call(mcp.token[up.A], "uploads", {"action": "import_excel", "upload_id": link3["upload_id"],
                                                      "target": "dataset", "position_id": pid}))
    assert "position_id applies to target rcm" in msg
    msg = _err(up._call(mcp.token[up.A], "uploads", {"action": "import_excel", "upload_id": link3["upload_id"],
                                                      "target": "rcm", "position_id": pid, "study_id": "s"}))
    assert "not both" in msg
    msg = _err(up._call(mcp.token[up.A], "uploads", {"action": "import_excel", "upload_id": link3["upload_id"],
                                                      "target": "rcm", "position_id": "nope"}))
    assert "Position not found" in msg
    link4, _ = up._upload(mcp, _xlsx(), "c2.xlsx", purpose="excel", uid=up.B)
    msg = _err(up._call(mcp.token[up.B], "uploads", {"action": "import_excel", "upload_id": link4["upload_id"],
                                                      "target": "rcm", "position_id": pid}))
    assert "positions aren't available" in msg


def test_the_tabs_csv_export_imports_again_adding_nothing(m):
    """The RCM tab's Export CSV (frontend/src/rcmImport.js) names its columns as
    the import reads them: a mode under no functional failure comes first with
    blank function cells, and a function with no failures has a row of its own."""
    pid = m.create_position("Conveyor C-2")["id"]
    rcm_sheet.run(m, pid, _table(), OPTIONS, dry_run=False)
    m.add_failure_mode(pid, "Motor hums")
    m.add_function(pid, "Keep the dust down")
    events = m.s.event_count(ORG)
    exported = (
        "Position,Function,Performance standard,Functional failure,Failure mode,Effects,Consequence,Decision,"
        "Run-to-failure basis,Task,Interval,Interval unit,Evidence check,Notes\n"
        "Conveyor C-2,,,,Motor hums,,,,,,,,,\n"
        "Conveyor C-2,Move grain from the pit to the silo,At least 40 t/h,Moves no grain,Belt torn,Line stops,"
        "Operational,On-condition,,Walk the belt and look for damage,1,weeks,,Severity 7\n"
        "Conveyor C-2,Keep the dust down,,,,,,,,,,,,\n")
    table = excel.read_csv(exported.encode(), "Conveyor C-2 RCM.csv")
    opts = rcm_sheet.default_options(table)
    assert set(opts["mapping"]) >= {"function", "standard", "failure", "mode", "effects", "consequence", "outcome",
                                    "task", "interval", "interval_unit", "notes"}
    out = rcm_sheet.run(m, pid, table, opts, dry_run=False)
    assert out["ok"] and m.s.event_count(ORG) == events
    assert (out["counts"]["functions"], out["counts"]["failures"], out["counts"]["modes"]) == (0, 0, 0)


# ---- the working behind a performance standard ---------------------------------------------

WORKING = "## Demand\n\n150 g ÷ 35,000 L = 4.3 ppm/day\n\n- 0.1 ppm per swim"
BASIS_HEADER = ["Function", "Performance standard", "Standard working", "Functional failure", "Failure mode"]


def _basis_csv(rows) -> bytes:
    import csv

    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(BASIS_HEADER)
    w.writerows(rows)
    return buf.getvalue().encode()


def test_a_standard_working_column_is_mapped_and_carried_down_a_function(m):
    pid = m.create_position("Pool")["id"]
    table = excel.read_csv(_basis_csv([
        ["Keep the water safe", "1-3 ppm chlorine", WORKING, "Too little chlorine", "Dosing pump fails"],
        ["", "", "", "", "Chlorinator trips"],
        ["Keep the water clear", "", "", "Cloudy", "Filter blocked"],
    ]), "pool.csv")
    opts = rcm_sheet.default_options(table)
    assert opts["mapping"]["standard_basis"] == "Standard working"
    assert opts["mapping"]["standard"] == "Performance standard"
    out = rcm_sheet.run(m, pid, table, opts, dry_run=False)
    assert out["ok"], out["errors"]
    safe, clear = _rcm(m, pid)["functions"]
    assert safe["standard_basis"] == WORKING and safe["standard"] == "1-3 ppm chlorine"
    assert not clear["has_basis"] and clear["standard_basis"] == ""
    _rebuilds_the_same(m)


def test_a_working_over_the_cap_is_a_row_error_and_nothing_is_written(m):
    pid = m.create_position("Pool")["id"]
    table = excel.read_csv(_basis_csv([["Keep the water safe", "", "x" * 20_001, "Too little", "Pump fails"]]), "p.csv")
    out = rcm_sheet.run(m, pid, table, rcm_sheet.default_options(table), dry_run=False)
    assert not out["ok"] and "20,000" in out["errors"][0] and "PDF" in out["errors"][0]
    assert _rcm(m, pid)["functions"] == []


def test_a_different_working_on_an_existing_function_is_left_as_it_is(m):
    pid = m.create_position("Pool")["id"]
    fn = m.add_function(pid, "Keep the water safe", "1-3 ppm", standard_basis="Our own sums")
    table = excel.read_csv(_basis_csv([["Keep the water safe", "1-3 ppm", WORKING, "Too little", "Pump fails"]]), "p.csv")
    out = rcm_sheet.run(m, pid, table, rcm_sheet.default_options(table), dry_run=False)
    assert out["ok"] and any("working" in w for w in out["warnings"])
    [safe] = _rcm(m, pid)["functions"]
    assert safe["id"] == fn["id"] and safe["standard_basis"] == "Our own sums"
