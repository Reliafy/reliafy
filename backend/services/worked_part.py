"""A part's failures and planned replacements over a run of windows, worked out (not simulated): the
quick forecast tool's part clause (forecast plan, Nov 2026: "the two agree" with the lines by owner).

RePyability's ``NonRepairable.cost_by_window`` gives, for one unit at its age, the exact distribution
of a priced count over each window and over the whole horizon, run to failure or with a planned
replacement at an age (``resets`` true: age replacement, the clock restarts at a failure; false:
block replacement on fixed dates). Priced with a failure at ``BIG`` and a planned replacement at 1,
each outcome's cost is ``BIG × failures + planned``, which gives the joint distribution of the two
counts. Units fail independently, so the units' joint distributions are convolved. Every line (the
failures, the planned replacements, their hours, cost and spares) is a sum ``a × failures + b ×
planned`` over that one joint distribution, so its mean and its 90% two-sided range (5th to 95th
percentile) are exact, and the views agree with each other.
"""

from __future__ import annotations

import numpy as np

BIG = 10_000  # a failure's price in the encoding; more planned replacements than this per unit can't happen here
MAX_GROUPS = 60  # distinct ages worked out one by one; more than this, the caller simulates instead
TRIM = 1e-13


def _trim(a: np.ndarray) -> np.ndarray:
    a = np.clip(a, 0.0, None)
    rows = np.nonzero(a.sum(axis=1) > TRIM)[0]
    cols = np.nonzero(a.sum(axis=0) > TRIM)[0]
    if rows.size == 0:
        return np.ones((1, 1))
    a = a[: rows[-1] + 1, : cols[-1] + 1]
    return a / a.sum()


def _conv(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    from scipy.signal import fftconvolve

    if a.size * b.size < 4_000:
        out = np.zeros((a.shape[0] + b.shape[0] - 1, a.shape[1] + b.shape[1] - 1))
        for i, j in zip(*np.nonzero(a)):
            out[i:i + b.shape[0], j:j + b.shape[1]] += a[i, j] * b
        return _trim(out)
    return _trim(fftconvolve(a, b))


def _power(a: np.ndarray, n: int) -> np.ndarray:
    out, base = np.ones((1, 1)), a
    while n:
        if n & 1:
            out = _conv(out, base)
        n >>= 1
        if n:
            base = _conv(base, base)
    return out


def _joint(window, planned: bool) -> np.ndarray:
    """J[f, p]: the chance of f failures and p planned replacements, from a priced window."""
    costs = np.rint(np.asarray(window.costs, dtype=float)).astype(int)
    probs = np.asarray(window.cost_probabilities, dtype=float)
    f = costs // BIG if planned else costs
    p = costs % BIG if planned else np.zeros_like(costs)
    out = np.zeros((int(f.max()) + 1, int(p.max()) + 1))
    np.add.at(out, (f, p), probs)
    return _trim(out)


def forecast(dist, groups: list[tuple[float, int]], ends, every=None, resets=True) -> dict:
    """{total: J, windows: [J, ...]} over the units (``groups``: [(age, how many)]), the windows ending
    at ``ends`` (in the life's unit, from now), with a planned replacement at age ``every`` (None: run
    to failure)."""
    from repyability import NonRepairable

    planned = every is not None
    part = NonRepairable(dist, unplanned_cost=float(BIG), planned_cost=1.0) if planned else \
        NonRepairable(dist, unplanned_cost=1.0, planned_cost=0.0)
    ends = np.maximum.accumulate(np.asarray(ends, dtype=float))
    total, windows = np.ones((1, 1)), [np.ones((1, 1)) for _ in ends]
    for age, count in groups:
        kw = {"resets": bool(resets)} if planned else {}
        if planned and not resets:
            kw["since_renewal"] = 0.0
        got = part.cost_by_window(ends, every, age=float(age), levels=(5.0, 95.0), **kw)
        total = _conv(total, _power(_joint(got.total, planned), count))
        for k, w in enumerate(list(got.windows)[: len(ends)]):
            windows[k] = _conv(windows[k], _power(_joint(w, planned), count))
    return {"total": total, "windows": windows}


def block(j: np.ndarray, a: float, b: float = 0.0) -> dict:
    """{expected, interval} of ``a × failures + b × planned``: 90% two-sided (5th to 95th percentile)."""
    f, p = np.indices(j.shape)
    vals = (a * f + b * p).ravel()
    w = j.ravel()
    order = np.argsort(vals, kind="stable")
    vals, w = vals[order], w[order]
    cum = np.cumsum(w)
    lo = vals[min(len(vals) - 1, int(np.searchsorted(cum, 0.05 - 1e-12)))]
    hi = vals[min(len(vals) - 1, int(np.searchsorted(cum, 0.95 - 1e-12)))]
    return {"expected": float(np.dot(vals, w)), "interval": [float(lo), float(hi)]}


def chance_any(j: np.ndarray) -> float:
    """The chance of at least one failure."""
    return float(1.0 - j[0, :].sum())
