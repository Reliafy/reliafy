"""Regression models with covariates that change over time (#60): fitting
from interval (start-stop) and timeline rows, evaluation along a covariate
schedule, plain readings of the coefficients, saving, the sample, the REST
routes and the MCP tools — every number checked against SurPyval called
directly."""

import io
import math

import matplotlib

matplotlib.use("Agg")

import mongomock
import numpy as np
import pandas as pd
import pytest
import surpyval as sp

from backend import fitting, tvc
from backend.fitting import FitError, fit
from backend.services import samples

INTERVALS = {"i": "pump", "xl": "start_h", "xr": "stop_h", "c": "censored"}
TIMELINE = {"i": "pump", "x": "hours", "c": "censored"}
OWNER = "user-a"


def _pumps() -> pd.DataFrame:
    """The sample's interval rows."""
    spec = next(d for d in samples.SAMPLE_DATASETS if d["id"] == "sample-ds-pump-load")
    return fitting.read_dataframe(spec["csv"])


def _timeline(df: pd.DataFrame) -> pd.DataFrame:
    """The same histories as timeline rows: one row per change, then the end."""
    rows = []
    for pump, g in df.groupby("pump", sort=False):
        rows += [(pump, r.start_h, r.load_pct, 1) for r in g.itertuples()]
        last = g.iloc[-1]
        rows.append((pump, last.stop_h, last.load_pct, last.censored))
    return pd.DataFrame(rows, columns=["pump", "hours", "load_pct", "censored"])


def _live(result: dict) -> dict:
    return fitting._MODEL_STORE[result["functions"]["model_id"]]


SCHEDULE = [{"t": 0, "values": {"load_pct": 60}}, {"t": 3000, "values": {"load_pct": 90}},
            {"t": 6000, "values": {"load_pct": 75}}]


def _sched():
    return sp.StepSchedule.from_changepoints([0, 3000, 6000], [[60.0], [90.0], [75.0]])


# ---- Fitting -----------------------------------------------------------------

def test_interval_rows_fit_as_surpyval_does():
    df = _pumps()
    r = fit("weibull_ph", df, INTERVALS, ["load_pct"], unit="hours", covariate_units={"load_pct": "%"})
    ref = sp.WeibullPH.fit_tvc_from_df(df, "pump", "start_h", "stop_h", "censored", Z_cols=["load_pct"])
    assert [p["value"] for p in r["params"]] == pytest.approx(list(ref.params[:2]))
    assert r["coefficients"][0]["value"] == pytest.approx(ref.params[2])
    se = ref.standard_errors()[2]
    assert r["coefficients"][0]["ci"] == pytest.approx([ref.params[2] - 1.959964 * se, ref.params[2] + 1.959964 * se])
    assert r["kind"] == "regression" and r["n"] == 30
    t = r["tvc"]
    assert t["layout"] == "intervals" and t["items"] == 30 and t["rows"] == len(df)
    assert t["failures"] == int((df["censored"] == 0).sum())
    assert t["bounds"] is True and t["mean"] is True
    field = t["covariates"][0]
    assert field["min"] == 60 and field["max"] == 90 and field["step"] == 10 and field["unit"] == "%"
    # The scores rank units by fixed covariates, so they're not given here.
    assert r["validation"]["available"] is False and "change over time" in r["validation"]["reason"]
    # The load really drives the hazard in the sample: the interval is above 0.
    assert r["coefficients"][0]["ci"][0] > 0


def test_timeline_rows_fit_the_same_model():
    df = _pumps()
    a = fit("weibull_ph", df, INTERVALS, ["load_pct"])
    b = fit("weibull_ph", _timeline(df), TIMELINE, ["load_pct"])
    ref = sp.WeibullPH.fit_tvc_timeline_from_df(_timeline(df), "pump", "hours", ["load_pct"], "censored")
    assert b["tvc"]["layout"] == "timeline" and b["tvc"]["items"] == 30
    assert b["tvc"]["failures"] == a["tvc"]["failures"]
    assert [p["value"] for p in b["params"]] == pytest.approx(list(ref.params[:2]))
    assert b["coefficients"][0]["value"] == pytest.approx(a["coefficients"][0]["value"])


def test_cox_fits_without_bounds_or_mean():
    df = _pumps()
    r = fit("cox_ph", df, INTERVALS, ["load_pct"])
    ref = sp.CoxPH.fit_tvc_from_df(df, "pump", "start_h", "stop_h", "censored", Z_cols=["load_pct"])
    assert r["coefficients"][0]["value"] == pytest.approx(ref.params[0])
    assert r["params"] == [] and r["tvc"]["bounds"] is False and r["tvc"]["mean"] is False
    assert r["gof"][0]["label"] == "Log partial likelihood"
    out = tvc.evaluate(_live(r)["model"], _live(r)["fields"], SCHEDULE, [1000.0, 5000.0], alpha_ci=0.1)
    assert out["bounds"] is None and "Cox" in out["bounds_note"]
    assert out["mean"] is None
    assert out["curves"]["sf"] == pytest.approx(ref.sf_tvc([1000.0, 5000.0], _sched()))


@pytest.mark.parametrize("dist_id", ["weibull_aft", "lognormal_ph", "weibull_po", "exponential_ah"])
def test_every_family_fits(dist_id):
    df = _pumps()
    r = fit(dist_id, df, INTERVALS, ["load_pct"])
    ref = fitting.REGRESSION_MODELS[dist_id]["fitter"].fit_tvc_from_df(
        df, "pump", "start_h", "stop_h", "censored", Z_cols=["load_pct"])
    assert r["coefficients"][0]["value"] == pytest.approx(ref.params[-1], rel=1e-6, abs=1e-9)
    assert r["tvc"]["readings"]


def test_status_words_and_inversion_apply_before_the_fit():
    df = _pumps()
    words = df.assign(state=np.where(df["censored"] == 0, "failed", "running")).drop(columns="censored")
    r = fit("weibull_ph", words, {**INTERVALS, "c": "state"}, ["load_pct"],
            options={"c_map": {"failed": 0, "running": 1}})
    a = fit("weibull_ph", df, INTERVALS, ["load_pct"])
    assert r["coefficients"][0]["value"] == pytest.approx(a["coefficients"][0]["value"])
    assert r["options"]["c_map"] == {"failed": 0, "running": 1}


def test_formula_with_a_categorical_covariate():
    df = _pumps().assign(duty=lambda d: np.where(d["load_pct"] >= 90, "high", "normal"))
    r = fit("weibull_ph", df, INTERVALS, formula="duty + load_pct")
    ref = sp.WeibullPH.fit_tvc_from_df(df, "pump", "start_h", "stop_h", "censored", formula="duty + load_pct")
    assert [c["name"] for c in r["coefficients"]] == list(ref.feature_names)
    reading = next(x["text"] for x in r["tvc"]["readings"] if x["name"].startswith("duty"))
    assert reading.startswith("duty = normal (against its base level) multiplies the hazard by")
    # A schedule of categorical levels is encoded as the fit's design.
    live = _live(r)
    sched = [{"t": 0, "values": {"duty": "normal", "load_pct": 60}},
             {"t": 3000, "values": {"duty": "high", "load_pct": 95}}]
    out = tvc.evaluate(live["model"], live["fields"], sched, [1000.0, 5000.0])
    Z = ref._prepare_Z(pd.DataFrame({"duty": ["normal", "high"], "load_pct": [60, 95]}))
    expected = ref.sf_tvc([1000.0, 5000.0], sp.StepSchedule.from_changepoints([0, 3000], Z))
    assert out["curves"]["sf"] == pytest.approx(expected)
    with pytest.raises(FitError, match="must be one of"):
        tvc.evaluate(live["model"], live["fields"], [{"t": 0, "values": {"duty": "weird"}}], [1.0])


@pytest.mark.parametrize("mapping, message", [
    ({"i": "pump", "xl": "start_h", "xr": "stop_h"}, "status column"),
    ({"i": "pump", "xl": "start_h", "c": "censored"}, "both the start and the stop"),
    ({"i": "pump", "c": "censored"}, "Pick the time columns"),
    ({**INTERVALS, "tl": "start_h"}, "Truncation"),
])
def test_incomplete_mappings_say_what_is_missing(mapping, message):
    with pytest.raises(FitError, match=message):
        fit("weibull_ph", _pumps(), mapping, ["load_pct"])


def test_an_item_column_needs_a_regression_model_and_covariates():
    with pytest.raises(FitError, match="need a regression model"):
        fit("weibull", _pumps(), INTERVALS)
    with pytest.raises(FitError, match="tick at least one"):
        fit("weibull_ph", _pumps(), INTERVALS)


# ---- Evaluation along a schedule ---------------------------------------------

def test_schedule_evaluation_matches_surpyval():
    df = _pumps()
    r = fit("weibull_ph", df, INTERVALS, ["load_pct"])
    live = _live(r)
    ref = sp.WeibullPH.fit_tvc_from_df(df, "pump", "start_h", "stop_h", "censored", Z_cols=["load_pct"])
    grid = np.linspace(0, 9000, 31)
    out = tvc.evaluate(live["model"], live["fields"], SCHEDULE, grid, alpha_ci=0.1, bound="lower")
    s = _sched()
    assert out["curves"]["sf"] == pytest.approx(ref.sf_tvc(grid, s))
    assert out["curves"]["ff"] == pytest.approx(1 - ref.sf_tvc(grid, s))
    assert out["curves"]["Hf"] == pytest.approx(ref.Hf_tvc(grid, s))
    assert out["bounds"]["lower"] == pytest.approx(ref.cb_tvc(grid, s, alpha_ci=0.1, bound="lower"))
    assert out["bounds"]["upper"] is None
    assert out["mean"] == pytest.approx(ref.mean_tvc(s))
    two = tvc.evaluate(live["model"], live["fields"], SCHEDULE, grid, on="ff", alpha_ci=0.05, bound="two-sided")
    cb = ref.cb_tvc(grid, s, on="ff", alpha_ci=0.05, bound="two-sided")
    assert two["bounds"]["lower"] == pytest.approx(cb[:, 0]) and two["bounds"]["upper"] == pytest.approx(cb[:, 1])
    # A schedule that steps up the load ages the pump faster than a steady 60%.
    steady = tvc.evaluate(live["model"], live["fields"], [{"t": 0, "values": {"load_pct": 60}}], grid)
    assert steady["curves"]["sf"][-1] > out["curves"]["sf"][-1]
    # A constant schedule is the ordinary fixed-covariate curve.
    assert steady["curves"]["sf"] == pytest.approx(ref.sf(grid, [[60.0]]))


def test_schedule_rows_carry_values_forward_and_sort():
    fields = [{"name": "a", "type": "number", "default": 1.0}, {"name": "b", "type": "number", "default": 2.0}]
    times, rows, norm = tvc.parse_schedule(
        [{"t": 50, "values": {"a": 5}}, {"from": 0, "values": {"b": 3}}], fields)
    assert times.tolist() == [0.0, 50.0]
    assert rows.to_dict("records") == [{"a": 1.0, "b": 3.0}, {"a": 5.0, "b": 3.0}]
    assert norm[1] == {"t": 50.0, "values": {"a": 5.0, "b": 3.0}}


@pytest.mark.parametrize("schedule, message", [
    ([], "at least one row"),
    ([{"t": 0, "values": {"nope": 1}}], "Unknown covariate"),
    ([{"t": -1, "values": {}}], "0 or more"),
    ([{"t": 0, "values": {}}, {"t": 0, "values": {}}], "same time"),
    ([{"t": "x", "values": {}}], "must be a number"),
    ([{"t": 0, "values": {"load_pct": "high"}}], "must be a number"),
])
def test_bad_schedules_are_refused_in_words(schedule, message):
    fields = [{"name": "load_pct", "type": "number", "default": 75.0}]
    with pytest.raises(FitError, match=message):
        tvc.parse_schedule(schedule, fields)


def test_points_with_conditional_age_and_bounds():
    df = _pumps()
    r = fit("weibull_ph", df, INTERVALS, ["load_pct"])
    live = _live(r)
    ref = sp.WeibullPH.fit_tvc_from_df(df, "pump", "start_h", "stop_h", "censored", Z_cols=["load_pct"])
    out = tvc.evaluate_points(live["model"], live["fields"], SCHEDULE, [1000, 4000], conditional_age=2000,
                              confidence=0.9)
    s = _sched()
    assert [p["reliability"] for p in out["points"]] == pytest.approx(ref.sf_tvc([1000, 4000], s))
    cond = ref.sf_tvc([3000.0, 6000.0], s, given=2000.0)
    assert [p["conditional_reliability"] for p in out["points"]] == pytest.approx(cond)
    cb = ref.cb_tvc([1000, 4000], s, alpha_ci=0.1, bound="two-sided")
    assert np.array([p["reliability_bounds"] for p in out["points"]]) == pytest.approx(cb)
    assert out["mean_life"] == pytest.approx(ref.mean_tvc(s))


# ---- Readings ----------------------------------------------------------------

def test_readings_by_family():
    fields = [{"name": "load", "type": "number", "default": 1.0, "step": 10.0}]
    coef = [{"name": "load", "value": 0.05, "ci": [0.01, 0.09], "covariate_unit": "%"}]
    hazard = tvc.readings(coef, "hazard", fields)[0]["text"]
    assert hazard == ("Every +10% in load multiplies the hazard by 1.65 (95% interval 1.11 to 2.46).")
    assert math.exp(0.5) == pytest.approx(1.6487, rel=1e-4)
    aft = tvc.readings(coef, "aft", fields)[0]["text"]
    assert "makes the item age 1.65× as fast" in aft
    po = tvc.readings([{**coef[0], "value": -0.05, "ci": [-0.09, -0.01]}], "odds", fields)[0]["text"]
    assert "multiplies the odds of surviving by 0.607 (95% interval 0.407 to 0.905)" in po
    ah = tvc.readings([{"name": "load", "value": 2e-5, "ci": None}], "additive", fields)[0]["text"]
    assert ah == "Every +10 in load adds 2.00e-04 to the hazard rate."


@pytest.mark.parametrize("span, step", [(30, 10), (0.4, 0.1), (40, 10), (3, 1), (700, 200), (0, 1)])
def test_round_steps(span, step):
    assert tvc._nice_step(span) == pytest.approx(step)


# ---- Saving, the sample and the REST routes ----------------------------------

@pytest.fixture()
def client(monkeypatch):
    from fastapi.testclient import TestClient

    from backend import config, db
    from backend.auth import get_current_user
    from backend.main import app

    monkeypatch.setattr(config, "AUTH_DISABLED", False)
    monkeypatch.setattr(config, "BILLING_ENABLED", False)
    test_db = mongomock.MongoClient()["reliafy_tvc_test"]
    monkeypatch.setattr(db, "_db", test_db)
    monkeypatch.setattr(db, "_simulated", True)
    app.dependency_overrides[get_current_user] = lambda: {"uid": OWNER, "email": "a@example.org", "name": "A"}
    tc = TestClient(app)
    tc.db = test_db
    try:
        yield tc
    finally:
        app.dependency_overrides.clear()


def _csv(df: pd.DataFrame) -> bytes:
    return df.to_csv(index=False).encode()


def test_fit_then_schedule_unsaved(client):
    r = client.post("/api/fit/weibull_ph", data={**INTERVALS, "z": ["load_pct"], "unit": "hours"},
                    files={"file": ("pumps.csv", io.BytesIO(_csv(_pumps())), "text/csv")})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["tvc"]["layout"] == "intervals"
    fit_id = body["functions"]["model_id"]
    got = client.post(f"/api/tvc/{fit_id}", json={"schedule": SCHEDULE, "alpha_ci": 0.1, "bound": "lower",
                                                  "x_max": 9000})
    assert got.status_code == 200, got.text
    out = got.json()
    assert out["curves"]["x"][-1] == pytest.approx(9000)
    ref = sp.WeibullPH.fit_tvc_from_df(_pumps(), "pump", "start_h", "stop_h", "censored", Z_cols=["load_pct"])
    assert out["curves"]["sf"] == pytest.approx(ref.sf_tvc(np.asarray(out["curves"]["x"]), _sched()))
    assert len(out["bounds"]["lower"]) == len(out["curves"]["x"])
    bad = client.post(f"/api/tvc/{fit_id}", json={"schedule": []})
    assert bad.status_code == 422 and "at least one row" in bad.json()["detail"]
    assert client.post("/api/tvc/nope", json={"schedule": SCHEDULE}).status_code == 404


def test_save_reopen_and_refit_on_demand(client):
    from backend.services import models as models_service

    r = client.post("/api/models", data={"name": "Pumps", "distribution": "weibull_ph", **INTERVALS,
                                         "z": ["load_pct"], "unit": "hours"},
                    files={"file": ("pumps.csv", io.BytesIO(_csv(_pumps())), "text/csv")})
    assert r.status_code == 200, r.text
    model = r.json()
    assert model["spec"]["mapping"] == INTERVALS
    first = client.post(f"/api/models/{model['id']}/tvc", json={"schedule": SCHEDULE}).json()
    # A fresh process: nothing cached, so the model is re-fitted from its spec.
    models_service._LIVE.clear()
    fitting._MODEL_STORE.clear()
    again = client.post(f"/api/models/{model['id']}/tvc", json={"schedule": SCHEDULE})
    assert again.status_code == 200, again.text
    assert again.json()["curves"]["sf"] == pytest.approx(first["curves"]["sf"])
    assert again.json()["mean"] == pytest.approx(first["mean"])
    # The ordinary calculator still evaluates it at fixed covariates.
    ev = client.post(f"/api/models/{model['id']}/evaluate", json={"load_pct": 60})
    assert ev.status_code == 200
    # A refit with an edited spec keeps the item column.
    put = client.put(f"/api/models/{model['id']}/fit", json={
        "distribution": "weibull_aft", "mapping": INTERVALS, "covariates": ["load_pct"], "unit": "hours"})
    assert put.status_code == 200, put.text
    assert put.json()["results"]["tvc"]["layout"] == "intervals"
    assert put.json()["results"]["effect"] == "aft"


def test_schedule_route_refuses_other_models(client):
    r = client.post("/api/models", data={"name": "Plain", "distribution": "weibull", "x": "stop_h"},
                    files={"file": ("pumps.csv", io.BytesIO(_csv(_pumps())), "text/csv")})
    resp = client.post(f"/api/models/{r.json()['id']}/tvc", json={"schedule": SCHEDULE})
    assert resp.status_code == 422
    assert client.post("/api/models/missing/tvc", json={"schedule": SCHEDULE}).status_code == 404


def test_sample_model_is_seeded_with_its_reading():
    from backend.services import samples as samples_service

    db = mongomock.MongoClient()["reliafy_tvc_samples"]
    samples_service.seed_samples(db)
    doc = db.models.find_one({"_id": "sample-model-pump-load-weibull-ph"})
    assert doc is not None and doc["kind"] == "regression"
    assert doc["spec"]["mapping"] == INTERVALS and doc["spec"]["covariate_units"] == {"load_pct": "%"}
    reading = doc["results"]["tvc"]["readings"][0]["text"]
    assert reading.startswith("Every +10% in load_pct multiplies the hazard by")


# ---- MCP ---------------------------------------------------------------------

def test_mcp_fit_and_reliability_along_a_schedule(env):  # noqa: F811 - env is a fixture
    from backend.tests.test_mcp import A, _call, _err, _ok

    ds = _ok(_call(env.token[A], "upload_dataset", {"name": "Pumps", "csv": _csv(_pumps()).decode()}))
    out = _ok(_call(env.token[A], "fit_distribution", {
        "distribution": "weibull_ph", "dataset_id": ds["id"], "id_column": "pump", "time_column": "start_h",
        "time_right_column": "stop_h", "censor_column": "censored", "covariates": ["load_pct"]}))
    ref = sp.WeibullPH.fit_tvc_from_df(_pumps(), "pump", "start_h", "stop_h", "censored", Z_cols=["load_pct"])
    assert out["coefficients"][0]["value"] == pytest.approx(ref.params[2])
    assert out["tvc"]["layout"] == "intervals" and out["tvc"]["readings"]
    assert "censoring" not in out  # rows are stretches of life, not units

    saved = _ok(_call(env.token[A], "fit_and_save_model", {
        "name": "Pumps TVC", "distribution": "weibull_ph", "dataset_id": ds["id"], "id_column": "pump",
        "time_column": "start_h", "time_right_column": "stop_h", "censor_column": "censored",
        "covariates": ["load_pct"]}))
    got = _ok(_call(env.token[A], "get_model", {"model_id": saved["model_id"]}))
    assert got["tvc"]["items"] == 30
    rel = _ok(_call(env.token[A], "reliability_at", {
        "model_id": saved["model_id"], "times": [1000, 4000], "covariate_schedule": SCHEDULE,
        "confidence": 0.9}))
    assert [p["reliability"] for p in rel["points"]] == pytest.approx(ref.sf_tvc([1000, 4000], _sched()))
    cb = ref.cb_tvc([1000, 4000], _sched(), alpha_ci=0.1, bound="two-sided")
    assert np.array([p["reliability_bounds"] for p in rel["points"]]) == pytest.approx(cb)
    assert rel["mean_life"] == pytest.approx(ref.mean_tvc(_sched()))

    assert "not both" in _err(_call(env.token[A], "reliability_at", {
        "model_id": saved["model_id"], "times": [1000], "covariate_schedule": SCHEDULE,
        "covariates": {"load_pct": 60}}))
    assert "dataset" in _err(_call(env.token[A], "fit_distribution", {
        "distribution": "weibull_ph", "data": [1, 2, 3], "id_column": "pump"}))


from backend.tests.test_mcp import env  # noqa: E402,F401 - the MCP fixture


@pytest.mark.parametrize("dist", ["additive_hazards", "buckley_james", "weibull_frailty", "cox_frailty"])
def test_models_without_covariates_over_time_say_so(dist):
    """#179's semi-parametric and shared-frailty regressions fit fixed
    covariates only: an item column gets a plain refusal, and the model list
    flags them so the wizard leaves them out."""
    df = _pumps()
    df["site"] = df["pump"].str[-1]
    mapping = {**INTERVALS, "group": "site"} if "frailty" in dist else INTERVALS
    with pytest.raises(FitError, match="can't fit covariates that change over time"):
        fit(dist, df, mapping, ["load_pct"])


def test_the_model_list_flags_covariates_over_time():
    from fastapi.testclient import TestClient

    from backend.main import app

    listed = {d["id"]: d for d in TestClient(app).get("/api/distributions").json()["distributions"]}
    assert listed["weibull_ph"]["tvc"] and listed["cox_ph"]["tvc"]
    assert not listed["weibull_frailty"]["tvc"] and not listed["buckley_james"]["tvc"]
