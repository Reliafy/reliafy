"""Reliafy Maintenance: a product's design positions are the position classes of the
positions built from them, and its design locations the location classes of the
locations built units carry (products.py). Grouping by the design link (not the free
text, which may differ), shown by product and path and following renames; a position
added to a built item later keeps its free-text class; the class reads (list, one
class, life data, costs, model, forecast, fleet duty); the position, tree and location
reads; a rebuilt graph; the routes and the MCP read."""

import pytest

from backend.maintenance import class_fleet, forecast, loop
from backend.maintenance.service import PROJECTORS, Invalid, Maintenance, NotFound
from backend.maintenance.store import GraphStore
from backend.tests.test_maintenance_mcp import _do, _get, _list, _ok, _session
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


def _two_uavs(m):
    """A product UAV (Propulsion › Motor 1, class text "Motor"; a layout location Arm 1)
    and two items built from it, a motor fitted at each Motor 1; one failed and was
    replaced. A free-text "Motor" pump-station position outside the product."""
    root = m.create_product("UAV", part_number="UAV-1")["id"]
    prop = m.create_position("Propulsion", parent_id=root)["id"]
    motor = m.create_position("Motor 1", parent_id=prop, position_class="Motor")["id"]
    arm = m.create_location("Arm 1", design_of=root)["id"]
    m.update_position(motor, location_id=arm)
    units = {}
    for serial in ("0001", "0002"):
        out = m.build_item(root, serial, dry_run=False)
        units[serial] = {r["path"].split(" › ")[-1]: r["id"] for r in out["positions"]} | {
            "top": out["top_position_id"]}
        m.fit(units[serial]["Motor 1"], new_item={"name": "Motor", "serial": f"M-{serial}"}, on="2026-01-01")
    m.remove(units["0001"]["Motor 1"], on="2026-04-01", reason="failure")
    m.fit(units["0001"]["Motor 1"], new_item={"name": "Motor", "serial": "M-0001b"}, on="2026-04-02")
    station = m.create_position("Pump station")["id"]
    pump_motor = m.create_position("Pump motor", parent_id=station, position_class="Motor")["id"]
    return {"root": root, "prop": prop, "motor": motor, "arm": arm, "units": units, "pump_motor": pump_motor}


def test_built_positions_group_by_their_design_position_even_when_the_text_differs(m):
    d = _two_uavs(m)
    key = f"design:{d['motor']}"
    # One item's free-text class edited: the design link still wins (the text is left as written).
    m.update_position(d["units"]["0002"]["Motor 1"], position_class="Brushless motor")
    assert m.position(d["units"]["0002"]["Motor 1"])["position_class"] == "Brushless motor"
    classes = {c["class_key"]: c for c in m.position_classes()}
    motor = classes[key]
    assert motor["position_class"] == "UAV › Propulsion › Motor 1"
    assert motor["design_position_id"] == d["motor"] and motor["product"] == {"id": d["root"], "name": "UAV"}
    assert motor["positions"] == 2 and motor["fitments"] == 3 and motor["failures"] == 1
    # The free text "Motor" is the pump station's alone now (not the design's own position, nor
    # the built ones); "Brushless motor" isn't a class at all.
    assert classes["Motor"]["positions"] == 1 and classes["Motor"]["design_position_id"] is None
    assert classes["Motor"]["class_key"] == "Motor" and "Brushless motor" not in classes
    life = m.class_life_data(key)
    assert {r["position_id"] for r in life["rows"]} == {d["units"]["0001"]["Motor 1"], d["units"]["0002"]["Motor 1"]}
    assert life["failures"] == 1 and life["suspensions"] == 2
    assert life["position_class"] == "UAV › Propulsion › Motor 1" and life["class_key"] == key
    # The class is found by its key, the design position's id or its label.
    for name in (key, d["motor"], "uav › propulsion ›  motor 1"):
        assert m.position_class(name)["class_key"] == key
        assert m.class_life_data(name)["failures"] == 1
    with pytest.raises(NotFound):
        m.class_life_data("Brushless motor")
    _rebuilt_matches(m)


def test_a_position_added_to_a_built_item_later_keeps_its_free_text_class(m):
    d = _two_uavs(m)
    spare = m.create_position("Motor 5", parent_id=d["units"]["0001"]["Propulsion"], position_class="Motor")["id"]
    assert m.position(spare)["class"]["class_key"] == "Motor"
    assert m.position(spare)["class"]["design_position_id"] is None
    classes = {c["class_key"]: c for c in m.position_classes()}
    assert classes["Motor"]["positions"] == 2 and classes[f"design:{d['motor']}"]["positions"] == 2
    # Nothing fitted at either free-text position yet: the class is there, with no lives pooled.
    assert m.class_life_data("Motor")["rows"] == []


def test_the_class_follows_a_rename_of_the_design(m):
    d = _two_uavs(m)
    m.update_position(d["prop"], name="Drive")
    m.update_position(d["motor"], name="Front motor")
    built = m.position(d["units"]["0001"]["Motor 1"])
    assert built["class"]["position_class"] == "UAV › Drive › Front motor"
    assert built["class"]["class_key"] == f"design:{d['motor']}"
    assert m.class_life_data("UAV › Drive › Front motor")["failures"] == 1
    # The tree pane's rows carry the design class; a free-text one stays as it is.
    rows = {r["id"]: r for r in m.tree_rows()["positions"]}
    row = rows[d["units"]["0002"]["Motor 1"]]
    assert row["class_key"] == f"design:{d['motor']}" and row["class_label"] == "UAV › Drive › Front motor"
    assert "class_key" not in rows[d["pump_motor"]] and rows[d["pump_motor"]]["position_class"] == "Motor"


def test_the_design_position_lists_the_positions_built_from_it(m):
    d = _two_uavs(m)
    built = m.position(d["motor"])["built_as"]
    assert [b["serial"] for b in built] == ["0001", "0002"]
    assert built[0]["id"] == d["units"]["0001"]["Motor 1"] and built[0]["path"].endswith("Propulsion › Motor 1")
    assert m.position(d["units"]["0001"]["Motor 1"])["built_as"] is None
    m.retire_position(d["units"]["0002"]["top"], cascade=True)
    assert [b["serial"] for b in m.position(d["motor"])["built_as"]] == ["0001"]


def test_costs_model_forecast_and_fleet_duty_use_the_design_class(m):
    d = _two_uavs(m)
    key = f"design:{d['motor']}"
    got = m.set_class_costs("UAV › Propulsion › Motor 1", planned_cost=100, failure_cost=1000)
    assert got["class_key"] == key and got["costs"]["planned_cost"] == 100
    # Stored under the stable key: a rename keeps them.
    m.update_position(d["motor"], name="Motor A")
    assert m.position_class(key)["costs"]["failure_cost"] == 1000
    # A model on the class reaches its built positions (From the class…).
    node_name = m.s.node(ORG, __import__("backend.maintenance.service", fromlist=["class_id"]).class_id(ORG, key))
    assert node_name["name"] == key
    m._emit("class.model_fitted", {"id": node_name["id"], "name": key, "model_id": "mdl-1", "distribution": "weibull",
                                   "params": [{"name": "alpha", "value": 300.0}, {"name": "beta", "value": 2.0}],
                                   "unit": "days", "fitted_on": m.today(), "failures": 1, "suspensions": 2})
    cm = m.class_model_of(d["units"]["0002"]["Motor 1"])
    assert cm["class_key"] == key and cm["position_class"] == "UAV › Propulsion › Motor A"
    assert m.class_model_of(d["pump_motor"]) is None
    fc = forecast.class_forecast(m, key, "month", 3)
    assert fc["class_key"] == key and fc["position_class"] == "UAV › Propulsion › Motor A"
    assert fc["n_positions"] == 2
    assert forecast.spares_plan(fc)["class_key"] == key
    assert loop.economics(m, key)["class_key"] == key
    # The fleet's duty column shows the design class.
    brief = class_fleet._position_brief(m, m.s.node(ORG, d["units"]["0001"]["Motor 1"]))
    assert brief["position_class"] == "UAV › Propulsion › Motor A" and brief["class_key"] == key
    _rebuilt_matches(m)


def test_a_label_two_design_positions_share_is_refused(m):
    root = m.create_product("UAV", part_number="UAV-1")["id"]
    a = m.create_position("Motor", parent_id=root)["id"]
    m.create_position("Motor", parent_id=root)
    m.build_item(root, "0001", dry_run=False)
    with pytest.raises(Invalid, match="More than one design position"):
        m.class_life_data("UAV › Motor")
    assert m.class_life_data(f"design:{a}")["position_class"] == "UAV › Motor"


def test_carried_locations_have_their_design_location_as_class(m):
    d = _two_uavs(m)
    top = d["units"]["0001"]["top"]
    copy = next(loc for loc in m.s.nodes(ORG, "Location") if loc.get("carried_by") == top)
    read = m.location(copy["id"])
    assert read["location_class"] == {"design_location_id": d["arm"], "label": "UAV › Arm 1",
                                      "product": {"id": d["root"], "name": "UAV"}}
    assert read["carried_as"] is None
    # The design location across every built unit: each copy, its unit and what's there.
    design = m.location(d["arm"])
    assert design["location_class"] is None
    rows = design["carried_as"]
    assert [r["serial"] for r in rows] == ["0001", "0002"]
    assert rows[0]["id"] == copy["id"] and rows[0]["unit"]["id"] == top and rows[0]["positions"] == 1
    m.update_location(d["arm"], name="Front arm")
    assert m.location(copy["id"])["location_class"]["label"] == "UAV › Front arm"


def test_the_routes(api):  # noqa: F811
    client = api
    root = client.post("/api/maintenance/products", json={"name": "UAV", "part_number": "UAV-9"}).json()["id"]
    motor = client.post("/api/maintenance/positions", json={"name": "Motor 1", "parent_id": root,
                                                            "position_class": "Motor"}).json()["id"]
    r = client.post(f"/api/maintenance/products/{root}/build", json={"serial": "0001", "dry_run": False})
    assert r.status_code == 200, r.text
    classes = client.get("/api/maintenance/classes").json()["classes"]
    mine = next(c for c in classes if c.get("design_position_id") == motor)
    assert mine["position_class"] == "UAV › Motor 1" and mine["class_key"] == f"design:{motor}"
    one = client.get("/api/maintenance/classes/one", params={"position_class": mine["class_key"]})
    assert one.status_code == 200 and one.json()["positions"] == 1
    assert client.get(f"/api/maintenance/positions/{motor}").json()["built_as"][0]["serial"] == "0001"


def test_over_mcp(env):  # noqa: F811
    async def flow(client):
        root = _ok(await _do(client, "maintenance", "products.create", name="UAV", part_number="UAV-8"))["id"]
        motor = _ok(await _do(client, "maintenance", "positions.create", name="Motor 1", parent_id=root,
                              position_class="Motor"))["id"]
        _ok(await _do(client, "maintenance", "products.build", product_id=root, serial="0001", dry_run=False))
        classes = _ok(await _list(client, "position_classes"))["classes"]
        mine = next(c for c in classes if c.get("design_position_id") == motor)
        life = _ok(await _get(client, "class_life_data", mine["class_key"]))
        return mine, life

    mine, life = _session(env["token"], flow)
    assert mine["position_class"] == "UAV › Motor 1" and mine["positions"] == 1
    assert life["class_key"] == mine["class_key"]
