"""Fault tree -> reliability block diagram conversion (shared by the Open-PSA
and Galileo importers).

A fault tree describes *failure* logic, an RBD *success* paths, so the gates
map by duality:

* OR  (fails if any child fails)            -> series
* AND (fails only if every child fails)     -> parallel
* at-least-``m``-of-``n`` children failed    -> k-of-n voting node requiring
  ``n - m + 1`` working branches

Reliafy's graph is path based: the system works iff the output is reachable
from the input through working blocks, where a ``knode`` passes only if at
least ``n`` of its incoming branches do. The graph is built recursively; every
sub-tree becomes a *part* with a list of entry nodes (fed from upstream) and
exit nodes (feeding downstream):

* series  — every exit of one part is wired to every entry of the next (or,
  when that would be a large mesh, through a junction knode);
* parallel — the parts' entries and exits are unioned;
* voting  — each child is collapsed to a single exit (a junction ``knode``
  with ``n = 1`` is a perfect OR-join) so the voting node counts exactly one
  incoming branch per child.

Entries are always real blocks (never knodes), so upstream fan-in can't be
mistaken for voting branches.

*Repeated events* — one basic event under several gates, directly or through
a gate used in more than one place — are drawn once per appearance: the first
is the event's block, the others are repeated blocks (``repeat_of`` the
first), which the analysis treats as the one component. The diagram is then
exactly the tree. Repeated blocks are reliability-only, so a repairable tree
with repeated events is imported as non-repairable (with a warning).

What can't be represented honestly raises :class:`RbdImportError`:
non-coherent logic (NOT / XOR), and a repeated event that isn't a plain
component (e.g. a Galileo spare gate used under two gates).

Constant events are folded away first: an event that can never fail (house
event ``false``, probability 0) drops out of the logic, and one that has
certainly failed (house event ``true``, probability 1) propagates through the
gates. If the top event itself becomes constant the tree has no diagram.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from typing import Optional, Union

from .types import RbdImportError

# Guards for untrusted input.
MAX_DEPTH = 100          # gate nesting depth (well beyond real trees; bounds recursion)
MAX_BLOCKS = 5000        # blocks in the produced diagram
MAX_EDGES = 50000
# Wire two parts directly (every exit -> every entry) up to this many edges;
# beyond it route through a junction node to keep the diagram readable.
JUNCTION_THRESHOLD = 16

GATE_OPS = ("or", "and", "atleast")


@dataclass
class Leaf:
    """A basic event (or a pre-built block such as a standby group).

    ``node`` holds the compact-graph fields for the block (``type``,
    ``model``, ``repair``, ``spares``, ...) without ``id``/``label``.
    ``constant`` marks an event with no time behaviour: ``True`` = certainly
    failed, ``False`` = never fails (``node`` is then ignored).
    """

    name: str
    node: Optional[dict] = None
    constant: Optional[bool] = None
    label: Optional[str] = None


@dataclass
class Gate:
    """``op`` is ``or``/``and``/``atleast``; ``k`` = failed children needed
    to fail an ``atleast`` gate. ``children`` are names in the tree."""

    name: str
    op: str
    children: list[str] = field(default_factory=list)
    k: Optional[int] = None
    label: Optional[str] = None


Node = Union[Leaf, Gate]


@dataclass
class FaultTree:
    nodes: dict[str, Node]
    top: str


# ---------------------------------------------------------------------------
# Simplified expression: ("leaf", name) | (op, k, [exprs]) | True | False
# ---------------------------------------------------------------------------


def _simplify(tree: FaultTree):
    """Fold constants and degenerate gates. Returns ``(expr, labels)`` where
    ``labels`` maps ``id(expr)`` of each voting expression to its gate's name."""
    memo: dict[str, object] = {}
    visiting: set[str] = set()
    labels: dict[int, str] = {}

    def visit(name: str, depth: int):
        if depth > MAX_DEPTH:
            raise RbdImportError(
                f"The fault tree is nested more than {MAX_DEPTH} gates deep — too deep to import.")
        if name in memo:
            return memo[name]
        node = tree.nodes.get(name)
        if node is None:
            raise RbdImportError(f"“{name}” is used in the fault tree but never defined.")
        if name in visiting:
            raise RbdImportError(f"The fault tree has a loop through “{name}”.")
        if isinstance(node, Leaf):
            out = node.constant if node.constant is not None else ("leaf", name)
            memo[name] = out
            return out
        visiting.add(name)
        try:
            kids = [visit(c, depth + 1) for c in node.children]
        finally:
            visiting.discard(name)
        out = _fold(node, kids)
        if isinstance(out, tuple) and out[0] == "atleast":
            labels.setdefault(id(out), node.label or name)
        memo[name] = out
        return out

    return visit(tree.top, 0), labels


def _fold(gate: Gate, kids: list):
    op = gate.op
    n_all = len(kids)
    if not n_all:
        raise RbdImportError(f"Gate “{gate.name}” has no inputs.")
    failed = sum(1 for c in kids if c is True)
    rest = [c for c in kids if c is not True and c is not False]
    if op == "or":
        k = 1
    elif op == "and":
        k = n_all
    elif op == "atleast":
        k = int(gate.k or 0)
        if k < 1 or k > n_all:
            raise RbdImportError(
                f"Gate “{gate.name}” needs {k} of its {n_all} inputs to fail — "
                "that's impossible to meet.")
    else:  # pragma: no cover - importers only build the three ops
        raise RbdImportError(f"Gate “{gate.name}”: unsupported logic “{op}”.")
    k -= failed
    n = len(rest)
    if k <= 0:
        return True
    if k > n:
        return False
    if k == 1:
        op_out = "or"
    elif k == n:
        op_out = "and"
    else:
        op_out = "atleast"
    if n == 1:
        return rest[0]
    if op_out in ("or", "and"):
        # Flatten nested gates of the same kind (series of series, ...).
        flat = []
        for c in rest:
            if isinstance(c, tuple) and c[0] == op_out:
                flat.extend(c[2])
            else:
                flat.append(c)
        return (op_out, None, flat)
    return ("atleast", k, rest)


def _leaves(expr) -> set[str]:
    out, seen, stack = set(), set(), [expr]
    while stack:
        e = stack.pop()
        if e[0] == "leaf":
            out.add(e[1])
        elif id(e) not in seen:
            seen.add(id(e))
            stack.extend(e[2])
    return out


def _repeated(expr) -> list[str]:
    """Basic events reached more than once from the top. Linear in the size
    of the (shared) expression DAG: a sub-expression met twice has all of its
    events repeated, without walking it again."""
    counts: dict[str, int] = {}
    repeated: set[str] = set()
    seen: set[int] = set()
    stack = [expr]
    while stack:
        e = stack.pop()
        if e[0] == "leaf":
            counts[e[1]] = counts.get(e[1], 0) + 1
            if counts[e[1]] > 1:
                repeated.add(e[1])
        elif id(e) in seen:
            repeated |= _leaves(e)
        else:
            seen.add(id(e))
            stack.extend(e[2])
    return sorted(repeated)


def repeated_events(tree: FaultTree) -> list[str]:
    """Names of basic events that appear more than once under the top event
    (directly, or through a gate used in more than one place)."""
    expr, _ = _simplify(tree)
    if isinstance(expr, bool):
        return []
    return _repeated(expr)


def _describe(names: list[str], limit: int = 8) -> str:
    shown = ", ".join(f"“{n}”" for n in names[:limit])
    more = len(names) - limit
    return shown + (f" and {more} more" if more > 0 else "")


# ---------------------------------------------------------------------------
# Graph construction
# ---------------------------------------------------------------------------


class _Builder:
    def __init__(self, tree: FaultTree, labels: dict[int, str], junction_threshold: float):
        self.tree = tree
        self.labels = labels
        self.junction_threshold = junction_threshold
        self.nodes: list[dict] = []
        self.edges: list[dict] = []
        self.ids: set[str] = {"input", "output"}
        self.leaf_ids: dict[str, str] = {}

    def _new_id(self, base: str) -> str:
        slug = re.sub(r"[^A-Za-z0-9_.:-]+", "_", base).strip("_") or "node"
        slug = slug[:60]
        nid, i = slug, 2
        while nid in self.ids:
            nid = f"{slug}_{i}"
            i += 1
        self.ids.add(nid)
        if len(self.ids) > MAX_BLOCKS:
            raise RbdImportError(
                f"The diagram would have more than {MAX_BLOCKS} blocks — too large to import.")
        return nid

    def _edge(self, src: str, tgt: str):
        self.edges.append({"source": src, "target": tgt})
        if len(self.edges) > MAX_EDGES:
            raise RbdImportError("The diagram would have too many connections to import.")

    def _knode(self, label: str, required: int, branches: int) -> str:
        nid = self._new_id("junction" if required == 1 and label == "Junction" else label)
        self.nodes.append({"id": nid, "type": "knode", "label": label, "n": required, "k": branches})
        return nid

    def leaf(self, name: str) -> str:
        leaf = self.tree.nodes[name]
        nid = self._new_id(name)
        first = self.leaf_ids.get(name)
        if first is not None:
            # A repeated event: the same component, drawn again.
            node = {"id": nid, "type": "component", "repeat_of": first}
        else:
            self.leaf_ids[name] = nid
            node = {"id": nid, **(leaf.node or {})}
        node["label"] = leaf.label or name
        self.nodes.append(node)
        return nid

    def connect(self, exits: list[str], entries: list[str]):
        if len(exits) > 1 and len(entries) > 1 and len(exits) * len(entries) > self.junction_threshold:
            j = self._knode("Junction", 1, len(exits))
            for x in exits:
                self._edge(x, j)
            for e in entries:
                self._edge(j, e)
            return
        for x in exits:
            for e in entries:
                self._edge(x, e)

    def collapse(self, exits: list[str]) -> str:
        if len(exits) == 1:
            return exits[0]
        j = self._knode("Junction", 1, len(exits))
        for x in exits:
            self._edge(x, j)
        return j

    def build(self, expr) -> tuple[list[str], list[str]]:
        # Recursion depth is bounded by MAX_DEPTH (checked in _simplify).
        if expr[0] == "leaf":
            nid = self.leaf(expr[1])
            return [nid], [nid]
        op, k, kids = expr
        if op == "or":
            parts = [self.build(c) for c in kids]
            for (_, x), (e, _) in zip(parts, parts[1:]):
                self.connect(x, e)
            return parts[0][0], parts[-1][1]
        if op == "and":
            entries, exits = [], []
            for c in kids:
                e, x = self.build(c)
                entries += e
                exits += x
            return entries, exits
        # at least k of n failed -> n - k + 1 of n working
        n = len(kids)
        required = n - k + 1
        entries, singles = [], []
        for c in kids:
            e, x = self.build(c)
            entries += e
            singles.append(self.collapse(x))
        v = self._knode(self.labels.get(id(expr)) or f"{required} of {n}", required, n)
        for s in singles:
            self._edge(s, v)
        return entries, [v]


def to_graph(
    tree: FaultTree,
    unit: str = "",
    repairable: bool = False,
    ccf_groups: Optional[list[dict]] = None,
) -> tuple[dict, list[str]]:
    """Convert a coherent fault tree to a compact RBD graph.

    ``ccf_groups`` members are basic-event names; they are translated to the
    produced node ids (groups left with fewer than two members are dropped
    with a warning). Returns ``(graph, warnings)``.
    """
    warnings: list[str] = []
    expr, labels = _simplify(tree)
    if expr is True:
        raise RbdImportError(
            f"The top event “{tree.top}” has certainly occurred (it depends only on events "
            "set to true), so there is no reliability to analyse.")
    if expr is False:
        raise RbdImportError(
            f"The top event “{tree.top}” can never occur (every path to it is through events "
            "that never fail), so there is nothing to analyse.")

    repeated = _repeated(expr)
    if repeated:
        blocks = [n for n in repeated if (tree.nodes[n].node or {}).get("type", "component") != "component"]
        if blocks:
            raise RbdImportError(
                f"The fault tree uses {_describe(blocks)} under more than one gate. Only a "
                "basic event can be drawn as a repeated block; a group such as a spare gate "
                "can't be shared between branches, and copying it would treat the copies as "
                "independent and change the result — so this tree can't be imported as an RBD.")
        warnings.append(
            f"Basic events used under more than one gate ({_describe(repeated)}) are drawn in "
            "each place as a repeated block (↺): one component, which the analysis counts once.")
        if repairable:
            repairable = False
            warnings.append(
                "Imported as a non-repairable (reliability) diagram and its repair data dropped: "
                "repeated blocks aren't supported in availability analysis yet.")

    # Repairable diagrams wire parts directly: availability analysis models
    # every knode as a (very nearly) never-failing component, so a junction
    # there would add a sliver of unavailability of its own.
    b = _Builder(tree, labels, math.inf if repairable else JUNCTION_THRESHOLD)
    entries, exits = b.build(expr)
    if repeated:  # always non-repairable (above): no repair data to carry
        for node in b.nodes:
            node.pop("repair", None)
    for e in entries:
        b._edge("input", e)
    for x in exits:
        b._edge(x, "output")

    nodes = [
        {"id": "input", "type": "input", "label": "Input"},
        *b.nodes,
        {"id": "output", "type": "output", "label": "Output"},
    ]
    graph: dict = {"nodes": nodes, "edges": b.edges, "unit": unit or ""}
    if repairable:
        graph["repairable"] = True

    if ccf_groups:
        out_groups = []
        for g in ccf_groups:
            members = [b.leaf_ids[m] for m in g.get("members") or [] if m in b.leaf_ids]
            if len(members) < 2:
                warnings.append(
                    f"Common-cause group “{g.get('name') or '?'}” has fewer than two members "
                    "left in the diagram and was dropped.")
                continue
            out_groups.append({"members": members, "beta": float(g["beta"])})
        if out_groups:
            graph["ccf_groups"] = out_groups
    return graph, warnings


# ---------------------------------------------------------------------------
# Life-model helpers (SurPyval parameter names)
# ---------------------------------------------------------------------------


def exponential_model(rate: float) -> dict:
    """Exponential with failure *rate* (SurPyval's ``failure_rate``)."""
    return {"distribution_id": "exponential",
            "params": [{"name": "failure_rate", "value": float(rate)}]}


def weibull_model(scale: float, shape: float) -> dict:
    return {"distribution_id": "weibull",
            "params": [{"name": "alpha", "value": float(scale)}, {"name": "beta", "value": float(shape)}]}


def gamma_model(shape: float, rate: float) -> dict:
    """Gamma with shape ``alpha`` and *rate* ``beta`` (an Erlang when the
    shape is an integer)."""
    return {"distribution_id": "gamma",
            "params": [{"name": "alpha", "value": float(shape)}, {"name": "beta", "value": float(rate)}]}


def lognormal_model(mu: float, sigma: float) -> dict:
    return {"distribution_id": "lognormal",
            "params": [{"name": "mu", "value": float(mu)}, {"name": "sigma", "value": float(sigma)}]}


def model_key(model: Optional[dict]):
    """Hashable identity of an inline model (to compare spares)."""
    if not model:
        return None
    return (model.get("distribution_id"),
            tuple((p["name"], round(float(p["value"]), 12)) for p in model.get("params") or []))
