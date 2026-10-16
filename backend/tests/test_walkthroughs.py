"""Guided walkthroughs (#32): their activation events, the admin report's
per-walkthrough counts, and the once-per-user automatic start."""

import re
from pathlib import Path

import mongomock
import pytest

REPO = Path(__file__).resolve().parents[2]
A = "user-a"
B = "user-b"
USERS = {
    A: {"uid": A, "email": "a@x.com", "name": "A", "email_verified": True},
    B: {"uid": B, "email": "b@x.com", "name": "B", "email_verified": True},
}


@pytest.fixture()
def client(monkeypatch):
    from fastapi.testclient import TestClient

    from backend import config, db
    from backend.auth import get_current_user
    from backend.main import app

    monkeypatch.setattr(config, "AUTH_DISABLED", False)
    monkeypatch.setattr(config, "BILLING_ENABLED", False)
    monkeypatch.setattr(config, "ADMIN_EMAILS", {"a@x.com"})
    test_db = mongomock.MongoClient()["reliafy_test"]
    monkeypatch.setattr(db, "_db", test_db)
    monkeypatch.setattr(db, "_simulated", True)

    tc = TestClient(app)

    def act_as(uid):
        app.dependency_overrides[get_current_user] = lambda: USERS[uid]

    tc.act_as = act_as
    tc.db = test_db
    try:
        yield tc
    finally:
        app.dependency_overrides.clear()


def _event(client, name, **extra):
    return client.post(
        "/api/metrics/event",
        json={"name": name, "path": "/modelling/new", **extra},
        headers={"user-agent": "Mozilla/5.0", "x-forwarded-for": "203.0.113.7"},
    )


def test_ids_match_the_frontend_definitions():
    from backend.services.walkthroughs import WALKTHROUGH_IDS

    src = (REPO / "frontend" / "src" / "walkthroughs.js").read_text()
    m = re.search(r"WALKTHROUGH_IDS = \[([^\]]*)\]", src)
    assert m and tuple(re.findall(r'"(\w+)"', m.group(1))) == WALKTHROUGH_IDS


def test_walkthrough_events_are_allowlisted_client_events():
    from backend.routers.telemetry import CLIENT_EVENTS

    assert {"walkthrough_started", "walkthrough_step", "walkthrough_completed",
            "walkthrough_skipped"} <= CLIENT_EVENTS


def test_events_stored_with_walkthrough_and_step(client):
    assert _event(client, "walkthrough_started", walkthrough="fit").status_code == 200
    assert _event(client, "walkthrough_step", walkthrough="fit", step=1).status_code == 200
    assert _event(client, "walkthrough_step", walkthrough="fit", step=2).status_code == 200
    assert _event(client, "walkthrough_completed", walkthrough="fit", step=4).status_code == 200
    assert _event(client, "walkthrough_skipped", walkthrough="rcm", step=2).status_code == 200
    docs = list(client.db.metrics_events.find({}, {"_id": 0, "name": 1, "walkthrough": 1, "step": 1}))
    assert {"name": "walkthrough_step", "walkthrough": "fit", "step": 2} in docs
    assert {"name": "walkthrough_started", "walkthrough": "fit"} in docs
    assert {"name": "walkthrough_skipped", "walkthrough": "rcm", "step": 2} in docs
    # Privacy as for every event: nothing identifies the client directly.
    blob = str(list(client.db.metrics_events.find({})))
    assert "203.0.113.7" not in blob and "Mozilla" not in blob


@pytest.mark.parametrize("payload", [
    {"name": "walkthrough_started"},  # no walkthrough
    {"name": "walkthrough_started", "walkthrough": "nope"},  # unknown one
    {"name": "walkthrough_step", "walkthrough": "fit"},  # a step needs its number
    {"name": "walkthrough_step", "walkthrough": "fit", "step": 0},
    {"name": "walkthrough_step", "walkthrough": "fit", "step": 99},
    {"name": "walkthrough_completed", "walkthrough": "fit", "step": "x"},
])
def test_malformed_walkthrough_events_refused(client, payload):
    name = payload.pop("name")
    assert _event(client, name, **payload).status_code == 422
    assert client.db.metrics_events.count_documents({}) == 0


def test_other_events_ignore_walkthrough_fields(client):
    assert _event(client, "first_run_rbd", walkthrough="rbd", step=3).status_code == 200
    doc = client.db.metrics_events.find_one({})
    assert doc["name"] == "first_run_rbd" and "walkthrough" not in doc and "step" not in doc


def test_auto_start_once_per_user(client):
    client.act_as(A)
    assert client.post("/api/me/walkthroughs/auto", json={"id": "rbd"}).json() == {"start": True}
    assert client.post("/api/me/walkthroughs/auto", json={"id": "rbd"}).json() == {"start": False}
    # Per walkthrough, and per user.
    assert client.post("/api/me/walkthroughs/auto", json={"id": "fit"}).json() == {"start": True}
    client.act_as(B)
    assert client.post("/api/me/walkthroughs/auto", json={"id": "rbd"}).json() == {"start": True}
    assert client.db.users.find_one({"_id": A})["walkthroughs_auto"] == ["rbd", "fit"]


def test_auto_start_unknown_id_refused(client):
    client.act_as(A)
    assert client.post("/api/me/walkthroughs/auto", json={"id": "nope"}).status_code == 422
    assert client.post("/api/me/walkthroughs/auto", json={}).status_code == 422


def test_auto_start_needs_sign_in(client):
    assert client.post("/api/me/walkthroughs/auto", json={"id": "rbd"}).status_code == 401


def test_auto_start_claims_are_not_logged_as_product_usage():
    from backend.services import usage

    assert usage.app_feature("POST", "/api/me/walkthroughs/auto") is None


def test_summarise_ignores_unknown_and_malformed():
    from backend.services.walkthroughs import summarise

    rows = summarise([
        {"name": "walkthrough_started", "walkthrough": "gone"},
        {"name": "walkthrough_step", "walkthrough": "rcm", "step": "2"},
        {"name": "walkthrough_step", "walkthrough": "rcm", "step": 2},
        {"name": "pageview"},
    ])
    rcm = next(r for r in rows if r["key"] == "rcm")
    assert rcm["steps"] == {"2": 1} and rcm["started"] == 0
    assert sum(r["started"] for r in rows) == 0
