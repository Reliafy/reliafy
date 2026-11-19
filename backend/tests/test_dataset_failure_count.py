"""One dataset, one failure count (persona review 19 Nov, W8).

"Process pump P-101 flow trials" has a status column named ``failed``, all 0,
and no reading of its own: its model read it as 0 = failed (900 failures, as
the fit wizard says), but the Data list and the dataset's page guessed from the
name that 1 = failed and said "0 failed". The count now follows the newest
model's mapping when the dataset keeps no reading, on every screen.
"""
import mongomock
import pandas as pd
import pytest

N = 20


def _csv(ones=0):
    rows = [[f"P-{i:02d}", 100.0 + 13 * i, 40 + 10 * (i % 9), 1 if i < ones else 0] for i in range(N)]
    return pd.DataFrame(rows, columns=["unit", "hours", "flow_pct", "failed"]).to_csv(index=False).encode()


@pytest.fixture()
def client(monkeypatch):
    from fastapi.testclient import TestClient

    from backend import config, db
    from backend.auth import get_current_user
    from backend.main import app

    monkeypatch.setattr(config, "AUTH_DISABLED", False)
    monkeypatch.setattr(config, "BILLING_ENABLED", False)
    test_db = mongomock.MongoClient()["reliafy_failure_count"]
    monkeypatch.setattr(db, "_db", test_db)
    monkeypatch.setattr(db, "_simulated", True)
    app.dependency_overrides[get_current_user] = lambda: {"uid": "user-a", "email": "a@example.com", "name": "A"}
    try:
        tc = TestClient(app)
        tc.db = test_db
        yield tc
    finally:
        app.dependency_overrides.clear()


def _dataset_without_reading(client, ones=0):
    r = client.post("/api/datasets", files={"file": ("p101.csv", _csv(ones), "text/csv")})
    assert r.status_code == 200, r.text
    ds_id = r.json()["id"]
    # Saved before datasets kept a reading (as on tst): only its model says how it was read.
    client.db.datasets.update_one({"_id": ds_id}, {"$unset": {"reading": ""}})
    return ds_id


def _summaries(client, ds_id):
    listed = next(d for d in client.get("/api/datasets").json()["datasets"] if d["id"] == ds_id)
    page = client.get(f"/api/datasets/{ds_id}").json()
    return listed["summary"], page["summary"], page


def _fit(client, ds_id, **extra):
    r = client.post("/api/models", data={"dataset_id": ds_id, "x": "hours", "c": "failed", "unit": "hours",
                                         "name": "P-101 life", "distribution": "exponential", **extra})
    assert r.status_code == 200, r.text


def test_list_page_and_wizard_count_the_failures_the_way_the_model_read_them(client):
    ds_id = _dataset_without_reading(client)
    _fit(client, ds_id)  # 0 = failed: every row is a failure
    listed, page, detail = _summaries(client, ds_id)
    assert detail["reading_source"] == "last_model"
    assert detail["reading"]["c"] == "failed" and not detail["reading"]["c_invert"]
    assert listed == page == f"{N} units · {N} failed"


def test_a_model_that_inverted_the_column_counts_its_way_everywhere(client):
    ds_id = _dataset_without_reading(client, ones=5)
    _fit(client, ds_id)  # 0 = failed: 15 failures
    assert _summaries(client, ds_id)[:2] == (f"{N} units · 15 failed",) * 2
    _fit(client, ds_id, c_invert="true")  # the newest model says 1 = failed: 5
    listed, page, detail = _summaries(client, ds_id)
    assert detail["reading"]["c_invert"] is True
    assert listed == page == f"{N} units · 5 failed"


def test_with_no_model_the_guess_is_unchanged(client):
    ds_id = _dataset_without_reading(client)
    listed, page, _ = _summaries(client, ds_id)
    assert listed == page == f"{N} units · 0 failed"  # "failed" all 0 read by its name: none failed
