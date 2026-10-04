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
import warnings
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
    if mapping.get("mode"):
        # The failure modes a growth projection classifies (#232).
        try:
            payload["failure_modes"] = failure_modes(df, mapping)
        except FitError:
            payload["failure_modes"] = None
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
    names = list(getattr(fitter, "parameter_names", []) or [])
    return names if len(names) == n else [f"p{k}" for k in range(n)]


def _build_payload(np_model, para, x, i, model_id: str, unit: str) -> dict:
    n_systems = int(len(set(i.tolist())))
    n_events = int(len(x))

    # Nonparametric MCF step (observed) with a 95% confidence band.
    nx = np.asarray(np_model.x, dtype=float)
    mcf_obs = np.asarray(np_model.mcf_hat, dtype=float)
    try:
        cb = np.asarray(np_model.mcf_cb(nx, alpha_ci=0.05), dtype=float)
        # Order-proof: SurPyval 0.22 returns (lower, upper); earlier releases
        # returned (upper, lower).
        lower, upper = np.minimum(cb[:, 0], cb[:, 1]).tolist(), np.maximum(cb[:, 0], cb[:, 1]).tolist()
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
        if direction == "none":  # SurPyval 0.22 says "none"; the app and API say "no trend"
            direction = "no trend"
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
    cis = param_intervals(model_id, para)
    payload = {
        "kind": "recurrent",
        "unit": (unit or "").strip(),
        "n_systems": n_systems,
        "n_events": n_events,
        "model": {"id": model_id, "name": MODELS[model_id]["name"]},
        "params": [{"name": n, "value": float(v), **({"ci": cis[n]} if n in cis else {})}
                   for n, v in zip(param_names, params_arr)],
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


def param_intervals(model_id: str, model) -> dict:
    """``{name: [lower, upper]}``: the 95% confidence interval on each of a
    Crow-AMSAA fit's parameters (SurPyval's Wald bounds from the observed
    information, kept inside each parameter's support). Only a maximum-
    likelihood fit to data has them: {} for another model family, a model
    built from its parameters, or one restored without its data."""
    if model_id != "crow_amsaa":
        return {}
    out = {}
    for name in getattr(model, "parameter_names", None) or []:
        try:
            with warnings.catch_warnings(), np.errstate(all="ignore"):
                warnings.simplefilter("ignore")
                lo, hi = (float(v) for v in np.asarray(model.param_cb(name, alpha_ci=0.05), dtype=float))
        except Exception:  # noqa: BLE001 - no likelihood (from params / restored): no interval
            return {}
        if np.isfinite(lo) and np.isfinite(hi) and lo <= hi:
            out[name] = [lo, hi]
    return out


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
# Reliability growth projection (AMSAA-Crow / Crow extended; #232)
# ---------------------------------------------------------------------------
#
# SurPyval 0.23's ``CrowAMSAA.projection``: the MTBF once the fixes found in
# a growth test are put in. Each failure carries a failure-mode label; BD
# modes (keys of ``fef``) are fixed after the test with a fix-effectiveness
# factor, BC modes (``bc``) were fixed during it, every other mode is an A
# mode (not fixed). Exact, closed form, fast: no simulation, no job.

DEFAULT_FEF = 0.7  # MIL-HDBK-189C's typical fix effectiveness
_MAX_MODES = 500


def _mode_label(value) -> str | None:
    """A failure-mode cell as a label: trimmed text, or None when blank."""
    if value is None:
        return None
    if isinstance(value, float):
        if not np.isfinite(value):
            return None
        if value.is_integer():
            value = int(value)  # a numeric mode column reads "3", not "3.0"
    label = str(value).strip()
    return label or None


def projection_inputs(df: pd.DataFrame, mapping: dict, test_end=None) -> dict:
    """``{x, i, c, modes}`` for :meth:`CrowAMSAA.projection` from the event
    data: one row per failure (``n`` expanded), plus each system's
    end-of-test row (``c = 1``). The end of the test comes from the data's
    own ``c = 1`` rows, else its observation window (``tr``), else
    ``test_end`` — the time every system's test stopped."""
    for key in ("i", "x", "mode"):
        col = mapping.get(key)
        if not col:
            raise FitError("Map the failure-mode column to project growth." if key == "mode"
                           else f"Column mapping is missing '{key}'.")
        if col not in df.columns:
            raise FitError(f"Column '{col}' is not in the dataset.")
    x = pd.to_numeric(df[mapping["x"]], errors="coerce")
    keep = x.notna() & df[mapping["i"]].notna()
    if not keep.any():
        raise FitError("No usable rows: event time must be numeric.")
    x = x[keep].to_numpy(dtype=float)
    i = df[mapping["i"]][keep].astype(str).to_numpy()
    modes = [_mode_label(v) for v in df[mapping["mode"]][keep].tolist()]

    def _numeric(key, fill):
        col = mapping.get(key)
        if not col or col not in df.columns:
            return None
        return np.nan_to_num(pd.to_numeric(df[col], errors="coerce")[keep].to_numpy(dtype=float), nan=fill)

    c = _numeric("c", 0.0)
    c = np.zeros(x.size, dtype=int) if c is None else c.astype(int)
    if np.any((c != 0) & (c != 1)):
        raise FitError("A growth projection takes failures (c = 0) and each system's end of test (c = 1) only; "
                       "left- or interval-censored rows can't be used.")
    tl = _numeric("tl", 0.0)
    if tl is not None and np.any(tl != 0):
        raise FitError("A growth projection needs every system tested from time 0 (no delayed entry).")
    n = _numeric("n", 1.0)
    if n is not None:
        reps = np.maximum(n, 1).astype(int)
        x, i, c = np.repeat(x, reps), np.repeat(i, reps), np.repeat(c, reps)
        modes = [m for m, k in zip(modes, reps) for _ in range(k)]

    # Each system's end of test: its own c = 1 row, else its window (tr),
    # else the test_end given.
    tr = _numeric("tr", np.nan)
    if tr is None:
        tr = _numeric("t", np.nan)
    ends: dict = {}
    if tr is not None and not np.all(np.isnan(tr)):
        tr_full = np.repeat(tr, reps) if n is not None else tr
        for sys_id, t in zip(i, tr_full):
            if np.isfinite(t):
                ends[sys_id] = max(ends.get(sys_id, 0.0), float(t))
    if test_end is not None:
        test_end = _positive(test_end, "The end of the test")
    closed = set(i[c == 1].tolist())
    extra = []
    for sys_id in dict.fromkeys(i.tolist()):
        if sys_id in closed:
            continue
        end = ends.get(sys_id, test_end)
        if end is not None:
            extra.append((end, sys_id))
    if extra:
        x = np.concatenate([x, [e for e, _ in extra]])
        i = np.concatenate([i, [s for _, s in extra]])
        c = np.concatenate([c, np.ones(len(extra), dtype=int)])
        modes = modes + [None] * len(extra)
    if len(set(m for m, cc in zip(modes, c) if cc == 0 and m is not None)) > _MAX_MODES:
        raise FitError(f"More than {_MAX_MODES} distinct failure modes; group them first.")
    return {"x": x, "i": i, "c": c, "modes": modes}


def failure_modes(df: pd.DataFrame, mapping: dict) -> list[dict]:
    """``[{label, failures, first}]``: each failure mode in the data, its
    number of failures and its first occurrence, most failures first.
    Failures with no label are counted under ``label: None``."""
    ins = projection_inputs(df, mapping)
    events = ins["c"] == 0
    rows: dict = {}
    for t, m in zip(ins["x"][events], np.asarray(ins["modes"], dtype=object)[events]):
        row = rows.setdefault(m, {"label": m, "failures": 0, "first": float(t)})
        row["failures"] += 1
        row["first"] = min(row["first"], float(t))
    return _json_safe(sorted(rows.values(), key=lambda r: (-r["failures"], r["first"])))


def clean_projection_settings(fef, bc=None) -> tuple[dict, list]:
    """``(fef, bc)`` validated: ``fef`` a {mode: factor in [0, 1]} dict,
    ``bc`` a list of mode labels, no mode in both."""
    if fef is None:
        fef = {}
    if not isinstance(fef, dict):
        raise FitError("fef must map each BD mode to its fix-effectiveness factor, e.g. {\"seal\": 0.7}.")
    clean_fef = {}
    for label, value in fef.items():
        key = _mode_label(label)
        if key is None:
            raise FitError("A BD mode needs a label.")
        try:
            d = float(value)
        except (TypeError, ValueError):
            raise FitError(f"Mode “{key}”: the fix-effectiveness factor must be a number from 0 to 1.")
        if not (np.isfinite(d) and 0.0 <= d <= 1.0):
            raise FitError(f"Mode “{key}”: the fix-effectiveness factor must be from 0 to 1 (got {value}).")
        clean_fef[key] = d
    if bc is None:
        bc = []
    if isinstance(bc, str) or not isinstance(bc, (list, tuple)):
        raise FitError("bc must be a list of the modes fixed during the test.")
    clean_bc = list(dict.fromkeys(k for k in (_mode_label(b) for b in bc) if k is not None))
    both = sorted(set(clean_fef) & set(clean_bc))
    if both:
        raise FitError(f"A mode is either fixed during the test (BC) or after it (BD), not both: {', '.join(both)}.")
    return clean_fef, clean_bc


def growth_projection(df: pd.DataFrame, mapping: dict, fef, bc=None, test_end=None, unit: str = "") -> dict:
    """The AMSAA-Crow growth projection of a test's event data: the
    demonstrated, projected and growth-potential intensity and MTBF (of one
    system), each failure mode's share, and h(T)."""
    fef, bc = clean_projection_settings(fef, bc)
    ins = projection_inputs(df, mapping, test_end=test_end)
    return projection_payload(ins, fef, bc, unit=unit, test_end=test_end)


def projection_payload(ins: dict, fef: dict, bc: list, unit: str = "", test_end=None) -> dict:
    """:func:`growth_projection` from ready inputs ``{x, i, c, modes}``."""
    events = np.asarray(ins["c"]) == 0
    missing = int(sum(1 for m, e in zip(ins["modes"], events) if e and m is None))
    if missing:
        raise FitError(f"{missing} failure{'s have' if missing != 1 else ' has'} no failure mode. Every failure "
                       "needs one to project growth.")
    seen = set(m for m, e in zip(ins["modes"], events) if e)
    unknown = sorted((set(fef) | set(bc)) - seen)
    if unknown:
        raise FitError(f"No failures of {', '.join(map(repr, unknown))} in the data: only modes seen in the test "
                       "can be classified.")
    try:
        with warnings.catch_warnings(), np.errstate(all="ignore"):
            warnings.simplefilter("ignore", RuntimeWarning)
            gp = CrowAMSAA.projection(ins["x"], np.asarray(ins["modes"], dtype=object), fef,
                                      i=ins["i"], c=ins["c"], bc=bc or None)
    except ValueError as exc:
        msg = str(exc)
        if "time-terminated" in msg:
            msg = ("A growth projection needs a time-terminated test: every system run from 0 to the same end "
                   "of test T. Give that time (the end of the test), or map each system's observation window "
                   "(tr) or its end-of-test row (c = 1) — all at the same time.")
        raise FitError(msg) from exc

    total = gp.systems * gp.T
    kind_of = {m: ("BD" if m in fef else "BC" if m in bc else "A") for m in seen}
    counts: dict = {}
    first: dict = {}
    for t, m in zip(np.asarray(ins["x"])[events], np.asarray(ins["modes"], dtype=object)[events]):
        counts[m] = counts.get(m, 0) + 1
        first[m] = min(first.get(m, np.inf), float(t))
    table = gp.modes
    modes = []
    for m in seen:
        row = {"label": m, "kind": kind_of[m], "failures": counts[m], "first": first[m],
               "intensity": counts[m] / total}
        if m in fef:
            row["fef"] = float(table.loc[m, "fef"])
            row["projected"] = float(table.loc[m, "projected"])
            row["removed"] = row["intensity"] - row["projected"]
        modes.append(row)
    modes.sort(key=lambda r: (-r["failures"], r["first"], str(r["label"])))

    bd_total = float(table["intensity"].sum()) if len(table) else 0.0
    unseen = gp.projected_intensity - gp.growth_potential_intensity
    return _json_safe({
        "T": gp.T,
        "systems": gp.systems,
        "total_time": total,
        "unit": (unit or "").strip(),
        "failures": dict(gp.failures),
        "n_bd_modes": int(len(table)),
        "demonstrated": {"intensity": gp.demonstrated_intensity, "mtbf": gp.demonstrated_mtbf},
        "projected": {"intensity": gp.projected_intensity, "mtbf": gp.projected_mtbf},
        "growth_potential": {"intensity": gp.growth_potential_intensity, "mtbf": gp.growth_potential_mtbf},
        "demonstrated_basis": "crow_amsaa" if gp.failures.get("BC") else "average",
        "mean_fef": gp.mean_fef,
        "beta_bd": gp.beta,
        "new_mode_intensity": gp.new_mode_intensity,
        # The projected intensity's parts: what isn't fixed (A and BC modes, as
        # demonstrated), what the BD fixes leave, and the new BD modes still
        # expected (mean FEF × h(T)).
        "components": {
            "unfixed": gp.demonstrated_intensity - bd_total,
            "bd_residual": float(table["projected"].sum()) if len(table) else 0.0,
            "unseen_bd": unseen,
        },
        "modes": modes,
        "fef": fef,
        "bc": bc,
        "test_end": float(test_end) if test_end is not None else None,
        "model": {"alpha": float(gp.model.params[0]), "beta": float(gp.model.params[1])},
    })


# ---------------------------------------------------------------------------
# A system's next failure under a Poisson-process model (#235)
# ---------------------------------------------------------------------------

def next_failure(model, age, within=None, quantiles=None) -> dict:
    """The next failure of a repairable system at ``age`` under a Poisson-
    process (minimal repair) model, in closed form: the chance it fails
    within ``t`` more is ``1 − exp(−(Λ(age + t) − Λ(age)))``, the ``q``
    quantile of the time to it ``Λ⁻¹(Λ(age) − ln(1 − q)) − age``, and its mean
    ``∫ exp(−(Λ(age + t) − Λ(age))) dt``."""
    from scipy.integrate import quad

    age = float(age)
    if not np.isfinite(age) or age < 0:
        raise FitError("The age must be zero or a positive time.")
    within = [float(w) for w in (within or [])]
    if any(not np.isfinite(w) or w <= 0 for w in within):
        raise FitError("Each 'within' time must be a positive time ahead.")
    quantiles = [0.1, 0.5, 0.9] if quantiles is None else [float(q) for q in quantiles]
    if any(not 0 < q < 1 for q in quantiles):
        raise FitError("Quantiles must be between 0 and 1 (e.g. 0.5 for the median).")
    model = _as_cif_model(model)
    with np.errstate(all="ignore"):
        lam_a = _cif_at(model, age)
        rocof = float(np.asarray(model.iif(np.array([age])), dtype=float).ravel()[0]) if age > 0 else None

        def ahead(t):
            return _cif_at(model, age + t) - lam_a

        rows = []
        for w in within:
            mu = ahead(w)
            rows.append({"time_ahead": w, "prob_failure": float(-np.expm1(-mu)), "expected_failures": mu})
        qs = []
        targets = np.array([lam_a - np.log1p(-q) for q in quantiles])
        times = np.asarray(model.inv_cif(targets), dtype=float) - age
        for q, t in zip(quantiles, times):
            qs.append({"q": q, "time_ahead": float(t), "age_at": float(t + age)})
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            mean, _ = quad(lambda t: np.exp(-ahead(t)), 0.0, np.inf, limit=200)
    return _json_safe({
        "age": age,
        "rocof": rocof,
        "instantaneous_mtbf": (1.0 / rocof) if rocof else None,
        "mean_time_to_next_failure": float(mean),
        "quantiles": qs,
        "within": rows,
        "assumption": ("Minimal repair: each failure is repaired to the state just before it, so the system's "
                       "failures follow the model's Poisson process from its current age."),
    })


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
