"""One asset opened on its own in the Explorer (?root=, Nov 2026: "assets and all their linkages
needs to be completely isolated"): the reads behind it take ``within`` (a place, or a top
position) and send that asset alone: the tree, the RCM, the models and the missions on its
positions. Nothing of another asset comes back, even where the two are connected, share an item
class or a position in one sits inside a position in the other."""

import mongomock
import pytest

from backend.maintenance.service import PROJECTORS, Maintenance, NotFound
from backend.maintenance.store import GraphStore

ORG = "org-isolation"


@pytest.fixture()
def m():
    return Maintenance(GraphStore(":memory:", PROJECTORS), ORG, "tester")


def _two_assets(m):
    """96 Anthony Street (a kitchen inside, a hot water system with its element, a spare element)
    and a farm (a bore pump), connected (the bore feeds the hot water), one item class fitted in
    both, and a loose item at no place. The farm's pump also has a child set at the house."""
    house = m.create_location("96 Anthony Street")["id"]
    kitchen = m.create_location("Kitchen", parent_id=house)["id"]
    farm = m.create_location("Farm")["id"]
    hws = m.create_position("Hot water", location_id=kitchen)["id"]
    elem = m.create_position("Element", parent_id=hws)["id"]
    pump = m.create_position("Bore pump", location_id=farm)["id"]
    gauge = m.create_position("Pump gauge at the house", parent_id=pump, location_id=house)["id"]
    heater = m.create_item_class("Heater")["id"]
    for pid, name in ((elem, "Element unit"), (pump, "Pump unit")):
        item = m.fit(pid, new_item={"name": name, "serial": name[:2]})["fitted"]["item"]["id"]
        m.assign_item_class(item, heater)
    spare = m.create_item("Spare element", serial="SP-1")["id"]
    m.place_item(spare, kitchen)
    m.place_item(m.create_item("Farm spare", serial="FS-1")["id"], farm)
    m.create_item("Loose item", serial="L-1")
    m.connect(pump, hws, kind="flow", medium="water")
    m.add_failure_mode(hws, "Tank corrodes", function="Heat water", failure="No hot water")
    m.add_failure_mode(pump, "Impeller wears", function="Pump water", failure="No water")
    return {"house": house, "kitchen": kitchen, "farm": farm, "hws": hws, "elem": elem, "pump": pump,
            "gauge": gauge}


def _names(read):
    return ({p["name"] for p in read["positions"]}, {loc["name"] for loc in read["locations"]},
            {s["name"] for s in read["spares"]}, {u["name"] for u in read["unhomed"]})


def test_the_tree_within_a_place_is_that_asset_alone(m):
    ids = _two_assets(m)
    whole = m.tree_rows()
    assert {"Hot water", "Bore pump"} <= _names(whole)[0] and "Loose item" in _names(whole)[3]

    positions, locations, spares, unhomed = _names(m.tree_rows(within=ids["house"]))
    # The gauge is set at the house, so it's this asset's (as positions_inside reads it) and a top
    # here: its parent (the farm's pump) is another asset's and isn't sent.
    assert positions == {"Hot water", "Element", "Pump gauge at the house"}
    assert locations == {"96 Anthony Street", "Kitchen"}
    assert spares == {"Spare element"}
    assert unhomed == set()
    read = m.tree_rows(within=ids["house"])
    by = {p["name"]: p for p in read["positions"]}
    assert by["Pump gauge at the house"]["parent_id"] is None
    assert by["Element"]["parent_id"] == ids["hws"]
    assert {loc["name"]: loc["parent_id"] for loc in read["locations"]} == {"96 Anthony Street": None,
                                                                             "Kitchen": ids["house"]}
    # Rollups count only what's inside the asset.
    assert by["Hot water"]["inside"]["positions"] == 1

    positions, locations, spares, _ = _names(m.tree_rows(within=ids["farm"]))
    assert positions == {"Bore pump"}  # its gauge is at the house: the house's
    assert locations == {"Farm"} and spares == {"Farm spare"}
    assert "inside" not in {p["name"]: p for p in m.tree_rows(within=ids["farm"])["positions"]}["Bore pump"]


def test_the_tree_within_a_position_is_its_tree_alone(m):
    ids = _two_assets(m)
    positions, locations, spares, unhomed = _names(m.tree_rows(within=ids["pump"]))
    assert positions == {"Bore pump", "Pump gauge at the house"}
    assert locations == set() and spares == set() and unhomed == set()
    with pytest.raises(NotFound):
        m.tree_rows(within="no-such-thing")


def test_a_redundancy_set_across_two_assets_counts_only_this_ones_members(m):
    ids = _two_assets(m)
    m.create_group("Water supply", [ids["hws"], ids["pump"]])
    whole = {p["name"]: p.get("redundancy") for p in m.tree_rows()["positions"]}
    assert whole["Hot water"]["n"] == 2
    house = {p["name"]: p.get("redundancy") for p in m.tree_rows(within=ids["house"])["positions"]}
    assert house["Hot water"]["n"] == 1 and house["Element"] is None


def test_the_rcm_within_an_asset_is_that_assets_alone(m):
    ids = _two_assets(m)
    assert {p["id"] for p in m.rcm_all()["positions"]} == {ids["hws"], ids["pump"]}
    house = m.rcm_all(within=ids["house"])
    assert [p["id"] for p in house["positions"]] == [ids["hws"]]
    assert set(house["parents"]) == {ids["hws"]}
    assert [p["id"] for p in m.rcm_all(within=ids["farm"])["positions"]] == [ids["pump"]]


# ---- over REST -------------------------------------------------------------------------------

@pytest.fixture()
def client(monkeypatch):
    from fastapi.testclient import TestClient

    from backend import config
    from backend import db as db_mod
    from backend.auth import get_current_user
    from backend.main import app
    from backend.routers import maintenance as router

    d = mongomock.MongoClient()["isolation_rest"]
    monkeypatch.setattr(db_mod, "_db", d)
    monkeypatch.setattr(db_mod, "_simulated", True)
    monkeypatch.setattr(router, "_store", GraphStore(":memory:", PROJECTORS))
    monkeypatch.setattr(config, "MAINTENANCE_ENABLED", True)
    monkeypatch.setattr(config, "MAINTENANCE_EMAILS", {"a@x.com"})
    app.dependency_overrides[get_current_user] = lambda: {
        "uid": ORG, "email": "a@x.com", "name": "A", "email_verified": True}
    yield TestClient(app)
    app.dependency_overrides.pop(get_current_user, None)


def _ok(r):
    assert r.status_code == 200, r.text
    return r.json()


def test_rest_reads_take_within_and_send_one_asset(client):
    post = lambda path, body: _ok(client.post(f"/api/maintenance{path}", json=body))  # noqa: E731
    house = post("/locations", {"name": "96 Anthony Street"})["id"]
    farm = post("/locations", {"name": "Farm"})["id"]
    hws = post("/positions", {"name": "Hot water", "location_id": house})["id"]
    pump = post("/positions", {"name": "Bore pump", "location_id": farm})["id"]
    post(f"/positions/{hws}/failure-modes", {"text": "Tank corrodes", "function": "Heat water"})
    post(f"/positions/{pump}/failure-modes", {"text": "Impeller wears", "function": "Pump water"})

    whole = _ok(client.get("/api/maintenance/tree"))
    assert "summary" in whole and {p["name"] for p in whole["positions"]} == {"Hot water", "Bore pump"}
    one = _ok(client.get("/api/maintenance/tree", params={"within": house}))
    assert "summary" not in one  # the workspace's counts are every asset's
    assert {p["name"] for p in one["positions"]} == {"Hot water"}
    assert {loc["name"] for loc in one["locations"]} == {"96 Anthony Street"}
    assert client.get("/api/maintenance/tree", params={"within": "nope"}).status_code == 404

    assert {p["id"] for p in _ok(client.get("/api/maintenance/rcm"))["positions"]} == {hws, pump}
    assert [p["id"] for p in _ok(client.get("/api/maintenance/rcm", params={"within": house}))["positions"]] == [hws]

    assert _ok(client.get("/api/maintenance/position-models", params={"within": farm}))["links"] == []
    assert _ok(client.get("/api/maintenance/position-missions", params={"within": farm}))["links"] == []
    assert client.get("/api/maintenance/position-models", params={"within": "nope"}).status_code == 404


# ---- merging one asset into another, and back (Derryn, 14 Nov 2026: "Alternately, they can merge one
# asset into another"). The app does it with the tree's own moves (frontend/src/assetMerge.js): a place
# goes inside a location of the other asset (location parent_id), a top position inside one of its
# positions (parent_id) or at one of its locations (location_id). Make this its own asset clears them.

def _assets(m):
    return {p["name"] for p in m.places()["places"]}


def test_a_place_merged_into_another_asset_comes_with_everything_and_splits_off_again(m):
    ids = _two_assets(m)
    before_farm = _names(m.tree_rows(within=ids["farm"]))
    assert {"96 Anthony Street", "Farm"} <= _assets(m)

    # Merge: the farm goes inside the house's kitchen.
    m.update_location(ids["farm"], parent_id=ids["kitchen"])
    live = m.s.snapshot()
    m.s.rebuild()
    assert m.s.snapshot() == live
    assert "Farm" not in _assets(m) and "96 Anthony Street" in _assets(m)
    positions, locations, spares, _ = _names(m.tree_rows(within=ids["house"]))
    assert {"Bore pump", "Hot water", "Element"} <= positions
    assert {"Farm", "Kitchen"} <= locations and {"Farm spare", "Spare element"} <= spares
    # Its history and RCM came along: the pump's failure mode and fitted item are still on it.
    assert "Impeller wears" in str(m.rcm_all(within=ids["house"]))
    assert m.position(ids["pump"])["fitted"]["item"]["name"] == "Pump unit"

    # Make this its own asset: back as it was.
    m.update_location(ids["farm"], parent_id=None)
    live = m.s.snapshot()
    m.s.rebuild()
    assert m.s.snapshot() == live
    assert {"96 Anthony Street", "Farm"} <= _assets(m)
    assert _names(m.tree_rows(within=ids["farm"])) == before_farm
    assert "Bore pump" not in _names(m.tree_rows(within=ids["house"]))[0]


def test_a_top_position_merged_inside_a_position_and_at_a_location_then_its_own_again(m):
    ids = _two_assets(m)
    skid = m.create_position("Skid")["id"]
    m.create_position("Skid motor", parent_id=skid)
    assert "Skid" in _names(m.tree_rows(within=skid))[0]

    # Inside the house's hot water: the house's tree has it; it's no asset of its own.
    m.update_position(skid, parent_id=ids["hws"])
    assert {"Skid", "Skid motor"} <= _names(m.tree_rows(within=ids["house"]))[0]
    assert "Skid" not in _names(m.tree_rows(within=ids["farm"]))[0]
    # Back: a top position at no place again (its own asset).
    m.update_position(skid, parent_id=None)
    assert "Skid" not in _names(m.tree_rows(within=ids["house"]))[0]
    assert {"Skid", "Skid motor"} == _names(m.tree_rows(within=skid))[0]

    # At the farm (a location): the farm's tree has it.
    m.update_position(skid, location_id=ids["farm"])
    assert {"Skid", "Skid motor"} <= _names(m.tree_rows(within=ids["farm"]))[0]
    m.update_position(skid, location_id=None)
    assert "Skid" not in _names(m.tree_rows(within=ids["farm"]))[0]
    live = m.s.snapshot()
    m.s.rebuild()
    assert m.s.snapshot() == live
