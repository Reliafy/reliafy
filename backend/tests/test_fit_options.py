"""Fit options (offset / LFP / zero-inflation / fixed) and the wider
distribution catalogue, end to end: fitting, persistence, reconstruction,
and the downstream guards."""

import matplotlib

matplotlib.use("Agg")

import io

import mongomock
import numpy as np
import pandas as pd
import pytest

from backend import fitting

A = "user-a"
USERS = {A: {"uid": A, "email": "a@x.com", "name": "A"}}


# ---- fitting layer ----------------------------------------------------------

def test_offset_recovers_failure_free_period():
    rng = np.random.default_rng(11)
    df = pd.DataFrame({"t": rng.weibull(2, 800) * 1000 + 400})
    r = fitting.fit("weibull", df, {"x": "t"}, None, None, None, options={"offset": True})
    assert r["extras"]["gamma"] == pytest.approx(400, rel=0.15)
    assert r["options"] == {"offset": True}
    assert any("gamma" in p["name"] for p in r["extra_params"])


def test_lfp_recovers_max_failing_fraction():
    rng = np.random.default_rng(7)
    t = rng.weibull(2, 1000) * 1000
    c = np.zeros(1000)
    c[600:] = 1          # 40% fail; the rest never will
    t[600:] = 6000       # suspended far beyond the failures
    df = pd.DataFrame({"t": t, "c": c})
    r = fitting.fit("weibull", df, {"x": "t", "c": "c"}, None, None, None, options={"lfp": True})
    assert r["extras"]["p"] == pytest.approx(0.6, abs=0.05)


def test_zero_inflation_recovers_doa_fraction():
    rng = np.random.default_rng(3)
    df = pd.DataFrame({"t": np.concatenate([np.zeros(80), rng.weibull(2, 720) * 1000])})
    r = fitting.fit("weibull", df, {"x": "t"}, None, None, None, options={"zi": True})
    assert r["extras"]["f0"] == pytest.approx(0.1, abs=0.02)


def test_fixed_parameter_is_respected():
    rng = np.random.default_rng(5)
    df = pd.DataFrame({"t": rng.weibull(2, 300) * 1000})
    r = fitting.fit("weibull", df, {"x": "t"}, None, None, None, options={"fixed": {"beta": 2.5}})
    beta = next(p for p in r["params"] if p["name"] == "beta")
    assert beta["value"] == pytest.approx(2.5, abs=1e-9)
    assert r["options"]["fixed"] == {"beta": 2.5}


def test_new_distributions_fit():
    rng = np.random.default_rng(9)
    df = pd.DataFrame({"t": rng.weibull(2, 250) * 1000})
    for dist_id, n_params in [
        ("loglogistic", 2), ("gumbel", 2), ("logistic", 2), ("expo_weibull", 3),
    ]:
        r = fitting.fit(dist_id, df, {"x": "t"}, None, None, None)
        assert len(r["params"]) == n_params, dist_id
        assert r["plot"]["scatter"]["x"], dist_id


def test_invalid_options_rejected():
    rng = np.random.default_rng(1)
    df = pd.DataFrame({"t": rng.weibull(2, 100) * 1000})
    with pytest.raises(fitting.FitError, match="offset"):
        fitting.fit("gumbel", df, {"x": "t"}, None, None, None, options={"offset": True})
    with pytest.raises(fitting.FitError, match="parameters are"):
        fitting.fit("weibull", df, {"x": "t"}, None, None, None, options={"fixed": {"nope": 1}})
    with pytest.raises(fitting.FitError, match="plain distributions"):
        fitting.fit("weibull_ph", df, {"x": "t"}, ["t"], None, None, options={"lfp": True})


def test_options_from_form():
    assert fitting.options_from_form("true", None, None, None) == {
        "offset": True, "zi": False, "lfp": False}
    assert fitting.options_from_form(None, None, None, None) is None
    assert fitting.options_from_form(None, None, None, '{"beta": 2}')["fixed"] == {"beta": 2}
    with pytest.raises(fitting.FitError):
        fitting.options_from_form(None, None, None, "{not json")


# ---- reconstruction + downstream guards -------------------------------------

def test_reconstruction_carries_extras():
    from backend.services.strategy import _model_from_params

    rng = np.random.default_rng(11)
    df = pd.DataFrame({"t": rng.weibull(2, 800) * 1000 + 400})
    r = fitting.fit("weibull", df, {"x": "t"}, None, None, None, options={"offset": True})
    model, _ = _model_from_params("weibull", r["params"], r["extras"])
    # Just past the offset almost nothing has failed (below it SurPyval
    # reports NaN — outside the support — which the plot layer nulls out).
    assert float(model.sf(r["extras"]["gamma"] * 1.05)) > 0.98
    assert float(model.qf(0.5)) > r["extras"]["gamma"]


def test_replacement_rejects_lfp():
    from backend.services.strategy import StrategyError, optimal_replacement

    params = [{"name": "alpha", "value": 1000.0}, {"name": "beta", "value": 2.0}]
    with pytest.raises(StrategyError, match="limited-failure-population"):
        optimal_replacement("weibull", params, 100, 1000, extras={"p": 0.6})


# ---- API round trip ----------------------------------------------------------

@pytest.fixture()
def client(monkeypatch):
    from fastapi.testclient import TestClient

    from backend import config, db
    from backend.auth import get_current_user
    from backend.main import app

    monkeypatch.setattr(config, "AUTH_DISABLED", False)
    monkeypatch.setattr(config, "BILLING_ENABLED", False)
    test_db = mongomock.MongoClient()["reliafy_test"]
    monkeypatch.setattr(db, "_db", test_db)
    monkeypatch.setattr(db, "_simulated", True)
    app.dependency_overrides[get_current_user] = lambda: USERS[A]
    tc = TestClient(app)
    tc.db = test_db
    try:
        yield tc
    finally:
        app.dependency_overrides.clear()


def test_save_and_fleet_guard_via_api(client):
    rng = np.random.default_rng(7)
    t = rng.weibull(2, 400) * 1000
    c = np.zeros(400)
    c[240:] = 1
    t[240:] = 6000
    csv = io.BytesIO(pd.DataFrame({"t": t, "c": c}).to_csv(index=False).encode())
    r = client.post(
        "/api/models",
        data={"name": "LFP pumps", "distribution": "weibull", "x": "t", "c": "c", "lfp": "true"},
        files={"file": ("d.csv", csv, "text/csv")},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["results"]["extras"]["p"] == pytest.approx(0.6, abs=0.06)
    model_id = body["id"]

    # A renewals fleet forecast on an LFP model reports stale with guidance.
    f = client.post("/api/fleet/fleets", json={"name": "F", "model_id": model_id}).json()
    put = client.put(
        f"/api/fleet/fleets/{f['id']}/items",
        json={
            "settings": {"periods": 6, "period_label": "months", "default_rate": 300, "method": "renewals"},
            "items": [{"name": "U1", "current_use": 500}],
            "expected_updated_at": f["updated_at"],
        },
    )
    forecast = put.json()["forecast"]
    assert forecast["status"] == "stale"
    assert "first failures" in forecast["reason"]

    # The 'single' method works fine on the same model.
    f2 = client.get(f"/api/fleet/fleets/{f['id']}").json()
    put2 = client.put(
        f"/api/fleet/fleets/{f['id']}/items",
        json={
            "settings": {"periods": 6, "period_label": "months", "default_rate": 300, "method": "single"},
            "items": [{"name": "U1", "current_use": 500}],
            "expected_updated_at": f2["updated_at"],
        },
    )
    forecast2 = put2.json()["forecast"]
    assert forecast2["status"] == "ok"
    assert 0 <= forecast2["expected"] <= 1


# ---- best fit ----------------------------------------------------------------

def test_best_fit_picks_lowest_aic():
    rng = np.random.default_rng(21)
    df = pd.DataFrame({"t": rng.lognormal(6.5, 0.5, 500)})
    r = fitting.fit("best", df, {"x": "t"}, None, None, None)
    sel = r["selection"]
    assert sel["criterion"] == "aic"
    aics = [c["aic"] for c in sel["candidates"]]
    assert aics == sorted(aics)
    assert r["distribution_id"] == sel["candidates"][0]["id"]
    # Lognormal data: the lognormal family should be at/near the top.
    assert sel["candidates"][0]["id"] in {"lognormal", "expo_weibull", "gamma", "weibull"}
    # Full payload identical to a direct fit (plot, functions, gof present).
    assert r["plot"]["scatter"]["x"] and r["gof"]


def test_best_fit_rejects_fixed_but_allows_offset():
    rng = np.random.default_rng(22)
    df = pd.DataFrame({"t": rng.weibull(2, 300) * 1000 + 500})
    with pytest.raises(fitting.FitError, match="specific distribution"):
        fitting.fit("best", df, {"x": "t"}, None, None, None, options={"fixed": {"beta": 2}})
    r = fitting.fit("best", df, {"x": "t"}, None, None, None, options={"offset": True})
    # Winner honoured the offset when it supports one.
    if r["options"].get("offset"):
        assert "gamma" in (r.get("extras") or {})


def test_best_fit_saved_model_persists_winner(client):
    rng = np.random.default_rng(23)
    csv = io.BytesIO(pd.DataFrame({"t": rng.weibull(2, 200) * 1000}).to_csv(index=False).encode())
    r = client.post(
        "/api/models",
        data={"name": "Auto pick", "distribution": "best", "x": "t"},
        files={"file": ("d.csv", csv, "text/csv")},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    winner = body["results"]["distribution_id"]
    assert winner != "best" and winner in body["results"]["selection"]["candidates"][0]["id"]
    # Refit-on-demand spec is pinned to the winner, so it can't drift.
    doc = client.db.models.find_one({"_id": body["id"]})
    assert doc["spec"]["distribution_id"] == winner


# ---- confidence bounds --------------------------------------------------------

def test_saved_model_confidence_endpoint(client):
    rng = np.random.default_rng(7)
    csv = io.BytesIO(pd.DataFrame({"t": rng.weibull(2.0, 120) * 800}).to_csv(index=False).encode())
    saved = client.post(
        "/api/models",
        data={"name": "CI demo", "distribution": "weibull", "x": "t", "unit": "hours"},
        files={"file": ("d.csv", csv, "text/csv")},
    ).json()
    # The saved results advertise a confidence path for the calculator.
    assert saved["results"]["functions"]["confidence_path"].endswith(f"/{saved['id']}/confidence")

    # Two-sided 95% bounds bracket the fitted reliability.
    r = client.post(f"/api/models/{saved['id']}/confidence",
                    json={"on": "sf", "alpha_ci": 0.05, "bound": "two-sided"})
    assert r.status_code == 200, r.text
    cb = r.json()
    assert cb["lower"] and cb["upper"] and len(cb["x"]) == len(cb["lower"])

    # One-sided lower bound returns only the lower array.
    r = client.post(f"/api/models/{saved['id']}/confidence", json={"bound": "lower"})
    assert r.status_code == 200 and r.json()["lower"] and r.json()["upper"] is None

    # A nonsensical level is a clean 422, not a 500.
    r = client.post(f"/api/models/{saved['id']}/confidence", json={"alpha_ci": 2})
    assert r.status_code == 422


def test_regression_model_has_no_confidence_path(client):
    df = pd.DataFrame({"t": [100, 200, 150, 300, 250, 400, 120, 220, 180, 350, 90, 410],
                       "c": [0, 0, 1, 0, 0, 1, 0, 0, 1, 0, 0, 1],
                       "temp": [60, 60, 60, 80, 80, 80, 100, 100, 100, 70, 70, 70]})
    csv = io.BytesIO(df.to_csv(index=False).encode())
    saved = client.post(
        "/api/models",
        data={"name": "PH", "distribution": "weibull_ph", "x": "t", "c": "c", "z": "temp"},
        files={"file": ("d.csv", csv, "text/csv")},
    ).json()
    assert saved["kind"] == "regression"
    # Regression models don't expose confidence bounds.
    assert "confidence_path" not in saved["results"]["functions"]
    assert client.post(f"/api/models/{saved['id']}/confidence", json={}).status_code == 422


# ---- edit / refit in place ----------------------------------------------------

def test_update_fit_in_place(client):
    rng = np.random.default_rng(31)
    csv = io.BytesIO(pd.DataFrame({"t": rng.weibull(2, 300) * 1000 + 400}).to_csv(index=False).encode())
    saved = client.post(
        "/api/models",
        data={"name": "Editable", "distribution": "weibull", "x": "t", "unit": "hours"},
        files={"file": ("d.csv", csv, "text/csv")},
    ).json()
    model_id = saved["id"]
    assert "extras" not in saved["results"]

    # Refit with an offset and a different distribution family available.
    r = client.put(
        f"/api/models/{model_id}/fit",
        json={"distribution": "weibull", "mapping": {"x": "t"}, "unit": "hours", "offset": True},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["id"] == model_id
    assert body["results"]["extras"]["gamma"] == pytest.approx(400, rel=0.2)
    assert body["spec"]["options"] == {"offset": True}

    # Best-fit refit resolves and pins the winner.
    r2 = client.put(
        f"/api/models/{model_id}/fit",
        json={"distribution": "best", "mapping": {"x": "t"}, "unit": "hours"},
    )
    assert r2.status_code == 200
    assert r2.json()["spec"]["distribution_id"] != "best"

    # A failing refit leaves the stored model untouched.
    r3 = client.put(
        f"/api/models/{model_id}/fit",
        json={"distribution": "gumbel", "mapping": {"x": "t"}, "offset": True},
    )
    assert r3.status_code == 422
    current = client.get(f"/api/models/{model_id}").json()
    assert current["results"]["distribution_id"] == r2.json()["results"]["distribution_id"]


def test_update_fit_rejected_for_read_only(client):
    from backend.services import samples as samples_service

    samples_service.seed_samples(client.db)
    sample = client.db.models.find_one({"kind": "distribution"})
    r = client.put(
        f"/api/models/{sample['_id']}/fit",
        json={"distribution": "weibull", "mapping": {"x": "t"}},
    )
    assert r.status_code in (402, 403)


# ---- create from parameters (in-app, no data) --------------------------------

def test_create_from_params_endpoint(client):
    r = client.post(
        "/api/models/from-params",
        json={"name": "Handbook Weibull", "distribution": "weibull", "unit": "hours",
              "params": [{"name": "alpha", "value": 1200}, {"name": "beta", "value": 2.3}]},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["results"]["params_only"] is True
    assert body["results"]["plot"] is None
    assert body["results"]["functions"]["curves"]["x"]  # functions work
    assert body["dataset_id"] == ""  # no dataset

    # It reads back like any model.
    got = client.get(f"/api/models/{body['id']}").json()
    assert got["results"]["distribution"] == "Weibull"


def test_create_from_params_with_offset_and_validation(client):
    r = client.post(
        "/api/models/from-params",
        json={"name": "Offset", "distribution": "weibull",
              "params": [{"name": "alpha", "value": 1000}, {"name": "beta", "value": 2}],
              "extras": {"gamma": 300, "p": 1, "f0": 0}},
    )
    assert r.status_code == 200
    assert r.json()["results"]["extras"] == {"gamma": 300.0}

    # Bad distribution and missing name -> 422.
    assert client.post("/api/models/from-params",
                       json={"name": "x", "distribution": "nope", "params": [{"value": 1}]}
                       ).status_code == 422
    assert client.post("/api/models/from-params",
                       json={"name": "", "distribution": "weibull", "params": [{"value": 1}]}
                       ).status_code == 422
