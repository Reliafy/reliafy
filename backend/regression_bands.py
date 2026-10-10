"""Confidence bands and B-lives of a regression model at chosen covariates (#54).

A parametric regression model (Weibull PH, Lognormal AFT, …) has a
reliability curve for every covariate row, and SurPyval bounds each one:
``cb(x, Z, on, alpha_ci, bound)`` is the Fisher-matrix (Wald) band of a
function at a row ``Z``, ``quantile_cb(p, Z, …)`` bounds its quantiles (the
B-lives) and ``mean(Z)`` is its mean life. This module only picks the row
and shapes those numbers; it computes nothing itself.

Cox PH is semi-parametric: its baseline is a step curve estimated from the
failures, with no parameters to carry the uncertainty through, so SurPyval
gives it no ``cb`` and Reliafy shows no band or B-lives for it (its ``qf`` is
an event time on a curve that often stops short of 0). The app says so in
words rather than showing nothing.
"""

from __future__ import annotations

import warnings
from typing import Optional

import numpy as np
import pandas as pd

SEMI_PARAMETRIC_NOTE = (
    "No confidence band: Cox PH is semi-parametric, so its baseline is a step curve with no parameters "
    "to carry the uncertainty through.")
SEMI_PARAMETRIC_LIFE_NOTE = (
    "No B-lives: a Cox model's reliability is a step curve that often stops short of 0, so a B-life would "
    "only be one of the failure times. Fit Weibull PH (or another parametric model) on the same covariates "
    "for B-lives and a confidence band.")
STRATIFIED_NOTE = (
    "No confidence band: each stratum of a stratified Cox model has its own step-curve baseline, with no "
    "parameters to carry the uncertainty through.")
NO_MTTF_NOTE = "MTTF: none at these covariates — the model's reliability never falls to 0."
# The regressions of #179 (semi-parametric, shared frailty): SurPyval bounds
# neither their curves nor their quantiles.
NO_BOUNDS_NOTE = (
    "No confidence band: SurPyval doesn't bound this model's curves (a semi-parametric or shared-frailty "
    "regression). Fit Weibull PH (or another parametric model) on the same covariates for a band.")
NO_BOUNDS_LIFE_NOTE = (
    "No B-lives with bounds: SurPyval doesn't bound this model's quantiles (a semi-parametric or "
    "shared-frailty regression). Fit Weibull PH (or another parametric model) on the same covariates for "
    "B-lives and a confidence band.")


def is_regression(entry: Optional[dict]) -> bool:
    """A live fitting-cache entry of a regression model (one with covariate
    inputs)."""
    return bool(entry and entry.get("fields"))


def has_bands(model) -> bool:
    """Whether SurPyval bounds this regression model's curves: the
    parametric families do; Cox PH (stratified or not) doesn't."""
    return model is not None and callable(getattr(model, "cb", None)) and callable(
        getattr(model, "quantile_cb", None))


def _is_cox(result: dict) -> bool:
    return (result.get("distribution_id") or "") == "cox_ph"


def _unbounded(result: dict) -> bool:
    """One of the regressions of #179, which have no band either."""
    from backend import more_models

    return (result.get("distribution_id") or "") in more_models.REGRESSION


def _is_cox_model(model) -> bool:
    """A live Cox PH model (stratified or not), as opposed to another model
    without bands."""
    from backend.regression_diagnostics import StratifiedCox

    return isinstance(model, StratifiedCox) or type(model).__name__ == "SemiParametricRegressionModel"


def band_note(model) -> str:
    """Why a live regression model has no band, in words."""
    return SEMI_PARAMETRIC_NOTE if _is_cox_model(model) else NO_BOUNDS_NOTE


def life_note(model) -> str:
    """Why a live regression model has no bounded B-lives, in words."""
    return SEMI_PARAMETRIC_LIFE_NOTE if _is_cox_model(model) else NO_BOUNDS_LIFE_NOTE


def result_has_bands(result: Optional[dict]) -> bool:
    """From a fit payload alone: a regression model with a band and bounded
    B-lives (every parametric family; not Cox PH)."""
    r = result or {}
    return (r.get("kind") == "regression" and not _is_cox(r) and not _unbounded(r)
            and bool(r.get("functions")))


def no_bands_note(result: Optional[dict]) -> Optional[str]:
    """Why a regression fit has no band, in words (None when it has one)."""
    r = result or {}
    if r.get("kind") == "regression" and _unbounded(r):
        return NO_BOUNDS_NOTE
    if r.get("kind") != "regression" or not _is_cox(r):
        return None
    strata = ((r.get("options") or {}).get("cox") or {}).get("strata")
    return STRATIFIED_NOTE if strata else SEMI_PARAMETRIC_NOTE


def notes(result: Optional[dict]) -> dict:
    """``{"bands_note", "life_note"}`` for a regression fit with no band and
    no B-lives (Cox PH): what the calculator and the life card say instead
    of nothing. ``{}`` for any other fit."""
    note = no_bands_note(result)
    if not note:
        return {}
    return {"bands_note": note,
            "life_note": NO_BOUNDS_LIFE_NOTE if _unbounded(result or {}) else SEMI_PARAMETRIC_LIFE_NOTE}


def covariate_row(fields: list, values: Optional[dict]) -> Optional[pd.DataFrame]:
    """The one-row covariate frame for ``values`` (a field left out, blank or
    not a number takes the fit's default), exactly as the calculator's curves
    are evaluated (``fitting.evaluate``)."""
    if not fields:
        return None
    values = values or {}
    row = {}
    for f in fields:
        value = values.get(f["name"], f["default"])
        if value in (None, ""):
            value = f["default"]
        if f.get("type") == "number":
            try:
                value = float(value)
            except (TypeError, ValueError):
                value = float(f["default"])
            if not np.isfinite(value):
                value = float(f["default"])
        else:
            value = str(value)
        row[f["name"]] = [value]
    return pd.DataFrame(row)


def band(model, fields: list, values: Optional[dict], grid: np.ndarray, on: str, alpha_ci: float,
         bound: str) -> np.ndarray:
    """SurPyval's ``cb`` of ``on`` over ``grid`` at the covariate row of
    ``values``: an ``(n, 2)`` array for a two-sided band, else ``(n,)``.

    Where the reliability is pinned at 1 or 0 (t = 0, or before a lifetime's
    support starts) the value is certain, so the bound there is the value
    itself; asking SurPyval at those points only risks a zero variance it
    calls undefined (see ``fitting._cb_off_pinned_points``)."""
    if not has_bands(model):
        raise ValueError(band_note(model))
    Z = covariate_row(fields, values)
    grid = np.asarray(grid, dtype=float)
    with np.errstate(all="ignore"), warnings.catch_warnings():
        warnings.simplefilter("ignore")
        sf = np.asarray(model.sf(grid, Z), dtype=float).ravel()
        free = np.isfinite(sf) & (sf > 0) & (sf < 1)
        if free.all() or not free.any():
            return np.asarray(model.cb(grid, Z, on=on, alpha_ci=alpha_ci, bound=bound), dtype=float)
        inner = np.asarray(model.cb(grid[free], Z, on=on, alpha_ci=alpha_ci, bound=bound), dtype=float)
        value = np.asarray(getattr(model, on)(grid[~free], Z), dtype=float).ravel()
    out = np.empty((grid.size, 2) if inner.ndim == 2 else grid.size, dtype=float)
    out[free] = inner
    out[~free] = value[:, None] if inner.ndim == 2 else value
    return out


class AtCovariates:
    """A regression model held at one covariate row, with the univariate
    quantile interface :mod:`backend.life_bounds` reads (``qf``,
    ``quantile_cb``, ``mean``), so the B-lives, MTTF and time at a
    reliability come from the same code as a plain distribution's — each
    value SurPyval's, at that row. A regression model has no ``mean_cb``, so
    its MTTF comes without a bound."""

    method = "MLE"

    def __init__(self, model, Z: Optional[pd.DataFrame]):
        self._model = model
        self._Z = Z

    def qf(self, p):
        return self._model.qf(np.atleast_1d(np.asarray(p, dtype=float)), self._Z)

    def quantile_cb(self, p, alpha_ci=0.05, bound="two-sided"):
        return self._model.quantile_cb(np.atleast_1d(np.asarray(p, dtype=float)), self._Z,
                                       alpha_ci=alpha_ci, bound=bound)

    def mean(self):
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            value = float(np.ravel(np.asarray(self._model.mean(self._Z), dtype=float))[0])
        # An additive-hazards row whose reliability never reaches 0 has no
        # finite mean, whatever number the integral stopped at.
        if any("has not fallen to 0" in str(w.message) for w in caught):
            return float("inf")
        return value


def life_answer(model, fields: list, body: Optional[dict], no_finite_maximum: bool = False) -> dict:
    """:func:`backend.life_bounds.answer` for a regression model at the
    covariate row ``body["covariates"]`` (the fit's defaults for any left
    out), echoed back as ``covariates``. Raises ValueError for Cox PH (no
    B-lives, by design) and on a bad request."""
    from backend import life_bounds

    if not has_bands(model):
        raise ValueError(life_note(model))
    body = dict(body or {})
    Z = covariate_row(fields, body.pop("covariates", None))
    out = life_bounds.answer(AtCovariates(model, Z), body, no_finite_maximum=no_finite_maximum)
    if Z is not None:
        out["covariates"] = {k: (v[0].item() if hasattr(v[0], "item") else v[0])
                             for k, v in Z.to_dict("list").items()}
    mttf = out.get("mttf")
    if mttf is not None and mttf.get("value") is None and out.get("b_lives"):
        out["mttf_note"] = NO_MTTF_NOTE
    return out
