"""Reliafy Maintenance: the Assets list's search (positions by name or tag, items by
name or serial, each with its site), the items of products, and deleting an item
(retired, so its history stays; a built item takes its tree; refusals say what to
do; undo brings both back)."""

import mongomock
import pytest

from backend.maintenance.service import PROJECTORS, Invalid, Maintenance
from backend.maintenance.store import GraphStore

ORG = "user-asset-search"


@pytest.fixture()
def m():
    return Maintenance(GraphStore(":memory:", PROJECTORS), ORG, "tester")


def _same_after_rebuild(m):
    before = m.s.snapshot()
    m.s.rebuild()
    assert m.s.snapshot() == before


def _plant(m):
    """Riverside (a site) › Pump house, holding Pumping station › Pump 1 (P-101, an item
    fitted, serial SN-42) and Pump 2 (P-102); a tree at no place (Loose rig › Pump 9);
    a product UAV (part UAV-2) with one item built, serial Q-7."""
    site = m.create_location("Riverside")["id"]
    house = m.create_location("Pump house", parent_id=site)["id"]
    station = m.create_position("Pumping station", location_id=house)["id"]
    p1 = m.create_position("Filter pump", tag="P-101", parent_id=station)["id"]
    p2 = m.create_position("Pump 2", tag="P-102", parent_id=station)["id"]
    m.fit(p1, new_item={"name": "Grundfos CR", "serial": "SN-42"})
    rig = m.create_position("Loose rig")["id"]
    p9 = m.create_position("Pump 9", parent_id=rig)["id"]
    uav = m.create_product("UAV", part_number="UAV-2")
    m.create_position("Motor 1", parent_id=uav["id"])
    built = m.build_item(uav["id"], "Q-7", dry_run=False)
    return dict(site=site, house=house, station=station, p1=p1, p2=p2, rig=rig, p9=p9, uav=uav["id"], built=built)


def test_search_finds_positions_by_tag_and_name_with_their_site(m):
    ids = _plant(m)
    found = m.asset_search("p-101")
    assert [p["id"] for p in found["positions"]] == [ids["p1"]]
    hit = found["positions"][0]
    assert hit["tag"] == "P-101" and hit["site"]["name"] == "Riverside" and hit["site"]["kind"] == "location"
    assert hit["path"] == "Pumping station" and hit["item"]["serial"] == "SN-42"
    # Every word, any order and case; the exact tag first.
    assert [p["name"] for p in m.asset_search("pump filter")["positions"]] == ["Filter pump"]
    assert m.asset_search("P-10")["positions_total"] == 2
    # A tree at no place: its top is the site.
    assert m.asset_search("pump 9")["positions"][0]["site"] == {
        "id": ids["rig"], "name": "Loose rig", "kind": "position", "unit": None}
    # A product's design isn't an asset; the tree built from it is, named as the unit.
    motors = m.asset_search("motor 1")["positions"]
    assert len(motors) == 1 and motors[0]["site"]["unit"] and "Q-7" in motors[0]["site"]["unit"]
    assert m.asset_search("  ") == {"q": "", "positions": [], "items": [], "positions_total": 0, "items_total": 0}


def test_search_finds_items_by_serial_with_where_they_are(m):
    _plant(m)
    item = m.asset_search("sn-42")["items"]
    assert len(item) == 1 and item[0]["where"]["how"] == "fitted" and item[0]["site"]["name"] == "Riverside"
    built = m.asset_search("Q-7")["items"]
    assert len(built) == 1 and built[0]["product"]["name"] == "UAV" and built[0]["product"]["built"] is True
    with pytest.raises(Invalid):
        m.asset_search("x", limit="many")


def test_items_of_products_include_one_whose_tree_was_deleted(m):
    ids = _plant(m)
    listed = m.product_items_list()["items"]
    assert [i["serial"] for i in listed] == ["Q-7"]
    top = ids["built"]["top_position_id"]
    m.delete_tree("position", top)
    # The item is still the product's (of its part), so it stays reachable.
    assert [i["serial"] for i in m.product_items_list()["items"]] == ["Q-7"]


def test_deleting_a_built_item_takes_its_tree_and_undo_brings_both_back(m):
    _plant(m)
    item_id = m.asset_search("Q-7")["items"][0]["id"]
    top = m.item(item_id)["fitted_to"]["id"]
    events = m.s.event_count(ORG)
    preview = m.delete_item(item_id)
    assert preview["dry_run"] and preview["tree"]["id"] == top and preview["tree"]["positions"] == 1 and m.s.event_count(ORG) == events
    done = m.delete_item(item_id, dry_run=False)
    assert done["deleted"] == item_id
    assert m.item(item_id)["retired"] is True and m.position(top)["retired"] is True
    assert m.asset_search("Q-7")["items"] == [] and m.product_items_list()["items"] == []
    with pytest.raises(Invalid, match="already deleted"):
        m.delete_item(item_id)
    _same_after_rebuild(m)
    back = m.restore_deleted_item(item_id)
    assert back["retired"] is False and back["fitted_to"]["id"] == top
    assert m.position(top)["retired"] is False
    _same_after_rebuild(m)


def test_deleting_an_item_is_refused_with_what_to_do(m):
    ids = _plant(m)
    fitted = m.asset_search("SN-42")["items"][0]["id"]
    with pytest.raises(Invalid, match="fitted to Filter pump. Take it out first"):
        m.delete_item(fitted)
    loose = m.create_item("Spare motor", serial="SM-1")["id"]
    m.open_work_order(None, "Rewind", item_id=loose)
    with pytest.raises(Invalid, match="1 open work order. Close or cancel it first"):
        m.delete_item(loose)
    holder = m.create_item("Engine", serial="E-1")["id"]
    m.create_position("Turbo 1", parent_id=holder)
    with pytest.raises(Invalid, match=r"Positions inside Engine are still in use \(Turbo 1\)"):
        m.delete_item(holder)
    # An unfitted item with history: deleted (retired), its history kept.
    m.remove(ids["p1"])
    out = m.delete_item(fitted, dry_run=False)
    assert out["history"]["fitments"] == 1 and m.item(fitted)["history"]


def test_the_routes(monkeypatch):
    from fastapi.testclient import TestClient

    from backend import config, db
    from backend.auth import get_current_user
    from backend.main import app
    from backend.routers import maintenance as router

    store = GraphStore(":memory:", PROJECTORS)
    monkeypatch.setattr(db, "_db", mongomock.MongoClient()["reliafy_asset_search"])
    monkeypatch.setattr(db, "_simulated", True)
    monkeypatch.setattr(router, "_store", store)
    monkeypatch.setattr(config, "MAINTENANCE_ENABLED", True)
    monkeypatch.setattr(config, "MAINTENANCE_EMAILS", {"s@x.com"})
    app.dependency_overrides[get_current_user] = lambda: {
        "uid": ORG, "email": "s@x.com", "name": "S", "email_verified": True}
    client = TestClient(app)
    try:
        _plant(Maintenance(store, ORG, "tester"))
        r = client.get("/api/maintenance/search", params={"q": "P-101"})
        assert r.status_code == 200 and r.json()["positions"][0]["tag"] == "P-101"
        listed = client.get("/api/maintenance/items/of-products")
        assert listed.status_code == 200 and listed.json()["items"][0]["serial"] == "Q-7"
        item_id = listed.json()["items"][0]["id"]
        preview = client.post(f"/api/maintenance/items/{item_id}/delete", json={})
        assert preview.status_code == 200 and preview.json()["dry_run"] is True
        done = client.post(f"/api/maintenance/items/{item_id}/delete", json={"dry_run": False})
        assert done.status_code == 200 and done.json()["deleted"] == item_id
        back = client.post(f"/api/maintenance/items/{item_id}/undelete")
        assert back.status_code == 200 and back.json()["retired"] is False
        fitted = client.get("/api/maintenance/search", params={"q": "SN-42"}).json()["items"][0]["id"]
        refused = client.post(f"/api/maintenance/items/{fitted}/delete", json={})
        assert refused.status_code == 422 and "Take it out first" in refused.json()["detail"]
    finally:
        app.dependency_overrides.pop(get_current_user, None)
