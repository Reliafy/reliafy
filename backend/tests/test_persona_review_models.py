"""Persona review (5 Oct), modelling items (#265).

3. Positive parameters' Wald intervals on the log scale (fits, saved models,
   get_model, the MCP fit tools).
4. The sample Crow-AMSAA model is growth-projection ready (and reaches a
   running deployment).
5. Optional stress / covariate units.
8. One spelling per time unit on models.
11. Regression models say why they have no single median / B10 / MTTF and
    give them at the covariate means.
"""

import io
import math

import mongomock
import numpy as np
import pandas as pd
import pytest

from backend import fitting, param_intervals
from backend.tests.test_mcp import A, _call, _err, _ok, env  # noqa: F401 - env is a fixture

Z95 = param_intervals.Z95


@pytest.fixture()
def samples(env):
    from backend.services import samples as samples_service

    samples_service.seed_samples(env.db)
    return env


def _df(x, c=None):
    return pd.DataFrame({"x": x, **({"c": c} if c is not None else {})})


# ---- 3. positive parameters: log-scale intervals ----------------------------------------------

# Three units, two failures: a symmetric Wald interval on the Weibull shape
# (1.24 ± 1.96 × 0.78) would start below zero.
THREE_POINTS = ([10.0, 50.0, 60.0], [0, 0, 1])


def test_three_point_weibull_shape_interval_stays_above_zero():
    r = fitting.fit("weibull", _df(*THREE_POINTS), {"x": "x", "c": "c"}, unit="hours")
    beta = next(p for p in r["params"] if p["name"] == "beta")
    assert beta["value"] - Z95 * beta["se"] < 0  # the old interval went negative
    lo, hi = beta["ci"]
    assert 0 < lo < beta["value"] < hi
    # The log-scale interval: value·exp(±z·se/value).
    k = Z95 * beta["se"] / beta["value"]
    assert (lo, hi) == pytest.approx((beta["value"] * math.exp(-k), beta["value"] * math.exp(k)))
    alpha = next(p for p in r["params"] if p["name"] == "alpha")
    assert alpha["ci"][0] > 0
    assert "log scale" in r["ci_note"]
    # The randomness verdict reads the same interval.
    assert r["randomness"]["beta_ci"] == beta["ci"]


def test_unbounded_parameters_keep_the_symmetric_interval():
    r = fitting.fit("normal", _df([10.0, 40.0, 90.0]), {"x": "x"})
    mu, sigma = r["params"]
    assert mu["ci"] == pytest.approx([mu["value"] - Z95 * mu["se"], mu["value"] + Z95 * mu["se"]])
    assert sigma["ci"][0] > 0 and (sigma["ci"][0] + sigma["ci"][1]) / 2 > sigma["value"]  # log scale: skewed up


@pytest.mark.parametrize("dist", ["lognormal", "exponential", "gamma", "gumbel", "loglogistic"])
def test_every_positive_parameter_stays_positive(dist):
    r = fitting.fit(dist, _df([3.0, 9.0, 11.0, 40.0]), {"x": "x"})
    bounds = param_intervals.bounds_of(fitting.DISTRIBUTIONS[dist]["dist"])
    for p in r["params"]:
        if p.get("ci") and bounds[p["name"]][0] == 0:
            assert p["ci"][0] > 0, (dist, p)


def test_a_probability_parameter_stays_inside_zero_one():
    r = fitting.fit("discrete_weibull", _df([1, 2, 2, 3, 4, 5, 7, 9]), {"x": "x"})
    q = next(p for p in r["params"] if p["name"] == "q")
    assert q["value"] + Z95 * q["se"] > 1  # the symmetric interval left (0, 1)
    assert 0 < q["ci"][0] < q["value"] < q["ci"][1] < 1


def test_wald_interval_helper():
    assert param_intervals.wald_interval(2.0, 0.5) == pytest.approx([2 - Z95 * 0.5, 2 + Z95 * 0.5])
    lo, hi = param_intervals.wald_interval(1.0, 1.0, 0, None)
    assert lo == pytest.approx(math.exp(-Z95)) and hi == pytest.approx(math.exp(Z95))
    lo, hi = param_intervals.wald_interval(0.5, 0.2, 0, 1)
    assert 0 < lo < 0.5 < hi < 1
    assert param_intervals.wald_interval(0.0, 1.0, 0, None) is None  # on the bound
    assert param_intervals.wald_interval(1.0, float("nan"), 0, None) is None


def test_regression_baseline_positive_coefficients_symmetric():
    from backend.services.samples import _SEAL_ALT_CSV

    df = pd.read_csv(io.BytesIO(_SEAL_ALT_CSV))
    r = fitting.fit("weibull_ph", df, {"x": "hours", "c": "censored"}, ["temp_C", "load"])
    for p in r["params"]:
        lo, hi = p["ci"]
        assert 0 < lo < p["value"] < hi and (lo + hi) / 2 > p["value"]  # log scale
    for c in r["coefficients"]:
        assert (c["ci"][0] + c["ci"][1]) / 2 == pytest.approx(c["value"])  # unbounded: symmetric
    assert r["ci_note"]


def _old_symmetric(value, se):
    return [value - Z95 * se, value + Z95 * se]


def _insert_old_weibull(db, model_id="old-weibull", owner=A):
    """A model saved before #265: symmetric intervals, one below zero."""
    db.models.insert_one({
        "_id": model_id, "id": model_id, "name": "Old Weibull", "owner_id": owner, "kind": "distribution",
        "distribution_id": "weibull", "dataset_id": "",
        "spec": {"distribution_id": "weibull", "unit": "hours", "params_only": True},
        "results": {
            "kind": "distribution", "distribution": "Weibull", "distribution_id": "weibull", "unit": "hours",
            "params": [{"name": "alpha", "value": 40.0, "se": 15.0, "ci": _old_symmetric(40.0, 15.0)},
                       {"name": "beta", "value": 1.24, "se": 0.78, "ci": _old_symmetric(1.24, 0.78)}],
            "randomness": {"basis": "beta_ci", "beta": 1.24, "beta_ci": _old_symmetric(1.24, 0.78),
                           "verdict": "random"},
        },
    })


def test_saved_models_are_served_log_scale_intervals(env):
    from backend.services import models as models_service

    _insert_old_weibull(env.db)
    m = models_service.get_model(env.db, "old-weibull", A)
    beta = m.results["params"][1]
    assert beta["ci"] == pytest.approx(param_intervals.wald_interval(1.24, 0.78, 0, None))
    assert beta["ci"][0] > 0
    assert m.results["randomness"]["beta_ci"] == beta["ci"]
    assert m.results["ci_note"] == param_intervals.CI_NOTE
    assert m.results["unit"] == "Hours"  # #265 item 8: one spelling
    # Served, not rewritten: the stored document is as it was.
    stored = env.db.models.find_one({"_id": "old-weibull"})["results"]
    assert stored["params"][1]["ci"][0] < 0 and stored["unit"] == "hours"
    # And over MCP.
    out = _ok(_call(env.token[A], "get_model", {"model_id": "old-weibull"}))
    assert out["params"][1]["ci"][0] > 0 and out["ci_note"] == param_intervals.CI_NOTE
    assert out["unit"] == "Hours"
    # Reading twice gives the same intervals (idempotent).
    again = param_intervals.corrected_results(m.results)
    assert again["params"] == m.results["params"]


def test_saved_regression_without_se_is_corrected_from_its_width():
    results = {"kind": "regression", "distribution_id": "weibull_ph",
               "params": [{"name": "alpha", "value": 10.0, "ci": _old_symmetric(10.0, 6.0)}],
               "coefficients": [{"name": "z", "value": 0.5, "ci": _old_symmetric(0.5, 0.4)}]}
    fixed = param_intervals.corrected_results(results)
    assert fixed["params"][0]["ci"] == pytest.approx(param_intervals.wald_interval(10.0, 6.0, 0, None))
    assert fixed["coefficients"] == results["coefficients"]


def test_mcp_fit_reports_log_scale_intervals_and_the_note(env):
    x, c = THREE_POINTS
    out = _ok(_call(env.token[A], "fit_distribution", {"distribution": "weibull", "data": x, "censored": c}))
    beta = next(p for p in out["params"] if p["name"] == "beta")
    assert beta["ci"][0] > 0
    assert "log scale" in out["ci_note"]


def test_alt_helper_is_the_shared_one():
    from backend import alt

    assert alt.bounded_wald_interval(0.994, 0.6, 0, None, 0.95) == pytest.approx(
        param_intervals.wald_interval(0.994, 0.6, 0, None))


# ---- 4. the sample Crow-AMSAA model is projection-ready -----------------------------------------

def test_sample_growth_projection_runs_with_its_defaults(samples):
    out = _ok(_call(samples.token[A], "growth_projection", {"model_id": "sample-rec-compressors"}))
    assert out["projected"]["mtbf"] > out["demonstrated"]["mtbf"]
    assert out["growth_potential"]["mtbf"] >= out["projected"]["mtbf"]
    kinds = {m["label"]: m["kind"] for m in out["modes"]}
    assert kinds == {"valve": "BD", "seal": "BD", "bearing": "A", "electrical": "A"}
    # Other settings still work, including another BD fix.
    custom = _ok(_call(samples.token[A], "growth_projection", {
        "model_id": "sample-rec-compressors", "fef": {"valve": 0.9}, "bd_modes": ["bearing"]}))
    assert {m["label"] for m in custom["modes"] if m["kind"] == "BD"} == {"valve", "bearing"}


def test_sample_projection_view_is_ready_in_the_app(samples):
    from backend.services import recurrent as recurrent_service

    doc = recurrent_service.get_model(samples.db, "sample-rec-compressors")
    view = recurrent_service.projection_view(samples.db, doc)
    assert view["available"] and view["mode_column"] == "failure_mode"
    assert {m["label"] for m in view["modes"]} == {"valve", "seal", "bearing", "electrical"}
    assert view["settings"]["fef"] == {"valve": 0.7, "seal": 0.8}
    assert view["result"]["projected"]["mtbf"] > view["result"]["demonstrated"]["mtbf"]


def test_an_existing_deployment_gets_the_failure_mode_column(monkeypatch):
    """Samples are seeded once and shared: a deployment seeded before #265
    has the compressor data without failure modes. The next start adds the
    column and maps it, and the projection works."""
    from backend import config
    from backend.services import samples

    monkeypatch.setattr(config, "SEED_SAMPLES", True)
    db = mongomock.MongoClient()["reliafy_upgrade_test"]
    new_csv, new_spec = samples._COMPRESSOR_EVENTS_CSV, samples.SAMPLE_RECURRENT_MODELS[0]["spec"]
    old_csv = "\n".join(",".join(line.split(",")[:3]) for line in new_csv.decode().strip().split("\n")).encode() + b"\n"
    old_spec = {k: v for k, v in new_spec.items() if k != "projection"}
    old_spec["mapping"] = {k: v for k, v in new_spec["mapping"].items() if k != "mode"}
    ds = next(d for d in samples.SAMPLE_DATASETS if d["id"] == "sample-ds-compressor-events")
    monkeypatch.setitem(ds, "csv", old_csv)
    monkeypatch.setitem(samples.SAMPLE_RECURRENT_MODELS[0], "spec", old_spec)
    samples.seed_samples(db)
    before = db.recurrent_models.find_one({"_id": "sample-rec-compressors"})
    assert "mode" not in before["spec"]["mapping"] and "projection" not in before["results"]

    monkeypatch.setitem(ds, "csv", new_csv)
    monkeypatch.setitem(samples.SAMPLE_RECURRENT_MODELS[0], "spec", new_spec)
    samples.seed_samples(db)
    dataset = db.datasets.find_one({"_id": "sample-ds-compressor-events"})
    assert "failure_mode" in [c["name"] for c in dataset["columns"]]
    after = db.recurrent_models.find_one({"_id": "sample-rec-compressors"})
    assert after["spec"]["mapping"]["mode"] == "failure_mode"
    assert after["spec"]["projection"]["fef"] == {"valve": 0.7, "seal": 0.8}
    assert after["results"]["projection"]["projected"]["mtbf"] > 0
    assert after["results"]["params"] == before["results"]["params"]  # the fit is unchanged
    samples.seed_samples(db)  # and idempotent
    assert db.recurrent_models.find_one({"_id": "sample-rec-compressors"}) == after


# ---- 5. stress and covariate units ----------------------------------------------------------------

def _fluid():
    from backend.services.samples import _INSULATING_FLUID_CSV

    return pd.read_csv(io.BytesIO(_INSULATING_FLUID_CSV))


def test_alt_stress_units_label_the_stresses_and_plots():
    from backend import alt

    payload, _ = alt.fit(_fluid(), {"x": "minutes"}, ["kV"], life_model_id="inverse_power", unit="minutes",
                         stress_labels=["Voltage"], stress_units=["kV"])
    assert payload["stresses"][0]["unit"] == "kV" and payload["stresses"][0]["label"] == "Voltage"
    assert payload["life_stress_plot"]["x_label"] == "Voltage (kV)"
    assert "unit_warnings" not in payload
    plain, _ = alt.fit(_fluid(), {"x": "minutes"}, ["kV"], life_model_id="inverse_power")
    assert "unit" not in plain["stresses"][0]  # optional: nothing without it
    with pytest.raises(fitting.FitError):
        alt.fit(_fluid(), {"x": "minutes"}, ["kV"], life_model_id="inverse_power", stress_units=["kV", "V"])


def test_a_thermal_model_in_celsius_is_warned_about():
    from backend import alt

    df = pd.DataFrame({"t": [100.0, 150, 90, 60, 70, 40, 30, 35, 20],
                       "temp": [60.0, 60, 60, 80, 80, 80, 100, 100, 100]})
    payload, _ = alt.fit(df, {"x": "t"}, ["temp"], life_model_id="arrhenius", stress_units=["°C"])
    assert payload["unit_warnings"] and "kelvin" in payload["unit_warnings"][0]
    kelvin, _ = alt.fit(df.assign(temp=df.temp + 273.15), {"x": "t"}, ["temp"], life_model_id="arrhenius",
                        stress_units=["K"])
    assert "unit_warnings" not in kelvin


def test_mcp_alt_stress_units(env):
    df = _fluid()
    out = _ok(_call(env.token[A], "fit_alt_model", {
        "name": "Fluid", "life_model": "inverse_power", "data": df.minutes.tolist(),
        "stresses": [[v] for v in df.kV.tolist()], "stress_names": ["Voltage"], "stress_units": ["kV"],
        "unit": "minutes"}))
    assert out["stress_units"] == ["kV"]
    use = _ok(_call(env.token[A], "alt_use_level", {"model_id": out["model_id"], "use_stress": [20.0]}))
    assert use["stress_units"] == ["kV"]
    msg = _err(_call(env.token[A], "fit_alt_model", {
        "name": "Fluid", "life_model": "inverse_power", "data": df.minutes.tolist(),
        "stresses": [[v] for v in df.kV.tolist()], "stress_units": ["kV", "V"]}))
    assert "stress_units" in msg


def _seal():
    from backend.services.samples import _SEAL_ALT_CSV

    return pd.read_csv(io.BytesIO(_SEAL_ALT_CSV))


def test_covariate_units_on_a_regression_fit_and_its_saved_model(env):
    from backend.services import datasets as datasets_service
    from backend.services import models as models_service
    from backend.services.samples import _SEAL_ALT_CSV

    units = {"temp_C": " °C ", "load": "", "not_a_covariate": "x"}
    r = fitting.fit("weibull_ph", _seal(), {"x": "hours", "c": "censored"}, ["temp_C", "load"],
                    covariate_units=units)
    assert r["covariate_units"] == {"temp_C": "°C"}
    fields = {f["name"]: f for f in r["functions"]["covariates"]}
    assert fields["temp_C"]["unit"] == "°C" and "unit" not in fields["load"]
    coef = {c["name"]: c for c in r["coefficients"]}
    assert coef["temp_C"]["covariate_unit"] == "°C" and "covariate_unit" not in coef["load"]

    ds = datasets_service.create_dataset(env.db, "seal.csv", _SEAL_ALT_CSV, A)
    m = models_service.save_model(env.db, "Seal PH", ds, "weibull_ph", {"x": "hours", "c": "censored"},
                                  ["temp_C", "load"], None, "hours", owner_id=A, covariate_units=units)
    assert m.spec["covariate_units"] == {"temp_C": "°C"}
    # A refit that doesn't mention units keeps them; {} clears them.
    kept = models_service.update_fit(env.db, m.id, A, "weibull_aft", {"x": "hours", "c": "censored"},
                                     ["temp_C", "load"], None, "hours", None)
    assert kept.results["covariate_units"] == {"temp_C": "°C"}
    cleared = models_service.update_fit(env.db, m.id, A, "weibull_ph", {"x": "hours", "c": "censored"},
                                        ["temp_C", "load"], None, "hours", None, covariate_units={})
    assert "covariate_units" not in cleared.results
    # Without units nothing changes.
    plain = fitting.fit("weibull_ph", _seal(), {"x": "hours", "c": "censored"}, ["temp_C", "load"])
    assert "covariate_units" not in plain and all("unit" not in f for f in plain["functions"]["covariates"])


def test_mcp_regression_covariate_units(env):
    from backend.services.samples import _SEAL_ALT_CSV

    ds = _ok(_call(env.token[A], "upload_dataset", {"name": "Seal", "csv": _SEAL_ALT_CSV.decode()}))
    dsid = ds.get("dataset_id") or ds.get("id")
    args = {"distribution": "weibull_ph", "dataset_id": dsid, "time_column": "hours",
            "censor_column": "censored", "covariates": ["temp_C", "load"]}
    out = _ok(_call(env.token[A], "fit_and_save_model", {**args, "name": "Seal",
                                                         "covariate_units": {"temp_C": "°C"}}))
    assert out["covariate_units"] == {"temp_C": "°C"}
    got = _ok(_call(env.token[A], "get_model", {"model_id": out["model_id"]}))
    assert got["covariate_units"] == {"temp_C": "°C"}
    assert {c["name"]: c.get("unit") for c in got["covariates"]}["temp_C"] == "°C"
    msg = _err(_call(env.token[A], "fit_distribution", {**args, "covariate_units": {"pressure": "bar"}}))
    assert "pressure" in msg


def test_app_routes_take_units(env, monkeypatch):
    import json

    from fastapi.testclient import TestClient

    from backend import config
    from backend.main import app
    from backend.services.samples import _INSULATING_FLUID_CSV, _SEAL_ALT_CSV

    monkeypatch.setattr(config, "AUTH_DISABLED", True)
    client = TestClient(app)
    res = client.post("/api/fit/weibull_ph", files={"file": ("seal.csv", _SEAL_ALT_CSV, "text/csv")},
                      data={"x": "hours", "c": "censored", "z": ["temp_C", "load"],
                            "covariate_units": json.dumps({"load": "kN"})})
    assert res.status_code == 200, res.text
    assert res.json()["covariate_units"] == {"load": "kN"}
    res = client.post("/api/alt/fit", files={"file": ("fluid.csv", _INSULATING_FLUID_CSV, "text/csv")},
                      data={"x": "minutes", "s1": "kV", "life_model": "inverse_power", "s1_unit": "kV"})
    assert res.status_code == 200, res.text
    assert res.json()["results"]["stresses"][0]["unit"] == "kV"
    assert res.json()["spec"]["stress_units"] == ["kV"]


# ---- 8. one spelling per time unit -----------------------------------------------------------------

@pytest.mark.parametrize("given,shown", [("hours", "Hours"), ("Hours", "Hours"), ("hrs", "Hours"), ("h", "Hours"),
                                         ("  months ", "Months"), ("km", "Kilometres"), ("cycles", "Cycles"),
                                         ("", ""), (None, ""), ("shots", "shots"), ("Flight hours", "Flight hours")])
def test_canonical_unit(given, shown):
    from backend.units import canonical_unit

    assert canonical_unit(given) == shown


def test_fits_and_saved_models_use_the_canonical_unit(env):
    from backend import recurrent
    from backend.schema import AltModelDoc, RecurrentModelDoc

    assert fitting.fit("weibull", _df([10.0, 20.0, 30.0]), {"x": "x"}, unit="hrs")["unit"] == "Hours"
    df = pd.DataFrame({"i": [1, 1, 2], "x": [10.0, 30.0, 20.0]})
    assert recurrent.fit(df, {"i": "i", "x": "x"}, unit="days")[0]["unit"] == "Days"
    assert RecurrentModelDoc(id="r", name="r", results={"unit": "hours"}).results["unit"] == "Hours"
    assert AltModelDoc(id="a", name="a", results={"unit": "minutes"}).results["unit"] == "Minutes"


# ---- 11. regression life metrics ---------------------------------------------------------------------

def test_regression_fit_explains_and_gives_metrics_at_the_covariate_means():
    r = fitting.fit("weibull_ph", _seal(), {"x": "hours", "c": "censored"}, ["temp_C", "load"])
    assert r["metrics_note"] == fitting.REGRESSION_METRICS_NOTE
    at = r["at_covariate_means"]
    model = fitting._MODEL_STORE[r["functions"]["model_id"]]["model"]
    Z = pd.DataFrame({"temp_C": [_seal().temp_C.mean()], "load": [_seal().load.mean()]})
    median, b10 = (float(v) for v in np.ravel(model.qf(np.array([0.5, 0.1]), Z)))
    assert at["median"] == pytest.approx(median, rel=1e-3) and at["b10"] == pytest.approx(b10, rel=1e-3)
    assert at["b10"] < at["median"] and at["mttf"] > 0
    assert {c["name"]: c["basis"] for c in at["covariates"]} == {"temp_C": "mean", "load": "mean"}
    cox = fitting.fit("cox_ph", _seal(), {"x": "hours", "c": "censored"}, ["temp_C", "load"])
    assert cox["metrics_note"] and "at_covariate_means" not in cox  # no quantile function


def test_mcp_regression_models_say_why_metrics_are_null(samples):
    out = _ok(_call(samples.token[A], "get_model", {"model_id": "sample-model-seal-weibull-ph"}))
    assert not out["metrics"]
    assert out["metrics_note"] == fitting.REGRESSION_METRICS_NOTE
    assert out["at_covariate_means"]["median"] > 0
    # A model saved before #265 has neither stored: computed from the live model.
    samples.db.models.update_one({"_id": "sample-model-seal-weibull-ph"},
                                 {"$unset": {"results.metrics_note": "", "results.at_covariate_means": ""}})
    again = _ok(_call(samples.token[A], "get_model", {"model_id": "sample-model-seal-weibull-ph"}))
    assert again["metrics_note"] == fitting.REGRESSION_METRICS_NOTE
    assert again["at_covariate_means"]["median"] == pytest.approx(out["at_covariate_means"]["median"])
    fit = _ok(_call(samples.token[A], "fit_distribution", {
        "distribution": "weibull_ph", "dataset_id": "sample-ds-seal-alt", "time_column": "hours",
        "censor_column": "censored", "covariates": ["temp_C", "load"]}))
    assert fit["metrics_note"] and fit["at_covariate_means"]["b10"] > 0


# ---- delete_model covers ALT and degradation; the dataset guard covers every kind ----------------

def _fluid_alt(env, name="Fluid ALT"):
    df = _fluid()
    return _ok(_call(env.token[A], "fit_alt_model", {
        "name": name, "life_model": "inverse_power", "data": df.minutes.tolist(),
        "stresses": [[v] for v in df.kV.tolist()], "unit": "minutes"}))


def test_mcp_delete_model_deletes_an_alt_model_unless_a_fleet_runs_on_it(env):
    from backend.services import fleet as fleet_service

    out = _fluid_alt(env)
    fleet = fleet_service.create_fleet(env.db, "Transformers", out["model_id"], A, "alt")
    msg = _err(_call(env.token[A], "delete_model", {"model_id": out["model_id"]}))
    assert "Transformers" in msg and "fleet" in msg
    assert env.db.alt_models.find_one({"_id": out["model_id"]}) is not None
    fleet_service.delete_fleet(env.db, fleet.id, A)
    done = _ok(_call(env.token[A], "delete_model", {"model_id": out["model_id"]}))
    assert done["deleted"] is True and done["kind"] == "alt"
    assert env.db.alt_models.find_one({"_id": out["model_id"]}) is None
    assert "not found" in _err(_call(env.token[A], "delete_model", {"model_id": out["model_id"]})).lower()


def test_mcp_delete_model_refuses_samples_of_every_kind(samples):
    for model_id in ("sample-alt-fluid", "sample-deg-brake-wear"):
        msg = _err(_call(samples.token[A], "delete_model", {"model_id": model_id}))
        assert "shared sample" in msg
    assert samples.db.alt_models.find_one({"_id": "sample-alt-fluid"}) is not None
    assert samples.db.degradation_models.find_one({"_id": "sample-deg-brake-wear"}) is not None


def test_mcp_delete_model_deletes_a_degradation_model_and_its_items(env):
    from backend.services import datasets as datasets_service
    from backend.services import degradation as degradation_service
    from backend.services.samples import SAMPLE_DEGRADATION_MODELS, _BRAKE_WEAR_CSV

    ds = datasets_service.create_dataset(env.db, "wear.csv", _BRAKE_WEAR_CSV, A)
    doc = degradation_service.save_model(env.db, "Wear", ds, dict(SAMPLE_DEGRADATION_MODELS[0]["spec"]), A)
    done = _ok(_call(env.token[A], "delete_model", {"model_id": doc.id}))
    assert done["deleted"] is True and done["kind"] == "degradation"
    assert env.db.degradation_models.find_one({"_id": doc.id}) is None


def test_a_dataset_behind_any_model_kind_cant_be_deleted(env, monkeypatch):
    from fastapi.testclient import TestClient

    from backend import config
    from backend.main import app
    from backend.services import datasets as datasets_service
    from backend.services import samples as samples_service

    out = _fluid_alt(env)
    msg = _err(_call(env.token[A], "delete_dataset", {"dataset_id": out["dataset_id"]}))
    assert "Fluid ALT" in msg and "ALT model" in msg
    assert env.db.datasets.find_one({"_id": out["dataset_id"]}) is not None
    # The app's route refuses too.
    monkeypatch.setattr(config, "AUTH_DISABLED", True)
    monkeypatch.setattr(config, "DEV_USER_ID", A)
    res = TestClient(app).delete(f"/api/datasets/{out['dataset_id']}")
    assert res.status_code == 409 and "Fluid ALT" in res.json()["detail"], res.text
    assert env.db.datasets.find_one({"_id": out["dataset_id"]}) is not None
    # Recurrent and degradation models count too (the shared samples here).
    samples_service.seed_samples(env.db)
    owners = [A, config.SAMPLE_OWNER]
    rec = datasets_service.dependents_for_dataset(env.db, "sample-ds-compressor-events", owners)
    deg = datasets_service.dependents_for_dataset(env.db, "sample-ds-brake-wear", owners)
    # (Two sample recurrent models use the compressor history, #65.)
    assert {d["kind"] for d in rec} == {"recurrent model"} and [d["kind"] for d in deg] == ["degradation model"]


def test_an_alt_model_whose_dataset_is_gone_still_gives_wald_bounds(env):
    from backend.services import alt as alt_service

    out = _fluid_alt(env)
    env.db.datasets.delete_one({"_id": out["dataset_id"]})  # deleted before the guard existed
    alt_service._LIVE.clear()
    use = _ok(_call(env.token[A], "alt_use_level", {"model_id": out["model_id"], "use_stress": [25.0]}))
    assert use["metrics"] and use["bounds"]["reliability_band"]
    msg = _err(_call(env.token[A], "alt_use_level", {"model_id": out["model_id"], "use_stress": [25.0],
                                                     "bounds_method": "lr"}))
    assert "dataset this model was fitted to was deleted" in msg
