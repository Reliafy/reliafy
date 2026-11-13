"""The asset tree in a spreadsheet (hierarchy.py): export, import, the round trip,
re-importing without duplicates, moves, problems by row, limits, the REST and MCP
ways in."""

import csv
import io

import pytest

from backend.maintenance import hierarchy, service
from backend.maintenance.service import PROJECTORS, Invalid, Maintenance
from backend.maintenance.store import GraphStore

ORG = "org-tree-sheet"


def _m(org=ORG):
    return Maintenance(GraphStore(":memory:", PROJECTORS), org, "tester", time_zone="Australia/Brisbane")


@pytest.fixture()
def m():
    return _m()


def _rebuilds(m):
    before = m.s.snapshot()
    m.s.rebuild()
    assert m.s.snapshot() == before


def _seed(m):
    """A small plant: a site with two units, pumps fitted, locations and classes."""
    site = m.create_location("Site A")
    house = m.create_location("Pump house", parent_id=site["id"], description="North end")
    rot = m.create_item_class("Rotating", code="ROT")
    pump_cls = m.create_item_class("Pump", parent_id=rot["id"], code="PU", description="Any pump")
    plant = m.create_position("Plant 1", tag="P1", description="The main plant", location_id=site["id"])
    unit = m.create_position("Unit 2", parent_id=plant["id"])
    a = m.create_position("Feed pump A", tag="P-101", parent_id=unit["id"], position_class="Centrifugal pump",
                          location_id=house["id"])
    b = m.create_position("Feed pump B", tag="P-102", parent_id=unit["id"], position_class="Centrifugal pump")
    m.create_position("I/O panel", parent_id=plant["id"])
    item = m.create_item("KSB Etanorm 50", serial="SN-1", part_number="ETN-50", manufacturer="KSB", model="Etanorm")
    m.fit(a["id"], item_id=item["id"], on="2023-04-01")
    m.assign_item_class(item["id"], pump_cls["id"])
    m.fit(b["id"], new_item={"name": "Spare pump", "serial": "SN-2"}, on="2022")
    m.create_position("Plant 2")
    return {"plant": plant["id"], "unit": unit["id"], "a": a["id"], "b": b["id"], "item": item["id"]}


def _sheets(data):
    """export()'s rows as read_file gives a file back (heading: text)."""
    def rows(cols, recs):
        return [(i, {h: r.get(f, "") for f, h, _ in cols}) for i, r in enumerate(recs, start=2)]
    return {"hierarchy": rows(hierarchy.COLUMNS, data["hierarchy"]),
            "locations": rows(hierarchy.LOCATION_COLUMNS, data["locations"]),
            "classes": rows(hierarchy.CLASS_COLUMNS, data["classes"])}


def _without_ids(data):
    """Export rows with ids replaced by the path they stand for (ids differ between workspaces)."""
    paths = {r["id"]: r["path"] for r in data["hierarchy"]}
    out = {}
    for key in ("hierarchy", "locations", "classes"):
        out[key] = [{k: (paths.get(v, v) if k == "parent_id" else "" if k in ("id", "item_id") else v)
                     for k, v in r.items()} for r in data[key]]
    return out


def _events(m):
    return m.s.event_count(m.org)


# ---- export ------------------------------------------------------------------------------------

def test_export_writes_every_column_with_paths_ids_items_and_side_sheets(m):
    ids = _seed(m)
    data = hierarchy.export(m)
    rows = {r["path"]: r for r in data["hierarchy"]}
    assert list(rows) == ["Plant 1", "Plant 1 > I/O panel", "Plant 1 > Unit 2", "Plant 1 > Unit 2 > Feed pump A",
                          "Plant 1 > Unit 2 > Feed pump B", "Plant 2"]
    a = rows["Plant 1 > Unit 2 > Feed pump A"]
    assert a == {"id": ids["a"], "parent_id": ids["unit"], "path": "Plant 1 > Unit 2 > Feed pump A",
                 "name": "Feed pump A", "tag": "P-101", "position_class": "Centrifugal pump", "description": "",
                 "location": "Site A > Pump house", "item_id": ids["item"], "item": "KSB Etanorm 50",
                 "serial": "SN-1", "part_number": "ETN-50", "manufacturer": "KSB", "model": "Etanorm",
                 "item_class": "Rotating > Pump", "installed_on": "2023-04-01"}
    assert rows["Plant 1 > Unit 2 > Feed pump B"]["installed_on"] == "2022"  # a year stays a year
    assert rows["Plant 1"]["location"] == "Site A" and rows["Plant 1"]["parent_id"] == ""
    assert [x["path"] for x in data["locations"]] == ["Site A", "Site A > Pump house"]
    assert [(x["path"], x["code"]) for x in data["classes"]] == [("Rotating", "ROT"), ("Rotating > Pump", "PU")]
    assert data["counts"] == {"positions": 6, "items": 2, "locations": 2, "classes": 2}


def test_branch_export_keeps_full_paths_and_only_what_it_names(m):
    ids = _seed(m)
    data = hierarchy.export(m, ids["unit"])
    assert [r["path"] for r in data["hierarchy"]] == ["Plant 1 > Unit 2", "Plant 1 > Unit 2 > Feed pump A",
                                                       "Plant 1 > Unit 2 > Feed pump B"]
    assert data["hierarchy"][0]["parent_id"] == ids["plant"]
    assert [x["path"] for x in data["locations"]] == ["Site A", "Site A > Pump house"]
    assert data["branch"]["path"] == "Plant 1 > Unit 2"
    # Importing the branch back changes nothing.
    n = _events(m)
    out = hierarchy.run(m, _sheets(data), dry_run=False)
    assert out["ok"] and out["positions_created"] == 0 and _events(m) == n
    assert out["not_in_file"] == 0


def test_xlsx_and_csv_files_read_back_to_the_same_rows(m):
    _seed(m)
    data = hierarchy.export(m)
    book = hierarchy.read_file(hierarchy.to_xlsx(data), "tree.xlsx")
    flat = hierarchy.read_file(hierarchy.to_csv(data), "tree.csv")
    want = _sheets(data)
    assert [r for _, r in book["hierarchy"]] == [r for _, r in want["hierarchy"]]
    assert [r for _, r in book["locations"]] == [r for _, r in want["locations"]]
    assert [r for _, r in book["classes"]] == [r for _, r in want["classes"]]
    assert [r for _, r in flat["hierarchy"]] == [r for _, r in want["hierarchy"]]
    assert flat["locations"] == [] and book["hierarchy"][0][0] == 2
    from openpyxl import load_workbook
    wb = load_workbook(io.BytesIO(hierarchy.to_xlsx(data)))
    assert wb.sheetnames == ["Hierarchy", "Locations", "Classes", "Read me"]
    readme = [row[0] for row in wb["Read me"].iter_rows(values_only=True)]
    assert all(h in readme for h in hierarchy.HEADINGS)
    text = hierarchy.to_csv(data).decode("utf-8-sig")
    assert next(csv.reader(io.StringIO(text))) == hierarchy.HEADINGS


# ---- the round trip ------------------------------------------------------------------------------

@pytest.mark.parametrize("fmt", ["xlsx", "csv"])
def test_round_trip_into_an_empty_workspace_gives_the_same_file(m, fmt):
    _seed(m)
    first = hierarchy.export(m)
    raw = hierarchy.to_xlsx(first) if fmt == "xlsx" else hierarchy.to_csv(first)
    fresh = _m("org-empty")
    sheets = hierarchy.read_file(raw, f"tree.{fmt}")
    dry = hierarchy.run(fresh, sheets, dry_run=True)
    assert dry["ok"], dry["problems"]
    assert (dry["positions_created"], dry["items_created"], dry["locations_created"]) == (6, 2, 2)
    assert dry["classes_created"] == 2
    assert dry["summary"] == "Will create 6 positions, 2 locations, 2 classes and 2 items."
    assert _events(fresh) == 0  # a dry run writes nothing
    done = hierarchy.run(fresh, sheets, dry_run=False)
    assert done["ok"] and not done["dry_run"]
    _rebuilds(fresh)
    second = hierarchy.export(fresh)
    if fmt == "csv":  # a CSV carries the Hierarchy sheet alone: a class's code and a location's description stay behind
        assert _without_ids(second)["hierarchy"] == _without_ids(first)["hierarchy"]
    else:
        assert _without_ids(second) == _without_ids(first)
    # And again: nothing new.
    n = _events(fresh)
    again = hierarchy.run(fresh, hierarchy.read_file(raw, f"tree.{fmt}"), dry_run=False)
    assert again["positions_created"] == again["items_created"] == again["locations_created"] == 0
    assert _events(fresh) == n


def test_reimporting_an_export_is_idempotent_and_says_nothing_changes(m):
    _seed(m)
    sheets = _sheets(hierarchy.export(m))
    n = _events(m)
    out = hierarchy.run(m, sheets, dry_run=False)
    assert out["ok"] and out["positions_unchanged"] == 6
    assert out["summary"] == "Nothing to change: everything in the file is already in Reliafy."
    assert _events(m) == n


# ---- edits in the sheet ---------------------------------------------------------------------------

def test_renames_tags_classes_and_moves_by_path_are_new_events(m):
    ids = _seed(m)
    data = hierarchy.export(m)
    rows = {r["path"]: r for r in data["hierarchy"]}
    rows["Plant 1 > Unit 2 > Feed pump A"]["name"] = "Feed pump A (duty)"
    rows["Plant 1 > Unit 2 > Feed pump A"]["tag"] = "P-101A"
    rows["Plant 1 > Unit 2 > Feed pump B"]["path"] = "Plant 2 > Feed pump B"  # a move
    rows["Plant 1 > Unit 2 > Feed pump B"]["serial"] = "SN-2B"
    rows["Plant 1"]["tag"] = ""  # blank never clears
    dry = hierarchy.run(m, _sheets(data), dry_run=True)
    assert dry["ok"], dry["problems"]
    assert (dry["positions_updated"], dry["positions_moved"], dry["items_updated"]) == (1, 1, 1)
    assert dry["moves"] == [{"row": 6, "name": "Feed pump B", "from": "Plant 1 > Unit 2 > Feed pump B",
                             "to": "Plant 2 > Feed pump B"}]
    assert dry["summary"] == "Will update 1 position, move 1 position and update 1 item."
    hierarchy.run(m, _sheets(data), dry_run=False)
    a = m.position(ids["a"])
    assert (a["name"], a["tag"]) == ("Feed pump A (duty)", "P-101A")
    assert m.s.node(ORG, ids["plant"])["tag"] == "P1"
    assert [p["name"] for p in m.position(ids["b"])["path"]][:1] == ["Plant 2"]
    assert m.current_fitment(ids["b"])["from"].startswith("2022")  # fitments untouched
    types = [e["type"] for e in m.s.events(ORG, 20)]
    assert "position.updated" in types and "item.updated" in types
    _rebuilds(m)


def test_a_sheet_made_by_hand_with_paths_only(m):
    text = ("Path,Tag,Position class,Fitted item,Item serial,Installed on,Location,Item class\n"
            "Mine,,,,,,,\n"
            "Mine > Crusher,CR-1,Crusher,Jaw crusher,JC-9,15/03/2021,Mine site > Plant area,Fixed > Crusher\n"
            "Mine > Conveyor 1,CV-1,Conveyor,,,,Mine site,\n")
    sheets = hierarchy.read_file(text.encode(), "mine.csv")
    dry = hierarchy.run(m, sheets)
    assert dry["ok"], dry["problems"]
    assert (dry["positions_created"], dry["locations_created"], dry["classes_created"], dry["items_created"]) \
        == (3, 2, 2, 1)
    hierarchy.run(m, sheets, dry_run=False)
    crusher = next(p for p in m.s.nodes(ORG, "Position") if p["name"] == "Crusher")
    assert m.current_fitment(crusher["id"])["from"] == "2021-03-15"  # day first when it isn't ISO
    _rebuilds(m)


def test_parent_id_rows_with_their_own_codes(m):
    rows = [{"ID": "A", "Name": "Area A"}, {"ID": "A1", "Parent ID": "A", "Name": "Tank 1"},
            {"ID": "A2", "Parent ID": "A", "Name": "Tank 2"}, {"ID": "A2-M", "Parent ID": "A2", "Name": "Mixer"}]
    sheets = {"hierarchy": hierarchy.rows_from_records(rows)}
    out = hierarchy.run(m, sheets, dry_run=False)
    assert out["positions_created"] == 4
    paths = [r["path"] for r in hierarchy.export(m)["hierarchy"]]
    assert paths == ["Area A", "Area A > Tank 1", "Area A > Tank 2", "Area A > Tank 2 > Mixer"]
    # Again: matched by path (their codes aren't Reliafy ids), nothing new.
    again = hierarchy.run(m, sheets, dry_run=False)
    assert again["positions_created"] == 0 and again["positions_unchanged"] == 4


def test_items_already_fitted_are_left_alone_with_a_note(m):
    ids = _seed(m)
    data = hierarchy.export(m)
    rows = {r["path"]: r for r in data["hierarchy"]}
    a = rows["Plant 1 > Unit 2 > Feed pump A"]
    a.update(item_id="", item="Another pump", serial="SN-9")
    rows["Plant 1 > Unit 2 > Feed pump B"]["installed_on"] = "2020-01-01"
    rows["Plant 1 > I/O panel"].update(item="PLC rack", installed_on="2024-02-01")
    out = hierarchy.run(m, _sheets(data), dry_run=False)
    assert out["ok"] and out["items_created"] == 1
    notes = " ".join(n["text"] for n in out["notes"])
    assert "Another pump wasn't fitted" in notes and "2020-01-01 wasn't applied" in notes
    assert m.current_fitment(ids["a"])["from"] == "2023-04-01"


# ---- problems ----------------------------------------------------------------------------------

def test_problems_are_listed_by_row_and_nothing_is_written(m):
    _seed(m)
    text = ("Path,Name,Installed on,Fitted item,Item class\n"
            "Plant 9 > Unit,,,,\n"                       # 2: missing parent
            "Plant 1 > New,,,,\n"                        # 3
            "Plant 1 > New,,,,\n"                        # 4: duplicate path
            "Plant 1 > Later,,2150-01-01,Pump,\n"        # 5: in the future
            "Plant 1 > Odd,,not a date,Pump,\n"          # 6: not a date
            "Plant 1 > Classy,,,Pump,Rotating > Pump > New kind\n")  # 7: a new class is made, not refused
    sheets = hierarchy.read_file(text.encode(), "bad.csv")
    n = _events(m)
    dry = hierarchy.run(m, sheets, dry_run=True)
    by_row = {p["row"]: p["text"] for p in dry["problems"]}
    assert set(by_row) == {2, 4, 5, 6}
    assert "Plant 9 isn't in the file or in Reliafy" in by_row[2]
    assert "Same path as row 3" in by_row[4]
    assert "in the future" in by_row[5] and "isn't a date" in by_row[6]
    assert dry["classes_created"] == 1 and not dry["ok"]
    assert dry["summary"] == "Fix 4 problems first: nothing is imported until then."
    with pytest.raises(Invalid, match="Nothing imported: 4 problems"):
        hierarchy.run(m, sheets, dry_run=False)
    assert _events(m) == n


def test_a_position_cant_be_moved_inside_itself(m):
    _seed(m)
    data = hierarchy.export(m)
    rows = {r["path"]: r for r in data["hierarchy"]}
    rows["Plant 1 > Unit 2"]["path"] = "Plant 1 > Unit 2 > Feed pump A > Unit 2"
    dry = hierarchy.run(m, _sheets(data))
    assert any("inside itself" in p["text"] for p in dry["problems"])


def test_the_workspace_limit_is_checked_before_anything_is_written(m, monkeypatch):
    _seed(m)
    monkeypatch.setattr(hierarchy, "MAX_POSITIONS", 8)
    rows = [{"Path": f"Plant 3 > P{i}"} for i in range(3)] + [{"Path": "Plant 3"}]
    dry = hierarchy.run(m, {"hierarchy": hierarchy.rows_from_records(rows)})
    assert dry["limits"]["positions"] == {"now": 6, "adding": 4, "max": 8, "room": 2, "fits": False}
    assert any("room for 2" in p["text"] for p in dry["problems"])


def test_positions_not_in_the_file_are_counted_never_deleted(m):
    _seed(m)
    data = hierarchy.export(m)
    data["hierarchy"] = [r for r in data["hierarchy"] if "Feed pump" not in r["path"]]
    out = hierarchy.run(m, _sheets(data), dry_run=False)
    assert out["not_in_file"] == 2
    assert sum(1 for p in m.s.nodes(ORG, "Position") if not p.get("retired")) == 6


def test_paths_with_slashes_in_names():
    assert hierarchy.split_path("Plant > I/O panel") == ["Plant", "I/O panel"]
    assert hierarchy.split_path("Plant / Unit 2 / Pump") == ["Plant", "Unit 2", "Pump"]
    assert hierarchy.split_path("  ") == []


# ---- REST and MCP ------------------------------------------------------------------------------

def test_service_limits_are_the_ones_the_plan_reads():
    assert hierarchy.MAX_POSITIONS == service.MAX_POSITIONS and hierarchy.MAX_ITEMS == service.MAX_ITEMS


UID, OTHER = "user-h", "user-other"


@pytest.fixture()
def api(monkeypatch):
    import mongomock
    from fastapi.testclient import TestClient

    from backend import config, db
    from backend.auth import get_current_user
    from backend.main import app
    from backend.routers import maintenance as router

    monkeypatch.setattr(config, "AUTH_DISABLED", False)
    monkeypatch.setattr(config, "BILLING_ENABLED", False)
    monkeypatch.setattr(config, "MAINTENANCE_ENABLED", True)
    monkeypatch.setattr(config, "MAINTENANCE_EMAILS", {"h@example.org"})
    test_db = mongomock.MongoClient()["maint_tree_sheet"]
    monkeypatch.setattr(db, "_db", test_db)
    monkeypatch.setattr(db, "_simulated", True)
    monkeypatch.setattr(router, "_store", GraphStore(":memory:", PROJECTORS))
    users = {UID: {"uid": UID, "email": "h@example.org", "name": "H", "email_verified": True},
             OTHER: {"uid": OTHER, "email": "o@example.org", "name": "O", "email_verified": True}}
    for u in users.values():
        test_db.users.insert_one({"_id": u["uid"], **{k: v for k, v in u.items() if k != "uid"}})
    who = {"uid": UID}
    app.dependency_overrides[get_current_user] = lambda: users[who["uid"]]
    try:
        yield {"client": TestClient(app), "who": who, "router": router}
    finally:
        app.dependency_overrides.clear()


def test_rest_export_preview_import_and_again(api):
    c = api["client"]
    top = c.post("/api/maintenance/positions", json={"name": "Plant 1", "tag": "P1"}).json()["id"]
    c.post("/api/maintenance/positions", json={"name": "Pump A", "parent_id": top})
    book = c.get("/api/maintenance/hierarchy/export")
    assert book.status_code == 200 and book.headers["content-type"].startswith("application/vnd.openxml")
    assert "attachment" in book.headers["content-disposition"]
    branch = c.get(f"/api/maintenance/hierarchy/export?position_id={top}&format=csv")
    assert branch.status_code == 200 and "Plant 1 > Pump A" in branch.content.decode("utf-8-sig")
    assert c.get("/api/maintenance/hierarchy/export?format=pdf").status_code == 422
    assert c.get("/api/maintenance/hierarchy/export?position_id=nope").status_code == 404
    edited = book.content
    up = lambda raw, name, **form: c.post("/api/maintenance/hierarchy/import",  # noqa: E731
                                          files={"file": (name, raw)}, data=form)
    same = up(edited, "tree.xlsx")  # dry run by default
    assert same.status_code == 200, same.text
    assert same.json()["dry_run"] and same.json()["positions_unchanged"] == 2
    new = b"Path,Tag\nPlant 1 > Pump B,P-2\nPlant 1 > Pump B > Seal,\n"
    preview = up(new, "more.csv")
    assert preview.json()["summary"] == "Will create 2 positions."
    done = up(new, "more.csv", dry_run="false")
    assert done.status_code == 200 and done.json()["positions_created"] == 2
    assert up(new, "more.csv", dry_run="false").json()["positions_created"] == 0
    bad = up(b"Path\nNowhere > X\n", "bad.csv", dry_run="false")
    assert bad.status_code == 422 and "Nothing imported" in bad.json()["detail"]
    assert up(b"\x00\x01garbage", "x.xlsx").status_code == 422
    api["who"]["uid"] = OTHER  # Maintenance isn't on for them: the routes aren't there
    assert c.get("/api/maintenance/hierarchy/export").status_code == 404
    assert up(new, "more.csv").status_code == 404


def test_mcp_list_tree_and_import_history_sheet_tree(env_mcp=None):
    """The maintenance tool's table: list.tree reads it, workspace.import_history with sheet 'tree' writes it."""
    from backend.maintenance import mcp_tools

    _, table = mcp_tools.TABLES["maintenance_workspace"]
    assert table["import_history"][:2] == ("rows", "dry_run sheet")
    _, kinds = mcp_tools.TABLES["maintenance_list"]
    assert kinds["tree"][:2] == ("", "position_id format")
    rows = [{"path": "Plant 1"}, {"Path": "Plant 1 > Pump A", "fitted item": "Pump", "installed on": "2024"}]
    table = hierarchy.rows_from_records([mcp_tools._tree_row(r) for r in rows])
    m = _m("org-mcp")
    out = hierarchy.run(m, {"hierarchy": table}, dry_run=False)
    assert out["positions_created"] == 2 and out["items_created"] == 1
    text = hierarchy.to_csv(hierarchy.export(m)).decode("utf-8-sig")
    again = hierarchy.run(m, {"hierarchy": hierarchy.rows_from_csv(text)}, dry_run=False)
    assert again["positions_unchanged"] == 2
