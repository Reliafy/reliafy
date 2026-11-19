"""Overhaul every X, replace after N overhauls: the cheapest rule for a repairable unit.

In plain words: a unit is repaired at each failure (it goes on as bad as it was), overhauled
every X of its time units (an overhaul takes off part of its age but doesn't make it new) and,
after N overhauls, replaced by a new one instead of the next overhaul. Overhauls keep the
repairs in check; the replacement clears the age that overhauls leave behind. The best X and N
balance the repairs (which get more frequent as the unit ages), the overhauls and the
replacement against how long a replacement cycle lasts.

The maths is RePyability's (``Repairable.optimal_overhaul_replace_policy`` and
``overhaul_replace_cost_rate``, 0.19): failures follow the model's cumulative intensity (minimal
repair), and the long-run cost rate of K = N + 1 periods of length X per replacement cycle is::

    g(X, K) = (cr * expected repairs over the cycle + (K - 1) co + cp) / (K X)

It is exact (no simulation), so it is free. Reliafy only adds the comparisons and the table of
the best X for each N (minimising RePyability's own cost rate over X), and turns downtime into
cost: each event's cost is its price plus the hours it keeps the unit down times the cost of an
hour down. The model's clock (its unit: operating hours, flight hours, cycles) stops while the
unit is down, so downtime adds cost but not time.

Comparisons, each the best of its kind under the same costs:

* run to failure: repair each failure and replace the unit at the n-th failure (no planned
  work; RePyability's failure-limit policy, with the replacement cost);
* overhaul only: overhaul every X and never replace (a very long run of overhauls);
* replace only: replace every X, no overhauls (N = 0).
"""

from __future__ import annotations

import math
from typing import Any

import numpy as np
from scipy.optimize import minimize_scalar

from backend.fitting import FitError, _json_safe

#: The most overhauls before a replacement searched by default (RePyability's own default is
#: 20 periods; N overhauls is N + 1 periods).
DEFAULT_MAX_OVERHAULS = 19
MAX_OVERHAULS = 60
#: Overhaul only: this many periods between resets stands in for "never replace" (the unit's age
#: settles within a few periods, so a reset this rare changes the rate by well under 0.1%).
_OVERHAUL_ONLY_PERIODS = 400
#: Lines drawn on the chart: N = 0 up to this many overhauls (plus the best N if it's beyond).
_CHART_LINES = 5
_GRID = 400


def _number(value, label: str, *, minimum: float = 0.0, strict: bool = False, required: bool = True):
    if value is None or value == "":
        if required:
            raise FitError(f"Enter the {label}.")
        return None
    try:
        v = float(value)
    except (TypeError, ValueError):
        raise FitError(f"The {label} must be a number.")
    if not math.isfinite(v) or v < minimum or (strict and v <= minimum):
        raise FitError(f"The {label} must be {'more than' if strict else 'at least'} {minimum:g}.")
    return v


def _model(model_or_params):
    """A minimal-repair model exposing ``cif``: a live surpyval recurrence model or a
    ``{"model_id": form, "params": [...]}`` spec (recurrent._as_cif_model)."""
    from backend import recurrent as recurrent_fit

    return recurrent_fit._as_cif_model(model_or_params)


def _unit(model, cr: float, co: float):
    from repyability.repairable import Repairable

    rep = Repairable(model)
    rep.set_repair_and_overhaul_costs(cr, co)
    return rep


def _rate(rep, x, cycles: int, factor: float, cp: float) -> np.ndarray:
    with np.errstate(all="ignore"):
        out = rep.overhaul_replace_cost_rate(np.atleast_1d(np.asarray(x, dtype=float)), int(cycles), factor, cp)
    return np.asarray(out, dtype=float)


def best_interval(rep, cycles: int, factor: float, cp: float, scale: float) -> tuple[float, float]:
    """The interval X minimising RePyability's cost rate for ``cycles`` periods per replacement,
    and that rate: a log grid around ``scale``, widened while the minimum sits at an end, then a
    bounded refinement between the grid points either side. (inf, rate at the far end) when a
    longer interval keeps paying."""
    lo_exp, hi_exp = -2.5, 2.5
    for _ in range(6):
        grid = scale * np.logspace(lo_exp, hi_exp, _GRID)
        rates = _rate(rep, grid, cycles, factor, cp)
        rates = np.where(np.isfinite(rates), rates, np.inf)
        i = int(np.argmin(rates))
        if i == len(grid) - 1:
            if hi_exp >= 9:
                return math.inf, float(rates[-1])
            hi_exp += 2.5
            continue
        if i == 0:
            lo_exp -= 2.5
            continue
        res = minimize_scalar(lambda x: float(_rate(rep, x, cycles, factor, cp)[0]),
                              bounds=(float(grid[i - 1]), float(grid[i + 1])), method="bounded",
                              options={"xatol": 1e-9 * float(grid[i])})
        x = float(res.x)
        return x, float(_rate(rep, x, cycles, factor, cp)[0])
    return float(grid[i]), float(rates[i])


def _repairs_per_cycle(rep, x: float, cycles: int, factor: float, cp: float, rate: float) -> float:
    """Expected repairs over one replacement cycle, read back from the cost rate."""
    return max(0.0, (rate * cycles * x - (cycles - 1) * rep.co - cp) / rep.cr)


def _saving(other: float | None, best: float) -> float | None:
    if other is None or not math.isfinite(other) or other <= 0:
        return None
    return (other - best) / other * 100.0


def optimal_overhaul_replace(model_or_params, *, cost_repair, cost_overhaul, cost_replace, overhaul_restores,
                             unit: str | None = "", downtime_repair=None, downtime_overhaul=None,
                             downtime_replace=None, downtime_cost=None, max_overhauls=None) -> dict[str, Any]:
    """The best "overhaul every X, replace after N overhauls" rule, with the comparisons, the
    best X for each N and the cost-rate curves. ``overhaul_restores`` is the share of its age an
    overhaul takes off (0–100 %: 100 is as good as new). Downtimes are hours; ``downtime_cost``
    the cost of an hour down. Raises FitError with what to do for inputs it can't use."""
    cr0 = _number(cost_repair, "repair cost (per failure)", strict=True)
    co0 = _number(cost_overhaul, "overhaul cost", strict=True)
    cp0 = _number(cost_replace, "replacement cost", strict=True)
    restores = _number(overhaul_restores, "share of its age an overhaul takes off (%)")
    if restores > 100:
        raise FitError("The share of its age an overhaul takes off is a percentage, 0 to 100 (100: as good as new).")
    factor = 1.0 - restores / 100.0
    if factor >= 1.0:
        raise FitError("An overhaul that takes off none of the unit's age changes nothing: enter how much it "
                       "takes off, more than 0% (100% is as good as new).")
    rate_down = _number(downtime_cost, "cost of an hour down", required=False) or 0.0
    hours = {k: _number(v, f"downtime of {k}", required=False) or 0.0
             for k, v in (("a repair", downtime_repair), ("an overhaul", downtime_overhaul),
                          ("a replacement", downtime_replace))}
    if any(hours.values()) and not rate_down:
        raise FitError("Enter the cost of an hour down too, so the downtime can be costed (or leave the downtimes "
                       "blank).")
    cr = cr0 + hours["a repair"] * rate_down
    co = co0 + hours["an overhaul"] * rate_down
    cp = cp0 + hours["a replacement"] * rate_down
    if co <= cr:
        raise FitError("An overhaul must cost more than a repair (with its downtime): otherwise you'd overhaul at "
                       "every failure instead of repairing.")
    kmax = int(_number(max_overhauls, "most overhauls to search", required=False) or DEFAULT_MAX_OVERHAULS)
    if kmax < 1 or kmax > MAX_OVERHAULS:
        raise FitError(f"Search between 1 and {MAX_OVERHAULS} overhauls before a replacement.")
    max_cycles = kmax + 1

    model = _model(model_or_params)
    rep = _unit(model, cr, co)
    unit = str(unit or "").strip()
    try:
        with np.errstate(all="ignore"):
            policy = rep.optimal_overhaul_replace_policy(factor, cp, max_cycles=max_cycles)
    except NotImplementedError as exc:
        raise FitError(str(exc)) from exc
    except ValueError as exc:
        raise FitError(str(exc)) from exc

    base: dict[str, Any] = {
        "unit": unit,
        "method": "exact",
        "costs": {"repair": cr, "overhaul": co, "replace": cp, "downtime_cost": rate_down or None,
                  "downtime_hours": {"repair": hours["a repair"], "overhaul": hours["an overhaul"],
                                     "replace": hours["a replacement"]}},
        "overhaul_restores": restores,
        "overhaul_factor": factor,
        "max_overhauls": kmax,
        "assumptions": [
            "Each failure is repaired back to how it was just before (minimal repair): the model's failure "
            "rate keeps rising with the unit's age.",
            f"An overhaul takes off {restores:g}% of the unit's age; a replacement makes it new.",
            "Repairs, overhauls and replacements are counted at their cost; the model's clock stops while the "
            "unit is down, so downtime adds cost, not time.",
            "Costs are long-run averages over many replacement cycles.",
            "Run to failure replaces the unit at a failure for the replacement cost (with its downtime).",
        ],
        "warnings": [],
    }

    run_to_failure = _run_to_failure(model, cr, cp)

    if not math.isfinite(policy.interval):
        return _json_safe({
            **base, "pays": False, "best": None,
            "reason": "Failures don't get more frequent as this unit ages, so overhauls and replacements don't "
                      "pay: repair it when it fails.",
            "comparisons": [run_to_failure], "by_overhauls": [], "curve": None,
            "sentence": "Repair it when it fails: its failures don't get more frequent with age, so planned "
                        "overhauls and replacements only add cost.",
        })

    x_best, k_best, g_best = float(policy.interval), int(policy.cycles), float(policy.cost_rate)
    scale = x_best
    # The best X for each number of overhauls (N = K - 1), on RePyability's own cost rate.
    rows = []
    for k in range(1, max_cycles + 1):
        if k == k_best:
            x, g = x_best, g_best
        else:
            x, g = best_interval(rep, k, factor, cp, scale)
        rows.append({"overhauls": k - 1, "interval": x if math.isfinite(x) else None, "cost_rate": g,
                     "replace_every": k * x if math.isfinite(x) else None, "best": k == k_best})

    overhaul_only_x, overhaul_only_g = best_interval(rep, _OVERHAUL_ONLY_PERIODS, factor, co, scale)
    replace_only = rows[0]
    comparisons = [
        run_to_failure,
        {"id": "overhaul_only", "label": "Overhaul only, never replace",
         "interval": overhaul_only_x if math.isfinite(overhaul_only_x) else None, "cost_rate": overhaul_only_g},
        {"id": "replace_only", "label": "Replace only, no overhauls",
         "interval": replace_only["interval"], "cost_rate": replace_only["cost_rate"]},
    ]
    for c in comparisons:
        c["saving_pct"] = _saving(c.get("cost_rate"), g_best)

    repairs = _repairs_per_cycle(rep, x_best, k_best, factor, cp, g_best)
    best = {"interval": x_best, "overhauls": k_best - 1, "cycles": k_best, "replace_every": k_best * x_best,
            "cost_rate": g_best, "repairs_per_cycle": repairs}

    if k_best == max_cycles:
        base["warnings"].append(
            f"The best plan has the most overhauls searched ({kmax}): more might pay. Raise the most overhauls to "
            "search and compare.")
    others = [c for c in comparisons if c.get("cost_rate") is not None and math.isfinite(c["cost_rate"])]
    runner = min(others, key=lambda c: c["cost_rate"]) if others else None
    # A plan of another kind can be cheaper still: RePyability searches N up to the limit, and the
    # cost rate can dip again far beyond it (overhaul only), or a failure limit can beat any fixed
    # interval. Said plainly, never hidden.
    cheaper = runner if runner and runner["cost_rate"] < g_best * (1 - 1e-9) else None
    if cheaper:
        base["warnings"].append(
            f"{cheaper['label']} costs {(-cheaper['saving_pct']):.1f}% less than the best overhaul-and-replace "
            f"plan searched (up to {kmax} overhauls). Consider it, or raise the most overhauls to search.")

    # The curves: cost rate over X for N = 0 … a few (and the best N), around the best X.
    t = np.linspace(0.15 * x_best, 3.0 * x_best, 120)
    shown = sorted({*range(0, min(_CHART_LINES, kmax) + 1), k_best - 1})
    series = []
    for n in shown:
        g = _rate(rep, t, n + 1, factor, cp)
        series.append({"overhauls": n, "cost_rate": [float(v) if math.isfinite(v) else None for v in g]})

    return _json_safe({
        **base, "pays": True, "best": best, "comparisons": comparisons, "by_overhauls": rows,
        "runner_up": runner["id"] if runner else None,
        "cheaper": cheaper["id"] if cheaper else None,
        "curve": {"t": t.tolist(), "series": series},
        "sentence": _sentence(best, unit, runner),
    })


def _run_to_failure(model, cr: float, cp: float) -> dict[str, Any]:
    """Repair each failure and replace at the n-th (the best n): RePyability's failure-limit
    policy with the replacement as the renewal. A replacement no dearer than a repair means
    replacing at every failure."""
    out: dict[str, Any] = {"id": "run_to_failure", "label": "Run to failure: repair, then replace at a failure"}
    try:
        with np.errstate(all="ignore"):
            if cp <= cr:
                rep = _unit(model, cp * 0.5, cp) if cp > 0 else None
                t1 = float(rep.expected_time_to_nth_failure(1)) if rep is not None else math.nan
                out.update(failure_count=1, cost_rate=cp / t1 if t1 > 0 else None)
            else:
                rep = _unit(model, cr, cp)
                p = rep.optimal_failure_limit_policy()
                out.update(failure_count=int(p.failure_count), cost_rate=float(p.cost_rate))
    except (ValueError, ArithmeticError) as exc:
        out.update(cost_rate=None, reason=f"No long-run cost: {exc}")
    return out


def _fmt(v: float) -> str:
    from backend.services.strategy import fmt_num

    return fmt_num(v)


def _sentence(best: dict, unit: str, runner: dict | None) -> str:
    from backend.units import unit_in_text

    u = f" {unit_in_text(unit)}" if unit else ""
    x = f"{_fmt(best['interval'])}{u}"
    if best["overhauls"] == 0:
        plan = f"Replace every {x}; overhauls don't pay"
    else:
        n = best["overhauls"]
        plan = (f"Overhaul every {x} and replace the unit after {n} overhaul{'s' if n != 1 else ''} "
                f"(every {_fmt(best['replace_every'])}{u})")
    if runner and runner.get("saving_pct") is not None and runner["saving_pct"] < 0:
        return (f"{plan}: the best overhaul-and-replace plan. But {runner['label'].lower()} costs "
                f"{-runner['saving_pct']:.0f}% less again.")
    if runner and runner.get("saving_pct") is not None and runner["saving_pct"] > 0.05:
        return f"{plan}. That costs {runner['saving_pct']:.0f}% less than the next best: {runner['label'].lower()}."
    return f"{plan}."


#: The inputs a call, and a saved analysis, takes (besides the model).
INPUTS = ("cost_repair", "cost_overhaul", "cost_replace", "overhaul_restores", "unit", "downtime_repair",
          "downtime_overhaul", "downtime_replace", "downtime_cost", "max_overhauls")


def from_inputs(inputs: dict, live=None) -> dict[str, Any]:
    """Run it from an endpoint body or a saved analysis's inputs: the model is ``live`` (a saved
    repairable model, read by the caller) or ``form`` + ``params`` (crow_amsaa, duane, hpp,
    cox_lewis; params as numbers or ``{name, value}``)."""
    if live is None:
        form = str(inputs.get("form") or "").strip()
        params = inputs.get("params") or []
        if not form or not params:
            raise FitError("Choose a saved repairable model, or enter the model's form and parameters.")
        live = {"model_id": form, "params": params}
    return optimal_overhaul_replace(live, **{k: inputs.get(k) for k in INPUTS})


def headline(results: dict) -> str:
    """One line for a saved analysis' list row."""
    from backend.units import unit_in_text

    best = (results or {}).get("best")
    if not best:
        return "Repair on failure: overhauls don't pay"
    u = f" {unit_in_text(results.get('unit'))}" if results.get("unit") else ""
    if best["overhauls"] == 0:
        return f"Replace every ~{_fmt(best['interval'])}{u}"
    return f"Overhaul every ~{_fmt(best['interval'])}{u}, replace after {best['overhauls']}"
