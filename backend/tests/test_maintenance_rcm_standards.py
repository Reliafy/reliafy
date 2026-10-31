"""A function's performance standards as a list (Standard nodes the function is
HELD_TO), the standard a functional failure BREACHES, the old single text
kept and shown until a list stands in for it, the split helper (a dry run,
never automatic), and the worksheet's standards. New events only: every graph
rebuilds the same, and older code replays what it knows."""

import pytest

from backend.maintenance import rcm_sheet
from backend.maintenance.service import PROJECTORS, Invalid, Maintenance, NotFound, propose_split
from backend.maintenance.store import GraphStore
from backend.services import excel, rcm_import
from backend.tests.test_maintenance_mcp import UID, _do, _get, _ok, _session, env  # noqa: F401
from backend.tests.test_maintenance_rcm_api import api  # noqa: F401

ORG = "user-a"
M = "/api/maintenance"


@pytest.fixture()
def m():
    return Maintenance(GraphStore(":memory:", PROJECTORS), ORG, "tester")


def _rebuilds_the_same(m):
    before = m.s.snapshot()
    m.s.rebuild()
    assert m.s.snapshot() == before


def _events(m, type):
    return [e for e in m.s.events(ORG, 5000) if e["type"] == type]


def _fn(m, fn_id):
    return m.function(fn_id)


# ---- the list ---------------------------------------------------------------------------

def test_a_function_holds_several_standards_and_its_old_text_becomes_the_first(m):
    pool = m.create_position("Pool")
    fn = m.add_function(pool["id"], "Keep the water balanced", "pH 7.2-7.8")
    assert fn["standards"] == [] and fn["standard"] == "pH 7.2-7.8" and fn["legacy_standard"] == ""
    ta = m.add_standard(fn["id"], "Total alkalinity 80-120 ppm", parameter="TA", comparator="between",
                        value="80-120", unit="ppm", source="E25 manual")
    assert ta["parameter"] == "TA" and ta["comparator"] == "between" and ta["value"] == "80-120"
    assert ta["unit"] == "ppm" and ta["source"] == "E25 manual" and ta["when"] is None and ta["order"] == 2
    view = _fn(m, fn["id"])
    assert [st["text"] for st in view["standards"]] == ["pH 7.2-7.8", "Total alkalinity 80-120 ppm"]
    assert view["standard"] == "pH 7.2-7.8; Total alkalinity 80-120 ppm"  # derived: one line for older readers
    assert view["legacy_standard"] == "pH 7.2-7.8" and view["standards_without_failure"] == 2
    assert m.s.node(ORG, fn["id"])["standard"] == "pH 7.2-7.8"  # the text itself stays
    # The same text again is the same standard; a change goes on the standard.
    assert m.add_standard(fn["id"], "  total ALKALINITY 80-120 ppm ")["id"] == ta["id"]
    changed = m.update_standard(ta["id"], text="Total alkalinity 80-120 ppm", when="while the filter pump runs",
                                source="")
    assert changed["when"] == "while the filter pump runs" and changed["source"] is None
    hardness = m.add_standard(fn["id"], "Calcium hardness 200-400 ppm", value=300)
    assert hardness["value"] == 300
    # Order: the list as given.
    m.reorder_standards(fn["id"], [hardness["id"], ta["id"], view["standards"][0]["id"]])
    assert [st["text"][:3] for st in _fn(m, fn["id"])["standards"]] == ["Cal", "Tot", "pH "]
    with pytest.raises(Invalid):
        m.reorder_standards(fn["id"], [hardness["id"]])
    # The single text can't be edited round the list.
    with pytest.raises(Invalid, match="list of performance standards"):
        m.update_function(fn["id"], standard="something else")
    m.update_function(fn["id"], text="Keep the water balanced always")  # the words still can
    # Refusals.
    with pytest.raises(Invalid):
        m.add_standard(fn["id"], "")
    with pytest.raises(Invalid):
        m.add_standard(fn["id"], "x", comparator="≈")
    with pytest.raises(Invalid):
        m.add_standard(fn["id"], "x", value=True)
    with pytest.raises(NotFound):
        m.update_standard("nope", text="x")
    # Removed: gone from the list, kept in the log.
    gone = m.remove_standard(hardness["id"])
    assert gone["removed"] == hardness["id"] and gone["failures_unlinked"] == 0
    assert [st["text"][:3] for st in _fn(m, fn["id"])["standards"]] == ["Tot", "pH "]
    with pytest.raises(Invalid, match="removed"):
        m.update_standard(hardness["id"], text="x")
    _rebuilds_the_same(m)


def test_a_functional_failure_breaches_one_standard_or_the_whole_function(m):
    pool = m.create_position("Pool")
    fn = m.add_function(pool["id"], "Keep the water balanced")
    ph = m.add_standard(fn["id"], "pH 7.2-7.8")
    ta = m.add_standard(fn["id"], "Total alkalinity 80-120 ppm")
    high = m.add_functional_failure(fn["id"], "pH above 7.8", standard_id=ph["id"])
    assert high["standard"] == {"id": ph["id"], "text": "pH 7.2-7.8"}
    none = m.add_functional_failure(fn["id"], "Water unusable")
    assert none["standard"] is None
    view = _fn(m, fn["id"])
    assert [(st["text"], st["failures"]) for st in view["standards"]] == [("pH 7.2-7.8", 1), ("Total alkalinity 80-120 ppm", 0)]
    assert view["standards_without_failure"] == 1
    # Re-pointed, cleared, and refused for another function's standard.
    moved = m.update_functional_failure(high["id"], standard_id=ta["id"])
    assert moved["standard"]["id"] == ta["id"] and moved["text"] == "pH above 7.8"
    assert m.update_functional_failure(high["id"], text="pH above 7.8", standard_id=None)["standard"] is None
    other = m.add_function(pool["id"], "Contain the water")
    theirs = m.add_standard(other["id"], "No leak")
    with pytest.raises(Invalid, match="another function"):
        m.update_functional_failure(high["id"], standard_id=theirs["id"])
    with pytest.raises(Invalid):
        m.add_functional_failure(fn["id"], "x", standard_id="nope")
    # A removed standard leaves its failures breaching the whole function.
    m.update_functional_failure(high["id"], standard_id=ph["id"])
    assert m.remove_standard(ph["id"])["failures_unlinked"] == 1
    assert m.functional_failure(high["id"])["standard"] is None
    # The bulk read carries the same.
    [p] = [p for p in m.rcm_all()["positions"] if p["id"] == pool["id"]]
    kept = p["functions"][0]
    assert [st["text"] for st in kept["standards"]] == ["Total alkalinity 80-120 ppm"]
    assert kept["failures"][0]["standard"] is None and kept["standards_without_failure"] == 1
    # The position is analysed on decisions alone: a standard with no failure is no gate.
    mode = m.add_failure_mode(pool["id"], "Acid under-dosed", functional_failure_id=high["id"])
    m.decide_failure_mode(mode["id"], "operational", {"outcome": "rtf", "rtf_basis": "random"})
    m.remove_functional_failure(none["id"])
    m.remove_function(other["id"])
    assert m.rcm_worksheet(pool["id"], "this")["positions"][0]["analysed"]
    _rebuilds_the_same(m)


def test_removing_a_function_takes_its_standards_and_copying_keeps_them(m):
    pool = m.create_position("Pool")
    fn = m.add_function(pool["id"], "Keep the water balanced", "pH 7.2-7.8")
    ta = m.add_standard(fn["id"], "Total alkalinity 80-120 ppm", when="in summer")
    ff = m.add_functional_failure(fn["id"], "Alkalinity low", standard_id=ta["id"])
    copy = m.copy_position(pool["id"], "Pool B")
    [p] = m.rcm_worksheet(copy["id"], "this")["positions"]
    cfn = p["functions"][0]
    assert [st["text"] for st in cfn["standards"]] == ["pH 7.2-7.8", "Total alkalinity 80-120 ppm"]
    assert cfn["standards"][1]["when"] == "in summer" and cfn["standards"][1]["id"] != ta["id"]
    assert cfn["failures"][0]["standard"]["text"] == "Total alkalinity 80-120 ppm"
    assert cfn["failures"][0]["standard"]["id"] == cfn["standards"][1]["id"]
    # Moved: the standards go with the function (they hang off it).
    other = m.create_position("Other")
    m.move_function(fn["id"], other["id"])
    assert [st["text"] for st in _fn(m, fn["id"])["standards"]] == ["pH 7.2-7.8", "Total alkalinity 80-120 ppm"]
    assert m.functional_failure(ff["id"])["standard"]["id"] == ta["id"]
    # Removed with the function.
    m.remove_function(fn["id"])
    assert len(_events(m, "standard.removed")) == 2
    with pytest.raises(Invalid):
        m.update_standard(ta["id"], text="x")
    _rebuilds_the_same(m)


def test_splitting_proposes_and_never_writes_on_its_own(m):
    assert propose_split("pH 7.4-7.6 (7.2-7.8 limits); total alkalinity 80-120 ppm;\nLSI -0.3 to +0.3; ") == [
        "pH 7.4-7.6 (7.2-7.8 limits)", "total alkalinity 80-120 ppm", "LSI -0.3 to +0.3"]
    assert propose_split("") == [] and propose_split(None) == []
    pool = m.create_position("Pool")
    fn = m.add_function(pool["id"], "Keep the water sanitised", "FC 1-3 ppm; CC < 0.5 ppm; given the pump runs")
    events = m.s.event_count(ORG)
    out = m.split_standard(fn["id"])
    assert out["dry_run"] and [x["text"] for x in out["proposed"]] == ["FC 1-3 ppm", "CC < 0.5 ppm", "given the pump runs"]
    assert m.s.event_count(ORG) == events
    # The user's edited lines, dry run still unless told otherwise.
    lines = [{"text": "FC 1-3 ppm", "when": "while the filter pump runs"}, {"text": "CC < 0.5 ppm", "source": "AS 3633"}]
    assert m.split_standard(fn["id"], lines)["dry_run"] and m.s.event_count(ORG) == events
    with pytest.raises(Invalid, match="twice"):
        m.split_standard(fn["id"], [{"text": "a"}, {"text": "A"}], dry_run=False)
    with pytest.raises(Invalid):
        m.split_standard(fn["id"], [{"text": ""}], dry_run=False)
    with pytest.raises(Invalid):
        m.split_standard(fn["id"], "not a list", dry_run=False)
    done = m.split_standard(fn["id"], lines, dry_run=False)
    assert not done["dry_run"]
    assert [(st["text"], st["when"], st["source"]) for st in done["standards"]] == [
        ("FC 1-3 ppm", "while the filter pump runs", None), ("CC < 0.5 ppm", None, "AS 3633")]
    assert done["standard"] == "FC 1-3 ppm; CC < 0.5 ppm"
    assert done["legacy_standard"] == "FC 1-3 ppm; CC < 0.5 ppm; given the pump runs"  # the text itself stays
    with pytest.raises(Invalid, match="already"):
        m.split_standard(fn["id"])
    bare = m.add_function(pool["id"], "Contain the water")
    with pytest.raises(Invalid, match="no performance standard text"):
        m.split_standard(bare["id"])
    _rebuilds_the_same(m)


def test_older_code_shows_the_function_without_the_list(tmp_path):
    path = str(tmp_path / "g.sqlite")
    m = Maintenance(GraphStore(path, PROJECTORS), ORG, "tester")
    pool = m.create_position("Pool")
    fn = m.add_function(pool["id"], "Keep the water balanced", "pH 7.2-7.8")
    ta = m.add_standard(fn["id"], "Total alkalinity 80-120 ppm")
    ff = m.add_functional_failure(fn["id"], "Alkalinity low", standard_id=ta["id"])
    m.update_functional_failure(ff["id"], text="Alkalinity below 80 ppm", standard_id=None)
    m.remove_standard(ta["id"])
    from backend.maintenance.service import _functional_failure_added, _patch
    older = {k: v for k, v in PROJECTORS.items() if not k.startswith("standard.")}
    older["functional_failure.updated"] = _patch
    older["functional_failure.added"] = lambda s, org, p: _functional_failure_added(s, org, {k: v for k, v in p.items() if k != "standard_id"})
    m.s._conn.close()
    old = GraphStore(path, older)
    old.rebuild()
    node = old.node(ORG, fn["id"])
    assert node["standard"] == "pH 7.2-7.8" and old.out(ORG, fn["id"], "HELD_TO") == []
    assert old.node(ORG, ff["id"])["text"] == "Alkalinity below 80 ppm"
    # Two standards were added (the old text became the first), one removed: passed over, logged.
    assert [x["why"] for x in old.skipped()] == ["UnknownEvent in standard.added"] * 2 + ["UnknownEvent in standard.removed"]


# ---- the worksheet --------------------------------------------------------------------------

HEADER = ["Function", "Performance standard", "Functional failure", "Failure mode", "Consequence", "Decision"]
OPTIONS = {"mapping": {"function": "Function", "standard": "Performance standard", "failure": "Functional failure",
                       "mode": "Failure mode", "consequence": "Consequence", "outcome": "Decision"}}


def _sheet(rows):
    text = ",".join(HEADER) + "\n" + "\n".join(",".join(r) for r in rows) + "\n"
    return excel.read_csv(text.encode(), "rcm.csv")


ROWS = [
    ["Keep the water balanced", "pH 7.2-7.8", "", "", "", ""],
    ["", "Total alkalinity 80-120 ppm", "", "", "", ""],
    ["", "pH 7.2-7.8", "pH above 7.8", "Acid under-dosed", "Operational", "Run to failure"],
    ["", "", "", "Stabiliser low", "Operational", "Run to failure"],
    ["", "Total alkalinity 80-120 ppm", "Alkalinity low", "Buffer not dosed", "Operational", "Run to failure"],
    ["", "", "Water unusable", "Everything wrong", "Operational", "Run to failure"],
    ["Contain the water", "No leak", "Leaks", "Liner torn", "Operational", "Run to failure"],
]


def test_the_parser_lists_a_functions_standards_and_each_failures_breach():
    built = rcm_import.build_tree(HEADER, [r for r in ROWS], OPTIONS)
    balanced, contain = built["functions"]
    assert balanced["standards"] == ["pH 7.2-7.8", "Total alkalinity 80-120 ppm"] and balanced["standard"] == "pH 7.2-7.8"
    assert [(f["text"], f.get("breaches")) for f in balanced["failures"]] == [
        ("pH above 7.8", "pH 7.2-7.8"), ("Alkalinity low", "Total alkalinity 80-120 ppm"), ("Water unusable", None)]
    assert contain["standards"] == ["No leak"] and contain["failures"][0].get("breaches") is None  # one standard: no link


def test_the_import_adds_standards_once_and_links_breaches(m):
    pid = m.create_position("Pool")["id"]
    out = rcm_sheet.run(m, pid, _sheet(ROWS), OPTIONS, dry_run=False)
    assert out["ok"] and out["counts"]["standards"] == 2 and out["counts"]["functions"] == 2
    [p] = m.rcm_worksheet(pid, "this")["positions"]
    balanced, contain = p["functions"]
    assert [st["text"] for st in balanced["standards"]] == ["pH 7.2-7.8", "Total alkalinity 80-120 ppm"]
    assert [(f["text"], (f["standard"] or {}).get("text")) for f in balanced["failures"]] == [
        ("pH above 7.8", "pH 7.2-7.8"), ("Alkalinity low", "Total alkalinity 80-120 ppm"), ("Water unusable", None)]
    assert contain["standards"] == [] and contain["standard"] == "No leak"  # one standard: the one text, as before
    events = m.s.event_count(ORG)
    again = rcm_sheet.run(m, pid, _sheet(ROWS), OPTIONS, dry_run=False)
    assert again["ok"] and again["counts"]["standards"] == 0 and m.s.event_count(ORG) == events
    # Onto a function that had the one text: it becomes the first item, the sheet's beside it.
    other = m.create_position("Pool 2")["id"]
    fn = m.add_function(other, "Keep the water balanced", "pH 7.4-7.6")
    out = rcm_sheet.run(m, other, _sheet(ROWS[:5]), OPTIONS, dry_run=False)
    assert out["ok"] and out["counts"]["standards"] == 2
    assert [st["text"] for st in _fn(m, fn["id"])["standards"]] == ["pH 7.4-7.6", "pH 7.2-7.8", "Total alkalinity 80-120 ppm"]
    assert any("went beside it" in w for w in out["warnings"])
    _rebuilds_the_same(m)


# ---- MCP, the batch and the routes -----------------------------------------------------------

def test_over_mcp_and_the_batch(env):
    async def flow(client):
        pool = _ok(await _do(client, "maintenance_positions", "create", name="Pool"))
        fn = _ok(await _do(client, "maintenance_failure_modes", "add_function", position_id=pool["id"],
                           text="Keep the water balanced", standard="pH 7.2-7.8"))
        ta = _ok(await _do(client, "maintenance_failure_modes", "add_standard", function_id=fn["id"],
                           text="Total alkalinity 80-120 ppm", unit="ppm", comparator="between", value="80-120"))
        ff = _ok(await _do(client, "maintenance_failure_modes", "add_functional_failure", function_id=fn["id"],
                           text="Alkalinity low", standard_id=ta["id"]))
        cleared = _ok(await _do(client, "maintenance_failure_modes", "update_functional_failure",
                                functional_failure_id=ff["id"], standard_id="none"))
        read = _ok(await _get(client, "function", fn["id"]))
        refused = await _do(client, "maintenance_failure_modes", "update_function", function_id=fn["id"], standard="x")
        sanitised = _ok(await _do(client, "maintenance_failure_modes", "add_function", position_id=pool["id"],
                                  text="Keep the water sanitised", standard="FC 1-3 ppm; CC < 0.5 ppm"))
        proposed = _ok(await _do(client, "maintenance_failure_modes", "split_standard", function_id=sanitised["id"]))
        split = _ok(await _do(client, "maintenance_failure_modes", "split_standard", function_id=sanitised["id"],
                              standards=[{"text": "FC 1-3 ppm"}, {"text": "CC < 0.5 ppm"}], dry_run=False))
        batch = _ok(await client.call_tool("maintenance_apply", {"operations": [
            {"ref": "s", "do": "failure_modes.add_standard", "args": {"function_id": fn["id"], "text": "LSI -0.3 to +0.3"}},
            {"do": "failure_modes.update_standard", "args": {"standard_id": "@s", "source": "Langelier"}},
        ]}))
        no_batch = await client.call_tool("maintenance_apply", {"operations": [
            {"do": "failure_modes.split_standard", "args": {"function_id": fn["id"]}}]})
        needs_confirm = await client.call_tool("maintenance_apply", {"operations": [
            {"do": "failure_modes.remove_standard", "args": {"standard_id": ta["id"]}}]})
        return fn, ta, ff, cleared, read, refused, proposed, split, batch, no_batch, needs_confirm

    fn, ta, ff, cleared, read, refused, proposed, split, batch, no_batch, needs_confirm = _session(env["token"], flow)
    assert ta["order"] == 2 and ta["unit"] == "ppm"
    assert ff["standard"]["id"] == ta["id"] and cleared["standard"] is None
    assert [st["text"] for st in read["standards"]] == ["pH 7.2-7.8", "Total alkalinity 80-120 ppm"]
    assert read["standard"] == "pH 7.2-7.8; Total alkalinity 80-120 ppm"
    assert refused.is_error and "list of performance standards" in refused.content[0].text
    assert proposed["dry_run"] and [x["text"] for x in proposed["proposed"]] == ["FC 1-3 ppm", "CC < 0.5 ppm"]
    assert not split["dry_run"] and [st["text"] for st in split["standards"]] == ["FC 1-3 ppm", "CC < 0.5 ppm"]
    assert batch["ok"] and batch["undo"][-1]["do"] == "failure_modes.remove_standard"
    assert batch["undo"][-1]["confirm"] == "LSI -0.3 to +0.3"
    assert no_batch.is_error and "isn't allowed in a batch" in no_batch.content[0].text
    assert needs_confirm.is_error and "confirm 'Total alkalinity 80-120 ppm'" in needs_confirm.content[0].text


def test_over_the_routes(api):
    pool = api.post(f"{M}/positions", json={"name": "Pool"}).json()
    fn = api.post(f"{M}/positions/{pool['id']}/functions", json={"text": "Keep the water balanced", "standard": "pH 7.2-7.8"}).json()
    r = api.post(f"{M}/functions/{fn['id']}/standards", json={"text": "Total alkalinity 80-120 ppm", "unit": "ppm"})
    assert r.status_code == 200, r.text
    ta = r.json()
    r = api.patch(f"{M}/standards/{ta['id']}", json={"when": "in summer", "value": 100})
    assert r.status_code == 200 and r.json()["when"] == "in summer" and r.json()["value"] == 100
    r = api.post(f"{M}/functions/{fn['id']}/failures", json={"text": "Alkalinity low", "standard_id": ta["id"]})
    assert r.status_code == 200 and r.json()["standard"]["id"] == ta["id"]
    ff = r.json()
    r = api.patch(f"{M}/functional-failures/{ff['id']}", json={"standard_id": None})
    assert r.status_code == 200 and r.json()["standard"] is None
    r = api.get(f"{M}/functions/{fn['id']}")
    ids = [st["id"] for st in r.json()["standards"]]
    assert len(ids) == 2 and r.json()["standard"] == "pH 7.2-7.8; Total alkalinity 80-120 ppm"
    r = api.put(f"{M}/functions/{fn['id']}/standards/order", json={"standard_ids": ids[::-1]})
    assert r.status_code == 200 and [st["id"] for st in r.json()["standards"]] == ids[::-1]
    r = api.patch(f"{M}/functions/{fn['id']}", json={"standard": "x"})
    assert r.status_code == 422 and "list of performance standards" in r.json()["detail"]
    r = api.get(f"{M}/positions/{pool['id']}/rcm")
    assert [st["text"] for st in r.json()["positions"][0]["functions"][0]["standards"]] == [
        "Total alkalinity 80-120 ppm", "pH 7.2-7.8"]
    other = api.post(f"{M}/positions/{pool['id']}/functions", json={"text": "Keep it clean", "standard": "a; b"}).json()
    r = api.post(f"{M}/functions/{other['id']}/standards/split")
    assert r.status_code == 200 and r.json()["dry_run"] and [x["text"] for x in r.json()["proposed"]] == ["a", "b"]
    r = api.post(f"{M}/functions/{other['id']}/standards/split", json={"standards": [{"text": "a"}, {"text": "b"}], "dry_run": False})
    assert r.status_code == 200 and not r.json()["dry_run"] and len(r.json()["standards"]) == 2
    assert api.delete(f"{M}/standards/{ta['id']}").status_code == 200
    assert api.delete(f"{M}/standards/{ta['id']}").status_code == 422
