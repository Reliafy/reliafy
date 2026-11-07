"""Reliafy Maintenance: the measurement points on a branch of the tree at once
(GET /api/maintenance/points, the Explorer's Measurements tab)."""

from backend.maintenance.service import PROJECTORS, Maintenance
from backend.maintenance.store import GraphStore


def test_points_at_reads_positions_and_items_skipping_others_and_retired():
    m = Maintenance(GraphStore(":memory:", PROJECTORS), "user-p")
    pool = m.create_position("Pool")["id"]
    spa = m.create_position("Spa")["id"]
    ph = m.add_point(pool, "pH", unit="", alarm_above=7.8, alarm_below=7.0)
    m.record_reading(ph["id"], 7.4)
    chlorine = m.add_point(spa, "Chlorine", unit="ppm", alarm_above=3, alarm_below=1)
    gone = m.add_point(spa, "Old gauge", unit="kPa")
    m.retire_point(gone["id"], "replaced")
    item = m.create_item("Pump #2")["id"]
    hours = m.add_point(None, "Hours", kind="counter", unit="hours", item_id=item)

    got = m.points_at([pool, spa, "nope", pool], [item, pool])
    ids = [p["id"] for p in got["points"]]
    assert sorted(ids) == sorted([ph["id"], chlorine["id"], hours["id"]]) and not got["more"]
    by_id = {p["id"]: p for p in got["points"]}
    assert by_id[ph["id"]]["reading"] == 7.4 and by_id[ph["id"]]["position"]["name"] == "Pool"
    assert by_id[hours["id"]]["item"]["name"] == "Pump #2"
    assert m.points_at([], []) == {"points": [], "more": False}


def test_points_route_reads_comma_separated_ids(monkeypatch):
    import mongomock
    from fastapi.testclient import TestClient

    from backend import config, db
    from backend.auth import get_current_user
    from backend.main import app
    from backend.routers import maintenance as router

    monkeypatch.setattr(db, "_db", mongomock.MongoClient()["reliafy_points_at"])
    monkeypatch.setattr(db, "_simulated", True)
    monkeypatch.setattr(router, "_store", GraphStore(":memory:", PROJECTORS))
    monkeypatch.setattr(config, "MAINTENANCE_ENABLED", True)
    monkeypatch.setattr(config, "MAINTENANCE_EMAILS", {"a@x.com"})
    client = TestClient(app)
    app.dependency_overrides[get_current_user] = lambda: {
        "uid": "org-pa", "email": "a@x.com", "name": "A", "email_verified": True}
    try:
        api = "/api/maintenance"
        a = client.post(f"{api}/positions", json={"name": "Pool"}).json()["id"]
        b = client.post(f"{api}/positions", json={"name": "Spa"}).json()["id"]
        for pid, name in ((a, "pH"), (b, "Chlorine")):
            client.post(f"{api}/positions/{pid}/points", json={"name": name, "alarm_above": 8})
        got = client.get(f"{api}/points", params={"position_ids": f"{a}, {b},"}).json()
        assert sorted(p["name"] for p in got["points"]) == ["Chlorine", "pH"]
        assert client.get(f"{api}/points").json() == {"points": [], "more": False}
    finally:
        app.dependency_overrides.clear()
