"""Fault-tree view of an RBD (#101): the builder graph converts through
RePyability's FaultTree.from_rbd (series -> OR, parallel -> AND, k-of-n ->
VOTE, bridge -> OR over cut sets), sub-systems are developed in place,
common cause becomes a shared event, and the top event probability is exactly
the calculator's unreliability."""

import copy
import json

import mongomock
import numpy as np
import pytest

from backend.services import rbd_analysis as ra
from backend.services import samples
from backend.services.rbd_analysis import AnalysisError
from backend.services.rbd_fault_tree import fault_tree
from backend.tests.test_rbd_analysis import _component, _edge, _io_nodes, _repairable_component
from backend.tests.test_rbd_large_diagrams import _bridge, _chains


def _weibull(nid, label, alpha, beta=1.5):
    return _component(nid, label, "weibull", [("alpha", alpha), ("beta", beta)])


def _series():
    nodes = _io_nodes() + [_weibull("a", "Pump", 900), _weibull("b", "Valve", 1500)]
    return {"nodes": nodes, "edges": [_edge("input", "a"), _edge("a", "b"), _edge("b", "output")]}


def _parallel():
    nodes = _io_nodes() + [_weibull("a", "Pump A", 900), _weibull("b", "Pump B", 1200)]
    edges = [_edge("input", "a"), _edge("input", "b"), _edge("a", "output"), _edge("b", "output")]
    return {"nodes": nodes, "edges": edges}


def _two_of_three():
    nodes = _io_nodes() + [
        _weibull("a", "A", 900), _weibull("b", "B", 1000), _weibull("c", "C", 1100),
        {"id": "vote", "type": "knode", "data": {"label": "2oo3", "n": 2, "k": 3}},
    ]
    edges = [_edge("input", x) for x in "abc"] + [_edge(x, "vote") for x in "abc"]
    return {"nodes": nodes, "edges": edges + [_edge("vote", "output")]}


def _unreliability(graph, t, resolve_subsystem=None):
    """1 - R(t) from the calculator's own RBD (pins and common cause included)."""
    rbd, *_, working, broken, _ = ra._build_rbd(graph, resolve_subsystem)
    return 1.0 - float(rbd.sf(t, working_nodes=working, broken_nodes=broken))


def _gate(result, gid):
    return next(g for g in result["gates"] if g["id"] == gid)


def _event(result, eid):
    return next(e for e in result["events"] if e["id"] == eid)


def _inputs(gate):
    return [i["id"] for i in gate["inputs"]]


def test_series_is_an_or_gate_and_matches_the_calculator():
    res = fault_tree(_series(), t=400.0)
    json.dumps(res)  # JSON-safe
    assert res["kind"] == "reliability" and res["t"] == 400.0
    assert [(g["id"], g["kind"]) for g in res["gates"]] == [("TOP", "or")]
    assert _inputs(_gate(res, "TOP")) == ["a", "b"]
    assert {e["id"]: e["label"] for e in res["events"]} == {"a": "Pump", "b": "Valve"}
    assert res["top_event_probability"] == pytest.approx(_unreliability(_series(), 400.0), abs=1e-12)


def test_parallel_is_an_and_gate():
    res = fault_tree(_parallel(), t=700.0)
    top = _gate(res, "TOP")
    assert top["kind"] == "and" and top["k"] == 2
    q = {e["id"]: e["probability"] for e in res["events"]}
    assert res["top_event_probability"] == pytest.approx(q["a"] * q["b"], rel=1e-12)
    assert res["top_event_probability"] == pytest.approx(_unreliability(_parallel(), 700.0), abs=1e-12)


def test_k_of_n_is_a_vote_on_the_failures_and_the_voting_node_drops_out():
    res = fault_tree(_two_of_three(), t=500.0)
    top = _gate(res, "TOP")
    # 2 of 3 must work, so 2 of 3 failures fail the system.
    assert top["kind"] == "vote" and top["k"] == 2 and sorted(_inputs(top)) == ["a", "b", "c"]
    assert "vote" not in {e["id"] for e in res["events"]}
    assert res["top_event_probability"] == pytest.approx(_unreliability(_two_of_three(), 500.0), abs=1e-12)
    assert res["cut_sets"]["count"] == 3 and all(c["order"] == 2 for c in res["cut_sets"]["listed"])


def test_bridge_is_an_or_over_its_cut_sets_with_repeated_events():
    res = fault_tree(_bridge(), t=300.0)
    top = _gate(res, "TOP")
    assert top["kind"] == "or"
    branches = [_gate(res, g) for g in _inputs(top)]
    assert all(b["kind"] == "and" for b in branches)
    assert sorted(sorted(_inputs(b)) for b in branches) == [["a", "b"], ["a", "d"], ["b", "c", "e"], ["c", "d"]]
    assert _event(res, "a")["repeated"] and not _event(res, "e")["repeated"]
    # Exact despite the repeated events (no rare-event approximation).
    assert res["top_event_probability"] == pytest.approx(_unreliability(_bridge(), 300.0), abs=1e-12)
    assert res["cut_sets"]["probability_sum"] > res["top_event_probability"]


def test_subsystem_is_developed_under_a_gate_named_after_the_block():
    sub = samples._pump_station_graph()
    top = {
        "nodes": _io_nodes() + [
            _weibull("filter", "Filter", 5000),
            {"id": "skid", "type": "subsystem",
             "data": {"label": "Pump skid", "rbd": {"id": "SUB", "name": "Pumps"}}},
        ],
        "edges": [_edge("input", "filter"), _edge("filter", "skid"), _edge("skid", "output")],
    }
    resolve = lambda i: sub if i == "SUB" else None  # noqa: E731
    res = fault_tree(top, resolve_subsystem=resolve, t=600.0)
    skid = next(g for g in res["gates"] if g.get("role") == "subsystem")
    assert skid["label"] == "Pump skid" and skid["kind"] == "or"
    assert "skid/controller" in _inputs(skid)
    pump = _event(res, "skid/pumpA")
    assert pump["label"] == "Pump A" and pump["path"] == ["Pump skid"]
    assert res["top_event_probability"] == pytest.approx(
        _unreliability(top, 600.0, resolve), abs=1e-12
    )


def test_default_time_is_the_calculators_importance_time():
    graph = samples._pump_station_graph()
    analysis = ra.analyze(graph)
    res = fault_tree(graph)
    t_rep = analysis["importance"]["time"]
    assert res["t"] == pytest.approx(t_rep) and res["t_default"] == pytest.approx(t_rep)
    sf = analysis["system"]["sf"][analysis["time"].index(t_rep)]
    assert res["top_event_probability"] == pytest.approx(1.0 - sf, abs=1e-12)
    # A chosen time moves the evaluation but not the default.
    later = fault_tree(graph, t=2 * t_rep)
    assert later["t_default"] == pytest.approx(t_rep)
    assert later["top_event_probability"] > res["top_event_probability"]


def test_common_cause_is_a_shared_event_and_stays_exact():
    graph = samples._instrument_air_design_graph()
    res = fault_tree(graph, t=5000.0)
    shared = next(e for e in res["events"] if e["node_type"] == "ccf")
    assert shared["repeated"] and shared["beta"] == 0.1
    members = [g for g in res["gates"] if g.get("role") == "ccf_member"]
    assert sorted(g["label"] for g in members) == ["Compressor A", "Compressor B", "Compressor C"]
    assert all(shared["id"] in _inputs(g) for g in members)
    assert _gate(res, "G1")["kind"] == "vote"
    assert res["top_event_probability"] == pytest.approx(_unreliability(graph, 5000.0), abs=1e-12)
    # The shared cause alone is a first-order cut set.
    assert any(c["events"] == [shared["id"]] for c in res["cut_sets"]["listed"])


def test_pinned_blocks_never_or_always_fail():
    graph = _parallel()
    graph["nodes"].append(_weibull("c", "Valve", 2000))
    graph["edges"] = [e for e in graph["edges"] if e["target"] != "output"] + [
        _edge("a", "c"), _edge("b", "c"), _edge("c", "output")
    ]
    graph["nodes"][2]["data"]["state"] = "failed"  # Pump A
    del graph["nodes"][2]["data"]["model"]  # a pinned block needs no model
    graph["nodes"][4]["data"]["state"] = "working"  # Valve
    res = fault_tree(graph, t=700.0)
    assert _event(res, "a")["pinned"] == "failed" and _event(res, "a")["probability"] == 1.0
    assert _event(res, "c")["pinned"] == "working" and _event(res, "c")["probability"] == 0.0
    assert res["top_event_probability"] == pytest.approx(_unreliability(graph, 700.0), abs=1e-12)
    assert res["top_event_probability"] == pytest.approx(_event(res, "b")["probability"], abs=1e-12)


def test_ranked_cut_sets_are_sorted_and_shares_are_of_the_top_event():
    res = fault_tree(samples._instrument_air_design_graph(), t=5000.0)
    cuts = res["cut_sets"]
    listed = cuts["listed"]
    assert cuts["complete"] and cuts["basis"] == "all" and cuts["count"] == len(listed)
    probs = [c["probability"] for c in listed]
    assert probs == sorted(probs, reverse=True)
    top = res["top_event_probability"]
    for c in listed:
        assert c["probability"] <= top + 1e-15
        assert c["share"] == pytest.approx(c["probability"] / top)
    # The rare-event sum bounds the (exact) top event from above, and is close.
    assert top <= cuts["probability_sum"] < 1.2 * top
    # Fussell-Vesely is the share of the cut sets holding the event.
    header = _event(res, "header")
    assert header["importance"]["fussell_vesely"] == pytest.approx(
        next(c["share"] for c in listed if c["events"] == ["header"])
    )


def test_importance_matches_repyability_measures():
    from repyability import FaultTree

    res = fault_tree(_bridge(), t=300.0)
    rbd, *_ = ra._build_rbd(_bridge())
    tree = FaultTree.from_rbd(rbd)
    expected = tree.birnbaum_importance(300.0)
    crit = tree.criticality_importance(300.0)
    for e in res["events"]:
        assert e["importance"]["birnbaum"] == pytest.approx(expected[e["id"]], rel=1e-9)
        assert e["importance"]["criticality"] == pytest.approx(crit[e["id"]], rel=1e-9)


def test_large_trees_list_the_most_likely_cut_sets_without_enumerating():
    # 4 chains of 40 in parallel: 40^4 = 2.56 million minimal cut sets.
    res = fault_tree(_chains(4, 40), t=80.0)
    cuts = res["cut_sets"]
    assert not cuts["complete"] and cuts["basis"] == "most_likely"
    assert cuts["count"] == 40 ** 4 and len(cuts["listed"]) == 100
    probs = [c["probability"] for c in cuts["listed"]]
    assert probs == sorted(probs, reverse=True)
    # The likeliest takes the likeliest block of each chain (the first: the
    # lowest alpha).
    assert sorted(cuts["listed"][0]["events"]) == ["c0_0", "c1_0", "c2_0", "c3_0"]
    q = {e["id"]: e["probability"] for e in res["events"]}
    assert probs[0] == pytest.approx(np.prod([q[f"c{c}_0"] for c in range(4)]))
    # Fussell-Vesely still covers all 2.56 million, without the listing: exact
    # since RePyability 0.11 (#137), a block of chain 0 is in a failed cut set
    # when it has failed and so has some block of every other chain.
    others = np.prod([1.0 - np.prod([1.0 - q[f"c{c}_{i}"] for i in range(40)]) for c in range(1, 4)])
    for i in (0, 17, 39):
        fv = next(e["importance"]["fussell_vesely"] for e in res["events"] if e["id"] == f"c0_{i}")
        assert fv == pytest.approx(q[f"c0_{i}"] * others / res["top_event_probability"], rel=1e-9)


def test_closed_form_fussell_vesely_matches_repyability():
    from repyability import FaultTree

    from backend.services.rbd_fault_tree import _module_fussell_vesely

    tree = FaultTree(
        {"top": ("or", ["v", "pumps", "vote"]), "pumps": ("and", ["p1", "p2"]),
         "vote": ("vote", 2, ["a", "b", "c"])},
        {"v": 0.01, "p1": 0.1, "p2": 0.2, "a": 0.05, "b": 0.07, "c": 0.09},
    )
    q = {e: float(p) for e, p in tree.events.items()}
    top = tree.top_event_probability()
    # The closed form is the rare-event sum (the fallback); RePyability 0.11's
    # default is the exact union (#137), so compare with its rare-event form.
    expected = tree.fussell_vesely(method="rare_event")
    for e, share in _module_fussell_vesely(tree, q).items():
        assert share / top == pytest.approx(expected[e], rel=1e-12)


def test_repairable_diagram_uses_steady_state_unavailability():
    graph = samples._instrument_air_availability_graph()
    res = fault_tree(graph, t=123.0)
    assert res["kind"] == "availability" and res["t"] is None
    rbd, _, gate_ids, working, broken = ra._build_repairable_rbd(graph)
    expected = 1.0 - rbd.mean_availability(working_nodes=working, broken_nodes=broken)
    assert res["top_event_probability"] == pytest.approx(expected, rel=1e-9)
    assert res["unavailability"] == pytest.approx(expected, rel=1e-9)
    assert _gate(res, "G1")["kind"] == "vote"


def test_repairable_pins_and_simple_graph():
    graph = {
        "repairable": True,
        "nodes": _io_nodes() + [
            _repairable_component("a", "A", 900, 1.4, 2.0),
            _repairable_component("b", "B", 1100, 1.4, 2.0),
        ],
        "edges": [_edge("input", "a"), _edge("input", "b"), _edge("a", "output"), _edge("b", "output")],
    }
    graph["nodes"][2]["data"]["state"] = "failed"
    res = fault_tree(graph)
    assert _event(res, "a")["probability"] == 1.0
    assert res["top_event_probability"] == pytest.approx(_event(res, "b")["probability"], rel=1e-12)


def test_a_diagram_that_cannot_fail_is_a_clear_error():
    graph = _series()
    graph["edges"].append(_edge("input", "output"))
    with pytest.raises(AnalysisError, match="can't fail"):
        fault_tree(graph, t=10.0)


def test_pinning_a_common_cause_member_is_a_clear_error():
    graph = copy.deepcopy(samples._instrument_air_design_graph())
    next(n for n in graph["nodes"] if n["id"] == "compA")["data"]["state"] = "failed"
    with pytest.raises(AnalysisError, match="common-cause"):
        fault_tree(graph, t=10.0)


def test_bad_time_is_a_clear_error():
    with pytest.raises(AnalysisError, match="positive"):
        fault_tree(_series(), t=-1.0)


# --- API --------------------------------------------------------------------

USER = {"uid": "user-ft", "email": "ft@example.org", "name": "Fault Tree"}


@pytest.fixture()
def client(monkeypatch):
    from fastapi.testclient import TestClient

    from backend import config, db
    from backend.auth import get_current_user
    from backend.main import app

    monkeypatch.setattr(config, "AUTH_DISABLED", False)
    test_db = mongomock.MongoClient()["reliafy_test"]
    monkeypatch.setattr(db, "_db", test_db)
    monkeypatch.setattr(db, "_simulated", True)
    app.dependency_overrides[get_current_user] = lambda: USER
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()


def test_api_resolves_saved_subsystems_in_the_callers_scope(client):
    saved = client.post("/api/rbds", json={"name": "Pumps", "graph": samples._pump_station_graph()})
    assert saved.status_code == 200
    sub_id = saved.json()["id"]
    graph = {
        "nodes": _io_nodes() + [
            {"id": "skid", "type": "subsystem",
             "data": {"label": "Pump skid", "rbd": {"id": sub_id, "name": "Pumps"}}},
        ],
        "edges": [_edge("input", "skid"), _edge("skid", "output")],
    }
    r = client.post("/api/rbds/fault-tree", json={"graph": graph, "t": 500})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["t"] == 500
    assert _event(body, "skid/pumpA")["path"] == ["Pump skid"]
    assert body["top_event_probability"] == pytest.approx(
        _unreliability(samples._pump_station_graph(), 500.0), abs=1e-12
    )


def test_api_reports_conversion_problems_as_422(client):
    r = client.post("/api/rbds/fault-tree", json={"graph": {"nodes": _io_nodes(), "edges": []}})
    assert r.status_code == 422
    assert r.json()["detail"] == "The diagram has no blocks yet. Add blocks between Input and Output, and connect them."
