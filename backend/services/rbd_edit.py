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
    {"op": "set", "name"?, "unit"?, "repairable"?, "repair_crews"?, "maintenance_groups"?,
     "safety_function"?, "target_sil"?, "costs"?: {"downtime_rate"?, "horizon"?, "discount_rate"?}}
    {"op": "add_ccf", "members": [...], "beta": ..., "basis"?, "mgl"?: [gamma, ...], "id"?}
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
    "k": ("knode", "standby"),
    "spares": ("standby",),
    "cold": ("standby",),
    "subsystem_rbd_id": ("subsystem",),
    # A repairable block's costs and maintenance (#99, #100, #156, #157).
    "instant_repair": ("component",),
    "costs": ("component", "standby"),
    "preventive": ("component",),
    "inspection": ("component",),
    "maintenance_group": ("component",),
    "crew_priority": ("component", "standby"),
    "repair_one_at_a_time": ("standby",),
    # Imperfect repair and replacement at the N-th failure (#68).
    "repair_quality": ("component",),
}
UPDATE_FIELDS = ("label", *_FIELD_TYPES)
#: Block settings ``update_node``'s ``clear`` can remove.
CLEARABLE = ("costs", "preventive", "inspection", "maintenance_group", "crew_priority", "instant_repair",
             "repair_one_at_a_time", "repair_quality")


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
                group = {**g, "members": members}
                if g.get("mgl"):
                    # A multiple Greek letter group has a letter per member
                    # beyond the first (#84): the last goes with the member.
                    group["mgl"] = list(g["mgl"])[:len(members) - 2]
                    if not group["mgl"]:
                        group.pop("mgl")
                groups.append(group)
                notes.append(f"left common-cause group {g.get('id')}"
                             + ("; its last Greek letter went with it" if g.get("mgl") else ""))
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
        clear = list(dict.fromkeys(op.get("clear") or []))
        for key in clear:
            if key not in CLEARABLE:
                raise EditError(f"clear takes {', '.join(CLEARABLE)}, not {key}.")
            if key in changes:
                raise EditError(f"{key} is both set and cleared — give one or the other.")
        if not changes and not clear:
            raise EditError(f"nothing to update — give one or more of {', '.join(UPDATE_FIELDS)}, or clear.")
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
                elif key == "repair_quality" and (value or {}).get("model", "perfect") == "perfect":
                    data.pop(key, None)  # perfect repair is the default (#68)
                elif key == "label":
                    label = str(value).strip()
                    if not label:
                        raise EditError("label can't be blank.")
                    data["label"] = label
                elif key in ("preventive", "inspection"):
                    # A block has a schedule or proof tests, not both: the new
                    # one replaces the other (and the RCM link it carried).
                    data.pop("inspection" if key == "preventive" else "preventive", None)
                    data.pop("rcm_source", None)
                    data[key] = value
                else:
                    data[key] = value
            for key in clear:
                data.pop(key, None)
                if key in ("preventive", "inspection"):
                    data.pop("rcm_source", None)
            rbd_graph.check_counts(ntype, data, where)
            node["data"] = data
        parts = [f"updated {', '.join(changes)}"] if changes else []
        if clear:
            parts.append(f"cleared {', '.join(clear)}")
        return f"{' and '.join(parts)} of {', '.join(ids)}"

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
        parts += self._set_repairable_settings(op)
        if not parts:
            raise EditError("nothing to set — give name, unit, repairable, repair_crews, maintenance_groups, "
                            "safety_function, target_sil and/or costs.")
        return "; ".join(parts)

    def _set_costs(self, costs: dict) -> list[str]:
        """``set``'s diagram costs (#99, #219): each field given replaces the
        diagram's, 0 clears it."""
        merged = dict(self.graph.get("costs") or {})
        parts = []
        names = {"downtime_rate": "system downtime cost", "horizon": "ownership horizon",
                 "discount_rate": "discount rate"}
        for key, name in names.items():
            if costs.get(key) is None:
                continue
            value = float(costs[key])
            if value:
                merged[key] = value
                parts.append(f"{name} {value:g}" + ("% a year" if key == "discount_rate" else ""))
            else:
                merged.pop(key, None)
                parts.append(f"{name} cleared")
        if merged:
            self.graph["costs"] = merged
        else:
            self.graph.pop("costs", None)
        return parts

    def _set_repairable_settings(self, op: dict) -> list[str]:
        """``set``'s repairable-diagram settings (#156, #157) and costs (#219)."""
        parts = []
        given = [k for k in ("repair_crews", "maintenance_groups", "safety_function", "target_sil", "costs")
                 if op.get(k) is not None]
        if given and not self.graph.get("repairable"):
            raise EditError(f"{', '.join(given)} apply to repairable diagrams only — set repairable true too.")
        if op.get("costs") is not None:
            parts += self._set_costs(op["costs"])
        if op.get("repair_crews") is not None:
            crews = int(op["repair_crews"])
            if crews:
                self.graph["repair_crews"] = {"crews": crews}
                parts.append(f"{crews} repair crew{'s' if crews != 1 else ''} shared by every block")
            else:
                self.graph.pop("repair_crews", None)
                parts.append("repair crews: as many as needed")
        if op.get("maintenance_groups") is not None:
            groups = dict(op["maintenance_groups"])
            if groups:
                self.graph["maintenance_groups"] = groups
                parts.append(f"maintenance groups set ({', '.join(groups)})")
            else:
                self.graph.pop("maintenance_groups", None)
                parts.append("maintenance groups cleared")
        if op.get("safety_function") is not None:
            if op["safety_function"]:
                self.graph["safety_function"] = True
                parts.append("marked as a safety function (PFDavg and SIL)")
            else:
                self.graph.pop("safety_function", None)
                self.graph.pop("target_sil", None)
                parts.append("no longer a safety function")
        if op.get("target_sil") is not None:
            sil = int(op["target_sil"])
            if sil:
                if not self.graph.get("safety_function"):
                    raise EditError("target_sil applies to a safety function — set safety_function true too.")
                self.graph["target_sil"] = sil
                parts.append(f"target SIL {sil}")
            else:
                self.graph.pop("target_sil", None)
                parts.append("target SIL cleared")
        return parts

    def _set_ccf(self, groups: list[dict]) -> None:
        if groups:
            self.graph["ccf_groups"] = groups
        else:
            self.graph.pop("ccf_groups", None)

    def add_ccf(self, op: dict) -> str:
        # In a repairable diagram a group is followed over time (RePyability
        # 0.12, #226) where its chains take it; validation says when not.
        try:
            beta = float(op.get("beta"))
        except (TypeError, ValueError):
            raise EditError("beta must be a number.") from None
        if not 0 < beta < 1:
            raise EditError(f"beta = {beta:g} is out of range — it's the fraction of each component's failures "
                            "that are shared-cause, 0 < beta < 1 (typically 0.01–0.2).")
        basis = op.get("basis")
        if basis is not None and basis not in ("rate", "probability"):
            raise EditError(f"basis must be 'rate' or 'probability'; got {basis!r}.")
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
        group = {"id": gid, "members": members, "beta": beta}
        if basis is not None:
            # Optional (#210): the rate basis is the lifetime default.
            group["basis"] = basis
        mgl = op.get("mgl")
        if mgl:
            # The multiple Greek letter model (#84): gamma, delta, … after beta.
            if len(mgl) != len(members) - 2:
                raise EditError(f"a multiple Greek letter group of {len(members)} members takes "
                                f"{len(members) - 2} letter(s) after beta in mgl (gamma, delta, …); got {len(mgl)}.")
            try:
                letters = [float(x) for x in mgl]
            except (TypeError, ValueError):
                raise EditError("mgl's letters must be numbers from 0 to 1.") from None
            if any(not 0 <= x <= 1 for x in letters):
                raise EditError("mgl's letters must be numbers from 0 to 1.")
            group["mgl"] = letters
        self._set_ccf([*groups, group])
        shown = f"; {basis} basis" if basis is not None else ""
        if mgl:
            shown += "; MGL " + ", ".join(f"{x:g}" for x in group["mgl"])
        return f"added common-cause group {gid} ({', '.join(members)}; beta {beta:g}{shown})"

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

    try:
        rbd_graph.check_size(ed.nodes, ed.edges)
    except GraphError as exc:
        raise EditError(f"after these ops {exc}") from None
    relaid = ed.topology_changed
    if relaid:
        nodes = [{k: v for k, v in n.items() if k != "positionAbsolute"} for n in ed.nodes]
        ed.graph["nodes"] = rbd_graph.layout_graph(nodes, ed.edges)
    return EditResult(graph=ed.graph, name=ed.name, applied=applied, relaid_out=relaid)
