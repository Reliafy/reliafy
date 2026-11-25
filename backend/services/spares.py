"""Spares stock levels from a failure forecast's demand (#31).

A forecast gives a part's demand over a window as a distribution: the raw
totals of a simulation (one per run), or an exact count (first failures are a
Poisson-binomial count, a repairable fleet's failures a Poisson one). From it,
never a normal approximation:

- hold N: the smallest stock with at least the service level's chance of
  covering the demand over the protection window, the replenishment lead time
  plus the review period (how often stock is checked; 0 = as soon as it falls to
  the reorder point). A stock-out is more demand in the window than the stock.
- reorder at: the same over the lead time alone. When usable stock falls to it,
  order back up to N. With no review period it equals N: order one for one.
- for a stock level: the chance it runs out over the window, and how many it is
  expected to be short.
- a repairable spare (a rotable) whose failed units come back after a repair
  turnaround: one for one, so the pool to keep is the demand over the turnaround
  (the single-site pipeline of Palm's theorem, read off the distribution). It is
  one site with one repair shop, and every unit sent away comes back.

A unit waiting for a spare is down, so it can't fail again until one comes (a
finite source, the machine-repairman model). The demand as a forecast gives it
takes no account of that, so two figures are worked out from it with the waits
in (:class:`Waiting`, set by the caller):

- a rotable pool: with ``S`` in the pool and ``k > S`` away, ``k - S`` units
  are waiting and only the rest can fail. The pipeline a random time finds is
  the demand over the turnaround reweighted by the share of units still up:
  ``P(k)`` times ``a_0 ... a_{k-1}``, ``a_j = (n - max(0, j - S)) / n`` (as
  RePyability's long-run ``spares_stock`` does). Exact for units with one
  constant failure rate, the same for each, replaced in no time, whatever the
  turnaround's distribution (it is insensitive to it); an approximation
  otherwise. It changes the pool to keep, its risk and its shortfall.
- the shortfall at a stock over a window with nothing arriving in it: once the
  stock is used up, a unit that fails stays down, so it is short one job at
  most. From a simulation, counted run by run (a down unit's later failures
  dropped); from a Poisson count, the pure-birth chain in closed form.

The chance of a stock-out over the window, and so hold N, the reorder point and
the risk curve, don't change: until the stock first runs out, no unit waits.

Quantiles are values the demand can take (whole failures times parts per job).
"""

from __future__ import annotations

import math

import numpy as np

DEFAULT_SERVICE_LEVEL = 0.95
MIN_SERVICE_LEVEL, MAX_SERVICE_LEVEL = 0.5, 0.999
MAX_LEAD_DAYS = 3 * 365.25  # a lead time, repair turnaround or review period, at most
CURVE_POINTS = 60  # stock levels in a risk curve, at most
_TINY = 1e-9


class SparesError(ValueError):
    """A spares input that can't be used."""


def service_level(value) -> float | None:
    """A target chance of no stock-out, from 0.5 to 0.999; a percentage (95) reads
    as 0.95. None when not given."""
    if value is None or value == "":
        return None
    try:
        level = float(value)
    except (TypeError, ValueError):
        raise SparesError("The service level must be a number, e.g. 0.95.") from None
    if 1 < level <= 100:
        level /= 100
    if not math.isfinite(level) or not MIN_SERVICE_LEVEL <= level <= MAX_SERVICE_LEVEL:
        raise SparesError("The service level is a chance of no stock-out from 0.5 to 0.999 (e.g. 0.95).")
    return level


def duration(value, what: str, most: float) -> float | None:
    """A non-negative length of time up to ``most``, or None when not given."""
    if value is None or value == "":
        return None
    try:
        out = float(value)
    except (TypeError, ValueError):
        raise SparesError(f"The {what} must be a number.") from None
    if not math.isfinite(out) or not 0 <= out <= most:
        raise SparesError(f"The {what} must be from 0 to {most:g}.")
    return out


class Waiting:
    """How a demand's units wait for a spare: ``units`` drawing on the stock
    (each failure using ``per`` parts), whether the figures with the waits in are
    ``exact`` for this case, and ``short`` (stock -> expected shortfall over the
    window, the waits in) when the caller can count it better than the pool's
    reweighting (a simulation's runs, a Poisson count)."""

    __slots__ = ("units", "per", "exact", "short")

    def __init__(self, units: int, per: float = 1.0, exact: bool = False, short=None):
        self.units = max(0, int(units))
        self.per = float(per) if per and per > 0 else 1.0
        self.exact = bool(exact)
        self.short = short

    def payload(self) -> dict:
        """What the result says about it."""
        return {"units": self.units, "exact": self.exact,
                "note": WAITING_EXACT if self.exact else WAITING_APPROX}


WAITING_EXACT = ("A unit waiting for a spare can't fail again until one comes; these figures take that in, "
                 "exactly for this case.")
WAITING_APPROX = ("A unit waiting for a spare can't fail again until one comes; these figures take that in, "
                  "approximately (exact for units with one constant failure rate, replaced in no time).")


class Demand:
    """A demand distribution over one window: the values it takes, ascending, and
    their chances. ``waiting`` (a :class:`Waiting`, set by the caller) says how its
    units wait for a spare: a pool's figures and the shortfall then take it in."""

    __slots__ = ("values", "probs", "cdf", "waiting")

    def __init__(self, values, probs, waiting: "Waiting | None" = None):
        self.values = np.asarray(values, dtype=float)
        self.probs = np.asarray(probs, dtype=float)
        self.cdf = np.cumsum(self.probs)
        self.waiting = waiting

    def with_waiting(self, waiting: "Waiting | None") -> "Demand":
        self.waiting = waiting
        return self

    @classmethod
    def from_samples(cls, samples) -> "Demand":
        """The raw totals of a simulation, one per run, each equally likely."""
        s = np.round(np.asarray(samples, dtype=float).ravel(), 9)
        if s.size == 0:
            return cls([0.0], [1.0])
        values, counts = np.unique(s, return_counts=True)
        return cls(values, counts / s.size)

    @classmethod
    def from_pmf(cls, pmf, per: float = 1.0) -> "Demand":
        """An exact count's distribution (pmf[k] = P(k failures)), each failure
        using ``per`` parts."""
        pmf = np.clip(np.nan_to_num(np.asarray(pmf, dtype=float).ravel()), 0.0, None)
        total = pmf.sum()
        if total <= 0:
            return cls([0.0], [1.0])
        return cls(np.arange(pmf.size) * float(per), pmf / total)

    @property
    def mean(self) -> float:
        return float((self.values * self.probs).sum())

    def quantile(self, level: float) -> float:
        """The smallest value the demand takes with P(demand <= it) >= level."""
        idx = int(np.searchsorted(self.cdf, level - _TINY, side="left"))
        return float(self.values[min(idx, self.values.size - 1)])

    def prob_short(self, stock: float) -> float:
        """P(demand > stock): the chance the stock runs out."""
        covered = int(np.searchsorted(self.values, stock + _TINY, side="right"))
        return float(max(0.0, 1.0 - (self.cdf[covered - 1] if covered else 0.0)))

    def expected_short(self, stock: float) -> float:
        """How many the stock is expected to be short: E[max(demand - stock, 0)]."""
        return float((np.maximum(self.values - stock, 0.0) * self.probs).sum())

    def curve(self, pool: bool = False) -> list[list[float]]:
        """[[stock, P(running out)], ...] from 0 to where the chance is under 0.1%
        (at most CURVE_POINTS levels), for a risk readout at any stock; a pool's
        with its units' waits in."""
        top = self.quantile(MAX_SERVICE_LEVEL)
        step = max(1, math.ceil(top / CURVE_POINTS))
        levels = np.arange(0, top + step, step, dtype=float)
        risk = self.pool_risk if pool else self.prob_short
        return [[float(s), round(risk(s), 6)] for s in levels]

    # ---- a rotable pool, its units waiting for a spare --------------------------

    def pooled(self, stock: float) -> "Demand":
        """The pipeline a random time finds with ``stock`` in the pool: the demand
        reweighted by the share of units still up (``a_j = (n - max(0, j - S)) /
        n`` for each job away past the ``S`` the pool covers). The demand itself
        when its units aren't known."""
        w = self.waiting
        if w is None or w.units <= 0 or self.values.size == 0:
            return self
        n = w.units
        jobs = np.rint(self.values / w.per).astype(np.int64)
        covered = math.floor(max(float(stock), 0.0) / w.per + _TINY)
        j = np.arange(int(jobs.max(initial=0)) + 1)
        going = np.clip(n - np.maximum(j - covered, 0), 0, None) / n
        reached = np.concatenate(([1.0], np.cumprod(going)[:-1]))
        probs = self.probs * reached[np.clip(jobs, 0, None)]
        if probs.sum() <= 0:
            return self
        return Demand(self.values, probs / probs.sum())

    def pool_risk(self, stock: float) -> float:
        """The chance a random time finds a unit waiting with ``stock`` in the pool."""
        return self.pooled(stock).prob_short(stock)

    def pool_short(self, stock: float) -> float:
        """How many the pool is short on average: the parts the waiting units want."""
        return self.pooled(stock).expected_short(stock)

    def hold(self, level: float, pool: bool = False) -> float:
        """Hold N: the smallest stock with at least ``level`` chance of covering
        the demand; a pool's with its units' waits in (never more than without)."""
        top = self.quantile(level)
        if not pool or self.waiting is None:
            return top
        steps = np.arange(0.0, top, self.waiting.per)
        for value in np.unique(np.concatenate((self.values[self.values < top - _TINY], steps))):
            if self.pool_risk(value) <= 1.0 - level + _TINY:
                return float(value)
        return top

    def short(self, stock: float, pool: bool = False) -> float:
        """The shortfall at ``stock``, the waits in where the units are known."""
        if pool:
            return self.pool_short(stock)
        if self.waiting is not None and self.waiting.short is not None:
            return float(self.waiting.short(stock))
        return self.expected_short(stock)


def answer(protect: Demand, lead: Demand | None, stock: float | None, level: float,
           unit_cost: float | None = None, *, curve: bool = True) -> dict:
    """Hold N over the protection window, the reorder point over the lead time
    (None for a repairable pool: it's one for one), the risk and shortfall at
    ``stock``, and what the stock is worth at ``unit_cost``."""
    pool = lead is None
    hold = protect.hold(level, pool)
    out = {"hold": hold, "reorder_at": lead.quantile(level) if lead is not None else None,
           "expected_demand": protect.mean}
    waits = protect.waiting is not None and (pool or protect.waiting.short is not None)
    if waits and (pool or stock is not None):
        out["waiting"] = protect.waiting.payload()
    if stock is not None:
        trigger = out["reorder_at"] if out["reorder_at"] is not None else hold
        risk = protect.pool_risk(stock) if pool else protect.prob_short(stock)
        out.update(stock=float(stock), risk_at_stock=risk,
                   expected_short=protect.short(stock, pool), to_order=max(0.0, hold - stock),
                   below_reorder=stock < trigger - _TINY)
    if unit_cost is not None:
        out["unit_cost"] = float(unit_cost)
        out["hold_cost"] = hold * float(unit_cost)
        if stock is not None:
            out["to_order_cost"] = out["to_order"] * float(unit_cost)
    if curve:
        out["risk_curve"] = protect.curve(pool)
    return out


def window_demand(events: dict, start: float, end: float, weights=None) -> np.ndarray:
    """Each run's demand in [start, end) (periods from now) from simulated
    failure events (``services.fleet._renewal_events``): failures (sims,), or
    with ``weights`` (items × parts, each failure's parts) each part's
    (sims × parts)."""
    t = events["t"]
    lo, hi = np.searchsorted(t, [start, end], side="left")
    sims, run, item = events["sims"], events["sim"][lo:hi], events["item"][lo:hi]
    if weights is None:
        return np.bincount(run, minlength=sims).astype(float)
    weights = np.asarray(weights, dtype=float)
    out = np.zeros((sims, weights.shape[1]))
    for j in range(weights.shape[1]):
        out[:, j] = np.bincount(run, weights=weights[item, j], minlength=sims)
    return out


def bernoulli_sum_pmfs(probs) -> np.ndarray:
    """How many of independent events happen, each with its own chance: the exact
    (Poisson-binomial) distribution, by convolution. ``probs`` is windows × events;
    returns windows × counts, cut where the tail is negligible."""
    p = np.clip(np.nan_to_num(np.atleast_2d(np.asarray(probs, dtype=float))), 0.0, 1.0)
    mean = p.sum(axis=1)
    sd = np.sqrt((p * (1 - p)).sum(axis=1))
    k = int(min(p.shape[1], math.ceil(float((mean + 12 * sd).max(initial=0.0)) + 12))) + 1
    pmf = np.zeros((p.shape[0], k))
    pmf[:, 0] = 1.0
    for j in np.flatnonzero(p.max(axis=0, initial=0.0) > 0):
        q = p[:, j:j + 1]
        pmf[:, 1:] = pmf[:, 1:] * (1 - q) + pmf[:, :-1] * q
        pmf[:, :1] *= 1 - q
    return pmf


def poisson_pmf(mean: float) -> np.ndarray:
    """A Poisson count's distribution, cut where the tail is negligible."""
    from scipy.stats import poisson

    mean = max(0.0, float(mean))
    if mean <= 0:
        return np.array([1.0])
    k = int(poisson.ppf(1 - 1e-12, mean)) + 2
    return poisson.pmf(np.arange(k), mean)


def runs_short(sim, unit, weights, sims: int, stock: float, fails=None) -> float:
    """The expected shortfall at ``stock`` over a window, from a simulation's
    demand events in it (each run's, in time order: ``sim``, ``unit`` and the parts
    each uses, ``weights``), with nothing arriving in the window. Once the stock is
    used up, a failure (``fails``; every event by default) leaves its unit down, so
    that unit's later failures in the run never happen and are dropped; a planned
    job that can't be done is short too, but its unit keeps running."""
    sim = np.asarray(sim, dtype=np.int64)
    if sim.size == 0 or sims <= 0:
        return 0.0
    unit = np.asarray(unit, dtype=np.int64)
    w = np.broadcast_to(np.asarray(weights, dtype=float), sim.shape).astype(float)
    f = np.ones(sim.size, dtype=bool) if fails is None else np.asarray(fails, dtype=bool)
    order = np.argsort(sim, kind="stable")  # by run, each run's events still in time order
    s, u, w, f = sim[order], unit[order], w[order], f[order]
    total = np.cumsum(w)
    first = np.concatenate(([0], np.flatnonzero(np.diff(s)) + 1))
    sizes = np.diff(np.concatenate((first, [s.size])))
    before = np.repeat(total[first] - w[first], sizes)
    unmet = np.minimum(w, np.maximum(total - before - float(stock), 0.0))
    unmet[unmet < _TINY] = 0.0
    key = s * (int(u.max(initial=0)) + 1) + u
    down = np.flatnonzero((unmet > 0) & f)
    if down.size:
        keys, at = np.unique(key[down], return_index=True)
        first_down = down[at]
        loc = np.clip(np.searchsorted(keys, key), 0, keys.size - 1)
        after = (keys[loc] == key) & (np.arange(s.size) > first_down[loc])
        unmet[after] = 0.0
    return float(unmet.sum()) / sims


def poisson_short(mean: float, units: int, stock: float, per: float = 1.0) -> float:
    """The expected shortfall at ``stock`` over a window for ``units`` alike units
    with Poisson demand (``mean`` failures in all were none to wait), nothing
    arriving in the window. In each unit's own time (its cumulative hazard,
    ``u = mean / units``) the stock covers ``m`` failures; from the ``m``-th, at
    ``tau ~ Gamma(m, units)``, each unit fails once more at most and then waits,
    so ``E[down] = units (P(tau < u) - E[e^(tau - u); tau < u])``. Exact for alike
    units with any one hazard (a time change); an approximation when they differ."""
    from scipy.stats import poisson

    n = int(units)
    mean = max(0.0, float(mean))
    if n <= 0 or mean <= 0:
        return 0.0
    per = float(per) if per and per > 0 else 1.0
    u = mean / n
    m = math.floor(max(float(stock), 0.0) / per + _TINY)
    left = max(float(stock), 0.0) - m * per  # parts short of a whole job, used by none
    reached = float(poisson.sf(m - 1, n * u)) if m > 0 else 1.0  # P(tau < u)
    if m == 0:
        tail = math.exp(-u)
    elif n == 1:
        tail = float(poisson.pmf(m, u))
    else:
        tail = math.exp(-u + m * math.log(n / (n - 1)) + float(poisson.logsf(m - 1, (n - 1) * u)))
    down = n * max(0.0, reached - tail)
    any_down = float(poisson.sf(m, n * u))
    return max(0.0, per * down - left * any_down)


def constant_hazard(dist) -> float | None:
    """A life's constant failure rate (exponential from 0, to 1e-9 over a spread of
    ages), or None."""
    try:
        mid = float(dist.qf(0.5))
        if not math.isfinite(mid) or mid <= 0:
            return None
        x = mid * np.array([0.01, 0.1, 0.5, 1.0, 2.0, 5.0])
        with np.errstate(all="ignore"):
            h = -np.log(np.asarray(dist.sf(x), dtype=float)) / x
    except Exception:  # noqa: BLE001 - a life that can't say
        return None
    if not np.all(np.isfinite(h)) or h[0] <= 0 or np.max(np.abs(h / h[0] - 1.0)) > 1e-9:
        return None
    return float(h[0])


def pct(p: float) -> str:
    """A chance in words: '31%', or 'under 1%' (a simulation's 0 is a small chance,
    not none)."""
    return "under 1%" if p < 0.005 else f"{p:.0%}"


def _n(v: float) -> str:
    return f"{v:,.0f}" if float(v).is_integer() else f"{v:,.2f}".rstrip("0").rstrip(".")


def level_text(level: float) -> str:
    """'95%', '99.5%'."""
    return f"{level:.1%}".replace(".0%", "%")


def sentence(ans: dict, level: float, window: str, unit: str = "", repairable: bool = False,
             review: bool = False, rising: tuple | None = None) -> str:
    """The recommendation in words. ``window``: what the hold covers ('the lead
    time (60 days)'); ``review``: stock is checked periodically, not continuously.
    ``rising`` (peak, 'from quarter 2'): a later window needs more, so the headline
    says so ('Hold 2 now, rising to 3 from quarter 2') rather than reading as
    the answer for every period."""
    each = f" {unit}" if unit and unit != "each" else ""
    sl = level_text(level)
    held = f"{_n(ans['hold'])}{each}"
    if rising is not None:
        held = f"{_n(ans['hold'])}{each} now, rising to {_n(rising[0])} {rising[1]}"
    if repairable:
        words = (f"Keep a pool of {held}: a {sl} chance of no shortage over {window}, "
                 "while failed ones are repaired (one site, every unit sent comes back).")
    else:
        words = f"Hold {held}: a {sl} chance of no stock-out over {window}."
        if ans.get("reorder_at") is not None and ans["hold"] > 0:
            if review:
                words += f" At each review, order back up to {_n(ans['hold'])}"
                words += (f"; between reviews, reorder if usable stock falls to {_n(ans['reorder_at'])}."
                          if ans["reorder_at"] < ans["hold"] else ".")
            elif ans["reorder_at"] >= ans["hold"]:
                words += " Order one for one: replace each as it's used."
            else:
                words += f" Reorder when usable stock falls to {_n(ans['reorder_at'])}."
    if "stock" in ans:
        words += (f" With {_n(ans['stock'])} usable now, the chance of running out is "
                  f"{pct(ans['risk_at_stock'])}.")
    return words
