"""Recurrent-event (repairable-system) analysis.

Where the rest of Reliafy models *time to a single failure*, this models a
*sequence* of failures/repairs per system — the repairable-systems question:
is the system getting better or worse, and how often will it fail?

Wraps :mod:`surpyval.recurrent`. From long-format event data (one row per
event: which system, at what time) plus each system's observation window, we
fit a nonparametric **MCF** (mean cumulative function, with confidence bounds),
a parametric model (the **Crow-AMSAA** power-law NHPP by default — the
reliability-growth model — or Duane, HPP or the Cox-Lewis log-linear NHPP),
two **trend tests** (Laplace and MIL-HDBK-189C) and a **goodness-of-fit** test
(Cramér-von Mises) — and derive the ROCOF / MTBF at the end of observation with
confidence bounds, the demonstrated MTBF, and a growth verdict from the growth
parameter's 95% interval (#81).

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
from backend.services.method_labels import hides_solver_names, note_fit
from backend.units import canonical_unit
from surpyval.recurrent import CoxLewis, CrowAMSAA, Duane, HPP, NonParametricCounting

# Parametric recurrence models offered: the power-law (Crow-AMSAA, Duane) and
# constant (HPP) intensities, and the Cox-Lewis log-linear intensity
# exp(alpha + beta·t) as an alternative trend shape.
MODELS = {
    "crow_amsaa": {"name": "Crow-AMSAA (NHPP)", "fitter": CrowAMSAA},
    "duane": {"name": "Duane", "fitter": Duane},
    "hpp": {"name": "Homogeneous Poisson (HPP)", "fitter": HPP},
    "cox_lewis": {"name": "Cox-Lewis (log-linear NHPP)", "fitter": CoxLewis},
}
MODEL_CHOICES = list(MODELS.keys())
# The models the (alpha = scale, beta = shape) parameter form builds: the power laws.
FROM_PARAMS_MODELS = ("crow_amsaa", "duane")

# Each model's growth parameter and its no-trend value. The growth verdict is
# "deteriorating" when the parameter's 95% interval lies wholly above that
# value, "improving" when wholly below, else "stable" (#81). Duane's shape is
# SurPyval's ``alpha``; Cox-Lewis's ``beta`` is a log-linear slope (0 = flat).
_GROWTH_PARAM = {
    "crow_amsaa": {"param": "beta", "symbol": "β", "what": "growth shape", "no_trend": 1.0},
    "duane": {"param": "alpha", "symbol": "β", "what": "growth shape", "no_trend": 1.0},
    "cox_lewis": {"param": "beta", "symbol": "β", "what": "log-linear slope", "no_trend": 0.0},
}
CI_LEVEL = 0.95            # parameter, ROCOF and MTBF intervals
DEMONSTRATED_LEVEL = 0.90  # the one-sided demonstrated-MTBF bound (MIL-HDBK-189C's usual level)
_CVM_BUDGET = 400_000      # events x bootstrap replicates for the Cramér-von Mises p-value (about 4 s)
_CVM_MAX_BOOT, _CVM_MIN_BOOT = 200, 40
_RESIDUAL_ROWS = 50        # systems kept in the per-system residual table, most excess failures first

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


def _is_renewal(model) -> bool:
    """An imperfect-repair (renewal / virtual-age) model (#65)."""
    return type(model).__name__ == "RenewalModel"


def _is_regression(model) -> bool:
    """A proportional-intensity model: its intensity needs covariates (#65)."""
    return getattr(model, "coeffs", None) is not None and hasattr(model, "feature_names")


def live_family(model) -> str:
    return "renewal" if _is_renewal(model) else "regression" if _is_regression(model) else "nhpp"


MINIMAL_REPAIR_ONLY = ("{what} needs a minimal-repair model (Crow-AMSAA, Duane, HPP or Cox-Lewis): {why}")
_FAMILY_WHY = {
    "renewal": "this imperfect-repair model has no closed-form failure intensity.",
    "regression": "this model's failure rate depends on each system's covariates.",
}


def serialize_live(cache_id: str) -> dict | None:
    """Serialise a stored live recurrent model so it can be persisted and
    rehydrated without re-fitting. ``None`` if there's nothing to serialise,
    or for an imperfect-repair model: its predictions start from each
    system's history, which a restored model doesn't carry, so it is re-fitted
    (quickly) instead."""
    m = _STORE.get(cache_id)
    if m is None or not hasattr(m, "to_dict") or _is_renewal(m):
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


def all_models() -> list[dict]:
    """Every recurrent model the app offers, by family (#65): the minimal-
    repair Poisson processes, intensity regression and imperfect repair."""
    from backend import recurrent_models as extra

    out = [{"id": k, "name": v["name"], "family": "nhpp"} for k, v in MODELS.items()]
    out += [{"id": k, "name": v["name"], "short": v["short"], "family": v["family"], "desc": v["desc"]}
            for k, v in extra.EXTRA_MODELS.items()]
    return out


def fit_spec(df: pd.DataFrame, spec: dict, gof_test: bool = True) -> tuple[dict, str]:
    """:func:`fit` from a saved model's spec (mapping, model, unit, options
    and observation windows)."""
    return fit(df, spec.get("mapping", {}), model_id=spec.get("model_id", "crow_amsaa"),
               unit=spec.get("unit", ""), gof_test=gof_test, options=spec.get("options"),
               windows=spec.get("windows"))


@hides_solver_names
def fit(df: pd.DataFrame, mapping: dict, model_id: str = "crow_amsaa", unit: str = "",
        gof_test: bool = True, options: dict | None = None, windows=None) -> tuple[dict, str]:
    """Fit the recurrent model and build the JSON-safe results payload.

    Returns ``(payload, cache_id)`` addressing the live parametric model.
    ``gof_test=False`` skips the (bootstrapped) Cramér-von Mises test, for a
    re-fit that only wants the live model. ``options`` are the model's own
    settings (a baseline, a memory) and ``windows`` each system's observation
    windows, entered by hand ({system: [[start, end], ...]} or text); window
    columns come in the mapping (``ws`` / ``we``). A cause column (``mode``)
    adds the MCF of each cause (#65).
    """
    from backend import recurrent_models as extra

    if model_id in extra.EXTRA_MODELS:
        windows = extra.windows_from(df, mapping, windows) if (windows or mapping.get("ws")) else None
        payload, live = extra.fit(df, mapping, model_id, unit, gof_test=gof_test, options=options,
                                  windows=windows)
        _add_marks(payload, df, mapping)
        return payload, store_live(live)
    if model_id not in MODELS:
        choices = MODEL_CHOICES + list(extra.EXTRA_MODELS)
        raise FitError(f"Unknown model '{model_id}'. Choose one of: {', '.join(choices)}.")
    inputs = build_inputs(df, mapping)
    gaps = None
    if windows or mapping.get("ws"):
        spans = extra.windows_from(df, mapping, windows)
        if spans:
            inputs, gaps = extra.apply_windows(inputs, spans)
    # The nonparametric MCF estimator doesn't support right truncation (tr) —
    # the parametric fitter does. Give each what it accepts.
    np_inputs = {k: v for k, v in inputs.items() if k != "tr"}

    try:
        with np.errstate(all="ignore"):
            np_model = note_fit(NonParametricCounting.fit(**np_inputs))
            para = note_fit(_fit_nhpp(model_id, inputs))
    except FitError:
        raise
    except Exception as exc:  # noqa: BLE001 - surface SurPyval's message
        raise FitError(extra.plain_error(exc)) from exc

    payload = _build_payload(np_model, para, inputs, model_id, unit, gof_test=gof_test)
    if gaps:
        payload["windows"] = gaps
    _add_marks(payload, df, mapping, inputs=None if gaps else inputs)
    return payload, store_live(para)


def _fit_nhpp(model_id: str, inputs: dict):
    """Fit a Poisson-process model. A Crow-AMSAA search that doesn't reach a
    verified maximum (it can wander off from its default start when systems
    are watched for different lengths) is started again from the same fit to
    the times rescaled to the unit interval, whose scale maps back exactly."""
    fitter = MODELS[model_id]["fitter"]
    if model_id != "crow_amsaa":
        return fitter.fit(**inputs)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", UserWarning)  # an unverified maximum is retried below
        para = fitter.fit(**inputs)
    if getattr(para, "maximum", "verified") == "verified":
        return para
    scale = float(np.max(inputs["x"])) if np.size(inputs["x"]) else 0.0
    if not np.isfinite(scale) or scale <= 0:
        return para
    scaled = dict(inputs, x=np.asarray(inputs["x"], dtype=float) / scale)
    for key in ("tl", "tr"):
        if inputs.get(key) is not None:
            scaled[key] = np.asarray(inputs[key], dtype=float) / scale
    if inputs.get("windows"):
        scaled["windows"] = {k: [(a / scale, b / scale) for a, b in v] for k, v in inputs["windows"].items()}
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            unit_fit = fitter.fit(**scaled)
        alpha, beta = (float(v) for v in np.asarray(unit_fit.params, dtype=float))
        if not (np.isfinite(alpha) and np.isfinite(beta)):
            return para
        retry = fitter.fit(**inputs, init=[alpha * scale, beta])
    except Exception:  # noqa: BLE001 - keep the first fit
        return para
    return retry if -retry.neg_ll() >= -para.neg_ll() or not np.all(np.isfinite(para.params)) else para


def _add_marks(payload: dict, df: pd.DataFrame, mapping: dict, inputs: dict | None = None) -> None:
    """With a cause (failure-mode) column: the failure modes a growth
    projection classifies (#232), and the MCF of each cause (#65). Not for a
    gapped fit (the by-cause models take no windows)."""
    from backend import recurrent_models as extra

    if not mapping.get("mode"):
        return
    try:
        payload["failure_modes"] = failure_modes(df, mapping)
    except FitError:
        payload["failure_modes"] = None
    if payload.get("windows"):
        payload["by_cause"] = {"causes": [], "reason": "Failures by cause aren't available with observation "
                                                       "gaps (windows) yet."}
        return
    try:
        ins = build_inputs(df, mapping) if inputs is None else inputs
        keep = extra.keep_mask(df, mapping)
        payload["by_cause"] = _json_safe(extra.by_cause(ins, extra.cause_labels(df, mapping, keep),
                                                        payload.get("unit", "")))
    except FitError as exc:
        payload["by_cause"] = {"causes": [], "reason": str(exc)}


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
    if p.size < 2 or model_id == "cox_lewis":  # HPP has no shape; Cox-Lewis isn't a power law
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


def _build_payload(np_model, para, inputs: dict, model_id: str, unit: str, gof_test: bool = True) -> dict:
    x, i = inputs["x"], inputs["i"]
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

    # The end of observation: the last event or end-of-test row, or the
    # latest observation window. The current ROCOF / MTBF and their bounds
    # are reported there — for a growth test, the demonstrated MTBF.
    t_end = end_of_observation(inputs)
    beta, _ = _power_law(model_id, params_arr)
    rocof, mtbf = _rates_at(para, t_end)

    param_names = _param_names(model_id, params_arr.size)
    cis = param_intervals(model_id, para)
    growth, growth_basis = growth_verdict(model_id, params_arr, cis)
    tests = trend_tests(para)
    payload = {
        "kind": "recurrent",
        "family": "nhpp",
        "unit": canonical_unit(unit),
        "n_systems": n_systems,
        "n_events": n_events,
        "model": {"id": model_id, "name": MODELS[model_id]["name"]},
        "params": [{"name": n, "value": float(v), **({"ci": cis[n]} if n in cis else {})}
                   for n, v in zip(param_names, params_arr)],
        "beta": beta,
        "beta_ci": _shape_ci(model_id, cis),
        "growth": growth,
        "growth_basis": growth_basis,
        "end_of_observation": t_end,
        "rocof": rocof,
        "mtbf": mtbf,
        **rate_bounds(model_id, para, t_end),
        "mcf": {
            "observed": {"x": nx.tolist(), "mcf": mcf_obs.tolist(), "lower": lower, "upper": upper},
            "fitted": {"x": grid.tolist(), "mcf": fitted.tolist()},
        },
        # ``trend`` (Laplace) is kept for older readers; ``trend_tests`` has both.
        "trend": next((t for t in tests if t["id"] == "laplace"), None),
        "trend_tests": tests,
        "gof": _gof(para),
        "gof_test": cramer_von_mises(para, n_events) if gof_test else None,
        "system_residuals": system_residuals(para) if n_systems > 1 else None,
    }
    return _json_safe(payload)


def end_of_observation(inputs: dict) -> float:
    """The latest time any system was observed: its last event (or end-of-
    test row), or its observation window (``tr``) when that's later."""
    t = float(np.max(inputs["x"])) if np.size(inputs["x"]) else 0.0
    tr = inputs.get("tr")
    if tr is not None and np.size(tr):
        t = max(t, float(np.nanmax(tr)))
    for spans in (inputs.get("windows") or {}).values():  # a gapped fit (#65)
        t = max([t, *(float(b) for _, b in spans)])
    return t


def _first(values) -> float | None:
    v = float(np.asarray(values, dtype=float).ravel()[0])
    return v if np.isfinite(v) else None


def _rates_at(model, t: float) -> tuple:
    """``(rocof, mtbf)``: the fitted intensity at ``t`` and its reciprocal,
    the instantaneous MTBF (``None`` where not finite and positive)."""
    if not t or t <= 0:
        return None, None
    try:
        with np.errstate(all="ignore"):
            rocof = _first(model.iif(np.array([float(t)])))
    except Exception:  # noqa: BLE001 - no intensity: no rates
        return None, None
    if rocof is None or rocof <= 0:
        return rocof, None
    return rocof, 1.0 / rocof


def _shape_ci(model_id: str, cis: dict) -> list | None:
    """The 95% interval on the power-law growth shape β (Crow-AMSAA's
    ``beta``, Duane's ``alpha``); None for HPP and Cox-Lewis."""
    if model_id not in ("crow_amsaa", "duane"):
        return None
    return cis.get(_GROWTH_PARAM[model_id]["param"])


def growth_verdict(model_id: str, params, cis: dict | None = None) -> tuple:
    """``(growth, basis)``: improving / stable / deteriorating, and why.

    With the growth parameter's 95% interval (a fit to data), the verdict is
    whether that interval excludes the no-trend value (β = 1 for a power law,
    a slope of 0 for Cox-Lewis): wholly above is deteriorating, wholly below
    improving, and an interval that includes it is "stable" — the data don't
    show a trend. A model built from known parameters has no interval, so the
    value itself decides. ``(None, None)`` for HPP (no trend by construction)."""
    g = _GROWTH_PARAM.get(model_id)
    if g is None:
        return None, None
    names = _param_names(model_id, len(params))
    if g["param"] not in names:
        return None, None
    value = float(params[names.index(g["param"])])
    null = g["no_trend"]
    ci = (cis or {}).get(g["param"])
    basis = {"parameter": g["param"], "symbol": g["symbol"], "what": g["what"], "estimate": value,
             "no_trend": null}
    if ci:
        lo, hi = float(ci[0]), float(ci[1])
        growth = "deteriorating" if lo > null else "improving" if hi < null else "stable"
        return growth, {**basis, "ci": [lo, hi], "level": CI_LEVEL, "rule": "interval"}
    if not np.isfinite(value):
        return None, None
    growth = "deteriorating" if value > null else "improving" if value < null else "stable"
    return growth, {**basis, "ci": None, "level": None, "rule": "value"}


def rate_bounds(model_id: str, model, t_end: float) -> dict:
    """Confidence bounds at the end of observation (#81): the 95% intervals on
    the ROCOF and the instantaneous MTBF, and the demonstrated MTBF's one-
    sided 90% lower bound ("demonstrated MTBF ≥ X at 90%").

    A Crow-AMSAA fit to a time-terminated test (every system observed from 0
    to the same end) or a failure-terminated test of one system gets Crow's
    exact bounds, as MIL-HDBK-189C tabulates; any other data, or another
    model, gets Wald (delta-method) bounds. ``bounds_method`` says which."""
    out = {"rocof_ci": None, "mtbf_ci": None, "demonstrated_mtbf": None, "bounds_method": None}
    if not t_end or t_end <= 0:
        return out
    t = np.array([float(t_end)])
    methods = ("crow", "wald") if model_id == "crow_amsaa" else ("wald",)
    for method in methods:
        try:
            with warnings.catch_warnings(), np.errstate(all="ignore"):
                warnings.simplefilter("ignore")
                mtbf_ci = np.asarray(model.mtbf_cb(t, alpha_ci=1 - CI_LEVEL, method=method), dtype=float).ravel()
                rocof_ci = np.asarray(model.iif_cb(t, alpha_ci=1 - CI_LEVEL, method=method), dtype=float).ravel()
                lower = _first(model.mtbf_cb(t, alpha_ci=1 - DEMONSTRATED_LEVEL, bound="lower", method=method))
        except Exception:  # noqa: BLE001 - Crow's bounds don't apply here (or no likelihood): next method
            continue
        point = _rates_at(model, t_end)[1]
        return {
            "rocof_ci": [float(rocof_ci[0]), float(rocof_ci[1])],
            "mtbf_ci": [float(mtbf_ci[0]), float(mtbf_ci[1])],
            "demonstrated_mtbf": {"at": float(t_end), "mtbf": point, "lower": lower,
                                  "confidence": DEMONSTRATED_LEVEL, "method": method},
            "bounds_method": method,
        }
    return out


_TREND_TESTS = (("laplace", "Laplace"), ("mil_hdbk_189c", "MIL-HDBK-189C"))


def trend_tests(model) -> list:
    """The Laplace and MIL-HDBK-189C trend tests (null: a homogeneous Poisson
    process) of the data the model was fitted to — each system tested on its
    own observation window, from its entry (``tl``) to its close (#81).
    ``trend`` is the trend concluded at 5% ("no trend" when not
    significant); ``direction`` the sign of the statistic either way."""
    out = []
    for test_id, label in _TREND_TESTS:
        try:
            with warnings.catch_warnings(), np.errstate(all="ignore"):
                warnings.simplefilter("ignore")
                tt = model.trend_test(test_id)
        except Exception:  # noqa: BLE001 - no data (built from parameters) or too few events
            continue
        p = float(tt.p_value)
        trend = getattr(tt, "trend", None)
        row = {
            "id": test_id,
            "test": label,
            "statistic": float(tt.statistic),
            "p_value": p,
            "trend": "no trend" if trend in (None, "none") else trend,
            "direction": getattr(tt, "direction", None),
            "significant": bool(p < 0.05),
        }
        if getattr(tt, "dof", None) is not None:
            row["dof"] = int(tt.dof)
        out.append(row)
    return out


def cramer_von_mises(model, n_events: int) -> dict | None:
    """The Cramér-von Mises goodness-of-fit test of the fitted intensity, its
    p-value by parametric bootstrap (a fixed seed, so a refit reads the
    same). The replicates shrink as the data grow, to keep it to a few
    seconds; past that it's skipped with a reason. None with no data."""
    n_boot = min(_CVM_MAX_BOOT, _CVM_BUDGET // max(int(n_events), 1))
    base = {"test": "Cramér-von Mises", "null": "the events follow the fitted intensity"}
    if n_boot < _CVM_MIN_BOOT:
        return {**base, "statistic": None, "p_value": None, "n_boot": 0, "adequate": None,
                "reason": f"Skipped: with {n_events:,} events the bootstrap p-value would take too long."}
    try:
        with warnings.catch_warnings(), np.errstate(all="ignore"):
            warnings.simplefilter("ignore")
            g = model.cramer_von_mises(n_boot=n_boot, random_state=0)
    except Exception:  # noqa: BLE001 - no data or likelihood (built from parameters, restored)
        return None
    p = float(g.p_value)
    return {**base, "statistic": float(g.statistic), "p_value": p, "n_boot": int(g.n_boot),
            "adequate": bool(p >= 0.05)}


def system_residuals(model) -> list | None:
    """Each system's failures against the model's expectation over its own
    observation window — SurPyval's martingale residuals (observed minus
    expected) — most excess failures first, capped at the top 50: the
    systems failing more (or less) than the fleet model explains."""
    try:
        with warnings.catch_warnings(), np.errstate(all="ignore"):
            warnings.simplefilter("ignore")
            res = np.asarray(model.residuals("martingale"), dtype=float)
        data = model.data
        items = list(data.items)
    except Exception:  # noqa: BLE001 - no data
        return None
    c = np.asarray(data.c)
    n = np.asarray(data.n) if getattr(data, "n", None) is not None else np.ones(len(c))
    ids = np.asarray(data.i)
    rows = []
    for item, r in zip(items, res):
        observed = float(n[(ids == item) & (c == 0)].sum())
        rows.append({"system": str(item), "failures": observed, "expected": observed - float(r),
                     "excess": float(r)})
    rows.sort(key=lambda row: -row["excess"])
    return rows[:_RESIDUAL_ROWS]


def param_intervals(model_id: str, model) -> dict:
    """``{name: [lower, upper]}``: the 95% confidence interval on each of a
    fit's parameters (SurPyval's Wald bounds from the observed information,
    kept inside each parameter's support). Only a maximum-likelihood fit to
    data has them: {} for a model built from its parameters or one restored
    without its data."""
    if model_id not in MODELS:
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


def fit_from_params(model_id: str, params: list, horizon: float, unit: str = "") -> tuple:
    """Build a recurrent model from known parameters — no data. ``params`` is an
    ordered list of ``{name, value}`` (Crow-AMSAA / Duane: alpha, beta).
    ``horizon`` sets the time range for the fitted MCF curve and the point at
    which ROCOF/MTBF are reported. Returns ``(payload, cache_id)``. The observed
    MCF step, confidence band, and trend test need data, so are omitted."""
    if model_id not in MODELS:
        raise FitError(f"Unknown model '{model_id}'. Choose one of: {', '.join(MODEL_CHOICES)}.")
    fitter = MODELS[model_id]["fitter"]
    if model_id not in FROM_PARAMS_MODELS or not hasattr(fitter, "from_params"):
        raise FitError(f"“{MODELS[model_id]['name']}” can't be built from parameters: fit it to event data.")
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
    beta, _ = _power_law(model_id, values)
    # The ROCOF/MTBF at the horizon. Known parameters have no interval, so
    # the growth verdict is β against 1 itself.
    rocof, mtbf = _rates_at(para, horizon)
    growth, growth_basis = growth_verdict(model_id, values)
    payload = {
        "kind": "recurrent",
        "unit": canonical_unit(unit),
        "n_systems": None,
        "n_events": None,
        "model": {"id": model_id, "name": MODELS[model_id]["name"]},
        "params": [{"name": n, "value": float(v)} for n, v in zip(_param_names(model_id, len(values)), values)],
        "beta": beta,
        "beta_ci": None,
        "growth": growth,
        "growth_basis": growth_basis,
        "rocof": rocof,
        "mtbf": mtbf,
        "mcf": {"observed": None, "fitted": {"x": grid.tolist(), "mcf": fitted.tolist()}},
        "trend": None,
        "trend_tests": [],  # trend tests, bounds and goodness of fit need event data
        "gof": [],  # no likelihood for a params-built model
        "from_params": True,
        "horizon": horizon,
    }
    return _json_safe(payload)


def predict(model, horizon: float) -> dict:
    """Expected cumulative failures by ``horizon`` from a fitted model (an
    imperfect-repair model's by simulation, with a fixed seed)."""
    if _is_regression(model):
        raise FitError("This model's failure rate depends on each system's covariates: read the expected "
                       "failures off its chart for the average system, or per level.")
    with np.errstate(all="ignore"):
        x = np.array([float(horizon)])
        values = model.mcf(x, random_state=0) if _is_renewal(model) else model.mcf(x)
        expected = float(np.asarray(values, dtype=float).ravel()[0])
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


_SHORT_NAMES = {"crow_amsaa": "Crow-AMSAA", "duane": "Duane", "hpp": "HPP", "cox_lewis": "Cox-Lewis"}


def projection_basis(saved_model: str | None = None) -> dict:
    """What a growth projection was computed with (#232). The projection is
    always a Crow-AMSAA fit to the event data; when it comes from a saved
    model of another kind (Duane, HPP) it says so, plainly:
    ``{projected_with, saved_model, basis_note}``."""
    out = {"projected_with": "crow_amsaa", "saved_model": saved_model or None, "basis_note": None}
    if saved_model and saved_model != "crow_amsaa":
        name = _SHORT_NAMES.get(saved_model) or MODELS.get(saved_model, {}).get("name") or str(saved_model)
        out["basis_note"] = f"Projected with a Crow-AMSAA fit to the same data (your saved model is {name})."
    return out


def growth_projection(df: pd.DataFrame, mapping: dict, fef, bc=None, test_end=None, unit: str = "",
                      saved_model: str | None = None) -> dict:
    """The AMSAA-Crow growth projection of a test's event data: the
    demonstrated, projected and growth-potential intensity and MTBF (of one
    system), each failure mode's share, and h(T). ``saved_model`` is the
    kind of the saved model the data came from, if any: a projection from a
    Duane or HPP model is still a Crow-AMSAA fit, and says so."""
    fef, bc = clean_projection_settings(fef, bc)
    ins = projection_inputs(df, mapping, test_end=test_end)
    return {**projection_payload(ins, fef, bc, unit=unit, test_end=test_end), **projection_basis(saved_model)}


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
        elif "BC modes" in msg and "at least 2 failures" in msg:
            # SurPyval 0.24 (#730): with BC modes the demonstrated MTBF uses
            # the bias-corrected shape, (N - 1) / N of the estimate.
            msg = ("With modes fixed during the test (BC), the demonstrated MTBF needs at least 2 failures; "
                   "the test has 1. Classify the mode as BD or A, or add the test's other failures.")
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
        "unit": canonical_unit(unit),
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

    if _is_renewal(model):
        from backend import recurrent_models as extra

        return extra.renewal_next_failure(model, age, within=within, quantiles=quantiles)
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
    fam = live_family(model_or_params)
    if fam != "nhpp" and not isinstance(model_or_params, dict):
        raise FitError(MINIMAL_REPAIR_ONLY.format(what="This", why=_FAMILY_WHY[fam]))
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


def _is_log_linear(model) -> bool:
    """A Cox-Lewis (log-linear intensity) model."""
    return getattr(getattr(model, "dist", None), "name", None) == "Cox-Lewis"


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

    if _is_log_linear(model):
        # Cox-Lewis, λ(t) = exp(α + β·t): no constant shape. Its slope β decides —
        # rising intensity (β > 0) always has a finite optimum.
        slope = float(np.asarray(model.params, dtype=float)[1])
        base = {**base, "shape": None, "log_linear_slope": slope}
        if not np.isfinite(slope):
            return _none("The model's slope can't be evaluated, so no overhaul interval can be computed.", None)
        if slope < -1e-12:
            return _none(
                f"The failure intensity is decreasing (log-linear slope β = {slope:.3g} < 0): failures get rarer "
                "with age, so an overhaul never pays — the cost rate keeps falling the longer you run between "
                "overhauls.", 0.0)
        if slope <= 1e-12:
            return _none(
                "The failure intensity is constant (slope β = 0): an overhaul doesn't lower the failure rate, so it "
                "only adds cost. Repair on failure; don't overhaul.", cr * _cif_at(model, t_ref) / t_ref)
    elif not np.isfinite(shape):
        return _none("The model's cumulative intensity can't be evaluated, so no overhaul interval can be computed.", None)
    elif shape < 1.0 - 1e-6:
        return _none(
            f"The failure intensity is decreasing (β = {shape:.3g} < 1): failures get rarer with age, so an "
            "overhaul never pays — the cost rate keeps falling the longer you run between overhauls.", 0.0)
    elif shape <= 1.0 + 1e-6:
        return _none(
            "The failure intensity is constant (β = 1, e.g. HPP): an overhaul doesn't lower the failure rate, "
            "so it only adds cost. Repair on failure; don't overhaul.", cr * _cif_at(model, t_ref) / t_ref)

    rep = Repairable(model)
    rep.set_repair_and_overhaul_costs(cr, co)
    with np.errstate(all="ignore"):  # the search can overflow a log-linear Λ far out
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
