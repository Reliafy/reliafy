"""Phased missions and undirected networks (#160), checked against
RePyability's ``PhasedMission`` and ``Network`` called directly."""

import json

import mongomock
import numpy as np
import pytest
import surpyval as surv
from repyability import Network, NonRepairableRBD, PhasedMission
from repyability.rbd.helper_classes import PerfectReliability

from backend.services import rbd_graph, rbd_network, rbd_phases, rbds
from backend.services import rbd_analysis as ra
from backend.services.rbd_analysis import AnalysisError
from backend.tests.test_mcp import _call, _err, _ok, env  # noqa: F401 - env is a fixture
from backend.tests.test_mcp import A as MCP_A
from backend.tests.test_rbd_export import _run


def _exp(rate):
    return {"source": "params", "distribution": "Exponential", "distribution_id": "exponential",
            "params": [{"name": "failure_rate", "value": rate}]}


def _wb(alpha, beta):
    return {"source": "params", "distribution": "Weibull", "distribution_id": "weibull",
            "params": [{"name": "alpha", "value": alpha}, {"name": "beta", "value": beta}]}


def _node(nid, ntype="component", label=None, **data):
    return {"id": nid, "type": ntype, "position": {"x": 0, "y": 0}, "data": {"label": label or nid.upper(), **data}}


def _io():
    return [_node("input", "input", "Input"), _node("output", "output", "Output")]


def _e(a, b):
    return {"id": f"{a}-{b}", "source": a, "target": b}


ENGINE = surv.Exponential.from_params([0.01])
GEAR = surv.Weibull.from_params([100, 2])


def _aircraft(**phases):
    """Two engines voting into a junction, then the landing gear: both engines
    at take-off and landing, either in cruise, where the gear isn't needed."""
    graph = {
        "nodes": _io() + [_node("e1", model=_exp(0.01)), _node("e2", model=_exp(0.01)),
                          _node("k1", "knode", "Engines", n=1, k=2), _node("gear", model=_wb(100, 2))],
        "edges": [_e("input", "e1"), _e("input", "e2"), _e("e1", "k1"), _e("e2", "k1"), _e("k1", "gear"),
                  _e("gear", "output")],
        "unit": "Hours",
        "phases": [
            {"name": "Take-off", "duration": 0.1, "votes": {"k1": 2}},
            {"name": "Cruise", "duration": 5, "not_needed": ["gear"]},
            {"name": "Landing", "duration": 0.2, "votes": {"k1": 2}},
        ],
    }
    graph.update(phases)
    return graph


def _direct_aircraft():
    edges = [("input", "e1"), ("input", "e2"), ("e1", "k1"), ("e2", "k1"), ("k1", "gear"), ("gear", "output")]
    rel = {"e1": ENGINE, "e2": ENGINE, "k1": PerfectReliability, "gear": GEAR}
    io = {"input_node": "input", "output_node": "output"}
    both = NonRepairableRBD(edges, rel, k={"k1": 2}, **io)
    cruise_edges = [(a.replace("gear", "g~"), b.replace("gear", "g~")) for a, b in edges]
    cruise = NonRepairableRBD(cruise_edges, {**{k: v for k, v in rel.items() if k != "gear"},
                                             "g~": PerfectReliability}, k={"k1": 1}, **io)
    return PhasedMission([("Take-off", 0.1, both), ("Cruise", 5.0, cruise), ("Landing", 0.2, both)])


# ---------------------------------------------------------------------------
# Phased missions
# ---------------------------------------------------------------------------
def test_mission_matches_phased_mission_called_directly():
    out = rbd_phases.analyze_phases(_aircraft())
    direct = _direct_aircraft()
    assert out["method"] == "exact"
    assert out["reliability"] == pytest.approx(direct.reliability(), abs=1e-12)
    failing = direct.phase_failure_probabilities()
    assert [p["failure_probability"] for p in out["phases"]] == pytest.approx(list(failing.values()), abs=1e-12)
    # The reliability at each phase's end is what's left after the failures so far.
    assert [p["reliability_at_end"] for p in out["phases"]] == pytest.approx(
        list(1 - np.cumsum(list(failing.values()))), abs=1e-12)
    assert out["phases"][-1]["reliability_at_end"] == pytest.approx(out["reliability"], abs=1e-12)
    assert [p["end"] for p in out["phases"]] == pytest.approx([0.1, 5.1, 5.3])
    # Losing one engine in cruise (allowed) dooms the landing (needs both).
    assert out["riskiest"]["name"] == "Landing"
    assert sum(p["share"] for p in out["phases"]) == pytest.approx(1.0)


def test_a_block_not_needed_still_ages_through_the_phase():
    # One block, needed only in the second phase: it must survive both.
    graph = {"nodes": _io() + [_node("a", model=_wb(100, 2))], "edges": [_e("input", "a"), _e("a", "output")],
             "phases": [{"name": "Idle", "duration": 30, "not_needed": ["a"]}, {"name": "Run", "duration": 20}]}
    out = rbd_phases.analyze_phases(graph)
    assert out["phases"][0]["failure_probability"] == pytest.approx(0.0, abs=1e-15)
    assert out["reliability"] == pytest.approx(float(GEAR.sf(50.0)), abs=1e-12)


def test_one_phase_needing_everything_is_the_diagrams_reliability():
    graph = _aircraft(phases=[{"name": "All", "duration": 40}])
    rbd, *_ = ra._build_rbd({k: v for k, v in graph.items() if k != "phases"})
    out = rbd_phases.analyze_phases(graph)
    assert out["reliability"] == pytest.approx(float(rbd.sf(40.0)), abs=1e-12)


def test_pinned_and_repeated_blocks():
    nodes = _io() + [_node("a", model=_wb(100, 2)), _node("b", model=_wb(80, 3), state="working"),
                     _node("a2", label="A again", repeat_of="a")]
    graph = {"nodes": nodes, "edges": [_e("input", "a"), _e("a", "b"), _e("b", "a2"), _e("a2", "output")],
             "phases": [{"name": "One", "duration": 10}, {"name": "Two", "duration": 10, "not_needed": ["a"]}]}
    out = rbd_phases.analyze_phases(graph)
    # b is pinned working; a (and its copy) aren't needed in phase two but still age.
    assert out["phases"][0]["failure_probability"] == pytest.approx(float(GEAR.ff(10.0)), abs=1e-12)
    assert out["phases"][1]["failure_probability"] == pytest.approx(0.0, abs=1e-15)


def test_too_large_missions_are_simulated_and_say_so(monkeypatch):
    from repyability.rbd import phased_mission

    exact = rbd_phases.analyze_phases(_aircraft())
    monkeypatch.setattr(phased_mission, "MAX_NODES", 2)
    out = rbd_phases.analyze_phases(_aircraft())
    assert out["method"] == "simulated"
    assert out["interval"]["n_samples"] == rbd_phases.SIM_MISSIONS
    assert out["interval"]["lower"] < out["reliability"] < out["interval"]["upper"]
    assert out["reliability"] == pytest.approx(exact["reliability"], abs=0.01)
    assert "simulated" in out["method_reason"]


@pytest.mark.parametrize("change, words", [
    ({"phases": [{"name": "A", "duration": 1, "votes": {"k1": 3}}]}, "needs 3 working inputs"),
    ({"repairable": True}, "non-repairable"),
    ({"ccf_groups": [{"id": "g", "members": ["e1", "e2"], "beta": 0.1}]}, "common-cause"),
    ({"network": {"source": "input", "target": "output"}}, "not a network"),
    ({"phases": []}, "no phases"),
    ({"phases": [{"name": "A", "duration": -1}]}, "at least 0"),
])
def test_what_a_mission_cant_take_is_refused_in_plain_words(change, words):
    with pytest.raises(AnalysisError, match=words):
        rbd_phases.analyze_phases(_aircraft(**change))


def test_the_setting_is_cleaned_and_carried_by_the_graph_formats():
    raw = _aircraft(phases=[{"name": " Take-off ", "duration": "0.5", "not_needed": ["gear", "gear"],
                             "votes": {"k1": 2.0}}])
    norm = rbd_graph.normalize_graph(raw)
    assert norm["phases"] == [{"name": "Take-off", "duration": 0.5, "not_needed": ["gear"], "votes": {"k1": 2}}]
    assert rbd_graph.compact_graph(norm)["phases"] == norm["phases"]
    with pytest.raises(rbd_graph.GraphError, match="two phases"):
        rbd_graph.normalize_graph(_aircraft(phases=[{"name": "A", "duration": 1}, {"name": "a", "duration": 2}]))


def test_validation_warns_about_phases_but_the_diagram_stays_valid():
    graph = _aircraft(phases=[{"name": "A", "duration": 1, "not_needed": ["gone"], "votes": {"k1": 3}}])
    check = rbds.validate_graph(mongomock.MongoClient()["t"], graph, "u")
    assert check["valid"]
    assert any("gone" in w for w in check["warnings"])
    assert any("needs 3 working inputs" in w for w in check["warnings"])


# ---------------------------------------------------------------------------
# Networks
# ---------------------------------------------------------------------------
def _bridge(**extra):
    """The bridge, undirected: A and B out of Input, C across, D and E in."""
    nodes = _io() + [_node(n, model=_wb(100, 2)) for n in ("a", "b", "c", "d", "e")]
    # Directions drawn every which way: a network ignores them.
    edges = [_e("input", "a"), _e("b", "input"), _e("a", "c"), _e("b", "c"), _e("c", "d"), _e("c", "e"),
             _e("a", "d"), _e("e", "b"), _e("d", "output"), _e("e", "output")]
    graph = {"nodes": nodes, "edges": edges, "unit": "Hours", "network": {"source": "input", "target": "output"}}
    graph.update(extra)
    return graph


def _direct_bridge(source="input", target="output"):
    pairs = [("input", "a"), ("b", "input"), ("a", "c"), ("b", "c"), ("c", "d"), ("c", "e"), ("a", "d"),
             ("e", "b"), ("d", "output"), ("e", "output")]
    links = {f"l{i}": (a, b, PerfectReliability) for i, (a, b) in enumerate(pairs)}
    return Network(links, source, target, nodes={n: GEAR for n in "abcde"})


def test_network_matches_network_called_directly():
    out = rbd_network.analyze_network(_bridge(), t=40.0, at_times=[10.0, 60.0])
    net = _direct_bridge()
    assert out["method"] == "exact"
    assert out["reliability"] == pytest.approx(float(net.sf(40.0)), abs=1e-12)
    assert out["at"]["sf"] == pytest.approx(list(net.sf(np.array([10.0, 60.0]))), abs=1e-12)
    assert out["mttf"] == pytest.approx(net.mean(), rel=1e-9)
    importance = {r["id"]: r["birnbaum"] for r in out["importance"]}
    direct = net.birnbaum_importance(40.0)
    assert importance == pytest.approx({n: abs(float(direct[n])) for n in "abcde"}, abs=1e-12)
    assert out["importance"][0]["birnbaum"] >= out["importance"][-1]["birnbaum"]
    assert out["curve"]["sf"] == pytest.approx(list(net.sf(np.array(out["curve"]["t"]))), abs=1e-12)


def test_default_time_is_where_the_connection_is_about_90_percent():
    out = rbd_network.analyze_network(_bridge())
    assert out["t_given"] is False
    assert out["reliability"] == pytest.approx(0.9, abs=0.02)


def test_direction_doesnt_matter_and_blocks_can_be_terminals():
    flipped = _bridge(edges=[_e(e["target"], e["source"]) for e in _bridge()["edges"]])
    assert rbd_network.analyze_network(flipped, t=40.0)["reliability"] == pytest.approx(
        rbd_network.analyze_network(_bridge(), t=40.0)["reliability"], abs=1e-12)
    out = rbd_network.analyze_network(_bridge(network={"source": "a", "target": "e"}), t=40.0)
    assert out["reliability"] == pytest.approx(float(_direct_bridge("a", "e").sf(40.0)), abs=1e-12)
    assert out["source"]["label"] == "A"


def test_too_large_networks_are_simulated_and_say_so(monkeypatch):
    from repyability import network

    exact = float(_direct_bridge().sf(40.0))
    monkeypatch.setattr(network, "MAX_STATES", 1)
    out = rbd_network.analyze_network(_bridge(), t=40.0)
    assert out["method"] == "simulated"
    assert out["reliability"] == pytest.approx(exact, abs=0.02)
    assert out["importance"] == []


@pytest.mark.parametrize("change, words", [
    ({"nodes": _io() + [_node("a", model=_wb(100, 2)), _node("k", "knode", n=1, k=2)],
      "edges": [_e("input", "a"), _e("a", "k"), _e("k", "output")]}, "vote node"),
    ({"nodes": _io() + [_node("a", model=_wb(100, 2)), _node("a2", repeat_of="a")],
      "edges": [_e("input", "a"), _e("a", "a2"), _e("a2", "output")]}, "repeated block"),
    ({"ccf_groups": [{"id": "g", "members": ["a", "b"], "beta": 0.1}]}, "common-cause"),
    ({"repairable": True}, "non-repairable"),
    ({"network": {"source": "input", "target": "zz"}}, "isn't in the diagram"),
    ({"edges": [_e("input", "a"), _e("b", "output")]}, "No path"),
])
def test_what_a_network_cant_take_is_refused_in_plain_words(change, words):
    with pytest.raises(AnalysisError, match=words):
        rbd_network.analyze_network(_bridge(**change))


def test_block_diagram_analyses_refuse_a_network_and_validation_checks_it():
    with pytest.raises(AnalysisError, match="network"):
        ra.analyze(_bridge())
    db = mongomock.MongoClient()["t"]
    check = rbds.validate_graph(db, _bridge(), "u")
    assert check["valid"] and check["network"]
    bad = rbds.validate_graph(db, _bridge(edges=[_e("input", "a")]), "u")
    assert not bad["valid"]


def test_network_setting_is_carried_and_checked():
    norm = rbd_graph.normalize_graph({**_bridge(), "network": {"target": "e"}})
    assert norm["network"] == {"source": "input", "target": "e"}
    with pytest.raises(rbd_graph.GraphError, match="repairable"):
        rbd_graph.normalize_graph({**_bridge(), "repairable": True})


# ---------------------------------------------------------------------------
# Exports
# ---------------------------------------------------------------------------
def test_python_export_of_a_network_runs_and_matches(tmp_path):
    from backend.services import rbd_export

    graph = _bridge()
    results, _ = _run(rbd_export.to_python(graph, "Bridge"), tmp_path)
    app = rbd_network.analyze_network(graph)
    assert results["exact"] is True
    assert results["time"] == pytest.approx(app["t"], rel=1e-9)
    assert results["reliability"] == pytest.approx(app["reliability"], abs=1e-10)
    assert results["mean"] == pytest.approx(app["mttf"], rel=1e-9)
    assert results["importance"] == pytest.approx({r["id"]: r["birnbaum"] for r in app["importance"]}, abs=1e-10)


def test_python_export_of_a_phased_mission_runs_and_matches(tmp_path):
    from backend.services import rbd_export

    graph = _aircraft()
    code = rbd_export.to_python(graph, "Aircraft")
    assert "PhasedMission" in code
    results, proc = _run(code, tmp_path)
    app = rbd_phases.analyze_phases(graph)
    mission = results["phased_mission"]
    assert mission["method"] == "exact"
    assert mission["reliability"] == pytest.approx(app["reliability"], abs=1e-12)
    assert list(mission["phase_failure_probabilities"].values()) == pytest.approx(
        [p["failure_probability"] for p in app["phases"]], abs=1e-12)
    assert "Riskiest phase: Landing" in proc.stdout


def test_python_export_with_common_cause_leaves_the_mission_out_and_runs(tmp_path):
    from backend.services import rbd_export

    graph = _aircraft(ccf_groups=[{"id": "g", "members": ["e1", "e2"], "beta": 0.1}])
    code = rbd_export.to_python(graph, "Aircraft")
    assert "PhasedMission(" not in code
    results, _ = _run(code, tmp_path)
    assert "phased_mission" not in results


def test_json_round_trips_networks_and_phases():
    from backend.services import rbd_json
    from backend.services.rbd_import import RbdImportError, import_file

    for graph in (rbd_graph.normalize_graph(_bridge()), rbd_graph.normalize_graph(_aircraft())):
        text = rbd_json.to_json(rbd_json.to_document(graph, "Round trip"))
        back = rbd_graph.normalize_graph(import_file(text.encode(), "x.json")[0].graph)
        assert back.get("network") == graph.get("network")
        assert back.get("phases") == graph.get("phases")
    doc = json.loads(rbd_json.to_json(rbd_json.to_document(rbd_graph.normalize_graph(_bridge()), "Net")))
    assert doc["type"] == "Network" and doc["source"] == "input" and len(doc["nodes"]) == 5
    doc["target"] = "a"
    with pytest.raises(RbdImportError, match="changed after Reliafy wrote it"):
        import_file(json.dumps(doc).encode(), "x.json")


# ---------------------------------------------------------------------------
# API and MCP
# ---------------------------------------------------------------------------
@pytest.fixture()
def client(monkeypatch):
    from fastapi.testclient import TestClient

    from backend import config, db
    from backend.auth import get_current_user
    from backend.main import app

    monkeypatch.setattr(config, "AUTH_DISABLED", False)
    monkeypatch.setattr(db, "_db", mongomock.MongoClient()["reliafy_test"])
    monkeypatch.setattr(db, "_simulated", True)
    app.dependency_overrides[get_current_user] = lambda: {"uid": "u-missions", "email": "m@example.org"}
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()


def test_api_endpoints(client):
    r = client.post("/api/rbds/phases", json={"graph": _aircraft()})
    assert r.status_code == 200, r.text
    assert r.json()["riskiest"]["name"] == "Landing"
    r = client.post("/api/rbds/network", json={"graph": _bridge(), "t": 40})
    assert r.status_code == 200, r.text
    assert r.json()["reliability"] == pytest.approx(float(_direct_bridge().sf(40.0)), abs=1e-12)
    assert client.post("/api/rbds/network", json={"graph": _aircraft()}).status_code == 422
    assert client.post("/api/rbds/analyze", json={"graph": _bridge()}).status_code == 422


def _compact(graph):
    return rbd_graph.compact_graph(rbd_graph.normalize_graph(graph))


def test_mcp_create_and_analyze_a_network(env):
    compact = _compact(_bridge())
    out = _ok(_call(env.token[MCP_A], "create_rbd", {
        "name": "Ring main", "unit": "Hours", "nodes": compact["nodes"], "edges": compact["edges"],
        "network": {"source": "input", "target": "output"}}))
    assert out["structure_summary"].startswith("Network (undirected)")
    res = _ok(_call(env.token[MCP_A], "analyze_rbd", {"rbd_id": out["id"], "times": [40]}))
    assert res["kind"] == "network" and res["method"] == "exact"
    assert res["reliability_at"][0]["reliability"] == pytest.approx(float(_direct_bridge().sf(40.0)), abs=1e-12)
    edited = _ok(_call(env.token[MCP_A], "edit_rbd", {"rbd_id": out["id"], "ops": [
        {"op": "set", "network": {"source": "a", "target": "e"}}]}))
    assert "between a and e" in " ".join(edited["applied"])
    assert "network" in _err(_call(env.token[MCP_A], "create_rbd", {
        "name": "x", "nodes": compact["nodes"], "edges": compact["edges"], "repairable": True,
        "network": {}}))


def test_mcp_create_with_phases_then_analyze_and_edit(env):
    compact = _compact({k: v for k, v in _aircraft().items() if k != "phases"})
    out = _ok(_call(env.token[MCP_A], "create_rbd", {
        "name": "Flight", "unit": "Hours", "nodes": compact["nodes"], "edges": compact["edges"],
        "phases": _aircraft()["phases"]}))
    res = _ok(_call(env.token[MCP_A], "analyze_rbd", {"rbd_id": out["id"]}))
    mission = res["phased_mission"]
    assert mission["mission_reliability"] == pytest.approx(_direct_aircraft().reliability(), abs=1e-12)
    assert mission["riskiest_phase"] == "Landing"
    edited = _ok(_call(env.token[MCP_A], "edit_rbd", {"rbd_id": out["id"], "ops": [
        {"op": "set", "phases": [{"name": "Only", "duration": 3}]}]}))
    assert "phased mission set (Only)" in " ".join(edited["applied"])
    res = _ok(_call(env.token[MCP_A], "analyze_rbd", {"rbd_id": out["id"], "summary_only": True}))
    assert [p["name"] for p in res["phased_mission"]["phases"]] == ["Only"]
    got = _ok(_call(env.token[MCP_A], "get_rbd", {"rbd_id": out["id"]}))
    assert json.dumps(got).count("Only") >= 1
