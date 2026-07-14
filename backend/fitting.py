"""Parametric model fitting and probability-plot data preparation.

Wraps SurPyval's parametric distributions. SurPyval does the heavy lifting
(parameter estimation, plotting positions, confidence bounds); this module
turns a CSV upload plus a column mapping into the ``x/c/n/xl/xr/tl/tr`` inputs
SurPyval expects, and shapes the plot data for a Plotly frontend.

The probability-plot axes are linearised with each distribution's own
``mpp_x_transform`` / ``mpp_y_transform`` so that a good fit plots as a straight
line. Because the transforms are applied here, the frontend can draw every
distribution on plain linear axes.

SurPyval's input model (see ``surpyval.utils.xcnt_handler``):

* ``x``    – observed values (1-D). Used for exact / right / left censored data.
* ``xl`` + ``xr`` – left and right bounds of interval-censored data. Must be
  supplied together and cannot be combined with ``x``.
* ``c``    – censoring flag per row: 0 observed, 1 right, -1 left, 2 interval.
* ``n``    – positive-integer count of observations per row.
* ``tl`` / ``tr`` – left / right truncation bounds per row (``-inf``/``inf``
  meaning untruncated on that side).
"""

from __future__ import annotations

import io
import json
import math
import uuid
from collections import OrderedDict
from typing import Optional

import numpy as np
import pandas as pd
from surpyval import (
    Exponential,
    ExponentialPH,
    Gamma,
    GammaPH,
    LogNormal,
    LogNormalPH,
    Normal,
    NormalPH,
    Weibull,
    WeibullPH,
)
from surpyval import ExpoWeibull, Gumbel, Logistic, LogLogistic
from surpyval import Binomial, FlemingHarrington, KaplanMeier, NelsonAalen, Turnbull
from surpyval import DiscreteWeibull, Geometric, NegativeBinomial
from surpyval.univariate.regression import CoxPH

# Plain distributions (no covariates), keyed by the id used in the API/URL.
# ``offsetable``: supports the 3-parameter offset (failure-free period) —
# only distributions on the half real line; a location shift is meaningless
# for full-real-line supports (Normal, Gumbel, Logistic).
DISTRIBUTIONS = {
    "weibull": {"name": "Weibull", "dist": Weibull, "offsetable": True},
    "exponential": {"name": "Exponential", "dist": Exponential, "offsetable": True},
    "normal": {"name": "Normal", "dist": Normal, "offsetable": False},
    "lognormal": {"name": "Lognormal", "dist": LogNormal, "offsetable": True},
    "gamma": {"name": "Gamma", "dist": Gamma, "offsetable": True},
    "loglogistic": {"name": "LogLogistic", "dist": LogLogistic, "offsetable": True},
    "expo_weibull": {"name": "Exponentiated Weibull", "dist": ExpoWeibull, "offsetable": True},
    "gumbel": {"name": "Gumbel", "dist": Gumbel, "offsetable": False},
    "logistic": {"name": "Logistic", "dist": Logistic, "offsetable": False},
}

# Discrete lifetime distributions: for life measured in whole counts — cycles,
# shocks, or demands to failure — rather than continuous time. Same x/c/n
# mapping and standard ``.fit`` interface as the continuous distributions, but
# there's no probability paper (no ``mpp`` transforms), so they produce fitted
# parameters, reliability functions and goodness-of-fit without a probability
# plot. Kept separate from ``DISTRIBUTIONS`` so they don't enter the continuous
# "best fit" comparison, which mixes incompatible supports.
DISCRETE = {
    "discrete_weibull": {"name": "Discrete Weibull", "dist": DiscreteWeibull},
    "geometric": {"name": "Geometric", "dist": Geometric},
    "negative_binomial": {"name": "Negative Binomial", "dist": NegativeBinomial},
}

# Non-parametric estimators (no distribution assumed): the "estimation axis"
# of the same single-event life data. Same x/c/n/xl/xr/tl/tr mapping as the
# distributions; produce an empirical survival curve, not fitted parameters.
NONPARAMETRIC = {
    "kaplan_meier": {"name": "Kaplan-Meier", "est": KaplanMeier},
    "nelson_aalen": {"name": "Nelson-Aalen", "est": NelsonAalen},
    "fleming_harrington": {"name": "Fleming-Harrington", "est": FlemingHarrington},
    "turnbull": {"name": "Turnbull", "est": Turnbull},
}

# Proportional-hazards regression models (require covariates). Each is fit with
# ``fitter.fit_from_df`` using covariate columns or a formula.
REGRESSION_MODELS = {
    "weibull_ph": {"name": "Weibull PH", "fitter": WeibullPH},
    "exponential_ph": {"name": "Exponential PH", "fitter": ExponentialPH},
    "lognormal_ph": {"name": "Lognormal PH", "fitter": LogNormalPH},
    "normal_ph": {"name": "Normal PH", "fitter": NormalPH},
    "gamma_ph": {"name": "Gamma PH", "fitter": GammaPH},
    "cox_ph": {"name": "Cox PH (semi-parametric)", "fitter": CoxPH},
}

# Probabilities are clipped away from 0/1 before the y-transform, which would
# otherwise map them to +/- infinity.
_EPS = 1e-12

# In-memory store of fitted regression models so the calculator can re-evaluate
# the reliability functions at user-entered covariate values without re-fitting
# (the model handles its own encoding, including categoricals). Bounded so it
# can't grow without limit; ids are invalidated on process restart.
_MODEL_STORE: "OrderedDict[str, dict]" = OrderedDict()
_MODEL_STORE_MAX = 64


class ModelNotFound(KeyError):
    """Raised when an evaluate request references an unknown/expired model."""


def _store_model(model, grid: np.ndarray, fields: list) -> str:
    model_id = uuid.uuid4().hex
    _MODEL_STORE[model_id] = {"model": model, "grid": grid, "fields": fields}
    while len(_MODEL_STORE) > _MODEL_STORE_MAX:
        _MODEL_STORE.popitem(last=False)
    return model_id


class FitError(ValueError):
    """Raised when the uploaded data cannot be turned into a fitted model."""


def read_dataframe(file_bytes: bytes) -> pd.DataFrame:
    """Parse uploaded bytes as a CSV into a DataFrame."""
    try:
        df = pd.read_csv(io.BytesIO(file_bytes))
    except Exception as exc:  # pragma: no cover - pandas raises many types
        raise FitError(f"Could not parse the file as CSV: {exc}") from exc

    if df.empty or df.shape[1] == 0:
        raise FitError("The uploaded CSV is empty.")
    return df


def preview(file_bytes: bytes, rows: int = 5) -> dict:
    """Return column names and a small sample of rows for the mapping UI."""
    df = read_dataframe(file_bytes)
    columns = [str(c) for c in df.columns]
    sample = (
        df.head(rows)
        .astype(object)
        .where(pd.notna(df.head(rows)), None)
        .values.tolist()
    )
    return {"columns": columns, "preview": sample, "n_rows": int(df.shape[0])}


def build_fit_inputs(df: pd.DataFrame, mapping: dict) -> dict:
    """Turn a column mapping into keyword arguments for ``<dist>.fit``.

    ``mapping`` maps any of ``x/c/n/xl/xr/tl/tr`` to a CSV column name. No
    validation is done here — SurPyval validates the combination of inputs and
    raises with a helpful message, which we surface. Columns are coerced to
    numbers (non-numeric cells become NaN, which SurPyval rejects), and blank
    truncation cells become the "untruncated" infinities.
    """
    mapping = {k: v for k, v in mapping.items() if v}  # drop unset fields

    kwargs: dict = {}
    for field, name in mapping.items():
        col = pd.to_numeric(df[name], errors="coerce").to_numpy(dtype=float)
        if field == "tl":
            col = np.where(np.isnan(col), -np.inf, col)
        elif field == "tr":
            col = np.where(np.isnan(col), np.inf, col)
        kwargs[field] = col

    return kwargs


def _ensure_covariance(model) -> None:
    """Work around a SurPyval numerical issue so confidence bounds are available.

    For large-scale fits (e.g. a Weibull with a scale parameter in the
    thousands) SurPyval's autograd Hessian can evaluate to NaN, leaving the
    model without a covariance matrix and therefore without confidence bounds.
    When that happens, recompute the covariance as the inverse of a
    finite-difference Hessian of the model's own negative log-likelihood at the
    MLE, using a per-parameter *relative* step so large magnitudes don't
    overflow. The point estimates are untouched — only the (missing) covariance
    is filled in. On any failure the model is left as-is and the band is simply
    omitted.
    """
    cov = getattr(model, "cov_matrix", None)
    if cov is not None and np.all(np.isfinite(np.asarray(cov, dtype=float))):
        return  # SurPyval already produced a usable covariance.
    # LFP/ZI fits carry the extra parameter inside the covariance (k+1 square);
    # recomputing over the base params alone would swap in a wrong-shaped
    # matrix and break the confidence bands. Leave those as-is.
    if float(getattr(model, "f0", 0.0) or 0.0) != 0.0:
        return
    if float(getattr(model, "p", 1.0) or 1.0) != 1.0:
        return
    try:
        params = np.asarray(model.params, dtype=float)
        gamma = float(getattr(model, "gamma", 0.0) or 0.0)
        f0 = float(getattr(model, "f0", 0.0) or 0.0)
        p = float(getattr(model, "p", 1.0) or 1.0)
        surv_data = model.surv_data
        neg_ll = model.dist._neg_ll_func

        def nll(theta):
            return float(neg_ll(surv_data, *theta, gamma, f0, p))

        n = len(params)
        step = np.maximum(np.abs(params), 1.0) * (np.finfo(float).eps ** (1 / 3)) * 50
        hess = np.empty((n, n))
        for i in range(n):
            for j in range(n):
                ei = np.zeros(n)
                ei[i] = step[i]
                ej = np.zeros(n)
                ej[j] = step[j]
                hess[i, j] = (
                    nll(params + ei + ej)
                    - nll(params + ei - ej)
                    - nll(params - ei + ej)
                    + nll(params - ei - ej)
                ) / (4 * step[i] * step[j])
        recomputed = np.linalg.inv(hess)
        if np.all(np.isfinite(recomputed)) and np.all(np.diag(recomputed) > 0):
            model.cov_matrix = recomputed
            model.hess_inv = recomputed
    except Exception:  # pragma: no cover - defensive; the band is just omitted
        pass


def _shape_plot(model, dist, heuristic: str = "Nelson-Aalen") -> dict:
    """Shape SurPyval's plot data into Plotly-ready (already-linearised) arrays.

    Both axes are transformed with the distribution's own probability-paper
    functions, so the frontend draws on plain linear axes.
    """
    data = model.get_plot_data(heuristic=heuristic)
    params = model.params

    def ty(p):
        p = np.clip(np.asarray(p, dtype=float), _EPS, 1 - _EPS)
        return dist.mpp_y_transform(p, *params)

    def tx(x):
        return dist.mpp_x_transform(np.asarray(x, dtype=float))

    scatter_x = tx(data["x_"])
    scatter_y = ty(data["F"])

    line_x = tx(data["x_model"])
    line_y = ty(data["cdf"])

    bounds = np.asarray(data["cbs"], dtype=float)
    lower = ty(bounds[:, 0])
    upper = ty(bounds[:, 1])

    x_ticks = tx(data["x_ticks"])
    y_ticks = ty(np.asarray(data["y_ticks"], dtype=float))

    x_range = [
        float(tx(np.array([data["x_scale_min"]]))[0]),
        float(tx(np.array([data["x_scale_max"]]))[0]),
    ]
    y_range = [
        float(ty(np.array([data["y_scale_min"]]))[0]),
        float(ty(np.array([data["y_scale_max"]]))[0]),
    ]

    return {
        "scatter": {"x": scatter_x.tolist(), "y": scatter_y.tolist()},
        "line": {"x": line_x.tolist(), "y": line_y.tolist()},
        "bounds": {
            "x": line_x.tolist(),
            "lower": lower.tolist(),
            "upper": upper.tolist(),
        },
        "x_range": x_range,
        "y_range": y_range,
        "x_ticks": {"vals": x_ticks.tolist(), "labels": list(data["x_ticks_labels"])},
        "y_ticks": {
            "vals": y_ticks.tolist(),
            "labels": list(data["y_ticks_labels"]),
        },
    }


def options_from_form(
    offset: Optional[str] = None,
    zi: Optional[str] = None,
    lfp: Optional[str] = None,
    fixed: Optional[str] = None,
) -> Optional[dict]:
    """Build an options dict from HTML-form string fields (both fit routers)."""

    def truthy(v):
        return str(v or "").strip().lower() in {"1", "true", "yes", "on"}

    opts = {"offset": truthy(offset), "zi": truthy(zi), "lfp": truthy(lfp)}
    if fixed and str(fixed).strip():
        try:
            opts["fixed"] = json.loads(fixed)
        except json.JSONDecodeError:
            raise FitError('fixed must be valid JSON, e.g. {"beta": 2}.')
    return opts if any(opts.values()) else None


# Pseudo-distribution id: fit every plain distribution and keep the lowest-AIC.
BEST_ID = "best"


def normalize_options(distribution: str, options: Optional[dict]) -> dict:
    """Validate/clean fit options (offset, zi, lfp, fixed) for a distribution.

    Raises :class:`FitError` on invalid combinations so both routers share the
    same messages.
    """
    opts = dict(options or {})
    out = {
        "offset": bool(opts.get("offset")),
        "zi": bool(opts.get("zi")),
        "lfp": bool(opts.get("lfp")),
        "fixed": opts.get("fixed") or None,
    }
    if not any([out["offset"], out["zi"], out["lfp"], out["fixed"]]):
        return {}
    if distribution == BEST_ID:
        if out["fixed"]:
            raise FitError(
                "Fix parameters after choosing a specific distribution — "
                "'Best fit' compares models with different parameter sets."
            )
        # offset applies only to the offsetable candidates; handled per-fit.
        return {k: v for k, v in out.items() if v}
    entry = DISTRIBUTIONS.get(distribution)
    if entry is None:
        raise FitError(
            "Fit options (offset/zi/lfp/fixed) apply to plain distributions only, "
            "not regression models."
        )
    if out["offset"] and not entry.get("offsetable"):
        raise FitError(
            f"{entry['name']} doesn't support an offset — its support is the "
            "whole real line, so a failure-free period isn't meaningful."
        )
    fixed = out["fixed"]
    if fixed is not None:
        if not isinstance(fixed, dict):
            raise FitError('fixed must be an object like {"beta": 2}.')
        names = set(getattr(entry["dist"], "param_names", []) or [])
        # Extras can be fixed too when their option is active.
        if out["offset"]:
            names.add("gamma")
        if out["lfp"]:
            names.add("p")
        if out["zi"]:
            names.add("f0")
        unknown = set(fixed) - names
        if unknown:
            raise FitError(
                f"Can't fix {', '.join(sorted(unknown))} — {entry['name']}'s "
                f"parameters are: {', '.join(sorted(names))}."
            )
        try:
            out["fixed"] = {k: float(v) for k, v in fixed.items()}
        except (TypeError, ValueError):
            raise FitError("Fixed parameter values must be numbers.")
    return {k: v for k, v in out.items() if v}


def fit(
    distribution: str,
    df: pd.DataFrame,
    mapping: dict,
    covariates: Optional[list] = None,
    formula: Optional[str] = None,
    unit: Optional[str] = None,
    options: Optional[dict] = None,
) -> dict:
    """Fit ``distribution`` (plain or proportional hazards) and build the payload.

    If ``distribution`` is a regression model it is fit with covariate columns
    (``covariates``) or a ``formula``; otherwise the plain distribution path is
    used. ``unit`` is the (optional) unit of ``x`` carried through for display.
    ``options`` (plain distributions only) may hold ``offset``/``zi``/``lfp``
    booleans and a ``fixed`` mapping. Any SurPyval error is wrapped in
    :class:`FitError`.
    """
    options = normalize_options(distribution, options)
    if distribution in REGRESSION_MODELS:
        result = _fit_regression(distribution, df, mapping, covariates, formula)
    elif distribution == BEST_ID:
        result = _fit_best(df, mapping, options)
    elif distribution in NONPARAMETRIC:
        result = _fit_nonparametric(distribution, df, mapping)
    elif distribution in DISCRETE:
        result = _fit_discrete(distribution, df, mapping)
    elif distribution in DISTRIBUTIONS:
        result = _fit_distribution(distribution, df, mapping, options)
    else:
        raise FitError(
            f"Unknown model '{distribution}'. Available: "
            f"{', '.join([BEST_ID, *DISTRIBUTIONS, *DISCRETE, *NONPARAMETRIC, *REGRESSION_MODELS])}."
        )
    result["unit"] = (unit or "").strip()
    # Confidence bounds and probability-paper transforms can produce non-finite
    # values at the extremes (e.g. a Weibull bound that maps to ±inf/NaN). These
    # are not valid JSON, so coerce them to null — Plotly renders them as gaps.
    return _json_safe(result)


def _json_safe(value):
    """Recursively replace non-finite floats (NaN, ±inf) with ``None`` so the
    payload is valid JSON (``json.dumps`` with ``allow_nan=False``)."""
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, dict):
        return {k: _json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(v) for v in value]
    if isinstance(value, np.floating):
        f = float(value)
        return f if math.isfinite(f) else None
    if isinstance(value, np.integer):
        return int(value)
    return value


def resolve_distribution_id(name: str) -> str:
    """Map a SurPyval distribution name (or a Reliafy id) to a Reliafy id.

    Accepts 'Weibull', 'weibull', 'LogNormal', 'lognormal', 'ExpoWeibull',
    'expo_weibull', etc. Raises FitError for anything unsupported.
    """
    if not name:
        raise FitError("No distribution given.")
    key = str(name).strip().lower().replace(" ", "_")
    if key in DISTRIBUTIONS:
        return key
    aliases = {
        "expoweibull": "expo_weibull",
        "exponentiatedweibull": "expo_weibull",
        "log_normal": "lognormal",
        "log_logistic": "loglogistic",
    }
    if key in aliases:
        return aliases[key]
    # Match by the human name of each distribution ("Weibull" -> "weibull").
    for did, entry in DISTRIBUTIONS.items():
        if entry["name"].lower().replace(" ", "_") == key:
            return did
    raise FitError(
        f"'{name}' isn't a supported plain distribution. Supported: "
        f"{', '.join(DISTRIBUTIONS)}."
    )


def result_from_params(
    distribution_id: str,
    params: list,
    extras: Optional[dict] = None,
    unit: Optional[str] = None,
) -> dict:
    """Build a result payload from parameters alone (no data).

    Used by model import when only the fitted parameters are supplied: there
    are no observations, so there's no probability plot or goodness-of-fit —
    but the reliability functions and life metrics are fully available.
    """
    entry = DISTRIBUTIONS.get(distribution_id)
    if entry is None:
        raise FitError(
            f"'{distribution_id}' isn't a supported plain distribution. "
            f"Supported: {', '.join(DISTRIBUTIONS)}."
        )
    dist = entry["dist"]
    values = [float(p["value"]) for p in (params or []) if "value" in p]
    if not values:
        raise FitError("No parameter values supplied.")
    kwargs = {
        k: float(v) for k, v in (extras or {}).items()
        if k in ("gamma", "p", "f0") and v is not None
    }
    try:
        model = dist.from_params(values, **kwargs)
    except Exception as exc:
        raise FitError(str(exc) or f"{type(exc).__name__}") from exc

    names = list(getattr(dist, "param_names", []) or [f"p{i}" for i in range(len(values))])
    result = {
        "distribution": entry["name"],
        "distribution_id": distribution_id,
        "kind": "distribution",
        "params": [{"name": n, "value": v, "se": None, "ci": None} for n, v in zip(names, values)],
        "n": None,
        "plot": None,
        "functions": {"meta": FUNCTIONS, "curves": _function_curves(model)},
        "gof": [],
        "unit": (unit or "").strip(),
        "params_only": True,
    }
    if kwargs:
        result["extras"] = kwargs
        result["extra_params"] = [{"name": _EXTRA_LABELS[k], "value": v} for k, v in kwargs.items()]
    randomness = _randomness_verdict(distribution_id, result["params"])
    if randomness is not None:
        result["randomness"] = randomness
    return _json_safe(result)


def result_per_demand(demands: int, failures: int) -> dict:
    """Per-demand (Binomial) reliability: probability of failure per demand.

    For one-shot / protective equipment where "reliability" is per-demand, not
    over time. ``p = failures / demands`` with a Wilson-score 95% interval
    (robust near 0 and 1). Reconstructs downstream via ``Binomial.from_params``.
    """
    try:
        demands = int(demands)
        failures = int(failures)
    except (TypeError, ValueError):
        raise FitError("Demands and failures must be whole numbers.")
    if demands <= 0:
        raise FitError("Number of demands must be a positive integer.")
    if not (0 <= failures <= demands):
        raise FitError("Failures must be between 0 and the number of demands.")

    p = failures / demands
    z = 1.959963984540054  # 95%
    denom = 1 + z * z / demands
    centre = (p + z * z / (2 * demands)) / denom
    half = z * math.sqrt(p * (1 - p) / demands + z * z / (4 * demands * demands)) / denom
    ci = [max(0.0, centre - half), min(1.0, centre + half)]

    return _json_safe({
        "distribution": "Per-demand (Binomial)",
        "distribution_id": "binomial",
        "kind": "per_demand",
        "params": [{"name": "p", "value": p, "se": None, "ci": ci}],
        "n": demands,
        "per_demand": {
            "demands": demands, "failures": failures,
            "p": p, "ci": ci, "reliability": 1.0 - p,
        },
        "functions": None,
        "gof": [],
    })


def _fit_best(df: pd.DataFrame, mapping: dict, options: Optional[dict] = None) -> dict:
    """Fit every plain distribution and return the full result for the
    lowest-AIC winner, with the ranking attached as ``selection``.

    The scoring pass is fits-only (no plots); the winner is then refit through
    the normal path so its payload is identical to a direct fit. Options apply
    per candidate where valid (offset only on offsetable distributions).
    """
    options = options or {}
    try:
        base_kwargs = build_fit_inputs(df, mapping)
    except Exception as exc:
        raise FitError(str(exc) or f"{type(exc).__name__}") from exc

    ranking = []
    for dist_id, entry in DISTRIBUTIONS.items():
        kwargs = dict(base_kwargs)
        for key in ("zi", "lfp"):
            if options.get(key):
                kwargs[key] = True
        if options.get("offset") and entry.get("offsetable"):
            kwargs["offset"] = True
        try:
            model = entry["dist"].fit(**kwargs)
            gof = _goodness_of_fit(model)
            aic = next((g["value"] for g in gof if g["id"] == "aic"), None)
        except Exception:
            continue  # a distribution that won't fit this data is skipped
        if aic is None or not math.isfinite(float(aic)):
            continue
        ranking.append({"id": dist_id, "name": entry["name"], "aic": float(aic)})

    if not ranking:
        raise FitError("None of the distributions could be fit to this data.")
    ranking.sort(key=lambda r: r["aic"])

    winner = ranking[0]["id"]
    win_options = dict(options)
    if win_options.get("offset") and not DISTRIBUTIONS[winner].get("offsetable"):
        win_options.pop("offset")
    result = _fit_distribution(winner, df, mapping, win_options)
    result["selection"] = {"criterion": "aic", "candidates": ranking}
    return result


# Extra fitted quantities from fit options: attribute name -> display label.
_EXTRA_LABELS = {
    "gamma": "gamma (offset)",
    "p": "p (max fraction failing)",
    "f0": "f0 (failed at t=0)",
}


def _extract_extras(model, options: dict) -> dict:
    """Pull the extra fitted quantities (offset gamma, LFP p, ZI f0)."""
    extras = {}
    if options.get("offset"):
        extras["gamma"] = float(getattr(model, "gamma"))
    if options.get("lfp"):
        extras["p"] = float(getattr(model, "p"))
    if options.get("zi"):
        extras["f0"] = float(getattr(model, "f0"))
    return extras


def _fit_distribution(
    distribution: str, df: pd.DataFrame, mapping: dict, options: Optional[dict] = None
) -> dict:
    entry = DISTRIBUTIONS[distribution]
    dist = entry["dist"]
    options = options or {}

    try:
        kwargs = build_fit_inputs(df, mapping)
        for key in ("offset", "zi", "lfp", "fixed"):
            if options.get(key):
                kwargs[key] = options[key]
        model = dist.fit(**kwargs)
        # Backfill the covariance when SurPyval's Hessian came out non-finite
        # (otherwise the confidence band would be all-NaN).
        _ensure_covariance(model)

        # Left (c=-1) and interval (c=2) censoring require the Turnbull
        # estimator for the empirical plotting positions.
        c = np.asarray(model.data["c"])
        heuristic = "Turnbull" if np.any((c == -1) | (c == 2)) else "Nelson-Aalen"
        plot = _shape_plot(model, dist, heuristic=heuristic)
        curves = _function_curves(model)
        gof = _goodness_of_fit(model)
    except Exception as exc:
        raise FitError(str(exc) or f"{type(exc).__name__}") from exc

    param_names = (
        getattr(model, "param_names", None)
        or getattr(dist, "param_names", None)
        or [f"p{i}" for i in range(len(model.params))]
    )
    params = _params_with_uncertainty(model, param_names)

    # Stash the live model so its confidence bounds can be recomputed on demand
    # (configurable level / bound) over the same grid the curves use.
    cache_id = _store_model(model, np.asarray(curves["x"], dtype=float), [])
    result = {
        "distribution": entry["name"],
        "distribution_id": distribution,
        "kind": "distribution",
        "params": params,
        "n": int(np.sum(model.data["n"])),
        "plot": plot,
        "functions": {"meta": FUNCTIONS, "curves": curves, "model_id": cache_id},
        "gof": gof,
    }
    if options:
        # Extra fitted quantities ride separately from ``params`` so every
        # downstream ``from_params(values)`` reconstruction stays valid; the
        # extras are re-applied via keyword arguments where models are rebuilt.
        extras = _extract_extras(model, options)
        if extras:
            result["extras"] = extras
            result["extra_params"] = [
                {"name": _EXTRA_LABELS[k], "value": v} for k, v in extras.items()
            ]
        result["options"] = {
            k: options[k] for k in ("offset", "zi", "lfp", "fixed") if options.get(k)
        }
    randomness = _randomness_verdict(distribution, params)
    if randomness is not None:
        result["randomness"] = randomness
    return result


# Value-axis columns for a discrete fit (event, interval and truncation
# bounds). All must land on the positive integers; ``n`` is a repeat count and
# is integer by construction, so it's not checked here.
_DISCRETE_AXIS_KEYS = ("x", "xl", "xr", "tl", "tr")


def _validate_discrete_inputs(kwargs: dict) -> None:
    """Discrete distributions live on the positive integers {1, 2, 3, ...}.

    SurPyval accepts floating-point values without complaint and would silently
    fit nonsense, so reject non-integer or sub-1 values up front with a clear
    message (the caller can pick a continuous distribution instead).
    """
    for key in _DISCRETE_AXIS_KEYS:
        if key not in kwargs:
            continue
        arr = np.asarray(kwargs[key], dtype=float)
        arr = arr[np.isfinite(arr)]
        if arr.size == 0:
            continue
        non_integer = np.unique(arr[np.mod(arr, 1) != 0])
        if non_integer.size:
            examples = ", ".join(f"{v:g}" for v in non_integer[:3])
            raise FitError(
                "Discrete distributions need whole-number counts — cycles, shocks "
                f"or demands to failure. Found non-integer values ({examples}). "
                "Round the data to whole numbers, or choose a continuous distribution."
            )
        if np.any(arr < 1):
            raise FitError(
                "Discrete distributions count from 1 (the first cycle or demand); "
                "values below 1 aren't supported. Shift a zero-based count by 1."
            )


def _fit_discrete(distribution: str, df: pd.DataFrame, mapping: dict) -> dict:
    """Fit a discrete lifetime distribution (Discrete Weibull / Geometric /
    Negative Binomial) to whole-count data.

    Same estimation machinery as the continuous distributions — fitted
    parameters (with confidence intervals), reliability functions and
    goodness-of-fit — but discrete models carry no probability-paper
    transforms, so there's no probability plot. Life metrics (median / MTTF /
    B10) come through as for any other model.
    """
    entry = DISCRETE[distribution]
    dist = entry["dist"]
    try:
        kwargs = build_fit_inputs(df, mapping)
        _validate_discrete_inputs(kwargs)
        model = dist.fit(**kwargs)
        curves = _function_curves(model)
        gof = _goodness_of_fit(model)
        metrics = _life_metrics(model)
    except Exception as exc:
        raise FitError(str(exc) or f"{type(exc).__name__}") from exc

    param_names = (
        getattr(model, "param_names", None)
        or getattr(dist, "param_names", None)
        or [f"p{i}" for i in range(len(model.params))]
    )
    params = _params_with_uncertainty(model, param_names)

    cache_id = _store_model(model, np.asarray(curves["x"], dtype=float), [])
    return {
        "distribution": entry["name"],
        "distribution_id": distribution,
        "kind": "discrete",
        "params": params,
        "n": int(np.sum(model.data["n"])),
        "plot": None,
        "functions": {"meta": FUNCTIONS, "curves": curves, "model_id": cache_id},
        "gof": gof,
        "metrics": metrics,
    }


def _fit_nonparametric(distribution: str, df: pd.DataFrame, mapping: dict) -> dict:
    """Fit a non-parametric survival estimator (KM/NA/FH/Turnbull).

    Produces an empirical step survival curve with confidence bounds instead
    of fitted parameters — no probability plot, no goodness-of-fit. The
    reliability functions (sf/ff via interpolation) and life metrics are
    still available, so the model reads back like any other in the calculator.
    """
    entry = NONPARAMETRIC[distribution]
    est = entry["est"]
    try:
        kwargs = build_fit_inputs(df, mapping)
        model = est.fit(**kwargs)
        xs = np.asarray(model.x, dtype=float)
        R = np.asarray(model.R, dtype=float)
        try:
            cb = np.asarray(model.cb(model.x, on="sf", alpha_ci=0.05), dtype=float)
            lower, upper = cb[:, 0], cb[:, 1]
        except Exception:  # not all estimators expose bounds for all data
            lower = upper = np.full_like(R, np.nan)
        curves = _function_curves(model)
        metrics = _life_metrics(model)
    except Exception as exc:
        raise FitError(str(exc) or f"{type(exc).__name__}") from exc

    finite = np.isfinite(xs)
    # Stash the live estimator so downstream consumers (RBD) can resolve it via
    # the same refit-on-demand path regression models use (get_live_model).
    cache_id = _store_model(model, np.asarray(curves["x"], dtype=float), [])
    return {
        "distribution": entry["name"],
        "distribution_id": distribution,
        "kind": "nonparametric",
        "params": [],
        "n": int(np.asarray(model.data["n"]).sum()) if hasattr(model, "data") else int(finite.sum()),
        "estimate": {
            "x": [float(v) for v in xs[finite]],
            "R": [float(v) for v in R[finite]],
            "cb_lower": [None if not np.isfinite(v) else float(v) for v in lower[finite]],
            "cb_upper": [None if not np.isfinite(v) else float(v) for v in upper[finite]],
        },
        "functions": {"meta": FUNCTIONS, "curves": curves, "model_id": cache_id},
        "gof": [],
        "metrics": metrics,
    }


def _life_metrics(model) -> dict:
    """Median / MTTF / B10 from any model exposing qf() and mean()."""
    def q(p):
        try:
            v = float(np.asarray(model.qf(p)).ravel()[0])
            return v if np.isfinite(v) else None
        except Exception:
            return None
    try:
        mttf = float(model.mean())
        mttf = mttf if np.isfinite(mttf) else None
    except Exception:
        mttf = None
    return {"median": q(0.5), "b10": q(0.1), "mttf": mttf}


def _params_with_uncertainty(model, param_names) -> list[dict]:
    """Parameter estimates with standard errors and 95% CIs from the fit's
    covariance matrix (plain normal approximation, ``value ± 1.96·se``).

    Kept on the natural scale for transparency; for positive parameters with
    small samples a log-scale interval would differ slightly near boundaries —
    acceptable for v1 and documented where the verdict is consumed.
    """
    values = np.atleast_1d(np.asarray(model.params, dtype=float))
    ses = [None] * len(values)
    cov = getattr(model, "cov_matrix", None)
    if cov is not None:
        cov = np.asarray(cov, dtype=float)
        if cov.shape == (len(values), len(values)) and np.all(np.isfinite(cov)):
            diag = np.diag(cov)
            ses = [float(np.sqrt(d)) if d > 0 else None for d in diag]

    z = 1.959963984540054  # 95%
    out = []
    for name, value, se in zip(param_names, values, ses):
        entry = {"name": name, "value": float(value)}
        if se is not None and math.isfinite(se):
            entry["se"] = se
            entry["ci"] = [float(value - z * se), float(value + z * se)]
        else:
            entry["se"] = None
            entry["ci"] = None
        out.append(entry)
    return out


def _randomness_verdict(distribution_id: str, params: list[dict]) -> dict | None:
    """Whether the fitted model is consistent with random (constant-rate)
    failures — the statistical evidence behind a run-to-failure decision.

    Weibull: read the shape parameter's 95% CI against 1. Exponential: random
    by construction (memoryless). Other distributions can't establish this and
    return no block.
    """
    if distribution_id == "exponential":
        return {"verdict": "random", "basis": "memoryless"}
    if distribution_id != "weibull":
        return None

    beta = next((p for p in params if p["name"] == "beta"), None)
    if beta is None:
        return None
    block = {"basis": "beta_ci", "beta": beta["value"], "beta_ci": beta.get("ci")}
    ci = beta.get("ci")
    if not ci:
        block["verdict"] = "inconclusive"
    elif ci[0] <= 1.0 <= ci[1]:
        block["verdict"] = "random"
    elif ci[0] > 1.0:
        block["verdict"] = "wear_out"
    else:
        block["verdict"] = "infant_mortality"
    return block


def _fit_regression(
    distribution: str,
    df: pd.DataFrame,
    mapping: dict,
    covariates: Optional[list],
    formula: Optional[str],
) -> dict:
    entry = REGRESSION_MODELS[distribution]
    fitter = entry["fitter"]
    mapping = {k: v for k, v in mapping.items() if v}

    # Only pass columns that were actually mapped — not every fitter (e.g. Cox)
    # accepts every optional column keyword.
    fit_kwargs = {"x_col": mapping.get("x")}
    for field, kw in (("c", "c_col"), ("n", "n_col"), ("tl", "tl_col"), ("tr", "tr_col")):
        if mapping.get(field):
            fit_kwargs[kw] = mapping[field]
    if formula:
        fit_kwargs["formula"] = formula
    elif covariates:
        fit_kwargs["Z_cols"] = list(covariates)

    try:
        model = fitter.fit_from_df(df, **fit_kwargs)
        gof = _goodness_of_fit(model)
    except Exception as exc:
        raise FitError(str(exc) or f"{type(exc).__name__}") from exc

    params_arr = np.asarray(model.params, dtype=float)
    k_dist = int(getattr(model, "k_dist", 0) or 0)

    # Baseline distribution parameters (empty for semi-parametric Cox).
    base_dist = getattr(model, "distribution", None)
    base_names = getattr(base_dist, "param_names", None) or [
        f"p{i}" for i in range(k_dist)
    ]
    baseline = [
        {"name": name, "value": float(value)}
        for name, value in zip(base_names, params_arr[:k_dist])
    ]

    # Regression coefficients with hazard ratios exp(beta).
    feature_names = getattr(model, "feature_names", None) or [
        f"b{i}" for i in range(len(params_arr) - k_dist)
    ]
    coefficients = [
        {"name": name, "value": float(value), "hazard_ratio": float(np.exp(value))}
        for name, value in zip(feature_names, params_arr[k_dist:])
    ]

    x_col = mapping.get("x")
    x_vals = (
        pd.to_numeric(df[x_col], errors="coerce").dropna().to_numpy()
        if x_col
        else np.array([])
    )
    n = int(x_vals.size)

    # Build the calculator: derive the raw covariate input fields, a time grid,
    # and the function curves at the default covariate values. Stash the model
    # so the frontend can re-evaluate at other covariate values.
    raw_vars = _raw_covariates(model, covariates)
    fields = _covariate_fields(df, raw_vars)
    hi = float(x_vals.max()) * 1.2 if x_vals.size else 1.0
    grid = np.linspace(0.0, hi, 300)
    default_row = pd.DataFrame({f["name"]: [f["default"]] for f in fields})
    try:
        curves = _eval_functions(model, grid, default_row if fields else None)
    except Exception:
        curves = None
    model_id = _store_model(model, grid, fields)

    functions = None
    if curves is not None:
        functions = {
            "meta": FUNCTIONS,
            "curves": curves,
            "covariates": fields,
            "model_id": model_id,
        }

    return {
        "distribution": entry["name"],
        "distribution_id": distribution,
        "kind": "regression",
        "params": baseline,
        "coefficients": coefficients,
        "n": n,
        "gof": gof,
        "functions": functions,
    }


def _raw_covariates(model, covariates: Optional[list]) -> list:
    """Names of the raw covariate columns the model was fit on."""
    spec = getattr(model, "_model_spec", None)
    required = getattr(spec, "required_variables", None)
    if required:
        return list(required)
    return list(covariates or [])


def _covariate_fields(df: pd.DataFrame, raw_vars) -> list:
    """Describe each covariate input for the calculator (type + default)."""
    raw = set(raw_vars)
    fields = []
    for col in df.columns:  # df order for stable presentation
        if col not in raw:
            continue
        series = df[col]
        if pd.api.types.is_numeric_dtype(series):
            mean = pd.to_numeric(series, errors="coerce").mean()
            fields.append(
                {
                    "name": str(col),
                    "type": "number",
                    "default": round(float(mean), 4) if pd.notna(mean) else 0.0,
                }
            )
        else:
            values = series.dropna().astype(str)
            options = sorted(values.unique().tolist())
            mode = values.mode()
            default = str(mode.iloc[0]) if len(mode) else (options[0] if options else "")
            fields.append(
                {
                    "name": str(col),
                    "type": "category",
                    "options": options,
                    "default": default,
                }
            )
    return fields


def evaluate(model_id: str, values: dict) -> dict:
    """Re-evaluate the reliability functions at given covariate ``values``."""
    entry = _MODEL_STORE.get(model_id)
    if entry is None:
        raise ModelNotFound(model_id)
    model, grid, fields = entry["model"], entry["grid"], entry["fields"]

    row = {}
    for f in fields:
        value = values.get(f["name"], f["default"])
        if f["type"] == "number":
            try:
                value = float(value)
            except (TypeError, ValueError):
                value = float(f["default"])
        else:
            value = str(value)
        row[f["name"]] = [value]

    df_row = pd.DataFrame(row) if row else None
    try:
        curves = _eval_functions(model, grid, df_row)
    except Exception as exc:
        raise FitError(str(exc) or f"{type(exc).__name__}") from exc
    return {"curves": curves}


# Reliability functions confidence bounds can be computed on, and the bound
# types SurPyval's ``cb`` accepts.
_CB_FUNCTIONS = {"sf", "ff", "hf", "Hf", "df"}
_CB_BOUNDS = {"two-sided", "lower", "upper"}


def confidence_bounds(
    model_id: str,
    on: str = "sf",
    alpha_ci: float = 0.05,
    bound: str = "two-sided",
) -> dict:
    """Confidence bounds of a fitted model's ``on`` function over its grid.

    Wraps SurPyval's ``model.cb`` — configurable significance ``alpha_ci`` and
    ``bound`` (two-sided / lower / upper). Available for plain, discrete and
    non-parametric models; regression (proportional-hazards) models don't
    expose confidence bounds. Two-sided returns both arrays; a one-sided bound
    returns just the relevant side (the other is ``None``).
    """
    if on not in _CB_FUNCTIONS:
        raise FitError(f"Can't compute confidence bounds on '{on}'.")
    if bound not in _CB_BOUNDS:
        raise FitError(f"Unknown bound '{bound}' — use two-sided, lower or upper.")
    if not 0.0 < alpha_ci < 1.0:
        raise FitError("Confidence level must be between 0% and 100% (exclusive).")

    entry = _MODEL_STORE.get(model_id)
    if entry is None:
        raise ModelNotFound(model_id)
    model, grid = entry["model"], np.asarray(entry["grid"], dtype=float)
    if not hasattr(model, "cb"):
        raise FitError("This model type doesn't provide confidence bounds.")

    try:
        with np.errstate(all="ignore"):
            cb = np.asarray(model.cb(grid, on=on, alpha_ci=alpha_ci, bound=bound), dtype=float)
    except Exception as exc:
        raise FitError(str(exc) or f"{type(exc).__name__}") from exc

    def _col(a):
        return [None if not np.isfinite(v) else float(v) for v in np.asarray(a, dtype=float)]

    if cb.ndim == 2:  # two-sided → columns [lower, upper]
        lower, upper = _col(cb[:, 0]), _col(cb[:, 1])
    elif bound == "lower":
        lower, upper = _col(cb), None
    else:  # upper
        lower, upper = None, _col(cb)

    return {
        "x": grid.tolist(),
        "on": on,
        "alpha_ci": alpha_ci,
        "bound": bound,
        "lower": lower,
        "upper": upper,
    }


# The reliability functions exposed in the calculator tab, with display labels.
FUNCTIONS = [
    {"id": "sf", "label": "Survival / reliability, R(t)"},
    {"id": "ff", "label": "Unreliability / CDF, F(t)"},
    {"id": "hf", "label": "Hazard rate, h(t)"},
    {"id": "Hf", "label": "Cumulative hazard, H(t)"},
    {"id": "df", "label": "Density, f(t)"},
]


def _eval_functions(model, grid, Z=None) -> dict:
    """Evaluate sf/ff/hf/Hf/df over ``grid`` (optionally at covariates ``Z``)."""
    grid = np.asarray(grid, dtype=float)
    curves = {"x": grid.tolist()}
    for fn in ("sf", "ff", "hf", "Hf", "df"):
        with np.errstate(all="ignore"):
            func = getattr(model, fn)
            y = np.asarray(func(grid) if Z is None else func(grid, Z), dtype=float)
        # JSON can't carry inf/nan; null them so the frontend skips those points.
        curves[fn] = [None if not np.isfinite(v) else float(v) for v in y]
    return curves


def _function_curves(model, points: int = 300) -> dict:
    """Evaluate sf/ff/hf/Hf/df over a grid from 0 to the 99th quantile."""
    try:
        hi = float(model.qf(0.99))
    except Exception:
        hi = None
    if hi is None or not np.isfinite(hi) or hi <= 0:
        # Fall back to the data range if the quantile is unavailable.
        xd = np.asarray(model.data["x"], dtype=float)
        xd = xd[np.isfinite(xd)]
        hi = float(xd.max()) * 1.5 if xd.size else 1.0
    return _eval_functions(model, np.linspace(0.0, hi, points))


def _goodness_of_fit(model) -> list:
    """Collect goodness-of-fit metrics as labelled, ordered entries."""

    def _value(attr):
        v = getattr(model, attr, None)
        if callable(v):  # aic/aic_c/bic are methods; log_likelihood is not
            try:
                v = v()
            except Exception:
                return None
        return v

    # Plain distributions expose log_likelihood; regression models expose the
    # negative log-likelihood instead, so fall back to that.
    ll = _value("log_likelihood")
    if ll is None:
        nll = _value("_neg_ll")
        ll = -nll if nll is not None else None

    candidates = [
        ("log_likelihood", "Log-likelihood", ll),
        ("aic", "AIC", _value("aic")),
        ("aic_c", "AICc", _value("aic_c")),
        ("bic", "BIC", _value("bic")),
    ]

    out = []
    for id_, label, value in candidates:
        if value is None:
            continue
        try:
            value = float(value)
        except (TypeError, ValueError):
            continue
        if np.isfinite(value):
            out.append({"id": id_, "label": label, "value": value})
    return out


# Backwards-compatible helper used in tests / simple callers.
def extract_times(file_bytes: bytes, column: Optional[str] = None) -> np.ndarray:
    """Read a CSV and pull out a single column of failure times as ``x``."""
    df = read_dataframe(file_bytes)
    if column is None:
        for name in df.columns:
            coerced = pd.to_numeric(df[name], errors="coerce")
            if coerced.notna().any():
                column = name
                break
        if column is None:
            raise FitError("No numeric column found in the CSV.")
    kwargs = build_fit_inputs(df, {"x": column})
    return kwargs["x"]
