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
from surpyval.univariate.regression import CoxPH

# Plain distributions (no covariates), keyed by the id used in the API/URL.
DISTRIBUTIONS = {
    "weibull": {"name": "Weibull", "dist": Weibull},
    "exponential": {"name": "Exponential", "dist": Exponential},
    "normal": {"name": "Normal", "dist": Normal},
    "lognormal": {"name": "Lognormal", "dist": LogNormal},
    "gamma": {"name": "Gamma", "dist": Gamma},
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


def fit(
    distribution: str,
    df: pd.DataFrame,
    mapping: dict,
    covariates: Optional[list] = None,
    formula: Optional[str] = None,
    unit: Optional[str] = None,
) -> dict:
    """Fit ``distribution`` (plain or proportional hazards) and build the payload.

    If ``distribution`` is a regression model it is fit with covariate columns
    (``covariates``) or a ``formula``; otherwise the plain distribution path is
    used. ``unit`` is the (optional) unit of ``x`` carried through for display.
    Any SurPyval error is wrapped in :class:`FitError`.
    """
    if distribution in REGRESSION_MODELS:
        result = _fit_regression(distribution, df, mapping, covariates, formula)
    elif distribution in DISTRIBUTIONS:
        result = _fit_distribution(distribution, df, mapping)
    else:
        raise FitError(
            f"Unknown model '{distribution}'. Available: "
            f"{', '.join([*DISTRIBUTIONS, *REGRESSION_MODELS])}."
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


def _fit_distribution(distribution: str, df: pd.DataFrame, mapping: dict) -> dict:
    entry = DISTRIBUTIONS[distribution]
    dist = entry["dist"]

    try:
        kwargs = build_fit_inputs(df, mapping)
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

    result = {
        "distribution": entry["name"],
        "distribution_id": distribution,
        "kind": "distribution",
        "params": params,
        "n": int(np.sum(model.data["n"])),
        "plot": plot,
        "functions": {"meta": FUNCTIONS, "curves": curves},
        "gof": gof,
    }
    randomness = _randomness_verdict(distribution, params)
    if randomness is not None:
        result["randomness"] = randomness
    return result


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
