"""One level for every interval (the 90% rule): life bounds 90% one-sided,
everything else 90% two-sided, and fits saved at 95% served at 90% on read
without touching the stored document."""

import copy
import io
import warnings

import numpy as np
import pandas as pd
import pytest
from scipy import stats

from backend import alt, fitting, levels, param_intervals
from backend.services import samples

warnings.filterwarnings("ignore")

DATASETS = {d["id"]: d for d in samples.SAMPLE_DATASETS}


def _df(dataset_id: str) -> pd.DataFrame:
    csv = DATASETS[dataset_id]["csv"]
    return pd.read_csv(io.BytesIO(csv) if isinstance(csv, bytes) else io.StringIO(csv))


def _bearings():
    return fitting.fit("weibull", _df("sample-ds-bearings"), {"x": "hours"}, unit="hours")


def test_the_rule_in_one_place():
    assert levels.LEVEL == 0.90 and levels.ALPHA == pytest.approx(0.10)
    assert levels.Z == pytest.approx(stats.norm.ppf(0.95))
    assert levels.pct() == "90%" and levels.RANGE_WORDS == "90% range"


def test_a_weibull_fit_gives_its_parameters_90_percent_intervals_as_surpyval_does():
    r = _bearings()
    assert r["ci_level"] == 0.90
    model = fitting.get_live_model(r["functions"]["model_id"]) if hasattr(fitting, "get_live_model") else None
    if model is None:
        import surpyval as sp

        x = _df("sample-ds-bearings")["hours"].to_numpy(dtype=float)
        model = sp.Weibull.fit(x)
    by = {p["name"]: p for p in r["params"]}
    for name in ("alpha", "beta"):
        lo, hi = np.ravel(model.param_cb(name, alpha_ci=0.10))
        assert by[name]["ci"] == pytest.approx([lo, hi], rel=1e-6)
    # The bearings sample: β 2.50, 90% 1.96–3.17 (it was 1.88–3.32 at 95%).
    assert by["beta"]["ci"] == pytest.approx([1.964, 3.170], abs=1e-3)
    assert r["plot"]["bounds"]["level"] == 0.90
    assert "90% Wald intervals" in r["ci_note"]
    # The B10's bound stays 90% one-sided lower.
    b10 = next(b for b in r["life"]["b_lives"] if b["label"] == "B10")
    assert r["life"]["confidence"] == 0.90 and b10["lower"] == pytest.approx(467.25, abs=0.1)


def _as_saved_at_95(result: dict) -> dict:
    """``result`` as a fit made before the rule stored it: 95% intervals, a
    95% band, no ``ci_level``."""
    old = copy.deepcopy(result)
    old.pop("ci_level", None)
    bounds = param_intervals.distribution_bounds(old["distribution_id"])
    old["params"] = [{**p, "ci": param_intervals.wald_interval(p["value"], p["se"], *(bounds.get(p["name"]) or (None, None))[:2],
                                                             z=levels.Z95)} for p in old["params"]]
    return old


@pytest.mark.parametrize("dist", ["weibull", "lognormal", "exponential", "gamma"])
def test_a_fit_saved_at_95_is_read_at_90_parameters_and_band(dist, monkeypatch):
    df = _df("sample-ds-bearings")
    fresh = fitting.fit(dist, df, {"x": "hours"}, unit="hours")
    monkeypatch.setattr(levels, "ALPHA", 0.05)
    at95 = fitting.fit(dist, df, {"x": "hours"}, unit="hours")
    monkeypatch.undo()
    old = _as_saved_at_95(at95)
    old["plot"]["bounds"].pop("level")
    stored = copy.deepcopy(old)

    from backend.schema import Model

    served = Model(id="m", name="old", owner_id="u", kind="distribution", distribution_id=dist,
                   results=old).results
    assert old == stored  # nothing written back
    assert served["ci_level"] == 0.90
    for got, want in zip(served["params"], fresh["params"]):
        assert got["ci"] == pytest.approx(want["ci"], rel=1e-9)
    assert served["plot"]["bounds"]["level"] == 0.90
    assert served["plot"]["bounds"]["lower"] == pytest.approx(fresh["plot"]["bounds"]["lower"], abs=1e-9)
    assert served["plot"]["bounds"]["upper"] == pytest.approx(fresh["plot"]["bounds"]["upper"], abs=1e-9)


def test_regression_coefficients_saved_at_95_are_read_at_90():
    df = _df("sample-ds-seal-alt")
    fresh = fitting.fit("weibull_ph", df, {"x": "hours", "c": "censored"}, covariates=["temp_C", "load"], unit="hours")
    old = copy.deepcopy(fresh)
    old.pop("ci_level")
    for c in old["coefficients"]:
        half = (c["ci"][1] - c["ci"][0]) / 2 * levels.Z95 / levels.Z
        c["ci"] = [c["value"] - half, c["value"] + half]
    served = param_intervals.at_level(old)
    for got, want in zip(served["coefficients"], fresh["coefficients"]):
        assert got["ci"] == pytest.approx(want["ci"], rel=1e-9)
    # The guide's numbers: temp_C 0.138 (90% 0.101 to 0.176).
    temp = next(c for c in fresh["coefficients"] if c["name"] == "temp_C")
    assert temp["ci"] == pytest.approx([0.1005, 0.1759], abs=1e-3)


def test_per_demand_defaults_to_90_percent():
    r = fitting.result_per_demand(200, 3)
    d = r["per_demand"]
    assert d["confidence"] == 0.90
    # 3 failures in 200 demands: at least 96.7% per demand (90% one-sided); it was 96.2% at 95%.
    assert d["reliability_lower"] == pytest.approx(1 - stats.beta.ppf(0.90, 4, 197), abs=1e-9)
    assert round(d["reliability_lower"] * 100, 1) == 96.7
    assert round(fitting.result_per_demand(200, 3, 0.95)["per_demand"]["reliability_lower"] * 100, 1) == 96.2


def test_forecast_ranges_are_90_percent():
    from backend.services import fleet

    assert fleet.INTERVAL_LEVEL == 0.9
    lo, hi = fleet._poisson_interval(np.array([40.0]))[0]
    assert (lo, hi) == (stats.poisson.ppf(0.05, 40.0), stats.poisson.ppf(0.95, 40.0))


def _alt_fit():
    spec = next(m for m in samples.SAMPLE_ALT_MODELS if m["id"] == "sample-alt-fluid")["spec"]
    payload, _ = alt.fit(_df("sample-ds-insulating-fluid"), spec["mapping"], spec["stress_cols"],
                         spec["distribution_id"], spec["life_model_id"], spec["unit"], spec["stress_labels"],
                         spec["stress_units"])
    return payload


def test_an_alt_fit_saved_at_95_is_read_at_90(monkeypatch):
    fresh = _alt_fit()
    assert fresh["ci_level"] == 0.90 and alt.DEFAULT_CONFIDENCE == 0.90
    for name, value in (("LEVEL", 0.95), ("Z", levels.Z95), ("ALPHA", 0.05)):
        monkeypatch.setattr(levels, name, value)
    old = _alt_fit()
    monkeypatch.undo()
    old.pop("ci_level")
    served = alt.positive_coefficient_intervals(old)
    assert served["ci_level"] == 0.90
    for key in ("params", "coefficients"):
        for got, want in zip(served[key], fresh[key]):
            assert got["ci"] == pytest.approx(want["ci"], rel=1e-6), key
    for got, want in zip(served["levels"], fresh["levels"]):
        if want.get("own"):
            assert got["own"]["life_ci"] == pytest.approx(want["own"]["life_ci"], rel=1e-6)


def test_a_joint_fit_saved_at_95_is_read_at_90():
    from backend import joint

    rows = [{"part": "survival", "name": "temp", "value": 0.2, "se": 0.1,
             "lower": 0.2 - levels.Z95 * 0.1, "upper": 0.2 + levels.Z95 * 0.1,
             "hr": float(np.exp(0.2)), "hr_lower": float(np.exp(0.2 - levels.Z95 * 0.1)),
             "hr_upper": float(np.exp(0.2 + levels.Z95 * 0.1))}]
    old = {"kind": "joint", "params": rows, "hazard_ratios": [], "marker": "vibration", "confidence": 0.95}
    served = joint.at_level(old)
    r = served["params"][0]
    assert served["ci_level"] == 0.90 and served["confidence"] == 0.95  # the survival band keeps its level
    assert [r["lower"], r["upper"]] == pytest.approx([0.2 - levels.Z * 0.1, 0.2 + levels.Z * 0.1])
    assert [r["hr_lower"], r["hr_upper"]] == pytest.approx(np.exp([0.2 - levels.Z * 0.1, 0.2 + levels.Z * 0.1]))
    assert "90% CI" in served["hazard_ratios"][0]["text"]


def test_recurrent_intervals_are_90_percent():
    from backend import recurrent, recurrent_models

    assert recurrent.CI_LEVEL == 0.90 and recurrent_models.CI_LEVEL == 0.90
    assert recurrent.DEMONSTRATED_LEVEL == 0.90


def test_availability_intervals_are_90_percent_but_runs_stop_where_they_did():
    from backend.services import rbd_analysis, rbd_next_failure, rbd_measures, rbd_uncertainty

    assert rbd_analysis._AVAIL_CONFIDENCE == 0.90
    assert rbd_analysis._AVAIL_STOP_CONFIDENCE == 0.95  # the run length, and so the estimates, don't move
    assert rbd_next_failure.NEXT_FAILURE_Z == pytest.approx(levels.Z)
    assert rbd_measures.LEVEL == 0.90 and rbd_uncertainty.DEFAULT_LEVEL == 0.90


def test_degradation_life_bounds_are_90_percent_one_sided():
    from backend import degradation

    spec = samples.SAMPLE_DEGRADATION_MODELS[0]["spec"]
    payload, _ = degradation.fit(_df("sample-ds-brake-wear"), spec["mapping"], spec["threshold"], path=spec["path"],
                                 unit=spec["unit"], measurement_unit=spec["measurement_unit"])
    c = payload["life_model"]["curves"]
    assert c["life_level"] == 0.90 and c["alpha_ci"] == pytest.approx(0.10)
    x = np.asarray(c["x"])
    lo = np.asarray([np.nan if v is None else v for v in c["life_lower"]])
    band = np.asarray([np.nan if v is None else v for v in c["lower"]])
    # The one-sided 90% bound sits inside the two-sided 90% band's lower end.
    assert np.all(lo[np.isfinite(lo) & np.isfinite(band)] >= band[np.isfinite(lo) & np.isfinite(band)] - 1e-12)
    # B10's lower bound on the brake pads: 3,670 hours (90% one-sided); the band's lower end gave 3,210 (95%).
    i = int(np.argmax(lo < 0.9))
    assert np.interp(0.9, lo[[i, i - 1]], x[[i, i - 1]]) == pytest.approx(3674, abs=5)
