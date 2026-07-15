"""Public programmatic API (/api/v1) — token-authed, personal scope."""

import matplotlib

matplotlib.use("Agg")

import mongomock
import pytest

A = "user-a"
USERS = {A: {"uid": A, "email": "a@x.com", "name": "A"}}


@pytest.fixture()
def client(monkeypatch):
    from fastapi.testclient import TestClient
    from backend import config, db
    from backend.auth import get_current_user
    from backend.main import app
    from backend.routers import ingest as ingest_router

    monkeypatch.setattr(config, "AUTH_DISABLED", False)
    monkeypatch.setattr(config, "BILLING_ENABLED", False)
    test_db = mongomock.MongoClient()["reliafy_test"]
    monkeypatch.setattr(db, "_db", test_db)
    monkeypatch.setattr(db, "_simulated", True)
    ingest_router._hits.clear()
    app.dependency_overrides[get_current_user] = lambda: USERS[A]
    test_db.users.update_one({"_id": A}, {"$set": USERS[A]}, upsert=True)
    tc = TestClient(app)
    tc.db = test_db
    try:
        yield tc
    finally:
        app.dependency_overrides.clear()


@pytest.fixture()
def auth(client):
    # Mint a token (session-authed) and return the bearer header.
    raw = client.post("/api/tokens", json={"name": "test"}).json()["token"]
    return {"Authorization": f"Bearer {raw}"}


def test_requires_a_token(client):
    # No token, no session (get_current_user isn't a dependency inside the guard).
    assert client.get("/api/v1/models").status_code == 401


def test_dataset_fit_read_reliability(client, auth):
    # Create a dataset.
    r = client.post("/api/v1/datasets", headers=auth, json={
        "name": "API bearings",
        "csv": "hours,failed\n120,1\n340,1\n510,0\n700,1\n980,1\n1200,0\n1500,1\n1800,0",
    })
    assert r.status_code == 200, r.text
    ds = r.json()
    assert ds["n_rows"] == 8 and ds["columns"] == ["hours", "failed"]

    # Fit a model from it.
    r = client.post("/api/v1/fit", headers=auth, json={
        "name": "API Weibull", "dataset_id": ds["id"], "distribution": "weibull",
        "mapping": {"x": "hours", "c": "failed"}, "unit": "hours",
    })
    assert r.status_code == 200, r.text
    mid = r.json()["id"]
    assert r.json()["distribution"] == "Weibull"

    # It appears in the list.
    ids = [m["id"] for m in client.get("/api/v1/models", headers=auth).json()["models"]]
    assert mid in ids

    # Detail carries params (+CIs) and goodness-of-fit.
    detail = client.get(f"/api/v1/models/{mid}", headers=auth).json()
    assert {p["name"] for p in detail["params"]} == {"alpha", "beta"}
    assert all("ci" in p for p in detail["params"])
    assert {"aic", "bic"} <= {g["id"] for g in detail["gof"]}

    # Reliability at a time.
    at = client.post(f"/api/v1/models/{mid}/reliability", headers=auth, json={"t": 500}).json()["at"]
    assert at["t"] == 500 and 0 <= at["reliability"] <= 1
    assert at["reliability"] + at["failure"] == pytest.approx(1.0, abs=1e-6)


def test_reads_are_scoped_to_the_caller(client, auth):
    # A model id that doesn't belong to this user (and isn't a sample) → 404.
    assert client.get("/api/v1/models/nope", headers=auth).status_code == 404


def test_strategy_calculators(client, auth):
    r = client.post("/api/v1/strategy/optimal-replacement", headers=auth, json={
        "distribution_id": "weibull", "params": [1435, 2.5],
        "planned_cost": 200, "unplanned_cost": 1500, "unit": "hours",
    })
    assert r.status_code == 200, r.text
    assert "optimal_time" in r.json() and "beneficial" in r.json()

    r = client.post("/api/v1/strategy/failure-finding", headers=auth, json={
        "distribution_id": "exponential", "params": [{"name": "failure_rate", "value": 1e-4}],
        "target_availability": 0.99, "unit": "hours",
    })
    assert r.status_code == 200, r.text
    assert "interval" in r.json()
