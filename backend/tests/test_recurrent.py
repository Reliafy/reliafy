"""Recurrent-event (repairable-system) models — fit + persistence API."""

import io
import json

import mongomock
import pandas as pd
import pytest

A = "user-a"


def _events_csv() -> bytes:
    rows = []
    for sys_id, times in {"A": [100, 180, 240, 280], "B": [120, 210, 270],
                          "C": [90, 160, 220, 260, 290]}.items():
        for t in times:
            rows.append({"system": sys_id, "time": t, "obs_end": 300})
    buf = io.StringIO()
    pd.DataFrame(rows).to_csv(buf, index=False)
    return buf.getvalue().encode()


def test_fit_payload_shape_and_json_safety():
    from backend import recurrent as rec

    df = pd.read_csv(io.BytesIO(_events_csv()))
    payload, cache_id = rec.fit(df, {"i": "system", "x": "time", "t": "obs_end"}, "crow_amsaa", "hours")
    json.dumps(payload, allow_nan=False)  # no NaN/inf leaks

    assert payload["kind"] == "recurrent"
    assert payload["n_systems"] == 3
    assert payload["n_events"] == 12
    assert payload["model"]["id"] == "crow_amsaa"
    assert payload["beta"] > 1  # this fleet is deteriorating
    assert payload["growth"] == "deteriorating"
    assert payload["mtbf"] and payload["mtbf"] > 0
    assert len(payload["mcf"]["observed"]["x"]) == payload["n_events"]
    assert payload["mcf"]["observed"]["upper"] is not None  # confidence band
    assert len(payload["mcf"]["fitted"]["x"]) == 200
    assert payload["trend"]["trend"] in ("increasing", "decreasing", "no trend", None)
    assert rec.get_live(cache_id) is not None
    # Prediction grows with the horizon.
    assert rec.predict(rec.get_live(cache_id), 400)["expected_events"] > \
        rec.predict(rec.get_live(cache_id), 300)["expected_events"]


def test_fit_errors():
    from backend import recurrent as rec
    from backend.fitting import FitError

    df = pd.read_csv(io.BytesIO(_events_csv()))
    with pytest.raises(FitError):  # unknown model
        rec.fit(df, {"i": "system", "x": "time"}, "nope")
    with pytest.raises(FitError):  # bad mapping
        rec.fit(df, {"i": "system", "x": "missing"}, "crow_amsaa")


def _client(monkeypatch, test_db):
    from fastapi.testclient import TestClient

    from backend import config, db
    from backend.main import app

    monkeypatch.setattr(config, "AUTH_DISABLED", False)
    monkeypatch.setattr(db, "_db", test_db)
    monkeypatch.setattr(db, "_simulated", True)
    return TestClient(app), app


def test_api_fit_save_get_predict_delete(monkeypatch):
    from backend.auth import get_current_user

    test_db = mongomock.MongoClient()["reliafy_test"]
    client, app = _client(monkeypatch, test_db)
    form = {"i": "system", "x": "time", "t": "obs_end", "model": "crow_amsaa", "unit": "hours"}
    try:
        app.dependency_overrides[get_current_user] = lambda: {"uid": A, "email": "a@x.com", "name": "A"}

        # Preview fit.
        r = client.post("/api/recurrent/fit", data=form,
                        files={"file": ("events.csv", _events_csv(), "text/csv")})
        assert r.status_code == 200, r.text
        assert r.json()["results"]["growth"] == "deteriorating"

        # Save, then read back.
        r = client.post("/api/recurrent/models", data={**form, "name": "Fleet X"},
                        files={"file": ("events.csv", _events_csv(), "text/csv")})
        assert r.status_code == 200, r.text
        model_id = r.json()["id"]
        assert r.json()["name"] == "Fleet X" and r.json()["n_systems"] == 3

        assert len(client.get("/api/recurrent/models").json()["models"]) == 1
        detail = client.get(f"/api/recurrent/models/{model_id}").json()
        assert detail["results"]["model"]["id"] == "crow_amsaa"

        # Predict (refits on demand).
        pred = client.post(f"/api/recurrent/models/{model_id}/predict", json={"horizon": 400})
        assert pred.status_code == 200 and pred.json()["expected_events"] > 0

        # Delete.
        assert client.delete(f"/api/recurrent/models/{model_id}").json()["ok"] is True
        assert client.get(f"/api/recurrent/models/{model_id}").status_code == 404
    finally:
        app.dependency_overrides.clear()
