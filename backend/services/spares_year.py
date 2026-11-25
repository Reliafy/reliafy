"""Spares for the year: each part's demand over a horizon, failures plus planned replacements,
against its stock and lead time.

One engine for every place the question is asked (a stand-alone analysis, a position or location
and everything under it, a position class, a product's design): the callers say what each unit is
(its life model, its age, how fast it ages, the planned jobs falling due on it and the parts each
job uses), and this works out the demand.

The rule, stated with every answer (:data:`RULE`):

* demand over a window = the planned replacements falling due in it + the failures in it. The
  failures come from a renewal simulation from each unit's age: a failed unit is replaced at once
  and the new one can fail again; a planned replacement renews it too, so it takes failures off.
  A planned job done only on an older unit (a shutdown's "only if older than") is skipped when the
  unit is younger then (it failed and was replaced shortly before);
* hold = the smallest stock with at least the service level's chance of covering the demand over
  the lead time (plus the review period); reorder at = the same over the lead time alone;
* order now = hold - usable now (not below 0); each planned job past the lead time that the stock
  left over doesn't cover is ordered by its date less the lead time;
* buy for the year = expected demand over the horizon + the hold's buffer - usable now, rounded up
  (not below 0). The buffer is the hold less the planned replacements in its window: those are in
  the demand already, so adding the whole hold bought each of them twice. The high case puts the
  demand's 90th percentile in place of the expected.

The simulation follows ``services.fleet._renewal_events`` draw for draw (each unit its own seeded
stream, one draw a round), so a unit with no planned jobs fails at the same times there and here:
the class forecast's spares and this answer agree where both apply. Time is in days from now; a
unit ages ``per_day`` of its model's unit a day (calendar, an operating plan's average or a
counter's recent rate: the caller's).
"""

from __future__ import annotations

import math
from datetime import date, timedelta

import numpy as np

from backend.services import spares

SIMS = 4000
MAX_DRAWS = 4_000_000  # units x runs
MAX_EVENTS = 20_000_000
YEAR_DAYS = 12 * 30.4375  # the class forecast's 12 months
Q_LOW, Q_HIGH = 0.1, 0.9  # the demand's likely range, as the class Spares tab gives it (P10-P90)
_TINY = 1e-9

RULE = ("Demand = planned replacements falling due + failures (a renewal simulation from each part's age: "
        "a failed part is replaced and can fail again; a planned replacement renews it). Hold = the smallest "
        "stock with at least the service level's chance of covering the demand over the lead time. Order now = "
        "hold - usable now. Buy for the year = expected demand + the hold's buffer (the hold less the planned "
        "replacements it already covers, which are in the demand) - usable now, rounded up.")


class SparesYearError(ValueError):
    """An input the answer can't use (the message says why)."""


def simulate(units: list[dict], horizon_days: float, sims: int | None = None) -> dict:
    """Every failure and planned job in [0, horizon_days) in each run.

    Each unit: ``seed`` (its own stream; by default its index, as the fleet's), ``dist`` (a SurPyval-like life with ``sf``, ``ff`` and ``qf``, or None: planned jobs
    only), ``age`` and ``per_day`` (in the life's unit), ``planned`` ([{day, min_age (life unit, or
    None), renews (bool)}], in date order). Returns {sims, sim, t (days), unit, kind (0 failure,
    1 planned), job (the planned job's index in its unit's list; -1 for a failure)}, by time."""
    n = len(units)
    if sims is None:
        sims = max(500, min(SIMS, MAX_DRAWS // max(n, 1)))
    runs, times, which, kinds, jobs = [], [], [], [], []
    total = 0

    def keep(idx, t, i, kind, job):
        nonlocal total
        runs.append(idx.astype(np.int32))
        times.append(np.asarray(t, dtype=float))
        which.append(np.full(idx.size, i, dtype=np.int32))
        kinds.append(np.full(idx.size, kind, dtype=np.int8))
        jobs.append(np.asarray(job, dtype=np.int32) if np.ndim(job) else np.full(idx.size, job, dtype=np.int32))
        total += idx.size
        if total > MAX_EVENTS:
            raise SparesYearError("Too many failures to simulate over this horizon: the lives are very short for it.")

    everyone = np.arange(sims)
    for i, u in enumerate(units):
        plans = [p for p in (u.get("planned") or []) if 0 <= float(p["day"]) < horizon_days]
        rate = float(u.get("per_day") or 0.0)
        dist = u.get("dist")
        age = float(u.get("age") or 0.0)
        if dist is None or rate <= 0:
            # Nothing to fail (no life model, or it doesn't age): the planned jobs, in every run.
            installed = -age
            for j, p in enumerate(plans):
                model_t = float(p["day"]) * rate
                if p.get("min_age") is not None and model_t - installed < float(p["min_age"]) - _TINY:
                    continue
                keep(everyone, np.full(sims, float(p["day"])), i, 1, j)
                if p.get("renews", True):
                    installed = model_t
            continue
        use = rate * horizon_days
        plan_t = np.array([float(p["day"]) * rate for p in plans] + [np.inf])
        plan_day = np.array([float(p["day"]) for p in plans] + [np.inf])
        min_age = np.array([-np.inf if p.get("min_age") is None else float(p["min_age"]) for p in plans] + [0.0])
        renews = np.array([bool(p.get("renews", True)) for p in plans] + [False])
        rng = np.random.default_rng([12345, int(u.get("seed", i))])
        sf_a = max(float(dist.sf(age)), 1e-12)
        ff_a = float(dist.ff(age))
        elapsed = np.asarray(dist.qf(ff_a + rng.uniform(size=sims) * sf_a), dtype=float) - age
        elapsed = np.nan_to_num(elapsed, nan=np.inf, posinf=np.inf)
        installed = np.full(sims, -age)
        nxt = np.zeros(sims, dtype=np.int64)  # each run's next planned job
        active = np.ones(sims, dtype=bool)
        while True:
            at_plan = plan_t[nxt]
            fail = active & (elapsed < use) & (elapsed < at_plan)
            plan = active & ~fail & (at_plan < use)
            active = fail | plan
            if not active.any():
                break
            draws = rng.uniform(size=sims)
            idx = np.flatnonzero(fail)
            if idx.size:
                keep(idx, elapsed[idx] / rate, i, 0, -1)
                installed[idx] = elapsed[idx]
                fresh = np.asarray(dist.qf(draws[idx]), dtype=float)
                elapsed[idx] += np.maximum(np.nan_to_num(fresh, nan=np.inf, posinf=np.inf), 0.0)
            idx = np.flatnonzero(plan)
            if idx.size:
                job = nxt[idx]
                ok = (at_plan[idx] - installed[idx]) >= min_age[job] - _TINY
                done = idx[ok]
                if done.size:
                    keep(done, plan_day[job[ok]], i, 1, job[ok])
                    again = done[renews[job[ok]]]
                    if again.size:
                        tp = plan_t[nxt[again]]
                        installed[again] = tp
                        fresh = np.asarray(dist.qf(draws[again]), dtype=float)
                        elapsed[again] = tp + np.maximum(np.nan_to_num(fresh, nan=np.inf, posinf=np.inf), 0.0)
                nxt[idx] += 1
    if not runs:
        empty = np.zeros(0, np.int32)
        return {"sims": sims, "sim": empty, "t": np.zeros(0), "unit": empty, "kind": np.zeros(0, np.int8),
                "job": empty}
    t = np.concatenate(times)
    order = np.argsort(t, kind="stable")
    return {"sims": sims, "sim": np.concatenate(runs)[order], "t": t[order], "unit": np.concatenate(which)[order],
            "kind": np.concatenate(kinds)[order], "job": np.concatenate(jobs)[order]}


def part_weights(events: dict, units: list[dict], key) -> np.ndarray:
    """How many of part ``key`` each event uses: a failure the unit's ``fail_parts[key]``, a planned
    job its own ``parts[key]``."""
    fail = np.array([float((u.get("fail_parts") or {}).get(key, 0.0)) for u in units] or [0.0])
    offsets = np.cumsum([0] + [len(u.get("planned") or []) for u in units])
    flat = np.array([float((p.get("parts") or {}).get(key, 0.0)) for u in units for p in (u.get("planned") or [])]
                    + [0.0])
    if events["t"].size == 0:
        return np.zeros(0)
    unit, kind, job = events["unit"], events["kind"], events["job"]
    planned = flat[np.where(kind == 1, offsets[unit] + np.maximum(job, 0), len(flat) - 1)]
    return np.where(kind == 1, planned, fail[unit])


def window(events: dict, weights: np.ndarray, start: float, end: float, kind: int | None = None) -> np.ndarray:
    """Each run's demand in [start, end) days from now (only failures or only planned jobs with
    ``kind`` 0 or 1)."""
    t = events["t"]
    lo, hi = np.searchsorted(t, [start, end], side="left")
    w = weights[lo:hi]
    if kind is not None:
        w = np.where(events["kind"][lo:hi] == kind, w, 0.0)
    return np.bincount(events["sim"][lo:hi], weights=w, minlength=events["sims"]).astype(float)


def waiting(events: dict, weights: np.ndarray, units: list[dict], key, start: float, end: float,
            pool: bool = False) -> spares.Waiting:
    """How the units using part ``key`` wait for it over [start, end) days: a shortfall counted run
    by run (a unit down once the stock is used up fails no more), or a pool's units for its
    reweighting. A pool's is exact for alike units on one constant rate with no planned jobs using
    the part; a shortfall's for any lives with none (a planned job left undone keeps its unit
    running on the old part, which the runs don't follow)."""
    qty = [float((u.get("fail_parts") or {}).get(key, 0.0)) for u in units]
    users = [u for u, q in zip(units, qty) if q > 0]
    per = float(np.mean([q for q in qty if q > 0])) if users else 1.0
    t = events["t"]
    lo, hi = np.searchsorted(t, [start, end], side="left")
    planned = bool(np.any((events["kind"][lo:hi] == 1) & (weights[lo:hi] > 0)))
    if pool:
        rates = {round(spares.constant_hazard(u["dist"]) or -1.0, 12) if u.get("dist") is not None else -1.0
                 for u in users}
        alike = (not planned and len({q for q in qty if q > 0}) <= 1 and -1.0 not in rates and len(rates) <= 1
                 and len({float(u.get("per_day") or 0.0) for u in users}) <= 1)
        return spares.Waiting(len(users), per, exact=alike)
    sim, unit, w = events["sim"][lo:hi], events["unit"][lo:hi], weights[lo:hi]
    fails = events["kind"][lo:hi] == 0
    return spares.Waiting(len(users), per, exact=not planned,
                          short=lambda st: spares.runs_short(sim, unit, w, events["sims"], st, fails))


def _q(values: np.ndarray, q: float) -> float:
    return float(np.quantile(values, q, method="inverted_cdf")) if values.size else 0.0


def _day(today: date, days: float) -> str:
    return (today + timedelta(days=math.floor(days + _TINY))).isoformat()


def _jobs(events: dict, weights: np.ndarray, units: list[dict], key, horizon: float) -> list[dict]:
    """The planned jobs using the part: each one's date, how many it uses, and the chance it's done
    (below 1 when it's done only on an older unit)."""
    sims = events["sims"]
    out = []
    planned = (events["kind"] == 1) & (weights > 0)
    for i, u in enumerate(units):
        for j, p in enumerate(u.get("planned") or []):
            qty = float((p.get("parts") or {}).get(key, 0.0))
            if qty <= 0 or not 0 <= float(p["day"]) < horizon:
                continue
            hit = planned & (events["unit"] == i) & (events["job"] == j)
            out.append({"day": float(p["day"]), "qty": qty, "chance": float(np.count_nonzero(hit)) / sims,
                        "label": p.get("label") or "", "unit": u.get("label") or "",
                        **{k: p[k] for k in ("task", "position", "package") if p.get(k)}})
    return sorted(out, key=lambda x: (x["day"], x["unit"], x["label"]))


def order_plan(jobs: list[dict], usable: float, hold: float, order_now: float, window_days: float,
               lead_days: float, today: date) -> list[dict]:
    """When to order for the planned jobs past the hold's window: the stock left over (usable now +
    what's ordered now - the hold) covers the first; each one it doesn't is ordered by its date less
    the lead time. A job done only on an older unit counts at its chance of being done."""
    free = usable + order_now - hold
    need, ordered, out = 0.0, 0.0, []
    for job in jobs:
        if job["day"] < window_days - _TINY:
            continue  # in the hold already
        need += job["qty"] * job["chance"]
        short = math.ceil(need - 1e-6) - free - ordered
        if short > 0:
            ordered += short
            by = max(0.0, job["day"] - lead_days)
            out.append({"qty": float(short), "by": _day(today, by), "for": _day(today, job["day"]),
                        "job": job["label"], "unit": job["unit"]})
    return out


def buy(demand: float, hold: float, planned_in_hold: float, usable: float) -> float:
    """What to buy over the horizon: its demand, plus the stock to have at its end, less what's usable now.
    The stock at the end is the hold's buffer: the hold less the planned replacements falling in its window,
    which the demand already counts (counting them in both bought each planned replacement twice)."""
    buffer = max(0.0, hold - max(0.0, planned_in_hold))
    return max(0.0, float(math.ceil(demand + buffer - usable - 1e-9)))


def answer_part(events: dict, units: list[dict], key, *, horizon_days: float, lead_days: float, level: float,
                usable: float, review_days: float = 0.0, today: date, months: int | None = None) -> dict:
    """One part's answer: its demand over the horizon (failures and planned), the stock to hold over
    its lead time (plus review), the risk at the stock usable now, what to order now and by when,
    and what to buy over the horizon."""
    weights = part_weights(events, units, key)
    total = window(events, weights, 0.0, horizon_days)
    fails = window(events, weights, 0.0, horizon_days, kind=0)
    planned = window(events, weights, 0.0, horizon_days, kind=1)
    protect_days = lead_days + review_days
    protect = spares.Demand.from_samples(window(events, weights, 0.0, protect_days)).with_waiting(
        waiting(events, weights, units, key, 0.0, protect_days))
    lead = spares.Demand.from_samples(window(events, weights, 0.0, lead_days))
    ans = spares.answer(protect, lead, usable, level)
    hold = ans["hold"]
    order_now = max(0.0, hold - usable)
    jobs = _jobs(events, weights, units, key, horizon_days)
    by = order_plan(jobs, usable, hold, order_now, protect_days, lead_days, today)
    mean = float(total.mean()) if total.size else 0.0
    p90 = _q(total, Q_HIGH)
    in_window = spares.Demand.from_samples(window(events, weights, 0.0, protect_days, kind=1)).mean
    out = {
        "demand": {"mean": mean, "p10": _q(total, Q_LOW), "p50": _q(total, 0.5), "p90": p90,
                   "failures": float(fails.mean()) if fails.size else 0.0,
                   "planned": float(planned.mean()) if planned.size else 0.0},
        "lead_window": {"days": protect_days, "mean": protect.mean, "planned": in_window,
                        "failures": protect.mean - in_window},
        "hold": hold, "reorder_at": ans["reorder_at"], "usable_now": usable,
        "risk_at_stock": ans.get("risk_at_stock"), "expected_short": ans.get("expected_short"),
        **({"waiting": ans["waiting"]} if "waiting" in ans else {}),
        "risk_curve": ans.get("risk_curve"),
        "order_now": order_now, "arrives": _day(today, lead_days) if order_now > 0 else None,
        "order_by": by,
        "buy_for_year": buy(mean, hold, in_window, usable),
        "buy_high_case": buy(p90, hold, in_window, usable),
        "jobs": [{**j, "date": _day(today, j["day"])} for j in jobs],
    }
    if months:
        step = horizon_days / months
        out["by_month"] = [{"start": _day(today, k * step),
                            "mean": float(window(events, weights, k * step, (k + 1) * step).mean()),
                            "planned": float(window(events, weights, k * step, (k + 1) * step, kind=1).mean())}
                           for k in range(months)]
    return out


def chance_short_before(events: dict, units: list[dict], key, stock: float, days: float) -> float:
    """The chance more of the part is wanted (planned and failures) before ``days`` than ``stock``."""
    weights = part_weights(events, units, key)
    return spares.Demand.from_samples(window(events, weights, 0.0, days)).prob_short(stock)


def words(row: dict, part_label: str, level: float, lead_days: float, horizon_words: str, unit: str = "") -> str:
    """The answer in words, the number first."""
    d = row["demand"]
    each = f" {unit}" if unit and unit != "each" else ""
    text = (f"{part_label}: about {_n(d['mean'])}{each} over {horizon_words} (likely {d['p10']:g}–{d['p90']:g})")
    if d["planned"] > _TINY:
        text += f": {_n(d['failures'])} failures + {_n(d['planned'])} planned"
    text += (f". Hold {row['hold']:g}: a {spares.level_text(level)} chance of no stock-out over the lead time "
             f"({lead_days:g} days). {row['usable_now']:g} usable now")
    if row.get("risk_at_stock") is not None:
        text += f", a {spares.pct(row['risk_at_stock'])} chance of running out"
    text += "."
    if row["order_now"] > 0:
        text += f" Order {row['order_now']:g} now (arriving about {_short(row['arrives'])})."
    for o in row["order_by"][:3]:
        text += f" Order {o['qty']:g} by {_short(o['by'])} for {_short(o['for'])}."
    return text


def _n(v: float) -> str:
    v = float(v)
    if abs(v) >= 10:
        return f"{v:,.0f}"
    return f"{v:.2g}" if abs(v) < 1 else f"{v:.2f}".rstrip("0").rstrip(".")


def _short(day: str | None) -> str:
    if not day:
        return ""
    d = date.fromisoformat(day)
    return f"{d.day} {d.strftime('%b')} {d.year}"
