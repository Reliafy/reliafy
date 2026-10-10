"""Competing risks: life data by failure mode (#177). Every number is
SurPyval's own, checked against SurPyval called directly."""

import matplotlib

matplotlib.use("Agg")

import io

import mongomock
import numpy as np
import pandas as pd
import pytest
from surpyval import CompetingRisks, CompetingRisksProportionalHazards, gray_test

from backend import competing_risks as cr
from backend import fitting
from backend.services import samples

A = "user-a"
USERS = {A: {"uid": A, "email": "a@x.com", "name": "A"}}
MAPPING = {"x": "hours", "e": "failure_mode", "g": "site"}


def _sample() -> pd.DataFrame:
    csv = next(d for d in samples.SAMPLE_DATASETS if d["id"] == "sample-ds-pump-modes")["csv"]
    return fitting.read_dataframe(csv)


def _arrays(df):
    x = df["hours"].to_numpy(dtype=float)
    e = np.array([None if pd.isna(v) else str(v) for v in df["failure_mode"]], dtype=object)
    c = np.array([1 if v is None else 0 for v in e])
    return x, e, c


def test_incidence_bounds_and_horizon_are_surpyvals():
    df = _sample()
    r = fitting.fit("competing_risks", df, MAPPING, unit="hours")
    assert r["kind"] == "competing_risks" and r["unit"] == "Hours"
    x, e, c = _arrays(df)
    model = CompetingRisks.fit(x, e, c, how="Kaplan-Meier")
    grid = np.asarray(r["curves"]["x"])
    for k in model.event_idx_map:
        assert r["curves"]["cif"][k] == pytest.approx(model.cif(grid, k).tolist())
        cb = np.asarray(model.cb(grid, k, on="cif", alpha_ci=0.05))
        got = np.array([np.nan if v is None else v for v in r["curves"]["lower"][k]])
        ok = np.isfinite(cb[:, 0])
        assert got[ok] == pytest.approx(cb[ok, 0])
    assert r["curves"]["all"] == pytest.approx(model.ff(grid).tolist())
    # The incidences add up to the all-cause (Kaplan-Meier) failure probability.
    stacked = np.sum([r["curves"]["cif"][k] for k in model.event_idx_map], axis=0)
    assert stacked == pytest.approx(r["curves"]["all"])

    assert r["last_failure"] == x[c == 0].max() and r["horizon"] == cr.nice_time(r["last_failure"]) == 5000
    assert [k["name"] for k in r["causes"]] == ["bearing wear", "seal leak", "impeller damage"]
    assert [k["failures"] for k in r["causes"]] == [29, 15, 6]
    top = r["causes"][0]
    assert top["at"]["cif"] == pytest.approx(float(model.cif([5000], "bearing wear")[0]))
    lo, hi = np.asarray(model.cb([5000], "bearing wear", on="cif", alpha_ci=0.05))[0]
    assert (top["at"]["lower"], top["at"]["upper"]) == (pytest.approx(lo), pytest.approx(hi))
    assert top["share"] == pytest.approx(top["at"]["cif"] / float(model.ff([5000])[0]))
    assert sum(k["share"] for k in r["causes"]) == pytest.approx(1.0)
    assert (r["failed"], r["running"], r["n"]) == (50, 22, 72)


def test_the_reading_and_who_leads_when():
    r = fitting.fit("competing_risks", _sample(), MAPPING, unit="hours")
    assert r["reading"].startswith("Bearing wear causes 58% of failures by 5,000 hours: 40% of units fail")
    assert "we're 95% sure it's between 28% and 52%" in r["reading"]
    assert [ld["cause"] for ld in r["leads"]] == ["seal leak", "bearing wear"]
    assert "Seal leak leads early; bearing wear overtakes it at about 2,810 hours." in r["reading"]


def test_grays_test_is_surpyvals():
    df = _sample()
    r = fitting.fit("competing_risks", df, MAPPING, unit="hours")
    g = r["gray"]
    assert g["available"] and g["groups"] == ["A", "B"] and g["group_column"] == "site"
    x, e, c = _arrays(df)
    site = df["site"].to_numpy(dtype=object)
    for row in g["results"]:
        expected = gray_test(x, e, site, event=row["cause"], c=c)
        assert row["p_value"] == pytest.approx(float(expected.p_value))
        assert row["statistic"] == pytest.approx(float(expected.statistic))
        # Each group's incidence at the horizon, from its own fit.
        sel = site == "B"
        own = CompetingRisks.fit(x[sel], e[sel], c[sel], how="Kaplan-Meier")
        b = next(v for v in row["by_group"] if v["group"] == "B")
        assert b["cif"] == pytest.approx(float(own.cif([5000], row["cause"])[0]))
    seal = next(row for row in g["results"] if row["cause"] == "seal leak")
    assert seal["significant"] and g["sentence"].startswith("Seal leak differs by site (Gray's test")
    # Without a group column there's no test.
    assert "gray" not in fitting.fit("competing_risks", df, {"x": "hours", "e": "failure_mode"})


@pytest.mark.parametrize("dist_id, kind", [("competing_risks_cox", "Cox"), ("competing_risks_fine_gray", "Fine-Gray")])
def test_regression_by_mode_is_surpyvals(dist_id, kind):
    df = _sample()
    r = fitting.fit(dist_id, df, MAPPING, covariates=["duty_pct"], unit="hours")
    reg = r["regression"]
    assert reg["model"] == kind and reg["covariates"] == ["duty_pct"]
    x, e, c = _arrays(df)
    frame = pd.DataFrame({"x": x, "e": e, "c": c, "duty_pct": df["duty_pct"].astype(float)})
    model = CompetingRisksProportionalHazards.fit_from_df(frame, x_col="x", e_col="e", Z_cols=["duty_pct"],
                                                          c_col="c", model=kind)
    table = model.summary()
    assert [f"{k['cause']}: {k['covariate']}" for k in reg["coefficients"]] == list(table.index)
    assert [k["ratio"] for k in reg["coefficients"]] == pytest.approx(table["exp(coef)"].tolist())
    assert [k["p_value"] for k in reg["coefficients"]] == pytest.approx(table["p"].tolist())
    bearing = next(k for k in reg["coefficients"] if k["cause"] == "bearing wear")
    assert bearing["ratio"] > 1 and bearing["p_value"] < 0.01  # duty wears bearings out sooner
    assert ("aic" in reg) == (kind == "Cox")
    # The incidence curves come with it.
    assert r["curves"]["cif"]["bearing wear"]


def test_status_column_and_the_data_checks():
    df = pd.DataFrame({"t": [5, 6, 7, 8, 9.0], "mode": ["a", "b", "a", "b", "a"], "c": [0, 0, 1, 0, 1]})
    r = fitting.fit("competing_risks", df, {"x": "t", "e": "mode", "c": "c"})
    # A unit still running has no mode, whatever the column says.
    assert [k["failures"] for k in r["causes"]] == [2, 1] and r["running"] == 2
    model = CompetingRisks.fit([5, 6, 7, 8, 9.0], ["a", "b", None, "b", None], [0, 0, 1, 0, 1], how="Kaplan-Meier")
    assert r["curves"]["cif"]["a"] == pytest.approx(model.cif(r["curves"]["x"], "a").tolist())
    # A word status is mapped as for any fit.
    words = df.assign(c=["Failed", "Failed", "Running", "Failed", "Running"])
    w = fitting.fit("competing_risks", words, {"x": "t", "e": "mode", "c": "c"},
                    options={"c_map": {"Failed": 0, "Running": 1}})
    assert w["curves"]["cif"] == r["curves"]["cif"]

    bad = [
        ({"x": "t", "e": "mode", "c": "c"}, df.assign(mode=["a", None, "a", "b", "a"]), "failed with no failure mode"),
        ({"x": "t", "e": "mode", "tl": "t"}, df, "one time per unit"),
        ({"x": "t", "e": "mode"}, df.assign(mode=[None] * 5), "No unit is marked failed"),
        ({"x": "t", "e": "t"}, pd.DataFrame({"t": np.arange(1, 15.0)}), "at most 12 can compete"),
        ({"x": "t", "e": "mode", "g": "site"}, df.assign(site=["x", None, "x", "y", "y"]), "no value in “site”"),
        ({"x": "t", "e": "mode", "c": "c"}, df.assign(c=[0, 2, 0, 0, 1]), "interval-censored"),
    ]
    for mapping, data, message in bad:
        with pytest.raises(fitting.FitError, match=message):
            fitting.fit("competing_risks", data, mapping)
    with pytest.raises(fitting.FitError, match="needs covariates"):
        fitting.fit("competing_risks_cox", df, {"x": "t", "e": "mode"})


def test_a_single_distribution_ignores_the_mode_and_group_columns():
    df = pd.DataFrame({"t": [5, 6, 7, 8, 9.0], "mode": ["a", "b", "a", "b", "a"]})
    with_mode = fitting.fit("weibull", df, {"x": "t", "e": "mode", "g": "mode"})
    plain = fitting.fit("weibull", df, {"x": "t"})
    assert [p["value"] for p in with_mode["params"]] == pytest.approx([p["value"] for p in plain["params"]])


def test_nice_time():
    assert cr.nice_time(5320) == 5000
    assert cr.nice_time(1450) == 1400
    assert cr.nice_time(43) == 40
    assert cr.nice_time(0.0123) == 0.01
    assert cr.nice_time(0.0137) == 0.013


# ---- the API -------------------------------------------------------------------

@pytest.fixture()
def client(monkeypatch):
    from fastapi.testclient import TestClient

    from backend import config, db
    from backend.auth import get_current_user
    from backend.main import app

    monkeypatch.setattr(config, "AUTH_DISABLED", False)
    monkeypatch.setattr(config, "BILLING_ENABLED", False)
    test_db = mongomock.MongoClient()["reliafy_cr_test"]
    monkeypatch.setattr(db, "_db", test_db)
    monkeypatch.setattr(db, "_simulated", True)
    app.dependency_overrides[get_current_user] = lambda: USERS[A]
    tc = TestClient(app)
    tc.db = test_db
    try:
        yield tc
    finally:
        app.dependency_overrides.clear()


def _csv():
    return io.BytesIO(_sample().to_csv(index=False).encode())


def test_fit_save_and_reopen(client):
    form = {"x": "hours", "e": "failure_mode", "g": "site", "unit": "hours"}
    fresh = client.post("/api/fit/competing_risks", data=form, files={"file": ("p.csv", _csv(), "text/csv")})
    assert fresh.status_code == 200, fresh.text
    body = fresh.json()
    assert body["kind"] == "competing_risks" and body["gray"]["available"] and "functions" not in body

    saved = client.post("/api/models", data={**form, "name": "Pumps by mode", "distribution": "competing_risks"},
                        files={"file": ("p.csv", _csv(), "text/csv")})
    assert saved.status_code == 200, saved.text
    model = saved.json()
    assert model["kind"] == "competing_risks"
    assert model["spec"]["mapping"] == {"x": "hours", "e": "failure_mode", "g": "site"}
    again = client.get(f"/api/models/{model['id']}").json()
    assert again["results"]["causes"] == body["causes"]

    # A refit in place keeps the failure-mode columns.
    refit = client.put(f"/api/models/{model['id']}/fit", json={
        "distribution": "competing_risks_cox", "mapping": {"x": "hours", "e": "failure_mode"},
        "covariates": ["duty_pct"], "unit": "hours"})
    assert refit.status_code == 200, refit.text
    assert refit.json()["results"]["regression"]["model"] == "Cox"

    # No life distribution to evaluate: refused, not a 500.
    assert client.post(f"/api/models/{model['id']}/life", json={}).status_code == 422


def test_the_sample_is_seeded(client, monkeypatch):
    from backend import config

    monkeypatch.setattr(config, "SEED_SAMPLES", True)
    samples.seed_samples(client.db)
    doc = client.db.models.find_one({"_id": "sample-model-pump-modes"})
    assert doc["kind"] == "competing_risks"
    assert doc["results"]["gray"]["available"] and doc["results"]["causes"][0]["name"] == "bearing wear"


def test_failure_modes_refuse_covariates_over_time_and_cox_options():
    """Competing risks don't combine with an item column (#60) or Cox PH's
    options (#61): a clear refusal, never one side silently dropped."""
    df = _sample()
    for dist in ("competing_risks", "weibull_ph"):
        with pytest.raises(fitting.FitError, match="covariates that change over time"):
            fitting.fit(dist, df, {**MAPPING, "i": "pump"}, covariates=["duty_pct"])
    cox = {"cox": {"tie_method": "breslow", "strata": "site"}}
    for dist in ("competing_risks_cox", "cox_ph"):
        with pytest.raises(fitting.FitError, match="not to failure modes"):
            fitting.fit(dist, df, {"x": "hours", "e": "failure_mode"}, covariates=["duty_pct"], options=cox)
    # Empty Cox options are no options: the fit by failure mode goes ahead.
    r = fitting.fit("competing_risks_cox", df, {"x": "hours", "e": "failure_mode"}, covariates=["duty_pct"],
                    options={"cox": {}})
    assert r["kind"] == "competing_risks"
