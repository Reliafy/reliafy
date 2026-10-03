"""Repeated blocks (#102): one component drawn in several places.

A node with ``data.repeat_of`` is a linked copy of a component. It is passed
to RePyability as a repeated node, so every appearance is the one component —
in the exact reliability, the path/cut sets, the importance measures and the
Python export — and results are reported once per component.
"""

import numpy as np
import pytest

from backend.services import rbd_analysis as ra
from backend.services import rbd_export
from backend.services.rbd_graph import GraphError, compact_graph, normalize_graph
from backend.services.rbd_repeats import find_repeats
from backend.tests.test_rbd_export import WHEN, _io, _node, _run


def _exp(rate):
    return {"source": "params", "distribution": "Exponential", "distribution_id": "exponential",
            "params": [{"name": "failure_rate", "value": rate}]}


LAM = {"a": 2e-3, "b": 3e-3, "psu": 5e-4}


def _shared_psu(**psu2):
    """Two trains, each Pump -> power supply; one supply feeds both, so it is
    drawn twice (``psu2`` repeats ``psu``)."""
    return {
        "unit": "hours",
        "nodes": [*_io(),
                  _node("a", "component", "Pump A", model=_exp(LAM["a"])),
                  _node("b", "component", "Pump B", model=_exp(LAM["b"])),
                  _node("psu", "component", "Power supply", model=_exp(LAM["psu"])),
                  _node("psu2", "component", "Power supply", repeat_of="psu", **psu2)],
        "edges": [{"source": "input", "target": "a"}, {"source": "a", "target": "psu"},
                  {"source": "psu", "target": "output"}, {"source": "input", "target": "b"},
                  {"source": "b", "target": "psu2"}, {"source": "psu2", "target": "output"}],
    }


def _exact(t):
    r = {k: np.exp(-v * np.asarray(t)) for k, v in LAM.items()}
    return r["psu"] * (1 - (1 - r["a"]) * (1 - r["b"]))


def test_repeated_block_is_one_component_exactly():
    graph = _shared_psu()
    res = ra.analyze(graph, t_max=1000.0)
    assert np.allclose(res["system"]["sf"], _exact(res["time"]), rtol=1e-12, atol=1e-15)
    # Not the answer of two independent supplies.
    independent = ra.analyze({**graph, "nodes": [
        n if n["id"] != "psu2" else _node("psu2", "component", "PSU 2", model=_exp(LAM["psu"]))
        for n in graph["nodes"]]}, t_max=1000.0)
    assert independent["system"]["sf"][100] > res["system"]["sf"][100] + 1e-3


def test_results_are_reported_once_per_component():
    res = ra.analyze(_shared_psu())
    assert sorted(n["id"] for n in res["nodes"]) == ["a", "b", "psu"]
    for key in ("birnbaum", "fussell_vesely", "criticality", "risk_achievement_worth",
                "risk_reduction_worth", "improvement_potential"):
        assert set(res["importance"][key]) == {"a", "b", "psu"}, key
    # The shared supply is a single-point failure: a cut set of its own.
    assert ["Power supply"] in res["structure"]["min_cut_sets"]
    assert res["structure"]["n_min_cut_sets"] == 2
    assert sorted(res["structure"]["min_path_sets"]) == [["Power supply", "Pump A"],
                                                        ["Power supply", "Pump B"]]
    # Birnbaum of the supply: R(system | psu works) - R(system | psu failed).
    t = res["importance"]["time"]
    ra_, rb = np.exp(-LAM["a"] * t), np.exp(-LAM["b"] * t)
    assert res["importance"]["birnbaum"]["psu"] == pytest.approx(1 - (1 - ra_) * (1 - rb), rel=1e-9)


def test_original_state_pins_every_appearance_and_copy_state_is_ignored():
    graph = _shared_psu(state="failed")  # a stale state on the copy: ignored
    res = ra.analyze(graph)
    assert np.allclose(res["system"]["sf"], _exact(res["time"]), rtol=1e-12)
    for n in graph["nodes"]:
        if n["id"] == "psu":
            n["data"]["state"] = "failed"
    assert max(ra.analyze(graph)["system"]["sf"]) == 0.0


def test_repeats_in_a_subsystem_are_resolved_there():
    sub = _shared_psu()
    top = {"nodes": [*_io(), _node("s", "subsystem", "Trains", rbd={"id": "sub", "name": "Trains"})],
           "edges": [{"source": "input", "target": "s"}, {"source": "s", "target": "output"}]}
    res = ra.analyze(top, resolve_subsystem={"sub": sub}.get, t_max=1000.0)
    assert np.allclose(res["system"]["sf"], _exact(res["time"]), rtol=1e-9)


@pytest.mark.parametrize("mutate, message", [
    (lambda ns: ns[-1]["data"].update(repeat_of="nope"), "isn't in this diagram"),
    (lambda ns: ns[-1]["data"].update(repeat_of="psu2"), "repeat of itself"),
    (lambda ns: ns.append(_node("psu3", "component", "x", repeat_of="psu2")), "itself a repeated block"),
    (lambda ns: ns.append(_node("g", "knode", "g", n=1)) or ns[-2]["data"].update(repeat_of="g"),
     "Only component blocks"),
    (lambda ns: ns.__setitem__(-1, {**ns[-1], "type": "series"}), "only a component block"),
])
def test_invalid_repeats_are_explained(mutate, message):
    graph = _shared_psu()
    mutate(graph["nodes"])
    v = ra.validate_graph(graph)
    assert not v["valid"] and any(message in e for e in v["errors"]), v["errors"]
    with pytest.raises(ra.AnalysisError, match=message):
        ra.analyze(graph)


def test_validation_accepts_repeats_and_names_copies():
    v = ra.validate_graph(_shared_psu())
    assert v["valid"] and v["analytic"], v["errors"]
    # A dangling copy is reported under the original's (marked) name.
    graph = _shared_psu()
    graph["edges"] = [e for e in graph["edges"] if e["source"] != "psu2"]
    v = ra.validate_graph(graph)
    assert any("↺ Power supply" in e for e in v["errors"]), v["errors"]


def test_repairable_diagrams_refuse_repeats():
    graph = _shared_psu()
    graph["repairable"] = True
    rep = _exp(0.5)
    for n in graph["nodes"]:
        if n["type"] == "component" and "repeat_of" not in n["data"]:
            n["data"]["repair"] = rep
    v = ra.validate_graph(graph)
    assert not v["valid"]
    assert any("non-repairable" in e and "“Power supply”" in e for e in v["errors"])
    # Only the one message — the copy isn't also asked for a repair time.
    assert not any("repair-time" in e for e in v["errors"])
    with pytest.raises(ra.AnalysisError, match="non-repairable"):
        ra.analyze_availability(graph, n_simulations=10)


def test_ccf_groups_skip_copies():
    graph = _shared_psu()
    graph["nodes"][3]["data"]["model"] = _exp(LAM["a"])  # symmetric pumps
    graph["ccf_groups"] = [{"members": ["a", "b", "psu2"], "beta": 0.1}]
    res = ra.analyze(graph)  # the copy isn't a separate member; a and b are
    assert res["ccf"] is not None


def test_compact_format_round_trips_repeat_of():
    compact = {"nodes": [{"id": "input", "type": "input"}, {"id": "output", "type": "output"},
                         {"id": "p", "type": "component", "label": "PSU",
                          "model": {"distribution_id": "exponential",
                                    "params": [{"name": "failure_rate", "value": 1e-3}]}},
                         {"id": "p2", "type": "component", "repeat_of": "p"}],
               "edges": [{"source": "input", "target": "p"}, {"source": "p", "target": "output"},
                         {"source": "input", "target": "p2"}, {"source": "p2", "target": "output"}]}
    graph = normalize_graph(compact)
    (copy,) = [n for n in graph["nodes"] if n["id"] == "p2"]
    assert copy["data"]["repeat_of"] == "p"
    assert compact_graph(graph)["nodes"][-1] == {"id": "p2", "type": "component", "label": "p2",
                                                 "repeat_of": "p"}
    compact["nodes"][-1]["repeat_of"] = "missing"
    with pytest.raises(GraphError, match="isn't in this diagram"):
        normalize_graph(compact)


def test_old_graphs_have_no_repeats():
    assert find_repeats(_shared_psu()["nodes"][:-1]) == ({}, {})


def test_diagrams_the_repeats_tie_up_too_much_are_refused_quickly():
    """Components repeated across chained voting groups (FFORT's "pcs" tree
    shape) would make RePyability list millions of path sets; the diagram is
    refused after a bounded replay of that search instead of tying the
    server up."""
    import time

    from backend.services import rbd_repeats
    from backend.services.rbd_import import fault_tree as ft

    nodes, tops = {}, []
    for i, (spares, fails) in enumerate([(6, 3), (3, 2)]):
        units = [f"M{i}a", f"M{i}b", *(f"S{i}_{j}" for j in range(spares))]
        for u in units:
            nodes[u] = ft.Leaf(u, {"type": "component", "model": ft.exponential_model(0.4)})
        nodes[f"MF{i}"] = ft.Gate(f"MF{i}", "and", units[:2])
        nodes[f"ACF{i}"] = ft.Gate(f"ACF{i}", "atleast", units, fails)
        nodes[f"V{i}"] = ft.Gate(f"V{i}", "or", [f"MF{i}", f"ACF{i}"])
        tops.append(f"V{i}")
    nodes["TOP"] = ft.Gate("TOP", "or", tops)
    graph = normalize_graph(ft.to_graph(ft.FaultTree(nodes, "TOP"))[0])
    start = time.perf_counter()
    v = ra.validate_graph(graph)
    assert not v["valid"] and rbd_repeats.CORE_MESSAGE in v["errors"]
    with pytest.raises(ra.AnalysisError, match="tie together too much"):
        ra.analyze(graph)
    assert time.perf_counter() - start < 10


# ---------------------------------------------------------------------------
# Download as Python
# ---------------------------------------------------------------------------
def test_export_reproduces_repeated_blocks(tmp_path):
    graph = _shared_psu()
    app = ra.analyze(graph)
    code = rbd_export.to_python(graph, "Shared supply", exported_at=WHEN)
    assert "\"psu2\": \"psu\",  # ↺ Power supply: the same component, drawn again" in code
    res, _ = _run(code, tmp_path)
    np.testing.assert_allclose(res["curve"]["sf"], app["system"]["sf"], atol=1e-12)
    assert res["mttf"] == pytest.approx(app["mttf"], rel=1e-9)
    pairs = {"Birnbaum": "birnbaum", "Fussell-Vesely": "fussell_vesely",
             "Criticality": "criticality", "RAW": "risk_achievement_worth",
             "RRW": "risk_reduction_worth", "Improvement": "improvement_potential"}
    for key, app_key in pairs.items():
        assert set(res["importance"][key]) == {"a", "b", "psu"}
        for node, value in app["importance"][app_key].items():
            assert res["importance"][key][node] == pytest.approx(value, rel=1e-9)


def test_export_of_repeats_in_subsystem_and_repairable_diagram():
    sub = _shared_psu()
    top = {"nodes": [*_io(), _node("s", "subsystem", "Trains", rbd={"id": "sub", "name": "Trains"})],
           "edges": [{"source": "input", "target": "s"}, {"source": "s", "target": "output"}]}
    code = rbd_export.to_python(top, "Top", resolve_subsystem={"sub": sub}.get, exported_at=WHEN)
    assert '"psu2": "psu",  # ↺ Power supply (repeated)' in code
    ns = {}
    exec(compile(code.replace('if __name__ == "__main__":', "if False:"), "x", "exec"), ns)
    t = np.linspace(0, 2000, 7)
    np.testing.assert_allclose(ns["rbd"].sf(t), _exact(t), rtol=1e-12)

    graph = _shared_psu()
    graph["repairable"] = True
    code = rbd_export.to_python(graph, "Rep", exported_at=WHEN)
    # As in the app, availability can't honour a repeated block: a placeholder.
    assert "power_supply_2 = missing_model(" in code
    assert "Repeated blocks (“Power supply”) are supported in non-repairable" in code.replace('"\n    "', "")


# ---------------------------------------------------------------------------
# Repeated blocks across the other RBD features
# ---------------------------------------------------------------------------
def _vote_with_shared_supply():
    """Three trains into a 2-out-of-3 vote; one supply feeds trains A and B,
    so it is drawn twice and can't be factored out of the vote."""
    return {
        "nodes": [*_io(), _node("a", "component", "A", model=_exp(1e-3)),
                  _node("b", "component", "B", model=_exp(2e-3)),
                  _node("c", "component", "C", model=_exp(3e-3)),
                  _node("psu", "component", "PSU", model=_exp(5e-4)),
                  _node("psu2", "component", "PSU", repeat_of="psu"),
                  _node("k", "knode", "2oo3", n=2)],
        "edges": [{"source": s, "target": t} for s, t in [
            ("input", "a"), ("a", "psu"), ("psu", "k"), ("input", "b"), ("b", "psu2"),
            ("psu2", "k"), ("input", "c"), ("c", "k"), ("k", "output")]],
    }


def test_fault_tree_view_shows_a_repeated_block_as_one_event():
    from backend.services import rbd_fault_tree

    graph = _vote_with_shared_supply()
    out = rbd_fault_tree.fault_tree(graph, t=300.0)
    rbd, *_ = ra._build_rbd(graph)
    assert out["top_event_probability"] == pytest.approx(1 - float(rbd.sf(np.array([300.0]))[0]), rel=1e-12)
    assert sorted(e["id"] for e in out["events"]) == ["a", "b", "c", "psu"]
    # The supply fails the system alone; the trains appear under several gates.
    assert any(c["events"] == ["psu"] for c in out["cut_sets"]["listed"])
    assert any(e["repeated"] for e in out["events"])


def test_design_refuses_repeated_blocks_explicitly_and_designs_the_rest():
    from backend.services import rbd_design
    from backend.services.rbd_design import DesignError

    graph = _shared_psu()
    for bid in ("psu", "psu2"):
        with pytest.raises(DesignError, match="drawn in more than one place"):
            rbd_design.design_redundancy(graph, 200.0, [{"id": bid, "cost": 1, "max_copies": 3}],
                                         budget={"cost": 3})
    res = rbd_design.design_redundancy(
        graph, 200.0, [{"id": "a", "cost": 1, "max_copies": 3}, {"id": "b", "cost": 1, "max_copies": 3}],
        budget={"cost": 4})
    # Brute force over the pump copies, with the shared supply counted once.
    ra_, rb, rp = (np.exp(-LAM[k] * 200.0) for k in ("a", "b", "psu"))
    best = max(rp * (1 - (1 - ra_) ** na * (1 - rb) ** nb)
               for na in range(1, 4) for nb in range(1, 4) if na + nb <= 4)
    assert res["design"]["reliability"] == pytest.approx(best, rel=1e-9)


def test_confidence_band_draws_a_repeated_block_once():
    import surpyval as surv

    fit = surv.Weibull.fit(np.array([90.0, 110, 120, 130, 140, 155, 170, 190, 200, 230, 260]))
    alpha, beta = (float(v) for v in fit.params)
    saved = {"source": "saved", "kind": "distribution", "modelId": "m1", "name": "PSU fit",
             "distribution_id": "weibull", "distribution": "Weibull",
             "params": [{"name": "alpha", "value": alpha}, {"name": "beta", "value": beta}]}
    graph = _shared_psu()
    graph["nodes"][4]["data"]["model"] = saved  # the supply
    res = ra.analyze(graph, resolve_model=lambda mid: {"model": fit} if mid == "m1" else None,
                     band={"level": 0.9})
    band = res["band"]
    assert [b["id"] for b in band["uncertain"]] == ["psu"]
    lower, upper = np.asarray(band["sf_lower"], dtype=float), np.asarray(band["sf_upper"], dtype=float)
    sf = np.asarray(res["system"]["sf"])
    mid = len(sf) // 3
    assert lower[mid] <= sf[mid] <= upper[mid] and upper[mid] - lower[mid] > 1e-3
