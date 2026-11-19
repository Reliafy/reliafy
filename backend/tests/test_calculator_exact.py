"""The Calculator's answer at the time typed is the model's own value there.

It used to be read off the plotted grid by straight lines between its points:
on a steep early curve (a lognormal with B10 226 h) that read 95.6%, at least
89.8% at 100 h where the model says 96.3%, at least 86.0% — an optimistic
bound. The evaluate and confidence routes now take ``at`` (repeatable): the
times to answer at exactly; the grid is for drawing only.
"""
import math

import mongomock
import numpy as np
import pytest
import surpyval as surv

# Right-censored lives with a steep start: lognormal, B10 about 226 h.
SIGMA = 0.5
MU = math.log(226) + 1.2816 * SIGMA
CENSOR_AT = 600.0


def _data():
    rng = np.random.default_rng(1119)
    lives = rng.lognormal(MU, SIGMA, 40)
    x = np.minimum(lives, CENSOR_AT).round(1)
    c = (lives > CENSOR_AT).astype(int)
    return x, c


def _csv():
    x, c = _data()
    rows = "\n".join(f"{a},{b}" for a, b in zip(x, c))
    return f"hours,censored\n{rows}\n".encode()


@pytest.fixture()
def client(monkeypatch):
    from fastapi.testclient import TestClient

    from backend import config, db
    from backend.auth import get_current_user
    from backend.main import app

    monkeypatch.setattr(config, "AUTH_DISABLED", False)
    monkeypatch.setattr(config, "BILLING_ENABLED", False)
    monkeypatch.setattr(db, "_db", mongomock.MongoClient()["reliafy_calc_exact"])
    monkeypatch.setattr(db, "_simulated", True)
    app.dependency_overrides[get_current_user] = lambda: {"uid": "user-a", "email": "a@example.com", "name": "A"}
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()


FORM = {"x": "hours", "c": "censored", "unit": "hours"}


@pytest.fixture()
def reference():
    x, c = _data()
    return surv.LogNormal.fit(x=x, c=c)


def _interp(curves, fn, t):
    xs = np.asarray(curves["x"], dtype=float)
    ys = np.asarray([np.nan if v is None else v for v in curves[fn]], dtype=float)
    return float(np.interp(t, xs, ys))


def test_a_fresh_fit_answers_at_exactly_the_time_asked(client, reference):
    fit = client.post("/api/fit/lognormal", data=FORM, files={"file": ("p.csv", _csv(), "text/csv")})
    assert fit.status_code == 200, fit.text
    fns = fit.json()["functions"]
    for t in (7.5, 100.0, 133.3):
        r = client.post(f"{fns['evaluate_path']}?at={t}", json={})
        assert r.status_code == 200, r.text
        curves = r.json()["curves"]
        assert curves["x"] == [t]
        for fn in ("sf", "ff", "hf", "Hf", "df"):
            assert curves[fn][0] == pytest.approx(float(getattr(reference, fn)(t)), rel=1e-6), (fn, t)
    # The bound at exactly 100 h: SurPyval's own, not the band's grid read by straight lines.
    r = client.post(f"{fns['confidence_path']}?at=100", json={"on": "sf", "alpha_ci": 0.1, "bound": "lower"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["x"] == [100.0] and body["upper"] is None
    want = float(np.asarray(reference.cb(np.array([100.0]), on="sf", alpha_ci=0.1, bound="lower")).ravel()[0])
    assert body["lower"][0] == pytest.approx(want, rel=1e-6)
    assert body["lower"][0] < float(reference.sf(100.0))


def test_a_saved_model_answers_exactly_too_and_the_grid_would_not(client, reference):
    saved = client.post("/api/models", data={**FORM, "name": "Pumps", "distribution": "lognormal"},
                        files={"file": ("p.csv", _csv(), "text/csv")})
    assert saved.status_code == 200, saved.text
    model = client.get(f"/api/models/{saved.json()['id']}").json()
    fns = model["results"]["functions"]
    # The age survived to and that age plus t, in one call (the conditional answer).
    r = client.post(f"{fns['evaluate_path']}?at=50&at=150", json={})
    assert r.status_code == 200, r.text
    curves = r.json()["curves"]
    assert curves["x"] == [50.0, 150.0]
    assert curves["sf"][1] / curves["sf"][0] == pytest.approx(
        float(reference.sf(150.0) / reference.sf(50.0)), rel=1e-6)
    # Off the grid's points on the steep start, straight lines are not the model's value.
    grid = fns["curves"]
    t = next(float(a + b) / 2 for a, b in zip(grid["x"], grid["x"][1:]) if a > 150)
    exact = client.post(f"{fns['evaluate_path']}?at={t}", json={}).json()["curves"]["sf"][0]
    assert exact == pytest.approx(float(reference.sf(t)), rel=1e-6)
    assert abs(_interp(grid, "sf", t) - exact) > 1e-7
    r = client.post(f"{fns['confidence_path']}?at={t}", json={"on": "sf", "alpha_ci": 0.1, "bound": "lower"})
    assert r.status_code == 200, r.text
    assert r.json()["lower"][0] == pytest.approx(
        float(np.asarray(reference.cb(np.array([t]), on="sf", alpha_ci=0.1, bound="lower")).ravel()[0]), rel=1e-6)


def test_bad_times_are_refused_in_plain_words(client):
    fit = client.post("/api/fit/lognormal", data=FORM, files={"file": ("p.csv", _csv(), "text/csv")})
    path = fit.json()["functions"]["evaluate_path"]
    r = client.post(f"{path}?at=inf", json={})
    assert r.status_code == 422
    assert "finite" in r.json()["detail"]
    many = "&".join(f"at={i}" for i in range(51))
    assert client.post(f"{path}?{many}", json={}).status_code == 422
