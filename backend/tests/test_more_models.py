"""More life models (#179, #72, #63): every number checked against SurPyval
called directly, through the fit, the REST API, the saved model and MCP.

Bounded distributions (Beta, Beta4, Uniform), discretized distributions,
the semi-parametric regressions (additive hazards, proportional odds,
Buckley-James), shared frailty with a Group by column, Royston-Parmar, and
a degradation model's induced (Lu-Meeker) life distribution.
"""

import io

import matplotlib

matplotlib.use("Agg")

import mongomock  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
import pytest  # noqa: E402
import surpyval as sp  # noqa: E402

from backend import fitting, more_models  # noqa: E402
from backend.fitting import FitError  # noqa: E402

A = "user-a"


def _frailty_df(seed: int = 4) -> pd.DataFrame:
    """Thirty sites of six units with a gamma site effect and one covariate."""
    rng = np.random.default_rng(seed)
    groups = np.repeat(np.arange(30), 6)
    u = rng.gamma(2.0, 0.5, 30)[groups]
    z = rng.binomial(1, 0.5, groups.size)
    temp = np.round(rng.normal(50, 5, groups.size), 2)
    x = 10 * (rng.exponential(1, groups.size) / (u * np.exp(0.5 * z))) ** 0.5
    c = (x > 15).astype(int)
    return pd.DataFrame({"t": np.round(np.minimum(x, 15), 4), "c": c, "z": z, "temp": temp,
                         "site": [f"S{g}" for g in groups]})


DF = _frailty_df()
MAP = {"x": "t", "c": "c"}


# ---------------------------------------------------------------------------
# Registries
# ---------------------------------------------------------------------------

def test_the_new_models_are_registered():
    for key in ("beta", "beta4", "uniform"):
        assert key in fitting.DISTRIBUTIONS and fitting.DISTRIBUTIONS[key]["bounded"]
    for key in ("discretized_lognormal", "discretized_gamma", "discretized_loglogistic"):
        assert key in fitting.DISCRETE
    for key in ("additive_hazards", "proportional_odds", "buckley_james", "weibull_frailty",
                "exponential_frailty", "lognormal_frailty", "gamma_frailty", "cox_frailty"):
        assert key in fitting.REGRESSION_MODELS
    assert "royston_parmar" in fitting.FLEXIBLE
    # Already there before (#72): Rayleigh and the Gumbel / Logistic variants.
    assert {"rayleigh", "gumbel_ph", "logistic_aft", "gumbel_po", "logistic_ah"} <= {
        *fitting.DISTRIBUTIONS, *fitting.REGRESSION_MODELS}


def test_bounded_distributions_stay_out_of_best_fit_and_mixtures():
    assert not set(more_models.BOUNDED) & set(fitting.best_candidates())
    r = fitting.fit("best", DF, MAP)
    ids = {c["id"] for c in r["selection"]["candidates"]} | {f["id"] for f in r["selection"].get("failed", [])}
    assert not ids & {"beta", "beta4", "uniform"}
    with pytest.raises(FitError, match="can't be mixed"):
        fitting.fit("mixture", DF, MAP, options={"mixture": 2, "mixture_distribution": "beta"})


# ---------------------------------------------------------------------------
# Bounded and discretized distributions
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("key,dist,x", [
    ("beta", sp.Beta, np.random.default_rng(1).beta(2, 5, 40)),
    ("beta4", sp.Beta4, np.random.default_rng(3).beta(3, 4, 60) * 100 + 20),
    ("uniform", sp.Uniform, np.random.default_rng(1).uniform(10, 50, 30)),
])
def test_bounded_fits_match_surpyval(key, dist, x):
    r = fitting.fit(key, pd.DataFrame({"x": x}), {"x": "x"})
    direct = dist.fit(x)
    assert r["kind"] == "distribution"
    assert [p["value"] for p in r["params"]] == pytest.approx(list(direct.params), rel=1e-6)
    assert r["life"]["mttf"]["value"] == pytest.approx(float(direct.mean()), rel=1e-6)


def test_beta_refuses_data_outside_zero_to_one():
    with pytest.raises(FitError, match="between 0 and 1"):
        fitting.fit("beta", DF, MAP)


def test_bounded_params_rebuild_a_saved_model():
    out = fitting.result_from_params("uniform", [{"name": "a", "value": 10}, {"name": "b", "value": 50}])
    assert out["functions"]["curves"]["sf"][0] == pytest.approx(1.0)


@pytest.mark.parametrize("key,base", [("discretized_lognormal", sp.LogNormal),
                                      ("discretized_gamma", sp.Gamma),
                                      ("discretized_loglogistic", sp.LogLogistic)])
def test_discretized_fits_match_surpyval(key, base):
    k = np.maximum(np.ceil(np.random.default_rng(2).lognormal(2, 0.5, 60)), 1)
    r = fitting.fit(key, pd.DataFrame({"k": k}), {"x": "k"})
    direct = sp.Discretize(base).fit(k)
    assert r["kind"] == "discrete"
    assert [p["value"] for p in r["params"]] == pytest.approx(list(direct.params), rel=1e-6)
    aic = next(g["value"] for g in r["gof"] if g["id"] == "aic")
    assert aic == pytest.approx(direct.aic(), rel=1e-9)


def test_discretized_refuses_non_counts():
    with pytest.raises(FitError, match="whole-number"):
        fitting.fit("discretized_gamma", pd.DataFrame({"k": [1.5, 2, 3]}), {"x": "k"})


# ---------------------------------------------------------------------------
# Semi-parametric regressions
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("key,fitter", [("additive_hazards", sp.AdditiveHazards),
                                        ("proportional_odds", sp.ProportionalOdds),
                                        ("buckley_james", sp.BuckleyJames)])
def test_semi_parametric_coefficients_match_surpyval(key, fitter):
    r = fitting.fit(key, DF, MAP, covariates=["z", "temp"])
    direct = fitter.fit_from_df(DF, x_col="t", Z_cols=["z", "temp"], c_col="c")
    assert r["kind"] == "regression" and r["semi_parametric"]
    assert [c["value"] for c in r["coefficients"]] == pytest.approx(list(direct.beta), rel=1e-6)
    table = direct.summary().reset_index()
    assert [row["value"] for row in r["coef_table"]] == pytest.approx(list(table["coef"]), rel=1e-9)
    # The calculator's curves at the covariate means are SurPyval's.
    Z = pd.DataFrame({"z": [DF["z"].mean()], "temp": [DF["temp"].mean()]})
    x = np.asarray(r["functions"]["curves"]["x"])
    assert r["functions"]["curves"]["sf"] == pytest.approx(
        list(np.asarray(direct.sf(x, Z.round(4)), dtype=float)), abs=1e-6)


def test_additive_hazards_and_proportional_odds_report_wald_intervals_and_p_values():
    for key, fitter in (("additive_hazards", sp.AdditiveHazards), ("proportional_odds", sp.ProportionalOdds)):
        r = fitting.fit(key, DF, MAP, covariates=["z"])
        direct = fitter.fit_from_df(DF, x_col="t", Z_cols=["z"], c_col="c")
        se = float(np.asarray(direct.standard_errors())[0])
        assert r["coefficients"][0]["ci"] == pytest.approx(
            [direct.beta[0] - 1.959964 * se, direct.beta[0] + 1.959964 * se], rel=1e-4)
        assert r["coefficients"][0]["p"] == pytest.approx(float(direct.p_values[0]), rel=1e-9)


def test_buckley_james_has_bootstrap_intervals_and_no_hazard():
    r = fitting.fit("buckley_james", DF, MAP, covariates=["z", "temp"])
    direct = sp.BuckleyJames.fit_from_df(DF, x_col="t", Z_cols=["z", "temp"], c_col="c")
    boot = direct.bootstrap_ci(alpha_ci=0.05, n_boot=200, random_state=0)
    for c, expect in zip(r["coefficients"], boot.tolist()):
        assert c["ci"] == pytest.approx(expect, rel=1e-9)
    assert r["ci_method"].startswith("bootstrap")
    # No hazard or density on a Buckley-James model: not offered.
    assert [m["id"] for m in r["functions"]["meta"]] == ["sf", "ff", "Hf"]
    assert r["functions"]["curves"]["hf"] is None
    assert r["gof"] == [] and "no log-likelihood" in r["gof_note"]


def test_semi_parametric_models_refuse_data_they_cannot_take():
    with pytest.raises(FitError, match="interval-censored"):
        fitting.fit("additive_hazards", DF.assign(r=DF.t + 1), {"xl": "t", "xr": "r"}, covariates=["z"])
    with pytest.raises(FitError, match="truncated"):
        fitting.fit("buckley_james", DF.assign(e=0.0), {**MAP, "tl": "e"}, covariates=["z"])


def test_step_baselines_give_no_life_at_the_covariate_means():
    """As for Cox: a step-function baseline's B10 would be an event time."""
    for key in ("additive_hazards", "proportional_odds", "buckley_james"):
        assert "at_covariate_means" not in fitting.fit(key, DF, MAP, covariates=["z"])


# ---------------------------------------------------------------------------
# Shared frailty
# ---------------------------------------------------------------------------

FRAILTY_MAP = {**MAP, "group": "site"}


@pytest.mark.parametrize("key,fitter", [("weibull_frailty", sp.WeibullFrailty),
                                        ("lognormal_frailty", sp.LogNormalFrailty),
                                        ("cox_frailty", sp.CoxFrailty)])
def test_frailty_matches_surpyval(key, fitter):
    r = fitting.fit(key, DF, FRAILTY_MAP, covariates=["z", "temp"])
    direct = fitter.fit_from_df(DF, x_col="t", group_col="site", Z_cols=["z", "temp"], c_col="c")
    assert [c["value"] for c in r["coefficients"]] == pytest.approx(list(direct.beta), rel=1e-6)
    f = r["frailty"]
    assert f["theta"] == pytest.approx(direct.theta, rel=1e-6)
    method = "wald" if key == "cox_frailty" else "lr"
    assert f["theta_ci"] == pytest.approx(list(direct.param_cb("theta", method=method)), rel=1e-6)
    assert f["kendall_tau"] == pytest.approx(direct.kendall_tau, rel=1e-6)
    assert f["group_column"] == "site" and f["n_groups"] == 30
    assert {g["label"]: g["frailty"] for g in f["groups"]} == pytest.approx(dict(direct.frailties))
    if key != "cox_frailty":
        # The baseline by its own names, with SurPyval's interval.
        names = list(direct.dist.parameter_names)
        assert [p["name"] for p in r["params"]] == names
        assert r["params"][0]["ci"] == pytest.approx(list(direct.param_cb(names[0])), rel=1e-6)


def test_frailty_reading_says_when_groups_may_not_differ():
    assert "may not differ" in more_models.frailty_reading(0.01, [0.0, 0.4])
    assert "The groups differ" in more_models.frailty_reading(0.5, [0.2, 1.0])


def test_group_by_is_required_for_frailty_and_refused_elsewhere():
    with pytest.raises(FitError, match="needs a Group by column"):
        fitting.fit("weibull_frailty", DF, MAP, covariates=["z"])
    with pytest.raises(FitError, match="shared-frailty models only"):
        fitting.fit("weibull_ph", DF, FRAILTY_MAP, covariates=["z"])
    with pytest.raises(FitError, match="Group by applies"):
        fitting.fit("weibull", DF, FRAILTY_MAP)
    with pytest.raises(FitError, match="can't be a covariate"):
        fitting.fit("weibull_frailty", DF, {**MAP, "group": "z"}, covariates=["z"])


def test_frailty_refuses_left_censoring_in_surpyval_words():
    with pytest.raises(FitError, match="right-censored"):
        fitting.fit("cox_frailty", DF.assign(c=np.where(DF.c == 1, -1, 0)), FRAILTY_MAP, covariates=["z"])


# ---------------------------------------------------------------------------
# Royston-Parmar
# ---------------------------------------------------------------------------

def test_royston_parmar_matches_surpyval():
    r = fitting.fit("royston_parmar", DF, MAP, unit="hours")
    direct = sp.RoystonParmar.fit(x=DF.t.to_numpy(float), c=DF.c.to_numpy(float))
    assert r["kind"] == "flexible"
    assert [p["value"] for p in r["params"]] == pytest.approx(list(direct.params), rel=1e-6)
    aic = next(g["value"] for g in r["gof"] if g["id"] == "aic")
    assert aic == pytest.approx(direct.aic(), rel=1e-9)
    assert r["life"]["mttf"]["value"] == pytest.approx(float(direct.mean()), rel=1e-4)
    # The data's own Kaplan-Meier curve rides along to read the fit against.
    km = sp.KaplanMeier.fit(x=DF.t.to_numpy(float), c=DF.c.to_numpy(float))
    assert r["estimate"]["R"] == pytest.approx(list(km.R), rel=1e-9)
    assert r["spline"]["n_terms"] == 3


def test_royston_parmar_confidence_and_life_from_the_live_model():
    r = fitting.fit("royston_parmar", DF, MAP)
    mid = r["functions"]["model_id"]
    cb = fitting.confidence_bounds(mid, on="sf", alpha_ci=0.1)
    direct = sp.RoystonParmar.fit(x=DF.t.to_numpy(float), c=DF.c.to_numpy(float))
    i = 100
    expect = np.asarray(direct.cb(np.array([cb["x"][i]]), on="sf", alpha_ci=0.1), dtype=float).ravel()
    assert [cb["lower"][i], cb["upper"][i]] == pytest.approx(list(expect), rel=1e-6)


# ---------------------------------------------------------------------------
# REST API: picker, fit, save, re-evaluate
# ---------------------------------------------------------------------------

def _client(monkeypatch):
    from fastapi.testclient import TestClient

    from backend import config, db
    from backend.auth import get_current_user
    from backend.main import app

    test_db = mongomock.MongoClient()["reliafy_more_models"]
    monkeypatch.setattr(config, "AUTH_DISABLED", False)
    monkeypatch.setattr(config, "BILLING_ENABLED", False)
    monkeypatch.setattr(db, "_db", test_db)
    monkeypatch.setattr(db, "_simulated", True)
    app.dependency_overrides[get_current_user] = lambda: {
        "uid": A, "email": "a@x.com", "name": "A", "email_verified": True}
    return TestClient(app), app, test_db


def _csv(df: pd.DataFrame) -> bytes:
    buf = io.StringIO()
    df.to_csv(buf, index=False)
    return buf.getvalue().encode()


def test_picker_lists_the_new_models_with_their_flags(monkeypatch):
    client, app, _ = _client(monkeypatch)
    try:
        d = {m["id"]: m for m in client.get("/api/distributions").json()["distributions"]}
    finally:
        app.dependency_overrides.clear()
    assert d["beta"]["more"] and d["beta"]["bounded"] and not d["beta"]["covariates"]
    assert d["discretized_gamma"]["discrete"] and d["discretized_gamma"]["more"]
    assert d["royston_parmar"]["flexible"] and not d["royston_parmar"]["covariates"]
    assert d["weibull_frailty"]["frailty"] and d["weibull_frailty"]["covariates"]
    assert d["buckley_james"]["semi"] and d["buckley_james"]["effect"] == "aft"
    assert "beta" not in {m["id"] for m in d["mixture"]["mixture_distributions"]}
    assert "more" not in d["weibull"]


def test_frailty_fits_saves_and_reevaluates_through_the_api(monkeypatch):
    client, app, _ = _client(monkeypatch)
    form = {"x": "t", "c": "c", "group": "site", "z": ["z", "temp"], "c_invert": "0"}
    files = {"file": ("sites.csv", _csv(DF), "text/csv")}
    try:
        r = client.post("/api/fit/weibull_frailty", data=form, files=files)
        assert r.status_code == 200, r.text
        assert r.json()["frailty"]["n_groups"] == 30
        bad = client.post("/api/fit/weibull_ph", data=form, files={"file": ("s.csv", _csv(DF), "text/csv")})
        assert bad.status_code == 422 and "shared-frailty" in bad.json()["detail"]

        saved = client.post("/api/models", data={**form, "name": "Sites", "distribution": "weibull_frailty"},
                            files={"file": ("sites.csv", _csv(DF), "text/csv")})
        assert saved.status_code == 200, saved.text
        mid = saved.json()["id"]
        detail = client.get(f"/api/models/{mid}").json()
        assert detail["spec"]["mapping"]["group"] == "site"
        # The calculator refits from the spec, Group by included.
        from backend import fitting as f

        f._MODEL_STORE.clear()
        from backend.services import models as ms

        ms._LIVE.clear()
        ev = client.post(f"/api/models/{mid}/evaluate", json={"z": 1, "temp": 50})
        assert ev.status_code == 200, ev.text
        direct = sp.WeibullFrailty.fit_from_df(DF, x_col="t", group_col="site", Z_cols=["z", "temp"], c_col="c")
        x = np.asarray(ev.json()["curves"]["x"])
        assert ev.json()["curves"]["sf"] == pytest.approx(
            list(direct.sf(x, pd.DataFrame({"z": [1.0], "temp": [50.0]}))), abs=1e-6)
    finally:
        app.dependency_overrides.clear()


def test_royston_parmar_saved_model_has_bounds_life_and_exact_values(monkeypatch):
    client, app, test_db = _client(monkeypatch)
    try:
        saved = client.post("/api/models", data={"x": "t", "c": "c", "c_invert": "0", "name": "RP",
                                                 "distribution": "royston_parmar"},
                            files={"file": ("rp.csv", _csv(DF[["t", "c"]]), "text/csv")})
        assert saved.status_code == 200, saved.text
        mid = saved.json()["id"]
        res = client.get(f"/api/models/{mid}").json()["results"]
        assert res["kind"] == "flexible"
        assert res["functions"]["confidence_path"] == f"/api/models/{mid}/confidence"
        assert client.post(f"/api/models/{mid}/confidence", json={"on": "sf"}).status_code == 200
        life = client.post(f"/api/models/{mid}/life", json={"confidence": 0.9})
        assert life.status_code == 200 and life.json()["b_lives"]
        from backend.services import models as ms

        model = ms.get_model(test_db, mid, A)
        ev = ms.evaluate_at(test_db, model, [5.0, 25.0], A)
        direct = sp.RoystonParmar.fit(x=DF.t.to_numpy(float), c=DF.c.to_numpy(float))
        assert ev["method"] == "exact"
        assert ev["values"]["sf"] == pytest.approx(list(direct.sf(np.array([5.0, 25.0]))), rel=1e-6)
    finally:
        app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# Degradation: the induced (Lu-Meeker) life distribution
# ---------------------------------------------------------------------------

def _deg_df() -> pd.DataFrame:
    rng = np.random.default_rng(1)
    x = np.tile(np.arange(100.0, 1100.0, 100.0), 8)
    i = np.repeat(np.arange(8), 10)
    a = np.repeat(rng.normal(10.0, 3.0, 8), 10)
    b = np.repeat(rng.normal(0.3, 0.05, 8), 10)
    y = a + b * x + rng.normal(0, 3.0, x.size)
    return pd.DataFrame({"item": [f"u{k}" for k in i], "hours": x, "wear": np.round(y, 4)})


def test_induced_life_matches_surpyval():
    from surpyval.degradation import DegradationAnalysis

    from backend import degradation_induced

    df = _deg_df()
    live = DegradationAnalysis.fit(df.hours.to_numpy(), df.wear.to_numpy(), df.item.to_numpy(), threshold=450)
    out = degradation_induced.induced_life(live, times=[1400.0], reliability=[0.9])
    direct = live.induced_life(n_samples=10_000, random_state=0)
    assert out["available"]
    assert out["mean"] == pytest.approx(direct.mean())
    assert out["median"] == pytest.approx(float(direct.qf(np.array([0.5]))[0]))
    assert out["at_times"][0]["reliability"] == pytest.approx(float(direct.sf(np.array([1400.0]))[0]))
    assert out["at_reliability"][0]["t"] == pytest.approx(float(direct.qf(np.array([0.1]))[0]))
    assert out["prob_never_fails"] == pytest.approx(direct.prob_never_fails)
    grid = np.asarray(out["curve"]["x"])
    assert out["curve"]["life_sf"] == pytest.approx(list(np.asarray(live.sf(grid), dtype=float)), abs=1e-9)
    with pytest.raises(ValueError, match="from 0 to 1"):
        degradation_induced.induced_life(live, reliability=[1.5])


def test_induced_life_endpoint(monkeypatch):
    client, app, _ = _client(monkeypatch)
    try:
        r = client.post("/api/degradation/models", data={
            "name": "Wear", "i": "item", "x": "hours", "y": "wear", "threshold": "450", "path": "linear"},
            files={"file": ("wear.csv", _csv(_deg_df()), "text/csv")})
        assert r.status_code == 200, r.text
        mid = r.json()["id"]
        out = client.post(f"/api/degradation/models/{mid}/induced-life", json={"times": [1400]})
        assert out.status_code == 200, out.text
        body = out.json()
        assert body["available"] and len(body["curve"]["x"]) == 200 and body["at_times"][0]["reliability"] > 0
        assert client.post(f"/api/degradation/models/{mid}/induced-life",
                           json={"reliability": [2]}).status_code == 422
        assert client.post("/api/degradation/models/nope/induced-life", json={}).status_code == 404
        # The degradation picker leaves the bounded distributions out.
        ids = {d["id"] for d in client.get("/api/degradation/options").json()["distributions"]}
        assert "weibull" in ids and not ids & {"beta", "beta4", "uniform"}
    finally:
        app.dependency_overrides.clear()
