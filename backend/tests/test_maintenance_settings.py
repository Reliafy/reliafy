"""Settings (Nov 2026): a point kind for a value someone sets (the pool's
chlorinator output, a pump timer's hours a day), kept as readings that hold until
the next change, and readings recorded from a work order (reading.added's new
work_order_id and task_id) so the history says which work order set it."""

import pytest

from backend.maintenance.service import PROJECTORS, Invalid, Maintenance
from backend.maintenance.store import GraphStore

ORG = "user-a"


@pytest.fixture()
def m():
    return Maintenance(GraphStore(":memory:", PROJECTORS), ORG, "tester")


def _rebuilds_the_same(m):
    before = m.s.snapshot()
    m.s.rebuild()
    assert m.s.snapshot() == before


def _events(m, type):
    return [e for e in m.s.events(ORG, 1000) if e["type"] == type]


def test_a_setting_holds_until_changed_and_never_alarms(m):
    pool = m.create_position("Pool")
    chl = m.add_point(pool["id"], "Chlorinator output", "setting", "%", range_min=0, range_max=100)
    assert chl["kind"] == "setting" and (chl["range_min"], chl["range_max"]) == (0, 100)
    m.record_reading(chl["id"], 45, on="2026-04-01")
    m.record_reading(chl["id"], 45, on="2026-07-01")  # checked, unchanged: not a change
    p = m.record_reading(chl["id"], 60, on="2026-10-01")
    assert p["reading"] == 60 and "trend_per_day" not in p and "rate_per_day" not in p
    assert [(c["value"], c["from"], c["on"]) for c in p["changes"]] == [(60, 45, "2026-10-01"), (45, None, "2026-04-01")]
    with pytest.raises(Invalid, match="outside Chlorinator output's allowed range"):
        m.record_reading(chl["id"], 120)
    assert not m.s.nodes(ORG, "WorkOrder")
    _rebuilds_the_same(m)


def test_a_point_can_become_a_setting(m):
    pool = m.create_position("Pool")
    timer = m.add_point(pool["id"], "Pump timer", "condition", "h/day")
    m.record_reading(timer["id"], 6, on="2026-10-01")
    p = m.update_point(timer["id"], kind="setting", range_min=0, range_max=24)
    assert p["kind"] == "setting" and p["range_max"] == 24 and p["changes"][0]["value"] == 6
    assert _events(m, "point.updated")[-1]["payload"]["changes"] == {"kind": "setting", "range_min": 0, "range_max": 24}
    assert m.update_point(timer["id"], kind="condition")["kind"] == "condition"
    with pytest.raises(Invalid, match="added as one"):
        m.update_point(timer["id"], kind="counter")
    # A trigger watches a condition point: not while one watches it.
    rain = m.add_point(pool["id"], "Rainfall", "condition", "mm")
    task = m.create_task(pool["id"], "Check after rain", None, None,
                         trigger={"kind": "reading", "point_id": rain["id"], "above": 50})
    with pytest.raises(Invalid, match="trigger watches"):
        m.update_point(rain["id"], kind="setting")
    assert task
    # A counter a task by use goes by stays a counter.
    hours = m.add_point(pool["id"], "Pump hours", "counter", "hours")
    m.create_task(pool["id"], "Service the pump", 500, "hours", )
    with pytest.raises(Invalid, match="goes by"):
        m.update_point(hours["id"], kind="setting")
    _rebuilds_the_same(m)


def test_readings_recorded_from_a_work_order_name_it(m):
    pool = m.create_position("Pool")
    chl = m.add_point(pool["id"], "Chlorinator output", "setting", "%")
    salt = m.add_point(pool["id"], "Salt", "condition", "ppm")
    other = m.add_point(pool["id"], "Water temperature", "condition", "°C")
    m.record_reading(chl["id"], 45, on="2026-04-01")
    task = m.create_task(pool["id"], "Seasonal change-over", 6, "months")
    m.set_task_resources(task["id"], {"tools": [{"name": "Salt meter", "point_id": salt["id"]}]})
    wo = m.open_work_order(pool["id"], "Change-over", "preventive", task_id=task["id"])
    view = m.work_order(wo["id"])
    asked = {p["name"]: p for p in view["reading_points"]}
    assert set(asked) == {"Chlorinator output", "Salt"} and asked["Chlorinator output"]["reading"] == 45
    assert asked["Salt"]["why"] == ["tool"] and asked["Chlorinator output"]["why"] == ["setting"]
    assert view["readings_by_task"] == {task["id"]: {"asked": 2, "recorded": 0}}
    # Record pressed: one value now, an empty box records nothing.
    view = m.record_work_order_readings(wo["id"], [{"point_id": salt["id"], "value": 3200, "unit": "ppm"},
                                                   {"point_id": chl["id"], "value": ""}])
    assert view["readings_by_task"][task["id"]] == {"asked": 2, "recorded": 1}
    with pytest.raises(Invalid, match="not %"):
        m.record_work_order_readings(wo["id"], [{"point_id": chl["id"], "value": 60, "unit": "%x"}])
    # Closing records the rest; the new setting names the work order and the task.
    m.close_work_order(wo["id"], [{"kind": "other", "notes": "change-over"}], on="2026-10-01",
                       readings=[{"point_id": chl["id"], "value": 60}, {"point_id": other["id"], "value": 24}])
    added = _events(m, "reading.added")[-2]["payload"]
    assert added["work_order_id"] == wo["id"] and added["task_id"] == task["id"]
    p = m.point(chl["id"])
    change = p["changes"][0]
    assert (change["value"], change["from"], change["work_order"]["number"]) == (60, 45, wo["number"])
    assert p["readings"][0]["work_order_id"] == wo["id"] and p["readings"][0]["task"]["name"] == "Seasonal change-over"
    view = m.work_order(wo["id"])
    taken = {r["point"]["name"]: r for r in view["readings_taken"]}
    assert set(taken) == {"Salt", "Chlorinator output", "Water temperature"} and taken["Chlorinator output"]["from"] == 45
    # A correction keeps the link.
    m.correct_reading(p["readings"][0]["id"], 65, reason="misread")
    assert m.point(chl["id"])["changes"][0]["work_order_id"] == wo["id"]
    _rebuilds_the_same(m)


def test_a_reading_links_to_a_work_order_only_when_it_can(m):
    pool = m.create_position("Pool")
    chl = m.add_point(pool["id"], "Chlorinator output", "setting", "%")
    wo = m.open_work_order(pool["id"], "Adjust")
    p = m.record_reading(chl["id"], 50, work_order_id=wo["id"])
    assert p["readings"][0]["work_order"]["number"] == wo["number"] and "task_id" not in p["readings"][0]
    with pytest.raises(Invalid, match="goes with work_order_id"):
        m.record_reading(chl["id"], 55, task_id="t1")
    other = m.create_task(pool["id"], "Something else", 1, "months")
    with pytest.raises(Invalid, match="isn't one work order"):
        m.record_reading(chl["id"], 55, work_order_id=wo["id"], task_id=other["id"])
    m.cancel_work_order(wo["id"], "duplicate")
    with pytest.raises(Invalid, match="cancelled"):
        m.record_reading(chl["id"], 55, work_order_id=wo["id"])
    # Old readings (no keys) read as before.
    m.record_reading(chl["id"], 52)
    assert "work_order_id" not in m.point(chl["id"])["readings"][0]
    _rebuilds_the_same(m)


def test_the_app_routes_take_kind_range_and_work_order_readings(monkeypatch):
    import mongomock
    from fastapi.testclient import TestClient

    from backend import config, db
    from backend.auth import get_current_user
    from backend.main import app
    from backend.routers import maintenance as router

    monkeypatch.setattr(db, "_db", mongomock.MongoClient()["reliafy_test"])
    monkeypatch.setattr(db, "_simulated", True)
    monkeypatch.setattr(router, "_store", GraphStore(":memory:", PROJECTORS))
    monkeypatch.setattr(config, "MAINTENANCE_ENABLED", True)
    monkeypatch.setattr(config, "MAINTENANCE_EMAILS", {"a@x.com"})
    client = TestClient(app)
    app.dependency_overrides[get_current_user] = lambda: {
        "uid": ORG, "email": "a@x.com", "name": "A", "email_verified": True}
    try:
        pid = client.post("/api/maintenance/positions", json={"name": "Pool"}).json()["id"]
        r = client.post(f"/api/maintenance/positions/{pid}/points",
                        json={"name": "Chlorinator output", "kind": "setting", "unit": "%", "range_min": 0,
                              "range_max": 100})
        assert r.status_code == 200 and r.json()["kind"] == "setting", r.text
        point = r.json()
        r = client.patch(f"/api/maintenance/points/{point['id']}", json={"kind": "condition", "range_max": 80})
        assert r.json()["kind"] == "condition" and r.json()["range_max"] == 80
        client.patch(f"/api/maintenance/points/{point['id']}", json={"kind": "setting"})
        wo = client.post("/api/maintenance/work-orders", json={"position_id": pid, "title": "Change-over"}).json()
        r = client.post(f"/api/maintenance/work-orders/{wo['id']}/readings",
                        json={"readings": [{"point_id": point["id"], "value": 60}]})
        assert r.status_code == 200, r.text
        assert r.json()["reading_points"][0]["recorded"]["value"] == 60
        r = client.post(f"/api/maintenance/points/{point['id']}/readings",
                        json={"value": 50, "work_order_id": wo["id"]})
        assert r.json()["changes"][0]["work_order"]["number"] == wo["number"]
    finally:
        app.dependency_overrides.clear()
