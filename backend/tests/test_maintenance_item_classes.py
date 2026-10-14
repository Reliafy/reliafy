"""Reliafy Maintenance: item classes (what kind of thing an item is, as a tree with
inherited attributes) and the manufacturer register. Both optional: a workspace that
never uses them sees nothing change."""

import json

import mongomock
import pytest

from backend.maintenance import taxonomy
from backend.maintenance.service import (
    MAX_CLASS_DEPTH, PROJECTORS, Invalid, LimitReached, Maintenance, NotFound, maker_keys,
)
from backend.maintenance.store import GraphStore

ORG = "org-ic"


@pytest.fixture()
def m():
    return Maintenance(GraphStore(":memory:", PROJECTORS), ORG, "tester")


def _pump_tree(m):
    rot = m.create_item_class("Rotating equipment", level="group")
    pump = m.create_item_class("Pump", rot["id"], code="PU", level="class", attributes=[
        {"name": "Flow", "unit": "m3/h"}, {"name": "Head", "unit": "m"}])
    cent = m.create_item_class("Centrifugal", pump["id"], level="type", attributes=[
        {"name": "Shaft seal", "kind": "choice", "options": ["mechanical seal", "packing"]},
        {"name": "Stages", "kind": "number"}, {"name": "Impeller material"}])
    return rot, pump, cent


# ---- the tree ------------------------------------------------------------------------------

def test_a_tree_of_classes_with_paths_codes_and_levels(m):
    rot, pump, cent = _pump_tree(m)
    assert cent["display"] == "Rotating equipment › Pump › Centrifugal"
    assert (pump["code"], pump["level"]) == ("PU", "class")
    tree = m.item_class_tree()
    assert [c["name"] for c in tree["tree"]] == ["Rotating equipment"]
    assert tree["tree"][0]["children"][0]["children"][0]["name"] == "Centrifugal"
    assert tree["counts"]["classes"] == 3
    assert [c["display"] for c in m.item_classes()] == [
        "Rotating equipment", "Rotating equipment › Pump", "Rotating equipment › Pump › Centrifugal"]
    renamed = m.update_item_class(pump["id"], name="Pumps", code="PU-1", level="equipment class")
    assert (renamed["name"], renamed["code"], renamed["level"]) == ("Pumps", "PU-1", "equipment class")
    with pytest.raises(Invalid):
        m.create_item_class("Pumps", rot["id"])  # a sibling of the same name
    with pytest.raises(Invalid):
        m.create_item_class("Pump > Centrifugal")  # > separates a path's levels
    with pytest.raises(NotFound):
        m.create_item_class("Orphan", "nope")


def test_moving_a_class_never_makes_a_cycle(m):
    rot, pump, cent = _pump_tree(m)
    for parent in (pump["id"], cent["id"]):
        with pytest.raises(Invalid, match="inside itself"):
            m.update_item_class(pump["id"], parent_id=parent)
    other = m.create_item_class("Machines")
    moved = m.update_item_class(pump["id"], parent_id=other["id"])
    assert moved["path"] == ["Machines", "Pump"]
    assert m.item_class(cent["id"])["display"] == "Machines › Pump › Centrifugal"
    top = m.update_item_class(pump["id"], parent_id=None)
    assert top["path"] == ["Pump"] and top["parent"] is None


def test_the_tree_is_at_most_so_deep(m):
    parent = None
    for i in range(MAX_CLASS_DEPTH):
        parent = m.create_item_class(f"L{i}", parent and parent["id"])
    with pytest.raises(Invalid, match="levels deep"):
        m.create_item_class("Too deep", parent["id"])
    other = m.create_item_class("Other")
    with pytest.raises(Invalid, match="levels deep"):
        m.update_item_class(m.item_classes()[0]["id"], parent_id=other["id"])


def test_retiring_a_class_needs_it_empty(m):
    rot, pump, cent = _pump_tree(m)
    with pytest.raises(Invalid, match="inside it"):
        m.retire_item_class(pump["id"])
    item = m.create_item("P-101")
    m.assign_item_class(item["id"], cent["id"])
    with pytest.raises(Invalid, match="1 item"):
        m.retire_item_class(cent["id"])
    m.assign_item_class(item["id"], None)
    m.retire_item_class(cent["id"])
    assert "Centrifugal" not in [c["name"] for c in m.item_classes()]
    with pytest.raises(Invalid, match="retired"):
        m.assign_item_class(item["id"], cent["id"])
    # A new class may take a retired one's name.
    assert m.create_item_class("Centrifugal", pump["id"])["name"] == "Centrifugal"


def test_item_classes_are_capped(m, monkeypatch):
    from backend.maintenance import service

    monkeypatch.setattr(service, "MAX_ITEM_CLASSES", 2)
    m.create_item_class("A")
    m.create_item_class("B")
    with pytest.raises(LimitReached):
        m.create_item_class("C")


# ---- attributes ------------------------------------------------------------------------------

def test_attributes_are_inherited_down_the_tree(m):
    rot, pump, cent = _pump_tree(m)
    got = m.item_class(cent["id"])
    assert [(a["name"], a["from"]["name"]) for a in got["attributes"]] == [
        ("Flow", "Pump"), ("Head", "Pump"), ("Shaft seal", "Centrifugal"), ("Stages", "Centrifugal"),
        ("Impeller material", "Centrifugal")]
    assert [a["kind"] for a in got["own_attributes"]] == ["choice", "number", "text"]
    # A child adds its own: it never repeats an inherited one, nor a parent one its children have.
    with pytest.raises(Invalid, match="inherited"):
        m.create_item_class("Split-case", pump["id"], attributes=[{"name": "flow", "unit": "L/s"}])
    with pytest.raises(Invalid, match="twice"):
        m.set_item_class_attributes(pump["id"], [{"name": "Flow", "unit": "m3/h"}, {"name": "Stages"}])
    with pytest.raises(Invalid, match="twice"):
        m.set_item_class_attributes(pump["id"], [{"name": "Flow", "unit": "m3/h"}, {"name": "flow"}])
    with pytest.raises(Invalid, match="options"):
        m.set_item_class_attributes(pump["id"], [{"name": "Drive", "kind": "choice"}])
    with pytest.raises(Invalid, match="kind"):
        m.set_item_class_attributes(pump["id"], [{"name": "Drive", "kind": "colour"}])
    with pytest.raises(Invalid, match="unit"):
        m.set_item_class_attributes(pump["id"], [{"name": "Flow (m3/h)"}])
    # Moving a class under one with the same attribute is refused too.
    other = m.create_item_class("Machines", attributes=[{"name": "Stages", "kind": "number"}])
    with pytest.raises(Invalid, match="twice"):
        m.update_item_class(pump["id"], parent_id=other["id"])
    pump2 = m.set_item_class_attributes(pump["id"], [{"name": "Flow", "unit": "m3/h"}, {"name": "Power", "unit": "kW"}])
    assert [a["name"] for a in pump2["own_attributes"]] == ["Flow", "Power"]


def test_item_attribute_values_are_checked_against_the_class(m):
    rot, pump, cent = _pump_tree(m)
    item = m.create_item("P-101")
    with pytest.raises(Invalid, match="no item class"):
        m.set_item_attributes(item["id"], {"Flow": 45})
    m.assign_item_class(item["id"], cent["id"])
    got = m.set_item_attributes(item["id"], {"Flow": 45, "head": "32 m", "Shaft seal": "Mechanical Seal",
                                             "Stages": "2", "Impeller material": "bronze"})
    values = {a["name"]: a["value"] for a in got["attributes"]}
    assert values == {"Flow": 45.0, "Head": 32.0, "Shaft seal": "mechanical seal", "Stages": 2.0,
                      "Impeller material": "bronze"}
    assert got["item_class"]["via"] == "item" and got["item_class"]["display"].endswith("Centrifugal")
    for bad, why in (({"Flow": "45 L/s"}, "m3/h"), ({"Flow": "lots"}, "number"), ({"Flow": True}, "number"),
                     ({"Shaft seal": "magnetic"}, "one of"), ({"Colour": "red"}, "no attribute"),
                     ({"Stages": "3 stages"}, "no unit"), ({"Flow": 1e15}, "between")):
        with pytest.raises(Invalid, match=why):
            m.set_item_attributes(item["id"], bad)
    # "" clears one; the rest are kept.
    got = m.set_item_attributes(item["id"], {"Impeller material": ""})
    assert {a["name"]: a["value"] for a in got["attributes"]}["Impeller material"] is None
    assert {a["name"]: a["value"] for a in got["attributes"]}["Flow"] == 45.0
    # An attribute taken off the class: its value stays on the item, shown apart.
    m.set_item_class_attributes(pump["id"], [{"name": "Flow", "unit": "m3/h"}])
    got = m.item(item["id"])
    assert got["other_attributes"] == {"Head": 32.0}
    # The free-form nameplate is untouched.
    assert m.update_item(item["id"], nameplate={"Year": "2019"})["nameplate"] == {"Year": "2019"}


def test_an_item_takes_its_part_s_class_unless_it_has_its_own(m):
    rot, pump, cent = _pump_tree(m)
    part = m.create_part("ETN-050-200", "Etanorm 050-032-200", manufacturer="KSB", item_class_id=cent["id"])
    assert part["item_class"]["name"] == "Centrifugal"
    item = m.create_item("P-101", serial="S1")
    assert m.item(item["id"])["item_class"] is None and m.item(item["id"])["part"] is None
    got = m.set_item_part(item["id"], part["id"])
    assert got["part"]["part_number"] == "ETN-050-200"
    assert (got["item_class"]["name"], got["item_class"]["via"]) == ("Centrifugal", "part")
    assert m.set_item_attributes(item["id"], {"Stages": 1})["attributes"][3]["value"] == 1.0
    own = m.assign_item_class(item["id"], pump["id"])
    assert (own["item_class"]["name"], own["item_class"]["via"]) == ("Pump", "item")
    assert own["other_attributes"] == {"Stages": 1.0}
    assert m.part(part["id"])["items"] == 1
    assert m.set_item_part(item["id"], None)["part"] is None


def test_an_item_made_from_a_part_is_linked_to_it(m):
    rot, pump, cent = _pump_tree(m)
    part = m.create_part("ETN-050-200", "Etanorm pump", manufacturer="KSB", item_class_id=cent["id"])
    pid = m.create_position("Cooling water pump A")["id"]
    m.fit(pid, new_item={"part_id": part["id"], "serial": "S1"}, on="2024-01-01")
    first = m.position(pid)["fitted"]["item"]
    assert (first["name"], first["part_number"], first["manufacturer"]) == ("Etanorm pump", "ETN-050-200", "KSB")
    assert m.item(first["id"])["item_class"]["via"] == "part"
    # A replacement made from the part, closing a work order.
    wo = m.open_work_order(pid, "Replace the pump")
    m.close_work_order(wo["id"], actions=[{"kind": "replace", "part_id": part["id"]}], on="2025-01-01")
    second = m.position(pid)["fitted"]["item"]
    assert second["id"] != first["id"]
    assert m.item(second["id"])["part"]["id"] == part["id"]
    assert m.item(second["id"])["item_class"]["name"] == "Centrifugal"


# ---- manufacturers -----------------------------------------------------------------------------

def test_manufacturer_names_match_by_alias_case_and_punctuation_aside(m):
    assert maker_keys("K.S.B.") == ("ksb", "ksb")
    assert maker_keys("KSB AG") == ("ksbag", "ksb")
    assert maker_keys("Grundfós Pumps Pty Ltd")[1] == "grundfospumps"
    ksb = m.create_manufacturer("KSB", aliases=["K.S.B.", "KSB SE & Co. KGaA", "ksb"])
    # "K.S.B." and "ksb" match the name already: only the alias that adds something is kept.
    assert ksb["aliases"] == ["KSB SE & Co. KGaA"]
    assert m.match_manufacturer("k s b")["match"]["id"] == ksb["id"]
    assert m.match_manufacturer("k s b")["how"] == "name"
    assert m.match_manufacturer("KSB se & co kgaa")["how"] == "alias"
    loose = m.match_manufacturer("KSB AG")
    assert (loose["match"]["id"], loose["how"]) == (ksb["id"], "company_form")
    none = m.match_manufacturer("KSBX Industrial")
    assert none["match"] is None and none["candidates"][0]["id"] == ksb["id"]
    assert m.match_manufacturer("Grundfos")["match"] is None
    with pytest.raises(Invalid, match="already in the register"):
        m.create_manufacturer("K-S-B")
    with pytest.raises(Invalid, match="already in the register"):
        m.create_manufacturer("Grundfos", aliases=["KSB"])
    up = m.update_manufacturer(ksb["id"], add_aliases=["KSB Pumps"], remove_aliases=["ksb se & co kgaa"])
    assert up["aliases"] == ["KSB Pumps"]


def test_links_follow_a_merge_and_filters_find_them(m):
    rot, pump, cent = _pump_tree(m)
    ksb = m.create_manufacturer("KSB")
    dup = m.create_manufacturer("K.S.B. Pumps", aliases=["KSB Pompes"])
    part = m.create_part("ETN", "Etanorm", manufacturer_id=dup["id"], item_class_id=cent["id"])
    assert part["manufacturer"] == "K.S.B. Pumps"  # the register's name, none being typed
    a = m.create_item("P-101")
    m.set_item_part(a["id"], part["id"])
    b = m.create_item("P-102", manufacturer="ksb")
    linked = m.link_manufacturer(b["id"], dup["id"])
    assert linked["manufacturer"] == "ksb"  # the typed text stays
    assert linked["manufacturer_entry"]["via"] == "item"
    assert m.item(a["id"])["manufacturer_entry"]["via"] == "part"
    merged = m.merge_manufacturers(dup["id"], ksb["id"])
    assert merged["aliases"] == ["K.S.B. Pumps", "KSB Pompes"]
    assert merged["counts"] == {"items": 2, "parts": 1}
    assert [x["name"] for x in m.manufacturers()] == ["KSB"]
    assert m.match_manufacturer("KSB Pompes")["match"]["id"] == ksb["id"]
    with pytest.raises(Invalid, match="merged"):
        m.link_manufacturer(b["id"], dup["id"])
    assert m.manufacturer(dup["id"])["merged_into"]["id"] == ksb["id"]
    # Filters: by manufacturer (a merged id finds its successor's) and by class with its subtree.
    assert {i["name"] for i in m.items(manufacturer_id=ksb["id"])} == {"P-101", "P-102"}
    assert {i["name"] for i in m.items(manufacturer_id=dup["id"])} == {"P-101", "P-102"}
    c = m.create_item("Valve V1")
    assert [i["name"] for i in m.items(manufacturer_id="none")] == ["Valve V1"]
    assert [i["name"] for i in m.items(item_class_id=rot["id"])] == ["P-101"]
    assert [i["name"] for i in m.items(item_class_id="none")] == ["P-102", "Valve V1"]
    assert [p["part_number"] for p in m.parts(item_class_id=pump["id"], manufacturer_id=ksb["id"])] == ["ETN"]
    assert m.parts(item_class_id=pump["id"], manufacturer_id="none") == []
    tree = m.item_class_tree()
    top = tree["tree"][0]
    assert (top["items"], top["all_items"], top["all_parts"]) == (0, 1, 1)
    assert tree["counts"]["items_classified"] == 1 and m.item(c["id"])["item_class"] is None


def test_linking_by_name_in_bulk_with_a_dry_run(m):
    ksb = m.create_manufacturer("KSB", aliases=["K.S.B."])
    m.create_item("P-101", manufacturer="K.S.B.")
    m.create_item("P-102", manufacturer="KSB AG")
    m.create_item("P-103", manufacturer="Grundfos")
    m.create_item("P-104", manufacturer="grundfos")
    m.create_part("ETN", "Etanorm", manufacturer="ksb")
    dry = m.link_manufacturers_by_name()
    assert dry["dry_run"] and len(dry["links"]) == 3
    assert dry["unmatched"] == [{"text": "Grundfos", "count": 1}, {"text": "grundfos", "count": 1}]
    assert m.items(manufacturer_id=ksb["id"]) == []
    done = m.link_manufacturers_by_name(dry_run=False)
    assert not done["dry_run"]
    assert {i["name"] for i in m.items(manufacturer_id=ksb["id"])} == {"P-101", "P-102"}
    assert m.link_manufacturers_by_name()["links"] == []


# ---- import, export and the starter taxonomy ------------------------------------------------------

CSV = """path,code,level,description,attributes
Rotating equipment,,group,,
Rotating equipment > Pump,PU,class,Moves a liquid,Flow (m3/h); Head (m)
Rotating equipment > Pump > Centrifugal,PU-C,type,,Stages [number]; Seal [choice: mechanical | packing]
Electrical > Motor,EM,class,,Power (kW); Frame [text]
"""


def test_a_taxonomy_imports_after_a_dry_run(m):
    rows = taxonomy.rows_from_csv(CSV)
    dry = taxonomy.run(m, rows)
    assert dry["dry_run"] and dry["ok"] and dry["counts"]["create"] == 5  # with Electrical, implied
    assert [c["path"] for c in dry["create"]][:2] == ["Electrical", "Rotating equipment"]
    assert m.item_classes() == []
    done = taxonomy.run(m, rows, dry_run=False, source="ACME classes")
    assert not done["dry_run"]
    cent = next(c for c in m.item_classes() if c["name"] == "Centrifugal")
    got = m.item_class(cent["id"])
    assert (got["code"], got["level"], got["source"]) == ("PU-C", "type", "ACME classes")
    assert [a["name"] for a in got["attributes"]] == ["Flow", "Head", "Stages", "Seal"]
    assert got["own_attributes"][1] == {"name": "Seal", "unit": "", "kind": "choice",
                                        "options": ["mechanical", "packing"]}
    # Again: nothing to do.
    again = taxonomy.run(m, rows, dry_run=False)
    # (Electrical was only implied by a path: it isn't a row of the file.)
    assert again["counts"] == {"create": 0, "update": 0, "unchanged": 4, "conflicts": 0, "errors": 0}
    # A changed file fills in what's missing and reports what differs.
    more = taxonomy.rows_from_json({"classes": [
        {"path": "Rotating equipment > Pump", "code": "PUMP", "attributes": [
            {"name": "Flow", "unit": "L/s"}, {"name": "Power", "unit": "kW"}]},
        {"name": "Split-case", "parent": "Rotating equipment > Pump", "attributes": "Stages [number]"},
        {"path": "Electrical", "description": "Electrical equipment"}]})
    plan = taxonomy.run(m, more, dry_run=False)
    assert plan["counts"]["create"] == 1 and plan["counts"]["update"] == 2
    whys = {(c["path"], c.get("attribute") or c.get("field")) for c in plan["conflicts"]}
    assert whys == {("Rotating equipment > Pump", "code"), ("Rotating equipment > Pump", "Flow")}
    pump = next(c for c in m.item_classes() if c["name"] == "Pump")
    assert [a["name"] for a in m.item_class(pump["id"])["own_attributes"]] == ["Flow", "Head", "Power"]
    assert m.item_class(pump["id"])["code"] == "PU"
    split = next(c for c in m.item_classes() if c["name"] == "Split-case")
    assert [a["name"] for a in m.item_class(split["id"])["own_attributes"]] == ["Stages"]


def test_an_import_with_errors_writes_nothing(m):
    rows = taxonomy.rows_from_json([
        {"path": "Pump"}, {"path": "pump"}, {"path": "Valve", "attributes": [{"name": "Size", "kind": "colour"}]},
        {"path": "Fan"}])
    out = taxonomy.run(m, rows, dry_run=False)
    assert out["dry_run"] and not out["ok"] and len(out["errors"]) == 2
    assert m.item_classes() == []
    with pytest.raises(Invalid):
        taxonomy.rows_from_json("{not json")
    with pytest.raises(Invalid, match="Row 2"):
        taxonomy.rows_from_csv("path,attributes\nPump,Flow (m3/h) [wrong]\n")
    with pytest.raises(Invalid, match="path column"):
        taxonomy.rows_from_csv("code\nPU\n")


def test_nested_json_and_export_round_trip(m):
    nested = [{"name": "Rotating equipment", "children": [
        {"name": "Pump", "code": "PU", "attributes": [{"name": "Flow", "unit": "m3/h"},
                                                      {"name": "Frequency", "unit": "Hz", "kind": "choice",
                                                       "options": ["50", "60"]},
                                                      {"name": "Stages", "kind": "number"},
                                                      {"name": "Note", "unit": "free", "kind": "text"}],
         "children": [{"name": "Centrifugal"}]}]}]
    taxonomy.run(m, taxonomy.rows_from_json(nested), dry_run=False)
    rows = taxonomy.export_json(m)["classes"]
    assert [r["path"] for r in rows] == ["Rotating equipment", "Rotating equipment > Pump",
                                         "Rotating equipment > Pump > Centrifugal"]
    text = taxonomy.export_csv(m)
    assert "Flow (m3/h); Frequency (Hz) [choice: 50 | 60]; Stages [number]; Note (free) [text]" in text
    other = Maintenance(GraphStore(":memory:", PROJECTORS), "org-other", "tester")
    taxonomy.run(other, taxonomy.rows_from_csv(text), dry_run=False)
    assert taxonomy.export_json(other)["classes"] == rows
    assert taxonomy.run(other, taxonomy.rows_from_json(json.dumps(taxonomy.export_json(m))))["counts"]["create"] == 0


def test_the_starter_taxonomy_loads_only_when_asked_and_only_once(m):
    assert m.item_classes() == []  # never loaded on its own
    dry = taxonomy.load_starter(m)
    assert dry["dry_run"] and dry["counts"]["create"] > 40 and m.item_classes() == []
    done = taxonomy.load_starter(m, dry_run=False)
    assert not done["dry_run"] and done["counts"]["create"] == dry["counts"]["create"]
    names = {c["name"] for c in m.item_classes()}
    for wanted in ("Pump", "Centrifugal", "Positive displacement", "Electric motor", "Compressor", "Fan", "Valve",
                   "Pressure vessel", "Heat exchanger", "Conveyor", "Gearbox", "Diesel engine", "Generator",
                   "Transformer", "Switchgear", "Instrument", "HVAC unit", "Water heater"):
        assert wanted in names
    motor = next(c for c in m.item_classes() if c["name"] == "Electric motor")
    got = m.item_class(motor["id"])
    assert {"Power", "Voltage", "Speed", "Frame"} <= {a["name"] for a in got["attributes"]}
    assert got["source"] == taxonomy.STARTER_SOURCE and got["code"] == ""
    again = taxonomy.load_starter(m, dry_run=False)
    assert again["counts"]["create"] == 0 and again["counts"]["update"] == 0 and again["counts"]["conflicts"] == 0
    assert len(m.item_classes()) == done["counts"]["create"]


# ---- the event log -------------------------------------------------------------------------------

def test_old_events_project_as_before(m):
    """Items and parts from before item classes: no class, no part, no manufacturer link."""
    m.s.apply(ORG, "item.created", {"id": "i1", "name": "Pump", "on": "2024-01-01"})
    m.s.apply(ORG, "part.created", {"id": "pt1", "part_number": "X", "name": "Seal", "on": "2024-01-01"})
    node = m.s.node(ORG, "i1")
    assert {k: node[k] for k in node if k not in ("id", "label")} == {
        "name": "Pump", "serial": "", "part_number": "", "manufacturer": "", "model": "", "nameplate": {},
        "notes": "", "created": "2024-01-01", "note_history": []}
    assert m.s.out(ORG, "i1", "OF_PART") == []
    item = m.item("i1")
    assert (item["item_class"], item["attributes"], item["other_attributes"], item["part"],
            item["manufacturer_entry"]) == (None, [], {}, None, None)
    assert m.part("pt1")["item_class"] is None and m.item_class_tree()["tree"] == []
    assert m.items()[0]["item_class"] is None


def test_a_rebuild_gives_the_same_graph(m):
    rot, pump, cent = _pump_tree(m)
    ksb = m.create_manufacturer("KSB")
    dup = m.create_manufacturer("KSB Pumps")
    part = m.create_part("ETN", "Etanorm", item_class_id=cent["id"], manufacturer_id=dup["id"])
    item = m.create_item("P-101", part_id=part["id"])
    m.set_item_attributes(item["id"], {"Flow": 45})
    m.update_item_class(pump["id"], parent_id=None)
    m.merge_manufacturers(dup["id"], ksb["id"])
    m.link_manufacturer(item["id"], ksb["id"])
    taxonomy.load_starter(m, dry_run=False)
    before = m.s.snapshot()
    m.s.rebuild()
    assert m.s.snapshot() == before


# ---- the API ---------------------------------------------------------------------------------------

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
    monkeypatch.setattr(config, "MAINTENANCE_EMAILS", {"ic@example.org"})
    test_db = mongomock.MongoClient()["maint_item_classes_api"]
    monkeypatch.setattr(db, "_db", test_db)
    monkeypatch.setattr(db, "_simulated", True)
    monkeypatch.setattr(router, "_store", GraphStore(":memory:", PROJECTORS))
    user = {"uid": "user-ic", "email": "ic@example.org", "name": "IC", "email_verified": True}
    test_db.users.insert_one({"_id": "user-ic", "email": "ic@example.org", "name": "IC", "email_verified": True})
    app.dependency_overrides[get_current_user] = lambda: user
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()


def test_item_classes_and_manufacturers_through_the_api(api):
    base = "/api/maintenance"
    assert api.get(f"{base}/item-classes").json()["tree"] == []
    dry = api.post(f"{base}/item-classes/starter", json={}).json()
    assert dry["dry_run"] and api.get(f"{base}/item-classes").json()["tree"] == []
    assert not api.post(f"{base}/item-classes/starter", json={"dry_run": False}).json()["dry_run"]
    classes = api.get(f"{base}/item-classes").json()["classes"]
    pump = next(c for c in classes if c["name"] == "Pump")
    end = next(c for c in classes if c["name"] == "End-suction")
    made = api.post(f"{base}/item-classes", json={"name": "Booster", "parent_id": pump["id"],
                                                  "attributes": [{"name": "Set pressure", "unit": "bar"}]}).json()
    assert made["display"] == "Rotating equipment › Pump › Booster"
    assert api.patch(f"{base}/item-classes/{pump['id']}", json={"parent_id": made["id"]}).status_code == 422
    assert api.patch(f"{base}/item-classes/{made['id']}", json={"code": "BST"}).json()["code"] == "BST"
    mk = api.post(f"{base}/manufacturers", json={"name": "KSB", "aliases": ["K.S.B."]}).json()
    assert api.post(f"{base}/manufacturers", json={"name": "ksb"}).status_code == 422
    assert api.get(f"{base}/manufacturers/match", params={"text": "K S B"}).json()["match"]["id"] == mk["id"]
    part = api.post(f"{base}/parts", json={"part_number": "ETN", "name": "Etanorm", "item_class_id": end["id"],
                                           "manufacturer_id": mk["id"]}).json()
    assert part["item_class"]["name"] == "End-suction" and part["manufacturer_entry"]["name"] == "KSB"
    item = api.post(f"{base}/items", json={"name": "P-101", "part_id": part["id"]}).json()
    assert item["item_class"]["via"] == "part" and item["manufacturer_entry"]["via"] == "part"
    got = api.put(f"{base}/items/{item['id']}/attributes", json={"values": {"Flow": "45 m3/h", "Stages": 1}}).json()
    assert {a["name"]: a["value"] for a in got["attributes"]}["Flow"] == 45.0
    assert api.put(f"{base}/items/{item['id']}/attributes", json={"values": {"Flow": "x"}}).status_code == 422
    assert api.put(f"{base}/items/{item['id']}/part", json={"part_id": None}).json()["part"] is None
    assert api.post(f"{base}/item-classes/assign", json={"target_id": item["id"],
                                                         "item_class_id": end["id"]}).json()["item_class"]["via"] == "item"
    assert [i["name"] for i in api.get(f"{base}/items", params={"item_class_id": pump["id"]}).json()["items"]] == ["P-101"]
    assert api.get(f"{base}/items", params={"manufacturer_id": mk["id"]}).json()["items"] == []
    assert api.post(f"{base}/manufacturers/link", json={"target_id": item["id"],
                                                        "manufacturer_id": mk["id"]}).status_code == 200
    assert len(api.get(f"{base}/parts", params={"manufacturer_id": mk["id"]}).json()["parts"]) == 1
    other = api.post(f"{base}/manufacturers", json={"name": "KSB Pumps Ltd"}).json()
    merged = api.post(f"{base}/manufacturers/{other['id']}/merge", json={"into_id": mk["id"]}).json()
    assert "KSB Pumps Ltd" in merged["aliases"]
    assert api.patch(f"{base}/manufacturers/{mk['id']}", json={"add_aliases": ["KSB SE"]}).json()["aliases"][-1] == "KSB SE"
    assert api.post(f"{base}/manufacturers/link-by-name", json={}).json()["dry_run"]
    assert len(api.get(f"{base}/manufacturers").json()["manufacturers"]) == 1
    csv_text = api.get(f"{base}/item-classes/export", params={"format": "csv"}).text
    assert csv_text.startswith("path,code,level,description,attributes")
    rows = api.get(f"{base}/item-classes/export").json()["classes"]
    assert any(r["path"] == "Rotating equipment > Pump > Booster" for r in rows)
    out = api.post(f"{base}/item-classes/import", json={"format": "csv", "text": "path\nExtra > Thing\n"}).json()
    assert out["dry_run"] and out["counts"]["create"] == 2
    out = api.post(f"{base}/item-classes/import", json={"classes": [{"path": "Extra"}], "dry_run": False}).json()
    assert not out["dry_run"] and out["counts"]["create"] == 1
    extra = next(c for c in api.get(f"{base}/item-classes").json()["classes"] if c["name"] == "Extra")
    assert api.post(f"{base}/item-classes/{extra['id']}/retire", json={}).json() == {"retired": extra["id"]}
    assert api.get(f"{base}/item-classes/{pump['id']}").json()["counts"]["items"] == 1
    assert api.get(f"{base}/item-classes/nope").status_code == 404
