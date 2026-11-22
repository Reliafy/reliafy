"""A replacement log with no item column, read as one stream of events (one
fleet's replacements against fleet hours): said on purpose in the reading
(``one_stream``), it tags the dataset Repairable with one stream and fits as
one system; a date column is never guessed as the item."""

import mongomock
import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient

U = "user-stream"


def _log() -> str:
    rng = np.random.default_rng(5)
    hours = np.sort(rng.uniform(0, 216000, 30)).round()
    days = pd.Timestamp("2023-12-01") + pd.to_timedelta(hours / 72000 * 365.25, unit="D")
    sets = rng.choice([f"GS-{k:02d}" for k in range(1, 13)], 30)
    df = pd.DataFrame({"replacement": range(1, 31), "date": days.strftime("%Y-%m-%d"),
                       "fleet_hours": hours.astype(int), "genset": sets, "reason": "failed in service"})
    return df.to_csv(index=False)


@pytest.fixture()
def web(monkeypatch):
    from backend import config, db
    from backend.auth import get_current_user
    from backend.main import app

    monkeypatch.setattr(config, "AUTH_DISABLED", False)
    monkeypatch.setattr(config, "BILLING_ENABLED", False)
    test_db = mongomock.MongoClient()["reliafy_stream_test"]
    monkeypatch.setattr(db, "_db", test_db)
    monkeypatch.setattr(db, "_simulated", True)
    app.dependency_overrides[get_current_user] = lambda: {
        "uid": U, "email": "s@example.org", "name": "S", "email_verified": True}
    try:
        yield TestClient(app), test_db
    finally:
        app.dependency_overrides.clear()


def test_a_date_is_never_guessed_as_the_item():
    from backend.services import dataset_reading as dr

    r = dr.guess_for_bytes(_log().encode())
    assert r["x"] == "fleet_hours" and r["i"] == "" and "date" in r["not_used"]
    assert r["one_stream"] is False


def test_one_stream_needs_no_item_column_and_tags_repairable(web):
    client, _ = web
    reading = {"x": "fleet_hours", "all_failed": True, "unit": "Hours", "not_used": ["date", "reason"],
               "z": [], "one_stream": True}
    res = client.post("/api/datasets/paste", json={"name": "Lift pumps", "content": _log(), "reading": reading})
    assert res.status_code == 200, res.text
    d = res.json()
    assert d["reading"]["one_stream"] is True
    assert "Repairable" in d["tags"] and "Non-repairable" not in d["tags"]
    assert d["summary"] == "1 stream · 30 failures"
    # Picking an item column drops it.
    res = client.put(f"/api/datasets/{d['id']}/reading", json={"reading": {**reading, "i": "genset"}})
    assert res.status_code == 200 and res.json()["reading"]["one_stream"] is False
    # Without it, each row is its own unit, as before.
    res = client.put(f"/api/datasets/{d['id']}/reading", json={"reading": {**reading, "one_stream": False}})
    assert "Non-repairable" in res.json()["tags"]


def test_one_stream_fits_as_one_system(web):
    client, _ = web
    reading = {"x": "fleet_hours", "all_failed": True, "unit": "Hours", "one_stream": True}
    d = client.post("/api/datasets/paste", json={"name": "Lift pumps", "content": _log(), "reading": reading}).json()
    form = {"dataset_id": d["id"], "i": "", "one_stream": "true", "x": "fleet_hours", "unit": "hours",
            "record_end": "216000", "model": "crow_amsaa"}
    res = client.post("/api/recurrent/fit", data=form)
    assert res.status_code == 200, res.text
    out = res.json()["results"]
    assert out["n_systems"] == 1 and out["n_events"] == 30 and out["end_of_observation"] == 216000
    # No item column and no one_stream: it says what to give.
    bad = client.post("/api/recurrent/fit", data={**form, "one_stream": ""})
    assert bad.status_code == 422 and "one stream" in bad.json()["detail"]
