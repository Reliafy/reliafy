"""Production availability: what share of a demand a diagram delivers (#122).

A block can carry a **capacity**, its throughput while it works: one number
(``data.capacity = 50``), or levels it works at with the probability of each
(``data.capacity = [{"value": 50, "probability": 0.8}, {"value": 25,
"probability": 0.2}]``, a multi-state component). The diagram may carry a
**demand** and the unit both are in, and a period to count production over:
``graph.production = {"demand": 100, "unit": "MW", "period": 8760}``.

RePyability (0.11+) gives the exact distribution of what the system can
deliver — the most that can flow from the input to the output through the
blocks that work, each passing at most its capacity (a series chain the least
of its blocks', a parallel group their sum) — and from it

* a repairable diagram's long-run distribution
  (``RepairableRBD.capacity_distribution``) and, over a period from new, the
  expected share of time at each level (``mission_capacity``);
* a non-repairable diagram's distribution at a time
  (``NonRepairableRBD.capacity_distribution``).

``delivered_fraction(demand)`` is the production availability: the expected
share of the demand delivered. Every figure comes from those calls; a block
without a capacity limits nothing (it passes whatever reaches it).
"""

from __future__ import annotations

import math
from typing import Any, Callable, Optional

#: Block types that take a capacity: a single component, and a standby group
#: (one unit runs at a time, so its capacity is the running unit's).
CAPACITY_TYPES = ("component", "standby")
#: The most capacity levels a block can have.
MAX_LEVELS = 10


class CapacityError(ValueError):
    """A capacity or demand that can't be used (user-facing text)."""


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------
def _positive(raw, what: str) -> float:
    if isinstance(raw, bool):
        raise CapacityError(f"{what} must be a number.")
    try:
        value = float(raw)
    except (TypeError, ValueError):
        raise CapacityError(f"{what} must be a number.") from None
    if not math.isfinite(value) or value <= 0:
        raise CapacityError(f"{what} must be a positive number.")
    return value


def parse_capacity(raw, where: str = "This block") -> Any:
    """A block's capacity, checked: a positive number, or a list of 1 to
    :data:`MAX_LEVELS` ``{value, probability}`` levels whose probabilities add
    up to 1 (a single level is stored as its number). ``None`` for none."""
    if raw is None or raw == "" or raw == []:
        return None
    if not isinstance(raw, (list, tuple)):
        return _positive(raw, f"{where}: the capacity")
    if len(raw) > MAX_LEVELS:
        raise CapacityError(f"{where}: give at most {MAX_LEVELS} capacity levels.")
    levels: dict[float, float] = {}
    for level in raw:
        if not isinstance(level, dict):
            raise CapacityError(f"{where}: each capacity level needs a value and a probability.")
        value = _positive(level.get("value"), f"{where}: a capacity level")
        p = _positive(level.get("probability"), f"{where}: the probability of capacity {value:g}")
        if p > 1:
            raise CapacityError(f"{where}: the probability of capacity {value:g} must be at most 1.")
        levels[value] = levels.get(value, 0.0) + p
    total = math.fsum(levels.values())
    if abs(total - 1.0) > 1e-6:
        raise CapacityError(
            f"{where}: the probabilities of the capacity levels must add up to 1 (they add up to {total:.4g})."
        )
    if len(levels) == 1:
        return next(iter(levels))
    return [{"value": v, "probability": levels[v] / total} for v in sorted(levels)]


def engine_capacity(value) -> Any:
    """A parsed capacity as RePyability takes it: a float, or ``{level:
    probability}``."""
    if isinstance(value, list):
        return {float(lv["value"]): float(lv["probability"]) for lv in value}
    return float(value)


def parse_production(raw) -> dict:
    """The diagram's demand, unit and period, checked; ``{}`` when unset."""
    if not raw:
        return {}
    if not isinstance(raw, dict):
        raise CapacityError("The production settings must be an object of demand, unit and period.")
    out: dict[str, Any] = {}
    if raw.get("demand") not in (None, ""):
        out["demand"] = _positive(raw["demand"], "The demand")
    if raw.get("period") not in (None, ""):
        out["period"] = _positive(raw["period"], "The period")
    unit = str(raw.get("unit") or "").strip()[:20]
    if unit:
        out["unit"] = unit
    return out


def _blocks(graph: dict) -> list[dict]:
    return [n for n in graph.get("nodes") or [] if isinstance(n, dict)
            and n.get("type") not in ("input", "output")]


def graph_capacities(graph: dict) -> dict:
    """``{node id: capacity as RePyability takes it}`` for the blocks given
    one. Raises :class:`CapacityError` for a bad value, or a capacity on a
    block type that can't carry one."""
    out = {}
    for node in _blocks(graph):
        data = node.get("data") or {}
        if data.get("capacity") in (None, "", []):
            continue
        label = data.get("label") or node.get("id")
        if node.get("type") not in CAPACITY_TYPES or data.get("repeat_of"):
            raise CapacityError(
                f"“{label}” can't carry a capacity: only single components and standby groups do (draw the "
                "units of a count block separately to give each its own)."
            )
        out[node["id"]] = engine_capacity(parse_capacity(data["capacity"], f"“{label}”"))
    return out


def has_capacity(graph: dict) -> bool:
    """Whether any block of the diagram carries a capacity."""
    return any((n.get("data") or {}).get("capacity") not in (None, "", []) for n in _blocks(graph or {}))


# ---------------------------------------------------------------------------
# The analysis
# ---------------------------------------------------------------------------
def _f(value) -> Optional[float]:
    value = float(value)
    return value if math.isfinite(value) else None


def _levels(dist) -> list[dict]:
    """The distribution's levels as JSON (an unlimited level is ``None``),
    leaving out levels of no probability."""
    out = []
    for level, p in zip(dist.levels.tolist(), dist.probabilities.tolist()):
        if p > 0:
            out.append({"capacity": _f(level), "probability": float(p)})
    return out


def _summary(dist, demand: Optional[float]) -> dict:
    """The figures RePyability gives from one capacity distribution."""
    positive = [lv for lv in dist.levels.tolist() if lv > 0]
    out: dict[str, Any] = {
        "levels": _levels(dist),
        # The capacity is positive exactly when the system works: meeting
        # the least positive level is the availability (or reliability).
        "availability": float(dist.meets(positive[0])) if positive else 0.0,
        "mean_capacity": _f(dist.mean),
        "unlimited": not math.isfinite(float(dist.levels[-1])),
    }
    if demand is not None:
        out["production_availability"] = float(dist.delivered_fraction(demand))
        out["meets_demand"] = float(dist.meets(demand))
    return out


def _message(exc: Exception, labels: dict) -> str:
    from backend.services.rbd_analysis import _with_labels

    return _with_labels(str(exc), labels)


def production(
    graph: dict,
    resolve_model: Optional[Callable] = None,
    resolve_subsystem: Optional[Callable] = None,
    t: Optional[float] = None,
) -> Optional[dict]:
    """The diagram's production availability and capacity distribution, or
    ``None`` when no block carries a capacity.

    A repairable diagram gives the long run, and the period from new (the
    diagram's ``production.period``, else ``t``) when there is one. A
    non-repairable diagram gives the distribution at ``t`` (else the
    period). Figures the engine can't give are left out with a reason in
    ``notes``. Raises :class:`CapacityError` for bad inputs and
    :class:`~.rbd_analysis.AnalysisError` for a diagram that can't be built.
    """
    from backend.services import rbd_analysis

    graph = graph or {}
    if not has_capacity(graph):
        return None
    capacities = graph_capacities(graph)
    settings = parse_production(graph.get("production"))
    demand = settings.get("demand")
    if t is not None:
        t = float(t)
        if not math.isfinite(t) or t <= 0:
            raise CapacityError("The time must be a positive number.")
    repairable = bool(graph.get("repairable"))
    out: dict[str, Any] = {
        "kind": "repairable" if repairable else "reliability",
        "demand": demand,
        "capacity_unit": settings.get("unit") or "",
        "time_unit": graph.get("unit") or "",
        "notes": [],
    }
    labels: dict = {}
    without = [
        (n.get("data") or {}).get("label") or n.get("id") for n in _blocks(graph)
        if n.get("id") not in capacities and n.get("type") not in ("knode",)
    ]
    if without:
        out["uncapped"] = without
    if demand is None:
        out["notes"].append("Set a demand to get the production availability: the share of it delivered.")

    if repairable:
        rbd, labels, _gates, working, broken = rbd_analysis._build_repairable_rbd(
            graph, resolve_model, capacity=capacities)
        status = rbd_analysis.common_cause_status(rbd)
        if status and not status.get("included") and status.get("reason"):
            out["notes"].append("Common-cause groups are left out: " + status["reason"])
        try:
            long_run = rbd.capacity_distribution(working_nodes=working or None, broken_nodes=broken or None)
        except (ValueError, NotImplementedError) as exc:
            raise CapacityError(_message(exc, labels)) from None
        out["basis"] = "long_run"
        out.update(_summary(long_run, demand))
        if demand is not None:
            # Lost output per unit time, on average: the demand not delivered.
            out["shortfall_rate"] = demand * (1.0 - out["production_availability"])
        period = settings.get("period") or t
        if period is not None:
            try:
                window = rbd.mission_capacity(period, working_nodes=working or None, broken_nodes=broken or None)
            except (ValueError, NotImplementedError) as exc:
                out["notes"].append("The period from new is left out: " + _message(exc, labels))
            else:
                block = {"length": float(period), "from_settings": "period" in settings,
                         **_summary(window, demand)}
                if demand is not None:
                    block["delivered"] = demand * period * block["production_availability"]
                    block["lost"] = demand * period * (1.0 - block["production_availability"])
                block.pop("levels", None)
                out["period"] = block
        return out

    rbd, labels, _types, _rel, working, broken, _baseline = rbd_analysis._build_rbd(
        graph, resolve_subsystem, None, resolve_model, capacity=capacities)
    at = t if t is not None else settings.get("period")
    if at is None:
        raise CapacityError("Give a time to read the capacity at (a non-repairable diagram's capacity falls "
                            "as its blocks fail).")
    try:
        dist = rbd.capacity_distribution(at, working_nodes=working or None, broken_nodes=broken or None)
    except (ValueError, NotImplementedError) as exc:
        raise CapacityError(_message(exc, labels)) from None
    out["basis"] = "at_time"
    out["t"] = float(at)
    out.update(_summary(dist, demand))
    return out


def production_for_owner(db, graph: dict, owners, t: Optional[float] = None) -> Optional[dict]:
    """:func:`production` with saved models and sub-systems resolved in the
    caller's scope, as the analysis resolves them."""
    from backend.services import models as models_service
    from backend.services import rbds as rbds_service

    def resolve_subsystem(sub_id: str):
        sub = rbds_service.get_rbd(db, sub_id, owners)
        return sub.graph if sub is not None else None

    def resolve_model(model_id: str):
        return models_service.get_live_model(db, model_id, owners)

    return production(graph, resolve_model, resolve_subsystem, t)


# ---------------------------------------------------------------------------
# Export and import
# ---------------------------------------------------------------------------
def document_capacity(graph: dict) -> Optional[list]:
    """The diagram's capacities as RePyability's ``rbd_to_dict`` writes them
    (``[{"node", "capacity"} | {"node", "levels": [[level, p], …]}]``), or
    ``None``."""
    caps = graph_capacities(graph or {})
    if not caps:
        return None
    out = []
    for node, value in caps.items():
        if isinstance(value, dict):
            out.append({"node": node, "levels": [[float(lv), float(p)] for lv, p in value.items()]})
        else:
            out.append({"node": node, "capacity": float(value)})
    return out


def from_document(entries) -> dict:
    """``{node name: capacity as the builder stores it}`` from a RePyability
    document's ``capacity`` list; entries it can't read are skipped (an
    unlimited capacity is no capacity)."""
    out = {}
    for entry in entries or []:
        if not isinstance(entry, dict) or "node" not in entry:
            continue
        try:
            if "levels" in entry:
                raw = [{"value": lv, "probability": p} for lv, p in entry["levels"]]
            else:
                raw = entry.get("capacity")
            value = parse_capacity(raw)
        except (CapacityError, TypeError, ValueError):
            continue
        if value is not None:
            out[str(entry["node"])] = value
    return out


def export_lines(graph: dict) -> list[str]:
    """The ``CAPACITY`` and ``DEMAND`` constants of a "Download as Python"
    script, or ``[]`` when no block carries a capacity."""
    caps = graph_capacities(graph or {})
    if not caps:
        return []
    settings = parse_production((graph or {}).get("production"))
    unit = settings.get("unit")
    out = [
        "# Each block's capacity: its throughput while it works"
        + (f" ({unit})" if unit else "") + ", or the levels it",
        "# works at with the probability of each. A block left out limits nothing.",
        "CAPACITY = {",
    ]
    for node, value in caps.items():
        out.append(f"    {node!r}: {value!r},")
    out.append("}")
    out.append(f"DEMAND = {settings.get('demand')!r}  # what the system is asked to deliver")
    if graph.get("repairable"):
        out.append(f"PERIOD = {settings.get('period')!r}  # production counted over this time from new")
    else:
        out.append(f"PERIOD = {settings.get('period')!r}  # the time the capacity is read at")
    return out


EXPORT_MAIN_CALL = 'if __name__ == "__main__":\n    main()\n'

_PRODUCTION_REPAIRABLE = '''
def production():
    """Production availability (Reliafy's Production section): the exact
    long-run distribution of what the system can deliver, and the expected
    share of the demand it delivers."""
    capacity = rbd.capacity_distribution(
        working_nodes=WORKING_NODES or None, broken_nodes=BROKEN_NODES or None
    )
    print("\\nCapacity in the long run")
    for level, p in zip(capacity.levels, capacity.probabilities):
        if p > 0:
            print(f"  {level:>12,.6g}: {p:.6f}")
    print(f"Mean capacity: {capacity.mean:,.6g}")
    if DEMAND:
        share = capacity.delivered_fraction(DEMAND)
        print(f"Production availability: {share:.6f}")
        print(f"Time the demand is met: {capacity.meets(DEMAND):.6f}")
        if PERIOD:
            window = rbd.mission_capacity(
                PERIOD,
                working_nodes=WORKING_NODES or None,
                broken_nodes=BROKEN_NODES or None,
            )
            lost = DEMAND * PERIOD * (1 - window.delivered_fraction(DEMAND))
            print(f"Over {PERIOD:,.6g}{(' ' + UNIT_TEXT) if UNIT_TEXT else ''} "
                  f"from new: {lost:,.6g} of output lost")
    return capacity
'''

_PRODUCTION_NONREPAIRABLE = '''
def production():
    """Production availability (Reliafy's Production section): the exact
    distribution of what the system can deliver at PERIOD, and the expected
    share of the demand it delivers then."""
    if not PERIOD:
        print("\\nSet PERIOD to read the capacity at a time.")
        return None
    overrides = {"working_nodes": WORKING_NODES, "broken_nodes": BROKEN_NODES}
    capacity = rbd.capacity_distribution(PERIOD, **overrides)
    print(f"\\nCapacity at t = {PERIOD:,.6g}")
    for level, p in zip(capacity.levels, capacity.probabilities):
        if p > 0:
            print(f"  {level:>12,.6g}: {p:.6f}")
    print(f"Mean capacity: {capacity.mean:,.6g}")
    if DEMAND:
        print(f"Share of the demand delivered: {capacity.delivered_fraction(DEMAND):.6f}")
    return capacity
'''


def export_main(graph: dict) -> Optional[str]:
    """The script's ``production()`` function and the ``__main__`` block that
    runs it after ``main()``, or ``None`` when no block carries a capacity."""
    if not graph_capacities(graph or {}):
        return None
    fn = _PRODUCTION_REPAIRABLE if graph.get("repairable") else _PRODUCTION_NONREPAIRABLE
    return fn.strip("\n") + '\n\n\nif __name__ == "__main__":\n    main()\n    production()\n'
