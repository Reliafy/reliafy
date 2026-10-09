"""Cost of ownership of a repairable RBD (#99), on RePyability 0.9.

* :func:`cost_summary` — the costs part of an availability result: the
  long-run cost rate and its breakdown (per category and per block: repairs,
  replacements, preventive maintenance, proof tests, the block's own downtime,
  and the system's lost production), the total cost of ownership over a
  horizon (purchase + running), and the simulated cost of the window with its
  spread, from the same simulation as the availability. Exact figures come from
  ``RepairableRBD.expected_cost_rate`` where RePyability has them (not for
  limited repair crews for wear-out lives); otherwise the simulated rate stands in, and every
  figure says which it is (``basis``).
* :func:`cheapest_design` — ``RepairableRBD.allocate_redundancy``: how many
  active copies of each priced block give the lowest total cost of ownership
  over a horizon, optionally with an availability floor, and the diagram with
  those copies drawn on it (nothing is saved; the builder puts it on the
  canvas). Since RePyability 0.12 (#227) whole *trains* — chains of blocks in
  series, such as a pump with its valve and motor — can be copied too: a copy
  of a train is another path alongside it into the node it feeds, joining a
  vote there (2-out-of-3 becomes 2-out-of-4).

Costs are in whatever currency the user entered them. The total cost of
ownership (and the cheapest design's) is undiscounted unless the diagram (or
the request) gives a discount rate in % a year (#219, RePyability 0.12's
``discount_rate``): then it is the present value, the purchases at the start
and the running costs discounted continuously, the horizon counting as
``(1 - exp(-r H)) / r``. The window's cost (simulated or exact) is never
discounted.
"""

from __future__ import annotations

import copy
import math
from typing import Any, Optional

import numpy as np

from backend.services import rbd_analysis as ra
from backend.services import rbd_maintenance as rm
from backend.services.rbd_analysis import AnalysisError

#: Cost categories, in display order (RePyability's ``by_category`` keys).
CATEGORIES = ("repair", "replace", "preventive", "inspection", "setup", "component_downtime", "system_downtime")
#: Percentiles of the window's cost reported.
PERCENTILES = (10, 50, 90)
#: The most copies of one block the cheapest-design search considers.
MAX_COPIES = 6
#: The most blocks and trains it designs at once (branch and bound suits a handful).
MAX_BLOCKS = 12
#: The most trains, and the most blocks in one train (#227).
MAX_TRAINS = 6
MAX_TRAIN_BLOCKS = 20
_COPY_GAP = 110
_COL_GAP = 280
_ARROW = {"type": "arrowclosed", "width": 18, "height": 18}


def _mean_cost(cost) -> float:
    """A block's cost as RePyability prices it on average: the number, or
    the mean of a cost range (surpyval's ``Uniform``)."""
    if isinstance(cost, (int, float, np.number)):
        return float(cost)
    return float(np.ravel(cost.mean())[0])


def _scalar(v) -> float:
    return float(np.atleast_1d(np.asarray(v, dtype=float))[0])


def exact_breakdown(rbd, overrides: dict) -> dict:
    """The exact long-run cost rate, by category and by block.

    ``expected_cost_rate`` gives the total; the split is its own terms
    (RePyability's ``_node_cost_rate``): failures × (repair + replacement),
    preventive replacements × their cost, one test per interval, the block's
    unavailability × its downtime rate, and the system's unavailability × the
    lost-production rate. Raises ``NotImplementedError`` where RePyability
    has no exact long-run values."""
    working = set(overrides.get("working_nodes") or ())
    broken = set(overrides.get("broken_nodes") or ())
    forced = working | broken
    setups = {g: group for g, group in getattr(rbd, "_maintenance", {}).items() if group.setup_cost}
    with np.errstate(all="ignore"):
        total = float(rbd.expected_cost_rate(**overrides))
        availability = {}
        if rbd.costs or setups:
            if rbd._crews_couple():
                # Limited repair crews (#156): the components' long-run values
                # come from the crews' Markov chain, as in expected_cost_rate.
                probabilities, weights = rbd._chain_probabilities(working, broken)
                availability = {n: float(weights @ probabilities[n]) for n in rbd.nodes}
            else:
                probs = rbd._probabilities_with_overrides(rbd.node_availability(), working, broken)
                availability = {n: _scalar(v) for n, v in probs.items()}
        system_down = 0.0
        if rbd.downtime_cost_rate:
            system_down = rbd.downtime_cost_rate * float(rbd.mean_unavailability(**overrides))
    blank = {k: 0.0 for k in CATEGORIES if k != "system_downtime"}
    by_block: dict[Any, dict] = {}
    for node, costs in rbd.costs.items():
        row = dict(blank)
        if node not in forced:
            # Corrective and preventive actions per unit time (a standby
            # group's units' failures, or from the crews' chain).
            failures, maintained = rbd._node_actions(node, availability[node])
            for key in ("repair", "replace"):
                if f"{key}_cost" in costs:
                    row[key] = _mean_cost(costs[f"{key}_cost"]) * failures
            if "preventive_cost" in costs:
                row["preventive"] = _mean_cost(costs["preventive_cost"]) * maintained
            if "inspection_cost" in costs:
                schedule = rbd._preventive.get(node)
                if schedule is not None and schedule.policy == "condition":
                    # Condition checks (#96) at each multiple of the interval it is up at.
                    row["inspection"] = (_mean_cost(costs["inspection_cost"])
                                         * rbd._block_cycle(node).before / schedule.interval)
                else:
                    row["inspection"] = _mean_cost(costs["inspection_cost"]) / rbd._inspection[node].interval
        if costs.get("downtime_cost"):
            row["component_downtime"] = costs["downtime_cost"] * (1.0 - availability[node])
        by_block[node] = row
    # A maintenance group's set-up (#108), at each failure and each preventive
    # replacement of a member, put on the member that opened the stop.
    for group in setups.values():
        for node in group.members:
            if node in forced:
                continue
            row = by_block.setdefault(node, dict(blank))
            row["setup"] += group.setup_cost * sum(rbd._node_actions(node, availability[node]))
    by_category = {k: math.fsum(r[k] for r in by_block.values()) for k in CATEGORIES if k != "system_downtime"}
    by_category["system_downtime"] = system_down
    return {"total": total, "by_category": by_category, "by_block": by_block}


def _window_mean(rbd, graph: dict, t_sim: float, overrides: dict,
                 state: Optional[dict]) -> tuple[Optional[float], str]:
    """``(value, basis)``: the window's expected cost from RePyability's
    ``expected_cost`` (from the same start as the simulation) when its route
    is exact or numerical, its basis that route; otherwise
    ``(None, "simulation")``. As the window's availability
    (``rbd_analysis._window_exact``), not above
    ``EXACT_WINDOW_MEAN_MAX_BLOCKS`` blocks."""
    if not ra.window_mean_exact_ok(graph):
        return None, "simulation"
    route = ra.window_routes(rbd)["expected_cost"]
    if route not in ra._OVER_TIME_OK:
        return None, "simulation"
    state_kw = {"state": state} if state else {}
    try:
        with np.errstate(all="ignore"):
            value = ra._f(rbd.expected_cost(float(t_sim), **overrides, **state_kw).mean)
    except Exception:  # noqa: BLE001 - the simulated mean stands
        return None, "simulation"
    return (value, route) if value is not None else (None, "simulation")


def _simulated(cost, exact_mean: Optional[float] = None, mean_basis: str = "simulation") -> Optional[dict]:
    """The window's simulated cost (a ``CostResult``) as plain numbers. Its
    ``mean`` is ``exact_mean`` where RePyability works it out
    (``mean_basis`` exact or numerical), the simulated one otherwise; the
    interval and percentiles are the simulation's."""
    if cost is None or not len(cost.samples):
        return None
    out: dict[str, Any] = {
        "mean": exact_mean if exact_mean is not None else ra._f(cost.mean),
        "mean_basis": mean_basis if exact_mean is not None else "simulation",
        "simulated_mean": ra._f(cost.sample_mean),
        "std": ra._f(cost.std) if len(cost.samples) > 1 else None,
        "cost_rate": ra._f(cost.cost_rate),
        "t_simulation": ra._f(cost.t_simulation),
        "n_simulations": int(cost.n_simulations),
        "percentiles": {str(q): ra._f(cost.percentile(q)) for q in PERCENTILES},
        "by_category": {k: ra._f(v) for k, v in (cost.by_category or {}).items()},
        "by_block": {str(k): ra._f(v) for k, v in (cost.by_component or {}).items()},
        "antithetic": bool(getattr(cost, "antithetic", False)),
    }
    try:
        ci = cost.mean_interval(ra._AVAIL_CONFIDENCE)
        out.update(lower=ra._f(ci.lower), upper=ra._f(ci.upper),
                   standard_error=ra._f(ci.standard_error), confidence=ra._AVAIL_CONFIDENCE)
    except Exception:  # noqa: BLE001 - fewer than two samples
        pass
    return out


def cost_summary(rbd, graph: dict, labels: dict, gate_ids: set, overrides: dict,
                 res, t_sim: float, per_node: list, importance: dict,
                 state: Optional[dict] = None) -> Optional[dict]:
    """The costs part of an availability result, or None when nothing is
    priced (no running cost and no purchase price). ``state`` is the
    simulation's start (RePyability ``NodeState``s), for the window's exact
    expected cost."""
    acquisition = float(rbd.acquisition_cost)
    if not rbd.has_costs and not acquisition:
        return None
    exact = None
    if rbd.has_costs:
        try:
            exact = exact_breakdown(rbd, overrides)
        except NotImplementedError:
            exact = None
    simulated = None
    if res is not None and getattr(res, "cost", None) is not None:
        exact_mean, mean_basis = (_window_mean(rbd, graph, t_sim, overrides, state)
                                  if rbd.has_costs else (None, "simulation"))
        simulated = _simulated(res.cost, exact_mean, mean_basis)
    if exact is not None:
        rate, basis = exact["total"], "exact"
    elif simulated is not None:
        rate, basis = simulated["cost_rate"], "simulation"
    elif not rbd.has_costs:
        rate, basis = 0.0, "exact"
    else:
        rate, basis = None, None

    # Each priced block: its running cost (exact per category, else the
    # simulated mean per unit time) next to its share of the downtime.
    share_sim = {r["id"]: r.get("share") for r in per_node or []}
    blocks = []
    priced = set(rbd.costs) | set(rbd.acquisition_costs) | {
        m for g in getattr(rbd, "_maintenance", {}).values() if g.setup_cost for m in g.members}
    for nid in rbd.components:
        if nid in gate_ids or nid not in priced:
            continue
        row: dict[str, Any] = {"id": str(nid), "label": labels.get(nid, str(nid)),
                               "acquisition": rbd.acquisition_costs.get(nid, 0.0)}
        if exact is not None:
            parts = exact["by_block"].get(nid) or {}
            row["categories"] = {k: ra._f(v) for k, v in parts.items()}
            row["rate"] = ra._f(math.fsum(parts.values()))
        elif simulated is not None and t_sim:
            row["rate"] = ra._f((simulated["by_block"].get(str(nid)) or 0.0) / t_sim)
        else:
            row["rate"] = None
        crit = (importance.get(str(nid)) or {}).get("unavailability_criticality")
        row["downtime_share"] = crit if crit is not None else share_sim.get(str(nid))
        row["downtime_share_basis"] = "exact" if crit is not None else "simulation"
        blocks.append(row)
    running = math.fsum(r["rate"] or 0.0 for r in blocks)
    for r in blocks:
        r["cost_share"] = (r["rate"] / running) if running > 0 and r["rate"] is not None else None
    blocks.sort(key=lambda r: (-(r["rate"] or 0.0), r["label"]))

    diagram = rm.diagram_costs(graph)
    horizon = diagram["horizon"] or float(t_sim)
    if exact is not None:
        by_category = {k: ra._f(v) for k, v in exact["by_category"].items()}
    elif simulated is not None and t_sim:
        by_category = {k: ra._f((v or 0.0) / t_sim) for k, v in simulated["by_category"].items()}
    else:
        by_category = None
    return {
        "priced": bool(rbd.has_costs),
        "downtime_cost_rate": float(rbd.downtime_cost_rate),
        "cost_rate": ra._f(rate) if rate is not None else None,
        "cost_rate_basis": basis,
        "by_category": by_category,
        "blocks": blocks,
        "acquisition_cost": acquisition,
        "horizon": horizon,
        "horizon_basis": "set" if diagram["horizon"] else "window",
        **present_value(acquisition, rate, horizon, rm.discount(graph)),
        "simulated": simulated,
    }


def present_value(acquisition: float, rate: Optional[float], horizon: float,
                  disc: Optional[dict]) -> dict:
    """The total cost of owning the system for ``horizon``: the purchases plus
    the running ``rate`` over it, as ``RepairableRBD.total_cost`` gives it —
    with a discount (:func:`rbd_maintenance.discount`) its present value, the
    horizon counting as ``(1 - exp(-r H)) / r`` (#219). ``running_cost`` and
    ``total_cost`` (None without a rate), the discount (% a year, and the
    continuous rate per unit time RePyability takes; None undiscounted) and,
    discounted, the undiscounted total beside it."""
    r = disc["per_unit"] if disc else 0.0
    # What a unit cost rate over the horizon is worth now, as total_cost
    # counts it: the horizon itself undiscounted.
    present = float(horizon) if r == 0.0 else -math.expm1(-r * float(horizon)) / r
    has_rate = rate is not None
    return {
        "running_cost": ra._f(rate * present) if has_rate else None,
        "total_cost": ra._f(acquisition + rate * present) if has_rate else None,
        "discount_rate": disc["annual"] if disc else None,
        "discount_rate_per_unit": r if disc else None,
        "undiscounted_total_cost": ra._f(acquisition + rate * horizon) if (disc and has_rate) else None,
    }


def with_discount(costs: Optional[dict], graph: dict, annual) -> Optional[dict]:
    """An availability result's ``costs`` re-priced at ``annual`` % a year (0:
    undiscounted) — the same long-run rate, purchases and horizon, so a saved
    result needn't be run again for another rate (the MCP ``analyze_rbd``'s
    ``discount_rate``)."""
    if not costs or annual is None:
        return costs
    disc = rm.discount(graph, annual)
    return {**costs, **present_value(float(costs.get("acquisition_cost") or 0.0), costs.get("cost_rate"),
                                     float(costs["horizon"]), disc)}


# ---------------------------------------------------------------------------
# Cheapest design: the redundancy with the lowest total cost of ownership
# ---------------------------------------------------------------------------
def _as_drawn(graph: dict) -> dict:
    """The diagram as drawn: what-if pins are ignored (as the Design tab
    ignores them), since the allocation is about the design itself."""
    out = copy.deepcopy(graph)
    for n in out.get("nodes") or []:
        if isinstance(n.get("data"), dict):
            n["data"].pop("state", None)
    return out


def _friendly(message: str, labels: dict) -> str:
    for nid, label in labels.items():
        message = message.replace(repr(nid), f"“{label}”")
    return message


def _order_chain(members: list, edges: list) -> Optional[list]:
    """``members`` in the order a chain in series runs (each fed by the one
    before it), or None when they aren't one chain."""
    inside = set(members)
    succ: dict = {}
    pred: dict = {}
    for src, tgt in edges:
        if src in inside and tgt in inside:
            succ.setdefault(src, []).append(tgt)
            pred.setdefault(tgt, []).append(src)
    heads = [m for m in members if m not in pred]
    if len(heads) != 1:
        return None
    order = [heads[0]]
    while len(order) < len(members):
        nxt = succ.get(order[-1]) or []
        if len(nxt) != 1 or nxt[0] in order:
            return None
        order.append(nxt[0])
    return order


def normalise_trains(trains) -> list[dict]:
    """Trains as given — ``[{"name", "blocks": [ids]}]`` or ``{name: [ids]}``
    — as ``[{"name", "blocks"}]``, checked for shape. Empty: none."""
    if not trains:
        return []
    if isinstance(trains, dict):
        items = [{"name": k, "blocks": v} for k, v in trains.items()]
    elif isinstance(trains, (list, tuple)):
        items = list(trains)
    else:
        raise AnalysisError("Trains must be a list of {name, blocks}.")
    if len(items) > MAX_TRAINS:
        raise AnalysisError(f"The cheapest design copies up to {MAX_TRAINS} trains at once.")
    out, names = [], set()
    for i, t in enumerate(items, start=1):
        if not isinstance(t, dict):
            raise AnalysisError("Each train must be {name, blocks}.")
        name = str(t.get("name") or "").strip()[:80] or f"Train {i}"
        if name in names:
            raise AnalysisError(f"Two trains are named “{name}” — name them apart.")
        names.add(name)
        blocks = t.get("blocks")
        if isinstance(blocks, (str, bytes)) or not isinstance(blocks, (list, tuple)) or not blocks:
            raise AnalysisError(f"Train “{name}” needs at least one block.")
        if len(blocks) > MAX_TRAIN_BLOCKS:
            raise AnalysisError(f"Train “{name}” has more than {MAX_TRAIN_BLOCKS} blocks.")
        out.append({"name": name, "blocks": list(dict.fromkeys(str(b) for b in blocks))})
    return out


def _checked_trains(trains: list[dict], graph: dict, rbd, labels: dict, gate_ids: set) -> list[dict]:
    """Each train's blocks in chain order, under an internal key (a train is
    named apart from the nodes in RePyability's ``units``): ``[{"key",
    "name", "blocks"}]``. Raises :class:`AnalysisError` in the user's words
    for a block that isn't a component or a set that isn't one chain
    (RePyability checks the rest: the chain's last block feeds one node)."""
    edges = [(e.get("source"), e.get("target")) for e in graph.get("edges") or []]
    taken = {str(n) for n in rbd.G.nodes}
    seen: dict = {}
    out = []
    for i, t in enumerate(trains, start=1):
        name = t["name"]
        for b in t["blocks"]:
            if b not in rbd.components or b in gate_ids:
                raise AnalysisError(f"Train “{name}”: “{labels.get(b, b)}” isn't a component block of this diagram.")
            if b in seen:
                raise AnalysisError(f"“{labels.get(b, b)}” is in trains “{seen[b]}” and “{name}” — "
                                    "a block is in one train at most.")
            seen[b] = name
        order = _order_chain(t["blocks"], edges)
        if order is None:
            raise AnalysisError(
                f"Train “{name}” must be a chain of blocks in series, each feeding the next alone — "
                f"{', '.join(labels.get(b, b) for b in t['blocks'])} aren't one.")
        key = f"train:{i}"
        while key in taken:
            key += "'"
        taken.add(key)
        out.append({"key": key, "name": name, "blocks": order})
    return out


def cheapest_design(graph: dict, resolve_model=None, horizon=None, min_availability=None,
                    blocks: Optional[list] = None, discount_rate=None, trains=None) -> dict:
    """The number of active copies of each priced block (every block with a
    purchase price, or ``blocks``) that owns the diagram for ``horizon`` at the
    lowest total cost (``RepairableRBD.allocate_redundancy``), optionally only
    among designs at least ``min_availability`` available; with the design as
    drawn for comparison, and the diagram with the copies drawn on it.
    ``discount_rate`` (% a year; default the diagram's, 0 undiscounted) makes
    the totals present values, and chooses the design with the lowest (#219).

    ``trains`` (#227, ``[{"name", "blocks"}]`` or ``{name: [block ids]}``)
    are chains of blocks in series that may be copied whole: each copy
    another path alongside the train, fed as its first block is and feeding
    the node its last feeds (a vote there keeps the number it needs, so a
    fourth train of a 2-out-of-3 makes it 2-out-of-4). With trains, the
    blocks copied one at a time default to the priced blocks outside them
    (``blocks=[]``: none)."""
    ra.require_blocks(graph)
    if not (graph or {}).get("repairable"):
        raise AnalysisError("The cheapest design is for repairable (availability) diagrams.")
    diagram = rm.diagram_costs(graph)
    horizon = rm._number(horizon, "ownership horizon", "Diagram", positive=True) or diagram["horizon"]
    if not horizon:
        raise AnalysisError("Set how long the system is owned (the horizon) to price it over.")
    disc = rm.discount(graph, discount_rate)
    r = disc["per_unit"] if disc else 0.0
    floor = None
    if not rm._blank(min_availability):
        try:
            floor = float(min_availability)
        except (TypeError, ValueError):
            floor = float("nan")
        if not 0.0 < floor < 1.0:
            raise AnalysisError("The minimum availability must be between 0% and 100%.")

    trains = normalise_trains(trains)
    drawn = _as_drawn(graph)
    rbd, labels, gate_ids, _, _ = ra._build_repairable_rbd(drawn, resolve_model)
    # Common-cause groups (#226): in the scoring wherever the availability
    # analysis has them; a grouped block's copies join its group.
    common_cause = ra.common_cause_summary(rbd, {}, drawn)
    trained = _checked_trains(trains, drawn, rbd, labels, gate_ids)
    in_trains = {b: t["name"] for t in trained for b in t["blocks"]}
    if blocks:
        chosen = [b for b in blocks if b in rbd.components and b not in gate_ids]
        both = [b for b in chosen if b in in_trains]
        if both:
            raise AnalysisError(
                f"“{labels.get(both[0], both[0])}” is in train “{in_trains[both[0]]}” and among the blocks "
                "copied on their own — copy it with its train or alone.")
    elif blocks is not None and trained:  # [] with trains: the trains alone
        chosen = []
    else:
        chosen = [n for n in rbd.components
                  if n in rbd.acquisition_costs and n not in gate_ids and n not in in_trains]
    for t in trained:
        if not any(rbd.acquisition_costs.get(b) for b in t["blocks"]):
            raise AnalysisError(
                f"Give a block of train “{t['name']}” a purchase price (in its Cost & maintenance "
                "section): the cheapest design weighs what a copy of the train costs against the "
                "downtime it saves.")
    if not chosen and not trained:
        raise AnalysisError(
            "Give at least one block a purchase price (in its Cost & maintenance section): "
            "the cheapest design weighs what a copy costs to buy and run against the "
            "downtime it saves."
        )
    if len(chosen) + len(trained) > MAX_BLOCKS:
        raise AnalysisError(
            f"The cheapest design handles up to {MAX_BLOCKS} priced blocks and trains at once — "
            f"this one has {len(chosen) + len(trained)}."
        )
    named = {**labels, **{t["key"]: t["name"] for t in trained}}
    if not rbd.downtime_cost_rate:
        note = ("The diagram has no system downtime cost, so extra copies only add cost — "
                "set the cost of an hour of downtime to weigh them.")
    else:
        note = None
    try:
        with np.errstate(all="ignore"):
            alloc = rbd.allocate_redundancy(
                horizon, nodes=chosen or None, min_availability=floor, max_units=MAX_COPIES, discount_rate=r,
                # Trains are copied whole (#227); without, every node copied alone.
                **({"trains": {t["key"]: t["blocks"] for t in trained}} if trained else {}),
            )
            current = {
                "total_cost": float(rbd.total_cost(horizon, discount_rate=r)),
                "cost_rate": float(rbd.expected_cost_rate()),
                "acquisition_cost": float(rbd.acquisition_cost),
                "availability": float(rbd.mean_availability()),
            }
    except NotImplementedError as exc:
        # Since RePyability 0.12 proof tests that take time have exact long-run
        # costs too (#159); limited repair crews for wear-out lives don't.
        reason = ra.plain_reason(_friendly(str(exc), named))
        if "a train holds a member" in str(exc) or "in a common-cause group, whose copies the allocation of trains" in str(exc):
            raise AnalysisError(
                f"{reason.split(', whose copies')[0]}: copies of a train can't yet join a "
                "common-cause group — take its members out of the train and copy them one at a time."
            ) from exc
        reason = reason.split(": estimate")[0].split(". Estimate")[0].split(". ")[0].rstrip(". ")
        raise AnalysisError(
            "The cheapest design needs exact long-run costs, which RePyability doesn't have "
            f"for this diagram: {reason}."
        ) from exc
    except ValueError as exc:
        msg = _friendly(str(exc), named)
        if "min_availability" in msg or "cannot be reached" in msg or "reach" in msg:
            raise AnalysisError(
                f"No design with up to {MAX_COPIES} copies of each priced block"
                f"{' and train' if trained else ''} reaches that availability — lower the minimum, "
                "or price more blocks."
            ) from exc
        if trained and "must end at a node feeding one node" in msg:
            raise AnalysisError(
                f"{msg.split(' must end')[0]} must end at a block feeding one node (a vote, a block or the "
                "output), which its copies join — its last block feeds more than one."
            ) from exc
        raise AnalysisError(f"Couldn't find the cheapest design: {msg}") from exc

    current["meets_floor"] = None if floor is None else current["availability"] >= floor
    units = {str(k): int(v) for k, v in alloc.units.items()}
    rows = [
        {"id": str(n), "label": labels.get(n, str(n)), "copies": units.get(str(n), 1),
         "price": rbd.acquisition_costs.get(n, 0.0)}
        for n in chosen
    ]
    # A train's copies are under its key in RePyability's units (#227).
    train_rows = [
        {"name": t["name"], "copies": units.pop(t["key"], 1),
         "blocks": [{"id": str(b), "label": labels.get(b, str(b))} for b in t["blocks"]],
         "price": float(sum(rbd.acquisition_costs.get(b, 0.0) for b in t["blocks"]))}
        for t in trained
    ]
    design = {
        "units": units,
        "blocks": rows,
        "trains": train_rows,
        "total_cost": float(alloc.total_cost),
        "cost_rate": float(alloc.cost_rate),
        "acquisition_cost": float(alloc.acquisition_cost),
        "availability": float(alloc.availability),
    }
    changed = any(v != 1 for v in units.values()) or any(t["copies"] != 1 for t in train_rows)
    return {
        "kind": "repairable_cost_design",
        "unit": (graph.get("unit") or "").strip(),
        "horizon": float(horizon),
        "min_availability": floor,
        # % a year, and the continuous rate per unit time RePyability took (None: undiscounted).
        "discount_rate": disc["annual"] if disc else None,
        "discount_rate_per_unit": r if disc else None,
        "method": alloc.method,
        "max_copies": MAX_COPIES,
        "current": current,
        "design": design,
        "saving": current["total_cost"] - design["total_cost"],
        "changed": changed,
        "note": note,
        "common_cause": _common_cause_out(common_cause),
        # Trains first, so a block's copies are wired to the trains' copies too.
        "graph": apply_copies(apply_train_copies(graph, train_rows), units) if changed else None,
        "repyability_version": ra._repyability_version(),
    }


def _common_cause_out(common: Optional[dict]) -> Optional[dict]:
    """The cheapest design's ``common_cause``: whether the designs were
    scored with the diagram's groups, and why not (#226)."""
    if common is None:
        return None
    out = {k: common.get(k) for k in ("groups", "included", "reason")}
    out["note"] = (
        f"Scored with the diagram's {common['groups']} common-cause group{'s' if common['groups'] != 1 else ''}: "
        "a grouped block's copies join its group, so a shared cause can take them out together."
        if common.get("included") else ra.common_cause_left_out(common["groups"], common.get("reason")))
    return out


def _edge(source: str, target: str) -> dict:
    return {"id": f"e-{source}-{target}", "source": source, "target": target,
            "type": "smoothstep", "markerEnd": dict(_ARROW)}


def _join_groups(out: dict, nid: str, copies: list[str]) -> None:
    """A common-cause group member's copies join its group (#226), as
    RePyability's ``allocate_redundancy`` scores them."""
    groups = out.get("ccf_groups")
    if not copies or not isinstance(groups, list):
        return
    out["ccf_groups"] = [
        {**g, "members": [*g["members"], *copies]}
        if isinstance(g, dict) and nid in (g.get("members") or []) else g
        for g in groups
    ]


def apply_copies(graph: dict, units: dict) -> dict:
    """The diagram with ``units[id]`` identical copies of each block, each
    wired between the block's own neighbours (active redundancy: any copy
    carries the path). Where a block feeds a k-out-of-n vote (k ≥ 2), whose
    count of incoming branches must not change, its copies join at a junction
    first. Copies keep the block's models, costs and maintenance (proof-tested
    copies are tested together, as the allocation assumes), and join its
    common-cause group (#226); pins are dropped. Nothing is saved."""
    out = copy.deepcopy(graph)
    nodes = list(out.get("nodes") or [])
    edges = list(out.get("edges") or [])
    by_id = {n.get("id"): n for n in nodes}
    taken = set(by_id)

    def fresh(base: str) -> str:
        i, nid = 1, base
        while nid in taken:
            i += 1
            nid = f"{base}{i}"
        taken.add(nid)
        return nid

    # Right to left, so a junction's new column shifts only what follows.
    order = sorted(
        (nid for nid, n in units.items() if int(n) > 1 and nid in by_id),
        key=lambda nid: -((by_id[nid].get("position") or {}).get("x", 0)),
    )
    for nid in order:
        n = int(units[nid])
        node = by_id[nid]
        data = node.get("data") or {}
        label = data.get("label") or nid
        pos = node.get("position") or {"x": 0, "y": 0}
        x0, y0 = pos.get("x", 0), pos.get("y", 0)
        ys = [y0 + (j - (n - 1) / 2) * _COPY_GAP for j in range(n)]
        node["position"] = {**pos, "y": ys[0]}
        node["data"] = {k: v for k, v in data.items() if k != "state"}
        copies = [node]
        for j in range(1, n):
            cid = fresh(f"{nid}x{j}")
            cdata = {k: copy.deepcopy(v) for k, v in data.items() if k not in ("state", "repeat_of")}
            cdata["label"] = f"{label} ({j + 1})"
            copies.append({
                **{k: v for k, v in node.items() if k not in ("id", "data", "position", "selected")},
                "id": cid, "position": {"x": x0, "y": ys[j]}, "data": cdata,
            })
        incoming = [e for e in edges if e.get("target") == nid]
        outgoing = [e for e in edges if e.get("source") == nid]
        voting = any(
            (by_id.get(e.get("target")) or {}).get("type") == "knode"
            and int(((by_id.get(e.get("target")) or {}).get("data") or {}).get("n") or 1) > 1
            for e in outgoing
        )
        new_edges = [_edge(e["source"], c["id"]) for e in incoming for c in copies[1:]]
        if voting:
            jid = fresh(f"{nid}j")
            for other in nodes:
                p = other.get("position")
                if p and other.get("id") != nid and p.get("x", 0) > x0 + 1:
                    other["position"] = {**p, "x": p.get("x", 0) + _COL_GAP}
            junction = {"id": jid, "type": "knode",
                        "position": {"x": x0 + _COL_GAP, "y": y0},
                        "data": {"label": "Junction", "n": 1, "k": n}}
            edges = [e for e in edges if e.get("source") != nid]
            new_edges += [_edge(c["id"], jid) for c in copies]
            new_edges += [_edge(jid, e["target"]) for e in outgoing]
            nodes.append(junction)
            by_id[jid] = junction
        else:
            new_edges += [_edge(c["id"], e["target"]) for e in outgoing for c in copies[1:]]
        index = nodes.index(node)
        nodes[index + 1:index + 1] = copies[1:]
        for c in copies[1:]:
            by_id[c["id"]] = c
        edges += new_edges
        _join_groups(out, nid, [c["id"] for c in copies[1:]])
    out["nodes"] = nodes
    out["edges"] = edges
    return out


def apply_train_copies(graph: dict, trains: list) -> dict:
    """The diagram with ``copies - 1`` more of each train (``[{"blocks":
    [{"id"} or id, ...], "copies"}]``, blocks in chain order) drawn below
    what is there: each copy fed by what feeds the train's first block and
    feeding the node its last block feeds, as RePyability scores it (#227).
    A vote there keeps the number it needs and gains the branches
    (2-out-of-3 becomes 2-out-of-4). Copies keep their blocks' models, costs
    and maintenance; pins are dropped. Nothing is saved."""
    out = copy.deepcopy(graph)
    nodes = list(out.get("nodes") or [])
    edges = list(out.get("edges") or [])
    by_id = {n.get("id"): n for n in nodes}
    taken = set(by_id)

    def fresh(base: str) -> str:
        i, nid = 1, base
        while nid in taken:
            i += 1
            nid = f"{base}{i}"
        taken.add(nid)
        return nid

    def pos(node) -> dict:
        return node.get("position") or {"x": 0, "y": 0}

    for train in trains:
        extra = int(train.get("copies") or 1) - 1
        ids = [b["id"] if isinstance(b, dict) else b for b in train.get("blocks") or []]
        if extra < 1 or not ids or any(i not in by_id for i in ids):
            continue
        feeds = [e.get("source") for e in edges if e.get("target") == ids[0]]
        exits = [e.get("target") for e in edges if e.get("source") == ids[-1]]
        xs = [pos(by_id[i]).get("x", 0) for i in ids]
        top = min(pos(by_id[i]).get("y", 0) for i in ids)
        # Below whatever is drawn across the train's columns.
        base = max(pos(n).get("y", 0) for n in nodes if min(xs) - 60 <= pos(n).get("x", 0) <= max(xs) + 60)
        for j in range(1, extra + 1):
            chain = []
            for nid in ids:
                node = by_id[nid]
                data = node.get("data") or {}
                cid = fresh(f"{nid}t{j}")
                cdata = {k: copy.deepcopy(v) for k, v in data.items() if k not in ("state", "repeat_of")}
                cdata["label"] = f"{data.get('label') or nid} ({j + 1})"
                p = pos(node)
                chain.append({
                    **{k: v for k, v in node.items() if k not in ("id", "data", "position", "selected")},
                    "id": cid, "data": cdata,
                    "position": {"x": p.get("x", 0), "y": base + j * _COPY_GAP + p.get("y", 0) - top},
                })
            for c in chain:
                by_id[c["id"]] = c
            nodes.extend(chain)
            edges += [_edge(src, chain[0]["id"]) for src in feeds]
            edges += [_edge(a["id"], b["id"]) for a, b in zip(chain, chain[1:])]
            edges += [_edge(chain[-1]["id"], tgt) for tgt in exits]
        for tgt in exits:  # a vote's count of branches (its "k"; "n" is the number needed)
            target = by_id.get(tgt) or {}
            data = target.get("data")
            if target.get("type") == "knode" and isinstance(data, dict) and data.get("k") is not None:
                try:
                    target["data"] = {**data, "k": int(data["k"]) + extra}
                except (TypeError, ValueError):
                    pass
    out["nodes"] = nodes
    out["edges"] = edges
    return out
