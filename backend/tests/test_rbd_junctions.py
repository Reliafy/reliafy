"""Voting gates anywhere in a repairable RBD (#224): since RePyability 0.12 a
k-of-n vote is a junction (``PerfectReliability``), folded out of the
structure, rather than a never-failing stand-in pinned working. Two 2-of-3
stages in series, against RePyability directly and the closed form, through
the exact and simulation paths, the fault tree, the Python export and the
MCP tools."""

import pytest
import surpyval as sv
from repyability import PerfectReliability, RepairableRBD

from backend.services import rbd_analysis as ra
from backend.services import rbd_export, rbd_json
from backend.services.rbd_fault_tree import fault_tree
from backend.tests.test_mcp import A, _call, _ok, env  # noqa: F401 - env is a fixture
from backend.tests.test_rbd_costs import _exp, _io
from backend.tests.test_rbd_export import WHEN, _run

LAM_A, LAM_B, MU = 0.01, 0.02, 0.1
N = 200  # fixed simulation counts keep the suite quick


def _comp(nid, rate):
    return {"id": nid, "type": "component", "position": {"x": 0, "y": 0},
            "data": {"label": nid.upper(), "model": _exp(rate), "repair": _exp(MU)}}


def _vote(nid, state=None):
    data = {"label": f"2oo3 {nid}", "n": 2, "k": 3}
    if state:
        data["state"] = state
    return {"id": nid, "type": "knode", "position": {"x": 0, "y": 0}, "data": data}


def _two_votes(**graph):
    """input -> a1..a3 -> 2oo3 'va' -> b1..b3 -> 2oo3 'vb' -> output: the vote
    'va' sits mid-diagram."""
    nodes, edges = [*_io()], []
    for stage, rate, src, vote in (("a", LAM_A, "input", "va"), ("b", LAM_B, "va", "vb")):
        for j in (1, 2, 3):
            nid = f"{stage}{j}"
            nodes.append(_comp(nid, rate))
            edges += [{"source": src, "target": nid}, {"source": nid, "target": vote}]
        nodes.append(_vote(vote))
    edges.append({"source": "vb", "target": "output"})
    return {"repairable": True, "unit": "hours", "nodes": nodes, "edges": edges, **graph}


def _two_of_three(rate):
    a = MU / (MU + rate)
    return 3 * a ** 2 - 2 * a ** 3


EXPECTED = _two_of_three(LAM_A) * _two_of_three(LAM_B)


def _direct():
    """The same diagram built on RePyability alone, the votes as junctions."""
    E = sv.Exponential.from_params

    def pump(rate):
        return {"reliability": E([rate]), "repairability": E([MU])}

    edges, comps = [], {"va": PerfectReliability, "vb": PerfectReliability}
    for stage, rate, src, vote in (("a", LAM_A, "s", "va"), ("b", LAM_B, "va", "vb")):
        for j in (1, 2, 3):
            nid = f"{stage}{j}"
            comps[nid] = pump(rate)
            edges += [(src, nid), (nid, vote)]
    edges.append(("vb", "t"))
    return RepairableRBD(edges, comps, k={"va": 2, "vb": 2}, input_node="s", output_node="t")


def test_votes_are_junctions_not_pinned_stand_ins():
    rbd, labels, gates, working, broken = ra._build_repairable_rbd(_two_votes())
    assert gates == {"va", "vb"} and rbd._junctions() == gates
    assert not gates & set(rbd.components) and not working and not broken
    assert rbd.mean_availability() == pytest.approx(EXPECTED, rel=1e-12)


def test_two_votes_in_series_match_repyability_and_the_closed_form():
    res = ra.analyze_availability(_two_votes(), n_simulations=N)
    assert res["availability_basis"] == "exact"
    assert res["steady_state_availability"] == pytest.approx(EXPECTED, rel=1e-12)
    direct = _direct()
    assert res["steady_state_availability"] == pytest.approx(direct.mean_availability(), rel=1e-12)
    assert res["mean_up_time"] == pytest.approx(direct.mean_up_time(), rel=1e-9)
    assert res["failure_frequency"] == pytest.approx(direct.system_failure_frequency(), rel=1e-9)
    # The votes are no blocks: not in the importance, criticality or downtime.
    blocks = {f"{s}{j}" for s in "ab" for j in (1, 2, 3)}
    assert set(res["importance"]) == blocks
    assert {r["id"] for r in res["per_node"]} <= blocks
    assert not {"va", "vb"} & set(res.get("criticality") or {})
    # The simulation ran on the same diagram (its interval holds the exact mean).
    p = res["precision"]
    assert p["n_simulations"] >= N and 0 < p["simulated_window_availability"] < 1


def test_exact_availability_over_time_with_a_mid_diagram_vote():
    out = ra.exact_availability(_two_votes(), horizon=500.0)
    assert out["status"] == "ok"
    assert {r["id"] for r in out["per_node"]} <= {f"{s}{j}" for s in "ab" for j in (1, 2, 3)}
    # From new the mission availability is above the long-run value.
    assert EXPECTED < out["mission_availability"] < 1


def test_votes_leave_the_cut_sets_and_the_fault_tree():
    rbd = ra._build_repairable_rbd(_two_votes())[0]
    cuts = [set(c) for c in rbd.get_min_cut_sets(include_in_out_nodes=False)]
    assert len(cuts) == 6 and all(len(c) == 2 and not c & {"va", "vb"} for c in cuts)
    res = fault_tree(_two_votes())
    assert res["kind"] == "availability"
    assert res["unavailability"] == pytest.approx(1 - EXPECTED, rel=1e-9)
    assert res["top_event_probability"] == pytest.approx(1 - EXPECTED, rel=1e-9)
    assert {e["id"] for e in res["events"]} == {f"{s}{j}" for s in "ab" for j in (1, 2, 3)}
    assert all(not set(c["events"]) & {"va", "vb"} for c in res["cut_sets"]["listed"])


def test_a_vote_pinned_working_is_just_a_junction_and_one_pinned_failed_downs_the_system():
    g = _two_votes()
    g["nodes"] = [_vote("va", "working") if n["id"] == "va" else n for n in g["nodes"]]
    rbd, _, gates, working, _ = ra._build_repairable_rbd(g)
    assert "va" in gates and "va" not in working and "va" in rbd._junctions()
    res = ra.analyze_availability(g, simulate=False)
    assert res["steady_state_availability"] == pytest.approx(EXPECTED, rel=1e-12)

    g["nodes"] = [_vote("va", "failed") if n["id"] == "va" else n for n in g["nodes"]]
    rbd, _, gates, _, broken = ra._build_repairable_rbd(g)
    assert "va" in gates and broken == {"va"} and "va" not in rbd._junctions()
    res = ra.analyze_availability(g, simulate=False)
    assert res["steady_state_availability"] == pytest.approx(0.0, abs=1e-12)
    assert "va" not in res["importance"]
    assert fault_tree(g)["unavailability"] == pytest.approx(1.0, abs=1e-12)


def test_crews_chain_covers_only_the_blocks_around_mid_diagram_votes():
    res = ra.analyze_availability(_two_votes(repair_crews={"crews": 2}), n_simulations=N)
    assert res["long_run_method"]["route"] == "exact"
    direct = _direct()
    crewed = RepairableRBD(direct._init_args["edges"], direct._init_args["components"],
                           k={"va": 2, "vb": 2}, input_node="s", output_node="t", repair_crews=2)
    assert res["steady_state_availability"] == pytest.approx(crewed.mean_availability(), rel=1e-9)
    assert res["repair_crews"]["jobs"] == 6


def test_export_gives_the_app_numbers_with_junctions(tmp_path):
    g = _two_votes()
    code = rbd_export.to_python(g, "Two votes", exported_at=WHEN)
    assert '"va": PerfectReliability,' in code and '"vb": PerfectReliability,' in code
    assert "pinned_stand_in" not in code and "WORKING_NODES = set()" in code
    out, _ = _run(code, tmp_path, n_sims="20")
    app = ra.analyze_availability(g, simulate=False)
    assert out["steady_state_availability"] == pytest.approx(app["steady_state_availability"], rel=1e-12)
    assert out["mean_up_time"] == pytest.approx(app["mean_up_time"], rel=1e-12)
    assert set(out["blocks"]) == {f"{s}{j}" for s in "ab" for j in (1, 2, 3)}


def test_repyability_json_keeps_the_junctions():
    from repyability.rbd.serialisation import rbd_from_dict

    doc = rbd_json.core(_two_votes())[0]
    rbd = rbd_from_dict(doc)
    assert rbd._junctions() == {"va", "vb"}
    assert rbd.mean_availability() == pytest.approx(EXPECTED, rel=1e-12)


def test_export_keeps_a_vote_pinned_failed_as_a_broken_stand_in(tmp_path):
    g = _two_votes()
    g["nodes"] = [_vote("vb", "failed") if n["id"] == "vb" else n for n in g["nodes"]]
    code = rbd_export.to_python(g, "Vote down", exported_at=WHEN)
    assert '"vb": pinned_stand_in(),' in code and 'BROKEN_NODES = {"vb"}' in code
    assert '"va": PerfectReliability,' in code


# ---------------------------------------------------------------------------
# MCP: create_rbd / edit_rbd take a vote mid-diagram in a repairable diagram
# ---------------------------------------------------------------------------
def _mcp_nodes():
    exp_a = {"distribution_id": "exponential", "params": [{"name": "failure_rate", "value": LAM_A}]}
    exp_b = {"distribution_id": "exponential", "params": [{"name": "failure_rate", "value": LAM_B}]}
    rep = {"distribution_id": "exponential", "params": [{"name": "failure_rate", "value": MU}]}
    nodes = [{"id": "input", "type": "input"}, {"id": "output", "type": "output"},
             {"id": "va", "type": "knode", "label": "2oo3 A", "n": 2, "k": 3},
             {"id": "vb", "type": "knode", "label": "2oo3 B", "n": 2, "k": 3}]
    edges = []
    for stage, model, src, vote in (("a", exp_a, "input", "va"), ("b", exp_b, "va", "vb")):
        for j in (1, 2, 3):
            nid = f"{stage}{j}"
            nodes.append({"id": nid, "type": "component", "label": nid.upper(), "model": model, "repair": rep})
            edges += [{"source": src, "target": nid}, {"source": nid, "target": vote}]
    edges.append({"source": "vb", "target": "output"})
    return nodes, edges


def test_mcp_create_and_analyse_a_repairable_rbd_with_a_mid_diagram_vote(env):
    nodes, edges = _mcp_nodes()
    out = _ok(_call(env.token[A], "create_rbd", {"name": "Two votes", "unit": "Hours", "repairable": True,
                                                 "nodes": nodes, "edges": edges}))
    res = _ok(_call(env.token[A], "analyze_rbd", {"rbd_id": out["id"]}))
    assert res["steady_state_availability"] == pytest.approx(EXPECTED, rel=1e-9)


def test_mcp_edit_rbd_adds_a_vote_mid_diagram(env):
    # Start with stage A in plain parallel, then vote 2-of-3 on it with edit_rbd.
    nodes, edges = _mcp_nodes()
    nodes = [n for n in nodes if n["id"] != "va"]
    edges = [e for e in edges if "va" not in (e["source"], e["target"])]
    edges += [{"source": f"a{j}", "target": f"b{i}"} for j in (1, 2, 3) for i in (1, 2, 3)]
    rid = _ok(_call(env.token[A], "create_rbd", {"name": "One vote", "unit": "Hours", "repairable": True,
                                                 "nodes": nodes, "edges": edges}))["id"]
    ops = [{"op": "remove_edge", "source": f"a{j}", "target": f"b{i}"} for j in (1, 2, 3) for i in (1, 2, 3)]
    ops.append({"op": "add_node", "node": {"id": "va", "type": "knode", "label": "2oo3 A", "n": 2, "k": 3}})
    ops += [{"op": "add_edge", "source": f"a{j}", "target": "va"} for j in (1, 2, 3)]
    ops += [{"op": "add_edge", "source": "va", "target": f"b{i}"} for i in (1, 2, 3)]
    _ok(_call(env.token[A], "edit_rbd", {"rbd_id": rid, "ops": ops}))
    res = _ok(_call(env.token[A], "analyze_rbd", {"rbd_id": rid}))
    assert res["steady_state_availability"] == pytest.approx(EXPECTED, rel=1e-9)
