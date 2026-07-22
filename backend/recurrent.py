"""Recurrent-event (repairable-system) analysis.

Where the rest of Reliafy models *time to a single failure*, this models a
*sequence* of failures/repairs per system — the repairable-systems question:
is the system getting better or worse, and how often will it fail?

Wraps :mod:`surpyval.recurrent`. From long-format event data (one row per
event: which system, at what time) plus each system's observation window, we
fit a nonparametric **MCF** (mean cumulative function, with confidence bounds),
a parametric **Crow-AMSAA** power-law NHPP (the reliability-growth model), and a
**trend test** (Laplace) — and derive the current ROCOF / MTBF and a plain
growth verdict from the Crow-AMSAA shape β.

Like the other fits, live surpyval objects can't be pickled, so they're kept in
a bounded in-memory store and re-fitted on demand from the dataset + spec.
"""

from __future__ import annotations

import uuid
from collections import OrderedDict

import numpy as np
import pandas as pd

from backend.fitting import FitError, _json_safe
from surpyval.recurrent import CrowAMSAA, Duane, HPP, NonParametricCounting, laplace

# Parametric recurrence models offered (all power-law / Poisson intensities).
MODELS = {
    "crow_amsaa": {"name": "Crow-AMSAA (NHPP)", "fitter": CrowAMSAA},
    "duane": {"name": "Duane", "fitter": Duane},
    "hpp": {"name": "Homogeneous Poisson (HPP)", "fitter": HPP},
}
MODEL_CHOICES = list(MODELS.keys())

_STORE: "OrderedDict[str, object]" = OrderedDict()
_STORE_MAX = 64


def store_live(model) -> str:
    cache_id = uuid.uuid4().hex
    _STORE[cache_id] = model
    while len(_STORE) > _STORE_MAX:
        _STORE.popitem(last=False)
    return cache_id


def get_live(cache_id: str):
    return _STORE.get(cache_id)


def build_inputs(df: pd.DataFrame, mapping: dict) -> dict:
    """Extract the SurPyval recurrent inputs from a long-format DataFrame.

    Required: ``i`` (system id) and ``x`` (event time). Optional modifiers,
    matching the life-data column surface: ``c`` (censor flag), ``n`` (count of
    events per row), ``tl``/``tr`` (left/right truncation) — ``tr`` is each
    system's observation window; the legacy ``t`` key is accepted as an alias
    for ``tr``. Returns a fitter kwargs dict with only the provided inputs.
    """
    for key in ("i", "x"):
        col = mapping.get(key)
        if not col:
            raise FitError(f"Column mapping is missing '{key}'.")
        if col not in df.columns:
            raise FitError(f"Column '{col}' is not in the dataset.")
    x = pd.to_numeric(df[mapping["x"]], errors="coerce")
    i = df[mapping["i"]].astype(str)
    keep = x.notna() & i.notna()
    if not keep.any():
        raise FitError("No usable rows: event time must be numeric.")
    x = x[keep].to_numpy(dtype=float)
    i = i[keep].to_numpy()
    out: dict = {"x": x, "i": i}

    def _numeric(key):
        col = mapping.get(key)
        if not col:
            return None
        if col not in df.columns:
            raise FitError(f"Column '{col}' is not in the dataset.")
        return pd.to_numeric(df[col], errors="coerce")[keep].to_numpy(dtype=float)

    c = _numeric("c")
    if c is not None:
        out["c"] = np.nan_to_num(c, nan=0.0).astype(int)  # missing -> observed
    n = _numeric("n")
    if n is not None:
        nn = np.nan_to_num(n, nan=1.0)
        nn[nn < 1] = 1
        out["n"] = nn.astype(int)
    tl = _numeric("tl")
    if tl is not None and not np.isnan(tl).all():
        out["tl"] = np.nan_to_num(tl, nan=0.0)  # missing -> observed from 0

    # Right-truncation / observation window: each event carries its system's
    # observation end. Optional; ``t`` is the legacy key for the same input.
    tr = _numeric("tr")
    if tr is None:
        tr = _numeric("t")
    if tr is not None and not np.isnan(tr).all():
        fill = float(np.nanmax(tr))
        tr = np.where(np.isnan(tr), np.maximum(x, fill), tr)
        out["tr"] = np.maximum(tr, x)  # window can't precede the event
    return out


def fit(df: pd.DataFrame, mapping: dict, model_id: str = "crow_amsaa", unit: str = "") -> tuple[dict, str]:
    """Fit the recurrent model and build the JSON-safe results payload.

    Returns ``(payload, cache_id)`` addressing the live parametric model.
    """
    if model_id not in MODELS:
        raise FitError(f"Unknown model '{model_id}'. Choose one of: {', '.join(MODEL_CHOICES)}.")
    inputs = build_inputs(df, mapping)
    x, i = inputs["x"], inputs["i"]
    # The nonparametric MCF estimator doesn't support right truncation (tr) —
    # the parametric fitter does. Give each what it accepts.
    np_inputs = {k: v for k, v in inputs.items() if k != "tr"}

    try:
        np_model = NonParametricCounting.fit(**np_inputs)
        fitter = MODELS[model_id]["fitter"]
        para = fitter.fit(**inputs)
    except FitError:
        raise
    except Exception as exc:  # noqa: BLE001 - surface SurPyval's message
        raise FitError(str(exc)) from exc

    payload = _build_payload(np_model, para, x, i, model_id, unit)
    return payload, store_live(para)


def _build_payload(np_model, para, x, i, model_id: str, unit: str) -> dict:
    n_systems = int(len(set(i.tolist())))
    n_events = int(len(x))

    # Nonparametric MCF step (observed) with a 95% confidence band.
    nx = np.asarray(np_model.x, dtype=float)
    mcf_obs = np.asarray(np_model.mcf_hat, dtype=float)
    try:
        cb = np.asarray(np_model.mcf_cb(nx, confidence=0.95), dtype=float)
        upper, lower = cb[:, 0].tolist(), cb[:, 1].tolist()
    except Exception:  # pragma: no cover - bounds are optional
        upper = lower = None

    # Parametric fit + fitted MCF over a smooth grid to the last observation.
    params_arr = np.asarray(para.params, dtype=float)
    t_hi = float(np.max(x)) if x.size else 1.0
    grid = np.linspace(0.0, t_hi, 200)
    with np.errstate(all="ignore"):
        fitted = np.asarray(para.mcf(grid), dtype=float)

    # Crow-AMSAA / power-law shape: MCF(t) = (t/alpha)^beta, so the current
    # rate of occurrence of failures (ROCOF) at the end is analytic.
    beta = float(params_arr[1]) if params_arr.size >= 2 else None
    alpha = float(params_arr[0]) if params_arr.size >= 1 else None
    rocof = mtbf = None
    growth = None
    if beta is not None and alpha and t_hi > 0:
        with np.errstate(all="ignore"):
            rocof = float((beta / alpha) * (t_hi / alpha) ** (beta - 1.0))
        if np.isfinite(rocof) and rocof > 0:
            mtbf = 1.0 / rocof
        growth = "improving" if beta < 0.95 else "deteriorating" if beta > 1.05 else "stable"

    # Trend test (Laplace): is the failure rate trending up/down?
    trend = None
    try:
        tt = laplace(x=x, i=i)
        signif = tt.p_value < 0.05
        direction = getattr(tt, "trend", None)
        trend = {
            "test": getattr(tt, "test", "Laplace"),
            "statistic": float(tt.statistic),
            "p_value": float(tt.p_value),
            "trend": direction,
            "significant": bool(signif),
        }
    except Exception:  # pragma: no cover - defensive
        trend = None

    param_names = ["alpha", "beta"] if model_id in ("crow_amsaa", "duane") else [f"p{k}" for k in range(params_arr.size)]
    payload = {
        "kind": "recurrent",
        "unit": (unit or "").strip(),
        "n_systems": n_systems,
        "n_events": n_events,
        "model": {"id": model_id, "name": MODELS[model_id]["name"]},
        "params": [{"name": n, "value": float(v)} for n, v in zip(param_names, params_arr)],
        "beta": beta,
        "growth": growth,
        "rocof": rocof,
        "mtbf": mtbf,
        "mcf": {
            "observed": {"x": nx.tolist(), "mcf": mcf_obs.tolist(), "lower": lower, "upper": upper},
            "fitted": {"x": grid.tolist(), "mcf": fitted.tolist()},
        },
        "trend": trend,
        "gof": _gof(para),
    }
    return _json_safe(payload)


def _gof(model) -> list:
    out = []
    for attr, label in (("aic", "AIC"), ("neg_ll", "Neg. log-likelihood")):
        v = getattr(model, attr, None)
        if callable(v):
            try:
                v = v()
            except Exception:
                v = None
        if v is not None and np.isfinite(float(v)):
            out.append({"id": attr, "label": label, "value": float(v)})
    return out


def fit_from_params(model_id: str, params: list, horizon: float, unit: str = "") -> tuple:
    """Build a recurrent model from known parameters — no data. ``params`` is an
    ordered list of ``{name, value}`` (Crow-AMSAA / Duane: alpha, beta).
    ``horizon`` sets the time range for the fitted MCF curve and the point at
    which ROCOF/MTBF are reported. Returns ``(payload, cache_id)``. The observed
    MCF step, confidence band, and trend test need data, so are omitted."""
    if model_id not in MODELS:
        raise FitError(f"Unknown model '{model_id}'. Choose one of: {', '.join(MODEL_CHOICES)}.")
    fitter = MODELS[model_id]["fitter"]
    if not hasattr(fitter, "from_params"):
        raise FitError(f"“{MODELS[model_id]['name']}” can't be built from parameters.")
    values = [float(p["value"]) for p in (params or []) if p.get("value") is not None]
    if len(values) < 2:
        raise FitError("Provide both parameters (alpha and beta).")
    try:
        horizon = float(horizon)
    except (TypeError, ValueError):
        raise FitError("Horizon must be a number.")
    if horizon <= 0:
        raise FitError("Horizon must be a positive time.")
    try:
        para = fitter.from_params(values)
    except Exception as exc:  # noqa: BLE001 - surface SurPyval's message
        raise FitError(str(exc)) from exc
    return _params_payload(para, model_id, values, horizon, unit), store_live(para)


def _params_payload(para, model_id: str, values: list, horizon: float, unit: str) -> dict:
    grid = np.linspace(0.0, horizon, 200)
    with np.errstate(all="ignore"):
        fitted = np.asarray(para.mcf(grid), dtype=float)
    alpha = float(values[0])
    beta = float(values[1])
    # Same power-law ROCOF/MTBF (at the horizon) and growth verdict as a data fit.
    rocof = mtbf = None
    with np.errstate(all="ignore"):
        if alpha:
            rocof = float((beta / alpha) * (horizon / alpha) ** (beta - 1.0))
    if rocof is not None and np.isfinite(rocof) and rocof > 0:
        mtbf = 1.0 / rocof
    growth = "improving" if beta < 0.95 else "deteriorating" if beta > 1.05 else "stable"
    payload = {
        "kind": "recurrent",
        "unit": (unit or "").strip(),
        "n_systems": None,
        "n_events": None,
        "model": {"id": model_id, "name": MODELS[model_id]["name"]},
        "params": [{"name": n, "value": float(v)} for n, v in zip(("alpha", "beta"), values)],
        "beta": beta,
        "growth": growth,
        "rocof": rocof,
        "mtbf": mtbf,
        "mcf": {"observed": None, "fitted": {"x": grid.tolist(), "mcf": fitted.tolist()}},
        "trend": None,
        "gof": [],  # no likelihood for a params-built model
        "from_params": True,
        "horizon": horizon,
    }
    return _json_safe(payload)


def predict(model, horizon: float) -> dict:
    """Expected cumulative failures by ``horizon`` from a fitted model."""
    with np.errstate(all="ignore"):
        expected = float(np.asarray(model.mcf(np.array([float(horizon)])), dtype=float).ravel()[0])
    return _json_safe({"horizon": float(horizon), "expected_events": expected})
