"""Redundancy design (#98): how many copies of each block, within budgets.

Small systems whose optimum is checked by brute force, budgets respected, a
non-dominated and sorted trade-off curve, clear refusals, and designs written
back onto the diagram that analyse to the reliability the search reported.
"""

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
        (lambda g: g.update(ccf_groups=[{"members": ["a", "b"], "beta": 0.1}]), None, {}, "common-cause"),
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
