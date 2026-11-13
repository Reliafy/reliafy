"""Reliafy Maintenance: a product's design locations (its physical layout, products.py)
and the copies a built unit carries. Making them (design_of, and inside one), a
rebuilt graph; kept off the Assets page, the asset tree's locations and the location
lists; placing the design's positions there (inherited down the tree) and what's
refused; building an item copies them, its positions placed at the copies, wherever
the unit is kept; deleting one keeps the positions placed there; the routes and the
MCP actions."""

import pytest

from backend.maintenance.service import PROJECTORS, Invalid, Maintenance
from backend.maintenance.store import GraphStore
from backend.tests.test_maintenance_mcp import _do, _list, _ok, _session
from backend.tests.test_maintenance_mcp import env  # noqa: F401
from backend.tests.test_maintenance_products import api  # noqa: F401

ORG = "user-products"


@pytest.fixture()
def m():
    return Maintenance(GraphStore(":memory:", PROJECTORS), ORG, "tester")


def _rebuilt_matches(m):
    before = m.s.snapshot()
    m.s.rebuild()
    assert m.s.snapshot() == before


def _quad(m):
    """A product Quad with Propulsion › Motor 1 and Power › Battery, and its layout: Arm 1 and
    Centre body › Battery bay."""
    p = m.create_product("Quad", part_number="Q-1")
    root = p["id"]
    prop = m.create_position("Propulsion", parent_id=root)["id"]
    motor = m.create_position("Motor 1", parent_id=prop)["id"]
    power = m.create_position("Power", parent_id=root)["id"]
    battery = m.create_position("Battery", parent_id=power)["id"]
    arm = m.create_location("Arm 1", design_of=root)["id"]
    body = m.create_location("Centre body", design_of=root)["id"]
    bay = m.create_location("Battery bay", parent_id=body)["id"]
    return {"root": root, "prop": prop, "motor": motor, "power": power, "battery": battery,
            "arm": arm, "body": body, "bay": bay}


def test_design_locations_are_the_products_and_rebuild_the_same(m):
    q = _quad(m)
    assert m.s.node(ORG, q["arm"])["design_of"] == q["root"]
    # One made inside a design location is the product's too.
    assert m.s.node(ORG, q["bay"])["design_of"] == q["root"]
    types = [e["type"] for e in m.s.events(ORG)]
    assert types.count("location.design_declared") == 3
    read = m.location(q["bay"])
    assert read["design_of"] == {"id": q["root"], "name": "Quad"} and read["carried_by"] is None
    assert read["path"] == [{"id": q["body"], "name": "Centre body"}]
    # Not a product, or a parent that isn't the product's: refused before anything is written.
    site = m.create_location("Site")["id"]
    plain = m.create_position("Pump")["id"]
    events = m.s.event_count(ORG)
    with pytest.raises(Invalid, match="isn't a product"):
        m.create_location("X", design_of=plain)
    with pytest.raises(Invalid, match="isn't one of Quad's locations"):
        m.create_location("X", parent_id=site, design_of=q["root"])
    assert m.s.event_count(ORG) == events
    _rebuilt_matches(m)


def test_design_locations_stay_off_the_assets(m):
    q = _quad(m)
    site = m.create_location("Site")["id"]
    assert [r["id"] for r in m.places()["places"]] == [site]
    assert [x["id"] for x in m.location_tree()] == [site]
    assert [x["id"] for x in m.locations()] == [site]
    # The product's own, on asking for them.
    tree = m.location_tree(of=q["root"])
    assert [x["name"] for x in tree] == ["Arm 1", "Centre body"]
    assert [x["name"] for x in tree[1]["children"]] == ["Battery bay"]
    assert {x["name"] for x in m.locations(of=q["root"])} == {"Arm 1", "Centre body", "Battery bay"}
    with pytest.raises(Invalid, match="isn't a product or an item built from one"):
        m.locations(of=q["motor"])
    # The tree read marks them, so the asset Explorer leaves them out and the product page keeps them.
    rows = {x["id"]: x for x in m.tree_rows()["locations"]}
    assert rows[q["arm"]]["design_of"] == q["root"] and "design_of" not in rows[site]


def test_placing_the_designs_positions_and_what_is_refused(m):
    q = _quad(m)
    m.update_position(q["prop"], location_id=q["arm"])
    m.update_position(q["battery"], location_id=q["bay"])
    # Inherited down the tree, as for assets.
    motor = m.position(q["motor"])["location"]
    assert motor["id"] == q["arm"] and motor["inherited"] and motor["inherited_from"]["id"] == q["prop"]
    assert m.position(q["battery"])["location"]["display"] == "Centre body › Battery bay"
    new = m.create_position("ESC 1", parent_id=q["prop"], location_id=q["arm"])
    assert m.position(new["id"])["location"]["id"] == q["arm"]
    site = m.create_location("Site")["id"]
    pump = m.create_position("Pump", location_id=site)["id"]
    other = m.create_product("Rover")["id"]
    rover_loc = m.create_location("Chassis", design_of=other)["id"]
    spare = m.create_item("Spare motor")["id"]
    part = m.create_part("M-1", "Motor")["id"]
    events = m.s.event_count(ORG)
    with pytest.raises(Invalid, match="only its own positions"):
        m.update_position(pump, location_id=q["arm"])
    with pytest.raises(Invalid, match="only its own positions"):
        m.update_position(q["motor"], location_id=rover_loc)
    with pytest.raises(Invalid, match="place you look after"):
        m.update_position(q["motor"], location_id=site)
    with pytest.raises(Invalid, match="only its own positions"):
        m.create_position("Valve", parent_id=pump, location_id=q["arm"])
    # A design location moves only inside its own layout; a place never into one.
    with pytest.raises(Invalid, match="stays in its own layout"):
        m.update_location(q["arm"], parent_id=site)
    with pytest.raises(Invalid, match="stays in its own layout"):
        m.update_location(site, parent_id=q["body"])
    # No items, stock or work at a design location.
    with pytest.raises(Invalid, match="design location: it has no items"):
        m.place_item(spare, q["arm"])
    with pytest.raises(Invalid, match="no stock"):
        m.adjust_stock(part, q["arm"], 2)
    with pytest.raises(Invalid, match="no tasks or work"):
        m.create_task(None, "Walk round", 1, unit="weeks", location_id=q["arm"])
    assert m.s.event_count(ORG) == events
    m.update_location(q["bay"], parent_id=None)  # to the top of the product's layout: fine
    assert m.s.node(ORG, q["bay"])["design_of"] == q["root"]
    _rebuilt_matches(m)


def test_building_an_item_copies_the_layout_and_follows_the_unit(m):
    q = _quad(m)
    m.update_position(q["prop"], location_id=q["arm"])
    m.update_position(q["battery"], location_id=q["bay"])
    dry = m.build_item(q["root"], "0007")
    assert dry["counts"]["locations"] == 3
    built = m.build_item(q["root"], "0007", dry_run=False)
    top = built["top_position_id"]
    ids = {r["path"].split(" › ")[-1]: r["id"] for r in built["positions"]}
    carried = m.locations(of=top)
    assert sorted(x["name"] for x in carried) == ["Arm 1", "Battery bay", "Centre body"]
    copies = {x["name"]: x["id"] for x in carried}
    for lid in copies.values():
        node = m.s.node(ORG, lid)
        assert node["carried_by"] == top and not node.get("design_of")
    assert m.s.node(ORG, copies["Arm 1"])["design_location_id"] == q["arm"]
    # Each copied position placed at the copy mirroring the design.
    assert m.position(ids["Propulsion"])["location"]["id"] == copies["Arm 1"]
    assert m.position(ids["Motor 1"])["location"]["id"] == copies["Arm 1"]
    assert m.position(ids["Battery"])["location"]["display"] == "Centre body › Battery bay"
    # Not assets, and the design's own are untouched.
    assert m.locations() == [] and m.location_tree() == []
    assert m.position(q["motor"])["location"]["id"] == q["arm"]
    # Kept in a hangar: the unit's locations are there, and move with it (no event of their own).
    hangar = m.create_location("Hangar 2")["id"]
    shed = m.create_location("Shed")["id"]
    m.update_position(top, location_id=hangar)
    assert m.position(ids["Motor 1"])["location"]["display"] == "Hangar 2 › Arm 1"
    assert m.position(ids["Battery"])["location"]["display"] == "Hangar 2 › Centre body › Battery bay"
    at_hangar = m.location(hangar)
    listed = {p["name"] for g in at_hangar["systems"] for p in g["positions"]}
    assert {"Motor 1", "Battery", "Propulsion"} <= listed
    events = m.s.event_count(ORG)
    m.update_position(top, location_id=shed)
    assert m.s.event_count(ORG) == events + 1
    assert m.position(ids["Motor 1"])["location"]["display"] == "Shed › Arm 1"
    # A unit's position may go at a place you look after, or its own unit's locations; another unit's: no.
    other = m.build_item(q["root"], "0008", dry_run=False)
    other_arm = next(x["id"] for x in m.locations(of=other["top_position_id"]) if x["name"] == "Arm 1")
    with pytest.raises(Invalid, match="only its own positions"):
        m.update_position(ids["Motor 1"], location_id=other_arm)
    with pytest.raises(Invalid, match="only its own positions"):
        m.update_position(ids["Motor 1"], location_id=q["arm"])
    m.update_position(ids["Motor 1"], location_id=hangar)
    # A location made inside a carried one is the unit's too.
    tip = m.create_location("Arm tip", parent_id=copies["Arm 1"])
    assert m.s.node(ORG, tip["id"])["carried_by"] == top
    _rebuilt_matches(m)


def test_deleting_a_design_location_keeps_the_positions_placed_there(m):
    q = _quad(m)
    m.update_position(q["battery"], location_id=q["bay"])
    m.update_position(q["power"], location_id=q["body"])
    preview = m.retire_location(q["body"], cascade=True, dry_run=True)
    assert preview["positions"] == 0 and preview["positions_unplaced"] == 2 and preview["locations"] == 2
    assert "2 positions placed there kept, with no place" in preview["summary"]
    done = m.retire_location(q["body"], cascade=True)
    assert sorted(done["positions_unplaced"]) == sorted([q["battery"], q["power"]])
    assert not m.s.node(ORG, q["battery"]).get("retired") and m.position(q["battery"])["location"] is None
    assert m.s.node(ORG, q["bay"])["retired"]
    _rebuilt_matches(m)
    back = m.restore_location(q["body"], cascade=True)
    assert back["positions_placed_back"] == 2
    assert m.position(q["battery"])["location"]["id"] == q["bay"]
    assert m.position(q["power"])["location"]["id"] == q["body"]
    # Deleting the product takes its layout with it, and undo brings it back.
    gone = m.delete_tree("position", q["root"])
    assert set(gone["locations_retired"]) == {q["arm"], q["body"], q["bay"]}
    assert m.locations(of=q["root"]) == []
    m.restore_deletion(q["root"])
    assert not m.s.node(ORG, q["arm"]).get("retired")
    _rebuilt_matches(m)


# ---- the routes and MCP ----------------------------------------------------------------------

def test_the_routes(api):  # noqa: F811
    M = "/api/maintenance"
    pid = api.post(f"{M}/products", json={"name": "Quad"}).json()["id"]
    arm = api.post(f"{M}/locations", json={"name": "Arm 1", "design_of": pid})
    assert arm.status_code == 200 and arm.json()["design_of"] == pid
    site = api.post(f"{M}/locations", json={"name": "Site"}).json()
    assert [x["id"] for x in api.get(f"{M}/locations").json()["locations"]] == [site["id"]]
    mine = api.get(f"{M}/locations", params={"of": pid}).json()
    assert [x["name"] for x in mine["locations"]] == ["Arm 1"] and [x["name"] for x in mine["tree"]] == ["Arm 1"]
    bad = api.post(f"{M}/locations", json={"name": "X", "design_of": site["id"]})
    assert bad.status_code in (400, 404, 422)


def test_design_locations_over_mcp(env):  # noqa: F811
    async def flow(client):
        made = _ok(await _do(client, "maintenance", "products.create", name="Quad"))
        arm = _ok(await _do(client, "maintenance", "locations.create", name="Arm 1", design_of=made["id"]))
        tip = _ok(await _do(client, "maintenance", "locations.create", name="Tip", parent_id=arm["id"]))
        site = _ok(await _do(client, "maintenance", "locations.create", name="Site"))
        theirs = _ok(await _list(client, "locations", product_id=made["id"]))
        assets = _ok(await _list(client, "locations"))
        return arm, tip, site, theirs, assets

    arm, tip, site, theirs, assets = _session(env["token"], flow)
    assert arm["design_of"] and tip["design_of"] == arm["design_of"]
    assert [x["name"] for x in theirs["tree"]] == ["Arm 1"] and [x["name"] for x in theirs["tree"][0]["children"]] == ["Tip"]
    assert [x["id"] for x in assets["tree"]] == [site["id"]]
