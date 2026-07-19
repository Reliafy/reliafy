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


def build_inputs(df: pd.DataFrame, mapping: dict) -> tuple:
    """Extract ``(x, i, t)`` from a DataFrame: event time, system id, and each
    system's observation window (``t`` optional → last event = observation end).
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

    # Right-truncation / observation window as a per-event array aligned with x
    # (each event carries its system's observation end). Optional — when absent,
    # surpyval treats each system as observed until its last event.
    t = None
    tcol = mapping.get("t")
    if tcol:
        if tcol not in df.columns:
            raise FitError(f"Column '{tcol}' is not in the dataset.")
        tt = pd.to_numeric(df[tcol], errors="coerce")[keep].to_numpy(dtype=float)
        if not np.isnan(tt).all():
            # Fill any gaps so the window is never before the event itself.
            fill = float(np.nanmax(tt))
            tt = np.where(np.isnan(tt), np.maximum(x, fill), tt)
            t = np.maximum(tt, x)  # observation end can't precede the event
    return x, i, t


def fit(df: pd.DataFrame, mapping: dict, model_id: str = "crow_amsaa", unit: str = "") -> tuple[dict, str]:
    """Fit the recurrent model and build the JSON-safe results payload.

    Returns ``(payload, cache_id)`` addressing the live parametric model.
    """
    if model_id not in MODELS:
        raise FitError(f"Unknown model '{model_id}'. Choose one of: {', '.join(MODEL_CHOICES)}.")
    x, i, t = build_inputs(df, mapping)

    try:
        np_model = NonParametricCounting.fit(x=x, i=i)
        fitter = MODELS[model_id]["fitter"]
        # ``tr`` = per-event right-truncation (the system's observation window).
        para = fitter.fit(x=x, i=i, tr=t) if t is not None else fitter.fit(x=x, i=i)
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


def predict(model, horizon: float) -> dict:
    """Expected cumulative failures by ``horizon`` from a fitted model."""
    with np.errstate(all="ignore"):
        expected = float(np.asarray(model.mcf(np.array([float(horizon)])), dtype=float).ravel()[0])
    return _json_safe({"horizon": float(horizon), "expected_events": expected})
