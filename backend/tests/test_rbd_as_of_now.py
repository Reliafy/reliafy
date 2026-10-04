"""Non-repairable RBDs as of now and their design life (#173, RePyability 0.11).

As of now: blocks that have failed, or run some time, condition the system's
reliability from now (``sf_given_state``), its remaining life
(``remaining_life``) and the importances (``importances_given_state``). The
design life is the time the system reliability falls to a target
(``time_to_reliability``), with an interval from the fitted blocks'
parameter uncertainty when a confidence band is asked for.
"""

import json

import matplotlib

matplotlib.use("Agg")

import numpy as np
import pytest
import surpyval as surv
from repyability import NodeState, NonRepairableRBD

from backend.services import rbd_analysis as ra
from backend.services.rbd_analysis import AnalysisError, analyze
from backend.tests.test_mcp import A, GRAPH, _call, _err, _ok, env  # noqa: F401
from backend.tests.test_rbd_uncertainty import (  # noqa: F401
    FIT,
    _edges,
    _graph,
    _node,
    _resolver,
    _saved,
    _save_model,
    client,
)

W = surv.Weibull.from_params


def _weibull(alpha, beta):
    return {"source": "params", "distribution_id": "weibull",
            "params": [{"name": "alpha", "value": alpha}, {"name": "beta", "value": beta}]}


def _pumps():
    """Two pumps in parallel, then a valve in series (hours)."""
    return _graph(
        [_node("a", _weibull(100, 2)), _node("b", _weibull(100, 2)), _node("v", _weibull(500, 1.5))],
        _edges(("input", "a"), ("input", "b"), ("a", "v"), ("b", "v"), ("v", "output")),
    )


def _repy():
    return NonRepairableRBD(
        [("s", "a"), ("s", "b"), ("a", "v"), ("b", "v"), ("v", "t")],
        {"a": W([100, 2]), "b": W([100, 2]), "v": W([500, 1.5])},
    )


# ---- the current state ----------------------------------------------------


def test_state_is_canonical():
    graph = _pumps()
    assert ra.parse_nonrepairable_state(graph, None) is None
    assert ra.parse_nonrepairable_state(graph, {}) is None
    assert ra.parse_nonrepairable_state(graph, {"a": {"age": 0}}) is None  # new
    assert ra.parse_nonrepairable_state(graph, {"v": {"age": 5}, "a": {"failed": True}, "b": {"down": True}}) == {
        "a": {"failed": True}, "b": {"failed": True}, "v": {"age": 5.0}}


@pytest.mark.parametrize("raw, message", [
    ([1], "must be an object"),
    ({"zz": {"age": 1}}, "isn't a block"),
    ({"input": {"age": 1}}, "isn't a block"),
    ({"a": {"age": -1}}, "≥ 0"),
    ({"a": {"age": "old"}}, "must be a number"),
    ({"a": {"failed": True, "age": 3}}, "has no age"),
    ({"a": {"failed": "yes"}}, "true or false"),
    ({"a": {"down": True, "since": 2}}, "isn't repaired"),
    ({"a": {"wear": 2}}, "unknown current-state field"),
    ({"a": 5}, "give"),
])
def test_state_is_validated(raw, message):
    with pytest.raises(AnalysisError, match=message):
        ra.parse_nonrepairable_state(_pumps(), raw)


def test_only_plain_unpinned_component_blocks_take_a_state():
    graph = _pumps()
    graph["nodes"].append(_node("p", _weibull(100, 2), "parallel", n=2))
    with pytest.raises(AnalysisError, match="only single component blocks"):
        ra.parse_nonrepairable_state(graph, {"p": {"age": 1}})
    graph = _pumps()
    graph["nodes"][2]["data"]["state"] = "failed"
    with pytest.raises(AnalysisError, match="pinned failed"):
        ra.parse_nonrepairable_state(graph, {"a": {"age": 1}})
    graph = _pumps()
    graph["nodes"][3]["data"]["repeat_of"] = "a"
    graph["nodes"][3]["data"].pop("model")
    with pytest.raises(AnalysisError, match="linked copy of A"):
        ra.parse_nonrepairable_state(graph, {"b": {"age": 1}})


# ---- the analysis as of now -------------------------------------------------


def test_as_of_now_matches_repyability():
    state = {"a": {"age": 50}, "b": {"failed": True}}
    res = analyze(_pumps(), current_state=state, target_reliability=0.9, at_times=[0, 10, 30])
    json.dumps(res)  # JSON-safe
    rbd, nodes = _repy(), {"a": NodeState(age=50), "b": NodeState(alive=False)}

    assert res["current_state"] == {"a": {"age": 50.0}, "b": {"failed": True}}
    assert res["reliability_now"] == pytest.approx(1.0)
    # The curve runs from now.
    assert res["at"]["sf"] == pytest.approx(list(rbd.sf_given_state(np.array([0.0, 10, 30]), nodes)))
    t = np.array(res["time"])
    assert res["system"]["sf"] == pytest.approx(list(rbd.sf_given_state(t, nodes)), abs=1e-12)
    # The design life is the remaining life to 90%.
    dl = res["design_life"]
    assert dl["from"] == "now" and dl["target"] == 0.9
    assert dl["time"] == pytest.approx(rbd.remaining_life(0.9, nodes), rel=1e-6)
    assert res["blife"]["b10"] == pytest.approx(dl["time"], rel=1e-3)
    # The mean remaining life: the area under the curve from now.
    grid = np.linspace(0, 2000, 40001)
    assert res["mttf"] == pytest.approx(np.trapezoid(rbd.sf_given_state(grid, nodes), grid), rel=1e-3)
    # The importances given the state, at the representative time.
    imp = rbd.importances_given_state(res["importance"]["time"], nodes)
    for key in ("birnbaum", "criticality"):
        for n in "abv":
            assert res["importance"][key][n] == pytest.approx(imp[key][n], abs=1e-9)
    # Per-block curves: the failed pump is 0, the aged one conditioned on its age.
    by_id = {n["id"]: n for n in res["nodes"]}
    assert set(by_id["b"]["sf"]) == {0.0}
    assert by_id["a"]["sf"][-1] == pytest.approx(float(W([100, 2]).sf(50 + t[-1]) / W([100, 2]).sf(50)))

    # Shorter than from new.
    new = analyze(_pumps(), target_reliability=0.9)
    assert new["design_life"]["time"] > dl["time"] and new["mttf"] > res["mttf"]
    assert "current_state" not in new and "reliability_now" not in new


def test_design_life_from_new_and_from_an_age():
    rbd = _repy()
    new = analyze(_pumps(), target_reliability=0.9)["design_life"]
    assert new == {"target": 0.9, "from": "new", "time": pytest.approx(rbd.time_to_reliability(0.9))}
    aged = analyze(_pumps(), target_reliability=0.9, conditional_age=40)["design_life"]
    r40 = float(rbd.sf(40))
    assert aged["from"] == "age"
    assert float(rbd.sf(40 + aged["time"])) / r40 == pytest.approx(0.9, abs=1e-6)
    # Not asked for: not there.
    assert "design_life" not in analyze(_pumps())


def test_a_failed_system_and_an_unreachable_target():
    res = analyze(_pumps(), current_state={"a": {"failed": True}, "b": {"failed": True}}, target_reliability=0.9)
    assert res["reliability_now"] == 0.0 and res["mttf"] is None
    assert res["design_life"]["time"] is None
    assert "already below 90% now" in res["design_life"]["message"]
    # A limited failure population (5% can fail at all): never falls to 90%.
    lfp = _graph([_node("f", {**_weibull(100, 2), "extras": {"p": 0.05}})],
                 _edges(("input", "f"), ("f", "output")))
    out = analyze(lfp, target_reliability=0.9)
    assert out["design_life"]["time"] is None and "never falls to 90%" in out["design_life"]["message"]


def test_pins_apply_as_of_now():
    graph = _pumps()
    graph["nodes"][4]["data"]["state"] = "working"  # the valve pinned working
    res = analyze(graph, current_state={"a": {"age": 50}}, target_reliability=0.9)
    rbd = NonRepairableRBD([("s", "a"), ("s", "b"), ("a", "t"), ("b", "t")],
                           {"a": W([100, 2]), "b": W([100, 2])})
    assert res["design_life"]["time"] == pytest.approx(rbd.remaining_life(0.9, {"a": NodeState(age=50)}), rel=1e-6)


def test_as_of_now_refusals():
    with pytest.raises(AnalysisError, match="not both"):
        analyze(_pumps(), current_state={"a": {"age": 5}}, conditional_age=10)
    graph = _pumps()
    graph["ccf_groups"] = [{"members": ["a", "b"], "beta": 0.1}]
    with pytest.raises(AnalysisError, match="common-cause"):
        analyze(graph, current_state={"a": {"age": 5}})
    for bad in (0, 1, 1.5, -0.2, "0.9", True):
        with pytest.raises(AnalysisError, match="target reliability"):
            analyze(_pumps(), target_reliability=bad)


# ---- the design life's uncertainty -------------------------------------------


def _fitted_pumps():
    return _graph(
        [_node("a", _saved("m1", FIT)), _node("b", _saved("m1", FIT)), _node("v", _weibull(5000, 1.5))],
        _edges(("input", "a"), ("input", "b"), ("a", "v"), ("b", "v"), ("v", "output")),
    )


def test_design_life_interval_from_the_fitted_blocks():
    res = analyze(_fitted_pumps(), resolve_model=_resolver({"m1": FIT}), band={"level": 0.9},
                  target_reliability=0.9)
    iv, t = res["band"]["design_life"], res["design_life"]["time"]
    assert iv["lower"] < t < iv["upper"]
    # Its B10 is the same quantity, from the same draws.
    assert iv == pytest.approx(res["band"]["blife"]["b10"], rel=1e-9)

    # As of now: the band and the interval run from now, and are shorter.
    now = analyze(_fitted_pumps(), resolve_model=_resolver({"m1": FIT}), band={"level": 0.9},
                  target_reliability=0.9, current_state={"a": {"age": 120}, "b": {"failed": True}})
    band = now["band"]
    assert band["sf_lower"][0] == pytest.approx(1.0) and band["sf_upper"][0] == pytest.approx(1.0)
    assert [b["id"] for b in band["uncertain"]] == ["a"]  # the failed pump draws nothing
    niv, nt = band["design_life"], now["design_life"]["time"]
    assert niv["lower"] < nt < niv["upper"] and niv["upper"] < iv["lower"]
    sf, lo, hi = (np.array(v) for v in (now["system"]["sf"], band["sf_lower"], band["sf_upper"]))
    mid = (sf > 0.05) & (sf < 0.95)
    assert mid.any() and np.all((lo[mid] <= sf[mid] + 1e-12) & (sf[mid] <= hi[mid] + 1e-12))


def test_the_interval_agrees_with_repyability():
    """One fitted block: RePyability's own time_to_reliability_uncertainty
    (different draws, the same sampler) gives much the same interval."""
    graph = _graph([_node("a", _saved("m1", FIT))], _edges(("input", "a"), ("a", "output")))
    res = analyze(graph, resolve_model=_resolver({"m1": FIT}), band={"level": 0.9}, target_reliability=0.9)
    ref = NonRepairableRBD([("s", "a"), ("a", "t")], {"a": FIT}).time_to_reliability_uncertainty(
        0.9, {"a": "fit"}, seed=1, n_draws=4000)
    lo, hi = ref.interval(0.9)
    assert res["design_life"]["time"] == pytest.approx(ref.nominal, rel=1e-6)
    assert res["band"]["design_life"]["lower"] == pytest.approx(lo, rel=0.08)
    assert res["band"]["design_life"]["upper"] == pytest.approx(hi, rel=0.08)


# ---- through the API and MCP ----------------------------------------------------


def test_api_as_of_now(client):
    _, block = _save_model(client)
    graph = _graph([_node("a", block), _node("b", block)],
                   _edges(("input", "a"), ("input", "b"), ("a", "output"), ("b", "output")))
    body = {"graph": graph, "current_state": {"a": {"age": 300}}, "target_reliability": 0.9,
            "band": {"level": 0.9}}
    r = client.post("/api/rbds/analyze", json=body)
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["current_state"] == {"a": {"age": 300.0}} and out["reliability_now"] == pytest.approx(1.0)
    iv = out["band"]["design_life"]
    assert iv["lower"] < out["design_life"]["time"] < iv["upper"]
    plain = client.post("/api/rbds/analyze", json={"graph": graph}).json()
    assert "design_life" not in plain and plain["mttf"] > out["mttf"]

    bad = client.post("/api/rbds/analyze", json={**body, "current_state": {"a": {"down": True, "since": 3}}})
    assert bad.status_code == 422 and "isn't repaired" in bad.json()["detail"]
    bad = client.post("/api/rbds/analyze", json={**body, "target_reliability": 90})
    assert bad.status_code == 422 and "between 0 and 1" in bad.json()["detail"]


def test_mcp_as_of_now_and_design_life(env):  # noqa: F811
    rid = _ok(_call(env.token[A], "create_rbd", {"name": "Pump skid", "unit": "Hours", **GRAPH}))["id"]
    new = _ok(_call(env.token[A], "analyze_rbd", {"rbd_id": rid, "target_reliability": 0.9}))
    assert new["design_life"]["from"] == "new" and new["design_life"]["time"] > 0
    assert "current_state" not in new and "confidence" not in new

    now = _ok(_call(env.token[A], "analyze_rbd", {
        "rbd_id": rid, "target_reliability": 0.9, "times": [0, 100],
        "current_state": {"p1": {"failed": True}, "ctl": {"age": 400}}}))
    assert now["from"] == "now" and now["reliability_now"] == pytest.approx(1.0)
    assert now["current_state"] == {"ctl": {"age": 400.0, "label": "Controller"},
                                    "p1": {"failed": True, "label": "Pump A"}}
    assert 0 < now["design_life"]["time"] < new["design_life"]["time"]
    assert now["mttf"] < new["mttf"]

    # Hand-entered blocks carry no uncertainty: the intervals say so.
    conf = _ok(_call(env.token[A], "analyze_rbd", {"rbd_id": rid, "target_reliability": 0.9,
                                                   "confidence": 0.9}))["confidence"]
    assert conf["level"] == 0.9 and conf["uncertain_blocks"] == [] and conf["design_life"] is None
    assert {b["label"] for b in conf["fixed_blocks"]} == {"Controller", "Pump A", "Pump B"}

    assert "isn't repaired" in _err(_call(env.token[A], "analyze_rbd", {
        "rbd_id": rid, "current_state": {"p1": {"down": True, "since": 2}}}))
    assert "not both" in _err(_call(env.token[A], "analyze_rbd", {
        "rbd_id": rid, "conditional_age": 10, "current_state": {"p1": {"age": 2}}}))
    _err(_call(env.token[A], "analyze_rbd", {"rbd_id": rid, "target_reliability": 1.5}))
