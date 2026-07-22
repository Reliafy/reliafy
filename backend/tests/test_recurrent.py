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


def test_build_inputs_full_surface_and_legacy_alias():
    from backend import recurrent as rec

    rows = []
    for sys_id, times in {"A": [100, 240], "B": [120, 270]}.items():
        for t in times:
            rows.append({"system": sys_id, "time": t, "qty": 1, "start": 0, "obs_end": 300})
    df = pd.DataFrame(rows)

    # Full modifier surface: c/n/tl/tr all extracted alongside i/x.
    ins = rec.build_inputs(df, {"i": "system", "x": "time", "n": "qty", "tl": "start", "tr": "obs_end"})
    assert set(ins) == {"i", "x", "n", "tl", "tr"}
    assert ins["x"].tolist() == [100, 240, 120, 270]
    assert ins["n"].tolist() == [1, 1, 1, 1]

    # Legacy 't' is accepted as an alias for the observation window (tr).
    legacy = rec.build_inputs(df, {"i": "system", "x": "time", "t": "obs_end"})
    assert "tr" in legacy and "t" not in legacy

    # A recurrent fit works with the extended mapping (counts + window).
    payload, _ = rec.fit(df, {"i": "system", "x": "time", "n": "qty", "tr": "obs_end"}, "crow_amsaa")
    assert payload["n_systems"] == 2 and payload["n_events"] == 4


def test_fit_errors():
    from backend import recurrent as rec
    from backend.fitting import FitError

    df = pd.read_csv(io.BytesIO(_events_csv()))
    with pytest.raises(FitError):  # unknown model
        rec.fit(df, {"i": "system", "x": "time"}, "nope")
    with pytest.raises(FitError):  # bad mapping
        rec.fit(df, {"i": "system", "x": "missing"}, "crow_amsaa")


def test_sample_seeds_and_is_read_only(monkeypatch):
    from backend import config
    from backend.services import samples

    monkeypatch.setattr(config, "SEED_SAMPLES", True)
    db = mongomock.MongoClient()["reliafy_test"]
    samples.seed_samples(db)

    doc = db.recurrent_models.find_one({"_id": "sample-rec-compressors"})
    assert doc is not None
    assert doc["owner_id"] == config.SAMPLE_OWNER  # shared sample owner
    r = doc["results"]
    assert r["n_systems"] == 4 and r["growth"] == "deteriorating" and r["beta"] > 1

    # Re-seeding is idempotent.
    samples.seed_samples(db)
    assert db.recurrent_models.count_documents({}) == 1

    # It surfaces to a normal user's list (read-only sample).
    from backend.services import recurrent as svc

    models = svc.list_models(db, ["someone", config.SAMPLE_OWNER])
    assert [m.id for m in models] == ["sample-rec-compressors"]


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


def test_api_from_params_save_and_predict(monkeypatch):
    from backend.auth import get_current_user

    test_db = mongomock.MongoClient()["reliafy_test"]
    client, app = _client(monkeypatch, test_db)
    try:
        app.dependency_overrides[get_current_user] = lambda: {"uid": A, "email": "a@x.com", "name": "A"}

        # Build a simple model straight from parameters — no dataset.
        r = client.post("/api/recurrent/from-params", data={
            "name": "Growth target", "model": "crow_amsaa",
            "alpha": 1200, "beta": 1.3, "horizon": 5000, "unit": "hours"})
        assert r.status_code == 200, r.text
        body = r.json()
        res = body["results"]
        assert res["from_params"] is True and res["beta"] == 1.3 and res["growth"] == "deteriorating"
        assert res["mcf"]["observed"] is None and len(res["mcf"]["fitted"]["x"]) == 200
        assert res["n_systems"] is None and body["dataset_id"] == ""

        # Reads back and predicts (refits via the params-only path).
        mid = body["id"]
        assert client.get(f"/api/recurrent/models/{mid}").json()["results"]["from_params"] is True
        pred = client.post(f"/api/recurrent/models/{mid}/predict", json={"horizon": 3000})
        assert pred.status_code == 200 and pred.json()["expected_events"] > 0

        # Bad inputs -> 422 (not a crash).
        assert client.post("/api/recurrent/from-params", data={
            "name": "x", "model": "crow_amsaa", "alpha": 1200, "beta": 1.3, "horizon": 0}).status_code == 422
    finally:
        app.dependency_overrides.clear()


def test_api_fit_and_save_from_saved_dataset(monkeypatch):
    from backend.auth import get_current_user

    test_db = mongomock.MongoClient()["reliafy_test"]
    client, app = _client(monkeypatch, test_db)
    try:
        app.dependency_overrides[get_current_user] = lambda: {"uid": A, "email": "a@x.com", "name": "A"}

        # Upload a dataset once, then drive the recurrent flow off its id (no file).
        ds = client.post("/api/datasets", files={"file": ("ev.csv", _events_csv(), "text/csv")},
                         data={"name": "Events"})
        assert ds.status_code == 200, ds.text
        dataset_id = ds.json()["id"]
        form = {"dataset_id": dataset_id, "i": "system", "x": "time", "t": "obs_end",
                "model": "crow_amsaa", "unit": "hours"}

        r = client.post("/api/recurrent/fit", data=form)
        assert r.status_code == 200, r.text
        assert r.json()["dataset_id"] == dataset_id  # reused, not re-uploaded

        r = client.post("/api/recurrent/models", data={**form, "name": "From saved dataset"})
        assert r.status_code == 200, r.text
        assert r.json()["dataset_id"] == dataset_id
    finally:
        app.dependency_overrides.clear()
