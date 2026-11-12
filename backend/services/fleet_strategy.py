"""A fleet forecast under a maintenance strategy: run to failure, or replace at an age.

The renewals forecast (:mod:`backend.services.fleet`) counts failures with each
failed item replaced by a new one: run to failure. With a planned-replacement
strategy each item is also replaced when it reaches ``replace_at`` (in the
model's unit) without failing, and an item already past that age is replaced
straight away (the catch-up, in the first period). The forecast then counts
failures and planned replacements apart, the parts they need between them, and,
with prices, what they cost: per period, per year and over the horizon, each
with its 90% range from the simulation.

The simulation is the renewal-reward process of age replacement, drawn per
item: the item in service's remaining life given its age, then new ones'
lives, each cut short at ``replace_at``. Seeded, so the same fleet gives the
same forecast.
"""

from __future__ import annotations

import math
from typing import Optional

import numpy as np

from backend.levels import Q_HIGH, Q_LOW

STRATEGIES = ("run_to_failure", "age")
_SIMS = 2000
_MAX_DRAWS = 2_000_000  # items × runs
_MAX_EVENTS = 20_000_000
_DAYS_A_YEAR = 365.25


class StrategyInputError(ValueError):
    """Strategy settings that can't be used; the message says what to change."""


def _number(value, label: str, *, positive: bool = False) -> Optional[float]:
    if value is None or value == "":
        return None
    try:
        v = float(value)
    except (TypeError, ValueError):
        raise StrategyInputError(f"{label} must be a number.") from None
    if not math.isfinite(v) or v < 0 or (positive and v == 0):
        raise StrategyInputError(f"{label} must be {'more than 0' if positive else 'at least 0'}.")
    return v


def clean(settings: dict) -> dict:
    """The strategy keys of a fleet's settings, checked: ``strategy``
    (run_to_failure or age), ``replace_at`` (the age, in the model's unit; an
    age strategy needs it) and the prices ``failure_cost`` / ``planned_cost``.
    Only the keys that are set come back, so a fleet without them keeps
    exactly the settings it had."""
    out: dict = {}
    kind = settings.get("strategy") or "run_to_failure"
    if kind not in STRATEGIES:
        raise StrategyInputError(f"Unknown strategy '{kind}' (run_to_failure or age).")
    replace_at = _number(settings.get("replace_at"), "The replacement age", positive=True)
    if kind == "age":
        if replace_at is None:
            raise StrategyInputError("Planned replacement needs the age to replace at, in the model's unit.")
        if settings.get("method", "renewals") != "renewals":
            raise StrategyInputError("Planned replacement counts replaced items: set the counting method to "
                                     "failures with replacement.")
        out["strategy"] = "age"
    if replace_at is not None:
        out["replace_at"] = replace_at
    for key, label in (("failure_cost", "The cost of a failure"), ("planned_cost", "The cost of a planned "
                                                                                     "replacement")):
        v = _number(settings.get(key), label)
        if v is not None:
            out[key] = v
    return out


def periods_a_year(period_days: Optional[float]) -> Optional[float]:
    return None if not period_days else _DAYS_A_YEAR / period_days


def _years(periods: int, period_days: Optional[float]) -> Optional[list[list[int]]]:
    """The periods (0-based) in each year from now, or None when the period
    label isn't a length of time (or a period is longer than a year)."""
    if not period_days or period_days > _DAYS_A_YEAR + 1e-9:
        return None
    groups: dict[int, list[int]] = {}
    for k in range(periods):
        groups.setdefault(int(math.floor(k * period_days / _DAYS_A_YEAR + 1e-9)), []).append(k)
    return [groups[y] for y in sorted(groups)]


def _spread(samples: np.ndarray) -> dict:
    samples = np.asarray(samples, dtype=float)
    lo, hi = np.quantile(samples, [Q_LOW, Q_HIGH]) if samples.size else (0.0, 0.0)
    return {"expected": float(samples.mean()) if samples.size else 0.0, "interval": [float(lo), float(hi)]}


def simulate(dist, ages, rates, periods: int, replace_at: Optional[float], *, seed: int = 12345) -> dict:
    """Every replacement in a simulation over ``periods``: its run (``sim``),
    time in periods from now (``t``, ascending), item (``item``) and whether it
    was planned (``planned``) rather than a failure. ``replace_at`` None is
    run to failure."""
    ages = np.asarray(ages, dtype=float)
    rates = np.asarray(rates, dtype=float)
    n = len(ages)
    sims = max(200, min(_SIMS, _MAX_DRAWS // max(n, 1)))
    runs, times, which, planned_flags, total = [], [], [], [], 0
    for i in range(n):
        a, rate = float(ages[i]), float(rates[i])
        use = rate * periods
        if rate <= 0 or use <= 0:
            continue
        rng = np.random.default_rng([seed, i])
        elapsed = np.zeros(sims)
        if replace_at is not None and a >= replace_at:
            # Already past the age: replaced now (the catch-up).
            gap = np.zeros(sims)
            planned = np.ones(sims, dtype=bool)
        else:
            sf_a = max(float(dist.sf(a)), 1e-12)
            ff_a = float(dist.ff(a))
            life = np.asarray(dist.qf(ff_a + rng.uniform(size=sims) * sf_a), dtype=float) - a
            life = np.nan_to_num(life, nan=np.inf, posinf=np.inf)
            if replace_at is None:
                gap, planned = life, np.zeros(sims, dtype=bool)
            else:
                left = replace_at - a
                planned = life >= left
                gap = np.where(planned, left, life)
        elapsed = elapsed + np.maximum(gap, 0.0)
        alive = elapsed < use
        while alive.any():
            idx = np.flatnonzero(alive)
            runs.append(idx.astype(np.int32))
            times.append(elapsed[idx] / rate)
            which.append(np.full(idx.size, i, dtype=np.int32))
            planned_flags.append(planned[idx].copy())
            total += idx.size
            if total > _MAX_EVENTS:
                raise StrategyInputError("Too many replacements to simulate over this horizon: the lives (or the "
                                         "replacement age) are very short for it.")
            life = np.asarray(dist.qf(rng.uniform(size=sims)[idx]), dtype=float)
            life = np.maximum(np.nan_to_num(life, nan=np.inf, posinf=np.inf), 0.0)
            if replace_at is None:
                step, now_planned = life, np.zeros(idx.size, dtype=bool)
            else:
                now_planned = life >= replace_at
                step = np.where(now_planned, replace_at, life)
            elapsed[idx] += step
            planned[idx] = now_planned
            alive[idx] = elapsed[idx] < use
    if not runs:
        empty = np.zeros(0)
        return {"sims": sims, "sim": empty.astype(np.int32), "t": empty, "item": empty.astype(np.int32),
                "planned": empty.astype(bool)}
    t = np.concatenate(times)
    order = np.argsort(t, kind="stable")
    return {"sims": sims, "sim": np.concatenate(runs)[order], "t": t[order],
            "item": np.concatenate(which)[order], "planned": np.concatenate(planned_flags)[order]}


def _per_sim_period(events: dict, periods: int, mask: np.ndarray) -> np.ndarray:
    """Counts (sims × periods) of the events in ``mask``."""
    sims = events["sims"]
    out = np.zeros((sims, periods))
    k = np.minimum(np.floor(events["t"][mask]).astype(int), periods - 1)
    np.add.at(out, (events["sim"][mask], k), 1.0)
    return out


def summarise(failures: np.ndarray, planned: Optional[np.ndarray], periods: int, period_days: Optional[float],
              failure_cost: Optional[float], planned_cost: Optional[float]) -> dict:
    """Totals, per period and per year, each with its 90% range, from per-run
    counts (sims × periods) of failures and (for an age strategy) planned
    replacements; with prices, what they cost."""
    planned = np.zeros_like(failures) if planned is None else planned
    parts = failures + planned
    priced = failure_cost is not None or (planned_cost is not None and planned.any())
    cost = None
    if priced:
        cost = failures * (failure_cost or 0.0) + planned * (planned_cost or 0.0)

    def block(cols) -> dict:
        row = {"failures": _spread(failures[:, cols].sum(axis=1)),
               "planned": _spread(planned[:, cols].sum(axis=1)),
               "parts": _spread(parts[:, cols].sum(axis=1))}
        if cost is not None:
            row["cost"] = _spread(cost[:, cols].sum(axis=1))
        return row

    every = list(range(periods))
    out = {"total": block(every),
           "per_period": [{"period": k + 1, **block([k])} for k in every]}
    groups = _years(periods, period_days)
    out["yearly"] = None if groups is None else [
        {"year": y + 1, "from_period": g[0] + 1, "to_period": g[-1] + 1, "complete": _full_year(g, period_days),
         **block(g)} for y, g in enumerate(groups)]
    return out


def _full_year(group: list[int], period_days: float) -> bool:
    return abs(len(group) * period_days - _DAYS_A_YEAR) < period_days / 2


def forecast_age(dist, ages, rates, periods: int, items, replace_at: float) -> dict:
    """The renewals forecast's fields (failures) under age replacement at
    ``replace_at``, plus ``planned`` and the simulated ``events`` (for the
    spares answer: every part, planned or not)."""
    events = simulate(dist, ages, rates, periods, replace_at)
    sims = events["sims"]
    fail = ~events["planned"]
    fails = _per_sim_period(events, periods, fail)
    plans = _per_sim_period(events, periods, events["planned"])
    n = len(items)
    fail_by_item = np.bincount(events["item"][fail], minlength=n) / sims
    plan_by_item = np.bincount(events["item"][~fail], minlength=n) / sims
    # An item's chance of at least one failure: the runs in which it fails.
    any_fail = np.zeros(n)
    if fail.any():
        pairs = np.unique(np.stack([events["item"][fail], events["sim"][fail]]), axis=1)
        any_fail = np.bincount(pairs[0], minlength=n) / sims
    per_fail = fails.sum(axis=1)
    lo, hi = np.percentile(per_fail, [Q_LOW * 100, Q_HIGH * 100])
    plan_total = plans.sum(axis=1)
    p_lo, p_hi = np.percentile(plan_total, [Q_LOW * 100, Q_HIGH * 100])
    catch_up = int(np.sum(np.asarray(ages, float) >= replace_at)) if len(items) else 0
    return {
        "expected": float(per_fail.mean()),
        "interval": [float(lo), float(hi)],
        "sims": sims,
        "per_item": [{"id": it["id"], "expected": float(fail_by_item[i]), "planned": float(plan_by_item[i]),
                      "prob_any": float(any_fail[i]), "overdue": bool(float(ages[i]) >= replace_at)}
                     for i, it in enumerate(items)],
        "per_period": [float(x) for x in fails.mean(axis=0)],
        "planned": {"expected": float(plan_total.mean()), "interval": [float(p_lo), float(p_hi)],
                    "per_period": [float(x) for x in plans.mean(axis=0)], "catch_up": catch_up},
        "_counts": (fails, plans),
        "_events": events,
    }


def renewals(dist, ages, uses, rates, periods: int, items, settings: dict, run_to_failure, period_days) -> dict:
    """The renewals forecast under the fleet's strategy: run to failure
    (``run_to_failure``, the fleet's own simulation, its numbers unchanged) or
    age replacement; either way with ``strategy``: totals, per period and per
    year with their ranges, and costs when priced."""
    kind = settings.get("strategy") or "run_to_failure"
    replace_at = settings.get("replace_at") if kind == "age" else None
    failure_cost, planned_cost = settings.get("failure_cost"), settings.get("planned_cost")
    if replace_at is not None:
        out = forecast_age(dist, ages, rates, periods, items, float(replace_at))
        fails, plans = out.pop("_counts")
        out.pop("_events", None)
    else:
        out = run_to_failure(dist, ages, uses, rates, periods, items, weights=np.ones((len(items), 1)))
        tally = out.pop("tally", None)
        fails = np.zeros((out.get("sims", 1), periods)) if tally is None else np.asarray(tally[:, :, 0], float)
        plans = None
    summary = summarise(fails, plans, periods, period_days, failure_cost, planned_cost if replace_at else None)
    out["strategy"] = {
        "kind": "age" if replace_at is not None else "run_to_failure",
        "replace_at": replace_at,
        "failure_cost": failure_cost,
        "planned_cost": planned_cost if replace_at is not None else None,
        "catch_up": (out.get("planned") or {}).get("catch_up", 0),
        **summary,
    }
    return out
