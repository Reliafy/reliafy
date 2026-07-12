"""Public share links: creation rules, unauthenticated reads, sanitization."""

import matplotlib

matplotlib.use("Agg")

import io

import mongomock
import numpy as np
import pandas as pd
import pytest

A = "user-a"
B = "user-b"

USERS = {
    A: {"uid": A, "email": "a@x.com", "name": "Alice"},
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
    test_db = mongomock.MongoClient()["reliafy_test"]
    monkeypatch.setattr(db, "_db", test_db)
    monkeypatch.setattr(db, "_simulated", True)

    tc = TestClient(app)

    def act_as(uid):
        if uid is None:
            app.dependency_overrides.pop(get_current_user, None)
        else:
            app.dependency_overrides[get_current_user] = lambda: USERS[uid]
            email = USERS[uid]["email"]
            test_db.users.update_one(
                {"_id": uid},
                {"$set": {"email": email, "email_lc": email, "name": USERS[uid]["name"]}},
                upsert=True,
            )

    tc.act_as = act_as
    tc.db = test_db
    try:
        yield tc
    finally:
        app.dependency_overrides.clear()


def _save_model(client, name="Pump bearings"):
    rng = np.random.default_rng(7)
    df = pd.DataFrame({"hours": rng.weibull(2.0, 40) * 1000})
    csv = io.BytesIO(df.to_csv(index=False).encode())
    r = client.post(
        "/api/models",
        data={"name": name, "distribution": "weibull", "x": "hours", "unit": "hours"},
        files={"file": ("data.csv", csv, "text/csv")},
    )
    assert r.status_code == 200, r.text
    return r.json()["id"]


def test_owner_creates_link_and_public_read_works(client):
    client.act_as(A)
    model_id = _save_model(client)
    r = client.post("/api/public-links", json={"collection": "models", "artifact_id": model_id})
    assert r.status_code == 200
    token = r.json()["token"]
    assert len(token) >= 20 and r.json()["path"] == f"/p/{token}"

    # Idempotent: re-creating returns the same token.
    again = client.post("/api/public-links", json={"collection": "models", "artifact_id": model_id})
    assert again.json()["token"] == token

    # Unauthenticated fetch works and carries the results.
    client.act_as(None)
    pub = client.get(f"/api/public/{token}")
    assert pub.status_code == 200
    data = pub.json()
    assert data["collection"] == "models"
    assert data["shared_by"] == "Alice"
    assert data["artifact"]["name"] == "Pump bearings"
    assert data["artifact"]["results"]["distribution"].lower().startswith("weibull")


def test_public_payload_has_no_identities(client):
    client.act_as(A)
    model_id = _save_model(client)
    token = client.post(
        "/api/public-links", json={"collection": "models", "artifact_id": model_id}
    ).json()["token"]
    client.act_as(None)
    body = client.get(f"/api/public/{token}").text
    assert "owner_id" not in body and "updated_by" not in body
    assert A not in body and "a@x.com" not in body


def test_only_owner_can_create_or_revoke(client):
    client.act_as(A)
    model_id = _save_model(client)
    token = client.post(
        "/api/public-links", json={"collection": "models", "artifact_id": model_id}
    ).json()["token"]

    client.act_as(B)
    r = client.post("/api/public-links", json={"collection": "models", "artifact_id": model_id})
    assert r.status_code == 404
    assert client.delete(f"/api/public-links/{token}").status_code == 404

    client.act_as(A)
    assert client.delete(f"/api/public-links/{token}").status_code == 200
    client.act_as(None)
    assert client.get(f"/api/public/{token}").status_code == 404


def test_unknown_token_and_unsupported_collection(client):
    client.act_as(None)
    assert client.get("/api/public/not-a-real-token").status_code == 404
    client.act_as(A)
    model_id = _save_model(client)
    r = client.post("/api/public-links", json={"collection": "rbds", "artifact_id": model_id})
    assert r.status_code == 400


def test_link_dies_with_artifact(client):
    client.act_as(A)
    model_id = _save_model(client)
    token = client.post(
        "/api/public-links", json={"collection": "models", "artifact_id": model_id}
    ).json()["token"]
    client.delete(f"/api/models/{model_id}")
    client.act_as(None)
    assert client.get(f"/api/public/{token}").status_code == 404


def test_public_endpoints_require_no_auth_but_management_does(client):
    client.act_as(None)
    assert client.post(
        "/api/public-links", json={"collection": "models", "artifact_id": "x"}
    ).status_code == 401


def test_sample_artifacts_rejected(client):
    from backend.services import samples as samples_service

    client.act_as(A)
    samples_service.seed_samples(client.db)
    sample = client.db.models.find_one({})
    r = client.post(
        "/api/public-links", json={"collection": "models", "artifact_id": sample["_id"]}
    )
    assert r.status_code == 400
    assert "Samples" in r.json()["detail"]
