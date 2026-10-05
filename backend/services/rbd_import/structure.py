"""A diagram's structure in a few words, for import previews (#187).

``import_rbd(save=false)`` exists so the conversion can be checked before
saving, which a bare node list doesn't allow. :func:`describe` reads a
persisted (normalised) graph and returns:

* ``structure`` — one line such as ``MCC → Valve → (PA ∥ PB)``, when the
  diagram is series-parallel (k-of-n voting included: ``2-of-3(S1, S2, S3)``);
  ``None`` for a bridge or any other wiring that isn't, with the edges then
  the way to read it. A repeated block is marked ↺;
* ``cut_sets`` — the block-level minimal cut sets (the smallest groups of
  blocks whose failure fails the system), smallest first, derived from that
  expression. Repeated blocks count as their original. Common-cause groups,
  standby switching and sub-systems' insides aren't expanded — a block is one
  event here.

Pure graph work: no life models are read, so it also describes a diagram
whose blocks still need one. Sizes are bounded (:data:`MAX_BLOCKS`,
:data:`MAX_CUT_SETS`); past them the field is ``None``.
"""

from __future__ import annotations

from itertools import combinations, count, product
from typing import Optional

from backend.services import rbd_repeats

MAX_BLOCKS = 300          # blocks beyond which no structure is attempted
MAX_CUT_SETS = 2000       # intermediate cut sets beyond which they aren't listed
LISTED_CUT_SETS = 20
_MAX_LINE = 600           # characters in the one-line structure

# Expressions: ("blk", node id) | ("s", [exprs]) | ("p", [exprs]) | ("v", k, [exprs]) | ("wire",)
_WIRE = ("wire",)
_JUNCTIONS = count()


class _TooBig(Exception):
    pass


def _series(a, b):
    parts = []
    for e in (a, b):
        if e == _WIRE:
            continue
        parts.extend(e[1] if e[0] == "s" else [e])
    if not parts:
        return _WIRE
    return parts[0] if len(parts) == 1 else ("s", parts)


def _parallel(exprs):
    if any(e == _WIRE for e in exprs):
        return _WIRE  # a bare wire beside a block: that branch can't fail
    parts = []
    for e in exprs:
        parts.extend(e[1] if e[0] == "p" else [e])
    return parts[0] if len(parts) == 1 else ("p", parts)


def _reduce(graph: dict):
    """Series-parallel reduction of the diagram, or ``None`` when it isn't one.

    Each block becomes an edge (its in-vertex to its out-vertex); a k-of-n
    node (``knode``) stays a vertex, voting on its incoming branches once
    they all come from one place."""
    nodes = {n["id"]: n for n in graph.get("nodes") or []}
    vote: dict[str, int] = {}
    edges: list[list] = []  # [u, v, expr]

    def vin(nid):
        return nid if nodes[nid]["type"] in ("knode", "input", "output") else f"{nid}:in"

    def vout(nid):
        return nid if nodes[nid]["type"] in ("knode", "input", "output") else f"{nid}:out"

    for nid, n in nodes.items():
        if n["type"] == "knode":
            need = int((n.get("data") or {}).get("n") or 1)
            if need > 1:
                vote[nid] = need
        elif n["type"] not in ("input", "output"):
            edges.append([vin(nid), vout(nid), ("blk", nid)])
    for e in graph.get("edges") or []:
        if e.get("source") in nodes and e.get("target") in nodes:
            edges.append([vout(e["source"]), vin(e["target"]), _WIRE])

    changed = True
    while changed and len(edges) > 1:
        changed = False
        # Parallel: edges sharing both ends (a voting vertex only once every
        # one of its incoming branches has arrived from the same vertex).
        groups: dict[tuple, list[int]] = {}
        for i, (u, v, _) in enumerate(edges):
            groups.setdefault((u, v), []).append(i)
        into: dict[str, int] = {}
        for u, v, _ in edges:
            into[v] = into.get(v, 0) + 1
        for (u, v), idx in groups.items():
            if v in vote:
                if len(idx) != into[v]:
                    continue
                k = vote.pop(v)
                exprs = [edges[i][2] for i in idx]
                if k > len(exprs):
                    return None  # needs more branches than it has: nothing to describe
                merged = ("v", k, exprs) if k < len(exprs) else _series_all(exprs)
            elif len(idx) > 1:
                merged = _parallel([edges[i][2] for i in idx])
            else:
                continue
            keep = set(idx[1:])
            edges[idx[0]][2] = merged
            edges = [e for i, e in enumerate(edges) if i not in keep]
            changed = True
            break
        if changed:
            continue
        # Series: a vertex with exactly one edge in and one out.
        ins: dict[str, list[int]] = {}
        outs: dict[str, list[int]] = {}
        for i, (u, v, _) in enumerate(edges):
            outs.setdefault(u, []).append(i)
            ins.setdefault(v, []).append(i)
        for w in ins:
            if w in ("input", "output") or w in vote:
                continue
            if len(ins[w]) == 1 and len(outs.get(w, [])) == 1:
                a, b = ins[w][0], outs[w][0]
                if a == b:
                    return None
                edges[a] = [edges[a][0], edges[b][1], _series(edges[a][2], edges[b][2])]
                del edges[b]
                changed = True
                break
        if changed:
            continue
        changed = _collapse_mesh(edges, vote, ins, outs)
    if len(edges) == 1 and edges[0][0] == "input" and edges[0][1] == "output" and not vote:
        return edges[0][2]
    return None


def _collapse_mesh(edges: list, vote: dict, ins: dict, outs: dict) -> bool:
    """Every exit of one group wired to every entry of the next (how two
    parallel groups are put in series) is the same as wiring them through a
    perfect junction: rewire one such mesh that way. Edges go from |X|·|Y| to
    |X| + |Y|, so the reduction still terminates."""
    by_targets: dict[frozenset, list[str]] = {}
    for u, idx in outs.items():
        if len(idx) < 2 or any(edges[i][2] != _WIRE for i in idx):
            continue
        targets = frozenset(edges[i][1] for i in idx)
        if len(targets) == len(idx):
            by_targets.setdefault(targets, []).append(u)
    for targets, sources in by_targets.items():
        if len(sources) < 2:
            continue
        group = set(sources)
        if any(y in vote for y in targets):
            continue  # a voting node counts its incoming branches
        if not all(len(ins.get(y, [])) == len(group) and all(edges[i][0] in group and edges[i][2] == _WIRE
                                                            for i in ins[y]) for y in targets):
            continue
        junction = f"junction:{next(_JUNCTIONS)}"
        edges[:] = [e for e in edges if not (e[0] in group and e[1] in targets)]
        edges.extend([u, junction, _WIRE] for u in sorted(group))
        edges.extend([junction, y, _WIRE] for y in sorted(targets))
        return True
    return False


def _series_all(exprs):
    out = _WIRE
    for e in exprs:
        out = _series(out, e)
    return out


def _render(expr, label, top=True) -> str:
    kind = expr[0]
    if kind == "blk":
        return label(expr[1])
    if kind == "wire":
        return "(wire)"
    if kind == "s":
        text = " → ".join(_render(e, label, False) for e in expr[1])
        return text if top else f"({text})"
    if kind == "p":
        return "(" + " ∥ ".join(_render(e, label, False) for e in expr[1]) + ")"
    return f"{expr[1]}-of-{len(expr[2])}(" + ", ".join(_render(e, label, True) for e in expr[2]) + ")"


def _minimize(sets) -> list[frozenset]:
    out: list[frozenset] = []
    for s in sorted(set(sets), key=len):
        if not any(o <= s for o in out):
            out.append(s)
    if len(out) > MAX_CUT_SETS:
        raise _TooBig
    return out


def _cuts(expr, ident) -> list[frozenset]:
    """Minimal cut sets of an expression (an empty list: it never fails)."""
    kind = expr[0]
    if kind == "blk":
        return [frozenset([ident(expr[1])])]
    if kind == "wire":
        return []
    if kind == "s":
        return _minimize(c for e in expr[1] for c in _cuts(e, ident))
    if kind == "p":
        return _product([_cuts(e, ident) for e in expr[1]])
    k, kids = expr[1], expr[2]
    fail = len(kids) - k + 1  # branches that must fail to defeat a k-of-n vote
    kid_cuts = [_cuts(e, ident) for e in kids]
    out: list[frozenset] = []
    for combo in combinations(kid_cuts, fail):
        out.extend(_product(list(combo)))
        if len(out) > MAX_CUT_SETS * 4:
            raise _TooBig
    return _minimize(out)


def _product(lists: list[list[frozenset]]) -> list[frozenset]:
    if any(not lst for lst in lists):
        return []  # one branch never fails, so neither does the group
    size = 1
    for lst in lists:
        size *= len(lst)
        if size > MAX_CUT_SETS * 4:
            raise _TooBig
    return _minimize(frozenset().union(*combo) for combo in product(*lists))


def structure_line(graph: dict) -> Optional[str]:
    """Just the one-line structure of :func:`describe` (no cut sets): for
    create_rbd / edit_rbd results (#265). ``None`` when it can't be given."""
    return describe(graph, cut_sets=False)["structure"]


def describe(graph: dict, cut_sets: bool = True) -> dict:
    """``{"structure", "cut_sets", "n_cut_sets"}`` for a persisted graph
    (see the module docstring); fields that can't be given are ``None``.
    ``cut_sets=False``: the structure line alone."""
    nodes = graph.get("nodes") or []
    blocks = [n for n in nodes if n.get("type") not in ("input", "output", "knode")]
    out: dict = {"structure": None, "cut_sets": None, "n_cut_sets": None}
    if not blocks or len(blocks) > MAX_BLOCKS:
        return out
    by_id = {n["id"]: n for n in nodes}

    def label(nid: str) -> str:
        n = by_id[nid]
        d = n.get("data") or {}
        text = str(d.get("label") or nid)
        if n.get("type") in ("series", "parallel") and d.get("n"):
            text += f" ×{d['n']} ({n['type']})"
        return text

    def ident(nid: str) -> str:
        return rbd_repeats.repeat_of(by_id[nid]) or nid

    def drawn(nid: str) -> str:
        """A block as drawn: a repeated block is marked ↺ (it's the original)."""
        text = label(nid)
        return f"{text} {rbd_repeats.REPEAT_MARK}" if ident(nid) != nid and not text.startswith(
            rbd_repeats.REPEAT_MARK) else text

    expr = _reduce(graph)
    if expr is None:
        return out
    line = _render(expr, drawn)
    out["structure"] = line if len(line) <= _MAX_LINE else line[:_MAX_LINE - 1] + "…"
    if not cut_sets:
        return out
    try:
        cuts = _cuts(expr, ident)
    except (_TooBig, RecursionError):
        return out
    cuts.sort(key=lambda s: (len(s), sorted(label(i) for i in s)))
    out["n_cut_sets"] = len(cuts)
    out["cut_sets"] = [sorted(label(i) for i in s) for s in cuts[:LISTED_CUT_SETS]]
    return out
