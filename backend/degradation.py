"""Degradation analysis: fit population degradation models and predict when
tracked items cross a failure threshold (remaining useful life).

Wraps :mod:`surpyval.degradation`. A *degradation model* is fitted from
long-format measurement histories — many items, each measured over time — plus
a failure threshold. The fit yields per-item degradation paths, pseudo failure
times (and a life distribution fitted to them), and population parameters that
act as the Bayesian prior when predicting for new items.

Like the life-model fits in :mod:`backend.fitting`, fitted SurPyval objects
can't be pickled, so live models are kept in a bounded in-memory store and
re-fitted on demand from the stored dataset + spec by the service layer.
"""

from __future__ import annotations

import uuid
from collections import OrderedDict
from datetime import datetime, timezone

import numpy as np
import pandas as pd

from backend.fitting import DISTRIBUTIONS, FitError, _json_safe
from surpyval.degradation import PATH_MODELS as _SURPYVAL_PATHS
from surpyval.degradation import DegradationAnalysis

# Path-model registry for the API/UI (display names from surpyval instances).
PATH_MODELS = {name: {"id": name, "name": pm.name} for name, pm in _SURPYVAL_PATHS.items()}
PATH_CHOICES = ["best", *PATH_MODELS.keys()]

POPULATION_METHODS = ["moments", "reml"]

# In-memory store of live (fitted) degradation models, so tracked-item
# predictions don't re-fit on every call. Bounded; rebuilt on a miss.
_DEG_STORE: "OrderedDict[str, object]" = OrderedDict()
_DEG_STORE_MAX = 64

# Monte-Carlo samples for Bayesian RUL prediction. Fixed seed so recomputing a
# prediction for identical inputs yields identical output (stable caching).
_RUL_SAMPLES = 4000
_RUL_SEED = 0


def store_live(model) -> str:
    cache_id = uuid.uuid4().hex
    _DEG_STORE[cache_id] = model
    while len(_DEG_STORE) > _DEG_STORE_MAX:
        _DEG_STORE.popitem(last=False)
    return cache_id


def get_live(cache_id: str):
    return _DEG_STORE.get(cache_id)


def build_inputs(df: pd.DataFrame, mapping: dict) -> tuple:
    """Extract (x, y, i) long-format arrays from a DataFrame via the column
    mapping ``{"i": <item col>, "x": <time col>, "y": <measurement col>}``."""
    for key in ("i", "x", "y"):
        col = mapping.get(key)
        if not col:
            raise FitError(f"Column mapping is missing '{key}'.")
        if col not in df.columns:
            raise FitError(f"Column '{col}' is not in the dataset.")
    if len({mapping["i"], mapping["x"], mapping["y"]}) != 3:
        raise FitError("Item, time, and measurement must be three different columns.")

    x = pd.to_numeric(df[mapping["x"]], errors="coerce")
    y = pd.to_numeric(df[mapping["y"]], errors="coerce")
    i = df[mapping["i"]].astype(str)
    keep = x.notna() & y.notna() & i.notna()
    if not keep.any():
        raise FitError("No usable rows: time and measurement must be numeric.")
    return (
        x[keep].to_numpy(dtype=float),
        y[keep].to_numpy(dtype=float),
        i[keep].to_numpy(),
    )


def fit(
    df: pd.DataFrame,
    mapping: dict,
    threshold: float,
    path: str = "best",
    distribution_id: str = "weibull",
    population_method: str = "moments",
    unit: str = "",
    measurement_unit: str = "",
) -> tuple[dict, str]:
    """Fit a degradation model and build the JSON-safe results payload.

    Returns ``(payload, cache_id)`` where ``cache_id`` addresses the live model
    in the in-memory store (for tracked-item predictions).
    """
    if path not in PATH_CHOICES:
        raise FitError(f"Unknown path model '{path}'. Choose one of: {', '.join(PATH_CHOICES)}.")
    if distribution_id not in DISTRIBUTIONS:
        raise FitError(f"Unknown life distribution '{distribution_id}'.")
    if population_method not in POPULATION_METHODS:
        raise FitError(f"population_method must be one of: {', '.join(POPULATION_METHODS)}.")
    try:
        threshold = float(threshold)
    except (TypeError, ValueError):
        raise FitError("Threshold must be a number.")
    if not np.isfinite(threshold):
        raise FitError("Threshold must be finite.")

    x, y, i = build_inputs(df, mapping)

    try:
        model = DegradationAnalysis.fit(
            x,
            y,
            i,
            threshold=threshold,
            path=path,
            distribution=DISTRIBUTIONS[distribution_id]["dist"],
            population_method=population_method,
        )
    except FitError:
        raise
    except Exception as exc:  # noqa: BLE001 - surface SurPyval's message
        raise FitError(str(exc)) from exc

    payload = _build_payload(model, distribution_id, unit, measurement_unit)
    return payload, store_live(model)


def _build_payload(model, distribution_id: str, unit: str, measurement_unit: str) -> dict:
    units_payload = []
    for idx, u in enumerate(model.units):
        mask = model.i == u
        ux = np.asarray(model.x[mask], dtype=float)
        uy = np.asarray(model.y[mask], dtype=float)
        pft = float(model.pseudo_failure_times[idx])
        censored = bool(model.c[idx])
        # Fitted path drawn from first measurement out to the (pseudo) failure
        # time so the crossing is visible; censored paths extend 20% past data.
        hi = pft if np.isfinite(pft) else float(ux.max()) * 1.2
        grid = np.linspace(float(ux.min()), max(hi, float(ux.max())), 100)
        line = np.asarray(model.path(grid, u), dtype=float)
        units_payload.append({
            "id": str(u),
            "scatter": {"x": ux.tolist(), "y": uy.tolist()},
            "line": {"x": grid.tolist(), "y": line.tolist()},
            "pseudo_failure_time": pft,
            "censored": censored,
        })

    selection = None
    if getattr(model, "path_selection", None):
        def _path_id(display_name: str) -> str:
            return next(
                (k for k, v in _SURPYVAL_PATHS.items() if v.name == display_name),
                display_name.lower(),
            )

        selection = sorted(
            (
                {"id": _path_id(name), "name": name, "aicc": float(score)}
                for name, score in model.path_selection.items()
            ),
            key=lambda r: (not np.isfinite(r["aicc"]), r["aicc"]),
        )

    life = model.life_model
    life_params = [
        {"name": n, "value": float(v)}
        for n, v in zip(life.dist.param_names, np.atleast_1d(life.params))
    ]
    # Reliability curve over a grid to the ~99th percentile for plotting.
    try:
        t_hi = float(life.qf(0.99))
        t_grid = np.linspace(0.0, t_hi, 200)
        curves = {
            "x": t_grid.tolist(),
            "sf": np.asarray(life.sf(t_grid), dtype=float).tolist(),
        }
        mean_life = float(life.mean())
    except Exception:  # pragma: no cover - defensive; curves are optional
        curves = None
        mean_life = None

    payload = {
        "kind": "degradation",
        "threshold": float(model.threshold),
        "unit": (unit or "").strip(),
        "measurement_unit": (measurement_unit or "").strip(),
        "n_units": int(len(model.units)),
        "n_measurements": int(len(model.x)),
        "path_model": {
            "id": next(
                (k for k, v in _SURPYVAL_PATHS.items() if v.name == model.path_model.name),
                model.path_model.name.lower(),
            ),
            "name": model.path_model.name,
            "n_params": int(model.path_params.shape[1]),
        },
        "path_selection": selection,
        "population_method": model.population_method,
        "measurement_var": float(model.measurement_var),
        "path_param_mean": np.asarray(model.path_param_mean, dtype=float).tolist(),
        "units": units_payload,
        "life_model": {
            "distribution": DISTRIBUTIONS[distribution_id]["name"],
            "distribution_id": distribution_id,
            "params": life_params,
            "mean": mean_life,
            "curves": curves,
        },
    }
    return _json_safe(payload)


def predict_item(model, t, y) -> dict:
    """Predict threshold crossing for one tracked item's measurements.

    Returns a JSON-safe blob for caching on the item document. Never raises for
    prediction problems — degraded results carry ``method: "point"`` (no
    measurement noise → no Bayesian posterior) or ``"error"`` (e.g. too few
    measurements for the path form) so a measurement is never lost.
    """
    t = np.asarray(t, dtype=float)
    y = np.asarray(y, dtype=float)
    base = {
        "predicted_at": datetime.now(timezone.utc).isoformat(),
        "n_measurements": int(len(t)),
        "last_t": float(t.max()) if len(t) else None,
    }

    try:
        pred = model.predict_rul(
            t, y, alpha_ci=0.05, n_samples=_RUL_SAMPLES, random_state=_RUL_SEED
        )
        lo, hi = pred.failure_time_interval
        rlo, rhi = pred.rul_interval
        return _json_safe({
            **base,
            "method": "bayesian",
            "alpha_ci": 0.05,
            "failure_time": float(pred.failure_time),
            "failure_time_interval": [float(lo), float(hi)],
            "rul": float(pred.rul),
            "rul_interval": [float(rlo), float(rhi)],
            "prob_failed": float(pred.prob_failed),
            "prob_never_fails": float(pred.prob_never_fails),
            "projection": _projection(model, pred.posterior_mean, t, pred),
        })
    except Exception:  # noqa: BLE001 - fall back to the point estimate
        pass

    try:
        ft = float(model.predict_failure_time(t, y))
        rul = float(model.predict_remaining_life(t, y))
        return _json_safe({
            **base,
            "method": "point",
            "failure_time": ft,
            "failure_time_interval": None,
            "rul": rul,
            "rul_interval": None,
            "prob_failed": None,
            "prob_never_fails": None,
            "projection": None,
        })
    except Exception as exc:  # noqa: BLE001
        return _json_safe({
            **base,
            "method": "error",
            "detail": str(exc),
        })


def _projection(model, theta, t, pred) -> dict | None:
    """Projected degradation path for the item chart: the path model at the
    posterior-mean parameters, out past the credible interval, with a 95%
    credible band from the posterior parameter covariance (delta method via
    the path jacobian)."""
    try:
        lo, hi = pred.failure_time_interval
        end = hi if np.isfinite(hi) else (pred.failure_time if np.isfinite(pred.failure_time) else None)
        if end is None or not np.isfinite(end):
            end = float(np.max(t)) * 1.5
        end = max(float(end) * 1.1, float(np.max(t)) * 1.05)
        grid = np.linspace(0.0, end, 120)
        theta = np.asarray(theta, dtype=float)
        vals = np.asarray(model.path_model.path(grid, *theta), dtype=float)
        out = {"x": grid.tolist(), "y": vals.tolist()}
        try:
            J = np.asarray(model.path_model.jacobian(grid, *theta), dtype=float)
            cov = np.asarray(pred.posterior_cov, dtype=float)
            se = np.sqrt(np.maximum(np.einsum("ij,jk,ik->i", J, cov, J), 0.0))
            z = 1.959963984540054  # 95%
            out["lo"] = (vals - z * se).tolist()
            out["hi"] = (vals + z * se).tolist()
        except Exception:  # pragma: no cover - band is optional
            pass
        return out
    except Exception:  # pragma: no cover - projection is cosmetic
        return None
