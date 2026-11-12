"""Expand a diagram's sub-system blocks into their own blocks (Nov 2026).

A diagram built from an asset tree makes a sub-assembly (a pump set holding a pump and its motor)
a sub-system block: its own RBD. A repairable diagram can't take sub-system blocks (availability
is worked out on component and standby blocks and k-of-n gates, and RePyability's repairable RBD
doesn't nest), and the Maintenance plan reads only component blocks, so the tasks on the positions
inside never reached the plan. Expanding puts each sub-system's blocks into the diagram in its
place, wired exactly as they were inside it: every path through the sub-system block becomes a
path from the blocks before it, through its inner blocks, to the blocks after it. Series stays
series, parallel stays parallel, and a vote stays a vote (where the sub-system fed a k-of-n gate
through several branches, a 1-of-n junction keeps it one input, as it was).

The result is a new layout to look over and save; nothing is saved here.
"""

from __future__ import annotations

from typing import Callable, Optional

from backend.units import canonical_unit

MAX_DEPTH = 6


class FlattenError(ValueError):
    """A sub-system that can't be expanded, in words."""


def _sub_ref(node: dict) -> Optional[str]:
    data = node.get("data") or {}
    return ((data.get("rbd") or {}).get("id")) or data.get("subsystem_rbd_id") or node.get("subsystem_rbd_id")


def _label(node: dict) -> str:
    return (node.get("data") or {}).get("label") or node.get("label") or node.get("id") or "a sub-system"


def _io(graph: dict) -> tuple[set, set]:
    ins = {n["id"] for n in graph.get("nodes") or [] if n.get("type") == "input"}
    outs = {n["id"] for n in graph.get("nodes") or [] if n.get("type") == "output"}
    return ins, outs


def _junction(nid: str, label: str, count: int) -> dict:
    return {"id": nid, "type": "knode", "data": {"label": label, "n": 1, "k": count}}


def expand(graph: dict, resolve_subsystem: Callable[[str], Optional[dict]], _depth: int = 0,
           _seen: frozenset = frozenset()) -> tuple[dict, list[str]]:
    """``(graph, expanded labels)``: ``graph`` with every sub-system block replaced by its own
    blocks (nested ones too), positions dropped so it is laid out afresh. Raises
    :class:`FlattenError` for a sub-system that can't be read, refers to itself, is in another
    time unit, or nests deeper than :data:`MAX_DEPTH`."""
    nodes = [dict(n) for n in graph.get("nodes") or [] if isinstance(n, dict)]
    edges = [{"source": e.get("source"), "target": e.get("target")} for e in graph.get("edges") or []
             if isinstance(e, dict)]
    unit = canonical_unit(graph.get("unit") or "")
    expanded: list[str] = []
    for node in [n for n in nodes if n.get("type") == "subsystem"]:
        label = _label(node)
        sub_id = _sub_ref(node)
        if not sub_id:
            raise FlattenError(f"“{label}” has no sub-system RBD to expand.")
        if sub_id in _seen:
            raise FlattenError(f"“{label}” contains itself, so it can't be expanded.")
        if _depth >= MAX_DEPTH:
            raise FlattenError(f"“{label}” is nested more than {MAX_DEPTH} deep.")
        sub = resolve_subsystem(sub_id)
        if not sub:
            raise FlattenError(f"“{label}”: its sub-system RBD isn't there any more (deleted, or not shared with you).")
        sub_unit = canonical_unit(sub.get("unit") or "")
        if unit and sub_unit and sub_unit != unit:
            raise FlattenError(f"“{label}” is in {sub.get('unit')}, the diagram in {graph.get('unit')}: its blocks "
                               "can't be put in this diagram as they are.")
        sub, inner_expanded = expand(sub, resolve_subsystem, _depth + 1, _seen | {sub_id})
        expanded += inner_expanded
        s_in, s_out = _io(sub)
        taken = {n["id"] for n in nodes}
        rename = {}
        inner = []
        for n in sub.get("nodes") or []:
            if n.get("id") in s_in or n.get("id") in s_out:
                continue
            new = n["id"] if n["id"] not in taken else f"{node['id']}-{n['id']}"
            rename[n["id"]] = new
            taken.add(new)
            inner.append({k: v for k, v in n.items() if k not in ("position", "positionAbsolute", "selected")}
                         | {"id": new})
        preds = [e["source"] for e in edges if e["target"] == node["id"]]
        succs = [e["target"] for e in edges if e["source"] == node["id"]]
        types = {n["id"]: n.get("type") for n in nodes} | {n["id"]: n.get("type") for n in inner}
        sub_edges = [{"source": e.get("source"), "target": e.get("target")} for e in sub.get("edges") or []]
        entries = [rename[e["target"]] for e in sub_edges if e["source"] in s_in and e["target"] in rename]
        exits = [rename[e["source"]] for e in sub_edges if e["target"] in s_out and e["source"] in rename]
        through = any(e["source"] in s_in and e["target"] in s_out for e in sub_edges)
        # A k-of-n gate counts its inputs: keep the sub-system one input to it, as it was.
        if len(preds) > 1 and any(types.get(t) == "knode" for t in entries):
            jid = f"{node['id']}-in"
            inner.append(_junction(jid, f"Into {label}", len(preds)))
            sub_edges = [{"source": jid, "target": e["target"]} if e["source"] in s_in else e for e in sub_edges]
            sub_edges.append({"source": next(iter(s_in)), "target": jid})
            rename[jid] = jid
        if (len(exits) + (1 if through else 0)) > 1 and any(types.get(t) == "knode" for t in succs):
            jid = f"{node['id']}-out"
            inner.append(_junction(jid, f"Out of {label}", len(exits) + (1 if through else 0)))
            sub_edges = [{"source": e["source"], "target": jid} if e["target"] in s_out else e for e in sub_edges]
            sub_edges.append({"source": jid, "target": next(iter(s_out))})
            rename[jid] = jid
        new_edges = []
        for e in sub_edges:
            srcs = preds if e["source"] in s_in else [rename.get(e["source"])]
            tgts = succs if e["target"] in s_out else [rename.get(e["target"])]
            new_edges += [{"source": s, "target": t} for s in srcs for t in tgts if s and t]
        nodes = [n for n in nodes if n["id"] != node["id"]] + inner
        edges = [e for e in edges if node["id"] not in (e["source"], e["target"])] + new_edges
        expanded.append(label)
    if not expanded:
        return graph, []
    seen, unique = set(), []
    for e in edges:
        key = (e["source"], e["target"])
        if key not in seen:
            seen.add(key)
            unique.append(e)
    # Each vote's k is the number of branches wired into it now.
    into = {}
    for e in unique:
        into[e["target"]] = into.get(e["target"], 0) + 1
    nodes = [{**n, "data": {**(n.get("data") or {}), "k": into.get(n["id"], 1)}} if n.get("type") == "knode" else n
             for n in nodes]
    out = {k: v for k, v in graph.items() if k not in ("nodes", "edges")}
    out["nodes"] = [{k: v for k, v in n.items() if k not in ("position", "positionAbsolute", "selected")} for n in nodes]
    out["edges"] = unique
    return out, expanded


def expand_saved(db, graph: dict, owners) -> dict:
    """The REST answer: {graph (normalised, laid out), expanded [labels], notes}. Raises
    FlattenError, or rbd_graph.GraphError."""
    from backend.services import models as models_service
    from backend.services import rbds as rbds_service
    from backend.services.rbd_graph import normalize_graph, wrap_layout

    def resolve(sub_id: str) -> Optional[dict]:
        doc = rbds_service.get_rbd(db, sub_id, owners)
        return doc.graph if doc is not None else None

    flat, expanded = expand(graph or {}, resolve)
    if not expanded:
        return {"graph": graph, "expanded": [], "notes": ["There are no sub-system blocks to expand."]}
    norm = normalize_graph(flat, resolve_saved_model=lambda mid: models_service.get_model(db, mid, owners))
    norm["nodes"] = wrap_layout(norm["nodes"])
    names = ", ".join(f"“{x}”" for x in expanded)
    notes = [f"Expanded {names} into {'its' if len(expanded) == 1 else 'their'} own blocks, wired as inside "
             f"{'it' if len(expanded) == 1 else 'them'}. Look it over and save."]
    if graph.get("repairable"):
        notes.append("Each new block needs a repair time before the diagram calculates.")
    return {"graph": norm, "expanded": expanded, "notes": notes}
