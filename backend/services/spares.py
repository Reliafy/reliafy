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


class Demand:
    """A demand distribution over one window: the values it takes, ascending, and
    their chances."""

    __slots__ = ("values", "probs", "cdf")

    def __init__(self, values, probs):
        self.values = np.asarray(values, dtype=float)
        self.probs = np.asarray(probs, dtype=float)
        self.cdf = np.cumsum(self.probs)

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

    def curve(self) -> list[list[float]]:
        """[[stock, P(running out)], ...] from 0 to where the chance is under 0.1%
        (at most CURVE_POINTS levels), for a risk readout at any stock."""
        top = self.quantile(MAX_SERVICE_LEVEL)
        step = max(1, math.ceil(top / CURVE_POINTS))
        levels = np.arange(0, top + step, step, dtype=float)
        return [[float(s), round(self.prob_short(s), 6)] for s in levels]


def answer(protect: Demand, lead: Demand | None, stock: float | None, level: float,
           unit_cost: float | None = None, *, curve: bool = True) -> dict:
    """Hold N over the protection window, the reorder point over the lead time
    (None for a repairable pool: it's one for one), the risk and shortfall at
    ``stock``, and what the stock is worth at ``unit_cost``."""
    hold = protect.quantile(level)
    out = {"hold": hold, "reorder_at": lead.quantile(level) if lead is not None else None,
           "expected_demand": protect.mean}
    if stock is not None:
        trigger = out["reorder_at"] if out["reorder_at"] is not None else hold
        out.update(stock=float(stock), risk_at_stock=protect.prob_short(stock),
                   expected_short=protect.expected_short(stock), to_order=max(0.0, hold - stock),
                   below_reorder=stock < trigger - _TINY)
    if unit_cost is not None:
        out["unit_cost"] = float(unit_cost)
        out["hold_cost"] = hold * float(unit_cost)
        if stock is not None:
            out["to_order_cost"] = out["to_order"] * float(unit_cost)
    if curve:
        out["risk_curve"] = protect.curve()
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


def pct(p: float) -> str:
    """A chance in words: '31%', or 'under 1%' (a simulation's 0 is a small chance,
    not none)."""
    return "under 1%" if p < 0.005 else f"{p:.0%}"


def _n(v: float) -> str:
    return f"{v:,.0f}" if float(v).is_integer() else f"{v:,.2f}".rstrip("0").rstrip(".")


def level_text(level: float) -> str:
    """'95%', '99.5%'."""
    return f"{level:.1%}".replace(".0%", "%")


def sentence(ans: dict, level: float, window: str, unit: str = "", repairable: bool = False) -> str:
    """The recommendation in words. ``window``: what the hold covers ('the lead
    time (60 days)')."""
    each = f" {unit}" if unit and unit != "each" else ""
    sl = level_text(level)
    if repairable:
        words = (f"Keep a pool of {_n(ans['hold'])}{each}: a {sl} chance of no shortage over {window}, "
                 "while failed ones are repaired (one site, every unit sent comes back).")
    else:
        words = f"Hold {_n(ans['hold'])}{each}: a {sl} chance of no stock-out over {window}."
        if ans.get("reorder_at") is not None:
            if ans["reorder_at"] >= ans["hold"]:
                words += " Order one for one: replace each as it's used."
            else:
                words += f" Reorder when usable stock falls to {_n(ans['reorder_at'])}."
    if "stock" in ans:
        words += (f" With {_n(ans['stock'])} usable now, the chance of running out is "
                  f"{pct(ans['risk_at_stock'])}.")
    return words
