"""Reliafy Maintenance: the limits on what one request or workspace can write:
text, numbers and dates, copies, rates and quotas; and requests that are
refused cleanly rather than failing."""

from datetime import datetime, timedelta, timezone

import mongomock
import pytest

from backend.maintenance import importer, photos
from backend.maintenance import service as service_mod
from backend.maintenance.service import PROJECTORS, Invalid, LimitReached, Maintenance, RateLimited, add_interval
from backend.maintenance.store import GraphStore

UID = "user-l"


@pytest.fixture()
def store():
    return GraphStore(":memory:", PROJECTORS)


def _task(m: Maintenance, position_id: str, interval=1.0, unit="days", task_id=None) -> str:
    tid = task_id or f"{m.org}-task"
    m.s.apply(m.org, "task.added", {"id": tid, "position_id": position_id, "name": "Check", "interval": interval,
                                    "unit": unit, "start": "2024-01-01"})
    return tid


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
    test_db = mongomock.MongoClient()["maint_limits_api"]
    monkeypatch.setattr(db, "_db", test_db)
    monkeypatch.setattr(db, "_simulated", True)
    monkeypatch.setattr(router, "_store", GraphStore(":memory:", PROJECTORS))
    monkeypatch.setattr(router, "_photo_store", photos.FilePhotoStore(str(tmp_path)))
    user = {"uid": UID, "email": "l@example.org", "name": "L", "email_verified": True}
    test_db.users.insert_one({"_id": UID, "email": "l@example.org", "name": "L", "email_verified": True})
    app.dependency_overrides[get_current_user] = lambda: user
    try:
        yield {"client": TestClient(app), "db": test_db, "user": user, "app": app, "router": router}
    finally:
        app.dependency_overrides.clear()



# ---- copies ---------------------------------------------------------------------------------

def test_a_copy_cant_go_inside_what_it_copies(store):
    m = Maintenance(store, UID)
    root = m.create_position("Station")
    child = m.create_position("Pump", parent_id=root["id"])
    before = len(store.log.since(0))
    for parent in (root["id"], child["id"]):
        with pytest.raises(Invalid, match="into itself"):
            m.copy_position(root["id"], "Copy", parent_id=parent)
    assert len(store.log.since(0)) == before


def test_a_copy_reads_the_tree_first_and_is_capped(store, monkeypatch):
    m = Maintenance(store, UID)
    root = m.create_position("Station")
    pump = m.create_position("Pump", parent_id=root["id"])
    _task(m, pump["id"])
    other = m.create_position("Station 2")
    copied = m.copy_position(root["id"], "Station copy", parent_id=other["id"])
    [pump_copy] = copied["children"]
    assert m.position(pump_copy["id"])["tasks"][0]["name"] == "Check"
    monkeypatch.setattr(service_mod, "MAX_COPY_NODES", 2)
    before = len(store.log.since(0))
    with pytest.raises(Invalid, match="more than 2"):
        m.copy_position(root["id"], "Too big")
    assert len(store.log.since(0)) == before  # nothing written


# ---- text, numbers and dates -----------------------------------------------------------------

def test_text_is_capped_by_field(store):
    m = Maintenance(store, UID)
    with pytest.raises(Invalid, match="at most 200"):
        m.create_position("x" * 201)
    pos = m.create_position("x" * 200, description="d" * 4000)
    with pytest.raises(Invalid, match="at most 4000"):
        m.update_position(pos["id"], description="d" * 4001)
    with pytest.raises(Invalid, match="at most 200"):
        m.create_item("Pump", serial="s" * 201)
    wo = m.open_work_order(pos["id"], "Fix", notes="n" * 4000)
    with pytest.raises(Invalid, match="at most 4000"):
        m.update_work_order(wo["id"], notes="n" * 4001)


def test_task_intervals_must_be_finite_and_in_range(store):
    m = Maintenance(store, UID)
    pos = m.create_position("Pump")
    tid = _task(m, pos["id"])
    for bad in (1e12, float("inf"), float("nan"), "abc", -1, 0):
        with pytest.raises(Invalid):
            m.update_task(tid, interval=bad)
    with pytest.raises(Invalid, match="100 years"):
        m.update_task(tid, interval=101, unit="years")
    with pytest.raises(Invalid):
        m.update_task(tid, interval=2e7, unit="hours")
    with pytest.raises(Invalid):
        m.update_task(tid, also_interval=1e9, also_unit="months")
    assert m.update_task(tid, interval=100, unit="years")["interval"] == 100
    assert m.update_task(tid, interval=5000, unit="hours")["interval"] == 5000


def test_readings_costs_and_dates_are_bounded(store):
    m = Maintenance(store, UID)
    pos = m.create_position("Pump")
    point = m.add_point(pos["id"], "Temp", kind="condition", unit="C")
    for bad in (1e13, float("inf"), float("nan")):
        with pytest.raises(Invalid):
            m.record_reading(point["id"], bad)
    with pytest.raises(Invalid):
        m.add_point(pos["id"], "T2", alarm_above=float("inf"))
    wo = m.open_work_order(pos["id"], "Fix")
    for bad in (float("inf"), 1e13):
        with pytest.raises(Invalid):
            m.add_cost(wo["id"], "Crane", bad)
    m.update_position(pos["id"], position_class="Pool pump")
    with pytest.raises(Invalid):
        m.set_class_costs("Pool pump", float("inf"), None)
    with pytest.raises(Invalid, match="between 1900 and 2199"):
        m.fit(pos["id"], new_item={"name": "Tank"}, on="9999-12-31")


def test_date_maths_out_of_range_gives_no_date_not_an_error(store):
    assert add_interval("9999-12-01", 1e12, "days") is None
    assert add_interval("9999-12-01", 1, "years") is None
    assert add_interval("2024-01-01", 1, "years") == "2025-01-01"
    m = Maintenance(store, UID)
    pos = m.create_position("Pump")
    _task(m, pos["id"], interval=1e12)  # as an older event might hold
    assert m.due_tasks(30) == [] and m.position(pos["id"])["tasks"][0]["next_due"] is None


def test_feed_readings_are_checked(store, monkeypatch):
    m = Maintenance(store, UID)
    pos = m.create_position("Engine")
    m.add_point(pos["id"], "Run hours", kind="counter", unit="hours", source="automated", tag="ENG.HRS")
    _task(m, pos["id"], interval=250, unit="hours")
    for rows in ([{"tag": "ENG.HRS", "value": 1, "time": "9999-12-30T00:00:00Z"}],
                 [{"tag": "ENG.HRS", "value": 1, "time": 1e20}],
                 [{"tag": "ENG.HRS", "value": 1, "time": "1999-12-31T00:00:00Z"}],
                 [{"tag": "ENG.HRS", "value": float("inf")}],
                 ["just a string"], "not a list"):
        with pytest.raises(Invalid):
            m.ingest(rows)
    now = datetime.now(timezone.utc)
    assert m.ingest([{"tag": "ENG.HRS", "value": 10, "time": (now - timedelta(days=2)).isoformat()},
                     {"tag": "ENG.HRS", "value": 20, "time": now.timestamp()}])["stored"] == 2
    m.due_tasks(30)
    monkeypatch.setattr(service_mod, "MAX_READINGS_PER_DAY", 3)
    with pytest.raises(RateLimited, match="a day"):
        m.ingest([{"tag": "ENG.HRS", "value": 30}, {"tag": "ENG.HRS", "value": 31}])


def test_one_organisations_trouble_doesnt_stop_the_daily_run(store, monkeypatch):
    from backend.maintenance import daily

    first, second = Maintenance(store, "aaa"), Maintenance(store, "zzz")
    for org in (first, second):
        _task(org, org.create_position("P")["id"])
    real = Maintenance.generate

    def generate(self, horizon_days=30):
        if self.org == "aaa":
            raise OverflowError("date value out of range")
        return real(self, horizon_days)

    monkeypatch.setattr(Maintenance, "generate", generate)
    result = daily.run(mongomock.MongoClient()["daily_limits"], store)
    assert result["failed"] == 1 and result["work_orders"] == 1
    assert len(second.work_orders()) == 1


# ---- rates and quotas -------------------------------------------------------------------------

def test_changes_per_minute_are_limited_per_organisation(store, monkeypatch):
    monkeypatch.setattr(service_mod, "WRITES_PER_MINUTE", 3)
    for i in range(3):
        Maintenance(store, UID).create_position(f"P{i}")
    with pytest.raises(RateLimited):
        Maintenance(store, UID).create_position("One too many")
    Maintenance(store, "another-org").create_position("Fine")  # each organisation has its own
    Maintenance(store, UID, "scheduler", limited=False).create_position("The daily run isn't limited")
    store.write_windows[UID][0] -= 61  # a minute later
    Maintenance(store, UID).create_position("Fine again")


def test_workspace_quotas(store, monkeypatch):
    m = Maintenance(store, UID)
    monkeypatch.setattr(service_mod, "MAX_POSITIONS", 2)
    root = m.create_position("A")
    m.create_position("B")
    with pytest.raises(LimitReached, match="at most 2 positions"):
        m.create_position("C")
    with pytest.raises(LimitReached):
        m.copy_position(root["id"], "A copy")
    monkeypatch.setattr(service_mod, "MAX_ITEMS", 1)
    m.create_item("Pump")
    with pytest.raises(LimitReached, match="items"):
        m.create_item("Another")
    with pytest.raises(LimitReached):
        importer.run(m, [{"position": "A", "item": "Motor", "fitted": "2024-01-01"}])
    monkeypatch.setattr(service_mod, "MAX_PHOTOS", 1)
    m.add_photo("ph1", root["id"], {"width": 1, "height": 1})
    with pytest.raises(LimitReached, match="photos"):
        m.add_photo("ph2", root["id"], {"width": 1, "height": 1})
    monkeypatch.setattr(service_mod, "MAX_EVENTS", store.event_count(UID))
    with pytest.raises(LimitReached, match="recorded changes"):
        Maintenance(store, UID).create_location("Shed")


# ---- requests that used to fail with an error --------------------------------------------------

def test_malformed_requests_are_refused_cleanly(store):
    m = Maintenance(store, UID)
    a, b = m.create_position("A"), m.create_position("B")
    with pytest.raises(Invalid, match="manual or photo"):
        m.set_coordinates(a["id"], 1, 2, {"any": "thing"})
    group = m.create_group("Pumps", [a["id"], b["id"]])
    with pytest.raises(Invalid, match="whole number"):
        m.update_group(group["id"], k="two")
    with pytest.raises(Invalid):
        m.create_group("Pumps", 5)
    wo = m.open_work_order(a["id"], "Fix")
    with pytest.raises(Invalid):
        m.close_work_order(wo["id"], actions="replace it")
    with pytest.raises(Invalid):
        m.close_work_order(wo["id"], actions=[{"kind": "repair"}], readings=["12"])
    tid = _task(m, a["id"])
    with pytest.raises(Invalid):
        m.update_task(tid, checklist=7)


class _Study:
    def __init__(self, functions):
        self.functions, self.system, self.name, self.id = functions, "Pool", "Pool RCM", "study-x"


def test_rcm_modes_without_an_id_or_with_a_bad_interval(store):
    m = Maintenance(store, UID)
    pos = m.create_position("Pool")
    no_id = _Study([{"text": "Pump", "failures": [{"text": "No flow", "modes": [
        {"text": "Blocked", "decision": {"outcome": "on_condition", "interval": 1, "interval_unit": "weeks"}}]}]}])
    assert m.apply_rcm(pos["id"], no_id)["failure_modes_added"] == 0
    bad = _Study([{"text": "Pump", "failures": [{"text": "No flow", "modes": [
        {"id": "m1", "text": "Blocked", "decision": {"outcome": "on_condition", "interval": "1e400",
                                                     "interval_unit": "weeks"}}]}]}])
    with pytest.raises(Invalid):
        m.apply_rcm(pos["id"], bad)


def test_api_limits_answer_with_their_status(api, monkeypatch):
    client = api["client"]
    pid = client.post("/api/maintenance/positions", json={"name": "P"}).json()["id"]
    assert client.post("/api/maintenance/positions", json={"name": "x" * 201}).status_code == 422
    monkeypatch.setattr(service_mod, "WRITES_PER_MINUTE", 0)
    r = client.post("/api/maintenance/positions", json={"name": "Q"})
    assert r.status_code == 429 and "minute" in r.json()["detail"]
    monkeypatch.setattr(service_mod, "WRITES_PER_MINUTE", 600)
    assert client.post("/api/maintenance/coordinates",
                       json={"node_id": pid, "lat": 1, "lon": 2, "source": "gps"}).status_code == 422


def test_feed_errors_answer_422_not_500(api, monkeypatch):
    from backend.routers import ingest as ingest_router

    ingest_router._hits.clear()
    client = api["client"]
    pid = client.post("/api/maintenance/positions", json={"name": "Engine"}).json()["id"]
    client.post(f"/api/maintenance/positions/{pid}/points",
                json={"name": "Hours", "kind": "counter", "unit": "hours", "source": "automated", "tag": "H"})
    api["app"].dependency_overrides[ingest_router.ingest_scope] = lambda: api["user"]
    for rows in (["x"], [{"tag": "H", "value": 1, "time": 1e20}], [{"tag": "H", "value": 1, "time": "9999-01-01"}]):
        r = client.post("/api/ingest/maintenance/readings", json={"readings": rows})
        assert r.status_code == 422, r.text
    monkeypatch.setattr(service_mod, "MAX_READINGS_PER_DAY", 0)
    r = client.post("/api/ingest/maintenance/readings", json={"readings": [{"tag": "H", "value": 1}]})
    assert r.status_code == 429
