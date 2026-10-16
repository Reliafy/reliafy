"""Reliafy Maintenance: product structure (#435). Parts made of parts (CONTAINS lines with a
quantity and a ref), indenture levels from the workspace's own list, where a part is used,
quantities rolled up the tree, positions made from a structure, and a BOM imported from CSV
or Excel."""

import io

import mongomock
import pytest

from backend.maintenance import bom, service
from backend.maintenance.service import PROJECTORS, Invalid, LimitReached, Maintenance, NotFound
from backend.maintenance.store import GraphStore
from backend.tests.neo4j_support import plant

ORG = "org-bom"

# Four levels of lines under a system: System > Subsystem > LRU > SRU > Component, with one
# bearing part used in two assemblies (the pump unit and its motor).
FOUR_LEVELS = """NHA,PN,Qty,Nomenclature,Indenture level,Manufacturer,Ref
,SYS-1,,Cooling water system,System,,
SYS-1,PU-1,2,Pump unit,Subsystem,,"P1, P2"
PU-1,MTR-1,1,Motor,LRU,ABB,M1
PU-1,BRG-1,2,Bearing 6205,Component,SKF,"B1, B2"
MTR-1,BRG-1,2,Bearing 6205,Component,SKF,
MTR-1,FAN-1,1,Cooling fan,SRU,,F1
FAN-1,BLD-1,6,Fan blade,Component,,
"""


@pytest.fixture()
def m():
    return Maintenance(GraphStore(":memory:", PROJECTORS), ORG, "tester")


def _rebuilds(m):
    """Replaying the log gives the graph as it is."""
    before = m.s.snapshot()
    m.s.rebuild()
    assert m.s.snapshot() == before


def _import(m, text, dry_run=True, filename="bom.csv"):
    header, rows = bom.table_from_file(text.encode() if isinstance(text, str) else text, filename)
    return bom.run(m, header, rows, dry_run)


def _pid(m, number):
    return next(p["id"] for p in m.parts() if p["part_number"] == number)


def _tree(node):
    """A structure tree as (part number, qty, ref, total, children)."""
    return (node["part_number"], node["qty"], node["ref"], node["total"], [_tree(c) for c in node["children"]])


# ---- the acceptance criteria -------------------------------------------------------------------

def test_a_four_level_bom_imports_from_csv_and_running_it_again_changes_nothing(m):
    dry = _import(m, FOUR_LEVELS)
    assert dry["dry_run"] and dry["ok"] and m.parts() == []  # a dry run writes nothing
    assert dry["columns"] == {"parent": "NHA", "part_number": "PN", "quantity": "Qty", "name": "Nomenclature",
                              "level": "Indenture level", "manufacturer": "Manufacturer", "ref": "Ref"}
    assert dry["counts"] == {"rows": 7, "parts_created": 6, "parts_updated": 0, "lines_added": 6, "lines_changed": 0,
                             "unchanged": 0, "levels_added": 0, "conflicts": 0, "errors": 0}
    done = _import(m, FOUR_LEVELS, dry_run=False)
    assert not done["dry_run"] and done["counts"] == dry["counts"]
    system = m.part_structure(_pid(m, "SYS-1"))
    assert system["counts"] == {"parts": 5, "lines": 6, "depth": 4, "lowest": 2}
    assert _tree(system["tree"]) == (
        "SYS-1", None, "", 1, [
            ("PU-1", 2.0, "P1, P2", 2.0, [
                ("BRG-1", 2.0, "B1, B2", 4.0, []),
                ("MTR-1", 1.0, "M1", 2.0, [
                    ("BRG-1", 2.0, "", 4.0, []),
                    ("FAN-1", 1.0, "F1", 2.0, [("BLD-1", 6.0, "", 12.0, [])])])])])
    motor = m.part(_pid(m, "MTR-1"))
    assert (motor["name"], motor["level"], motor["manufacturer"], motor["used_in"]) == ("Motor", "LRU", "ABB", 1)
    assert [(c["part_number"], c["qty"]) for c in motor["components"]] == [("BRG-1", 2.0), ("FAN-1", 1.0)]

    events, graph = m.s.event_count(ORG), m.s.snapshot()
    again = _import(m, FOUR_LEVELS, dry_run=False)
    assert again["ok"] and again["counts"] == {"rows": 7, "parts_created": 0, "parts_updated": 0, "lines_added": 0,
                                               "lines_changed": 0, "unchanged": 6, "levels_added": 0,
                                               "conflicts": 0, "errors": 0}
    assert m.s.event_count(ORG) == events and m.s.snapshot() == graph
    _rebuilds(m)


def test_a_loop_is_refused_with_its_path_named(m):
    _import(m, FOUR_LEVELS, dry_run=False)
    events = m.s.event_count(ORG)
    # A good row and a bad one: the bad one names the loop, and neither is written.
    got = _import(m, "NHA,PN,Qty\nSYS-1,NEW-1,1\nBLD-1,SYS-1,1\n", dry_run=False)
    assert got["dry_run"] and not got["ok"]
    assert got["errors"] == [{"row": 3, "error": "That makes a loop: BLD-1 › SYS-1 › PU-1 › MTR-1 › FAN-1 › BLD-1. "
                                                 "A part can't contain a part it's inside."}]
    assert m.s.event_count(ORG) == events and "NEW-1" not in {p["part_number"] for p in m.parts()}
    # A loop made within the file, and a part named as its own parent.
    within = _import(m, "Parent part number,Part number\nA,B\nB,C\nC,A\n")
    assert "That makes a loop: A › B › C › A." in within["errors"][0]["error"]
    assert _import(m, "NHA,PN\nX,x\n")["errors"] == [{"row": 2, "error": "x can't contain itself."}]
    # Added by hand: the same.
    with pytest.raises(Invalid, match="loop: BLD-1 › SYS-1 › PU-1 › MTR-1 › FAN-1 › BLD-1"):
        m.add_component(_pid(m, "BLD-1"), _pid(m, "SYS-1"))
    with pytest.raises(Invalid, match="can't contain itself"):
        m.add_component(_pid(m, "BLD-1"), _pid(m, "BLD-1"))
    assert m.s.event_count(ORG) == events


def test_where_used_lists_parent_parts_positions_and_items(m):
    _import(m, FOUR_LEVELS, dry_run=False)
    brg = _pid(m, "BRG-1")
    store = m.create_location("Store")["id"]
    plant_ = m.create_position("Plant")["id"]
    de = m.create_position("Drive-end bearing", parent_id=plant_)["id"]
    m.add_position_part(de, brg, role="replacement")
    housing = m.create_position("Spare housing", parent_id=plant_)["id"]
    fitted = m.fit(housing, new_item={"name": "Bearing", "serial": "SN-1", "part_id": brg})["fitted"]["item"]
    spare = m.create_item("Bearing", serial="SN-2", part_id=brg)["id"]
    m.place_item(spare, store)
    typed = m.create_item("Old bearing", serial="SN-0", part_number="brg-1")["id"]  # its number typed in, not linked

    used = m.where_used(brg)
    assert [(p["part_number"], p["qty"], p["ref"]) for p in used["parents"]] == [("MTR-1", 2.0, ""),
                                                                                 ("PU-1", 2.0, "B1, B2")]
    assert [(a["part_number"], a["total"], a["direct"], a["top"]) for a in used["assemblies"]] == [
        ("SYS-1", 8.0, False, True), ("PU-1", 4.0, True, False), ("MTR-1", 2.0, True, False)]
    assert [(p["position"]["name"], p["position"]["path"], p["how"]) for p in used["positions"]] == [
        ("Drive-end bearing", ["Plant"], "listed"), ("Spare housing", ["Plant"], "fitted")]
    assert used["positions"][1]["item"] == {"id": fitted["id"], "name": "Bearing", "serial": "SN-1"}
    assert [(i["serial"], i["linked"], (i["fitted_to"] or {}).get("name"), i["location"]) for i in used["items"]] == [
        ("SN-1", True, "Spare housing", None), ("SN-2", True, None, "Store"), ("SN-0", False, None, None)]
    assert used["items"][2]["id"] == typed
    assert used["counts"] == {"parents": 2, "assemblies": 3, "positions": 2, "items": 3}
    # The top: used nowhere.
    top = m.where_used(_pid(m, "SYS-1"))
    assert top["parents"] == top["assemblies"] == top["positions"] == top["items"] == []
    with pytest.raises(NotFound):
        m.where_used("nope")


def test_quantities_roll_up_for_a_component_shared_by_two_assemblies(m):
    part = lambda number, level="": m.create_part(number, number.title(), unit="each")["id"]  # noqa: E731
    system, drive, gearbox, motor, bearing = (part(n) for n in ("SYSTEM", "DRIVE", "GEARBOX", "MOTOR", "BEARING"))
    m.add_component(gearbox, bearing, 4)
    m.add_component(motor, bearing, 2)
    m.add_component(drive, gearbox, 1)
    m.add_component(drive, motor, 2)
    got = m.add_component(system, drive, 3)
    rolled = {r["part_number"]: (r["total"], r["lowest"]) for r in got["rollup"]}
    # 3 drives x (4 in the gearbox + 2 motors x 2) = 24 bearings.
    assert rolled == {"DRIVE": (3.0, False), "GEARBOX": (3.0, False), "MOTOR": (6.0, False), "BEARING": (24.0, True)}
    assert _tree(got["tree"])[4][0][4] == [("GEARBOX", 1.0, "", 3.0, [("BEARING", 4.0, "", 12.0, [])]),
                                           ("MOTOR", 2.0, "", 6.0, [("BEARING", 2.0, "", 12.0, [])])]
    assert {a["part_number"]: a["total"] for a in m.where_used(bearing)["assemblies"]} == {
        "GEARBOX": 4.0, "MOTOR": 2.0, "DRIVE": 8.0, "SYSTEM": 24.0}
    # Stock on hand, and what's installed across the items of the top part.
    m.adjust_stock(bearing, m.create_location("Store")["id"], 5)
    for serial in ("S1", "S2"):
        m.create_item("System", serial=serial, part_id=system)
    row = next(r for r in m.part_structure(system)["rollup"] if r["part_number"] == "BEARING")
    assert (row["on_hand"], row["installed"]) == (5.0, 48.0)
    # A line changed, then taken out: the totals follow.
    m.update_component(motor, bearing, quantity=3, ref="B1-B3")
    assert {r["part_number"]: r["total"] for r in m.part_structure(system)["rollup"]}["BEARING"] == 30.0
    m.remove_component(gearbox, bearing)
    assert {r["part_number"]: r["total"] for r in m.part_structure(system)["rollup"]}["BEARING"] == 18.0
    assert m.part_structure(gearbox)["rollup"] == [] and m.part(gearbox)["components"] == []
    _rebuilds(m)


def test_positions_from_structure_dry_run_then_for_real(m):
    _import(m, FOUR_LEVELS, dry_run=False)
    system = _pid(m, "SYS-1")
    cooling = m.create_position("Cooling")["id"]
    events = m.s.event_count(ORG)
    dry = m.positions_from_structure(system, cooling, levels=["System", "Subsystem", "LRU"])
    assert dry["dry_run"] and m.s.event_count(ORG) == events  # nothing written
    assert dry["counts"] == {"create": 5, "reuse": 0, "parts_list": 5, "skipped": 0}
    assert dry["levels"] == ["System", "Subsystem", "LRU"]
    assert [(r["path"], r["tag"], r["new"]) for r in dry["positions"]] == [
        ("Cooling › Cooling water system", "", True),
        ("Cooling › Cooling water system › Pump unit 1", "P1", True),
        ("Cooling › Cooling water system › Pump unit 1 › Motor", "M1", True),
        ("Cooling › Cooling water system › Pump unit 2", "P2", True),
        ("Cooling › Cooling water system › Pump unit 2 › Motor", "M1", True)]

    done = m.positions_from_structure(system, cooling, levels=["System", "Subsystem", "LRU"], dry_run=False)
    assert not done["dry_run"] and done["counts"] == dry["counts"]
    top = m.position(done["top"])
    assert top["name"] == "Cooling water system" and [c["name"] for c in top["children"]] == ["Pump unit 1",
                                                                                              "Pump unit 2"]
    pump2 = m.position(top["children"][1]["id"])
    assert pump2["tag"] == "P2" and [(x["role"], x["part"]["part_number"]) for x in pump2["parts_list"]] == [
        ("replacement", "PU-1")]
    motor = m.position(pump2["children"][0]["id"])
    assert motor["name"] == "Motor" and motor["parts_list"][0]["part"]["part_number"] == "MTR-1"
    # The as-designed part now shows where it's used in the register.
    assert [p["position"]["path"][-1] for p in m.where_used(_pid(m, "MTR-1"))["positions"]] == ["Pump unit 1",
                                                                                                "Pump unit 2"]
    # Again: the positions are there, so nothing is made.
    events = m.s.event_count(ORG)
    again = m.positions_from_structure(system, cooling, levels=["System", "Subsystem", "LRU"], dry_run=False)
    assert again["counts"] == {"create": 0, "reuse": 5, "parts_list": 0, "skipped": 0}
    assert m.s.event_count(ORG) == events
    _rebuilds(m)


def test_positions_from_structure_by_the_levels_chosen(m):
    _import(m, FOUR_LEVELS + "PU-1,GRS-1,0.25,Grease,Component,,\n", dry_run=False)
    system = _pid(m, "SYS-1")
    # Only the LRUs: the system and pump units pass through, so a motor for each pump unit.
    got = m.positions_from_structure(system, levels=["lru"])
    assert [(r["path"], r["level"]) for r in got["positions"]] == [("Motor 1", "LRU"), ("Motor 2", "LRU")]
    # Every part: a quarter of a grease tin isn't a position; six fan blades are six.
    every = m.positions_from_structure(system, m.create_position("Area 1")["id"])
    assert every["levels"] is None and every["counts"]["skipped"] == 2  # in each pump unit
    assert {(s["part_number"], s["quantity"]) for s in every["skipped"]} == {("GRS-1", 0.25)}
    names = [r["path"].split(" › ")[-1] for r in every["positions"]]
    assert names.count("Fan blade 6") == 2 and "Fan blade 7" not in names  # one fan per motor, two motors
    assert names.count("Bearing 6205 1") == 4  # in each pump unit, and in each pump unit's motor
    # Inside an item (positions that travel with it).
    item = m.create_item("Pump unit P-100", part_id=_pid(m, "PU-1"))["id"]
    inside = m.positions_from_structure(_pid(m, "PU-1"), item, levels=["LRU", "SRU"], dry_run=False)
    assert inside["under"] == {"id": item, "name": "Pump unit P-100", "kind": "Item"}
    assert [r["path"] for r in inside["positions"]] == ["Pump unit P-100 › Motor", "Pump unit P-100 › Motor › Cooling fan"]
    assert [p["name"] for p in m.item(item)["positions"]] == ["Motor"]
    # Refused: no levels, a level not on the list, a retired position, too many at once.
    with pytest.raises(Invalid, match="at least one"):
        m.positions_from_structure(system, levels=[])
    with pytest.raises(Invalid, match="isn't on the list"):
        m.positions_from_structure(system, levels=["Widget"])
    old = m.create_position("Old")["id"]
    m.retire_position(old)
    with pytest.raises(Invalid, match="retired"):
        m.positions_from_structure(system, old)
    with pytest.raises(NotFound):
        m.positions_from_structure("nope")
    assert len(m.positions_from_structure(system)["positions"]) > 10
    _rebuilds(m)


def test_positions_from_structure_has_a_ceiling(m, monkeypatch):
    big = m.create_part("BIG", "Big")["id"]
    m.add_component(big, m.create_part("BOLT", "Bolt")["id"], 40)
    monkeypatch.setattr(service, "MAX_COPY_NODES", 30)
    with pytest.raises(Invalid, match="more than 30 positions"):
        m.positions_from_structure(big)


def test_indenture_levels_are_the_workspaces_own_list(m):
    assert m.part_levels() == ["System", "Subsystem", "Assembly", "LRU", "SRU", "Component"]
    pump = m.create_part("P-1", "Pump")["id"]
    assert m.set_part_level(pump, "lru")["level"] == "LRU"  # as the list spells it
    with pytest.raises(Invalid, match="isn't on the list of indenture levels"):
        m.set_part_level(pump, "Widget")
    events = m.s.event_count(ORG)
    m.set_part_level(pump, "LRU")
    assert m.s.event_count(ORG) == events  # no change, no event
    # Renamed: the parts at it follow; a case-only change renames too.
    got = m.set_part_levels(["System", "Assembly", "Line-replaceable unit", "component"], {"LRU": "line-replaceable unit"})
    assert [(x["name"], x["parts"]) for x in got["levels"]] == [
        ("System", 0), ("Assembly", 0), ("Line-replaceable unit", 1), ("component", 0)]
    assert m.part(pump)["level"] == "Line-replaceable unit"
    # A level parts are at can't be dropped; nor can one be listed twice, or the list be empty.
    with pytest.raises(Invalid, match="1 part is at Line-replaceable unit"):
        m.set_part_levels(["System"])
    with pytest.raises(Invalid, match="twice"):
        m.set_part_levels(["A", "a"])
    with pytest.raises(Invalid, match="at least one"):
        m.set_part_levels(["", " "])
    with pytest.raises(Invalid, match="isn't on the list now"):
        m.set_part_levels(["X"], {"Nope": "X"})
    m.set_part_levels(["System", "LINE-REPLACEABLE UNIT"])
    assert m.part(pump)["level"] == "LINE-REPLACEABLE UNIT"
    assert m.set_part_level(pump, "")["level"] == ""
    # An import adds a level the list doesn't have to the end of it.
    got = _import(m, "PN,Level\nMOD-1,Module\nMOD-2,module\n", dry_run=False)
    assert got["levels_added"] == ["Module"] and m.part_levels() == ["System", "LINE-REPLACEABLE UNIT", "Module"]
    assert m.part(_pid(m, "MOD-2"))["level"] == "Module"
    _rebuilds(m)


def test_structure_lines_are_checked(m, monkeypatch):
    a, b, c = (m.create_part(n, n)["id"] for n in ("A", "B", "C"))
    m.add_component(a, b, 2, "R1, R2")
    with pytest.raises(Invalid, match="already in A"):
        m.add_component(a, b)
    with pytest.raises(Invalid, match="more than 0"):
        m.add_component(a, c, 0)
    with pytest.raises(Invalid, match="must be a number"):
        m.add_component(a, c, "two")
    with pytest.raises(Invalid, match="isn't in A"):
        m.update_component(a, c, 1)
    with pytest.raises(Invalid, match="isn't in A"):
        m.remove_component(a, c)
    with pytest.raises(NotFound):
        m.add_component(a, "nope")
    events = m.s.event_count(ORG)
    m.update_component(a, b, 2, "R1, R2")
    assert m.s.event_count(ORG) == events  # nothing changed
    monkeypatch.setattr(service, "MAX_COMPONENTS_EACH", 1)
    with pytest.raises(LimitReached):
        m.add_component(a, c)
    monkeypatch.setattr(service, "MAX_COMPONENTS_EACH", 500)
    monkeypatch.setattr(service, "MAX_STRUCTURE_LEVELS", 2)
    with pytest.raises(Invalid, match="at most 2 levels"):
        m.add_component(b, c)
    monkeypatch.setattr(bom, "MAX_STRUCTURE_LEVELS", 2)
    assert "more than 2 levels deep" in _import(m, "NHA,PN\nB,C\n")["errors"][0]["error"]


def test_an_import_fills_in_reports_conflicts_and_adds_up_repeated_lines(m):
    m.create_part("PU-1", "Pump unit", manufacturer="KSB")
    got = _import(m, "Next higher assembly,P/N,Qty,Description,Mfr,Ref Des\n"
                     "PU-1,BLT-1,4,Bolt,,A1\nPU-1,BLT-1,2,Bolt,,A2\n,PU-1,,Pump set,Grundfos,\n"
                     "PU-1,NUT-1,,Nut,,\n", dry_run=False)
    assert got["ok"] and got["counts"]["lines_added"] == 2
    assert got["lines_added"][0] == {"parent": "PU-1", "part_number": "BLT-1", "qty": 6.0, "ref": "A1, A2",
                                     "rows": [2, 3]}
    assert {(x["part_number"], x["field"]) for x in got["conflicts"]} == {("PU-1", "name"), ("PU-1", "manufacturer")}
    pu = m.part(_pid(m, "PU-1"))
    assert (pu["name"], pu["manufacturer"]) == ("Pump unit", "KSB")  # kept as they were
    assert {c["part_number"]: c["qty"] for c in pu["components"]} == {"BLT-1": 6.0, "NUT-1": 1.0}
    # The file says something else now: the line changes, the rest stays.
    again = _import(m, "NHA,PN,Qty\nPU-1,BLT-1,8\n", dry_run=False)
    assert again["counts"]["lines_changed"] == 1 and again["lines_changed"][0]["was"] == {"qty": 6.0, "ref": "A1, A2"}
    assert {c["part_number"]: c["qty"] for c in m.part(_pid(m, "PU-1"))["components"]} == {"BLT-1": 8.0, "NUT-1": 1.0}
    # Rows that can't be read.
    bad = _import(m, "NHA,PN,Qty\nPU-1,,2\nPU-1,X-1,-1\nPU-1,X-2,lots\n")
    assert [e["row"] for e in bad["errors"]] == [2, 3, 4]
    with pytest.raises(Invalid, match="no part number column"):
        _import(m, "Parent,Thing\nA,B\n")
    # A column named by the caller rather than guessed.
    header, rows = bom.table_from_file(b"Assy,Item code\nPU-1,WSH-1\n", "x.csv")
    assert bom.run(m, header, rows, mapping={"part_number": "Item code"})["counts"]["lines_added"] == 1
    _rebuilds(m)


def test_an_excel_bom_imports_like_a_csv(m):
    from openpyxl import Workbook

    wb = Workbook()
    ws = wb.active
    ws.append(["Cooling water system BOM"])  # a title above the header
    ws.append([])
    ws.append(["Next higher assembly", "PN", "Qty", "Nomenclature", "Indenture level"])
    ws.append([None, 100200, None, "Cooling water system", "System"])
    ws.append([100200, 300400, 2, "Pump unit", "Subsystem"])
    ws.append([300400, "MTR-1", 1.0, "Motor", "LRU"])
    ws.append(["MTR-1", "BRG-1", 2, "Bearing", "Component"])
    buf = io.BytesIO()
    wb.save(buf)
    got = _import(m, buf.getvalue(), dry_run=False, filename="bom.xlsx")
    assert got["ok"] and got["counts"]["parts_created"] == 4 and got["counts"]["lines_added"] == 3
    assert {p["part_number"] for p in m.parts()} == {"100200", "300400", "MTR-1", "BRG-1"}  # not "100200.0"
    assert m.part_structure(_pid(m, "100200"))["counts"]["depth"] == 3


# ---- indented BOMs: a level on each row instead of a parent ------------------------------------

# FOUR_LEVELS again, indented: rows in tree order with a level number, no parent column. The
# bearing is in the pump unit after the motor's parts, so its parent is two rows back up.
INDENTED = """Level,PN,Qty,Nomenclature,Indenture level,Manufacturer,Ref
0,SYS-1,,Cooling water system,System,,
1,PU-1,2,Pump unit,Subsystem,,"P1, P2"
2,MTR-1,1,Motor,LRU,ABB,M1
3,BRG-1,2,Bearing 6205,Component,SKF,
3,FAN-1,1,Cooling fan,SRU,,F1
4,BLD-1,6,Fan blade,Component,,
2,BRG-1,2,Bearing 6205,Component,SKF,"B1, B2"
"""
FOUR_LEVELS_TREE = (
    "SYS-1", None, "", 1, [
        ("PU-1", 2.0, "P1, P2", 2.0, [
            ("BRG-1", 2.0, "B1, B2", 4.0, []),
            ("MTR-1", 1.0, "M1", 2.0, [
                ("BRG-1", 2.0, "", 4.0, []),
                ("FAN-1", 1.0, "F1", 2.0, [("BLD-1", 6.0, "", 12.0, [])])])])])


def _relevel(text, levels):
    """INDENTED with its level column swapped for ``levels`` (one per row, in order)."""
    lines = text.strip().split("\n")
    header = lines[0].split(",", 1)[1]
    return "\n".join([f"{levels[0]},{header}"] + [f"{lv},{ln.split(',', 1)[1]}"
                                                  for lv, ln in zip(levels[1:], lines[1:])]) + "\n"


def test_an_indented_bom_by_level_number_makes_the_same_structure_and_reruns_unchanged(m):
    dry = _import(m, INDENTED)
    assert dry["dry_run"] and dry["ok"] and m.parts() == []
    assert dry["format"] == {"id": "levels", "label": "Indented, by level number", "column": "Level"}
    assert dry["columns"] == {"bom_level": "Level", "part_number": "PN", "quantity": "Qty", "name": "Nomenclature",
                              "level": "Indenture level", "manufacturer": "Manufacturer", "ref": "Ref"}
    assert dry["counts"] == {"rows": 7, "parts_created": 6, "parts_updated": 0, "lines_added": 6, "lines_changed": 0,
                             "unchanged": 0, "levels_added": 0, "conflicts": 0, "errors": 0}
    done = _import(m, INDENTED, dry_run=False)
    assert done["ok"] and not done["dry_run"]
    assert _tree(m.part_structure(_pid(m, "SYS-1"))["tree"]) == FOUR_LEVELS_TREE
    assert m.part(_pid(m, "MTR-1"))["level"] == "LRU"  # the indenture text column, as it is
    # Again, as levels from 1, and as the parent-and-child file: all the same lines, nothing written.
    events, graph = m.s.event_count(ORG), m.s.snapshot()
    for text in (INDENTED, _relevel(INDENTED, ["Level", 1, 2, 3, 4, 4, 5, 3]), FOUR_LEVELS):
        again = _import(m, text, dry_run=False)
        assert again["ok"] and again["counts"]["unchanged"] == 6
        assert again["counts"]["parts_created"] + again["counts"]["lines_added"] + again["counts"]["lines_changed"] == 0
    assert m.s.event_count(ORG) == events and m.s.snapshot() == graph
    _rebuilds(m)


@pytest.mark.parametrize("levels, kind", [
    (["Lvl", "0", ".1", "..2", "...3", "...3", "....4", "..2"], "dotted"),
    (["BOM level", "1", ".2", "..3", "...4", "...4", "....5", "..3"], "dotted"),
    (["Indenture", "1", "1.1", "1.1.1", "1.1.1.1", "1.1.1.2", "1.1.1.2.1", "1.1.2"], "outline"),
    (["LCN", "A", "A1", "A1A", "A1A01", "A1A02", "A1A02X", "A1B"], "lcn"),
])
def test_each_indented_format_is_detected_and_makes_the_same_structure(m, levels, kind):
    got = _import(m, _relevel(INDENTED, levels), dry_run=False)
    assert got["ok"], got["errors"]
    assert got["format"]["id"] == kind and got["format"]["column"] == levels[0]
    assert got["counts"]["lines_added"] == 6
    assert _tree(m.part_structure(_pid(m, "SYS-1"))["tree"]) == FOUR_LEVELS_TREE
    again = _import(m, _relevel(INDENTED, levels), dry_run=False)
    assert again["counts"]["unchanged"] == 6 and again["counts"]["lines_added"] == again["counts"]["lines_changed"] == 0


def test_outline_numbers_and_lcns_can_come_in_any_order_but_level_numbers_cannot(m):
    shuffled = "Outline number,PN,Qty\n1.2.1,C,3\n1.1,A,1\n1,TOP,\n1.2,B,2\n"
    got = _import(m, shuffled, dry_run=False)
    assert got["ok"] and got["format"]["id"] == "outline"
    assert _tree(m.part_structure(_pid(m, "TOP"))["tree"]) == (
        "TOP", None, "", 1, [("A", 1.0, "", 1.0, []), ("B", 2.0, "", 2.0, [("C", 3.0, "", 6.0, [])])])
    lcn = _import(m, "LCN,PN\nAB,C\nA,TOP\nAA,X\n", dry_run=False)
    assert lcn["ok"] and {(x["parent"], x["part_number"]) for x in lcn["lines_added"]} == {("TOP", "C"), ("TOP", "X")}
    # Level numbers say where a row is only by the rows above it: a child before its parent is refused.
    events = m.s.event_count(ORG)
    child_first = _import(m, "Level,PN\n2,GRANDCHILD\n0,TOP2\n1,CHILD\n", dry_run=False)
    assert child_first["dry_run"] and child_first["errors"] == [
        {"row": 2, "error": "It's at level 2, but the first row has to be at the top level (0)."}]
    up_then_down = _import(m, "Level,PN\n0,TOP2\n1,CHILD\n0,TOP3\n2,LOST\n")
    assert up_then_down["errors"] == [{"row": 5, "error": "It's at level 2 straight after a row at level 0: a level "
                                                          "is skipped (one level down at a time)."}]
    assert m.s.event_count(ORG) == events


def test_a_level_jump_is_refused_naming_the_row(m):
    jumps = {
        "Level,PN\n1,A\n2,B\n4,C\n3,D\n": (4, "It's at level 4 straight after a row at level 2: a level is skipped "
                                            "(one level down at a time)."),
        "Lvl,PN\n.1,A\n..2,B\n....4,C\n": (4, "It's at level 4 straight after a row at level 2: a level is skipped "
                                            "(one level down at a time)."),
        "Level,PN\n1,A\n1.1,B\n1.1.1.1,C\n": (4, "It's 1.1.1.1, but there's no 1.1.1: that's more than one level "
                                              "below 1.1."),
        "Level,PN\n1,A\n2.1,B\n": (3, "It's 2.1, but there's no 2 to hold it."),
        "LCN,PN\nA,SYS\nA01,PU\nA0101,MTR\nA02,PU2\nA020101,X\n": (
            6, "LCN A020101 is longer than others at its level (A0101): the level between it and A02 is missing."),
        "LCN,PN\nA,SYS\nA01,PU\nB01,X\nB0101,Y\n": (
            4, "LCN B01 doesn't extend any other LCN in the file and is longer than the top's (A): its parent is "
               "missing."),
    }
    for text, (row, error) in jumps.items():
        got = _import(m, text, dry_run=False)
        assert got["dry_run"] and not got["ok"] and got["errors"] == [{"row": row, "error": error}], text
    assert m.parts() == []  # all or nothing
    # Repeated codes, a blank level and a stray value among numbers are row errors too.
    assert _import(m, "Level,PN\n1,A\n1.1,B\n1.1,C\n")["errors"][0]["row"] == 4
    assert _import(m, "LCN,PN\nA,X\na,Y\n")["errors"] == [{"row": 3, "error": "LCN A is on row 2 too."}]
    odd = _import(m, "Level,PN\n0,A\n1,B\n,C\nx,D\n1,E\n")
    assert odd["format"]["id"] == "levels"
    assert odd["errors"] == [{"row": 4, "error": "The level is blank."},
                             {"row": 5, "error": "The level 'x' isn't a whole number (0, 1, 2) like the others."}]


def test_several_top_rows_are_several_top_parts(m):
    got = _import(m, "Level,PN,Qty\n1,PUMP-A,\n2,IMP-1,1\n2,SEAL-1,2\n1,PUMP-B,\n2,IMP-1,1\n1,SPARE-KIT,\n",
                  dry_run=False)
    assert got["ok"] and got["counts"]["parts_created"] == 5 and got["counts"]["lines_added"] == 3
    roots = [p["part_number"] for p in m.parts() if p["components"] and not p["used_in"]]
    assert sorted(roots) == ["PUMP-A", "PUMP-B"]
    assert m.part(_pid(m, "SPARE-KIT"))["components"] == []  # a top row with nothing under it: just a part
    assert {p["part_number"] for p in m.where_used(_pid(m, "IMP-1"))["parents"]} == {"PUMP-A", "PUMP-B"}


def test_an_assembly_listed_twice_says_its_lines_once(m):
    # The motor's bearings, under each pump: one line, not added up. Two rows under one motor do add up.
    text = ("Level,PN,Qty,Ref\n0,SYS,,\n1,PU-A,1,\n2,MTR,1,\n3,BRG,1,B1\n3,BRG,1,B2\n1,PU-B,1,\n2,MTR,1,\n"
            "3,BRG,2,B1\n")
    got = _import(m, text, dry_run=False)
    assert got["ok"]
    assert [x for x in got["lines_added"] if x["part_number"] == "BRG"] == [
        {"parent": "MTR", "part_number": "BRG", "qty": 2.0, "ref": "B1, B2", "rows": [5, 6, 9]}]
    differs = _import(m, text.replace("3,BRG,2,B1", "3,BRG,3,B1"))
    assert differs["errors"] == [{"row": 9, "error": "MTR holds 3 of BRG here, but 2 at row 5: one part has one "
                                                     "structure."}]


def test_levels_name_indenture_only_when_asked(m):
    text = "Level,PN,Indenture level\n0,SYS,\n1,PU,\n2,MTR,Line-replaceable unit\n3,BRG,\n"
    header, rows = bom.table_from_file(text.encode(), "bom.csv")
    plain = bom.run(m, header, rows)
    assert plain["parts_created"] == [{"part_number": "SYS", "name": "SYS"}, {"part_number": "PU", "name": "PU"},
                                      {"part_number": "MTR", "name": "MTR", "level": "Line-replaceable unit"},
                                      {"part_number": "BRG", "name": "BRG"}]
    named = bom.run(m, header, rows, dry_run=False, level_names=m.part_levels())
    assert named["ok"] and named["levels_added"] == ["Line-replaceable unit"]
    assert [m.part(_pid(m, n))["level"] for n in ("SYS", "PU", "MTR", "BRG")] == [
        "System", "Subsystem", "Line-replaceable unit", "LRU"]  # its own text wins
    deep = bom.table_from_file(b"Level,PN\n0,A\n1,B\n2,C\n", "x.csv")
    assert bom.run(m, *deep, level_names=["Top", "Next"])["errors"] == [
        {"row": 4, "error": "It's 2 levels below the top: deeper than the 2 level names."}]
    with pytest.raises(Invalid, match="needs an indented BOM"):
        bom.run(m, *bom.table_from_file(FOUR_LEVELS.encode(), "x.csv"), level_names=["System"])
    # A parent-and-child file's numeric level column isn't taken for indenture level names.
    got = _import(m, "NHA,PN,Level\n,TOP,0\nTOP,KID,1\n")
    assert got["format"]["id"] == "parent" and "level" not in got["columns"] and got["counts"]["levels_added"] == 0
    _rebuilds(m)


def test_an_indented_bom_from_excel_and_from_rows(m):
    from openpyxl import Workbook

    wb = Workbook()
    ws = wb.active
    ws.append(["Pump set, indented BOM"])
    ws.append([])
    ws.append(["Level", "Part number", "Qty", "Description"])
    ws.append([1, 100200, None, "Pump set"])  # numbers, as Excel keeps them
    ws.append([2.0, 300400, 2, "Pump unit"])
    ws.append([3, "MTR-1", 1, "Motor"])
    ws.append([4, "BRG-1", 2, "Bearing"])
    ws.append([3, "SEAL-1", 1, "Seal"])
    buf = io.BytesIO()
    wb.save(buf)
    got = _import(m, buf.getvalue(), dry_run=False, filename="bom.xlsx")
    assert got["ok"] and got["format"]["id"] == "levels"
    assert got["counts"]["parts_created"] == 5 and got["counts"]["lines_added"] == 4
    assert {p["part_number"] for p in m.parts()} == {"100200", "300400", "MTR-1", "BRG-1", "SEAL-1"}
    assert m.part_structure(_pid(m, "100200"))["counts"]["depth"] == 3
    assert _import(m, buf.getvalue(), dry_run=False, filename="bom.xlsx")["counts"]["unchanged"] == 4
    # Rows given directly (the MCP tool's), outline numbers in any order.
    header, rows = bom.table_from_rows([{"level": "1.1", "part number": "300400", "qty": 3},
                                        {"level": 1, "part number": "100200"}])
    again = bom.run(m, header, rows, dry_run=False)
    assert again["format"]["id"] == "outline" and again["counts"]["lines_changed"] == 1
    _rebuilds(m)


def test_the_shared_plants_structure_reads_back_and_rebuilds(m):
    """The plant the graph and Neo4j tests share carries a structure too."""
    p = plant(m)
    got = m.part_structure(p["part"])
    assert {r["part_number"]: r["total"] for r in got["rollup"]} == {"M-200": 1.0, "B-6205": 4.0, "S-10": 1.0}
    assert m.part(p["motor"])["level"] == "Line-replaceable unit"
    assert [x["part_number"] for x in m.where_used(p["seal"])["parents"]] == ["M-200"]
    assert got["items"] == 2  # the items made from the pump part
    _rebuilds(m)


# ---- the app's routes ------------------------------------------------------------------------------

@pytest.fixture()
def api(monkeypatch):
    from fastapi.testclient import TestClient

    from backend import config, db
    from backend.auth import get_current_user
    from backend.main import app
    from backend.routers import maintenance as router

    monkeypatch.setattr(config, "AUTH_DISABLED", False)
    monkeypatch.setattr(config, "BILLING_ENABLED", False)
    monkeypatch.setattr(config, "MAINTENANCE_ENABLED", True)
    monkeypatch.setattr(config, "MAINTENANCE_EMAILS", {"s@example.org"})
    test_db = mongomock.MongoClient()["maint_structure_api"]
    monkeypatch.setattr(db, "_db", test_db)
    monkeypatch.setattr(db, "_simulated", True)
    monkeypatch.setattr(router, "_store", GraphStore(":memory:", PROJECTORS))
    user = {"uid": "user-s", "email": "s@example.org", "name": "S", "email_verified": True}
    test_db.users.insert_one({"_id": "user-s", "email": "s@example.org", "name": "S", "email_verified": True})
    app.dependency_overrides[get_current_user] = lambda: user
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()


def test_product_structure_through_the_api(api):
    base = "/api/maintenance"
    levels = api.get(f"{base}/parts/levels").json()
    assert [x["name"] for x in levels["levels"]] == levels["default"]
    files = {"file": ("bom.csv", FOUR_LEVELS.encode(), "text/csv")}
    dry = api.post(f"{base}/parts/import-bom", files=files)
    assert dry.status_code == 200 and dry.json()["dry_run"] and dry.json()["counts"]["parts_created"] == 6
    done = api.post(f"{base}/parts/import-bom", files=files, data={"dry_run": "false"}).json()
    assert not done["dry_run"]
    parts = {p["part_number"]: p for p in api.get(f"{base}/parts").json()["parts"]}
    system, motor, brg = parts["SYS-1"]["id"], parts["MTR-1"]["id"], parts["BRG-1"]["id"]
    assert parts["PU-1"]["level"] == "Subsystem" and len(parts["PU-1"]["components"]) == 2
    tree = api.get(f"{base}/parts/{system}/structure").json()
    assert tree["counts"]["depth"] == 4
    loop = api.post(f"{base}/parts/{brg}/structure", json={"child_id": system})
    assert loop.status_code == 422 and "loop" in loop.json()["detail"]
    extra = api.post(f"{base}/parts", json={"part_number": "TB-1", "name": "Terminal box"}).json()
    added = api.post(f"{base}/parts/{motor}/structure", json={"child_id": extra["id"], "quantity": 1, "ref": "TB"})
    assert added.status_code == 200 and "TB-1" in {c["part_number"] for c in added.json()["tree"]["children"]}
    changed = api.patch(f"{base}/parts/{motor}/structure/{extra['id']}", json={"quantity": 2}).json()
    assert {c["part_number"]: c["qty"] for c in changed["tree"]["children"]}["TB-1"] == 2
    assert api.delete(f"{base}/parts/{motor}/structure/{extra['id']}").status_code == 200
    used = api.get(f"{base}/parts/{brg}/where-used").json()
    assert {p["part_number"] for p in used["parents"]} == {"PU-1", "MTR-1"}
    assert api.put(f"{base}/parts/{extra['id']}/level", json={"level": "SRU"}).json()["level"] == "SRU"
    assert api.put(f"{base}/parts/{extra['id']}/level", json={"level": "Nope"}).status_code == 422
    renamed = api.put(f"{base}/parts/levels", json={"levels": ["System", "Subsystem", "LRU", "Shop unit",
                                                               "Component"], "renamed": {"SRU": "Shop unit"}})
    assert renamed.status_code == 200 and api.get(f"{base}/parts/{extra['id']}").json()["level"] == "Shop unit"
    pos = api.post(f"{base}/positions", json={"name": "Cooling"}).json()
    dry_pos = api.post(f"{base}/parts/{system}/structure/positions",
                       json={"parent_id": pos["id"], "levels": ["System", "Subsystem"]}).json()
    assert dry_pos["dry_run"] and dry_pos["counts"]["create"] == 3
    made = api.post(f"{base}/parts/{system}/structure/positions",
                    json={"parent_id": pos["id"], "levels": ["System", "Subsystem"], "dry_run": False}).json()
    assert not made["dry_run"] and api.get(f"{base}/positions/{made['top']}").json()["name"] == "Cooling water system"
    assert api.get(f"{base}/parts/nope/structure").status_code == 404
    bad = api.post(f"{base}/parts/import-bom", files={"file": ("x.csv", b"Thing\nA\n", "text/csv")})
    assert bad.status_code == 422 and "part number column" in bad.json()["detail"]
    mapped = api.post(f"{base}/parts/import-bom", files={"file": ("x.csv", b"Assy,Code\nSYS-1,Z-1\n", "text/csv")},
                      data={"mapping": '{"part_number": "Code", "parent": "Assy"}'}).json()
    assert mapped["counts"]["lines_added"] == 1
    assert api.post(f"{base}/parts/import-bom", files=files, data={"mapping": "[1]"}).status_code == 422
    # An indented BOM: the format detected, and levels named from the list only when asked.
    indented = {"file": ("bom.csv", b"Level,PN\n0,NEW-SYS\n1,NEW-SUB\n", "text/csv")}
    dry = api.post(f"{base}/parts/import-bom", files=indented).json()
    assert dry["format"]["id"] == "levels" and dry["parts_created"][1] == {"part_number": "NEW-SUB",
                                                                          "name": "NEW-SUB"}
    named = api.post(f"{base}/parts/import-bom", files=indented, data={"levels_by_depth": "true"}).json()
    assert named["parts_created"][1]["level"] == "Subsystem"
