"""Wald intervals that stay inside a parameter's support (#265).

A plain Wald interval, ``value ± z·se``, is symmetric. For a parameter that
must be positive (a Weibull scale or shape, a lognormal σ, an exponential
rate) a small sample gives a large standard error, and the symmetric interval
can go below zero: a Weibull shape of [−1.6, 12.8]. The usual remedy is to
take the interval on the log scale and transform it back, ``value·exp(±z·se /
value)``: it is never below zero, and it is the interval SurPyval's own
``param_cb`` gives. A parameter bounded on both sides (a probability such as
the discrete Weibull's ``q``) takes it on the logit scale, which keeps it inside
(0, 1). An unbounded parameter (a location such as a normal μ) keeps the
symmetric interval.

#262 did this for the ALT life-stress coefficients
(:func:`backend.alt.bounded_wald_interval` uses :func:`wald_interval`); this
module does it for every fitted distribution, discrete and regression model,
at fit time and, for fits saved before, when they are read
(:func:`corrected_results`, applied as a saved :class:`backend.schema.Model`
is loaded).
"""

from __future__ import annotations

import math
from typing import Optional

Z95 = 1.959963984540054  # the two-sided 95% normal quantile

CI_NOTE = (
    "95% Wald intervals. A parameter that must be positive (a scale, shape or rate) has its interval "
    "taken on the log scale and transformed back, so it never goes below zero; a parameter bounded on "
    "both sides (a probability) uses the logit scale; an unbounded parameter (a location such as a "
    "normal μ) keeps the symmetric value ± 1.96·se.")


def _finite(v) -> bool:
    try:
        return v is not None and math.isfinite(float(v))
    except (TypeError, ValueError):
        return False


def wald_interval(value: float, se: float, lower=None, upper=None, z: float = Z95) -> Optional[list]:
    """A two-sided Wald interval that respects the support ``(lower, upper)``
    (``None`` for an open side).

    * unbounded: ``value ± z·se``;
    * one bound: on the log of the distance to it, ``lower + d·exp(±z·se/d)``
      with ``d = value − lower`` (mirrored for an upper bound);
    * both bounds: on the logit of the position between them.

    None when the estimate sits on or outside a bound, or the standard error
    isn't usable."""
    if not (_finite(value) and _finite(se)) or float(se) < 0:
        return None
    value, se = float(value), float(se)
    lo_b = float(lower) if _finite(lower) else None
    hi_b = float(upper) if _finite(upper) else None
    if lo_b is None and hi_b is None:
        return [value - z * se, value + z * se]
    if lo_b is not None and hi_b is not None:
        width = hi_b - lo_b
        if width <= 0 or not (lo_b < value < hi_b):
            return None
        u = (value - lo_b) / width
        # se of logit(u) by the delta method: se / (width·u·(1 − u)).
        k = z * se / (width * u * (1.0 - u))
        logit = math.log(u / (1.0 - u))

        def expit(t: float) -> float:
            return 1.0 / (1.0 + math.exp(-t)) if t >= 0 else math.exp(t) / (1.0 + math.exp(t))

        return [lo_b + width * expit(logit - k), lo_b + width * expit(logit + k)]
    if lo_b is not None:
        d = value - lo_b
        if d <= 0:
            return None
        return [lo_b + d * _exp(-z * se / d), lo_b + d * _exp(z * se / d)]
    d = hi_b - value
    if d <= 0:
        return None
    return [hi_b - d * _exp(z * se / d), hi_b - d * _exp(-z * se / d)]


def _exp(t: float) -> float:
    """``exp`` that saturates instead of overflowing (an enormous standard
    error gives an infinite upper bound, not an exception)."""
    try:
        return math.exp(t)
    except OverflowError:
        return math.inf


def is_bounded(bounds) -> bool:
    """True when ``(lower, upper)`` closes at least one side."""
    if not bounds:
        return False
    lower, upper = (tuple(bounds) + (None, None))[:2]
    return _finite(lower) or _finite(upper)


def distribution_bounds(distribution_id: str | None) -> dict:
    """``{parameter name: (lower, upper)}`` from SurPyval's declared bounds
    for a plain, discrete or regression model's (baseline) distribution; {}
    for anything else (mixtures, Cox, per-demand, unknown ids)."""
    if not distribution_id:
        return {}
    from backend import fitting  # local: heavy import, and fitting imports this module

    entry = fitting.DISTRIBUTIONS.get(distribution_id) or fitting.DISCRETE.get(distribution_id)
    if entry is None and distribution_id in fitting.REGRESSION_MODELS:
        base = distribution_id.rsplit("_", 1)[0]
        entry = fitting.DISTRIBUTIONS.get(base)
    dist = (entry or {}).get("dist")
    return bounds_of(dist)


def bounds_of(dist) -> dict:
    """``{parameter name: (lower, upper)}`` of a SurPyval distribution."""
    names = list(getattr(dist, "parameter_names", None) or [])
    bounds = list(getattr(dist, "bounds", None) or [])
    out = {}
    for name, b in zip(names, bounds):
        out[name] = tuple(b) if b is not None else (None, None)
    return out


def _symmetric(value: float, lo: float, hi: float) -> bool:
    return abs((lo + hi) / 2.0 - value) <= 1e-9 * max(1.0, abs(value), abs(hi - lo))


def corrected_params(params, bounds: dict) -> tuple[list, bool]:
    """``(params, changed)``: saved parameters whose 95% interval is the old
    symmetric ``value ± z·se`` rebuilt on the log (or logit) scale, the way a
    fit gives it now. The standard error is the stored ``se`` or, where none
    was stored, read back from the interval's width. Anything else is kept."""
    if not isinstance(params, list) or not bounds:
        return params, False
    changed = False
    out = []
    for p in params:
        ci = p.get("ci") if isinstance(p, dict) else None
        b = bounds.get(p.get("name")) if isinstance(p, dict) else None
        if not (is_bounded(b) and isinstance(ci, (list, tuple)) and len(ci) == 2):
            out.append(p)
            continue
        try:
            value, lo, hi = float(p["value"]), float(ci[0]), float(ci[1])
        except (TypeError, ValueError, KeyError):
            out.append(p)
            continue
        if not (math.isfinite(lo) and math.isfinite(hi)) or hi <= lo or not _symmetric(value, lo, hi):
            out.append(p)
            continue
        se = p.get("se")
        se = float(se) if _finite(se) else (hi - lo) / (2.0 * Z95)
        out.append({**p, "ci": wald_interval(value, se, *b[:2])})
        changed = True
    return out, changed


def corrected_results(results):
    """A saved fit's results with every bounded parameter's interval on the
    log (or logit) scale, and ``ci_note`` saying so. Results without
    parameter intervals (mixtures, per-demand, parameters-only models,
    another kind) come back as they are."""
    if not isinstance(results, dict):
        return results
    kind = results.get("kind")
    if kind not in ("distribution", "discrete", "regression"):
        return results
    params = results.get("params")
    if not isinstance(params, list) or not any(isinstance(p, dict) and p.get("ci") for p in params):
        return results
    try:
        bounds = distribution_bounds(results.get("distribution_id"))
    except Exception:  # noqa: BLE001 - never fail a read over the intervals
        return results
    fixed, changed = corrected_params(params, bounds)
    if not changed and results.get("ci_note"):
        return results
    out = dict(results)
    out["params"] = fixed
    if bounds:
        out["ci_note"] = CI_NOTE
    randomness = results.get("randomness")
    if changed and isinstance(randomness, dict) and randomness.get("basis") == "beta_ci" \
            and not randomness.get("reason"):
        # The Weibull randomness verdict reads β's interval against 1: read
        # the corrected one (a fit that didn't converge keeps "inconclusive").
        from backend import fitting

        verdict = fitting._randomness_verdict(results.get("distribution_id"), fixed)
        if verdict is not None:
            out["randomness"] = verdict
    return out


def note_for(params) -> Optional[str]:
    """:data:`CI_NOTE` when any parameter carries an interval, else None."""
    return CI_NOTE if any(isinstance(p, dict) and p.get("ci") for p in (params or [])) else None
