"""Redundancy design (#98): how many copies of each block, within budgets.

Small systems whose optimum is checked by brute force, budgets respected, a
non-dominated and sorted trade-off curve, clear refusals, and designs written
back onto the diagram that analyse to the reliability the search reported.
"""

import copy
import itertools
import time
import math

import mongomock
import pytest

from backend.services import rbd_design as rd
from backend.services.rbd_design import DesignError

T = 100.0


def _exp(rate):
    return {
        "source": "params", "distribution": "Exponential", "distribution_id": "exponential",
        "params": [{"name": "failure_rate", "value": rate}],
    }


def _weibull(alpha, beta):
    return {
        "source": "params", "distribution": "Weibull", "distribution_id": "weibull",
        "params": [{"name": "alpha", "value": alpha}, {"name": "beta", "value": beta}],
    }


def _node(nid, model, ntype="component", x=0, y=0, **data):
    return {"id": nid, "type": ntype, "position": {"x": x, "y": y},
            "data": {"label": nid.title(), "model": model, **data}}


def _io():
    return [
        {"id": "input", "type": "input", "position": {"x": 0, "y": 0}, "data": {"label": "Input"}},
        {"id": "output", "type": "output", "position": {"x": 900, "y": 0}, "data": {"label": "Output"}},
    ]


def _edges(*pairs):
    return [{"id": f"{s}-{t}", "source": s, "target": t} for s, t in pairs]


def _series(rates=(0.001, 0.002)):
    """input -> a -> b -> output, exponential blocks."""
    ids = ["a", "b", "c"][: len(rates)]
    nodes = _io() + [_node(i, _exp(r), x=200 * (j + 1)) for j, (i, r) in enumerate(zip(ids, rates))]
    chain = ["input", *ids, "output"]
    return {"nodes": nodes, "edges": _edges(*zip(chain, chain[1:])), "unit": "hours"}


def _bridge_free():
    """input -> ctrl -> {pumpA | pumpB} -> output: pumps not in series."""
    nodes = _io() + [
        _node("ctrl", _exp(0.001), x=200),
        _node("pumpA", _exp(0.004), x=400, y=-80),
        _node("pumpB", _exp(0.003), x=400, y=80),
    ]
    edges = _edges(("input", "ctrl"), ("ctrl", "pumpA"), ("ctrl", "pumpB"),
                   ("pumpA", "output"), ("pumpB", "output"))
    return {"nodes": nodes, "edges": edges, "unit": "hours"}


def _p(rate, t=T):
    return math.exp(-rate * t)


def _active(p, n, k=1):
    """P(at least k of n copies of reliability p work)."""
    return sum(math.comb(n, j) * p**j * (1 - p) ** (n - j) for j in range(k, n + 1))


def _block(bid, cost, max_copies=4, **extra):
    return {"id": bid, "cost": cost, "max_copies": max_copies, **extra}


# ---------------------------------------------------------------------------
# The optimum, checked by brute force
# ---------------------------------------------------------------------------
def test_series_budget_optimum_matches_brute_force():
    graph = _series((0.002, 0.004))
    costs = {"a": 3.0, "b": 2.0}
    res = rd.design_redundancy(
        graph, T, [_block("a", 3), _block("b", 2)], budget={"cost": 13}
    )
    best = max(
        (
            _active(_p(0.002), na) * _active(_p(0.004), nb), -(3 * na + 2 * nb), na, nb
        )
        for na, nb in itertools.product(range(1, 5), repeat=2)
        if costs["a"] * na + costs["b"] * nb <= 13
    )
    d = res["design"]
    assert d["reliability"] == pytest.approx(best[0], rel=1e-9)
    copies = {b["id"]: b["copies"] for b in d["blocks"]}
    assert (copies["a"], copies["b"]) == (best[2], best[3])
    assert d["cost"] <= 13
    assert res["mode"] == "budget" and res["method"] == "exact"
    # The diagram as drawn: one of each.
    assert res["current"]["reliability"] == pytest.approx(_p(0.002) * _p(0.004), rel=1e-9)
    assert res["current"]["cost"] == 5


def test_non_series_budget_and_target_match_brute_force():
    graph = _bridge_free()
    blocks = [_block("ctrl", 5, 3), _block("pumpA", 2, 3), _block("pumpB", 3, 3)]
    unit = {"ctrl": 5, "pumpA": 2, "pumpB": 3}

    def rel(nc, na, nb):
        pa, pb = _active(_p(0.004), na), _active(_p(0.003), nb)
        return _active(_p(0.001), nc) * (1 - (1 - pa) * (1 - pb))

    grid = [
        (rel(*n), 5 * n[0] + 2 * n[1] + 3 * n[2], n)
        for n in itertools.product(range(1, 4), repeat=3)
    ]
    res = rd.design_redundancy(graph, T, blocks, budget={"cost": 16})
    within = max(r for r, c, _ in grid if c <= 16)
    assert res["design"]["reliability"] == pytest.approx(within, rel=1e-9)
    assert res["design"]["cost"] <= 16

    res = rd.design_redundancy(graph, T, blocks, target=0.97)
    cheapest = min(c for r, c, _ in grid if r >= 0.97)
    assert res["mode"] == "target"
    assert res["design"]["cost"] == pytest.approx(cheapest)
    assert res["design"]["reliability"] >= 0.97
    assert sum(unit[b["id"]] * b["copies"] for b in res["design"]["blocks"]) == pytest.approx(cheapest)


def test_weight_limit_is_respected():
    graph = _series((0.002, 0.004))
    blocks = [_block("a", 1, weight=3), _block("b", 1, weight=1)]
    res = rd.design_redundancy(graph, T, blocks, budget={"cost": 6, "weight": 7})
    d = res["design"]
    assert res["resources"] == ["cost", "weight"]
    assert d["resources"]["cost"] <= 6 and d["resources"]["weight"] <= 7
    brute = max(
        _active(_p(0.002), na) * _active(_p(0.004), nb)
        for na, nb in itertools.product(range(1, 5), repeat=2)
        if na + nb <= 6 and 3 * na + nb <= 7
    )
    assert d["reliability"] == pytest.approx(brute, rel=1e-9)
    # Per-block use adds up to the total.
    assert sum(b["resources"]["weight"] for b in d["blocks"]) == pytest.approx(d["resources"]["weight"])


def test_component_types_can_mix_within_a_block():
    graph = _series((0.002, 0.01))
    premium = {"name": "Premium", "model": _exp(0.001), "cost": 2}
    blocks = [_block("a", 1), _block("b", 1, types=[premium])]
    res = rd.design_redundancy(graph, T, blocks, budget={"cost": 6})
    pa, pb, pp = _p(0.002), _p(0.01), _p(0.001)
    best = 0.0
    for na in range(1, 5):
        for ns, npr in itertools.product(range(0, 5), repeat=2):
            if 1 <= ns + npr <= 4 and na + ns + 2 * npr <= 6:
                rb = 1 - (1 - pb) ** ns * (1 - pp) ** npr
                best = max(best, _active(pa, na) * rb)
    assert res["design"]["reliability"] == pytest.approx(best, rel=1e-9)
    b = next(x for x in res["design"]["blocks"] if x["id"] == "b")
    assert sum(m["copies"] for m in b["mix"]) == b["copies"]
    assert {m["name"] for m in b["mix"]} <= {"Current", "Premium"}


def test_k_out_of_n_block_needs_k_working_copies():
    graph = _series((0.002,))
    res = rd.design_redundancy(graph, T, [_block("a", 1, 5, required=2)], budget={"cost": 4})
    b = res["design"]["blocks"][0]
    assert b["copies"] == 4 and b["required"] == 2
    assert res["design"]["reliability"] == pytest.approx(_active(_p(0.002), 4, 2), rel=1e-9)


def test_parallel_block_is_redesigned_from_one_unit():
    graph = _series((0.002,))
    graph["nodes"][2] = _node("a", _exp(0.002), "parallel", x=200, n=3, kind="parallel")
    res = rd.design_redundancy(graph, T, [_block("a", 1, 6)], budget={"cost": 5})
    assert res["current"]["cost"] == 3  # three units as drawn
    assert res["current"]["reliability"] == pytest.approx(_active(_p(0.002), 3), rel=1e-9)
    assert res["design"]["blocks"][0]["copies"] == 5


def test_what_if_pins_are_ignored():
    graph = _series((0.002, 0.004))
    graph["nodes"][2]["data"]["state"] = "failed"
    res = rd.design_redundancy(graph, T, [_block("a", 1), _block("b", 1)], budget={"cost": 2})
    assert res["current"]["reliability"] == pytest.approx(_p(0.002) * _p(0.004), rel=1e-9)


# ---------------------------------------------------------------------------
# The trade-off curve
# ---------------------------------------------------------------------------
def test_front_is_sorted_non_dominated_and_holds_the_optimum():
    graph = _bridge_free()
    blocks = [_block("ctrl", 5, 3), _block("pumpA", 2, 3), _block("pumpB", 3, 3)]
    res = rd.design_redundancy(graph, T, blocks, budget={"cost": 16})
    front = res["front"]
    assert len(front) >= 5
    costs = [d["cost"] for d in front]
    rels = [d["reliability"] for d in front]
    assert costs == sorted(costs)
    assert all(b > a for a, b in zip(rels, rels[1:]))  # strictly better as it costs more
    for d in front:
        assert not any(
            o["cost"] <= d["cost"] and o["reliability"] > d["reliability"] + 1e-12 for o in front
        )
    # Not limited by the cost budget: it shows what more money buys.
    assert costs[-1] > 16
    # The best design within the budget is on the curve.
    on_budget = max(d["reliability"] for d in front if d["cost"] <= 16)
    assert on_budget == pytest.approx(res["design"]["reliability"], rel=1e-12)
    # Each point is the best reliability for its cost (brute force).
    unit = {"ctrl": 5, "pumpA": 2, "pumpB": 3}
    for d in front:
        nc, na, nb = ({b["id"]: b["copies"] for b in d["blocks"]}[k] for k in ("ctrl", "pumpA", "pumpB"))
        assert unit["ctrl"] * nc + unit["pumpA"] * na + unit["pumpB"] * nb == pytest.approx(d["cost"])


def test_large_non_series_problems_use_greedy_and_a_sampled_curve(monkeypatch):
    # Pretend the problem is huge: the answer comes from the fast greedy
    # search, and the curve from the best design at each spending level.
    monkeypatch.setattr(rd, "EXACT_COMBINATIONS", 1)
    monkeypatch.setattr(rd, "FRONT_SEARCH_LIMIT", 1)
    graph = _bridge_free()
    blocks = [_block("ctrl", 5, 3), _block("pumpA", 2, 3), _block("pumpB", 3, 3)]
    res = rd.design_redundancy(graph, T, blocks, budget={"cost": 16})
    assert res["method"] == "greedy"
    assert res["design"]["cost"] <= 16
    assert "spending levels" in res["front_note"]
    rels = [d["reliability"] for d in res["front"]]
    assert len(rels) >= 3 and all(b > a for a, b in zip(rels, rels[1:]))
    monkeypatch.undo()
    best = rd.design_redundancy(graph, T, blocks, budget={"cost": 16})["design"]["reliability"]
    # A heuristic: near the proven optimum, never above it.
    assert best * 0.97 <= res["design"]["reliability"] <= best + 1e-12


@pytest.mark.parametrize("which", ["chains", "stages"])
def test_large_diagrams_stay_quick(which):
    # 20,736 minimal cut sets (too many to list), and 25 redundant stages
    # (3^25 combinations): both searched greedily, in seconds.
    from backend.tests.test_rbd_large_diagrams import _chains, _stages

    graph = _chains(4, 12) if which == "chains" else _stages(25)
    ids = [n["id"] for n in graph["nodes"] if n["type"] == "component"][: rd.MAX_BLOCKS]
    started = time.monotonic()
    res = rd.design_redundancy(graph, 200, [_block(i, 1, 3) for i in ids], budget={"cost": 1.5 * len(ids)})
    assert time.monotonic() - started < 15
    assert res["method"] == "greedy"
    assert res["design"]["cost"] <= 1.5 * len(ids)
    assert res["design"]["reliability"] >= res["current"]["reliability"]


def test_front_respects_weight_limits():
    graph = _series((0.002, 0.004))
    blocks = [_block("a", 1, weight=3), _block("b", 1, weight=1)]
    res = rd.design_redundancy(graph, T, blocks, budget={"cost": 6, "weight": 7})
    assert res["front"]
    assert all(d["resources"]["weight"] <= 7 + 1e-9 for d in res["front"])


# ---------------------------------------------------------------------------
# Refusals
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "mutate, blocks, kwargs, needle",
    [
        (lambda g: g.update(repairable=True), None, {}, "non-repairable"),
        (None, [], {}, "at least one block"),
        (None, [_block("zz", 1)], {}, "isn't in the diagram"),
        (None, [_block("a", 0)], {}, "unit cost"),
        (None, [_block("a", 1, 99)], {}, "most copies"),
        (None, [_block("a", 1, 3, required=2, strategy="cold")], {}, "one unit running"),
        (None, [_block("a", 1, strategy="warm")], {}, "redundancy must be"),
        (None, None, {"budget": None}, "budget, or a target"),
        (None, None, {"target": 1.0, "budget": None}, "below 1"),
        (None, None, {"t": 0}, "mission time"),
        (None, None, {"budget": {"cost": 1}}, "at least 2"),
        (None, None, {"target": 0.999999, "budget": None}, "unreachable"),
    ],
)
def test_bad_requests_are_refused_clearly(mutate, blocks, kwargs, needle):
    graph = _series((0.002, 0.004))
    if mutate:
        mutate(graph)
    args = {"t": T, "budget": {"cost": 6}, "target": None, **kwargs}
    with pytest.raises(DesignError, match=needle):
        rd.design_redundancy(
            graph, args["t"], [_block("a", 1), _block("b", 1)] if blocks is None else blocks,
            budget=args["budget"], target=args["target"],
        )


def test_only_components_and_parallel_blocks_can_be_copied():
    graph = _series((0.002, 0.004))
    graph["nodes"][2] = {"id": "a", "type": "subsystem", "position": {"x": 200, "y": 0},
                         "data": {"label": "Skid", "rbd": {"id": "x"}}}
    with pytest.raises(DesignError, match="“Skid” is a subsystem block"):
        rd.design_redundancy(graph, T, [_block("a", 1)], budget={"cost": 3})


def test_fixed_subsystems_stay_as_drawn():
    sub = _series((0.001,))
    graph = _series((0.002, 0.004))
    graph["nodes"][2] = {"id": "a", "type": "subsystem", "position": {"x": 200, "y": 0},
                         "data": {"label": "Skid", "rbd": {"id": "sub1"}}}
    res = rd.design_redundancy(
        graph, T, [_block("b", 1)], budget={"cost": 3},
        resolve_subsystem=lambda sid: sub if sid == "sub1" else None,
    )
    assert res["design"]["reliability"] == pytest.approx(_p(0.001) * _active(_p(0.004), 3), rel=1e-9)


# ---------------------------------------------------------------------------
# Writing a design back onto the diagram
# ---------------------------------------------------------------------------
def _applied(graph, blocks, res):
    out = rd.apply_design(graph, blocks, res["design"]["blocks"])
    return out, rd.applied_reliability(out, T)


def test_apply_active_copies_as_parallel_blocks():
    graph = _bridge_free()
    blocks = [_block("ctrl", 5, 3), _block("pumpA", 2, 3), _block("pumpB", 3, 3)]
    res = rd.design_redundancy(graph, T, blocks, budget={"cost": 16})
    out, r = _applied(graph, blocks, res)
    assert r == pytest.approx(res["design"]["reliability"], rel=1e-9)
    by_id = {n["id"]: n for n in out["nodes"]}
    for b in res["design"]["blocks"]:
        node = by_id[b["id"]]
        if b["copies"] == 1:
            assert node["type"] == "component"
        else:
            assert node["type"] == "parallel" and node["data"]["n"] == b["copies"]
            assert node["data"]["model"] == next(n for n in graph["nodes"] if n["id"] == b["id"])["data"]["model"]
    # The input graph is untouched (nothing is saved or mutated).
    assert all(n["type"] == "component" for n in graph["nodes"] if n["id"] in ("ctrl", "pumpA", "pumpB"))


def test_apply_k_out_of_n_as_a_voting_node():
    graph = _series((0.002, 0.004))
    blocks = [_block("a", 1, 5, required=2), _block("b", 1, 1)]
    res = rd.design_redundancy(graph, T, blocks, budget={"cost": 5})
    out, r = _applied(graph, blocks, res)
    assert r == pytest.approx(res["design"]["reliability"], rel=1e-9)
    vote = next(n for n in out["nodes"] if n["type"] == "knode")
    assert vote["data"]["n"] == 2 and vote["data"]["k"] == 4
    assert sum(1 for e in out["edges"] if e["target"] == vote["id"]) == 4
    # The block after the vote moved right to make room for the new column.
    b_before = next(n for n in graph["nodes"] if n["id"] == "b")["position"]["x"]
    assert next(n for n in out["nodes"] if n["id"] == "b")["position"]["x"] > b_before


def test_apply_cold_spares_as_a_standby_block():
    graph = _series((0.002, 0.004))
    blocks = [_block("a", 1, 4, strategy="cold", switching=0.9), _block("b", 1, 1)]
    res = rd.design_redundancy(graph, T, blocks, budget={"cost": 4})
    a = next(b for b in res["design"]["blocks"] if b["id"] == "a")
    assert a["strategy"] == "cold" and a["copies"] == 3
    out, r = _applied(graph, blocks, res)
    node = next(n for n in out["nodes"] if n["id"] == "a")
    assert node["type"] == "standby"
    assert node["data"]["spares"] == 2 and node["data"]["cold"] is True
    assert node["data"]["startProb"] == 0.9
    assert r == pytest.approx(res["design"]["reliability"], rel=1e-6)


def test_apply_mixed_types_wires_each_type_in_parallel():
    graph = _series((0.002, 0.004))
    premium = {"name": "Premium", "model": _exp(0.0005), "cost": 3}
    blocks = [_block("a", 1, 1), _block("b", 1, 4, types=[premium])]
    res = rd.design_redundancy(graph, T, blocks, budget={"cost": 6})
    b = next(x for x in res["design"]["blocks"] if x["id"] == "b")
    # One premium backed by two standard units beats four standard ones.
    assert [(m["name"], m["copies"]) for m in b["mix"]] == [("Current", 2), ("Premium", 1)]
    out, r = _applied(graph, blocks, res)
    assert r == pytest.approx(res["design"]["reliability"], rel=1e-9)
    labels = [n["data"]["label"] for n in out["nodes"] if n["id"].startswith("b")]
    assert any("Premium" in label for label in labels)


def test_apply_every_front_point_matches_its_reliability():
    graph = _bridge_free()
    blocks = [_block("ctrl", 5, 2), _block("pumpA", 2, 2, required=1), _block("pumpB", 3, 2)]
    res = rd.design_redundancy(graph, T, blocks, target=0.95)
    for d in res["front"]:
        out = rd.apply_design(graph, blocks, d["blocks"])
        assert rd.applied_reliability(out, T) == pytest.approx(d["reliability"], rel=1e-9)


def test_apply_refuses_a_design_for_other_blocks():
    graph = _series((0.002, 0.004))
    with pytest.raises(DesignError, match="wasn't part of the design"):
        rd.apply_design(graph, [_block("a", 1)], [{"id": "b", "mix": [{"type": 0, "copies": 2}]}])


# ---------------------------------------------------------------------------
# Common-cause (beta-factor) groups: copies join the group (RePyability 0.11, #140)
# ---------------------------------------------------------------------------
PUMP = _weibull(400.0, 1.5)


def _pumps(beta=0.1, ctrl_rate=0.0005):
    """input -> ctrl -> {pumpA | pumpB} -> output, the (identical) pumps in a
    beta-factor common-cause group."""
    nodes = _io() + [
        _node("ctrl", _exp(ctrl_rate), x=200),
        _node("pumpA", PUMP, x=400, y=-80),
        _node("pumpB", PUMP, x=400, y=80),
    ]
    edges = _edges(("input", "ctrl"), ("ctrl", "pumpA"), ("ctrl", "pumpB"),
                   ("pumpA", "output"), ("pumpB", "output"))
    graph = {"nodes": nodes, "edges": edges, "unit": "hours"}
    if beta:
        graph["ccf_groups"] = [{"id": "g1", "members": ["pumpA", "pumpB"], "beta": beta}]
    return graph


def _with_copies(graph, copies):
    """The diagram with each block's extra active copies drawn by hand: each
    a component wired in parallel with it, and in its common-cause group."""
    out = copy.deepcopy(graph)
    for bid, n in copies.items():
        node = next(x for x in out["nodes"] if x["id"] == bid)
        ins = [e["source"] for e in out["edges"] if e["target"] == bid]
        outs = [e["target"] for e in out["edges"] if e["source"] == bid]
        for j in range(1, n):
            cid = f"{bid}_{j}"
            out["nodes"].append({**copy.deepcopy(node), "id": cid})
            out["edges"] += _edges(*[(s, cid) for s in ins], *[(cid, t) for t in outs])
            for g in out.get("ccf_groups") or []:
                if bid in g["members"]:
                    g["members"].append(cid)
    return out


PUMP_BLOCKS = [_block("ctrl", 3, 3), _block("pumpA", 2, 3), _block("pumpB", 2, 3)]


def _units(design):
    return {b["id"]: b["copies"] for b in design["blocks"]}


def test_a_common_cause_diagram_is_designed():
    graph = _pumps()
    res = rd.design_redundancy(graph, T, PUMP_BLOCKS, budget={"cost": 14})
    assert res["common_cause"] == [
        {"id": "g1", "beta": 0.1, "members": ["Pumpa", "Pumpb"], "designed": ["Pumpa", "Pumpb"]}
    ]
    # As drawn, with the group (below the same diagram without it).
    assert res["current"]["reliability"] == pytest.approx(rd.applied_reliability(graph, T), rel=1e-12)
    assert res["current"]["reliability"] < rd.applied_reliability(_pumps(beta=0), T)
    # A group with a member left out of the design is still scored.
    res = rd.design_redundancy(graph, T, [_block("ctrl", 3, 3)], budget={"cost": 6})
    assert res["common_cause"][0]["designed"] == []
    assert res["design"]["reliability"] == pytest.approx(
        rd.applied_reliability(_with_copies(graph, {"ctrl": 2}), T), rel=1e-12)


def test_common_cause_scores_match_brute_force_and_the_library():
    import surpyval as surv
    from repyability import BetaFactor, CCFGroup, NonRepairableRBD

    graph = _pumps()
    res = rd.design_redundancy(graph, T, PUMP_BLOCKS, budget={"cost": 14})
    # Every design within the budget, its copies drawn in the group by hand.
    best = 0.0
    for c, a, b in itertools.product(range(1, 4), repeat=3):
        if 3 * c + 2 * a + 2 * b <= 14:
            units = {"ctrl": c, "pumpA": a, "pumpB": b}
            best = max(best, rd.applied_reliability(_with_copies(graph, units), T))
    assert res["design"]["reliability"] == pytest.approx(best, rel=1e-12)
    for d in res["front"]:
        drawn = rd.applied_reliability(_with_copies(graph, _units(d)), T)
        assert d["reliability"] == pytest.approx(drawn, rel=1e-12)
    # RePyability's allocation with the group, called directly.
    pump = surv.Weibull.from_params([400.0, 1.5])
    rbd = NonRepairableRBD(
        [("input", "ctrl"), ("ctrl", "pumpA"), ("ctrl", "pumpB"), ("pumpA", "output"), ("pumpB", "output")],
        {"ctrl": surv.Exponential.from_params([0.0005]), "pumpA": pump, "pumpB": pump},
        ccf_groups=[CCFGroup(["pumpA", "pumpB"], BetaFactor(0.1))],
    )
    costs = {"ctrl": {"cost": 3.0}, "pumpA": {"cost": 2.0}, "pumpB": {"cost": 2.0}}
    want = rbd.allocate_redundancy(costs, budget={"cost": 14.0}, t=T, max_units=3)
    assert res["design"]["reliability"] == pytest.approx(want.reliability, rel=1e-12)
    assert _units(res["design"]) == {k: int(v) for k, v in want.units.items()}


def test_common_cause_makes_redundancy_pay_off_less():
    blocks = [_block("ctrl", 2, 3), _block("pumpA", 2, 3), _block("pumpB", 2, 3)]
    free = rd.design_redundancy(_pumps(beta=0, ctrl_rate=1e-4), T, blocks, budget={"cost": 8})
    shared = rd.design_redundancy(_pumps(beta=0.3, ctrl_rate=1e-4), T, blocks, budget={"cost": 8})
    # Independent pumps: the spare money buys a third pump. With a shared
    # cause that a third pump can't escape, it buys a second controller.
    assert sorted(_units(free["design"]).items()) == [("ctrl", 1), ("pumpA", 2), ("pumpB", 1)]
    assert _units(shared["design"]) == {"ctrl": 2, "pumpA": 1, "pumpB": 1}
    assert shared["design"]["reliability"] < free["design"]["reliability"]
    gain = {beta: r["design"]["reliability"] - r["current"]["reliability"]
            for beta, r in ((0, free), (0.3, shared))}
    assert 0 < gain[0.3] < gain[0]
    # More copies can't get past the shared cause: a target independent pumps
    # reach is out of reach with the group, and one both reach costs more.
    with pytest.raises(DesignError, match="unreachable"):
        rd.design_redundancy(_pumps(beta=0.1), T, PUMP_BLOCKS, target=0.99)
    assert rd.design_redundancy(_pumps(beta=0), T, PUMP_BLOCKS, target=0.99)["design"]["cost"] == 12
    cheap = {beta: rd.design_redundancy(_pumps(beta=beta), T, PUMP_BLOCKS, target=0.97)["design"]
             for beta in (0, 0.1)}
    assert cheap[0.1]["cost"] >= cheap[0]["cost"]
    # The front's best design with the group stays below the cap at which
    # only the shared cause is left.
    shared = rd.design_redundancy(_pumps(beta=0.1), T, PUMP_BLOCKS, budget={"cost": 40})
    q = 1 - math.exp(-((T / 400.0) ** 1.5))
    cap = (1 - 0.1 * q) * _active(_p(0.0005), 3)
    assert max(d["reliability"] for d in shared["front"]) < cap


@pytest.mark.parametrize("mode", [{"budget": {"cost": 14}}, {"target": 0.97}])
def test_applied_copies_join_the_group_and_analyse_as_designed(mode):
    graph = _pumps()
    res = rd.design_redundancy(graph, T, PUMP_BLOCKS, **mode)
    assert res["mode"] == ("target" if "target" in mode else "budget")
    for d in [res["design"], *res["front"]]:
        out, notes = rd.apply_design_with_notes(graph, PUMP_BLOCKS, d["blocks"])
        assert rd.applied_reliability(out, T) == pytest.approx(d["reliability"], rel=1e-12)
        members = set(out["ccf_groups"][0]["members"])
        units = _units(d)
        pumps = {n["id"] for n in out["nodes"] if n["id"].startswith("pump")}
        assert members == pumps and len(pumps) == units["pumpA"] + units["pumpB"]
        assert all(n["type"] == "component" for n in out["nodes"] if n["id"] in pumps)
        assert out["ccf_groups"][0]["beta"] == 0.1 and out["ccf_groups"][0]["id"] == "g1"
        added = len(pumps) - 2
        assert len(notes) == (units["pumpA"] > 1) + (units["pumpB"] > 1)
        assert all("joined its common-cause group (β = 0.1)" in n for n in notes) or not added
    # The diagram given is untouched.
    assert graph["ccf_groups"][0]["members"] == ["pumpA", "pumpB"]


def _instrument_air():
    from backend.services import samples

    return samples._instrument_air_design_graph()


def test_instrument_air_compressor_copies_join_their_group_behind_a_junction():
    graph = _instrument_air()
    t = 4000.0
    blocks = [_block(c, 40, 3) for c in ("compA", "compB", "compC")] + [
        _block("filter", 2, 3), _block("header", 10, 3)]
    res = rd.design_redundancy(graph, t, blocks, budget={"cost": 200})
    assert res["common_cause"][0]["beta"] == 0.1
    design = _units(res["design"])
    assert sum(design[c] for c in ("compA", "compB", "compC")) == 4
    out, notes = rd.apply_design_with_notes(graph, blocks, res["design"]["blocks"])
    assert rd.applied_reliability(out, t) == pytest.approx(res["design"]["reliability"], rel=1e-12)
    # Four compressors in the group; the extra one joins its twin at a
    # junction, so the 2-out-of-3 vote still has three inputs.
    group = out["ccf_groups"][0]
    assert len(group["members"]) == 4 and group["beta"] == 0.1
    assert sorted(e["source"] for e in out["edges"] if e["target"] == "vote") == sorted(
        [c for c in ("compA", "compB", "compC") if design[c] == 1]
        + [f"{c}j" for c in ("compA", "compB", "compC") if design[c] == 2])
    junction = next(n for n in out["nodes"] if n["id"].endswith("j"))
    assert junction["type"] == "knode" and junction["data"]["n"] == 1
    assert len(notes) == 1 and "1 added copy joined its common-cause group (β = 0.1)" in notes[0]
    # Independent compressors would have done better with the same money.
    free = {**graph, "ccf_groups": []}
    assert rd.design_redundancy(free, t, blocks, budget={"cost": 200})["design"]["reliability"] > (
        res["design"]["reliability"])


def test_mixed_type_copies_feeding_a_vote_join_at_a_junction():
    """Side-by-side copies feeding a 2-out-of-3 vote would each count as an
    input: they join at a junction, and the vote keeps its three inputs."""
    graph = {**_instrument_air(), "ccf_groups": []}
    premium = {"name": "Premium", "model": _weibull(20000, 1.6), "cost": 60}
    blocks = [_block("compA", 40, 3, types=[premium])]
    design = [{"id": "compA", "strategy": "active",
               "mix": [{"type": 0, "copies": 1}, {"type": 1, "copies": 1}]}]
    out = rd.apply_design(graph, blocks, design)
    assert sorted(e["source"] for e in out["edges"] if e["target"] == "vote") == ["compAj", "compB", "compC"]
    t = 4000.0
    # As if Compressor A were the pair: its reliability folded into one block.
    pair = 1 - (1 - math.exp(-((t / 12000) ** 1.6))) * (1 - math.exp(-((t / 20000) ** 1.6)))
    alpha = t / (-math.log(pair)) ** (1 / 1.6)  # a Weibull with R(t) = pair
    same = copy.deepcopy(graph)
    next(n for n in same["nodes"] if n["id"] == "compA")["data"]["model"] = _weibull(alpha, 1.6)
    assert rd.applied_reliability(out, t) == pytest.approx(rd.applied_reliability(same, t), rel=1e-9)


def test_k_out_of_n_copies_of_a_member_join_the_group():
    graph = _pumps()
    blocks = [_block("pumpA", 1, 4, required=2), _block("pumpB", 1, 1)]
    res = rd.design_redundancy(graph, T, blocks, budget={"cost": 5})
    out, _ = rd.apply_design_with_notes(graph, blocks, res["design"]["blocks"])
    assert rd.applied_reliability(out, T) == pytest.approx(res["design"]["reliability"], rel=1e-12)
    copies = [n["id"] for n in out["nodes"] if n["id"].startswith("pumpA") and n["type"] == "component"]
    assert len(copies) == 4
    assert set(out["ccf_groups"][0]["members"]) == {*copies, "pumpB"}


@pytest.mark.parametrize(
    "block, needle",
    [
        (_block("pumpA", 1, 3, strategy="cold"), "active redundancy"),
        (_block("pumpA", 1, 3, strategy="choose"), "active redundancy"),
        (_block("pumpA", 1, 3, types=[{"name": "Big", "model": PUMP, "cost": 2}]), "alternative component types"),
    ],
)
def test_a_member_takes_active_copies_of_itself(block, needle):
    with pytest.raises(DesignError, match=needle):
        rd.design_redundancy(_pumps(), T, [block], budget={"cost": 6})


def test_a_parallel_block_in_a_group_is_not_redesigned():
    graph = _pumps()
    graph["nodes"][3] = _node("pumpA", PUMP, "parallel", x=400, y=-80, n=2, kind="parallel")
    with pytest.raises(DesignError, match="parallel block in a common-cause group"):
        rd.design_redundancy(graph, T, [_block("pumpA", 1)], budget={"cost": 4})


def test_a_group_left_with_one_member_is_removed():
    groups = [{"id": "g", "members": ["a", "b"], "beta": 0.1},
              {"id": "h", "members": ["c", "d", "e"], "beta": 0.2},
              {"id": "k", "members": ["f", "g"], "beta": 0.3}]
    kept, notes = rd._prune_groups(groups, {"a", "c"}, {"a": "Pump A", "b": "Pump B"})
    assert kept == [{"id": "h", "members": ["d", "e"], "beta": 0.2}, groups[2]]
    assert notes == ["The common-cause group of Pump A, Pump B (β = 0.1) was left with fewer "
                     "than two members, so it was removed."]


def test_a_repairable_diagram_with_a_group_gets_its_cheapest_design():
    """Repairable diagrams' Design tab is the cheapest design (#99), on the
    availability analysis, which leaves common-cause groups out (as do
    RePyability's repairable allocations): a group changes nothing there."""
    from backend.services import rbd_costs

    def pump(nid, y):
        return _node(nid, _exp(1e-3), x=200, y=y, repair=_exp(0.1),
                     costs={"repair": 500, "acquisition": 2000})

    graph = {"repairable": True, "unit": "hours", "costs": {"downtime_rate": 500, "horizon": 87600},
             "nodes": _io() + [pump("a", -80), pump("b", 80)],
             "edges": _edges(("input", "a"), ("input", "b"), ("a", "output"), ("b", "output"))}
    plain = rbd_costs.cheapest_design(graph, horizon=87600)
    grouped = rbd_costs.cheapest_design({**graph, "ccf_groups": [{"members": ["a", "b"], "beta": 0.1}]},
                                        horizon=87600)
    assert grouped["design"]["units"] == plain["design"]["units"]
    assert grouped["design"]["total_cost"] == pytest.approx(plain["design"]["total_cost"])


# ---------------------------------------------------------------------------
# API
# ---------------------------------------------------------------------------
USER = {"uid": "user-design", "email": "design@example.org", "name": "Designer"}


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


def test_design_endpoint_is_free_and_applies(client):
    graph = _series((0.002, 0.004))
    blocks = [_block("a", 1), _block("b", 1)]
    r = client.post("/api/rbds/design", json={"graph": graph, "t": T, "blocks": blocks, "budget": {"cost": 5}})
    assert r.status_code == 200, r.text
    res = r.json()
    assert res["design"]["cost"] <= 5 and res["front"]
    r = client.post("/api/rbds/design/apply", json={
        "graph": graph, "blocks": blocks, "design": res["design"]["blocks"], "t": T,
    })
    assert r.status_code == 200, r.text
    assert r.json()["reliability"] == pytest.approx(res["design"]["reliability"], rel=1e-9)
    # Nothing is saved.
    assert client.get("/api/rbds").json()["rbds"] == [] or all(
        x["is_sample"] for x in client.get("/api/rbds").json()["rbds"]
    )


def test_design_endpoint_reports_bad_input_as_422(client):
    graph = _series((0.002, 0.004))
    graph["repairable"] = True
    r = client.post("/api/rbds/design", json={"graph": graph, "t": T, "blocks": [_block("a", 1)], "budget": {"cost": 5}})
    assert r.status_code == 422
    assert "non-repairable" in r.json()["detail"]


def test_design_endpoint_designs_and_applies_a_common_cause_diagram(client):
    graph = _pumps()
    r = client.post("/api/rbds/design", json={"graph": graph, "t": T, "blocks": PUMP_BLOCKS, "budget": {"cost": 14}})
    assert r.status_code == 200, r.text
    res = r.json()
    assert res["common_cause"][0]["beta"] == 0.1
    r = client.post("/api/rbds/design/apply", json={
        "graph": graph, "blocks": PUMP_BLOCKS, "design": res["design"]["blocks"], "t": T,
    })
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["reliability"] == pytest.approx(res["design"]["reliability"], rel=1e-12)
    assert len(body["graph"]["ccf_groups"][0]["members"]) > 2
    assert body["notes"] and "common-cause group" in body["notes"][0]
