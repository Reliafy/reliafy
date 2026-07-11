"""Degradation models and tracked-item RUL predictions."""

import matplotlib

matplotlib.use("Agg")

import io
import json

import mongomock
import numpy as np
import pandas as pd
import pytest


@pytest.fixture()
def session(monkeypatch):
    from backend import db

    test_db = mongomock.MongoClient()["reliafy_test"]
    monkeypatch.setattr(db, "_db", test_db)
    monkeypatch.setattr(db, "_simulated", True)
    yield test_db


A = "user-a"
B = "user-b"


def _deg_df(n_units: int = 6) -> pd.DataFrame:
    rng = np.random.default_rng(0)
    rows = []
    for u in range(n_units):
        slope = 0.02 + 0.004 * u
        for t in np.arange(1, 9) * 50.0:
            rows.append({"item": f"item-{u}", "hours": t, "wear": 1.0 + slope * t + rng.normal(0, 0.05)})
    return pd.DataFrame(rows)


def _deg_csv(n_units: int = 6) -> bytes:
    buf = io.StringIO()
    _deg_df(n_units).to_csv(buf, index=False)
    return buf.getvalue().encode()


MAPPING = {"i": "item", "x": "hours", "y": "wear"}


# ---- Fit wrapper ------------------------------------------------------------

def test_fit_payload_shape_and_json_safety():
    from backend import degradation

    payload, cache_id = degradation.fit(_deg_df(), MAPPING, 8.0, path="best", unit="hours", measurement_unit="mm")
    json.dumps(payload, allow_nan=False)  # raises if any NaN/inf leaked

    assert payload["n_units"] == 6
    assert payload["threshold"] == 8.0
    assert payload["path_model"]["id"] in degradation.PATH_MODELS
    assert payload["path_selection"][0]["aicc"] <= payload["path_selection"][-1]["aicc"]
    for u in payload["units"]:
        assert len(u["scatter"]["x"]) == 8
        assert len(u["line"]["x"]) == len(u["line"]["y"]) == 100
        assert u["pseudo_failure_time"] is None or u["pseudo_failure_time"] > 0
    assert payload["life_model"]["distribution_id"] == "weibull"
    assert degradation.get_live(cache_id) is not None


def test_fit_errors():
    from backend import degradation
    from backend.fitting import FitError

    with pytest.raises(FitError):  # one unit only
        degradation.fit(_deg_df(1), MAPPING, 8.0)
    with pytest.raises(FitError):  # bad mapping
        degradation.fit(_deg_df(), {"i": "item", "x": "hours", "y": "nope"}, 8.0)
    with pytest.raises(FitError):  # same column twice
        degradation.fit(_deg_df(), {"i": "item", "x": "hours", "y": "hours"}, 8.0)
    with pytest.raises(FitError):  # bad threshold
        degradation.fit(_deg_df(), MAPPING, float("nan"))


def test_predict_item_shapes_and_flat_case():
    from backend import degradation

    _, cache_id = degradation.fit(_deg_df(), MAPPING, 8.0, path="linear")
    live = degradation.get_live(cache_id)

    pred = degradation.predict_item(live, [50.0, 100.0, 150.0], [2.0, 3.1, 4.2])
    json.dumps(pred, allow_nan=False)
    assert pred["method"] == "bayesian"
    lo, hi = pred["failure_time_interval"]
    assert lo <= pred["failure_time"] <= hi
    assert 0.0 <= pred["prob_failed"] <= 1.0
    assert pred["projection"] and len(pred["projection"]["x"]) > 0

    # Flat (non-degrading) measurements: JSON-safe, carries never-fails signal.
    flat = degradation.predict_item(live, [50.0, 100.0, 150.0], [1.0, 1.0, 1.0])
    json.dumps(flat, allow_nan=False)
    assert flat["method"] in ("bayesian", "point")
    if flat["method"] == "bayesian":
        assert flat["prob_never_fails"] > 0


# ---- Service round trip -----------------------------------------------------

def test_save_refit_and_track(session):
    from backend.services import datasets as ds
    from backend.services import degradation as svc

    dataset = ds.create_dataset(session, "wear.csv", _deg_csv(), A)
    spec = {"mapping": MAPPING, "threshold": 8.0, "path": "linear",
            "distribution_id": "weibull", "population_method": "moments",
            "unit": "hours", "measurement_unit": "mm"}
    doc = svc.save_model(session, "Wear model", dataset, spec, A)
    assert doc.results["n_units"] == 6

    # Clear the live cache: creating an item must transparently re-fit.
    svc._LIVE.clear()
    item = svc.create_item(session, doc.id, "asset-1", [{"t": 50, "y": 2.0}, {"t": 100, "y": 3.1}, {"t": 150, "y": 4.2}], A)
    assert item.prediction["method"] in ("bayesian", "point")
    assert item.prediction["n_measurements"] == 3

    # Append advances the prediction; non-monotonic time is rejected.
    before = item.prediction["predicted_at"]
    item = svc.append_measurement(session, doc.id, item.id, 200.0, 5.2, A)
    assert item.prediction["n_measurements"] == 4
    assert item.prediction["predicted_at"] >= before
    from backend.fitting import FitError
    with pytest.raises(FitError):
        svc.append_measurement(session, doc.id, item.id, 100.0, 9.9, A)

    # Owner isolation.
    assert svc.get_model(session, doc.id, B) is None
    assert svc.get_item(session, doc.id, item.id, B) is None
    with pytest.raises(svc.ModelNotFound):
        svc.rename_model(session, doc.id, "hijack", B)

    # Delete cascades tracked items.
    svc.delete_model(session, doc.id, A)
    assert session.tracked_items.count_documents({}) == 0


# ---- API + caps ---------------------------------------------------------------

def _client(monkeypatch, test_db):
    from fastapi.testclient import TestClient

    from backend import config, db
    from backend.main import app

    monkeypatch.setattr(config, "AUTH_DISABLED", False)
    monkeypatch.setattr(db, "_db", test_db)
    monkeypatch.setattr(db, "_simulated", True)
    return TestClient(app), app


def test_api_flow_and_caps(monkeypatch):
    from backend import config
    from backend.auth import get_current_user

    test_db = mongomock.MongoClient()["reliafy_test"]
    client, app = _client(monkeypatch, test_db)
    monkeypatch.setattr(config, "BILLING_ENABLED", True)
    monkeypatch.setattr(config, "FREE_MAX_DEGRADATION_MODELS", 1)
    monkeypatch.setattr(config, "FREE_MAX_TRACKED_ITEMS", 3)

    form = {"name": "Wear", "i": "item", "x": "hours", "y": "wear",
            "threshold": "8.0", "path": "linear"}
    try:
        app.dependency_overrides[get_current_user] = lambda: {"uid": A, "email": "a@x.com", "name": "A"}

        # Preview fit.
        r = client.post("/api/degradation/fit", data={k: v for k, v in form.items() if k != "name"},
                        files={"file": ("wear.csv", _deg_csv(), "text/csv")})
        assert r.status_code == 200, r.text
        assert r.json()["results"]["n_units"] == 6

        # Save (1st: ok, 2nd: capped).
        r = client.post("/api/degradation/models", data=form,
                        files={"file": ("wear.csv", _deg_csv(), "text/csv")})
        assert r.status_code == 200, r.text
        model_id = r.json()["id"]
        r2 = client.post("/api/degradation/models", data={**form, "name": "Wear 2"},
                         files={"file": ("wear2.csv", _deg_csv(5), "text/csv")})
        assert r2.status_code == 402 and r2.json()["code"] == "cap"

        # Items: 3 ok, 4th capped.
        for n in range(3):
            r = client.post(f"/api/degradation/models/{model_id}/items",
                            json={"name": f"asset-{n}", "measurements": [{"t": 50, "y": 2.0}, {"t": 100, "y": 3.0}]})
            assert r.status_code == 200, r.text
            assert r.json()["prediction"]["method"] in ("bayesian", "point")
        r = client.post(f"/api/degradation/models/{model_id}/items",
                        json={"name": "asset-3", "measurements": [{"t": 50, "y": 2.0}]})
        assert r.status_code == 402 and r.json()["code"] == "cap"

        # Admin bypasses both caps.
        monkeypatch.setattr(config, "ADMIN_EMAILS", {"a@x.com"})
        r = client.post(f"/api/degradation/models/{model_id}/items",
                        json={"name": "asset-admin", "measurements": [{"t": 50, "y": 2.0}]})
        assert r.status_code == 200

        # Detail includes items; measurement append updates prediction.
        detail = client.get(f"/api/degradation/models/{model_id}").json()
        assert len(detail["items"]) == 4
        item_id = detail["items"][-1]["id"]
        r = client.post(f"/api/degradation/models/{model_id}/items/{item_id}/measurements",
                        json={"t": 150.0, "y": 4.1})
        assert r.status_code == 200 and r.json()["n_measurements"] == 3

        # usage_summary carries the new keys.
        monkeypatch.setattr(config, "ADMIN_EMAILS", set())
        bill = client.get("/api/billing").json()
        assert bill["caps"]["degradation_models"] == 1
        assert bill["usage"]["tracked_items"] == 4

        # Other user sees nothing.
        app.dependency_overrides[get_current_user] = lambda: {"uid": B, "email": "b@x.com", "name": "B"}
        assert client.get(f"/api/degradation/models/{model_id}").status_code == 404
        assert client.get("/api/degradation/models").json()["models"] == []
    finally:
        app.dependency_overrides.clear()


# ---- Samples ------------------------------------------------------------------

def test_degradation_samples_seed_and_are_read_only(session, monkeypatch):
    from backend.auth import get_current_user
    from backend.services import samples

    samples.seed_samples(session)
    samples.seed_samples(session)  # idempotent

    assert session.degradation_models.count_documents({}) == len(samples.SAMPLE_DEGRADATION_MODELS)
    assert session.tracked_items.count_documents({}) == len(samples.SAMPLE_TRACKED_ITEMS)
    item = session.tracked_items.find_one({"_id": "sample-item-truck-07"})
    assert item["prediction"]["method"] in ("bayesian", "point")

    from backend import config
    from backend.main import app
    from fastapi.testclient import TestClient
    monkeypatch.setattr(config, "AUTH_DISABLED", False)
    client = TestClient(app)
    try:
        app.dependency_overrides[get_current_user] = lambda: {"uid": A, "email": "a@x.com", "name": "A"}
        models = client.get("/api/degradation/models").json()["models"]
        assert any(m["id"] == "sample-deg-brake-wear" and m["is_sample"] for m in models)

        detail = client.get("/api/degradation/models/sample-deg-brake-wear").json()
        assert len(detail["items"]) == 2

        # Sample items are read-only; users can register their own on the model.
        r = client.post("/api/degradation/models/sample-deg-brake-wear/items/sample-item-truck-07/measurements",
                        json={"t": 3000.0, "y": 5.0})
        assert r.status_code == 403
        r = client.post("/api/degradation/models/sample-deg-brake-wear/items",
                        json={"name": "my pad", "measurements": [{"t": 500, "y": 1.0}, {"t": 1500, "y": 2.2}]})
        assert r.status_code == 200
        assert r.json()["prediction"]["method"] in ("bayesian", "point")

        # "Deleting" the sample model hides it for this user only.
        assert client.delete("/api/degradation/models/sample-deg-brake-wear").json()["ok"] is True
        assert client.get("/api/degradation/models/sample-deg-brake-wear").status_code == 404
        app.dependency_overrides[get_current_user] = lambda: {"uid": B, "email": "b@x.com", "name": "B"}
        assert client.get("/api/degradation/models/sample-deg-brake-wear").status_code == 200
    finally:
        app.dependency_overrides.clear()
