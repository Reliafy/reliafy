"""Tests for the Strategy decision tools (model comparison, optimal replacement)."""

import numpy as np
import pandas as pd
import pytest

from backend.services import strategy as st
from backend.services.strategy import StrategyError


def _weibull_data(alpha=500.0, beta=2.5, n=200, seed=0):
    from surpyval import Weibull

    rng = np.random.default_rng(seed)
    x = Weibull.random(n, alpha, beta)
    return pd.DataFrame({"time": np.round(np.abs(x), 3)})


def test_compare_ranks_and_returns_curves():
    res = st.compare_models(_weibull_data(), {"x": "time"}, unit="Hours")
    ids = [m["id"] for m in res["models"]]
    assert set(ids) <= {"weibull", "exponential", "normal", "lognormal", "gamma"}
    # Ranked best-first by AIC.
    aics = [m["aic"] for m in res["models"] if m["aic"] is not None]
    assert aics == sorted(aics)
    assert res["best_id"] == ids[0]
    # Each model has a reliability curve aligned to the grid + life metrics.
    for m in res["models"]:
        assert len(m["sf"]) == len(res["time"])
        assert "b10" in m["metrics"]
    assert len(res["empirical"]["x"]) > 0


def test_compare_needs_x():
    with pytest.raises(StrategyError):
        st.compare_models(pd.DataFrame({"time": [1, 2, 3]}), {})


def test_optimal_replacement_beneficial_for_wearout():
    params = [{"name": "alpha", "value": 10000}, {"name": "beta", "value": 6}]
    res = st.optimal_replacement("weibull", params, 30, 5000, unit="Hours")
    assert res["beneficial"] is True
    assert res["optimal_time"] == pytest.approx(3263, rel=5e-2)
    assert res["optimal_cost_rate"] < res["run_to_failure_cost_rate"]
    assert 0 < res["savings"] < 1


def test_optimal_replacement_run_to_failure_for_exponential():
    params = [{"name": "failure_rate", "value": 0.01}]
    res = st.optimal_replacement("exponential", params, 30, 5000)
    # Memoryless -> preventive replacement gives no benefit.
    assert res["beneficial"] is False
    assert res["optimal_time"] is None


def test_optimal_replacement_validates_costs():
    params = [{"name": "alpha", "value": 100}, {"name": "beta", "value": 2}]
    with pytest.raises(StrategyError):
        st.optimal_replacement("weibull", params, 5000, 30)  # cp >= cu


def test_compare_two_dominance_and_metrics():
    a = {
        "label": "A",
        "kind": "parametric",
        "distribution_id": "weibull",
        "params": [{"name": "alpha", "value": 80}, {"name": "beta", "value": 2.0}],
    }
    b = {
        "label": "B",
        "kind": "parametric",
        "distribution_id": "weibull",
        "params": [{"name": "alpha", "value": 160}, {"name": "beta", "value": 2.0}],
    }
    res = st.compare_two(a, b, unit="Hours")
    assert res["verdict"]["more_reliable"] == "b"
    assert len(res["a"]["sf"]) == len(res["time"])
    assert res["b"]["metrics"]["median"] > res["a"]["metrics"]["median"]


def test_compare_two_parametric_vs_nonparametric():
    from surpyval import Weibull

    a = {
        "label": "Spec sheet",
        "kind": "parametric",
        "distribution_id": "weibull",
        "params": [{"name": "alpha", "value": 100}, {"name": "beta", "value": 2.0}],
    }
    data = np.abs(Weibull.random(200, 130, 2.0))
    b = {"label": "Field data", "kind": "nonparametric", "x": data.tolist()}
    res = st.compare_two(a, b)
    assert res["b"]["kind"] == "nonparametric"
    assert res["b"]["metrics"]["mttf_restricted"] is True
    assert res["verdict"]["more_reliable"] in {"a", "b", "mixed", "tie"}


def test_compare_two_difference_test_significant():
    from surpyval import Weibull

    a = {"label": "A", "kind": "nonparametric",
         "x": np.abs(Weibull.random(120, 100, 2.0)).tolist()}
    b = {"label": "B", "kind": "nonparametric",
         "x": np.abs(Weibull.random(120, 180, 2.0)).tolist()}
    tests = st.compare_two(a, b)["tests"]
    assert tests["available"] is True
    ids = {r["id"] for r in tests["results"]}
    assert {"log-rank", "gehan", "tarone-ware"} <= ids
    assert tests["significant"] is True  # alpha=180 vs 100 differ strongly


def test_compare_two_difference_test_unavailable_for_parametric():
    a = {"label": "A", "kind": "parametric", "distribution_id": "weibull",
         "params": [{"name": "alpha", "value": 100}, {"name": "beta", "value": 2}]}
    b = {"label": "B", "kind": "nonparametric", "x": [10.0, 20.0, 30.0, 40.0]}
    tests = st.compare_two(a, b)["tests"]
    assert tests["available"] is False
    assert "raw data" in tests["reason"]
