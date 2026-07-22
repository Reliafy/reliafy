"""Per-demand (Binomial) reliability models."""

import mongomock
import pytest

from backend import fitting

A = "user-a"
USERS = {A: {"uid": A, "email": "a@x.com", "name": "A"}}


def test_result_per_demand_math():
    r = fitting.result_per_demand(130, 3)
    assert r["kind"] == "per_demand"
    d = r["per_demand"]
    assert d["p"] == pytest.approx(3 / 130)
    assert d["reliability"] == pytest.approx(1 - 3 / 130)
    lo, hi = d["ci"]
    assert 0 < lo < d["p"] < hi < 0.1        # Wilson interval brackets p
    assert r["functions"] is None and r["gof"] == []


def test_per_demand_edge_cases():
    zero = fitting.result_per_demand(50, 0)
    assert zero["per_demand"]["p"] == 0.0 and zero["per_demand"]["ci"][0] == pytest.approx(0, abs=1e-9)
    allf = fitting.result_per_demand(50, 50)
    assert allf["per_demand"]["p"] == 1.0 and allf["per_demand"]["ci"][1] == pytest.approx(1, abs=1e-9)
    for bad in ((0, 0), (10, 11), (-1, 0)):
        with pytest.raises(fitting.FitError):
            fitting.result_per_demand(*bad)


def test_success_run_zero_failures():
    # Classic "59 for 95/95": 59 clean demands demonstrate ~95% reliability at 95%.
    r = fitting.result_per_demand(59, 0, confidence=0.95)
    sr = r["per_demand"]["success_run"]
    assert sr["confidence"] == 0.95
    assert sr["reliability_lower"] == pytest.approx(0.95, abs=5e-3)
    # Formula check: R = (1 - C)^(1/n).
    assert fitting.result_per_demand(22, 0, confidence=0.90)["per_demand"]["success_run"]["reliability_lower"] \
        == pytest.approx((1 - 0.90) ** (1 / 22))
    # Only applies with zero failures.
    assert "success_run" not in fitting.result_per_demand(100, 3)["per_demand"]
    # Confidence is validated.
    for bad in (0.0, 1.0, 1.5, -0.1):
        with pytest.raises(fitting.FitError):
            fitting.result_per_demand(59, 0, confidence=bad)


@pytest.fixture()
def client(monkeypatch):
    from fastapi.testclient import TestClient
    from backend import config, db
    from backend.auth import get_current_user
    from backend.main import app

    monkeypatch.setattr(config, "AUTH_DISABLED", False)
    monkeypatch.setattr(config, "BILLING_ENABLED", False)
    test_db = mongomock.MongoClient()["reliafy_test"]
    monkeypatch.setattr(db, "_db", test_db)
    monkeypatch.setattr(db, "_simulated", True)
    app.dependency_overrides[get_current_user] = lambda: USERS[A]
    tc = TestClient(app)
    tc.db = test_db
    try:
        yield tc
    finally:
        app.dependency_overrides.clear()


def test_per_demand_endpoint(client):
    r = client.post("/api/models/per-demand", json={"name": "Relief valve", "demands": 130, "failures": 3})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["kind"] == "per_demand"
    assert body["results"]["per_demand"]["p"] == pytest.approx(3 / 130)
    assert body["dataset_id"] == ""

    # Reads back like any model.
    got = client.get(f"/api/models/{body['id']}").json()
    assert got["results"]["distribution"] == "Per-demand (Binomial)"

    # Validation.
    assert client.post("/api/models/per-demand", json={"name": "x", "demands": 10, "failures": 20}).status_code == 422
    assert client.post("/api/models/per-demand", json={"name": "", "demands": 10, "failures": 1}).status_code == 422

    # Success run: zero failures + confidence -> demonstrated reliability bound.
    sr = client.post("/api/models/per-demand",
                     json={"name": "Igniter demo", "demands": 59, "failures": 0, "confidence": 0.95})
    assert sr.status_code == 200, sr.text
    block = sr.json()["results"]["per_demand"]["success_run"]
    assert block["confidence"] == 0.95 and block["reliability_lower"] == pytest.approx(0.95, abs=5e-3)
