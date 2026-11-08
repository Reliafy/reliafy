"""Consumables (Nov 2026): salt added to the pool is neither a reading nor a setting
but a consumption. A consumable is a catalogue part (or, with none, a name) used at a
position: each addition is a consumable.used event, taken out of stock where the part
is held (the existing stock.adjusted); a part used on a work order there counts too.
The Measurements tab lists them beside the points (points_at's consumables)."""

import pytest

from backend.maintenance.service import PROJECTORS, Invalid, Maintenance
from backend.maintenance.store import GraphStore

ORG = "user-c"


@pytest.fixture()
def m():
    return Maintenance(GraphStore(":memory:", PROJECTORS), ORG, "tester")


def _rebuilds_the_same(m):
    before = m.s.snapshot()
    m.s.rebuild()
    assert m.s.snapshot() == before


def test_salt_from_stock_with_its_cost_and_the_lsa_dose(m):
    pool = m.create_position("Pool")["id"]
    shed = m.create_location("Pool shed")["id"]
    garage = m.create_location("Garage")["id"]
    m.update_position(pool, location_id=shed)
    salt = m.create_part("SALT-20", "Pool salt", unit="kg", unit_cost=0.6)["id"]
    m.adjust_stock(salt, garage, 200, "delivered")
    m.adjust_stock(salt, shed, 40, "delivered")
    m.add_position_part(pool, salt, role="consumable", quantity=20)
    task = m.create_task(pool, "Top up salt", 1, "months")
    m.set_task_resources(task["id"], {"consumables": [{"name": "Pool salt", "qty": 20, "unit": "kg"}]})

    out = m.record_consumable_use(pool, 20, part_id=salt, on="2026-10-18", note="after rain")
    # Out of the shed's stock (where the pool is), not the garage's.
    assert out["from_location"] == "Pool shed"
    assert {s["location"]["name"]: s["on_hand"] for s in out["consumable"]["part"]["stock"]} == {"Garage": 200, "Pool shed": 20}
    row = out["consumable"]
    assert row["name"] == "Pool salt" and row["unit"] == "kg" and row["listing_id"]
    assert [(u["qty"], u["on"], u["cost"], u["note"]) for u in row["uses"]] == [(20, "2026-10-18", 12.0, "after rain")]
    assert row["lsa"] == [{"task": {"id": task["id"], "name": "Top up salt"}, "qty": 20, "unit": "kg",
                           "interval": 1, "interval_unit": "months"}]
    # More than the shed holds: out of the garage instead.
    assert m.record_consumable_use(pool, 30, part_id=salt)["from_location"] == "Garage"
    with pytest.raises(Invalid, match="counted in kg"):
        m.record_consumable_use(pool, 1, part_id=salt, unit="L")
    with pytest.raises(Invalid, match="more than 0"):
        m.record_consumable_use(pool, 0, part_id=salt)
    with pytest.raises(Invalid, match="future"):
        m.record_consumable_use(pool, 1, part_id=salt, on="2198-01-01")
    _rebuilds_the_same(m)


def test_a_named_consumable_a_work_orders_part_and_the_tab_read(m):
    pool = m.create_position("Pool")["id"]
    spa = m.create_position("Spa")["id"]
    # No catalogue part: a name and a unit; no stock moves.
    out = m.record_consumable_use(pool, 1.5, name="Hydrochloric acid", unit="L", cost=9, on="2026-10-01")
    assert out["from_location"] is None and out["consumable"]["part"] is None
    m.record_consumable_use(pool, 0.5, name="hydrochloric acid", unit="L", on="2026-10-08")
    # A listed consumable part used on a work order there counts too.
    cleaner = m.create_part("CELL-CLN", "Cell cleaner", unit="L", unit_cost=12)["id"]
    m.add_position_part(spa, cleaner, role="consumable")
    wo = m.open_work_order(spa, "Clean the cell")
    m.add_part_used(wo["id"], part_id=cleaner, quantity=0.25)
    got = m.points_at([pool, spa], [])["consumables"]
    by = {r["name"]: r for r in got}
    assert [u["qty"] for u in by["Hydrochloric acid"]["uses"]] == [0.5, 1.5]
    assert by["Cell cleaner"]["uses"][0]["work_order"]["id"] == wo["id"]
    assert by["Cell cleaner"]["uses"][0]["cost"] == 3.0
    assert by["Cell cleaner"]["position"]["name"] == "Spa"
    # Off the parts list, a part only used on work orders isn't a consumable row any more
    # (a bearing on a work order isn't a consumable); one added by hand stays listed.
    m.remove_position_part(by["Cell cleaner"]["listing_id"])
    assert m.points_at([spa], [])["consumables"] == []
    m.record_consumable_use(spa, 0.25, part_id=cleaner, on="2026-10-02")
    again = m.points_at([spa], [])["consumables"]
    assert [len(r["uses"]) for r in again] == [2]  # its own use, and the work order's again
    _rebuilds_the_same(m)


def test_record_route_and_the_mcp_record_action_take_a_consumable(monkeypatch):
    import mongomock
    from fastapi.testclient import TestClient

    from backend import config, db
    from backend.auth import get_current_user
    from backend.main import app
    from backend.routers import maintenance as router

    monkeypatch.setattr(db, "_db", mongomock.MongoClient()["reliafy_consumables"])
    monkeypatch.setattr(db, "_simulated", True)
    monkeypatch.setattr(router, "_store", GraphStore(":memory:", PROJECTORS))
    monkeypatch.setattr(config, "MAINTENANCE_ENABLED", True)
    monkeypatch.setattr(config, "MAINTENANCE_EMAILS", {"a@x.com"})
    client = TestClient(app)
    app.dependency_overrides[get_current_user] = lambda: {
        "uid": "org-co", "email": "a@x.com", "name": "A", "email_verified": True}
    try:
        api = "/api/maintenance"
        pool = client.post(f"{api}/positions", json={"name": "Pool"}).json()["id"]
        r = client.post(f"{api}/positions/{pool}/consumables", json={"name": "Mineral blend", "unit": "kg", "qty": 2})
        assert r.status_code == 200, r.text
        assert r.json()["consumable"]["uses"][0]["qty"] == 2
        assert client.post(f"{api}/positions/{pool}/consumables", json={"name": "Salt", "qty": -1}).status_code in (400, 422)
        got = client.get(f"{api}/points", params={"position_ids": pool}).json()
        assert [c["name"] for c in got["consumables"]] == ["Mineral blend"]
    finally:
        app.dependency_overrides.pop(get_current_user, None)


def test_the_record_action_says_what_it_takes():
    from backend.maintenance.mcp_tools import MEASUREMENTS

    required, optional, text = MEASUREMENTS["record"]
    assert required == "value"
    assert {"point_id", "position_id", "part_id", "name", "unit", "cost"} <= set(optional.split())
    assert "consumable" in text
