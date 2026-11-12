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

Every interval is 90% two-sided (:mod:`backend.levels`). A fit saved before
that rule holds 95% intervals and no ``ci_level``: a read serves them at 90%,
rebuilt from the stored standard error (:func:`at_level`); the stored document
is left as it is.
"""

from __future__ import annotations

import math
from typing import Optional

from backend import levels

Z95 = levels.Z95  # the two-sided 95% normal quantile: intervals saved before the 90% rule
Z = levels.Z  # the two-sided 90% one every interval is at now

CI_NOTE = (
    "90% Wald intervals (two-sided). A parameter that must be positive (a scale, shape or rate) has its interval "
    "taken on the log scale and transformed back, so it never goes below zero; a parameter bounded on "
    "both sides (a probability) uses the logit scale; an unbounded parameter (a location such as a "
    "normal μ) keeps the symmetric value ± 1.645·se.")


def _finite(v) -> bool:
    try:
        return v is not None and math.isfinite(float(v))
    except (TypeError, ValueError):
        return False


def wald_interval(value: float, se: float, lower=None, upper=None, z: float = Z) -> Optional[list]:
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
    # Relative to the numbers themselves: a coefficient of 5e-26 is not "about zero".
    return abs((lo + hi) / 2.0 - value) <= 1e-9 * max(abs(value), abs(hi - lo), 1e-300)


def corrected_params(params, bounds: dict, z_stored: float = Z) -> tuple[list, bool]:
    """``(params, changed)``: saved parameters whose interval is the old
    symmetric ``value ± z·se`` rebuilt on the log (or logit) scale at 90%, the
    way a fit gives it now. The standard error is the stored ``se`` or, where
    none was stored, read back from the interval's width at ``z_stored``.
    Anything else is kept."""
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
        se = float(se) if _finite(se) else (hi - lo) / (2.0 * z_stored)
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
    results = at_level(results)
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


def _rescaled(p: dict, bound, z_from: float) -> dict:
    """One saved parameter (or coefficient) with its interval moved from
    ``z_from`` to 90%: from its stored standard error where it has one, on
    the scale its interval was taken on (log or logit for a bounded one);
    else read back from the interval's width."""
    ci = p.get("ci")
    if not (isinstance(ci, (list, tuple)) and len(ci) == 2):
        return p
    lower, upper = (tuple(bound or ()) + (None, None))[:2]
    se = p.get("se")
    if _finite(se) and _finite(p.get("value")):
        new = wald_interval(float(p["value"]), float(se), lower, upper)
        if new is not None:
            return {**p, "ci": new}
    try:
        value, lo, hi = float(p["value"]), float(ci[0]), float(ci[1])
    except (TypeError, ValueError, KeyError):
        return p
    log = _finite(lower) and float(lower) == 0.0 and lo > 0 and not _symmetric(value, lo, hi)
    new = levels.rescale(value, lo, hi, log=log, z_from=z_from)
    return {**p, "ci": new} if new is not None else p


# The scale SurPyval's Wald band on F(t) is symmetric on, per family: a band
# saved at 95% is moved to 90% exactly on it (checked against fresh fits in
# test_ninety_percent.py). A family not listed keeps its saved band and says
# its level (95%).
_BAND_SCALE = {
    "weibull": "cloglog", "exponential": "cloglog", "gumbel": "cloglog", "rayleigh": "cloglog",
    "gamma": "logit", "loglogistic": "logit", "gumbel_lev": "logit", "logistic": "logit", "beta4": "logit",
    "normal": "probit", "lognormal": "probit",
}


def _band_at_level(results: dict, z_from: float):
    """A saved probability plot's band moved from ``z_from`` to 90%, or None
    when it can't be (a family whose band scale isn't known, no parameters)."""
    import numpy as np
    from scipy import stats

    plot = results.get("plot")
    b = plot.get("bounds") if isinstance(plot, dict) else None
    if not isinstance(b, dict) or b.get("level") is not None:
        return None
    scale = _BAND_SCALE.get(results.get("distribution_id"))
    if scale is None:
        return None
    from backend import fitting

    dist = (fitting.DISTRIBUTIONS.get(results["distribution_id"]) or {}).get("dist")
    params = [p.get("value") for p in results.get("params") or [] if isinstance(p, dict)]
    line = plot.get("line") or {}
    if dist is None or not params or len(line.get("y") or []) != len(b.get("lower") or []):
        return None
    eps = 1e-15
    fwd = {"cloglog": lambda f: np.log(-np.log1p(-f)), "logit": lambda f: np.log(f / (1 - f)),
           "probit": stats.norm.ppf}[scale]
    inv = {"cloglog": lambda u: -np.expm1(-np.exp(u)), "logit": lambda u: 1 / (1 + np.exp(-u)),
           "probit": stats.norm.cdf}[scale]
    k = Z / z_from
    with np.errstate(all="ignore"):
        def to_f(y):
            arr = np.asarray([np.nan if v is None else v for v in y], dtype=float)
            return np.clip(np.asarray(dist.mpp_inv_y_transform(arr, *params), dtype=float), eps, 1 - eps)

        u_line = fwd(to_f(line["y"]))
        out = {}
        for key in ("lower", "upper"):
            u = u_line + (fwd(to_f(b[key])) - u_line) * k
            y = np.asarray(dist.mpp_y_transform(np.clip(inv(u), eps, 1 - eps), *params), dtype=float)
            if not np.all(np.isfinite(y)):
                return None
            out[key] = y.tolist()
    return {**plot, "bounds": {**b, **out, "level": LEVEL_TWO_SIDED}}


LEVEL_TWO_SIDED = levels.LEVEL


def at_level(results, z_from: float = Z95):
    """A saved fit's results with its parameter and coefficient intervals at
    90% two-sided (``ci_level``). Results already at 90% (or without
    intervals) come back as they are; nothing is written back."""
    if not isinstance(results, dict) or results.get("ci_level") is not None:
        return results
    if results.get("kind") == "joint":
        from backend import joint

        return joint.at_level(results)
    if results.get("kind") not in ("distribution", "discrete", "regression"):
        return results
    if results.get("method") in ("library", "bayesian_update") or results.get("credible_level") is not None:
        # A library record's bounds are its source's spread, and a Bayesian update's are
        # 90% credible intervals already: neither is a fit's 95% Wald interval.
        return results
    params = results.get("params") if isinstance(results.get("params"), list) else []
    coefs = results.get("coefficients") if isinstance(results.get("coefficients"), list) else []
    if not any(isinstance(p, dict) and p.get("ci") for p in [*params, *coefs]):
        return results
    if str(results.get("ci_method") or "").startswith("bootstrap"):
        # Bootstrap percentile intervals (Buckley-James) can't be moved without the
        # resamples: they keep their 95% and say so.
        return {**results, "ci_level": 0.95}
    try:
        bounds = distribution_bounds(results.get("distribution_id"))
    except Exception:  # noqa: BLE001 - never fail a read over the intervals
        bounds = {}
    out = dict(results)
    out["params"] = [_rescaled(p, bounds.get(p.get("name")), z_from) if isinstance(p, dict) else p
                     for p in params] if params else results.get("params")
    if coefs:
        out["coefficients"] = [_rescaled(c, None, z_from) if isinstance(c, dict) else c for c in coefs]
    if isinstance(results.get("coef_table"), list):
        # SurPyval's summary rows (more_models.summary_rows): Wald on each term's own scale.
        out["coef_table"] = [{**row, "ci": levels.rescale(row.get("value"), *row["ci"], log=None) or row["ci"]}
                             if isinstance(row, dict) and isinstance(row.get("ci"), list) and len(row["ci"]) == 2
                             else row for row in results["coef_table"]]
        t = out.get("tvc")
        if isinstance(t, dict) and t.get("readings"):
            try:  # the sentences quote the intervals: say them again at 90%
                from backend import tvc

                out["tvc"] = {**t, "readings": tvc.readings(out["coefficients"], out.get("effect"),
                                                            t.get("covariates") or [])}
            except Exception:  # noqa: BLE001 - keep the saved sentences
                pass
    out["ci_level"] = levels.LEVEL
    frailty = out.get("frailty")
    if isinstance(frailty, dict) and frailty.get("theta_ci") and frailty.get("theta_ci_level") is None:
        # A profile-likelihood interval: kept as saved, at its own 95%.
        out["frailty"] = {**frailty, "theta_ci_level": 0.95}
    try:
        plot = _band_at_level(results, z_from)
    except Exception:  # noqa: BLE001 - the band keeps its saved level and says so
        plot = None
    if plot is not None:
        out["plot"] = plot
    if out.get("ci_note"):
        out["ci_note"] = CI_NOTE
    randomness = out.get("randomness")
    if isinstance(randomness, dict) and randomness.get("basis") == "beta_ci" and not randomness.get("reason"):
        from backend import fitting

        verdict = fitting._randomness_verdict(out.get("distribution_id"), out["params"])
        if verdict is not None:
            out["randomness"] = verdict
    return out


def note_for(params) -> Optional[str]:
    """:data:`CI_NOTE` when any parameter carries an interval, else None."""
    return CI_NOTE if any(isinstance(p, dict) and p.get("ci") for p in (params or [])) else None
