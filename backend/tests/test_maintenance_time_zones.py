"""A workspace's time zone: setting it (personal and team), and Reliafy
Maintenance's calendar days following it: today, work orders' dates, feed
readings' days, due and overdue, and the daily run."""

import os
import time
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import mongomock
import pytest

from backend.maintenance.series import MongoSeries
from backend.maintenance.service import PROJECTORS, Maintenance
from backend.maintenance.store import GraphStore
from backend.services import time_zones

UID = "user-tz"
BNE = "Australia/Brisbane"  # UTC+10, no daylight saving


def _at(monkeypatch, iso: str) -> None:
    """Pretend it's this UTC moment."""
    moment = datetime.fromisoformat(iso).replace(tzinfo=timezone.utc)
    monkeypatch.setattr(time_zones, "_now", lambda: moment)


@pytest.fixture()
def server_in_utc(monkeypatch):
    """The server's own zone is UTC, as in production (the machine running the
    tests may be anywhere)."""
    monkeypatch.setenv("TZ", "UTC")
    time.tzset()
    yield
    monkeypatch.undo()
    time.tzset()


# ---- the setting -------------------------------------------------------------------------

def test_a_time_zone_is_an_iana_name():
    assert time_zones.clean(" Australia/Brisbane ") == BNE
    assert time_zones.clean("Europe/London") == "Europe/London"
    assert time_zones.clean("") is None and time_zones.clean(None) is None  # cleared: UTC
    for bad in ("Mars/Olympus_Mons", "../../etc/passwd", "+10:00", "x" * 100, 10):
        with pytest.raises(time_zones.BadTimeZone):
            time_zones.clean(bad)
    assert time_zones.zone(None) is None and time_zones.zone("Not/AZone") is None
    assert time_zones.zone_name("Not/AZone") is None and time_zones.zone_name(BNE) == BNE


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
    monkeypatch.setattr(config, "MAINTENANCE_EMAILS", {"tz@example.org", "mate@example.org"})
    test_db = mongomock.MongoClient()["maint_tz_api"]
    monkeypatch.setattr(db, "_db", test_db)
    monkeypatch.setattr(db, "_simulated", True)
    monkeypatch.setattr(router, "_store", GraphStore(":memory:", PROJECTORS))
    users = {u: {"uid": u, "email": f"{n}@example.org", "name": n, "email_verified": True}
             for u, n in ((UID, "tz"), ("user-mate", "mate"))}
    for u in users.values():
        test_db.users.insert_one({"_id": u["uid"], "email": u["email"], "name": u["name"], "email_verified": True})
    client = TestClient(app)
    client.act_as = lambda uid: app.dependency_overrides.__setitem__(get_current_user, lambda: users[uid])
    client.act_as(UID)
    try:
        yield client, test_db
    finally:
        app.dependency_overrides.clear()


def test_the_personal_workspace_sets_its_time_zone(api):
    client, db = api
    assert client.get("/api/me/time-zone").json() == {"time_zone": None}
    assert client.get("/api/me").json()["time_zone"] is None
    r = client.put("/api/me/time-zone", json={"time_zone": "Mars/Olympus_Mons"})
    assert r.status_code == 422 and "isn't a time zone" in r.json()["detail"]
    assert client.put("/api/me/time-zone", json={"time_zone": BNE}).json() == {"time_zone": BNE}
    assert client.get("/api/me").json()["time_zone"] == BNE
    assert client.get("/api/maintenance/overview").json()["time_zone"] == BNE
    assert time_zones.of_owner(db, UID) == BNE
    assert client.put("/api/me/time-zone", json={"time_zone": None}).json() == {"time_zone": None}
    assert client.get("/api/maintenance/overview").json()["time_zone"] is None


def test_a_team_owner_sets_the_teams_time_zone(api):
    client, db = api
    db.teams.insert_one({"_id": "t1", "name": "Plant", "owner_uid": UID, "invites": [],
                         "members": [{"uid": UID, "role": "owner"}, {"uid": "user-mate", "role": "member"}]})
    client.put("/api/me/time-zone", json={"time_zone": "Europe/London"})
    r = client.put("/api/teams/t1/time-zone", json={"time_zone": BNE})
    assert r.status_code == 200 and r.json()["time_zone"] == BNE
    assert client.put("/api/teams/t1/time-zone", json={"time_zone": "Nowhere"}).status_code == 422
    assert client.get("/api/teams").json()["teams"][0]["time_zone"] == BNE
    # The active workspace's zone: the team's in the team, the user's own in personal.
    assert client.get("/api/maintenance/overview", headers={"X-Workspace-Id": "t1"}).json()["time_zone"] == BNE
    assert client.get("/api/maintenance/overview").json()["time_zone"] == "Europe/London"
    assert time_zones.of_owner(db, "team:t1") == BNE
    client.act_as("user-mate")
    assert client.put("/api/teams/t1/time-zone", json={"time_zone": "UTC"}).status_code == 403
    assert client.get("/api/maintenance/overview", headers={"X-Workspace-Id": "t1"}).json()["time_zone"] == BNE


# ---- Maintenance follows it ---------------------------------------------------------------

def test_unset_is_the_servers_day_as_before(monkeypatch, server_in_utc):
    _at(monkeypatch, "2026-10-14T23:30:00")
    m = Maintenance(GraphStore(":memory:", PROJECTORS), UID)
    assert m.time_zone is None and m.today() == "2026-10-14"
    pid = m.create_position("Pump")["id"]
    assert m.open_work_order(pid, "Leak")["opened"] == "2026-10-14"


def test_a_work_order_opened_at_2330_utc_in_brisbane_is_dated_the_next_day(monkeypatch, server_in_utc):
    _at(monkeypatch, "2026-10-14T23:30:00")  # 09:30 on the 15th in Brisbane
    m = Maintenance(GraphStore(":memory:", PROJECTORS), UID, time_zone=BNE)
    pid = m.create_position("Pump")["id"]
    wo = m.open_work_order(pid, "Leak")
    assert wo["opened"] == "2026-10-15"
    point = m.add_point(pid, "Run hours", kind="counter", unit="hours")
    m.record_reading(point["id"], 100)  # read this morning: today, locally
    assert m.point(point["id"])["read_at"] == "2026-10-15"
    m.record_reading(point["id"], 110, "2026-10-15")  # not "in the future" in Brisbane


def _feed_store(backend):
    if backend == "mongo":
        db = mongomock.MongoClient()["tz_feeds"]
        return GraphStore(":memory:", PROJECTORS, series=MongoSeries(db))
    return GraphStore(":memory:", PROJECTORS)


@pytest.mark.parametrize("backend", ["sqlite", "mongo"])
def test_a_feed_reading_is_dated_by_its_day_in_the_zone(backend):
    store = _feed_store(backend)
    m = Maintenance(store, UID, time_zone=BNE)
    pid = m.create_position("Hot water system")["id"]
    point = m.add_point(pid, "Outlet temperature", unit="°C", source="automated", tag="hws", alarm_below=50)
    # The last 23:30 UTC that's passed: 09:30 the next day in Brisbane.
    now = datetime.now(timezone.utc)
    t = now.replace(hour=23, minute=30, second=0, microsecond=0)
    t = t if t <= now else t - timedelta(days=1)
    out = m.ingest([{"tag": "hws", "value": 38, "time": t.isoformat()}])
    utc_day, local_day = t.date().isoformat(), (t.date() + timedelta(days=1)).isoformat()
    assert store.series.daily(UID, point["id"], tz=ZoneInfo(BNE)) == [{"on": local_day, "value": 38}]
    assert store.series.daily(UID, point["id"], tz=timezone.utc) == [{"on": utc_day, "value": 38}]
    # The timestamp is stored as it came; the alarm's work order is dated by the local day.
    assert m.point(point["id"])["read_at"].startswith(utc_day + "T23:30")
    wo = m.work_order(out["work_orders_raised"][0]["id"])
    assert wo["opened"] == local_day and wo["due"] == local_day


def _weekly_task(m: Maintenance, last_done: str) -> str:
    pid = m.create_position("Smoke alarms")["id"]
    return m.create_task(pid, "Press test", 1, "weeks", last_done=last_done)["id"]


def test_due_and_overdue_turn_over_at_local_midnight(monkeypatch, server_in_utc):
    _at(monkeypatch, "2026-10-10T00:00:00")
    m = Maintenance(GraphStore(":memory:", PROJECTORS), UID, time_zone=BNE)
    utc = Maintenance(m.s, UID)  # the same workspace read without a zone
    task_id = _weekly_task(m, "2026-10-08")

    def view(mm):
        return next(t for t in mm.due_tasks(30) if t["id"] == task_id)

    _at(monkeypatch, "2026-10-15T13:59:00")  # 23:59 on the 15th in Brisbane: due today
    assert view(m)["next_due"] == "2026-10-15" and not view(m)["overdue"]
    _at(monkeypatch, "2026-10-15T14:00:00")  # midnight in Brisbane: overdue
    assert view(m)["overdue"]
    assert not view(utc)["overdue"]  # still the 15th in UTC
    _at(monkeypatch, "2026-10-16T00:00:00")
    assert view(utc)["overdue"]
    assert [t["id"] for t in m.due_tasks(0)] == [task_id]


def test_warranty_and_past_fitments_use_the_local_day(monkeypatch, server_in_utc):
    _at(monkeypatch, "2026-10-14T23:30:00")  # the 15th in Brisbane
    m = Maintenance(GraphStore(":memory:", PROJECTORS), UID, time_zone=BNE)
    pid = m.create_position("Pump")["id"]
    item = m.create_item("Pump", warranty={"ends_on": "2026-10-14"})
    assert not m.item(item["id"])["warranty"]["in_warranty"]  # ended yesterday, locally
    m.add_past_fitment(pid, "2026-01-01", "2026-10-15", reason="planned", new_item={"name": "Old pump"})
    utc = Maintenance(m.s, UID)
    assert utc.item(item["id"])["warranty"]["in_warranty"]
    with pytest.raises(Exception, match="future"):
        utc.add_past_fitment(pid, "2026-01-01", "2026-10-15", reason="planned", new_item={"name": "Older pump"})


def test_the_daily_run_works_out_each_workspaces_dates_in_its_zone(monkeypatch, server_in_utc):
    from backend import config
    from backend.maintenance import daily
    from backend.services import email as email_service

    sent = {}
    monkeypatch.setattr(email_service, "send", lambda to, subject, body, **k: sent.__setitem__(to, body))
    monkeypatch.setattr(config, "MAINTENANCE_ENABLED", True)
    monkeypatch.setattr(config, "AUTH_DISABLED", False)
    monkeypatch.setattr(config, "MAINTENANCE_EMAILS", {"bne@example.org", "la@example.org"})
    db = mongomock.MongoClient()["tz_daily"]
    db.users.insert_many([
        {"_id": "user-bne", "email": "bne@example.org", "email_verified": True, "time_zone": BNE},
        {"_id": "user-la", "email": "la@example.org", "email_verified": True, "time_zone": "America/Los_Angeles"},
    ])
    store = GraphStore(":memory:", PROJECTORS)
    _at(monkeypatch, "2026-10-10T00:00:00")
    for org in ("user-bne", "user-la"):
        _weekly_task(Maintenance(store, org), "2026-10-08")  # due on the 15th
    # One run for everyone: 00:30 on the 16th in Brisbane, 07:30 on the 15th in Los Angeles.
    _at(monkeypatch, "2026-10-15T14:30:00")
    result = daily.run(db, store, today=date(2026, 10, 16))
    assert result["work_orders"] == 2 and result["emails"] == 2
    opened = {org: [w["opened"] for w in Maintenance(store, org).work_orders("open")]
              for org in ("user-bne", "user-la")}
    assert opened == {"user-bne": ["2026-10-16"], "user-la": ["2026-10-15"]}
    assert "Overdue: 1 task" in sent["bne@example.org"]
    assert "Overdue" not in sent["la@example.org"]
