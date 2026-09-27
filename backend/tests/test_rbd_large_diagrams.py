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


@pytest.mark.parametrize("graph", [_bridge(), _stages(4)], ids=["bridge", "stages"])
def test_importance_measures_identical_to_repyability(graph):
    rbd = ra._build_rbd(graph, None, None, None, None)[0]
    probs = {n: np.array([1.0 if n in ("input", "output") else 0.8]) for n in rbd.nodes}
    cuts = list(rbd.get_min_cut_sets(include_in_out_nodes=False))
    new = ra._importance_measures(rbd, probs, cuts)
    with np.errstate(all="ignore"):
        old = {
            "birnbaum": rbd._birnbaum_importance(probs),
            "fussell_vesely": rbd._fussell_vesely(probs, fv_type="c"),
            "risk_achievement_worth": rbd._risk_achievement_worth(probs),
            "risk_reduction_worth": rbd._risk_reduction_worth(probs),
            "criticality": rbd._criticality_importance(probs),
            "improvement_potential": rbd._improvement_potential(probs),
        }
    for key, vals in old.items():
        for n in rbd.nodes:
            a, b = float(np.atleast_1d(vals[n])[0]), float(new[key][n])
            assert (a == b) or (np.isnan(a) and np.isnan(b)), (key, n, a, b)


@pytest.mark.parametrize("graph", [_bridge(), _stages(5)], ids=["bridge", "stages"])
def test_low_order_cut_sets_match_the_full_derivation(graph):
    rbd = ra._build_rbd(graph, None, None, None, None)[0]
    paths = list(rbd.get_min_path_sets(include_in_out_nodes=False))
    full = {c for c in rbd.get_min_cut_sets(include_in_out_nodes=False) if len(c) <= 3}
    assert set(ra._low_order_cut_sets(paths, 3)) == full


def test_large_diagram_lists_lowest_order_cut_sets(monkeypatch):
    monkeypatch.setattr(ra, "_FULL_CUT_SETS_MAX_PATHS", 4)
    monkeypatch.setattr(ra, "_LISTED_PATH_SETS", 5)
    res = ra.analyze(_stages(4))  # 16 path sets
    st = res["structure"]
    assert st["n_min_path_sets"] == 16 and len(st["min_path_sets"]) == 5
    assert st["cut_sets_complete"] is False and st["cut_sets_max_order"] == 3
    assert sorted(map(sorted, st["min_cut_sets"])) == sorted(
        sorted([f"A{i}", f"B{i}"]) for i in range(4))
    assert res["importance"]["fussell_vesely_basis"] == "cut sets of up to 3 blocks"


def test_small_diagram_keeps_complete_cut_sets():
    st = ra.analyze(_bridge())["structure"]
    assert st["cut_sets_complete"] is True and st["n_min_path_sets"] == 3  # a-c, b-d, a-e-d
    assert "cut_sets_max_order" not in st


def test_too_many_paths_is_refused_with_advice(monkeypatch):
    monkeypatch.setattr(ra, "_MAX_PATH_SETS", 8)
    with pytest.raises(AnalysisError, match="16 distinct success paths.*sub-system block"):
        ra.analyze(_stages(4))


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
