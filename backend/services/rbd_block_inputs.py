"""A block's life or repair model entered as its mean (#299).

The block dialog takes a model as SurPyval's parameters or, for the common
distributions, as its mean — the MTBF or the MTTR an engineer has to hand —
plus the shape or spread the mean leaves open (a Weibull's β, a lognormal's
σ). This module turns a mean into parameters and says what a model's mean and
median are, for the dialog's echo ("Mean 13.6 h · median 12 h").

Nothing here is a formula of its own: the distribution is SurPyval's, built
with ``from_params``, and its ``mean()`` and ``qf(0.5)`` are SurPyval's. A
mean is turned into parameters by solving SurPyval's own ``mean()`` for the
one parameter it leaves free (the scale, the rate or the log-location),
which the mean moves monotonically.
"""

from __future__ import annotations

import math
import warnings
from typing import Optional

import numpy as np
from scipy.optimize import brentq

from backend.fitting import DISTRIBUTIONS

#: The distributions a mean can be entered for: the parameter solved for,
#: the ones the user gives with the mean (in SurPyval's names), and whether
#: the solved one is positive (solved on the log scale) or a location.
MEAN_ENTRY = {
    "exponential": {"solve": "failure_rate", "given": [], "positive": True},
    "weibull": {"solve": "alpha", "given": ["beta"], "positive": True},
    "lognormal": {"solve": "mu", "given": ["sigma"], "positive": False},
    "normal": {"solve": "mu", "given": ["sigma"], "positive": False},
    "gamma": {"solve": "beta", "given": ["alpha"], "positive": True},
    "loglogistic": {"solve": "alpha", "given": ["beta"], "positive": True},
}
#: The given parameters in words, for a message.
_GIVEN_WORDS = {("weibull", "beta"): "shape β", ("lognormal", "sigma"): "spread σ",
                ("normal", "sigma"): "standard deviation σ", ("gamma", "alpha"): "shape α",
                ("loglogistic", "beta"): "shape β"}


class BlockInputError(ValueError):
    """A model the dialog can't build, in words the user can act on."""


def _finite(value) -> Optional[float]:
    try:
        v = float(np.asarray(value, dtype=float).reshape(-1)[0])
    except (TypeError, ValueError, IndexError):
        return None
    return v if math.isfinite(v) else None


def _entry(distribution_id: str) -> dict:
    entry = DISTRIBUTIONS.get(str(distribution_id or ""))
    if entry is None:
        raise BlockInputError(f"Unknown distribution “{distribution_id}”.")
    return entry


def _build(distribution_id: str, values: list):
    dist = _entry(distribution_id)["dist"]
    with np.errstate(all="ignore"), warnings.catch_warnings():
        warnings.simplefilter("ignore")
        return dist.from_params([float(v) for v in values])


def _names(distribution_id: str) -> list:
    return list(getattr(_entry(distribution_id)["dist"], "parameter_names", []))


def summary(distribution_id: str, params: list) -> dict:
    """The mean and median of a model given as SurPyval parameters
    (``[{name, value}]``), each None where SurPyval's is infinite or
    undefined (a log-logistic with β ≤ 1 has no mean)."""
    names = _names(distribution_id)
    by_name = {}
    for p in params or []:
        try:
            by_name[p["name"]] = float(p["value"])
        except (KeyError, TypeError, ValueError):
            raise BlockInputError("Each parameter needs a name and a number.") from None
    missing = [n for n in names if n not in by_name]
    if missing:
        raise BlockInputError(f"Missing parameter: {', '.join(missing)}.")
    try:
        model = _build(distribution_id, [by_name[n] for n in names])
        with np.errstate(all="ignore"), warnings.catch_warnings():
            warnings.simplefilter("ignore")
            mean = _finite(model.mean())
            median = _finite(model.qf(0.5))
    except BlockInputError:
        raise
    except Exception as exc:  # noqa: BLE001 - SurPyval's own refusal, in its words
        raise BlockInputError(f"These parameters don't make a {_entry(distribution_id)['name']}: {exc}") from None
    return {
        "distribution_id": distribution_id,
        "params": [{"name": n, "value": by_name[n]} for n in names],
        "mean": mean,
        "median": median,
    }


def from_mean(distribution_id: str, mean: float, given: Optional[dict] = None) -> dict:
    """SurPyval parameters whose mean is ``mean``, with the shape or spread
    in ``given`` (``{"beta": 1.6}``); the same answer as :func:`summary`,
    whose ``mean`` is then ``mean`` (to solver precision)."""
    form = MEAN_ENTRY.get(str(distribution_id or ""))
    if form is None:
        name = _entry(distribution_id)["name"]
        raise BlockInputError(f"A {name} can't be entered as a mean: enter its parameters.")
    target = _finite(mean)
    if target is None or target <= 0:
        raise BlockInputError("The mean must be a positive number.")
    given = dict(given or {})
    fixed = {}
    for g in form["given"]:
        v = _finite(given.get(g))
        if v is None or v <= 0:
            raise BlockInputError(f"Give the {_GIVEN_WORDS.get((distribution_id, g), g)} as a positive number.")
        fixed[g] = v
    names = _names(distribution_id)
    solve = form["solve"]

    def mean_at(x: float) -> Optional[float]:
        values = {**fixed, solve: math.exp(x) if form["positive"] else x}
        try:
            model = _build(distribution_id, [values[n] for n in names])
            with np.errstate(all="ignore"), warnings.catch_warnings():
                warnings.simplefilter("ignore")
                return _finite(model.mean())
        except Exception:  # noqa: BLE001 - outside the parameter's range
            return None

    # The mean is monotone in the free parameter: solve on the log of the
    # mean, so a mean of 1e-6 and one of 1e6 solve alike.
    def gap(x: float) -> float:
        m = mean_at(x)
        return math.log(m) - math.log(target) if m is not None and m > 0 else float("nan")

    # Start where the answer usually is (a scale near the mean, a log-mean
    # near its log, a normal's mean at the mean), then widen both ways until
    # the mean crosses the target.
    x0 = math.log(target) if (form["positive"] or distribution_id == "lognormal") else target
    step = 1.0 if (form["positive"] or distribution_id == "lognormal") else max(1.0, abs(target)) / 2
    g0 = gap(x0)
    if not math.isfinite(g0) and distribution_id == "loglogistic" and fixed["beta"] <= 1:
        raise BlockInputError("A log-logistic has a mean only when its shape β is above 1.")
    if not math.isfinite(g0):
        raise BlockInputError(f"No {_entry(distribution_id)['name']} with this shape has that mean.")
    bracket = (x0, x0) if g0 == 0 else None
    for _ in range(80):
        if bracket:
            break
        for x in (x0 - step, x0 + step):
            g = gap(x)
            if math.isfinite(g) and g * g0 <= 0:
                bracket = (min(x0, x), max(x0, x))
                break
        step *= 2.0
    if bracket is None:
        raise BlockInputError(f"No {_entry(distribution_id)['name']} with this shape has that mean.")
    x = bracket[0] if bracket[0] == bracket[1] else brentq(gap, *bracket, xtol=1e-14, rtol=1e-14, maxiter=500)
    value = math.exp(x) if form["positive"] else x
    params = [{"name": n, "value": float(value if n == solve else fixed[n])} for n in names]
    return summary(distribution_id, params)


def mean_entry_forms() -> dict:
    """For the dialog: the distributions that take a mean, and what else
    each needs (SurPyval's parameter names)."""
    return {k: {"given": list(v["given"])} for k, v in MEAN_ENTRY.items() if k in DISTRIBUTIONS}
