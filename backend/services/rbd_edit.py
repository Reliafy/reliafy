"""Batched, atomic edits to a saved RBD graph (the MCP ``edit_rbd`` tool).

An agent changes a diagram by sending a short list of operations instead of
re-sending the whole graph. :func:`apply_ops` applies them in order to a copy
of the persisted graph and returns the result plus one short line per op; it
never touches the database, so the caller validates the result as a whole and
saves it — or nothing — afterwards.

Ops (plain dicts, already shape-checked by the MCP layer's pydantic models)::

    {"op": "add_node", "node": {...compact node...},
     "between": [src, tgt] | "after": id | "before": id | "parallel_to": id}
    {"op": "remove_node", "id": ..., "reconnect": "auto" | "none"}
    {"op": "update_node", "id": ... | "ids": [...], "label"?, "model"?, ...}
    {"op": "add_edge", "source": ..., "target": ...}
    {"op": "remove_edge", "source": ..., "target": ...}
    {"op": "set", "name"?, "unit"?, "repairable"?}
    {"op": "add_ccf", "members": [...], "beta": ..., "id"?}
    {"op": "remove_ccf", "id": ...}

Layout: whenever an op changes which nodes exist or how they connect, the
whole diagram is re-laid out with :func:`rbd_graph.layout_graph` — the same
layered left-to-right layout ``create_rbd`` gives a new diagram (and the
builder's Auto-arrange), so new and rewired blocks never overlap. Positions
can't simply be cleared: the builder loads saved nodes as they are and needs
one on every node (only the public page falls back to auto-layout). A batch
that only changes labels, models or settings keeps the existing positions, so
an arrangement made by hand in the builder survives it.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass, field
from typing import Callable, Optional

from backend.services import rbd_graph
from backend.services.rbd_graph import GraphError

MAX_OPS = 100

IO_TYPES = ("input", "output")

# Which node types each update_node field applies to.
_FIELD_TYPES = {
    "model": ("component", "series", "parallel", "standby"),
    "repair": ("component", "series", "parallel", "standby"),
    "n": ("series", "parallel", "knode"),
    "k": ("knode",),
    "spares": ("standby",),
    "cold": ("standby",),
    "subsystem_rbd_id": ("subsystem",),
}
UPDATE_FIELDS = ("label", *_FIELD_TYPES)


class EditError(ValueError):
    """An op that can't be applied (user-facing text)."""


@dataclass
class EditResult:
    graph: dict
    name: str
    applied: list[str] = field(default_factory=list)
    relaid_out: bool = False


def _arrow(s: str, t: str) -> str:
    return f"{s}→{t}"


class _Editor:
    def __init__(self, graph: dict, name: str, resolve_saved_model, self_id: Optional[str]):
        self.graph = copy.deepcopy(graph or {})
        self.graph.setdefault("nodes", [])
        self.graph.setdefault("edges", [])
        self.name = name
        self.resolve = resolve_saved_model
        self.self_id = self_id
        self.topology_changed = False

    # ---- lookups -----------------------------------------------------------

    @property
    def nodes(self) -> list[dict]:
        return self.graph["nodes"]

    @property
    def edges(self) -> list[dict]:
        return self.graph["edges"]

    def node(self, nid: str) -> dict:
        for n in self.nodes:
            if n.get("id") == nid:
                return n
        raise EditError(f"there's no node '{nid}' (ids are case-sensitive; get_rbd lists them).")

    def has_node(self, nid: str) -> bool:
        return any(n.get("id") == nid for n in self.nodes)

    def has_edge(self, s: str, t: str) -> bool:
        return any(e.get("source") == s and e.get("target") == t for e in self.edges)

    def sources(self, nid: str) -> list[str]:
        return list(dict.fromkeys(e["source"] for e in self.edges if e.get("target") == nid))

    def targets(self, nid: str) -> list[str]:
        return list(dict.fromkeys(e["target"] for e in self.edges if e.get("source") == nid))

    # ---- primitive changes -------------------------------------------------

    def link(self, s: str, t: str) -> bool:
        """Add s -> t unless it exists (or would be a self-loop). True if added."""
        if s == t or self.has_edge(s, t):
            return False
        taken = {e.get("id") for e in self.edges}
        eid, i = f"e-{s}-{t}", 2
        while eid in taken:
            eid, i = f"e-{s}-{t}-{i}", i + 1
        self.edges.append(rbd_graph.make_edge(s, t, eid))
        self.topology_changed = True
        return True

    def unlink(self, pred) -> None:
        before = len(self.edges)
        self.graph["edges"] = [e for e in self.edges if not pred(e)]
        if len(self.edges) != before:
            self.topology_changed = True

    def block(self, nid: str, what: str) -> dict:
        n = self.node(nid)
        if n.get("type") in IO_TYPES:
            raise EditError(f"'{nid}' is the diagram's {n['type']} node — {what}.")
        return n

    # ---- ops ---------------------------------------------------------------

    def add_node(self, op: dict) -> str:
        raw = dict(op.get("node") or {})
        nid = str(raw.get("id") or "").strip()
        if raw.get("type") in IO_TYPES:
            raise EditError("a diagram has exactly one input and one output node, and this one already does — "
                            "add blocks between them.")
        if nid and self.has_node(nid):
            raise EditError(f"node id '{nid}' is already in use (ids are case-sensitive) — pick a new one.")
        if raw.get("subsystem_rbd_id") and raw["subsystem_rbd_id"] == self.self_id:
            raise EditError("a diagram can't embed itself as a sub-system.")
        node = rbd_graph.normalize_node(raw, self.resolve)
        nid = node["id"]
        placements = [k for k in ("between", "after", "before", "parallel_to") if op.get(k) is not None]
        if len(placements) > 1:
            raise EditError(f"give at most one placement (between, after, before or parallel_to), not "
                            f"{' and '.join(placements)}.")
        self.nodes.append(node)
        self.topology_changed = True
        where = placements[0] if placements else None

        if where == "between":
            s, t = op["between"]
            if not self.has_edge(s, t):
                raise EditError(f"there's no edge {_arrow(s, t)} to insert '{nid}' into.")
            self.unlink(lambda e: e.get("source") == s and e.get("target") == t)
            self.link(s, nid)
            self.link(nid, t)
            return f"added {nid} between {s} and {t}"
        if where == "after":
            x = op["after"]
            if self.node(x).get("type") == "output":
                raise EditError("nothing can come after the output node.")
            outs = self.targets(x)
            self.unlink(lambda e: e.get("source") == x)
            for t in outs:
                self.link(nid, t)
            self.link(x, nid)
            return f"added {nid} after {x}"
        if where == "before":
            x = op["before"]
            if self.node(x).get("type") == "input":
                raise EditError("nothing can come before the input node.")
            ins = self.sources(x)
            self.unlink(lambda e: e.get("target") == x)
            for s in ins:
                self.link(s, nid)
            self.link(nid, x)
            return f"added {nid} before {x}"
        if where == "parallel_to":
            y = op["parallel_to"]
            self.block(y, "a block can't sit in parallel with it")
            ins, outs = self.sources(y), self.targets(y)
            if not ins and not outs:
                raise EditError(f"'{y}' has no connections to copy, so '{nid}' can't go in parallel with it.")
            for s in ins:
                self.link(s, nid)
            for t in outs:
                self.link(nid, t)
            return f"added {nid} parallel to {y}"
        return f"added {nid} (unconnected: add its edges)"

    def remove_node(self, op: dict) -> str:
        nid = op["id"]
        self.block(nid, "it can't be removed")
        ins, outs = self.sources(nid), self.targets(nid)
        self.graph["nodes"] = [n for n in self.nodes if n.get("id") != nid]
        self.unlink(lambda e: nid in (e.get("source"), e.get("target")))
        self.topology_changed = True
        line = f"removed {nid}"

        if op.get("reconnect", "auto") == "auto":
            # Heal series gaps without creating bypasses: only a neighbour the
            # removal left with no outgoing (or incoming) edge is rejoined, so
            # dropping one of two parallel pumps adds nothing.
            joined = []
            for i in ins:
                if not self.targets(i):
                    joined += [(i, o) for o in outs]
            for o in outs:
                if not self.sources(o):
                    joined += [(i, o) for i in ins]
            added = [_arrow(i, o) for i, o in dict.fromkeys(joined) if self.link(i, o)]
            if added:
                line += "; joined " + ", ".join(added)

        notes = []
        groups = []
        for g in self.graph.get("ccf_groups") or []:
            members = [m for m in (g.get("members") or []) if m != nid]
            if len(members) == len(g.get("members") or []):
                groups.append(g)
            elif len(members) >= 2:
                groups.append({**g, "members": members})
                notes.append(f"left common-cause group {g.get('id')}")
            else:
                notes.append(f"dropped common-cause group {g.get('id')} (under 2 members)")
        if notes:
            self._set_ccf(groups)
            line += "; " + "; ".join(notes)
        return line

    def update_node(self, op: dict) -> str:
        ids = op.get("ids") or ([op["id"]] if op.get("id") else [])
        if bool(op.get("id")) == bool(op.get("ids")):
            raise EditError("give exactly one of id or ids.")
        changes = {k: op[k] for k in UPDATE_FIELDS if k in op}
        if not changes:
            raise EditError(f"nothing to update — give one or more of {', '.join(UPDATE_FIELDS)}.")
        ids = list(dict.fromkeys(ids))
        for nid in ids:
            node = self.node(nid)
            ntype = node.get("type")
            for key in changes:
                allowed = _FIELD_TYPES.get(key)
                if allowed and ntype not in allowed:
                    raise EditError(f"'{nid}' is a {ntype} node, which has no {key} "
                                    f"(only {', '.join(allowed)} nodes do).")
            data = dict(node.get("data") or {})
            where = f"node '{data.get('label') or nid}'"
            for key, value in changes.items():
                if key == "model":
                    data["model"] = rbd_graph.normalize_model(value, where, self.resolve)
                elif key == "repair":
                    data["repair"] = rbd_graph.normalize_repair(value, where)
                elif key == "subsystem_rbd_id":
                    if value == self.self_id:
                        raise EditError("a diagram can't embed itself as a sub-system.")
                    data["rbd"] = {"id": str(value)}
                elif key == "label":
                    label = str(value).strip()
                    if not label:
                        raise EditError("label can't be blank.")
                    data["label"] = label
                else:
                    data[key] = value
            node["data"] = data
        return f"updated {', '.join(changes)} of {', '.join(ids)}"

    def add_edge(self, op: dict) -> str:
        s, t = op["source"], op["target"]
        self.node(s), self.node(t)
        if s == t:
            raise EditError(f"an edge can't loop from '{s}' to itself.")
        if self.has_edge(s, t):
            raise EditError(f"the edge {_arrow(s, t)} already exists.")
        if self.node(s).get("type") == "output":
            raise EditError("the output node can't have outgoing edges.")
        if self.node(t).get("type") == "input":
            raise EditError("the input node can't have incoming edges.")
        self.link(s, t)
        return f"added edge {_arrow(s, t)}"

    def remove_edge(self, op: dict) -> str:
        s, t = op["source"], op["target"]
        self.node(s), self.node(t)
        if not self.has_edge(s, t):
            raise EditError(f"there's no edge {_arrow(s, t)}.")
        self.unlink(lambda e: e.get("source") == s and e.get("target") == t)
        return f"removed edge {_arrow(s, t)}"

    def set(self, op: dict) -> str:
        parts = []
        if op.get("name") is not None:
            name = str(op["name"]).strip()
            if not name:
                raise EditError("name can't be blank.")
            self.name = name
            parts.append(f"renamed to “{name}”")
        if op.get("unit") is not None:
            self.graph["unit"] = str(op["unit"]).strip()
            parts.append(f"unit set to {self.graph['unit'] or '(none)'} (parameters are not rescaled)")
        if op.get("repairable") is not None:
            if op["repairable"]:
                self.graph["repairable"] = True
            else:
                self.graph.pop("repairable", None)
            parts.append("made repairable (availability)" if op["repairable"]
                         else "made non-repairable (reliability)")
        if not parts:
            raise EditError("nothing to set — give name, unit and/or repairable.")
        return "; ".join(parts)

    def _set_ccf(self, groups: list[dict]) -> None:
        if groups:
            self.graph["ccf_groups"] = groups
        else:
            self.graph.pop("ccf_groups", None)

    def add_ccf(self, op: dict) -> str:
        if self.graph.get("repairable"):
            raise EditError("common-cause groups are reliability-only — this diagram is repairable (availability).")
        try:
            beta = float(op.get("beta"))
        except (TypeError, ValueError):
            raise EditError("beta must be a number.") from None
        if not 0 < beta < 1:
            raise EditError(f"beta = {beta:g} is out of range — it's the fraction of each component's failures "
                            "that are shared-cause, 0 < beta < 1 (typically 0.01–0.2).")
        members = list(dict.fromkeys(op.get("members") or []))
        if len(members) < 2:
            raise EditError("a common-cause group couples 2 or more distinct components.")
        groups = list(self.graph.get("ccf_groups") or [])
        grouped = {m: g.get("id") for g in groups for m in g.get("members") or []}
        for m in members:
            if self.node(m).get("type") != "component":
                raise EditError(f"'{m}' isn't a component block — common-cause groups couple component blocks.")
            if m in grouped:
                raise EditError(f"'{m}' is already in common-cause group {grouped[m]} (remove_ccf it first).")
        taken = {g.get("id") for g in groups}
        gid = op.get("id")
        if gid and gid in taken:
            raise EditError(f"common-cause group id '{gid}' is already in use.")
        if not gid:
            i = 1
            while f"ccf-{i}" in taken:
                i += 1
            gid = f"ccf-{i}"
        self._set_ccf([*groups, {"id": gid, "members": members, "beta": beta}])
        return f"added common-cause group {gid} ({', '.join(members)}; beta {beta:g})"

    def remove_ccf(self, op: dict) -> str:
        gid = op["id"]
        groups = list(self.graph.get("ccf_groups") or [])
        if not any(g.get("id") == gid for g in groups):
            have = ", ".join(str(g.get("id")) for g in groups) or "none"
            raise EditError(f"there's no common-cause group '{gid}' (groups: {have}).")
        self._set_ccf([g for g in groups if g.get("id") != gid])
        return f"removed common-cause group {gid}"


_OPS = ("add_node", "remove_node", "update_node", "add_edge", "remove_edge", "set", "add_ccf", "remove_ccf")


def _describe(op: dict) -> str:
    """A short handle for an op in an error message."""
    kind = op.get("op")
    if kind == "add_node":
        return f"add_node {(op.get('node') or {}).get('id', '')}".strip()
    if kind in ("remove_node", "remove_ccf"):
        return f"{kind} {op.get('id', '')}".strip()
    if kind == "update_node":
        return f"update_node {op.get('id') or ', '.join(op.get('ids') or [])}".strip()
    if kind in ("add_edge", "remove_edge"):
        return f"{kind} {_arrow(op.get('source'), op.get('target'))}"
    return str(kind)


def apply_ops(
    graph: dict,
    ops: list[dict],
    name: str,
    resolve_saved_model: Optional[Callable[[str], object]] = None,
    self_id: Optional[str] = None,
) -> EditResult:
    """Apply ``ops`` in order to a copy of ``graph``.

    Raises :class:`EditError` naming the failing op's index (0-based) and why;
    nothing is half-applied because the input graph is never modified.
    ``self_id`` is the edited diagram's own id (it can't embed itself).
    """
    if not ops:
        raise EditError("give at least one op.")
    if len(ops) > MAX_OPS:
        raise EditError(f"at most {MAX_OPS} ops per call; split the edit into batches.")
    ed = _Editor(graph, name, resolve_saved_model, self_id)
    applied = []
    for i, op in enumerate(ops):
        kind = op.get("op")
        if kind not in _OPS:
            raise EditError(f"ops[{i}]: unknown op '{kind}' — use one of {', '.join(_OPS)}.")
        try:
            applied.append(getattr(ed, kind)(op))
        except (EditError, GraphError) as exc:
            raise EditError(f"ops[{i}] ({_describe(op)}): {exc}") from None

    relaid = ed.topology_changed
    if relaid:
        nodes = [{k: v for k, v in n.items() if k != "positionAbsolute"} for n in ed.nodes]
        ed.graph["nodes"] = rbd_graph.layout_graph(nodes, ed.edges)
    return EditResult(graph=ed.graph, name=ed.name, applied=applied, relaid_out=relaid)
