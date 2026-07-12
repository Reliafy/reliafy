"""First-party analytics: event storage, privacy properties, traffic rollup."""

import mongomock
import pytest

A = "user-a"
B = "user-b"

USERS = {
    A: {"uid": A, "email": "a@x.com", "name": "A"},
    B: {"uid": B, "email": "b@x.com", "name": "B"},
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


def _post_event(client, payload=None, ua="Mozilla/5.0", ip="203.0.113.7"):
    return client.post(
        "/api/metrics/event",
        json={"name": "pageview", "path": "/", **(payload or {})},
        headers={"user-agent": ua, "x-forwarded-for": f"{ip}, 169.254.1.1"},
    )


def test_event_stored_without_raw_identifiers(client):
    r = _post_event(client, {"path": "/weibull-analysis-software", "referrer": "https://news.ycombinator.com/item?id=1"})
    assert r.status_code == 200
    doc = client.db.metrics_events.find_one({})
    assert doc["path"] == "/weibull-analysis-software"
    assert doc["ref_host"] == "news.ycombinator.com"
    assert doc["day"] and len(doc["visitor"]) == 16
    # Privacy: nothing stored can identify the client directly.
    blob = str(doc)
    assert "203.0.113.7" not in blob and "Mozilla" not in blob


def test_same_visitor_same_day_same_hash(client):
    _post_event(client, {"path": "/a"})
    _post_event(client, {"path": "/b"})
    _post_event(client, {"path": "/c"}, ip="198.51.100.9")
    hashes = [d["visitor"] for d in client.db.metrics_events.find({})]
    assert hashes[0] == hashes[1] and hashes[2] != hashes[0]


def test_visitor_hash_rotates_daily():
    from backend.services.metrics import _visitor_hash

    h1 = _visitor_hash("2026-07-12", "1.2.3.4", "ua")
    h2 = _visitor_hash("2026-07-13", "1.2.3.4", "ua")
    assert h1 != h2


def test_bots_filtered(client):
    _post_event(client, ua="Mozilla/5.0 (compatible; Googlebot/2.1)")
    _post_event(client, ua="HeadlessChrome/126.0")
    assert client.db.metrics_events.count_documents({}) == 0


def test_own_site_referrer_dropped(client):
    _post_event(client, {"referrer": "https://reliafy.com/blog"})
    _post_event(client, {"referrer": "https://reliafy-abc123.australia-southeast1.run.app/"})
    docs = list(client.db.metrics_events.find({}))
    assert all(d["ref_host"] == "" for d in docs)


def test_utm_captured_and_clipped(client):
    _post_event(client, {"utm_source": "hn" * 200, "utm_medium": "social", "utm_campaign": "launch"})
    doc = client.db.metrics_events.find_one({})
    assert doc["utm_medium"] == "social" and doc["utm_campaign"] == "launch"
    assert len(doc["utm_source"]) == 100


def test_traffic_endpoint_gated_and_aggregates(client):
    _post_event(client, {"path": "/", "referrer": "https://news.ycombinator.com/"})
    _post_event(client, {"path": "/", "utm_source": "linkedin"})
    _post_event(client, {"path": "/login"}, ip="198.51.100.9")
    _post_event(client, {"name": "signup", "path": "/login"})

    client.act_as(B)
    assert client.get("/api/admin/traffic").status_code == 403

    client.act_as(A)
    data = client.get("/api/admin/traffic?days=7").json()
    assert data["pageviews"] == 3
    today = data["daily"][-1]
    assert today["pageviews"] == 3 and today["visitors"] == 2
    assert len(data["daily"]) == 7
    assert {"key": "/", "count": 2} in data["top_pages"]
    assert data["top_referrers"] == [{"key": "news.ycombinator.com", "count": 1}]
    assert data["top_sources"] == [{"key": "linkedin", "count": 1}]
    assert data["events"] == [{"key": "signup", "count": 1}]


def test_signup_event_once_per_account(client):
    client.act_as(A)
    client.get("/api/me")
    client.get("/api/me")
    signups = list(client.db.metrics_events.find({"name": "signup"}))
    assert len(signups) == 1
    client.act_as(B)
    client.get("/api/me")
    assert client.db.metrics_events.count_documents({"name": "signup"}) == 2


def test_traffic_days_clamped(client):
    client.act_as(A)
    assert client.get("/api/admin/traffic?days=5000").json()["days"] == 90
    assert client.get("/api/admin/traffic?days=0").json()["days"] == 14
