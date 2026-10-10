"""Induced life distribution of a degradation model (#63).

The Lu-Meeker approach: draw path parameters from the fitted population and
push each draw through the path model to the threshold, giving the failure
times the path model itself implies. SurPyval's
``DegradationModel.induced_life`` does it by Monte Carlo; this module gives
its reliability curve beside the pseudo-failure-time fit's (the two should
agree), its mean and median, the reliability at a time and the time at a
reliability.

A fixed seed and sample size, so a model's numbers never change between
views.
"""

from __future__ import annotations

import math
from typing import Optional

import numpy as np

N_SAMPLES = 10_000
SEED = 0
GRID_POINTS = 200
MAX_POINTS = 50


def _f(v) -> Optional[float]:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) else None


def _col(a) -> list:
    return [_f(v) for v in np.asarray(a, dtype=float).ravel()]


def _points(values, name: str, lo: float, hi: float) -> list[float]:
    values = values if isinstance(values, (list, tuple)) else [values]
    if len(values) > MAX_POINTS:
        raise ValueError(f"At most {MAX_POINTS} {name} at a time.")
    out = []
    for v in values:
        f = _f(v)
        if f is None or not lo <= f <= hi:
            raise ValueError(f"Each {name[:-1]} must be a number from {lo:g} to {hi:g}.")
        out.append(f)
    return out


def induced_life(live, times=None, reliability=None) -> dict:
    """The induced life distribution of a fitted degradation model ``live``:
    ``{"available", "n_samples", "mean", "median", "b10", "prob_never_fails",
    "curve": {"x", "sf", "life_sf"}}``, plus ``"at_times"`` (reliability at
    each of ``times``) and ``"at_reliability"`` (the time by which each
    reliability in ``reliability`` is reached) when asked. ``life_sf`` is the
    pseudo-failure-time fit's curve on the same grid. Raises ValueError for a
    bad request; a model SurPyval can't induce a life for comes back
    ``{"available": False, "reason"}``."""
    times = _points(times, "times", 0.0, math.inf) if times is not None else None
    reliability = _points(reliability, "reliabilities", 0.0, 1.0) if reliability is not None else None
    try:
        dist = live.induced_life(n_samples=N_SAMPLES, random_state=SEED)
    except Exception as exc:  # noqa: BLE001 - say why, never fail the page
        return {"available": False, "reason": str(exc).strip() or type(exc).__name__}

    never = _f(getattr(dist, "prob_never_fails", 0.0)) or 0.0
    q = np.asarray(dist.qf(np.array([0.1, 0.5, 0.99])), dtype=float)
    hi = _f(q[2])
    if hi is None or hi <= 0:
        # Most draws never reach the threshold: span the finite ones.
        finite = np.asarray(getattr(dist, "samples", []), dtype=float)
        finite = finite[np.isfinite(finite)]
        hi = float(finite.max()) if finite.size else None
    out: dict = {
        "available": True,
        "n_samples": N_SAMPLES,
        "mean": _f(dist.mean()),
        "median": _f(q[1]),
        "b10": _f(q[0]),
        "prob_never_fails": never,
    }
    if hi:
        grid = np.linspace(0.0, hi * 1.05, GRID_POINTS)
        curve = {"x": grid.tolist(), "sf": _col(dist.sf(grid))}
        try:
            curve["life_sf"] = _col(live.sf(grid))
        except Exception:  # noqa: BLE001 - the comparison is a convenience
            pass
        out["curve"] = curve
    if times is not None:
        out["at_times"] = [{"t": t, "reliability": _f(np.asarray(dist.sf(np.array([t])), dtype=float)[0])}
                           for t in times]
    if reliability is not None:
        # qf takes the failure fraction: R = 0.9 is the time 10% have failed.
        out["at_reliability"] = [
            {"reliability": r, "t": _f(np.asarray(dist.qf(np.array([1.0 - r])), dtype=float)[0])}
            for r in reliability]
    return out
