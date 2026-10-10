"""Confidence bands and B-lives of a regression model at chosen covariates
(#54): the calculator's band and life card, the REST endpoints and MCP's
reliability_at — every number checked against SurPyval called directly."""

import io

import matplotlib

matplotlib.use("Agg")

import mongomock
import numpy as np
import pandas as pd
import pytest

from backend import fitting, more_models, regression_bands
from backend.fitting import REGRESSION_MODELS, FitError, fit

OWNER = "user-a"
MAPPING = {"x": "week", "c": "c"}
COVS = ["fin", "age", "prio"]


def _rossi() -> pd.DataFrame:
    from surpyval.datasets import load_rossi_static

    df = load_rossi_static()[["week", "arrest", "fin", "age", "prio"]].copy()
    df["c"] = 1 - df["arrest"]  # Reliafy: 0 = failed, 1 = still running
    return df


def _csv(df: pd.DataFrame) -> bytes:
    return df.to_csv(index=False).encode()


def _direct(dist="weibull_ph"):
    return REGRESSION_MODELS[dist]["fitter"].fit_from_df(_rossi(), x_col="week", c_col="c", Z_cols=COVS)


ROW = {"fin": 1, "age": 30, "prio": 2}
Z = pd.DataFrame({"fin": [1.0], "age": [30.0], "prio": [2.0]})


# ---- The band ------------------------------------------------------------------

@pytest.mark.parametrize("bound", ["two-sided", "lower", "upper"])
def test_band_is_surpyvals_cb_at_the_covariates(bound):
    r = fit("weibull_ph", _rossi(), MAPPING, covariates=COVS)
    out = fitting.confidence_bounds(r["functions"]["model_id"], on="sf", alpha_ci=0.1, bound=bound, values=ROW)
    x = np.asarray(out["x"])
    inner = x > 0  # at t = 0 the reliability is 1, certainly: the bound is the value
    want = np.asarray(_direct().cb(x[inner], Z, on="sf", alpha_ci=0.1, bound=bound), dtype=float)
    if bound == "two-sided":
        assert np.allclose(np.asarray(out["lower"])[inner], want[:, 0])
        assert np.allclose(np.asarray(out["upper"])[inner], want[:, 1])
    else:
        side = out["lower"] if bound == "lower" else out["upper"]
        assert out["upper" if bound == "lower" else "lower"] is None
        assert np.allclose(np.asarray(side)[inner], want)
    assert (out["lower"] or out["upper"])[0] == pytest.approx(1.0)


def test_band_follows_the_covariates_and_defaults_the_rest():
    r = fit("weibull_ph", _rossi(), MAPPING, covariates=COVS)
    mid = r["functions"]["model_id"]
    young = fitting.confidence_bounds(mid, values={"age": 20})
    old = fitting.confidence_bounds(mid, values={"age": 45})
    # Older at release, lower hazard (age's coefficient is negative): a higher band.
    assert old["lower"][150] > young["lower"][150]
    # Covariates left out take the fit's defaults, as the calculator's curves do.
    fields = fitting._MODEL_STORE[mid]["fields"]
    defaults = {f["name"]: f["default"] for f in fields}
    assert fitting.confidence_bounds(mid, values={}) == fitting.confidence_bounds(mid, values=defaults)


# The regressions of #179 (semi-parametric, shared frailty) have none: below.
@pytest.mark.parametrize("dist", [d for d in REGRESSION_MODELS if d != "cox_ph" and d not in more_models.REGRESSION])
def test_every_parametric_family_has_a_band(dist):
    r = fit(dist, _rossi(), MAPPING, covariates=COVS)
    assert regression_bands.result_has_bands(r)
    out = fitting.confidence_bounds(r["functions"]["model_id"], on="sf", alpha_ci=0.1, values=ROW)
    lo, hi = out["lower"][100], out["upper"][100]
    assert lo is not None and hi is not None and lo <= hi


@pytest.mark.parametrize("dist", list(more_models.REGRESSION))
def test_more_regressions_have_no_band_and_say_why(dist):
    """SurPyval bounds neither the curves nor the quantiles of the
    semi-parametric and shared-frailty regressions: no band or life path,
    and the notes name them rather than Cox PH."""
    df = _rossi()
    df["grp"] = (df.index % 20).astype(str)
    mapping = {**MAPPING, "group": "grp"} if more_models.REGRESSION[dist].get("frailty") else MAPPING
    r = fit(dist, df, mapping, covariates=COVS)
    assert not regression_bands.result_has_bands(r)
    notes = regression_bands.notes(r)
    assert "Cox PH" not in notes["bands_note"] and "No B-lives" in notes["life_note"]
    with pytest.raises(FitError, match="doesn't bound"):
        fitting.confidence_bounds(r["functions"]["model_id"], values=ROW)
    entry = fitting._MODEL_STORE[r["functions"]["model_id"]]
    with pytest.raises(ValueError, match="No B-lives"):
        regression_bands.life_answer(entry["model"], entry["fields"], {})


def test_cox_has_no_band_and_says_why():
    r = fit("cox_ph", _rossi(), MAPPING, covariates=COVS)
    assert not regression_bands.result_has_bands(r)
    notes = regression_bands.notes(r)
    assert "semi-parametric" in notes["bands_note"] and "B-lives" in notes["life_note"]
    with pytest.raises(FitError, match="semi-parametric"):
        fitting.confidence_bounds(r["functions"]["model_id"], values=ROW)
    entry = fitting._MODEL_STORE[r["functions"]["model_id"]]
    with pytest.raises(ValueError, match="No B-lives"):
        regression_bands.life_answer(entry["model"], entry["fields"], {})


def test_plain_distributions_are_unchanged():
    r = fit("weibull", _rossi(), MAPPING)
    assert regression_bands.notes(r) == {} and not regression_bands.result_has_bands(r)
    out = fitting.confidence_bounds(r["functions"]["model_id"], values={"ignored": 1})
    assert out["lower"] and out["upper"]


# ---- B-lives at the covariates ---------------------------------------------------

def test_life_is_surpyvals_qf_quantile_cb_and_mean():
    r = fit("weibull_ph", _rossi(), MAPPING, covariates=COVS)
    entry = fitting._MODEL_STORE[r["functions"]["model_id"]]
    out = regression_bands.life_answer(entry["model"], entry["fields"], {"covariates": ROW, "confidence": 0.9})
    m = _direct()
    probs = np.array([0.01, 0.05, 0.10, 0.50])
    assert [b["label"] for b in out["b_lives"]] == ["B1", "B5", "B10", "B50"]
    assert np.allclose([b["value"] for b in out["b_lives"]], m.qf(probs, Z))
    lower = [float(np.ravel(m.quantile_cb(np.array([p]), Z, alpha_ci=0.1, bound="lower"))[0]) for p in probs]
    assert np.allclose([b["lower"] for b in out["b_lives"]], lower)
    # SurPyval 0.23's mean life at a constant row: the path integral.
    from surpyval.univariate.regression.tvc_schedule import StepSchedule

    assert out["mttf"]["value"] == pytest.approx(float(m.mean_tvc(StepSchedule.constant(Z.to_numpy(dtype=float)[0]))))
    assert out["mttf"]["lower"] is None  # SurPyval has no mean_cb for a regression model
    assert out["covariates"] == {"fin": 1.0, "age": 30.0, "prio": 2.0}


def test_time_at_reliability_two_sided():
    r = fit("weibull_aft", _rossi(), MAPPING, covariates=COVS)
    entry = fitting._MODEL_STORE[r["functions"]["model_id"]]
    out = regression_bands.life_answer(entry["model"], entry["fields"], {
        "covariates": ROW, "reliability": [0.9], "confidence": 0.95, "bound": "two-sided"})
    m = _direct("weibull_aft")
    lo, hi = np.ravel(m.quantile_cb(np.array([0.1]), Z, alpha_ci=0.05, bound="two-sided"))
    pt = out["points"][0]
    assert pt["time"] == pytest.approx(float(m.qf(np.array([0.1]), Z)[0]))
    assert (pt["lower"], pt["upper"]) == (pytest.approx(lo), pytest.approx(hi))


def test_a_row_that_never_fails_has_no_mttf():
    class NeverZero:
        def qf(self, p, Z):
            return np.asarray(p) * 10

        def quantile_cb(self, p, Z, alpha_ci=0.05, bound="two-sided"):
            return np.asarray(p) * 5

        def cb(self, *a, **k):
            pass

        def mean(self, Z):
            import warnings

            warnings.warn("The survival along this path has not fallen to 0: it is still …", UserWarning)
            return 1e15

    out = regression_bands.life_answer(NeverZero(), [], {"confidence": 0.9})
    assert out["mttf"]["value"] is None and "never falls to 0" in out["mttf_note"]


# ---- API ---------------------------------------------------------------------------

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
    app.dependency_overrides[get_current_user] = lambda: {"uid": OWNER, "email": "a@example.org", "name": "A"}
    tc = TestClient(app)
    tc.db = test_db
    try:
        yield tc
    finally:
        app.dependency_overrides.clear()


def _post_fit(client, dist, url="/api/fit/{d}", **extra):
    return client.post(
        url.format(d=dist),
        data={"x": "week", "c": "c", "z": COVS, **extra},
        files={"file": ("rossi.csv", io.BytesIO(_csv(_rossi())), "text/csv")},
    )


def test_fresh_fit_band_and_life_endpoints(client):
    r = _post_fit(client, "weibull_ph")
    assert r.status_code == 200, r.text
    fns = r.json()["functions"]
    assert fns["confidence_path"].startswith("/api/confidence/") and fns["life_path"].startswith("/api/life/")

    band = client.post(fns["confidence_path"], json={"on": "sf", "alpha_ci": 0.1, "bound": "lower",
                                                     "values": ROW}).json()
    x = np.asarray(band["x"])
    want = _direct().cb(x[1:], Z, on="sf", alpha_ci=0.1, bound="lower")
    assert np.allclose(band["lower"][1:], want)

    life = client.post(fns["life_path"], json={"confidence": 0.9, "covariates": ROW}).json()
    assert life["b_lives"][2]["value"] == pytest.approx(float(_direct().qf(np.array([0.1]), Z)[0]))
    assert life["b_lives"][2]["lower"] < life["b_lives"][2]["value"]


def test_fresh_cox_fit_says_why_there_is_no_band(client):
    fns = _post_fit(client, "cox_ph").json()["functions"]
    assert "confidence_path" not in fns and "life_path" not in fns
    assert "semi-parametric" in fns["bands_note"] and "No B-lives" in fns["life_note"]


def test_saved_model_band_and_life(client):
    saved = client.post(
        "/api/models",
        data={"name": "Rossi PH", "distribution": "weibull_ph", "x": "week", "c": "c", "z": COVS},
        files={"file": ("rossi.csv", io.BytesIO(_csv(_rossi())), "text/csv")},
    ).json()
    fns = saved["results"]["functions"]
    assert fns["confidence_path"] == f"/api/models/{saved['id']}/confidence"
    assert fns["life_path"] == f"/api/models/{saved['id']}/life"
    band = client.post(fns["confidence_path"], json={"bound": "two-sided", "values": ROW}).json()
    x = np.asarray(band["x"])
    want = _direct().cb(x[1:], Z, on="sf", alpha_ci=0.05, bound="two-sided")
    assert np.allclose(band["lower"][1:], want[:, 0]) and np.allclose(band["upper"][1:], want[:, 1])
    life = client.post(fns["life_path"], json={"covariates": ROW, "reliability": [0.9]}).json()
    assert life["points"][0]["time"] == pytest.approx(float(_direct().qf(np.array([0.1]), Z)[0]))
    # A bad confidence is a clean 422.
    assert client.post(fns["life_path"], json={"confidence": 2, "covariates": ROW}).status_code == 422


# ---- MCP ---------------------------------------------------------------------------

from backend.tests.test_mcp import A as MCP_A, _call, _ok, env  # noqa: E402,F401 - the MCP harness


def _mcp_saved(env, dist):
    ds = _ok(_call(env.token[MCP_A], "upload_dataset", {"name": "Rossi", "csv": _csv(_rossi()).decode()}))
    return _ok(_call(env.token[MCP_A], "fit_and_save_model", {
        "name": f"Rossi {dist}", "dataset_id": ds["id"], "distribution": dist, "time_column": "week",
        "censor_column": "c", "covariates": COVS}))


def test_mcp_reliability_at_band_and_life(env):
    saved = _mcp_saved(env, "weibull_ph")
    out = _ok(_call(env.token[MCP_A], "reliability_at", {
        "model_id": saved["model_id"], "times": [20, 52], "covariates": ROW, "confidence": 0.9}))
    want = _direct().cb(np.array([20.0, 52.0]), Z, on="sf", alpha_ci=0.1, bound="two-sided")
    assert np.allclose([p["reliability_bounds"] for p in out["points"]], want, rtol=1e-6)
    assert "the app's calculator draws its band" in out["bounds_note"]
    life = out["life"]
    b10 = life["b_lives"][2]
    assert b10["value"] == pytest.approx(float(_direct().qf(np.array([0.1]), Z)[0]))
    assert b10["lower"] == pytest.approx(float(np.ravel(_direct().quantile_cb(
        np.array([0.1]), Z, alpha_ci=0.1, bound="lower"))[0]))


def test_mcp_reliability_at_cox_says_why(env):
    saved = _mcp_saved(env, "cox_ph")
    out = _ok(_call(env.token[MCP_A], "reliability_at", {
        "model_id": saved["model_id"], "times": [20], "covariates": ROW, "confidence": 0.9}))
    assert out["points"][0]["reliability_bounds"] is None and "semi-parametric" in out["bounds_note"]
    assert "No B-lives" in out["life"]["note"]
