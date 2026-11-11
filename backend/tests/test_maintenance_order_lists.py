"""Reliafy Maintenance: the reads behind the Orders pages. The history (closed and
cancelled work orders, with what was done), searching the work orders, and what's
due within a chosen window."""

from datetime import date

import mongomock
import pytest

from backend.maintenance import service
from backend.maintenance.service import PROJECTORS, Maintenance
from backend.maintenance.store import GraphStore

ORG = "user-ol"


@pytest.fixture()
def today(monkeypatch):
    class Clock:
        day = date(2026, 11, 10)

        def set(self, text):
            self.day = date.fromisoformat(text)

    clock = Clock()
    monkeypatch.setattr(service.time_zones, "today", lambda name=None: clock.day)
    return clock


@pytest.fixture()
def m(today):
    return Maintenance(GraphStore(":memory:", PROJECTORS), ORG, "tester")


def _history(m):
    pump = m.create_position("Feed pump", tag="P-101")["id"]
    fan = m.create_position("Cooling fan")["id"]
    checked = m.open_work_order(pump, "Check the seal")
    m.close_work_order(checked["id"], [{"kind": "inspect", "finding": "ok"}])
    swapped = m.open_work_order(fan, "Swap the belt")
    m.close_work_order(swapped["id"], [{"kind": "replace", "new_item": {"name": "Belt B2"}}], notes="New belt from the store")
    dropped = m.open_work_order(fan, "Paint the guard")
    m.cancel_work_order(dropped["id"], "Not needed")
    still = m.open_work_order(pump, "Tighten the coupling")
    return {"checked": checked, "swapped": swapped, "dropped": dropped, "still": still}


def test_done_lists_closed_and_cancelled_newest_first_with_what_was_done(m):
    wos = _history(m)
    done = m.work_orders("done")
    assert [w["id"] for w in done] == [wos["dropped"]["id"], wos["swapped"]["id"], wos["checked"]["id"]]
    by_id = {w["id"]: w for w in done}
    assert by_id[wos["checked"]["id"]]["done"] == [{"kind": "inspect", "finding": "ok"}]
    assert by_id[wos["swapped"]["id"]]["done"] == [{"kind": "replace", "finding": None}]
    assert by_id[wos["dropped"]["id"]]["done"] == [] and by_id[wos["dropped"]["id"]]["status"] == "cancelled"
    # Nothing still open, and no overdue mark on a finished one.
    assert all(not w["overdue"] for w in done)
    # Other reads don't carry it.
    assert "done" not in m.work_orders("closed")[0] and "done" not in m.work_orders("open")[0]


def test_search_matches_title_notes_what_its_on_and_number(m):
    wos = _history(m)
    ids = lambda rows: {w["id"] for w in rows}  # noqa: E731
    assert ids(m.work_orders("done", q="belt")) == {wos["swapped"]["id"]}  # title and close notes
    assert ids(m.work_orders("done", q="FEED PUMP")) == {wos["checked"]["id"]}  # what it's on, any case
    assert ids(m.work_orders("done", q="p-101")) == {wos["checked"]["id"]}  # its tag
    assert ids(m.work_orders(None, q="pump")) == {wos["checked"]["id"], wos["still"]["id"]}
    number = wos["swapped"]["number"]
    assert ids(m.work_orders("done", q=f"#{number}")) == {wos["swapped"]["id"]}
    assert m.work_orders("done", q="nothing like this") == []
    assert len(m.work_orders("done", q="  ")) == 3


def test_the_api_lists_history_searches_and_reads_due_by_window(monkeypatch, today):
    from fastapi.testclient import TestClient

    from backend import config, db
    from backend.auth import get_current_user
    from backend.main import app
    from backend.routers import maintenance as router

    monkeypatch.setattr(db, "_db", mongomock.MongoClient()["reliafy_order_lists"])
    monkeypatch.setattr(db, "_simulated", True)
    monkeypatch.setattr(router, "_store", GraphStore(":memory:", PROJECTORS))
    monkeypatch.setattr(config, "MAINTENANCE_ENABLED", True)
    monkeypatch.setattr(config, "MAINTENANCE_EMAILS", {"o@x.com"})
    app.dependency_overrides[get_current_user] = lambda: {
        "uid": ORG, "email": "o@x.com", "name": "O", "email_verified": True}
    client = TestClient(app)
    base = "/api/maintenance"
    try:
        pump = client.post(f"{base}/positions", json={"name": "Feed pump"}).json()["id"]
        for title in ("Check the seal", "Swap the belt", "Grease it"):
            wo = client.post(f"{base}/work-orders", json={"position_id": pump, "title": title}).json()
            client.post(f"{base}/work-orders/{wo['id']}/close", json={"actions": [{"kind": "repair"}]})
        client.post(f"{base}/work-orders", json={"position_id": pump, "title": "Still to do"})

        done = client.get(f"{base}/work-orders", params={"status": "done"}).json()
        assert done["total"] == 3 and [w["title"] for w in done["work_orders"]][0] == "Grease it"
        assert done["work_orders"][0]["done"] == [{"kind": "repair", "finding": None}]
        page = client.get(f"{base}/work-orders", params={"status": "done", "limit": 2}).json()
        assert page["total"] == 3 and len(page["work_orders"]) == 2
        found = client.get(f"{base}/work-orders", params={"status": "done", "q": "belt"}).json()
        assert [w["title"] for w in found["work_orders"]] == ["Swap the belt"] and found["total"] == 1
        assert client.get(f"{base}/work-orders", params={"status": "open"}).json()["total"] == 1

        # What's due, by the window asked for: a weekly task is in 7 days, a yearly one only in 366.
        client.post(f"{base}/positions/{pump}/tasks", json={"name": "Weekly check", "interval": 1, "unit": "weeks",
                                                            "start": "2026-11-12"})
        client.post(f"{base}/positions/{pump}/tasks", json={"name": "Yearly overhaul", "interval": 1,
                                                            "unit": "years", "start": "2027-06-01"})
        week = client.get(f"{base}/due", params={"horizon_days": 7}).json()
        assert week["horizon_days"] == 7 and [t["name"] for t in week["due"]] == ["Weekly check"]
        assert week["today"] == "2026-11-10"
        year = client.get(f"{base}/due", params={"horizon_days": 9999}).json()
        assert year["horizon_days"] == 366 and {t["name"] for t in year["due"]} == {"Weekly check", "Yearly overhaul"}
        assert client.get(f"{base}/due").json()["horizon_days"] == 30
    finally:
        app.dependency_overrides.pop(get_current_user, None)


def test_a_package_work_order_says_how_far_through_its_lines_it_is(m, today):
    today.set("2026-11-01")
    pump = m.create_position("Pump 1")["id"]
    tasks = [m.create_task(pump, name, 1, "weeks", start="2026-11-07")["id"] for name in ("Grease", "Check seal")]
    m.create_package("Weekly round", position_id=pump, every=1, unit="weeks", weekday="saturday",
                     anchor="2026-11-07", tasks=tasks)
    m.generate(30)
    [wo] = m.work_orders("open")
    assert wo["package"]["name"] == "Weekly round"
    assert (wo["lines_answered"], wo["lines_total"]) == (0, 2)
    m.mark_line(wo["id"], tasks[0], "done")
    [wo] = m.work_orders("open")
    assert (wo["lines_answered"], wo["lines_total"]) == (1, 2)
