"""Non-parametric life results (#85): the B-lives with their bounds, the mean
life restricted to a horizon with its interval, and the simultaneous bands.
Every number is SurPyval's own, checked against SurPyval called directly."""

import matplotlib

matplotlib.use("Agg")

import io

import mongomock
import numpy as np
import pandas as pd
import pytest
from surpyval import FlemingHarrington, KaplanMeier, NelsonAalen, Turnbull

from backend import fitting, life_bounds, np_life

A = "user-a"
B = "user-b"
USERS = {A: {"uid": A, "email": "a@x.com", "name": "A"}, B: {"uid": B, "email": "b@x.com", "name": "B"}}
PROBS = np.array([0.01, 0.05, 0.10, 0.50])
ESTIMATORS = [("kaplan_meier", KaplanMeier), ("nelson_aalen", NelsonAalen),
              ("fleming_harrington", FlemingHarrington), ("turnbull", Turnbull)]


def _data(seed=5, n=60, end=1400.0):
    """Weibull lives with the units still running at ``end`` censored there:
    the curve never reaches zero, so its mean is restricted."""
    rng = np.random.default_rng(seed)
    t = rng.weibull(2.0, n) * 1000
    c = (t > end).astype(int)
    return np.where(c == 1, end, t), c


def _fit(dist_id, t, c):
    return fitting.fit(dist_id, pd.DataFrame({"t": t, "c": c}), {"x": "t", "c": "c"}, unit="hours")


@pytest.mark.parametrize("dist_id, est", ESTIMATORS)
def test_fit_carries_b_lives_and_the_restricted_mean(dist_id, est):
    t, c = _data()
    life = _fit(dist_id, t, c)["life"]
    model = est.fit(t, c)
    assert [b["value"] for b in life["b_lives"]] == pytest.approx(np.asarray(model.qf(PROBS)).tolist())
    # The one-sided 90% bound is the lower end of the two-sided 80% interval.
    two = np.asarray(model.quantile_cb(PROBS, alpha_ci=0.2)).reshape(-1, 2)
    got = [b["lower"] for b in life["b_lives"]]
    assert [g for g in got if g is not None] == pytest.approx([v for v in two[:, 0] if np.isfinite(v)])

    mttf = life["mttf"]
    assert mttf["tau"] == pytest.approx(float(t.max()))
    assert mttf["restricted"] is True
    assert mttf["value"] == pytest.approx(float(model.mean(t.max())))
    lo, hi = np.asarray(model.mean_cb(t.max(), alpha_ci=0.2))
    assert mttf["lower"] == pytest.approx(max(lo, 0.0)) and mttf["upper"] == pytest.approx(hi)
    assert mttf["lower"] < mttf["value"] < mttf["upper"]


def test_the_mean_is_the_whole_mean_when_the_curve_reaches_zero():
    t = np.array([312.0, 420, 506, 588, 655, 719, 773, 824, 889, 946])
    life = _fit("kaplan_meier", t, np.zeros_like(t))["life"]
    assert life["mttf"]["restricted"] is False
    assert life["mttf"]["value"] == pytest.approx(float(KaplanMeier.fit(t).mean()))


def test_a_horizon_and_a_confidence_are_asked_for():
    t, c = _data(9)
    km = KaplanMeier.fit(t, c)
    out = life_bounds.answer(km, {"confidence": 0.95, "tau": 800})
    assert out["mttf"]["tau"] == 800
    assert out["mttf"]["value"] == pytest.approx(float(km.mean(800)))
    rmst = km.rmst(800, alpha_ci=0.1)  # 95% one-sided = the 90% two-sided interval's ends
    assert out["mttf"]["lower"] == pytest.approx(float(rmst["lower"]))
    assert out["mttf"]["upper"] == pytest.approx(float(rmst["upper"]))
    for bad in ({"tau": -1}, {"tau": "soon"}, {"tau": 0}):
        with pytest.raises(ValueError):
            life_bounds.answer(km, bad)


@pytest.mark.parametrize("method", ["hall-wellner", "nair"])
def test_bands_are_surpyvals(method):
    t, c = _data(13, 80)
    est = _fit("kaplan_meier", t, c)["estimate"]
    band = est["bands"][method]
    km = KaplanMeier.fit(t, c)
    expected = np.asarray(km.band(np.asarray(band["x"]), method=method, alpha_ci=0.05))
    assert band["lower"] == pytest.approx(expected[:, 0].tolist())
    assert band["upper"] == pytest.approx(expected[:, 1].tolist())
    # A whole-curve band is at least as wide as the pointwise one where both exist.
    pw = np.asarray(km.cb(np.asarray(band["x"]), alpha_ci=0.05)).reshape(-1, 2)
    assert np.all(np.asarray(band["upper"]) - np.asarray(band["lower"]) >= pw[:, 1] - pw[:, 0] - 1e-9)


def test_no_band_without_failures_and_never_raises():
    assert np_life.bands(object()) == {}
    km = KaplanMeier.fit([5.0, 6.0, 7.0], [1, 1, 1])
    assert np_life.bands(km) == {}


# ---- the API -------------------------------------------------------------------

@pytest.fixture()
def client(monkeypatch):
    from fastapi.testclient import TestClient

    from backend import config, db
    from backend.auth import get_current_user
    from backend.main import app

    monkeypatch.setattr(config, "AUTH_DISABLED", False)
    monkeypatch.setattr(config, "BILLING_ENABLED", False)
    test_db = mongomock.MongoClient()["reliafy_np_life_test"]
    monkeypatch.setattr(db, "_db", test_db)
    monkeypatch.setattr(db, "_simulated", True)
    who = {"uid": A}
    app.dependency_overrides[get_current_user] = lambda: USERS[who["uid"]]
    tc = TestClient(app)
    tc.who = who
    try:
        yield tc
    finally:
        app.dependency_overrides.clear()


def test_life_endpoints_take_a_horizon(client):
    t, c = _data()
    csv = pd.DataFrame({"t": t, "c": c}).to_csv(index=False).encode()
    fresh = client.post("/api/fit/kaplan_meier", data={"x": "t", "c": "c", "unit": "hours"},
                        files={"file": ("d.csv", io.BytesIO(csv), "text/csv")}).json()
    km = KaplanMeier.fit(t, c)
    out = client.post(fresh["functions"]["life_path"], json={"confidence": 0.9, "tau": 1000}).json()
    assert out["mttf"]["value"] == pytest.approx(float(km.mean(1000)))
    assert client.post(fresh["functions"]["life_path"], json={"tau": -5}).status_code == 422

    saved = client.post("/api/models", data={"name": "KM", "distribution": "kaplan_meier", "x": "t", "c": "c",
                                             "unit": "hours"},
                        files={"file": ("d.csv", io.BytesIO(csv), "text/csv")}).json()
    assert saved["results"]["life"]["mttf"]["restricted"] is True
    assert set(saved["results"]["estimate"]["bands"]) == {"hall-wellner", "nair"}
    out = client.post(f"/api/models/{saved['id']}/life", json={"confidence": 0.8, "tau": 600}).json()
    assert out["mttf"]["value"] == pytest.approx(float(km.mean(600)))
    assert out["mttf"]["lower"] == pytest.approx(float(km.mean_cb(600, alpha_ci=0.4)[0]))
