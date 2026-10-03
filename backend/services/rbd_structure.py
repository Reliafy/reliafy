"""A diagram's logical structure at a glance, without its life models (#187).

An import preview has to show *how* the blocks are arranged, not just which
blocks there are, so the conversion can be checked before saving. Two views,
both from RePyability's own reduction of the drawn graph (life models play no
part, so blocks still lacking one are fine):

* ``structure`` — one line, e.g. ``(PA ∥ PB) → MCC → Valve → 2-of-3(C1, C2,
  C3)``: ``→`` series, ``∥`` parallel, ``k-of-n(...)`` voting. It is read off
  RePyability's modular (series–parallel) decomposition, so a mesh of
  connections reads as the series–parallel structure it is. It describes the
  drawing: a repeated block (``↺ S``) appears in each place it is drawn.
  Junctions and voting nodes (``knode``) are drawing devices and don't
  appear; a part that isn't series–parallel (a bridge) is shown as
  ``network of (...)`` over its modules — its minimal cut sets say the rest.
* ``min_cut_sets`` — the smallest minimal cut sets, by block label, with
  their count (exact, or low-order only for a large diagram, when the count
  may be unknown; see :func:`backend.services.rbd_analysis._structure_sets`).

Everything is best-effort: a diagram that can't be reduced (or is too large)
just gets no structure.
"""

from __future__ import annotations

from typing import Any

from backend.services import rbd_analysis, rbd_repeats

MAX_BLOCKS = 2000         # describe the structure up to this many blocks
MAX_CUT_SET_BLOCKS = 300  # list cut sets up to this many blocks
LISTED_CUT_SETS = 20
MAX_CHARS = 600           # the one-line structure, truncated beyond

SERIES_SEP, PARALLEL_SEP = " → ", " ∥ "


def _build(graph: dict):
    """``(rbd, drawn, labels, knodes)``, or None: ``rbd`` is the diagram's
    structure (a repeated block is one component) and ``drawn`` the drawing
    (each copy standing alone; None without copies). Every component stands
    in with the same placeholder life model."""
    import surpyval as sp
    from repyability.rbd.helper_classes import PerfectReliability
    from repyability.rbd.non_repairable_rbd import NonRepairableRBD

    nodes = [n for n in graph.get("nodes") or [] if isinstance(n, dict)]
    edges = [(e["source"], e["target"]) for e in graph.get("edges") or []
             if isinstance(e, dict) and e.get("source") and e.get("target")]
    ids = {n.get("id") for n in nodes}
    if not edges or "input" not in ids or "output" not in ids:
        return None
    repeats, problems = rbd_repeats.find_repeats(nodes)
    if problems:
        return None
    stand_in = sp.Exponential.from_params([1.0])
    reliabilities: dict[Any, Any] = {}
    k: dict[Any, int] = {}
    labels: dict[Any, str] = {}
    knodes: set = set()
    for n in nodes:
        nid, ntype = n.get("id"), n.get("type")
        if ntype in ("input", "output"):
            continue
        data = n.get("data") or {}
        labels[nid] = data.get("label") or str(nid)
        if nid in repeats:
            reliabilities[nid] = repeats[nid]
        elif ntype == "knode":
            reliabilities[nid] = PerfectReliability
            k[nid] = max(int(data.get("n") or 1), 1)
            knodes.add(nid)
        else:
            reliabilities[nid] = stand_in
    if not reliabilities or len(reliabilities) - len(knodes) > MAX_BLOCKS:
        return None
    labels.update(rbd_repeats.copy_labels(nodes, repeats))
    if repeats and not rbd_repeats.core_search_fits(edges, reliabilities, repeats, k, "input", "output"):
        return None
    def make(rel):
        return NonRepairableRBD(edges, rel, k=k, input_node="input", output_node="output",
                                on_infeasible_rbd="raise")

    drawn = make({n: stand_in if n in repeats else m for n, m in reliabilities.items()}) if repeats else None
    return make(reliabilities), drawn, labels, knodes


def _one_line(rbd, labels: dict, knodes: set) -> str:
    from repyability.rbd.modular import KOON, NODE, PARALLEL, SERIES

    dec = rbd._decomposition()
    if dec.always_works:
        return "always works (the input is wired straight to the output)"
    # Terms are in post-order, so each one's children are rendered first.
    # Each entry is (text, kind), kind None for a single block; knodes are None.
    out: list = []
    for term in dec.terms:
        if term[0] == NODE:
            out.append(None if term[1] in knodes else (labels.get(term[1], str(term[1])), None))
            continue
        kids = [out[c] for c in term[1] if out[c] is not None]
        if term[0] != SERIES:  # unordered: list members alphabetically
            kids.sort(key=lambda kid: kid[0])
        if term[0] == KOON:
            text = f"{term[2]}-of-{len(term[1])}(" + ", ".join(t for t, _ in kids) + ")"
            out.append((text, None))
            continue
        kind = SERIES if term[0] == SERIES else PARALLEL
        if not kids:
            out.append(None)
        elif len(kids) == 1:
            out.append(kids[0])
        else:
            parts = [f"({t})" if k not in (None, kind) else t for t, k in kids]
            out.append(((SERIES_SEP if kind == SERIES else PARALLEL_SEP).join(parts), kind))
    if dec.root is not None:
        top = out[dec.root]
        return top[0] if top else "always works"
    # A core that isn't series-parallel: name its top-level modules.
    used = {c for term in dec.terms if term[0] != NODE for c in term[1]}
    parts = sorted(out[i] for i in range(len(dec.terms)) if i not in used and out[i] is not None)
    return "network of (" + ", ".join(f"({t})" if k else t for t, k in parts) + ")"


def describe(graph: dict) -> dict:
    """``{structure, min_cut_sets, n_min_cut_sets, cut_sets_complete}`` for a
    persisted (normalised) graph — only the keys that could be worked out."""
    try:
        built = _build(graph)
    except Exception:  # noqa: BLE001 - a preview aid, never an error
        return {}
    if built is None:
        return {}
    rbd, drawn, labels, knodes = built
    out: dict = {}
    try:
        line = _one_line(drawn or rbd, labels, knodes)
        out["structure"] = line if len(line) <= MAX_CHARS else line[:MAX_CHARS - 1] + "…"
    except Exception:  # noqa: BLE001
        pass
    if len(labels) - len(knodes) <= MAX_CUT_SET_BLOCKS:
        try:
            sets = rbd_analysis._structure_sets(rbd)
            # A knode never fails itself, so a "cut" through one isn't real.
            named = sorted((sorted(labels.get(n, str(n)) for n in s) for s in sets["cuts"]
                            if not knodes & set(s)), key=lambda s: (len(s), s))
            out["min_cut_sets"] = named[:LISTED_CUT_SETS]
            # The count: exact when every set was listed; a partial count
            # would include cuts through knodes.
            out["n_min_cut_sets"] = (len(named) if sets["cuts_complete"]
                                     else None if knodes else sets["n_cuts"])
            out["cut_sets_complete"] = sets["cuts_complete"]
        except Exception:  # noqa: BLE001
            pass
    return out
