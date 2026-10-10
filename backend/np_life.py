"""Non-parametric life results (#85): the mean life with its bounds, and the
simultaneous confidence bands of the survival curve.

A Kaplan-Meier (or Nelson-Aalen, Fleming-Harrington, Turnbull) estimate
reaches zero only when its last observation is a failure. Otherwise the area
under it, the mean life, can only be counted up to a horizon τ: the
*restricted* mean life (RMST), SurPyval's ``mean(tau)`` with ``mean_cb``
bounding it. The B-lives and their Brookmeyer-Crowley bounds come from
:mod:`backend.life_bounds`, which already reads them off ``quantile_cb``.

The pointwise band (``cb``) holds at each time separately; ``band`` widens it
so the whole curve lies inside it with the stated confidence (Hall-Wellner,
or Nair's equal-precision band). This module only shapes SurPyval's numbers;
it computes nothing itself.
"""

from __future__ import annotations

import math
import warnings
from typing import Optional

import numpy as np

BAND_METHODS = ("hall-wellner", "nair")
BAND_CONFIDENCE = 0.95


def is_nonparametric(model) -> bool:
    """A SurPyval non-parametric estimate (an empirical curve, no ``dist``)."""
    return hasattr(model, "R") and hasattr(model, "mean_cb") and not hasattr(model, "dist")


def _num(v) -> Optional[float]:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) else None


def last_time(model) -> Optional[float]:
    """The largest finite observed time: the default horizon τ."""
    xs = np.asarray(getattr(model, "x", []), dtype=float)
    xs = xs[np.isfinite(xs)]
    return float(xs.max()) if xs.size else None


def check_tau(tau) -> Optional[float]:
    """``tau`` as a positive float (None stays None), or ValueError."""
    if tau is None or tau == "":
        return None
    try:
        t = float(tau)
    except (TypeError, ValueError):
        raise ValueError("The horizon for the mean life must be a number.") from None
    if not math.isfinite(t) or t <= 0:
        raise ValueError("The horizon for the mean life must be a time above 0.")
    return t


def mean_life(model, alpha: float, tau=None) -> dict:
    """The (restricted) mean life to ``tau`` (default: the last observation)
    with its one-sided lower bound at ``1 − alpha`` and the upper end of the
    same interval.

    ``mean_cb`` is two-sided only, so the one-sided ``1 − α`` lower bound is
    the lower end of the two-sided ``1 − 2α`` interval (as the B-lives' are).
    ``restricted`` is false when the curve has reached zero by ``tau``: the
    area is then the whole mean life, the MTTF. ``{"value", "lower", "upper",
    "tau", "restricted"}``; a value SurPyval can't give is None."""
    tau = check_tau(tau)
    end = last_time(model)
    horizon = tau if tau is not None else end
    out = {"value": None, "lower": None, "upper": None, "tau": _num(horizon), "restricted": True}
    if horizon is None:
        return out
    with np.errstate(all="ignore"), warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        try:
            out["value"] = _num(model.mean(horizon))
        except Exception:  # noqa: BLE001 - no mean: shown as a dash
            return out
        try:
            out["restricted"] = not float(np.ravel(model.sf(horizon))[0]) <= 0.0
        except Exception:  # noqa: BLE001 - say restricted: the safe reading
            out["restricted"] = True
        try:
            lo, hi = np.ravel(np.asarray(model.mean_cb(horizon, alpha_ci=min(2 * alpha, 0.999)), dtype=float))[:2]
            out["lower"], out["upper"] = _num(lo), _num(hi)
        except Exception:  # noqa: BLE001 - the value stands without its bounds
            pass
    if out["lower"] is not None and out["value"] is not None:
        # A normal interval can reach below zero; a mean life can't.
        out["lower"] = max(out["lower"], 0.0)
    return out


def bands(model, confidence: float = BAND_CONFIDENCE) -> dict:
    """The survival curve's simultaneous confidence bands at ``confidence``,
    at the estimate's own times: ``{method: {"x", "lower", "upper"}}`` over
    the times each band covers (SurPyval gives NaN outside its range). A band
    SurPyval refuses (no failures, say) is left out; never raises."""
    xs = np.asarray(getattr(model, "x", []), dtype=float)
    xs = xs[np.isfinite(xs)]
    out: dict = {}
    if not xs.size:
        return out
    for method in BAND_METHODS:
        try:
            with np.errstate(all="ignore"), warnings.catch_warnings():
                warnings.simplefilter("ignore", RuntimeWarning)
                b = np.asarray(model.band(xs, method=method, alpha_ci=1.0 - confidence), dtype=float).reshape(-1, 2)
        except Exception:  # noqa: BLE001 - that band isn't available for these data
            continue
        keep = np.isfinite(b[:, 0]) & np.isfinite(b[:, 1])
        if keep.sum() < 2:
            continue
        out[method] = {
            "x": [float(v) for v in xs[keep]],
            "lower": [float(v) for v in b[keep, 0]],
            "upper": [float(v) for v in b[keep, 1]],
        }
    return out
