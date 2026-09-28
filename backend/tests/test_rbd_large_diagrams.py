"""Large / highly redundant diagrams stay fast: vectorised importance measures
(identical to RePyability's), cut sets derived fully only when cheap (else the
lowest-order ones, labelled), a path-count cap with advice, and availability
simulations sized to a time budget over a horizon set by the blocks that
actually carry downtime."""

import numpy as np
import pytest

from backend.services import rbd_analysis as ra
from backend.services.rbd_analysis import AnalysisError
from backend.tests.test_rbd_analysis import _component, _edge, _io_nodes, _repairable_component


def _stages(k, repairable=False):
    """k stages of duplicated units in series: 2^k minimal path sets."""
    nodes, edges, prev = _io_nodes(), [], ["input"]
    for i in range(k):
        cur = []
        for side in "ab":
            nid = f"{side}{i}"
            if repairable:
                nodes.append(_repairable_component(nid, f"{side.upper()}{i}", 1000 + 50 * i, 1.5, 2.0))
            else:
                nodes.append(_component(nid, f"{side.upper()}{i}", "weibull", [("alpha", 1000 + 50 * i), ("beta", 1.5)]))
            cur.append(nid)
        edges += [_edge(p, c) for p in prev for c in cur]
        prev = cur
    edges += [_edge(p, "output") for p in prev]
    return {"nodes": nodes, "edges": edges, "unit": "Hours", "repairable": repairable}


def _bridge():
    """The classic bridge: not series-parallel, so cut sets are non-trivial."""
    nodes = _io_nodes() + [
        _component(n, n.upper(), "weibull", [("alpha", a), ("beta", 1.2)])
        for n, a in (("a", 900), ("b", 1100), ("c", 1300), ("d", 800), ("e", 1000))
    ]
    edges = [_edge("input", "a"), _edge("input", "b"), _edge("a", "c"), _edge("b", "d"),
             _edge("a", "e"), _edge("e", "d"), _edge("c", "output"), _edge("d", "output")]
    return {"nodes": nodes, "edges": edges, "unit": "Hours"}


def _chains(n_chains, length):
    """n_chains series chains in parallel: length^n_chains minimal cut sets."""
    nodes, edges = _io_nodes(), []
    for c in range(n_chains):
        prev = "input"
        for i in range(length):
            nid = f"c{c}_{i}"
            nodes.append(_component(nid, f"C{c}.{i}", "weibull", [("alpha", 1000 + i), ("beta", 1.5)]))
            edges.append(_edge(prev, nid))
            prev = nid
        edges.append(_edge(prev, "output"))
    return {"nodes": nodes, "edges": edges, "unit": "Hours"}


def _voting():
    """A 2-of-3 vote in series with a bridge-free pair: exercises k-of-n."""
    nodes = _io_nodes() + [
        _component(n, n.upper(), "weibull", [("alpha", 900 + 50 * i), ("beta", 1.4)])
        for i, n in enumerate(("a", "b", "c", "d", "e"))
    ] + [{"id": "v", "type": "knode", "data": {"label": "2oo3", "n": 2, "k": 3}}]
    edges = [_edge("input", x) for x in "abc"] + [_edge(x, "v") for x in "abc"] + [
        _edge("v", "d"), _edge("v", "e"), _edge("d", "output"), _edge("e", "output")]
    return {"nodes": nodes, "edges": edges, "unit": "Hours"}


@pytest.mark.parametrize("graph", [_bridge(), _stages(4), _chains(3, 3), _voting()],
                         ids=["bridge", "stages", "chains", "voting"])
def test_set_counts_match_enumeration(graph):
    rbd = ra._build_rbd(graph, None, None, None, None)[0]
    n_paths, n_cuts = ra._set_counts(rbd)
    assert n_paths == len(rbd.get_min_path_sets(include_in_out_nodes=False))
    assert n_cuts == len(rbd.get_min_cut_sets(include_in_out_nodes=False))


@pytest.mark.parametrize("graph", [_bridge(), _stages(5), _chains(2, 4), _voting()],
                         ids=["bridge", "stages", "chains", "voting"])
def test_low_order_cut_sets_match_the_full_derivation(graph):
    rbd = ra._build_rbd(graph, None, None, None, None)[0]
    full = {c for c in rbd.get_min_cut_sets(include_in_out_nodes=False) if len(c) <= 3}
    assert set(ra._low_order_cut_sets(rbd, 3)) == full


def test_importance_is_repyabilitys_with_failure_oriented_criticality():
    """The calculator's measures are RePyability's own; criticality is the
    failure-oriented form, so blocks in series are ranked (the success form
    was exactly 1 for each of them)."""
    graph = _bridge()
    res = ra.analyze(graph)
    imp, t = res["importance"], res["importance"]["time"]
    rbd = ra._build_rbd(graph, None, None, None, None)[0]
    probs = {n: rbd.reliabilities[n].sf(np.array([t])) for n in rbd.nodes}
    for key, want in (
        ("birnbaum", rbd._birnbaum_importance(probs)),
        ("criticality", rbd._criticality_importance(probs, kind="failure")),
        ("fussell_vesely", rbd._fussell_vesely(probs, fv_type="c")),
        ("risk_achievement_worth", rbd._risk_achievement_worth(probs)),
    ):
        for n in "abcde":
            assert imp[key][n] == pytest.approx(float(np.atleast_1d(want[n])[0]), rel=1e-12), (key, n)
    series = ra.analyze(_stages(1) | {"nodes": _io_nodes() + [
        _component("p", "P", "weibull", [("alpha", 500), ("beta", 2)]),
        _component("q", "Q", "weibull", [("alpha", 5000), ("beta", 2)])],
        "edges": [_edge("input", "p"), _edge("p", "q"), _edge("q", "output")]})["importance"]
    assert series["criticality"]["p"] > series["criticality"]["q"]


def test_small_diagram_keeps_complete_cut_sets():
    st = ra.analyze(_bridge())["structure"]
    assert st["cut_sets_complete"] is True and st["n_min_path_sets"] == 3  # a-c, b-d, a-e-d
    assert st["n_min_cut_sets"] == len(st["min_cut_sets"])
    assert "cut_sets_max_order" not in st


def test_thirty_redundant_stages_analyse_without_listing_a_billion_paths():
    res = ra.analyze(_stages(30))
    st = res["structure"]
    assert st["n_min_path_sets"] == 2 ** 30 and st["min_path_sets"] == []
    assert st["cut_sets_complete"] is True and st["n_min_cut_sets"] == 30
    assert res["mttf"] > 0 and res["importance"]["birnbaum"]


def test_millions_of_cut_sets_fall_back_to_the_lowest_order():
    """4 chains of 12 in parallel: 12^4 = 20,736 minimal cut sets, all of order
    4 — none of order <= 3, so the listing is empty and says why."""
    res = ra.analyze(_chains(4, 12))
    st = res["structure"]
    assert st["n_min_cut_sets"] == 12 ** 4 and st["cut_sets_complete"] is False
    assert st["min_cut_sets"] == [] and st["cut_sets_max_order"] == 3
    assert res["importance"]["fussell_vesely_basis"] == "cut sets of up to 3 blocks"
    assert st["n_min_path_sets"] == 4 and len(st["min_path_sets"]) == 4


def test_listing_limit_is_configurable(monkeypatch):
    monkeypatch.setattr(ra, "_MAX_ENUMERATED_SETS", 3)
    st = ra.analyze(_stages(4))["structure"]  # 16 path sets, 4 cut sets
    assert st["n_min_path_sets"] == 16 and st["min_path_sets"] == []
    assert st["cut_sets_complete"] is False
    assert sorted(map(sorted, st["min_cut_sets"])) == sorted(sorted([f"A{i}", f"B{i}"]) for i in range(4))


def test_horizon_ignores_a_rarely_failing_exponential_block():
    """An exponential block's availability settles on its *repair* timescale,
    however rare its failures: MTTF 1e6 h mustn't set a 1e7 h horizon."""
    wear = _repairable_component("pump", "Pump", 1000, 2.0, 2.0)
    tank = _component("tank", "Tank", "exponential", [("failure_rate", 1e-6)])
    tank["data"]["repair"] = {"source": "params", "distribution_id": "lognormal",
                              "params": [{"name": "mu", "value": 3.0}, {"name": "sigma", "value": 0.4}]}
    graph = {"nodes": _io_nodes() + [wear, tank], "repairable": True, "unit": "Hours",
             "edges": [_edge("input", "pump"), _edge("pump", "tank"), _edge("tank", "output")]}
    pump_cycle = ra._spec_mean(wear["data"]["model"]) + ra._spec_mean(wear["data"]["repair"])
    assert ra._availability_horizon(graph) == pytest.approx(10 * pump_cycle)


def test_horizon_ignores_blocks_that_carry_no_downtime():
    """A redundant, very reliable block doesn't stretch the simulation."""
    series = _repairable_component("a", "A", 1000, 2.0, 2.0)
    backup1 = _repairable_component("b1", "B1", 90000, 2.0, 2.0)
    backup2 = _repairable_component("b2", "B2", 1000, 2.0, 2.0)
    graph = {"nodes": _io_nodes() + [series, backup1, backup2], "repairable": True, "unit": "Hours",
             "edges": [_edge("input", "a"), _edge("a", "b1"), _edge("a", "b2"),
                       _edge("b1", "output"), _edge("b2", "output")]}
    assert ra._availability_horizon(graph) < 20_000


def test_simulation_is_sized_to_the_time_budget(monkeypatch):
    monkeypatch.setattr(ra, "_AVAIL_SIMS", 200)
    monkeypatch.setattr(ra, "_AVAIL_MIN_SIMS", 30)
    monkeypatch.setattr(ra, "_AVAIL_TIME_BUDGET", 1e-9)  # nothing fits
    graph = _stages(2, repairable=True)
    default = ra.analyze_availability(graph)
    assert default["n_simulations"] == 30 and default["horizon_shortened"] is True
    assert default["t_simulation"] < ra._availability_horizon(graph)
    # A horizon the user chose is kept; only the replication count gives way.
    chosen = ra.analyze_availability(graph, t_simulation=5000.0)
    assert chosen["t_simulation"] == 5000.0 and chosen["horizon_shortened"] is False
    assert chosen["n_simulations"] == 30
    # An explicit replication count is honoured as given.
    fixed = ra.analyze_availability(graph, n_simulations=25)
    assert fixed["n_simulations"] == 25 and fixed["horizon_shortened"] is False


def test_generous_budget_runs_the_full_count(monkeypatch):
    monkeypatch.setattr(ra, "_AVAIL_SIMS", 60)
    res = ra.analyze_availability(_stages(2, repairable=True))
    assert res["n_simulations"] == 60 and res["horizon_shortened"] is False


def _standby_graph(**extra):
    unit = {"source": "params", "distribution_id": "exponential",
            "params": [{"name": "failure_rate", "value": 1e-3}]}
    node = {"id": "sb", "type": "standby", "data": {"label": "Pumps", "model": unit, "spares": 1, **extra}}
    return {"nodes": _io_nodes() + [node], "unit": "Hours",
            "edges": [_edge("input", "sb"), _edge("sb", "output")]}


def test_warm_standby_sits_between_cold_and_hot():
    t = 1500.0
    r = {name: ra.analyze(_standby_graph(**kw), t_max=3000.0) for name, kw in (
        ("cold", {"cold": True}), ("warm", {"dormancy": 0.4}), ("hot", {"cold": False}))}
    at = {k: np.interp(t, v["time"], v["system"]["sf"]) for k, v in r.items()}
    assert at["hot"] < at["warm"] < at["cold"]
    # Exact: rates (1 + 0.4)·λ then λ (hypoexponential).
    lam, a = 1e-3, 1.4e-3
    exact = (a * np.exp(-lam * t) - lam * np.exp(-a * t)) / (a - lam)
    assert at["warm"] == pytest.approx(exact, rel=1e-4)
    # dormancy overrides the legacy flag; 0 and 1 are exactly cold and hot.
    assert ra.analyze(_standby_graph(cold=False, dormancy=0.0), t_max=3000.0)["system"]["sf"] == r["cold"]["system"]["sf"]
    assert ra.analyze(_standby_graph(cold=True, dormancy=1.0), t_max=3000.0)["system"]["sf"] == r["hot"]["system"]["sf"]


@pytest.mark.parametrize("bad", [-0.1, 1.5, "warm"])
def test_invalid_dormancy_is_a_clear_error(bad):
    with pytest.raises(AnalysisError, match="dormancy factor"):
        ra.analyze(_standby_graph(dormancy=bad))


def test_warm_standby_exports_with_its_dormancy_factor():
    from backend.services import rbd_export

    code = rbd_export.to_python(_standby_graph(dormancy=0.4), "Warm pumps")
    assert "StandbyModel([pumps_unit, pumps_unit], k=1, dormancy_factor=0.4)" in code
    assert "warm standby" in code
