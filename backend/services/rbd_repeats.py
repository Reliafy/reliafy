"""Repeated blocks: one component drawn in several places of a diagram (#102).

A shared power supply feeding two trains, or a basic event under several
fault-tree gates, is one physical component that a block diagram has to draw
more than once. In a Reliafy graph the extra appearances are *linked copies*:
a ``component`` node whose ``data.repeat_of`` names the node it repeats. A
copy has its own position and connections but no model of its own — it is the
original, so it works or has failed wherever it is drawn.

RePyability (0.9+) takes exactly this: in ``NonRepairableRBD``'s
``reliabilities`` a value that is the *name of another node* makes the key a
repeated node, and the exact engine, the path/cut sets, the importance
measures and the simulated lifetimes all treat every appearance as the one
component. ``RepairableRBD`` has no such notion (each node is simulated as its
own unit), so repairable diagrams refuse copies rather than silently making
them independent.

The rules, checked here for every consumer (analysis, validation, the compact
graph format, the Python export):

* the copy is a ``component`` node and its target a ``component`` node of the
  *same* diagram (a nested sub-system is a separate diagram, so a copy can't
  reach into or out of one);
* a copy can't repeat itself or another copy (no chains, so no cycles).

Old diagrams have no ``repeat_of`` anywhere and are unaffected.
"""

from __future__ import annotations

from typing import Optional

REPEAT_KEY = "repeat_of"
# Marks a copy wherever it is named (canvas, results, errors).
REPEAT_MARK = "↺"


def repeat_of(node: dict) -> Optional[str]:
    """The id a node repeats, or None for an ordinary node."""
    target = (node.get("data") or {}).get(REPEAT_KEY)
    if target is None or target == "":
        return None
    return str(target)


def copy_label(label: str) -> str:
    """How a copy is named: the original's label, marked."""
    return f"{REPEAT_MARK} {label}"


def _label(node: dict) -> str:
    return (node.get("data") or {}).get("label") or str(node.get("id"))


def find_repeats(nodes: list[dict]) -> tuple[dict[str, str], dict[str, str]]:
    """``({copy id: original id}, {copy id: problem})`` for a diagram's nodes.

    A problem is a user-facing message for a copy that breaks the rules; such
    copies are left out of the first map (callers treat any problem as an
    error)."""
    by_id = {n.get("id"): n for n in nodes if isinstance(n, dict)}
    repeats: dict[str, str] = {}
    problems: dict[str, str] = {}
    for nid, node in by_id.items():
        target = repeat_of(node)
        if target is None:
            continue
        label = _label(node)
        original = by_id.get(target)
        if node.get("type") != "component":
            problems[nid] = (
                f"“{label}” is marked as a repeat of another block, but only a "
                "component block can be a repeated block.")
        elif target == str(nid):
            problems[nid] = f"“{label}” is marked as a repeat of itself."
        elif original is None:
            problems[nid] = (
                f"“{label}” repeats a block that isn't in this diagram. A repeated "
                "block must repeat a component of the same diagram (not one inside "
                "a sub-system).")
        elif repeat_of(original) is not None:
            problems[nid] = (
                f"“{label}” repeats “{_label(original)}”, which is itself a repeated "
                "block — repeat the original component instead.")
        elif original.get("type") != "component":
            problems[nid] = (
                f"“{label}” repeats “{_label(original)}”, a {original.get('type')} "
                "block. Only component blocks can be repeated.")
        else:
            repeats[nid] = target
    return repeats, problems


def copy_labels(nodes: list[dict], repeats: dict[str, str]) -> dict[str, str]:
    """``{copy id: "↺ <original's label>"}`` — a copy is named after the
    component it repeats (its own stored label may be stale)."""
    by_id = {n.get("id"): n for n in nodes if isinstance(n, dict)}
    return {c: copy_label(_label(by_id[t])) for c, t in repeats.items() if t in by_id}


# RePyability keeps every appearance of a repeated component out of its
# modules, so the part of the diagram they tie together is left as a "core"
# whose minimal path sets it lists by a memoised search over the drawn
# blocks. That is exact and quick for a shared supply or a few shared events,
# but a component repeated across a chain of voting groups (FFORT's "pcs"
# tree) makes the search's candidate lists explode and would tie the server up
# for many minutes. So the same search is first replayed here under a work
# budget (the set comparisons it makes), and a diagram over it is refused.
CORE_SEARCH_BUDGET = 15_000_000  # about a second of work, either way


def core_search_fits(edges, reliabilities: dict, repeats: dict, k: dict,
                     input_node=None, output_node=None) -> bool:
    """Whether RePyability's core search for this diagram finishes within
    :data:`CORE_SEARCH_BUDGET` (True when it can't be checked — the real
    build then reports the problem).

    The diagram is reduced exactly as RePyability reduces it (its private
    ``_Reduction``, with every appearance of a repeated component pinned out
    of the modules), then its path-set search (``min_path_sets``) is replayed
    on the core, counting the work and stopping at the budget."""
    from repyability.rbd.modular import _SINK, _Reduction
    from repyability.rbd.non_repairable_rbd import NonRepairableRBD

    # The same drawing with every copy standing alone: no repeated nodes, so
    # it reduces fully (and quickly); only its graph is needed.
    twin = {n: reliabilities[repeats[n]] if n in repeats else m for n, m in reliabilities.items()}
    try:
        rbd = NonRepairableRBD(edges, twin, k=k, input_node=input_node, output_node=output_node,
                               on_infeasible_rbd="ignore")
        if not rbd.structure_check.get("is_valid"):
            return True
        reduction = _Reduction(rbd.G, rbd.input_node, rbd.output_node,
                               pinned=set(repeats) | set(repeats.values()))
        reduction.run()
        if len(reduction.alive) <= 1:
            return True
        core = reduction.core_graph()
    except Exception:  # noqa: BLE001 - the real build reports the problem
        return True
    try:
        _BoundedSearch(core, CORE_SEARCH_BUDGET).paths(_SINK)
    except _OverBudget:
        return False
    return True


class _OverBudget(Exception):
    pass


class _BoundedSearch:
    """RePyability's ``min_path_sets`` (memoised at vertices with several
    successors; each k-of-n merge minimalised as it is formed), counting
    every set comparison against a budget."""

    def __init__(self, graph, budget: int):
        self.graph = graph
        self.budget = budget
        self.memo: dict = {}

    def paths(self, v) -> list:
        from itertools import combinations, product

        g = self.graph
        if v in self.memo:
            return self.memo[v]
        if g.in_degree(v) == 0:
            return [frozenset([v])]
        subs = [[s | {v} for s in self.paths(p)] for p in g.predecessors(v)]
        subs = [s for s in subs if s]
        out: list = []
        for comb in combinations(range(len(subs)), g.nodes[v]["k"]):
            for tup in product(*(subs[i] for i in comb)):
                s = frozenset().union(*tup)
                minimal, kept = True, []
                for i, o in enumerate(out):
                    if s >= o:
                        minimal = False
                        self.budget -= i + 1
                        break
                    if not s <= o:
                        kept.append(o)
                else:
                    self.budget -= len(out) + 1
                # Forming the candidate costs about ten comparisons.
                self.budget -= 10
                if self.budget < 0:
                    raise _OverBudget
                if minimal:
                    kept.append(s)
                    out = kept
        if g.out_degree(v) > 1:
            self.memo[v] = out
        return out


CORE_MESSAGE = (
    "The repeated blocks tie together too much of this diagram to analyse it "
    "exactly in reasonable time (the paths through the blocks they link are too "
    "many to list). Repeat fewer blocks: where a shared component matters "
    "little, draw it as separate blocks.")


def repairable_message(nodes: list[dict], repeats: dict[str, str]) -> str:
    """Why a repairable diagram with repeated blocks can't be analysed."""
    by_id = {n.get("id"): n for n in nodes if isinstance(n, dict)}
    names = sorted({_label(by_id[t]) for t in repeats.values() if t in by_id})
    shown = ", ".join(f"“{n}”" for n in names[:4]) + (" and more" if len(names) > 4 else "")
    return (
        f"Repeated blocks{f' ({shown})' if shown else ''} are supported in non-repairable (reliability) "
        "diagrams only: availability analysis simulates every block as its own "
        "unit, which would make the copies independent and change the answer. "
        "Switch the diagram to non-repairable, or draw separate components.")
