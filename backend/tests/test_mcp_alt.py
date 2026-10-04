"""ALT and regression over MCP: fit_alt_model / alt_use_level (#231, #237)
and interval-censored regression through fit_distribution (#237).

The tools reach the same fits and bounds as the app (backend.alt and
backend.fitting, themselves checked against SurPyval in
test_alt_bounds_interval). The helpers and ``env`` fixture come from test_mcp.
"""

import numpy as np
import pandas as pd
import pytest

from backend import alt
from backend.tests.test_alt_bounds_interval import USE, _alt_df, _inspected, _reg_df
from backend.tests.test_mcp import A, B, _call, _err, _ok, env  # noqa: F401 - env is a fixture


def _csv(df: pd.DataFrame) -> str:
    return df.to_csv(index=False)


def _values(items):
    return [p["value"] for p in items]


def test_fit_alt_model_inline_inspection_data_matches_the_app(env):
    df = _inspected(_alt_df())
    out = _ok(_call(env.token[A], "fit_alt_model", {
        "name": "Seal ALT", "life_model": "arrhenius", "data": df["lo"].tolist(), "data_right": df["hi"].tolist(),
        "censored": df["flag"].tolist(), "stresses": [[t] for t in df["tempK"]], "stress_names": ["Temperature (K)"],
        "unit": "hours"}))
    ref, _ = alt.fit(df, {"xl": "lo", "xr": "hi", "c": "flag"}, ["tempK"], "weibull", "arrhenius")
    assert out["saved"] and out["url"].endswith(f"/modelling/alt/{out['model_id']}")
    assert _values(out["shape_params"]) == pytest.approx(_values(ref["params"]))
    assert _values(out["life_stress_coefficients"]) == pytest.approx(_values(ref["coefficients"]))
    assert out["interval_censored"] is True and out["bounds_methods"] == ["wald", "lr"]
    assert out["censoring"]["n_interval_censored"] == int((df["flag"] == 2).sum())
    assert out["stresses"] == ["Temperature (K)"]
    # Saved as the app saves it: the dataset holds xl / xr / c / stress1.
    doc = env.db.alt_models.find_one({"_id": out["model_id"]})
    assert doc["spec"]["mapping"] == {"xl": "xl", "xr": "xr", "c": "c"} and doc["spec"]["stress_cols"] == ["stress1"]

    # alt_use_level: Wald by default; bootstrap is refused for interval data.
    ev = _ok(_call(env.token[A], "alt_use_level", {"model_id": out["model_id"], "use_stress": USE,
                                                   "mission_time": 2000}))
    assert ev["bounds"]["method"] == "wald" and ev["bounds"]["b10"]["lower"] < ev["metrics"]["b10"]
    assert ev["bounds"]["mission"]["lower"] <= ev["metrics"]["mission_reliability"]
    assert len(ev["bounds"]["reliability_band"]) <= 21
    msg = _err(_call(env.token[A], "alt_use_level", {"model_id": out["model_id"], "use_stress": USE,
                                                     "bounds_method": "bootstrap"}))
    assert "Bootstrap bounds aren't available" in msg


def test_fit_alt_model_from_a_dataset_and_bounds_by_method(env):
    a = env.token[A]
    df = _alt_df()
    ds = _ok(_call(a, "upload_dataset", {"name": "ALT", "csv": _csv(df)}))
    out = _ok(_call(a, "fit_alt_model", {"name": "Exact ALT", "dataset_id": ds["id"], "time_column": "hours",
                                         "censor_column": "cens", "stress_columns": ["tempK"]}))
    assert out["bounds_methods"] == ["wald", "lr", "bootstrap"]
    m = alt.refit(alt.build_inputs(df, {"x": "hours", "c": "cens"}, ["tempK"]), "weibull", "arrhenius")
    for method in ("lr", "bootstrap"):
        ev = _ok(_call(a, "alt_use_level", {"model_id": out["model_id"], "use_stress": USE, "bounds_method": method,
                                            "confidence": 0.9, "ref_stress": [400]}))
        kw = {"n_boot": alt.DEFAULT_N_BOOT, "random_state": alt.BOOTSTRAP_SEED} if method == "bootstrap" else {}
        ref = m.quantile_cb(0.1, [USE], alpha_ci=0.1, bound="lower", method=method, **kw)
        assert ev["bounds"]["b10"]["lower"] == pytest.approx(float(np.ravel(ref)[0]), rel=1e-6), method
        assert ev["acceleration_factor"] > 1
    # Another user can't read it.
    assert "not found" in _err(_call(env.token[B], "alt_use_level", {"model_id": out["model_id"],
                                                                      "use_stress": USE}))


def test_fit_alt_model_explains_misplaced_inputs(env):
    a = env.token[A]
    assert "exactly one" in _err(_call(a, "fit_alt_model", {"name": "x"}))
    msg = _err(_call(a, "fit_alt_model", {"name": "x", "data": [1, 2, 3], "stresses": [[300], [350]]}))
    assert "one entry per time" in msg
    msg = _err(_call(a, "fit_alt_model", {"name": "x", "life_model": "dual_power", "data": [1, 2],
                                          "stresses": [[300], [350]]}))
    assert "2 stress values per row" in msg
    msg = _err(_call(a, "fit_alt_model", {"name": "x", "data": [1, 2], "stresses": [[300], [350]],
                                          "stress_columns": ["t"]}))
    assert "stress_columns only applies with dataset_id" in msg
    assert env.db.alt_models.count_documents({}) == 0 and env.db.datasets.count_documents({}) == 0


def test_regression_takes_inspection_columns_over_mcp(env):
    from backend import fitting

    a = env.token[A]
    df = _reg_df()
    ds = _ok(_call(a, "upload_dataset", {"name": "Field", "csv": _csv(df)}))
    out = _ok(_call(a, "fit_distribution", {"dataset_id": ds["id"], "time_column": "lo", "time_right_column": "hi",
                                            "censor_column": "flag", "distribution": "weibull_ph",
                                            "covariates": ["age"]}))
    ref = fitting.fit("weibull_ph", df, {"xl": "lo", "xr": "hi", "c": "flag"}, covariates=["age"])
    assert _values(out["params"]) == pytest.approx(_values(ref["params"]))
    assert out["coefficients"][0]["value"] == pytest.approx(ref["coefficients"][0]["value"])
