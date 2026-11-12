"""B-lives, MTTF and the time at a reliability, with one-sided bounds (#288).

A design engineer asks "what's B10 at 90% confidence?": the time by which
10% have failed, and the time we can be 90% sure it is at least. SurPyval
answers both: ``qf`` is the quantile (the B-life), ``quantile_cb`` bounds it
(the Fisher-matrix bound on time of Nelson and of Meeker and Escobar), and
``mean`` / ``mean_cb`` do the same for the MTTF. This module only shapes
those numbers for the app and the API; it computes nothing itself.

Models that can't bound a quantile (a fit by a method other than maximum
likelihood, parameters entered without data, a mixture) still get their
values, with ``lower`` null and ``bounds_note`` saying why. Non-parametric
estimators bound a quantile two-sided only (Brookmeyer-Crowley); the lower
end of the two-sided ``1 − 2α`` interval is the one-sided ``1 − α`` bound.
"""

from __future__ import annotations

import math
from typing import Optional

import numpy as np
from backend.errors import client_reason
from backend.warn_capture import ignore_warnings

# The B-lives the life card shows: the fraction failed, and its label.
B_LIVES = ((0.01, "B1"), (0.05, "B5"), (0.10, "B10"), (0.50, "B50"))
DEFAULT_CONFIDENCE = 0.90
BOUNDS = ("lower", "upper", "two-sided")

NO_COVARIANCE = ("No confidence bounds: they come from the fit's covariance, which a maximum-likelihood "
                 "fit to data has and this model doesn't.")
MIXTURE_NOTE = "No confidence bounds: a mixture has no covariance matrix."
NOT_MLE_NOTE = ("No confidence bounds: only a maximum-likelihood fit has them. B-life bounds come from that fit's "
                "covariance, which a probability-plot (MPP), spacings (MPS) or least-squares (MSE) fit doesn't give. "
                "For the bound, fit the same data by maximum likelihood (the default method).")
NO_MAXIMUM_NOTE = "No confidence bounds: the fit has no finite maximum, so its covariance means nothing."
# A model that bounds its curve but not its quantiles (Royston-Parmar, #179).
CURVE_ONLY_NOTE = ("No bounds on the B-lives: this model's confidence bounds are on its curve (the calculator's "
                   "band), not on its quantiles.")
# A Bayesian update's bounds are credible intervals (SurPyval's quantile_cri and mean_cri), so the
# card says so rather than calling them confidence bounds.
CREDIBLE_NOTE = ("The bounds are credible intervals from a Bayesian update: there's that chance the value lies "
                 "beyond the bound, given the baseline and the data. They aren't confidence bounds.")


def _num(v) -> Optional[float]:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) else None


def check_confidence(confidence) -> float:
    """``confidence`` as a float strictly between 0 and 1, or ValueError."""
    try:
        c = float(confidence)
    except (TypeError, ValueError):
        raise ValueError("Confidence must be a number between 0 and 1 (e.g. 0.9).") from None
    if not 0.0 < c < 1.0:
        raise ValueError("Confidence must be between 0% and 100% (exclusive).")
    return c


def _is_nonparametric(model) -> bool:
    return hasattr(model, "R") and hasattr(model, "quantile_cb") and not hasattr(model, "dist")


def is_bayesian(model) -> bool:
    """A SurPyval Bayesian fit (``fit_bayes``): its intervals are credible ones, from ``cri``,
    ``quantile_cri`` and ``mean_cri``; its ``cb`` refuses."""
    return hasattr(model, "posterior") and hasattr(model, "quantile_cri") and hasattr(model, "cri")


def _no_bounds_reason(model) -> Optional[str]:
    """Why ``model`` can't bound a quantile, or None when it can."""
    if not hasattr(model, "quantile_cb"):
        if hasattr(model, "m") and hasattr(model, "w"):
            return MIXTURE_NOTE
        return CURVE_ONLY_NOTE if hasattr(model, "cb") and hasattr(model, "knots") else NO_COVARIANCE
    if _is_nonparametric(model) or is_bayesian(model):
        return None
    method = getattr(model, "method", "MLE")
    if method == "given parameters":
        return NO_COVARIANCE
    if method != "MLE":
        return NOT_MLE_NOTE
    return None


def _quantile_bounds(model, probs: np.ndarray, alpha: float, bound: str):
    """``(lower, upper)`` arrays (None for a side not asked for) of the
    quantiles at ``probs``, by SurPyval's ``quantile_cb``."""
    with np.errstate(all="ignore"), ignore_warnings(RuntimeWarning):
        # An undefined bound comes back nan, and is shown as none.
        if is_bayesian(model):
            # Credible intervals of the quantiles, from the posterior draws.
            cri = np.asarray(model.quantile_cri(probs, alpha_ci=alpha, bound=bound), dtype=float)
            if bound == "two-sided":
                cri = cri.reshape(-1, 2)
                lo, hi = cri[:, 0], cri[:, 1]
            else:
                cri = cri.reshape(-1)
                lo, hi = (cri, None) if bound == "lower" else (None, cri)
        elif _is_nonparametric(model):
            # Two-sided only: a one-sided 1 − α bound is one end of 1 − 2α.
            two = np.asarray(model.quantile_cb(probs, alpha_ci=alpha if bound == "two-sided" else 2 * alpha),
                             dtype=float).reshape(-1, 2)
            lo, hi = two[:, 0], two[:, 1]
        else:
            # One probability at a time: SurPyval 0.23 returns nan for a whole
            # call when one quantile's variance is zero (a zero-inflated
            # model's B1 at t = 0, say), and that would take the rest with it.
            def one(p):
                try:
                    return np.ravel(np.asarray(model.quantile_cb(np.array([p]), alpha_ci=alpha, bound=bound),
                                               dtype=float))
                except ValueError:
                    raise
                except Exception:  # noqa: BLE001 - that quantile goes without its bound
                    return np.full(2 if bound == "two-sided" else 1, np.nan)

            cb = np.array([one(p) for p in probs])
            if bound == "two-sided":
                lo, hi = cb[:, 0], cb[:, 1]
            else:
                cb = cb[:, 0]
                lo, hi = (cb, None) if bound == "lower" else (None, cb)
    if bound == "lower":
        hi = None
    elif bound == "upper":
        lo = None
    return lo, hi


# Inspection (interval) data: a non-parametric estimate knows how much fails
# between two inspection times, not when within them.
INTERVAL_NOTE = ("Inspection data: the non-parametric estimate knows how many units failed between two "
                 "inspection times, not when within them, so each B-life is given as the interval it falls in. "
                 "The lower bound is the start of the interval its bound falls in.")
NO_INTERVAL_BOUND = ("No lower bound: no failure is known to have happened before {start}, so the data can't say how "
                     "early the first failures come. Use a parametric fit (Weibull, say) for this B-life's bound.")


def _has_intervals(model) -> bool:
    """A non-parametric estimate fitted to interval or left-censored data
    (inspection times): its steps sit at the inspection times."""
    if not _is_nonparametric(model):
        return False
    data = getattr(model, "data", None)
    c = data.get("c") if isinstance(data, dict) else None
    if c is None:
        return False
    c = np.asarray(c, dtype=float).ravel()
    return bool(np.isin(c, (2, -1)).any())


def _interval_points(model, probs: np.ndarray, alpha: float, bound: str) -> list[dict]:
    """Each quantile of a non-parametric estimate of inspection data as the
    interval it falls in, ``{"between": [a, b], "lower", "upper", "lower_note"}``.

    The estimate (Turnbull's) puts a mass of failures between two inspection
    times without saying where: the B-life is "between 1,000 and 1,500 h",
    never the interval's end. Its lower bound is the start of the interval in
    which the curve's upper bound first reaches the share (Brookmeyer-Crowley,
    read conservatively); where that interval starts at a time with no failure
    known before it (the band has no width there), no bound can be given."""
    xs = np.asarray(model.x, dtype=float)
    F = 1.0 - np.asarray(model.R, dtype=float)
    with np.errstate(all="ignore"), warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        # One-sided 1 − α bounds are the ends of the two-sided 1 − 2α band.
        a2 = alpha if bound == "two-sided" else 2 * alpha
        sf_cb = np.asarray(model.cb(xs, on="sf", alpha_ci=a2), dtype=float).reshape(-1, 2)
    ff_upper = 1.0 - sf_cb[:, 0]  # the failure probability's upper bound
    ff_lower = 1.0 - sf_cb[:, 1]
    out = []
    for p in probs:
        k = int(np.argmax(F >= p - 1e-12)) if (F >= p - 1e-12).any() else None
        point: dict = {"between": None, "lower": None, "upper": None, "lower_note": None}
        if k is None:
            out.append(point)
            continue
        start = float(xs[k - 1]) if k > 0 else 0.0
        point["between"] = [start, float(xs[k])]
        if bound in ("lower", "two-sided"):
            hit = np.nonzero(ff_upper >= p - 1e-12)[0]
            if hit.size:
                j = int(hit[0])
                if j == 0 or not (np.isfinite(ff_upper[j - 1]) and ff_upper[j - 1] > 0):
                    point["lower_note"] = NO_INTERVAL_BOUND.format(start=f"{float(xs[max(j - 1, 0)]):,.4g}")
                else:
                    point["lower"] = float(xs[j - 1])
        if bound in ("upper", "two-sided"):
            hit = np.nonzero(ff_lower >= p - 1e-12)[0]
            point["upper"] = float(xs[int(hit[0])]) if hit.size else None
        out.append(point)
    return out


def _quantiles(model, probs: np.ndarray) -> list[Optional[float]]:
    with np.errstate(all="ignore"):
        try:
            if is_bayesian(model):
                # The posterior median of each quantile: the B10 the Bayesian panel quotes.
                q = np.asarray(model.quantile_cri(probs, point=True), dtype=float).reshape(-1)
            else:
                q = np.asarray(model.qf(probs), dtype=float).reshape(-1)
        except Exception:  # noqa: BLE001 - one at a time (a mixture's bisection, say)
            q = np.array([_num(np.ravel(np.asarray(model.qf(float(p)), dtype=float))[0]) or np.nan
                          for p in probs])
    return [_num(v) for v in q]


def time_at_reliability(model, reliability, confidence: float = DEFAULT_CONFIDENCE,
                        bound: str = "lower", with_bounds: bool = True) -> dict:
    """The time by which reliability has fallen to each of ``reliability``
    (``qf(1 − R)``), with its bound(s) at ``confidence``.

    Returns ``{"confidence", "bound", "points": [{"reliability", "time",
    "lower", "upper"}], "bounds_note"}``; a side not asked for is None, and so
    is a time the model never reaches (a limited failure population that
    never falls that far)."""
    confidence = check_confidence(confidence)
    if bound not in BOUNDS:
        raise ValueError(f"Unknown bound '{bound}': use lower, upper or two-sided.")
    rs = np.atleast_1d(np.asarray(reliability, dtype=float)).reshape(-1)
    if rs.size == 0 or not np.all((rs > 0) & (rs < 1)):
        raise ValueError("Reliability must be between 0 and 1 (exclusive), e.g. 0.9 for 90%.")
    probs = 1.0 - rs
    times = _quantiles(model, probs)
    lo = hi = None
    note = None if with_bounds else NO_MAXIMUM_NOTE
    if with_bounds:
        note = _no_bounds_reason(model)
    if note is None:
        try:
            lo, hi = _quantile_bounds(model, probs, 1.0 - confidence, bound)
        except Exception as exc:  # noqa: BLE001 - the values stand without their bounds
            note = f"No confidence bounds: {client_reason(exc)}."
            lo = hi = None
        else:
            if is_bayesian(model):
                note = CREDIBLE_NOTE
    points = []
    for i, r in enumerate(rs):
        points.append({
            "reliability": float(r),
            "time": times[i],
            "lower": _num(lo[i]) if lo is not None and times[i] is not None else None,
            "upper": _num(hi[i]) if hi is not None and times[i] is not None else None,
        })
    if _has_intervals(model):
        # Inspection data: each B-life is the interval it falls in, never the
        # interval's end given as both the value and its bound.
        try:
            spans = _interval_points(model, probs, 1.0 - confidence, bound)
        except Exception:  # noqa: BLE001 - the values stand, without bounds
            spans = [{"between": None, "lower": None, "upper": None, "lower_note": None}] * len(points)
        for pt, span in zip(points, spans):
            if span["between"] and span["between"][0] < span["between"][1]:
                pt["time"] = None
                pt["between"] = span["between"]
            pt["lower"], pt["upper"] = span["lower"], span["upper"]
            if span["lower_note"]:
                pt["lower_note"] = span["lower_note"]
        note = INTERVAL_NOTE
    return {"confidence": confidence, "bound": bound, "points": points, "bounds_note": note}


def _mttf(model, alpha: float, with_bounds: bool, tau=None) -> dict:
    if _is_nonparametric(model):
        # #85: the area under an empirical curve, restricted to a horizon
        # unless the curve reaches zero, with mean_cb's bounds.
        from backend import np_life

        return np_life.mean_life(model, alpha, tau)
    out = {"value": None, "lower": None}
    try:
        with np.errstate(all="ignore"):
            out["value"] = _num(model.mean())
    except Exception:  # noqa: BLE001 - no mean: shown as a dash
        return out
    if out["value"] is None or not with_bounds or _is_nonparametric(model) or _no_bounds_reason(model):
        return out
    try:
        with np.errstate(all="ignore"), ignore_warnings(RuntimeWarning):
            # A Bayesian update's mean has a credible bound, not a confidence bound.
            bound = model.mean_cri(alpha_ci=alpha, bound="lower") if is_bayesian(model) \
                else model.mean_cb(alpha_ci=alpha, bound="lower")
            out["lower"] = _num(np.ravel(np.asarray(bound, dtype=float))[0])
    except Exception:  # noqa: BLE001 - the value stands without its bound
        pass
    return out


def life_summary(model, confidence: float = DEFAULT_CONFIDENCE, with_bounds: bool = True, tau=None) -> dict:
    """B1, B5, B10 and B50 and the MTTF, each with a one-sided lower bound at
    ``confidence`` (the time we can be that sure it is at least).

    ``{"confidence", "bound": "lower", "b_lives": [{"p", "label", "value",
    "lower"}], "mttf": {"value", "lower"}, "bounds_note"}``. ``with_bounds``
    false (a fit with no finite maximum) gives the values alone. An MTTF that
    is infinite (a limited failure population: some never fail) is null. A non-parametric estimate's ``mttf`` is its
    mean life to ``tau`` (default: its last observation), with ``tau``,
    ``upper`` and ``restricted`` (#85)."""
    confidence = check_confidence(confidence)
    probs = np.array([p for p, _ in B_LIVES])
    at = time_at_reliability(model, 1.0 - probs, confidence, "lower", with_bounds=with_bounds)
    b_lives = [{"p": p, "label": label, "value": pt["time"], "lower": pt["lower"],
                **({"between": pt["between"]} if pt.get("between") else {}),
                **({"lower_note": pt["lower_note"]} if pt.get("lower_note") else {})}
               for (p, label), pt in zip(B_LIVES, at["points"])]
    return {
        "confidence": confidence,
        "bound": "lower",
        "b_lives": b_lives,
        "mttf": _mttf(model, 1.0 - confidence, with_bounds and at["bounds_note"] in (None, CREDIBLE_NOTE), tau),
        "bounds_note": at["bounds_note"],
    }


def life_for(model, no_finite_maximum: bool = False) -> Optional[dict]:
    """:func:`life_summary` at the default confidence, for a fit payload:
    None when the model has no quantiles to give. Never raises — the life
    card is a convenience, and must never fail a fit."""
    if model is None:
        return None
    try:
        out = life_summary(model, DEFAULT_CONFIDENCE, with_bounds=not no_finite_maximum)
    except Exception:  # noqa: BLE001 - a fit without B-lives is still a fit
        return None
    if all(b["value"] is None for b in out["b_lives"]) and out["mttf"]["value"] is None:
        return None
    return out


MAX_POINTS = 50


def answer(model, body: Optional[dict], no_finite_maximum: bool = False) -> dict:
    """The app's life request on a live model: ``{"confidence"}`` gives the
    :func:`life_summary`; with ``"reliability": [R, ...]`` (and ``"bound"``,
    lower by default) the :func:`time_at_reliability` instead; with
    ``"requirement": {"b", "life"}`` (and an optional ``"unit"`` for the
    sentence) the check of :mod:`backend.life_requirement`. ``"tau"`` sets a
    non-parametric estimate's mean-life horizon (#85). Raises
    ValueError on a bad request."""
    body = body or {}
    confidence = body.get("confidence", DEFAULT_CONFIDENCE)
    if model is None or not hasattr(model, "qf"):
        raise ValueError("This model has no quantile function, so no B-lives.")
    if body.get("requirement") is not None:
        # #295: "B10 ≥ 50,000 at 90%": {"requirement": {"b": 10, "life": 50000}}.
        from backend.life_requirement import check_requirement

        req = body["requirement"] if isinstance(body["requirement"], dict) else {}
        return check_requirement(model, req.get("b"), req.get("life"), confidence,
                                 no_finite_maximum=no_finite_maximum, unit=str(body.get("unit") or ""))
    if body.get("reliability") is not None:
        rel = body["reliability"]
        rel = rel if isinstance(rel, (list, tuple)) else [rel]
        if len(rel) > MAX_POINTS:
            raise ValueError(f"At most {MAX_POINTS} reliabilities at a time.")
        return time_at_reliability(model, rel, confidence, body.get("bound") or "lower",
                                   with_bounds=not no_finite_maximum)
    return life_summary(model, confidence, with_bounds=not no_finite_maximum, tau=body.get("tau"))
