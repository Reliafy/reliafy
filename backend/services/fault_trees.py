"""Fault trees built by hand: their own saved items (``fault_trees``).

A fault tree works down from an undesired *top event* through *gates* to the
*basic events* that cause it:

* an **OR** gate occurs when any of its inputs occurs;
* an **AND** gate occurs when all of its inputs occur;
* a **vote** gate (k of n) occurs when at least ``k`` of its ``n`` inputs occur.

Only coherent logic: NOT, XOR, INHIBIT and the dynamic gates (priority-AND,
spare, functional dependency, sequence) are refused with a note saying so.

The stored tree (``tree``)::

    {"unit": "hours", "top": "top",
     "nodes": [
       {"id": "top", "type": "gate", "gate": "or", "label": "Loss of thrust",
        "inputs": ["arm1", "battery"]},
       {"id": "arm1", "type": "gate", "gate": "vote", "k": 2, "label": "...", "inputs": [...]},
       {"id": "battery", "type": "event", "label": "Battery pack",
        "model": {...},            # a block's non-repairable model, as the RBD block picker stores it
        "placeholder": true},      # optional: a guessed value, flagged in every result
       {"id": "check", "type": "event", "label": "...", "probability": 0.001},  # fixed (unavailability q)
       {"id": "todo", "type": "event", "label": "..."}]}                       # no data yet

A basic event under more than one gate is a *repeated* event (one event,
counted once); a gate sits under one gate only, except in imported trees.

The analysis is the RBD fault-tree view's engine (``rbd_fault_tree``): the
gates and basic events go into RePyability's ``FaultTree`` exactly as that
view builds them, each event's model built as an RBD block's is
(``rbd_analysis._build_distribution``), and the same ``_payload`` works out
the top event, gate probabilities, ranked minimal cut sets and importance.
So a tree and the RBD it converts to (:func:`to_rbd_graph`, the importers'
conversion) give the same numbers — the tests hold them to it.
"""

from __future__ import annotations

import math
import re
import uuid
from datetime import datetime, timezone
from typing import Any, Callable, Optional
from xml.sax.saxutils import escape, quoteattr

import numpy as np
from pydantic import BaseModel, Field

from backend.services import access
from backend.services import rbd_analysis as ra
from backend.services import rbd_fault_tree as rft
from backend.services.rbd_analysis import AnalysisError
from backend.services.rbd_import import fault_tree as ft

#: The most gates and basic events a tree holds. Exact analysis is quick at
#: this size; beyond it a tree is better built as an RBD of sub-systems.
MAX_NODES = 500
MAX_LABEL = 120
MAX_NOTE = 1000
GATE_KINDS = ("or", "and", "vote")
#: Gate types refused, by the words people use for them.
REFUSED_GATES = {
    "not": "NOT", "xor": "XOR", "inhibit": "INHIBIT", "nand": "NAND", "nor": "NOR", "iff": "IFF",
    "pand": "priority-AND", "por": "priority-OR", "spare": "spare", "csp": "spare", "hsp": "spare",
    "wsp": "spare", "fdep": "functional dependency", "pdep": "probabilistic dependency",
    "seq": "sequence enforcer",
}
REFUSED_NOTE = (
    "Reliafy's fault trees use AND, OR and k-of-n vote gates (coherent logic). NOT, XOR and INHIBIT gates, "
    "and the dynamic gates (priority-AND, spare, functional dependency, sequence), aren't supported.")
_ID = re.compile(r"^[A-Za-z0-9_.:-]{1,64}$")


class FaultTreeError(ValueError):
    """A tree that can't be saved or analysed as it is (user-facing text)."""


class FaultTreeDoc(BaseModel):
    """A saved fault tree. ``rbd_id`` is the RBD made from it by "Open as RBD", if any."""

    id: str
    name: str
    owner_id: Optional[str] = None
    updated_by: Optional[dict] = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    tree: dict = Field(default_factory=dict)
    rbd_id: Optional[str] = None


# ---------------------------------------------------------------------------
# Shape: checking a tree as saved
# ---------------------------------------------------------------------------


def _text(value, where: str, what: str, limit: int) -> str:
    if value is None:
        return ""
    if not isinstance(value, str):
        raise FaultTreeError(f"{where}: {what} must be text.")
    value = " ".join(value.split())
    if len(value) > limit:
        raise FaultTreeError(f"{where}: {what} is longer than {limit} characters.")
    return value


def _probability(value, where: str) -> float:
    try:
        p = float(value)
    except (TypeError, ValueError):
        raise FaultTreeError(f"{where}: the probability must be a number between 0 and 1.") from None
    if not (math.isfinite(p) and 0.0 <= p <= 1.0):
        raise FaultTreeError(f"{where}: the probability must be between 0 and 1 (got {value}).")
    return p


def normalize_tree(raw, resolve_saved_model: Optional[Callable[[str], object]] = None) -> dict:
    """A tree as given (API, MCP, the editor) in the stored shape, or a
    :class:`FaultTreeError` saying what to fix.

    This is the check on saving, so a tree in progress passes: a gate with no
    inputs yet, a vote asking for more inputs than it has, an event with no
    data. :func:`check_complete` is the check before analysing."""
    from backend.services import rbd_graph

    if not isinstance(raw, dict):
        raise FaultTreeError("The tree must be an object with nodes and top.")
    nodes_in = raw.get("nodes")
    if not isinstance(nodes_in, list) or not nodes_in:
        raise FaultTreeError("The tree needs nodes: at least its top event, a gate.")
    if len(nodes_in) > MAX_NODES:
        raise FaultTreeError(
            f"A fault tree holds up to {MAX_NODES} gates and basic events; this one has {len(nodes_in)}. "
            "Split it: build each branch as its own tree, or model the system as an RBD with sub-systems.")
    nodes: list[dict] = []
    seen: set[str] = set()
    for i, n in enumerate(nodes_in):
        if not isinstance(n, dict):
            raise FaultTreeError(f"Node {i + 1} must be an object.")
        nid = str(n.get("id") or "").strip()
        if not _ID.match(nid):
            raise FaultTreeError(
                f"Node {i + 1}: id “{nid}” must be 1–64 letters, digits, '_', '-', '.' or ':'.")
        if nid in seen:
            raise FaultTreeError(f"Two nodes share the id “{nid}”.")
        seen.add(nid)
        where = f"“{n.get('label') or nid}”"
        ntype = str(n.get("type") or ("gate" if n.get("gate") or n.get("inputs") else "event")).lower()
        label = _text(n.get("label"), where, "the name", MAX_LABEL) or nid
        out: dict[str, Any] = {"id": nid, "type": ntype, "label": label}
        note = _text(n.get("note"), where, "the note", MAX_NOTE)
        if note:
            out["note"] = note
        if ntype == "gate":
            kind = str(n.get("gate") or "or").strip().lower()
            if kind in ("atleast", "koon", "k_of_n", "voting"):
                kind = "vote"
            if kind in REFUSED_GATES:
                raise FaultTreeError(f"Gate {where} is a {REFUSED_GATES[kind]} gate. {REFUSED_NOTE}")
            if kind not in GATE_KINDS:
                raise FaultTreeError(f"Gate {where}: the gate must be or, and or vote (got “{kind}”).")
            inputs = n.get("inputs") or []
            if not isinstance(inputs, list) or not all(isinstance(x, str) for x in inputs):
                raise FaultTreeError(f"Gate {where}: inputs must be a list of node ids.")
            if len(set(inputs)) != len(inputs):
                raise FaultTreeError(f"Gate {where} lists an input more than once.")
            out.update(gate=kind, inputs=list(inputs))
            if kind == "vote":
                try:
                    k = int(n.get("k"))
                except (TypeError, ValueError):
                    raise FaultTreeError(
                        f"Vote gate {where} needs k: how many of its inputs must occur.") from None
                if k < 1:
                    raise FaultTreeError(f"Vote gate {where}: k must be at least 1.")
                out["k"] = k
        elif ntype == "event":
            model, prob = n.get("model"), n.get("probability")
            if model is not None and prob is not None:
                raise FaultTreeError(
                    f"Basic event {where}: give a model OR a fixed probability, not both.")
            if model is not None:
                try:
                    out["model"] = rbd_graph.normalize_model(model, f"Basic event {where}", resolve_saved_model)
                except rbd_graph.GraphError as exc:
                    raise FaultTreeError(str(exc)) from None
                if out["model"].get("kind") == "joint":
                    raise FaultTreeError(
                        f"Basic event {where}: a condition and life model needs a block's readings — use "
                        "it in an RBD; a basic event takes a life distribution or a probability.")
            elif prob is not None:
                out["probability"] = _probability(prob, f"Basic event {where}")
            # One flag, on the event (a model's own placeholder flag moves to it).
            guessed = isinstance(out.get("model"), dict) and out["model"].pop("placeholder", False)
            if n.get("placeholder") or guessed:
                out["placeholder"] = True
        else:
            raise FaultTreeError(f"Node {where}: type must be gate or event (got “{ntype}”).")
        nodes.append(out)

    by_id = {n["id"]: n for n in nodes}
    top = str(raw.get("top") or nodes[0]["id"])
    if top not in by_id or by_id[top]["type"] != "gate":
        raise FaultTreeError("The top event must be one of the tree's gates.")
    parents: dict[str, int] = {}
    for n in nodes:
        for x in n.get("inputs") or []:
            if x not in by_id:
                raise FaultTreeError(f"Gate “{n['label']}” has an input “{x}” that isn't in the tree.")
            if x == top:
                raise FaultTreeError("The top event can't be another gate's input.")
            parents[x] = parents.get(x, 0) + 1
    # Every node under the top, and no loops.
    reached: set[str] = set()
    on_path: set[str] = set()

    def walk(nid: str, depth: int) -> None:
        if depth > ft.MAX_DEPTH:
            raise FaultTreeError(f"The tree is nested more than {ft.MAX_DEPTH} gates deep.")
        if nid in on_path:
            raise FaultTreeError(f"The tree has a loop through “{by_id[nid]['label']}”.")
        if nid in reached:
            return
        reached.add(nid)
        on_path.add(nid)
        for x in by_id[nid].get("inputs") or []:
            walk(x, depth + 1)
        on_path.discard(nid)

    walk(top, 0)
    stray = [by_id[n["id"]]["label"] for n in nodes if n["id"] not in reached]
    if stray:
        raise FaultTreeError(
            "Every gate and basic event must be under the top event; these aren't: "
            + ", ".join(f"“{s}”" for s in stray[:8]) + (" …" if len(stray) > 8 else "") + ".")
    unit = _text(raw.get("unit"), "The tree", "the time unit", 40)
    return {"unit": unit, "top": top, "nodes": nodes}


def placeholder_labels(tree: dict) -> list[str]:
    """Basic events on guessed (placeholder) data."""
    return [n["label"] for n in tree.get("nodes") or [] if n.get("type") == "event" and n.get("placeholder")]


def missing_data_labels(tree: dict) -> list[str]:
    """Basic events with no failure data yet."""
    return [n["label"] for n in tree.get("nodes") or []
            if n.get("type") == "event" and n.get("model") is None and n.get("probability") is None]


def _names(labels: list[str], limit: int = 8) -> str:
    shown = ", ".join(f"“{s}”" for s in labels[:limit])
    return shown + (f" and {len(labels) - limit} more" if len(labels) > limit else "")


def check_complete(tree: dict) -> None:
    """What stops a saved tree being analysed, as one :class:`FaultTreeError`."""
    problems = []
    for n in tree.get("nodes") or []:
        if n.get("type") != "gate":
            continue
        inputs = n.get("inputs") or []
        if not inputs:
            problems.append(f"gate “{n['label']}” has no inputs yet")
        elif n["gate"] == "vote" and n["k"] > len(inputs):
            problems.append(f"vote gate “{n['label']}” needs {n['k']} of its inputs but has {len(inputs)}")
    missing = missing_data_labels(tree)
    if missing:
        problems.append(
            f"basic event{'s' if len(missing) > 1 else ''} {_names(missing)} "
            f"{'have' if len(missing) > 1 else 'has'} no failure data yet (pick a model, enter a rate, or a "
            "fixed probability; mark a guess as a placeholder)")
    if problems:
        raise FaultTreeError("Can't analyse yet: " + "; ".join(problems) + ".")


# ---------------------------------------------------------------------------
# Analysis: the RBD fault-tree view's engine
# ---------------------------------------------------------------------------


def _gate_spec(n: dict) -> tuple:
    if n["gate"] == "vote":
        k, size = n["k"], len(n["inputs"])
        # A vote of 1 is an OR and of all its inputs an AND: named as such,
        # as the RBD view names them.
        if k == 1:
            return ("or", list(n["inputs"]))
        if k == size:
            return ("and", list(n["inputs"]))
        return ("vote", k, list(n["inputs"]))
    return (n["gate"], list(n["inputs"]))


def _event_model(n: dict, resolve_model):
    if n.get("probability") is not None:
        return float(n["probability"])
    return ra._build_distribution(n["model"], f"Basic event “{n['label']}”", resolve_model)


def build_engine_tree(tree: dict, resolve_model=None):
    """``(FaultTree, gate_info, event_info)`` for the RBD view's ``_payload``."""
    from repyability import FaultTree

    check_complete(tree)
    gates, events, gate_info, event_info = {}, {}, {}, {}
    for n in tree["nodes"]:
        if n["type"] == "gate":
            gates[n["id"]] = _gate_spec(n)
            gate_info[n["id"]] = {"label": n["label"], "role": "top" if n["id"] == tree["top"] else "gate"}
        else:
            events[n["id"]] = _event_model(n, resolve_model)
            event_info[n["id"]] = {"label": n["label"], "path": [], "node_type": "component"}
    try:
        engine = FaultTree(gates, events, top=tree["top"])
    except ValueError as exc:  # normalize_tree catches these first; defensive
        raise FaultTreeError(f"The tree can't be analysed: {exc}") from None
    return engine, gate_info, event_info


def _lifetime(engine) -> dict:
    return {e: m for e, m in engine.events.items() if not isinstance(m, float)}


def _top_curve(engine, grid: np.ndarray) -> np.ndarray:
    with np.errstate(all="ignore"):
        return np.asarray(engine.top_event_probability(grid), dtype=float)


def _default_time(engine, t_max: Optional[float]) -> tuple[float, np.ndarray]:
    """``(t, grid)``: the axis, sized as the RBD calculator sizes it (to the
    events' own time scales, then to where the top event is nearly certain),
    and the time on it where the top event probability is closest to 10%
    (system reliability about 90%, the RBD view's design point)."""
    grid = ra._time_grid(_lifetime(engine), t_max)
    if not (t_max is not None and np.isfinite(t_max) and t_max > 0):
        ceiling = float(grid[-1])
        probe = np.geomspace(ceiling * 1e-6, ceiling, 400)
        top = _top_curve(engine, probe)
        if np.all(np.isfinite(top)) and top[0] < 0.99:
            over = np.nonzero(top >= 0.99)[0]
            if over.size:
                ceiling = float(min(ceiling, probe[over[0]] * 1.15))
        grid = np.linspace(0.0, ceiling, ra._GRID_POINTS)
    top = _top_curve(engine, grid)
    idx = int(np.argmin(np.abs(top - 0.1)))
    if not (0.0 < top[idx] < 1.0):
        idx = len(grid) // 2
    return float(grid[idx]), grid


def analyse(tree: dict, resolve_model=None, t: Optional[float] = None, t_max: Optional[float] = None) -> dict:
    """The top event, gates, minimal cut sets and importance of a stored tree.

    With any time-based event, evaluated at ``t`` (default: where the top
    event probability is about 10%), with the top event over time in
    ``curve``; with only fixed probabilities, ``kind`` is ``probability`` and
    time doesn't enter. Raises :class:`FaultTreeError` /
    :class:`AnalysisError` with a fixable message."""
    if t is not None:
        try:
            t = float(t)
        except (TypeError, ValueError):
            raise FaultTreeError("The time must be a number.") from None
        if not (math.isfinite(t) and t > 0):
            raise FaultTreeError("The time must be a positive number.")
    engine, gate_info, event_info = build_engine_tree(tree, resolve_model)
    timed = bool(_lifetime(engine))
    curve = None
    t_default = None
    if timed:
        t_default, grid = _default_time(engine, t_max)
        t_eval = t if t is not None else t_default
        top = _top_curve(engine, grid)
        curve = {"t": [ra._f(x) for x in grid], "probability": [ra._f(x) for x in top]}
    else:
        t_eval = 1.0  # no event depends on time
    out = rft._payload(engine, gate_info, event_info, t_eval, "reliability")
    # The gates by the tree's own ids too (the payload codes them TOP, G1, …).
    code_of = rft._display_names(engine)
    node_of = {code: nid for nid, code in code_of.items()}
    by_id = {n["id"]: n for n in tree["nodes"]}
    for g in out["gates"]:
        g["node_id"] = node_of.get(g["id"])
        g["gate"] = by_id[g["node_id"]]["gate"] if g["node_id"] in by_id else g["kind"]
    for e in out["events"]:
        n = by_id.get(e["id"], {})
        e["source"] = "probability" if n.get("probability") is not None else "model"
        e["placeholder"] = bool(n.get("placeholder"))
    out["kind"] = "reliability" if timed else "probability"
    out["t"] = t_eval if timed else None
    out["t_default"] = t_default
    out["curve"] = curve
    out["unit"] = tree.get("unit") or ""
    notes = []
    placeholders = placeholder_labels(tree)
    if placeholders:
        notes.append(f"Placeholder (guessed) data on {_names(placeholders)}: these results are illustrative "
                     "until the guesses are replaced.")
    out["placeholders"] = placeholders
    out["notes"] = notes
    return out


def analyse_for_owner(db, tree: dict, owner_id, t: Optional[float] = None, t_max: Optional[float] = None) -> dict:
    """:func:`analyse` with saved models resolved in the caller's scope, as an RBD's are."""
    from backend.services import models as models_service

    def resolve_model(model_id: str) -> dict | None:
        return models_service.get_live_model(db, model_id, owner_id)

    return analyse(tree, resolve_model=resolve_model, t=t, t_max=t_max)


# ---------------------------------------------------------------------------
# To and from the importers' gate tree, the RBD and Open-PSA
# ---------------------------------------------------------------------------


def to_import_tree(tree: dict) -> tuple[ft.FaultTree, list[str]]:
    """The importers' ``FaultTree`` (Leaf / Gate) for a stored tree, and the
    labels of fixed-probability events (an RBD block has no fixed-probability
    model, so they become blocks without one, as an import makes them)."""
    check_complete(tree)
    nodes: dict[str, ft.Node] = {}
    fixed: list[str] = []
    for n in tree["nodes"]:
        if n["type"] == "gate":
            op = {"or": "or", "and": "and", "vote": "atleast"}[n["gate"]]
            nodes[n["id"]] = ft.Gate(n["id"], op, list(n["inputs"]), k=n.get("k"), label=n["label"])
        elif n.get("probability") is not None:
            p = float(n["probability"])
            if p in (0.0, 1.0):
                nodes[n["id"]] = ft.Leaf(n["id"], constant=p == 1.0, label=n["label"])
            else:
                fixed.append(n["label"])
                nodes[n["id"]] = ft.Leaf(n["id"], {"type": "component"}, label=n["label"])
        else:
            model = dict(n["model"])
            if n.get("placeholder"):
                model["placeholder"] = True
            nodes[n["id"]] = ft.Leaf(n["id"], {"type": "component", "model": model}, label=n["label"])
    return ft.FaultTree(nodes, tree["top"]), fixed


def to_rbd_graph(tree: dict, resolve_saved_model=None) -> tuple[dict, list[str]]:
    """The RBD for a stored tree, by the importers' conversion (OR → series,
    AND → parallel, k of n failed → n − k + 1 of n working), in the builder's
    saved shape: ``(graph, notes)``."""
    from backend.services import rbd_graph
    from backend.services.rbd_import.types import RbdImportError

    imported, fixed = to_import_tree(tree)
    try:
        compact, notes = ft.to_graph(imported, unit=tree.get("unit") or "")
    except RbdImportError as exc:
        raise FaultTreeError(str(exc)) from None
    if fixed:
        notes.append(
            f"{_names(fixed)} {'have' if len(fixed) > 1 else 'has'} a fixed probability, which an RBD block "
            f"can't hold: {'they are blocks' if len(fixed) > 1 else 'it is a block'} WITHOUT a non-repairable "
            "model — set one (e.g. a failure rate) before analysing the RBD. Nothing was assumed.")
    try:
        graph = rbd_graph.normalize_graph(compact, resolve_saved_model=resolve_saved_model)
    except rbd_graph.GraphError as exc:
        raise FaultTreeError(f"The RBD couldn't be built: {exc}") from None
    return graph, notes


def from_imported(tree: ft.FaultTree, fixed: Optional[dict] = None, unit: str = "") -> tuple[dict, list[str]]:
    """A stored tree from an importer's gate tree (Open-PSA, Galileo):
    ``(tree, notes)``. Raises :class:`FaultTreeError` for what a fault tree
    here can't hold (a spare gate: dynamic)."""
    fixed = fixed or {}
    notes: list[str] = []
    ids: dict[str, str] = {}
    used: set[str] = set()

    def new_id(name: str) -> str:
        if name in ids:
            return ids[name]
        slug = re.sub(r"[^A-Za-z0-9_.:-]+", "_", name).strip("_")[:56] or "node"
        nid, i = slug, 2
        while nid in used:
            nid = f"{slug}_{i}"
            i += 1
        used.add(nid)
        ids[name] = nid
        return nid

    out: list[dict] = []
    reached: set[str] = set()
    stack = [tree.top]
    order: list[str] = []
    while stack:
        name = stack.pop()
        if name in reached:
            continue
        reached.add(name)
        order.append(name)
        node = tree.nodes.get(name)
        if isinstance(node, ft.Gate):
            stack.extend(reversed(node.children))
    dropped_repair = []
    for name in order:
        node = tree.nodes[name]
        label = (node.label or name)[:MAX_LABEL]
        if isinstance(node, ft.Gate):
            gate = {"or": "or", "and": "and", "atleast": "vote"}[node.op]
            row = {"id": new_id(name), "type": "gate", "gate": gate, "label": label,
                   "inputs": [new_id(c) for c in node.children]}
            if gate == "vote":
                row["k"] = int(node.k or 1)
            out.append(row)
            continue
        row = {"id": new_id(name), "type": "event", "label": label}
        if node.constant is not None:
            row["probability"] = 1.0 if node.constant else 0.0
        elif name in fixed:
            row["probability"] = float(fixed[name])
        else:
            block = node.node or {}
            if block.get("type", "component") != "component":
                raise FaultTreeError(
                    f"“{label}” is a spare (standby) gate, which is dynamic logic: a fault tree here holds "
                    "AND, OR and vote gates only. Import the file as an RBD instead — standby is drawn there.")
            if block.get("repair"):
                dropped_repair.append(label)
            if block.get("model"):
                row["model"] = block["model"]
        out.append(row)
    if dropped_repair:
        notes.append(f"Repair data on {_names(dropped_repair)} was left out: a fault tree here works over "
                     "time to failure (and fixed probabilities), not repair.")
    if len(out) > MAX_NODES:
        raise FaultTreeError(
            f"The tree has {len(out)} gates and basic events — more than the {MAX_NODES} a fault tree holds. "
            "Import it as an RBD instead.")
    return {"unit": unit or "", "top": ids[tree.top], "nodes": out}, notes


def _param(model: dict, name: str) -> Optional[float]:
    for p in model.get("params") or []:
        if p.get("name") == name:
            try:
                return float(p.get("value"))
            except (TypeError, ValueError):
                return None
    return None


def to_openpsa(name: str, tree: dict, resolve_model=None, t: Optional[float] = None) -> tuple[str, list[str]]:
    """The tree as Open-PSA Model Exchange Format XML: ``(xml, notes)``.

    Exponential and Weibull events keep their models (over the system mission
    time); a fixed probability is a number. Any other model has no Open-PSA
    form, so it is written as its probability at ``t`` (the analysis time)
    and listed in ``notes`` and in a comment in the file."""
    check_complete(tree)
    by_id = {n["id"]: n for n in tree["nodes"]}
    notes: list[str] = []
    gates, events = [], []
    approximated = []
    ref = (lambda x: f'<gate name={quoteattr(x)}/>' if by_id[x]["type"] == "gate"
           else f'<basic-event name={quoteattr(x)}/>')
    for n in tree["nodes"]:
        label = f"\n      <label>{escape(n['label'])}</label>" if n["label"] != n["id"] else ""
        if n["type"] == "gate":
            kids = "".join(f"\n        {ref(x)}" for x in n["inputs"])
            head = {"or": "<or>", "and": "<and>", "vote": f'<atleast min="{n.get("k")}">'}[n["gate"]]
            tail = {"or": "</or>", "and": "</and>", "vote": "</atleast>"}[n["gate"]]
            gates.append(f'    <define-gate name={quoteattr(n["id"])}>{label}\n      {head}{kids}\n      {tail}\n'
                         "    </define-gate>")
            continue
        if n.get("probability") is not None:
            expr = f'<float value="{float(n["probability"])!r}"/>'
        else:
            model = n["model"]
            dist = model.get("distribution_id")
            rate, alpha, beta = _param(model, "failure_rate"), _param(model, "alpha"), _param(model, "beta")
            if dist == "exponential" and rate is not None and not model.get("extras"):
                expr = f'<exponential><float value="{rate!r}"/><system-mission-time/></exponential>'
            elif dist == "weibull" and alpha is not None and beta is not None and not model.get("extras"):
                expr = (f'<Weibull><float value="{alpha!r}"/><float value="{beta!r}"/><float value="0.0"/>'
                        "<system-mission-time/></Weibull>")
            else:
                if t is None:
                    raise FaultTreeError(
                        f"“{n['label']}” uses a model Open-PSA can't express; give a time to export its "
                        "probability at.")
                m = ra._build_distribution(model, n["label"], resolve_model)
                q = float(np.atleast_1d(np.asarray(m.ff(np.array([t])), dtype=float))[0])
                expr = f'<float value="{q!r}"/>'
                approximated.append(n["label"])
        events.append(f'    <define-basic-event name={quoteattr(n["id"])}>{label}\n      {expr}\n'
                      "    </define-basic-event>")
    if approximated:
        notes.append(f"{_names(approximated)} {'use models' if len(approximated) > 1 else 'uses a model'} Open-PSA "
                     f"can't express, so {'their probabilities' if len(approximated) > 1 else 'its probability'} "
                     f"at t = {t:g} {tree.get('unit') or ''} {'are' if len(approximated) > 1 else 'is'} written "
                     "as fixed numbers.".replace("  ", " "))
    unit = tree.get("unit") or ""
    comment = ""
    if unit or notes:
        lines = ([f"Time unit: {unit}."] if unit else []) + notes
        comment = "\n<!-- " + " ".join(lines).replace("--", "-") + " -->"
    xml = (
        '<?xml version="1.0" encoding="UTF-8"?>' + comment + "\n"
        "<opsa-mef>\n"
        f"  <define-fault-tree name={quoteattr(name or 'Fault tree')}>\n"
        + "\n".join(gates + events) + "\n"
        "  </define-fault-tree>\n"
        "</opsa-mef>\n"
    )
    return xml, notes


# ---------------------------------------------------------------------------
# Storage
# ---------------------------------------------------------------------------


class FaultTreeNotFound(KeyError):
    """Raised when a fault tree id is unknown (or not the caller's)."""


def _from(doc: dict | None) -> Optional[FaultTreeDoc]:
    from backend.db import from_doc

    return from_doc(FaultTreeDoc, doc)


def save_tree(db, name: str, tree: dict, owner_id: str, tree_id: str | None = None,
              expected_updated_at: str | None = None) -> FaultTreeDoc:
    """Create a tree, or update one ``owner_id`` owns (``tree_id``), with an
    optimistic check on ``expected_updated_at`` as RBDs have."""
    from backend.db import to_doc

    name = (name or "").strip()[:200] or "Untitled fault tree"
    existing = db.fault_trees.find_one({"_id": tree_id, "owner_id": owner_id}) if tree_id else None
    if existing is not None:
        query = {"_id": tree_id, "owner_id": owner_id}
        if expected_updated_at and existing.get("updated_at") is not None:
            if not access.timestamps_match(existing["updated_at"], expected_updated_at):
                raise access.EditConflict()
            query["updated_at"] = existing["updated_at"]
        doc = _from(existing)
        doc.name, doc.tree = name, tree
        doc.updated_at = access.next_updated_at(existing.get("updated_at"))
        result = db.fault_trees.update_one(
            query, {"$set": {"name": name, "tree": tree, "updated_at": doc.updated_at}})
        if result.matched_count == 0:
            raise access.EditConflict()
        return doc
    doc = FaultTreeDoc(id=uuid.uuid4().hex, name=name, owner_id=owner_id, tree=tree)
    db.fault_trees.insert_one(to_doc(doc))
    return doc


def list_trees(db, owner_id, hidden=frozenset()) -> list[FaultTreeDoc]:
    """The owner's trees plus the shared samples, newest first, minus hidden samples."""
    return [
        _from(d) for d in db.fault_trees.find({"owner_id": {"$in": access.owner_in(owner_id)}}).sort("created_at", -1)
        if d["_id"] not in hidden
    ]


def get_tree(db, tree_id: str, owner_id) -> Optional[FaultTreeDoc]:
    return _from(db.fault_trees.find_one({"_id": tree_id, "owner_id": {"$in": access.owner_in(owner_id)}}))


def rename_tree(db, tree_id: str, name: str, owner_id: str) -> FaultTreeDoc:
    doc = get_tree(db, tree_id, owner_id)
    if doc is None or doc.owner_id != owner_id:
        raise FaultTreeNotFound(tree_id)
    doc.name = (name or "").strip()[:200] or doc.name
    doc.updated_at = access.next_updated_at(doc.updated_at)
    db.fault_trees.update_one({"_id": tree_id, "owner_id": owner_id},
                              {"$set": {"name": doc.name, "updated_at": doc.updated_at}})
    return doc


def link_rbd(db, tree_id: str, rbd_id: str, owner_id: str) -> None:
    db.fault_trees.update_one({"_id": tree_id, "owner_id": owner_id}, {"$set": {"rbd_id": rbd_id}})


def delete_tree(db, tree_id: str, owner_id: str) -> None:
    if db.fault_trees.delete_one({"_id": tree_id, "owner_id": owner_id}).deleted_count == 0:
        raise FaultTreeNotFound(tree_id)


def counts(tree: dict) -> dict:
    nodes = tree.get("nodes") or []
    return {"n_gates": sum(1 for n in nodes if n.get("type") == "gate"),
            "n_events": sum(1 for n in nodes if n.get("type") == "event")}


# ---------------------------------------------------------------------------
# The sample
# ---------------------------------------------------------------------------


def _exp(rate: float) -> dict:
    return {"source": "params", "distribution": "Exponential", "distribution_id": "exponential",
            "params": [{"name": "failure_rate", "value": rate}]}


def _sample_uav_tree() -> dict:
    """A small quadcopter's loss of thrust or control, in hours. Invented
    figures, in line with the sample UAV product's FME(C)A. A quadcopter
    can't fly on three motors, so losing any one arm (its motor or its speed
    controller) is enough: an OR of the four arms. The flight controller
    votes between three IMUs, so it loses attitude only when two of the
    three have failed: a 2-of-3 vote."""
    nodes = [
        {"id": "top", "type": "gate", "gate": "or", "label": "Loss of thrust or control in flight",
         "inputs": ["thrust", "battery", "control"]},
        {"id": "thrust", "type": "gate", "gate": "or", "label": "Thrust lost on any arm",
         "note": "A quadcopter can't fly on three motors: losing one arm brings it down.",
         "inputs": [f"arm{i}" for i in range(1, 5)]},
    ]
    for i in range(1, 5):
        nodes.append({"id": f"arm{i}", "type": "gate", "gate": "or", "label": f"Arm {i}: no thrust",
                      "inputs": [f"motor{i}", f"esc{i}"]})
    for i in range(1, 5):
        nodes.append({"id": f"motor{i}", "type": "event", "label": f"Motor {i} fails", "model": _exp(8e-5)})
        nodes.append({"id": f"esc{i}", "type": "event", "label": f"Speed controller {i} fails", "model": _exp(3e-5)})
    nodes += [
        {"id": "battery", "type": "event", "label": "Battery pack fails",
         "note": "Wears out with use: a Weibull life.",
         "model": {"source": "params", "distribution": "Weibull", "distribution_id": "weibull",
                   "params": [{"name": "alpha", "value": 1500.0}, {"name": "beta", "value": 2.5}]}},
        {"id": "control", "type": "gate", "gate": "or", "label": "Flight control lost",
         "inputs": ["fc", "imus"]},
        {"id": "fc", "type": "event", "label": "Flight controller fails", "model": _exp(1e-5)},
        {"id": "imus", "type": "gate", "gate": "vote", "k": 2, "label": "Two of three IMUs fail",
         "note": "The flight controller votes between three IMUs: one failure is outvoted.",
         "inputs": ["imu_a", "imu_b", "imu_c"]},
    ]
    for c in "abc":
        nodes.append({"id": f"imu_{c}", "type": "event", "label": f"IMU {c.upper()} fails", "model": _exp(2e-5)})
    return {"unit": "Hours", "top": "top", "nodes": nodes}


SAMPLE_FAULT_TREES = [
    {"id": "sample-fault-tree-quadcopter", "name": "Quadcopter UAV — loss of thrust or control (sample)",
     "tree": _sample_uav_tree},
]


def seed_samples(db, owner: str) -> None:
    """Add the sample trees that aren't there yet (owned by ``owner``, the
    shared sample owner). Never raises: a sample never blocks start-up."""
    import logging

    from backend.db import to_doc

    log = logging.getLogger(__name__)
    for spec in SAMPLE_FAULT_TREES:
        try:
            if db.fault_trees.find_one({"_id": spec["id"]}, {"_id": 1}) is not None:
                continue
            tree = normalize_tree(spec["tree"]())
            db.fault_trees.insert_one(to_doc(FaultTreeDoc(id=spec["id"], name=spec["name"], owner_id=owner,
                                                          tree=tree)))
        except Exception as exc:  # pragma: no cover - defensive; never block boot
            log.warning("Failed to seed sample fault tree %r: %s", spec["id"], exc)
