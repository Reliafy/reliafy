"""Personal API tokens + the ingestion API, end to end."""

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
    A: {"uid": A, "email": "a@x.com", "name": "A"},
    B: {"uid": B, "email": "b@x.com", "name": "B"},
}


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

    tc = TestClient(app)

    def act_as(uid):
        if uid is None:
            app.dependency_overrides.pop(get_current_user, None)
        else:
            app.dependency_overrides[get_current_user] = lambda: USERS[uid]
            test_db.users.update_one(
                {"_id": uid},
                {"$set": {"email": USERS[uid]["email"], "name": USERS[uid]["name"]}},
                upsert=True,
            )

    tc.act_as = act_as
    tc.db = test_db
    try:
        yield tc
    finally:
        app.dependency_overrides.clear()


def _weibull_csv(n=120, seed=2, shift=0.0):
    rng = np.random.default_rng(seed)
    return pd.DataFrame({"hours": rng.weibull(2, n) * 1000 + shift})


def _save_model(client, name="Bearings"):
    csv = io.BytesIO(_weibull_csv().to_csv(index=False).encode())
    r = client.post(
        "/api/models",
        data={"name": name, "distribution": "weibull", "x": "hours", "unit": "hours"},
        files={"file": ("lives.csv", csv, "text/csv")},
    )
    assert r.status_code == 200, r.text
    return r.json()


# ---- tokens -------------------------------------------------------------------

def test_token_lifecycle(client):
    client.act_as(A)
    created = client.post("/api/tokens", json={"name": "cron"}).json()
    assert created["token"].startswith("rlf_") and len(created["token"]) > 20
    raw = created["token"]

    # Only the hash is stored.
    doc = client.db.api_tokens.find_one({})
    assert raw not in str(doc)

    listed = client.get("/api/tokens").json()["tokens"]
    assert listed[0]["prefix"] == raw[:9] and "token" not in listed[0]

    # Revoke; the raw token stops working.
    assert client.delete(f"/api/tokens/{created['id']}").status_code == 200
    client.act_as(None)
    r = client.post(
        "/api/ingest/fleets/x/usage",
        json={"items": []},
        headers={"Authorization": f"Bearer {raw}"},
    )
    assert r.status_code == 401


def test_token_rejected_outside_ingest(client):
    client.act_as(A)
    raw = client.post("/api/tokens", json={"name": "t"}).json()["token"]
    client.act_as(None)
    r = client.get("/api/models", headers={"Authorization": f"Bearer {raw}"})
    assert r.status_code == 401  # tokens never grant read access


# ---- fleet usage ----------------------------------------------------------------

def test_ingest_fleet_usage_json_and_csv(client):
    client.act_as(A)
    model = _save_model(client)
    fleet = client.post("/api/fleet/fleets", json={"name": "Trucks", "model_id": model["id"]}).json()
    client.put(
        f"/api/fleet/fleets/{fleet['id']}/items",
        json={
            "settings": {"periods": 12, "period_label": "months", "default_rate": 100, "method": "single"},
            "items": [{"name": "Truck 01", "current_use": 100}, {"name": "Truck 02", "current_use": 200}],
            "expected_updated_at": fleet["updated_at"],
        },
    )
    raw = client.post("/api/tokens", json={"name": "cron"}).json()["token"]
    client.act_as(None)

    r = client.post(
        f"/api/ingest/fleets/{fleet['id']}/usage",
        json={"items": [{"name": "truck 01", "current_use": 900}]},
        headers={"Authorization": f"Bearer {raw}"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["updated_items"] == 1 and body["forecast"]["status"] == "ok"

    # CSV body updates both; unknown names are a clean 422 with nothing applied.
    csv = "name,current_use\nTruck 01,950\nTruck 02,400\n"
    r2 = client.post(
        f"/api/ingest/fleets/{fleet['id']}/usage",
        content=csv,
        headers={"Authorization": f"Bearer {raw}", "Content-Type": "text/csv"},
    )
    assert r2.status_code == 200 and r2.json()["updated_items"] == 2

    r3 = client.post(
        f"/api/ingest/fleets/{fleet['id']}/usage",
        json={"items": [{"name": "Truck 99", "current_use": 1}]},
        headers={"Authorization": f"Bearer {raw}"},
    )
    assert r3.status_code == 422 and "Truck 99" in r3.json()["detail"]

    client.act_as(A)
    items = client.get(f"/api/fleet/fleets/{fleet['id']}").json()["items"]
    assert {it["name"]: it["current_use"] for it in items} == {"Truck 01": 950, "Truck 02": 400}


def test_ingest_denies_other_users_fleet(client):
    client.act_as(A)
    model = _save_model(client)
    fleet = client.post("/api/fleet/fleets", json={"name": "F", "model_id": model["id"]}).json()
    client.act_as(B)
    raw = client.post("/api/tokens", json={"name": "b"}).json()["token"]
    client.act_as(None)
    r = client.post(
        f"/api/ingest/fleets/{fleet['id']}/usage",
        json={"items": [{"name": "x", "current_use": 1}]},
        headers={"Authorization": f"Bearer {raw}"},
    )
    assert r.status_code == 404


# ---- measurements ----------------------------------------------------------------

def _degradation_setup(client):
    """A degradation model + tracked fleet + one item with two readings."""
    rows = ["item,hours,wear"]
    rng = np.random.default_rng(5)
    for unit in range(1, 7):
        slope = 1.0 + 0.1 * rng.standard_normal()
        for t in (100, 200, 300, 400):
            rows.append(f"u{unit},{t},{max(0.1, slope * t / 40):.2f}")
    csv = io.BytesIO("\n".join(rows).encode())
    model = client.post(
        "/api/degradation/models",
        data={"name": "Wear", "i": "item", "x": "hours", "y": "wear",
              "path": "linear", "threshold": "12"},
        files={"file": ("wear.csv", csv, "text/csv")},
    )
    assert model.status_code == 200, model.text
    model_id = model.json()["id"]
    fleet = client.post("/api/fleet/tracked", json={"name": "Line 1", "model_id": model_id}).json()
    item = client.post(
        f"/api/degradation/models/{model_id}/items",
        json={"name": "Pump 7", "measurements": [{"t": 100, "y": 2.4}, {"t": 200, "y": 4.9}],
              "fleet_id": fleet["id"]},
    )
    assert item.status_code == 200, item.text
    return fleet["id"]


def test_ingest_measurements_appends_and_dedups(client):
    client.act_as(A)
    fleet_id = _degradation_setup(client)
    raw = client.post("/api/tokens", json={"name": "cron"}).json()["token"]
    client.act_as(None)

    r = client.post(
        f"/api/ingest/tracking/{fleet_id}/measurements",
        json={"measurements": [
            {"item": "Pump 7", "time": 300, "value": 7.6},
            {"item": "Pump 7", "time": 200, "value": 4.9},   # exact duplicate: skipped
        ]},
        headers={"Authorization": f"Bearer {raw}"},
    )
    assert r.status_code == 200, r.text
    report = r.json()["items"][0]
    assert report["added"] == 1
    assert report["health"] in {"healthy", "plan", "replace", "monitoring"}

    # Re-sending the same batch is a no-op (idempotent).
    r2 = client.post(
        f"/api/ingest/tracking/{fleet_id}/measurements",
        json={"measurements": [{"item": "Pump 7", "time": 300, "value": 7.6}]},
        headers={"Authorization": f"Bearer {raw}"},
    )
    assert r2.json()["items"][0]["added"] == 0

    # Time-travel that isn't a duplicate is a hard error.
    r3 = client.post(
        f"/api/ingest/tracking/{fleet_id}/measurements",
        json={"measurements": [{"item": "Pump 7", "time": 250, "value": 9.9}]},
        headers={"Authorization": f"Bearer {raw}"},
    )
    assert r3.status_code == 422


# ---- dataset lives -----------------------------------------------------------------

def test_ingest_dataset_lives_appends_and_refits(client):
    client.act_as(A)
    model = _save_model(client)
    dataset_id = model["dataset_id"]
    n_before = model["results"]["n"]
    raw = client.post("/api/tokens", json={"name": "cron"}).json()["token"]
    client.act_as(None)

    csv = _weibull_csv(n=40, seed=9).to_csv(index=False)
    r = client.post(
        f"/api/ingest/datasets/{dataset_id}/lives",
        content=csv,
        headers={"Authorization": f"Bearer {raw}", "Content-Type": "text/csv"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["appended"] == 40
    assert body["refit"][0]["status"] == "refit"
    assert body["refit"][0]["n"] == n_before + 40

    # The saved model itself was updated in place.
    client.act_as(A)
    updated = client.get(f"/api/models/{model['id']}").json()
    assert updated["results"]["n"] == n_before + 40

    # Unknown columns: clean 422, nothing applied.
    client.act_as(None)
    r2 = client.post(
        f"/api/ingest/datasets/{dataset_id}/lives",
        json={"rows": [{"nope": 1}]},
        headers={"Authorization": f"Bearer {raw}"},
    )
    assert r2.status_code == 422 and "Unknown column" in r2.json()["detail"]


def test_ingest_rate_limit(client, monkeypatch):
    from backend.routers import ingest as ingest_router

    monkeypatch.setattr(ingest_router, "_RATE_LIMIT", 3)
    client.act_as(A)
    raw = client.post("/api/tokens", json={"name": "t"}).json()["token"]
    client.act_as(None)
    headers = {"Authorization": f"Bearer {raw}"}
    codes = [
        client.post("/api/ingest/fleets/x/usage", json={"items": []}, headers=headers).status_code
        for _ in range(5)
    ]
    assert 429 in codes
