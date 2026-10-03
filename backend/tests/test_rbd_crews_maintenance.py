"""Repair crews and standby groups (#156) and RePyability 0.11's maintenance
policies (#157) on repairable RBDs: condition-based replacement, opportunistic
maintenance groups with a shared set-up cost, hidden failures for any life,
and a safety function's PFDavg with staggered, imperfect proof tests and
common cause. Each against RePyability 0.11 directly (the same numbers), then
validation, the MCP tools and the Python export."""

import math

import matplotlib

matplotlib.use("Agg")

import pytest  # noqa: E402
import surpyval as sv  # noqa: E402
from repyability import BetaFactor, CCFGroup, RepairableRBD  # noqa: E402
from scipy.integrate import quad  # noqa: E402

from backend.services import rbd_analysis as ra  # noqa: E402
from backend.services import rbd_export, rbd_policies  # noqa: E402
from backend.services.rbd_analysis import AnalysisError  # noqa: E402
from backend.services.rbds import availability_cache_key  # noqa: E402
from backend.tests.test_mcp import A, _call, _err, _ok, env  # noqa: E402,F401 - env is a fixture
from backend.tests.test_mcp_rbd_edit import _doc, _edit, _node as _saved_node  # noqa: E402
from backend.tests.test_rbd_costs import _exp, _io, _ln, _node, _series, _w  # noqa: E402
from backend.tests.test_rbd_export import WHEN, _run  # noqa: E402

N = 200  # fixed simulation counts keep the suite quick
E = sv.Exponential.from_params
W = sv.Weibull.from_params


def _parallel(*nodes, **graph):
    edges = []
    for n in nodes:
        edges += [{"id": f"i-{n['id']}", "source": "input", "target": n["id"]},
                  {"id": f"o-{n['id']}", "source": n["id"], "target": "output"}]
    return {"repairable": True, "unit": "hours", "nodes": [*_io(), *nodes], "edges": edges, **graph}


def _standby(nid="g", **data):
    return {"id": nid, "type": "standby", "position": {"x": 200, "y": 0},
            "data": {"label": nid.upper(), "model": _exp(0.01), "repair": _exp(0.1), "spares": 2,
                     "dormancy": 0, **data}}


def _pumps(n=2, **extra):
    return [_node(f"p{i}", model=_exp(0.01), repair=_exp(0.1), **extra) for i in range(1, n + 1)]


def _direct(edges, components, **kw):
    return RepairableRBD(edges, components, input_node="s", output_node="t", **kw)


PAR = [("s", "a"), ("s", "b"), ("a", "t"), ("b", "t")]


def _pump_spec():
    return {"reliability": E([0.01]), "repairability": E([0.1])}


# ---------------------------------------------------------------------------
# Repair crews (#156)
# ---------------------------------------------------------------------------
def test_fewer_crews_lower_availability_with_the_exact_markov_value():
    """Two exponential pumps in parallel (λ = 0.01, μ = 0.1). One crew: a
    birth-death chain with rates 2λ, λ up and μ, μ down, so both are down
    with probability (2λ²/μ²) / (1 + 2λ/μ + 2λ²/μ²) = 0.02 / 1.22."""
    out = {}
    for crews in (None, 2, 1):
        g = _parallel(*_pumps(), **({"repair_crews": {"crews": crews}} if crews else {}))
        out[crews] = ra.analyze_availability(g, n_simulations=N)
    assert out[None]["steady_state_availability"] == pytest.approx(1 - (1 / 11) ** 2, rel=1e-12)
    assert out[2]["steady_state_availability"] == pytest.approx(out[None]["steady_state_availability"], rel=1e-12)
    one = out[1]
    assert one["steady_state_availability"] == pytest.approx(1 - 0.02 / 1.22, rel=1e-12)
    assert one["steady_state_availability"] < out[None]["steady_state_availability"]
    direct = _direct(PAR, {"a": _pump_spec(), "b": _pump_spec()}, repair_crews=1)
    assert one["steady_state_availability"] == pytest.approx(direct.mean_availability(), rel=1e-12)
    assert one["mean_up_time"] == pytest.approx(direct.mean_up_time(), rel=1e-12)
    # The method is surfaced: RePyability's Markov chain of the repair queue.
    assert one["long_run_method"]["route"] == "exact"
    assert "Markov chain" in one["long_run_method"]["reason"]
    assert one["repair_crews"] == {"crews": 1, "jobs": 2, "blocks": 2, "limited": True,
                                   "priorities": {}, "own_repairer": []}
    assert out[2]["repair_crews"]["limited"] is False
    assert "repair_crews" not in out[None]


def test_crews_with_a_voting_gate_still_solve_the_chain():
    """A k-of-n gate is a (pinned, never-failing) component too: its stand-in
    is exponential so the crews' chain covers it, and it adds nothing."""
    nodes = [*_pumps(3), {"id": "vote", "type": "knode", "position": {"x": 400, "y": 0},
                          "data": {"label": "2oo3", "n": 2, "k": 3}}]
    edges = [e for p in ("p1", "p2", "p3") for e in ({"source": "input", "target": p},
                                                       {"source": p, "target": "vote"})]
    edges.append({"source": "vote", "target": "output"})
    g = {"repairable": True, "unit": "hours", "nodes": [*_io(), *nodes], "edges": edges,
         "repair_crews": {"crews": 1}}
    r = ra.analyze_availability(g, n_simulations=N)
    pump = _pump_spec
    direct = RepairableRBD([("s", "a"), ("s", "b"), ("s", "c"), ("a", "t"), ("b", "t"), ("c", "t")],
                           {"a": pump(), "b": pump(), "c": pump()}, k={"t": 2}, repair_crews=1)
    assert r["long_run_method"]["route"] == "exact"
    assert r["steady_state_availability"] == pytest.approx(direct.mean_availability(), rel=1e-9)
    assert r["repair_crews"]["jobs"] == 3  # the gate is no job


def test_crews_with_wear_out_lives_are_simulated_and_say_why():
    g = _parallel(_node("a", model=_w(100, 2), repair=_exp(0.1)), *_pumps(1), repair_crews={"crews": 1})
    r = ra.analyze_availability(g, n_simulations=N)
    assert r["steady_state_availability"] is None and r["availability_basis"] == "simulation"
    assert r["long_run_method"]["route"] == "refused"
    assert "exponential" in r["long_run_method"]["reason"]
    assert r["n_simulations"] >= N and 0 < r["precision"]["window_availability"] < 1


def test_crew_priority_reaches_repyability():
    g = _parallel(*_pumps(), repair_crews={"crews": 1})
    g["nodes"][2]["data"]["crew_priority"] = 5
    rbd = ra._build_repairable_rbd(g)[0]
    assert rbd.repair_crews == 1 and rbd._priority == {"p1": 5.0}
    # Priority changes which pump waits, not (for identical pumps) the system.
    assert rbd.mean_availability() == pytest.approx(1 - 0.02 / 1.22, rel=1e-12)


@pytest.mark.parametrize("crews", [0, 1.5, "two", -1])
def test_bad_crew_counts_are_clear_errors(crews):
    g = _parallel(*_pumps(), repair_crews={"crews": crews})
    v = ra.validate_graph(g)
    assert not v["valid"] and any("repair crews must be a whole number" in e for e in v["errors"]), v
    with pytest.raises(AnalysisError, match="repair crews"):
        ra._build_repairable_rbd(g)


def test_crews_change_the_cache_key():
    g = _parallel(*_pumps())
    assert availability_cache_key(g) != availability_cache_key({**g, "repair_crews": {"crews": 1}})


def test_crews_cost_breakdown_adds_up():
    g = _parallel(*_pumps(costs={"repair": 100, "downtime": 5}), repair_crews={"crews": 1},
                  costs={"downtime_rate": 1000})
    r = ra.analyze_availability(g, n_simulations=N)
    rbd = ra._build_repairable_rbd(g)[0]
    assert r["costs"]["cost_rate_basis"] == "exact"
    assert r["costs"]["cost_rate"] == pytest.approx(rbd.expected_cost_rate(), rel=1e-12)
    assert math.fsum(r["costs"]["by_category"].values()) == pytest.approx(r["costs"]["cost_rate"], rel=1e-9)


# ---------------------------------------------------------------------------
# Standby groups (#156)
# ---------------------------------------------------------------------------
def _standby_spec():
    return {"reliability": E([0.01]), "repairability": E([0.1]),
            "standby": {"units": 3, "k": 1, "dormancy_factor": 0.0, "switching_probability": 1.0}}


def test_standby_group_matches_repyability():
    r = ra.analyze_availability(_series(_standby()), n_simulations=N)
    direct = _direct([("s", "g"), ("g", "t")], {"g": _standby_spec()})
    assert r["steady_state_availability"] == pytest.approx(direct.mean_availability(), rel=1e-12)
    assert r["long_run_method"]["route"] == "exact"


def test_standby_group_repaired_one_unit_at_a_time():
    """One repairer for the group: the cold 1+2 group's chain with one crew
    (a birth-death chain λ up, μ down: down with probability
    (λ/μ)³ / Σ (λ/μ)^i) — less available than repairing every unit at once."""
    all_at_once = ra.analyze_availability(_series(_standby()), n_simulations=N)["steady_state_availability"]
    r = ra.analyze_availability(_series(_standby(repair_one_at_a_time=True)), n_simulations=N)
    rho = 0.1
    assert r["steady_state_availability"] == pytest.approx(1 - rho ** 3 / (1 + rho + rho ** 2 + rho ** 3), rel=1e-12)
    assert r["steady_state_availability"] < all_at_once
    direct = _direct([("s", "g"), ("g", "t")], {"g": _standby_spec()}, repair_crews=1)
    assert r["steady_state_availability"] == pytest.approx(direct.mean_availability(), rel=1e-12)


def test_standby_group_in_a_diagram_with_crews_and_costs():
    sb = _standby(costs={"repair": 200}, crew_priority=2)
    g = _series(sb, _node("v", model=_exp(1e-3), repair=_exp(0.5), costs={"repair": 50}),
                repair_crews={"crews": 1})
    r = ra.analyze_availability(g, n_simulations=N)
    rbd = ra._build_repairable_rbd(g)[0]
    assert rbd._standby["g"].units == 3 and rbd._priority == {"g": 2.0}
    # The chain has no place for a standby group among other jobs: simulated.
    assert r["long_run_method"]["route"] == "refused" and r["steady_state_availability"] is None
    assert r["costs"]["cost_rate_basis"] == "simulation"
    # Without the crew limit its unit repairs are priced exactly.
    g2 = {**g}
    g2.pop("repair_crews")
    r2 = ra.analyze_availability(g2, n_simulations=N)
    rbd2 = ra._build_repairable_rbd(g2)[0]
    assert r2["costs"]["cost_rate"] == pytest.approx(rbd2.expected_cost_rate(), rel=1e-12)
    assert r2["costs"]["by_category"]["repair"] == pytest.approx(
        200 * rbd2._standby_long_run("g").unit_failure_frequency + 50 * rbd2._node_frequencies("v")[0], rel=1e-9)


@pytest.mark.parametrize("data, needle", [
    ({"standbyModel": _exp(0.02)}, "units are identical"),
    ({"instant_repair": True}, "need a repair time"),
    ({"preventive": {"interval": 100}}, "takes no scheduled replacement"),
    ({"repair_one_at_a_time": True, "costs": {"repair": 5}}, "remove its costs"),
    ({"spares": 0}, "spares, 1 or more"),
    ({"repair": None}, "no repair-time distribution"),
])
def test_standby_group_errors(data, needle):
    sb = _standby()
    sb["data"].update(data)
    sb["data"] = {k: v for k, v in sb["data"].items() if v is not None}
    v = ra.validate_graph(_series(sb))
    assert not v["valid"] and any(needle in e for e in v["errors"]), v["errors"]


# ---------------------------------------------------------------------------
# Condition-based replacement (#96, #145)
# ---------------------------------------------------------------------------
def _cbm(**pm):
    return _node("pump", model=_w(100, 3), repair=_exp(1.0), costs={"replace": 100},
                 preventive={"policy": "condition", "interval": 10, "threshold": 0.05, "cost": 10,
                             "inspection_cost": 1, **pm})


def test_condition_based_replacement_matches_repyability():
    g = _series(_cbm())
    r = ra.analyze_availability(g, n_simulations=N)
    direct = _direct([("s", "c"), ("c", "t")], {"c": {
        "reliability": W([100, 3]), "repairability": E([1.0]), "replace_cost": 100,
        "preventive": {"interval": 10, "policy": "condition", "threshold": 0.05, "cost": 10,
                       "inspection_cost": 1}}})
    assert r["steady_state_availability"] == pytest.approx(direct.mean_availability(), rel=1e-12)
    assert r["long_run_method"]["route"] == "numerical"
    c = r["costs"]
    assert c["cost_rate"] == pytest.approx(direct.expected_cost_rate(), rel=1e-12)
    assert math.fsum(c["by_category"].values()) == pytest.approx(c["cost_rate"], rel=1e-9)
    # A condition check at each interval the pump is up at.
    up = direct._block_cycle("c").before
    assert c["by_category"]["inspection"] == pytest.approx(1 * up / 10, rel=1e-12)
    assert c["by_category"]["preventive"] > 0


def test_condition_based_replacement_beats_running_to_failure():
    run = ra.analyze_availability(_series(_node("pump", model=_w(100, 3), repair=_exp(1.0),
                                                costs={"replace": 100})), n_simulations=N)
    cbm = ra.analyze_availability(_series(_cbm()), n_simulations=N)
    assert cbm["steady_state_availability"] > run["steady_state_availability"]
    assert cbm["costs"]["cost_rate"] < run["costs"]["cost_rate"]


@pytest.mark.parametrize("pm, needle", [
    ({"threshold": None}, "set the replacement threshold"),
    ({"threshold": 1.5}, "must be a probability"),
    ({"policy": "age"}, "applies only to condition-based"),
    ({"interval": None}, "set the inspection interval"),
])
def test_condition_based_errors(pm, needle):
    node = _cbm(**pm)
    node["data"]["preventive"] = {k: v for k, v in node["data"]["preventive"].items() if v is not None}
    v = ra.validate_graph(_series(node))
    assert not v["valid"] and any(needle in e for e in v["errors"]), v["errors"]


# ---------------------------------------------------------------------------
# Opportunistic maintenance groups (#108)
# ---------------------------------------------------------------------------
def _wearing(nid, group, opportunity=None):
    pm = {"policy": "age", "interval": 80, "cost": 10}
    if opportunity is not None:
        pm["opportunity"] = opportunity
    return _node(nid, model=_w(100, 3), repair=_exp(1.0), costs={"replace": 50}, preventive=pm,
                 maintenance_group=group)


def _two_wearing(shared: bool, setup=5000.0):
    if shared:
        nodes = (_wearing("a", "g", 50), _wearing("b", "g", 50))
        groups = {"g": {"setup_cost": setup}}
    else:
        nodes = (_wearing("a", "g1"), _wearing("b", "g2"))
        groups = {"g1": {"setup_cost": setup}, "g2": {"setup_cost": setup}}
    return _series(*nodes, maintenance_groups=groups)


def test_separate_groups_are_exact_with_a_setup_category():
    g = _two_wearing(shared=False)
    r = ra.analyze_availability(g, n_simulations=N)
    spec = lambda grp: {"reliability": W([100, 3]), "repairability": E([1.0]), "replace_cost": 50,  # noqa: E731
                        "preventive": {"interval": 80, "policy": "age", "cost": 10}, "group": grp}
    direct = _direct([("s", "a"), ("a", "b"), ("b", "t")], {"a": spec("g1"), "b": spec("g2")},
                     maintenance_groups={"g1": {"setup_cost": 5000.0}, "g2": {"setup_cost": 5000.0}})
    c = r["costs"]
    assert c["cost_rate_basis"] == "exact"
    assert c["cost_rate"] == pytest.approx(direct.expected_cost_rate(), rel=1e-12)
    actions = sum(direct._node_actions("a", direct.node_availability()["a"]))
    assert c["by_category"]["setup"] == pytest.approx(2 * 5000 * actions, rel=1e-9)
    assert math.fsum(c["by_category"].values()) == pytest.approx(c["cost_rate"], rel=1e-9)


def test_opportunistic_grouping_lowers_cost_when_setup_dominates():
    """The same two wearing pumps: renewed together at the group's stops they
    share one set-up per stop, so the cost falls (simulated: RePyability has
    no exact values for early renewal)."""
    separate = ra.analyze_availability(_two_wearing(shared=False), n_simulations=N)
    shared = ra.analyze_availability(_two_wearing(shared=True), n_simulations=N)
    assert shared["long_run_method"]["route"] == "refused"
    assert shared["costs"]["cost_rate_basis"] == "simulation"
    assert shared["costs"]["cost_rate"] < 0.8 * separate["costs"]["cost_rate"]
    assert shared["opportunistic_renewals"]["A"] > 0
    # The same numbers as RePyability's own simulation of the same diagram.
    rbd = ra._build_repairable_rbd(_two_wearing(shared=True))[0]
    t = shared["t_simulation"]
    mine, _ = ra._simulate(rbd, t, {"working_nodes": set(), "broken_nodes": set()}, N)
    spec = {"reliability": W([100, 3]), "repairability": E([1.0]), "replace_cost": 50, "group": "g",
            "preventive": {"interval": 80, "policy": "age", "cost": 10, "opportunity": 50}}
    direct = _direct([("s", "a"), ("a", "b"), ("b", "t")], {"a": dict(spec), "b": dict(spec)},
                     maintenance_groups={"g": {"setup_cost": 5000.0, "system_down": False}})
    theirs, _ = ra._simulate(direct, t, {"working_nodes": set(), "broken_nodes": set()}, N)
    assert mine.cost.mean == pytest.approx(theirs.cost.mean, rel=1e-12)
    assert mine.cost.by_category["setup"] == pytest.approx(theirs.cost.by_category["setup"], rel=1e-12)


@pytest.mark.parametrize("node, groups, needle", [
    (_node("a", model=_w(100, 3), repair=_exp(1.0),
           preventive={"policy": "age", "interval": 80, "opportunity": 50}), None, "needs a maintenance group"),
    (_wearing("a", "g", 90), None, "from 0 to the replacement interval"),
    (_node("a", model=_w(100, 3), repair=_exp(1.0), maintenance_group="g",
           preventive={"policy": "block", "interval": 80, "opportunity": 50}), None, "applies only to age"),
    (_node("a", model=_exp(1e-3), instant_repair=True, maintenance_group="g", inspection={"interval": 10}),
     None, "can't be in a maintenance group"),
    (_wearing("a", "g"), {"g": {"setup_cost": -1}}, "set-up cost must be a non-negative"),
    (_wearing("a", "g"), {"g": {"system_down": "yes"}}, "system_down must be true or false"),
    (_wearing("a", "g"), {"g": {"setup": 5}}, "unknown option"),
])
def test_opportunistic_errors(node, groups, needle):
    g = _series(node, **({"maintenance_groups": groups} if groups else {}))
    v = ra.validate_graph(g)
    assert not v["valid"] and any(needle in e for e in v["errors"]), v["errors"]


def test_unused_group_options_warn_and_are_left_out():
    g = _series(_wearing("a", "g"), maintenance_groups={"g": {"setup_cost": 10}, "old": {"setup_cost": 5}})
    v = ra.validate_graph(g)
    assert v["valid"] and any("“old” has no blocks" in w for w in v["warnings"])
    assert set(ra._build_repairable_rbd(g)[0]._maintenance) == {"g"}


# ---------------------------------------------------------------------------
# Hidden failures for any life (#144)
# ---------------------------------------------------------------------------
def test_hidden_failures_of_a_wearing_life_are_exact():
    """Tests every τ = 100, instant tests and repairs: a unit is renewed at the
    first test after it fails, at τ·N, N = ⌈T/τ⌉, so it is up MTTF of every
    τ·E[N] = τ·Σₖ R(kτ) (a renewal-reward cycle)."""
    g = _series(_node("valve", model=_w(1000, 2), instant_repair=True, inspection={"interval": 100}))
    r = ra.analyze_availability(g, n_simulations=N)
    direct = _direct([("s", "v"), ("v", "t")], {"v": {
        "reliability": W([1000, 2]), "repairability": "instant", "inspection": {"interval": 100}}})
    assert r["steady_state_availability"] == pytest.approx(direct.mean_availability(), rel=1e-12)
    assert r["availability_basis"] == "exact" and r["long_run_method"]["route"] == "numerical"
    mttf = 1000 * math.gamma(1.5)
    cycle = 100 * sum(math.exp(-(k / 10) ** 2) for k in range(200))
    assert r["unavailability"] == pytest.approx(1 - mttf / cycle, rel=1e-6)


# ---------------------------------------------------------------------------
# Safety functions: PFDavg, SIL, staggered and imperfect tests, common cause (#136)
# ---------------------------------------------------------------------------
LAM, TAU = 1e-3, 100.0


def _channel(nid, **test):
    return _node(nid, model=_exp(LAM), instant_repair=True, inspection={"interval": TAU, **test})


def _channel_spec(**test):
    return {"reliability": E([LAM]), "repairability": "instant", "inspection": {"interval": TAU, **test}}


def _sif(a=None, b=None, **graph):
    return _parallel(_channel("a", **(a or {})), _channel("b", **(b or {})), safety_function=True, **graph)


def test_pfdavg_of_a_1oo2_matches_repyability_and_the_formula():
    r = ra.analyze_availability(_sif(), n_simulations=N)
    s = r["safety"]
    direct = _direct(PAR, {"a": _channel_spec(), "b": _channel_spec()})
    assert s["pfd_avg"] == pytest.approx(direct.mean_unavailability(), rel=1e-12)
    # (1/τ) ∫₀^τ (1 − e^(−λt))² dt ≈ (λτ)²/3.
    exact = quad(lambda t: (1 - math.exp(-LAM * t)) ** 2, 0, TAU)[0] / TAU
    assert s["pfd_avg"] == pytest.approx(exact, rel=1e-9)
    assert s["sil"] == 2 and s["basis"] == "exact" and s["common_cause"] is None
    assert s["proof_tested_blocks"] == 2 and not s["staggered"] and not s["imperfect_tests"]


def test_staggered_tests_lower_pfdavg():
    together = ra.analyze_availability(_sif(), n_simulations=N)["safety"]
    staggered = ra.analyze_availability(_sif(b={"offset": TAU / 2}), n_simulations=N)["safety"]
    direct = _direct(PAR, {"a": _channel_spec(), "b": _channel_spec(offset=TAU / 2)})
    assert staggered["pfd_avg"] == pytest.approx(direct.mean_unavailability(), rel=1e-12)
    assert staggered["pfd_avg"] < together["pfd_avg"] and staggered["staggered"]


def test_imperfect_proof_tests_raise_pfdavg():
    perfect = ra.analyze_availability(_sif(), n_simulations=N)["safety"]
    test = {"coverage": 0.9, "full_test": 10 * TAU}
    imperfect = ra.analyze_availability(_sif(a=test, b=test), n_simulations=N)["safety"]
    direct = _direct(PAR, {"a": _channel_spec(**test), "b": _channel_spec(**test)})
    assert imperfect["pfd_avg"] == pytest.approx(direct.mean_unavailability(), rel=1e-12)
    assert imperfect["pfd_avg"] > perfect["pfd_avg"] and imperfect["imperfect_tests"]


def test_common_cause_enters_pfdavg():
    ccf = [{"id": "c1", "members": ["a", "b"], "beta": 0.1}]
    without = ra.analyze_availability(_sif(), n_simulations=N)
    r = ra.analyze_availability(_sif(ccf_groups=ccf, target_sil=3), n_simulations=N)
    s = r["safety"]
    direct = _direct(PAR, {"a": _channel_spec(), "b": _channel_spec()},
                     ccf_groups=[CCFGroup(members=["a", "b"], model=BetaFactor(0.1))])
    assert s["pfd_avg"] == pytest.approx(direct.mean_unavailability(), rel=1e-12)
    assert s["pfd_avg"] > without["safety"]["pfd_avg"]
    assert s["common_cause"] == {"groups": 1, "included": True, "note": None}
    assert s["sil"] == 2 and s["target_sil"] == 3 and s["meets_target"] is False
    # The availability figures leave the groups out (RePyability's simulation can't take them).
    assert r["steady_state_availability"] == pytest.approx(without["steady_state_availability"], rel=1e-12)


def test_common_cause_left_out_when_the_chain_cannot_take_it():
    ccf = [{"id": "c1", "members": ["a", "b"], "beta": 0.1}]
    g = _parallel(_node("a", model=_w(1000, 2), instant_repair=True, inspection={"interval": TAU}),
                  _node("b", model=_w(1000, 2), instant_repair=True, inspection={"interval": TAU}),
                  safety_function=True, ccf_groups=ccf)
    s = ra.analyze_availability(g, n_simulations=N)["safety"]
    assert s["common_cause"]["included"] is False and "exponential" in s["common_cause"]["note"]
    assert s["pfd_avg"] == pytest.approx(ra._build_repairable_rbd(g)[0].mean_unavailability(), rel=1e-12)


def test_no_safety_block_unless_marked():
    assert "safety" not in ra.analyze_availability(_parallel(_channel("a"), _channel("b")), n_simulations=N)


@pytest.mark.parametrize("pfd, sil", [(5e-6, 4), (1e-5, 4), (5e-5, 4), (1e-4, 3), (9.99e-4, 3), (1e-3, 2),
                                      (0.05, 1), (0.1, None), (0.5, None), (None, None)])
def test_sil_bands(pfd, sil):
    assert rbd_policies.sil_band(pfd) == sil


@pytest.mark.parametrize("test, needle", [
    ({"coverage": 0.9}, "set the full-test interval"),
    ({"coverage": 0.9, "full_test": 250}, "whole multiple"),
    ({"coverage": 1.2}, "must be a probability"),
    ({"offset": TAU}, "within the first interval"),
])
def test_proof_test_errors(test, needle):
    v = ra.validate_graph(_sif(b=test))
    assert not v["valid"] and any(needle in e for e in v["errors"]), v["errors"]


def test_target_sil_error_and_ccf_warnings():
    v = ra.validate_graph(_sif(target_sil=5))
    assert any("target SIL must be 1, 2, 3 or 4" in e for e in v["errors"])
    ccf = [{"id": "c1", "members": ["a", "b"], "beta": 0.1}]
    plain = _parallel(_channel("a"), _channel("b"), ccf_groups=ccf)
    assert any("mark the diagram as a safety function" in w for w in ra.validate_graph(plain)["warnings"])
    assert any("enter the safety function's PFDavg" in w
               for w in ra.validate_graph(_sif(ccf_groups=ccf))["warnings"])


# ---------------------------------------------------------------------------
# Existing maintenance keeps working (R2)
# ---------------------------------------------------------------------------
def test_r2_maintenance_unchanged():
    g = _series(_node("pump", model=_w(1000, 2.5), repair=_ln(3.0, 0.5), costs={"replace": 500},
                      preventive={"policy": "age", "interval": 580, "cost": 100}))
    rbd = ra._build_repairable_rbd(g)[0]
    assert rbd._preventive["pump"].policy == "age" and rbd._member_group == {} and rbd.repair_crews is None
    r = ra.analyze_availability(g, n_simulations=N)
    assert r["costs"]["cost_rate"] == pytest.approx(rbd.expected_cost_rate(), rel=1e-12)
    assert r["costs"]["by_category"]["setup"] == 0.0


# ---------------------------------------------------------------------------
# MCP: create_rbd / edit_rbd round-trip the new fields
# ---------------------------------------------------------------------------
def _m(dist, **params):
    return {"distribution_id": dist, "params": [{"name": k, "value": v} for k, v in params.items()]}


def _mcp_graph():
    exp = _m("exponential", failure_rate=1e-3)
    rep = _m("lognormal", mu=1.0, sigma=0.4)
    return {
        "nodes": [
            {"id": "input", "type": "input"}, {"id": "output", "type": "output"},
            {"id": "a", "type": "component", "label": "Channel A", "model": exp, "instant_repair": True,
             "inspection": {"interval": 100, "coverage": 0.9, "full_test": 1000}},
            {"id": "b", "type": "component", "label": "Channel B", "model": exp, "instant_repair": True,
             "inspection": {"interval": 100, "offset": 50}},
            {"id": "pump", "type": "component", "label": "Pump", "model": _m("weibull", alpha=100, beta=3),
             "repair": rep, "costs": {"replace": {"min": 40, "max": 60}},
             "preventive": {"policy": "condition", "interval": 10, "threshold": 0.05, "inspection_cost": 1},
             "crew_priority": 2},
            {"id": "fan", "type": "component", "label": "Fan", "model": _m("weibull", alpha=100, beta=3),
             "repair": rep, "maintenance_group": "north",
             "preventive": {"policy": "age", "interval": 80, "opportunity": 50}},
            {"id": "bank", "type": "standby", "label": "Bank", "model": exp, "repair": rep, "spares": 2,
             "dormancy": 0, "repair_one_at_a_time": True},
        ],
        "edges": [{"source": "input", "target": "a"}, {"source": "input", "target": "b"},
                  {"source": "a", "target": "pump"}, {"source": "b", "target": "pump"},
                  {"source": "pump", "target": "fan"}, {"source": "fan", "target": "bank"},
                  {"source": "bank", "target": "output"}],
    }


def test_mcp_create_rbd_round_trips_the_new_fields(env):
    out = _ok(_call(env.token[A], "create_rbd", {
        "name": "SIF", "unit": "Hours", "repairable": True, **_mcp_graph(), "repair_crews": 2,
        "maintenance_groups": {"north": {"setup_cost": 500}}, "safety_function": True, "target_sil": 2}))
    graph = _doc(env, out["id"])["graph"]
    assert graph["repair_crews"] == {"crews": 2} and graph["safety_function"] is True
    assert graph["target_sil"] == 2 and graph["maintenance_groups"] == {"north": {"setup_cost": 500.0}}
    nodes = {n["id"]: n["data"] for n in graph["nodes"]}
    assert nodes["a"]["inspection"] == {"interval": 100.0, "coverage": 0.9, "full_test": 1000.0}
    assert nodes["b"]["inspection"]["offset"] == 50.0
    assert nodes["pump"]["preventive"]["threshold"] == 0.05 and nodes["pump"]["crew_priority"] == 2.0
    assert nodes["pump"]["costs"] == {"replace": {"min": 40.0, "max": 60.0}}
    assert nodes["fan"]["maintenance_group"] == "north" and nodes["fan"]["preventive"]["opportunity"] == 50.0
    assert nodes["bank"]["repair_one_at_a_time"] is True
    got = _ok(_call(env.token[A], "get_rbd", {"rbd_id": out["id"]}))["graph"]
    assert got["repair_crews"] == {"crews": 2} and got["safety_function"] is True
    assert {n["id"]: n for n in got["nodes"]}["fan"]["maintenance_group"] == "north"
    # analyze_rbd reports the method, the crews and the safety function.
    res = _ok(_call(env.token[A], "analyze_rbd", {"rbd_id": out["id"]}))
    assert res["repair_crews"]["crews"] == 2 and res["long_run_method"]["route"] in (
        "exact", "numerical", "refused")
    assert res["safety"]["pfd_avg"] > 0


def test_mcp_create_rbd_refuses_settings_on_a_reliability_diagram(env):
    g = {"nodes": [{"id": "input", "type": "input"}, {"id": "output", "type": "output"},
                   {"id": "a", "type": "component", "model": _m("exponential", failure_rate=1e-3)}],
         "edges": [{"source": "input", "target": "a"}, {"source": "a", "target": "output"}]}
    msg = _err(_call(env.token[A], "create_rbd", {"name": "x", **g, "repair_crews": 1}))
    assert "repairable diagrams only" in msg


def test_mcp_edit_rbd_sets_and_clears_the_new_fields(env):
    rid = _ok(_call(env.token[A], "create_rbd", {"name": "SIF", "unit": "Hours", "repairable": True,
                                                 **_mcp_graph()}))["id"]
    out = _ok(_edit(env, rid,
                    {"op": "set", "repair_crews": 1, "safety_function": True, "target_sil": 3,
                     "maintenance_groups": {"north": {"setup_cost": 900, "system_down": True}}},
                    {"op": "update_node", "id": "b", "inspection": {"interval": 100, "offset": 25}},
                    {"op": "update_node", "id": "pump", "clear": ["preventive", "crew_priority"],
                     "maintenance_group": "north"},
                    {"op": "update_node", "id": "bank", "repair_one_at_a_time": False, "crew_priority": 4},
                    {"op": "add_ccf", "members": ["a", "b"], "beta": 0.05}))
    assert "1 repair crew shared by every block" in out["applied"][0]
    graph = _doc(env, rid)["graph"]
    assert graph["repair_crews"] == {"crews": 1} and graph["target_sil"] == 3
    assert graph["maintenance_groups"] == {"north": {"setup_cost": 900.0, "system_down": True}}
    assert graph["ccf_groups"][0]["members"] == ["a", "b"]
    assert _saved_node(env, rid, "b")["data"]["inspection"] == {"interval": 100.0, "offset": 25.0}
    pump = _saved_node(env, rid, "pump")["data"]
    assert "preventive" not in pump and "crew_priority" not in pump and pump["maintenance_group"] == "north"
    bank = _saved_node(env, rid, "bank")["data"]
    assert bank["repair_one_at_a_time"] is False and bank["crew_priority"] == 4.0
    # Clearing the diagram settings.
    _ok(_edit(env, rid, {"op": "set", "repair_crews": 0, "safety_function": False, "maintenance_groups": {}}))
    graph = _doc(env, rid)["graph"]
    assert not {"repair_crews", "safety_function", "target_sil", "maintenance_groups"} & set(graph)


def test_mcp_edit_rbd_errors(env):
    rid = _ok(_call(env.token[A], "create_rbd", {"name": "SIF", "unit": "Hours", "repairable": True,
                                                 **_mcp_graph()}))["id"]
    assert "only component nodes" in _err(_edit(env, rid, {"op": "update_node", "id": "bank",
                                                           "preventive": {"interval": 10}}))
    assert "set safety_function true" in _err(_edit(env, rid, {"op": "set", "target_sil": 2}))
    # A setting RePyability would refuse fails validation, and nothing is saved.
    msg = _err(_edit(env, rid, {"op": "update_node", "id": "a", "maintenance_group": "north"}))
    assert "can't be in a maintenance group" in msg


# ---------------------------------------------------------------------------
# Download as Python: the script runs and matches the app
# ---------------------------------------------------------------------------
def _export_graph():
    ccf = [{"id": "c1", "members": ["a", "b"], "beta": 0.1}]
    nodes = [_channel("a"), _channel("b", offset=TAU / 2),
             _standby("bank", costs={"repair": 20}),
             _node("pump", model=_w(100, 3), repair=_exp(1.0), costs={"replace": 100},
                   preventive={"policy": "condition", "interval": 10, "threshold": 0.05, "cost": 10,
                               "inspection_cost": 1}, crew_priority=1)]
    edges = [("input", "a"), ("input", "b"), ("a", "bank"), ("b", "bank"), ("bank", "pump"), ("pump", "output")]
    return {"repairable": True, "unit": "hours", "nodes": [*_io(), *nodes],
            "edges": [{"id": f"e{i}", "source": s, "target": t} for i, (s, t) in enumerate(edges)],
            "safety_function": True, "target_sil": 1, "ccf_groups": ccf, "costs": {"downtime_rate": 100}}


def test_export_reproduces_crews_policies_and_pfdavg(tmp_path):
    g = _export_graph()
    app = ra.analyze_availability(g, n_simulations=60)
    code = rbd_export.to_python(g, "SIF", exported_at=WHEN)
    assert "CCFGroup(members=['a', 'b'], model=BetaFactor(0.1))" in code
    assert '"threshold": 0.05' in code and '"offset": 50' in code and '"standby": {"units": 3' in code
    res, proc = _run(code, tmp_path, n_sims="60")
    assert res["steady_state_availability"] == pytest.approx(app["steady_state_availability"], rel=1e-12)
    assert res["safety"]["pfd_avg"] == pytest.approx(app["safety"]["pfd_avg"], rel=1e-12)
    assert res["safety"]["common_cause"] is True and res["safety"]["sil"] == app["safety"]["sil"]
    assert res["long_run_method"]["route"] == app["long_run_method"]["route"]
    assert res["costs"]["cost_rate"] == pytest.approx(app["costs"]["cost_rate"], rel=1e-12)
    assert "PFDavg" in proc.stdout


def test_export_with_crews_groups_and_one_at_a_time_standby(tmp_path):
    g = _two_wearing(shared=True)
    g["nodes"].append(_standby("bank", repair_one_at_a_time=True))
    g["edges"] = [{"source": a, "target": b} for a, b in
                  (("input", "a"), ("a", "b"), ("b", "bank"), ("bank", "output"))]
    g["repair_crews"] = {"crews": 1}
    code = rbd_export.to_python(g, "Groups", exported_at=WHEN)
    assert "repair_crews=1" in code and "maintenance_groups=MAINTENANCE_GROUPS" in code
    assert "repair_crews=1)" in code  # the bank's own repairer
    app = ra.analyze_availability(g, n_simulations=60)
    res, _ = _run(code, tmp_path, n_sims="60")
    assert math.isnan(res["steady_state_availability"]) and app["steady_state_availability"] is None
    assert res["n_simulations"] == app["n_simulations"]
    assert res["precision"]["window_availability"] == pytest.approx(
        app["precision"]["window_availability"], rel=1e-12)
    assert res["costs"]["cost_rate"] == pytest.approx(app["costs"]["cost_rate"], rel=1e-9)
