"""Tests for the Strategy decision tools (optimal replacement, compare-two, failure finding)."""

import numpy as np
import pytest

from backend.services import strategy as st
from backend.services.strategy import StrategyError


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


# ---- parameter uncertainty (#189) ----------------------------------------------

def test_compute_and_saved_analyses_keep_the_models_extras():
    """The calculators' extras (offset, LFP fraction, zero inflation) are
    used when computing and saving, so a saved analysis matches what the
    calculator showed."""
    import mongomock

    from backend.services import strategy_store

    weib = [{"name": "alpha", "value": 1000.0}, {"name": "beta", "value": 3.0}]
    inputs = {"distribution_id": "weibull", "params": weib, "planned_cost": 100, "unplanned_cost": 1000,
              "extras": {"p": 0.6}}
    shown = st.optimal_replacement("weibull", weib, 100, 1000, extras={"p": 0.6})
    assert shown["beneficial"] is False
    assert strategy_store.compute("optimal_replacement", inputs)["beneficial"] is False
    db = mongomock.MongoClient()["t"]
    saved = strategy_store.save_analysis(db, "LFP pumps", "optimal_replacement", inputs, "user-a")
    assert saved.results["beneficial"] is False and saved.results["recommendation"] == shown["recommendation"]

    rate = [{"name": "failure_rate", "value": 1e-3}]
    ff = strategy_store.compute("failure_finding", {
        "distribution_id": "exponential", "params": rate, "target_availability": 0.99,
        "extras": {"gamma": 500.0}})
    assert ff["interval"] == pytest.approx(
        st.failure_finding("exponential", rate, 0.99, extras={"gamma": 500.0})["interval"])
    assert ff["interval"] > st.failure_finding("exponential", rate, 0.99)["interval"]


def _weibull(beta_ci, alpha=7746.0, beta=1.77):
    return [{"name": "alpha", "value": alpha, "se": 1000.0, "ci": [alpha - 1960, alpha + 1960]},
            {"name": "beta", "value": beta, "se": 0.37, "ci": beta_ci}]


def test_replacement_flags_a_shape_interval_reaching_one():
    # The issue's case: β = 1.77, 95% CI [1.05, 2.49], costs 4,000 / 25,000.
    res = st.optimal_replacement("weibull", _weibull([1.05, 2.49]), 4000, 25000, unit="hours")
    assert res["beneficial"] is True and res["optimal_time"] == pytest.approx(3610, rel=1e-3)
    assert res["shape_ci"] == {"name": "beta", "value": 1.77, "lower": 1.05, "upper": 2.49, "level": 0.95}

    # At β = 1.05 preventive replacement doesn't pay; at 2.49 it does, as the
    # calculator gives for those parameters typed in.
    assert res["optimal_time_range"][0] is None and res["savings_range"][0] == 0.0
    upper = st.optimal_replacement("weibull", [{"name": "alpha", "value": 7746.0}, {"name": "beta", "value": 2.49}],
                                   4000, 25000)
    assert res["optimal_time_range"][1] == pytest.approx(upper["optimal_time"])
    assert res["savings_range"][1] == pytest.approx(upper["savings"])

    note = res["uncertainty_note"]
    assert note.startswith("The shape's 95% interval reaches 1.05: the data only weakly show wear-out")
    assert "at β = 1.05 preventive replacement doesn't pay" in note
    assert "at β = 2.49, replace at about 3,416 hours (45% saving)" in note
    assert res["recommendation"].startswith("Replace preventively at about 3,610 hours.")
    assert res["recommendation"].endswith(note)
    assert "held at their estimates" in res["sensitivity_method"]


def test_replacement_shape_interval_including_one():
    res = st.optimal_replacement("weibull", _weibull([-0.2, 2.7]), 4000, 25000)
    assert res["shape_ci"]["lower"] == 0.0  # a Wald interval below 0 is floored: the shape can't be negative
    assert "includes 1: the data don't rule out random failures" in res["uncertainty_note"]
    assert res["optimal_time_range"][0] is None and res["optimal_time_range"][1] > 0


def test_replacement_clear_wear_out_has_ranges_but_no_note():
    res = st.optimal_replacement("weibull", _weibull([2.2, 3.8], beta=3.0), 4000, 25000)
    assert res["uncertainty_note"] is None
    assert all(t > 0 for t in res["optimal_time_range"]) and all(s > 0 for s in res["savings_range"])
    assert "Replace preventively" in res["recommendation"] and "interval" not in res["recommendation"]


def test_replacement_without_a_covariance_is_unchanged():
    # Parameters typed in (or saved without data) carry no CI: no new fields.
    plain = [{"name": "alpha", "value": 7746.0}, {"name": "beta", "value": 1.77}]
    for params in (plain, [{**p, "se": None, "ci": None} for p in plain]):
        res = st.optimal_replacement("weibull", params, 4000, 25000)
        assert res["beneficial"] is True
        assert not {"shape_ci", "optimal_time_range", "savings_range", "uncertainty_note"} & set(res)


def test_failure_finding_reports_the_rate_interval():
    params = [{"name": "failure_rate", "value": 1e-3, "se": 2.5e-4, "ci": [5e-4, 1.5e-3]}]
    res = st.failure_finding("exponential", params, 0.99, "hours")
    assert res["interval"] == pytest.approx(20.0)
    assert res["interval_range"] == pytest.approx([0.02 / 1.5e-3, 0.02 / 5e-4])  # shortest first
    assert res["rate_ci"]["lower"] == 5e-4 and res["rate_ci"]["level"] == 0.95
    assert "runs from 13.3 to 40 hours" in res["uncertainty_note"]
    assert res["note"].endswith(res["uncertainty_note"])

    # A lower bound at 0: no upper limit on the interval.
    open_ended = st.failure_finding(
        "exponential", [{"name": "failure_rate", "value": 1e-3, "ci": [-2e-4, 2.2e-3]}], 0.99)
    assert open_ended["interval_range"][0] == pytest.approx(0.02 / 2.2e-3)
    assert open_ended["interval_range"][1] is None
    assert "don't bound the interval from above" in open_ended["uncertainty_note"]

    # No CI (typed in), or not exponential: unchanged.
    assert "interval_range" not in st.failure_finding("exponential", [{"name": "failure_rate", "value": 1e-3}], 0.99)
    assert "interval_range" not in st.failure_finding("weibull", _weibull([1.05, 2.49]), 0.99)
