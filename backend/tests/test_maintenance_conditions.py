"""Reliafy Maintenance: conditions, what locations, positions, items and connections
are exposed to (Outdoor, Seawater, Zone 1, Ambient temperature). A register of the
workspace's own, applied to things and inherited down the trees when read.
(Condition monitoring, measurement points with alarms, is test_maintenance_condition.py.)"""

import json

import mongomock
import pytest

from backend.maintenance import conditions as register_io
from backend.maintenance.service import (
    MAX_CONDITION_DEPTH, PROJECTORS, Invalid, LimitReached, Maintenance, NotFound,
)
from backend.maintenance.store import GraphStore
from backend.tests.neo4j_support import plant

ORG = "org-cond"


@pytest.fixture()
def m():
    return Maintenance(GraphStore(":memory:", PROJECTORS), ORG, "tester")


def _rebuilds(m):
    """Replaying the log gives the graph as it is."""
    before = m.s.snapshot()
    m.s.rebuild()
    assert m.s.snapshot() == before


def _names(view, key="conditions"):
    return {e["condition"]["display"]: (e["value"], e["source"]["name"], e["own"]) for e in view[key]}


def _plant(m):
    """Site > (Area 2, Control room); a cooling system in Area 2 with a pump inside it
    (fitted), and a PLC in the control room."""
    site = m.create_location("Site")
    area = m.create_location("Area 2", site["id"])
    room = m.create_location("Control room", site["id"])
    cooling = m.create_position("Cooling", location_id=area["id"])
    pump = m.create_position("Pump", parent_id=cooling["id"])
    plc = m.create_position("PLC", location_id=room["id"])
    item = m.fit(pump["id"], new_item={"name": "P1", "serial": "S1"})["fitted"]["item"]
    return {"site": site, "area": area, "room": room, "cooling": cooling, "pump": pump, "plc": plc, "item": item}


# ---- the acceptance criteria -------------------------------------------------------------------

def test_a_condition_on_a_site_reaches_every_position_in_it_and_the_items_fitted(m):
    p = _plant(m)
    outdoor = m.create_condition("Outdoor")
    m.apply_condition(p["site"]["id"], outdoor["id"])
    for key in ("pump", "cooling", "plc"):
        assert _names(m.position(p[key]["id"])) == {"Outdoor": (None, "Site", False)}, key
    assert _names(m.item(p["item"]["id"])) == {"Outdoor": (None, "Site", False)}
    assert _names(m.location(p["area"]["id"])) == {"Outdoor": (None, "Site", False)}
    assert _names(m.location(p["site"]["id"])) == {"Outdoor": (None, "Site", True)}
    got = m.conditions_of(p["pump"]["id"])
    assert got["target"] == {"id": p["pump"]["id"], "name": "Pump", "kind": "Position"}
    assert got["conditions"][0]["source"] == {"id": p["site"]["id"], "name": "Site", "kind": "Location"}
    # A spare placed in a store on the site has it too; one placed nowhere has only its own.
    store = m.create_location("Store", p["site"]["id"])
    spare = m.create_item("Spare pump")
    assert _names(m.item(spare["id"])) == {}
    m.place_item(spare["id"], store["id"])
    assert _names(m.item(spare["id"])) == {"Outdoor": (None, "Site", False)}
    _rebuilds(m)


def test_an_exclusion_stops_an_inherited_condition_and_a_move_brings_it_back(m):
    p = _plant(m)
    outdoor = m.create_condition("Outdoor")
    m.apply_condition(p["site"]["id"], outdoor["id"])
    got = m.exclude_condition(p["room"]["id"], outdoor["id"], "air-conditioned building")
    assert got["conditions"] == [] and got["excluded"][0]["own"] and got["excluded"][0]["note"] == \
        "air-conditioned building"
    plc = m.position(p["plc"]["id"])
    assert plc["conditions"] == []
    assert _names(plc, "excluded_conditions") == {"Outdoor": (None, "Control room", False)}
    # Moved out of the room, the PLC is outdoors again; moved back, it isn't.
    m.update_position(p["plc"]["id"], location_id=p["area"]["id"])
    assert _names(m.position(p["plc"]["id"])) == {"Outdoor": (None, "Site", False)}
    m.update_position(p["plc"]["id"], location_id=p["room"]["id"])
    assert m.position(p["plc"]["id"])["conditions"] == []
    # So for the item fitted at a position moved into the room, and for the room moved off the site.
    m.update_position(p["cooling"]["id"], location_id=p["room"]["id"])
    assert m.item(p["item"]["id"])["conditions"] == []
    m.update_location(p["room"]["id"], parent_id=None)
    assert m.position(p["plc"]["id"])["excluded_conditions"][0]["source"]["name"] == "Control room"
    # Taking the exclusion off: what's above applies again (once the room is back on the site).
    m.update_location(p["room"]["id"], parent_id=p["site"]["id"])
    m.remove_condition(p["room"]["id"], outdoor["id"])
    assert _names(m.position(p["plc"]["id"])) == {"Outdoor": (None, "Site", False)}
    _rebuilds(m)


def test_a_value_set_lower_down_overrides_one_from_above(m):
    p = _plant(m)
    temp = m.create_condition("Ambient temperature", unit="°C")
    assert (temp["kind"], temp["unit"]) == ("value", "°C")
    m.apply_condition(p["site"]["id"], temp["id"], 40)
    m.apply_condition(p["area"]["id"], temp["id"], "55 °C", "sun all day")
    assert _names(m.position(p["pump"]["id"])) == {"Ambient temperature": (55.0, "Area 2", False)}
    assert m.position(p["pump"]["id"])["conditions"][0]["note"] == "sun all day"
    assert _names(m.item(p["item"]["id"])) == {"Ambient temperature": (55.0, "Area 2", False)}
    assert _names(m.position(p["plc"]["id"])) == {"Ambient temperature": (40.0, "Site", False)}
    # A position's own value beats its location's; positions above it come before where it is.
    m.apply_condition(p["cooling"]["id"], temp["id"], 30)
    assert _names(m.position(p["pump"]["id"])) == {"Ambient temperature": (30.0, "Cooling", False)}
    m.apply_condition(p["pump"]["id"], temp["id"], 70)
    assert _names(m.item(p["item"]["id"])) == {"Ambient temperature": (70.0, "Pump", False)}
    # Applying again changes the value; checks on what a value is.
    m.apply_condition(p["pump"]["id"], temp["id"], 65)
    assert m.position(p["pump"]["id"])["conditions"][0]["value"] == 65.0
    with pytest.raises(Invalid, match="°C"):
        m.apply_condition(p["pump"]["id"], temp["id"], "150 °F")
    with pytest.raises(Invalid, match="number"):
        m.apply_condition(p["pump"]["id"], temp["id"], "hot")
    outdoor = m.create_condition("Outdoor")
    with pytest.raises(Invalid, match="has no value"):
        m.apply_condition(p["pump"]["id"], outdoor["id"], 1)
    events = len(m.s.events(ORG, 1000))
    m.apply_condition(p["pump"]["id"], temp["id"], 65)  # nothing new: no event
    assert len(m.s.events(ORG, 1000)) == events
    _rebuilds(m)


def test_retiring_a_condition_hides_it_and_keeps_the_history(m):
    p = _plant(m)
    outdoor = m.create_condition("Outdoor")
    coastal = m.create_condition("Coastal")
    m.apply_condition(p["site"]["id"], outdoor["id"])
    m.apply_condition(p["site"]["id"], coastal["id"], note="2 km from the sea")
    m.exclude_condition(p["room"]["id"], outdoor["id"])
    m.retire_condition(outdoor["id"], "not tracked")
    for view in (m.position(p["pump"]["id"]), m.position(p["plc"]["id"]), m.location(p["site"]["id"])):
        assert list(_names(view)) == ["Coastal"] and view["excluded_conditions"] == []
    assert [c["name"] for c in m.conditions()] == ["Coastal"]
    assert [c["name"] for c in m.condition_tree()["tree"]] == ["Coastal"]
    # The register and the log still hold it.
    gone = m.condition(outdoor["id"])
    assert gone["retired"] and gone["applied_to"][0]["name"] == "Site"
    types = [e["type"] for e in m.s.events(ORG, 1000)]
    assert types.count("condition.applied") == 3 and "condition.retired" in types
    with pytest.raises(Invalid, match="retired"):
        m.apply_condition(p["pump"]["id"], outdoor["id"])
    with pytest.raises(Invalid, match="retired"):
        m.retire_condition(outdoor["id"])
    _rebuilds(m)


def test_import_and_export_by_path_round_trip_with_a_dry_run_first(m):
    rows = register_io.rows_from_csv(
        "path,kind,unit,code,description\n"
        "Outdoor,,,ENV-OUT,Open to the weather\n"
        "Hazardous area > Zone 1,,,HA-1,\n"
        "Hazardous area > Zone 2,,,,\n"
        "Ambient temperature,value,°C,,\n")
    dry = register_io.run(m, rows)
    assert dry["dry_run"] and dry["ok"] and dry["counts"]["create"] == 5  # Hazardous area is implied
    assert m.conditions() == []
    done = register_io.run(m, rows, dry_run=False, source="site list")
    assert not done["dry_run"] and done["counts"]["create"] == 5
    assert [c["display"] for c in m.conditions()] == [
        "Ambient temperature", "Hazardous area", "Hazardous area › Zone 1", "Hazardous area › Zone 2", "Outdoor"]
    again = register_io.run(m, rows, dry_run=False)
    assert again["counts"] == {"create": 0, "update": 0, "unchanged": 4, "conflicts": 0, "errors": 0}

    other = Maintenance(GraphStore(":memory:", PROJECTORS), "org-other")
    for text, read in ((register_io.export_csv(m), register_io.rows_from_csv),
                       (json.dumps(register_io.export_json(m)), register_io.rows_from_json)):
        other_m = Maintenance(GraphStore(":memory:", PROJECTORS), "org-x")
        assert register_io.run(other_m, read(text), dry_run=False)["counts"]["create"] == 5
        assert register_io.export_rows(other_m) == register_io.export_rows(m)
    assert register_io.export_json(m)["format"] == "reliafy-conditions"

    # Filling in, conflicts left alone, and nothing written when any row is wrong.
    fill = register_io.run(m, register_io.rows_from_json([
        {"path": "Hazardous area > Zone 2", "code": "HA-2"}, {"path": "Outdoor", "code": "X", "kind": "value"}]),
        dry_run=False)
    assert fill["counts"]["update"] == 1 and {c["field"] for c in fill["conflicts"]} == {"code", "kind"}
    bad = register_io.run(other, register_io.rows_from_json([
        {"path": "New one"}, {"path": "Twice"}, {"path": "twice"}, {"name": "Unit", "kind": "presence", "unit": "m"}]),
        dry_run=False)
    assert not bad["ok"] and bad["counts"]["errors"] == 2 and other.conditions() == []
    with pytest.raises(Invalid):
        register_io.rows_from_csv("code\nX\n")
    _rebuilds(m)


def test_the_shared_plants_conditions_read_back_and_rebuild(m):
    """The plant the graph and Neo4j tests share carries conditions too: each shape
    reads back as it should, and the log rebuilds the same graph."""
    p = plant(m)
    turbo1 = m.item(p["engine"])["positions"][0]["id"]
    assert _names(m.position(turbo1)) == {"Ambient temperature": (90.0, "Engine E1", False)}
    f13 = m.position(p["f13"])
    assert _names(f13) == {"Ambient temperature": (55.0, "Area X", False),
                           "Hazardous area › Zone 1": (None, "MCC-3", False)}
    assert _names(f13, "excluded_conditions") == {"Outdoor": (None, "Substation 2", False)}
    assert _names(m.location(p["yard"])) == {}  # its only condition was retired
    assert _names(m.location(p["gallery"])) == {"Outdoor": (None, "Site", False),
                                                "Ambient temperature": (40.0, "Site", False)}
    line = m.connections(p["tank"])["downstream"][0]
    assert [e["condition"]["name"] for e in line["conditions"]] == ["Outdoor"]
    _rebuilds(m)


# ---- the register -----------------------------------------------------------------------------------

def test_the_register_is_a_tree_with_names_kinds_and_moves_checked(m):
    hazard = m.create_condition("Hazardous area", code="HA", description="Flammable atmospheres")
    zone1 = m.create_condition("Zone 1", hazard["id"])
    assert zone1["display"] == "Hazardous area › Zone 1" and zone1["parent"]["id"] == hazard["id"]
    with pytest.raises(Invalid, match="already"):
        m.create_condition("zone 1", hazard["id"])
    with pytest.raises(Invalid, match=">"):
        m.create_condition("Hazardous area > Zone 2")
    with pytest.raises(Invalid, match="unit"):
        m.create_condition("Outdoor", kind="presence", unit="m")
    with pytest.raises(Invalid, match="kind"):
        m.create_condition("Outdoor", kind="sometimes")
    with pytest.raises(NotFound):
        m.create_condition("Orphan", "nope")
    with pytest.raises(Invalid, match="inside itself"):
        m.update_condition(hazard["id"], parent_id=zone1["id"])
    parent = None
    for depth in range(MAX_CONDITION_DEPTH):
        parent = m.create_condition(f"Level {depth}", parent and parent["id"])
    with pytest.raises(Invalid, match="levels deep"):
        m.create_condition("Too deep", parent["id"])
    renamed = m.update_condition(zone1["id"], name="Zone 1 (gas)", code="Z1", parent_id=None)
    assert renamed["display"] == "Zone 1 (gas)" and renamed["code"] == "Z1"
    level0 = next(c for c in m.conditions() if c["name"] == "Level 0")
    with pytest.raises(Invalid, match="inside it"):
        m.retire_condition(level0["id"])
    # Kind and unit: a presence condition can become a value one; one with values stays one.
    salinity = m.create_condition("Salinity")
    salinity = m.update_condition(salinity["id"], unit="ppt")
    assert (salinity["kind"], salinity["unit"]) == ("value", "ppt")
    site = m.create_location("Site")
    m.apply_condition(site["id"], salinity["id"], 35)
    with pytest.raises(Invalid, match="stays a value"):
        m.update_condition(salinity["id"], kind="presence")
    assert m.update_condition(salinity["id"], unit="g/kg")["unit"] == "g/kg"
    tree = m.condition_tree()
    assert {c["name"]: c["applied"] for c in tree["tree"]}["Salinity"] == 1
    _rebuilds(m)


def test_connections_hold_only_their_own_conditions(m):
    a, b = m.create_position("Sea chest"), m.create_position("Cooler")
    seawater = m.create_condition("Seawater")
    m.apply_condition(a["id"], seawater["id"])
    line = m.connect(a["id"], b["id"], medium="seawater")
    assert line["conditions"] == []
    got = m.apply_condition(line["id"], seawater["id"], note="raw, unfiltered")
    assert got["target"]["kind"] == "Interface" and got["conditions"][0]["own"]
    assert m.position(a["id"])["connections"]["downstream"][0]["conditions"][0]["note"] == "raw, unfiltered"
    with pytest.raises(Invalid, match="only its own"):
        m.exclude_condition(line["id"], seawater["id"])
    assert m.position(b["id"])["conditions"] == []  # nothing passes along a connection
    m.disconnect(line["id"])
    with pytest.raises(Invalid, match="retired"):
        m.apply_condition(line["id"], seawater["id"])
    _rebuilds(m)


def test_positions_inside_an_item_take_the_items_and_its_positions_conditions(m):
    truck = m.create_position("Truck 14")
    engine = m.fit(truck["id"], new_item={"name": "Engine E1"})["fitted"]["item"]
    turbo = m.create_position("Turbo 1", parent_id=engine["id"])
    dusty, hot = m.create_condition("Dusty"), m.create_condition("High temperature")
    m.apply_condition(truck["id"], dusty["id"])
    m.apply_condition(engine["id"], hot["id"])
    assert _names(m.position(turbo["id"])) == {"Dusty": (None, "Truck 14", False),
                                                "High temperature": (None, "Engine E1", False)}
    # Out of the truck and into a store, the engine (and its turbo) take the store's.
    m.remove(truck["id"], reason="planned")
    workshop = m.create_location("Workshop")
    m.place_item(engine["id"], workshop["id"])
    indoor = m.create_condition("Indoor")
    m.apply_condition(workshop["id"], indoor["id"])
    assert set(_names(m.position(turbo["id"]))) == {"High temperature", "Indoor"}
    _rebuilds(m)


def test_removing_applies_only_to_what_is_set_there_and_limits_hold(m, monkeypatch):
    from backend.maintenance import service

    p = _plant(m)
    outdoor = m.create_condition("Outdoor")
    m.apply_condition(p["site"]["id"], outdoor["id"])
    with pytest.raises(Invalid, match="isn't set on"):
        m.remove_condition(p["pump"]["id"], outdoor["id"])
    with pytest.raises(NotFound):
        m.apply_condition(m.create_task(p["pump"]["id"], "Grease", 6)["id"], outdoor["id"])
    monkeypatch.setattr(service, "MAX_CONDITIONS_EACH", 1)
    other = m.create_condition("Coastal")
    with pytest.raises(LimitReached):
        m.apply_condition(p["site"]["id"], other["id"])
    m.apply_condition(p["site"]["id"], outdoor["id"], note="changing one already there is fine")
    monkeypatch.setattr(service, "MAX_CONDITIONS", 2)
    with pytest.raises(LimitReached):
        m.create_condition("Third")


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
    monkeypatch.setattr(config, "MAINTENANCE_EMAILS", {"c@example.org"})
    test_db = mongomock.MongoClient()["maint_conditions_api"]
    monkeypatch.setattr(db, "_db", test_db)
    monkeypatch.setattr(db, "_simulated", True)
    monkeypatch.setattr(router, "_store", GraphStore(":memory:", PROJECTORS))
    user = {"uid": "user-c2", "email": "c@example.org", "name": "C", "email_verified": True}
    test_db.users.insert_one({"_id": "user-c2", "email": "c@example.org", "name": "C", "email_verified": True})
    app.dependency_overrides[get_current_user] = lambda: user
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()


def test_conditions_through_the_api(api):
    base = "/api/maintenance"
    site = api.post(f"{base}/locations", json={"name": "Site"}).json()
    room = api.post(f"{base}/locations", json={"name": "Room", "parent_id": site["id"]}).json()
    pos = api.post(f"{base}/positions", json={"name": "Pump", "location_id": room["id"]}).json()
    outdoor = api.post(f"{base}/conditions", json={"name": "Outdoor"}).json()
    temp = api.post(f"{base}/conditions", json={"name": "Ambient temperature", "unit": "°C"}).json()
    r = api.post(f"{base}/conditions/of/{site['id']}", json={"condition_id": outdoor["id"]})
    assert r.status_code == 200 and r.json()["conditions"][0]["own"]
    api.post(f"{base}/conditions/of/{site['id']}", json={"condition_id": temp["id"], "value": 41})
    assert api.post(f"{base}/conditions/of/{site['id']}",
                    json={"condition_id": temp["id"], "value": "x"}).status_code == 422
    api.post(f"{base}/conditions/of/{room['id']}", json={"condition_id": outdoor["id"], "action": "exclude"})
    got = api.get(f"{base}/positions/{pos['id']}").json()
    assert [c["condition"]["name"] for c in got["conditions"]] == ["Ambient temperature"]
    assert got["excluded_conditions"][0]["source"]["name"] == "Room"
    assert api.get(f"{base}/conditions/of/{pos['id']}").json()["conditions"][0]["value"] == 41
    api.post(f"{base}/conditions/of/{room['id']}", json={"condition_id": outdoor["id"], "action": "remove"})
    assert len(api.get(f"{base}/locations/{room['id']}").json()["conditions"]) == 2
    assert api.post(f"{base}/conditions/of/{room['id']}", json={"condition_id": outdoor["id"],
                                                                "action": "nope"}).status_code == 422
    listed = api.get(f"{base}/conditions").json()
    assert {c["name"] for c in listed["tree"]} == {"Outdoor", "Ambient temperature"} and len(listed["conditions"]) == 2
    one = api.get(f"{base}/conditions/{temp['id']}").json()
    assert one["applied_to"][0]["value"] == 41
    assert api.patch(f"{base}/conditions/{outdoor['id']}", json={"description": "Open to the weather"}).json()[
        "description"] == "Open to the weather"
    csv_text = api.get(f"{base}/conditions/export?format=csv").text
    assert "Ambient temperature,value,°C" in csv_text
    imported = api.post(f"{base}/conditions/import", json={"format": "csv", "text": "path\nCoastal\n"}).json()
    assert imported["dry_run"] and imported["counts"]["create"] == 1
    api.post(f"{base}/conditions/import", json={"conditions": [{"path": "Coastal"}], "dry_run": False})
    assert api.post(f"{base}/conditions/{outdoor['id']}/retire", json={}).json() == {"retired": outdoor["id"]}
    assert {c["name"] for c in api.get(f"{base}/conditions").json()["conditions"]} == {"Ambient temperature",
                                                                                       "Coastal"}
    assert api.get(f"{base}/conditions/of/nope").status_code == 404
