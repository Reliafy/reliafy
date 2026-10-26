"""Reliafy Maintenance: meters, tasks by use, whichever-comes-first, and the
daily run that raises work and emails a digest."""

from datetime import date, timedelta

import mongomock
import pytest

from backend.maintenance.service import PROJECTORS, Invalid, Maintenance
from backend.maintenance.store import GraphStore
from backend.tests.rcm_tree import position_with_rcm


def _ago(days: int) -> str:
    return (date.today() - timedelta(days=days)).isoformat()


class _Rcm:
    name = "Pool pump"
    functions = [{"id": "f", "text": "Circulate", "failures": [{"id": "ff", "text": "No flow", "modes": [
        {"id": "m1", "text": "Seal worn", "consequence": "operational",
         "decision": {"outcome": "fixed_interval", "interval": 500, "interval_unit": "hours",
                      "task": "Replace the seal"}}]}]}]


@pytest.fixture()
def m():
    return Maintenance(GraphStore(":memory:", PROJECTORS), "user-u", "tester")


def test_a_task_by_use_projects_its_date_from_the_meter(m):
    pos = position_with_rcm(m, _Rcm.functions, _Rcm.name)["position"]
    pid, task = pos["id"], pos["tasks"][0]
    assert task["by_use"] and task["next_due"] is None and "counter" in task["limits"][0]["note"]
    meter = m.add_point(pid, "Run hours", kind="counter", unit="hrs")
    assert meter["unit"] == "hours" and meter["kind"] == "counter" and meter["source"] == "manual"
    m.record_reading(meter["id"], 1000, _ago(60))
    m.fit(pid, new_item={"name": "Pump"}, on=_ago(60))  # renewal: last done at 1000 h
    m.record_reading(meter["id"], 1400, _ago(10))
    view = m.position(pid)["tasks"][0]
    assert view["last_done_reading"] == 1000
    lim = view["limits"][0]
    assert lim["due_at_reading"] == 1500 and lim["counter"]["rate_per_day"] == 8
    assert view["next_due"] == (date.today() + timedelta(days=2)).isoformat()  # 100 h at 8 h a day
    with pytest.raises(Invalid):
        m.record_reading(meter["id"], 1300)  # meters only go up


def test_whichever_comes_first_and_the_reading_at_the_work(m):
    pos = position_with_rcm(m, _Rcm.functions, _Rcm.name)["position"]
    pid, task = pos["id"], pos["tasks"][0]
    meter = m.add_point(pid, "", kind="counter", unit="hours")
    m.record_reading(meter["id"], 0, _ago(200))
    m.record_reading(meter["id"], 100, _ago(100))  # 1 h a day: 500 h is 400 days away
    m.update_task(task["id"], also_interval=3, also_unit="months")
    view = m.position(pid)["tasks"][0]
    calendar = next(lim for lim in view["limits"] if lim["limit"] == "3 months")
    assert view["next_due"] == calendar["next_due"]  # the calendar limit comes first
    wo = m.open_work_order(pid, "Seal", type="preventive", task_id=task["id"])
    m.close_work_order(wo["id"], [{"kind": "repair"}], readings=[{"point_id": meter["id"], "value": 180}])
    done = m.position(pid)["tasks"][0]
    assert done["last_done"] == date.today().isoformat() and done["last_done_reading"] == 180
    m.update_task(task["id"], also_interval=0)
    assert len(m.position(pid)["tasks"][0]["limits"]) == 1


def test_daily_run_raises_work_once_and_emails_a_digest(monkeypatch):
    from backend import config
    from backend.maintenance import daily
    from backend.services import email as email_service

    sent = []
    monkeypatch.setattr(email_service, "send", lambda to, subject, body, **k: sent.append((to, subject, body)))
    monkeypatch.setattr(config, "MAINTENANCE_ENABLED", True)
    monkeypatch.setattr(config, "AUTH_DISABLED", False)
    monkeypatch.setattr(config, "MAINTENANCE_EMAILS", {"me@example.org"})
    db = mongomock.MongoClient()["daily"]
    db.users.insert_one({"_id": "user-u", "email": "me@example.org", "email_verified": True})
    store = GraphStore(":memory:", PROJECTORS)
    m = Maintenance(store, "user-u")

    class Weekly:
        name = "Smoke alarms"
        functions = [{"id": "f", "text": "Detect", "failures": [{"id": "ff", "text": "No alarm", "modes": [
            {"id": "m1", "text": "Battery flat", "consequence": "hidden",
             "decision": {"outcome": "failure_finding", "interval": 1, "interval_unit": "weeks",
                          "task": "Press test"}}]}]}]

    position_with_rcm(m, Weekly.functions, Weekly.name)
    first = daily.run(db, store)
    assert first["work_orders"] == 1 and first["emails"] == 1
    assert "Press test" in sent[0][2] and sent[0][0] == "me@example.org"
    assert daily.run(db, store)["skipped"] == "already ran today"
    db.maintenance_runs.delete_many({})
    db.users.update_one({"_id": "user-u"}, {"$set": {"maintenance_digest_off": True}})
    assert daily.run(db, store)["work_orders"] == 0  # its work order is already open
    assert len(sent) == 1
