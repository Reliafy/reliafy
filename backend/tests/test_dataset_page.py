"""The dataset page's API: creating identical data says so, default names
drop the file extension, renaming, the per-column profile (distinct counts
and unit histories) and "Used by N models" across every model kind."""

import io

import mongomock
import pandas as pd
import pytest

from backend.services import datasets as ds_service
from backend.services import samples

A = "user-a"
USERS = {A: {"uid": A, "email": "a@x.com", "name": "A"}}
PUMP = "unit,hours,failed,site\nP01,1240,1,North\nP02,980,1,North\nP03,1500,0,South\nP04,2100,1,South\n"


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


def _upload(client, text=PUMP, filename="pump_test.csv", **form):
    return client.post("/api/datasets", files={"file": (filename, text.encode(), "text/csv")}, data=form)


def test_default_name_drops_the_extension(client):
    r = _upload(client)
    assert r.status_code == 200, r.text
    assert r.json()["name"] == "pump_test"
    assert "reused" not in r.json()
    assert ds_service.default_name("Fleet.XLSX") == "Fleet"
    assert ds_service.default_name("notes") == "notes"
    assert ds_service.default_name(None) == "dataset"


def test_identical_data_is_reported_as_reused(client):
    first = _upload(client, name="Pumps").json()
    again = _upload(client, name="Pumps again").json()
    assert again["id"] == first["id"] and again["reused"] is True
    assert again["name"] == "Pumps"  # the existing name stands; the app offers the new one
    pasted = client.post("/api/datasets/paste", json={"name": "Other", "content": PUMP}).json()
    assert pasted["id"] == first["id"] and pasted["reused"] is True


def test_rename(client):
    ds = _upload(client).json()
    r = client.patch(f"/api/datasets/{ds['id']}", json={"name": "  Pump test  "})
    assert r.status_code == 200, r.text
    assert r.json()["name"] == "Pump test"
    assert client.get(f"/api/datasets/{ds['id']}").json()["name"] == "Pump test"
    assert client.patch(f"/api/datasets/{ds['id']}", json={"name": " "}).status_code == 422
    assert client.patch("/api/datasets/nope", json={"name": "x"}).status_code == 404


def test_samples_cannot_be_renamed(client):
    samples.seed_samples(client.db)
    r = client.patch("/api/datasets/sample-ds-bearings", json={"name": "Mine now"})
    assert r.status_code == 403


def test_profile_counts_distinct_values(client):
    ds = _upload(client).json()
    body = client.get(f"/api/datasets/{ds['id']}").json()
    assert body["profile"]["distinct"] == {"unit": 4, "hours": 4, "failed": 2, "site": 2}
    assert body["profile"]["repeated_units"] is None


def _csv(raw: bytes) -> pd.DataFrame:
    return pd.read_csv(io.BytesIO(raw))


def test_unit_histories_are_recognised():
    # Repair history: events per compressor, times differ between units.
    assert ds_service.repeated_units(_csv(samples._COMPRESSOR_EVENTS_CSV)) == {
        "column": "compressor", "kind": "recurrent"}
    # Wear measured on a shared time grid.
    assert ds_service.repeated_units(_csv(samples._BRAKE_WEAR_CSV)) == {
        "column": "item", "kind": "degradation"}
    # One row per unit, and a site column sorted by time: plain life data.
    assert ds_service.repeated_units(_csv(samples._PUMP_CSV)) is None
    assert ds_service.repeated_units(_csv(PUMP.encode())) is None
    sorted_by_site = "site,hours\nNorth,100\nNorth,200\nSouth,150\nSouth,300\n"
    assert ds_service.repeated_units(_csv(sorted_by_site.encode())) is None


def test_used_by_counts_every_model_kind(client):
    samples.seed_samples(client.db)
    listed = {d["id"]: d for d in client.get("/api/datasets").json()["datasets"]}
    # The compressor history feeds a recurrent model, the brake wear a
    # degradation model: both count, not only life models.
    assert listed["sample-ds-compressor-events"]["n_models"] >= 1
    assert listed["sample-ds-brake-wear"]["n_models"] >= 1
    detail = client.get("/api/datasets/sample-ds-compressor-events").json()
    assert detail["n_models"] == listed["sample-ds-compressor-events"]["n_models"]
    assert any(o["collection"] == "recurrent_models" for o in detail["other_models"])
    assert detail["profile"]["repeated_units"]["kind"] == "recurrent"
