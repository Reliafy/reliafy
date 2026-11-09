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
    assert m.points_at([], []) == {"points": [], "more": False, "channels": [], "consumables": []}
    assert got["channels"] == []


def test_points_at_lists_signal_channels_with_latest_level_trend_and_band_state():
    from datetime import datetime, timedelta, timezone

    m = Maintenance(GraphStore(":memory:", PROJECTORS), "user-pc")
    pump = m.create_position("Filter pump")["id"]
    other = m.create_position("Heater")["id"]
    m.add_point(pump, "Pressure", unit="kPa")
    power = m.add_signal_channel(pump, None, "Pump power", "W", tag="plug.power")
    m.add_signal_channel(other, None, "Heater temp", "C")
    item = m.create_item("Motor")["id"]
    m.add_signal_channel(None, item, "Motor vibration", "mm/s")
    gone = m.add_signal_channel(pump, None, "Old plug", "W")
    m.retire_signal_channel(gone["id"])
    m.add_signal_level(power["id"], "Power level", "value", None, alarm_above=900)
    now = datetime.now(timezone.utc)
    for i, w in enumerate((610, 640, 950)):
        m.add_signal_snapshot((now - timedelta(hours=3 - i)).isoformat(), power["id"], value=w)

    got = m.points_at([pump], [item])
    assert [c["name"] for c in got["channels"]] == ["Motor vibration", "Pump power"]
    row = next(c for c in got["channels"] if c["name"] == "Pump power")
    assert row["kind"] == "channel" and row["unit"] == "W" and row["position"]["name"] == "Filter pump"
    assert row["stat"] == "value" and row["latest"]["value"] == 950
    assert [r["value"] for r in row["recent"]] == [610, 640, 950]
    assert [b["name"] for b in row["bands"]] == ["Power level"] and row["bands"][0]["status"] == "high"
    assert row["attention"] is True and row["snapshots"]["count"] == 3
    quiet = next(c for c in got["channels"] if c["name"] == "Motor vibration")
    assert quiet["latest"] is None and quiet["recent"] == [] and quiet["attention"] is False
    # The channel's band is also a measuring point on the position, as before.
    assert sorted(p["name"] for p in got["points"]) == ["Power level", "Pressure"]


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
        assert client.get(f"{api}/points").json() == {"points": [], "more": False, "channels": [], "consumables": []}
        client.post(f"{api}/signals/channels", json={"position_id": a, "name": "Pump power", "unit": "W"})
        got = client.get(f"{api}/points", params={"position_ids": a}).json()
        assert [c["name"] for c in got["channels"]] == ["Pump power"]
    finally:
        app.dependency_overrides.clear()
