"""Reliafy Maintenance: automated feeds into the time-series store, counted use and
alarms from them, and the older meter/condition events replaying as measurement
points."""

from datetime import date, datetime, timedelta, timezone

import mongomock
import pytest

from backend.maintenance.series import MongoSeries
from backend.maintenance.service import PROJECTION_VERSION, PROJECTORS, Invalid, Maintenance
from backend.maintenance.store import GraphStore, MongoEventLog
from backend.tests.rcm_tree import position_with_rcm

ORG = "user-f"


def _ts(days_ago: float) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=days_ago)).isoformat()


class _Rcm:
    name = "Pool pump"
    functions = [{"id": "f", "text": "Circulate", "failures": [{"id": "ff", "text": "No flow", "modes": [
        {"id": "m1", "text": "Seal worn", "consequence": "operational",
         "decision": {"outcome": "fixed_interval", "interval": 500, "interval_unit": "hours",
                      "task": "Replace the seal"}}]}]}]


@pytest.mark.parametrize("backend", ["sqlite", "mongo"])
def test_an_automated_counter_drives_a_task_by_use(backend):
    if backend == "mongo":
        db = mongomock.MongoClient()["feeds"]
        store = GraphStore(":memory:", PROJECTORS, MongoEventLog(db), series=MongoSeries(db))
    else:
        store = GraphStore(":memory:", PROJECTORS)
    m = Maintenance(store, ORG)
    pos = position_with_rcm(m, _Rcm.functions, _Rcm.name)["position"]
    with pytest.raises(Invalid):
        m.add_point(pos["id"], "Run hours", kind="counter", unit="hours", source="automated")  # no tag
    point = m.add_point(pos["id"], "Run hours", kind="counter", unit="hours", source="automated",
                        tag="sensor.pool_pump_hours")
    # Home Assistant posting hourly: 8 h a day for 30 days, from 2000 h.
    rows = [{"tag": "sensor.pool_pump_hours", "value": 2000 + 8 * d, "time": _ts(30 - d)} for d in range(31)]
    rows.append({"tag": "sensor.unknown", "value": 1})
    out = m.ingest(rows)
    assert out["stored"] == 31 and out["unknown_tags"] == {"sensor.unknown": 1}
    view = m.point(point["id"])
    assert view["reading"] == 2240 and view["rate_per_day"] == pytest.approx(8, rel=0.01)
    with pytest.raises(Invalid):
        m.record_reading(point["id"], 2300)  # fed automatically
    # The pump was fitted 20 days ago: the renewal records the feed's reading then.
    m.fit(pos["id"], new_item={"name": "Pump"}, on=(date.today() - timedelta(days=20)).isoformat())
    task = m.position(pos["id"])["tasks"][0]
    assert task["last_done_reading"] == pytest.approx(2080, abs=8)
    # Feed readings are dated by their day in the workspace's zone, and so is today (no
    # zone here: the machine's own, both), so the due date is exact.
    due = date.today() + timedelta(days=round((2580 - 2240) / 8))
    assert task["next_due"] == due.isoformat()


def test_an_automated_condition_feed_raises_one_inspection():
    m = Maintenance(GraphStore(":memory:", PROJECTORS), ORG)
    pid = m.create_position("Hot water system")["id"]
    point = m.add_point(pid, "Outlet temperature", unit="°C", source="automated", tag="sensor.hws_outlet",
                        alarm_below=50)
    ok = m.ingest([{"tag": "sensor.hws_outlet", "value": 61, "time": _ts(1)}])
    assert ok["work_orders_raised"] == []
    cold = m.ingest([{"tag": "sensor.hws_outlet", "value": 38, "time": _ts(0.1)}])
    assert len(cold["work_orders_raised"]) == 1
    again = m.ingest([{"tag": "sensor.hws_outlet", "value": 36}])
    assert again["work_orders_raised"] == []  # one open at a time
    view = m.point(point["id"])
    assert view["status"] == "low" and "below the 50 alarm limit" in m.work_orders("open")[0]["title"]
    with pytest.raises(Invalid):
        m.ingest([{"tag": "sensor.hws_outlet", "value": "warm"}])


def test_older_meter_and_condition_events_replay_as_points(tmp_path):
    """A local graph written before measurement points: rebuilt on open, the old
    meters and condition points come back as points with their readings."""
    path = str(tmp_path / "m.sqlite")
    old = GraphStore(path, PROJECTORS, version=1)
    pid = Maintenance(old, ORG).create_position("Pump")["id"]
    old.apply(ORG, "meter.added", {"id": "m1", "position_id": pid, "name": "Hours", "unit": "hours",
                                   "on": "2026-01-01"})
    old.apply(ORG, "meter.read", {"id": "r1", "meter_id": "m1", "on": "2026-01-02", "value": 10})
    old.apply(ORG, "condition_point.added", {"id": "c1", "position_id": pid, "name": "Vibration", "unit": "mm/s",
                                             "alarm_above": 7.1, "alarm_below": None, "source": "manual", "tag": "",
                                             "on": "2026-01-01"})
    old.apply(ORG, "condition.read", {"id": "r2", "point_id": "c1", "on": "2026-01-02", "value": 3.2})
    reopened = Maintenance(GraphStore(path, PROJECTORS, version=PROJECTION_VERSION), ORG)
    points = {p_["name"]: p_ for p_ in reopened.position(pid)["measurements"]}
    assert (points["Hours"]["kind"], points["Hours"]["reading"]) == ("counter", 10)
    assert (points["Vibration"]["kind"], points["Vibration"]["reading"]) == ("condition", 3.2)


def test_the_ingest_api_takes_a_token_and_feeds_points(monkeypatch):
    from fastapi.testclient import TestClient

    from backend import config, db
    from backend.main import app
    from backend.routers import ingest as ingest_router
    from backend.routers import maintenance as router
    from backend.services import tokens

    monkeypatch.setattr(config, "AUTH_DISABLED", False)
    monkeypatch.setattr(config, "BILLING_ENABLED", False)
    monkeypatch.setattr(config, "MAINTENANCE_ENABLED", True)
    monkeypatch.setattr(config, "MAINTENANCE_EMAILS", {"f@example.org"})
    test_db = mongomock.MongoClient()["feeds_api"]
    monkeypatch.setattr(db, "_db", test_db)
    monkeypatch.setattr(db, "_simulated", True)
    store = GraphStore(":memory:", PROJECTORS)
    monkeypatch.setattr(router, "_store", store)
    ingest_router._hits.clear()
    test_db.users.insert_one({"_id": ORG, "email": "f@example.org", "name": "F", "email_verified": True})
    token = tokens.create_token(test_db, ORG, "home assistant", scopes=["ingest"])["token"]
    m = Maintenance(store, ORG)
    pid = m.create_position("Pool pump")["id"]
    m.add_point(pid, "Hours", kind="counter", unit="hours", source="automated", tag="sensor.pool_hours")
    client = TestClient(app)
    r = client.post("/api/ingest/maintenance/readings", headers={"Authorization": f"Bearer {token}"},
                    json={"readings": [{"tag": "sensor.pool_hours", "value": 1234.5}]})
    assert r.status_code == 200, r.text
    assert r.json()["stored"] == 1
    csv = "tag,value,time\nsensor.pool_hours,1240,2026-10-13T10:00:00+10:00\n"
    r = client.post("/api/ingest/maintenance/readings", content=csv,
                    headers={"Authorization": f"Bearer {token}", "Content-Type": "text/csv"})
    assert r.status_code == 200 and r.json()["stored"] == 1
    monkeypatch.setattr(config, "MAINTENANCE_EMAILS", set())
    denied = client.post("/api/ingest/maintenance/readings", headers={"Authorization": f"Bearer {token}"},
                         json={"readings": []})
    assert denied.status_code == 404
