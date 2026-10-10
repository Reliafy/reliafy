"""Adding a block in place in the builder (#282): the diagrams the builder's
helpers make (``frontend/src/rbdBuilderOps.js``; the same diagrams are
checked there by ``rbdAddInPlace.test.js``) are valid and compute as the
series or parallel structure they were meant to be — against the closed
form and RePyability built directly.

Every block is exponential with rate λ = 0.001, so r(t) = e^(−λt).
"""

import json
from pathlib import Path

import numpy as np
import pytest
import surpyval as sp
from repyability import NonRepairableRBD, PerfectReliability

from backend.services import rbd_analysis as ra

FIXTURE = json.loads((Path(__file__).parent / "fixtures" / "rbd_add_in_place.json").read_text())
LAM = 0.001
TIMES = [100.0, 500.0, 1000.0, 2500.0]


def _r(t):
    return np.exp(-LAM * np.asarray(t))


def _sf(graph):
    out = ra.analyze(graph, at_times=TIMES)
    assert out["at"]["t"] == pytest.approx(TIMES)
    return np.asarray(out["at"]["sf"], dtype=float)


def _direct(graph):
    """The same diagram built in RePyability directly."""
    e = sp.Exponential.from_params([LAM])
    comps, k = {}, {}
    for n in graph["nodes"]:
        if n["type"] == "component":
            comps[n["id"]] = e
        elif n["type"] == "knode":
            comps[n["id"]] = PerfectReliability
            k[n["id"]] = n["data"]["n"]
    edges = [(x["source"], x["target"]) for x in graph["edges"]]
    return NonRepairableRBD(edges, comps, k=k or None).sf(np.asarray(TIMES))


EXPECTED = {
    # Series: r²
    "after": lambda r: r ** 2,
    "split": lambda r: r ** 2,
    # Two identical blocks in parallel: 1 − (1 − r)²
    "alongside": lambda r: 1 - (1 - r) ** 2,
    # A third branch into the junction already there: 1 − (1 − r)³
    "alongside_joined": lambda r: 1 - (1 - r) ** 3,
    # A line of two bypassed by one: 1 − (1 − r²)(1 − r)
    "bypass": lambda r: 1 - (1 - r ** 2) * (1 - r),
    # 2-of-3 where the first vote is a parallel pair p = 1 − (1 − r)²:
    # P(at least two of p, r, r)
    "alongside_vote": lambda r: (lambda p: p * r * r + p * 2 * r * (1 - r) + (1 - p) * r * r)(1 - (1 - r) ** 2),
}


@pytest.mark.parametrize("name", sorted(EXPECTED))
def test_each_added_diagram_is_valid_and_computes_as_intended(name):
    graph = FIXTURE[name]
    check = ra.validate_graph(graph)
    assert check["valid"] is True and not check["errors"], check
    got = _sf(graph)
    assert got == pytest.approx(EXPECTED[name](_r(TIMES)), abs=1e-9)
    assert got == pytest.approx(_direct(graph), abs=1e-9)


def test_alongside_is_a_true_parallel_pair():
    """The founder's check: two identical exponential blocks side by side
    give R = 1 − (1 − e^(−λt))², above either block alone."""
    got = _sf(FIXTURE["alongside"])
    r = _r(TIMES)
    assert got == pytest.approx(1 - (1 - r) ** 2, abs=1e-9)
    assert np.all(got > r)
    paths = ra.analyze(FIXTURE["alongside"])["structure"]["min_path_sets"]
    assert sorted(paths) == [["New"], ["a"]]
