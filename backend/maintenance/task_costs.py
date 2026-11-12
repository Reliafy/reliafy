"""What a task costs each time it's done, and the trade rates behind it (Nov 2026).

A task's cost per occurrence is one number kept with the task on its position,
so the RCM's "is it worth doing?" and its interval calculators read it rather
than ask for it again. It comes from one of two places:

* typed on the task (``task.cost_set``): a figure the user knows (a contractor's
  quote, the cost of a service); it stands until it's cleared;
* its LSA record otherwise: each labour line's people × hours at its trade's
  hourly rate (``trade.rate_set``: one rate per trade for the workspace, used by
  every task), plus the spares at their part's unit cost and the consumables'
  costs. What can't be priced (a trade with no rate, a spare with no part cost)
  is listed, so the figure says it's partial.

New events (older logs replay unchanged):

* ``task.cost_set {id, cost}``: the cost typed on the task (a number; None
  clears it, and the LSA's figure is used again);
* ``trade.rate_set {id, trade, rate}``: a trade's hourly rate (``id`` from the
  trade's name, :func:`trade_rate_id`, so the same trade in any case is one
  rate; ``rate`` None clears it).

Projectors read only the payload and write through the store interface.
"""

from __future__ import annotations

from backend.maintenance.store import GraphStore

MAX_TRADE_RATES = 500


def trade_key(trade: str) -> str:
    """A trade's name as rates are matched: case and spacing aside."""
    return " ".join(str(trade or "").split()).lower()


def trade_rate_id(org: str, trade: str) -> str:
    """The node id of a trade's rate (one per trade in the organisation)."""
    return f"trade-rate:{org}:{trade_key(trade)}"


def _task_cost_set(s: GraphStore, org: str, p: dict) -> None:
    s.patch_node(org, p["id"], {"cost": p.get("cost")})


def _trade_rate_set(s: GraphStore, org: str, p: dict) -> None:
    s.put_node(org, p["id"], "TradeRate", {"trade": p["trade"], "rate": p.get("rate")})


PROJECTORS = {
    "task.cost_set": _task_cost_set,
    "trade.rate_set": _trade_rate_set,
}


def rates_map(nodes) -> dict:
    """{trade key: {trade, rate}} from the TradeRate nodes (cleared ones left out)."""
    return {trade_key(n["trade"]): {"trade": n["trade"], "rate": n["rate"]}
            for n in nodes if n.get("rate") is not None}


def _tidy(v):
    return None if v is None else round(v, 2)


def cost_of(task: dict, resources: dict, rates: dict) -> dict:
    """A task's cost per occurrence, and where it came from.

    ``task``: the task node (its ``cost`` typed, its ``trade``); ``resources``: its
    LSA record as read (``_resources_view``: spares carry their part's
    ``unit_cost``); ``rates``: :func:`rates_map`.

    Returns {amount, source ('typed' | 'lsa' | None), typed, lsa: {amount,
    labour_cost, labour_hours, materials_cost, complete, missing_rates,
    missing_prices}}. ``amount`` is the typed cost when there is one, else the
    LSA's figure when it prices anything (``complete`` false when part of it
    couldn't be), else None: no cost yet."""
    labour_cost = 0.0
    priced_labour = False
    missing_rates: list[str] = []
    for line in resources.get("labour") or []:
        trade = line.get("trade") or task.get("trade") or ""
        hours = (line.get("people") or 1) * (line.get("hours") or 0)
        if not hours:
            continue
        rate = rates.get(trade_key(trade)) if trade else None
        if rate is None:
            name = trade or "no trade"
            if name not in missing_rates:
                missing_rates.append(name)
            continue
        labour_cost += hours * rate["rate"]
        priced_labour = True
    materials = 0.0
    priced_materials = False
    missing_prices: list[str] = []
    for line in resources.get("spares") or []:
        if line.get("unit_cost") is None:
            missing_prices.append(line.get("name") or line.get("part_number") or "a spare")
            continue
        materials += line["unit_cost"] * (line.get("qty") or 0)
        priced_materials = True
    for line in resources.get("consumables") or []:
        if line.get("cost") is None:
            missing_prices.append(line.get("name") or "a consumable")
            continue
        materials += line["cost"]
        priced_materials = True
    priced = priced_labour or priced_materials
    lsa = {
        "amount": _tidy(labour_cost + materials) if priced else None,
        "labour_cost": _tidy(labour_cost) if priced_labour else None,
        "labour_hours": resources.get("labour_hours") or 0,
        "materials_cost": _tidy(materials) if priced_materials else None,
        "complete": priced and not missing_rates and not missing_prices,
        "missing_rates": missing_rates, "missing_prices": missing_prices,
    }
    typed = task.get("cost")
    if typed is not None:
        return {"amount": _tidy(typed), "source": "typed", "typed": _tidy(typed), "lsa": lsa}
    if priced:
        return {"amount": lsa["amount"], "source": "lsa", "typed": None, "lsa": lsa}
    return {"amount": None, "source": None, "typed": None, "lsa": lsa}


# Where a saved interval calculation keeps the task's own cost, by its kind: what a check
# costs (the P-F calculator), a test (failure finding), a planned replacement (optimal age).
COST_INPUT = {
    "on_condition_interval": "inspection_cost",
    "failure_finding_interval": "test_cost",
    "failure_finding": "test_cost",
    "optimal_replacement": "planned_cost",
}


def changed_since(used, now) -> bool:
    """Whether a task's cost now differs from the one a saved calculation used (to the cent)."""
    if used is None or now is None:
        return False
    try:
        return round(float(used), 2) != round(float(now), 2)
    except (TypeError, ValueError):
        return False
