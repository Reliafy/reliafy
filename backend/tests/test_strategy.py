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


# ---- Failure finding + saved analyses (RCM prerequisites) --------------------

def test_failure_finding_math_and_validation():
    import pytest as _pytest

    from backend.services.strategy import StrategyError, failure_finding

    r = failure_finding("exponential", [{"name": "failure_rate", "value": 0.001}], 0.99, "hours")
    assert abs(r["interval"] - 20.0) < 1e-9  # 2 * (1-0.99) * 1000
    assert r["mttf"] == 1000.0

    with _pytest.raises(StrategyError):
        failure_finding("exponential", [{"name": "failure_rate", "value": 0.001}], 1.5)
    with _pytest.raises(StrategyError):
        failure_finding("exponential", [{"name": "failure_rate", "value": 0.001}], 0)


def test_saved_analyses_roundtrip_and_isolation(monkeypatch):
    import mongomock

    from backend import db as db_module
    from backend.services import strategy_store
    from backend.services.strategy import StrategyError

    session = mongomock.MongoClient()["reliafy_test"]
    monkeypatch.setattr(db_module, "_db", session)
    monkeypatch.setattr(db_module, "_simulated", True)

    inputs = {
        "distribution_id": "weibull",
        "params": [{"name": "alpha", "value": 1000.0}, {"name": "beta", "value": 2.5}],
        "planned_cost": 100.0,
        "unplanned_cost": 1000.0,
        "unit": "hours",
    }
    doc = strategy_store.save_analysis(session, "Bearing plan", "optimal_replacement", inputs, "user-a")
    # Results were computed server-side, never taken from the client.
    assert doc.results["beneficial"] is True
    assert doc.results["optimal_time"] > 0

    docs = strategy_store.list_analyses(session, "user-a")
    assert [d.id for d in docs] == [doc.id]
    assert strategy_store.list_analyses(session, "user-b") == []
    assert strategy_store.get_analysis(session, doc.id, "user-b") is None

    import pytest as _pytest
    with _pytest.raises(strategy_store.AnalysisNotFound):
        strategy_store.rename_analysis(session, doc.id, "hijack", "user-b")
    with _pytest.raises(StrategyError):
        strategy_store.save_analysis(session, "x", "bogus_kind", {}, "user-a")

    ffi = strategy_store.save_analysis(
        session, "Relief valve check", "failure_finding",
        {"distribution_id": "exponential", "params": [{"name": "failure_rate", "value": 1 / 8760}],
         "target_availability": 0.99, "unit": "hours"},
        "user-a",
    )
    assert abs(ffi.results["interval"] - 175.2) < 0.1
    assert "Check every" in strategy_store.headline(ffi)
