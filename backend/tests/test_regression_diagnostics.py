"""Does a regression model's assumption hold? (#61): the proportional-hazards
test, robust standard errors, tie methods, stratified Cox and the residuals —
each checked against SurPyval called directly — through the fit, the REST
endpoints and MCP."""

import io

import matplotlib

matplotlib.use("Agg")

import mongomock
import numpy as np
import pandas as pd
import pytest
from surpyval.univariate.regression import CoxPH

from backend import fitting
from backend import regression_diagnostics as rd
from backend.fitting import FitError, fit

OWNER = "user-a"
MAPPING = {"x": "week", "c": "c"}
COVS = ["fin", "age", "prio"]


def _rossi() -> pd.DataFrame:
    from surpyval.datasets import load_rossi_static

    df = load_rossi_static()[["week", "arrest", "fin", "age", "prio", "race"]].copy()
    df["c"] = 1 - df["arrest"]  # Reliafy: 0 = failed, 1 = still running
    df["site"] = np.where(df.index % 3 == 0, "north", "south")
    df["unit"] = df.index % 40
    return df


def _csv(df: pd.DataFrame) -> bytes:
    return df.to_csv(index=False).encode()


def _cox(**kw):
    return CoxPH.fit_from_df(_rossi(), x_col="week", c_col="c", Z_cols=COVS, **kw)


# ---- The proportional-hazards test --------------------------------------------------

def test_cox_ph_test_is_check_ph_with_a_global_row_and_a_verdict():
    d = fit("cox_ph", _rossi(), MAPPING, covariates=COVS)["diagnostics"]
    ph = d["ph_test"]
    want = _cox().check_ph().reset_index()
    rows = {r["covariate"]: r for r in [*ph["rows"], ph["global"]]}
    for rec in want.to_dict("records"):
        got = rows[rec["covariate"]]
        assert got["statistic"] == pytest.approx(rec["statistic"]) and got["p"] == pytest.approx(rec["p"])
        assert got["df"] == rec["df"]
    assert ph["global"]["covariate"] == "GLOBAL" and ph["global"]["df"] == 3
    # Rossi: overall p ≈ 0.075, but age's effect changes over time (p ≈ 0.012).
    assert ph["verdict"] == "check" and ph["tone"] == "caveat" and ph["flagged"] == ["age"]
    assert ph["title"] == "Mostly proportional; check age" and "age" in ph["reading"]
    assert ph["source"] == "model" and "source_note" not in ph


def test_parametric_ph_is_tested_with_cox_on_the_same_covariates():
    ph = fit("weibull_ph", _rossi(), MAPPING, covariates=COVS)["diagnostics"]["ph_test"]
    want = _cox().check_ph()
    assert ph["global"]["p"] == pytest.approx(want.loc["GLOBAL", "p"])
    assert ph["source"] == "cox" and "Cox model on the same covariates" in ph["source_note"]


@pytest.mark.parametrize("dist", ["weibull_aft", "lognormal_po", "weibull_ah"])
def test_the_test_doesnt_apply_to_other_families(dist):
    d = fit(dist, _rossi(), MAPPING, covariates=COVS)["diagnostics"]
    assert d["ph_test"]["available"] is False and d["ph_test"]["applies"] is False
    assert "Doesn't apply" in d["ph_test"]["reason"]


def test_verdicts():
    class Fake:
        def __init__(self, rows):
            self.rows = rows

        def check_ph(self, transform="km"):
            return pd.DataFrame(self.rows).set_index("covariate")

    holds = rd.ph_test(Fake([{"covariate": "a", "statistic": 0.1, "df": 1, "p": 0.7},
                             {"covariate": "GLOBAL", "statistic": 0.1, "df": 1, "p": 0.7}]))
    assert holds["verdict"] == "holds" and holds["tone"] == "good"
    fails = rd.ph_test(Fake([{"covariate": "a", "statistic": 9, "df": 1, "p": 0.002},
                             {"covariate": "b", "statistic": 0.1, "df": 1, "p": 0.8},
                             {"covariate": "GLOBAL", "statistic": 9.1, "df": 2, "p": 0.01}]))
    assert fails["verdict"] == "fails" and fails["title"] == "Hazards don't look proportional"
    assert "effect of a" in fails["reading"] and "stratify" in fails["reading"]
    undefined = rd.ph_test(Fake([{"covariate": "GLOBAL", "statistic": np.nan, "df": 1, "p": np.nan}]))
    assert undefined["available"] is False


def test_interval_data_has_no_test():
    df = _rossi().assign(xl=lambda d: d["week"] * 0.9, xr=lambda d: d["week"])
    d = fit("weibull_ph", df, {"xl": "xl", "xr": "xr"}, covariates=COVS)["diagnostics"]
    assert d["ph_test"]["available"] is False and "interval" in d["ph_test"]["reason"]


def test_diagnostics_never_raise():
    out, model = rd.diagnose(object(), _rossi(), MAPPING, {}, "cox_ph", "hazard")
    assert out["ph_test"]["available"] is False and model is None


# ---- Robust standard errors ----------------------------------------------------------

def test_robust_errors_are_surpyvals_sandwich():
    rob = fit("cox_ph", _rossi(), MAPPING, covariates=COVS)["diagnostics"]["robust"]
    plain, want = _cox().summary(), _cox().summary(robust=True)
    for row in rob["rows"]:
        name = row["covariate"]
        assert row["se"] == pytest.approx(plain.loc[name, "se(coef)"])
        assert row["robust_se"] == pytest.approx(want.loc[name, "se(coef)"])
        assert row["ratio_lower"] == pytest.approx(want.loc[name, "exp(coef) lower 95%"])
        assert row["p"] == pytest.approx(want.loc[name, "p"])
    assert rob["cluster"] is None and rob["tone"] == "good" and "within" in rob["reading"]


def test_clustered_robust_errors():
    df = _rossi()
    r = fit("cox_ph", df, MAPPING, covariates=COVS, options={"cox": {"cluster": "unit"}})
    rob = r["diagnostics"]["robust"]
    want = _cox().summary(robust=True, cluster=df["unit"].to_numpy())
    assert rob["cluster"] == "unit" and rob["n_clusters"] == 40
    assert [row["robust_se"] for row in rob["rows"]] == pytest.approx(list(want["se(coef)"]))
    assert r["options"] == {"cox": {"cluster": "unit"}}

    few = fit("cox_ph", df, MAPPING, covariates=COVS, options={"cox": {"cluster": "race"}})["diagnostics"]["robust"]
    assert few["tone"] == "caveat" and few["title"] == "Too few clusters to trust" and "Only 2" in few["reading"]


# ---- Tie methods and strata -------------------------------------------------------------

@pytest.mark.parametrize("ties", ["breslow", "exact", "kalbfleisch-prentice"])
def test_tie_methods(ties):
    r = fit("cox_ph", _rossi(), MAPPING, covariates=COVS, options={"cox": {"tie_method": ties}})
    want = _cox(tie_method=ties)
    assert [c["value"] for c in r["coefficients"]] == pytest.approx(list(want.params))
    assert r["options"] == {"cox": {"tie_method": ties}}
    t = r["diagnostics"]["ties"]
    assert t["method"] == ties and t["shared_times"] > 0 and rd.TIE_METHODS[ties] in t["reading"]


def test_efron_is_the_default_and_kept_out_of_the_spec():
    r = fit("cox_ph", _rossi(), MAPPING, covariates=COVS, options={"cox": {"tie_method": "efron"}})
    assert "options" not in r and r["diagnostics"]["ties"]["method"] == "efron"
    assert "(the default)" in r["diagnostics"]["ties"]["reading"]


def test_stratified_cox():
    df = _rossi()
    r = fit("cox_ph", df, MAPPING, covariates=COVS, options={"cox": {"strata": "site"}})
    want = _cox(strata_col="site")
    assert [c["value"] for c in r["coefficients"]] == pytest.approx(list(want.params))
    # The stratum is a calculator input; the curves are that stratum's.
    fields = r["functions"]["covariates"]
    assert fields[-1] == {"name": "site", "type": "category", "options": ["north", "south"],
                          "default": "south", "stratum": True}
    out = fitting.evaluate(r["functions"]["model_id"], {"site": "north", "fin": 1, "age": 30, "prio": 2})
    x = np.asarray(out["curves"]["x"])
    Z = pd.DataFrame({"fin": [1.0], "age": [30.0], "prio": [2.0]})
    assert np.allclose(out["curves"]["sf"], want.sf(x, Z, stratum="north"))
    # Scored like any other model; the checks that need one baseline say why not.
    assert r["validation"]["available"] is True
    d = r["diagnostics"]
    assert d["strata"]["column"] == "site" and d["strata"]["levels"] == ["north", "south"]
    assert d["ph_test"]["available"] is False and "stratified" in d["ph_test"]["reason"]
    assert d["robust"]["reason"] == d["ph_test"]["reason"]
    # No band (and the calculator says so).
    assert "stratified" in fitting.regression_bands.no_bands_note(r)


def test_stratified_rows_are_evaluated_per_stratum():
    df = _rossi()
    r = fit("cox_ph", df, MAPPING, covariates=COVS, options={"cox": {"strata": "site"}})
    model = fitting._MODEL_STORE[r["functions"]["model_id"]]["model"]
    rows = df[[*COVS, "site"]].iloc[:6].reset_index(drop=True)
    x = np.full(6, 30.0)
    got = model.sf(x, rows)
    inner = _cox(strata_col="site")
    for i in range(6):
        one = inner.sf(np.array([30.0]), rows[COVS].iloc[[i]], stratum=rows["site"][i])
        assert got[i] == pytest.approx(float(np.ravel(one)[0]))
    with pytest.raises(ValueError, match="Unknown site"):
        model.sf(x[:1], rows.iloc[[0]].assign(site="east"))


@pytest.mark.parametrize("opts, message", [
    ({"tie_method": "random"}, "Unknown tie method"),
    ({"strata": "nope"}, "no such column"),
    ({"strata": "age"}, "is a covariate"),
    ({"colour": "red"}, "Unknown Cox option"),
])
def test_bad_cox_options(opts, message):
    with pytest.raises(FitError, match=message):
        fit("cox_ph", _rossi(), MAPPING, covariates=COVS, options={"cox": opts})


def test_cox_options_are_cox_only():
    with pytest.raises(FitError, match="Cox PH only"):
        fit("weibull_ph", _rossi(), MAPPING, covariates=COVS, options={"cox": {"tie_method": "breslow"}})
    with pytest.raises(FitError, match="Cox PH only"):
        fit("weibull", _rossi(), MAPPING, options={"cox": {"strata": "site"}})


# ---- Residuals ---------------------------------------------------------------------------

def test_residuals_are_surpyvals():
    r = fit("cox_ph", _rossi(), MAPPING, covariates=COVS)
    diag = fitting._MODEL_STORE[r["functions"]["model_id"]]["diag"]
    res = rd.residuals(diag)
    want = _cox()
    df = _rossi()
    t = df["week"].to_numpy(float)[df["c"].to_numpy() == 0]
    sch = want.compute_residuals("scaled_schoenfeld")
    age = res["schoenfeld"][1]
    assert age["covariate"] == "age" and age["coef"] == pytest.approx(want.params[1])
    order = np.argsort(t, kind="stable")
    assert age["x"] == pytest.approx(t[order], rel=1e-3)
    assert age["y"] == pytest.approx(sch[order, 1], rel=1e-3, abs=1e-6)
    assert len(age["trend"]["x"]) == rd.TREND_BINS
    # Martingale and deviance: one per unit, thinned to MAX_POINTS for the plot.
    assert res["n"] == len(df) and len(res["martingale"]["x"]) == rd.MAX_POINTS
    mart = want.compute_residuals("martingale")
    assert min(res["martingale"]["y"]) == pytest.approx(mart.min(), rel=1e-3)


def test_residuals_without_a_cox_model():
    assert rd.residuals(None)["available"] is False


# ---- API -----------------------------------------------------------------------------------

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


def _save(client, dist="cox_ph", **extra):
    r = client.post(
        "/api/models",
        data={"name": "Rossi", "distribution": dist, "x": "week", "c": "c", "z": COVS, **extra},
        files={"file": ("rossi.csv", io.BytesIO(_csv(_rossi())), "text/csv")},
    )
    assert r.status_code == 200, r.text
    return r.json()


def test_fresh_fit_with_cox_options_and_residuals(client):
    r = client.post(
        "/api/fit/cox_ph",
        data={"x": "week", "c": "c", "z": COVS, "cox": '{"tie_method": "breslow", "cluster": "unit"}'},
        files={"file": ("rossi.csv", io.BytesIO(_csv(_rossi())), "text/csv")},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["options"] == {"cox": {"tie_method": "breslow", "cluster": "unit"}}
    assert body["diagnostics"]["robust"]["cluster"] == "unit"
    res = client.get(body["functions"]["residuals_path"])
    assert res.status_code == 200 and res.json()["available"] is True and res.json()["source"] == "model"
    assert client.get("/api/residuals/nope").status_code == 404

    bad = client.post("/api/fit/cox_ph", data={"x": "week", "c": "c", "z": COVS, "cox": "not json"},
                      files={"file": ("rossi.csv", io.BytesIO(_csv(_rossi())), "text/csv")})
    assert bad.status_code == 422 and "JSON object" in bad.json()["detail"]


def test_saved_model_keeps_its_cox_options_and_refits_with_them(client):
    saved = _save(client, cox='{"strata": "site"}')
    assert saved["results"]["options"] == {"cox": {"strata": "site"}}
    # The calculator evaluates a stratum; a refit (the live model gone) keeps it.
    from backend.services import models as ms

    ms._LIVE.clear()
    out = client.post(f"/api/models/{saved['id']}/evaluate", json={"site": "north"})
    assert out.status_code == 200, out.text
    # Edit fit: drop the strata, choose Breslow.
    r = client.put(f"/api/models/{saved['id']}/fit", json={
        "distribution": "cox_ph", "mapping": MAPPING, "covariates": COVS, "cox": {"tie_method": "breslow"}})
    assert r.status_code == 200, r.text
    assert r.json()["results"]["options"] == {"cox": {"tie_method": "breslow"}}
    assert r.json()["results"]["diagnostics"]["ph_test"]["available"] is True


def test_diagnostics_endpoint_is_lazy_and_cached(client, monkeypatch):
    saved = _save(client, dist="weibull_ph")
    expected = saved["results"]["diagnostics"]
    client.db.models.update_one({"_id": saved["id"]}, {"$unset": {"results.diagnostics": ""}})
    got = client.get(f"/api/models/{saved['id']}/diagnostics")
    assert got.status_code == 200 and got.json() == expected
    assert client.db.models.find_one({"_id": saved["id"]})["results"]["diagnostics"] == expected

    from backend.services import models as ms

    monkeypatch.setattr(ms, "_refit_result", lambda *a: pytest.fail("refitted"))
    assert client.get(f"/api/models/{saved['id']}/diagnostics").json() == expected
    assert client.get("/api/models/nope/diagnostics").status_code == 404


def test_residuals_endpoint_for_a_saved_model(client):
    saved = _save(client, dist="weibull_ph")
    path = saved["results"]["functions"]["residuals_path"]
    assert path == f"/api/models/{saved['id']}/residuals"
    from backend.services import models as ms

    ms._LIVE.clear()  # a live model restored without its checks refits once
    res = client.get(path).json()
    assert res["available"] is True and res["source"] == "cox" and len(res["schoenfeld"]) == 3

    aft = _save(client, dist="weibull_aft")
    res = client.get(f"/api/models/{aft['id']}/residuals").json()
    assert res["available"] is False and "Doesn't apply" in res["reason"]


def test_plain_models_have_no_checks(client):
    r = client.post("/api/models", data={"name": "W", "distribution": "weibull", "x": "week", "c": "c"},
                    files={"file": ("rossi.csv", io.BytesIO(_csv(_rossi())), "text/csv")}).json()
    assert "diagnostics" not in r["results"] and "residuals_path" not in r["results"]["functions"]
    assert client.get(f"/api/models/{r['id']}/diagnostics").status_code == 422


def test_rest_api_v1_reports_the_checks(client):
    client.db.users.update_one({"_id": OWNER}, {"$set": {"uid": OWNER, "email": "a@example.org", "name": "A"}},
                               upsert=True)
    raw = client.post("/api/tokens", json={"name": "test"}).json()["token"]
    saved = _save(client)
    got = client.get(f"/api/v1/models/{saved['id']}", headers={"Authorization": f"Bearer {raw}"})
    assert got.status_code == 200, got.text
    assert got.json()["diagnostics"]["ph_test"]["verdict"] == "check"


# ---- MCP ---------------------------------------------------------------------------------

from backend.tests.test_mcp import A as MCP_A, _call, _ok, env  # noqa: E402,F401 - the MCP harness


def test_mcp_fit_get_model_and_cox_options(env):
    ds = _ok(_call(env.token[MCP_A], "upload_dataset", {"name": "Rossi", "csv": _csv(_rossi()).decode()}))
    args = {"dataset_id": ds["id"], "distribution": "cox_ph", "time_column": "week", "censor_column": "c",
            "covariates": COVS}
    fitted = _ok(_call(env.token[MCP_A], "fit_distribution", {
        **args, "cox_options": {"tie_method": "breslow", "cluster_column": "unit"}}))
    d = fitted["diagnostics"]
    assert d["ph_test"]["verdict"] == "check" and d["robust"]["cluster"] == "unit"
    assert d["ties"]["method"] == "breslow" and fitted["options"]["cox"]["tie_method"] == "breslow"

    saved = _ok(_call(env.token[MCP_A], "fit_and_save_model", {**args, "name": "Rossi Cox"}))
    env.db.models.update_one({"_id": saved["model_id"]}, {"$unset": {"results.diagnostics": ""}})
    got = _ok(_call(env.token[MCP_A], "get_model", {"model_id": saved["model_id"]}))
    assert got["diagnostics"]["ph_test"]["global"]["p"] == pytest.approx(_cox().check_ph().loc["GLOBAL", "p"])

    stray = _call(env.token[MCP_A], "fit_distribution", {"data": [1, 2, 3], "cox_options": {"tie_method": "exact"}})
    assert "dataset" in str(stray).lower()
