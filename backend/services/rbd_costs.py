"""Cost of ownership of a repairable RBD (#99), on RePyability 0.9.

* :func:`cost_summary` — the costs part of an availability result: the
  long-run cost rate and its breakdown (per category and per block: repairs,
  replacements, preventive maintenance, proof tests, the block's own downtime,
  and the system's lost production), the total cost of ownership over a
  horizon (purchase + running), and the simulated cost of the window with its
  spread, from the same simulation as the availability. Exact figures come from
  ``RepairableRBD.expected_cost_rate`` where RePyability has them (not for
  proof tests whose tests or repairs take time); otherwise the simulated rate stands in, and every
  figure says which it is (``basis``).
* :func:`cheapest_design` — ``RepairableRBD.allocate_redundancy``: how many
  active copies of each priced block give the lowest total cost of ownership
  over a horizon, optionally with an availability floor, and the diagram with
  those copies drawn on it (nothing is saved; the builder puts it on the
  canvas).

Costs are undiscounted, in whatever currency the user entered them.
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
CATEGORIES = ("repair", "replace", "preventive", "inspection", "component_downtime", "system_downtime")
#: Percentiles of the window's cost reported.
PERCENTILES = (10, 50, 90)
#: The most copies of one block the cheapest-design search considers.
MAX_COPIES = 6
#: The most blocks it designs at once (branch and bound suits a handful).
MAX_BLOCKS = 12
_COPY_GAP = 110
_COL_GAP = 280
_ARROW = {"type": "arrowclosed", "width": 18, "height": 18}


def _mean_cost(cost) -> float:
    from repyability.rbd.repairable_rbd import _mean_cost as mean

    return float(mean(cost))


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
    with np.errstate(all="ignore"):
        total = float(rbd.expected_cost_rate(**overrides))
        availability = {}
        if rbd.costs:
            probs = rbd._probabilities_with_overrides(rbd.node_availability(), working, broken)
            availability = {n: _scalar(v) for n, v in probs.items()}
        system_down = 0.0
        if rbd.downtime_cost_rate:
            system_down = rbd.downtime_cost_rate * (1.0 - float(rbd.mean_availability(**overrides)))
    by_block: dict[Any, dict] = {}
    for node, costs in rbd.costs.items():
        row = {k: 0.0 for k in CATEGORIES if k != "system_downtime"}
        if node not in forced:
            failures, maintained, _ = rbd._node_frequencies(node)
            for key in ("repair", "replace"):
                if f"{key}_cost" in costs:
                    row[key] = _mean_cost(costs[f"{key}_cost"]) * failures
            if "preventive_cost" in costs:
                row["preventive"] = _mean_cost(costs["preventive_cost"]) * maintained
            if "inspection_cost" in costs:
                row["inspection"] = _mean_cost(costs["inspection_cost"]) / rbd._inspection[node].interval
        if costs.get("downtime_cost"):
            row["component_downtime"] = costs["downtime_cost"] * (1.0 - availability[node])
        by_block[node] = row
    by_category = {k: math.fsum(r[k] for r in by_block.values()) for k in CATEGORIES if k != "system_downtime"}
    by_category["system_downtime"] = system_down
    return {"total": total, "by_category": by_category, "by_block": by_block}


def _simulated(cost) -> Optional[dict]:
    """The window's simulated cost (a ``CostResult``) as plain numbers."""
    if cost is None or not len(cost.samples):
        return None
    out: dict[str, Any] = {
        "mean": ra._f(cost.mean),
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
                 res, t_sim: float, per_node: list, importance: dict) -> Optional[dict]:
    """The costs part of an availability result, or None when nothing is
    priced (no running cost and no purchase price)."""
    acquisition = float(rbd.acquisition_cost)
    if not rbd.has_costs and not acquisition:
        return None
    exact = None
    if rbd.has_costs:
        try:
            exact = exact_breakdown(rbd, overrides)
        except NotImplementedError:
            exact = None
    simulated = _simulated(getattr(res, "cost", None)) if res is not None else None
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
    priced = set(rbd.costs) | set(rbd.acquisition_costs)
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
        "running_cost": ra._f(rate * horizon) if rate is not None else None,
        "total_cost": ra._f(acquisition + rate * horizon) if rate is not None else None,
        "simulated": simulated,
    }


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


def cheapest_design(graph: dict, resolve_model=None, horizon=None, min_availability=None,
                    blocks: Optional[list] = None) -> dict:
    """The number of active copies of each priced block (every block with a
    purchase price, or ``blocks``) that owns the diagram for ``horizon`` at the
    lowest total cost (``RepairableRBD.allocate_redundancy``), optionally only
    among designs at least ``min_availability`` available; with the design as
    drawn for comparison, and the diagram with the copies drawn on it."""
    if not (graph or {}).get("repairable"):
        raise AnalysisError("The cheapest design is for repairable (availability) diagrams.")
    diagram = rm.diagram_costs(graph)
    horizon = rm._number(horizon, "ownership horizon", "Diagram", positive=True) or diagram["horizon"]
    if not horizon:
        raise AnalysisError("Set how long the system is owned (the horizon) to price it over.")
    floor = None
    if not rm._blank(min_availability):
        try:
            floor = float(min_availability)
        except (TypeError, ValueError):
            floor = float("nan")
        if not 0.0 < floor < 1.0:
            raise AnalysisError("The minimum availability must be between 0% and 100%.")

    drawn = _as_drawn(graph)
    rbd, labels, gate_ids, _, _ = ra._build_repairable_rbd(drawn, resolve_model)
    if blocks:
        chosen = [b for b in blocks if b in rbd.components and b not in gate_ids]
    else:
        chosen = [n for n in rbd.components if n in rbd.acquisition_costs and n not in gate_ids]
    if not chosen:
        raise AnalysisError(
            "Give at least one block a purchase price (in its Cost & maintenance section): "
            "the cheapest design weighs what a copy costs to buy and run against the "
            "downtime it saves."
        )
    if len(chosen) > MAX_BLOCKS:
        raise AnalysisError(
            f"The cheapest design handles up to {MAX_BLOCKS} priced blocks at once — "
            f"this diagram has {len(chosen)}."
        )
    if not rbd.downtime_cost_rate:
        note = ("The diagram has no system downtime cost, so extra copies only add cost — "
                "set the cost of an hour of downtime to weigh them.")
    else:
        note = None
    try:
        with np.errstate(all="ignore"):
            alloc = rbd.allocate_redundancy(
                horizon, nodes=chosen, min_availability=floor, max_units=MAX_COPIES,
            )
            current = {
                "total_cost": float(rbd.total_cost(horizon)),
                "cost_rate": float(rbd.expected_cost_rate()),
                "acquisition_cost": float(rbd.acquisition_cost),
                "availability": float(rbd.mean_availability()),
            }
    except NotImplementedError as exc:
        raise AnalysisError(
            "The cheapest design needs exact long-run costs, which RePyability doesn't have "
            "for this diagram: " + _friendly(str(exc), labels).split(": estimate")[0].split(". Estimate")[0]
            + ". For proof-tested blocks, use instant tests and instant repair."
        ) from exc
    except ValueError as exc:
        msg = _friendly(str(exc), labels)
        if "min_availability" in msg or "cannot be reached" in msg or "reach" in msg:
            raise AnalysisError(
                f"No design with up to {MAX_COPIES} copies of each priced block reaches that "
                "availability — lower the minimum, or price more blocks."
            ) from exc
        raise AnalysisError(f"Couldn't find the cheapest design: {msg}") from exc

    current["meets_floor"] = None if floor is None else current["availability"] >= floor
    units = {str(k): int(v) for k, v in alloc.units.items()}
    rows = [
        {"id": str(n), "label": labels.get(n, str(n)), "copies": units.get(str(n), 1),
         "price": rbd.acquisition_costs.get(n, 0.0)}
        for n in chosen
    ]
    design = {
        "units": units,
        "blocks": rows,
        "total_cost": float(alloc.total_cost),
        "cost_rate": float(alloc.cost_rate),
        "acquisition_cost": float(alloc.acquisition_cost),
        "availability": float(alloc.availability),
    }
    changed = any(v != 1 for v in units.values())
    return {
        "kind": "repairable_cost_design",
        "unit": (graph.get("unit") or "").strip(),
        "horizon": float(horizon),
        "min_availability": floor,
        "method": alloc.method,
        "max_copies": MAX_COPIES,
        "current": current,
        "design": design,
        "saving": current["total_cost"] - design["total_cost"],
        "changed": changed,
        "note": note,
        "graph": apply_copies(graph, units) if changed else None,
        "repyability_version": ra._repyability_version(),
    }


def _edge(source: str, target: str) -> dict:
    return {"id": f"e-{source}-{target}", "source": source, "target": target,
            "type": "smoothstep", "markerEnd": dict(_ARROW)}


def apply_copies(graph: dict, units: dict) -> dict:
    """The diagram with ``units[id]`` identical copies of each block, each
    wired between the block's own neighbours (active redundancy: any copy
    carries the path). Where a block feeds a k-out-of-n vote (k ≥ 2), whose
    count of incoming branches must not change, its copies join at a junction
    first. Copies keep the block's models, costs and maintenance (proof-tested
    copies are tested together, as the allocation assumes); pins are dropped.
    Nothing is saved."""
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
    out["nodes"] = nodes
    out["edges"] = edges
    return out
