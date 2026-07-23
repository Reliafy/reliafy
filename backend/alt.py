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
from collections import OrderedDict
from typing import Optional

import numpy as np
import pandas as pd

from backend.fitting import (
    DISTRIBUTIONS,
    FitError,
    _eval_functions,
    _json_safe,
)
from surpyval import AcceleratedLife
from surpyval.univariate.regression import accelerated_life as _al

_LM = _al.LIFE_MODELS


# Life-stress relationships offered, keyed by the id used in the API/URL.
# ``model`` is the SurPyval life model; ``n_stress`` is how many stress columns
# it consumes; ``log_y`` hints the life-vs-stress plot should use a log life
# axis (multiplicative acceleration). Ordered single-stress first, then dual.
LIFE_MODELS = {
    "arrhenius": {
        "name": "Arrhenius",
        "model": _LM["InverseExponential"],
        "n_stress": 1,
        "log_y": True,
        "desc": "Thermal acceleration — life ∝ exp(b / stress). Use absolute "
                "temperature (K). The classic model for chemical/thermal ageing.",
    },
    "exponential": {
        "name": "Exponential",
        "model": _LM["Exponential"],
        "n_stress": 1,
        "log_y": True,
        "desc": "Log-linear in stress — life ∝ exp(a + b·stress). For a stress "
                "whose effect is exponential and doesn't need inverting.",
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
        "desc": "Life ∝ stress^−n. The standard model for voltage, load or "
                "pressure acceleration.",
    },
    "power": {
        "name": "Power law",
        "model": _LM["Power"],
        "n_stress": 1,
        "log_y": True,
        "desc": "Life ∝ a·stress^n — a power relationship where higher stress "
                "raises life (rare; use inverse power for the usual case).",
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
def build_inputs(df: pd.DataFrame, mapping: dict, stress_cols: list) -> dict:
    """Extract SurPyval ALT inputs from a DataFrame.

    ``mapping`` carries the life-data columns (``x`` required; ``c``/``n``
    optional). ``stress_cols`` is the ordered list of one or two stress columns.
    Returns a kwargs dict: ``x`` (times), ``Z`` (n×k stresses), and optional
    ``c``/``n``.
    """
    xcol = mapping.get("x")
    if not xcol:
        raise FitError("Column mapping is missing the failure-time column 'x'.")
    if xcol not in df.columns:
        raise FitError(f"Column '{xcol}' is not in the dataset.")
    if not stress_cols:
        raise FitError("Select at least one stress column.")
    for s in stress_cols:
        if s not in df.columns:
            raise FitError(f"Stress column '{s}' is not in the dataset.")

    x = pd.to_numeric(df[xcol], errors="coerce")
    Z = np.column_stack([pd.to_numeric(df[s], errors="coerce").to_numpy(float) for s in stress_cols])
    keep = x.notna().to_numpy() & np.isfinite(Z).all(axis=1)
    if not keep.any():
        raise FitError("No usable rows: failure time and stresses must be numeric.")

    out: dict = {"x": x.to_numpy(float)[keep], "Z": Z[keep]}

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
    n = _numeric("n")
    if n is not None:
        nn = np.nan_to_num(n, nan=1.0)
        nn[nn < 1] = 1
        out["n"] = nn.astype(int)
    return out


# ---------------------------------------------------------------------------
# Fit
# ---------------------------------------------------------------------------
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
        model = AcceleratedLife(dist, entry["model"]).fit(**inputs)
    except FitError:
        raise
    except Exception as exc:  # noqa: BLE001 - surface SurPyval's message
        raise FitError(str(exc) or f"{type(exc).__name__}") from exc

    payload = _build_payload(
        model, inputs, distribution_id, life_model_id, unit, stress_cols, stress_labels
    )
    return payload, store_live(model)


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

    def _ci(i):
        if ses is None or not np.isfinite(ses[i]):
            return None
        return [float(params[i] - _Z95 * ses[i]), float(params[i] + _Z95 * ses[i])]

    # Distribution shape parameters: everything after the substituted scale
    # (index 0, a fixed placeholder). Names come from the distribution.
    dist_param_names = list(getattr(dist_of(distribution_id), "param_names", []) or [])
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
        "n": int(x.size),
        "stresses": stresses,
        "params": shape_params,
        "coefficients": coeffs,
        "levels": levels,
        "life_stress_plot": _life_stress_plot(model, Z, uniq, life_at_uniq, entry, labels),
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


def _life_stress_plot(model, Z, uniq, life_at_uniq, entry, labels) -> dict:
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
    return {
        "x_label": labels[primary],
        "y_label": "Characteristic life",
        "log_y": bool(entry["log_y"]),
        "lines": lines,
        "points": points,
        "secondary_label": labels[1] if Z.shape[1] > 1 else None,
    }


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
) -> dict:
    """Reliability at a *use-level* stress: sf/ff/hf/… over a time grid, key
    metrics, the extrapolated characteristic life, and — when a reference (test)
    stress is given — the acceleration factor between them.
    """
    Zuse = np.atleast_2d(np.asarray(use_stress, dtype=float))
    if Zuse.shape[1] != LIFE_MODELS[life_model_id]["n_stress"]:
        raise FitError("Use-stress dimensions don't match the fitted model.")

    life_use = float(_characteristic_life(model, Zuse)[0])
    # The regression model has no quantile function, so we work off a fine grid
    # at the use stress: extend it until failure is (nearly) certain, then read
    # BX lives by inverting ff and the mean by integrating sf.
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
    for q, key in ((0.5, "b50"), (0.1, "b10"), (0.01, "b1")):
        metrics[key] = _invert_ff(fine, ff_fine, q)

    af = None
    if ref_stress is not None:
        Zref = np.atleast_2d(np.asarray(ref_stress, dtype=float))
        life_ref = float(_characteristic_life(model, Zref)[0])
        if np.isfinite(life_ref) and life_ref > 0 and np.isfinite(life_use):
            af = {"ref_stress": [float(v) for v in Zref.ravel()],
                  "value": life_use / life_ref}

    return _json_safe({
        "use_stress": [float(v) for v in Zuse.ravel()],
        "curves": curves,
        "metrics": metrics,
        "acceleration_factor": af,
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
