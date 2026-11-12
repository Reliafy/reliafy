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


def test_failure_finding_without_an_interval_is_headed_as_the_menu_names_it():
    """A saved failure-finding analysis with no interval reads "Failure
    finding", the menu's word, not "Failure-finding interval"."""
    from types import SimpleNamespace

    from backend.services import strategy_store

    doc = SimpleNamespace(kind="failure_finding", results={"interval": None, "unit": "hours"})
    assert strategy_store.headline(doc) == "Failure finding"


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
    # SurPyval 0.23's name for the LFP fraction is read the same way.
    lfp_p = strategy_store.compute("optimal_replacement", {**inputs, "extras": {"lfp_p": 0.6}})
    assert lfp_p["recommendation"] == shown["recommendation"]

    rate = [{"name": "failure_rate", "value": 1e-3}]
    ff = strategy_store.compute("failure_finding", {
        "distribution_id": "exponential", "params": rate, "target_availability": 0.99,
        "extras": {"gamma": 500.0}})
    assert ff["interval"] == pytest.approx(
        st.failure_finding("exponential", rate, 0.99, extras={"gamma": 500.0})["interval"])
    assert ff["interval"] > st.failure_finding("exponential", rate, 0.99)["interval"]


# --- optimal replacement: the range, the reasons and the cost checks ----------

_PUMP = [
    {"name": "alpha", "value": 32.66, "se": 4.2, "ci": [25.32, 42.13]},
    {"name": "beta", "value": 1.819, "se": 0.37, "ci": [1.215, 2.721]},
]


def test_optimal_replacement_range_comes_from_the_parameter_bounds():
    res = st.optimal_replacement("weibull", _PUMP, 1000, 8000, unit="Months")
    rng = res["optimal_time_range"]
    assert rng["level"] == 0.95 and rng["always_beneficial"] is True
    assert [(c["param"], c["bound"]) for c in rng["cases"]] == [
        ("alpha", "lower"), ("alpha", "upper"), ("beta", "lower"), ("beta", "upper"),
    ]
    assert rng["lower"] < res["optimal_time"] < rng["upper"]
    # Each end is the same calculation run on the moved parameter.
    moved = [{"name": "alpha", "value": 25.32}, {"name": "beta", "value": 1.819}]
    assert rng["cases"][0]["optimal_time"] == pytest.approx(
        st.optimal_replacement("weibull", moved, 1000, 8000)["optimal_time"]
    )
    note = res["optimal_time_range_note"]
    assert "months" in note and "not a confidence interval" in note


def test_optimal_replacement_has_no_range_without_bounds():
    plain = [{"name": "alpha", "value": 32.66}, {"name": "beta", "value": 1.819}]
    entered = [{**p, "se": None, "ci": None} for p in plain]
    for params in (plain, entered):
        res = st.optimal_replacement("weibull", params, 1000, 8000)
        assert res["beneficial"] is True
        assert res["optimal_time_range"] is None
        assert "without confidence bounds" in res["optimal_time_range_note"]


def test_optimal_replacement_range_says_when_a_bound_stops_paying():
    params = [_PUMP[0], {"name": "beta", "value": 1.819, "ci": [0.9, 3.6]}]
    res = st.optimal_replacement("weibull", params, 1000, 8000)
    assert res["beneficial"] is True
    assert res["optimal_time_range"]["always_beneficial"] is False
    assert "beta at its lower bound (0.9)" in res["optimal_time_range_note"]


@pytest.mark.parametrize("dist, params, reason, words", [
    ("exponential", [{"name": "failure_rate", "value": 0.001}], "constant_failure_rate", "failure rate is constant"),
    ("weibull", [{"name": "alpha", "value": 30}, {"name": "beta", "value": 0.8}], "no_wear_out", "falls with age"),
    ("weibull", [{"name": "alpha", "value": 30}, {"name": "beta", "value": 1.0}], "no_wear_out", "failure rate is constant"),
])
def test_optimal_replacement_says_why_no_age_pays(dist, params, reason, words):
    res = st.optimal_replacement(dist, params, 1000, 8000)
    assert res["beneficial"] is False and res["optimal_time"] is None
    assert res["reason"] == reason
    assert res["recommendation"].startswith("Replacing on age doesn't pay for this model")
    assert words in res["recommendation"]


def test_optimal_replacement_reason_is_none_when_it_pays():
    assert st.optimal_replacement("weibull", _PUMP, 1000, 8000)["reason"] is None


@pytest.mark.parametrize("cp, cu, words", [
    (-5, 8000, "can't be negative"),
    (0, 8000, "planned cost above 0"),
    (8000, 8000, "must be higher than the planned cost"),
    (9000, 8000, "must be higher than the planned cost"),
])
def test_optimal_replacement_cost_messages_say_what_to_do(cp, cu, words):
    with pytest.raises(StrategyError, match=words):
        st.optimal_replacement("weibull", _PUMP, cp, cu)


def test_optimal_replacement_answers_in_the_models_own_unit():
    """12 Nov review: a bearing model fitted in days (Weibull α 581, β 5.94)
    with costs 1,050 / 9,000 replaces at about 316 days, and says days, not
    hours. With no unit the sentence carries no unit word (never a default)."""
    params = [{"name": "alpha", "value": 581.0}, {"name": "beta", "value": 5.94}]
    res = st.optimal_replacement("weibull", params, 1050, 9000, unit="Days")
    assert res["optimal_time"] == pytest.approx(316, abs=1)
    assert res["unit"] == "Days"
    assert "about 316 days" in res["recommendation"]
    assert "hours" not in res["recommendation"]
    bare = st.optimal_replacement("weibull", params, 1050, 9000)
    assert "about 316." in bare["recommendation"] and "hour" not in bare["recommendation"]
