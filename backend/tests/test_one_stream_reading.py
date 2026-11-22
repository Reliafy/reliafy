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


# ---- The dataset's own end of record ------------------------------------------

_SUP_J17 = "/Users/derrynknife/Projects/reliafy/planning/testing/data/sup-j17-lift-pump-replacements.csv"


def _fit_form(dataset_id, **extra):
    return {"dataset_id": dataset_id, "i": "", "one_stream": "true", "x": "fleet_hours", "unit": "hours",
            "model": "crow_amsaa", **extra}


def _upload(client, content, **reading):
    base = {"x": "fleet_hours", "all_failed": True, "unit": "Hours", "one_stream": True, **reading}
    res = client.post("/api/datasets/paste", json={"name": "Lift pumps", "content": content, "reading": base})
    assert res.status_code == 200, res.text
    return res.json()


def test_the_reading_keeps_and_checks_the_end_of_record(web):
    client, _ = web
    d = _upload(client, _log(), record_end=216000)
    assert d["reading"]["record_end"] == 216000
    assert "record ends at 216000" in d["reading_summary"]
    res = client.put(f"/api/datasets/{d['id']}/reading", json={"reading": {**d["reading"], "record_end": "abc"}})
    assert res.status_code == 422 and "end of the record" in res.json()["detail"]
    cleared = client.put(f"/api/datasets/{d['id']}/reading", json={"reading": {**d["reading"], "record_end": ""}})
    assert cleared.status_code == 200 and cleared.json()["reading"]["record_end"] is None


def test_a_fit_with_no_end_given_uses_the_datasets_end(web):
    client, _ = web
    d = _upload(client, _log(), record_end=216000)
    out = client.post("/api/recurrent/fit", data=_fit_form(d["id"])).json()["results"]
    assert out["end_of_observation"] == 216000
    typed = client.post("/api/recurrent/fit", data=_fit_form(d["id"], record_end="216000")).json()["results"]
    assert out["beta"] == pytest.approx(typed["beta"])
    # A typed end overrides it; with none on the dataset, the last failure ends the record.
    over = client.post("/api/recurrent/fit", data=_fit_form(d["id"], record_end="250000")).json()["results"]
    assert over["end_of_observation"] == 250000
    plain = _upload(client, _log() + " ")
    assert plain["id"] != d["id"]
    last = client.post("/api/recurrent/fit", data=_fit_form(plain["id"])).json()["results"]
    assert last["end_of_observation"] < 216000 and last["beta"] != pytest.approx(out["beta"])
    # A saved model keeps the end it was fitted to.
    saved = client.post("/api/recurrent/models", data={**_fit_form(d["id"]), "name": "Fleet trend"})
    assert saved.status_code == 200, saved.text
    assert saved.json()["results"]["end_of_observation"] == 216000


@pytest.mark.skipif(not __import__("os").path.exists(_SUP_J17), reason="planning test data not checked out")
def test_the_sup_j17_log_fits_to_its_datasets_end(web):
    client, _ = web
    with open(_SUP_J17) as f:
        content = f.read()
    d = _upload(client, content, record_end=216000, not_used=["date", "genset", "part", "reason", "replacement"])
    out = client.post("/api/recurrent/fit", data=_fit_form(d["id"])).json()["results"]
    assert out["end_of_observation"] == 216000
    assert out["beta"] == pytest.approx(0.588, abs=0.0006)
