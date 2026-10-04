"""Common-cause groups split the failure rate over a lifetime (#210), and
analyze_rbd's common-cause curve is opt-in and labelled (#214).

A beta-factor group on RePyability's default *probability* basis splits each
member's failure probability Q — a rare-event model, right for a short mission
but not a lifetime: as Q → 1 it made adding common cause *raise* the MTTF, and
a redundant group never fully failed. Non-repairable analysis now splits the
failure *rate* (``BetaFactor(beta, basis="rate")``) unless a group says
otherwise.
"""

import copy
import warnings

import numpy as np
import pytest
import surpyval

from backend.services import rbd_analysis as ra
from backend.services import rbd_edit, rbd_fault_tree, samples
from backend.services.reliability_agent import _build_rbd_graph
from backend.tests.test_mcp import A, _call, _err, _ok, env  # noqa: F401 - env is a fixture


def _w(alpha, beta):
    return {"source": "params", "distribution": "Weibull", "distribution_id": "weibull",
            "params": [{"name": "alpha", "value": alpha}, {"name": "beta", "value": beta}]}


def _exp(rate):
    return {"source": "params", "distribution": "Exponential", "distribution_id": "exponential",
            "params": [{"name": "failure_rate", "value": rate}]}


def _node(nid, label, model=None, ntype="component"):
    data = {"label": label}
    if model is not None:
        data["model"] = model
    return {"id": nid, "type": ntype, "position": {"x": 0, "y": 0}, "data": data}


def _repro(beta=0.1, basis=None):
    """The issue's repro: the pump-station sample with a third pump in
    parallel and a strainer after a Weibull(3000, 1.8) controller, pumps A/B/C
    in a common-cause group."""
    g = copy.deepcopy(samples._pump_station_graph())
    for n in g["nodes"]:
        if n["id"] == "controller":
            n["data"]["model"] = _w(3000.0, 1.8)
    g["nodes"][-1:-1] = [_node("pumpC", "Pump C", _w(900.0, 1.4)), _node("strainer", "Strainer", _exp(2e-4))]
    g["edges"] = [{"source": s, "target": t} for s, t in (
        ("input", "controller"), ("controller", "strainer"), ("strainer", "pumpA"), ("strainer", "pumpB"),
        ("strainer", "pumpC"), ("pumpA", "output"), ("pumpB", "output"), ("pumpC", "output"))]
    if beta:
        group = {"id": "g", "members": ["pumpA", "pumpB", "pumpC"], "beta": beta}
        if basis:
            group["basis"] = basis
        g["ccf_groups"] = [group]
    return g


def _parallel(n=3, beta=0.1, basis=None):
    """``n`` identical pumps in parallel (1-of-n), one common-cause group."""
    nodes = [_node("input", "Input", ntype="input"), _node("output", "Output", ntype="output")]
    ids = [f"p{i}" for i in range(n)]
    nodes += [_node(i, f"Pump {i}", _w(900.0, 1.4)) for i in ids]
    edges = [{"source": "input", "target": i} for i in ids] + [{"source": i, "target": "output"} for i in ids]
    group = {"id": "g", "members": ids, "beta": beta}
    if basis:
        group["basis"] = basis
    return {"unit": "Hours", "nodes": nodes, "edges": edges, "ccf_groups": [group]}


def _quiet(graph, **kw):
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        return ra.analyze(graph, **kw)


# ---- #210: the issue's numbers ---------------------------------------------------------

def test_issue_repro_rate_basis_numbers():
    none = _quiet(_repro(beta=0), at_times=[1000.0])
    rate = _quiet(_repro(), at_times=[1000.0])
    assert none["at"]["sf"][0] == pytest.approx(0.4826, abs=5e-5)
    assert none["mttf"] == pytest.approx(1033, abs=1)
    assert rate["at"]["sf"][0] == pytest.approx(0.4624, abs=5e-5)
    assert rate["mttf"] == pytest.approx(1005, abs=1)
    # The group is on the rate basis, and nothing warns about it.
    assert rate["ccf"]["groups"][0]["basis"] == "rate"
    assert "warnings" not in rate
    # Adding common cause lowers the reliability and the MTTF (it raised them).
    assert rate["at"]["sf"][0] < none["at"]["sf"][0] and rate["mttf"] < none["mttf"]
    assert rate["blife"]["b10"] < none["blife"]["b10"] and rate["blife"]["b50"] < none["blife"]["b50"]


@pytest.mark.parametrize("beta", [0.01, 0.1, 0.3, 0.6, 0.9])
@pytest.mark.parametrize("make", [_repro, _parallel])
def test_adding_common_cause_never_raises_the_mttf(make, beta):
    graph = make(beta=beta)
    without = {k: v for k, v in graph.items() if k != "ccf_groups"}
    with_ccf, base = _quiet(graph), _quiet(without)
    assert with_ccf["mttf"] <= base["mttf"] * (1 + 1e-9)
    # Nor the reliability, anywhere on the curve.
    sf, base_sf = np.array(with_ccf["system"]["sf"]), np.array(with_ccf["ccf"]["baseline_sf"])
    assert np.all(sf <= base_sf + 1e-12)


def test_mttf_is_repyabilitys_exact_mean():
    rbd, *_ = ra._build_rbd(_repro())
    assert rbd.ccf_groups[0].model.basis == "rate"
    assert _quiet(_repro())["mttf"] == pytest.approx(float(rbd.mean()), rel=1e-12)


def test_a_one_of_three_group_fails_completely():
    """Over a lifetime the group's reliability goes to 0 — on the probability
    basis it stalled at (1 − β)(1 − (1 − β)³) ≈ 0.244."""
    graph = _parallel(3, beta=0.1)
    floor = 0.9 * (1 - 0.9 ** 3)
    res = _quiet(graph, at_times=[5000.0, 20000.0])
    assert res["at"]["sf"][1] < 1e-6
    assert res["at"]["sf"][0] < floor
    old = _quiet(_parallel(3, beta=0.1, basis="probability"), at_times=[20000.0])
    assert old["at"]["sf"][0] == pytest.approx(floor, rel=1e-6)


def test_samples_with_common_cause_use_the_rate_basis():
    graph = samples._instrument_air_design_graph()
    res = _quiet(graph, at_times=[5000.0, 20000.0])
    prob = copy.deepcopy(graph)
    prob["ccf_groups"][0]["basis"] = "probability"
    old = _quiet(prob, at_times=[5000.0, 20000.0])
    # The 2oo3 group no longer plateaus: lower far-tail reliability, and an MTTF
    # (the probability basis has none).
    assert res["at"]["sf"][1] < old["at"]["sf"][1]
    assert res["mttf"] == pytest.approx(8736.5, rel=1e-3)
    assert old["mttf"] is None


# ---- #210: the probability basis, when a group asks for it ---------------------------

def test_probability_basis_warns_and_gives_no_mttf():
    res = ra.analyze(_repro(basis="probability"))
    assert res["mttf"] is None
    assert res["ccf"]["groups"][0]["basis"] == "probability"
    text = " ".join(res["warnings"])
    # RePyability's warning, relayed in Reliafy's words (labels, no Python).
    assert "“Pump A”, “Pump B”, “Pump C”" in text and "probability basis" in text
    assert "basis to rate" in text and "BetaFactor(" not in text
    assert any(w.startswith("The MTTF isn't given") for w in res["warnings"])


def test_relaying_doesnt_swallow_other_warnings():
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        res = ra.analyze(_repro(basis="probability"))
    assert res["warnings"]
    # The common-cause warning went into the result, not out as a Python warning.
    assert not any("Common-cause group" in str(w.message) for w in caught)


def test_validation_checks_the_basis():
    v = ra.validate_graph(_repro(basis="probability"))
    assert v["valid"] and any("probability basis" in w for w in v["warnings"])
    assert not any("probability basis" in w for w in ra.validate_graph(_repro())["warnings"])
    v = ra.validate_graph(_repro(basis="hazard"))
    assert not v["valid"] and any("basis must be 'rate' or 'probability'" in e for e in v["errors"])
    with pytest.raises(ra.AnalysisError, match="basis"):
        ra.analyze(_repro(basis="hazard"))


def test_repairable_groups_keep_the_probability_default():
    """A safety function's PFDavg comes from RePyability's Markov chain, which
    splits the rate whatever the basis: the default stays as it was."""
    assert ra.ccf_basis({"beta": 0.1}, repairable=True) == "probability"
    assert ra.ccf_basis({"beta": 0.1}) == "rate"
    assert ra.ccf_basis({"beta": 0.1, "basis": "rate"}, repairable=True) == "rate"


def test_fault_tree_top_event_matches_the_calculator():
    graph = _repro()
    t = 1000.0
    tree = rbd_fault_tree.fault_tree(graph, t=t)
    r = _quiet(graph, at_times=[t])["at"]["sf"][0]
    assert tree["top_event_probability"] == pytest.approx(1 - r, rel=1e-9)
    ccf = [e for e in tree["events"] if e.get("node_type") == "ccf"]
    assert ccf and ccf[0]["basis"] == "rate"


# ---- #210: where a group's basis is set -------------------------------------------------

def test_add_ccf_takes_a_basis():
    graph = _repro(beta=0)
    out = rbd_edit.apply_ops(graph, [{"op": "add_ccf", "members": ["pumpA", "pumpB"], "beta": 0.1,
                                      "basis": "probability"}], "R")
    assert out.graph["ccf_groups"][0]["basis"] == "probability"
    assert "probability basis" in out.applied[0]
    out = rbd_edit.apply_ops(graph, [{"op": "add_ccf", "members": ["pumpA", "pumpB"], "beta": 0.1}], "R")
    assert "basis" not in out.graph["ccf_groups"][0]
    with pytest.raises(rbd_edit.EditError, match="basis"):
        rbd_edit.apply_ops(graph, [{"op": "add_ccf", "members": ["pumpA", "pumpB"], "beta": 0.1,
                                    "basis": "hazard"}], "R")


def test_stages_take_a_common_cause_basis():
    stage = {"label": "Pumps", "common_cause_beta": 0.1, "common_cause_basis": "probability", "components": [
        {"label": f"P{i}", "distribution": "weibull",
         "params": [{"name": "alpha", "value": 900}, {"name": "beta", "value": 1.4}]} for i in range(2)]}
    graph = _build_rbd_graph(None, "u", [stage])
    assert graph["ccf_groups"][0]["basis"] == "probability"
    del stage["common_cause_basis"]
    assert "basis" not in _build_rbd_graph(None, "u", [stage])["ccf_groups"][0]


def test_mcp_add_ccf_basis_and_warnings(env):
    nodes = [{"id": "input", "type": "input"}, {"id": "output", "type": "output"}] + [
        {"id": f"p{i}", "type": "component", "label": f"Pump {i}", "model": {
            "distribution_id": "weibull", "params": [{"name": "alpha", "value": 900}, {"name": "beta", "value": 1.4}]}}
        for i in range(2)]
    edges = [{"source": "input", "target": "p0"}, {"source": "input", "target": "p1"},
             {"source": "p0", "target": "output"}, {"source": "p1", "target": "output"}]
    rid = _ok(_call(env.token[A], "create_rbd", {"name": "Pumps", "nodes": nodes, "edges": edges}))["id"]
    out = _ok(_call(env.token[A], "edit_rbd", {"rbd_id": rid, "ops": [
        {"op": "add_ccf", "members": ["p0", "p1"], "beta": 0.1, "basis": "probability"}]}))
    assert out["applied"] == ["added common-cause group ccf-1 (p0, p1; beta 0.1; probability basis)"]
    res = _ok(_call(env.token[A], "analyze_rbd", {"rbd_id": rid}))
    assert res["mttf"] is None
    assert any("probability basis" in w for w in res["warnings"])
    msg = _err(_call(env.token[A], "edit_rbd", {"rbd_id": rid, "ops": [
        {"op": "add_ccf", "members": ["p0", "p1"], "beta": 0.1, "basis": "hazard"}]}))
    assert "basis" in msg


# ---- #214: the curve without common cause is opt-in and labelled ---------------------

def test_analyze_rbd_ccf_curve_is_opt_in(env):
    out = _ok(_call(env.token[A], "create_rbd", {"name": "Pumps", "stages": [
        {"label": "Pumps", "common_cause_beta": 0.1, "components": [
            {"label": f"Pump {i}", "distribution": "weibull",
             "params": [{"name": "alpha", "value": 900}, {"name": "beta", "value": 1.4}]} for i in range(3)]}]}))
    rid = out["id"]
    res = _ok(_call(env.token[A], "analyze_rbd", {"rbd_id": rid}))
    ccf = res["ccf"]
    assert "baseline_sf" not in ccf and "curve_without" not in ccf
    assert "include_curves" in ccf["curve_omitted"]
    assert ccf["reliability_with"] < ccf["reliability_without"]
    full = _ok(_call(env.token[A], "analyze_rbd", {"rbd_id": rid, "include_curves": True}))["ccf"]
    assert "baseline_sf" not in full and "curve_omitted" not in full
    curve = full["curve_without"]
    assert [p["t"] for p in curve] == [p["t"] for p in res["curve"]]
    for with_, without in zip(res["curve"], curve):
        assert set(without) == {"t", "reliability"}
        assert with_["reliability"] <= without["reliability"] + 1e-12


def test_rest_result_keeps_the_app_payload():
    """The app's result still carries baseline_sf (the calculator's), now with
    each group's basis."""
    res = _quiet(_repro())
    assert len(res["ccf"]["baseline_sf"]) == len(res["time"])


def test_surpyval_reference_for_the_rate_split():
    """The rate split by hand: the shared cause has not struck with R ** beta,
    each pump survives its own causes with R ** (1 - beta)."""
    t = np.array([300.0, 900.0, 2000.0])
    r = surpyval.Weibull.from_params([900.0, 1.4]).sf(t)
    beta = 0.1
    want = r ** beta * (1 - (1 - r ** (1 - beta)) ** 3)
    got = _quiet(_parallel(3, beta=beta), at_times=t.tolist())["at"]["sf"]
    np.testing.assert_allclose(got, want, rtol=1e-9)
