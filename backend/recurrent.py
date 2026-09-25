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


def serialize_live(cache_id: str) -> dict | None:
    """Serialise a stored live recurrent model so it can be persisted and
    rehydrated without re-fitting. ``None`` if there's nothing to serialise."""
    m = _STORE.get(cache_id)
    if m is None or not hasattr(m, "to_dict"):
        return None
    try:
        return {"model": m.to_dict()}
    except Exception:  # noqa: BLE001 - never block a save on serialisation
        return None


def restore_live(serialized: dict) -> str:
    """Rehydrate a serialised recurrent model into the store; returns a cache id."""
    import surpyval

    return store_live(surpyval.from_dict(serialized["model"]))


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


def _power_law(model_id: str, params) -> tuple:
    """(shape, scale) of the model's power-law MCF in Crow-AMSAA form,
    MCF(t) = (t/scale)^shape, whatever the fitter's own parameterisation.

    Crow-AMSAA is ``[alpha, beta]`` = (scale, shape). SurPyval's Duane is
    ``[alpha, b]`` with MCF(t) = b * t^alpha — alpha is the *shape* and b a
    rate constant, so scale = b^(-1/alpha). Reading ``params[1]`` as the shape
    for both (as this module used to) gave Duane a shape of ~0: every Duane fit
    was labelled "improving" and its ROCOF/MTBF were meaningless (#88).
    """
    p = np.asarray(params, dtype=float)
    if p.size < 2:
        return None, None
    if model_id == "duane":
        shape, b = float(p[0]), float(p[1])
        scale = float(b ** (-1.0 / shape)) if b > 0 and shape > 0 else None
        return shape, scale
    return float(p[1]), float(p[0])


def _param_names(model_id: str, n: int) -> list:
    fitter = MODELS.get(model_id, {}).get("fitter")
    names = list(getattr(fitter, "param_names", []) or [])
    return names if len(names) == n else [f"p{k}" for k in range(n)]


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
    beta, alpha = _power_law(model_id, params_arr)
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

    param_names = _param_names(model_id, params_arr.size)
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
    # The form always takes Crow-AMSAA-style (alpha = scale, beta = shape).
    # Duane's own parameters are (shape, b) with b = scale^(-shape).
    native = values
    if model_id == "duane":
        scale, shape = values[0], values[1]
        if scale <= 0 or shape <= 0:
            raise FitError("Both parameters must be positive.")
        native = [shape, scale ** (-shape)]
    try:
        para = fitter.from_params(native)
    except Exception as exc:  # noqa: BLE001 - surface SurPyval's message
        raise FitError(str(exc)) from exc
    return _params_payload(para, model_id, native, horizon, unit), store_live(para)


def _params_payload(para, model_id: str, values: list, horizon: float, unit: str) -> dict:
    grid = np.linspace(0.0, horizon, 200)
    with np.errstate(all="ignore"):
        fitted = np.asarray(para.mcf(grid), dtype=float)
    beta, alpha = _power_law(model_id, values)
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
        "params": [{"name": n, "value": float(v)} for n, v in zip(_param_names(model_id, len(values)), values)],
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


# ---------------------------------------------------------------------------
# Optimal overhaul interval (Barlow–Hunter minimal repair + overhaul)
# ---------------------------------------------------------------------------

_OVERHAUL_GRID_POINTS = 200


def _as_cif_model(model_or_params):
    """A model exposing ``cif(t)`` from either a live surpyval recurrence model
    or a ``{"model_id", "params"}`` spec (params as floats or ``{name, value}``)."""
    if hasattr(model_or_params, "cif"):
        return model_or_params
    if isinstance(model_or_params, dict):
        model_id = model_or_params.get("model_id") or "crow_amsaa"
        if model_id not in MODELS:
            raise FitError(f"Unknown model '{model_id}'.")
        values = [float(p["value"]) if isinstance(p, dict) else float(p) for p in model_or_params.get("params") or []]
        fitter = MODELS[model_id]["fitter"]
        if not hasattr(fitter, "from_params"):
            raise FitError(f"“{MODELS[model_id]['name']}” can't be built from parameters.")
        try:
            return fitter.from_params(values)
        except Exception as exc:  # noqa: BLE001 - surface SurPyval's message
            raise FitError(str(exc)) from exc
    raise FitError("Model must be a fitted recurrence model or a parameter spec.")


def _positive(value, label: str) -> float:
    try:
        v = float(value)
    except (TypeError, ValueError):
        raise FitError(f"{label} must be a number.")
    if not np.isfinite(v) or v <= 0:
        raise FitError(f"{label} must be a positive number.")
    return v


def _cif_at(model, t: float) -> float:
    return float(np.asarray(model.cif(np.array([float(t)])), dtype=float).ravel()[0])


def _growth_exponent(model) -> float:
    """Local log–log slope of the cumulative intensity, d ln Λ / d ln t, taken
    where Λ ≈ 1. For the power-law models Reliafy fits (Crow-AMSAA, Duane, HPP)
    this is the constant shape β (1 for HPP) whatever the parameterisation."""
    t_ref = 1.0
    inv = getattr(model, "inv_cif", None)
    if callable(inv):
        try:
            with np.errstate(all="ignore"):
                tr = float(np.asarray(inv(np.array([1.0])), dtype=float).ravel()[0])
            if np.isfinite(tr) and tr > 0:
                t_ref = tr
        except Exception:  # noqa: BLE001 - fall back to t = 1
            pass
    with np.errstate(all="ignore"):
        a, b = _cif_at(model, t_ref), _cif_at(model, 2.0 * t_ref)
    if not (np.isfinite(a) and np.isfinite(b) and a > 0 and b > 0):
        return float("nan"), t_ref
    return float(np.log(b / a) / np.log(2.0)), t_ref


def optimal_overhaul(model_or_params, cost_repair, cost_overhaul, t_max=None, horizon=None) -> dict:
    """Optimal overhaul interval for a repairable system under minimal repair.

    Between overhauls each failure is minimally repaired (cost ``cost_repair``,
    "as bad as old"); an overhaul (cost ``cost_overhaul``) restores the system
    to as-good-as-new. Overhauling every ``T`` makes each cycle a renewal cycle,
    so the long-run cost rate is ``g(T) = (cr·Λ(T) + co) / T`` with ``Λ`` the
    model's cumulative intensity. RePyability's ``Repairable`` minimises it.

    A finite optimum exists only when the system deteriorates (Λ grows
    super-linearly, β > 1); otherwise ``g`` keeps falling as ``T`` grows and
    ``optimal`` is ``None`` with a ``reason``.

    "Never overhaul" has no finite long-run rate when β > 1 — the repair rate
    grows without bound, so ``g(T) → ∞``. It is reported instead as the
    repairs-only cost rate ``cr·Λ(H)/H`` averaged over a horizon ``H``
    (``horizon`` if given, else the curve's end ``t_max``, default 3·T*).
    For β < 1 its limit is 0; for an HPP it is ``cr·λ``.
    """
    from repyability.repairable import Repairable

    cr = _positive(cost_repair, "Repair cost")
    co = _positive(cost_overhaul, "Overhaul cost")
    if co <= cr:
        # The maths only needs co > 0, but RePyability's minimal-repair policy
        # requires co > cr: if an overhaul costs no more than a repair you'd
        # simply overhaul at every failure rather than repair.
        raise FitError("Overhaul cost must be greater than the repair cost (otherwise just overhaul at every failure).")
    t_max = _positive(t_max, "Chart horizon") if t_max is not None else None
    horizon = _positive(horizon, "Horizon") if horizon is not None else None

    model = _as_cif_model(model_or_params)
    shape, t_ref = _growth_exponent(model)
    base = {"cost_repair": cr, "cost_overhaul": co, "shape": shape}

    def _none(reason: str, limit):
        return _json_safe({**base, "optimal": None, "reason": reason,
                           "never_overhaul": {"limit_cost_rate": limit}})

    if not np.isfinite(shape):
        return _none("The model's cumulative intensity can't be evaluated, so no overhaul interval can be computed.", None)
    if shape < 1.0 - 1e-6:
        return _none(
            f"The failure intensity is decreasing (β = {shape:.3g} < 1): failures get rarer with age, so an "
            "overhaul never pays — the cost rate keeps falling the longer you run between overhauls.", 0.0)
    if shape <= 1.0 + 1e-6:
        return _none(
            "The failure intensity is constant (β = 1, e.g. HPP): an overhaul doesn't lower the failure rate, "
            "so it only adds cost. Repair on failure; don't overhaul.", cr * _cif_at(model, t_ref) / t_ref)

    rep = Repairable(model)
    rep.set_repair_and_overhaul_costs(cr, co)
    policy = rep.optimal_overhaul_policy()
    t_star = float(policy.interval)
    if not np.isfinite(t_star) or t_star <= 0:
        return _none("Overhauling never pays for this model: the cost rate keeps falling the longer you run.",
                     float(policy.cost_rate))
    g_star = float(rep.cost_rate(t_star))

    # Chart grid: always show the minimum and the rise after it, and start at
    # 0.1·T* so the co/T blow-up near zero doesn't flatten the curve.
    t_hi = max(t_max if t_max is not None else 3.0 * t_star, 1.5 * t_star)
    grid = np.linspace(0.1 * t_star, t_hi, _OVERHAUL_GRID_POINTS)
    with np.errstate(all="ignore"):
        curve = np.asarray(rep.cost_rate(grid), dtype=float)

    h = horizon if horizon is not None else t_hi
    with np.errstate(all="ignore"):
        none_rate = cr * _cif_at(model, h) / h
    saving = (none_rate - g_star) / none_rate * 100.0 if none_rate > 0 else None

    return _json_safe({
        **base,
        "optimal": {
            "interval": t_star,
            "cost_rate": g_star,
            "expected_failures_per_cycle": _cif_at(model, t_star),
        },
        "never_overhaul": {"horizon": h, "cost_rate": none_rate, "limit_cost_rate": None},  # unbounded as T → ∞
        "saving_pct": saving,
        "curve": {"t": grid.tolist(), "cost_rate": curve.tolist()},
    })
