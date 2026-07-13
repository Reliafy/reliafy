"""Create a dataset from pasted tabular text (CSV / TSV) — form + agent path."""

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


def test_paste_csv(client):
    r = client.post("/api/datasets/paste", json={"name": "Bearings", "content": "hours,failed\n1240,1\n980,1\n1500,0"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["name"] == "Bearings" and body["n_rows"] == 3
    assert [c["name"] for c in body["columns"]] == ["hours", "failed"]


def test_paste_tsv_from_spreadsheet(client):
    r = client.post("/api/datasets/paste", json={"name": "Excel", "content": "hours\tfailed\n1240\t1\n980\t0"})
    assert r.status_code == 200, r.text
    assert r.json()["n_rows"] == 2
    assert [c["name"] for c in r.json()["columns"]] == ["hours", "failed"]


def test_paste_validation(client):
    assert client.post("/api/datasets/paste", json={"name": "x", "content": ""}).status_code == 422
    # A single column (no delimiter) is rejected with a helpful message.
    r = client.post("/api/datasets/paste", json={"name": "x", "content": "hours\n100\n200"})
    assert r.status_code == 422 and "column" in r.json()["detail"].lower()


def test_paste_dedupes_by_content(client):
    payload = {"name": "One", "content": "a,b\n1,2\n3,4"}
    first = client.post("/api/datasets/paste", json=payload).json()
    again = client.post("/api/datasets/paste", json={"name": "Two", "content": "a,b\n1,2\n3,4"}).json()
    assert first["id"] == again["id"]  # identical data reuses the dataset
