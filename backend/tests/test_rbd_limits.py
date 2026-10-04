"""Diagram size and block unit counts are bounded wherever a diagram is
written or analysed, and chosen simulation windows are bounded."""

import copy
import time

import mongomock
import pytest

from backend.services import rbd_analysis as ra
from backend.services import rbd_edit
from backend.services import rbd_graph
from backend.services.rbd_graph import GraphError
from backend.tests.test_rbd_analysis import _component, _edge, _io_nodes, _repairable_component


def _timed(fn, *args, **kwargs):
    start = time.perf_counter()
    try:
        out = fn(*args, **kwargs)
    except Exception as exc:  # noqa: BLE001 - the caller checks which
        out = exc
    return out, time.perf_counter() - start


_EXP = {"distribution_id": "exponential", "params": [{"name": "failure_rate", "value": 1e-3}]}


def _compact(block: dict) -> dict:
    return {
        "nodes": [{"id": "input", "type": "input"}, {"id": "a", **block}, {"id": "output", "type": "output"}],
        "edges": [{"source": "input", "target": "a"}, {"source": "a", "target": "output"}],
    }


@pytest.mark.parametrize("block, match", [
    ({"type": "parallel", "n": 10 ** 9, "model": _EXP}, "from 1 to 1,000"),
    ({"type": "series", "n": 0, "model": _EXP}, "from 1 to 1,000"),
    ({"type": "series", "n": 2.5, "model": _EXP}, "whole number"),
    ({"type": "series", "n": "lots", "model": _EXP}, "whole number"),
    ({"type": "standby", "spares": 10 ** 6, "model": _EXP}, "number of spares"),
    ({"type": "knode", "n": 2, "k": 10 ** 9}, "from 1 to 5,000"),
    ({"type": "knode", "n": 10 ** 9}, "from 1 to 5,000"),
])
def test_normalize_graph_bounds_unit_counts(block, match):
    with pytest.raises(GraphError, match=match):
        rbd_graph.normalize_graph(_compact(block))


def test_normalize_graph_accepts_counts_within_bounds():
    out = rbd_graph.normalize_graph(_compact({"type": "parallel", "n": 1000, "model": _EXP}))
    assert out["nodes"][1]["data"]["n"] == 1000


def test_normalize_graph_bounds_the_number_of_blocks():
    nodes = [{"id": f"b{i}", "type": "component", "model": _EXP} for i in range(rbd_graph.MAX_BLOCKS + 1)]
    with pytest.raises(GraphError, match="at most 5,000"):
        rbd_graph.normalize_graph({"nodes": nodes, "edges": []})


def test_normalize_graph_bounds_the_number_of_connections():
    edges = [{"source": "input", "target": "output"}] * (rbd_graph.MAX_EDGES + 1)
    with pytest.raises(GraphError, match="connections"):
        rbd_graph.normalize_graph({"nodes": [{"id": "input", "type": "input"}, {"id": "output", "type": "output"}],
                                   "edges": edges})


def test_edit_ops_bound_unit_counts():
    graph = rbd_graph.normalize_graph(_compact({"type": "parallel", "n": 2, "model": _EXP}))
    with pytest.raises(rbd_edit.EditError, match="from 1 to 1,000"):
        rbd_edit.apply_ops(graph, [{"op": "update_node", "id": "a", "n": 10 ** 9}], "D")
    knode = rbd_graph.normalize_graph(_compact({"type": "knode", "n": 1, "k": 2}))
    with pytest.raises(rbd_edit.EditError, match="from 1 to 5,000"):
        rbd_edit.apply_ops(knode, [{"op": "update_node", "id": "a", "k": 10 ** 9}], "D")


def test_load_sharing_group_needs_k_within_its_units():
    graph = {"nodes": _io_nodes() + [{"id": "a", "type": "loadshare",
                                      "data": {"label": "A", "units": 3, "k": 4}}],
             "edges": [_edge("input", "a"), _edge("a", "output")]}
    with pytest.raises(GraphError, match=r"k \(4\) can't exceed the number of units \(3\)"):
        rbd_graph.check_limits(graph)
    graph["nodes"][2]["data"].update(units=10 ** 9, k=1)
    with pytest.raises(GraphError, match="from 1 to 1,000"):
        rbd_graph.check_limits(graph)


def test_vote_node_requiring_more_than_its_branches_is_explained():
    from backend.services import rbds as rbds_service

    graph = rbd_graph.normalize_graph({
        "nodes": [{"id": "input", "type": "input"}, {"id": "a", "type": "component", "model": _EXP},
                  {"id": "b", "type": "component", "model": _EXP},
                  {"id": "v", "type": "knode", "n": 3, "k": 2}, {"id": "output", "type": "output"}],
        "edges": [{"source": "input", "target": "a"}, {"source": "input", "target": "b"},
                  {"source": "a", "target": "v"}, {"source": "b", "target": "v"},
                  {"source": "v", "target": "output"}]})
    check = rbds_service.validate_graph(mongomock.MongoClient()["limits"], graph, "u1")
    assert not check["valid"]
    assert any("requires 3 working inputs but only 2 branches" in e for e in check["errors"])


def test_saving_a_diagram_checks_its_limits():
    from backend.services import rbds as rbds_service

    db = mongomock.MongoClient()["limits"]
    graph = {"nodes": _io_nodes() + [{"id": "a", "type": "parallel", "data": {"label": "A", "n": 10 ** 9}}],
             "edges": [_edge("input", "a"), _edge("a", "output")]}
    with pytest.raises(GraphError):
        rbds_service.save_rbd(db, "D", graph, "u1")
    assert db.rbds.count_documents({}) == 0


def test_analysis_refuses_unit_counts_over_the_limit_before_building():
    node = _component("a", "A", "weibull", [("alpha", 1000), ("beta", 1.5)])
    node["type"] = "parallel"
    node["data"]["n"] = 10 ** 9
    graph = {"nodes": _io_nodes() + [node], "edges": [_edge("input", "a"), _edge("a", "output")]}
    out, seconds = _timed(ra.analyze, graph)
    assert isinstance(out, ra.AnalysisError), out
    assert "from 1 to 1,000" in str(out)
    assert seconds < 1.0


def _repairable_series():
    return {
        "unit": "hours", "repairable": True,
        "nodes": _io_nodes() + [_repairable_component("a", "A", 1000, 1.5, 2.0),
                                _repairable_component("b", "B", 1200, 1.5, 2.0)],
        "edges": [_edge("input", "a"), _edge("a", "b"), _edge("b", "output")],
    }


@pytest.mark.parametrize("value", [None, 0, -5, float("nan"), float("inf"), "x"])
def test_chosen_horizon_ignores_values_that_are_not_a_positive_time(value):
    assert ra.chosen_horizon(value, _repairable_series()) == (None, False)


def test_chosen_horizon_is_capped_relative_to_the_diagram():
    graph = _repairable_series()
    reference = max(ra._availability_horizon(graph), ra._life_scale(graph))
    assert ra.chosen_horizon(5000.0, graph) == (5000.0, False)
    t, capped = ra.chosen_horizon(1e300, graph)
    assert capped and t == pytest.approx(ra._AVAIL_MAX_HORIZON_FACTOR * reference)


def test_availability_with_a_huge_window_is_bounded(monkeypatch):
    monkeypatch.setattr(ra, "_AVAIL_SIMS", 40)
    graph = _repairable_series()
    out, seconds = _timed(ra.analyze_availability, graph, t_simulation=1e300)
    assert not isinstance(out, Exception), out
    assert out["horizon_shortened"] is True
    assert out["t_simulation"] <= ra._AVAIL_MAX_HORIZON_FACTOR * max(
        ra._availability_horizon(graph), ra._life_scale(graph)) * (1 + 1e-9)
    assert seconds < 60


def test_a_chosen_window_far_over_budget_is_shortened(monkeypatch):
    monkeypatch.setattr(ra, "_AVAIL_TIME_BUDGET", 10.0)
    # Within the limit the chosen window stands; beyond, it is shortened to fit.
    assert ra._plan_simulation(1.0, 20_000, 50.0, True) == (100, 100, 50.0, False)
    batch, max_n, t, short = ra._plan_simulation(4.0, 20_000, 50.0, True)
    assert (batch, max_n, short) == (100, 100, True)
    assert t == pytest.approx(50.0 * ra._AVAIL_USER_TIME_LIMIT / 400)


def test_comparison_window_is_bounded():
    from backend.services import rbd_compare

    a = _repairable_series()
    b = copy.deepcopy(a)
    b["nodes"][2]["data"]["model"]["params"][0]["value"] = 1500
    out = rbd_compare.compare_availability(a, b, t_simulation=1e300, n_simulations=4)
    assert out["horizon_shortened"] is True
    assert out["t_simulation"] < 1e12



def test_standby_spares_zero_from_older_diagrams_still_reads_as_one():
    from backend.services import rbd_graph

    rbd_graph.check_counts("standby", {"spares": 0}, "Standby")  # accepted
    import pytest as _pytest
    with _pytest.raises(rbd_graph.GraphError):
        rbd_graph.check_counts("standby", {"spares": -1}, "Standby")
