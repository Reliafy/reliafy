"""Tests for the RePyability-backed RBD analysis."""

import numpy as np
import pytest

from backend.services import rbd_analysis as ra
from backend.services.rbd_analysis import AnalysisError, analyze, validate_graph


def _component(node_id, label, dist_id, params):
    return {
        "id": node_id,
        "type": "component",
        "data": {
            "label": label,
            "model": {
                "source": "params",
                "distribution_id": dist_id,
                "distribution": dist_id.title(),
                "params": [{"name": n, "value": v} for n, v in params],
            },
        },
    }


def _io_nodes():
    return [
        {"id": "input", "type": "input", "data": {"label": "Input"}},
        {"id": "output", "type": "output", "data": {"label": "Output"}},
    ]


def _edge(src, tgt):
    return {"id": f"{src}-{tgt}", "source": src, "target": tgt}


def test_series_system_is_product_of_components():
    graph = {
        "unit": "Hours",
        "nodes": _io_nodes()
        + [
            _component("c1", "Pump", "weibull", [("alpha", 100), ("beta", 2)]),
            _component("c2", "Valve", "exponential", [("failure_rate", 0.01)]),
        ],
        "edges": [_edge("input", "c1"), _edge("c1", "c2"), _edge("c2", "output")],
    }
    result = analyze(graph)

    assert result["unit"] == "Hours"
    assert len(result["system"]["sf"]) == len(result["time"])

    # The system reliability of a series system is the product of the two
    # component reliabilities at every time.
    from surpyval import Exponential, Weibull

    t = np.asarray(result["time"])
    expected = Weibull.from_params([100, 2]).sf(t) * Exponential.from_params([0.01]).sf(
        t
    )
    got = np.asarray([v for v in result["system"]["sf"]], dtype=float)
    assert np.allclose(got, expected, atol=1e-9)

    # Two components, both reported; min path set is the pair.
    assert {n["id"] for n in result["nodes"]} == {"c1", "c2"}
    assert result["structure"]["min_path_sets"] == [["Pump", "Valve"]]
    assert result["mttf"] is not None and result["mttf"] > 0


def test_parallel_more_reliable_than_either_component():
    graph = {
        "nodes": _io_nodes()
        + [
            _component("c1", "A", "weibull", [("alpha", 50), ("beta", 1.5)]),
            _component("c2", "B", "weibull", [("alpha", 50), ("beta", 1.5)]),
        ],
        "edges": [
            _edge("input", "c1"),
            _edge("input", "c2"),
            _edge("c1", "output"),
            _edge("c2", "output"),
        ],
    }
    result = analyze(graph)

    from surpyval import Weibull

    t = np.asarray(result["time"])
    comp = Weibull.from_params([50, 1.5]).sf(t)
    got = np.asarray(result["system"]["sf"], dtype=float)
    # Parallel redundancy: system reliability >= each component (strictly
    # greater wherever the component can fail).
    assert np.all(got >= comp - 1e-12)
    assert got[t > 0][0] > comp[t > 0][0]

    # Two single-component minimal path sets in parallel.
    paths = result["structure"]["min_path_sets"]
    assert sorted(paths) == [["A"], ["B"]]


def test_knode_two_out_of_three_requires_two_branches():
    # Three parallel components feed a 2-out-of-3 voting node.
    comps = [
        _component(f"c{i}", f"C{i}", "exponential", [("failure_rate", 0.1)])
        for i in (1, 2, 3)
    ]
    graph = {
        "nodes": _io_nodes()
        + comps
        + [{"id": "v", "type": "knode", "data": {"label": "Vote", "n": 2, "k": 3}}],
        "edges": [
            _edge("input", "c1"),
            _edge("input", "c2"),
            _edge("input", "c3"),
            _edge("c1", "v"),
            _edge("c2", "v"),
            _edge("c3", "v"),
            _edge("v", "output"),
        ],
    }
    result = analyze(graph)

    # Each minimal path set is a pair of components (any 2 of the 3) plus the
    # voting node.
    paths = result["structure"]["min_path_sets"]
    assert all(len(p) == 3 and "Vote" in p for p in paths)
    assert len(paths) == 3  # C(3,2)

    # The voting gate is structural, so it isn't reported as a node curve.
    assert "v" not in {n["id"] for n in result["nodes"]}


def test_count_block_matches_explicit_parallel():
    # A parallel block with count 3 should equal three explicit components.
    block_graph = {
        "nodes": _io_nodes()
        + [
            {
                "id": "p",
                "type": "parallel",
                "data": {
                    "label": "Trio",
                    "n": 3,
                    "model": {
                        "distribution_id": "exponential",
                        "params": [{"name": "failure_rate", "value": 0.05}],
                    },
                },
            }
        ],
        "edges": [_edge("input", "p"), _edge("p", "output")],
    }
    result = analyze(block_graph)

    from surpyval import Exponential

    t = np.asarray(result["time"])
    one = Exponential.from_params([0.05]).sf(t)
    expected = 1 - (1 - one) ** 3
    got = np.asarray(result["system"]["sf"], dtype=float)
    assert np.allclose(got, expected, atol=1e-9)


def test_missing_life_model_is_a_clear_error():
    graph = {
        "nodes": _io_nodes()
        + [
            {"id": "c1", "type": "component", "data": {"label": "Empty", "model": None}}
        ],
        "edges": [_edge("input", "c1"), _edge("c1", "output")],
    }
    with pytest.raises(AnalysisError) as exc:
        analyze(graph)
    assert "life model" in str(exc.value)


def test_no_edges_is_a_clear_error():
    graph = {"nodes": _io_nodes(), "edges": []}
    with pytest.raises(AnalysisError):
        analyze(graph)


def test_cold_standby_uses_repyability_standby_model():
    graph = {
        "nodes": _io_nodes()
        + [
            {
                "id": "sb",
                "type": "standby",
                "data": {
                    "label": "Standby",
                    "cold": True,
                    "spares": 1,
                    "startProb": 1.0,
                    "model": {
                        "distribution_id": "exponential",
                        "params": [{"name": "failure_rate", "value": 0.01}],
                    },
                },
            }
        ],
        "edges": [_edge("input", "sb"), _edge("sb", "output")],
    }
    result = analyze(graph)

    from repyability.rbd.standby_node import StandbyModel
    from surpyval import Exponential

    sb = StandbyModel([Exponential.from_params([0.01])] * 2, k=1)
    t = np.asarray(result["time"])
    assert np.allclose(result["system"]["sf"], sb.sf(t), atol=1e-9)
    # Two cold-standby units of rate 0.01 -> MTTF = 2 / 0.01 = 200.
    assert result["mttf"] == pytest.approx(200.0, rel=1e-3)


def test_subsystem_resolved_via_callback():
    # A top-level diagram with one sub-system node that points at a saved RBD.
    sub_graph = {
        "nodes": _io_nodes()
        + [_component("c1", "Inner", "weibull", [("alpha", 80), ("beta", 2)])],
        "edges": [_edge("input", "c1"), _edge("c1", "output")],
    }
    top = {
        "nodes": _io_nodes()
        + [
            {
                "id": "ss",
                "type": "subsystem",
                "data": {"label": "Block", "rbd": {"id": "SUB", "name": "Sub"}},
            }
        ],
        "edges": [_edge("input", "ss"), _edge("ss", "output")],
    }

    result = analyze(top, resolve_subsystem=lambda i: sub_graph if i == "SUB" else None)

    from surpyval import Weibull

    t = np.asarray(result["time"])
    expected = Weibull.from_params([80, 2]).sf(t)
    got = np.asarray(result["system"]["sf"], dtype=float)
    assert np.allclose(got, expected, atol=1e-9)


# --- validation / analytic-solvability gate ---------------------------------


def test_validate_accepts_valid_analytic_rbd():
    graph = {
        "nodes": _io_nodes()
        + [
            _component("c1", "Pump", "weibull", [("alpha", 100), ("beta", 2)]),
            _component("c2", "Valve", "exponential", [("failure_rate", 0.01)]),
        ],
        "edges": [_edge("input", "c1"), _edge("c1", "c2"), _edge("c2", "output")],
    }
    v = validate_graph(graph)
    assert v["valid"] and v["analytic"] and v["can_calculate"]
    assert v["errors"] == []


def test_validate_flags_missing_life_model():
    graph = {
        "nodes": _io_nodes()
        + [
            {"id": "c1", "type": "component", "data": {"label": "Empty", "model": None}}
        ],
        "edges": [_edge("input", "c1"), _edge("c1", "output")],
    }
    v = validate_graph(graph)
    assert not v["valid"] and not v["can_calculate"]
    assert any("life model" in e for e in v["errors"])


def test_validate_flags_dangling_node():
    graph = {
        "nodes": _io_nodes()
        + [
            _component("c1", "A", "weibull", [("alpha", 10), ("beta", 1)]),
            _component("c2", "B", "weibull", [("alpha", 10), ("beta", 1)]),
        ],
        # c2 is fed from input but never reaches output.
        "edges": [_edge("input", "c1"), _edge("c1", "output"), _edge("input", "c2")],
    }
    v = validate_graph(graph)
    assert not v["valid"]
    assert any("B" in e for e in v["errors"])


def test_validate_blocks_non_analytic_standby():
    graph = {
        "nodes": _io_nodes()
        + [
            {
                "id": "sb",
                "type": "standby",
                "data": {
                    "label": "Standby",
                    "cold": True,
                    "spares": 1,
                    "startProb": 1.0,
                    "model": {
                        "distribution_id": "exponential",
                        "params": [{"name": "failure_rate", "value": 0.01}],
                    },
                },
            }
        ],
        "edges": [_edge("input", "sb"), _edge("sb", "output")],
    }
    v = validate_graph(graph)
    # Structurally valid, but standby needs simulation -> not analytic.
    assert v["valid"] and not v["analytic"]
    assert not v["can_calculate"]
    assert v["non_analytic_nodes"] == {"Standby": "StandbyModel"}


def test_validate_no_connections():
    v = validate_graph({"nodes": _io_nodes(), "edges": []})
    assert not v["valid"] and not v["can_calculate"]
    assert v["errors"]


# --- proportional-hazards (covariate) nodes ---------------------------------


def _ph_fitted_model():
    """Fit a small Weibull PH model on (time, age) for use as a node model."""
    import pandas as pd
    from surpyval import Weibull, WeibullPH

    rng = np.random.default_rng(0)
    n = 200
    age = rng.normal(50, 10, n)
    x = Weibull.random(n, 10, 2.0) * np.exp(-(0.05 * (age - 50)) / 2)
    model = WeibullPH.fit_from_df(
        pd.DataFrame({"t": x, "age": age}), x_col="t", Z_cols=["age"]
    )
    fields = [{"name": "age", "type": "number", "default": 50.0}]
    return {"model": model, "fields": fields, "grid": np.linspace(0, 30, 50)}


def _ph_node(node_id, label, model_id="M"):
    return {
        "id": node_id,
        "type": "component",
        "data": {
            "label": label,
            "model": {
                "source": "saved",
                "kind": "regression",
                "modelId": model_id,
                "name": "Weibull PH",
                "distribution": "Weibull PH",
                "distribution_id": "weibull_ph",
                "covariates": [{"name": "age", "type": "number", "default": 50.0}],
            },
        },
    }


def test_ph_node_is_valid_and_analytic():
    graph = {
        "nodes": _io_nodes() + [_ph_node("c1", "Engine")],
        "edges": [_edge("input", "c1"), _edge("c1", "output")],
    }
    # No resolve_model needed for validation: a PH node is analytically solvable.
    v = validate_graph(graph)
    assert v["valid"] and v["analytic"] and v["can_calculate"]


def test_ph_node_covariates_change_system_reliability():
    entry = _ph_fitted_model()
    graph = {
        "unit": "Hours",
        "nodes": _io_nodes() + [_ph_node("c1", "Engine")],
        "edges": [_edge("input", "c1"), _edge("c1", "output")],
    }
    resolve = lambda mid: entry if mid == "M" else None  # noqa: E731

    young = analyze(
        graph, t_max=30, covariates={"c1": {"age": 30}}, resolve_model=resolve
    )
    old = analyze(
        graph, t_max=30, covariates={"c1": {"age": 70}}, resolve_model=resolve
    )

    mid = len(young["time"]) // 2
    # Younger age -> lower hazard -> more reliable system.
    assert young["system"]["sf"][mid] > old["system"]["sf"][mid]
    assert young["mttf"] > old["mttf"]


def test_ph_node_without_selection_is_invalid():
    node = _ph_node("c1", "Engine")
    node["data"]["model"].pop("modelId")
    graph = {
        "nodes": _io_nodes() + [node],
        "edges": [_edge("input", "c1"), _edge("c1", "output")],
    }
    v = validate_graph(graph)
    assert not v["valid"]
    assert any("proportional-hazards model" in e for e in v["errors"])


def test_conditional_survival_matches_ratio():
    from surpyval import Weibull

    graph = {
        "unit": "Hours",
        "nodes": _io_nodes()
        + [_component("c1", "Pump", "weibull", [("alpha", 100), ("beta", 2)])],
        "edges": [_edge("input", "c1"), _edge("c1", "output")],
    }
    s = 50.0
    res = analyze(graph, t_max=100, conditional_age=s)
    W = Weibull.from_params([100, 2])
    t = np.asarray(res["time"])
    expected = W.sf(t + s) / W.sf(s)
    got = np.asarray(res["system"]["sf"], dtype=float)
    assert np.allclose(got, expected, atol=1e-6)
    assert got[0] == pytest.approx(1.0)  # R(0 | s) = 1
    assert res["conditional_age"] == s
    # Mean residual life at s is shorter than the unconditional MTTF here.
    assert res["mttf"] < analyze(graph, t_max=100)["mttf"]


def test_pinned_working_and_failed_override_the_model():
    """A node pinned working/failed (manual what-if) contributes as perfectly
    reliable / unreliable regardless of its life model."""
    import json

    io = _io_nodes()

    def pinned(comp, state):
        return {**comp, "data": {**comp["data"], "state": state}}

    c1 = _component("c1", "Pump", "weibull", [("alpha", 100), ("beta", 2)])
    c2 = _component("c2", "Valve", "exponential", [("failure_rate", 0.01)])

    # Series with c2 pinned failed -> the system is always failed.
    g = {
        "unit": "Hours",
        "nodes": io + [c1, pinned(c2, "failed")],
        "edges": [_edge("input", "c1"), _edge("c1", "c2"), _edge("c2", "output")],
    }
    r = analyze(g)
    json.dumps(r, allow_nan=False)  # forced 0/1 must not leak NaN/inf
    assert max(r["system"]["sf"]) == pytest.approx(0.0, abs=1e-9)

    # Parallel with c2 pinned working -> the system is always working.
    g2 = {
        "unit": "Hours",
        "nodes": io + [c1, pinned(c2, "working")],
        "edges": [
            _edge("input", "c1"), _edge("input", "c2"),
            _edge("c1", "output"), _edge("c2", "output"),
        ],
    }
    r2 = analyze(g2)
    assert min(r2["system"]["sf"]) == pytest.approx(1.0, abs=1e-9)

    # A pinned node needs no life model of its own.
    nomodel = {"id": "c3", "type": "component", "data": {"label": "spare", "state": "working"}}
    g3 = {
        "unit": "Hours",
        "nodes": io + [nomodel],
        "edges": [_edge("input", "c3"), _edge("c3", "output")],
    }
    r3 = analyze(g3)
    assert min(r3["system"]["sf"]) == pytest.approx(1.0, abs=1e-9)
