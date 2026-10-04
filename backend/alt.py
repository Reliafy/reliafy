"""Accelerated Life Testing (ALT).

Where the life-data models fit a single distribution to failure times at *one*
operating condition, ALT fits failure times collected at several elevated
**stress** levels (temperature, voltage, load, …) and a **life-stress
relationship** that ties the distribution's characteristic life to the stress —
so you can **extrapolate to a lower use-level stress** you'd never have time to
test at directly. That extrapolation, plus the acceleration factor between a
test stress and the field, is the whole point.

Wraps :func:`surpyval.AcceleratedLife`, which substitutes the distribution's
scale parameter with a life-stress function ``phi(stress)`` and returns a
standard ``ParametricRegressionModel`` — so the reliability functions,
confidence bounds and serialisation are shared with the regression models.

Like the other fits, live SurPyval objects can't be pickled, so a fitted model
is kept in a bounded in-memory store and can also be serialised (``to_dict``)
for persistence and rehydrated without re-fitting.
"""

from __future__ import annotations

import uuid
import warnings
from collections import OrderedDict
from typing import Optional

import numpy as np
import pandas as pd

from backend.fitting import (
    DISTRIBUTIONS,
    FitError,
    _eval_functions,
    _json_safe,
    failure_positions_mask,
    no_maximum_notice,
    outside_support_message,
    reissue_deprecations,
    without_intervals,
)
from backend.services.method_labels import hides_solver_names, note_fit
from surpyval import AcceleratedLife
from surpyval.univariate.regression import accelerated_life as _al

_LM = _al.LIFE_MODELS


# Life-stress relationships offered, keyed by the id used in the API/URL.
# ``model`` is the SurPyval life model; ``n_stress`` is how many stress columns
# it consumes; ``log_y`` hints the life-vs-stress plot should use a log life
# axis (multiplicative acceleration). Ordered single-stress first, then dual.
#
# SurPyval ships each single-stress relationship twice, once inverted — the pairs
# ``Exponential``/``InverseExponential`` and ``Power``/``InversePower`` describe
# the *same* family of curves, reparameterised, and fit to identical likelihoods.
# Only one of each is offered: two dropdown entries that silently do the same
# thing is worse than one. We keep the parameterisation whose coefficients read
# the right way round — ``Exponential`` so Arrhenius' ``a`` is Ea/k (positive,
# life rising as temperature falls) and ``InversePower`` so ``n`` is the usual
# positive exponent — because the inverted forms drive one coefficient to
# extreme magnitudes (a ~ 1e18) for the same fit.
LIFE_MODELS = {
    "arrhenius": {
        "name": "Arrhenius",
        "model": _LM["Exponential"],
        "n_stress": 1,
        "log_y": True,
        "desc": "Thermal acceleration — life = b·exp(a / stress). Use absolute "
                "temperature (K). The classic model for chemical/thermal ageing.",
    },
    "eyring": {
        "name": "Eyring",
        "model": _LM["Eyring"],
        "n_stress": 1,
        "log_y": True,
        "desc": "Thermal model derived from reaction-rate theory — a physically "
                "grounded alternative to Arrhenius.",
    },
    "inverse_power": {
        "name": "Inverse power law",
        "model": _LM["InversePower"],
        "n_stress": 1,
        "log_y": True,
        "desc": "Life = 1/(a·stress^n). The standard model for voltage, load or "
                "pressure acceleration.",
    },
    "linear": {
        "name": "Linear",
        "model": _LM["Linear"],
        "n_stress": 1,
        "log_y": False,
        "desc": "Life = a + b·stress. A simple straight-line relationship.",
    },
    "dual_exponential": {
        "name": "Dual exponential (temp–humidity)",
        "model": _LM["DualExponential"],
        "n_stress": 2,
        "log_y": True,
        "desc": "Two stresses combined exponentially — e.g. temperature and "
                "humidity (the Peck-style model).",
    },
    "power_exponential": {
        "name": "Temperature–nonthermal",
        "model": _LM["PowerExponential"],
        "n_stress": 2,
        "log_y": True,
        "desc": "Temperature (exponential) with a second non-thermal stress "
                "(power) — e.g. temperature and voltage.",
    },
    "dual_power": {
        "name": "Dual power",
        "model": _LM["DualPower"],
        "n_stress": 2,
        "log_y": True,
        "desc": "Two stresses combined by a power law.",
    },
}
LIFE_MODEL_CHOICES = list(LIFE_MODELS)

# ALT reuses the plain continuous distributions as its life-distribution.
ALT_DISTRIBUTIONS = ("weibull", "lognormal", "normal", "exponential", "gamma")


_STORE: "OrderedDict[str, object]" = OrderedDict()
_STORE_MAX = 64

# np.trapz was removed in NumPy 2.0 in favour of np.trapezoid.
_trapezoid = getattr(np, "trapezoid", None) or np.trapz


def store_live(model) -> str:
    cache_id = uuid.uuid4().hex
    _STORE[cache_id] = model
    while len(_STORE) > _STORE_MAX:
        _STORE.popitem(last=False)
    return cache_id


def get_live(cache_id: str):
    return _STORE.get(cache_id)


def serialize_live(cache_id: str) -> dict | None:
    """Serialise a stored ALT model for persistence; ``None`` if unavailable."""
    m = _STORE.get(cache_id)
    if m is None or not hasattr(m, "to_dict"):
        return None
    try:
        return {"model": m.to_dict()}
    except Exception:  # noqa: BLE001 - never block a save on serialisation
        return None


def restore_live(serialized: dict) -> str:
    """Rehydrate a serialised ALT model into the store; returns a cache id."""
    import surpyval

    return store_live(surpyval.from_dict(serialized["model"]))


# ---------------------------------------------------------------------------
# Inputs
# ---------------------------------------------------------------------------
def _time_column(df: pd.DataFrame, col: str) -> np.ndarray:
    if col not in df.columns:
        raise FitError(f"Column '{col}' is not in the dataset.")
    return pd.to_numeric(df[col], errors="coerce").to_numpy(float)


def build_inputs(df: pd.DataFrame, mapping: dict, stress_cols: list) -> dict:
    """Extract SurPyval ALT inputs from a DataFrame.

    ``mapping`` carries the life-data columns: the failure time ``x``, or, for
    inspection data (#237), the interval ``xl`` (the last inspection the unit
    passed) and ``xr`` (the one that found it failed; blank = still running);
    ``c``/``n`` and the truncation ``tl``/``tr`` are optional. ``stress_cols``
    is the ordered list of one or two stress columns. Returns a kwargs dict:
    ``x`` (times, or an n×2 array of interval bounds), ``Z`` (n×k stresses),
    and optional ``c``/``n``/``t`` (an n×2 truncation window).
    """
    mapping = {k: v for k, v in (mapping or {}).items() if v}
    interval = bool(mapping.get("xl") or mapping.get("xr"))
    if interval and (mapping.get("x") or not (mapping.get("xl") and mapping.get("xr"))):
        raise FitError("Map the failure time to x, or inspection data to both xl (the last inspection it "
                       "passed) and xr (the one that found it failed), not both.")
    if not interval and not mapping.get("x"):
        raise FitError("Column mapping is missing the failure-time column 'x'.")
    if not stress_cols:
        raise FitError("Select at least one stress column.")
    for s in stress_cols:
        if s not in df.columns:
            raise FitError(f"Stress column '{s}' is not in the dataset.")

    Z = np.column_stack([pd.to_numeric(df[s], errors="coerce").to_numpy(float) for s in stress_cols])
    if interval:
        lo = _time_column(df, mapping["xl"])
        hi = _time_column(df, mapping["xr"])
        # A blank (or infinite) upper bound: not found failed at any
        # inspection, so still running past the lower one — right-censored
        # there, the time repeated as SurPyval takes a censored row.
        open_ended = ~np.isfinite(hi)
        hi = np.where(open_ended, lo, hi)
        keep = np.isfinite(lo) & np.isfinite(Z).all(axis=1)
        x = np.column_stack([lo, hi])
        if not mapping.get("c"):
            # No flags: equal bounds are a failure seen at that time, unequal
            # ones an interval, an open end still running.
            inferred = np.where(open_ended, 1, np.where(lo == hi, 0, 2))
    else:
        x = _time_column(df, mapping["x"])
        keep = np.isfinite(x) & np.isfinite(Z).all(axis=1)
    if not keep.any():
        raise FitError("No usable rows: failure time and stresses must be numeric.")

    out: dict = {"x": x[keep], "Z": Z[keep]}

    def _numeric(key):
        col = mapping.get(key)
        if not col:
            return None
        if col not in df.columns:
            raise FitError(f"Column '{col}' is not in the dataset.")
        return pd.to_numeric(df[col], errors="coerce").to_numpy(float)[keep]

    c = _numeric("c")
    if c is not None:
        out["c"] = np.nan_to_num(c, nan=0.0).astype(int)  # missing -> observed
    elif interval:
        out["c"] = inferred[keep]
    n = _numeric("n")
    if n is not None:
        nn = np.nan_to_num(n, nan=1.0)
        nn[nn < 1] = 1
        out["n"] = nn.astype(int)
    # Truncation (delayed entry, or failures past an age never recorded), as
    # the life-data fits take it; a blank cell is untruncated.
    tl, tr = _numeric("tl"), _numeric("tr")
    if tl is not None or tr is not None:
        size = int(keep.sum())
        tl = np.full(size, -np.inf) if tl is None else np.where(np.isnan(tl), -np.inf, tl)
        tr = np.full(size, np.inf) if tr is None else np.where(np.isnan(tr), np.inf, tr)
        out["t"] = np.column_stack([tl, tr])
    return out


def is_interval(inputs: dict) -> bool:
    """Whether ``build_inputs``' times are inspection intervals (n×2)."""
    return np.ndim(inputs.get("x")) == 2


def _lower_times(inputs: dict) -> np.ndarray:
    """One time per row: the time itself, or an interval's lower bound."""
    x = np.asarray(inputs["x"], dtype=float)
    return x[:, 0] if x.ndim == 2 else x


def bounds_methods(inputs: dict) -> list:
    """The bound methods SurPyval 0.23 offers for these data: the
    bootstrap resamples exact and right-censored data only (#617), so it's
    left out for interval- and left-censored data."""
    c = inputs.get("c")
    if is_interval(inputs) or (c is not None and np.any(np.isin(c, (-1, 2)))):
        return ["wald", "lr"]
    return list(BOUND_METHODS)


# ---------------------------------------------------------------------------
# Fit
# ---------------------------------------------------------------------------
@hides_solver_names
def fit(
    df: pd.DataFrame,
    mapping: dict,
    stress_cols: list,
    distribution_id: str = "weibull",
    life_model_id: str = "arrhenius",
    unit: str = "",
    stress_labels: Optional[list] = None,
) -> tuple[dict, str]:
    """Fit an ALT model and build the JSON-safe results payload.

    Returns ``(payload, cache_id)`` addressing the live model.
    """
    if distribution_id not in ALT_DISTRIBUTIONS:
        raise FitError(
            f"Unknown ALT distribution '{distribution_id}'. Choose one of: "
            f"{', '.join(ALT_DISTRIBUTIONS)}."
        )
    if life_model_id not in LIFE_MODELS:
        raise FitError(
            f"Unknown life-stress model '{life_model_id}'. Choose one of: "
            f"{', '.join(LIFE_MODEL_CHOICES)}."
        )
    entry = LIFE_MODELS[life_model_id]
    need = entry["n_stress"]
    if len(stress_cols) != need:
        raise FitError(
            f"“{entry['name']}” needs {need} stress column"
            f"{'' if need == 1 else 's'}, but {len(stress_cols)} were mapped."
        )

    inputs = build_inputs(df, mapping, stress_cols)
    dist = DISTRIBUTIONS[distribution_id]["dist"]
    try:
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            model = note_fit(AcceleratedLife(dist, entry["model"]).fit(**inputs))
        reissue_deprecations(caught)
    except FitError:
        raise
    except Exception as exc:  # noqa: BLE001 - surface SurPyval's message
        # Named by the dataset's own rows (build_inputs drops unusable ones).
        c_col = mapping.get("c")
        x_col = mapping.get("x") or mapping.get("xl")
        msg = outside_support_message(
            exc, pd.to_numeric(df[x_col], errors="coerce").to_numpy(float),
            pd.to_numeric(df[c_col], errors="coerce").fillna(0).to_numpy(float)
            if c_col in df.columns else None,
            DISTRIBUTIONS[distribution_id]["name"], getattr(dist, "support", (0.0, np.inf)))
        raise FitError(msg or str(exc) or f"{type(exc).__name__}") from exc

    payload = _build_payload(
        model, inputs, distribution_id, life_model_id, unit, stress_cols, stress_labels
    )
    # No finite maximum (#230): an ALT fit with the failures at too few stress
    # levels; the use-level extrapolation of such a fit means nothing.
    pm = getattr(entry["model"], "phi_param_map", {}) or {}
    names = [n for n, _ in sorted(pm.items(), key=lambda kv: kv[1])]
    payload["maximum"] = getattr(model, "maximum", None)
    notice = no_maximum_notice(model, caught, names, kind="alt")
    if notice:
        payload["no_finite_maximum"] = notice
        payload["params"] = without_intervals(payload["params"])
        payload["coefficients"] = without_intervals(payload["coefficients"])
    return payload, store_live(model)


def refit(inputs: dict, distribution_id: str, life_model_id: str):
    """Fit the live model again from :func:`build_inputs`' arrays (the
    compute service's bootstrap job has no dataset, only these). The same
    data give the same model as :func:`fit`."""
    if distribution_id not in ALT_DISTRIBUTIONS or life_model_id not in LIFE_MODELS:
        raise FitError("Unknown ALT distribution or life-stress model.")
    dist = DISTRIBUTIONS[distribution_id]["dist"]
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            return note_fit(AcceleratedLife(dist, LIFE_MODELS[life_model_id]["model"]).fit(**inputs))
    except Exception as exc:  # noqa: BLE001 - surface SurPyval's message
        raise FitError(str(exc) or type(exc).__name__) from exc


_Z95 = 1.959963984540054


def _characteristic_life(model, Z: np.ndarray) -> np.ndarray:
    """The distribution's characteristic life (substituted scale) at stresses
    ``Z`` (an n×k array) — i.e. ``phi(Z)``, flattened to 1-D."""
    with np.errstate(all="ignore"):
        return np.asarray(model.phi(np.atleast_2d(Z)), dtype=float).ravel()


def _build_payload(
    model, inputs, distribution_id, life_model_id, unit, stress_cols, stress_labels
) -> dict:
    entry = LIFE_MODELS[life_model_id]
    dist_name = DISTRIBUTIONS[distribution_id]["name"]
    x, Z = inputs["x"], inputs["Z"]
    k_dist = int(getattr(model, "k_dist", 1) or 1)
    params = np.asarray(model.params, dtype=float)
    try:
        ses = np.asarray(model.standard_errors(), dtype=float).ravel()
        if ses.size != params.size:
            ses = None
    except Exception:  # noqa: BLE001
        ses = None

    model_names = list(getattr(model, "parameter_names", []) or [])

    def _ci(i):
        if ses is None or not np.isfinite(ses[i]):
            return None
        # SurPyval's own 95% Wald interval (#231): on the log scale for a
        # positive shape parameter, so it stays inside its support; the
        # life-stress coefficients are unbounded, so theirs is symmetric.
        if i < len(model_names):
            ci = param_interval(model, model_names[i], 0.95, "wald")
            if ci is not None:
                return ci
        return [float(params[i] - _Z95 * ses[i]), float(params[i] + _Z95 * ses[i])]

    # Distribution shape parameters: everything after the substituted scale
    # (index 0, a fixed placeholder). Names come from the distribution.
    dist_param_names = list(getattr(dist_of(distribution_id), "parameter_names", []) or [])
    shape_params = []
    for i in range(1, k_dist):
        name = dist_param_names[i] if i < len(dist_param_names) else f"p{i}"
        shape_params.append({"name": name, "value": float(params[i]), "ci": _ci(i)})

    # Life-stress coefficients: the phi parameters, in map order.
    pm = getattr(entry["model"], "phi_param_map", {}) or {}
    coeffs = []
    for name, off in sorted(pm.items(), key=lambda kv: kv[1]):
        idx = k_dist + off
        if idx < params.size:
            coeffs.append({"name": name, "value": float(params[idx]), "ci": _ci(idx)})

    labels = stress_labels or list(stress_cols)
    stresses = [{"key": f"s{j + 1}", "column": stress_cols[j], "label": labels[j]}
                for j in range(len(stress_cols))]

    # Per test-stress level: the fitted characteristic life at each unique stress
    # combination present in the data, plus the observed count.
    uniq, counts = _unique_rows(Z)
    life_at_uniq = _characteristic_life(model, uniq)
    levels = []
    for row, cnt, life in zip(uniq, counts, life_at_uniq):
        levels.append({
            "stress": [float(v) for v in row],
            "n": int(cnt),
            "characteristic_life": float(life) if np.isfinite(life) else None,
        })

    payload = {
        "kind": "alt",
        "unit": (unit or "").strip(),
        "distribution": dist_name,
        "distribution_id": distribution_id,
        "life_model": entry["name"],
        "life_model_id": life_model_id,
        "n": int(np.shape(x)[0]),
        **({"interval_censored": True} if is_interval(inputs) else {}),
        "bounds_methods": bounds_methods(inputs),
        "stresses": stresses,
        "params": shape_params,
        "coefficients": coeffs,
        "levels": levels,
        "life_stress_plot": _life_stress_plot(model, Z, uniq, life_at_uniq, entry, labels, inputs),
        "probability_plot": _probability_plot(
            model, dist_of(distribution_id), inputs, k_dist, uniq, life_at_uniq, labels
        ),
        "gof": _gof(model),
        "functions": {"evaluate_path": None},  # filled by the service with the model id
    }
    return _json_safe(payload)


def dist_of(distribution_id: str):
    return DISTRIBUTIONS[distribution_id]["dist"]


def _unique_rows(Z: np.ndarray):
    """Unique stress rows and their counts, order-stable by first appearance."""
    Z = np.atleast_2d(Z)
    seen: "OrderedDict[tuple, int]" = OrderedDict()
    for row in Z:
        key = tuple(np.round(row, 9).tolist())
        seen[key] = seen.get(key, 0) + 1
    rows = np.array([list(k) for k in seen.keys()], dtype=float)
    counts = np.array(list(seen.values()), dtype=int)
    return rows, counts


def _life_stress_plot(model, Z, uniq, life_at_uniq, entry, labels, inputs=None) -> dict:
    """Characteristic-life-vs-stress data: fitted line(s) over the stress range
    (extended below the lowest tested stress toward use level), plus the fitted
    point at each tested level. For two stresses we draw one line per unique
    secondary-stress level, plotted against the primary stress."""
    primary = 0
    zc = Z[:, primary]
    lo, hi = float(np.min(zc)), float(np.max(zc))
    span = hi - lo or max(abs(hi), 1.0)
    grid = np.linspace(lo - 0.4 * span, hi + 0.1 * span, 120)

    def line_for(secondary_val):
        if Z.shape[1] == 1:
            G = grid.reshape(-1, 1)
        else:
            G = np.column_stack([grid, np.full_like(grid, secondary_val)])
        life = _characteristic_life(model, G)
        keep = np.isfinite(life) & (life > 0)
        return {
            "stress": grid[keep].tolist(),
            "life": life[keep].tolist(),
            "secondary": None if Z.shape[1] == 1 else float(secondary_val),
        }

    if Z.shape[1] == 1:
        lines = [line_for(None)]
    else:
        sec_levels = sorted({float(v) for v in np.round(uniq[:, 1], 9)})
        lines = [line_for(s) for s in sec_levels]

    points = [
        {"stress": float(row[primary]),
         "life": float(life) if np.isfinite(life) else None,
         "secondary": None if Z.shape[1] == 1 else float(row[1])}
        for row, life in zip(uniq, life_at_uniq)
    ]
    out = {
        "x_label": labels[primary],
        "y_label": "Characteristic life",
        "log_y": bool(entry["log_y"]),
        "lines": lines,
        "points": points,
        "secondary_label": labels[1] if Z.shape[1] > 1 else None,
    }
    if inputs is not None and is_interval(inputs):
        out["observations"] = _interval_observations(inputs, primary)
    return out


# Rows drawn on the life-stress plot for inspection data, at most.
_MAX_PLOTTED_ROWS = 2000


def _interval_observations(inputs: dict, primary: int = 0) -> dict:
    """Inspection data on the life-stress plot (#237): each unit found failed
    between two inspections as a vertical range at its stress, and each one
    seen to fail at a known time as a point. Units still running aren't drawn
    (they have no failure time). Past ``_MAX_PLOTTED_ROWS`` rows an evenly
    spaced subset is drawn and ``shown`` says how many."""
    x = np.asarray(inputs["x"], dtype=float)
    s = np.asarray(inputs["Z"], dtype=float)[:, primary]
    c = inputs.get("c")
    lo, hi = x[:, 0], x[:, 1]
    if c is None:
        c = np.where(lo == hi, 0, np.where(np.isfinite(hi), 2, 1))
    c = np.asarray(c)
    ranged = (c == 2) & np.isfinite(hi) & (hi > lo)
    exact = (c == 0) & np.isfinite(lo)
    idx_r, idx_e = np.flatnonzero(ranged), np.flatnonzero(exact)
    total = idx_r.size + idx_e.size
    if total > _MAX_PLOTTED_ROWS:
        idx_r = idx_r[np.linspace(0, idx_r.size - 1, _MAX_PLOTTED_ROWS * idx_r.size // total).astype(int)] \
            if idx_r.size else idx_r
        idx_e = idx_e[np.linspace(0, idx_e.size - 1, _MAX_PLOTTED_ROWS * idx_e.size // total).astype(int)] \
            if idx_e.size else idx_e
    ranges = {"stress": [], "time": []}
    for i in idx_r:
        # One trace, segments split by gaps (null), so the plot stays light.
        ranges["stress"] += [float(s[i]), float(s[i]), None]
        # A lower bound of 0 (failed before the first inspection) is kept: the
        # app draws it to the foot of a logarithmic axis.
        ranges["time"] += [float(max(lo[i], 0.0)), float(hi[i]), None]
    return {
        "ranges": ranges,
        "failures": {"stress": s[idx_e].tolist(), "time": lo[idx_e].tolist()},
        "n_ranges": int(ranged.sum()),
        "n_failures": int(exact.sum()),
        "shown": int(idx_r.size + idx_e.size),
    }


_EPS = 1e-6


def _stress_label(row, labels) -> str:
    """Legend label for a stress level, e.g. ``Voltage (kV)=30`` or, for two
    stresses, ``Temperature (°C)=80 · Load=0.9``."""
    return " · ".join(f"{labels[j]}={_num(float(v))}" for j, v in enumerate(row))


def _num(v: float) -> str:
    return f"{v:g}"


def _probability_plot(model, dist, inputs, k_dist, uniq, life_at_uniq, labels) -> dict | None:
    """Per-stress-level probability plot on the distribution's own paper.

    For each tested stress level: the failure points (empirical plotting
    positions) as a scatter, and the model's fitted CDF for that level as a
    line — all linearised with the distribution's ``mpp`` transforms, so a good
    fit at every level plots as parallel straight lines (common shape) and the
    data hugging them confirms the fit. Returns ``None`` if the distribution has
    no probability paper.
    """
    if not (hasattr(dist, "mpp_x_transform") and hasattr(dist, "mpp_y_transform")):
        return None
    x, Z = inputs["x"], inputs["Z"]
    c = inputs.get("c")
    n = inputs.get("n")
    t = inputs.get("t")
    shape = [float(v) for v in np.asarray(model.params, dtype=float)[1:k_dist]]

    def tx(vals):
        return np.asarray(dist.mpp_x_transform(np.asarray(vals, dtype=float)), dtype=float)

    def ty(p):
        p = np.clip(np.asarray(p, dtype=float), _EPS, 1 - _EPS)
        return np.asarray(dist.mpp_y_transform(p, *shape), dtype=float)

    series = []
    all_x, all_t = [], []
    for row, life in zip(uniq, life_at_uniq):
        if not np.isfinite(life) or life <= 0:
            continue
        mask = np.all(np.isclose(Z, row, rtol=0, atol=0), axis=1)
        xs = x[mask]
        if xs.size == 0:
            continue
        cs = c[mask] if c is not None else None
        ns = n[mask] if n is not None else None

        # Empirical plotting positions from a quick per-level fit of the base
        # distribution (positions are the data's median ranks — the line we draw
        # is the ALT model's, not this throwaway fit).
        scatter = None
        try:
            fit_kwargs = {"x": xs}
            if cs is not None:
                fit_kwargs["c"] = cs
            if ns is not None:
                fit_kwargs["n"] = ns
            if t is not None:
                fit_kwargs["t"] = t[mask]
            per_level = note_fit(dist.fit(**fit_kwargs))
            # Inspection (interval) and left-censored data have no exact
            # failure times to rank: the Turnbull estimate places them (#237).
            turnbull = xs.ndim == 2 or (cs is not None and np.any(np.isin(cs, (-1, 2))))
            pdata = per_level.get_plot_data(heuristic="Turnbull" if turnbull else "Nelson-Aalen")
            sx = np.asarray(pdata["x_"], dtype=float)
            sF = np.asarray(pdata["F"], dtype=float)
            # Only failures are plotted; censored units adjust the positions.
            keep = (np.ones(sx.size, dtype=bool) if turnbull
                    else failure_positions_mask(per_level, sx.size))
            keep &= np.isfinite(sx) & (sx > 0) & np.isfinite(sF) & (sF > 0)
            if keep.any():
                scatter = {"x": tx(sx[keep]).tolist(), "y": ty(sF[keep]).tolist()}
                all_t.extend(sx[keep].tolist())
        except Exception:  # noqa: BLE001 - a level may be too small / all-censored
            scatter = None

        # Fitted line for this level: the base distribution at (characteristic
        # life, shape) evaluated over the level's time range.
        lv = dist.from_params([float(life), *shape])
        obs = np.asarray(xs, dtype=float).ravel()
        obs = obs[np.isfinite(obs) & (obs > 0)]
        lo = float(obs.min()) * 0.6 if obs.size else float(life) * 0.1
        hi = float(obs.max()) * 1.4 if obs.size else float(life) * 2.0
        grid = np.linspace(max(lo, _EPS), hi, 80)
        with np.errstate(all="ignore"):
            cdf = np.asarray(lv.ff(grid), dtype=float)
        lk = np.isfinite(cdf) & (cdf > _EPS) & (cdf < 1 - _EPS)
        line = {"x": tx(grid[lk]).tolist(), "y": ty(cdf[lk]).tolist()}
        all_t.extend(grid[lk].tolist())

        series.append({
            "label": _stress_label(row, labels),
            "stress": [float(v) for v in row],
            "scatter": scatter,
            "line": line,
        })
        all_x.extend(line["x"])

    if not series:
        return None

    # Axis ticks: real times on the (transformed) x-axis, standard probability
    # levels on the y-axis.
    t_arr = np.asarray(all_t, dtype=float)
    x_ticks = _time_ticks(dist, t_arr, tx)
    probs = [0.01, 0.05, 0.1, 0.25, 0.5, 0.9, 0.99]
    y_ticks = {
        "vals": ty(np.asarray(probs)).tolist(),
        "labels": [f"{int(p * 100)}%" if p * 100 >= 1 else f"{p * 100:g}%" for p in probs],
    }
    return {
        "distribution": _dist_name(dist),
        "series": series,
        "x_ticks": x_ticks,
        "y_ticks": y_ticks,
    }


def _dist_name(dist) -> str:
    for entry in DISTRIBUTIONS.values():
        if entry["dist"] is dist:
            return entry["name"]
    return getattr(dist, "name", "")


def _time_ticks(dist, times: np.ndarray, tx) -> dict:
    """Nice real-time ticks placed on the transformed x-axis. Uses decades when
    the x-transform is logarithmic (Weibull/Lognormal/…), else linear ticks."""
    times = times[np.isfinite(times) & (times > 0)]
    if times.size == 0:
        return {"vals": [], "labels": []}
    lo, hi = float(times.min()), float(times.max())
    # Detect a log-like transform: ln stretches [1,10] by ~2.30.
    d1 = float(tx(np.array([1.0, 10.0]))[1] - tx(np.array([1.0, 10.0]))[0])
    log_like = abs(d1 - np.log(10.0)) < 1e-6
    if log_like:
        # 1-2-5 steps per decade, clipped to the data range: plain decades often
        # put only a single tick inside the plotted span.
        import math
        e0, e1 = math.floor(math.log10(lo)), math.ceil(math.log10(hi))
        vals = [m * 10.0 ** e for e in range(e0, e1 + 1) for m in (1, 2, 5)]
        vals = [v for v in vals if lo * 0.95 <= v <= hi * 1.05]
        if len(vals) < 2:  # very narrow span — fall back to the endpoints
            vals = [lo, hi]
    else:
        vals = list(np.linspace(lo, hi, 6))
    vals = sorted(v for v in vals if v > 0)
    return {"vals": tx(np.asarray(vals)).tolist(), "labels": [_tick_label(v) for v in vals]}


def _tick_label(v: float) -> str:
    """Readable axis label: plain integers with separators up to 1e7, else 1e/sci."""
    if v >= 1 and v < 1e7 and abs(v - round(v)) < 1e-6:
        return f"{int(round(v)):,}"
    return f"{v:g}"


def _gof(model) -> list:
    out = []
    for attr, label in (("aic", "AIC"), ("bic", "BIC"), ("neg_ll", "Neg. log-likelihood")):
        v = getattr(model, attr, None)
        if callable(v):
            try:
                v = v()
            except Exception:
                v = None
        if v is not None and np.isfinite(float(v)):
            out.append({"id": attr, "label": label, "value": float(v)})
    return out


# ---------------------------------------------------------------------------
# Evaluate at a use-level stress
# ---------------------------------------------------------------------------
def evaluate(
    model,
    use_stress: list,
    life_model_id: str,
    ref_stress: Optional[list] = None,
    points: int = 300,
    *,
    mission_time: Optional[float] = None,
    confidence: float = 0.95,
    bounds_method: Optional[str] = "wald",
) -> dict:
    """Reliability at a *use-level* stress: sf/ff/hf/… over a time grid, key
    metrics, the extrapolated characteristic life, and — when a reference (test)
    stress is given — the acceleration factor between them. ``mission_time``
    adds the reliability over that mission. With ``bounds_method`` (Wald by
    default, instant; None for none) it carries the confidence bounds of
    :func:`use_level_bounds` too (#231).
    """
    Zuse = _use_row(use_stress, life_model_id)
    if mission_time is not None:
        mission_time = _mission_time(mission_time)

    life_use = float(_characteristic_life(model, Zuse)[0])
    # A fine grid at the use stress, extended until failure is (nearly)
    # certain: the mean integrates sf over it, and it backs up the B-lives
    # where SurPyval's quantile function (qf, 0.23) gives none.
    hi = _grid_extent(model, Zuse, life_use, target=0.9999)
    fine = np.linspace(0.0, hi, 4000)
    Zfine = np.repeat(Zuse, fine.size, axis=0)
    with np.errstate(all="ignore"):
        ff_fine = np.clip(np.nan_to_num(np.asarray(model.ff(fine, Zfine), dtype=float), nan=0.0), 0.0, 1.0)
        sf_fine = np.clip(1.0 - ff_fine, 0.0, 1.0)

    # Curves for the calculator over a display grid to the 0.999 life.
    hi_disp = _grid_extent(model, Zuse, life_use, target=0.999)
    grid = np.linspace(0.0, hi_disp, points)
    curves = _eval_functions(model, grid, np.repeat(Zuse, grid.size, axis=0))

    metrics = {
        "characteristic_life": life_use if np.isfinite(life_use) else None,
        "mean_life": float(_trapezoid(sf_fine, fine)),
    }
    exact_q = _quantiles(model, Zuse, [0.5, 0.1, 0.01])
    for q, key, v in zip((0.5, 0.1, 0.01), ("b50", "b10", "b1"), exact_q):
        metrics[key] = v if v is not None else _invert_ff(fine, ff_fine, q)
    if mission_time is not None:
        with np.errstate(all="ignore"):
            r = float(np.asarray(model.sf(np.array([mission_time]), Zuse), dtype=float).ravel()[0])
        metrics["mission_time"] = mission_time
        metrics["mission_reliability"] = r if np.isfinite(r) else None

    af = None
    if ref_stress is not None:
        Zref = np.atleast_2d(np.asarray(ref_stress, dtype=float))
        life_ref = float(_characteristic_life(model, Zref)[0])
        if np.isfinite(life_ref) and life_ref > 0 and np.isfinite(life_use):
            af = {"ref_stress": [float(v) for v in Zref.ravel()],
                  "value": life_use / life_ref}

    out = {
        "use_stress": [float(v) for v in Zuse.ravel()],
        "curves": curves,
        "metrics": metrics,
        "acceleration_factor": af,
        "t_max": float(hi_disp),
    }
    if bounds_method is not None:
        try:
            out["bounds"] = use_level_bounds(
                model, use_stress, life_model_id, method=bounds_method, confidence=confidence,
                mission_time=mission_time, t_max=hi_disp)
        except FitError as exc:
            out["bounds"] = None
            out["bounds_note"] = str(exc)
    return _json_safe(out)


# ---------------------------------------------------------------------------
# Confidence bounds at the use stress (#231)
# ---------------------------------------------------------------------------
#: SurPyval 0.23's bound methods on a regression model: Wald (delta method,
#: instant), likelihood ratio (#583: a search of the likelihood, about a
#: second or two) and the conditional parametric bootstrap (#617: BCa
#: interval over ``n_boot`` refits; tens of seconds, so a compute job).
BOUND_METHODS = ("wald", "lr", "bootstrap")
METHOD_NAMES = {"wald": "Wald (Fisher matrix)", "lr": "Likelihood ratio", "bootstrap": "Bootstrap (BCa)"}
DEFAULT_CONFIDENCE = 0.95
#: Bootstrap refits: SurPyval's default. 1000 is steadier at a 5% tail, at
#: five times the cost.
DEFAULT_N_BOOT = 200
MAX_N_BOOT = 1000
#: The bootstrap's seed: fixed, so a model's bootstrap bounds are the same
#: on every run (and the refits are shared by the band, the B-lives and the
#: coefficients, as SurPyval keeps them per integer seed).
BOOTSTRAP_SEED = 231
#: Points of the band on the reliability curve. The likelihood-ratio band
#: searches the likelihood at each one (~30 ms a point), so it gets fewer.
BAND_POINTS = {"wald": 120, "lr": 41, "bootstrap": 120}
#: Fewer failures than this and no method holds its nominal coverage when
#: extrapolating (SurPyval's study, #583/#617: 90% bounds covered 0.71-0.87
#: with 11 failures, 0.88-0.90 with 46).
FEW_FAILURES = 20
#: Rows the likelihood-ratio and bootstrap bounds take in one request.
MAX_ROWS_LR = 5_000
MAX_ROWS_BOOTSTRAP = 5_000


def _use_row(use_stress, life_model_id: str) -> np.ndarray:
    Zuse = np.atleast_2d(np.asarray(use_stress, dtype=float))
    if Zuse.shape[0] != 1 or Zuse.shape[1] != LIFE_MODELS[life_model_id]["n_stress"]:
        raise FitError("Use-stress dimensions don't match the fitted model.")
    if not np.all(np.isfinite(Zuse)):
        raise FitError("Use-level stresses must be finite numbers.")
    return Zuse


def _mission_time(value) -> float:
    try:
        t = float(value)
    except (TypeError, ValueError):
        raise FitError("The mission time must be a number.") from None
    if not np.isfinite(t) or t <= 0:
        raise FitError("The mission time must be a positive number.")
    return t


def check_method(method: Optional[str]) -> str:
    m = (method or "wald").strip().lower()
    if m not in BOUND_METHODS:
        raise FitError(f"Unknown bounds method '{method}'. Choose one of: {', '.join(BOUND_METHODS)}.")
    return m


def check_confidence(confidence) -> float:
    try:
        c = float(confidence)
    except (TypeError, ValueError):
        raise FitError("The confidence level must be a number between 0 and 1.") from None
    if not 0.5 <= c < 1.0:
        raise FitError("The confidence level must be at least 0.5 and below 1 (e.g. 0.9 or 0.95).")
    return c


def check_n_boot(n_boot) -> int:
    try:
        n = int(n_boot)
    except (TypeError, ValueError):
        raise FitError("n_boot must be a whole number.") from None
    if not 100 <= n <= MAX_N_BOOT:
        raise FitError(f"n_boot must be between 100 and {MAX_N_BOOT}.")
    return n


def _quantiles(model, Zuse: np.ndarray, probs: list) -> list:
    """B-lives from SurPyval's quantile function (``qf``, 0.23), None where it
    gives none."""
    try:
        with np.errstate(all="ignore"), warnings.catch_warnings():
            warnings.simplefilter("ignore")
            q = np.asarray(model.qf(np.asarray(probs, dtype=float), Zuse), dtype=float).ravel()
    except Exception:  # noqa: BLE001 - fall back to the grid
        return [None] * len(probs)
    return [float(v) if np.isfinite(v) else None for v in q]


def param_interval(model, name: str, confidence: float, method: str = "wald", **boot) -> Optional[list]:
    """A two-sided interval on one fitted parameter from SurPyval's
    ``param_cb``, or None where it has none."""
    try:
        with np.errstate(all="ignore"), warnings.catch_warnings():
            warnings.simplefilter("ignore")
            ci = np.asarray(model.param_cb(name, alpha_ci=1.0 - confidence, bound="two-sided",
                                           method=method, **boot), dtype=float).ravel()
    except Exception:  # noqa: BLE001 - e.g. no covariance
        return None
    if ci.size != 2 or not np.all(np.isfinite(ci)):
        return None
    return [float(ci[0]), float(ci[1])]


def has_data(model) -> bool:
    """Whether a live model still holds the data it was fitted to: the
    likelihood-ratio and bootstrap bounds need it; a model rehydrated from
    its saved dict doesn't keep it."""
    return getattr(model, "data", None) is not None


def n_failures(model) -> Optional[float]:
    """Failures (and inspection-interval failures) the model was fitted to."""
    data = getattr(model, "data", None)
    try:
        c = np.asarray(data.c if hasattr(data, "c") else data["c"]).ravel()
        n = np.asarray(data.n if hasattr(data, "n") else data["n"], dtype=float).ravel()
        return float(n[np.isin(c, (0, 2))].sum())
    except Exception:  # noqa: BLE001
        return None


def _plain_warning(text: str) -> str:
    """A SurPyval warning in the app's words (it names its own arguments)."""
    return (text.replace("method='lr'", "the likelihood-ratio method")
                .replace("method='wald'", "the Wald method")
                .replace("cb()", "the reliability bounds"))


def use_level_bounds(
    model,
    use_stress: list,
    life_model_id: str,
    *,
    method: str = "wald",
    confidence: float = DEFAULT_CONFIDENCE,
    mission_time: Optional[float] = None,
    t_max: Optional[float] = None,
    n_boot: int = DEFAULT_N_BOOT,
    seed: int = BOOTSTRAP_SEED,
) -> dict:
    """Confidence bounds at a use-level stress from SurPyval 0.23 (#231):

    * ``band``: a two-sided band on the reliability R(t) over ``[0, t_max]``
      (``cb``);
    * ``b_lives``: the B10 and B1 lives with a one-sided *lower* bound
      (``quantile_cb``): the life that, with this confidence, at least 90%
      (99%) of units reach;
    * ``mission``: R(mission_time) with its one-sided lower bound (``cb``);
    * ``coefficients``: two-sided intervals on the distribution's shape and
      the life-stress coefficients (``param_cb``).

    ``method`` is ``wald`` (default), ``lr`` or ``bootstrap``; the last two
    need the data the model was fitted to (:func:`has_data`), and the
    bootstrap can't take left- or interval-censored data. Raises
    :class:`FitError` with a plain reason when the bounds can't be had.
    """
    method = check_method(method)
    confidence = check_confidence(confidence)
    Zuse = _use_row(use_stress, life_model_id)
    if mission_time is not None:
        mission_time = _mission_time(mission_time)
    alpha = 1.0 - confidence
    boot = {}
    if method == "bootstrap":
        boot = {"n_boot": check_n_boot(n_boot), "random_state": int(seed)}
    if method != "wald" and not has_data(model):
        raise FitError(f"{METHOD_NAMES[method]} bounds need the data the model was fitted to.")
    if method == "bootstrap" and getattr(model, "data", None) is not None:
        c = np.asarray(getattr(model.data, "c", None) if hasattr(model.data, "c") else model.data["c"])
        if np.any(np.isin(c, (-1, 2))):
            raise FitError("Bootstrap bounds aren't available for inspection (interval-censored) or "
                           "left-censored data: a resample would need inspection times the data don't "
                           "record. Use the Wald or likelihood-ratio method.")
    life_use = float(_characteristic_life(model, Zuse)[0])
    if t_max is None:
        t_max = _grid_extent(model, Zuse, life_use, target=0.999)
    grid = np.linspace(0.0, float(t_max), BAND_POINTS[method])

    caught_all = []
    try:
        with np.errstate(all="ignore"), warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            band = np.asarray(model.cb(grid, Zuse, on="sf", alpha_ci=alpha, bound="two-sided",
                                       method=method, **boot), dtype=float).reshape(-1, 2)
            probs = np.array([0.1, 0.01])
            q_hat = np.asarray(model.qf(probs, Zuse), dtype=float).ravel()
            q_lo = np.asarray(model.quantile_cb(probs, Zuse, alpha_ci=alpha, bound="lower",
                                                method=method, **boot), dtype=float).ravel()
            mission = None
            if mission_time is not None:
                r_hat = float(np.asarray(model.sf(np.array([mission_time]), Zuse), dtype=float).ravel()[0])
                r_lo = float(np.asarray(model.cb(np.array([mission_time]), Zuse, on="sf", alpha_ci=alpha,
                                                 bound="lower", method=method, **boot),
                                        dtype=float).ravel()[0])
                mission = {"time": mission_time, "reliability": r_hat, "lower": r_lo}
        caught_all.extend(caught)
    except FitError:
        raise
    except Exception as exc:  # noqa: BLE001 - SurPyval's reason, in the app's words
        reason = _plain_warning(str(exc).strip() or type(exc).__name__)
        raise FitError(f"No {METHOD_NAMES[method].lower()} bounds for this model: {reason}") from exc

    names = list(getattr(model, "parameter_names", []) or [])
    k_dist = int(getattr(model, "k_dist", 1) or 1)
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        coefficients = []
        for i, name in enumerate(names):
            if i == 0:
                continue  # the substituted scale: the life-stress relation itself
            coefficients.append({
                "name": name,
                "value": float(np.asarray(model.params, dtype=float)[i]),
                "kind": "shape" if i < k_dist else "life_stress",
                "ci": param_interval(model, name, confidence, method, **boot),
            })
    caught_all.extend(caught)

    warnings_out = []
    for w in caught_all:
        text = _plain_warning(str(w.message))
        if issubclass(w.category, (DeprecationWarning, FutureWarning)) or text in warnings_out:
            continue
        if issubclass(w.category, RuntimeWarning) and "invalid value" in text:
            continue
        warnings_out.append(text)
    fails = n_failures(model)
    if fails is not None and fails < FEW_FAILURES:
        warnings_out.insert(0, (
            f"Only {fails:g} failures. With this few, no bound method holds its stated confidence when "
            "extrapolating to the use stress: in SurPyval's study of an accelerated test extrapolated 40 °C "
            "below its coolest cell, 90% bounds covered 71-87% of the time with 11 failures, against "
            "88-90% with 46. Read these bounds as optimistic."))

    def _f(v):
        v = float(v)
        return v if np.isfinite(v) else None

    return _json_safe({
        "method": method,
        "method_name": METHOD_NAMES[method],
        "confidence": confidence,
        **({"n_boot": boot["n_boot"], "seed": boot["random_state"]} if boot else {}),
        "use_stress": [float(v) for v in Zuse.ravel()],
        "band": {"x": grid.tolist(), "lower": [_f(v) for v in band[:, 0]],
                 "upper": [_f(v) for v in band[:, 1]], "two_sided": True},
        "b_lives": {
            "b10": {"value": _f(q_hat[0]), "lower": _f(q_lo[0])},
            "b1": {"value": _f(q_hat[1]), "lower": _f(q_lo[1])},
        },
        "mission": mission,
        "coefficients": coefficients,
        "warnings": warnings_out,
        "note": (f"Two-sided {confidence * 100:g}% band on R(t); B-lives and the mission reliability "
                 f"carry one-sided {confidence * 100:g}% lower bounds; intervals on the parameters are "
                 f"two-sided {confidence * 100:g}%. Method: {METHOD_NAMES[method]}."),
    })


def _grid_extent(model, Z: np.ndarray, life: float, target: float) -> float:
    """A time span at stress ``Z`` that reaches ``ff = target`` — start from the
    characteristic life and double until the tail is covered (capped)."""
    hi = life * 4.0 if np.isfinite(life) and life > 0 else 1.0
    Z = np.atleast_2d(Z)
    for _ in range(8):
        grid = np.linspace(0.0, hi, 256)
        with np.errstate(all="ignore"):
            ff = np.asarray(model.ff(grid, np.repeat(Z, grid.size, axis=0)), dtype=float)
        if np.nanmax(ff) >= target:
            break
        hi *= 2.0
    return float(hi)


def _invert_ff(grid: np.ndarray, ff: np.ndarray, p: float):
    """The time at which ff first reaches ``p`` (a BX life), by grid inversion."""
    idx = int(np.searchsorted(ff, p))
    if idx <= 0 or idx >= grid.size:
        return None
    # Linear interpolation between the bracketing grid points.
    f0, f1 = ff[idx - 1], ff[idx]
    if f1 == f0:
        return float(grid[idx])
    frac = (p - f0) / (f1 - f0)
    return float(grid[idx - 1] + frac * (grid[idx] - grid[idx - 1]))
