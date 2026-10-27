"""Regression families beyond the first batch, and Best fit's score choice.

* Log-logistic baselines for proportional hazards, accelerated failure time,
  proportional odds and additive hazards (SurPyval's generic PH / AFT / PO /
  AH on LogLogistic).
* The shared frailty's own distribution: gamma (default) or log-normal.
* The model's own assumption checks (SurPyval's ``diagnose()``) for every
  regression family but Cox, which keeps its own.
* Best fit ranked by AIC, AICc, BIC or negative log-likelihood, with each
  candidate's parameter count and delta, and guidance in words.

Every number is checked against SurPyval called directly.
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
from backend.tests.test_more_models import DF as SITES  # noqa: E402

A = "user-a"
TRUE_BETA = 2.0
TRUE_COEF = {"temp": 0.04, "load": -0.6}


def _loglogistic_df(n: int = 1500, seed: int = 11) -> pd.DataFrame:
    """Log-logistic times (shape 2) whose scale falls as temperature rises
    and as load rises: an accelerated-failure-time truth."""
    rng = np.random.default_rng(seed)
    temp = rng.normal(0, 1, n)
    load = rng.binomial(1, 0.5, n)
    u = rng.uniform(size=n)
    base = 30.0 * (u / (1 - u)) ** (1 / TRUE_BETA)  # log-logistic(alpha=30, beta=2)
    t = base * np.exp(TRUE_COEF["temp"] * temp + TRUE_COEF["load"] * load) ** 1.0
    c = (t > 80).astype(int)
    return pd.DataFrame({"t": np.round(np.minimum(t, 80), 4), "c": c, "temp": temp, "load": load,
                         "site": np.random.default_rng(seed).integers(0, 12, n)})


DF = _loglogistic_df()
MAP = {"x": "t", "c": "c"}
COVS = ["temp", "load"]


# ---------------------------------------------------------------------------
# Log-logistic baselines
# ---------------------------------------------------------------------------

LOGLOG = {"loglogistic_ph": ("hazard", sp.PH), "loglogistic_aft": ("aft", sp.AFT),
          "loglogistic_po": ("odds", sp.PO), "loglogistic_ah": ("additive", sp.AH)}


def test_the_loglogistic_baselines_are_registered_with_their_effect():
    for key, (effect, _) in LOGLOG.items():
        entry = fitting.REGRESSION_MODELS[key]
        assert entry["effect"] == effect and entry["name"].startswith("LogLogistic ")
        assert not entry.get("more")  # everyday models, beside Weibull and lognormal


@pytest.mark.parametrize("key", list(LOGLOG))
def test_loglogistic_regressions_match_surpyval(key):
    _, maker = LOGLOG[key]
    r = fitting.fit(key, DF, MAP, covariates=COVS)
    direct = maker(sp.LogLogistic).fit_from_df(DF, x_col="t", c_col="c", Z_cols=COVS)
    assert r["kind"] == "regression" and r["distribution_id"] == key
    got = [p["value"] for p in r["params"]] + [c["value"] for c in r["coefficients"]]
    assert got == pytest.approx(list(direct.params), rel=1e-6)
    assert [p["name"] for p in r["params"]] == ["alpha", "beta"]
    assert {g["id"]: g["value"] for g in r["gof"]}["aic"] == pytest.approx(direct.aic(), rel=1e-6)
    assert r["functions"]["curves"]["sf"][0] == pytest.approx(1.0, abs=1e-6)


def test_loglogistic_aft_recovers_the_truth():
    r = fitting.fit("loglogistic_aft", DF, MAP, covariates=COVS)
    beta = next(p["value"] for p in r["params"] if p["name"] == "beta")
    assert beta == pytest.approx(TRUE_BETA, rel=0.1)
    coefs = {c["name"]: c for c in r["coefficients"]}
    # SurPyval's AFT coefficient speeds time up: it is minus the log-time effect.
    for name, truth in TRUE_COEF.items():
        truth = -truth
        lo, hi = coefs[name]["ci"]
        assert lo < truth < hi, (name, truth, coefs[name])
    assert r["ratio_label"] == "time ratio"


def test_loglogistic_proportional_odds_is_the_same_model_as_aft():
    """For the log-logistic, odds of failure scale as (t/alpha)^beta: PO and
    AFT are one model, with the PO coefficient = -beta x the AFT coefficient."""
    aft = fitting.fit("loglogistic_aft", DF, MAP, covariates=COVS)
    po = fitting.fit("loglogistic_po", DF, MAP, covariates=COVS)
    beta = next(p["value"] for p in aft["params"] if p["name"] == "beta")
    for a, p in zip(aft["coefficients"], po["coefficients"]):
        assert p["value"] == pytest.approx(-beta * a["value"], rel=1e-3)
    aic = lambda r: {g["id"]: g["value"] for g in r["gof"]}["aic"]  # noqa: E731
    assert aic(aft) == pytest.approx(aic(po), abs=1e-3)


def test_loglogistic_regression_takes_covariates_that_change_over_time():
    rows = []
    rng = np.random.default_rng(5)
    for unit in range(120):
        life = float(np.exp(rng.logistic() * 0.5 + 3))
        stop = min(life, 40.0)
        cut = stop / 2
        rows += [{"unit": unit, "start": 0.0, "end": cut, "failed": 1, "load": float(rng.integers(0, 2))},
                 {"unit": unit, "start": cut, "end": stop, "failed": 0 if life <= 40.0 else 1,
                  "load": float(rng.integers(0, 2))}]
    df = pd.DataFrame(rows)
    r = fitting.fit("loglogistic_ph", df, {"i": "unit", "xl": "start", "xr": "end", "c": "failed"},
                    covariates=["load"])
    assert r["kind"] == "regression" and r.get("tvc")


# ---------------------------------------------------------------------------
# Shared frailty: gamma or log-normal
# ---------------------------------------------------------------------------

SMAP = {"x": "t", "c": "c", "group": "site"}


@pytest.mark.parametrize("key,baseline", [("weibull_frailty", sp.Weibull), ("lognormal_frailty", sp.LogNormal)])
def test_lognormal_frailty_matches_surpyval(key, baseline):
    r = fitting.fit(key, SITES, SMAP, covariates=["z"], options={"frailty_family": "lognormal"})
    direct = sp.Frailty(baseline, family="lognormal").fit_from_df(
        SITES, x_col="t", group_col="site", Z_cols=["z"], c_col="c")
    assert r["frailty"]["family"] == "lognormal"
    assert r["frailty"]["theta"] == pytest.approx(direct.theta, rel=1e-5)
    assert r["coefficients"][0]["value"] == pytest.approx(direct.beta[0], rel=1e-5)
    assert r["options"] == {"frailty_family": "lognormal"}
    gamma = fitting.fit(key, SITES, SMAP, covariates=["z"])
    assert gamma["frailty"]["family"] == "gamma" and "options" not in gamma


def test_frailty_family_is_refused_where_it_does_not_apply():
    with pytest.raises(FitError, match="gamma frailty only"):
        fitting.fit("cox_frailty", SITES, SMAP, covariates=["z"], options={"frailty_family": "lognormal"})
    with pytest.raises(FitError, match="shared-frailty models only"):
        fitting.fit("weibull_ph", SITES, MAP, covariates=["z"], options={"frailty_family": "lognormal"})
    with pytest.raises(FitError, match="shared-frailty models only"):
        fitting.fit("weibull", SITES, MAP, options={"frailty_family": "gamma"})
    with pytest.raises(FitError, match="'gamma' or 'lognormal'"):
        fitting.fit("weibull_frailty", SITES, SMAP, covariates=["z"], options={"frailty_family": "cauchy"})
    # The default is the gamma, spelled out.
    assert fitting.fit("weibull_frailty", SITES, SMAP, covariates=["z"],
                       options={"frailty_family": "gamma"})["frailty"]["family"] == "gamma"


# ---------------------------------------------------------------------------
# The model's own checks
# ---------------------------------------------------------------------------

def _checks(key, df=DF, mapping=MAP, covs=COVS):
    return fitting.fit(key, df, mapping, covariates=covs)["diagnostics"]["model_checks"]


@pytest.mark.parametrize("key,check", [
    ("weibull_aft", "functional_form"),
    ("weibull_po", "proportional_odds"),
    ("weibull_ah", "constant_effects"),
    ("proportional_odds", "proportional_odds"),
    ("additive_hazards", "constant_effects"),
    ("loglogistic_aft", "functional_form"),
])
def test_model_checks_are_surpyvals_diagnose(key, check):
    mc = _checks(key)
    assert mc["available"] and mc["rows"]
    assert check in {r["check"] for r in mc["rows"]}
    for row in mc["rows"]:
        assert row["verdict"] in ("ok", "warn", "fail") and row["title"] and row["detail"]
        assert row["p"] is None or 0.0 <= row["p"] <= 1.0
    assert mc["reading"] and isinstance(mc["ok"], bool)


def test_model_checks_equal_the_libraries_own_report():
    model = sp.WeibullPO.fit_from_df(DF, x_col="t", c_col="c", Z_cols=COVS)
    table = model.diagnose().to_dict()["table"]
    mc = _checks("weibull_po")
    assert [(r["check"], round(r["statistic"], 6)) for r in mc["rows"]] == [
        (t["check"], round(t["statistic"], 6)) for t in table]


def test_a_misspecified_baseline_is_flagged_with_something_to_try():
    rng = np.random.default_rng(2)
    n = 600
    z = rng.normal(size=n)
    t = np.exp(rng.normal(1.5, 0.9, n) + 0.4 * z)  # lognormal, fitted as Weibull
    df = pd.DataFrame({"t": t, "c": np.zeros(n, dtype=int), "z": z})
    mc = _checks("weibull_aft", df, MAP, ["z"])
    assert not mc["ok"] or any(r["verdict"] == "warn" for r in mc["rows"])
    assert any(a["check"] == "error_distribution" for a in mc["advice"])
    assert "AFT fits better" in " ".join(r["detail"] for r in mc["rows"])


def test_model_checks_for_frailty_and_the_models_without_any():
    mc = fitting.fit("weibull_frailty", SITES, SMAP, covariates=["z"])["diagnostics"]["model_checks"]
    assert mc["available"] and "frailty_variance" in {r["check"] for r in mc["rows"]}
    bj = _checks("buckley_james")
    assert bj["available"] is False and "no assumption checks" in bj["reason"]
    # Cox keeps its own tests; no second set beside them.
    cox = fitting.fit("cox_ph", DF, MAP, covariates=COVS)["diagnostics"]
    assert "model_checks" not in cox and cox["ph_test"]["available"]


def test_model_checks_survive_json():
    import json

    r = fitting.fit("weibull_ah", DF, MAP, covariates=COVS)
    json.dumps(r["diagnostics"], allow_nan=False)


# ---------------------------------------------------------------------------
# Best fit's score
# ---------------------------------------------------------------------------

BEST_DF = pd.DataFrame({"t": np.round(np.random.default_rng(3).weibull(1.8, 80) * 100, 3)})
BEST_MAP = {"x": "t"}


@pytest.mark.parametrize("criterion", ["aic", "aic_c", "bic", "neg_ll"])
def test_best_fit_ranks_by_the_chosen_score(criterion):
    opts = None if criterion == "aic" else {"criterion": criterion}
    r = fitting.fit("best", BEST_DF, BEST_MAP, options=opts)
    sel = r["selection"]
    assert sel["criterion"] == criterion and sel["criterion_label"]
    rows = sel["candidates"]
    assert len(rows) >= 8
    values = [row[criterion] for row in rows]
    assert values == sorted(values)
    assert rows[0]["delta"] == 0 and all(row["delta"] >= 0 for row in rows)
    assert all(row["k"] >= 1 for row in rows)
    # The winner is what was saved as the fit.
    assert r["distribution_id"] == rows[0]["id"]
    # Each score is SurPyval's own on that distribution.
    for row in rows[:3]:
        entry = fitting.DISTRIBUTIONS[row["id"]]
        direct = entry["dist"].fit(x=BEST_DF["t"].to_numpy())
        expect = {"aic": direct.aic(), "aic_c": direct.aic_c(), "bic": direct.bic(),
                  "neg_ll": -direct.log_likelihood}[criterion]
        assert row[criterion] == pytest.approx(expect, rel=1e-6)
        assert row["k"] == np.atleast_1d(direct.params).size


def test_best_fit_defaults_to_aic_and_says_nothing_extra():
    r = fitting.fit("best", BEST_DF, BEST_MAP)
    assert r["selection"]["criterion"] == "aic"
    assert "criterion" not in (r.get("options") or {})


def test_best_fit_criterion_is_refused_elsewhere_and_when_unknown():
    with pytest.raises(FitError, match="choose Best fit"):
        fitting.fit("weibull", BEST_DF, BEST_MAP, options={"criterion": "bic"})
    with pytest.raises(FitError, match="criterion must be one of"):
        fitting.fit("best", BEST_DF, BEST_MAP, options={"criterion": "r2"})
    assert fitting.fit("best", BEST_DF, BEST_MAP, options={"criterion": "AICc"})["selection"]["criterion"] == "aic_c"


def test_best_fit_respects_censoring_and_says_what_it_skipped():
    rng = np.random.default_rng(8)
    t = rng.weibull(2.0, 60) * 50
    df = pd.DataFrame({"t": t, "c": (t > 55).astype(int)})
    r = fitting.fit("best", df, {"x": "t", "c": "c"}, options={"criterion": "bic"})
    assert r["selection"]["candidates"][0]["delta"] == 0
    # Negative times can't be fitted by anything on the positive half-line.
    bad = pd.DataFrame({"t": [-5.0, 3, 8, 12, 20, 25, 31, 40]})
    r = fitting.fit("best", bad, {"x": "t"})
    skipped = {f["id"]: f["reason"] for f in r["selection"].get("failed", [])}
    assert skipped and all(reason for reason in skipped.values())
    assert {c["id"] for c in r["selection"]["candidates"]} <= {"normal", "gumbel", "logistic", "gumbel_lev"}


def test_best_fit_guidance_in_words():
    neg = fitting.fit("best", BEST_DF, BEST_MAP, options={"criterion": "neg_ll"})
    assert any("does not penalise extra parameters" in g for g in neg["selection"]["guidance"])
    rows = [{"id": "a", "name": "Alpha", "k": 3, "aic": 100.0}, {"id": "b", "name": "Beta", "k": 2, "aic": 101.0},
            {"id": "c", "name": "Gamma", "k": 2, "aic": 120.0}]
    notes = fitting.best_fit_guidance(rows, "aic", failures=40)
    assert len(notes) == 1 and "within 2 AIC" in notes[0] and "Beta has fewer parameters" in notes[0]
    few = fitting.best_fit_guidance(rows, "aic", failures=6)
    assert any("3 parameters and only 6 failures" in n for n in few)
    assert fitting.best_fit_guidance([{"id": "c", "name": "Gamma", "k": 2, "aic": 1.0}], "aic", 3) == []
    lonely = fitting.best_fit_guidance(rows[:1], "aic_c", failures=2)
    assert any("AICc needs more failures" in n for n in lonely)


def test_best_fit_with_mixtures_still_ranks_singles_by_the_chosen_score():
    r = fitting.fit("best", BEST_DF, BEST_MAP, options={"criterion": "bic", "include_mixtures": True})
    sel = r["selection"]
    assert sel["criterion"] == "bic" and sel["mixture_criterion"] == "bic"
    singles = [c for c in sel["candidates"] if "mixture" not in c]
    assert [c["bic"] for c in singles] == sorted(c["bic"] for c in singles)


# ---------------------------------------------------------------------------
# REST and MCP
# ---------------------------------------------------------------------------

def _client(monkeypatch):
    from fastapi.testclient import TestClient

    from backend import config, db
    from backend.auth import get_current_user
    from backend.main import app

    test_db = mongomock.MongoClient()["reliafy_regression_families"]
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


def test_picker_lists_the_loglogistic_models_by_effect(monkeypatch):
    client, app, _ = _client(monkeypatch)
    try:
        d = {m["id"]: m for m in client.get("/api/distributions").json()["distributions"]}
    finally:
        app.dependency_overrides.clear()
    for key, (effect, _) in LOGLOG.items():
        assert d[key]["effect"] == effect and d[key]["covariates"] and "more" not in d[key]
    assert d["loglogistic_ph"]["tvc"]


def test_rest_fit_save_and_refit_with_a_frailty_family_and_a_best_fit_score(monkeypatch):
    client, app, test_db = _client(monkeypatch)
    try:
        form = {"x": "t", "c": "c", "group": "site", "z": ["z"], "c_invert": "0"}
        files = lambda: {"file": ("s.csv", _csv(SITES), "text/csv")}  # noqa: E731
        r = client.post("/api/fit/weibull_frailty", data={**form, "frailty_family": "lognormal"}, files=files())
        assert r.status_code == 200, r.text
        assert r.json()["frailty"]["family"] == "lognormal"
        bad = client.post("/api/fit/cox_frailty", data={**form, "frailty_family": "lognormal"}, files=files())
        assert bad.status_code == 422 and "gamma frailty only" in bad.json()["detail"]

        saved = client.post("/api/models", data={**form, "name": "S", "distribution": "weibull_frailty",
                                                 "frailty_family": "lognormal"}, files=files())
        assert saved.status_code == 200, saved.text
        mid = saved.json()["id"]
        assert client.get(f"/api/models/{mid}").json()["spec"]["options"] == {"frailty_family": "lognormal"}
        from backend import fitting as f
        from backend.services import models as ms

        f._MODEL_STORE.clear()
        ms._LIVE.clear()  # the calculator refits from the spec, family included
        ev = client.post(f"/api/models/{mid}/evaluate", json={"z": 1})
        assert ev.status_code == 200, ev.text
        direct = sp.Frailty(sp.Weibull, family="lognormal").fit_from_df(
            SITES, x_col="t", group_col="site", Z_cols=["z"], c_col="c")
        x = np.asarray(ev.json()["curves"]["x"])
        assert ev.json()["curves"]["sf"] == pytest.approx(
            list(direct.sf(x, pd.DataFrame({"z": [1.0]}))), abs=1e-6)

        best = client.post("/api/fit/best", data={"x": "t", "criterion": "bic"},
                           files={"file": ("b.csv", _csv(BEST_DF), "text/csv")})
        assert best.status_code == 200, best.text
        assert best.json()["selection"]["criterion"] == "bic"
        refused = client.post("/api/fit/weibull", data={"x": "t", "criterion": "bic"},
                              files={"file": ("b.csv", _csv(BEST_DF), "text/csv")})
        assert refused.status_code == 422 and "Best fit" in refused.json()["detail"]

        # A saved Best fit keeps how it was chosen, and the winner is its model.
        kept = client.post("/api/models", data={"x": "t", "name": "Best", "distribution": "best",
                                                "criterion": "aic_c"},
                           files={"file": ("b.csv", _csv(BEST_DF), "text/csv")})
        assert kept.status_code == 200, kept.text
        detail = kept.json()
        assert detail["results"]["selection"]["criterion"] == "aic_c"
        assert detail["results"]["distribution_id"] == detail["results"]["selection"]["candidates"][0]["id"]
    finally:
        app.dependency_overrides.clear()


def test_the_v1_schema_carries_the_new_arguments(monkeypatch):
    client, app, _ = _client(monkeypatch)
    try:
        spec = client.get("/api/v1/openapi.json").json()
    finally:
        app.dependency_overrides.clear()
    text = str(spec)
    assert "frailty_family" in text and "'criterion'" in text
