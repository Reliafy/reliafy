"""Redundancy allocation: how many copies of each block a design needs (#98).

Given a non-repairable builder graph, a mission time ``t`` and, for the blocks
the user wants to design, what one copy costs (and optionally weighs and how
much space it takes), the most copies that fit, and optional alternative
component types, this finds

* the most reliable design within a budget (cost, weight and/or volume), or
* the cheapest design that reaches a target reliability at ``t``,

exactly, with RePyability's ``NonRepairableRBD.allocate_redundancy`` (a dynamic
program when the designed blocks are in series with the rest, an exhaustive
search otherwise), and the whole cost–reliability trade-off with
``redundancy_front``. Redundancy can be active copies (all running, ``k`` of
them needed), cold-standby spares, or whichever is better per block.

:func:`apply_design` writes a chosen design back onto the diagram with the
blocks the builder already has — a component, a ``parallel`` block of ``n``
identical units, a cold ``standby`` block, or copies wired into a k-out-of-n
voting node — so the user can review it and save it themselves.

Only single components (and parallel blocks of identical units, whose ``n``
becomes the number of copies) can be given copies — not a repeated block (one
component drawn in several places, #102), which is refused explicitly; the
rest of a diagram with repeated blocks is designed as usual. Everything else in the
diagram — sub-systems, standby, k-of-n gates, load-sharing and series blocks —
stays as drawn. Repairable diagrams are refused here: the library allocates
over reliability at a mission time (their cheapest design is #99's).

Common-cause (beta-factor) groups are scored in every candidate design
(RePyability 0.11, #140): a copy of a group member joins its group, so the
shared cause that fails the member fails each of its copies too, with the
group's ``beta`` unchanged at the larger size. Such a member's copies are
active copies of its own model (``required`` of them needed): no alternative
types and no cold spares, which the library doesn't model in a group.
:func:`apply_design` draws each copy of a member as its own component and adds
it to the member's group, so the applied diagram analyses to the reliability
the design reported.
"""

from __future__ import annotations

import copy
import math
import time
from typing import Callable, Optional

import numpy as np

from repyability import ComponentOption

from backend.services import rbd_analysis, rbd_repeats
from backend.services.rbd_analysis import AnalysisError

#: Resources a copy can use. Cost is always given; weight and volume are
#: optional (a block that doesn't give one uses none of it).
RESOURCES = ("cost", "weight", "volume")
#: Block types that can be given copies.
ALLOCATABLE = ("component", "parallel")
#: The most copies of one block the panel offers (keeps the search quick).
MAX_COPIES = 8
#: The most blocks designed at once.
MAX_BLOCKS = 25
#: The most component types per block, the one as drawn included.
MAX_TYPES = 4
#: Points of the trade-off curve returned for the chart.
FRONT_POINTS = 300
#: Beyond this many combinations of block designs, a trade-off curve over
#: blocks that aren't all in series is sampled at spending levels instead of
#: listed exhaustively (which takes seconds per few hundred thousand).
FRONT_SEARCH_LIMIT = 300_000
FRONT_LEVELS = 30
FRONT_SECONDS = 3.0
#: Beyond this many combinations (blocks not all in series), the answer comes
#: from the library's greedy search: exact takes tens of seconds, or gives up.
EXACT_COMBINATIONS = 5_000_000
STRATEGIES = ("active", "cold", "choose")

# Layout of blocks written back onto the canvas (see RbdBuilder's layout).
_COL_GAP = 280
_COPY_GAP = 110
_ARROW = {"type": "arrowclosed", "width": 18, "height": 18}
_HORIZONTAL = {"sourcePosition": "right", "targetPosition": "left"}


class DesignError(ValueError):
    """A design request that can't be solved (user-facing text)."""


# ---------------------------------------------------------------------------
# Input checking
# ---------------------------------------------------------------------------
def _number(raw, what: str, *, minimum: float = 0.0, strict: bool = False) -> float:
    try:
        value = float(raw)
    except (TypeError, ValueError):
        raise DesignError(f"{what} must be a number.") from None
    if not math.isfinite(value) or value < minimum or (strict and value <= minimum):
        bound = "greater than" if strict else "at least"
        raise DesignError(f"{what} must be a finite number {bound} {minimum:g}.")
    return value


def _integer(raw, what: str, low: int, high: int) -> int:
    try:
        value = float(raw)
    except (TypeError, ValueError):
        raise DesignError(f"{what} must be a whole number.") from None
    if not value.is_integer() or not low <= value <= high:
        raise DesignError(f"{what} must be a whole number from {low} to {high}.")
    return int(value)


def _amounts(raw: dict, where: str) -> dict:
    """What one copy uses: a positive cost, and optional weight and volume."""
    out = {"cost": _number(raw.get("cost"), f"{where}: the unit cost", strict=True)}
    for r in RESOURCES[1:]:
        if raw.get(r) not in (None, ""):
            out[r] = _number(raw.get(r), f"{where}: the {r}")
    return out


def _check_graph(graph: dict) -> dict:
    if not isinstance(graph, dict):
        raise DesignError("The diagram is missing.")
    if graph.get("repairable"):
        raise DesignError(
            "Redundancy design works on non-repairable diagrams (reliability at a "
            "mission time). Switch the diagram to Non-repairable to design it."
        )
    return {n.get("id"): n for n in graph.get("nodes") or [] if isinstance(n, dict)}


def _group_index(graph: dict) -> dict:
    """Each node's common-cause group as drawn: ``{node id: index into
    graph['ccf_groups']}``."""
    out: dict = {}
    for i, g in enumerate(graph.get("ccf_groups") or []):
        if isinstance(g, dict):
            for m in g.get("members") or []:
                out.setdefault(m, i)
    return out


def _beta_text(group: dict) -> str:
    try:
        return f"{float(group.get('beta')):g}"
    except (TypeError, ValueError):
        return str(group.get("beta"))


def _parse_blocks(graph: dict, raw_blocks) -> list[dict]:
    """The designed blocks, checked: id, label, current copies, what a copy of
    each type uses, the life model of each type, and the redundancy options."""
    nodes = _check_graph(graph)
    repeated = set(rbd_repeats.find_repeats(list(nodes.values()))[0].values())
    groups = _group_index(graph)
    if not isinstance(raw_blocks, list) or not raw_blocks:
        raise DesignError("Choose at least one block to design.")
    if len(raw_blocks) > MAX_BLOCKS:
        raise DesignError(f"Design at most {MAX_BLOCKS} blocks at a time.")
    blocks, seen = [], set()
    for raw in raw_blocks:
        if not isinstance(raw, dict):
            raise DesignError("Each designed block must be an object.")
        bid = raw.get("id")
        node = nodes.get(bid)
        if node is None:
            raise DesignError(f"Block '{bid}' isn't in the diagram.")
        if bid in seen:
            raise DesignError(f"Block '{bid}' is listed twice.")
        seen.add(bid)
        data = node.get("data") or {}
        label = data.get("label") or bid
        ntype = node.get("type")
        if rbd_repeats.repeat_of(node) is not None or bid in repeated:
            # A repeated block (#102) is one component drawn in several places:
            # its copies would all have to be wired into each appearance, which
            # neither the library's allocation nor apply_design does.
            raise DesignError(
                f"“{label}” is drawn in more than one place (a repeated block), so it "
                "can't be given copies here. Design the other blocks, or draw its "
                "appearances as separate components to design it.")
        if ntype not in ALLOCATABLE:
            kind = {"knode": "k-out-of-n"}.get(ntype, ntype)
            raise DesignError(
                f"“{label}” is a {kind} block. Only single components and parallel "
                "blocks of identical units can be given copies; sub-systems, "
                "standby, k-out-of-n, load-sharing and series blocks stay as drawn."
            )
        if not data.get("model"):
            raise DesignError(f"“{label}” has no life model — set one to design it.")
        group = groups.get(bid)
        if group is not None and ntype != "component":
            # As drawn the whole block is one member; designed, each unit would
            # have to join the group, which changes what the group means.
            raise DesignError(
                f"“{label}” is a parallel block in a common-cause group, so it can't be "
                "given copies here. Draw its units as separate components in the group "
                "to design it.")
        max_copies = _integer(raw.get("max_copies", 3), f"“{label}”: the most copies", 1, MAX_COPIES)
        required = _integer(raw.get("required", 1), f"“{label}”: the copies that must work", 1, max_copies)
        strategy = raw.get("strategy") or "active"
        if strategy not in STRATEGIES:
            raise DesignError(f"“{label}”: redundancy must be active, cold standby or best of the two.")
        if strategy != "active" and required > 1:
            raise DesignError(
                f"“{label}”: standby spares are supported with one unit running. "
                "For k-out-of-n, use active redundancy."
            )
        switching = 1.0
        if strategy != "active":
            switching = _number(raw.get("switching", 1.0), f"“{label}”: the switch reliability")
            if switching > 1.0:
                raise DesignError(f"“{label}”: the switch reliability must be from 0 to 1.")
        types = [{
            "name": str(raw.get("name") or "Current"),
            "model": data["model"],
            "amounts": _amounts(raw, f"“{label}”"),
        }]
        alternatives = raw.get("types") or []
        if not isinstance(alternatives, list):
            raise DesignError(f"“{label}”: the alternative types must be a list.")
        if group is not None and strategy != "active":
            raise DesignError(
                f"“{label}” is in a common-cause group: its copies join the group as "
                "active copies (a shared cause striking cold spares isn't modelled), so "
                "use active redundancy for it.")
        if group is not None and alternatives:
            raise DesignError(
                f"“{label}” is in a common-cause group, whose members are identical: "
                "its copies join the group as copies of it, so it can't take "
                "alternative component types.")
        if len(alternatives) + 1 > MAX_TYPES:
            raise DesignError(f"“{label}”: give at most {MAX_TYPES - 1} alternative types.")
        for i, alt in enumerate(alternatives, start=1):
            if not isinstance(alt, dict):
                raise DesignError(f"“{label}”: each alternative type must be an object.")
            name = str(alt.get("name") or f"Type {i + 1}")
            if not alt.get("model"):
                raise DesignError(f"“{label}”: set a life model for the “{name}” type.")
            types.append({
                "name": name,
                "model": alt["model"],
                "amounts": _amounts(alt, f"“{label}” ({name})"),
            })
        current = max(int(data.get("n") or 1), 1) if ntype == "parallel" else 1
        blocks.append({
            "id": bid,
            "label": label,
            "node": node,
            "current": current,
            "max_copies": max_copies,
            "required": required,
            "strategy": strategy,
            "switching": switching,
            "types": types,
            "group": group,
        })
    return blocks


def _stripped(graph: dict, designed: set) -> dict:
    """The graph to allocate over: what-if pins cleared (the design is about
    the components' real reliability) and each designed parallel block reduced
    to one unit of its model — the copies are what the search chooses."""
    out = copy.deepcopy(graph)
    for node in out.get("nodes") or []:
        data = node.get("data") or {}
        data.pop("state", None)
        if node.get("id") in designed and node.get("type") == "parallel":
            node["type"] = "component"
            data.pop("n", None)
            data.pop("kind", None)
    return out


def _build(graph: dict, resolve_model, resolve_subsystem):
    try:
        rbd, labels, _types, reliabilities, *_ = rbd_analysis._build_rbd(
            graph, resolve_subsystem, None, resolve_model
        )
    except AnalysisError as exc:
        raise DesignError(str(exc)) from None
    return rbd, labels, reliabilities


def _type_model(block: dict, ty: dict, resolve_model):
    """The life model of an alternative component type."""
    try:
        return rbd_analysis._build_distribution(
            ty["model"], f"“{block['label']}” ({ty['name']})", resolve_model
        )
    except AnalysisError as exc:
        raise DesignError(str(exc)) from None


def _reliability_at(rbd, t: float) -> float:
    return float(np.ravel(rbd.sf(np.atleast_1d(float(t))))[0])


def _friendly(message: str, blocks: list[dict]) -> str:
    """A RePyability message in the panel's terms (block labels, not ids)."""
    for b in blocks:
        message = message.replace(f"node {b['id']!r}", f"“{b['label']}”")
        message = message.replace(f"Node {b['id']!r}", f"“{b['label']}”")
    for r in RESOURCES:
        message = message.replace(f"budget[{r!r}]", f"the {r} budget")
    message = (
        message.replace("within max_units", "within the most copies allowed")
        .replace("max_units", "most copies")
        .replace("costed node", "designed block")
        .replace("costs", "the designed blocks")
    )
    return message[:1].upper() + message[1:]


# ---------------------------------------------------------------------------
# Allocation
# ---------------------------------------------------------------------------
def _design_payload(result, blocks: list[dict], resources: list[str]) -> dict:
    """One allocation (a RedundancyAllocation) as JSON: per block the copies,
    their types and what they use."""
    out = []
    for b in blocks:
        copies = int(result.units[b["id"]])
        if len(b["types"]) > 1:
            counts = {int(k): int(v) for k, v in (result.mix.get(b["id"]) or {}).items()}
        else:
            counts = {0: copies}
        mix = [
            {"type": i, "name": b["types"][i]["name"], "copies": counts[i]}
            for i in sorted(counts)
            if counts[i]
        ]
        used = {
            r: math.fsum(b["types"][m["type"]]["amounts"].get(r, 0.0) * m["copies"] for m in mix)
            for r in resources
        }
        out.append({
            "id": b["id"],
            "label": b["label"],
            "copies": copies,
            "required": b["required"],
            "strategy": result.strategy.get(b["id"], "active"),
            "mix": mix,
            "resources": used,
        })
    return {
        "reliability": float(result.reliability),
        "cost": float(result.resources.get("cost", result.cost)),
        "resources": {r: float(result.resources.get(r, 0.0)) for r in resources},
        "blocks": out,
    }


def _cost_front(front: list) -> list:
    """The designs no other beats on cost and reliability alone (with weight or
    volume limits too, the library's front is non-dominated in every resource,
    so it also holds designs that only save weight): increasing cost, strictly
    increasing reliability."""
    out, best = [], -1.0
    for d in sorted(front, key=lambda d: (d["cost"], -d["reliability"])):
        if d["reliability"] > best + 1e-12:
            out.append(d)
            best = d["reliability"]
    if len(out) > FRONT_POINTS:
        step = (len(out) - 1) / (FRONT_POINTS - 1)
        out = [out[round(i * step)] for i in range(FRONT_POINTS)]
    return out


def _combinations(blocks: list[dict], mixing: bool) -> int:
    """How many designs the exhaustive trade-off search could examine: the
    product of each block's ways to be built (numbers of copies, their types
    and, for "best of the two", active or cold)."""
    total = 1
    for b in blocks:
        kinds, low, high = len(b["types"]), b["required"], b["max_copies"]
        if mixing:
            ways = sum(math.comb(c + kinds - 1, kinds - 1) for c in range(low, high + 1))
        else:
            ways = kinds * (high - low + 1)
        total *= ways * (2 if b["strategy"] == "choose" else 1)
    return total


def _sampled_front(rbd, costs, blocks, limits, reach, options) -> tuple[list, int]:
    """The best design at evenly spaced spending levels up to ``reach``: the
    exact search for one budget prunes hard, where listing every design of a
    large non-series problem would not. Stops after a few seconds, so the curve
    may end before ``reach``."""
    least = math.fsum(
        b["required"] * min(ty["amounts"]["cost"] for ty in b["types"]) for b in blocks
    )
    # Cheapest first: a bigger budget leaves the search more to examine, so
    # stopping early keeps the quick lower part of the curve.
    found, levels, started = [], 0, time.monotonic()
    for level in np.linspace(least, reach, FRONT_LEVELS):
        if time.monotonic() - started > FRONT_SECONDS:
            break
        try:
            found.append(rbd.allocate_redundancy(costs, budget={**limits, "cost": float(level)}, **options))
            levels += 1
        except ValueError:
            continue  # nothing fits this level (e.g. a weight limit)
    return found, levels


def design_redundancy(
    graph: dict,
    t,
    blocks,
    budget: Optional[dict] = None,
    target=None,
    mixing: bool = True,
    resolve_model: Optional[Callable] = None,
    resolve_subsystem: Optional[Callable] = None,
) -> dict:
    """The best redundancy design for a diagram, and the cost–reliability
    trade-off around it.

    ``blocks`` is a list of ``{id, cost, weight?, volume?, max_copies,
    required?, strategy?, switching?, name?, types?}`` — ``types`` being
    alternative component types ``{name, model, cost, weight?, volume?}`` next
    to the block's own model. Give a ``budget`` (``{cost?, weight?, volume?}``)
    to maximise reliability within it, or a ``target`` reliability to find the
    cheapest design reaching it (within the budget's limits, if any).
    """
    t = _number(t, "The mission time", strict=True)
    parsed = _parse_blocks(graph, blocks)
    budget = {r: v for r, v in (budget or {}).items() if v not in (None, "")}
    unknown = [r for r in budget if r not in RESOURCES]
    if unknown:
        raise DesignError(f"The budget can limit {', '.join(RESOURCES)}; got {', '.join(unknown)}.")
    limits = {r: _number(v, f"The {r} budget", strict=True) for r, v in budget.items()}
    if target not in (None, ""):
        target = _number(target, "The target reliability", strict=True)
        if target >= 1.0:
            raise DesignError("The target reliability must be below 1 (e.g. 0.99).")
    else:
        target = None
        if not limits:
            raise DesignError("Give a budget, or a target reliability to reach.")

    # The resources in play: cost, plus weight / volume if any copy uses them
    # or the budget limits them. A copy that doesn't state one uses none.
    resources = ["cost"] + [
        r for r in RESOURCES[1:]
        if r in limits or any(r in ty["amounts"] for b in parsed for ty in b["types"])
    ]
    for b in parsed:
        for ty in b["types"]:
            ty["amounts"] = {r: ty["amounts"].get(r, 0.0) for r in resources}

    ids = {b["id"] for b in parsed}
    # The diagram's common-cause groups come with it: every candidate design
    # is scored with them, a grouped block's copies joining its group.
    rbd, labels, reliabilities = _build(_stripped(graph, ids), resolve_model, resolve_subsystem)
    for b in parsed:
        b["models"] = [reliabilities[b["id"]]] + [
            _type_model(b, ty, resolve_model) for ty in b["types"][1:]
        ]
    costs = {}
    for b in parsed:
        if len(b["types"]) == 1:
            costs[b["id"]] = dict(b["types"][0]["amounts"])
        else:
            costs[b["id"]] = [
                ComponentOption(i, model, dict(ty["amounts"]))
                for i, (ty, model) in enumerate(zip(b["types"], b["models"]))
            ]
    options = dict(
        t=t,
        max_units={b["id"]: b["max_copies"] for b in parsed},
        required={b["id"]: b["required"] for b in parsed},
        strategy={b["id"]: b["strategy"] for b in parsed},
        switching_probability={b["id"]: b["switching"] for b in parsed if b["strategy"] != "active"},
        mixing=bool(mixing),
    )
    # Designed blocks in series with the rest (each alone a cut set) are solved
    # by a dynamic program at any size; otherwise the exact search is
    # exhaustive (with pruning), so a very large problem gets the library's
    # fast greedy search instead — as does one where the exact search gives
    # up. The exact methods list the minimal cut sets, so a diagram with too
    # many to list (see rbd_analysis) is searched greedily too.
    n_cuts = rbd_analysis._set_counts(rbd)[1]
    listable = n_cuts is not None and n_cuts <= rbd_analysis._MAX_ENUMERATED_SETS
    singles = {node for cut in rbd_analysis._low_order_cut_sets(rbd, 1) for node in cut}
    in_series = all(b["id"] in singles for b in parsed)
    combinations = _combinations(parsed, mixing)
    exact = listable and (in_series or combinations <= EXACT_COMBINATIONS)
    method = "exact" if exact else "greedy"
    try:
        try:
            best = rbd.allocate_redundancy(
                costs, budget=limits or None, target=target, method=method, **options
            )
        except ValueError as exc:
            if method != "exact" or "exact search" not in str(exc):
                raise
            method = "greedy"
            best = rbd.allocate_redundancy(
                costs, budget=limits or None, target=target, method=method, **options
            )
    except (ValueError, NotImplementedError) as exc:
        raise DesignError(_friendly(str(exc), parsed)) from None

    # The trade-off around the answer, within any weight / volume limit and
    # the most copies — and up to twice what the answer, the budget or the
    # diagram as drawn costs, so the chart shows what more money would buy.
    current_use = {
        r: math.fsum(b["types"][0]["amounts"][r] * b["current"] for b in parsed) for r in resources
    }
    reach = 2.0 * max(float(best.resources["cost"]), limits.get("cost", 0.0), current_use["cost"])
    front, front_note = [], None
    try:
        if listable and (in_series or combinations <= FRONT_SEARCH_LIMIT):
            found = rbd.redundancy_front(costs, budget={**limits, "cost": reach}, **options)
        else:
            found, levels = _sampled_front(
                rbd, costs, parsed, limits, reach, {**options, "method": method}
            )
            found.append(best)
            front_note = (
                f"Too many combinations to list every design: the curve joins the best "
                f"designs at {levels} spending levels."
            )
        front = _cost_front([_design_payload(d, parsed, resources) for d in found])
    except (ValueError, NotImplementedError):
        front_note = "The trade-off curve is too large to compute for this many blocks and copies."

    # The diagram as drawn, for comparison.
    as_drawn, _, _ = _build(_stripped(graph, set()), resolve_model, resolve_subsystem)
    return {
        "t": t,
        "unit": graph.get("unit") or "",
        "mode": "target" if target is not None else "budget",
        "target": target,
        "budget": limits,
        "resources": resources,
        "current": {
            "reliability": _reliability_at(as_drawn, t),
            "cost": current_use["cost"],
            "resources": current_use,
        },
        "design": _design_payload(best, parsed, resources),
        "method": best.method,
        "front": front,
        "front_note": front_note,
        "common_cause": _common_cause(graph, rbd, labels, reliabilities, ids),
    }


def _common_cause(graph: dict, rbd, labels: dict, reliabilities: dict, designed: set) -> list[dict]:
    """The common-cause groups the designs were scored with (those the
    analysis takes in: at least two members and 0 < beta < 1), each with its
    members' labels and which of them are being designed."""
    taken = [frozenset(g.members) for g in getattr(rbd, "ccf_groups", None) or []]
    out = []
    for i, g in enumerate(graph.get("ccf_groups") or []):
        if not isinstance(g, dict):
            continue
        # As rbd_analysis._ccf_groups reads them (a repeated block is no member).
        members = [m for m in dict.fromkeys(g.get("members") or []) if m in reliabilities
                   and not isinstance(reliabilities[m], str)]
        if frozenset(members) not in taken:
            continue
        out.append({
            "id": g.get("id") or f"group-{i + 1}",
            "beta": float(g.get("beta")),
            "members": [labels[m] for m in members],
            "designed": [labels[m] for m in members if m in designed],
        })
    return out


# ---------------------------------------------------------------------------
# Writing a design back onto the diagram
# ---------------------------------------------------------------------------
def _edge(source: str, target: str) -> dict:
    return {
        "id": f"e-{source}-{target}",
        "source": source,
        "target": target,
        "type": "smoothstep",
        "markerEnd": dict(_ARROW),
    }


def _units(block: dict, chosen: dict) -> list[int]:
    """The type of each copy, in type order (the order cold spares switch in)."""
    counts: dict[int, int] = {}
    for m in chosen.get("mix") or []:
        try:
            i, n = int(m.get("type")), int(m.get("copies"))
        except (TypeError, ValueError, AttributeError):
            raise DesignError(f"“{block['label']}”: the design's component types are malformed.") from None
        if not 0 <= i < len(block["types"]) or n < 0:
            raise DesignError(f"“{block['label']}”: the design names a component type that isn't set up.")
        counts[i] = counts.get(i, 0) + n
    units = [i for i in sorted(counts) for _ in range(counts[i])]
    if not units:
        raise DesignError(f"“{block['label']}”: the design gives it no copies.")
    if len(units) > block["max_copies"]:
        raise DesignError(f"“{block['label']}”: the design has more copies than allowed.")
    if len(units) < block["required"]:
        raise DesignError(f"“{block['label']}”: the design has fewer copies than must work.")
    return units


def _replacement(
    block: dict, chosen: dict, *, joins: bool = False
) -> tuple[list[dict], list[tuple[str, str]], list[str], list[str], bool]:
    """The builder nodes for one designed block.

    Returns ``(nodes, inner_edges, entry, exit, adds_column)``: every node in
    ``entry`` takes the block's incoming edges, every node in ``exit`` its
    outgoing ones, and ``adds_column`` says a voting node was added after it.

    A block in a common-cause group has each active copy drawn as its own
    component, so each can join the group. ``joins`` says the block feeds a
    voting node needing more than one input, which would count side-by-side
    copies as separate inputs: they are then gathered at a junction (a
    1-out-of-n voting node) first.
    """
    node, label, bid = block["node"], block["label"], block["id"]
    units = _units(block, chosen)
    strategy = chosen.get("strategy") or "active"
    k = block["required"]
    base = {key: v for key, v in node.items() if key not in ("type", "data", "selected", "width", "height", "positionAbsolute", "dragging")}
    pos = node.get("position") or {"x": 0, "y": 0}
    data = {key: v for key, v in (node.get("data") or {}).items() if key not in ("n", "k", "kind", "state", "model")}

    def model(i):
        return copy.deepcopy(block["types"][i]["model"])

    def named(i):
        # The label says which type a copy is when it isn't the one as drawn.
        return label if i == 0 else f"{label} ({block['types'][i]['name']})"

    def component(nid, i, y):
        return {**base, "id": nid, "type": "component", **_HORIZONTAL,
                "position": {"x": pos.get("x", 0), "y": y},
                "data": {**data, "label": named(i), "model": model(i)}}

    def group(nid, i, n, y):
        # n identical active copies: one component, or a parallel block.
        if n == 1:
            return component(nid, i, y)
        return {**base, "id": nid, "type": "parallel", **_HORIZONTAL,
                "position": {"x": pos.get("x", 0), "y": y},
                "data": {**data, "kind": "parallel", "label": named(i), "n": n, "model": model(i)}}

    def stacked(count):
        y0 = pos.get("y", 0)
        return [y0 + (j - (count - 1) / 2) * _COPY_GAP for j in range(count)]

    if len(units) == 1:
        return [component(bid, units[0], pos.get("y", 0))], [], [bid], [bid], False

    if strategy == "cold":
        primary, spares = units[0], units[1:]
        if len(set(spares)) > 1:
            raise DesignError(
                f"“{label}”: this design's cold spares mix types, which one standby "
                "block can't draw. Untick “Mix types within a block” and design again."
            )
        out = {**base, "id": bid, "type": "standby", **_HORIZONTAL, "position": dict(pos),
               "data": {**data, "kind": "standby", "label": named(primary), "model": model(primary),
                        "spares": len(spares), "cold": True, "dormancy": 0,
                        "startProb": block["switching"],
                        "standbyModel": model(spares[0]) if spares[0] != primary else None}}
        return [out], [], [bid], [bid], False

    def voted(copies, need):
        # Every copy on its own branch into a voting node needing ``need`` (a
        # junction when one will do, as rbd_costs.apply_copies draws it).
        vote_id = f"{bid}v" if need > 1 else f"{bid}j"
        vote = {"id": vote_id, "type": "knode",
                "position": {"x": pos.get("x", 0) + _COL_GAP, "y": pos.get("y", 0)},
                "data": {"label": f"{need}-out-of-{len(copies)}" if need > 1 else "Junction",
                         "n": need, "k": len(copies)}}
        inner = [(c["id"], vote_id) for c in copies]
        return copies + [vote], inner, [c["id"] for c in copies], [vote_id], True

    if k == 1:
        if block.get("group") is not None:
            # Each copy its own component, so each can join the group.
            ys = stacked(len(units))
            nodes = [component(bid if j == 0 else f"{bid}x{j}", i, ys[j]) for j, i in enumerate(units)]
        else:
            kinds = sorted(set(units))
            ys = stacked(len(kinds))
            nodes = [
                group(bid if j == 0 else f"{bid}x{j}", i, units.count(i), ys[j])
                for j, i in enumerate(kinds)
            ]
        if len(nodes) > 1 and joins:
            return voted(nodes, 1)
        ids = [n["id"] for n in nodes]
        return nodes, [], ids, ids, False

    # k-out-of-n: every copy on its own branch into a voting node.
    ys = stacked(len(units))
    return voted([component(bid if j == 0 else f"{bid}x{j}", i, ys[j]) for j, i in enumerate(units)], k)


def apply_design(graph: dict, blocks, design_blocks) -> dict:
    """The diagram with a design drawn on it, as the builder stores graphs
    (see :func:`apply_design_with_notes`)."""
    return apply_design_with_notes(graph, blocks, design_blocks)[0]


def apply_design_with_notes(graph: dict, blocks, design_blocks) -> tuple[dict, list[str]]:
    """The diagram with a design drawn on it, as the builder stores graphs,
    and notes on what happened to its common-cause groups.

    ``blocks`` is the same list :func:`design_redundancy` was given (it holds
    the component types' models); ``design_blocks`` is the ``blocks`` list of
    one design it returned. A block with one copy stays a component (of the
    chosen type); active copies become a ``parallel`` block (one per type when
    types are mixed, all wired between the same neighbours, or gathered at a
    junction, a 1-out-of-n voting node, when they feed a vote needing more
    than one input); k-out-of-n copies each get a branch into a voting node;
    cold spares become a cold ``standby`` block. A common-cause group member's copies are each drawn as a component
    and join its group (same beta), as the allocation scored them; a group
    left with fewer than two members is removed. Nothing is saved.
    """
    parsed = {b["id"]: b for b in _parse_blocks(graph, blocks)}
    if not isinstance(design_blocks, list) or not design_blocks:
        raise DesignError("The design has no blocks.")
    out = copy.deepcopy(graph)
    nodes = list(out.get("nodes") or [])
    edges = list(out.get("edges") or [])
    taken = {n.get("id") for n in nodes}
    groups = out.get("ccf_groups") or []
    notes: list[str] = []
    # Right to left, so a voting node's new column shifts only what follows.
    chosen = [d for d in design_blocks if isinstance(d, dict)]
    for d in chosen:
        if d.get("id") not in parsed:
            raise DesignError(f"Block '{d.get('id')}' wasn't part of the design request.")
    chosen.sort(key=lambda d: -((parsed[d["id"]]["node"].get("position") or {}).get("x", 0)))
    for d in chosen:
        block = parsed[d["id"]]
        index = next(i for i, n in enumerate(nodes) if n.get("id") == block["id"])
        # The block as it now stands (an earlier shift may have moved it).
        block = {**block, "node": nodes[index]}
        # Copies side by side into a vote needing more than one input would
        # each count as an input: they join at a junction first.
        by_id = {n.get("id"): n for n in nodes}
        joins = any(
            (by_id.get(e.get("target")) or {}).get("type") == "knode"
            and _required_of(by_id[e.get("target")]) > 1
            for e in edges if e.get("source") == block["id"]
        )
        new_nodes, inner, entry, exit_, adds_column = _replacement(block, d, joins=joins)
        for n in new_nodes:
            if n["id"] != block["id"] and n["id"] in taken:
                raise DesignError(f"“{block['label']}”: block id '{n['id']}' is already in use.")
        x0 = (block["node"].get("position") or {}).get("x", 0)
        if adds_column:
            for n in nodes:
                p = n.get("position")
                if p and n.get("id") != block["id"] and p.get("x", 0) > x0 + 1:
                    n["position"] = {**p, "x": p.get("x", 0) + _COL_GAP}
        nodes[index:index + 1] = new_nodes
        taken.update(n["id"] for n in new_nodes)
        incoming = [e for e in edges if e.get("target") == block["id"]]
        outgoing = [e for e in edges if e.get("source") == block["id"]]
        edges = [e for e in edges if block["id"] not in (e.get("source"), e.get("target"))]
        for e in incoming:
            edges += [_edge(e["source"], nid) for nid in entry]
        for e in outgoing:
            edges += [_edge(nid, e["target"]) for nid in exit_]
        edges += [_edge(s, t) for s, t in inner]
        if block["group"] is not None:
            # The copies join the member's group, as the allocation scored them.
            group = groups[block["group"]]
            copies = [n["id"] for n in new_nodes if n["type"] == "component" and n["id"] != block["id"]]
            if copies:
                group["members"] = list(dict.fromkeys([*(group.get("members") or []), *copies]))
                notes.append(
                    f"“{block['label']}”: {len(copies)} added cop{'y' if len(copies) == 1 else 'ies'} "
                    f"joined its common-cause group (β = {_beta_text(group)}).")
    # A designed member no longer drawn as a component (or not drawn at all)
    # leaves its group; a group that leaves with fewer than two members is no
    # group, and is removed. Groups the design didn't touch stay as they are.
    after = {n.get("id"): n.get("type") for n in nodes}
    gone = {bid for bid in parsed if after.get(bid) != "component"}
    if gone and groups:
        labels = {n.get("id"): (n.get("data") or {}).get("label") or n.get("id") for n in graph.get("nodes") or []}
        out["ccf_groups"], dropped = _prune_groups(groups, gone, labels)
        notes += dropped
    out["nodes"] = nodes
    out["edges"] = edges
    return out, notes


def _required_of(vote: dict) -> int:
    """How many working inputs a voting node needs (its ``n``)."""
    try:
        return int((vote.get("data") or {}).get("n") or 1)
    except (TypeError, ValueError):
        return 1


def _prune_groups(groups: list, gone: set, labels: dict) -> tuple[list, list[str]]:
    """The common-cause groups without the members in ``gone``, and a note for
    each group that drops below two members and is removed."""
    kept, notes = [], []
    for g in groups:
        before = list(g.get("members") or []) if isinstance(g, dict) else []
        members = [m for m in before if m not in gone]
        if members == before:
            kept.append(g)
            continue
        if len(set(members)) < 2:
            names = ", ".join(str(labels.get(m, m)) for m in dict.fromkeys(before))
            notes.append(
                f"The common-cause group of {names} (β = {_beta_text(g)}) was left with "
                "fewer than two members, so it was removed.")
            continue
        kept.append({**g, "members": members})
    return kept, notes


def applied_reliability(graph: dict, t, resolve_model=None, resolve_subsystem=None) -> float:
    """R(t) of a diagram as drawn (what-if pins ignored), to check an applied
    design against the reliability the allocation reported."""
    t = _number(t, "The mission time", strict=True)
    rbd, _, _ = _build(_stripped(graph, set()), resolve_model, resolve_subsystem)
    return _reliability_at(rbd, t)
