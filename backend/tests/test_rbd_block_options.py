"""What a block and a group can model (#318, #68, #84, #326, #328).

Mixture lives on repairable (and non-repairable) blocks, imperfect repair by
Kijima's virtual age and replacement at the N-th failure, structural
importance, k-of-n standby, the multiple Greek letter (MGL) common-cause
model, "Check by simulation" on standby and load-sharing blocks, and common
cause with proof tests that take time. Each figure is checked against
RePyability (and SurPyval) called directly; the exports are run or read back.
"""

import copy
import json
import warnings

import numpy as np
import pytest
import surpyval as sp
from repyability import MGL, BetaFactor, CCFGroup, NonRepairableRBD, PerfectReliability, RepairableRBD
from repyability.rbd.standby_node import StandbyModel
from surpyval import MixtureModel

from backend.services import rbd_analysis as ra
from backend.services import rbd_block_check, rbd_edit, rbd_export, rbd_graph, rbd_import, rbd_json
from backend.tests.test_mcp import A, _call, _err, _ok, env  # noqa: F401 - env is a fixture
from backend.tests.test_public_links import client  # noqa: F401 - fixture
from backend.tests.test_rbd_export import _run

warnings.filterwarnings("ignore", category=RuntimeWarning)


def W(alpha, beta):
    return {"distribution_id": "weibull", "params": [{"name": "alpha", "value": alpha}, {"name": "beta", "value": beta}]}


def E(rate):
    return {"distribution_id": "exponential", "params": [{"name": "failure_rate", "value": rate}]}


LN = {"distribution_id": "lognormal", "params": [{"name": "mu", "value": 2.0}, {"name": "sigma", "value": 0.5}]}
MIX = {"distribution_id": "mixture", "base_distribution_id": "weibull", "params": [
    {"name": "alpha1", "value": 60.0}, {"name": "beta1", "value": 0.8}, {"name": "weight1", "value": 0.25},
    {"name": "alpha2", "value": 2000.0}, {"name": "beta2", "value": 3.5}, {"name": "weight2", "value": 0.75}]}


def _mixture():
    return MixtureModel.from_dict({"model": "MixtureModel", "dist": "Weibull", "m": 2,
                                   "params": [[60.0, 0.8], [2000.0, 3.5]], "w": [0.25, 0.75]})


def _graph(blocks, edges, repairable=False, **extra):
    nodes = [{"id": "input", "type": "input"}, *blocks, {"id": "output", "type": "output"}]
    return rbd_graph.normalize_graph({"nodes": nodes, "edges": [{"source": s, "target": t} for s, t in edges],
                                      "unit": "Hours", "repairable": repairable, **extra})


def _series(*blocks, repairable=False, **extra):
    ids = ["input", *[b["id"] for b in blocks], "output"]
    return _graph(list(blocks), list(zip(ids, ids[1:])), repairable, **extra)


def _parallel(*blocks, repairable=False, **extra):
    edges = [e for b in blocks for e in (("input", b["id"]), (b["id"], "output"))]
    return _graph(list(blocks), edges, repairable, **extra)


def _block(nid, model, **data):
    return {"id": nid, "type": "component", "label": nid.upper(), "model": model, **data}


# ---- #318: a mixture life ---------------------------------------------------------------

def test_a_mixture_is_a_repairable_blocks_life_as_repyability_takes_it():
    g = _series(_block("a", MIX, repair=LN), _block("b", W(3000, 2), repair=LN), repairable=True)
    assert g["nodes"][1]["data"]["model"]["distribution"] == "Weibull mixture (2 components)"
    assert ra.validate_graph(g)["errors"] == []
    out = ra.analyze_availability(g, simulate=False)
    ln = sp.LogNormal.from_params([2.0, 0.5])
    direct = RepairableRBD([("input", "a"), ("a", "b"), ("b", "output")],
                           {"a": {"reliability": _mixture(), "repairability": ln},
                            "b": {"reliability": sp.Weibull.from_params([3000, 2]), "repairability": ln}})
    assert out["steady_state_availability"] == pytest.approx(direct.mean_availability(), rel=1e-12)
    assert out["failure_frequency"] == pytest.approx(direct.system_failure_frequency(), rel=1e-9)


def test_a_mixture_life_in_a_reliability_diagram_and_its_mttf():
    g = _series(_block("a", MIX), _block("b", W(3000, 2)))
    out = ra.analyze(g)
    direct = NonRepairableRBD([("input", "a"), ("a", "b"), ("b", "output")],
                              {"a": _mixture(), "b": sp.Weibull.from_params([3000, 2])})
    assert out["mttf"] == pytest.approx(direct.mean(), rel=1e-3)


@pytest.mark.parametrize("change, needle", [
    (lambda p: p[:-1] + [{"name": "weight2", "value": 0.7}], "add up to 1"),
    (lambda p: p[:2] + p[3:], "mode 1 of the mixture is missing weight1"),
    (lambda p: [{**x, "value": -1.0} if x["name"] == "beta1" else x for x in p], "mode 1"),
    (lambda p: p[:3], "at least two modes"),
])
def test_a_mixture_is_checked_in_plain_words(change, needle):
    bad = {**MIX, "params": change(copy.deepcopy(MIX["params"]))}
    with pytest.raises(rbd_graph.GraphError, match=needle):
        rbd_graph.normalize_model(bad, "node 'a'")


def test_a_saved_mixture_fit_is_a_block_life_over_mcp(env):
    rng_times = [float(x) for x in np.concatenate([sp.Weibull.from_params([60, 0.8]).qf(np.linspace(0.05, 0.95, 12)),
                                                    sp.Weibull.from_params([2000, 3.5]).qf(np.linspace(0.05, 0.95, 36))])]
    saved = _ok(_call(env.token[A], "fit_and_save_model", {
        "data": rng_times, "distribution": "mixture", "unit": "hours", "name": "Two modes"}))
    graph = {"nodes": [{"id": "input", "type": "input"},
                       {"id": "p", "type": "component", "label": "Pump", "model": {"saved_model_id": saved["model_id"]},
                        "repair": LN},
                       {"id": "output", "type": "output"}],
             "edges": [{"source": "input", "target": "p"}, {"source": "p", "target": "output"}]}
    rbd = _ok(_call(env.token[A], "create_rbd", {"name": "Mixed", "repairable": True, **graph}))
    stored = next(n for n in env.db.rbds.find_one({"_id": rbd["id"]})["graph"]["nodes"] if n["id"] == "p")
    model = stored["data"]["model"]
    assert model["distribution_id"] == "mixture" and model["base_distribution_id"] == "weibull"
    got = _ok(_call(env.token[A], "get_rbd", {"rbd_id": rbd["id"]}))
    compact = next(n for n in got["graph"]["nodes"] if n["id"] == "p")["model"]
    assert compact["saved_model_id"] == saved["model_id"] and compact["base_distribution_id"] == "weibull"
    # get_rbd's compact model round-trips through edit_rbd.
    _ok(_call(env.token[A], "edit_rbd", {"rbd_id": rbd["id"], "ops": [
        {"op": "update_node", "id": "p", "model": compact}]}))
    # An inline mixture, too.
    _ok(_call(env.token[A], "edit_rbd", {"rbd_id": rbd["id"], "ops": [
        {"op": "update_node", "id": "p", "model": {k: MIX[k] for k in ("distribution_id", "base_distribution_id",
                                                                        "params")}}]}))
    out = _ok(_call(env.token[A], "analyze_rbd", {"rbd_id": rbd["id"], "simulate": False}))
    direct = RepairableRBD([("input", "p"), ("p", "output")],
                           {"p": {"reliability": _mixture(), "repairability": sp.LogNormal.from_params([2.0, 0.5])}})
    assert out["steady_state_availability"] == pytest.approx(direct.mean_availability(), rel=1e-9)


def test_mixture_exports(tmp_path):
    g = _series(_block("a", MIX, repair=LN, costs={"repair": 100}), repairable=True)
    doc = rbd_json.to_document(g, "Mixed")
    assert doc["components"][0]["component"]["reliability"]["model"]["model"] == "MixtureModel"
    # A file edited in code (no Reliafy part) comes back with the mixture life.
    core = {k: v for k, v in doc.items() if k != "reliafy"}
    [d] = rbd_import.import_file(json.dumps(core).encode(), "m.json")
    a = next(n for n in d.graph["nodes"] if n["type"] == "component")
    assert a["data"]["model"]["distribution_id"] == "mixture"
    assert ra.analyze_availability(rbd_graph.normalize_graph(d.graph), simulate=False)["steady_state_availability"] \
        == pytest.approx(ra.analyze_availability(g, simulate=False)["steady_state_availability"], rel=1e-12)
    res, _ = _run(rbd_export.to_python(g, "Mixed"), tmp_path, n_sims="40")
    assert res["steady_state_availability"] == pytest.approx(
        ra.analyze_availability(g, simulate=False)["steady_state_availability"], rel=1e-12)


# ---- #68: imperfect repair, replacement at the N-th failure, structural importance -------

KIJIMA = {"model": "kijima1", "q": 0.4, "replace_after": 3}


def test_imperfect_repair_reaches_the_component_spec_and_is_simulated():
    g = _series(_block("a", W(1000, 2.5), repair=LN, repair_quality=KIJIMA, costs={"repair": 100, "replace": 900}),
                _block("b", W(3000, 2), repair=LN), repairable=True)
    rbd, *_ = ra._build_repairable_rbd(g)
    spec = rbd._init_args["components"]["a"]
    assert spec["repair"] == {"model": "kijima1", "q": 0.4} and spec["replace_after"] == 3
    out = ra.analyze_availability(g, n_simulations=40)
    # No exact long run (a repair doesn't renew it): the engine says why, and the simulation stands.
    assert out["steady_state_availability"] is None and out["figures_basis"]["failure_frequency"] == "simulation"
    assert "repaired imperfectly" in out["long_run_method"]["reason"] and "“A”" in out["long_run_method"]["reason"]
    assert out["costs"]["cost_rate_basis"] == "simulation"
    # Structural importance still stands: it needs no exact long run.
    assert out["importance"]["a"]["structural"] == pytest.approx(rbd.structural_importance()["a"])


@pytest.mark.parametrize("quality, needle", [
    ({"model": "kijima1", "q": 1.5}, "from 0"),
    ({"model": "kijima2", "q": 0, "replace_after": 2}, "needs q above 0"),
    ({"model": "perfect", "replace_after": 2}, "needs imperfect repair"),
    ({"model": "kijima1", "q": 0.5, "replace_after": 1.5}, "whole number"),
])
def test_repair_quality_is_checked_in_plain_words(quality, needle):
    g = _series(_block("a", W(1000, 2.5), repair=LN, repair_quality=quality), repairable=True)
    errors = ra.validate_graph(g)["errors"]
    assert any(needle in e for e in errors), errors


def test_imperfect_repair_is_refused_where_repyability_refuses_it():
    standby = {"id": "s", "type": "standby", "label": "S", "model": W(1000, 2), "repair": LN, "spares": 1,
               "repair_quality": {"model": "kijima1", "q": 0.5}}
    errors = ra.validate_graph(_series(standby, repairable=True))["errors"]
    assert any("takes no imperfect repair" in e for e in errors)
    cond = _block("c", W(1000, 2.5), repair=LN, repair_quality={"model": "kijima1", "q": 0.5},
                  preventive={"policy": "condition", "interval": 100, "threshold": 0.05})
    assert any("replaced on condition" in e for e in ra.validate_graph(_series(cond, repairable=True))["errors"])


def test_repair_quality_over_mcp_and_in_the_exports(env, tmp_path):
    graph = {"nodes": [{"id": "input", "type": "input"},
                       {"id": "a", "type": "component", "label": "Pump", "model": W(1000, 2.5), "repair": LN,
                        "repair_quality": KIJIMA},
                       {"id": "output", "type": "output"}],
             "edges": [{"source": "input", "target": "a"}, {"source": "a", "target": "output"}]}
    rbd = _ok(_call(env.token[A], "create_rbd", {"name": "Worn", "repairable": True, **graph}))
    node = lambda: next(n for n in env.db.rbds.find_one({"_id": rbd["id"]})["graph"]["nodes"] if n["id"] == "a")
    assert node()["data"]["repair_quality"] == KIJIMA
    _ok(_call(env.token[A], "edit_rbd", {"rbd_id": rbd["id"], "ops": [
        {"op": "update_node", "id": "a", "repair_quality": {"model": "kijima2", "q": 0.7}}]}))
    assert node()["data"]["repair_quality"] == {"model": "kijima2", "q": 0.7}
    _ok(_call(env.token[A], "edit_rbd", {"rbd_id": rbd["id"], "ops": [
        {"op": "update_node", "id": "a", "clear": ["repair_quality"]}]}))
    assert "repair_quality" not in node()["data"]
    msg = _err(_call(env.token[A], "edit_rbd", {"rbd_id": rbd["id"], "ops": [
        {"op": "update_node", "id": "a", "repair_quality": {"model": "kijima1", "q": 2}}]}))
    assert "q" in msg

    g = _series(_block("a", W(1000, 2.5), repair=LN, repair_quality=KIJIMA, costs={"repair": 100}), repairable=True)
    core = {k: v for k, v in rbd_json.to_document(g, "Worn").items() if k != "reliafy"}
    assert core["components"][0]["component"]["replace_after"] == 3
    [d] = rbd_import.import_file(json.dumps(core).encode(), "w.json")
    assert next(n for n in d.graph["nodes"] if n["type"] == "component")["data"]["repair_quality"] == KIJIMA
    code = rbd_export.to_python(g, "Worn")
    assert '"replace_after": 3' in code
    res, proc = _run(code, tmp_path, n_sims="20")
    assert res["n_simulations"] == 20 and "repaired imperfectly" in proc.stdout


def test_structural_importance_matches_repyability():
    g = _graph([_block("a", W(1000, 2)), _block("b", W(800, 1.5)), _block("c", W(2000, 3))],
               [("input", "a"), ("input", "b"), ("a", "c"), ("b", "c"), ("c", "output")])
    out = ra.analyze(g)
    rbd, *_ = ra._build_rbd(g, None, set(), None, None)
    assert out["importance"]["structural"] == pytest.approx(rbd.structural_importance())
    assert out["importance"]["structural"]["c"] == pytest.approx(0.75)
    rg = _graph([_block(n, E(1e-3), repair=E(0.1)) for n in "abc"],
                [("input", "a"), ("input", "b"), ("a", "c"), ("b", "c"), ("c", "output")], repairable=True)
    rows = ra.analyze_availability(rg, simulate=False)["importance"]
    assert {k: r["structural"] for k, r in rows.items()} == pytest.approx({"a": 0.25, "b": 0.25, "c": 0.75})


# ---- #84: k-of-n standby -------------------------------------------------------------------

def _standby(**data):
    return {"id": "s", "type": "standby", "label": "Train", "model": W(100, 2), "spares": 1, "k": 2, **data}


@pytest.mark.parametrize("dormancy", [0.0, 1.0])
def test_k_of_n_standby_is_repyabilitys_standby_model(dormancy):
    g = _series(_standby(dormancy=dormancy, cold=dormancy == 0.0))
    out = ra.analyze(g, at_times=[50.0, 120.0])
    w = sp.Weibull.from_params([100, 2])
    direct = StandbyModel([w, w, w], k=2, dormancy_factor=dormancy)
    assert out["at"]["sf"] == pytest.approx(list(direct.sf([50.0, 120.0])), rel=1e-6)
    assert out["mttf"] == pytest.approx(direct.mean(), rel=1e-3)


def test_cold_k_of_n_standby_with_imperfect_switching():
    g = _series(_standby(dormancy=0, cold=True, startProb=0.9))
    out = ra.analyze(g, at_times=[80.0])
    w = sp.Weibull.from_params([100, 2])
    assert out["at"]["sf"][0] == pytest.approx(
        float(StandbyModel([w, w, w], k=2, switching_probability=0.9).sf(80.0)), rel=1e-6)


@pytest.mark.parametrize("data, needle", [
    ({"dormancy": 0.5}, "warm standby with 2 units running"),
    ({"dormancy": 0, "cold": True, "k": 3, "spares": 1, "standbyModel": W(150, 2)}, "spare model of its own"),
])
def test_k_of_n_standby_limits_are_said_plainly(data, needle):
    errors = ra.validate_graph(_series(_standby(**data)))["errors"]
    assert any(needle in e for e in errors), errors
    # A repairable diagram's standby group isn't such an arrangement: no error there.
    rep = _series(_standby(**{**data, "standbyModel": None}, repair=LN), repairable=True)
    assert not any(needle in e for e in ra.validate_graph(rep)["errors"])


def test_switching_on_warm_spares_is_warned_of():
    warnings_ = ra.validate_graph(_series(_standby(k=1, dormancy=0.5, startProb=0.9)))["warnings"]
    assert any("start-success probability applies to cold standby only" in w for w in warnings_)


def test_repairable_k_of_n_standby_group(tmp_path):
    g = _series(_standby(model=E(0.01), repair=E(0.1), dormancy=0, cold=True), repairable=True)
    rbd, *_ = ra._build_repairable_rbd(g)
    assert rbd._init_args["components"]["s"]["standby"]["units"] == 3
    assert rbd._init_args["components"]["s"]["standby"]["k"] == 2
    direct = RepairableRBD([("input", "s"), ("s", "output")], {"s": {
        "reliability": sp.Exponential.from_params([0.01]), "repairability": sp.Exponential.from_params([0.1]),
        "standby": {"units": 3, "k": 2, "dormancy_factor": 0.0, "switching_probability": 1.0}}})
    out = ra.analyze_availability(g, simulate=False)
    assert out["steady_state_availability"] == pytest.approx(direct.mean_availability(), rel=1e-12)
    # Both exports keep k; the Reliafy-less file comes back with it.
    core = {k: v for k, v in rbd_json.to_document(g, "Train").items() if k != "reliafy"}
    [d] = rbd_import.import_file(json.dumps(core).encode(), "t.json")
    s = next(n for n in d.graph["nodes"] if n["type"] == "standby")
    assert s["data"]["k"] == 2 and s["data"]["spares"] == 1
    res, _ = _run(rbd_export.to_python(g, "Train"), tmp_path, n_sims="20")
    assert res["steady_state_availability"] == pytest.approx(out["steady_state_availability"], rel=1e-12)


def test_nonrepairable_k_of_n_standby_exports(tmp_path):
    g = _series(_standby(dormancy=0, cold=True))
    core = {k: v for k, v in rbd_json.to_document(g, "Train").items() if k != "reliafy"}
    assert core["reliabilities"][0]["model"]["k"] == 2
    [d] = rbd_import.import_file(json.dumps(core).encode(), "t.json")
    assert next(n for n in d.graph["nodes"] if n["type"] == "standby")["data"]["k"] == 2
    res, _ = _run(rbd_export.to_python(g, "Train"), tmp_path)
    assert res["mttf"] == pytest.approx(ra.analyze(g)["mttf"], rel=1e-3)


def test_standby_k_over_mcp(env):
    graph = {"nodes": [{"id": "input", "type": "input"},
                       {"id": "s", "type": "standby", "label": "Train", "model": W(100, 2), "spares": 1, "k": 2},
                       {"id": "output", "type": "output"}],
             "edges": [{"source": "input", "target": "s"}, {"source": "s", "target": "output"}]}
    rbd = _ok(_call(env.token[A], "create_rbd", {"name": "Train", **graph}))
    _ok(_call(env.token[A], "edit_rbd", {"rbd_id": rbd["id"], "ops": [{"op": "update_node", "id": "s", "k": 1}]}))
    s = next(n for n in env.db.rbds.find_one({"_id": rbd["id"]})["graph"]["nodes"] if n["id"] == "s")
    assert s["data"]["k"] == 1


# ---- #84: the multiple Greek letter model ---------------------------------------------------

def _trio(repairable=False, mgl=(0.3,), **extra):
    blocks = [_block(n, E(1e-3), **({"repair": E(0.1)} if repairable else {})) for n in ("a", "b", "c")]
    vote = {"id": "v", "type": "knode", "label": "2oo3", "n": 2, "k": 3}
    edges = [e for n in "abc" for e in (("input", n), (n, "v"))] + [("v", "output")]
    group = {"id": "ccf-1", "members": ["a", "b", "c"], "beta": 0.1, **({"mgl": list(mgl)} if mgl else {})}
    return _graph([*blocks, vote], edges, repairable, ccf_groups=[group], **extra)


def _trio_direct(model, repairable=False):
    e = sp.Exponential.from_params([1e-3])
    edges = [e_ for n in "abc" for e_ in (("input", n), (n, "v"))] + [("v", "output")]
    groups = [CCFGroup(["a", "b", "c"], model)]
    if repairable:
        r = sp.Exponential.from_params([0.1])
        comps = {**{n: {"reliability": e, "repairability": r} for n in "abc"}, "v": PerfectReliability}
        return RepairableRBD(edges, comps, k={"v": 2}, ccf_groups=groups)
    return NonRepairableRBD(edges, {"a": e, "b": e, "c": e, "v": PerfectReliability}, k={"v": 2}, ccf_groups=groups)


def test_an_mgl_group_in_a_reliability_diagram():
    out = ra.analyze(_trio(), at_times=[300.0])
    direct = _trio_direct(MGL(0.1, 0.3, basis="rate"))
    assert out["at"]["sf"][0] == pytest.approx(float(direct.sf(300.0)), rel=1e-9)
    beta_only = ra.analyze(_trio(mgl=None), at_times=[300.0])["at"]["sf"][0]
    assert beta_only == pytest.approx(float(_trio_direct(BetaFactor(0.1, basis="rate")).sf(300.0)), rel=1e-9)
    assert beta_only != pytest.approx(out["at"]["sf"][0], rel=1e-6)


def test_an_mgl_group_in_a_repairable_diagram():
    out = ra.analyze_availability(_trio(repairable=True), simulate=False)
    assert out["common_cause"]["included"] is True
    direct = _trio_direct(MGL(0.1, 0.3, basis="rate"), repairable=True)
    assert out["steady_state_availability"] == pytest.approx(direct.mean_availability(), rel=1e-12)


def test_mgl_letters_are_checked():
    errors = ra.validate_graph(_trio(mgl=(0.3, 0.2)))["errors"]
    assert any("needs 2 letters" in e for e in errors), errors
    assert any("must be a probability" in e for e in ra.validate_graph(_trio(mgl=(1.5,)))["errors"])


def test_mgl_over_edit_rbd_and_its_member_removal():
    g = _trio(mgl=None)
    g.pop("ccf_groups")
    out = rbd_edit.apply_ops(g, [{"op": "add_ccf", "members": ["a", "b", "c"], "beta": 0.1, "mgl": [0.3]}], "T")
    assert out.graph["ccf_groups"][0]["mgl"] == [0.3]
    with pytest.raises(rbd_edit.EditError, match="takes 1 letter"):
        rbd_edit.apply_ops(g, [{"op": "add_ccf", "members": ["a", "b", "c"], "beta": 0.1, "mgl": [0.3, 0.2]}], "T")
    gone = rbd_edit.apply_ops(out.graph, [{"op": "remove_node", "id": "c", "reconnect": "none"}], "T")
    assert "mgl" not in gone.graph["ccf_groups"][0] and gone.graph["ccf_groups"][0]["members"] == ["a", "b"]


def test_mgl_exports_and_imports(tmp_path):
    for repairable in (False, True):
        g = _trio(repairable=repairable)
        core = {k: v for k, v in rbd_json.to_document(g, "Trio").items() if k != "reliafy"}
        assert core["ccf_groups"][0]["model"] == {"kind": "mgl", "letters": [0.1, 0.3], "basis": "rate"}
        [d] = rbd_import.import_file(json.dumps(core).encode(), "t.json")
        assert d.graph["ccf_groups"][0]["mgl"] == [0.3]
        code = rbd_export.to_python(g, "Trio")
        assert "MGL(0.1, 0.3, basis='rate')" in code
        res, _ = _run(code, tmp_path, name=f"trio{int(repairable)}.py", n_sims="20")
        if repairable:
            assert res["steady_state_availability"] == pytest.approx(
                ra.analyze_availability(g, simulate=False)["steady_state_availability"], rel=1e-12)
        else:
            assert res["mttf"] == pytest.approx(ra.analyze(g)["mttf"], rel=1e-3)


def test_the_fault_tree_says_it_draws_no_mgl_group():
    from backend.services.rbd_fault_tree import fault_tree

    with pytest.raises(ra.AnalysisError, match="multiple Greek letter"):
        fault_tree(_trio(), t=100.0)


def test_an_mgl_member_isnt_given_copies():
    from backend.services import rbd_design

    with pytest.raises(rbd_design.DesignError, match="multiple Greek letter"):
        rbd_design._parse_blocks(_trio(), [{"id": "a", "max_copies": 2}])


# ---- #326: check an exact mean by simulation ---------------------------------------------

@pytest.mark.parametrize("data", [{"k": 2, "dormancy": 0, "cold": True}, {"k": 1, "dormancy": 1}])
def test_check_by_simulation_matches_repyability(data):
    node = {"id": "s", "type": "standby", "data": {"label": "Train", "model": W(100, 2), "spares": 1, **data}}
    out = rbd_block_check.check_mean(node, unit="Hours", samples=4000)
    w = sp.Weibull.from_params([100, 2])
    model = StandbyModel([w] * (data["k"] + 1), k=data["k"], dormancy_factor=data["dormancy"])
    assert out["exact_mean"] == pytest.approx(model.mean(method="exact"), rel=1e-12)
    ci = NonRepairableRBD([("in", "x"), ("x", "out")], {"x": model}).mean_time_to_failure_interval(
        mc_samples=4000, seed=1)
    assert out["simulated"]["estimate"] == pytest.approx(ci.estimate, rel=1e-12)
    assert (out["simulated"]["lower"], out["simulated"]["upper"]) == pytest.approx((ci.lower, ci.upper), rel=1e-12)
    assert out["within"] is True and "inside the interval" in out["summary"]


def test_check_by_simulation_over_http(client):
    client.act_as(A)
    node = {"id": "s", "type": "standby", "data": {"label": "Train", "model": W(100, 2), "spares": 2, "dormancy": 0}}
    r = client.post("/api/rbds/check-block-mean", json={"node": node, "unit": "Hours"})
    assert r.status_code == 200 and r.json()["simulated"]["n_samples"] == rbd_block_check.CHECK_SAMPLES
    r = client.post("/api/rbds/check-block-mean", json={"node": {"type": "component", "data": {}}})
    assert r.status_code == 422 and "standby and load-sharing" in r.json()["detail"]


# ---- #328: common cause with proof tests that take time ------------------------------------

def _timed_pair():
    def block(nid, offset):
        return _block(nid, E(1e-5), repair=E(0.125), costs={"repair": 100},
                      inspection={"interval": 8760, "duration": 4, "offset": offset, "cost": 50})
    return _parallel(block("a", 0), block("b", 4380), repairable=True, safety_function=True,
                     ccf_groups=[{"id": "ccf-1", "members": ["a", "b"], "beta": 0.1}])


def _timed_direct():
    e, rep, dur = sp.Exponential.from_params([1e-5]), sp.Exponential.from_params([0.125]), sp.ExactEventTime.from_params(4.0)

    def spec(off):
        return {"reliability": e, "repairability": rep, "repair_cost": 100.0,
                "inspection": {"interval": 8760.0, "duration": dur, "offset": off, "cost": 50.0}}
    return RepairableRBD([("input", "a"), ("a", "output"), ("input", "b"), ("b", "output")],
                         {"a": spec(0.0), "b": spec(4380.0)}, ccf_groups=[CCFGroup(["a", "b"], BetaFactor(0.1))])


def test_timed_tests_keep_the_group_in_every_figure_but_the_frequency(tmp_path):
    g = _timed_pair()
    out = ra.analyze_availability(g, n_simulations=40)
    direct = _timed_direct()
    cc = out["common_cause"]
    assert cc["included"] is True and "frequency_left_out" in cc
    # Availability, PFDavg and the cost rate take the group, exactly as RePyability does.
    assert out["steady_state_availability"] == pytest.approx(direct.mean_availability(), rel=1e-12)
    assert out["safety"]["pfd_avg"] == pytest.approx(direct.mean_unavailability(), rel=1e-12)
    assert out["costs"]["cost_rate"] == pytest.approx(direct.expected_cost_rate(), rel=1e-9)
    # The exact failure frequency is the one RePyability refuses: only the simulated estimate stands.
    with pytest.raises(NotImplementedError):
        direct.system_failure_frequency()
    assert out["figures_basis"]["failure_frequency"] == "simulation"
    assert "importance_left_out" in cc  # the measures the engine gives no value for here, said
    exact = ra.exact_availability(g)
    assert exact["common_cause_included"] is True and exact["expected_failures"] > 0
    # The script keeps the group and its availability, and leaves the frequency out.
    res, proc = _run(rbd_export.to_python(g, "SIF"), tmp_path, n_sims="20")
    assert res["steady_state_availability"] == pytest.approx(out["steady_state_availability"], rel=1e-12)
    assert "Failure frequency: nan" in proc.stdout
