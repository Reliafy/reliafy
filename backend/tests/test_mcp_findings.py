"""Regression tests for the findings of the adversarial MCP test (fix/mcp-test-findings).

Each test reproduces one report's repro through the real MCP mount (the
helpers and ``env`` fixture come from test_mcp) or, for shared validation,
through the service the web app uses too.
"""

import numpy as np
import pandas as pd
import pytest
import surpyval
from fastapi.testclient import TestClient

from backend.tests.test_mcp import A, TIMES, FLAGS, _call, _err, _ok, env  # noqa: F401 - env is a fixture

BEARINGS = "sample-model-bearings-weibull"
SEAL_PH = "sample-model-seal-weibull-ph"
PUMPS = "sample-model-pumps-weibull"


@pytest.fixture()
def samples(env):
    from backend.services import samples as samples_service

    samples_service.seed_samples(env.db)
    return env


def _weibull_of(db, model_id):
    r = db.models.find_one({"_id": model_id})["results"]
    p = {q["name"]: q["value"] for q in r["params"]}
    return surpyval.Weibull.from_params([p["alpha"], p["beta"]])


# ---- P1.1 reliability_at evaluates the distribution, not the stored curve -------

def test_reliability_at_is_exact_far_past_the_curve(samples):
    out = _ok(_call(samples.token[A], "reliability_at", {
        "model_id": BEARINGS, "times": [1e12, 250], "conditional_age": 1e6}))
    ref = _weibull_of(samples.db, BEARINGS)
    far, near = out["points"]
    assert out["method"] == "exact"
    assert far["reliability"] == 0.0 and far["failure"] == 1.0
    # Conditional on surviving to 1e6 (R ≈ 0): never the old 1.0.
    assert far["conditional_reliability"] in (0.0, None)
    assert near["reliability"] == pytest.approx(float(ref.sf(250)), rel=1e-12)
    assert near["density"] == pytest.approx(float(ref.df(250)), rel=1e-12)
    assert not any(p.get("beyond_curve") for p in out["points"])
    assert "held" not in out["note"]


def test_conditional_reliability_matches_the_ratio_in_range(samples):
    out = _ok(_call(samples.token[A], "reliability_at", {
        "model_id": BEARINGS, "times": [300], "conditional_age": 500}))
    ref = _weibull_of(samples.db, BEARINGS)
    want = float(ref.sf(800) / ref.sf(500))
    assert out["points"][0]["conditional_reliability"] == pytest.approx(want, rel=1e-9)


def test_ph_model_discloses_the_covariates_used(samples):
    from backend.services import models as models_service

    out = _ok(_call(samples.token[A], "reliability_at", {"model_id": SEAL_PH, "times": [1000, 5000]}))
    fields = samples.db.models.find_one({"_id": SEAL_PH})["results"]["functions"]["covariates"]
    defaults = {f["name"]: f["default"] for f in fields}
    assert out["method"] == "exact"
    assert out["covariates_used"] == defaults
    assert set(out["covariate_defaults"]) == set(defaults)
    for name, value in defaults.items():
        assert f"{name} = {value:g}" in out["note"]
    assert "training-data mean" in out["note"]
    # No beyond_curve flag contradicting the note, and the value is the live model's own.
    assert not any(p.get("beyond_curve") for p in out["points"])
    live = models_service.get_live_model(samples.db, SEAL_PH, None)
    Z = pd.DataFrame({k: [v] for k, v in defaults.items()})
    assert out["points"][0]["reliability"] == pytest.approx(float(live["model"].sf(np.array([1000.0]), Z)[0]))

    given = _ok(_call(samples.token[A], "reliability_at", {
        "model_id": SEAL_PH, "times": [1000], "covariates": {"temp_C": 60}}))
    assert given["covariates_used"]["temp_C"] == 60 and given["covariate_defaults"] == ["load"]
    msg = _err(_call(samples.token[A], "reliability_at", {
        "model_id": SEAL_PH, "times": [1000], "covariates": {"humidity": 3}}))
    assert "humidity" in msg and "temp_C" in msg
    msg = _err(_call(samples.token[A], "reliability_at", {
        "model_id": BEARINGS, "times": [1000], "covariates": {"temp_C": 60}}))
    assert "no covariates" in msg


def test_nonparametric_model_is_interpolated_and_says_so(env):
    saved = _ok(_call(env.token[A], "fit_and_save_model", {
        "data": TIMES, "censored": FLAGS, "distribution": "kaplan_meier", "name": "KM"}))
    out = _ok(_call(env.token[A], "reliability_at", {"model_id": saved["model_id"], "times": [500, 1e7]}))
    assert out["method"] == "interpolated"
    assert out["points"][1]["beyond_curve"] is True and "held at its end" in out["note"]
    assert not out["points"][0].get("beyond_curve")


def test_rest_reliability_is_exact_too(samples):
    from backend.main import app

    ref = _weibull_of(samples.db, BEARINGS)
    at = TestClient(app).post(f"/api/v1/models/{BEARINGS}/reliability",
                              headers={"Authorization": f"Bearer {samples.token[A]}"}, json={"t": 250}).json()["at"]
    assert at["reliability"] == pytest.approx(float(ref.sf(250)), rel=1e-12)


def test_analyze_rbd_reliability_at_is_exact_past_the_axis(env):
    graph = {"nodes": [
        {"id": "input", "type": "input"},
        {"id": "a", "type": "component", "label": "Motor", "model": {
            "distribution_id": "weibull", "params": [{"name": "alpha", "value": 1000}, {"name": "beta", "value": 2}]}},
        {"id": "output", "type": "output"}],
        "edges": [{"source": "input", "target": "a"}, {"source": "a", "target": "output"}]}
    rid = _ok(_call(env.token[A], "create_rbd", {"name": "One", **graph}))["id"]
    out = _ok(_call(env.token[A], "analyze_rbd", {"rbd_id": rid, "times": [500, 1e6]}))
    ref = surpyval.Weibull.from_params([1000, 2])
    assert out["reliability_at"][0]["reliability"] == pytest.approx(float(ref.sf(500)), rel=1e-9)
    assert out["reliability_at"][1]["reliability"] == 0.0


# ---- P1.2 parameter names are never read by position ---------------------------

def test_calculators_refuse_unrecognised_param_names(env):
    msg = _err(_call(env.token[A], "failure_finding_interval", {
        "distribution_id": "exponential", "params": [{"name": "mttf", "value": 10000}],
        "target_availability": 0.99}))
    assert "failure_rate" in msg and "mttf" in msg
    msg = _err(_call(env.token[A], "optimal_replacement", {
        "distribution_id": "weibull", "planned_cost": 1, "unplanned_cost": 10,
        "params": [{"name": "scale", "value": 1200}, {"name": "shape", "value": 2.5}]}))
    assert "alpha, beta" in msg and "scale" in msg

    # Any order still works, and matches the ordered call.
    ordered = _ok(_call(env.token[A], "optimal_replacement", {
        "distribution_id": "weibull", "planned_cost": 1, "unplanned_cost": 10,
        "params": [{"name": "alpha", "value": 1200}, {"name": "beta", "value": 2.5}]}))
    swapped = _ok(_call(env.token[A], "optimal_replacement", {
        "distribution_id": "Weibull", "planned_cost": 1, "unplanned_cost": 10,
        "params": [{"name": "beta", "value": 2.5}, {"name": "alpha", "value": 1200}]}))
    assert swapped["optimal_time"] == pytest.approx(ordered["optimal_time"])


def test_strategy_service_keeps_the_positional_api_shorthand():
    from backend.services import strategy

    named = strategy.failure_finding("weibull", [{"name": "beta", "value": 2}, {"name": "alpha", "value": 100}], 0.99)
    bare = strategy.failure_finding("weibull", [{"value": 100}, {"value": 2}], 0.99)
    assert named["interval"] == pytest.approx(bare["interval"])
    with pytest.raises(strategy.StrategyError, match="missing: beta"):
        strategy.failure_finding("weibull", [{"name": "alpha", "value": 100}], 0.99)


def test_rbd_blocks_refuse_unrecognised_param_names(env):
    bad = {"distribution_id": "weibull", "params": [{"name": "scale", "value": 900}, {"name": "shape", "value": 1.4}]}
    graph = {"nodes": [{"id": "input", "type": "input"}, {"id": "a", "type": "component", "label": "Pump", "model": bad},
                       {"id": "output", "type": "output"}],
             "edges": [{"source": "input", "target": "a"}, {"source": "a", "target": "output"}]}
    msg = _err(_call(env.token[A], "create_rbd", {"name": "Bad names", **graph}))
    assert "Pump" in msg and "alpha, beta" in msg and "scale" in msg

    stages = [{"components": [{"label": "Pump", "distribution": "weibull",
                               "params": [{"name": "eta", "value": 900}, {"name": "beta", "value": 1.4}]}]}]
    msg = _err(_call(env.token[A], "create_rbd", {"name": "Bad stage", "stages": stages}))
    assert "eta" in msg and "alpha" in msg
    assert env.db.rbds.count_documents({"owner_id": A}) == 0

    msg = _err(_call(env.token[A], "save_model", {
        "name": "x", "distribution": "exponential", "params": [{"name": "mttf", "value": 100}]}))
    assert "failure_rate" in msg and "mttf" in msg


def test_saved_rbd_with_bad_param_names_fails_analysis_clearly():
    from backend.services import rbd_analysis

    graph = {"nodes": [
        {"id": "input", "type": "input", "data": {}},
        {"id": "a", "type": "component", "data": {"label": "Fan", "model": {
            "distribution_id": "weibull", "params": [{"name": "scale", "value": 9}, {"name": "shape", "value": 1}]}}},
        {"id": "output", "type": "output", "data": {}}],
        "edges": [{"source": "input", "target": "a"}, {"source": "a", "target": "output"}]}
    check = rbd_analysis.validate_graph(graph)
    assert not check["valid"] and any("Fan" in e and "scale" in e for e in check["errors"])


# ---- P1.3 time-unit mismatch between a saved model and the diagram ---------------

def _saved_block_graph(model_id):
    return {"nodes": [{"id": "input", "type": "input"},
                      {"id": "p", "type": "component", "label": "Pump", "model": {"saved_model_id": model_id}},
                      {"id": "output", "type": "output"}],
            "edges": [{"source": "input", "target": "p"}, {"source": "p", "target": "output"}]}


def test_unit_mismatch_warns_on_create_and_analyze(samples):
    created = _ok(_call(samples.token[A], "create_rbd", {
        "name": "Mixed units", "unit": "Hours", **_saved_block_graph(PUMPS)}))
    assert any("months" in w and "Hours" in w and "Pump" in w for w in created["warnings"])
    out = _ok(_call(samples.token[A], "analyze_rbd", {"rbd_id": created["id"]}))
    assert any("months" in w for w in out["warnings"])

    same = _ok(_call(samples.token[A], "create_rbd", {
        "name": "Same units", "unit": "Months", **_saved_block_graph(PUMPS)}))
    assert not any("fitted in" in w for w in same["warnings"])


def test_unit_mismatch_is_in_the_apps_validation_and_blank_is_unknown():
    from backend.services import rbd_analysis

    def graph(diagram_unit, model_unit):
        return {"unit": diagram_unit, "nodes": [
            {"id": "input", "type": "input", "data": {}},
            {"id": "a", "type": "component", "data": {"label": "Seal", "model": {
                "source": "saved", "name": "Seal life", "unit": model_unit, "distribution_id": "weibull",
                "params": [{"name": "alpha", "value": 9}, {"name": "beta", "value": 1}]}}},
            {"id": "output", "type": "output", "data": {}}],
            "edges": [{"source": "input", "target": "a"}, {"source": "a", "target": "output"}]}

    assert any("Seal life" in w for w in rbd_analysis.validate_graph(graph("hours", "cycles"))["warnings"])
    for d, m in (("Hours", "hrs"), ("hours", ""), ("", "cycles"), ("Hours", None)):
        assert rbd_analysis.unit_warnings(graph(d, m)) == [], (d, m)
