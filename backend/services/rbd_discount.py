"""The cost of owning a repairable RBD over several horizons, from new and
at the long-run rate, discounted or not (#319, RePyability 0.13).

RePyability 0.13 prices ownership itself (its #231):

* ``RepairableRBD.total_cost(horizon, discount_rate=r)`` takes an array of
  horizons, and an endless one (``inf``) when the costs are discounted: the
  purchases plus the long-run cost rate over each horizon, its present value
  with a rate — for an endless horizon, the net present cost;
* ``RepairableRBD.expected_cost(t, discount_rate=r)`` is the exact (or
  numerical) expected cost of owning the system *from new*, each cost
  discounted from when it falls: the early years, which count most, are those
  that differ from the long-run rate.

So Reliafy no longer works out a discount factor of its own: every figure
here is one of those two calls. :func:`by_horizon` gives the rows the
availability result's costs, the cheapest design and the MCP tools report;
:func:`horizons` chooses which horizons (the one set, 5, 10 and 20 years in
a calendar unit, and endless when discounted).

A running cost the library can't work out exactly (limited repair crews for
wear-out lives, say: the simulated rate stands in) can't be discounted by it
either: its present values are left out, with the reason
(:data:`NO_PRESENT_VALUE`), and only the undiscounted total is given.
"""

from __future__ import annotations

import time
import warnings
from typing import Any, Optional

import numpy as np

from backend.services import rbd_analysis as ra
from backend.services import rbd_maintenance as rm
from backend.services.rbd_analysis import AnalysisError

#: Ownership horizons compared by default, in years (a calendar time unit).
DEFAULT_YEARS = (5, 10, 20)
#: The most finite horizons one request prices.
MAX_HORIZONS = 6
#: Seconds the set horizon's cost from new may take for the other horizons'
#: to be worked out too.
FROM_NEW_BUDGET_S = 1.5
#: The most condition checks (a horizon over the shortest check interval of a
#: block replaced on condition) the cost from new follows in an analysis:
#: each takes the library about 50 ms to follow, so more would hold up
#: Calculate. Past it the figure is left out with a note; the exported
#: script still works it out.
MAX_CONDITION_CHECKS = 25

NO_PRESENT_VALUE = (
    "No present value: this diagram has no exact long-run cost rate (the simulated one stands in), "
    "and RePyability discounts only its own exact costs. The totals are undiscounted.")
NO_FROM_NEW = "RePyability has no exact cost over time for this diagram"


def _years_per_unit(graph: dict) -> Optional[float]:
    """Years in one of the diagram's time units, or None for a unit that
    isn't a calendar one (cycles, km, none)."""
    from backend.units import normalize_unit

    per_year = rm.UNITS_PER_YEAR.get(normalize_unit(graph.get("unit")) or "")
    return 1.0 / per_year if per_year else None


def parse_horizons(values) -> Optional[list[float]]:
    """Horizons given by a caller (the diagram's unit), checked: up to
    :data:`MAX_HORIZONS` positive numbers. None when none are given."""
    if values is None:
        return None
    if isinstance(values, (str, bytes)) or not isinstance(values, (list, tuple)):
        raise AnalysisError("Horizons must be a list of times in the diagram's unit, e.g. [43800, 87600].")
    out = []
    for v in values:
        h = rm._number(v, "horizon", "Horizons", positive=True)
        if h is not None:
            out.append(h)
    if len(out) > MAX_HORIZONS:
        raise AnalysisError(f"Compare up to {MAX_HORIZONS} horizons at once.")
    return out or None


def horizons(graph: dict, chosen: float, disc: Optional[dict], given: Optional[list] = None) -> list[dict]:
    """The horizons to price, shortest first: ``chosen`` (the diagram's
    horizon, or the window), and ``given`` (the caller's, in the diagram's
    unit) or else 5, 10 and 20 years in a calendar unit; then, when the costs
    are discounted, an endless horizon. Each ``{"horizon", "years", "set",
    "endless"}``; the endless one has ``horizon`` None (JSON has no
    infinity)."""
    years = _years_per_unit(graph)
    extra = list(given) if given else ([y / years for y in DEFAULT_YEARS] if years else [])
    finite: list[float] = []
    for h in [float(chosen), *extra]:
        if h > 0 and np.isfinite(h) and not any(abs(h - f) <= 1e-9 * max(h, f) for f in finite):
            finite.append(h)
    finite = sorted(finite[:MAX_HORIZONS + 1])
    rows = [{"horizon": h, "years": (h * years) if years else None,
             "set": abs(h - float(chosen)) <= 1e-9 * max(h, float(chosen)), "endless": False}
            for h in finite]
    if disc:
        rows.append({"horizon": None, "years": None, "set": False, "endless": True})
    return rows


def _times(rows: list[dict]) -> np.ndarray:
    return np.array([np.inf if r["endless"] else r["horizon"] for r in rows], dtype=float)


def _quiet(fn, *args, **kwargs):
    """``fn(...)`` with RePyability's warning that a rate discounts the costs
    away silenced: a rate is at most 100% a year in a calendar unit, and the
    figures say what they are."""
    with warnings.catch_warnings(), np.errstate(all="ignore"):
        warnings.simplefilter("ignore")
        return fn(*args, **kwargs)


def long_run(rbd, overrides: dict, rows: list[dict], rate: Optional[float], basis: Optional[str],
             disc: Optional[dict]) -> tuple[list[Optional[float]], list[Optional[float]], Optional[str]]:
    """``(totals, undiscounted, note)`` for ``rows``: the total cost of
    ownership at the long-run rate over each (``total_cost``: a present value
    when discounted, the endless one the net present cost) and, discounted,
    the undiscounted total beside it (None for an endless horizon). With a
    simulated ``rate`` the library can't price the horizons: the undiscounted
    totals are the purchases plus that rate over each, and the present values
    are left out (``note`` says why)."""
    n = len(rows)
    if rate is None:
        return [None] * n, [None] * n, None
    r = disc["per_unit"] if disc else 0.0
    times = _times(rows)
    finite = np.isfinite(times)
    if basis != "exact":
        acquisition = float(rbd.acquisition_cost)
        plain = [ra._f(acquisition + rate * t) if np.isfinite(t) else None for t in times]
        if disc:
            return [None] * n, plain, NO_PRESENT_VALUE
        return plain, [None] * n, None
    # An endless horizon only comes with a rate (horizons()).
    totals = np.atleast_1d(_quiet(rbd.total_cost, times, discount_rate=r, **overrides))
    undiscounted = [None] * n
    if disc and finite.any():
        plain = np.full(n, np.nan)
        plain[finite] = _quiet(rbd.total_cost, times[finite], **overrides)
        undiscounted = [ra._f(v) for v in plain]
    return [ra._f(v) for v in totals], undiscounted, None


def _condition_checks(graph: dict) -> Optional[tuple[str, float]]:
    """``(label, interval)`` of the block replaced on condition checked most
    often, or None when there is none."""
    best = None
    for node in graph.get("nodes") or []:
        data = node.get("data") or {}
        pm = data.get("preventive") or {}
        if node.get("type") != "component" or pm.get("policy") != "condition":
            continue
        try:
            interval = float(pm.get("interval"))
        except (TypeError, ValueError):
            continue
        if interval > 0 and (best is None or interval < best[1]):
            best = (data.get("label") or node.get("id"), interval)
    return best


def _too_slow(checks: Optional[tuple[str, float]], t: float) -> bool:
    return checks is not None and t / checks[1] > MAX_CONDITION_CHECKS


def from_new(rbd, graph: dict, overrides: dict, rows: list[dict],
             disc: Optional[dict]) -> tuple[list[Optional[float]], Optional[str], Optional[str]]:
    """``(totals, basis, note)``: the expected cost of owning the system from
    new over each finite horizon — the purchases plus RePyability's
    ``expected_cost`` (exact or numerical), each cost discounted from when it
    falls when a rate is set — or Nones and why not. An endless horizon has
    none (the library prices windows from new up to a finite end); nor has a
    diagram above :data:`rbd_analysis.EXACT_WINDOW_MEAN_MAX_BLOCKS` blocks,
    as for the window's exact mean."""
    n = len(rows)
    none = [None] * n
    times = _times(rows)
    finite = np.isfinite(times)
    if not finite.any():
        return none, None, None
    if not rbd.has_costs:
        # Bought and never charged again: the purchases at every horizon.
        acquisition = ra._f(rbd.acquisition_cost)
        return [acquisition if f else None for f in finite], "exact", None
    if not ra.window_mean_exact_ok(graph):
        return none, None, (f"The costs from new are worked out for diagrams of up to "
                            f"{ra.EXACT_WINDOW_MEAN_MAX_BLOCKS} blocks.")
    route = ra.window_routes(rbd)["expected_cost"]
    if route not in ra._OVER_TIME_OK:
        return none, None, f"{NO_FROM_NEW}."
    r = disc["per_unit"] if disc else 0.0
    out: list = [None] * n
    # The set horizon first, on its own; the others together after it, unless
    # it alone took longer than FROM_NEW_BUDGET_S (a block replaced on
    # condition, say, whose curves are long to follow).
    first = next((i for i, row in enumerate(rows) if row["set"]), None)
    rest = [i for i in range(n) if finite[i] and i != first]
    # A block replaced on condition is slow to follow from new over many
    # checks: those horizons are left out here (Download as Python has them).
    checks = _condition_checks(graph)
    slow = [i for i in range(n) if finite[i] and _too_slow(checks, float(times[i]))]
    if slow:
        rest = [i for i in rest if i not in slow]
        if first in slow:
            first = None
        if first is None and not rest:
            unit = (graph.get("unit") or "").strip().lower() or "time units"
            return none, None, (f"The costs from new are left out: “{checks[0]}” is replaced on condition, checked "
                                f"every {checks[1]:,.4g} {unit}, which takes too long to follow here over these "
                                "horizons. Download as Python works them out.")
    started = time.perf_counter()
    try:
        if first is not None:
            out[first] = ra._f(_quiet(rbd.expected_cost, float(times[first]), discount_rate=r, **overrides).total)
    except (NotImplementedError, ValueError) as exc:
        return none, None, f"{NO_FROM_NEW}: {ra.plain_reason(str(exc))}"
    if rest and time.perf_counter() - started > FROM_NEW_BUDGET_S:
        return out, route, "The costs from new over the other horizons take too long to work out here."
    slow_note = ("The costs from new over the longer horizons take too long to work out here (a block replaced on "
                 "condition); Download as Python works them out." if slow else None)
    if rest:
        try:
            cost = _quiet(rbd.expected_cost, times[rest], discount_rate=r, **overrides)
        except (NotImplementedError, ValueError) as exc:
            # A long horizon can be beyond what the library follows exactly.
            return out, route, f"{NO_FROM_NEW} over the other horizons: {ra.plain_reason(str(exc))}"
        for i, v in zip(rest, np.atleast_1d(np.asarray(cost.total, dtype=float))):
            out[i] = ra._f(v)
    return out, route, slow_note


def by_horizon(rbd, graph: dict, overrides: dict, chosen: float, rate: Optional[float],
               basis: Optional[str], disc: Optional[dict], given: Optional[list] = None) -> dict:
    """The cost of ownership over each horizon (:func:`horizons`): ``rows``
    of ``{"horizon", "years", "set", "endless", "total_cost" (at the
    long-run rate), "from_new" (from new, when the library has it),
    "undiscounted_total_cost"}`` with ``from_new_basis`` (exact /
    numerical) and the notes on what's left out."""
    rows = horizons(graph, chosen, disc, given)
    totals, undiscounted, note = long_run(rbd, overrides, rows, rate, basis, disc)
    news, new_basis, new_note = from_new(rbd, graph, overrides, rows, disc)
    out: list[dict[str, Any]] = []
    for row, total, plain, new in zip(rows, totals, undiscounted, news):
        out.append({**row, "total_cost": total, "from_new": new, "undiscounted_total_cost": plain})
    return {
        "rows": out,
        "discount_rate": disc["annual"] if disc else None,
        "from_new_basis": new_basis,
        "from_new_note": new_note,
        "present_value_note": note,
    }
