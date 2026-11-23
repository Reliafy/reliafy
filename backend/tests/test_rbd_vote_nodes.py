"""k-of-n vote nodes are checked against the inputs wired into them, by one check, for the
builder's badge, Calculate, the API, MCP and import alike: needing more working inputs than are
wired in is refused, naming the node; needing all of two or more is valid but said (it adds no
redundancy, so it acts as series)."""

import numpy as np
import pytest
from fastapi.testclient import TestClient

from backend import config
from backend.services import rbd_analysis as ra
from backend.services.rbd_analysis import AnalysisError, analyze, validate_graph
from backend.tests.test_mcp import A, _call, _err, _ok, env  # noqa: F401 - env is a fixture

RATE = 0.01


def _comp(nid, label):
    return {"id": nid, "type": "component", "data": {"label": label, "model": {
        "source": "params", "distribution_id": "exponential", "distribution": "Exponential",
        "params": [{"name": "failure_rate", "value": RATE}]}}}


def _e(s, t):
    return {"id": f"{s}-{t}", "source": s, "target": t}


def _pair(need, wired=2, label="Logic"):
    """Two blocks in parallel into a vote node needing ``need``; ``wired`` of them wired into it
    (the other leads straight to the output)."""
    nodes = [{"id": "input", "type": "input", "data": {}}, {"id": "output", "type": "output", "data": {}},
             _comp("a", "Logic 1"), _comp("b", "Logic 2"),
             {"id": "v", "type": "knode", "data": {"label": label, "n": need, "k": 2}}]
    edges = [_e("input", "a"), _e("input", "b"), _e("a", "v"), _e("v", "output")]
    edges.append(_e("b", "v") if wired == 2 else _e("b", "output"))
    return {"nodes": nodes, "edges": edges}


def _two_of_one():
    """A 2-of-n vote node with one input, in series with a block."""
    nodes = [{"id": "input", "type": "input", "data": {}}, {"id": "output", "type": "output", "data": {}},
             _comp("a", "Workstation 1"),
             {"id": "v", "type": "knode", "data": {"label": "Workstations", "n": 2, "k": 3}}]
    return {"nodes": nodes, "edges": [_e("input", "a"), _e("a", "v"), _e("v", "output")]}


MSG_2_OF_1 = "Vote node “Workstations” needs at least 2 inputs for 2-of-n; it has 1"
MSG_2_OF_2 = "“Logic” is 2 of 2: both must work, so this pair adds no redundancy. Did you mean 1 of 2?"


# ---- more needed than wired: refused, naming the node -----------------------------------

def test_needing_more_inputs_than_wired_is_refused_with_the_node_named():
    check = validate_graph(_two_of_one())
    assert check["valid"] is False and check["can_calculate"] is False
    assert any(MSG_2_OF_1 in e for e in check["errors"])
    assert check["vote_nodes"] == [{"id": "v", "label": "Workstations", "inputs": 1, "need": 2, "kind": "too_many",
                                    "message": check["vote_nodes"][0]["message"]}]
    with pytest.raises(AnalysisError, match="needs at least 2 inputs for 2-of-n; it has 1"):
        analyze(_two_of_one())


def test_the_declared_total_on_the_node_is_never_trusted():
    # "2 of 3" typed on the node, but one input wired: the wiring decides.
    graph = _two_of_one()
    assert graph["nodes"][-1]["data"]["k"] == 3
    assert not validate_graph(graph)["can_calculate"]


def test_a_vote_node_with_nothing_wired_in_says_so():
    notes = ra.vote_node_notes([{"id": "v", "type": "knode", "data": {"n": 2}}], [("v", "output")])
    assert notes[0]["kind"] == "too_many" and "nothing is wired into it" in notes[0]["message"]


# ---- all of two or more: valid, series, and said ----------------------------------------

def test_needing_all_inputs_is_valid_but_warned_and_acts_as_series():
    graph = _pair(2)
    check = validate_graph(graph)
    assert check["can_calculate"] is True
    assert MSG_2_OF_2 in check["warnings"]
    assert [v["kind"] for v in check["vote_nodes"]] == ["all_must_work"]

    result = analyze(graph)
    assert MSG_2_OF_2 in result["warnings"]  # in the result's assumptions too
    t = np.asarray(result["time"], dtype=float)
    got = np.asarray(result["system"]["sf"], dtype=float)
    assert np.allclose(got, np.exp(-2 * RATE * t), atol=1e-9)  # two in series


def test_one_of_two_is_redundancy_with_no_note():
    graph = _pair(1)
    check = validate_graph(graph)
    assert check["can_calculate"] is True and "vote_nodes" not in check
    result = analyze(graph)
    assert not any("redundancy" in w for w in result.get("warnings") or [])
    t = np.asarray(result["time"], dtype=float)
    r = np.exp(-RATE * t)
    assert np.allclose(np.asarray(result["system"]["sf"], dtype=float), 1 - (1 - r) ** 2, atol=1e-9)


def test_three_of_three_is_warned_in_general_words():
    assert ra.all_must_work_message("Pumps", 3) == (
        "“Pumps” is 3 of 3: all 3 must work, so it adds no redundancy (it acts as series). "
        "Did you mean fewer, such as 1 of 3?")


def test_a_one_input_pass_through_is_allowed_but_flagged():
    graph = _pair(1, wired=1)
    check = validate_graph(graph)
    assert check["can_calculate"] is True
    assert any("has one input and needs 1, so it does nothing" in w for w in check["warnings"])
    assert [v["kind"] for v in check["vote_nodes"]] == ["pass_through"]


def test_a_one_input_junction_that_fans_out_is_not_flagged():
    nodes = [{"id": "input", "type": "input", "data": {}}, {"id": "output", "type": "output", "data": {}},
             _comp("a", "A"), _comp("b", "B"), {"id": "j", "type": "knode", "data": {"n": 1}}]
    edges = [("input", "j"), ("j", "a"), ("j", "b"), ("a", "output"), ("b", "output")]
    assert ra.vote_node_notes(nodes, edges) == []


# ---- the API, MCP and import run the same check -----------------------------------------

@pytest.fixture()
def client(monkeypatch):
    monkeypatch.setattr(config, "AUTH_DISABLED", True)
    from backend.main import app

    return TestClient(app)


def test_api_validate_and_analyze(client):
    check = client.post("/api/rbds/validate", json={"graph": _two_of_one()}).json()
    assert not check["can_calculate"] and any(MSG_2_OF_1 in e for e in check["errors"])
    r = client.post("/api/rbds/analyze", json={"graph": _two_of_one()})
    assert r.status_code >= 400 and MSG_2_OF_1 in r.text

    check = client.post("/api/rbds/validate", json={"graph": _pair(2)}).json()
    assert check["can_calculate"] and MSG_2_OF_2 in check["warnings"]
    r = client.post("/api/rbds/analyze", json={"graph": _pair(2)})
    assert r.status_code == 200, r.text
    assert MSG_2_OF_2 in r.json()["warnings"]


def _compact(graph):
    nodes = []
    for n in graph["nodes"]:
        d = n.get("data") or {}
        node = {"id": n["id"], "type": n["type"]}
        if n["type"] == "component":
            node.update(label=d["label"], model={"distribution_id": "exponential",
                                                  "params": [{"name": "failure_rate", "value": RATE}]})
        elif n["type"] == "knode":
            node.update(label=d.get("label"), n=d["n"])
        nodes.append(node)
    return {"nodes": nodes, "edges": [{"source": e["source"], "target": e["target"]} for e in graph["edges"]]}


@pytest.mark.usefixtures("mcp_on")
def test_mcp_create_and_analyse(env):
    msg = _err(_call(env.token[A], "change", {"action": "rbd_create", "name": "Two of one", **_compact(_two_of_one())}))
    assert MSG_2_OF_1 in msg

    made = _ok(_call(env.token[A], "change", {"action": "rbd_create", "name": "Pair", **_compact(_pair(2))}))
    assert MSG_2_OF_2 in made["warnings"]
    out = _ok(_call(env.token[A], "analyse", {"action": "rbd", "rbd_id": made["id"]}))
    assert MSG_2_OF_2 in str(out)


def test_import_says_so_without_changing_the_file():
    from backend.services.rbd_import import note_vote_nodes
    from backend.services.rbd_import.types import ImportedDiagram

    diagrams = [ImportedDiagram(name="Two of one", graph=_compact(_two_of_one())),
                ImportedDiagram(name="Pair", graph=_compact(_pair(2)))]
    note_vote_nodes(diagrams)
    assert any(MSG_2_OF_1 in w for w in diagrams[0].warnings)
    assert MSG_2_OF_2 in diagrams[1].warnings
    assert next(n for n in diagrams[0].graph["nodes"] if n["id"] == "v")["n"] == 2  # unchanged
