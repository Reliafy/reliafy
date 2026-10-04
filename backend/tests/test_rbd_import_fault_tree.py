"""Fault tree -> RBD conversion (backend/services/rbd_import/fault_tree.py).

The core property: for every coherent tree, the produced graph's
path-connectivity equals the tree's structure function for every combination
of component states. Checked exhaustively on random trees — including trees
with repeated events (one basic event under several gates, directly or through
a shared gate), whose extra appearances are repeated blocks (``repeat_of``):
the same component, failed wherever it is drawn.
"""

import itertools
import random

import numpy as np
import pytest

from backend.services.rbd_graph import normalize_graph
from backend.services.rbd_import import fault_tree as ft
from backend.services.rbd_import.types import RbdImportError


# ---------------------------------------------------------------------------
# Reference semantics
# ---------------------------------------------------------------------------


def tree_fails(tree: ft.FaultTree, failed: set[str], name: str | None = None) -> bool:
    """Direct evaluation of the fault tree: does the top event occur?"""
    node = tree.nodes[name or tree.top]
    if isinstance(node, ft.Leaf):
        return node.constant if node.constant is not None else node.name in failed
    kids = [tree_fails(tree, failed, c) for c in node.children]
    need = {"or": 1, "and": len(kids)}.get(node.op, node.k)
    return sum(kids) >= need


def graph_works(graph: dict, failed_ids: set[str]) -> bool:
    """Path semantics of a compact graph: a block passes if it works and at
    least one predecessor passes; a knode passes if ≥ n predecessors pass."""
    nodes = {n["id"]: n for n in graph["nodes"]}
    preds: dict[str, list[str]] = {nid: [] for nid in nodes}
    succ: dict[str, list[str]] = {nid: [] for nid in nodes}
    for e in graph["edges"]:
        preds[e["target"]].append(e["source"])
        succ[e["source"]].append(e["target"])
    indeg = {nid: len(p) for nid, p in preds.items()}
    order, queue = [], [nid for nid, d in indeg.items() if d == 0]
    while queue:
        nid = queue.pop()
        order.append(nid)
        for t in succ[nid]:
            indeg[t] -= 1
            if indeg[t] == 0:
                queue.append(t)
    assert len(order) == len(nodes), "graph has a cycle"
    passes: dict[str, bool] = {}
    for nid in order:
        node = nodes[nid]
        up = sum(passes[p] for p in preds[nid])
        if node["type"] == "input":
            passes[nid] = True
        elif node["type"] == "knode":
            passes[nid] = up >= node["n"]
        else:
            # A repeated block is the component it repeats.
            comp = node.get("repeat_of") or nid
            passes[nid] = up >= 1 and comp not in failed_ids
    return passes["output"]


def leaf_id_map(graph: dict) -> dict[str, str]:
    """Event name -> its block (the original, never a repeated block)."""
    return {n["label"]: n["id"] for n in graph["nodes"]
            if n["type"] == "component" and not n.get("repeat_of")}


def check_structure(tree: ft.FaultTree):
    graph, _ = ft.to_graph(tree)
    ids = leaf_id_map(graph)
    events = sorted(n for n, v in tree.nodes.items() if isinstance(v, ft.Leaf) and v.constant is None)
    # Every knode's k is its true number of incoming branches.
    incoming: dict[str, int] = {}
    for e in graph["edges"]:
        incoming[e["target"]] = incoming.get(e["target"], 0) + 1
    for n in graph["nodes"]:
        if n["type"] == "knode":
            assert n["k"] == incoming[n["id"]]
            assert 1 <= n["n"] <= n["k"]
    # A repeated block repeats an original block of the same event.
    originals = {n["id"]: n for n in graph["nodes"] if not n.get("repeat_of")}
    for n in graph["nodes"]:
        if n.get("repeat_of"):
            assert originals[n["repeat_of"]]["label"] == n["label"]
            assert "model" not in n
    for bits in itertools.product((False, True), repeat=len(events)):
        failed = {e for e, b in zip(events, bits) if b}
        failed_ids = {ids[e] for e in failed if e in ids}
        assert graph_works(graph, failed_ids) == (not tree_fails(tree, failed)), failed
    return graph


# ---------------------------------------------------------------------------
# Random coherent trees
# ---------------------------------------------------------------------------


def _component():
    return {"type": "component", "model": ft.exponential_model(0.01)}


def random_tree(rng: random.Random, n_leaves: int, constants: bool = False,
                repeats: bool = False) -> ft.FaultTree:
    """A random coherent tree. With ``repeats``, gates also take extra inputs
    already used elsewhere — a basic event or an earlier gate (a shared
    sub-tree) — so events repeat. Earlier gates can't reach the new one, so
    the tree stays acyclic."""
    nodes: dict[str, ft.Leaf | ft.Gate] = {}
    pool = []
    for i in range(n_leaves):
        name = f"E{i}"
        nodes[name] = ft.Leaf(name, _component())
        pool.append(name)
    if constants:
        for i in range(rng.randint(1, 2)):
            name = f"H{i}"
            nodes[name] = ft.Leaf(name, constant=rng.random() < 0.5)
            pool.append(name)
    rng.shuffle(pool)
    g = 0
    while len(pool) > 1:
        size = min(len(pool), rng.randint(2, 4))
        kids = [pool.pop() for _ in range(size)]
        if repeats:
            used = [n for n in nodes if n not in kids and n not in pool]
            for _ in range(rng.randint(0, 2)):
                if used:
                    kids.append(used.pop(rng.randrange(len(used))))
            size = len(kids)
        op = rng.choice(["or", "and", "atleast"])
        k = rng.randint(1, size) if op == "atleast" else None
        name = f"G{g}"
        g += 1
        nodes[name] = ft.Gate(name, op, kids, k)
        pool.insert(rng.randint(0, len(pool)), name)
    return ft.FaultTree(nodes, pool[0])


@pytest.mark.parametrize("seed", range(120))
def test_random_trees_match_structure_function(seed):
    rng = random.Random(seed)
    tree = random_tree(rng, rng.randint(2, 9), constants=seed % 4 == 0)
    try:
        check_structure(tree)
    except RbdImportError as exc:
        # Only legitimate refusals: the constants made the top certain/impossible.
        assert "certainly occurred" in str(exc) or "can never occur" in str(exc)
        states = [tree_fails(tree, set(), None), tree_fails(tree, set(tree.nodes), None)]
        assert states[0] == states[1]


def test_junction_threshold_paths_also_match(monkeypatch):
    # Force junctions everywhere, and never — both must preserve the logic.
    for threshold in (0, 10**6):
        monkeypatch.setattr(ft, "JUNCTION_THRESHOLD", threshold)
        for seed in range(30):
            rng = random.Random(1000 + seed)
            check_structure(random_tree(rng, rng.randint(3, 8)))


def test_series_of_parallels_uses_direct_edges_then_junction(monkeypatch):
    leaves = {f"{p}{i}": ft.Leaf(f"{p}{i}", _component()) for p in "AB" for i in range(5)}
    tree = ft.FaultTree({
        **leaves,
        "PA": ft.Gate("PA", "and", [f"A{i}" for i in range(5)]),
        "PB": ft.Gate("PB", "and", [f"B{i}" for i in range(5)]),
        "TOP": ft.Gate("TOP", "or", ["PA", "PB"]),
    }, "TOP")
    graph = check_structure(tree)  # 5x5 > threshold -> one junction
    assert sum(n["type"] == "knode" for n in graph["nodes"]) == 1
    monkeypatch.setattr(ft, "JUNCTION_THRESHOLD", 25)
    graph = check_structure(tree)
    assert not any(n["type"] == "knode" for n in graph["nodes"])


def test_repairable_diagrams_wire_directly_instead_of_junctions():
    # Availability analysis treats every knode as a component; junctions
    # there would add unavailability, so a repairable import avoids them.
    leaves = {f"{p}{i}": ft.Leaf(f"{p}{i}", _component()) for p in "AB" for i in range(5)}
    tree = ft.FaultTree({
        **leaves,
        "PA": ft.Gate("PA", "and", [f"A{i}" for i in range(5)]),
        "PB": ft.Gate("PB", "and", [f"B{i}" for i in range(5)]),
        "TOP": ft.Gate("TOP", "or", ["PA", "PB"]),
    }, "TOP")
    graph, _ = ft.to_graph(tree, repairable=True)
    assert graph["repairable"] is True
    assert not any(n["type"] == "knode" for n in graph["nodes"])
    assert len(graph["edges"]) == 5 + 25 + 5


def test_voting_gate_maps_to_knode_requiring_n_minus_m_plus_1():
    leaves = {f"P{i}": ft.Leaf(f"P{i}", _component()) for i in range(3)}
    tree = ft.FaultTree({**leaves, "V": ft.Gate("V", "atleast", list(leaves), 2)}, "V")
    graph = check_structure(tree)
    (k,) = [n for n in graph["nodes"] if n["type"] == "knode"]
    assert (k["n"], k["k"], k["label"]) == (2, 3, "V")


def test_voting_over_subtrees_collapses_multi_exit_children():
    # 2-of-3 failed where one child is itself a parallel pair (two exits).
    nodes = {n: ft.Leaf(n, _component()) for n in ("A", "B", "C", "D")}
    nodes["AB"] = ft.Gate("AB", "and", ["A", "B"])
    nodes["V"] = ft.Gate("V", "atleast", ["AB", "C", "D"], 2)
    graph = check_structure(ft.FaultTree(nodes, "V"))
    knodes = {n["label"]: n for n in graph["nodes"] if n["type"] == "knode"}
    assert knodes["V"]["k"] == 3 and knodes["Junction"]["n"] == 1


@pytest.mark.parametrize("seed", range(120))
def test_random_trees_with_repeated_events_match_structure_function(seed):
    rng = random.Random(5000 + seed)
    tree = random_tree(rng, rng.randint(2, 8), constants=seed % 5 == 0, repeats=True)
    try:
        check_structure(tree)
    except RbdImportError as exc:
        assert "certainly occurred" in str(exc) or "can never occur" in str(exc)


def test_repeated_event_becomes_a_repeated_block():
    nodes = {n: ft.Leaf(n, _component()) for n in ("A", "B", "C")}
    nodes["G1"] = ft.Gate("G1", "and", ["A", "B"])
    nodes["G2"] = ft.Gate("G2", "and", ["A", "C"])
    nodes["TOP"] = ft.Gate("TOP", "or", ["G1", "G2"])
    tree = ft.FaultTree(nodes, "TOP")
    assert ft.repeated_events(tree) == ["A"]
    graph = check_structure(tree)
    (copy,) = [n for n in graph["nodes"] if n.get("repeat_of")]
    assert copy["repeat_of"] == leaf_id_map(graph)["A"] and copy["label"] == "A"
    _, warnings = ft.to_graph(tree)
    assert any("“A”" in w and "repeated block" in w for w in warnings)


def test_repeated_events_make_a_repairable_tree_non_repairable():
    comp = {"type": "component", "model": ft.exponential_model(0.01),
            "repair": ft.exponential_model(1.0)}
    nodes = {n: ft.Leaf(n, dict(comp)) for n in ("A", "B", "C")}
    nodes["G1"] = ft.Gate("G1", "and", ["A", "B"])
    nodes["G2"] = ft.Gate("G2", "and", ["A", "C"])
    nodes["TOP"] = ft.Gate("TOP", "or", ["G1", "G2"])
    graph, warnings = ft.to_graph(ft.FaultTree(nodes, "TOP"), repairable=True)
    assert "repairable" not in graph
    assert not any("repair" in n for n in graph["nodes"])
    assert any("non-repairable" in w for w in warnings)
    # The tree's own leaves are left untouched.
    assert all("repair" in nodes[n].node for n in ("A", "B", "C"))


def test_repeated_non_component_leaf_is_refused():
    standby = {"type": "standby", "model": ft.exponential_model(0.01), "spares": 1, "cold": True}
    nodes = {"S": ft.Leaf("S", standby), "B": ft.Leaf("B", _component()),
             "C": ft.Leaf("C", _component())}
    nodes["G1"] = ft.Gate("G1", "and", ["S", "B"])
    nodes["G2"] = ft.Gate("G2", "and", ["S", "C"])
    nodes["TOP"] = ft.Gate("TOP", "or", ["G1", "G2"])
    with pytest.raises(RbdImportError, match="“S”.*more than one gate"):
        ft.to_graph(ft.FaultTree(nodes, "TOP"))


@pytest.mark.parametrize("seed", range(12))
def test_repeated_event_trees_analyse_to_the_exact_probability(seed):
    """End to end: the imported diagram's reliability (RePyability's exact
    engine, repeated blocks as one component) equals the tree's top-event
    probability enumerated over every combination of event states."""
    from backend.services import rbd_analysis

    rng = random.Random(9000 + seed)
    tree = random_tree(rng, rng.randint(3, 7), repeats=True)
    events = sorted(n for n, v in tree.nodes.items() if isinstance(v, ft.Leaf))
    rates = {e: rng.uniform(0.2, 3.0) for e in events}
    for e in events:
        tree.nodes[e].node = {"type": "component", "model": ft.exponential_model(rates[e])}
    graph, _ = ft.to_graph(tree)
    t = 0.4
    res = rbd_analysis.analyze(normalize_graph(graph), t_max=2 * t)
    i = int(np.argmin(np.abs(np.asarray(res["time"]) - t)))
    t = res["time"][i]
    q = {e: 1 - np.exp(-rates[e] * t) for e in events}
    expected = 0.0
    for bits in itertools.product((False, True), repeat=len(events)):
        failed = {e for e, b in zip(events, bits) if b}
        if not tree_fails(tree, failed):
            p = 1.0
            for e in events:
                p *= q[e] if e in failed else 1 - q[e]
            expected += p
    assert res["system"]["sf"][i] == pytest.approx(expected, rel=1e-9, abs=1e-12)
    # Results are per component: one importance row per event, not per block.
    assert set(res["importance"]["birnbaum"]) <= set(leaf_id_map(graph).values())


def test_shared_gate_repeats_all_its_events():
    nodes = {n: ft.Leaf(n, _component()) for n in ("A", "B", "C", "D")}
    nodes["S"] = ft.Gate("S", "or", ["A", "B"])
    nodes["G1"] = ft.Gate("G1", "and", ["S", "C"])
    nodes["G2"] = ft.Gate("G2", "and", ["S", "D"])
    nodes["TOP"] = ft.Gate("TOP", "or", ["G1", "G2"])
    assert ft.repeated_events(ft.FaultTree(nodes, "TOP")) == ["A", "B"]


def test_repeat_hidden_by_a_constant_is_not_a_repeat():
    # G2 = AND(A, never) can never fail, so A is effectively used once.
    nodes = {n: ft.Leaf(n, _component()) for n in ("A", "B")}
    nodes["NEVER"] = ft.Leaf("NEVER", constant=False)
    nodes["G1"] = ft.Gate("G1", "or", ["A", "B"])
    nodes["G2"] = ft.Gate("G2", "and", ["A", "NEVER"])
    nodes["TOP"] = ft.Gate("TOP", "or", ["G1", "G2"])
    graph = check_structure(ft.FaultTree(nodes, "TOP"))
    assert len(leaf_id_map(graph)) == 2


def test_constant_true_reduces_voting_threshold():
    nodes = {n: ft.Leaf(n, _component()) for n in ("A", "B", "C")}
    nodes["T"] = ft.Leaf("T", constant=True)
    nodes["V"] = ft.Gate("V", "atleast", ["A", "B", "C", "T"], 3)  # -> 2 of A,B,C failed
    graph = check_structure(ft.FaultTree(nodes, "V"))
    (k,) = [n for n in graph["nodes"] if n["type"] == "knode"]
    assert (k["n"], k["k"]) == (2, 3)


def test_top_certain_or_impossible_is_refused():
    nodes = {"A": ft.Leaf("A", _component()), "T": ft.Leaf("T", constant=True),
             "F": ft.Leaf("F", constant=False)}
    with pytest.raises(RbdImportError, match="certainly occurred"):
        ft.to_graph(ft.FaultTree({**nodes, "G": ft.Gate("G", "or", ["A", "T"])}, "G"))
    with pytest.raises(RbdImportError, match="can never occur"):
        ft.to_graph(ft.FaultTree({**nodes, "G": ft.Gate("G", "and", ["A", "F"])}, "G"))


def test_loops_undefined_and_depth_are_refused(monkeypatch):
    a = ft.Leaf("A", _component())
    with pytest.raises(RbdImportError, match="loop"):
        ft.to_graph(ft.FaultTree({"A": a, "G": ft.Gate("G", "or", ["A", "H"]),
                                  "H": ft.Gate("H", "and", ["G", "A"])}, "G"))
    with pytest.raises(RbdImportError, match="never defined"):
        ft.to_graph(ft.FaultTree({"G": ft.Gate("G", "or", ["X", "Y"])}, "G"))
    nodes = {"A": a, "B": ft.Leaf("B", _component())}
    prev = "A"
    for i in range(ft.MAX_DEPTH + 5):
        nodes[f"G{i}"] = ft.Gate(f"G{i}", "or", [prev, "B"] if i == 0 else [prev])
        prev = f"G{i}"
    with pytest.raises(RbdImportError, match="deep"):
        ft.to_graph(ft.FaultTree(nodes, prev))


def test_graph_normalises_and_analyses_to_the_exact_answer():
    """HIPPS-shaped tree with exponential events: Reliafy's analysis of the
    imported graph equals the closed form."""
    from backend.services import rbd_analysis

    lam = {"LS": 1e-6, "P1": 7e-7, "P2": 7e-7, "P3": 7e-7, "SV1": 2.6e-6, "SDV1": 4.1e-6}
    nodes = {n: ft.Leaf(n, {"type": "component", "model": ft.exponential_model(r)}) for n, r in lam.items()}
    nodes["PSH"] = ft.Gate("PSH", "atleast", ["P1", "P2", "P3"], 2)
    nodes["W1"] = ft.Gate("W1", "or", ["SV1", "SDV1"])
    nodes["TOP"] = ft.Gate("TOP", "or", ["LS", "PSH", "W1"])
    graph, _ = ft.to_graph(ft.FaultTree(nodes, "TOP"), unit="hours")
    res = rbd_analysis.analyze(normalize_graph(graph), t_max=1e5)
    t = np.asarray(res["time"])
    r = np.exp(-lam["P1"] * t)
    r_vote = 3 * r**2 - 2 * r**3
    expected = np.exp(-(lam["LS"] + lam["SV1"] + lam["SDV1"]) * t) * r_vote
    assert np.allclose(res["system"]["sf"], expected, rtol=1e-9, atol=1e-12)


def test_ccf_groups_are_translated_to_node_ids():
    nodes = {n: ft.Leaf(n, _component()) for n in ("A B", "C")}
    nodes["G"] = ft.Gate("G", "and", ["A B", "C"])
    graph, warnings = ft.to_graph(
        ft.FaultTree(nodes, "G"),
        ccf_groups=[{"name": "g", "members": ["A B", "C"], "beta": 0.1},
                    {"name": "lonely", "members": ["C", "missing"], "beta": 0.2}])
    ids = leaf_id_map(graph)
    assert graph["ccf_groups"] == [{"members": [ids["A B"], ids["C"]], "beta": 0.1}]
    assert any("lonely" in w for w in warnings)
    normalize_graph(graph)
