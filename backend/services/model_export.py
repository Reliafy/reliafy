"""Download as Python for a saved life model (the ``models`` collection).

One script per model: it holds the data the model was fitted to (after the
app's own preparation), makes the same SurPyval call the app made, and prints
the numbers the model page shows, at the app's levels: B-lives and the mean
life with a 90% one-sided lower bound, parameters with a 90% two-sided
interval.

Covered here: fitted distributions (with an offset, a limited failure
population, zero-inflation, fixed parameters or another fit method; Best fit
saves its winner), mixtures, discrete distributions, non-parametric estimates,
models saved from parameters, per-demand (Binomial) models and Bayesian
updates. Regression and time-varying covariate models are built by
:mod:`backend.services.regression_export`.
"""

from __future__ import annotations

from typing import Optional

import numpy as np
import pandas as pd

from backend import fitting
from backend.schema import Model
from backend.services import python_export as px
from backend.units import unit_in_text

#: Fit options that change the data before the fit, not the fit itself.
_PREP_KEYS = (fitting.CENSOR_INVERT_KEY, fitting.CENSOR_MAP_KEY, fitting.STRICT_INTERVALS_KEY)


class ExportError(fitting.FitError):
    """A model this download can't reproduce, said in words."""


def _surpyval_name(obj) -> Optional[str]:
    import surpyval

    for attr in sorted(dir(surpyval)):
        if getattr(surpyval, attr, None) is obj:
            return attr
    return None


def _unit_words(model: Model) -> str:
    unit = (model.results or {}).get("unit") or (model.spec or {}).get("unit") or ""
    return unit_in_text(unit) or ""


def prepare(df: pd.DataFrame, spec: dict, unit: Optional[str]) -> tuple[pd.DataFrame, dict, dict, list[str]]:
    """The data and mapping as ``fitting.fit`` hands them to the fitter:
    the unit column converted, a status column of words read, a 1 = failed
    column turned round. Returns ``(df, mapping, remaining options, notes)``;
    each note says in words what was done, for the script's comments."""
    from backend import competing_risks, unit_column

    mapping = competing_risks.plain_mapping(spec.get("mapping") or {})
    options = dict(spec.get("options") or {})
    notes: list[str] = []
    u_col = options.pop(unit_column.UNIT_COLUMN_KEY, None)
    if u_col:
        try:
            df, _ = unit_column.convert(df, mapping, str(u_col), unit)
        except ValueError as exc:
            raise ExportError(str(exc)) from exc
        notes.append(f"Each row's time was converted to {unit_in_text(unit) or unit} using the "
                     f"'{u_col}' column, as the app did.")
    c_invert = bool(options.pop(fitting.CENSOR_INVERT_KEY, False)) and bool(mapping.get("c"))
    c_map = options.pop(fitting.CENSOR_MAP_KEY, None) if mapping.get("c") else None
    options.pop(fitting.CENSOR_MAP_KEY, None)
    options.pop(fitting.STRICT_INTERVALS_KEY, None)
    if c_map:
        df = fitting.map_censor_column(df, mapping["c"], c_map)
        notes.append(f"The words in '{mapping['c']}' were read as censor flags ({c_map}).")
    elif c_invert:
        df = fitting.invert_censor_column(df, mapping["c"])
        notes.append(f"'{mapping['c']}' used 1 = failed; it was turned round to 0 = failed, 1 = still running.")
    return df, mapping, options, notes


def _inputs_frame(kwargs: dict) -> pd.DataFrame:
    """SurPyval's ``x/c/n/xl/xr/tl/tr`` arrays as one table, one column each."""
    cols = {k: np.asarray(kwargs[k], dtype=float).ravel() for k in ("x", "xl", "xr", "c", "n", "tl", "tr")
            if kwargs.get(k) is not None}
    return pd.DataFrame(cols)


_DATA_WORDS = [
    "The data, one row per unit (or group of identical units):",
    "  x      the time it failed, or was last seen running",
    "  xl/xr  inspection data: seen working at xl, found failed by xr",
    "  c      0 = failed, 1 = still running, -1 = failed before x, 2 = failed between xl and xr",
    "  n      how many units the row stands for",
    "  tl/tr  delayed entry: the unit was only watched from tl (and up to tr)",
]

_READ_DATA = [
    "data = pd.read_csv(io.StringIO(DATA))",
    "fit_inputs = {column: data[column].to_numpy(dtype=float) for column in data.columns}",
]

# The interval the app shows beside a parameter (backend/param_intervals.py):
# 90% two-sided, kept inside the parameter's allowed range.
_WALD = '''
Z = 1.6448536269514722  # the 90% two-sided normal quantile


def interval(value, se, lower=None, upper=None):
    """A 90% two-sided interval for a parameter from its standard error.

    A parameter that must stay above a limit (a scale or shape above 0) gets its
    interval on the log scale, so it never crosses the limit; one between two
    limits (a proportion) on the logit scale; any other is value +/- Z * se."""
    if se is None or not np.isfinite(se) or se < 0 or not np.isfinite(value):
        return None, None
    lower = lower if lower is not None and np.isfinite(lower) else None
    upper = upper if upper is not None and np.isfinite(upper) else None
    if lower is None and upper is None:
        return value - Z * se, value + Z * se
    if lower is not None and upper is not None:
        width = upper - lower
        if width <= 0 or not (lower < value < upper):
            return None, None
        u = (value - lower) / width
        k = Z * se / (width * u * (1 - u))
        logit = np.log(u / (1 - u))
        return lower + width / (1 + np.exp(-(logit - k))), lower + width / (1 + np.exp(-(logit + k)))
    if lower is not None:
        d = value - lower
        if d <= 0:
            return None, None
        return lower + d * np.exp(-Z * se / d), lower + d * np.exp(Z * se / d)
    d = upper - value
    if d <= 0:
        return None, None
    return upper - d * np.exp(Z * se / d), upper - d * np.exp(-Z * se / d)


def fill_covariance(model):
    """When SurPyval's own covariance comes out missing or not finite (a fit by
    probability plotting, say, or a large scale), the app works it out from a
    finite-difference Hessian of the log-likelihood at the fitted values. Same here."""
    try:
        cov = np.asarray(model.covariance(), dtype=float)
        if np.all(np.isfinite(cov)):
            return
    except Exception:
        pass
    if float(getattr(model, "f0", 0.0) or 0.0) != 0.0 or float(getattr(model, "lfp_p", 1.0) or 1.0) != 1.0:
        return
    try:
        params = np.asarray(model.params, dtype=float)
        gamma = float(getattr(model, "gamma", 0.0) or 0.0)
        surv_data, neg_ll = model.surv_data, model.dist._neg_ll_func

        def nll(theta):
            return float(neg_ll(surv_data, *theta, gamma, 0.0, 1.0))

        n = len(params)
        step = np.maximum(np.abs(params), 1.0) * (np.finfo(float).eps ** (1 / 3)) * 50
        hess = np.empty((n, n))
        for i in range(n):
            for j in range(n):
                ei, ej = np.zeros(n), np.zeros(n)
                ei[i], ej[j] = step[i], step[j]
                hess[i, j] = (nll(params + ei + ej) - nll(params + ei - ej) - nll(params - ei + ej)
                              + nll(params - ei - ej)) / (4 * step[i] * step[j])
        recomputed = np.linalg.inv(hess)
        if np.all(np.isfinite(recomputed)) and np.all(np.diag(recomputed) > 0):
            model._covariance = recomputed
            model.hess_inv = recomputed
    except Exception:
        pass


def standard_errors(model, n_params):
    """Each parameter's standard error from the fit's covariance (None without one)."""
    try:
        cov = np.atleast_2d(np.asarray(model.covariance(), dtype=float))
    except Exception:
        return [None] * n_params
    if cov.shape != (n_params, n_params) or not np.all(np.isfinite(cov)):
        return [None] * n_params
    return [float(np.sqrt(d)) if d > 0 else None for d in np.diag(cov)]
'''.strip("\n").splitlines()

B_LIVES = "B_LIVES = [(0.01, \"B1\"), (0.05, \"B5\"), (0.10, \"B10\"), (0.50, \"B50\")]"


def _print_params_lines(dist_var: str, with_intervals: bool) -> list[str]:
    lines = [
        "",
        "# The parameters, each with its 90% two-sided interval.",
        f"names = list({dist_var}.parameter_names)",
        f"limits = list({dist_var}.bounds)",
        "values = np.atleast_1d(np.asarray(model.params, dtype=float))",
    ]
    if with_intervals:
        lines.append("errors = standard_errors(model, len(values))")
    else:
        lines.append("errors = [None] * len(values)  # this fit has no usable covariance, so no intervals")
    lines += [
        "for name, value, se, (low_limit, high_limit) in zip(names, values, errors, limits):",
        "    low, high = interval(value, se, low_limit, high_limit)",
        "    print_interval(name, value, low, high)",
    ]
    return lines


def _life_lines(unit: str, *, bounds: bool, how: str = "parametric") -> list[str]:
    """Print B1, B5, B10, B50 and the mean life with their 90% one-sided
    lower bounds. ``how``: parametric, nonparametric, bayes or mixture."""
    u = repr(unit)
    lines = ["", "# B-lives: the time by which 1%, 5%, 10% and 50% have failed. The lower bound is the",
             "# time we can be 90% sure it is at least (a 90% one-sided bound).", B_LIVES]
    if how == "bayes":
        lines += [
            "for p, label in B_LIVES:",
            "    value = float(np.ravel(model.quantile_cri(np.array([p]), point=True))[0])",
            "    lower = float(np.ravel(model.quantile_cri(np.array([p]), alpha_ci=0.10, bound=\"lower\"))[0])",
            f"    print_bound(label, value, lower, unit={u})",
            "",
            "# The mean life, with its 90% one-sided lower (credible) bound.",
            "mean = float(model.mean())",
            "mean_lower = float(np.ravel(model.mean_cri(alpha_ci=0.10, bound=\"lower\"))[0])",
            f"print_bound(\"Mean life\", mean, mean_lower, unit={u})",
        ]
        return lines
    if how == "mixture":
        lines += [
            "for p, label in B_LIVES:",
            "    try:",
            "        lower = float(np.ravel(model.quantile_cb(np.array([p]), alpha_ci=0.10, bound=\"lower\"))[0])",
            "    except Exception:",
            "        lower = None",
            f"    print_bound(label, mixture_quantile(p), lower, unit={u})",
            "",
            "# The mean life (with its lower bound where SurPyval gives one for a mixture).",
            "try:",
            "    mean_lower = float(np.ravel(model.mean_cb(alpha_ci=0.10, bound=\"lower\"))[0])",
            "except Exception:",
            "    mean_lower = None",
            f"print_bound(\"Mean life\", model.mean(), mean_lower, unit={u})",
        ]
        return lines
    if how == "nonparametric":
        lines += [
            "# A one-sided 90% bound is one end of the two-sided 80% interval.",
            "for p, label in B_LIVES:",
            "    value = float(np.ravel(model.qf(np.array([p])))[0])",
            "    lower = float(np.asarray(model.quantile_cb(np.array([p]), alpha_ci=0.20), dtype=float).reshape(-1, 2)[0, 0])",
            f"    print_bound(label, value, lower, unit={u})",
            "",
            "# The mean life: the area under the curve up to the last observation (restricted",
            "# to that time unless the curve reaches zero), with its 90% one-sided lower bound.",
            "tau = float(np.max(np.asarray(model.x, dtype=float)[np.isfinite(np.asarray(model.x, dtype=float))]))",
            "mean = float(model.mean(tau=tau))",
            "mean_lower = max(float(np.ravel(model.mean_cb(tau=tau, alpha_ci=0.20))[0]), 0.0)",
            f"print_bound(\"Mean life\", mean, mean_lower, unit={u})",
        ]
        return lines
    lines += [
        "for p, label in B_LIVES:",
        "    value = float(np.ravel(model.qf(np.array([p])))[0])",
    ]
    if bounds:
        lines += [
            "    try:",
            "        lower = float(np.ravel(model.quantile_cb(np.array([p]), alpha_ci=0.10, bound=\"lower\"))[0])",
            "    except Exception:",
            "        lower = None",
        ]
    else:
        lines.append("    lower = None  # no bound: see the note at the top")
    lines += [
        f"    print_bound(label, value, lower, unit={u})",
        "",
        "# The mean life (MTTF), with its 90% one-sided lower bound.",
        "mean = float(model.mean())",
    ]
    if bounds:
        lines += [
            "try:",
            "    mean_lower = float(np.ravel(model.mean_cb(alpha_ci=0.10, bound=\"lower\"))[0])",
            "except Exception:",
            "    mean_lower = None",
        ]
    else:
        lines.append("mean_lower = None")
    lines.append(f"print_bound(\"Mean life\", mean, mean_lower, unit={u})")
    return lines


def _imports(*names: str) -> list[str]:
    out = ["import io", "", "import numpy as np", "import pandas as pd"]
    if names:
        out.append(f"from surpyval import {', '.join(sorted(set(names)))}")
    return out + [""]


# ---------------------------------------------------------------------------
# One script per kind
# ---------------------------------------------------------------------------
def _distribution_script(model: Model, df: pd.DataFrame) -> str:
    spec = model.spec or {}
    results = model.results or {}
    dist_id = spec.get("distribution_id") or model.distribution_id
    unit_label = (results.get("unit") or spec.get("unit") or "")
    df, mapping, options, notes = prepare(df, spec, unit_label)
    if dist_id == fitting.MIXTURE_ID:
        return _mixture_script(model, df, mapping, options, notes)
    entry = fitting.DISTRIBUTIONS.get(dist_id)
    name = _surpyval_name(entry["dist"]) if entry else None
    if not name:
        raise ExportError(f"Download as Python isn't available for {results.get('distribution') or dist_id} "
                          "models yet.")
    options = fitting.normalize_options(dist_id, options)
    kwargs = fitting.build_fit_inputs(df, mapping)
    call = []
    for key in ("offset", "zi", "lfp", "fixed", "how"):
        if options.get(key):
            value = options[key]
            if key == "fixed":
                value = {("lfp_p" if k == "p" else k): v for k, v in value.items()}
            call.append(f"{key}={px.literal(value)}")
    how = options.get("how") or "MLE"
    no_max = bool(results.get("no_finite_maximum"))
    bounds = how == "MLE" and not no_max
    unit = _unit_words(model)
    what = f"a {entry['name']} fitted by " + {
        "MLE": "maximum likelihood", "MPP": "probability plotting", "MPS": "maximum spacings",
        "MSE": "least squares (MSE)", "MOM": "the method of moments"}.get(how, how)
    head_notes = list(notes)
    if not bounds:
        head_notes.append("This fit has no confidence bounds on its B-lives, as on the page: "
                          + ("only a maximum-likelihood fit has them." if how != "MLE"
                             else "the fit has no finite maximum, so its covariance means nothing."))
    extras = []
    if options.get("offset"):
        extras.append('print_value("gamma (offset)", model.gamma, UNIT)')
    if options.get("lfp"):
        extras.append('print_value("p (max fraction failing)", model.lfp_p)')
    if options.get("zi"):
        extras.append('print_value("f0 (failed at t=0)", model.f0)')
    body = [
        *px.comment(" ".join(_DATA_WORDS[:1])),
        *[f"# {w}" for w in _DATA_WORDS[1:]],
        *px.csv_block("DATA", _inputs_frame(kwargs)),
        f"UNIT = {unit!r}",
        "",
        *_READ_DATA,
        "",
        *px.comment(f"Fit the {entry['name']} exactly as the app did"
                    + (f" (options: {', '.join(call)})" if call else "") + "."),
        f"model = {name}.fit(**fit_inputs{''.join(', ' + c for c in call)})",
        "fill_covariance(model)",
        "print(model)",
        "print()",
        *_print_params_lines(name, with_intervals=not no_max),
        *([""] + ["# The extra fitted quantities from the fit options."] + extras if extras else []),
        *_life_lines(unit, bounds=bounds),
    ]
    return px.assemble(
        px.header(model.name, f"a {entry['name']} life model.", notes=[what[0].upper() + what[1:] + ".",
                                                                     *head_notes], unit=unit),
        _imports(name), px.PRINT_HELPERS, [""], _WALD, ["", ""], body)


def _mixture_script(model: Model, df: pd.DataFrame, mapping: dict, options: dict, notes: list[str]) -> str:
    base = fitting.mixture_base(options)
    m = int(options.get("mixture") or fitting.MIXTURE_DEFAULT_COMPONENTS)
    entry = fitting.DISTRIBUTIONS[base]
    name = _surpyval_name(entry["dist"])
    kwargs = fitting.build_fit_inputs(df, mapping)
    unit = _unit_words(model)
    body = [
        *px.comment(_DATA_WORDS[0]),
        *[f"# {w}" for w in _DATA_WORDS[1:]],
        *px.csv_block("DATA", _inputs_frame(kwargs)),
        "",
        *_READ_DATA,
        "",
        f"# A mixture of {m} {entry['name']} distributions (failure modes muddled in one data set),",
        "# fitted by expectation-maximisation as the app did.",
        f"model = MixtureModel(dist={name}, m={m})",
        "model.fit(**fit_inputs)",
        "",
        "",
        "def mixture_quantile(p):",
        '    """The time by which a fraction p has failed, by bisection on the mixed CDF (the app\'s way)."""',
        "    hi = 1.0",
        "    for _ in range(200):",
        "        if float(np.ravel(model.ff(hi))[0]) >= p or hi > 1e12:",
        "            break",
        "        hi *= 2.0",
        "    lo = 0.0",
        "    for _ in range(100):",
        "        mid = 0.5 * (lo + hi)",
        "        if float(np.ravel(model.ff(mid))[0]) < p:",
        "            lo = mid",
        "        else:",
        "            hi = mid",
        "    return 0.5 * (lo + hi)",
        "",
        "",
        "# Each component's parameters and its weight (the share of units in it). A mixture has",
        "# no covariance, so no intervals.",
        f"names = list({name}.parameter_names)",
        "values = np.asarray(model.params, dtype=float).reshape(model.m, -1)",
        "weights = np.ravel(np.asarray(model.w, dtype=float))",
        "for j in range(model.m):",
        "    for k, name in enumerate(names):",
        "        print_value(f\"{name}{j + 1}\", values[j][k])",
        "    print_value(f\"weight{j + 1}\", weights[j])",
        *_life_lines(unit, bounds=False, how="mixture"),
    ]
    return px.assemble(
        px.header(model.name, f"a mixture of {m} {entry['name']} distributions.", notes=notes, unit=unit),
        _imports(name, "MixtureModel"), px.PRINT_HELPERS, ["", ""], body)


def _discrete_script(model: Model, df: pd.DataFrame) -> str:
    spec = model.spec or {}
    dist_id = spec.get("distribution_id") or model.distribution_id
    entry = fitting.DISCRETE.get(dist_id)
    name = _surpyval_name(entry["dist"]) if entry else None
    if not name:
        raise ExportError(f"Download as Python isn't available for {(model.results or {}).get('distribution')} "
                          "models yet.")
    df, mapping, _, notes = prepare(df, spec, spec.get("unit"))
    kwargs = fitting.build_fit_inputs(df, mapping)
    body = [
        *px.comment(_DATA_WORDS[0] + " (whole counts: cycles, demands, shots)"),
        *[f"# {w}" for w in _DATA_WORDS[1:]],
        *px.csv_block("DATA", _inputs_frame(kwargs)),
        "",
        *_READ_DATA,
        "",
        f"model = {name}.fit(**fit_inputs)",
        "print(model)",
        "print()",
        *_print_params_lines(name, with_intervals=True),
        "",
        "# The median, the B10 (the count by which 10% have failed) and the mean.",
        'print_value("Median", np.ravel(model.qf(0.5))[0])',
        'print_value("B10", np.ravel(model.qf(0.1))[0])',
        'print_value("Mean life", model.mean())',
    ]
    return px.assemble(px.header(model.name, f"a {entry['name']} (discrete) life model.", notes=notes),
                       _imports(name), px.PRINT_HELPERS, [""], _WALD, ["", ""], body)


_INTERVAL_POINTS = '''
def interval_b_lives(model, alpha=0.10):
    """Inspection data: the estimate knows how many failed between two inspection
    times, not when, so each B-life is the interval it falls in. Its lower bound is
    the start of the interval in which the curve's upper band first reaches the share."""
    xs = np.asarray(model.x, dtype=float)
    F = 1.0 - np.asarray(model.R, dtype=float)
    band = np.asarray(model.cb(xs, on="sf", alpha_ci=2 * alpha), dtype=float).reshape(-1, 2)
    upper_F = 1.0 - band[:, 0]
    for p, label in B_LIVES:
        reached = F >= p - 1e-12
        if not reached.any():
            print_bound(label, float(np.ravel(model.qf(np.array([p])))[0]), None, unit=UNIT)
            continue
        k = int(np.argmax(reached))
        start = float(xs[k - 1]) if k > 0 else 0.0
        hit = np.nonzero(upper_F >= p - 1e-12)[0]
        lower = None
        if hit.size:
            j = int(hit[0])
            if j > 0 and np.isfinite(upper_F[j - 1]) and upper_F[j - 1] > 0:
                lower = float(xs[j - 1])
        value = float(np.ravel(model.qf(np.array([p])))[0])
        if start < xs[k]:
            print(f"{label} between: {fmt(start)} and {fmt(xs[k])} {UNIT}")
            value = None
        print_bound(label, value, lower, unit=UNIT)
'''.strip("\n").splitlines()


def _nonparametric_script(model: Model, df: pd.DataFrame) -> str:
    spec = model.spec or {}
    dist_id = spec.get("distribution_id") or model.distribution_id
    entry = fitting.NONPARAMETRIC[dist_id]
    name = _surpyval_name(entry["est"])
    df, mapping, _, notes = prepare(df, spec, spec.get("unit"))
    kwargs = fitting.build_fit_inputs(df, mapping)
    unit = _unit_words(model)
    interval = np.isin(np.asarray(kwargs.get("c", []), dtype=float), (2, -1)).any()
    body = [
        *px.comment(_DATA_WORDS[0]),
        *[f"# {w}" for w in _DATA_WORDS[1:]],
        *px.csv_block("DATA", _inputs_frame(kwargs)),
        f"UNIT = {unit!r}",
        "",
        *_READ_DATA,
        "",
        f"# The {entry['name']} estimate: the data's own reliability curve, no distribution assumed.",
        f"model = {name}.fit(**fit_inputs)",
    ]
    if interval:
        body += ["", B_LIVES, "", *_INTERVAL_POINTS, "", "", "interval_b_lives(model)",
                 *_life_lines(unit, bounds=True, how="nonparametric")[-6:]]
    else:
        body += _life_lines(unit, bounds=True, how="nonparametric")
    return px.assemble(px.header(model.name, f"a {entry['name']} estimate of reliability.", notes=notes,
                                 unit=unit),
                       _imports(name), px.PRINT_HELPERS, ["", ""], body)


def _params_only_script(model: Model) -> str:
    results = model.results or {}
    spec = model.spec or {}
    dist_id = spec.get("distribution_id") or model.distribution_id
    entry = fitting.DISTRIBUTIONS.get(dist_id)
    name = _surpyval_name(entry["dist"]) if entry else None
    if not name:
        raise ExportError(f"Download as Python isn't available for {results.get('distribution') or dist_id} "
                          "models yet.")
    values = [p["value"] for p in results.get("params") or []]
    extras = fitting.surpyval_extras(results.get("extras"))
    unit = _unit_words(model)
    call = "".join(f", {k}={px.num(v)}" for k, v in extras.items())
    body = [
        "# The parameters as they were entered (no data, so no intervals or bounds).",
        f"model = {name}.from_params([{', '.join(px.num(v) for v in values)}]{call})",
        "print(model)",
        "print()",
        f"for name, value in zip({name}.parameter_names, model.params):",
        "    print_value(name, value)",
        *_life_lines(unit, bounds=False),
    ]
    return px.assemble(px.header(model.name, f"a {entry['name']} life model from its parameters.", unit=unit),
                       _imports(name), px.PRINT_HELPERS, ["", ""], body)


def _per_demand_script(model: Model) -> str:
    stored = (model.spec or {}).get("per_demand") or {}
    batches = stored.get("batches") or [{"demands": stored.get("demands"), "failures": stored.get("failures")}]
    confidence = float(stored.get("confidence") or 0.90)
    failures = [int(b["failures"]) for b in batches]
    demands = [int(b["demands"]) for b in batches]
    body = [
        "# Failures and demands (one pair per batch: a site, a lot, a test campaign).",
        f"FAILURES = {failures!r}",
        f"DEMANDS = {demands!r}",
        f"CONFIDENCE = {confidence!r}",
        "ALPHA = 1 - CONFIDENCE",
        "",
        "# The chance of failing on demand, pooled over every batch (Binomial).",
        "model = Binomial.fit(FAILURES, n_trials=DEMANDS)",
        "p = float(model.params[1])",
        "# Exact (Clopper-Pearson) bounds.",
        'low, high = (float(v) for v in np.ravel(model.param_cb("p", alpha_ci=ALPHA)))',
        "low, high = max(0.0, low), min(1.0, high)",
        'p_upper = float(np.ravel(model.param_cb("p", alpha_ci=ALPHA, bound="upper"))[0])',
        'print_interval("Failure probability per demand", p, low, high)',
        'print_bound("Failure probability per demand", p, p_upper, side="upper")',
        'print_interval("Reliability per demand", 1 - p, 1 - high, 1 - low)',
        'print_bound("Reliability per demand", 1 - p, 1 - p_upper)',
        "if sum(FAILURES) == 0:",
        "    # No failures: the success-run demonstration.",
        '    print_value("Demonstrated reliability (success run)", success_run(sum(DEMANDS), alpha_ci=ALPHA))',
    ]
    note = (f"The intervals are at {confidence:.0%}, the level the model was saved with."
            if abs(confidence - 0.90) > 1e-9 else "")
    lines = px.PRINT_HELPERS
    if abs(confidence - 0.90) > 1e-9:
        lines = [ln.replace("90% two-sided", f"{confidence:.0%} two-sided").replace("90% one-sided",
                                                                                     f"{confidence:.0%} one-sided")
                 for ln in lines]
    return px.assemble(px.header(model.name, "a per-demand (Binomial) reliability model.",
                                 notes=[note] if note else []),
                       ["import numpy as np", "from surpyval import Binomial, success_run", ""], lines,
                       ["", ""], body)


def _bayes_script(model: Model) -> str:
    spec = model.spec or {}
    b = spec.get("bayes") or {}
    dist_id = spec.get("distribution_id")
    from backend.services import bayes_life

    dist = bayes_life.DISTS.get(dist_id)
    name = _surpyval_name(dist) if dist is not None else None
    if not name or not b:
        raise ExportError("This Bayesian update can't be downloaded as Python: its recipe isn't saved with it.")
    x = np.asarray(b["x"], dtype=float).reshape(-1, 2)
    unit = _unit_words(model)
    frame = pd.DataFrame({"shortest": x[:, 0], "longest": x[:, 1], "c": np.asarray(b["c"], dtype=int)})
    body = [
        "# The history: each row's time (shortest = longest for an exact time; a span for",
        "# inspection data) and c (0 = failed, 1 = still running).",
        *px.csv_block("DATA", frame),
        "",
        "# The prior: the baseline, weighed by how much it was trusted (SurPyval's prior spec).",
        f"PRIORS = {px.literal(b['priors'])}",
        "",
        "data = pd.read_csv(io.StringIO(DATA))",
        'x = data[["shortest", "longest"]].to_numpy(dtype=float)',
        'c = data["c"].to_numpy(dtype=int)',
        "",
        "# The Bayesian update: the baseline moved by this history.",
        f"model = {name}.fit_bayes(x, c, priors=PriorSpec.from_dict(PRIORS), unit={spec.get('unit') or None!r})",
        "",
        "# The parameters: posterior medians with 90% two-sided credible intervals.",
        f"for name, median in zip({name}.parameter_names, model.params):",
        "    low, high = model.param_cri(name, alpha_ci=0.10)",
        "    print_interval(name, median, low, high)",
        *_life_lines(unit, bounds=True, how="bayes"),
    ]
    return px.assemble(
        px.header(model.name, f"a Bayesian update of a {bayes_life.LABELS[dist_id]} baseline.",
                  notes=["The bounds are credible intervals, as on the page, not confidence bounds."], unit=unit),
        _imports(name), ["from surpyval.bayes.prior import PriorSpec", ""], px.PRINT_HELPERS, ["", ""], body)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
def source_for(db, model: Model) -> str:
    """The script for ``model``. Raises :class:`ExportError` (a FitError)
    when it can't be reproduced."""
    from backend.services import datasets as datasets_service

    spec = model.spec or {}
    results = model.results or {}
    if spec.get("method") == "bayesian_update":
        return _bayes_script(model)
    if model.kind == "per_demand" or spec.get("per_demand"):
        return _per_demand_script(model)
    if spec.get("params_only") or results.get("params_only"):
        return _params_only_script(model)
    if model.kind in ("joint",):
        raise ExportError("Use the condition and life page's own download for this model.")
    supported = ("distribution", "discrete", "nonparametric", "regression")
    if model.kind not in supported:
        raise ExportError(f"Download as Python isn't available for {results.get('distribution') or model.kind} "
                          "models yet.")
    dataset = datasets_service.get_dataset(db, model.dataset_id, owner_id=model.owner_id) \
        if model.dataset_id else None
    if dataset is None:
        raise ExportError("The data this model was fitted to isn't there any more, so it can't be refitted.")
    df = datasets_service.load_dataframe(dataset)
    if model.kind == "regression":
        from backend.services import regression_export

        return regression_export.script(model, df)
    if model.kind == "discrete":
        return _discrete_script(model, df)
    if model.kind == "nonparametric":
        return _nonparametric_script(model, df)
    return _distribution_script(model, df)


def export_python(db, model: Model) -> tuple[str, str]:
    """``(filename, source)`` of the model's Download as Python."""
    return px.filename(model.name, "life_model"), source_for(db, model)
