"""B-lives, MTTF and the time at a reliability with one-sided bounds (#288),
and the distribution comparison on a saved model (#293): every number is
SurPyval's own, checked here against SurPyval called directly."""

import matplotlib

matplotlib.use("Agg")

import io

import mongomock
import numpy as np
import pandas as pd
import pytest
from surpyval import KaplanMeier, LogNormal, Weibull

from backend import fitting, life_bounds
from backend.tests.test_mcp import FLAGS, TIMES, _call, _ok, env  # noqa: F401 - env is a fixture
from backend.tests.test_mcp import A as MCP_USER

A = "user-a"
B = "user-b"
USERS = {A: {"uid": A, "email": "a@x.com", "name": "A"}, B: {"uid": B, "email": "b@x.com", "name": "B"}}

PROBS = np.array([0.01, 0.05, 0.10, 0.50])


def _data(seed=7, n=60):
    rng = np.random.default_rng(seed)
    t = rng.weibull(2.0, n) * 1000
    c = (t > 1400).astype(int)
    t = np.where(c == 1, 1400, t)
    return t, c


def _expected(model, confidence):
    alpha = 1 - confidence
    return (np.asarray(model.qf(PROBS)), np.asarray(model.quantile_cb(PROBS, alpha_ci=alpha, bound="lower")),
            float(model.mean()), float(model.mean_cb(alpha_ci=alpha, bound="lower")))


@pytest.mark.parametrize("dist_id, dist", [("weibull", Weibull), ("lognormal", LogNormal)])
def test_fit_result_carries_b_lives_and_mttf_as_surpyval_gives_them(dist_id, dist):
    t, c = _data()
    r = fitting.fit(dist_id, pd.DataFrame({"t": t, "c": c}), {"x": "t", "c": "c"}, unit="hours")
    life = r["life"]
    assert life["confidence"] == 0.9 and life["bound"] == "lower" and life["bounds_note"] is None
    assert [b["label"] for b in life["b_lives"]] == ["B1", "B5", "B10", "B50"]

    q, lower, mean, mean_lower = _expected(dist.fit(t, c), 0.9)
    assert [b["value"] for b in life["b_lives"]] == pytest.approx(q.tolist(), rel=1e-6)
    assert [b["lower"] for b in life["b_lives"]] == pytest.approx(lower.tolist(), rel=1e-6)
    assert life["mttf"]["value"] == pytest.approx(mean, rel=1e-6)
    assert life["mttf"]["lower"] == pytest.approx(mean_lower, rel=1e-6)
    # A lower bound is below its estimate.
    assert all(b["lower"] < b["value"] for b in life["b_lives"])
    assert life["mttf"]["lower"] < life["mttf"]["value"]
    # The same B10 and MTTF as the metrics the MCP tools have always given.
    assert life["b_lives"][2]["value"] == pytest.approx(fitting._life_metrics(dist.fit(t, c))["b10"], rel=1e-6)


def test_time_at_reliability_matches_quantile_cb_for_every_bound():
    t, c = _data(11)
    model = Weibull.fit(t, c)
    for bound in ("lower", "upper", "two-sided"):
        out = life_bounds.time_at_reliability(model, [0.9, 0.5], 0.95, bound)
        expected = np.asarray(model.quantile_cb([0.1, 0.5], alpha_ci=0.05, bound=bound))
        times = [p["time"] for p in out["points"]]
        assert times == pytest.approx(np.asarray(model.qf([0.1, 0.5])).tolist(), rel=1e-9)
        if bound == "two-sided":
            got = [v for p in out["points"] for v in (p["lower"], p["upper"])]
            assert got == pytest.approx(expected.ravel().tolist(), rel=1e-9)
        elif bound == "lower":
            assert [p["lower"] for p in out["points"]] == pytest.approx(expected.tolist(), rel=1e-9)
            assert all(p["upper"] is None for p in out["points"])
        else:
            assert [p["upper"] for p in out["points"]] == pytest.approx(expected.tolist(), rel=1e-9)
            assert all(p["lower"] is None for p in out["points"])


def test_nonparametric_one_sided_bound_is_one_end_of_the_two_sided():
    t, c = _data(3, 80)
    km = KaplanMeier.fit(t, c)
    out = life_bounds.time_at_reliability(km, [0.9], 0.9, "lower")
    two = np.asarray(km.quantile_cb([0.1], alpha_ci=0.2)).reshape(-1, 2)
    assert out["points"][0]["lower"] == pytest.approx(two[0, 0])
    assert out["points"][0]["time"] == pytest.approx(float(np.ravel(km.qf([0.1]))[0]))


def test_models_without_a_covariance_get_values_and_say_why():
    r = fitting.result_from_params("weibull", [{"name": "alpha", "value": 1000}, {"name": "beta", "value": 2}])
    life = r["life"]
    assert life["b_lives"][2]["value"] == pytest.approx(float(Weibull.from_params([1000, 2]).qf(0.1)))
    assert all(b["lower"] is None for b in life["b_lives"]) and life["mttf"]["lower"] is None
    assert "covariance" in life["bounds_note"]

    t, c = _data()
    mpp = fitting.fit("weibull", pd.DataFrame({"t": t, "c": c}), {"x": "t", "c": "c"}, options={"how": "MPP"})
    assert mpp["life"]["b_lives"][0]["lower"] is None
    assert "maximum-likelihood" in mpp["life"]["bounds_note"]


def test_limited_failure_population_has_no_mttf():
    rng = np.random.default_rng(7)
    t = rng.weibull(2, 600) * 1000
    c = np.zeros(600)
    c[360:] = 1
    t[360:] = 6000
    r = fitting.fit("weibull", pd.DataFrame({"t": t, "c": c}), {"x": "t", "c": "c"}, options={"lfp": True})
    assert r["life"]["mttf"] == {"value": None, "lower": None}
    assert r["life"]["b_lives"][2]["value"] is not None


def test_bad_requests_are_refused():
    model = Weibull.fit(*_data())
    for bad in ({"confidence": 1.2}, {"confidence": "x"}, {"reliability": [1.0]}, {"reliability": [0.5], "bound": "both"}):
        with pytest.raises(ValueError):
            life_bounds.answer(model, bad)


# ---- the API -------------------------------------------------------------------

@pytest.fixture()
def client(monkeypatch):
    from fastapi.testclient import TestClient

    from backend import config, db
    from backend.auth import get_current_user
    from backend.main import app

    monkeypatch.setattr(config, "AUTH_DISABLED", False)
    monkeypatch.setattr(config, "BILLING_ENABLED", False)
    test_db = mongomock.MongoClient()["reliafy_life_test"]
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


def _csv():
    t, c = _data()
    return t, c, io.BytesIO(pd.DataFrame({"t": t, "c": c}).to_csv(index=False).encode())


def test_fresh_fit_life_endpoint(client):
    t, c, csv = _csv()
    r = client.post("/api/fit/weibull", data={"x": "t", "c": "c", "unit": "hours"},
                    files={"file": ("d.csv", csv, "text/csv")}).json()
    path = r["functions"]["life_path"]
    assert path == f"/api/life/{r['functions']['model_id']}"
    model = Weibull.fit(t, c)

    # Another confidence: the same shape, SurPyval's numbers at 95%.
    life = client.post(path, json={"confidence": 0.95}).json()
    q, lower, mean, mean_lower = _expected(model, 0.95)
    assert [b["lower"] for b in life["b_lives"]] == pytest.approx(lower.tolist(), rel=1e-6)
    assert life["mttf"]["lower"] == pytest.approx(mean_lower, rel=1e-6)

    # Time at reliability: R = 90% is B10.
    at = client.post(path, json={"reliability": [0.9], "confidence": 0.9, "bound": "lower"}).json()
    assert at["points"][0]["time"] == pytest.approx(float(model.qf(0.1)), rel=1e-6)
    assert at["points"][0]["lower"] == pytest.approx(float(model.quantile_cb(0.1, alpha_ci=0.1, bound="lower")),
                                                     rel=1e-6)

    assert client.post(path, json={"confidence": 2}).status_code == 422
    assert client.post(path, json={"reliability": [0, 0.5]}).status_code == 422
    # Only the account that fitted it.
    client.who["uid"] = B
    assert client.post(path, json={}).status_code == 404


def test_saved_model_life_and_compare(client):
    t, c, csv = _csv()
    saved = client.post("/api/models", data={"name": "Bearings", "distribution": "weibull", "x": "t", "c": "c",
                                             "unit": "hours"},
                        files={"file": ("d.csv", csv, "text/csv")}).json()
    mid = saved["id"]
    assert saved["results"]["functions"]["life_path"] == f"/api/models/{mid}/life"
    assert saved["results"]["life"]["b_lives"][2]["value"] == pytest.approx(float(Weibull.fit(t, c).qf(0.1)), rel=1e-6)

    life = client.post(f"/api/models/{mid}/life", json={"confidence": 0.8}).json()
    _, lower, _, _ = _expected(Weibull.fit(t, c), 0.8)
    assert [b["lower"] for b in life["b_lives"]] == pytest.approx(lower.tolist(), rel=1e-6)
    at = client.post(f"/api/models/{mid}/life", json={"reliability": [0.5], "bound": "two-sided"}).json()
    assert at["points"][0]["lower"] < at["points"][0]["time"] < at["points"][0]["upper"]

    # Compare: Best fit's own ranking on the same data, best first.
    cmp = client.post(f"/api/models/{mid}/compare").json()
    best = fitting.fit("best", pd.DataFrame({"t": t, "c": c}), {"x": "t", "c": "c"})["selection"]
    assert [x["id"] for x in cmp["candidates"]] == [x["id"] for x in best["candidates"]]
    assert cmp["candidates"][0]["aic"] == pytest.approx(best["candidates"][0]["aic"])
    weibull_aic = next(x["aic"] for x in cmp["candidates"] if x["id"] == "weibull")
    assert weibull_aic == pytest.approx(next(g["value"] for g in saved["results"]["gof"] if g["id"] == "aic"))
    assert cmp["criterion"] == "aic"

    client.who["uid"] = B
    assert client.post(f"/api/models/{mid}/life", json={}).status_code == 404
    assert client.post(f"/api/models/{mid}/compare").status_code == 404


def test_mcp_get_model_gives_the_same_life(env):  # noqa: F811 - the fixture
    saved = _ok(_call(env.token[MCP_USER], "fit_and_save_model", {
        "data": TIMES, "censored": FLAGS, "unit": "hours", "name": "MCP bearings"}))
    detail = _ok(_call(env.token[MCP_USER], "get_model", {"model_id": saved["model_id"]}))
    model = Weibull.fit(np.asarray(TIMES, dtype=float), np.asarray(FLAGS))
    life = detail["life"]
    assert [b["value"] for b in life["b_lives"]] == pytest.approx(np.asarray(model.qf(PROBS)).tolist(), rel=1e-6)
    assert life["b_lives"][2]["lower"] == pytest.approx(
        float(model.quantile_cb(0.1, alpha_ci=0.1, bound="lower")), rel=1e-6)
    # Consistent with the metrics beside it.
    assert life["b_lives"][2]["value"] == pytest.approx(detail["metrics"]["b10"], rel=1e-9)
    assert life["mttf"]["value"] == pytest.approx(detail["metrics"]["mttf"], rel=1e-9)
