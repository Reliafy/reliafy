"""Positions (functional locations) linked to locations (the physical tree): a
position's location, set or inherited; a fitted item is where its position is;
placements only for items that aren't fitted; a location's view of the positions
and items there; work orders by area."""

from datetime import date, timedelta

import mongomock
import pytest

from backend.maintenance import service
from backend.maintenance.service import PROJECTORS, Invalid, Maintenance
from backend.maintenance.store import GraphStore

ORG = "user-l"


@pytest.fixture()
def m():
    return Maintenance(GraphStore(":memory:", PROJECTORS), ORG, "tester")


def _ago(days: int) -> str:
    return (date.today() - timedelta(days=days)).isoformat()


def _plant(m):
    """Electrical > MCC-3 > Feeder 12 / Feeder 13, and Conveyors > Belt 1 > Drive; Site >
    Area X > Substation 2, and Site > Conveyor gallery."""
    site = m.create_location("Site")["id"]
    area = m.create_location("Area X", parent_id=site)["id"]
    sub = m.create_location("Substation 2", parent_id=area)["id"]
    gallery = m.create_location("Conveyor gallery", parent_id=site)["id"]
    elec = m.create_position("Electrical")["id"]
    mcc = m.create_position("MCC-3", parent_id=elec, location_id=sub)["id"]
    f12 = m.create_position("Feeder 12", parent_id=mcc, location_id=gallery)["id"]
    f13 = m.create_position("Feeder 13", parent_id=mcc)["id"]
    conv = m.create_position("Conveyors")["id"]
    belt = m.create_position("Belt 1", parent_id=conv, location_id=gallery)["id"]
    drive = m.create_position("Drive", parent_id=belt)["id"]
    return {"site": site, "area": area, "sub": sub, "gallery": gallery, "elec": elec, "mcc": mcc,
            "f12": f12, "f13": f13, "conv": conv, "belt": belt, "drive": drive}


# ---- a position's location ---------------------------------------------------------------

def test_a_position_inherits_its_parents_location_and_a_child_can_override(m):
    p = _plant(m)
    assert m.position(p["elec"])["location"] is None  # unset everywhere is fine
    mcc = m.position(p["mcc"])["location"]
    assert (mcc["id"], mcc["inherited"], mcc["inherited_from"]) == (p["sub"], False, None)
    assert mcc["display"] == "Site › Area X › Substation 2"
    assert [a["name"] for a in mcc["path"]] == ["Site", "Area X"]
    f13 = m.position(p["f13"])["location"]
    assert (f13["id"], f13["inherited"]) == (p["sub"], True)
    assert f13["inherited_from"] == {"id": p["mcc"], "name": "MCC-3", "kind": "Position"}
    f12 = m.position(p["f12"])["location"]
    assert (f12["name"], f12["inherited"]) == ("Conveyor gallery", False)

    # Moving MCC-3 moves Feeder 13 with it; clearing it leaves both unset.
    m.update_position(p["mcc"], location_id=p["area"])
    assert m.position(p["f13"])["location"]["name"] == "Area X"
    m.update_position(p["mcc"], location_id=None)
    assert m.position(p["mcc"])["location"] is None and m.position(p["f13"])["location"] is None
    assert m.position(p["f12"])["location"]["name"] == "Conveyor gallery"


def test_a_location_must_exist_in_the_workspace(m):
    pid = m.create_position("Pump")["id"]
    with pytest.raises(service.NotFound):
        m.update_position(pid, location_id="nope")
    with pytest.raises(service.NotFound):
        m.create_position("Pump B", location_id=pid)  # a position isn't a location
    other = Maintenance(m.s, "user-other", "x")
    theirs = other.create_location("Their shed")["id"]
    with pytest.raises(service.NotFound):
        m.update_position(pid, location_id=theirs)


def test_setting_the_same_location_again_records_nothing(m):
    shed = m.create_location("Shed")["id"]
    pid = m.create_position("Pump", location_id=shed)["id"]
    before = m.s.event_count(ORG)
    m.update_position(pid, location_id=shed)
    assert m.s.event_count(ORG) == before
    m.update_position(pid, location_id="")
    assert m.position(pid)["location"] is None


def test_positions_inside_an_item_are_where_the_item_is(m):
    yard, workshop = m.create_location("Truck yard")["id"], m.create_location("Workshop")["id"]
    truck = m.create_position("Truck 14", location_id=yard)["id"]
    m.fit(truck, new_item={"name": "Engine", "serial": "E123"})
    engine = m.position(truck)["fitted"]["item"]["id"]
    turbo = m.create_position("Turbo 1", parent_id=engine)["id"]
    view = m.position(turbo)["location"]
    assert view["name"] == "Truck yard" and view["inherited_from"]["id"] == truck
    # The engine comes out and goes to the workshop: its turbo position goes with it.
    m.remove(truck)
    assert m.position(turbo)["location"] is None  # out, and not placed yet
    m.place_item(engine, workshop)
    view = m.position(turbo)["location"]
    assert view["name"] == "Workshop" and view["inherited_from"] == {"id": engine, "name": "Engine", "kind": "Item"}


def test_a_copy_takes_the_locations_set_on_the_original(m):
    p = _plant(m)
    copy = m.copy_position(p["mcc"], "MCC-4", parent_id=p["elec"])
    assert copy["location"]["id"] == p["sub"] and not copy["location"]["inherited"]
    kids = {c["name"]: c["id"] for c in copy["children"]}
    assert m.position(kids["Feeder 12"])["location"]["name"] == "Conveyor gallery"
    assert m.position(kids["Feeder 13"])["location"]["inherited_from"]["id"] == copy["id"]
    created = [e for e in m.s.events(ORG, 50) if e["type"] == "position.created"]
    # Only a location set on the original travels in the event.
    by_name = {e["payload"]["name"]: e["payload"] for e in created}
    assert "location_id" not in by_name["Feeder 13"] and by_name["MCC-4"]["location_id"] == p["sub"]


# ---- a fitted item is where its position is ---------------------------------------------------

def test_a_fitted_item_is_where_its_position_is(m):
    p = _plant(m)
    m.fit(p["f13"], new_item={"name": "Breaker", "serial": "B1"}, on=_ago(100))
    iid = m.position(p["f13"])["fitted"]["item"]["id"]
    item = m.item(iid)
    assert item["location"]["id"] == p["sub"] and item["location"]["how"] == "fitted"
    assert item["location"]["position"]["id"] == p["f13"] and item["last_at"] is None
    assert item["location"]["inherited_from"]["name"] == "MCC-3"
    listed = next(i for i in m.items() if i["id"] == iid)
    assert listed["location"]["name"] == "Substation 2" and listed["location"]["how"] == "fitted"
    # Placing it is refused, with what to do instead.
    with pytest.raises(Invalid, match=r"fitted to Feeder 13.*\(Site › Area X › Substation 2\).*location_id"):
        m.place_item(iid, p["gallery"])
    # Moving the position moves the item.
    m.update_position(p["f13"], location_id=p["gallery"])
    assert m.item(iid)["location"]["name"] == "Conveyor gallery"


def test_a_removed_item_is_last_at_its_position_until_placed(m):
    p = _plant(m)
    store = m.create_location("Store", parent_id=p["site"])["id"]
    m.fit(p["f13"], new_item={"name": "Breaker"}, on=_ago(100))
    iid = m.position(p["f13"])["fitted"]["item"]["id"]
    m.remove(p["f13"], on=_ago(5))
    item = m.item(iid)
    assert item["location"] is None
    assert item["last_at"]["location"]["id"] == p["sub"] and item["last_at"]["position"]["id"] == p["f13"]
    assert item["last_at"]["since"] == _ago(5)
    assert next(i for i in m.items() if i["id"] == iid)["last_at"]["name"] == "Substation 2"
    with pytest.raises(Invalid, match="came out of Feeder 13"):
        m.place_item(iid, store, on=_ago(10))
    item = m.place_item(iid, store)
    assert item["location"]["how"] == "placed" and item["location"]["name"] == "Store"
    assert item["last_at"] is None and item["placements"][0]["current"]
    # Fitted again elsewhere: the store placement stays in the history but no longer says where it is.
    m.fit(p["drive"], item_id=iid)
    item = m.item(iid)
    assert item["location"]["name"] == "Conveyor gallery" and not item["placements"][0]["current"]
    assert item["placements"][0]["to"] is None  # the history isn't rewritten


def test_a_spare_is_where_it_is_placed(m):
    store = m.create_location("Store A")["id"]
    spare = m.create_item("Spare anode")["id"]
    assert m.item(spare)["location"] is None and m.item(spare)["last_at"] is None
    item = m.place_item(spare, store)
    assert (item["location"]["name"], item["location"]["how"], item["location"]["since"]) == \
        ("Store A", "placed", date.today().isoformat())


def test_old_placements_of_fitted_items_stay_in_the_history_but_dont_decide(m):
    """Events from before the change: an item placed while fitted (the old default)."""
    plant_room, store = m.create_location("Plant room")["id"], m.create_location("Store")["id"]
    pid = m.create_position("Hot water system")["id"]
    m.fit(pid, new_item={"name": "Rheem 315"}, on="2019-03-01")
    iid = m.position(pid)["fitted"]["item"]["id"]
    m._emit("item.placed", {"item_id": iid, "location_id": plant_room, "placement_id": "pl1", "on": "2019-03-01"})
    item = m.item(iid)
    assert item["location"] is None  # the position has no location yet
    assert item["placements"] == [{"from": "2019-03-01", "to": None, "current": False,
                                   "location": {"id": plant_room, "name": "Plant room"}}]
    assert m.location(plant_room)["items"] == [] and m.location(plant_room)["counts"]["items"] == 0
    # The one-off tidy-up offers the placement as the position's location...
    spare = m.create_item("Spare element")["id"]
    m.place_item(spare, store, on="2018-01-01")
    pid2 = m.create_position("Spare heater")["id"]
    m.fit(pid2, item_id=spare, on="2020-01-01")  # placed in the store before it went in: left alone
    plan = m.adopt_placements()
    assert plan["dry_run"] and [c["position"]["id"] for c in plan["changes"]] == [pid]
    assert plan["skipped"][0]["item"]["id"] == spare and "before it was fitted" in plan["skipped"][0]["why"]
    assert m.position(pid)["location"] is None  # a dry run writes nothing
    done = m.adopt_placements(dry_run=False)
    assert not done["dry_run"] and m.position(pid)["location"]["name"] == "Plant room"
    assert m.item(iid)["location"]["name"] == "Plant room"
    # ...and running it again finds nothing more to do.
    again = m.adopt_placements()
    assert again["changes"] == [] and "already there" in again["skipped"][0]["why"]


def test_adopting_leaves_a_position_with_its_own_location(m):
    a, b = m.create_location("A")["id"], m.create_location("B")["id"]
    pid = m.create_position("Pump", location_id=a)["id"]
    m.fit(pid, new_item={"name": "Astral"}, on="2020-01-01")
    iid = m.position(pid)["fitted"]["item"]["id"]
    m._emit("item.placed", {"item_id": iid, "location_id": b, "placement_id": "pl2", "on": "2020-01-01"})
    plan = m.adopt_placements(dry_run=False)
    assert plan["changes"] == [] and "its own location already: A" in plan["skipped"][0]["why"]
    assert m.position(pid)["location"]["name"] == "A"


# ---- a location's view ---------------------------------------------------------------------------

def test_a_location_shows_its_positions_by_system_rolled_up_and_its_loose_items(m):
    p = _plant(m)
    store = m.create_location("Store", parent_id=p["site"])["id"]
    m.fit(p["f13"], new_item={"name": "Breaker", "serial": "B1"})
    m.fit(p["drive"], new_item={"name": "Motor", "serial": "M1"})
    spare = m.create_item("Spare breaker")["id"]
    m.place_item(spare, store)
    m.open_work_order(p["drive"], "Noisy")

    sub = m.location(p["sub"])
    assert [g["system"]["name"] for g in sub["systems"]] == ["Electrical"]
    rows = sub["systems"][0]["positions"]
    assert [(r["path"], r["direct"]) for r in rows] == [("Electrical › MCC-3", True),
                                                       ("Electrical › MCC-3 › Feeder 13", False)]
    assert rows[1]["inherited_from"]["name"] == "MCC-3" and rows[1]["item"]["serial"] == "B1"
    assert sub["counts"] == {"positions_here": 2, "positions": 2, "fitted_items": 1, "items_here": 0, "items": 0,
                             "open_work_orders": 0}

    site = m.location(p["site"])
    assert [(g["system"]["name"], g["count"]) for g in site["systems"]] == [("Conveyors", 2), ("Electrical", 3)]
    gallery_rows = [r for g in site["systems"] for r in g["positions"] if r["location"]["id"] == p["gallery"]]
    assert {r["name"] for r in gallery_rows} == {"Feeder 12", "Belt 1", "Drive"}
    assert site["counts"] == {"positions_here": 0, "positions": 5, "fitted_items": 2, "items_here": 0, "items": 1,
                              "open_work_orders": 1}
    assert site["items"] == [{**m._item_brief(m.s.node(ORG, spare)), "since": date.today().isoformat(),
                              "location": {"id": store, "name": "Store"}}]
    assert {c["name"]: (c["positions"], c["items"]) for c in site["children"]} == {
        "Area X": (2, 0), "Conveyor gallery": (3, 0), "Store": (0, 1)}
    assert not site["positions_truncated"]

    # The tree: here, and with what's inside.
    tree = {n["name"]: n for n in m.location_tree()[0]["children"]}
    assert (tree["Area X"]["positions"], tree["Area X"]["all_positions"]) == (0, 2)
    assert (tree["Conveyor gallery"]["positions"], tree["Store"]["items"]) == (3, 1)
    assert m.location_tree()[0]["all_positions"] == 5 and m.location_tree()[0]["all_items"] == 1


def test_a_location_lists_at_most_so_many_positions_but_counts_them_all(m, monkeypatch):
    monkeypatch.setattr(service, "MAX_LOCATION_POSITIONS", 3)
    shed = m.create_location("Shed")["id"]
    top = m.create_position("System", location_id=shed)["id"]
    for i in range(5):
        m.create_position(f"P{i}", parent_id=top)
    view = m.location(shed)
    assert view["counts"]["positions"] == 6 and view["positions_truncated"]
    assert sum(len(g["positions"]) for g in view["systems"]) == 3


def test_retired_positions_leave_the_location(m):
    shed = m.create_location("Shed")["id"]
    pid = m.create_position("Old pump", location_id=shed)["id"]
    m.retire_position(pid)
    assert m.location(shed)["counts"]["positions"] == 0


# ---- work orders by area ---------------------------------------------------------------------------

def test_work_orders_by_location_including_the_locations_inside_it(m):
    p = _plant(m)
    a = m.open_work_order(p["f13"], "Trip test")
    b = m.open_work_order(p["drive"], "Noisy")
    c = m.open_work_order(p["elec"], "Survey")  # no location anywhere above it
    assert {w["id"] for w in m.work_orders("open", p["sub"])} == {a["id"]}
    assert {w["id"] for w in m.work_orders("open", p["area"])} == {a["id"]}
    assert {w["id"] for w in m.work_orders("open", p["site"])} == {a["id"], b["id"]}
    assert {w["id"] for w in m.work_orders(None, p["gallery"])} == {b["id"]}
    assert len(m.work_orders("open")) == 3
    by_id = {w["id"]: w for w in m.work_orders()}
    assert by_id[a["id"]]["location"]["display"] == "Site › Area X › Substation 2"
    assert by_id[c["id"]]["location"] is None
    assert m.work_order(b["id"])["location"]["name"] == "Conveyor gallery"
    with pytest.raises(service.NotFound):
        m.work_orders("open", "nope")


# ---- the projection --------------------------------------------------------------------------------

def test_rebuild_gives_the_same_graph(m):
    test_a_position_inherits_its_parents_location_and_a_child_can_override(m)
    before = m.s.snapshot()
    m.s.rebuild()
    assert m.s.snapshot() == before


def test_events_without_a_location_project_as_before():
    s = GraphStore(":memory:", PROJECTORS)
    s.apply(ORG, "position.created", {"id": "p1", "name": "Pump", "tag": "", "parent_id": None,
                                      "position_class": "", "description": "", "on": "2026-01-01"})
    s.apply(ORG, "position.updated", {"id": "p1", "changes": {"name": "Pump A"}})
    assert s.out(ORG, "p1", "LOCATED_AT") == [] and s.node(ORG, "p1")["name"] == "Pump A"
    assert "location_id" not in s.node(ORG, "p1")


# ---- through the API and MCP -----------------------------------------------------------------------

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
    monkeypatch.setattr(config, "MAINTENANCE_EMAILS", {"l@example.org"})
    test_db = mongomock.MongoClient()["maint_locations_api"]
    monkeypatch.setattr(db, "_db", test_db)
    monkeypatch.setattr(db, "_simulated", True)
    monkeypatch.setattr(router, "_store", GraphStore(":memory:", PROJECTORS))
    user = {"uid": "user-l", "email": "l@example.org", "name": "L", "email_verified": True}
    test_db.users.insert_one({"_id": "user-l", "email": "l@example.org", "name": "L", "email_verified": True})
    app.dependency_overrides[get_current_user] = lambda: user
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()


def test_locations_through_the_api(api):
    base = "/api/maintenance"
    site = api.post(f"{base}/locations", json={"name": "Site"}).json()["id"]
    sub = api.post(f"{base}/locations", json={"name": "Substation 2", "parent_id": site}).json()["id"]
    mcc = api.post(f"{base}/positions", json={"name": "MCC-3", "location_id": sub}).json()["id"]
    feeder = api.post(f"{base}/positions", json={"name": "Feeder 13", "parent_id": mcc}).json()["id"]
    pos = api.get(f"{base}/positions/{feeder}").json()
    assert pos["location"]["display"] == "Site › Substation 2" and pos["location"]["inherited"]
    assert api.post(f"{base}/positions", json={"name": "X", "location_id": "nope"}).status_code == 404
    wo = api.post(f"{base}/work-orders", json={"position_id": feeder, "title": "Trip test"}).json()
    assert [w["id"] for w in api.get(f"{base}/work-orders", params={"status": "open", "location_id": site})
            .json()["work_orders"]] == [wo["id"]]
    other = api.post(f"{base}/locations", json={"name": "Elsewhere"}).json()["id"]
    assert api.get(f"{base}/work-orders", params={"location_id": other}).json()["work_orders"] == []
    loc = api.get(f"{base}/locations/{site}").json()
    assert loc["counts"]["positions"] == 2 and loc["counts"]["open_work_orders"] == 1
    listed = api.get(f"{base}/locations").json()
    assert {x["display"] for x in listed["locations"]} == {"Site", "Site › Substation 2", "Elsewhere"}
    assert listed["tree"][1]["all_positions"] == 2  # Elsewhere, then Site

    # A fitted item can't be placed; clearing the location leaves the position unset.
    item = api.post(f"{base}/positions/{feeder}/fit", json={"new_item": {"name": "Breaker"}}).json()["fitted"]["item"]
    refused = api.post(f"{base}/items/{item['id']}/place", json={"location_id": other})
    assert refused.status_code == 422 and "position's location" in refused.json()["detail"]
    assert api.get(f"{base}/items/{item['id']}").json()["location"]["how"] == "fitted"
    cleared = api.patch(f"{base}/positions/{mcc}", json={"location_id": None}).json()
    assert cleared["location"] is None
    assert api.post(f"{base}/locations/adopt-placements", json={}).json() == {"dry_run": True, "changes": [],
                                                                             "skipped": []}


# ---- the assets: top-level places ------------------------------------------------------------

def _home(m):
    """A house the way people set one up: one top-level place with places inside it,
    positions located at different levels, and positions at no place at all."""
    home = m.create_location("96 Example Street")["id"]
    house = m.create_location("House", parent_id=home)["id"]
    lower = m.create_location("Lower floor", parent_id=house)["id"]
    bedroom = m.create_location("Bedroom 3", parent_id=lower)["id"]
    pool_area = m.create_location("Pool area", parent_id=home)["id"]
    m.create_location("Shed", parent_id=home)
    pool = m.create_position("Swimming pool", location_id=pool_area)["id"]
    pump = m.create_position("Pool pump", parent_id=pool)["id"]  # inherits the pool area
    aircon = m.create_position("Air conditioner", location_id=bedroom)["id"]
    car = m.create_position("Family car")["id"]  # at no place
    tyres = m.create_position("Tyres", parent_id=car)["id"]
    dishwasher = m.create_position("Dishwasher")["id"]
    return {"home": home, "house": house, "bedroom": bedroom, "pool_area": pool_area, "pool": pool,
            "pump": pump, "aircon": aircon, "car": car, "tyres": tyres, "dishwasher": dishwasher}


def test_the_assets_are_the_top_level_places_with_everything_inside_counted(m):
    h = _home(m)
    m.fit(h["pump"], new_item={"name": "Pump", "serial": "P1"})
    m.fit(h["aircon"], new_item={"name": "Split system"})
    m.fit(h["tyres"], new_item={"name": "Tyre set"})
    spare = m.create_item("Spare filter")["id"]
    m.place_item(spare, h["pool_area"])
    m.open_work_order(h["pump"], "Noisy")
    m.open_work_order(None, "Check the gutters", location_id=h["house"])
    m.open_work_order(h["car"], "Service")
    m.create_task(h["aircon"], "Clean the filters", 1, "weeks")  # due within 30 days
    m.create_task(h["pool"], "Test the water", 6, "months", last_done=_ago(400))  # overdue
    m.create_task(h["pump"], "Replace the seal", 2, "years")  # not due yet
    m.create_task(h["dishwasher"], "Clean the filter", 2, "weeks")

    view = m.places()
    assert view["horizon_days"] == 30
    [home] = view["places"]
    assert {k: home[k] for k in ("name", "locations", "positions", "items", "open_work_orders", "due", "overdue")} == {
        "name": "96 Example Street", "locations": 5, "positions": 3, "items": 3, "open_work_orders": 2,
        "due": 2, "overdue": 1}
    assert home["next_due"] == min(t["next_due"] for t in m.due_tasks(30) if t["name"] != "Clean the filter")
    rest = view["not_placed"]
    assert {k: rest[k] for k in ("positions", "items", "open_work_orders", "due", "overdue")} == {
        "positions": 3, "items": 1, "open_work_orders": 1, "due": 1, "overdue": 0}
    assert set(rest["position_ids"]) == {h["car"], h["tyres"], h["dishwasher"]}

    # A second property is a second asset; placing the car there moves it (and its tyres) across.
    other = m.create_location("Beach house")["id"]
    m.create_location("Garage", parent_id=other)
    m.update_position(h["car"], location_id=other)
    view = m.places()
    assert [(p["name"], p["positions"], p["items"], p["open_work_orders"], p["locations"]) for p in view["places"]] == [
        ("96 Example Street", 3, 3, 2, 5), ("Beach house", 2, 1, 1, 1)]
    assert view["not_placed"]["position_ids"] == [h["dishwasher"]]

    # A retired position doesn't count.
    m.retire_position(h["dishwasher"], "Sold")
    assert m.places()["not_placed"]["positions"] == 0
    # A place moved to the top level becomes an asset, taking what's inside it.
    m.update_location(h["bedroom"], parent_id=None)
    assert [(p["name"], p["positions"]) for p in m.places()["places"]] == [
        ("96 Example Street", 2), ("Beach house", 2), ("Bedroom 3", 1)]


def test_no_places_means_no_assets_and_every_position_is_not_placed(m):
    pid = m.create_position("Pump")["id"]
    assert m.places() == {"places": [], "horizon_days": 30, "not_placed": {
        "positions": 1, "items": 0, "open_work_orders": 0, "due": 0, "overdue": 0, "next_due": None,
        "position_ids": [pid]}}
