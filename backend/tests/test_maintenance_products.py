"""Reliafy Maintenance: products (design trees) and the items built from them.
Declaring and clearing a design and what's refused; making a product with its
part; building an item (the dry run, then the tree, the item, its fitment and
the provenance on every position); serials; the design roll-up across items
(items, pooled life data, failure reports) and reports refused on a design; the
tree marks; the items overview; a rebuilt graph; the routes and the MCP area."""

import mongomock
import pytest

from backend.maintenance import service as service_mod
from backend.maintenance.service import PROJECTORS, Invalid, Maintenance, NotFound
from backend.maintenance.store import GraphStore
from backend.tests.test_maintenance_mcp import _do, _get, _list, _ok, _session
from backend.tests.test_maintenance_mcp import env  # noqa: F401

ORG = "user-products"
UID = "user-products"


@pytest.fixture()
def m():
    return Maintenance(GraphStore(":memory:", PROJECTORS), ORG, "tester")


def _uav(m, rev="C"):
    """A product UAV Mk2 (part UAV-2) with Propulsion › Motor 1 (a failure mode and a
    task) and Power › Battery."""
    p = m.create_product("UAV Mk2", part_number="UAV-2", rev=rev, description="Quadcopter")
    root = p["id"]
    prop = m.create_position("Propulsion", parent_id=root)["id"]
    motor = m.create_position("Motor 1", parent_id=prop, position_class="Motor")["id"]
    power = m.create_position("Power", parent_id=root)["id"]
    battery = m.create_position("Battery", parent_id=power)["id"]
    m.add_failure_mode(motor, "Bearing worn")
    m.create_task(motor, "Inspect motor", 3, unit="months")
    return {"product": p, "root": root, "prop": prop, "motor": motor, "power": power, "battery": battery}


def _built(m, root, serial):
    """The positions of the item built with this serial, by name."""
    out = m.build_item(root, serial, dry_run=False)
    return out, {r["path"].split(" › ")[-1]: r["id"] for r in out["positions"]}


def _rebuilt_matches(m):
    before = m.s.snapshot()
    m.s.rebuild()
    assert m.s.snapshot() == before


# ---- products and designs -----------------------------------------------------------------

def test_create_product_makes_the_part_and_the_declared_design(m):
    p = m.create_product("UAV Mk2", part_number="UAV-2", rev="C", description="Quadcopter")
    assert p["name"] == "UAV Mk2" and p["rev"] == "C" and p["description"] == "Quadcopter"
    assert p["part"]["part_number"] == "UAV-2" and p["part"]["name"] == "UAV Mk2"
    assert p["items_built"] == 0 and p["open_reports"] == 0 and p["positions"] == 1
    assert p["declared_on"] == m.today()
    assert m.position(p["id"])["design"] == {"rev": "C", "part": p["part"], "declared_on": m.today()}
    assert [x["id"] for x in m.products()["products"]] == [p["id"]]
    # An existing part instead; both at once, a number in the catalogue, or a part that's another
    # product's, refused (before anything is written).
    pump = m.create_part("SKID-1", "Pump skid")
    skid = m.create_product("Pump skid", part_id=pump["id"])
    assert skid["part"]["id"] == pump["id"] and skid["rev"] == ""
    events = m.s.event_count(ORG)
    with pytest.raises(Invalid, match="not both"):
        m.create_product("X", part_number="X-1", part_id=pump["id"])
    with pytest.raises(Invalid, match="already in the catalogue"):
        m.create_product("X", part_number="uav-2")
    with pytest.raises(Invalid, match="already the product Pump skid"):
        m.create_product("Y", part_id=pump["id"])
    with pytest.raises(Invalid, match="name is required"):
        m.create_product(" ")
    assert m.s.event_count(ORG) == events
    # No part at all is allowed (it can be given later).
    assert m.create_product("Bare")["part"] is None
    _rebuilt_matches(m)


def test_declare_change_rev_and_clear(m):
    plant = m.create_position("Rig")["id"]
    inner = m.create_position("Deck", parent_id=plant)["id"]
    part = m.create_part("RIG-1", "Rig")
    with pytest.raises(Invalid, match="declare its top-level position"):
        m.declare_design(inner)
    d = m.declare_design(plant, part_id=part["id"], rev="A")
    assert d["rev"] == "A" and d["part"]["id"] == part["id"]
    # Again: a new rev label, the part kept; "none" takes the part off.
    assert m.declare_design(plant, rev="B")["part"]["id"] == part["id"]
    assert m.product(plant)["rev"] == "B"
    assert m.declare_design(plant, part_id="none")["part"] is None
    assert m.product(plant)["rev"] == "B"
    cleared = m.clear_design(plant)
    assert cleared["design"] is None and m.position(plant)["design"] is None
    assert m.products()["products"] == []
    with pytest.raises(Invalid, match="isn't a product's design"):
        m.clear_design(plant)
    with pytest.raises(Invalid, match="isn't a product"):
        m.product(plant)
    with pytest.raises(NotFound):
        m.declare_design("nope")
    _rebuilt_matches(m)


def test_a_tree_with_items_or_built_from_a_design_cant_be_a_design(m):
    plant = m.create_position("Plant")["id"]
    pump = m.create_position("Pump", parent_id=plant)["id"]
    m.fit(pump, new_item={"name": "P-1", "serial": "1"}, on="2025-01-01")
    with pytest.raises(Invalid, match="Items have been fitted in Plant .at Pump.: it's a plant"):
        m.declare_design(plant)
    # Even once it's out again: a fitment is history.
    m.remove(pump, on="2025-06-01")
    with pytest.raises(Invalid, match="Items have been fitted"):
        m.declare_design(plant)
    ids = _uav(m)
    built, _ = _built(m, ids["root"], "0001")
    with pytest.raises(Invalid, match="built from a product's design"):
        m.declare_design(built["top_position_id"])


def test_a_design_stays_a_whole_tree(m):
    ids = _uav(m)
    plant = m.create_position("Plant")["id"]
    with pytest.raises(Invalid, match="stays a whole tree"):
        m.update_position(ids["root"], parent_id=plant)
    with pytest.raises(Invalid, match="between a product's design and another tree"):
        m.update_position(ids["motor"], parent_id=plant)
    with pytest.raises(Invalid, match="between a product's design and another tree"):
        m.update_position(plant, parent_id=ids["prop"])
    # Inside the design, moving is as before.
    m.update_position(ids["battery"], parent_id=ids["prop"])
    assert m.position(ids["battery"])["path"][-1]["name"] == "Propulsion"


# ---- building an item ------------------------------------------------------------------------

def test_build_dry_run_lists_the_paths_and_writes_nothing(m):
    ids = _uav(m)
    events = m.s.event_count(ORG)
    d = m.build_item(ids["root"], "0007")
    assert d["dry_run"] is True and m.s.event_count(ORG) == events
    assert d["name"] == "UAV Mk2 · 0007" and d["serial"] == "0007" and d["rev"] == "C"
    assert d["item"] == {"name": "UAV Mk2 · 0007", "serial": "0007", "part": ids["product"]["part"]}
    assert [r["path"] for r in d["positions"]] == [
        "UAV Mk2 · 0007", "UAV Mk2 · 0007 › Power", "UAV Mk2 · 0007 › Power › Battery",
        "UAV Mk2 · 0007 › Propulsion", "UAV Mk2 · 0007 › Propulsion › Motor 1"]
    assert d["positions"][0]["design_position_id"] == ids["root"] and "id" not in d["positions"][0]
    assert d["counts"] == {"positions": 5, "failure_modes": 1, "tasks": 1, "parts_list": 0}
    assert d["top_position_id"] is None
    # A rev and a name of its own.
    named = m.build_item(ids["root"], "0008", rev="B", name="Drone 8")
    assert named["rev"] == "B" and named["positions"][0]["path"] == "Drone 8"


def test_build_writes_the_tree_the_item_its_fitment_and_the_provenance(m):
    ids = _uav(m)
    out, at = _built(m, ids["root"], "0007")
    top = out["top_position_id"]
    assert out["dry_run"] is False and at["UAV Mk2 · 0007"] == top
    item = out["item"]
    assert item["serial"] == "0007" and item["part"]["part_number"] == "UAV-2"
    # The item is fitted at the new top, of the product's part, and knows its product.
    got = m.item(item["id"])
    assert got["fitted_to"]["id"] == top and got["part"]["id"] == ids["product"]["part"]["id"]
    assert got["product"] == {"id": ids["root"], "name": "UAV Mk2", "top_position_id": top, "built": True}
    # The tree is a copy, with its failure modes and tasks, at the top level.
    motor = m.position(at["Motor 1"])
    assert [fm["text"] for fm in motor["failure_modes"]] == ["Bearing worn"]
    assert [t["name"] for t in motor["tasks"]] == ["Inspect motor"]
    assert m.position(top)["path"] == []
    # Every copied position says what it implements.
    assert motor["implements"] == {"design_position_id": ids["motor"], "design_rev": "C", "name": "Motor 1",
                                   "gone": False, "product": {"id": ids["root"], "name": "UAV Mk2"}}
    assert m.position(top)["implements"]["design_position_id"] == ids["root"]
    assert m.position(ids["motor"])["implements"] is None and motor["design"] is None
    # Renamed and moved inside the item's tree, the link stays.
    m.update_position(at["Motor 1"], name="Motor front-left", parent_id=at["Power"])
    assert m.position(at["Motor 1"])["implements"]["design_position_id"] == ids["motor"]
    assert m.product(ids["root"])["items_built"] == 1
    # The design itself is unchanged: no item, still a template.
    assert m.position(ids["root"])["fitted"] is None
    _rebuilt_matches(m)


def test_serials_must_be_given_and_new_for_the_product(m):
    ids = _uav(m)
    m.build_item(ids["root"], "0007", dry_run=False)
    for serial in ("0007", " 0007 "):
        with pytest.raises(Invalid, match="Serial .*0007.* is already used by an item of UAV Mk2"):
            m.build_item(ids["root"], serial)
    with pytest.raises(Invalid, match="serial is required"):
        m.build_item(ids["root"], "")
    # An item of the part made by hand with that serial counts too.
    m.create_item("Spare frame", serial="0100", part_id=ids["product"]["part"]["id"])
    with pytest.raises(Invalid, match="0100 is already used"):
        m.build_item(ids["root"], "0100")
    # Another product may use the same serial.
    other = m.create_product("Rover", part_number="RV-1")
    assert m.build_item(other["id"], "0007", dry_run=False)["item"]["serial"] == "0007"
    # Not a product: refused.
    plant = m.create_position("Plant")["id"]
    with pytest.raises(Invalid, match="isn't a product"):
        m.build_item(plant, "1")


def test_build_respects_the_copy_limit(m, monkeypatch):
    ids = _uav(m)
    monkeypatch.setattr(service_mod, "MAX_COPY_NODES", 4)
    events = m.s.event_count(ORG)
    with pytest.raises(Invalid, match="more than 4 positions"):
        m.build_item(ids["root"], "0007", dry_run=False)
    assert m.s.event_count(ORG) == events


def test_items_cant_be_fitted_into_a_design(m):
    ids = _uav(m)
    events = m.s.event_count(ORG)
    with pytest.raises(Invalid, match="This is a product's design: fit items into an item built from it."):
        m.fit(ids["motor"], new_item={"name": "Motor", "serial": "M-1"})
    with pytest.raises(Invalid, match="This is a product's design"):
        m.add_past_fitment(ids["motor"], "2025-01-01", "2025-06-01", reason="planned",
                           new_item={"name": "Motor", "serial": "M-0"})
    assert m.s.event_count(ORG) == events
    # Fitting into an item built from it is fine.
    _, at = _built(m, ids["root"], "0007")
    assert m.fit(at["Motor 1"], new_item={"name": "Motor", "serial": "M-1"})["fitted"]["item"]["serial"] == "M-1"


# ---- the roll-up and failure reports ---------------------------------------------------------

def _three(m):
    """Three items built, a motor fitted at each Motor 1; two failed and were replaced."""
    ids = _uav(m)
    units = {}
    for serial in ("0007", "0008", "0009"):
        _, at = _built(m, ids["root"], serial)
        units[serial] = at
        m.fit(at["Motor 1"], new_item={"name": "Motor M-2210", "serial": f"M-{serial}"}, on="2026-01-01")
    for serial in ("0007", "0009"):
        m.remove(units[serial]["Motor 1"], on="2026-04-01", reason="failure", failure_mode_text="Bearing worn")
        m.fit(units[serial]["Motor 1"], new_item={"name": "Motor M-2210", "serial": f"M-{serial}b"},
              on="2026-04-02")
    return ids, units


def test_the_rollup_shows_each_item_and_pools_the_life_data(m):
    ids, units = _three(m)
    r = m.design_rollup(ids["motor"])
    assert r["design_position"]["path"] == ["UAV Mk2", "Propulsion", "Motor 1"]
    assert r["product"]["id"] == ids["root"] and r["product"]["rev"] == "C"
    assert [x["serial"] for x in r["items"]] == ["0007", "0008", "0009"]
    assert r["counts"] == {"items": 3, "by_rev": {"C": 3}}
    row = r["items"][0]
    assert row["position"]["id"] == units["0007"]["Motor 1"] and row["rev"] == "C" and row["hours"] is None
    assert row["fitted"]["serial"] == "M-0007b" and row["fitted"]["since"] == "2026-04-02"
    assert row["built_on"] == m.today()
    life = r["life_data"]
    assert len(life["rows"]) == 5 and life["failures"] == 2 and life["suspensions"] == 3
    assert {x["serial"] for x in life["rows"]} == {"0007", "0008", "0009"}
    failed = [x for x in life["rows"] if x["c"] == 0]
    assert [x["x"] for x in failed] == [90, 90] and failed[0]["failure_mode"] == "Bearing worn"
    # The same row shape as class_life_data (which pools by position class).
    cls = m.class_life_data("Motor")
    assert {k for k in cls["rows"][0]} <= {k for k in life["rows"][0]}
    # The product's top rolls up too: one row per item, nothing fitted at the design itself.
    top = m.design_rollup(ids["root"])
    assert len(top["items"]) == 3 and top["items"][0]["fitted"]["name"] == "UAV Mk2 · 0007"
    with pytest.raises(Invalid, match="isn't in a product's design"):
        m.design_rollup(units["0007"]["Motor 1"])


def test_hours_come_from_an_hours_counter_when_there_is_one(m):
    ids = _uav(m)
    out, at = _built(m, ids["root"], "0007")
    assert m.product_items(ids["root"])["items"][0]["hours"] is None
    point = m.add_point(out["top_position_id"], "Flight hours", kind="counter", unit="h")
    m.record_reading(point["id"], 212, on=m.today())
    [row] = m.product_items(ids["root"])["items"]
    assert row["hours"] == {"value": 212, "unit": "hours", "point_id": point["id"]}
    assert m.design_rollup(ids["motor"])["items"][0]["hours"]["value"] == 212


def test_reports_are_refused_on_a_design_and_roll_up_across_items(m):
    ids, units = _three(m)
    for pid in (ids["root"], ids["motor"]):
        with pytest.raises(Invalid, match="A report is about an item: pick one of the items built from this product."):
            m.file_failure_report(pid, "Overheat")
    a = m.file_failure_report(units["0007"]["Motor 1"], "Overheat", occurred_on="2026-05-01")
    m.file_failure_report(units["0009"]["Motor 1"], "Overheat again", occurred_on="2026-06-01")
    m.file_failure_report(units["0008"]["Battery"], "Swelling", occurred_on="2026-06-02")
    r = m.design_rollup(ids["motor"])
    assert [x["title"] for x in r["reports"]] == ["Overheat again", "Overheat"]
    assert [x["unit"]["serial"] for x in r["reports"]] == ["0009", "0007"]
    assert r["reports"][1]["item"]["serial"] == "M-0007b" and r["reports"][1]["level"] == []
    assert r["reports_total"] == 2 and r["open_reports"] == 2
    # At the product's top: every report on every item, with the level below each item's top.
    top = m.design_rollup(ids["root"])
    assert top["reports_total"] == 3
    assert next(x for x in top["reports"] if x["title"] == "Swelling")["level"] == ["Power", "Battery"]
    # The product list and the items count open reports in each item's tree.
    assert m.product(ids["root"])["open_reports"] == 3
    by_serial = {x["serial"]: x["open_reports"] for x in m.product_items(ids["root"])["items"]}
    assert by_serial == {"0007": 1, "0008": 1, "0009": 1}
    m.verify_failure_report(a["id"], "worked")
    m.set_failure_report_status(a["id"], "closed")
    assert m.product(ids["root"])["open_reports"] == 2
    _rebuilt_matches(m)


def test_a_retired_design_position_reads_as_gone(m):
    ids = _uav(m)
    _, at = _built(m, ids["root"], "0007")
    m.retire_position(ids["battery"])
    gone = m.position(at["Battery"])["implements"]
    assert gone["gone"] is True and gone["design_position_id"] == ids["battery"]
    row = next(r for r in m.tree_rows()["positions"] if r["id"] == at["Battery"])
    assert row["design_gone"] is True and row["design_position_id"] == ids["battery"]


# ---- the tree marks and the items overview --------------------------------------------------

def test_the_tree_marks_designs_and_built_trees(m):
    ids = _uav(m)
    out, at = _built(m, ids["root"], "0007")
    plant = m.create_position("Plant")["id"]
    rows = {r["id"]: r for r in m.tree_rows()["positions"]}
    assert rows[ids["root"]]["design"] == {"rev": "C", "part_id": ids["product"]["part"]["id"]}
    assert "design" not in rows[ids["motor"]] and "design_position_id" not in rows[ids["motor"]]
    top = rows[out["top_position_id"]]
    assert top["built_from"] == {"product_id": ids["root"], "rev": "C", "serial": "0007"}
    assert top["design_position_id"] == ids["root"]
    assert rows[at["Motor 1"]]["design_position_id"] == ids["motor"] and "built_from" not in rows[at["Motor 1"]]
    assert not {"design", "design_position_id", "built_from", "design_gone"} & set(rows[plant])
    # The nested tree (the overview's) carries the same marks.
    tops = {n["id"]: n for n in m.tree()}
    assert tops[ids["root"]]["design"]["rev"] == "C" and tops[out["top_position_id"]]["built_from"]["serial"] == "0007"


def test_items_overview_lists_filters_and_pages(m):
    ids, units = _three(m)
    loose = m.create_item("Spare frame", serial="F-1", part_id=ids["product"]["part"]["id"])
    other = m.create_item("Hand drill", serial="D-9")
    m.file_failure_report(units["0008"]["Motor 1"], "Noisy")
    every = m.items_overview()
    assert every["total"] == 3 + 5 + 2 and every["limit"] == 100
    by_serial = {x["serial"]: x for x in every["items"]}
    built = by_serial["0008"]
    assert built["product"] == {"id": ids["root"], "name": "UAV Mk2", "built": True}
    assert built["position"]["path"] == "UAV Mk2 · 0008" and built["status"] == "fitted"
    assert built["open_reports"] == 1 and built["top_position_id"] == units["0008"]["UAV Mk2 · 0008"]
    motor = by_serial["M-0008"]
    assert motor["product"] is None and motor["position"]["path"] == "UAV Mk2 · 0008 › Propulsion › Motor 1"
    assert motor["open_reports"] == 1  # the report involves it
    assert by_serial["F-1"]["product"] == {"id": ids["root"], "name": "UAV Mk2", "built": False}
    assert by_serial["F-1"]["status"] == "not placed" and by_serial["D-9"]["product"] is None
    # Filters.
    assert {x["serial"] for x in m.items_overview(product_id=ids["root"])["items"]} == {"0007", "0008", "0009", "F-1"}
    assert other["id"] in {x["id"] for x in m.items_overview(product_id="none")["items"]}
    assert [x["id"] for x in m.items_overview(q="drill")["items"]] == [other["id"]]
    assert m.items_overview(q="uav mk2")["total"] == 4  # by the product's name too
    assert loose["id"] in {x["id"] for x in m.items_overview(q="F-1")["items"]}
    # Paging.
    page = m.items_overview(limit=3, offset=3)
    assert len(page["items"]) == 3 and page["total"] == 10
    assert page["items"][0]["id"] == every["items"][3]["id"]
    for bad in ({"limit": 0}, {"limit": 501}, {"offset": -1}, {"limit": "x"}):
        with pytest.raises(Invalid, match="limit"):
            m.items_overview(**bad)
    with pytest.raises(NotFound):
        m.items_overview(product_id="nope")


def test_clear_is_refused_while_built_items_are_in_use(m):
    ids = _uav(m)
    out, _ = _built(m, ids["root"], "0007")
    with pytest.raises(Invalid, match="1 item was built from UAV Mk2"):
        m.clear_design(ids["root"])
    m.remove(out["top_position_id"])
    m.retire_position(out["top_position_id"], cascade=True)
    m.clear_design(ids["root"])
    assert m.products()["products"] == []
    _rebuilt_matches(m)


# ---- the routes ------------------------------------------------------------------------------

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
    monkeypatch.setattr(config, "MAINTENANCE_EMAILS", {"pr@example.org"})
    test_db = mongomock.MongoClient()["maint_products_api"]
    monkeypatch.setattr(db, "_db", test_db)
    monkeypatch.setattr(db, "_simulated", True)
    monkeypatch.setattr(router, "_store", GraphStore(":memory:", PROJECTORS))
    user = {"uid": UID, "email": "pr@example.org", "name": "Priya", "email_verified": True}
    test_db.users.insert_one({"_id": UID, "email": "pr@example.org", "name": "Priya", "email_verified": True})
    app.dependency_overrides[get_current_user] = lambda: user
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()


def test_the_routes(api):
    from backend.auth import get_current_user
    from backend.main import app

    M = "/api/maintenance"
    made = api.post(f"{M}/products", json={"name": "UAV Mk2", "part_number": "UAV-2", "rev": "C"})
    assert made.status_code == 200, made.text
    pid = made.json()["id"]
    assert api.post(f"{M}/products", json={}).status_code == 422
    prop = api.post(f"{M}/positions", json={"name": "Propulsion", "parent_id": pid}).json()["id"]
    motor = api.post(f"{M}/positions", json={"name": "Motor 1", "parent_id": prop}).json()["id"]
    assert [p["id"] for p in api.get(f"{M}/products").json()["products"]] == [pid]
    assert api.get(f"{M}/products/{pid}").json()["rev"] == "C"
    assert api.get(f"{M}/products/nope").status_code == 404

    dry = api.post(f"{M}/products/{pid}/build", json={"serial": "0007"})
    assert dry.status_code == 200 and dry.json()["dry_run"] is True and len(dry.json()["positions"]) == 3
    assert api.get(f"{M}/products/{pid}/items").json()["items"] == []
    built = api.post(f"{M}/products/{pid}/build", json={"serial": "0007", "dry_run": False}).json()
    assert built["dry_run"] is False and built["item"]["serial"] == "0007"
    again = api.post(f"{M}/products/{pid}/build", json={"serial": "0007", "dry_run": False})
    assert again.status_code == 422 and "already used" in again.json()["detail"]
    [row] = api.get(f"{M}/products/{pid}/items").json()["items"]
    assert row["serial"] == "0007" and row["top_position_id"] == built["top_position_id"]

    roll = api.get(f"{M}/positions/{motor}/design-rollup").json()
    assert [x["serial"] for x in roll["items"]] == ["0007"]
    refused = api.post(f"{M}/failure-reports", json={"position_id": motor, "title": "Overheat"})
    assert refused.status_code == 422 and refused.json()["detail"].startswith("A report is about an item")
    over = api.get(f"{M}/items/overview", params={"product_id": pid, "q": "0007"}).json()
    assert over["total"] == 1 and over["items"][0]["product"]["built"] is True
    assert api.get(f"{M}/items/overview", params={"limit": 0}).status_code == 422
    tree = {p["id"]: p for p in api.get(f"{M}/tree").json()["positions"]}
    assert tree[pid]["design"]["rev"] == "C" and tree[built["top_position_id"]]["built_from"]["serial"] == "0007"

    plain = api.post(f"{M}/positions", json={"name": "Spare tree"}).json()["id"]
    declared = api.put(f"{M}/positions/{plain}/design", json={"rev": "A"})
    assert declared.status_code == 200 and declared.json()["rev"] == "A"
    assert api.delete(f"{M}/products/{plain}/design").json()["design"] is None
    assert api.delete(f"{M}/products/{pid}/design").status_code == 422  # an item was built from it
    # Signed out: 401 from each.
    app.dependency_overrides.pop(get_current_user)
    for method, path in (("get", "/products"), ("post", "/products"), ("get", f"/products/{pid}/items"),
                         ("post", f"/products/{pid}/build"), ("get", "/items/overview"),
                         ("get", f"/positions/{motor}/design-rollup"), ("put", f"/positions/{plain}/design"),
                         ("delete", f"/products/{pid}/design")):
        kwargs = {"json": {}} if method in ("post", "put") else {}
        assert getattr(api, method)(f"{M}{path}", **kwargs).status_code == 401, path


# ---- over MCP ----------------------------------------------------------------------------------

def test_products_over_mcp(env):  # noqa: F811
    async def flow(client):
        made = _ok(await _do(client, "maintenance", "products.create", name="UAV Mk2", part_number="UAV-2", rev="C"))
        motor = _ok(await _do(client, "maintenance", "positions.create", name="Motor 1", parent_id=made["id"]))
        dry = _ok(await _do(client, "maintenance", "products.build", product_id=made["id"], serial="0007"))
        real = _ok(await _do(client, "maintenance", "products.build", product_id=made["id"], serial="0007",
                             dry_run=False))
        dup = await _do(client, "maintenance", "products.build", product_id=made["id"], serial="0007")
        missing = await _do(client, "maintenance", "products.build", product_id=made["id"])
        listed = _ok(await _list(client, "products"))
        items = _ok(await _list(client, "product_items", product_id=made["id"]))
        overview = _ok(await _list(client, "items_overview", product_id=made["id"], limit=10))
        one = _ok(await _get(client, "product", made["id"]))
        roll = _ok(await _get(client, "design_rollup", motor["id"]))
        refused = await _do(client, "maintenance", "failure_reports.file", position_id=motor["id"], title="Hot")
        plain = _ok(await _do(client, "maintenance", "positions.create", name="Rig"))
        declared = _ok(await _do(client, "maintenance", "products.declare", position_id=plain["id"], rev="A"))
        unconfirmed = await client.call_tool("maintenance", {"action": "apply", "operations": [
            {"do": "products.clear", "args": {"product_id": plain["id"]}}]})
        batch = _ok(await client.call_tool("maintenance", {"action": "apply", "dry_run": False, "operations": [
            {"do": "products.clear", "args": {"product_id": plain["id"]}, "confirm": "Rig"}]}))
        no_build = await client.call_tool("maintenance", {"action": "apply", "operations": [
            {"do": "products.build", "args": {"product_id": made["id"], "serial": "9"}}]})
        guide = _ok(await client.call_tool("maintenance", {"action": "guide", "topic": "products"}))
        return (made, dry, real, dup, missing, listed, items, overview, one, roll, refused, declared, unconfirmed,
                batch, no_build, guide)

    (made, dry, real, dup, missing, listed, items, overview, one, roll, refused, declared, unconfirmed, batch,
     no_build, guide) = _session(env["token"], flow)
    assert made["part"]["part_number"] == "UAV-2"
    assert dry["dry_run"] is True and real["dry_run"] is False and real["item"]["serial"] == "0007"
    assert dup.is_error and "already used" in dup.content[0].text
    assert missing.is_error and "serial" in missing.content[0].text
    assert [p["name"] for p in listed["products"]] == ["UAV Mk2"] and listed["products"][0]["items_built"] == 1
    assert [x["serial"] for x in items["items"]] == ["0007"] and overview["total"] == 1
    assert one["id"] == made["id"] and [x["serial"] for x in roll["items"]] == ["0007"]
    assert refused.is_error and "A report is about an item" in refused.content[0].text
    assert declared["rev"] == "A"
    assert unconfirmed.is_error and "confirm 'Rig'" in unconfirmed.content[0].text
    assert batch["applied"] == 1
    assert no_build.is_error
    assert "products.build" in guide["guide"] and "dry_run" in guide["guide"]
