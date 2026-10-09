"""The fault tree of a builder RBD: a read-only view of its failure logic (#101).

A fault tree and an RBD describe one system from opposite sides — the diagram
says when it works, the tree when it fails. RePyability 0.9's
``FaultTree.from_rbd`` turns a diagram into its tree: a series block becomes
an OR gate, a parallel block an AND gate, a k-of-n block a VOTE gate on the
failures that defeat it, and a part that isn't series-parallel (a bridge) an
OR gate over its minimal cut sets. Perfect junctions (k-of-n voting nodes)
drop out.

The diagram is built exactly as the calculator builds it
(``rbd_analysis._build_rbd``), so every block keeps the life model the
calculator uses, and the top event probability is the calculator's
unreliability ``1 - R(t)``. On top of ``from_rbd``:

* a **sub-system** block is developed into its own gates (under a gate named
  after the block), rather than left as one opaque event;
* a **common-cause** (beta-factor) group becomes the textbook construction —
  each member fails independently OR by the group's shared cause, one event
  feeding every member's gate — which is exactly how RePyability evaluates the
  group in the diagram: on the rate basis (Reliafy's lifetime default, #210)
  the events have not occurred by ``t`` with ``R(t) ** (1 - beta)`` and
  ``R(t) ** beta``; on the probability basis they occur with ``(1 - beta) Q``
  and ``beta Q``. RePyability 0.12's ``FaultTree(ccf_groups=...)`` (#229)
  keeps the members as the basic events and folds the shared cause into the
  cut sets' probabilities; the explicit shared event gives the same top event
  and importance, and shows the shared cause as a cut set of its own, as PRA
  codes list it (the tests check the two agree). ``common_cause`` in the
  result sums up each group: the shared cause's probability and the share of
  the top event carried by the cut sets holding it;
* blocks **pinned** working/failed become events that never / always occur;
* a **repairable** diagram gets the same tree over the blocks' steady-state
  unavailabilities, so its top event is the long-run unavailability.
"""

from __future__ import annotations

import heapq
import warnings
from itertools import combinations
from math import comb
from typing import Any, Callable, Optional

import numpy as np

from backend.services import rbd_analysis as ra
from backend.services.rbd_analysis import AnalysisError
from repyability import FaultTree
from repyability.rbd.ccf import VALIDITY as CCF_VALIDITY
from repyability.rbd.helper_classes import PerfectReliability
from repyability.rbd.non_repairable_rbd import NonRepairableRBD

# Cut sets listed in the result, most likely first; the count is always given.
_LISTED_CUT_SETS = 100
# Gates beyond which a tree is too big to be worth drawing (a large core that
# isn't series-parallel becomes one AND gate per cut set).
_MAX_GATES = 3000


class _Share:
    """A fixed share of a model's failure: the two halves of a beta-factor
    group member — its independent part and the shared cause — as FaultTree
    events (anything with ``sf``/``ff``).

    On the rate basis (#210, Reliafy's lifetime default) the share is of the
    model's failure *rate*: the event has not occurred by ``t`` with
    ``R(t) ** fraction``, so the independent part (``1 - beta``) and the
    shared cause (``beta``) are independent events whose OR is the member's
    own ``1 - R(t)``. On the probability basis it is of the probability,
    ``fraction * Q(t)``."""

    def __init__(self, model, fraction: float, name: str, basis: str = "probability"):
        self.model = model
        self.fraction = float(fraction)
        self.basis = basis
        self.dist = ra._DistName(name)

    def _q(self, x) -> np.ndarray:
        if hasattr(self.model, "ff"):
            return np.asarray(self.model.ff(x), dtype=float)
        return 1.0 - np.asarray(self.model.sf(x), dtype=float)

    def ff(self, x) -> np.ndarray:
        x = np.asarray(x, dtype=float)
        q = self._q(x)
        if self.basis == "rate":
            # 1 - R ** fraction, from log1p(-Q) so a small Q keeps its precision.
            with np.errstate(divide="ignore", invalid="ignore"):
                return -np.expm1(self.fraction * np.log1p(-np.clip(q, 0.0, 1.0)))
        return self.fraction * q

    def sf(self, x) -> np.ndarray:
        return 1.0 - self.ff(x)


class _Builder:
    """Accumulates one flat FaultTree from a diagram and its sub-systems.

    Names are strings: a top-level block's event is its builder node id, a
    block inside sub-system ``s`` is ``"s/<id>"`` (nested further as needed),
    and gates are ``"<prefix>#<name>"``, so nothing collides."""

    def __init__(self, resolve_subsystem, resolve_model, covariates):
        self.resolve_subsystem = resolve_subsystem
        self.resolve_model = resolve_model
        self.covariates = covariates
        self.gates: dict[str, tuple] = {}
        self.events: dict[str, Any] = {}
        self.gate_info: dict[str, dict] = {}
        self.event_info: dict[str, dict] = {}

    def add(self, tree: FaultTree, prefix: str, events: dict, info: dict) -> str:
        """Graft ``tree`` in under ``prefix``: its events are replaced by
        ``events`` (name -> model, or a gate spec to develop the event into a
        gate of the same name). Returns the grafted top gate's name."""
        def name(x) -> str:
            return f"{prefix}{x}" if x in tree.events else f"{prefix}#{x}"

        for g, spec in tree.gates.items():
            self.gates[name(g)] = (*spec[:-1], [name(x) for x in spec[-1]])
        for e in tree.events:
            model = events[e]
            if isinstance(model, tuple):  # developed into a gate
                self.gates[name(e)] = model
            else:
                self.events[name(e)] = model
                self.event_info[name(e)] = info[e]
        return name(tree.top)


def _structure_rbd(rbd: NonRepairableRBD, reliabilities: dict) -> NonRepairableRBD:
    """The diagram rebuilt with other node models and no common-cause groups:
    they're added to the tree afterwards, as explicit shared events (since
    RePyability 0.12 ``from_rbd`` would keep them as ``ccf_groups`` over the
    members instead, with no event of their own to draw or rank)."""
    args = dict(rbd._init_args)
    args["reliabilities"] = reliabilities
    args["ccf_groups"] = None
    return NonRepairableRBD(**args)


def _from_rbd(rbd: NonRepairableRBD, where: str) -> FaultTree:
    try:
        return FaultTree.from_rbd(rbd)
    except ValueError as exc:
        raise AnalysisError(
            f"{where} can't fail, so it has no fault tree: every route from "
            "input to output needs a block that never fails (or the input "
            "joins the output directly)."
        ) from exc


def _develop(
    b: _Builder,
    graph: dict,
    prefix: str,
    path: list[str],
    visited: set,
    top_level: bool,
) -> str:
    """Add a diagram's tree to ``b`` and return its top gate's name.

    Only the top-level diagram honours pinned blocks — the calculator
    evaluates a sub-system with its own blocks' life models, so the tree
    does too."""
    rbd, labels, node_types, reliabilities, working, broken, _ = ra._build_rbd(
        graph, b.resolve_subsystem, visited, b.resolve_model, b.covariates
    )
    if not top_level:
        working, broken = set(), set()
    groups = ra._ccf_groups(graph, reliabilities)
    for group in groups:
        pinned = [m for m in group.members if m in working or m in broken]
        if pinned:
            raise AnalysisError(
                f"{labels.get(pinned[0], pinned[0])} is pinned working/failed but "
                "belongs to a common-cause group — unpin it, or take it out of the "
                "group, to see the fault tree."
            )

    # A pinned block without a life model stands in as never-failing, which
    # from_rbd would drop as a junction: give it a model so it stays an event
    # (its probability is fixed to 0 or 1 below).
    structural = dict(rbd._init_args["reliabilities"])
    for n in working | broken:
        if structural.get(n) is PerfectReliability and node_types.get(n) != "knode":
            structural[n] = _Share(PerfectReliability, 1.0, "Pinned")
    where = "This diagram" if top_level else f"Sub-system “{path[-1]}”"
    tree = _from_rbd(_structure_rbd(rbd, structural), where)

    events: dict[Any, Any] = {}
    info: dict[Any, dict] = {}
    for e in tree.events:
        label = labels.get(e, str(e))
        info[e] = {"label": label, "path": list(path), "node_type": node_types.get(e)}
        if e in working or e in broken:
            events[e] = 0.0 if e in working else 1.0
            info[e]["pinned"] = "working" if e in working else "failed"
        else:
            events[e] = reliabilities[e]

    # Sub-systems: develop each into its own gates, under a gate that keeps
    # the block's name (so parent gates still point at it). One in a
    # common-cause group stays a single event, split below.
    in_groups = {m for g in groups for m in g.members}
    for e in list(tree.events):
        if node_types.get(e) != "subsystem" or isinstance(events[e], float) or e in in_groups:
            continue
        node = next(n for n in graph.get("nodes") or [] if n.get("id") == e)
        ref = (node.get("data") or {}).get("rbd") or {}
        sub_graph = b.resolve_subsystem(ref["id"]) if b.resolve_subsystem else None
        if sub_graph is None:  # _build_rbd already resolved it; defensive
            raise AnalysisError(f"{labels.get(e, e)}: sub-system not found.")
        sub_prefix = f"{prefix}{e}/"
        sub_top = _develop(
            b, sub_graph, sub_prefix, [*path, labels.get(e, str(e))],
            visited | {ref["id"]}, top_level=False,
        )
        # Take over the sub-tree's top gate under the block's own name.
        events[e] = b.gates.pop(sub_top)
        b.gate_info[f"{prefix}{e}"] = {
            "label": labels.get(e, str(e)), "path": list(path), "role": "subsystem",
        }

    # Common cause: each member fails independently OR by the shared cause.
    for i, group in enumerate(groups, start=1):
        members = [m for m in group.members if m in tree.events]
        if not members:
            continue
        beta, basis = group.model.beta, group.model.basis
        shared = f"{prefix}ccf:{i}"
        b.events[shared] = _Share(reliabilities[members[0]], beta, "CommonCause", basis)
        b.event_info[shared] = {
            "label": "Common cause: " + ", ".join(labels.get(m, str(m)) for m in members),
            "path": list(path), "node_type": "ccf", "beta": beta, "basis": basis,
            "members": [labels.get(m, str(m)) for m in members],
        }
        for m in members:
            independent = f"{prefix}{m}:independent"
            b.events[independent] = _Share(reliabilities[m], 1.0 - beta, "Independent", basis)
            b.event_info[independent] = {
                **info[m], "label": f"{info[m]['label']} (independent)",
                "node_type": "ccf_independent",
            }
            events[m] = ("or", [independent, shared])
            b.gate_info[f"{prefix}{m}"] = {
                "label": info[m]["label"], "path": list(path), "role": "ccf_member",
                "beta": beta, "basis": basis,
            }

    top = b.add(tree, prefix, events, info)
    if len(b.gates) > _MAX_GATES:
        raise AnalysisError(
            f"This diagram's fault tree has more than {_MAX_GATES:,} gates — too "
            "large to draw. Its reliability is still on the Calculator tab."
        )
    return top


def _repairable_tree(graph: dict, resolve_model) -> tuple[FaultTree, dict, float]:
    """The fault tree of a repairable diagram over its blocks' steady-state
    unavailabilities: ``(tree, event_info, long-run unavailability)``."""
    rbd, labels, gate_ids, working, broken = ra._build_repairable_rbd(graph, resolve_model, with_ccf=False)
    availability = rbd.node_availability()
    args = rbd._init_args
    structural = {
        n: (PerfectReliability if n in gate_ids and n not in broken else _Share(PerfectReliability, 1.0, "Block"))
        for n in args["components"]
    }
    structure = NonRepairableRBD(
        args["edges"], structural, k=args["k"],
        input_node=args["input_node"], output_node=args["output_node"],
    )
    tree = _from_rbd(structure, "This diagram")
    events: dict[Any, float] = {}
    info: dict[Any, dict] = {}
    for e in tree.events:
        info[e] = {"label": labels.get(e, str(e)), "path": [], "node_type": "component"}
        if e in working or e in broken:
            events[e] = 0.0 if e in working else 1.0
            info[e]["pinned"] = "working" if e in working else "failed"
        else:
            events[e] = min(max(1.0 - float(availability[e]), 0.0), 1.0)
    unavailability = 1.0 - float(
        rbd.mean_availability(working_nodes=working, broken_nodes=broken)
    )
    return FaultTree(tree.gates, events, top=tree.top), info, unavailability


def _default_time(graph: dict, resolve_subsystem, resolve_model, covariates, t_max) -> float:
    """The calculator's representative time for importance measures: where the
    system reliability is closest to 0.9 on its time axis (else the axis
    midpoint). Mirrors ``rbd_analysis.analyze`` (without a conditional age)."""
    rbd, _, _, reliabilities, working, broken, _ = ra._build_rbd(
        graph, resolve_subsystem, None, resolve_model, covariates
    )
    overrides = {"working_nodes": working, "broken_nodes": broken}
    grid = ra._time_grid(reliabilities, t_max)
    if not (t_max is not None and np.isfinite(t_max) and t_max > 0):
        grid = np.linspace(
            0.0, ra._system_horizon(rbd, float(grid[-1]), 0.0, **overrides), ra._GRID_POINTS
        )
    sf = ra._conditional_sf(rbd, grid, 0.0, **overrides)
    idx = int(np.argmin(np.abs(sf - 0.9)))
    if not (0.0 < sf[idx] < 1.0):
        idx = len(grid) // 2
    return float(grid[idx])


def _event_probabilities(tree: FaultTree, t: float) -> dict:
    """Each event's probability of having occurred by ``t``."""
    out = {}
    for e, model in tree.events.items():
        if isinstance(model, float):
            out[e] = model
        elif hasattr(model, "ff"):
            out[e] = float(np.atleast_1d(np.asarray(model.ff(np.array([t])), dtype=float))[0])
        else:
            out[e] = 1.0 - float(np.atleast_1d(np.asarray(model.sf(np.array([t])), dtype=float))[0])
    return out


def _at_least(k: int, probs: list[float]) -> float:
    """P(at least ``k`` of independent events occur), by dynamic programming."""
    dist = [1.0]  # dist[j] = P(exactly j occurred so far)
    for p in probs:
        nxt = [0.0] * (len(dist) + 1)
        for j, v in enumerate(dist):
            nxt[j] += v * (1.0 - p)
            nxt[j + 1] += v * p
        dist = nxt
    return float(sum(dist[k:]))


def _gate_probabilities(tree: FaultTree, q: dict, t: float) -> dict:
    """Each gate's probability of occurring. A gate below which nothing is
    shared with the rest of the tree is closed form from its inputs; one that
    shares events (a bridge's cut sets, a common cause) is evaluated exactly
    as a tree of its own."""
    gates = tree.gates
    parents: dict[str, int] = {}
    for spec in gates.values():
        for x in spec[-1]:
            parents[x] = parents.get(x, 0) + 1
    out: dict[str, float] = {}
    own: dict[str, bool] = {}

    def below(g) -> tuple[dict, set]:
        sub_gates, sub_events, stack = {}, set(), [g]
        while stack:
            x = stack.pop()
            if x in sub_gates or x in sub_events:
                continue
            if x in gates:
                sub_gates[x] = gates[x]
                stack.extend(gates[x][-1])
            else:
                sub_events.add(x)
        return sub_gates, sub_events

    def visit(g):
        if g in out:
            return
        inputs = gates[g][-1]
        for x in inputs:
            if x in gates:
                visit(x)
        own[g] = all(parents[x] == 1 and (x not in gates or own[x]) for x in inputs)
        if own[g]:
            probs = [out[x] if x in gates else q[x] for x in inputs]
            kind = gates[g][0]
            if kind == "or":
                out[g] = 1.0 - float(np.prod([1.0 - p for p in probs]))
            elif kind == "and":
                out[g] = float(np.prod(probs))
            else:
                out[g] = _at_least(gates[g][1], probs)
        else:
            sub_gates, sub_events = below(g)
            sub = FaultTree(sub_gates, {e: tree.events[e] for e in sub_events}, top=g)
            out[g] = float(sub.top_event_probability(t))

    visit(tree.top)
    return out


class _DecompositionOf:
    """Lets ``rbd_analysis._set_counts`` count a tree's cut sets: it only
    needs ``_decomposition()``, and a tree's decomposition is over the system
    working, exactly like a diagram's."""

    def __init__(self, tree: FaultTree):
        self._tree = tree

    def _decomposition(self):
        return self._tree._decomposition


def _low_order_cut_sets(tree: FaultTree, max_order: int = ra._LOW_ORDER_CUT_MAX) -> list:
    """Minimal cut sets of up to ``max_order`` events, found by evaluating the
    tree: a set is a cut set iff the top event occurs with exactly it
    occurred. Each candidate is one column of a vectorised exact evaluation
    (as ``rbd_analysis._low_order_cut_sets`` does for a diagram)."""
    names = sorted(tree.events, key=str)
    dec = tree._decomposition
    found: list[int] = []
    out: list[frozenset] = []
    for k in range(1, max_order + 1):
        if comb(len(names), k) > ra._LOW_ORDER_CANDIDATES_MAX:
            break
        cands = []
        for cand in combinations(range(len(names)), k):
            mask = 0
            for i in cand:
                mask |= 1 << i
            if not any(f & mask == f for f in found):
                cands.append((cand, mask))
        for start in range(0, len(cands), 20_000):
            chunk = cands[start:start + 20_000]
            p = {e: np.ones(len(chunk)) for e in names}
            for col, (cand, _) in enumerate(chunk):
                for i in cand:
                    p[names[i]][col] = 0.0
            q = {e: 1.0 - v for e, v in p.items()}
            _, fails = dec.probabilities(p, q, shape=len(chunk), works=False, fails=True)
            fails = np.broadcast_to(np.asarray(fails, dtype=float), (len(chunk),))
            for col, (cand, mask) in enumerate(chunk):
                if fails[col] > 0.5:
                    found.append(mask)
                    out.append(frozenset(names[i] for i in cand))
    return out


def _rank_key(item) -> tuple:
    cut, p = item
    return (-p, len(cut), sorted(map(str, cut)))


def _best_products(lists: list[list], k: int) -> list:
    """The ``k`` most likely unions of one cut set from each list (each list
    sorted most likely first, over disjoint events): a best-first search of
    the product, pairwise."""
    out = lists[0]
    for other in lists[1:]:
        heap = [(-(out[0][1] * other[0][1]), 0, 0)]
        seen = {(0, 0)}
        merged = []
        while heap and len(merged) < k:
            neg, i, j = heapq.heappop(heap)
            merged.append((out[i][0] | other[j][0], -neg))
            for a, c in ((i + 1, j), (i, j + 1)):
                if a < len(out) and c < len(other) and (a, c) not in seen:
                    seen.add((a, c))
                    heapq.heappush(heap, (-(out[a][1] * other[c][1]), a, c))
        out = merged
    return out


def _most_likely_cut_sets(tree: FaultTree, q: dict, k: int) -> Optional[list]:
    """The ``k`` most likely minimal cut sets without listing them all, for a
    tree with no repeated events or gates (so every gate is independent of
    the rest, and its cut sets are exactly its inputs' combined: an OR's are
    its inputs' together, an AND's one from each input, a VOTE's one from
    each of any ``k`` inputs). None when that doesn't hold, or a vote has
    too many input combinations to search."""
    gates = tree.gates
    uses: dict[Any, int] = {}
    for spec in gates.values():
        for x in spec[-1]:
            uses[x] = uses.get(x, 0) + 1
    if any(n > 1 for n in uses.values()):
        return None
    best: dict[Any, list] = {e: [(frozenset([e]), q[e])] for e in tree.events}
    for g in tree._post_order():
        if g not in gates:
            continue
        kind, inputs = gates[g][0], gates[g][-1]
        lists = [best[x] for x in inputs]
        if kind == "or":
            best[g] = sorted((c for lst in lists for c in lst), key=_rank_key)[:k]
        elif kind == "and":
            best[g] = _best_products(lists, k)
        else:
            needed = gates[g][1]
            if comb(len(lists), needed) > 2000:
                return None
            found = [c for chosen in combinations(lists, needed) for c in _best_products(list(chosen), k)]
            best[g] = sorted(found, key=_rank_key)[:k]
    return sorted(best[tree.top], key=_rank_key)


def _elementary(values: list[float], k: int) -> float:
    """The elementary symmetric polynomial ``e_k`` of ``values``."""
    e = [1.0] + [0.0] * k
    for v in values:
        for j in range(k, 0, -1):
            e[j] += e[j - 1] * v
    return e[k]


def _module_fussell_vesely(tree: FaultTree, q: dict) -> dict:
    """Each event's summed cut-set probability (Fussell–Vesely's numerator)
    without listing the cut sets, for a tree with no repeated events or
    gates. The sum over a gate's cut sets is closed form — an OR's is its
    inputs' sums added, an AND's multiplied, a VOTE's the elementary
    symmetric polynomial of them — and an event's share is ``q_e dS/dq_e``
    (every cut set holds it at most once), found in one backward pass."""
    gates = tree.gates
    order = [x for x in tree._post_order() if x in gates]
    total: dict[Any, float] = dict(q)
    for g in order:
        kind, inputs = gates[g][0], [total[x] for x in gates[g][-1]]
        if kind == "or":
            total[g] = sum(inputs)
        elif kind == "and":
            total[g] = float(np.prod(inputs))
        else:
            total[g] = _elementary(inputs, gates[g][1])
    grad: dict[Any, float] = {tree.top: 1.0}
    for g in reversed(order):
        kind, inputs = gates[g][0], gates[g][-1]
        for i, x in enumerate(inputs):
            others = [total[y] for j, y in enumerate(inputs) if j != i]
            if kind == "or":
                d = 1.0
            elif kind == "and":
                d = float(np.prod(others))
            else:
                d = _elementary(others, gates[g][1] - 1)
            grad[x] = grad.get(x, 0.0) + grad[g] * d
    return {e: q[e] * grad.get(e, 0.0) for e in tree.events}


def _ranked_cut_sets(tree: FaultTree, q: dict, t: float) -> dict:
    """``{ranked: [(set, p)], count, complete, basis}``: every minimal cut
    set when there are few enough to list; else the most likely ones when the
    tree allows finding them directly, else the lowest-order ones (the count
    is then RePyability's, exact or an upper bound)."""
    _, n_cuts = ra._set_counts(_DecompositionOf(tree))
    if n_cuts is not None and n_cuts <= ra._MAX_ENUMERATED_SETS:
        ranked = tree.ranked_cut_sets(t)
        return {"ranked": ranked, "count": len(ranked), "complete": True, "basis": "all"}
    ranked = _most_likely_cut_sets(tree, q, _LISTED_CUT_SETS)
    if ranked is not None:
        return {"ranked": ranked, "count": n_cuts, "complete": False, "basis": "most_likely"}
    cuts = _low_order_cut_sets(tree)
    ranked = sorted(((c, float(np.prod([q[e] for e in c]))) for c in cuts), key=_rank_key)
    return {"ranked": ranked, "count": n_cuts, "complete": False, "basis": "low_order"}


def _display_names(tree: FaultTree) -> dict:
    """Gate codes for display, top-down: the top event ``TOP``, then ``G1``,
    ``G2``, ... in breadth-first order."""
    codes = {tree.top: "TOP"}
    queue = [tree.top]
    gates = tree.gates
    while queue:
        g = queue.pop(0)
        for x in gates[g][-1]:
            if x in gates and x not in codes:
                codes[x] = f"G{len(codes)}"
                queue.append(x)
    return codes


def _payload(
    tree: FaultTree,
    gate_info: dict,
    event_info: dict,
    t: float,
    kind: str,
) -> dict:
    """The JSON result for a built tree evaluated at ``t`` (``kind`` is
    ``"reliability"``, or ``"availability"`` for steady-state events)."""
    q = _event_probabilities(tree, t)
    gate_p = _gate_probabilities(tree, q, t)
    top_p = gate_p[tree.top]
    codes = _display_names(tree)
    gates = tree.gates
    uses: dict[str, int] = {}
    for spec in gates.values():
        for x in spec[-1]:
            uses[x] = uses.get(x, 0) + 1

    # Importance: every measure from one pass of conditioning on each event.
    importance: dict[str, dict] = {e: {} for e in tree.events}
    try:
        with np.errstate(all="ignore"):
            top, occurred, not_occurred, _, _ = tree._conditioned(t)
            for e in tree.events:
                o, n = float(occurred[e][0]), float(not_occurred[e][0])
                importance[e] = {
                    "birnbaum": ra._f(o - n),
                    "criticality": ra._f((o - n) * q[e] / top[0]),
                    "risk_achievement_worth": ra._f(o / top[0]),
                    "risk_reduction_worth": ra._f(top[0] / n),
                }
    except Exception:  # noqa: BLE001 - the tree and cut sets still stand
        pass

    cuts = _ranked_cut_sets(tree, q, t)
    # Fussell–Vesely: the share of the top event carried by the cut sets
    # containing the event. Exact since RePyability 0.11 (#137): the
    # probability that one of them has occurred, as the calculator reports
    # it. Should that fail, the rare-event sum stands in: in closed form
    # without repeated events, else over the listed cut sets (only the
    # lowest-order ones when there are too many to list).
    try:
        with np.errstate(all="ignore"):
            exact = tree.fussell_vesely(t)
        for e in tree.events:
            importance[e]["fussell_vesely"] = ra._f(float(np.atleast_1d(exact[e])[0])) if top_p > 0 else None
    except Exception:  # noqa: BLE001
        fv: dict[str, float] = {}
        if cuts["basis"] == "most_likely":  # no repeats: closed form without the list
            fv = _module_fussell_vesely(tree, q)
        else:
            for cut, p in cuts["ranked"]:
                for e in cut:
                    fv[e] = fv.get(e, 0.0) + p
        for e in tree.events:
            importance[e]["fussell_vesely"] = ra._f(fv.get(e, 0.0) / top_p) if top_p > 0 else None

    order = list(codes)  # gates top-down; events in first-seen order under them
    seen_events: list[str] = []
    for g in order:
        for x in gates[g][-1]:
            if x in tree.events and x not in seen_events:
                seen_events.append(x)

    def gate_row(g) -> dict:
        spec = gates[g]
        info = gate_info.get(g, {})
        row = {
            "id": codes[g],
            "kind": spec[0],
            "k": spec[1] if spec[0] == "vote" else (1 if spec[0] == "or" else len(spec[-1])),
            "inputs": [
                {"kind": "gate", "id": codes[x]} if x in gates else {"kind": "event", "id": x}
                for x in spec[-1]
            ],
            "probability": ra._f(gate_p[g]),
            "repeated": uses.get(g, 0) > 1,
        }
        for key in ("label", "role", "path", "beta", "basis"):
            if key in info:
                row[key] = info[key]
        return row

    def event_row(e) -> dict:
        info = event_info.get(e, {})
        return {
            "id": e,
            "label": info.get("label", e),
            "path": info.get("path", []),
            "node_type": info.get("node_type"),
            "pinned": info.get("pinned"),
            "beta": info.get("beta"),
            "basis": info.get("basis"),
            "probability": ra._f(q[e]),
            "repeated": uses.get(e, 0) > 1,
            "importance": importance[e],
        }

    ranked = cuts["ranked"]
    listed = [
        {
            "events": sorted(c, key=lambda e: (-q[e], str(e))),
            "order": len(c),
            "probability": ra._f(p),
            "share": ra._f(p / top_p) if top_p > 0 else None,
        }
        for c, p in ranked[:_LISTED_CUT_SETS]
    ]
    # Each common-cause group's shared event (#229): its probability, and the
    # share of the top event carried by the cut sets holding it (its exact
    # Fussell–Vesely), with how many of the listed cut sets hold it.
    common_cause = []
    for e in seen_events:
        info = event_info.get(e, {})
        if info.get("node_type") != "ccf":
            continue
        common_cause.append({
            "event": e,
            "label": info.get("label", e),
            "path": info.get("path", []),
            "members": info.get("members", []),
            "beta": info.get("beta"),
            "basis": info.get("basis"),
            "probability": ra._f(q[e]),
            "share": importance[e].get("fussell_vesely"),
            "cut_sets_listed": sum(1 for row in listed if e in row["events"]),
        })
    return {
        "kind": kind,
        "t": t if kind == "reliability" else None,
        "top": "TOP",
        "top_event_probability": ra._f(top_p),
        "gates": [gate_row(g) for g in order],
        "events": [event_row(e) for e in seen_events],
        "cut_sets": {
            "listed": listed,
            "count": cuts["count"],
            "complete": cuts["complete"],
            # all | most_likely (the likeliest, found directly) | low_order
            # (every one of up to max_order events)
            "basis": cuts["basis"],
            "max_order": ra._LOW_ORDER_CUT_MAX if cuts["basis"] == "low_order" else None,
            # Rare-event (sum) approximation over the cut sets found — an
            # upper bound on the top event when the list is complete.
            "probability_sum": ra._f(sum(p for _, p in ranked)),
        },
        "common_cause": common_cause,
        "n_gates": len(gates),
        "n_events": len(tree.events),
        "repyability_version": ra._repyability_version(),
    }


def fault_tree(
    graph: dict,
    resolve_subsystem: Optional[Callable[[str], dict]] = None,
    resolve_model=None,
    covariates: Optional[dict] = None,
    t: Optional[float] = None,
    t_max: Optional[float] = None,
) -> dict:
    """The fault tree of a builder graph, evaluated at time ``t``.

    ``t`` defaults to the calculator's importance time (see
    :func:`_default_time`; ``t_max`` is the calculator's axis limit, if set).
    A repairable diagram is evaluated at steady state and ``t`` is ignored.
    Raises :class:`AnalysisError` with a user-facing message when the diagram
    can't be converted.
    """
    unit = (graph.get("unit") or "").strip()
    if graph.get("repairable"):
        try:
            tree, event_info, unavailability = _repairable_tree(graph, resolve_model)
        except NotImplementedError:
            # No exact long-run values (one repair crew for wear-out lives,
            # say). Proof tests whose tests or repairs take time have them
            # since RePyability 0.12 (#159).
            raise AnalysisError(
                "The fault tree uses the blocks' exact long-run unavailabilities, which "
                "RePyability doesn't have for this diagram (limited repair crews for "
                "wear-out lives, say) — the Calculator tab simulates it."
            ) from None
        out = _payload(tree, {tree.top: {"label": None, "role": "top"}}, event_info, 1.0, "availability")
        out["unavailability"] = ra._f(unavailability)
        out["unit"] = unit
        out["notes"] = (
            ["This tree is over the blocks alone: its common-cause groups aren't in it (the Calculator "
             "tab's availability takes them in)."]
            if graph.get("ccf_groups") else []
        )
        return out

    if t is not None:
        try:
            t = float(t)
        except (TypeError, ValueError):
            raise AnalysisError("The time must be a number.") from None
        if not (np.isfinite(t) and t > 0):
            raise AnalysisError("The time must be a positive number.")
    b = _Builder(resolve_subsystem, resolve_model, covariates)
    top = _develop(b, graph, "", [], set(), top_level=True)
    with warnings.catch_warnings():
        # A probability-basis group past its range is noted below at the
        # tree's own time, not over the calculator's whole time axis.
        warnings.filterwarnings("ignore", message=r"Common-cause group \[")
        t_default = _default_time(graph, resolve_subsystem, resolve_model, covariates, t_max)
    b.gate_info[top] = {"label": None, "role": "top"}
    tree = FaultTree(b.gates, b.events, top=top)
    t_eval = t if t is not None else t_default
    out = _payload(tree, b.gate_info, b.event_info, t_eval, "reliability")
    out["t_default"] = t_default
    out["unit"] = unit
    out["notes"] = _ccf_notes(out["common_cause"])
    return out


def _ccf_notes(groups: list) -> list[str]:
    """A note for each probability-basis group whose members' probability of
    failing is past the small values the split is meant for (RePyability's
    ``VALIDITY``), as the calculator relays RePyability's warning (#210)."""
    notes = []
    for g in groups:
        beta, p = g.get("beta"), g.get("probability")
        if g.get("basis") != "probability" or not beta or p is None:
            continue
        q = p / beta  # the shared cause occurs with beta * Q
        if q > CCF_VALIDITY:
            notes.append(
                f"{g['label']} (β = {beta:g}, probability basis): its members' probability of failing is "
                f"{q:.3g} here, beyond the {CCF_VALIDITY:g} the probability split is meant for — a rare-event "
                "model, which understates the common cause over a lifetime. Set the group's basis to rate "
                "(Reliafy's default) for lifetime figures.")
    return notes


def fault_tree_for_owner(
    db,
    graph: dict,
    owner_id,
    t: Optional[float] = None,
    t_max: Optional[float] = None,
    covariates: Optional[dict] = None,
) -> dict:
    """:func:`fault_tree` with sub-systems and saved models resolved in the
    caller's scope, exactly as ``rbds.analyze_graph`` resolves them."""
    from backend.services import models as models_service
    from backend.services import rbds as rbds_service

    def resolve_subsystem(sub_id: str) -> dict | None:
        sub = rbds_service.get_rbd(db, sub_id, owner_id)
        return sub.graph if sub is not None else None

    def resolve_model(model_id: str) -> dict | None:
        return models_service.get_live_model(db, model_id, owner_id)

    return fault_tree(
        graph,
        resolve_subsystem=resolve_subsystem,
        resolve_model=resolve_model,
        covariates=covariates,
        t=t,
        t_max=t_max,
    )
