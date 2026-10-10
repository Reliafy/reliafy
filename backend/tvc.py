"""Regression models with covariates that change over time (#60).

A pump's load, a motor's duty or a seal's temperature is rarely fixed for
its whole life: it steps from one value to another. SurPyval fits those
step-function (time-varying) covariates for every regression family
Reliafy offers — parametric proportional hazards, accelerated failure time,
proportional odds, additive hazards, and semi-parametric Cox — from either
of two layouts:

* **interval rows** — one row per stretch of an item's life at one
  covariate value: ``item, start, stop, status, covariates`` (the counting
  process / start-stop layout). Mapped as ``i``, ``xl`` (start), ``xr``
  (stop) and ``c``; each row's status says whether that interval ended in a
  failure (0) or not (1).
* **timeline rows** — one row per change: ``item, time, status,
  covariates``, a value taking effect at its time and holding until the
  item's next row, whose last row is the failure or removal. Mapped as
  ``i``, ``x`` and ``c``; only the last row's status counts.

A mapping with an item column (``i``) is what makes a fit time-varying, so a
saved model's spec re-fits the same way with no extra flag. Evaluation runs
along a covariate *schedule* (change-points the user enters): reliability
with ``sf_tvc``, cumulative hazard with ``Hf_tvc``, the mean life with
``mean_tvc`` and confidence bounds with ``cb_tvc`` (parametric models only:
SurPyval has no bounds for Cox along a path). Everything statistical is
SurPyval's; this module maps columns, shapes payloads and words readings.
"""

from __future__ import annotations

import math
import re
import warnings
from typing import Optional

import numpy as np
import pandas as pd

from backend import param_intervals

LAYOUTS = ("intervals", "timeline")
# Functions along a schedule: SurPyval gives survival and cumulative hazard
# along a path (and the failure probability from them), not the hazard rate
# or density.
FUNCTIONS = [
    {"id": "sf", "label": "Reliability R(t)"},
    {"id": "ff", "label": "Probability of failure F(t)"},
    {"id": "Hf", "label": "Cumulative hazard H(t)"},
]
_FUNCTION_IDS = {f["id"] for f in FUNCTIONS}
_BOUNDS = {"two-sided", "lower", "upper"}
MAX_CHANGES = 50

VALIDATION_REASON = (
    "Not available for covariates that change over time: these scores rank units by one fixed set of "
    "covariate values each, and here each unit's covariates follow a path.")
METRICS_LABEL = ("With each covariate held at its average over the data's rows (a categorical one at its "
                 "most common level) for the whole life — use the calculator's schedule for a changing one.")


def is_tvc(mapping: Optional[dict]) -> bool:
    """A mapping with an item column fits covariates that change over time."""
    return bool((mapping or {}).get("i"))


def layout_of(mapping: dict) -> str:
    return "intervals" if (mapping.get("xl") or mapping.get("xr")) else "timeline"


def _check(mapping: dict, covariates, formula, model_name: str) -> str:
    """The layout, or FitError naming what is missing, in plain words."""
    from backend.fitting import FitError

    if mapping.get("tl") or mapping.get("tr"):
        raise FitError(
            "Truncation columns can't be combined with covariates that change over time: an item whose "
            "first row starts after 0 is already treated as observed from that time.")
    if mapping.get("xl") or mapping.get("xr"):
        if not (mapping.get("xl") and mapping.get("xr")) or mapping.get("x"):
            raise FitError("Interval rows need both the start and the stop of each row, and no single time "
                           "column.")
        layout = "intervals"
    elif mapping.get("x"):
        layout = "timeline"
    else:
        raise FitError("Pick the time columns: each row's start and stop, or (for a timeline) the time each "
                       "row's values take effect.")
    if not mapping.get("c"):
        raise FitError("Pick the status column: covariates that change over time need each item's rows "
                       "to say which one ended in a failure.")
    if not (covariates or (formula and str(formula).strip())):
        raise FitError(f"{model_name} needs the covariates that change over time — tick at least one.")
    return layout


def _numeric(df: pd.DataFrame, cols) -> pd.DataFrame:
    df = df.copy()
    for col in cols:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    return df


def fit_model(fitter, df: pd.DataFrame, mapping: dict, covariates, formula, layout: str):
    """SurPyval's TVC fit of ``fitter`` to ``df`` (with ``formula`` checked
    already, or the ``covariates`` columns)."""
    z = {"formula": formula} if formula else {"Z_cols": list(covariates)}
    n = {"n_col": mapping["n"]} if mapping.get("n") else {}
    if layout == "intervals":
        data = _numeric(df, [mapping["xl"], mapping["xr"], mapping["c"]])
        return fitter.fit_tvc_from_df(data, mapping["i"], mapping["xl"], mapping["xr"], mapping["c"],
                                      **z, **n)
    data = _numeric(df, [mapping["x"], mapping["c"]])
    if formula:
        return fitter.fit_tvc_timeline_from_df(data, mapping["i"], mapping["x"], None, mapping["c"],
                                               formula=formula, **n)
    return fitter.fit_tvc_timeline_from_df(data, mapping["i"], mapping["x"], list(covariates), mapping["c"],
                                           **n)


def _data_counts(df: pd.DataFrame, mapping: dict, layout: str) -> dict:
    """Items, rows and failures, as the fit read them (a status of 0 is a
    failure: on any row for interval rows, on an item's last row for a
    timeline)."""
    ids = df[mapping["i"]]
    c = pd.to_numeric(df[mapping["c"]], errors="coerce")
    if layout == "intervals":
        failures = int((c == 0).sum())
    else:
        t = pd.to_numeric(df[mapping["x"]], errors="coerce")
        last = pd.DataFrame({"i": ids, "t": t, "c": c}).sort_values(["i", "t"]).groupby("i", sort=False).tail(1)
        failures = int((last["c"] == 0).sum())
    return {"items": int(ids.nunique()), "rows": int(len(df)), "failures": failures}


def _nice_step(span: float) -> float:
    """A round step about a third of the covariate's range: 30 → 10,
    0.4 → 0.1, 40 → 10 (1, 2 or 5 times a power of ten)."""
    if not (span and math.isfinite(span) and span > 0):
        return 1.0
    raw = span / 3.0
    power = 10.0 ** math.floor(math.log10(raw))
    for m in (5, 2, 1):
        if m * power <= raw:
            return m * power
    return power


def schedule_fields(df: pd.DataFrame, fields: list) -> list:
    """The calculator's covariate fields with each numeric one's range in the
    data and a round step for readings."""
    out = []
    for f in fields:
        f = dict(f)
        if f.get("type") == "number" and f["name"] in df.columns:
            col = pd.to_numeric(df[f["name"]], errors="coerce").dropna()
            if col.size:
                lo, hi = float(col.min()), float(col.max())
                f.update({"min": lo, "max": hi, "step": _nice_step(hi - lo)})
        out.append(f)
    return out


def _sig(v: float, digits: int = 3) -> str:
    if v is None or not math.isfinite(v):
        return "—"
    if v == 0:
        return "0"
    mag = abs(v)
    if mag >= 1e7 or mag < 1e-3:
        return f"{v:.{digits - 1}e}"
    decimals = max(0, digits - 1 - int(math.floor(math.log10(mag))))
    text = f"{v:,.{decimals}f}"
    return text.rstrip("0").rstrip(".") if "." in text else text


_LEVEL = re.compile(r"^(?P<var>.+)\[T\.(?P<level>.+)\]$")


def readings(coefficients: list, effect: str, fields: list) -> list:
    """One plain sentence per coefficient: what a step in its covariate does.

    A numeric covariate steps by its field's round ``step`` ("Every +10 % in
    load_pct multiplies the hazard by 1.53"), a categorical level reads
    against the base level, anything else per unit of its term. The
    multiplier is exp(β·step) — what it multiplies depends on the family:
    the hazard (PH, Cox), how fast the item ages (AFT: SurPyval scales time
    by exp(β'z)), the odds of surviving (PO: exp(β'z) multiplies them);
    additive hazards add β·step to the hazard rate."""
    by_name = {f["name"]: f for f in fields or []}
    out = []
    for c in coefficients or []:
        name, beta, ci = c["name"], c.get("value"), c.get("ci")
        if beta is None or not math.isfinite(beta):
            continue
        field = by_name.get(name)
        level = _LEVEL.match(name)
        if field and field.get("type") == "number":
            step = float(field.get("step") or 1.0)
            u = c.get("covariate_unit") or field.get("unit")
            lead = f"Every +{_sig(step)}{(u if u == '%' else ' ' + u) if u else ''} in {name}"
        elif level:
            step = 1.0
            lead = f"{level['var']} = {level['level']} (against its base level)"
        else:
            step = 1.0
            lead = f"Every +1 in {name}"
        lo_hi = [v * step for v in ci] if ci else None
        if effect == "additive":
            text = f"{lead} adds {_sig(beta * step)} to the hazard rate"
            interval = lo_hi
        else:
            factor = math.exp(beta * step)
            verb = {"hazard": "multiplies the hazard by",
                    "aft": "makes the item age",
                    "odds": "multiplies the odds of surviving by"}.get(effect, "multiplies the hazard by")
            text = (f"{lead} {verb} {_sig(factor)}× as fast" if effect == "aft"
                    else f"{lead} {verb} {_sig(factor)}")
            interval = sorted(math.exp(v) for v in lo_hi) if lo_hi else None
        if interval and all(math.isfinite(v) for v in interval):
            text += f" (95% interval {_sig(interval[0])} to {_sig(interval[1])})"
        out.append({"name": name, "text": text + "."})
    return out


def _baseline_and_coefficients(model, effect: str, ratio_label):
    """Baseline parameters and coefficients with 95% Wald intervals, in the
    shape the regression payload uses (see ``fitting._fit_regression``)."""
    params = np.asarray(model.params, dtype=float)
    k = int(getattr(model, "k_dist", 0) or 0)
    try:
        ses = np.asarray(model.standard_errors(), dtype=float).ravel()
        ses = ses if ses.size == params.size else None
    except Exception:  # noqa: BLE001 - Cox without one / a singular Hessian
        ses = None

    def ci(i, bounds=(None, None)):
        if ses is None or not np.isfinite(ses[i]):
            return None
        return param_intervals.wald_interval(float(params[i]), float(ses[i]), *bounds[:2])

    base = getattr(model, "distribution", None)
    names = getattr(base, "parameter_names", None) or [f"p{i}" for i in range(k)]
    bounds = param_intervals.bounds_of(base)
    baseline = [{"name": n, "value": float(params[i]), "ci": ci(i, tuple(bounds.get(n) or (None, None)))}
                for i, n in enumerate(names)]
    features = getattr(model, "feature_names", None) or [f"b{i}" for i in range(params.size - k)]
    coefficients = []
    for j, n in enumerate(features):
        value = float(params[k + j])
        coef = {"name": n, "value": value, "ci": ci(k + j)}
        if ratio_label is not None:
            coef["ratio"] = float(np.exp(value))
            coef["hazard_ratio"] = coef["ratio"]
        coefficients.append(coef)
    return baseline, coefficients, list(features)


def fit(distribution: str, df: pd.DataFrame, mapping: dict, covariates=None, formula=None,
        covariate_units=None) -> dict:
    """Fit a regression model with covariates that change over time and build
    its payload: the regression payload (baseline, coefficients, fit
    statistics, a calculator at the covariate means) plus ``tvc``: the
    layout, the data counts, the schedule inputs and a plain reading per
    coefficient. Raises ``fitting.FitError``."""
    from backend import fitting
    from backend.formula_check import FormulaRejected, check_formula
    from backend.model_validation import unavailable
    from backend.services.method_labels import note_fit

    entry = fitting.REGRESSION_MODELS.get(distribution)
    if entry is None:
        raise fitting.FitError(
            "An item id column is for covariates that change over time, which need a regression model "
            "(e.g. Weibull PH or Cox PH). Clear the item id, or choose a regression model.")
    mapping = {k: v for k, v in mapping.items() if v}
    for col in mapping.values():
        if col not in df.columns:
            raise fitting.FitError(f"The data has no column named '{col}'.")
    layout = _check(mapping, covariates, formula, entry["name"])
    if formula:
        try:
            formula = check_formula(formula, df.columns)
        except FormulaRejected as exc:
            raise fitting.FitError(str(exc)) from exc
        covariates = None
    try:
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            model = note_fit(fit_model(entry["fitter"], df, mapping, covariates, formula, layout))
        fitting.reissue_deprecations(caught)
        gof = fitting._goodness_of_fit(model)
    except fitting.FitError:
        raise
    except Exception as exc:
        raise fitting.FitError(str(exc) or type(exc).__name__) from exc

    effect = entry.get("effect", "hazard")
    ratio_label = fitting._RATIO_LABELS.get(effect)
    baseline, coefficients, features = _baseline_and_coefficients(model, effect, ratio_label)

    raw_vars = fitting._raw_covariates(model, covariates)
    fields = fitting._covariate_fields(df, raw_vars)
    units = fitting.clean_covariate_units(covariate_units, raw_vars)
    if units:
        fields = [{**f, "unit": units[f["name"]]} if f["name"] in units else f for f in fields]
        coefficients = [{**c, "covariate_unit": units[c["name"]]} if c["name"] in units else c
                        for c in coefficients]
    fields = schedule_fields(df, fields)

    # The calculator's grid reaches past the latest time in the data.
    time_cols = [mapping["xr"]] if layout == "intervals" else [mapping["x"]]
    times = pd.to_numeric(df[time_cols[0]], errors="coerce").to_numpy(dtype=float)
    times = times[np.isfinite(times)]
    hi = float(times.max()) * 1.2 if times.size and times.max() > 0 else 1.0
    grid = np.linspace(0.0, hi, 300)
    default_row = pd.DataFrame({f["name"]: [f["default"]] for f in fields})
    try:
        curves = fitting._eval_functions(model, grid, default_row if fields else None)
    except Exception:  # noqa: BLE001 - the payload stands without them
        curves = None
    model_id = fitting._store_model(model, grid, fields)
    functions = None if curves is None else {
        "meta": fitting.FUNCTIONS, "curves": curves, "covariates": fields, "model_id": model_id}

    extra: dict = {}
    no_max = fitting.no_maximum_notice(model, caught, features, kind="regression")
    if no_max:
        extra["no_finite_maximum"] = no_max
        baseline = fitting.without_intervals(baseline)
        coefficients = fitting.without_intervals(coefficients)
    if distribution == "cox_ph" and gof:
        partial = {"log_likelihood": "Log partial likelihood"}
        gof = [{**g, "label": partial.get(g["id"], f"{g['label']} (partial)"), "partial": True} for g in gof]
        extra["gof_note"] = (
            "A Cox model's log-likelihood, AIC and BIC are on its partial likelihood: compare them "
            "only with other Cox models on the same data, never with a parametric model's.")
    extra["metrics_note"] = fitting.REGRESSION_METRICS_NOTE
    if not no_max:
        at_means = fitting.regression_metrics_at_defaults(model, fields)
        if at_means is not None:
            extra["at_covariate_means"] = {**at_means, "label": METRICS_LABEL}
    if units:
        extra["covariate_units"] = units
    counts = _data_counts(df, mapping, layout)
    return {
        **extra,
        "maximum": getattr(model, "maximum", None),
        "distribution": entry["name"],
        "distribution_id": distribution,
        "kind": "regression",
        "effect": effect,
        "ratio_label": ratio_label,
        "params": baseline,
        "coefficients": coefficients,
        "n": counts["items"],
        "gof": gof,
        "functions": functions,
        "validation": unavailable(VALIDATION_REASON),
        "tvc": {
            "layout": layout,
            **counts,
            "covariates": fields,
            "readings": [] if no_max else readings(coefficients, effect, fields),
            "bounds": hasattr(model, "cb_tvc"),
            "mean": hasattr(model, "mean_tvc"),
        },
    }


# ---------------------------------------------------------------------------
# Evaluation along a schedule
# ---------------------------------------------------------------------------

def parse_schedule(schedule, fields: list) -> tuple[np.ndarray, pd.DataFrame, list]:
    """``(times, rows, normalised)`` from ``[{"t": 0, "values": {...}}, ...]``
    (``"from"`` is accepted for ``"t"``). Sorted by time; a covariate a row
    leaves out keeps its previous value (the fit's default on the first
    row). Raises ``fitting.FitError`` in plain words."""
    from backend.fitting import FitError

    if not isinstance(schedule, list) or not schedule:
        raise FitError("Give a covariate schedule: at least one row, from time 0.")
    if len(schedule) > MAX_CHANGES:
        raise FitError(f"A schedule can have at most {MAX_CHANGES} changes.")
    names = [f["name"] for f in fields]
    rows = []
    for k, row in enumerate(schedule):
        if not isinstance(row, dict):
            raise FitError("Each schedule row is {\"t\": time, \"values\": {covariate: value}}.")
        t = row.get("t", row.get("from"))
        try:
            t = float(t)
        except (TypeError, ValueError):
            raise FitError(f"Schedule row {k + 1}: the time must be a number.") from None
        if not math.isfinite(t) or t < 0:
            raise FitError(f"Schedule row {k + 1}: the time must be 0 or more.")
        values = row.get("values") or {}
        if not isinstance(values, dict):
            raise FitError(f"Schedule row {k + 1}: values must be an object of covariate values.")
        unknown = sorted(set(values) - set(names))
        if unknown:
            raise FitError(f"Unknown covariate(s): {', '.join(unknown)}. This model's covariates are: "
                           f"{', '.join(names) or 'none'}.")
        rows.append((t, values))
    rows.sort(key=lambda r: r[0])
    times = [r[0] for r in rows]
    if len(set(times)) != len(times):
        raise FitError("Two schedule rows start at the same time — give each change its own time.")
    current = {f["name"]: f.get("default") for f in fields}
    table, normalised = [], []
    for t, values in rows:
        for f in fields:
            if f["name"] not in values or values[f["name"]] in (None, ""):
                continue
            v = values[f["name"]]
            if f.get("type") == "number":
                try:
                    v = float(v)
                except (TypeError, ValueError):
                    raise FitError(f"Covariate '{f['name']}' must be a number.") from None
                if not math.isfinite(v):
                    raise FitError(f"Covariate '{f['name']}' must be a finite number.")
            else:
                v = str(v)
                if f.get("options") and v not in f["options"]:
                    raise FitError(f"Covariate '{f['name']}' must be one of: {', '.join(map(str, f['options']))}.")
            current[f["name"]] = v
        table.append(dict(current))
        normalised.append({"t": t, "values": dict(current)})
    return np.asarray(times, dtype=float), pd.DataFrame(table, columns=names), normalised


def step_schedule(model, times: np.ndarray, rows: pd.DataFrame):
    """A SurPyval ``StepSchedule`` from change-point times and covariate rows
    (encoded as the model's design: a formula's categorical levels too)."""
    from surpyval import StepSchedule

    prepare = getattr(model, "_prepare_Z", None)
    Z = prepare(rows) if callable(prepare) else rows.to_numpy(dtype=float)
    return StepSchedule.from_changepoints(times, np.atleast_2d(np.asarray(Z, dtype=float)))


def _clean(a) -> list:
    return [float(v) if np.isfinite(v) else None for v in np.asarray(a, dtype=float).ravel()]


def evaluate(model, fields: list, schedule, grid, *, on: str = "sf", alpha_ci: Optional[float] = None,
             bound: str = "lower") -> dict:
    """Reliability, failure probability and cumulative hazard along a
    covariate schedule over ``grid``; with ``alpha_ci``, confidence bounds on
    ``on`` (``cb_tvc``, Wald; parametric models only — the reason otherwise);
    and the mean life along the schedule where SurPyval gives one."""
    from backend.fitting import FitError

    if on not in _FUNCTION_IDS:
        raise FitError(f"Can't evaluate '{on}' along a schedule — use sf, ff or Hf.")
    if bound not in _BOUNDS:
        raise FitError("Unknown bound — use two-sided, lower or upper.")
    if alpha_ci is not None and not 0.0 < float(alpha_ci) < 1.0:
        raise FitError("Confidence level must be between 0% and 100% (exclusive).")
    times, rows, normalised = parse_schedule(schedule, fields)
    grid = np.asarray(grid, dtype=float)
    try:
        sched = step_schedule(model, times, rows)
        with np.errstate(all="ignore"), warnings.catch_warnings():
            warnings.simplefilter("ignore")
            sf = np.asarray(model.sf_tvc(grid, sched), dtype=float)
            Hf = np.asarray(model.Hf_tvc(grid, sched), dtype=float)
    except FitError:
        raise
    except Exception as exc:
        raise FitError(str(exc) or type(exc).__name__) from exc
    out = {"curves": {"x": grid.tolist(), "sf": _clean(sf), "ff": _clean(1.0 - sf), "Hf": _clean(Hf)},
           "schedule": normalised, "on": on}
    if (np.isfinite(sf) & (sf > 1.0 + 1e-6)).any():
        out["warning"] = ("The cumulative hazard goes negative along this schedule, so reliability rises "
                          "above 1 — which is impossible. This additive-hazards fit is unreliable here; try a "
                          "proportional-hazards model instead.")
    if alpha_ci is not None:
        out["bounds"], out["bounds_note"] = _bounds(model, grid, sched, on, float(alpha_ci), bound)
    out["mean"] = _mean(model, sched)
    return out


def _bounds(model, grid, sched, on, alpha_ci, bound):
    if not hasattr(model, "cb_tvc"):
        return None, "Cox models have no confidence bounds along a schedule; a parametric model does."
    try:
        with np.errstate(all="ignore"), warnings.catch_warnings():
            warnings.simplefilter("ignore")
            cb = np.asarray(model.cb_tvc(grid, sched, on=on, alpha_ci=alpha_ci, bound=bound), dtype=float)
    except Exception as exc:  # noqa: BLE001 - e.g. no covariance from a singular fit
        return None, f"No confidence bounds for this fit ({str(exc).strip() or type(exc).__name__})."
    if cb.ndim == 2:
        lower, upper = _clean(cb[:, 0]), _clean(cb[:, 1])
    elif bound == "lower":
        lower, upper = _clean(cb), None
    else:
        lower, upper = None, _clean(cb)
    return ({"x": np.asarray(grid, dtype=float).tolist(), "on": on, "alpha_ci": alpha_ci, "bound": bound,
             "lower": lower, "upper": upper},
            "Wald (delta-method) bounds from the fit's covariance, carried along the schedule.")


def _mean(model, sched) -> Optional[float]:
    fn = getattr(model, "mean_tvc", None)
    if not callable(fn):
        return None
    try:
        with np.errstate(all="ignore"), warnings.catch_warnings():
            warnings.simplefilter("ignore")
            v = float(fn(sched))
    except Exception:  # noqa: BLE001 - a convenience: absent rather than wrong
        return None
    return v if math.isfinite(v) and v >= 0 else None


def evaluate_points(model, fields: list, schedule, times, *, conditional_age: Optional[float] = None,
                    confidence: Optional[float] = None) -> dict:
    """Point values along a schedule at exactly ``times`` (the MCP's
    reliability_at): reliability, failure probability, cumulative hazard,
    the conditional reliability R(age + t | age) when ``conditional_age`` is
    given, and two-sided ``confidence`` bounds on R and F where the model has
    them."""
    from backend.fitting import FitError

    t = np.asarray([float(v) for v in times], dtype=float)
    stimes, rows, normalised = parse_schedule(schedule, fields)
    try:
        sched = step_schedule(model, stimes, rows)
        with np.errstate(all="ignore"), warnings.catch_warnings():
            warnings.simplefilter("ignore")
            sf = np.asarray(model.sf_tvc(t, sched), dtype=float)
            Hf = np.asarray(model.Hf_tvc(t, sched), dtype=float)
            cond = None
            if conditional_age is not None:
                a = float(conditional_age)
                H_a = float(np.asarray(model.Hf_tvc(np.array([a]), sched), dtype=float)[0])
                H_l = np.asarray(model.Hf_tvc(a + t, sched), dtype=float)
                cond = np.clip(np.exp(-(H_l - H_a)), 0.0, 1.0)
    except FitError:
        raise
    except Exception as exc:
        raise FitError(str(exc) or type(exc).__name__) from exc
    points = []
    for k, tk in enumerate(t):
        p = {"t": float(tk), "reliability": _clean([sf[k]])[0], "failure": _clean([1.0 - sf[k]])[0],
             "cumulative_hazard": _clean([Hf[k]])[0]}
        if cond is not None:
            p["conditional_reliability"] = _clean([cond[k]])[0]
        points.append(p)
    out = {"points": points, "schedule": normalised, "mean_life": _mean(model, sched)}
    if confidence is not None:
        alpha = 1.0 - float(confidence)
        r, note = _bounds(model, t, sched, "sf", alpha, "two-sided")
        f, _ = _bounds(model, t, sched, "ff", alpha, "two-sided")
        for k, p in enumerate(points):
            p["reliability_bounds"] = [r["lower"][k], r["upper"][k]] if r else None
            p["failure_bounds"] = [f["lower"][k], f["upper"][k]] if f else None
        out["bounds_note"] = note
    return out
