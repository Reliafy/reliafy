import io

import matplotlib

matplotlib.use("Agg")  # no display in CI

import numpy as np
import pytest

from backend.fitting import (
    DISCRETE,
    DISTRIBUTIONS,
    FitError,
    build_fit_inputs,
    extract_times,
    fit,
    preview,
    read_dataframe,
)


def _csv(text: str) -> bytes:
    return io.BytesIO(text.encode()).getvalue()


def _df(text: str):
    return read_dataframe(_csv(text))


def test_preview_returns_columns_and_rows():
    p = preview(_csv("a,b\n1,2\n3,4\n5,6\n"))
    assert p["columns"] == ["a", "b"]
    assert p["n_rows"] == 3
    assert len(p["preview"]) == 3


def test_extract_times_first_numeric_column():
    times = extract_times(_csv("time\n10\n20\n30\n40\n"))
    assert times.tolist() == [10, 20, 30, 40]


def test_build_inputs_only_maps_set_fields():
    df = _df("x,extra\n10,1\n20,2\n")
    kwargs = build_fit_inputs(df, {"x": "x", "c": "", "n": None})
    assert set(kwargs) == {"x"}
    assert kwargs["x"].tolist() == [10.0, 20.0]


def test_build_inputs_truncation_fills_infinities():
    df = _df("x,tl,tr\n10,5,\n20,,30\n")
    kwargs = build_fit_inputs(df, {"x": "x", "tl": "tl", "tr": "tr"})
    assert kwargs["tl"].tolist() == [5.0, -np.inf]
    assert kwargs["tr"].tolist() == [np.inf, 30.0]


# build_fit_inputs no longer validates — SurPyval does, and fit() surfaces it.
def test_fit_surfaces_x_and_interval_error():
    df = _df("a,b,c\n1,1,2\n2,2,3\n3,3,4\n")
    with pytest.raises(FitError, match="either 'x'"):
        fit("weibull", df, {"x": "a", "xl": "b", "xr": "c"})


def test_fit_surfaces_negative_value_error():
    df = _df("x\n-1\n2\n3\n4\n")
    with pytest.raises(FitError, match="support"):
        fit("weibull", df, {"x": "x"})


def test_fit_surfaces_non_numeric_error():
    df = _df("x\n10\nabc\n30\n40\n")
    with pytest.raises(FitError, match="NaN"):
        fit("weibull", df, {"x": "x"})


def test_fit_weibull_basic():
    df = _df("x\n" + "\n".join(map(str, [10, 20, 30, 40, 50, 60, 70, 80])) + "\n")
    result = fit("weibull", df, {"x": "x"})
    assert result["distribution"] == "Weibull"
    assert result["n"] == 8
    names = {p["name"] for p in result["params"]}
    assert names == {"alpha", "beta"}
    plot = result["plot"]
    assert len(plot["scatter"]["x"]) == len(plot["scatter"]["y"])
    assert len(plot["x_ticks"]["vals"]) == len(plot["x_ticks"]["labels"])


def test_fit_large_scale_weibull_is_json_safe_with_bounds():
    # Regression: SurPyval's autograd Hessian goes NaN for large-scale fits
    # (scale ~thousands), which used to make the result non-JSON-serialisable
    # (500) and the confidence band all-NaN. The result must be valid JSON and
    # the band must be finite (covariance is backfilled).
    import json

    rng = np.random.default_rng(11)
    x = 9210.0 * rng.weibull(1.84, size=200)
    df = _df("x\n" + "\n".join(map(str, x.round(1))) + "\n")
    result = fit("weibull", df, {"x": "x"})

    # Valid JSON with allow_nan=False — i.e. no NaN/Inf leaks through.
    json.dumps(result, allow_nan=False)

    bounds = result["plot"]["bounds"]
    lower, upper = bounds["lower"], bounds["upper"]
    assert lower and upper
    assert all(v is not None and np.isfinite(v) for v in lower + upper)
    assert all(lo <= up for lo, up in zip(lower, upper))


def test_fit_weibull_with_right_censoring():
    df = _df("x,c\n10,0\n20,0\n30,1\n40,0\n50,1\n60,0\n70,0\n80,1\n")
    result = fit("weibull", df, {"x": "x", "c": "c"})
    assert result["params"][1]["value"] > 0  # beta


def test_fit_weibull_with_counts():
    df = _df("x,n\n10,3\n20,5\n30,2\n40,4\n")
    result = fit("weibull", df, {"x": "x", "n": "n"})
    assert result["n"] == 14


def test_fit_weibull_interval_censored():
    df = _df("lo,hi\n9,11\n18,22\n28,33\n40,45\n55,60\n68,75\n")
    result = fit("weibull", df, {"xl": "lo", "xr": "hi"})
    assert result["params"][0]["value"] > 0  # alpha


def test_fit_includes_functions_and_gof():
    values = [10, 20, 30, 40, 50, 60, 70, 80]
    df = _df("x\n" + "\n".join(map(str, values)) + "\n")
    result = fit("weibull", df, {"x": "x"})

    curves = result["functions"]["curves"]
    ids = [f["id"] for f in result["functions"]["meta"]]
    assert ids == ["sf", "ff", "hf", "Hf", "df"]
    assert len(curves["x"]) == len(curves["sf"]) > 0
    for fn in ids:
        assert fn in curves

    gof_ids = {g["id"] for g in result["gof"]}
    assert {"log_likelihood", "aic", "bic"} <= gof_ids
    for g in result["gof"]:
        assert isinstance(g["value"], float)


def _covariate_df():
    import numpy as np
    import pandas as pd

    from surpyval import Weibull

    rng = np.random.default_rng(3)
    n = 120
    age = rng.normal(50, 10, n)
    sex = rng.choice(["M", "F"], n)
    beta = 0.04 * (age - 50) + np.where(sex == "M", 0.5, 0.0)
    x = Weibull.random(n, 12, 2.0) * np.exp(-beta / 2)
    return pd.DataFrame(
        {"time": np.round(x, 3), "age": np.round(age, 1), "sex": sex,
         "censored": np.zeros(n, dtype=int)}
    )


def test_fit_weibull_ph_with_covariate_columns():
    df = _covariate_df()
    result = fit("weibull_ph", df, {"x": "time", "c": "censored"}, covariates=["age"])
    assert result["kind"] == "regression"
    # Baseline alpha/beta plus one coefficient for age with a hazard ratio.
    assert {p["name"] for p in result["params"]} == {"alpha", "beta"}
    assert [c["name"] for c in result["coefficients"]] == ["age"]
    assert result["coefficients"][0]["hazard_ratio"] > 0
    assert "plot" not in result
    assert {"aic", "bic"} <= {g["id"] for g in result["gof"]}


def test_fit_weibull_ph_with_formula_expands_categoricals():
    df = _covariate_df()
    result = fit("weibull_ph", df, {"x": "time", "c": "censored"}, formula="age + sex")
    names = [c["name"] for c in result["coefficients"]]
    assert "age" in names
    assert any(name.startswith("sex") for name in names)


def test_regression_calculator_and_evaluate():
    from backend.fitting import ModelNotFound, evaluate

    df = _covariate_df()
    result = fit("weibull_ph", df, {"x": "time", "c": "censored"}, formula="age + sex")
    funcs = result["functions"]
    assert funcs is not None
    fields = {f["name"]: f for f in funcs["covariates"]}
    assert fields["age"]["type"] == "number"
    assert fields["sex"]["type"] == "category"
    assert set(fields["sex"]["options"]) == {"M", "F"}

    # Higher age + male should reduce survival relative to younger + female.
    mid = 150
    high = evaluate(funcs["model_id"], {"age": 70, "sex": "M"})["curves"]["sf"]
    low = evaluate(funcs["model_id"], {"age": 30, "sex": "F"})["curves"]["sf"]
    assert high[mid] < low[mid]

    with pytest.raises(ModelNotFound):
        evaluate("does-not-exist", {})


def test_fit_cox_ph_has_coefficients_no_baseline():
    df = _covariate_df()
    result = fit("cox_ph", df, {"x": "time", "c": "censored"}, formula="age + sex")
    assert result["kind"] == "regression"
    assert result["params"] == []  # semi-parametric: no baseline distribution
    assert any(c["name"] == "age" for c in result["coefficients"])


def test_unknown_distribution_raises():
    df = _df("x\n10\n20\n30\n")
    with pytest.raises(FitError, match="Unknown model"):
        fit("rayleigh", df, {"x": "x"})


@pytest.mark.parametrize("dist_id", list(DISCRETE))
def test_fit_discrete_distributions(dist_id):
    import json

    # Whole-count cycles-to-failure.
    cycles = [3, 5, 5, 6, 7, 7, 8, 8, 9, 10, 11, 12, 14, 16, 20]
    df = _df("cycles\n" + "\n".join(map(str, cycles)) + "\n")
    result = fit(dist_id, df, {"x": "cycles"}, None, None, "cycles")

    assert result["kind"] == "discrete"
    assert result["distribution_id"] == dist_id
    assert result["n"] == len(cycles)
    # Discrete models carry no probability paper — no plot.
    assert result["plot"] is None
    # Fitted parameters with confidence intervals, plus goodness-of-fit.
    assert len(result["params"]) >= 1
    assert all("ci" in p for p in result["params"])
    assert {"aic", "bic"} <= {g["id"] for g in result["gof"]}
    # Reliability functions and life metrics are available for the calculator.
    assert "curves" in result["functions"]
    assert result["metrics"]["median"] is not None
    # The payload must be valid JSON (no NaN/Inf leaks).
    json.dumps(result, allow_nan=False)


def test_discrete_not_in_continuous_best_fit():
    # Discrete distributions must not compete in the continuous "best fit"
    # comparison (incompatible supports) — the two registries stay disjoint.
    assert set(DISCRETE) & set(DISTRIBUTIONS) == set()


def test_discrete_rejects_non_integer_values():
    df = _df("cycles\n3.5\n5.2\n7\n9.1\n")
    with pytest.raises(FitError, match="whole-number"):
        fit("discrete_weibull", df, {"x": "cycles"})


def test_discrete_rejects_sub_one_values():
    df = _df("cycles\n0\n1\n2\n3\n")
    with pytest.raises(FitError, match="count from 1"):
        fit("geometric", df, {"x": "cycles"})


def test_discrete_accepts_integer_valued_floats():
    # CSV parsing yields floats (3.0); those are whole numbers and must fit.
    df = _df("cycles\n3.0\n5.0\n5.0\n7.0\n9.0\n10.0\n12.0\n16.0\n20.0\n")
    result = fit("discrete_weibull", df, {"x": "cycles"})
    assert result["kind"] == "discrete"


@pytest.mark.parametrize("dist_id", list(DISTRIBUTIONS))
def test_fit_all_distributions(dist_id):
    values = [10, 20, 30, 40, 50, 60, 70, 80, 90, 100]
    df = _df("x\n" + "\n".join(map(str, values)) + "\n")
    result = fit(dist_id, df, {"x": "x"})
    assert result["distribution_id"] == dist_id
    assert result["n"] == len(values)
    assert len(result["params"]) >= 1
    plot = result["plot"]
    # Every transformed coordinate must be finite for Plotly to render it.
    for key in ("x", "y"):
        assert np.isfinite(plot["scatter"][key]).all()
        assert np.isfinite(plot["line"][key]).all()
    assert np.isfinite(plot["x_range"]).all()
    assert np.isfinite(plot["y_range"]).all()


def test_params_carry_confidence_intervals():
    import json

    import numpy as np
    import pandas as pd

    from backend import fitting

    rng = np.random.default_rng(1)
    df = pd.DataFrame({"t": np.round(rng.weibull(2.0, 60) * 100, 2)})
    r = fitting.fit("weibull", df, {"x": "t"}, None, None, None)
    json.dumps(r, allow_nan=False)
    for p in r["params"]:
        assert p["se"] is not None and p["se"] > 0
        lo, hi = p["ci"]
        assert lo < p["value"] < hi


def test_randomness_verdicts():
    import numpy as np
    import pandas as pd

    from backend import fitting

    rng = np.random.default_rng(2)
    wear = pd.DataFrame({"t": np.round(rng.weibull(3.0, 80) * 100, 2)})
    r = fitting.fit("weibull", wear, {"x": "t"}, None, None, None)
    assert r["randomness"]["verdict"] == "wear_out"
    assert r["randomness"]["beta_ci"][0] > 1

    rand = pd.DataFrame({"t": np.round(rng.exponential(100, 80), 2)})
    r2 = fitting.fit("weibull", rand, {"x": "t"}, None, None, None)
    assert r2["randomness"]["verdict"] == "random"

    r3 = fitting.fit("exponential", rand, {"x": "t"}, None, None, None)
    assert r3["randomness"] == {"verdict": "random", "basis": "memoryless"}

    r4 = fitting.fit("lognormal", wear, {"x": "t"}, None, None, None)
    assert "randomness" not in r4
