"""Regression tests for the findings of the adversarial MCP test (fix/mcp-test-findings).

Each test reproduces one report's repro through the real MCP mount (the
helpers and ``env`` fixture come from test_mcp) or, for shared validation,
through the service the web app uses too.
"""

import math

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


# ---- P2.5 an RBD must run from one input to one output --------------------------

def _w(alpha=1000, beta=2):
    return {"distribution_id": "weibull", "params": [{"name": "alpha", "value": alpha}, {"name": "beta", "value": beta}]}


def test_create_rbd_refuses_a_diagram_with_no_output(env):
    msg = _err(_call(env.token[A], "create_rbd", {
        "name": "No output", "nodes": [{"id": "input", "type": "input"}, {"id": "a", "type": "component", "model": _w()}],
        "edges": [{"source": "input", "target": "a"}]}))
    assert "exactly one output node" in msg
    assert env.db.rbds.count_documents({"owner_id": A}) == 0


def test_analyze_rbd_never_returns_an_empty_error(env, monkeypatch):
    from backend.services import rbd_graph, rbds as rbds_service

    # A malformed diagram saved some other way (the app saves drafts unvalidated).
    graph = rbd_graph.normalize_graph({"nodes": [{"id": "input", "type": "input"},
                                                 {"id": "a", "type": "component", "model": _w()}],
                                       "edges": [{"source": "input", "target": "a"}]})
    rid = rbds_service.save_rbd(env.db, "Draft", graph, A).id
    msg = _err(_call(env.token[A], "analyze_rbd", {"rbd_id": rid}))
    assert "exactly one output node" in msg

    # Anything unexpected still reaches the caller as an explanation, not "Error executing tool".
    ok = _ok(_call(env.token[A], "create_rbd", {"name": "Fine", **_chain("Motor")}))

    def boom(*a, **k):
        raise IndexError("index 1 is out of bounds")

    monkeypatch.setattr(rbds_service, "analyze_graph", boom)
    msg = _err(_call(env.token[A], "analyze_rbd", {"rbd_id": ok["id"]}))
    assert "couldn't analyse" in msg and "IndexError" in msg and "get_rbd" in msg


def test_app_validation_reports_missing_io_nodes():
    from backend.services import rbd_analysis, rbd_graph

    graph = rbd_graph.normalize_graph({"nodes": [{"id": "input", "type": "input"},
                                                 {"id": "a", "type": "component", "model": _w()}],
                                       "edges": [{"source": "input", "target": "a"}]})
    check = rbd_analysis.validate_graph(graph)
    assert not check["valid"] and any("exactly one output node" in e for e in check["errors"])
    with pytest.raises(rbd_analysis.AnalysisError, match="exactly one output node"):
        rbd_analysis.analyze(graph)


# ---- P2.6 the stages form refuses settings it can't honour -----------------------

def _stage(n, **kw):
    return {"label": "Pumps", "components": [
        {"label": f"Pump {i + 1}", "distribution": "weibull",
         "params": [{"name": "alpha", "value": 900}, {"name": "beta", "value": 1.4}]} for i in range(n)], **kw}


def test_stage_settings_are_refused_not_clamped(env):
    for kw, needle in (({"k_of_n": 3}, "between 1 and 2"), ({"k_of_n": 0}, "between 1 and 2"),
                       ({"common_cause_beta": 5}, "0 ≤ beta < 1"), ({"common_cause_beta": -0.1}, "0 ≤ beta < 1"),
                       ({"common_cause_beta": 1}, "0 ≤ beta < 1")):
        msg = _err(_call(env.token[A], "create_rbd", {"name": "S", "stages": [_stage(2, **kw)]}))
        assert needle in msg, (kw, msg)
    msg = _err(_call(env.token[A], "create_rbd", {"name": "S", "stages": [_stage(1, common_cause_beta=0.1)]}))
    assert "2 or more components" in msg
    assert env.db.rbds.count_documents({"owner_id": A}) == 0

    ok = _ok(_call(env.token[A], "create_rbd", {"name": "S", "stages": [_stage(2, common_cause_beta=0.1, k_of_n=2)]}))
    doc = env.db.rbds.find_one({"_id": ok["id"]})
    assert doc["graph"]["ccf_groups"][0]["beta"] == 0.1
    knode = next(n for n in doc["graph"]["nodes"] if n["type"] == "knode")
    assert knode["data"]["n"] == 2
    # 2 of 2 is a series structure: warned, in our words (no "strucuture").
    assert any("series structure" in w for w in ok["warnings"])
    assert not any("strucuture" in w for w in ok["warnings"])


# ---- P2.7 redundant-looking blocks wired in series -------------------------------

def _chain(*labels):
    nodes = [{"id": "input", "type": "input"}] + [
        {"id": f"n{i}", "type": "component", "label": lab, "model": _w()} for i, lab in enumerate(labels)
    ] + [{"id": "output", "type": "output"}]
    ids = [n["id"] for n in nodes]
    return {"nodes": nodes, "edges": [{"source": s, "target": t} for s, t in zip(ids, ids[1:])]}


def test_redundant_pair_in_series_is_a_warning(env):
    out = _ok(_call(env.token[A], "create_rbd", {"name": "Pumps", **_chain("Pump A", "Pump B (standby)")}))
    assert any("Pump A" in w and "Pump B (standby)" in w and "parallel" in w for w in out["warnings"])
    res = _ok(_call(env.token[A], "analyze_rbd", {"rbd_id": out["id"]}))
    assert any("redundant pair" in w for w in res["warnings"])


def test_redundancy_heuristic_keeps_false_positives_low():
    from backend.services import rbd_analysis, rbd_graph
    from backend.tests.test_mcp import GRAPH

    def warned(*labels):
        return rbd_analysis.series_redundancy_warnings(rbd_graph.normalize_graph(_chain(*labels)))

    for pair in (("Valve 1", "Valve 2"), ("P1", "P2"), ("Train i", "Train ii"), ("Fan left", "Fan right"),
                 ("Controller", "Backup battery"), ("Duty pump", "Filter")):
        assert warned(*pair), pair
    for pair in (("Controller", "Pump A"), ("Stage 1 pump", "Stage 2 pump"), ("Main pump", "Main valve"),
                 ("Motor", "Gearbox"), ("Bearing", "Bearing")):
        assert not warned(*pair), pair
    # Only directly adjacent series blocks: a parallel pair is fine.
    assert not rbd_analysis.series_redundancy_warnings(rbd_graph.normalize_graph(GRAPH))


def test_a_standby_nodes_own_label_is_not_a_redundant_pair():
    """#183: "duty/standby" in a standby (or parallel / load-sharing) node's
    label describes its own units, not its neighbours in series."""
    from backend.services import rbd_analysis, rbd_graph

    for ntype in ("standby", "parallel", "loadshare"):
        graph = rbd_graph.normalize_graph(
            _chain("Suction strainer", "CW pumps A/B (duty/standby)", "Discharge check valve"))
        next(n for n in graph["nodes"] if n["id"] == "n1")["type"] = ntype
        assert not rbd_analysis.series_redundancy_warnings(graph), ntype
    # A plain component so labelled still warns.
    graph = _chain("Suction strainer", "CW pump (standby)")
    assert rbd_analysis.series_redundancy_warnings(rbd_graph.normalize_graph(graph))


# ---- P2.8 conflicting inputs are refused, never resolved silently ----------------

def test_conflicting_inputs_are_refused(samples):
    a = samples.token[A]
    inline = {"distribution_id": "weibull", "params": [{"name": "alpha", "value": 10}, {"name": "beta", "value": 3}]}
    msg = _err(_call(a, "optimal_replacement", {"model_id": BEARINGS, **inline, "planned_cost": 1, "unplanned_cost": 9}))
    assert "exactly one of model_id or distribution_id + params" in msg
    msg = _err(_call(a, "failure_finding_interval", {"model_id": BEARINGS, **inline, "target_availability": 0.9}))
    assert "exactly one of model_id" in msg

    msg = _err(_call(a, "fit_distribution", {"data": TIMES, "time_column": "hours"}))
    assert "time_column" in msg and "dataset_id" in msg
    ds = _ok(_call(a, "upload_dataset", {"name": "d", "csv": "t,c\n" + "\n".join(
        f"{t},{c}" for t, c in zip(TIMES, FLAGS))}))
    msg = _err(_call(a, "fit_distribution", {"dataset_id": ds["id"], "time_column": "t", "censored": FLAGS}))
    assert "censored" in msg and "inline data" in msg

    graph = _saved_block_graph(BEARINGS)
    msg = _err(_call(a, "create_rbd", {"name": "x", "stages": [_stage(1)], "edges": graph["edges"]}))
    assert "exactly one form" in msg
    clash = {**graph, "nodes": [{**n, "model": {"saved_model_id": BEARINGS, **inline}} if n["id"] == "p" else n
                                for n in graph["nodes"]]}
    msg = _err(_call(a, "create_rbd", {"name": "x", **clash}))
    assert "exactly one of saved_model_id" in msg
    stage = {"components": [{"label": "Bearing", "model_id": BEARINGS, "distribution": "weibull",
                             "params": inline["params"]}]}
    assert "exactly one of model_id" in _err(_call(a, "create_rbd", {"name": "x", "stages": [stage]}))

    # get_rbd's compact form (saved id + its own params) still round-trips.
    created = _ok(_call(a, "create_rbd", {"name": "Linked", **graph}))
    compact = _ok(_call(a, "get_rbd", {"rbd_id": created["id"]}))["graph"]
    again = _ok(_call(a, "create_rbd", {"name": "Copy", "nodes": compact["nodes"], "edges": compact["edges"],
                                        "include_graph": True}))
    assert next(n for n in again["graph"]["nodes"] if n["id"] == "p")["model"]["saved_model_id"] == BEARINGS


def test_fleet_alert_refuses_arguments_its_kind_ignores(env):
    from backend.tests.test_fleet_alerts import _mcp_fleet

    fid = _mcp_fleet(env)
    msg = _err(_call(env.token[A], "create_fleet_alert", {"fleet_id": fid, "kind": "above", "threshold": 2, "percent": 5}))
    assert "percent" in msg and "threshold" in msg


# ---- P2.9 negative times -----------------------------------------------------------

def test_negative_times_are_refused(samples):
    a = samples.token[A]
    assert "≥ 0" in _err(_call(a, "reliability_at", {"model_id": BEARINGS, "times": [-100]}))
    assert "conditional_age" in _err(_call(a, "reliability_at", {
        "model_id": BEARINGS, "times": [1], "conditional_age": -5}))
    zero = _ok(_call(a, "reliability_at", {"model_id": BEARINGS, "times": [0]}))
    assert zero["points"][0]["reliability"] == 1.0

    rid = _ok(_call(a, "create_rbd", {"name": "One", **_chain("Motor")}))["id"]
    for bad in (-10, 0):
        assert "t_max must be a positive" in _err(_call(a, "analyze_rbd", {"rbd_id": rid, "t_max": bad}))
    assert "≥ 0" in _err(_call(a, "analyze_rbd", {"rbd_id": rid, "times": [-1]}))
    assert "conditional_age" in _err(_call(a, "analyze_rbd", {"rbd_id": rid, "conditional_age": -1}))


def test_repairable_analysis_refuses_reliability_only_arguments(env):
    from backend.tests.test_mcp import REPAIRABLE_STAGES

    rid = _ok(_call(env.token[A], "create_rbd", {"name": "R", "repairable": True, "stages": REPAIRABLE_STAGES}))["id"]
    assert "non-repairable" in _err(_call(env.token[A], "analyze_rbd", {"rbd_id": rid, "times": [10]}))


def test_optimal_overhaul_refuses_a_non_positive_t_max(env):
    from backend.services import recurrent as recurrent_service

    doc = recurrent_service.save_from_params(
        env.db, "Compressors", "crow_amsaa",
        [{"name": "alpha", "value": 1000}, {"name": "beta", "value": 2}], 5000, "hours", A)
    msg = _err(_call(env.token[A], "optimal_overhaul", {
        "model_id": doc.id, "cost_repair": 100, "cost_overhaul": 1000, "t_max": -1}))
    assert "t_max must be a positive" in msg


# ---- P3.12 an impossible k-of-n gate is explained up front ------------------------

def test_impossible_vote_node_is_explained(env):
    nodes = [{"id": "input", "type": "input"},
             {"id": "a", "type": "component", "label": "Pump A", "model": _w()},
             {"id": "b", "type": "component", "label": "Pump B", "model": _w()},
             {"id": "v", "type": "knode", "label": "v", "n": 5, "k": 2},
             {"id": "output", "type": "output"}]
    edges = [{"source": "input", "target": "a"}, {"source": "input", "target": "b"},
             {"source": "a", "target": "v"}, {"source": "b", "target": "v"}, {"source": "v", "target": "output"}]
    msg = _err(_call(env.token[A], "create_rbd", {"name": "Vote", "nodes": nodes, "edges": edges}))
    assert "Vote node “v” requires 5 working inputs but only 2 branches feed it" in msg
    assert "no paths through" not in msg


# ---- P3.10 / P3.11 censoring messages speak MCP ---------------------------------

def test_censoring_errors_name_the_c_invert_parameter(env):
    a = env.token[A]
    msg = _err(_call(a, "fit_distribution", {"data": [100, 200, 300], "censored": [1, 1, 1]}))
    assert "c_invert=true" in msg and "tick" not in msg and "0 = the unit failed" in msg
    msg = _err(_call(a, "fit_distribution", {"data": [100, 200, 300], "censored": [0, 1, 1]}))
    assert "Only 1 of the 3" in msg and "c_invert=true" in msg and "tick" not in msg
    msg = _err(_call(a, "fit_distribution", {"data": [100, 200, 300], "censored": [0, 0, 0], "c_invert": True}))
    assert "drop c_invert" in msg and "tick" not in msg
    # The app keeps its own wording.
    from backend import fitting

    with pytest.raises(fitting.FitError, match="My censor column uses 1 = failed"):
        fitting.fit("weibull", pd.DataFrame({"x": [1, 2], "c": [1, 1]}), {"x": "x", "c": "c"})


def test_left_censoring_is_documented_and_explained(env):
    from backend.tests.test_mcp import _run

    tools = {t.name: t for t in _run(env.token[A], lambda c: c.list_tools()).tools}
    assert "-1 = left-censored" in str(tools["fit_distribution"].input_schema)
    msg = _err(_call(env.token[A], "fit_distribution", {"data": TIMES, "censored": [2] + FLAGS[1:]}))
    assert "-1 (left-censored" in msg and "0 (failed" in msg
    out = _ok(_call(env.token[A], "fit_distribution", {"data": TIMES, "censored": [-1] + FLAGS[1:]}))
    assert out["params"]


# ---- P3.13 degenerate fits are flagged ----------------------------------------------

def test_zero_variance_best_fit_is_flagged(env):
    out = _ok(_call(env.token[A], "fit_distribution", {"data": [5.0] * 6, "distribution": "best"}))
    assert any("identical" in w for w in out["warnings"])
    failed = out["selection"]["failed"]
    assert failed and all({"id", "name", "reason"} <= set(f) for f in failed)
    n_ok = len(out["selection"]["candidates"])
    assert n_ok + len(failed) == 11
    assert any(f"Only {n_ok} of the 11" in w for w in out["warnings"])


def test_failed_mle_leads_with_fit_ok_false(env):
    from backend import fitting

    data = [1e-300, 1e-100, 1.0, 1e100, 1e300]
    out = _ok(_call(env.token[A], "fit_distribution", {"data": data}))
    assert list(out)[:2] == ["fit_ok", "warning"] and out["fit_ok"] is False
    assert "did NOT converge" in out["warning"]
    # One warning, phrased for an agent: no duplicate fit_warning, no Python-API advice.
    assert "fit_warning" not in out and "init" not in out["warning"] and "fit()" not in out["warning"]
    assert out["warning"].count("did NOT converge") == 1 and "rescaling" in out["warning"]
    # The app's payload gains the flag (additive) and keeps fit_warning for its view.
    app = fitting.fit("weibull", pd.DataFrame({"x": data}), {"x": "x"})
    assert app["fit_ok"] is False and app["fit_warning"]
    ok = fitting.fit("weibull", pd.DataFrame({"x": TIMES}), {"x": "x"})
    assert ok["fit_ok"] is True and "warnings" not in ok


# ---- P3.14 notes use significant figures ------------------------------------------

def test_notes_never_round_small_numbers_to_zero(env):
    from backend.services.strategy import fmt_num

    ff = _ok(_call(env.token[A], "failure_finding_interval", {
        "distribution_id": "exponential", "params": [{"name": "failure_rate", "value": 10}],
        "target_availability": 0.99}))
    assert "about every 0.002" in ff["note"]
    assert [fmt_num(v) for v in (0, 2e-5, 0.0123, 1.5, 999.6, 12345.6, 3.2e9)] == [
        "0", "2e-05", "0.0123", "1.5", "1,000", "12,346", "3.2e+09"]


# ---- #189 optimal_replacement flags a shape interval that reaches 1 -----------------------

def _fitted_weibull(env, name, seed, beta, n=30, cutoff=7000.0):
    """A saved Weibull fitted to n units of Weibull(7746, beta) life, still running at cutoff."""
    rng = np.random.default_rng(seed)
    t = 7746 * rng.weibull(beta, n)
    flags = [int(x > cutoff) for x in t]
    out = _ok(_call(env.token[A], "fit_and_save_model", {
        "name": name, "data": [round(min(x, cutoff), 1) for x in t], "censored": flags, "unit": "hours"}))
    (b,) = [p for p in out["params"] if p["name"] == "beta"]
    return out["model_id"], b


def test_optimal_replacement_flags_weak_wear_out_evidence(env):
    costs = {"planned_cost": 4000, "unplanned_cost": 25000}
    weak, b = _fitted_weibull(env, "Weak", seed=1, beta=1.77)  # β ≈ 1.97, 95% CI ≈ [1.09, 2.84]
    assert 1 < b["ci"][0] < 1.2
    out = _ok(_call(env.token[A], "optimal_replacement", {"model_id": weak, **costs}))
    assert out["beneficial"] is True
    su = out["shape_uncertainty"]
    assert su["beta_ci_95"] == [float(f"{v:.4g}") for v in b["ci"]] and su["held_fixed"] == "alpha at its estimate"
    assert su["at_beta_lower"]["savings"] < 0.5 * out["savings"] < su["at_beta_upper"]["savings"]
    assert "reaches down to 1.09" in out["uncertainty_note"] and "weakly" in out["uncertainty_note"]

    random_ish, b = _fitted_weibull(env, "Random-ish", seed=3, beta=1.77)  # CI ≈ [0.91, 2.23]
    assert b["ci"][0] < 1 < b["ci"][1]
    out = _ok(_call(env.token[A], "optimal_replacement", {"model_id": random_ish, **costs}))
    assert "includes 1" in out["uncertainty_note"]
    assert out["shape_uncertainty"]["at_beta_lower"]["beneficial"] is False

    clear, b = _fitted_weibull(env, "Clear", seed=7, beta=4.0, n=60, cutoff=1e9)
    out = _ok(_call(env.token[A], "optimal_replacement", {"model_id": clear, **costs}))
    assert b["ci"][0] > 3 and out["shape_uncertainty"]["at_beta_lower"]["beneficial"]
    assert "uncertainty_note" not in out

    inline = _ok(_call(env.token[A], "optimal_replacement", {
        "distribution_id": "weibull", "params": [{"name": "alpha", "value": 7746}, {"name": "beta", "value": 1.77}],
        **costs}))
    assert "shape_uncertainty" not in inline and "uncertainty_note" not in inline  # no fit, no interval


def test_failure_finding_interval_gets_the_shape_treatment(env):
    """#189 follow-up: the failure-finding interval at each end of a fitted
    Weibull's β interval (α held), and a note when an end asks for a test
    interval 20%+ shorter than the estimate's — the unsafe side."""
    target = {"target_availability": 0.99}
    early, b = _fitted_weibull(env, "Early", seed=3, beta=0.6, n=20, cutoff=1e9)  # β ≈ 0.62, CI ≈ [0.41, 0.83]
    out = _ok(_call(env.token[A], "failure_finding_interval", {"model_id": early, **target}))
    su = out["shape_uncertainty"]
    assert su["beta_ci_95"] == [float(f"{v:.4g}") for v in b["ci"]] and su["held_fixed"] == "alpha at its estimate"
    alpha = next(p["value"] for p in _ok(_call(env.token[A], "get_model", {"model_id": early}))["params"]
                 if p["name"] == "alpha")
    for end, beta in (("at_beta_lower", b["ci"][0]), ("at_beta_upper", b["ci"][1])):
        expected = 2 * 0.01 * alpha * math.gamma(1 + 1 / beta)  # FFI = 2(1 - A) MTTF, α held
        assert su[end]["interval"] == pytest.approx(expected, rel=1e-3)
    assert su["at_beta_upper"]["interval"] < 0.8 * out["interval"]
    assert "as short as" in out["uncertainty_note"] and "shorter one" in out["uncertainty_note"]

    clear, _ = _fitted_weibull(env, "Clear", seed=7, beta=4.0, n=60, cutoff=1e9)
    out = _ok(_call(env.token[A], "failure_finding_interval", {"model_id": clear, **target}))
    assert out["shape_uncertainty"]["at_beta_lower"]["interval"] > 0.8 * out["interval"]
    assert "uncertainty_note" not in out

    inline = _ok(_call(env.token[A], "failure_finding_interval", {
        "distribution_id": "weibull", "params": [{"name": "alpha", "value": 7746}, {"name": "beta", "value": 0.6}],
        **target}))
    assert "shape_uncertainty" not in inline and "uncertainty_note" not in inline  # no fit, no interval


def _nhpp_model(env, name, seed, beta, systems, window):
    """A saved Crow-AMSAA model fitted to power-law (alpha 1000) event times."""
    from backend.services import datasets as datasets_service
    from backend.services import recurrent as recurrent_service

    rng = np.random.default_rng(seed)
    lines = ["system,time,window"]
    for s in range(systems):
        t = 1000.0 * np.cumsum(rng.exponential(1.0, 400)) ** (1.0 / beta)
        lines += [f"S{s},{x:.2f},{window}" for x in t[t <= window]]
    ds = datasets_service.create_dataset(env.db, name, "\n".join(lines).encode(), A)
    spec = {"mapping": {"i": "system", "x": "time", "tr": "window"}, "model_id": "crow_amsaa", "unit": "hours"}
    return recurrent_service.save_model(env.db, name, ds, spec, A)


def test_optimal_overhaul_gets_the_shape_treatment(env):
    """#189 follow-up: the overhaul optimum at each end of the Crow-AMSAA
    β interval (α held, savings over the estimate's horizon), and the same
    notes as optimal_replacement."""
    from backend import recurrent as recurrent_fit
    from backend.services import recurrent as recurrent_service

    costs = {"cost_repair": 100, "cost_overhaul": 1000}
    clear = _nhpp_model(env, "Compressors", seed=1, beta=2.5, systems=5, window=3000)
    (a, b) = clear.results["params"]
    assert 2.0 < b["ci"][0] < b["value"] < b["ci"][1]  # the interval is stored with the fit
    out = _ok(_call(env.token[A], "optimal_overhaul", {"model_id": clear.id, **costs}))
    su = out["shape_uncertainty"]
    assert su["beta_ci_95"] == [float(f"{v:.4g}") for v in b["ci"]] and su["held_fixed"] == "alpha at its estimate"
    low = recurrent_fit.optimal_overhaul({"model_id": "crow_amsaa", "params": [a["value"], b["ci"][0]]}, 100, 1000)
    assert su["at_beta_lower"]["optimal_interval"] == pytest.approx(low["optimal"]["interval"], rel=1e-3)
    assert su["at_beta_lower"]["saving_pct"] == pytest.approx(low["saving_pct"], rel=1e-3)
    assert su["at_beta_lower"]["horizon"] == pytest.approx(3 * low["optimal"]["interval"], rel=1e-3)
    assert su["at_beta_lower"]["pays"] and su["at_beta_lower"]["saving_pct"] >= 0.5 * out["saving_pct"]
    assert "uncertainty_note" not in out

    weak = _nhpp_model(env, "Pumps", seed=2, beta=1.5, systems=2, window=2000)
    out = _ok(_call(env.token[A], "optimal_overhaul", {"model_id": weak.id, **costs}))
    assert out["optimal"] and out["shape_uncertainty"]["beta_ci_95"][0] < 1
    assert out["shape_uncertainty"]["at_beta_lower"]["pays"] is False
    assert "includes 1" in out["uncertainty_note"] and "tentative" in out["uncertainty_note"]

    # A model saved before intervals were stored gets one from a refit, kept on the model.
    params = [{k: v for k, v in p.items() if k != "ci"} for p in clear.results["params"]]
    env.db.recurrent_models.update_one({"_id": clear.id}, {"$set": {"results.params": params}})
    assert "shape_uncertainty" in _ok(_call(env.token[A], "optimal_overhaul", {"model_id": clear.id, **costs}))
    assert env.db.recurrent_models.find_one({"_id": clear.id})["results"]["params"][1]["ci"]

    # Built from parameters: no data, no interval.
    doc = recurrent_service.save_from_params(
        env.db, "Typed", "crow_amsaa", [{"name": "alpha", "value": 1000}, {"name": "beta", "value": 2}], 5000,
        "hours", A)
    out = _ok(_call(env.token[A], "optimal_overhaul", {"model_id": doc.id, **costs}))
    assert "shape_uncertainty" not in out and "uncertainty_note" not in out


# ---- #190 a censor column named like a failure flag -----------------------------------

def test_fit_warns_when_the_censor_column_sounds_like_1_means_failed(env):
    from backend import mcp_server

    failed = [1 - f for f in FLAGS]  # the spreadsheet way: 1 = failed
    ds = _ok(_call(env.token[A], "upload_dataset", {
        "name": "Pumps", "csv": "hours,failed,censored\n"
        + "\n".join(f"{t},{a},{b}" for t, a, b in zip(TIMES, failed, FLAGS))}))
    base = {"dataset_id": ds["id"], "time_column": "hours"}

    out = _ok(_call(env.token[A], "fit_distribution", {**base, "censor_column": "failed"}))
    (warning,) = [w for w in out["warnings"] if "c_invert" in w]
    assert "“failed” sounds like 1 = failed" in warning and "3 failures and 7 still running" in warning
    assert list(out)[0] == "warnings"  # ahead of the numbers
    assert out["censoring"] == {"n_failed": 3, "n_right_censored": 7, "n_left_censored": 0}

    fixed = _ok(_call(env.token[A], "fit_distribution", {**base, "censor_column": "failed", "c_invert": True}))
    assert "warnings" not in fixed and fixed["censoring"]["n_failed"] == 7
    plain = _ok(_call(env.token[A], "fit_distribution", {**base, "censor_column": "censored"}))
    assert "warnings" not in plain and plain["censoring"]["n_failed"] == 7
    assert [p["value"] for p in plain["params"]] == pytest.approx([p["value"] for p in fixed["params"]])

    saved = _ok(_call(env.token[A], "fit_and_save_model", {**base, "censor_column": "failed", "name": "Pumps"}))
    assert any("c_invert=true" in w for w in saved["warnings"]) and saved["censoring"]["n_failed"] == 3

    names = {"failed": True, "Failed?": True, "is_failure": True, "FailFlag": True, "Status": True,
             "event": True, "censored": False, "suspended": False, "fail_or_censor": False, "c": False}
    assert {n: mcp_server._sounds_like_failure_flag(n) for n in names} == names


# ---- P3.15 large payloads are opt-in --------------------------------------------------

def test_calculator_curves_are_opt_in(env):
    args = {"distribution_id": "weibull", "planned_cost": 1, "unplanned_cost": 10,
            "params": [{"name": "alpha", "value": 1200}, {"name": "beta", "value": 2.5}]}
    out = _ok(_call(env.token[A], "optimal_replacement", args))
    assert "curve" not in out and "include_curve" in out["curve_omitted"] and out["optimal_time"]
    full = _ok(_call(env.token[A], "optimal_replacement", {**args, "include_curve": True}))
    assert len(full["curve"]["t"]) == 200

    from backend.services import recurrent as recurrent_service

    doc = recurrent_service.save_from_params(
        env.db, "Compressors", "crow_amsaa",
        [{"name": "alpha", "value": 1000}, {"name": "beta", "value": 2}], 5000, "hours", A)
    base = {"model_id": doc.id, "cost_repair": 100, "cost_overhaul": 1000}
    assert "curve" not in _ok(_call(env.token[A], "optimal_overhaul", base))
    assert _ok(_call(env.token[A], "optimal_overhaul", {**base, "include_curve": True}))["curve"]["t"]


def test_fleet_forecast_lists_the_top_items_by_default(env):
    from backend.services import fleet as fs
    from backend.tests.test_fleet_alerts import _mcp_fleet

    fid = _mcp_fleet(env)
    fs.replace_items(env.db, fid, {"periods": 6, "default_rate": 5, "method": "single"},
                     [{"name": f"P{i}", "current_use": 10 + 3 * i} for i in range(30)], A)
    out = _ok(_call(env.token[A], "fleet_forecast", {"fleet_id": fid}))
    items = out["forecast"]["per_item"]
    assert len(items) == 20 and "30 items" in out["forecast"]["per_item_note"]
    assert items == sorted(items, key=lambda r: -r["expected"])
    assert len(_ok(_call(env.token[A], "fleet_forecast", {"fleet_id": fid, "include_items": True}))
               ["forecast"]["per_item"]) == 30


# ---- P3.16 the export's run command is the script's own ---------------------------

def test_export_run_matches_the_script_header(env):
    from backend.services import rbd_export

    rid = _ok(_call(env.token[A], "create_rbd", {"name": "One", **_chain("Motor")}))["id"]
    out = _ok(_call(env.token[A], "export_rbd_python", {"rbd_id": rid}))
    assert out["run"] == rbd_export.run_command(out["filename"])
    assert out["run"].endswith(f"python {out['filename']}")
    v = rbd_export.detect_versions()
    assert f"--no-deps \"git+https://github.com/derrynknife/RePyability.git@v{v['repyability']}\"" in out["run"]
    header = out["script"].split('"""')[1]
    flat = header.replace("\\\n        ", "")
    for cmd in rbd_export.install_commands():
        assert cmd in flat


# ---- P3.17 delete tools --------------------------------------------------------------

def test_delete_tools_follow_the_apps_rules(samples):
    from backend.mcp_server import PRO_ONLY_TOOLS, UNGATED_TOOLS
    from backend.tests.test_mcp import B

    a = samples.token[A]
    # Every plan, counted against the quota like any other tool.
    assert not {"delete_model", "delete_dataset", "delete_rbd"} & (PRO_ONLY_TOOLS | UNGATED_TOOLS)

    saved = _ok(_call(a, "fit_and_save_model", {"data": TIMES, "censored": FLAGS, "name": "Mine"}))
    mid, did = saved["model_id"], saved["dataset_id"]
    rbd = _ok(_call(a, "create_rbd", {"name": "Uses it", **_saved_block_graph(mid)}))

    # Samples and other people's artifacts are off limits.
    assert "shared sample" in _err(_call(a, "delete_model", {"model_id": BEARINGS}))
    assert "shared sample" in _err(_call(a, "delete_dataset", {"dataset_id": "sample-ds-bearings"}))
    sample_rbd = samples.db.rbds.find_one({"owner_id": "__samples__"})["_id"]
    assert "shared sample" in _err(_call(a, "delete_rbd", {"rbd_id": sample_rbd}))
    assert "not found" in _err(_call(samples.token[B], "delete_model", {"model_id": mid})).lower()
    assert samples.db.models.find_one({"_id": BEARINGS}) is not None

    # The app's dependency rule: a dataset in use by a model can't go.
    msg = _err(_call(a, "delete_dataset", {"dataset_id": did}))
    assert "used by 1 model" in msg and "Mine" in msg

    # Stricter than the app: a model a fleet forecast runs on is refused, naming the fleet.
    from backend.services import fleet as fleet_service

    fleet = fleet_service.create_fleet(samples.db, "Pump fleet", mid, A)
    msg = _err(_call(a, "delete_model", {"model_id": mid}))
    assert "can't be deleted" in msg and "Pump fleet" in msg and f"/fleet/forecasts/{fleet.id}" in msg
    assert samples.db.models.find_one({"_id": mid}) is not None
    fleet_service.delete_fleet(samples.db, fleet.id, A)

    out = _ok(_call(a, "delete_model", {"model_id": mid}))
    assert out["deleted"] and out["affected"]["rbds"] == [{"id": rbd["id"], "name": "Uses it"}]
    assert samples.db.models.find_one({"_id": mid}) is None
    assert _ok(_call(a, "delete_dataset", {"dataset_id": did}))["deleted"]
    assert samples.db.datasets.find_one({"_id": did}) is None

    # A diagram embedded as a sub-system is reported when it goes.
    inner = _ok(_call(a, "create_rbd", {"name": "Inner", **_chain("Motor")}))["id"]
    outer = _ok(_call(a, "create_rbd", {"name": "Outer", "nodes": [
        {"id": "input", "type": "input"}, {"id": "s", "type": "subsystem", "subsystem_rbd_id": inner},
        {"id": "output", "type": "output"}], "edges": [
        {"source": "input", "target": "s"}, {"source": "s", "target": "output"}]}))["id"]
    out = _ok(_call(a, "delete_rbd", {"rbd_id": inner}))
    assert out["affected"]["rbds"] == [{"id": outer, "name": "Outer"}]
    assert samples.db.rbds.find_one({"_id": inner}) is None
    assert "not found" in _err(_call(a, "delete_rbd", {"rbd_id": inner})).lower()



# ---- Retest polish (2026-10-02) -----------------------------------------------------------

def test_conditional_at_an_age_whose_reliability_underflows_is_explained_not_nulled(samples):
    """R(1e6) for the bearings Weibull is exp(-1.2e7): positive, but it reads 0
    as a float. The conditional is still defined (via cumulative hazards), so
    it's returned, with a note, rather than null."""
    out = _ok(_call(samples.token[A], "reliability_at",
                    {"model_id": BEARINGS, "times": [1, 100], "conditional_age": 1e6}))
    first, second = out["points"]
    assert 0 < first["conditional_reliability"] < 1e-10 and second["conditional_reliability"] == 0
    assert "too small to show" in out["note"] and "isn't 0" in out["note"]


def test_failed_candidate_reasons_are_not_cut_mid_word():
    from backend.fitting import _short_reason

    assert _short_reason(["Short reason."]) == "Short reason."
    long = "Provide more distinct observations. " * 20
    assert _short_reason([long]).endswith("observations.") and len(_short_reason([long])) <= 300
    words = "word " * 100
    cut = _short_reason([words])
    assert cut.endswith("…") and cut[:-1].split()[-1] == "word"


def test_failure_finding_note_prints_the_target_as_given(env):
    out = _ok(_call(env.token[A], "failure_finding_interval", {
        "distribution_id": "exponential", "params": [{"name": "failure_rate", "value": 1e-4}],
        "target_availability": 0.9999999}))
    assert "near 99.99999%" in out["note"]
