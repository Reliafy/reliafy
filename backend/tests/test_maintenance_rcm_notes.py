"""Notes and rationale on every RCM row: a function's, a performance standard's
and a functional failure's set whole by their own event (``<kind>.notes_set``
{id, notes}), a failure mode's its existing ``notes``; carried on every read,
copied with a position, replayed the same, skipped by the code before them;
round-tripped by the RCM / FME(C)A export and the worksheet import; over the
app's routes and the maintenance tool."""

import csv
import io

import matplotlib

matplotlib.use("Agg")

import pytest

from backend.maintenance import fmea_sheet, rcm_sheet
from backend.maintenance.service import LONG_TEXT, PROJECTORS, Invalid, Maintenance
from backend.maintenance.store import GraphStore, new_id
from backend.services import excel
from backend.tests.test_api_tools import A, B, _auth, env, maint  # noqa: F401 - fixtures
from backend.tests.test_maintenance_documents import app, pdf  # noqa: F401 - fixtures

pytestmark = pytest.mark.usefixtures("mcp_on")

ORG = "user-notes"
WHY_FN = "The pool must be safe to swim in.\n\nSet with the council's health officer, 2024."
WHY_STD = "AS 3633 range for public pools.\nBelow 1 ppm germs survive; above 3 ppm eyes sting."
WHY_FF = "Seen twice in the 2023 summer."
WHY_MODE = "The doser's diaphragm cracks after about 18 months."


@pytest.fixture()
def m():
    return Maintenance(GraphStore(":memory:", PROJECTORS), ORG, "tester")


def _events(m, kind):
    return [e for e in m.s.log.since(0, 10_000) if e["type"] == kind]


def _pool(m):
    pid = m.create_position("Pool")["id"]
    fn = m.add_function(pid, "Keep the water sanitised", notes=WHY_FN)
    st = m.add_standard(fn["id"], "Free chlorine 1-3 ppm", notes=WHY_STD)
    m.add_standard(fn["id"], "pH 7.2-7.8")
    ff = m.add_functional_failure(fn["id"], "Free chlorine below 1 ppm", standard_id=st["id"], notes=WHY_FF)
    mode = m.add_failure_mode(pid, "Doser diaphragm cracked", functional_failure_id=ff["id"])
    m.update_failure_mode(mode["id"], notes=WHY_MODE)
    return pid, fn, st, ff, mode


def test_each_kind_sets_reads_and_clears_its_notes_with_its_own_event(m):
    pid, fn, st, ff, mode = _pool(m)
    assert fn["notes"] == WHY_FN and st["notes"] == WHY_STD and ff["notes"] == WHY_FF
    assert [e["payload"] for e in _events(m, "function.notes_set")] == [{"id": fn["id"], "notes": WHY_FN}]
    assert [e["payload"] for e in _events(m, "standard.notes_set")] == [{"id": st["id"], "notes": WHY_STD}]
    assert [e["payload"] for e in _events(m, "functional_failure.notes_set")] == [{"id": ff["id"], "notes": WHY_FF}]
    # The added events are as they always were: notes ride in their own event.
    assert "notes" not in _events(m, "function.added")[0]["payload"]
    assert "notes" not in _events(m, "standard.added")[0]["payload"]
    assert "notes" not in _events(m, "functional_failure.added")[0]["payload"]

    # Every read carries notes on every row kind.
    sheet = m.rcm_worksheet(pid)["positions"][0]["functions"][0]
    assert sheet["notes"] == WHY_FN
    assert [s["notes"] for s in sheet["standards"]] == [WHY_STD, ""]
    assert sheet["failures"][0]["notes"] == WHY_FF and sheet["failures"][0]["modes"][0]["notes"] == WHY_MODE
    bulk = m.rcm_all()["positions"][0]["functions"][0]
    assert bulk["notes"] == WHY_FN and bulk["standards"][0]["notes"] == WHY_STD and bulk["failures"][0]["notes"] == WHY_FF
    assert m.function(fn["id"])["notes"] == WHY_FN and m.function(fn["id"])["failures"][0]["notes"] == WHY_FF
    assert m.failure_mode_rcm(mode["id"])["notes"] == WHY_MODE

    # Changed, unchanged (no event), cleared; line endings become \n, the ends trimmed.
    count = m.s.event_count(ORG)
    m.update_function(fn["id"], notes=WHY_FN)
    m.update_standard(st["id"], notes=f"  {WHY_STD}\n")
    m.update_functional_failure(ff["id"], notes=WHY_FF)
    assert m.s.event_count(ORG) == count
    assert m.update_function(fn["id"], notes="One\r\nTwo\rThree")["notes"] == "One\nTwo\nThree"
    assert m.update_standard(st["id"], notes="")["notes"] == ""
    assert m.update_functional_failure(ff["id"], text="Chlorine low", notes="")["notes"] == ""
    # set_rcm_notes: one call for every kind.
    assert m.set_rcm_notes("standard", st["id"], "Back")["notes"] == "Back"
    assert m.set_rcm_notes("failure_mode", mode["id"], "Mode why")["notes"] == "Mode why"
    with pytest.raises(Invalid, match="kind is"):
        m.set_rcm_notes("task", fn["id"], "x")


def test_the_cap_is_4000_characters_and_a_refusal_changes_nothing(m):
    pid, fn, st, ff, mode = _pool(m)
    assert m.update_function(fn["id"], notes="x" * LONG_TEXT)["notes"] == "x" * LONG_TEXT
    count = m.s.event_count(ORG)
    for call in (lambda: m.update_function(fn["id"], text="New words", notes="x" * (LONG_TEXT + 1)),
                 lambda: m.update_standard(st["id"], notes="x" * (LONG_TEXT + 1)),
                 lambda: m.update_functional_failure(ff["id"], notes="x" * (LONG_TEXT + 1)),
                 lambda: m.add_function(pid, "Another", notes="x" * (LONG_TEXT + 1)),
                 lambda: m.update_failure_mode(mode["id"], notes="x" * (LONG_TEXT + 1))):
        with pytest.raises(Invalid, match="4000"):
            call()
    assert m.s.event_count(ORG) == count  # checked before anything is written


def test_a_copy_carries_them_a_move_keeps_them_and_the_log_replays_the_same(m):
    pid, fn, st, ff, mode = _pool(m)
    copy = m.copy_position(pid, "Pool 2")
    copied = m.rcm_worksheet(copy["id"], "this")["positions"][0]["functions"][0]
    assert copied["id"] != fn["id"] and copied["notes"] == WHY_FN
    assert copied["standards"][0]["notes"] == WHY_STD and copied["failures"][0]["notes"] == WHY_FF
    assert copied["failures"][0]["modes"][0]["notes"] == WHY_MODE
    other = m.create_position("Spa")["id"]
    m.move_function(fn["id"], other)
    assert m.function(fn["id"])["notes"] == WHY_FN
    before = m.s.snapshot()
    m.s.rebuild()
    assert m.s.snapshot() == before


def test_a_cascade_delete_and_its_undo_keep_the_notes(m):
    pid, fn, st, ff, mode = _pool(m)
    m.remove_function(fn["id"], cascade=True)
    m.restore_rcm(fn["id"])
    back = m.rcm_worksheet(pid)["positions"][0]["functions"][0]
    assert back["notes"] == WHY_FN and back["failures"][0]["notes"] == WHY_FF


def test_the_code_before_the_events_skips_them(m):
    pid, fn, st, ff, mode = _pool(m)
    old = GraphStore(":memory:", {k: v for k, v in PROJECTORS.items() if not k.endswith(".notes_set")})
    for e in m.s.log.since(0, 10_000):
        old.log.append({"id": new_id(), "org": e["org"], "type": e["type"], "at": "", "actor": None,
                        "payload": e["payload"]})
    old.sync()
    assert "notes" not in old.node(ORG, fn["id"]) and old.node(ORG, ff["id"])["text"] == ff["text"]
    assert Maintenance(old, ORG, "tester").rcm_worksheet(pid)["positions"][0]["functions"][0]["notes"] == ""


# ---- the export and the worksheet import ----------------------------------------------------

def _csv(rows) -> bytes:
    buf = io.StringIO()
    csv.writer(buf).writerows(rows)
    return buf.getvalue().encode()


def test_the_export_writes_every_kinds_notes_and_the_import_reads_them_back(m):
    pid, fn, st, ff, mode = _pool(m)
    rows = fmea_sheet.rows(m.rcm_worksheet(pid))
    head = rows[0]
    for name in ("Function notes", "Standard notes", "Functional failure notes", "Failure mode notes"):
        assert name in head
    col = {h: i for i, h in enumerate(head)}
    assert [r[col["Function notes"]] for r in rows[1:]].count(WHY_FN) == 1  # on its first row only
    assert [r[col["Standard notes"]] for r in rows[1:]].count(WHY_STD) == 1  # on the standard's own row
    assert [r[col["Functional failure notes"]] for r in rows[1:]].count(WHY_FF) == 1
    assert [r[col["Failure mode notes"]] for r in rows[1:]].count(WHY_MODE) == 1
    assert all(len(r) == len(head) for r in rows)

    # Onto a new position: every note comes back, line breaks and all.
    table = excel.read_csv(_csv(rows), "Pool RCM.csv")
    opts = rcm_sheet.default_options(table)
    assert {"function_notes", "standard_notes", "failure_notes", "notes"} <= set(opts["mapping"])
    assert opts["mapping"]["notes"] == "Failure mode notes" and opts["mapping"]["function"] == "Function"
    fresh = m.create_position("New pool")["id"]
    out = rcm_sheet.run(m, fresh, table, opts, dry_run=False)
    assert out["ok"], out["errors"]
    got = m.rcm_worksheet(fresh, "this")["positions"][0]["functions"][0]
    assert got["notes"] == WHY_FN
    assert [(s["text"], s["notes"]) for s in got["standards"]] == [("Free chlorine 1-3 ppm", WHY_STD), ("pH 7.2-7.8", "")]
    assert got["failures"][0]["notes"] == WHY_FF and got["failures"][0]["modes"][0]["notes"] == WHY_MODE

    # Onto the same position again: nothing to add, nothing written.
    events = m.s.event_count(ORG)
    again = rcm_sheet.run(m, pid, table, opts, dry_run=False)
    assert again["ok"] and m.s.event_count(ORG) == events
    assert not any("notes of its own" in w for w in again["warnings"])


def test_the_import_fills_blank_notes_keeps_others_and_a_single_standard_with_notes_becomes_a_list(m):
    pid = m.create_position("Pump")["id"]
    fn = m.add_function(pid, "Pump water", notes="Ours")
    m.add_functional_failure(fn["id"], "No flow")
    header = ["Function", "Function notes", "Performance standard", "Standard notes", "Functional failure",
              "Functional failure notes", "Failure mode"]
    table = excel.read_csv(_csv([header,
                                 ["Pump water", "Theirs", "", "", "No flow", "Inlet blocks in autumn", "Impeller worn"],
                                 ["Lift water", "", "10 m head", "From the tank height", "Too little head", "", "Seal leaks"]]),
                           "pump.csv")
    out = rcm_sheet.run(m, pid, table, rcm_sheet.default_options(table), dry_run=False)
    assert out["ok"], out["errors"]
    assert any("notes of its own" in w for w in out["warnings"])
    fns = {f["text"]: f for f in m.rcm_worksheet(pid)["positions"][0]["functions"]}
    assert fns["Pump water"]["notes"] == "Ours"  # kept
    assert fns["Pump water"]["failures"][0]["notes"] == "Inlet blocks in autumn"  # was blank: filled
    lift = fns["Lift water"]
    assert [(s["text"], s["notes"]) for s in lift["standards"]] == [("10 m head", "From the tank height")]
    before = m.s.snapshot()
    m.s.rebuild()
    assert m.s.snapshot() == before


def test_the_import_reads_a_standards_notes_from_its_own_row_and_a_functions_from_any_row():
    from backend.services import rcm_import

    header = ["Function", "Function notes", "Performance standard", "Standard notes", "Functional failure",
              "Functional failure notes", "Failure mode", "Notes"]
    rows = [
        ["Dose", "", "1-3 ppm", "AS 3633", "", "", "", ""],
        ["Dose", "", "pH 7.2-7.8", "", "", "", "", ""],
        ["Dose", "Line one\nLine two", "", "", "Low chlorine", "", "Doser fails", "Mode note"],
        [None, "ignored: the first wins", "", "", None, "Failure note", "Tank empty", ""],
    ]
    mapping = {"function": "Function", "function_notes": "Function notes", "standard": "Performance standard",
               "standard_notes": "Standard notes", "failure": "Functional failure",
               "failure_notes": "Functional failure notes", "mode": "Failure mode", "notes": "Notes"}
    built = rcm_import.build_tree(header, rows, {"mapping": mapping}, keep_rows=True)
    fn = built["functions"][0]
    assert fn["notes"] == "Line one\nLine two"
    assert fn["standard_notes"] == {"1-3 ppm": "AS 3633"}
    assert fn["failures"][0]["notes"] == "Failure note" and fn["failures"][0]["modes"][0]["notes"] == "Mode note"
    assert built["counts"]["skipped_rows"] == 0  # a standard's own row with its notes isn't a skipped row
    long = rcm_import.build_tree(header, [["Dose", "x" * 3500, "", "", "", "", "Doser fails", "y" * 3900]],
                                 {"mapping": mapping}, keep_rows=True)["functions"][0]
    assert len(long["notes"]) == 3500 and len(long["modes"][0]["notes"]) == 3900  # notes aren't cut at 2,000


# ---- over the app's routes and the maintenance tool -----------------------------------------

def test_the_apps_routes_take_notes_on_each_kind(app):
    _, client, _ = app
    M = "/api/maintenance"
    pid = client.post(f"{M}/positions", json={"name": "Pool"}).json()["id"]
    fn = client.post(f"{M}/positions/{pid}/functions", json={"text": "Sanitise", "notes": WHY_FN}).json()
    assert fn["notes"] == WHY_FN
    st = client.post(f"{M}/functions/{fn['id']}/standards", json={"text": "1-3 ppm", "notes": WHY_STD}).json()
    assert st["notes"] == WHY_STD
    ff = client.post(f"{M}/functions/{fn['id']}/failures", json={"text": "Low", "notes": WHY_FF}).json()
    assert ff["notes"] == WHY_FF
    assert client.patch(f"{M}/functions/{fn['id']}", json={"notes": "F"}).json()["notes"] == "F"
    assert client.patch(f"{M}/standards/{st['id']}", json={"notes": "S"}).json()["notes"] == "S"
    assert client.patch(f"{M}/functional-failures/{ff['id']}", json={"notes": "X"}).json()["notes"] == "X"
    r = client.patch(f"{M}/functions/{fn['id']}", json={"notes": "x" * (LONG_TEXT + 1)})
    assert r.status_code == 422 and "4000" in r.text
    sheet = client.get(f"{M}/positions/{pid}/rcm").json()["positions"][0]["functions"][0]
    assert (sheet["notes"], sheet["standards"][0]["notes"], sheet["failures"][0]["notes"]) == ("F", "S", "X")
    assert client.get(f"{M}/rcm").json()["positions"][0]["functions"][0]["notes"] == "F"


def test_the_maintenance_tool_takes_notes_on_add_and_update(maint):
    pid = maint.post("/api/v1/maintenance/positions.create", {"name": "Pool"}).json()["id"]
    fn = maint.post("/api/v1/maintenance/failure_modes.add_function",
                    {"position_id": pid, "text": "Sanitise", "notes": WHY_FN})
    assert fn.status_code == 200, fn.text
    fid = fn.json()["id"]
    assert fn.json()["notes"] == WHY_FN
    st = maint.post("/api/v1/maintenance/failure_modes.add_standard",
                    {"function_id": fid, "text": "1-3 ppm", "notes": WHY_STD}).json()
    ff = maint.post("/api/v1/maintenance/failure_modes.add_functional_failure",
                    {"function_id": fid, "text": "Low", "notes": WHY_FF}).json()
    assert st["notes"] == WHY_STD and ff["notes"] == WHY_FF
    assert maint.post("/api/v1/maintenance/failure_modes.update_function",
                      {"function_id": fid, "notes": "F"}).json()["notes"] == "F"
    assert maint.post("/api/v1/maintenance/failure_modes.update_standard",
                      {"standard_id": st["id"], "notes": "S"}).json()["notes"] == "S"
    assert maint.post("/api/v1/maintenance/failure_modes.update_functional_failure",
                      {"functional_failure_id": ff["id"], "notes": "X"}).json()["notes"] == "X"
    sheet = maint.post("/api/v1/maintenance/get.rcm", {"id": pid}).json()["positions"][0]["functions"][0]
    assert (sheet["notes"], sheet["standards"][0]["notes"], sheet["failures"][0]["notes"]) == ("F", "S", "X")
    spec = maint.client.get("/api/v1/openapi.json", headers=_auth(maint.token[A])).json()
    for action in ("add_function", "update_function", "add_standard", "update_standard", "add_functional_failure",
                   "update_functional_failure"):
        assert "notes" in str(spec["paths"][f"/api/v1/maintenance/failure_modes.{action}"]), action
