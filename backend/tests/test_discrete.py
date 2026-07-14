"""Discrete lifetime distributions (Discrete Weibull / Geometric / Negative
Binomial) as first-class models — endpoint listing and save round-trip."""

import matplotlib

matplotlib.use("Agg")

import io

import mongomock
import pandas as pd
import pytest

A = "user-a"
USERS = {A: {"uid": A, "email": "a@x.com", "name": "A"}}


def _cycles_df():
    # Whole-count cycles-to-failure.
    return pd.DataFrame({"cycles": [3, 5, 5, 6, 7, 7, 8, 8, 9, 10, 11, 12, 14, 16, 20]})


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


def test_discrete_in_distributions_endpoint(client):
    dists = client.get("/api/distributions").json()["distributions"]
    by_id = {d["id"]: d for d in dists}
    for did in ("discrete_weibull", "geometric", "negative_binomial"):
        assert did in by_id
        assert by_id[did]["discrete"] is True
        assert by_id[did]["covariates"] is False


def test_save_discrete_weibull_round_trip(client):
    csv = io.BytesIO(_cycles_df().to_csv(index=False).encode())
    r = client.post(
        "/api/models",
        data={"name": "Relay cycles", "distribution": "discrete_weibull",
              "x": "cycles", "unit": "cycles"},
        files={"file": ("d.csv", csv, "text/csv")},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["kind"] == "discrete"
    res = body["results"]
    assert res["distribution_id"] == "discrete_weibull"
    assert res["plot"] is None  # no probability paper for discrete
    assert {p["name"] for p in res["params"]} == {"q", "beta"}
    assert res["metrics"]["median"] is not None
    assert body["dataset_id"]  # data uploaded and linked

    # It reads back like any saved model.
    got = client.get(f"/api/models/{body['id']}").json()
    assert got["results"]["kind"] == "discrete"
