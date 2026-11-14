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


def test_fit_payload_carries_residuals_and_path_parameter_names():
    """Each reading's residual about its item's fitted path (the model page's
    scatter check) and the path's parameter names (its Data tab)."""
    from backend import degradation

    payload, cache_id = degradation.fit(_deg_df(), MAPPING, 8.0, path="linear", unit="hours")
    live = degradation.get_live(cache_id)
    assert payload["path_model"]["param_names"] == ["a", "b"]
    assert len(payload["path_param_mean"]) == len(payload["path_model"]["param_names"])
    for u in payload["units"]:
        x = np.asarray(u["scatter"]["x"])
        y = np.asarray(u["scatter"]["y"])
        r = np.asarray(u["residuals"], dtype=float)
        assert r.shape == y.shape
        np.testing.assert_allclose(r, y - live.path(x, u["id"]), atol=1e-9)
        # A least-squares line: each item's residuals sum to zero.
        assert abs(r.sum()) < 1e-8
    # The pooled scatter about the paths is the fit's measurement variance.
    allr = np.concatenate([u["residuals"] for u in payload["units"]])
    dof = len(allr) - 2 * payload["n_units"]
    assert payload["measurement_var"] == pytest.approx(float(allr @ allr) / dof, rel=1e-6)


def test_reliability_curves_shape_and_bounds():
    from backend import degradation

    _, cache_id = degradation.fit(_deg_df(), MAPPING, 8.0, path="linear")
    live = degradation.get_live(cache_id)

    curves = degradation.reliability_curves(live, alpha_ci=0.10)
    assert curves is not None
    json.dumps(curves, allow_nan=False)  # JSON-safe (no NaN/inf)
    assert curves["alpha_ci"] == 0.10
    assert len(curves["x"]) == len(curves["sf"]) == 200
    # sf is a survival curve: monotone non-increasing, within [0, 1].
    sf = [v for v in curves["sf"] if v is not None]
    assert all(0.0 <= v <= 1.0001 for v in sf)
    assert sf == sorted(sf, reverse=True)
    # Two-stage band brackets the point curve where all three are present.
    if "lower" in curves and "upper" in curves:
        for lo, s, hi in zip(curves["lower"], curves["sf"], curves["upper"]):
            if None in (lo, s, hi):
                continue
            assert lo <= s + 1e-9 and s <= hi + 1e-9


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
        app.dependency_overrides[get_current_user] = lambda: {"uid": A, "email": "a@x.com", "name": "A", "email_verified": True}

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

        # Reliability endpoint: refits on demand, honours the confidence level.
        rc = client.get(f"/api/degradation/models/{model_id}/reliability?confidence=0.80")
        assert rc.status_code == 200, rc.text
        curves = rc.json()
        assert curves["alpha_ci"] == pytest.approx(0.20)
        assert len(curves["x"]) == len(curves["sf"]) == 200
        assert client.get(
            f"/api/degradation/models/{model_id}/reliability?confidence=1.5"
        ).status_code == 422
        assert client.get(
            "/api/degradation/models/does-not-exist/reliability"
        ).status_code == 404

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
        app.dependency_overrides[get_current_user] = lambda: {"uid": B, "email": "b@x.com", "name": "B", "email_verified": True}
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
    doc = session.degradation_models.find_one({"_id": "sample-deg-brake-wear"})
    assert all("residuals" in u for u in doc["results"]["units"])
    # An older seed (no residuals) is refitted once to gain them.
    session.degradation_models.update_one(
        {"_id": "sample-deg-brake-wear"},
        {"$unset": {f"results.units.{k}.residuals": "" for k in range(len(doc["results"]["units"]))}},
    )
    samples.seed_samples(session)
    doc = session.degradation_models.find_one({"_id": "sample-deg-brake-wear"})
    assert all("residuals" in u for u in doc["results"]["units"])
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
        app.dependency_overrides[get_current_user] = lambda: {"uid": A, "email": "a@x.com", "name": "A", "email_verified": True}
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
        app.dependency_overrides[get_current_user] = lambda: {"uid": B, "email": "b@x.com", "name": "B", "email_verified": True}
        assert client.get("/api/degradation/models/sample-deg-brake-wear").status_code == 200
    finally:
        app.dependency_overrides.clear()


# ---- Wizard: distinct item ids over every row ------------------------------------

def test_preview_counts_distinct_values_over_every_row():
    """The sample shows only the first item; ``n_unique`` counts all six."""
    from backend.fitting import preview

    p = preview(_deg_csv(), rows=5, distinct=True)
    assert {row[0] for row in p["preview"]} == {"item-0"}
    assert p["n_unique"][p["columns"].index("item")] == 6
    assert p["n_unique"][p["columns"].index("hours")] == 8
    # Opt-in: other callers (the MCP tools, the agent) keep the old shape.
    assert "n_unique" not in preview(_deg_csv(), rows=5)


def test_columns_and_dataset_detail_carry_distinct_counts(monkeypatch):
    from backend.auth import get_current_user

    test_db = mongomock.MongoClient()["reliafy_test"]
    client, app = _client(monkeypatch, test_db)
    try:
        app.dependency_overrides[get_current_user] = lambda: {"uid": A, "email": "a@x.com", "name": "A", "email_verified": True}
        r = client.post("/api/columns", files={"file": ("wear.csv", _deg_csv(4), "text/csv")})
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["n_unique"][body["columns"].index("item")] == 4

        r = client.post("/api/datasets", files={"file": ("wear.csv", _deg_csv(3), "text/csv")})
        assert r.status_code == 200, r.text
        detail = client.get(f"/api/datasets/{r.json()['id']}").json()
        assert detail["n_unique"][detail["preview_columns"].index("item")] == 3
    finally:
        app.dependency_overrides.clear()


# ---- A lognormal life's band in its far left tail --------------------------------

def _pad_wear(seed: int = 2) -> pd.DataFrame:
    """Brake pads worn linearly from 12 mm, each at a lognormal rate (median
    9 mm per 50,000 km, sigma 0.25), read every 5,000 km with 0.15 mm noise
    until under 3 mm. Seed 2's lognormal fit has rounding noise in the raw
    band where the reliability is within 1e-13 of 1."""
    rng = np.random.default_rng(seed)
    rows = []
    for u in range(15):
        rate = 9.0 / 50000 * np.exp(rng.normal(0, 0.25))
        for km in range(0, 200001, 5000):
            y = 12 - rate * km + rng.normal(0, 0.15)
            rows.append({"pad": f"P{u}", "km": km, "mm": round(y, 2)})
            if y < 3:
                break
    return pd.DataFrame(rows)


def _time_at(x, y, r):
    x = np.asarray(x, dtype=float)
    y = np.asarray(y, dtype=float)
    i = int(np.argmax(y <= r))
    return x[i - 1] + (r - y[i - 1]) * (x[i] - x[i - 1]) / (y[i] - y[i - 1])


def test_lognormal_band_has_no_spike_and_matches_an_independent_bound():
    import surpyval as sp
    from scipy.stats import norm

    from backend import degradation

    payload, cache_id = degradation.fit(
        _pad_wear(), {"i": "pad", "x": "km", "y": "mm"}, 3.0,
        path="linear", distribution_id="lognormal", population_method="reml", unit="km",
    )
    curves = payload["life_model"]["curves"]
    x = np.asarray(curves["x"], dtype=float)
    live = degradation.get_live(cache_id)
    raw = np.asarray(live.cb(x, on="sf", alpha_ci=0.1, bound="two-sided"), dtype=float)[:, 0]
    # SurPyval 0.26's raw band dipped (to ~0) near the curve's start: what made
    # the Calculator read "90% band 6,000-41,900 km". 0.27's doesn't; the app's
    # band below holds either way.
    assert np.nanmin(raw[:60]) > 0.5
    for key in ("lower", "upper", "life_lower"):
        v = np.asarray(curves[key], dtype=float)
        assert np.all(np.diff(v) <= 1e-12), key  # never rises with distance

    # Independent: a lognormal fitted to the crossing distances alone, with
    # delta-method bounds on log B-life. The app's two-stage band also carries
    # the paths' uncertainty, so it may sit a little lower, never far lower.
    ln = sp.LogNormal.fit(np.asarray(live.pseudo_failure_times), c=np.asarray(live.c))
    mu, s = ln.params
    for q in (0.01, 0.10):
        zp = norm.ppf(q)
        g = np.array([1.0, zp])
        se = float(np.sqrt(g @ ln.hess_inv @ g))
        one_sided = np.exp(mu + zp * s - norm.ppf(0.90) * se)
        band_low = np.exp(mu + zp * s - norm.ppf(0.95) * se)
        app_one = _time_at(x, curves["life_lower"], 1 - q)
        app_band = _time_at(x, curves["lower"], 1 - q)
        assert 0.85 * one_sided < app_one < 1.02 * one_sided, (q, app_one, one_sided)
        assert 0.85 * band_low < app_band < 1.02 * band_low, (q, app_band, band_low)


def test_saved_model_header_curves_recomputed_on_read(session):
    """A model saved before the 90% one-sided curve (or with the old spiky
    band) is read back with its curves worked out afresh."""
    from backend import degradation as degradation_fit
    from backend.services import degradation as svc
    from backend.services import datasets as datasets_service

    ds = datasets_service.create_dataset(session, "wear", _deg_csv(), owner_id=A)
    spec = {"mapping": MAPPING, "threshold": 8.0, "path": "linear", "distribution_id": "weibull",
            "population_method": "moments", "unit": "hours", "measurement_unit": "mm"}
    doc = svc.save_model(session, "old", ds, spec, A)
    stale = dict(doc.results)
    lm = dict(stale["life_model"])
    lm["curves"] = {k: v for k, v in lm["curves"].items() if k not in ("life_lower", "life_level")}
    lm["curves"]["alpha_ci"] = 0.05
    session["degradation_models"].update_one({"_id": doc.id}, {"$set": {"results.life_model": lm}})
    fresh = svc.current_results(session, svc.get_model(session, doc.id, A), A)
    c = fresh["life_model"]["curves"]
    assert c["life_level"] == pytest.approx(0.9)
    assert c["alpha_ci"] == pytest.approx(degradation_fit._DEFAULT_ALPHA)
    assert "life_lower" in c


def test_induced_life_axis_stops_near_the_lives_not_at_the_slowest_path():
    """Linear wear whose drawn rates come near zero: the induced life's 99th
    percentile is ~100x its median. The chart's axis stops near the lives
    (and says what share crosses later), not out at millions of km."""
    from backend import degradation, degradation_induced

    _, cache_id = degradation.fit(_pad_wear(), {"i": "pad", "x": "km", "y": "mm"}, 3.0, path="linear", unit="km")
    live = degradation.get_live(cache_id)
    out = degradation_induced.induced_life(live)
    end = out["curve"]["x"][-1]
    assert end <= 1.2 * max(out["b10"], 1) * 10  # well within an order of magnitude of the lives
    assert end < 1.5 * max(float(live.life_model.qf(0.99)), float(live.induced_life(n_samples=10_000, random_state=0).qf(0.95)))
    assert end > out["median"]
    if "beyond" in out["curve"]:
        assert 0 < out["curve"]["beyond"] < 0.2
