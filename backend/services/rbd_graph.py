"""Compact <-> persisted RBD graphs, server side.

A Python port of ``frontend/src/rbdGraph.js`` (``normalizeRbdGraph`` /
``compactGraph``) so programmatic callers — the MCP server — speak the same
compact node format as the in-app assistant and get diagrams that open on the
builder canvas exactly as if the assistant had drawn them: input/output
handles, fleshed-out life models and a tidy left-to-right layered layout.

Compact node (what an assistant writes and reads)::

    {"id": "p1", "type": "component", "label": "Pump A",
     "model": {"distribution_id": "weibull",
               "params": [{"name": "alpha", "value": 900}, {"name": "beta", "value": 1.4}],
               "placeholder": true,           # optional: a guessed value
               "extras": {"gamma": 100}},     # optional: offset gamma, LFP p, ZI f0
     "repair": {...},                         # repairable diagrams only
     "instant_repair": true,                  # repairable: repaired in zero time
     "costs": {"repair": 200, "replace": 1500, "downtime": 50, "acquisition": 20000},
     "preventive": {"policy": "age", "interval": 580, "duration": 7, "cost": 1000},
     "inspection": {"interval": 8760, "duration": 0, "cost": 300},  # hidden failures
     # a per-action cost may be a range, drawn uniformly: "repair": {"min": 150, "max": 250}
     "n": 2, "k": 3, "spares": 1, "cold": true,
     "standbyModel": {...}, "startProb": 0.98,  # cold standby: spare's own model, switch reliability
     "dormancy": 0.3,                         # standby: 0 cold, 1 hot, between = warm
     "subsystem_rbd_id": "<saved rbd id>"}

A repeated block — the same physical component drawn again elsewhere — is a
component node with ``"repeat_of": "<id of the component it repeats>"`` and
no model of its own (see :mod:`backend.services.rbd_repeats`).

A node may instead carry the persisted ``data: {...}`` object; both are
accepted. ``model.saved_model_id`` references a saved plain life model; it is
resolved (owner-scoped) into the same shape the builder's model picker stores.
A repairable diagram may carry ``"costs": {"downtime_rate": 500, "horizon":
87600}`` (see :mod:`backend.services.rbd_maintenance` for the cost and
maintenance fields), ``"repair_crews": {"crews": 2}``, ``"maintenance_groups":
{name: {"setup_cost", "system_down"}}``, ``"safety_function": true`` and
``"target_sil"`` (see :mod:`backend.services.rbd_policies`).
"""

from __future__ import annotations

import math
from typing import Callable, Optional

from backend.services import rbd_repeats

COL_GAP = 280
ROW_GAP = 150

NODE_TYPES = ("input", "output", "component", "series", "parallel", "knode", "standby", "subsystem")

_ARROW = {"type": "arrowclosed", "width": 18, "height": 18}
#: Repairable block fields beyond the models (#99/#100), carried as given.
MAINTENANCE_KEYS = ("instant_repair", "costs", "preventive", "inspection", "rcm_source",
                    "maintenance_group", "crew_priority", "repair_one_at_a_time", "repair_quality")
#: Diagram-level settings of a repairable diagram (#99, #156, #157), carried as given.
DIAGRAM_KEYS = ("costs", "repair_crews", "maintenance_groups", "safety_function", "target_sil")
#: A block's capacity and the diagram's demand (#122, :mod:`.rbd_capacity`).
CAPACITY_KEYS = ("capacity",)
PRODUCTION_KEYS = ("production",)


class GraphError(ValueError):
    """A compact graph that can't be turned into a diagram (user-facing text)."""


# Size limits for any diagram, however it arrives (builder save, import, the
# assistant, the MCP server) — the same ceilings as the importers'.
MAX_BLOCKS = 5000               # blocks, besides the input and output nodes
MAX_EDGES = 50_000
MAX_UNITS = 1000                # identical units / spares in one block
#: Count fields per node type: ``(field, what, upper bound)``. A vote node's
#: ``n`` (inputs required) and ``k`` (inputs wired) are bounded by the
#: diagram's size; the unit counts expand into that many units each.
_COUNT_FIELDS = {
    "series": (("n", "the number of identical units (n)", MAX_UNITS),),
    "parallel": (("n", "the number of identical units (n)", MAX_UNITS),),
    "standby": (("spares", "the number of spares", MAX_UNITS),
                ("k", "the number of units running (k)", MAX_UNITS)),
    "loadshare": (("units", "the number of units", MAX_UNITS),
                  ("k", "the number of units required (k)", MAX_UNITS)),
    "knode": (("n", "the number of working inputs required (n)", MAX_BLOCKS),
              ("k", "the number of inputs (k)", MAX_BLOCKS)),
}


def _count(value, where: str, what: str, upper: int) -> int:
    if isinstance(value, bool):
        raise GraphError(f"{where}: {what} must be a whole number.")
    try:
        number = float(value)
    except (TypeError, ValueError):
        raise GraphError(f"{where}: {what} must be a whole number.") from None
    if not math.isfinite(number) or number != int(number):
        raise GraphError(f"{where}: {what} must be a whole number.")
    if not 1 <= number <= upper:
        raise GraphError(f"{where}: {what} must be from 1 to {upper:,} (got {value}).")
    return int(number)


def check_counts(ntype: str, data: dict, where: str) -> None:
    """Validate a block's unit counts (``n``, ``k``, ``spares``, ``units``):
    whole numbers from 1 to their bound, and a load-sharing group's ``k`` no
    more than its ``units``. A vote node's ``n`` is checked against the
    branches actually wired into it when the diagram is validated (its ``k``
    is only the count the builder shows). Missing fields are left to their
    defaults."""
    got = {}
    for key, what, upper in _COUNT_FIELDS.get(ntype, ()):
        value = data.get(key)
        if value is None or value == "":
            continue
        if ntype == "standby" and key == "spares" and value in (0, "0", 0.0):
            continue  # older diagrams hold 0; the analysis has always read it as 1
        got[key] = _count(value, where, what, upper)
    if ntype == "loadshare" and "k" in got and "units" in got and got["k"] > got["units"]:
        raise GraphError(f"{where}: k ({got['k']}) can't exceed the number of units ({got['units']}).")


def check_size(nodes, edges) -> None:
    """At most :data:`MAX_BLOCKS` blocks and :data:`MAX_EDGES` connections."""
    if not isinstance(nodes, list) or not isinstance(edges, list):
        raise GraphError("nodes and edges must be lists.")
    blocks = sum(1 for n in nodes if not (isinstance(n, dict) and n.get("type") in ("input", "output")))
    if blocks > MAX_BLOCKS:
        raise GraphError(f"the diagram has {blocks:,} blocks; a diagram can hold at most {MAX_BLOCKS:,} "
                         "(group parts of it into sub-systems).")
    if len(edges) > MAX_EDGES:
        raise GraphError(f"the diagram has {len(edges):,} connections; a diagram can hold at most "
                         f"{MAX_EDGES:,} (group parts of it into sub-systems).")


def check_limits(graph) -> None:
    """Size and unit-count limits for a whole graph, compact or persisted
    (a node's fields may sit on it or in its ``data``). Raises
    :class:`GraphError`."""
    if not isinstance(graph, dict):
        raise GraphError("the diagram must be an object.")
    nodes = graph.get("nodes") or []
    edges = graph.get("edges") or []
    check_size(nodes, edges)
    for raw in nodes:
        if not isinstance(raw, dict):
            continue
        fields = {k: raw[k] for k in ("n", "k", "spares", "units", "label") if raw.get(k) is not None}
        if isinstance(raw.get("data"), dict):
            fields.update(raw["data"])
        label = fields.get("label") or raw.get("id")
        check_counts(str(raw.get("type") or ""), fields, f"node '{label}'")


# A diagram with nothing to analyse yet (#271): only Input and Output, or
# blocks with no path through them from Input to Output. Every analysis
# answers these in the same plain words (a 422 for the API and MCP callers);
# the app shows its own empty state and doesn't ask.
NO_BLOCKS = "no_blocks"
NOT_CONNECTED = "not_connected"
GAP_MESSAGES = {
    NO_BLOCKS: "The diagram has no blocks yet. Add blocks between Input and Output, and connect them.",
    NOT_CONNECTED: ("The diagram's blocks aren't connected from Input to Output yet. Connect them so at least "
                    "one path runs from Input, through the blocks, to Output."),
}


def diagram_gap(graph) -> Optional[str]:
    """:data:`NO_BLOCKS` when the diagram has no blocks besides Input and
    Output, :data:`NOT_CONNECTED` when no block lies on a path from Input to
    Output, else None. A diagram without exactly one Input and one Output is
    left to the analyses' own messages (None)."""
    if not isinstance(graph, dict):
        return None
    nodes = [n for n in graph.get("nodes") or [] if isinstance(n, dict)]
    blocks = {n.get("id") for n in nodes if n.get("type") not in ("input", "output")}
    if not blocks:
        return NO_BLOCKS
    ends = {kind: [n.get("id") for n in nodes if n.get("type") == kind] for kind in ("input", "output")}
    if len(ends["input"]) != 1 or len(ends["output"]) != 1:
        return None
    forward: dict = {}
    backward: dict = {}
    for e in graph.get("edges") or []:
        if isinstance(e, dict) and e.get("source") is not None and e.get("target") is not None:
            forward.setdefault(e["source"], []).append(e["target"])
            backward.setdefault(e["target"], []).append(e["source"])

    def reach(start, adjacency) -> set:
        seen, stack = {start}, [start]
        while stack:
            for nxt in adjacency.get(stack.pop(), ()):
                if nxt not in seen:
                    seen.add(nxt)
                    stack.append(nxt)
        return seen

    on_path = reach(ends["input"][0], forward) & reach(ends["output"][0], backward) & blocks
    return None if on_path else NOT_CONNECTED


def gap_message(graph) -> Optional[str]:
    """The plain message for :func:`diagram_gap`, or None."""
    gap = diagram_gap(graph)
    return GAP_MESSAGES[gap] if gap else None


def layout_graph(nodes: list[dict], edges: list[dict]) -> list[dict]:
    """Longest-path layered layout (mirrors the builder's Auto-arrange)."""
    ids = {n["id"] for n in nodes}
    indeg = {n["id"]: 0 for n in nodes}
    adj: dict[str, list[str]] = {n["id"]: [] for n in nodes}
    for e in edges:
        if e["source"] not in ids or e["target"] not in ids:
            continue
        adj[e["source"]].append(e["target"])
        indeg[e["target"]] += 1

    rank: dict[str, int] = {}
    remaining = dict(indeg)
    queue = [n["id"] for n in nodes if remaining[n["id"]] == 0]
    for nid in queue:
        rank[nid] = 0
    while queue:
        nid = queue.pop(0)
        r = rank.get(nid, 0)
        for t in adj[nid]:
            rank[t] = max(rank.get(t, 0), r + 1)
            remaining[t] -= 1
            if remaining[t] == 0:
                queue.append(t)
    for n in nodes:
        rank.setdefault(n["id"], 0)

    max_rank = max(rank.values(), default=0)
    if "input" in ids:
        rank["input"] = 0
    if "output" in ids:
        rank["output"] = max(max_rank, 1)

    cols: dict[int, list[dict]] = {}
    for n in nodes:
        cols.setdefault(rank[n["id"]], []).append(n)
    out = []
    for r, members in cols.items():
        members.sort(key=lambda n: n["id"])
        m = len(members)
        for i, n in enumerate(members):
            out.append({**n, "position": {"x": r * COL_GAP, "y": (i - (m - 1) / 2) * ROW_GAP}})
    return out


def _params(raw, where: str) -> list[dict]:
    out = []
    for p in raw or []:
        if not isinstance(p, dict) or p.get("name") is None or p.get("value") is None:
            raise GraphError(f"{where}: params must be a list of {{name, value}}.")
        try:
            out.append({"name": str(p["name"]), "value": float(p["value"])})
        except (TypeError, ValueError):
            raise GraphError(f"{where}: parameter '{p['name']}' must be a number.") from None
    return out


def _inline_model(model: dict, where: str) -> dict:
    """Flesh out an inline ``{distribution_id, params}`` model."""
    from backend import fitting
    from backend.services import rbd_mixture

    dist = str(model.get("distribution_id") or model.get("distribution") or "").strip()
    if dist == rbd_mixture.MIXTURE_ID:
        # Two failure modes (#318): base_distribution_id + numbered params.
        try:
            return rbd_mixture.normalize(model, where)
        except rbd_mixture.MixtureError as exc:
            raise GraphError(str(exc)) from None
    if not dist:
        raise GraphError(f"{where}: the model needs a distribution_id (or a saved_model_id).")
    try:
        dist_id = fitting.resolve_distribution_id(dist)
    except fitting.FitError:
        raise GraphError(
            f"{where}: unsupported distribution '{dist}' — use one of {', '.join(fitting.DISTRIBUTIONS)}."
        ) from None
    params = _params(model.get("params"), where)
    if not params and model.get("mean") is not None:
        params = _params_from_mean(dist_id, model, where)
    if not params:
        raise GraphError(f"{where}: the model needs params, e.g. [{{\"name\": \"alpha\", \"value\": 900}}].")
    try:
        fitting.param_values(dist_id, params, where)  # SurPyval names only
    except fitting.FitError as exc:
        raise GraphError(str(exc)) from None
    out = {
        "source": "params",
        "distribution": fitting.DISTRIBUTIONS[dist_id]["name"],
        "distribution_id": dist_id,
        "params": params,
    }
    extras = _extras(model.get("extras"), where)
    if extras:
        out["extras"] = extras
    if model.get("placeholder"):
        out["placeholder"] = True
    return out


def _params_from_mean(dist_id: str, model: dict, where: str) -> list[dict]:
    """A model given as its ``mean`` (an MTBF or MTTR) and the shape or spread
    in ``given`` (#299): SurPyval's parameters with that mean."""
    from backend.services import rbd_block_inputs

    given = model.get("given") or {}
    if not isinstance(given, dict):
        raise GraphError(f"{where}: given must be an object, e.g. {{\"beta\": 1.6}}.")
    try:
        return rbd_block_inputs.from_mean(dist_id, model.get("mean"), given)["params"]
    except rbd_block_inputs.BlockInputError as exc:
        raise GraphError(f"{where}: {exc}") from None


def _extras(raw, where: str) -> dict:
    """A model's fitted extras the analysis rebuilds it with: an offset
    ``gamma``, an LFP ``p`` and a zero-inflation ``f0`` (finite numbers)."""
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise GraphError(f"{where}: extras must be an object of gamma, p and f0.")
    out = {}
    for key in ("gamma", "p", "f0"):
        value = raw.get(key)
        if value is None:
            continue
        try:
            number = float(value)
        except (TypeError, ValueError):
            raise GraphError(f"{where}: {key} must be a number.") from None
        if isinstance(value, bool) or not math.isfinite(number):
            raise GraphError(f"{where}: {key} must be a finite number.")
        out[key] = number
    return out


def _positions(nodes: list) -> Optional[dict]:
    """``{id: position}`` when every node already has a finite ``{x, y}``
    (a diagram drawn elsewhere keeps its layout), else None."""
    out = {}
    for n in nodes:
        pos = n.get("position") if isinstance(n, dict) else None
        if not isinstance(pos, dict):
            return None
        try:
            x, y = float(pos.get("x")), float(pos.get("y"))
        except (TypeError, ValueError):
            return None
        if not (math.isfinite(x) and math.isfinite(y)):
            return None
        out[str(n.get("id") or "").strip()] = {"x": x, "y": y}
    return out


def _saved_model(model_id: str, where: str, resolve_saved_model) -> dict:
    """The builder model-picker shape for a saved model reference."""
    saved = resolve_saved_model(model_id) if resolve_saved_model else None
    if saved is None:
        raise GraphError(f"{where}: saved model '{model_id}' not found.")
    r = saved.results or {}
    if saved.kind == "nonparametric":
        # RePyability 0.12 refuses a non-parametric node in a diagram.
        raise GraphError(
            f"{where}: model “{saved.name}” is non-parametric ({r.get('distribution') or 'an empirical estimate'}), "
            "which an RBD block can't take. Fit a parametric distribution (Weibull, say) to the same "
            "data and use that, or give distribution_id + params inline."
        )
    if saved.kind not in ("distribution", "regression"):
        raise GraphError(
            f"{where}: model “{saved.name}” is a {saved.kind} model — RBD blocks need a "
            "life distribution; give distribution_id + params inline instead."
        )
    return {
        "source": "saved",
        "kind": saved.kind,
        "modelId": saved.id,
        "name": saved.name,
        "distribution": r.get("distribution"),
        "distribution_id": r.get("distribution_id") or saved.distribution_id,
        "params": [{"name": p.get("name"), "value": p.get("value")} for p in (r.get("params") or [])],
        "extras": r.get("extras"),
        "covariates": (r.get("functions") or {}).get("covariates") or [],
        "unit": r.get("unit") or "",
        # A mixture fit's modes (#318): the distribution each follows.
        **({"base_distribution_id": r.get("base_distribution_id") or "weibull", "mixture": r.get("mixture")}
           if r.get("distribution_id") == "mixture" else {}),
    }


def _model(model, where: str, resolve_saved_model) -> dict:
    if not isinstance(model, dict):
        raise GraphError(f"{where}: model must be an object.")
    saved_id = model.get("saved_model_id") or model.get("modelId") or model.get("model_id")
    if saved_id:
        out = _saved_model(str(saved_id), where, resolve_saved_model)
        if model.get("source") != "saved" and _inline_disagrees(model, out):
            # The compact form get_rbd returns repeats a saved model's own
            # distribution + params, so those round-trip; different ones are
            # a conflict, never silently dropped.
            raise GraphError(
                f"{where}: give exactly one of saved_model_id or distribution_id + params — the inline "
                f"values disagree with the saved model “{out.get('name')}”. Drop them to use the saved "
                "model, or drop saved_model_id to use them.")
        if model.get("placeholder"):
            out["placeholder"] = True
        return out
    return _inline_model(model, where)


def _inline_disagrees(model: dict, saved: dict) -> bool:
    """Whether a compact model's inline distribution/params differ from the
    saved model it also references."""
    from backend import fitting

    dist = model.get("distribution_id") or model.get("distribution")
    if dist == "mixture" or saved.get("distribution_id") == "mixture":
        if dist and dist != saved.get("distribution_id"):
            return True
    elif dist:
        try:
            if fitting.resolve_distribution_id(str(dist)) != saved.get("distribution_id"):
                return True
        except fitting.FitError:
            return True
    if model.get("params"):
        mine = {str(p.get("name")): p.get("value") for p in model["params"] if isinstance(p, dict)}
        theirs = {str(p.get("name")): p.get("value") for p in saved.get("params") or []}
        if set(mine) != set(theirs):
            return True
        for name, value in mine.items():
            try:
                if abs(float(value) - float(theirs[name])) > 1e-9 * max(1.0, abs(float(theirs[name]))):
                    return True
            except (TypeError, ValueError):
                return True
    return False


def normalize_model(model, where: str, resolve_saved_model=None) -> dict:
    """A compact life model (inline, or a ``saved_model_id``) in the persisted shape."""
    return _model(model, where, resolve_saved_model)


def normalize_repair(repair, where: str) -> dict:
    """A compact time-to-repair model (inline only) in the persisted shape."""
    if not isinstance(repair, dict):
        raise GraphError(f"{where}: repair must be an object.")
    return _inline_model(repair, f"{where} repair")


def normalize_node(raw, resolve_saved_model: Optional[Callable[[str], object]] = None) -> dict:
    """One compact (or persisted) node in the persisted builder shape, without
    a position (:func:`layout_graph` places it). Raises :class:`GraphError`."""
    if not isinstance(raw, dict):
        raise GraphError("each node must be an object.")
    nid = str(raw.get("id") or "").strip()
    ntype = str(raw.get("type") or "").strip()
    if not nid:
        raise GraphError("every node needs an id.")
    if ntype not in NODE_TYPES:
        raise GraphError(f"node '{nid}': type must be one of {', '.join(NODE_TYPES)}.")

    data = dict(raw.get("data") or {})
    for key in ("label", "model", "repair", "n", "k", "spares", "cold", "dormancy",
                "standbyModel", "startProb", "repeat_of") + MAINTENANCE_KEYS + CAPACITY_KEYS:
        if raw.get(key) is not None and key not in data:
            data[key] = raw[key]
    if raw.get("subsystem_rbd_id") and "rbd" not in data:
        data["rbd"] = {"id": str(raw["subsystem_rbd_id"])}
    where = f"node '{data.get('label') or nid}'"
    if data.get("model") is not None:
        data["model"] = normalize_model(data["model"], where, resolve_saved_model)
    if data.get("standbyModel") is not None:
        data["standbyModel"] = normalize_model(data["standbyModel"], f"{where} spare", resolve_saved_model)
    if data.get("repair") is not None:
        data["repair"] = normalize_repair(data["repair"], where)
    for key in ("costs", "preventive", "inspection", "rcm_source", "repair_quality"):
        if data.get(key) is not None and not isinstance(data[key], dict):
            raise GraphError(f"{where}: {key} must be an object.")
    if isinstance(data.get("repair_quality"), dict) and data["repair_quality"].get("model", "perfect") == "perfect" \
            and data["repair_quality"].get("replace_after") is None:
        data.pop("repair_quality")  # perfect repair is the default (#68)
    if data.get("maintenance_group") is not None and not isinstance(data["maintenance_group"], str):
        raise GraphError(f"{where}: maintenance_group must be a group name.")
    for key in ("preventive", "inspection"):
        spec = data.get(key)
        if spec and isinstance(spec.get("duration"), dict):
            data[key] = {**spec, "duration": _inline_model(spec["duration"], f"{where} {key} duration")}
    check_counts(ntype, data, where)
    _check_capacity(ntype, data, where)
    if not data.get("label"):
        data["label"] = "Input" if ntype == "input" else "Output" if ntype == "output" else nid

    node = {"id": nid, "type": ntype, "data": data}
    if ntype == "input":
        node.update(sourcePosition="right", deletable=False, className="rbd-node rbd-io")
    elif ntype == "output":
        node.update(targetPosition="left", deletable=False, className="rbd-node rbd-io")
    return node


def _check_capacity(ntype: str, data: dict, where: str) -> None:
    """A block's capacity, checked and stored as :mod:`.rbd_capacity` reads
    it (#122)."""
    from backend.services import rbd_capacity

    if data.get("capacity") in (None, "", []):
        data.pop("capacity", None)
        return
    if ntype not in rbd_capacity.CAPACITY_TYPES:
        raise GraphError(f"{where}: only component and standby blocks take a capacity.")
    try:
        data["capacity"] = rbd_capacity.parse_capacity(data["capacity"], where)
    except rbd_capacity.CapacityError as exc:
        raise GraphError(str(exc)) from None


def make_edge(source: str, target: str, edge_id: str) -> dict:
    """A persisted builder edge source -> target."""
    return {"id": edge_id, "source": source, "target": target, "type": "smoothstep", "markerEnd": dict(_ARROW)}


def normalize_graph(
    graph: dict,
    resolve_saved_model: Optional[Callable[[str], object]] = None,
) -> dict:
    """Turn a compact ``{nodes, edges, unit, repairable?}`` into the persisted
    builder shape, laid out left to right — unless every node already has a
    ``position`` (a diagram drawn elsewhere, e.g. a RePyability JSON file
    Reliafy wrote), which is kept. Raises :class:`GraphError` with a fixable
    message."""
    raw_nodes = graph.get("nodes") or []
    raw_edges = graph.get("edges") or []
    check_size(raw_nodes, raw_edges)

    nodes, seen = [], set()
    for raw in raw_nodes:
        if isinstance(raw, dict) and str(raw.get("id") or "").strip() in seen:
            raise GraphError(f"duplicate node id '{str(raw['id']).strip()}'.")
        node = normalize_node(raw, resolve_saved_model)
        seen.add(node["id"])
        nodes.append(node)

    _, problems = rbd_repeats.find_repeats(nodes)
    if problems:
        raise GraphError(next(iter(problems.values())))

    edges = []
    for i, e in enumerate(raw_edges):
        if not isinstance(e, dict) or not e.get("source") or not e.get("target"):
            raise GraphError("each edge needs a source and a target node id.")
        src, tgt = str(e["source"]), str(e["target"])
        for end in (src, tgt):
            if end not in seen:
                raise GraphError(f"edge {src} -> {tgt} references unknown node '{end}'.")
        edges.append(make_edge(src, tgt, e.get("id") or f"e-{src}-{tgt}-{i}"))

    positions = _positions(raw_nodes) if raw_nodes else None
    if positions is not None:
        placed = [{**n, "position": positions[n["id"]]} for n in nodes]
    else:
        placed = layout_graph(nodes, edges)
    out = {"nodes": placed, "edges": edges, "unit": str(graph.get("unit") or "")}
    if graph.get("repairable"):
        out["repairable"] = True
    if graph.get("ccf_groups"):
        out["ccf_groups"] = graph["ccf_groups"]
    for key in DIAGRAM_KEYS:
        if graph.get(key):
            out[key] = graph[key]
    if graph.get("production"):
        from backend.services import rbd_capacity

        try:
            production = rbd_capacity.parse_production(graph["production"])
        except rbd_capacity.CapacityError as exc:
            raise GraphError(str(exc)) from None
        if production:
            out["production"] = production
    _carry_mission(graph, out)
    return out


def _carry_mission(graph: dict, out: dict) -> None:
    """A phased mission's phases and a network's terminals (#160), cleaned."""
    from backend.services import rbd_network, rbd_phases

    rbd_phases.carry(graph, out)
    rbd_network.carry(graph, out)


def compact_graph(graph: dict) -> dict:
    """Strip a persisted graph to what an assistant needs to read and edit."""
    nodes = []
    for n in graph.get("nodes") or []:
        d = n.get("data") or {}
        node = {"id": n.get("id"), "type": n.get("type")}
        if d.get("label"):
            node["label"] = d["label"]
        for key in ("model", "repair", "standbyModel"):
            m = d.get(key)
            if isinstance(m, dict):
                cm = {"distribution_id": m.get("distribution_id"), "params": m.get("params")}
                if m.get("base_distribution_id"):
                    cm["base_distribution_id"] = m["base_distribution_id"]  # a mixture's modes (#318)
                if m.get("modelId"):
                    cm["saved_model_id"] = m["modelId"]
                if m.get("placeholder"):
                    cm["placeholder"] = True
                if m.get("extras") and not m.get("modelId"):
                    cm["extras"] = m["extras"]
                node[key] = cm
        for key in ("n", "k", "spares", "cold", "dormancy", "startProb", "repeat_of") + MAINTENANCE_KEYS \
                + CAPACITY_KEYS:
            if d.get(key) is not None:
                node[key] = d[key]
        if isinstance(d.get("rbd"), dict) and d["rbd"].get("id"):
            node["subsystem_rbd_id"] = d["rbd"]["id"]
        nodes.append(node)
    edges = [{"source": e.get("source"), "target": e.get("target")} for e in graph.get("edges") or []]
    out = {"nodes": nodes, "edges": edges, "unit": graph.get("unit") or ""}
    if graph.get("repairable"):
        out["repairable"] = True
    if graph.get("ccf_groups"):
        out["ccf_groups"] = graph["ccf_groups"]
    for key in DIAGRAM_KEYS + PRODUCTION_KEYS:
        if graph.get(key):
            out[key] = graph[key]
    try:
        _carry_mission(graph, out)
    except GraphError:
        pass  # a malformed saved setting: left out of the compact view
    return out


def placeholder_labels(graph: dict) -> list[str]:
    """Labels of blocks whose life model is a guessed placeholder."""
    return [
        (n.get("data") or {}).get("label") or n.get("id")
        for n in graph.get("nodes") or []
        if isinstance((n.get("data") or {}).get("model"), dict) and n["data"]["model"].get("placeholder")
    ]
