"""Download as Python for regression models: covariates fixed per unit
(proportional hazards, AFT, proportional odds, additive hazards, Cox PH,
Buckley-James, shared frailty, ...) and covariates that change over time.

The script embeds the data as the app prepared it (censor flags the right way
round, times in the model's unit, inspection rows read, text covariates as
categories), makes the same SurPyval ``fit_from_df`` (or
``fit_tvc_..._from_df``) call the app made, then prints the page's numbers:
the baseline parameters and coefficients with their 90% two-sided intervals,
each coefficient's ratio, and the median, B10 and mean life at the covariate
means where the page gives them.
"""

from __future__ import annotations

from typing import Optional

import numpy as np
import pandas as pd

from backend import fitting, more_models, regression_diagnostics, tvc, unit_column
from backend.levels import Z
from backend.services import python_export as px
from backend.units import unit_in_text

_WRAPPERS = {"ph": "PH", "aft": "AFT", "po": "PO", "ah": "AH"}

# The same Wald interval the app uses (backend/param_intervals.py), written
# out so the script needs nothing from Reliafy.
WALD_HELPER = f'''
Z90 = {Z!r}  # the normal quantile for a 90% two-sided interval


def wald_interval(value, se, lower=None, upper=None):
    """A 90% two-sided interval for a parameter from its standard error.

    A parameter that must stay above a bound (a Weibull shape above 0, say)
    gets its interval on the log scale of its distance from that bound, so the
    interval never crosses it; one held between two bounds uses the logit
    scale; a free parameter (a coefficient) gets value +/- 1.645 x se."""
    def finite(v):
        return v is not None and np.isfinite(float(v))

    if not (finite(value) and finite(se)) or se < 0:
        return None
    value, se = float(value), float(se)
    lo = float(lower) if finite(lower) else None
    hi = float(upper) if finite(upper) else None

    def exp(t):
        return math.exp(t) if t < 709 else math.inf

    if lo is None and hi is None:
        return [value - Z90 * se, value + Z90 * se]
    if lo is not None and hi is not None:
        width = hi - lo
        if width <= 0 or not (lo < value < hi):
            return None
        u = (value - lo) / width
        k = Z90 * se / (width * u * (1.0 - u))
        logit = math.log(u / (1.0 - u))

        def expit(t):
            return 1.0 / (1.0 + math.exp(-t)) if t >= 0 else math.exp(t) / (1.0 + math.exp(t))

        return [lo + width * expit(logit - k), lo + width * expit(logit + k)]
    if lo is not None:
        d = value - lo
        if d <= 0:
            return None
        return [lo + d * exp(-Z90 * se / d), lo + d * exp(Z90 * se / d)]
    d = hi - value
    if d <= 0:
        return None
    return [hi - d * exp(Z90 * se / d), hi - d * exp(-Z90 * se / d)]


def label(name):
    """A parameter's name as a printed label (no colons: "a:b" -> "a * b")."""
    return str(name).replace(":", " * ")
'''.strip("\n").splitlines()


def label(name) -> str:
    """The printed label of a parameter's name (as the script's ``label``)."""
    return str(name).replace(":", " * ")


def fitter_code(distribution: str, frailty_family: Optional[str] = None) -> str:
    """The SurPyval expression for the app's fitter of ``distribution``."""
    import surpyval

    entry = fitting.REGRESSION_MODELS.get(distribution)
    if entry is None:
        raise fitting.FitError(f"'{distribution}' isn't a regression model this download knows.")
    if entry.get("frailty") and frailty_family:
        return f"surpyval.Frailty(surpyval.{entry['baseline']}, family={frailty_family!r})"
    fitter = entry["fitter"]
    for name in dir(surpyval):
        if not name.startswith("_") and getattr(surpyval, name) is fitter:
            return f"surpyval.{name}"
    base, _, wrap = distribution.rpartition("_")
    dist = getattr(fitter, "distribution", None)
    dist_name = getattr(dist, "name", None) if dist is not None else None
    if wrap in _WRAPPERS and dist_name and getattr(surpyval, dist_name, None) is dist:
        return f"surpyval.{_WRAPPERS[wrap]}(surpyval.{dist_name})"
    if wrap in _WRAPPERS and base == "loglogistic":
        return f"surpyval.{_WRAPPERS[wrap]}(surpyval.LogLogistic)"
    raise fitting.FitError(f"{entry['name']} can't be downloaded as Python yet.")


def prepare(spec: dict, df: pd.DataFrame) -> tuple[pd.DataFrame, dict, dict, list[str]]:
    """The data and options as ``fitting.fit`` reads them before it picks a
    fitter: ``(df, mapping, options, notes)``, where ``notes`` says in words
    what was done to the data (a converted unit, flipped censor flags)."""
    from backend import competing_risks

    mapping = competing_risks.plain_mapping(dict(spec.get("mapping") or {}))
    options = dict(spec.get("options") or {})
    unit = spec.get("unit")
    notes: list[str] = []
    u_col = options.pop(unit_column.UNIT_COLUMN_KEY, None)
    if u_col:
        try:
            df, done = unit_column.convert(df, mapping, str(u_col), unit)
        except ValueError as exc:
            raise fitting.FitError(str(exc)) from exc
        notes.append(f"Every time was converted to {unit_in_text(done['to']) or done['to']} using the "
                     f"unit column “{u_col}”, as the app did before the fit.")
    c_invert = bool(options.pop(fitting.CENSOR_INVERT_KEY, False)) and bool(mapping.get("c"))
    c_map = options.pop(fitting.CENSOR_MAP_KEY, None) if mapping.get("c") else None
    options.pop(fitting.CENSOR_MAP_KEY, None)
    options.pop(fitting.STRICT_INTERVALS_KEY, None)
    if c_map:
        df = fitting.map_censor_column(df, mapping["c"], c_map)
        notes.append(f"The status column “{mapping['c']}” was read as censor flags ({_codes(c_map)}).")
    elif c_invert:
        df = fitting.invert_censor_column(df, mapping["c"])
        notes.append(f"The status column “{mapping['c']}” used 1 for a failure; it was flipped to "
                     "0 = failed, 1 = still running, as the app did.")
    return df, mapping, options, notes


def _codes(c_map: dict) -> str:
    return ", ".join(f"{k} = {v}" for k, v in (c_map or {}).items())


def _used_columns(df: pd.DataFrame, names: list, formula: Optional[str]) -> list:
    """The columns the fit reads, in the data's order."""
    keep = {str(n) for n in names if n}
    if formula:
        keep |= {str(c) for c in df.columns if str(c) in formula}
    return [c for c in df.columns if str(c) in keep]


def _data_lines(df: pd.DataFrame, columns: list) -> tuple[list[str], str]:
    """The embedded data and the line that reads it back (text columns stay
    text, so an id like 007 isn't read as the number 7)."""
    frame = df[columns].copy()
    text_cols = [str(c) for c in frame.columns if not (pd.api.types.is_numeric_dtype(frame[c])
                                                       or pd.api.types.is_bool_dtype(frame[c]))]
    dtype = (", dtype={" + ", ".join(f"{c!r}: str" for c in text_cols) + "}") if text_cols else ""
    return px.csv_block("DATA", frame), f"data = pd.read_csv(io.StringIO(DATA){dtype})"


def _kwargs_text(kwargs: dict) -> list[str]:
    return [f"    {k}={px.literal(v)}," for k, v in kwargs.items()]


def _shown_unit(spec: dict, results: dict) -> str:
    return unit_in_text(results.get("unit") or spec.get("unit") or "") or ""


def _effect_lines(entry: dict, distribution: str, results: dict) -> list[str]:
    """Printing the baseline, the coefficients and their ratios, as the page."""
    effect = entry.get("effect", "hazard")
    ratio_label = fitting._RATIO_LABELS.get(effect)
    sign = fitting._RATIO_SIGN.get(effect, 1.0)
    no_max = bool(results.get("no_finite_maximum"))
    lines = [
        "",
        "# ---- The numbers on the page ----",
        "params = np.atleast_1d(np.asarray(model.params, dtype=float))",
        "k = int(getattr(model, 'k_dist', 0) or 0)  # how many of them are the baseline's",
        "try:",
        "    ses = np.asarray(model.standard_errors(), dtype=float).ravel()",
        "    ses = ses if ses.size == params.size else None",
        "except Exception:  # no standard errors (a Cox model may have none for its baseline)",
        "    ses = None",
        "",
        "",
        "def interval(i, lower=None, upper=None):",
        f"    if {no_max!r} or ses is None or not np.isfinite(ses[i]):",
        "        return None",
        "    return wald_interval(params[i], ses[i], lower, upper)",
        "",
    ]
    if no_max:
        lines += px.comment("The app found this fit has no finite maximum, so it shows no intervals: "
                            "they would come from a covariance that means nothing.")
    if entry.get("frailty"):
        lines += [
            "# The baseline distribution's parameters, from SurPyval's summary table (90% two-sided).",
            "table = model.summary(alpha_ci=0.10).reset_index()",
            'low_col = next(c for c in table.columns if str(c).startswith("coef lower"))',
            'high_col = next(c for c in table.columns if str(c).startswith("coef upper"))',
            'for row in table[table["part"] == "baseline"].to_dict("records"):',
            f'    if {no_max!r}:',
            '        print_value(f"Baseline {label(row[\'name\'])}", row["coef"])',
            "    else:",
            '        print_interval(f"Baseline {label(row[\'name\'])}", row["coef"], row[low_col], row[high_col])',
        ]
    else:
        lines += [
            "# The baseline distribution's parameters (none for a Cox-type model, whose",
            "# baseline is a step curve estimated from the data).",
            "base = getattr(model, 'distribution', None)",
            "names = list(getattr(base, 'parameter_names', None) or [f'p{i}' for i in range(k)])",
            "bounds = dict(zip(names, list(getattr(base, 'bounds', None) or [])))",
            "for i, name in enumerate(names):",
            "    lower, upper = (tuple(bounds.get(name) or ()) + (None, None))[:2]",
            "    ci = interval(i, lower, upper)",
            '    print_interval(f"Baseline {label(name)}", params[i], *(ci or (None, None)))',
        ]
    lines += [
        "",
        "# Each covariate's coefficient, with its 90% two-sided interval.",
        "features = list(getattr(model, 'feature_names', None) or [f'b{j}' for j in range(params.size - k)])",
        "cis = [interval(k + j) for j in range(len(features))]",
    ]
    if distribution == "buckley_james" and not no_max:
        lines += [
            "# Buckley-James has no standard errors: the app's intervals come from 200",
            "# bootstrap resamples (with a fixed seed, so they repeat exactly).",
            "wald_cis = cis",
            "try:",
            "    boot = np.asarray(model.bootstrap_ci(alpha_ci=0.10, n_boot=200, random_state=0), dtype=float)",
            "    if boot.shape == (len(features), 2):",
            "        cis = [list(b) for b in boot]",
            "except Exception:",
            "    pass",
        ]
    else:
        lines.append("wald_cis = cis")
    lines += [
        "for j, name in enumerate(features):",
        "    value = params[k + j]",
        '    print_interval(f"Coefficient {label(name)}", value, *(cis[j] or (None, None)))',
    ]
    if ratio_label:
        words = ratio_label[0].upper() + ratio_label[1:]
        meaning = {
            "hazard": "the hazard is multiplied by exp(coefficient) for each unit of the covariate",
            "aft": "the life is multiplied by exp(-coefficient): above 1 lives longer",
            "odds": "the odds of having failed are multiplied by exp(-coefficient)",
        }[effect]
        lines += [
            f"    # The {ratio_label}: {meaning}.",
            f"    ratio = math.exp({sign!r} * value)",
            "    ends = sorted(math.exp(" + repr(sign) + " * v) for v in wald_cis[j]) if wald_cis[j] else (None, None)",
            f'    print_interval(f"{words} {{label(name)}}", ratio, *ends)',
        ]
    frailty = results.get("frailty")
    if entry.get("frailty") and frailty:
        lr = "lr" if frailty.get("theta_ci_method") == "profile likelihood" else None
        kw = ', method="lr"' if lr else ""
        lines += [
            "",
            "# The shared frailty: how much the groups differ (theta = 0: not at all), with its",
            f"# 90% two-sided interval ({frailty.get('theta_ci_method') or 'Wald'}).",
            "try:",
            f'    theta_ci = np.asarray(model.param_cb("theta", alpha_ci=0.10{kw}), dtype=float).ravel()',
            "except Exception:",
            "    theta_ci = np.array([])",
            'print_interval("Frailty variance theta", model.theta,',
            "               *(theta_ci if theta_ci.size == 2 else (None, None)))",
        ]
    return lines


def _metrics_lines(results: dict, shown_unit: str) -> list[str]:
    """The median, B10 and mean life at the covariate row the page uses."""
    at = results.get("at_covariate_means")
    if not at:
        return []
    row = {c["name"]: c["value"] for c in at.get("covariates") or []}
    unit = px.literal(shown_unit)
    lines = [
        "",
        "# ---- Life at the covariate means ----",
        *px.comment("A regression model has no single life: it depends on the covariates. The page gives "
                    "the median, B10 and mean life with each numeric covariate at its average over the data "
                    "and each categorical one at its most common level. This is that row."),
        f"Z = pd.DataFrame({{name: [value] for name, value in {px.literal(row)}.items()}}) if {bool(row)!r} else None",
        "with np.errstate(all='ignore'):",
        "    q = np.asarray(model.qf(np.array([0.5, 0.1, 1e-6, 1.0 - 1e-9]), Z), dtype=float).ravel()",
        "median, b10, first, last = (float(v) for v in q[:4])",
        "mean_life = None",
        "if np.isfinite(first) and np.isfinite(last) and 0 < first < last:",
        "    # The mean life is the area under the survival curve, on a fine grid to where",
        "    # almost nothing survives.",
        "    t = np.concatenate([[0.0], np.geomspace(first, last, 4000)])",
        "    with np.errstate(all='ignore'):",
        "        s = np.asarray(model.sf(t, Z), dtype=float).ravel()",
        "    if s.size == t.size and np.all(np.isfinite(s)):",
        "        trapezoid = getattr(np, 'trapezoid', None) or np.trapz",
        "        mean_life = float(trapezoid(s, t))",
        "",
        "",
        "def life(v):",
        "    return v if v is not None and np.isfinite(v) and v >= 0 else None",
        "",
        "",
        f'print_value("Median life at the covariate means", life(median), {unit})',
        f'print_value("B10 life at the covariate means", life(b10), {unit})',
        f'print_value("Mean life at the covariate means", life(mean_life), {unit})',
    ]
    return lines


def _common_head(model, spec: dict, results: dict, what: str, notes: list[str]) -> list[str]:
    shown = _shown_unit(spec, results)
    return px.header(model.name or "Regression model", what, unit=shown, notes=notes) + [
        "import io",
        "import math",
        "",
        "import numpy as np",
        "import pandas as pd",
        "import surpyval",
        "",
        *px.PRINT_HELPERS,
        "",
        "",
        *WALD_HELPER,
        "",
    ]


def script(model, df: pd.DataFrame) -> str:
    """The Download as Python script of a saved regression model (``results``
    kind "regression", covariates fixed or changing over time), from the raw
    dataset ``df``. Raises :class:`fitting.FitError` when it can't be made."""
    spec = model.spec or {}
    results = model.results or {}
    distribution = spec.get("distribution_id") or model.distribution_id
    if distribution not in fitting.REGRESSION_MODELS:
        raise fitting.FitError("This model isn't a regression model.")
    df, mapping, options, notes = prepare(spec, df)
    if tvc.is_tvc(mapping):
        return _tvc_script(model, spec, results, distribution, df, mapping, notes)
    return _fixed_script(model, spec, results, distribution, df, mapping, options, notes)


def _fixed_script(model, spec, results, distribution, df, mapping, options, notes) -> str:
    cox_opts = options.get(regression_diagnostics.COX_KEY)
    family = options.get(more_models.FAMILY_KEY)
    mapping = more_models.check_group(distribution, mapping, spec.get("covariates"))
    inputs = fitting.regression_inputs(distribution, df, mapping, spec.get("covariates"), spec.get("formula"),
                                       cox_opts, family)
    entry = inputs["entry"]
    kwargs = {**inputs["fit_kwargs"], **inputs["cox_kwargs"]}
    cleaned = inputs["cox_opts"] or {}
    columns = _used_columns(inputs["df"], [v for k, v in kwargs.items() if k.endswith("_col")]
                            + list(kwargs.get("Z_cols") or []),
                            kwargs.get("formula"))
    data, read = _data_lines(inputs["df"], columns)
    shown = _shown_unit(spec, results)
    covs = ", ".join(spec.get("covariates") or []) or (spec.get("formula") or "")
    what = f"{entry['name']}, life explained by {covs}" if covs else entry["name"]
    lines = _common_head(model, spec, results, what, notes)
    lines += [
        "# ---- The data ----",
        *px.comment("One row per unit, as the app read it. Censoring: 0 = failed, 1 = still running "
                    "(right-censored), -1 = failed before that time, 2 = failed between two times."
                    + (" Text covariates are categories: each level is compared with a base level."
                       if "formula" in kwargs and not spec.get("formula") else "")),
        *data,
        read,
        "",
        "# ---- The fit: the same SurPyval call the app made ----",
        f"model = {fitter_code(distribution, family)}.fit_from_df(",
        "    data,",
        *_kwargs_text(kwargs),
        ")",
        "print(model)",
    ]
    if cleaned.get("cluster"):
        lines += ["", *px.comment(f"The app's Diagnostics tab also compares robust standard errors clustered by "
                                  f"“{cleaned['cluster']}” with these; they don't change the numbers below.")]
    lines += _effect_lines(entry, distribution, results)
    lines += _metrics_lines(results, shown)
    return px.assemble(lines)


def _tvc_script(model, spec, results, distribution, df, mapping, notes) -> str:
    from backend.formula_check import FormulaRejected, check_formula

    entry = fitting.REGRESSION_MODELS[distribution]
    if not hasattr(entry["fitter"], "fit_tvc_from_df"):
        raise fitting.FitError(f"{entry['name']} can't fit covariates that change over time.")
    mapping = {k: v for k, v in mapping.items() if v}
    covariates, formula = spec.get("covariates"), spec.get("formula")
    layout = tvc._check(mapping, covariates, formula, entry["name"])
    if formula:
        try:
            formula = check_formula(formula, df.columns)
        except FormulaRejected as exc:
            raise fitting.FitError(str(exc)) from exc
        covariates = None
    elif covariates:
        df, auto = fitting.covariates_as_formula(df, covariates)
        if auto:
            formula = check_formula(auto, df.columns)
    time_cols = [mapping["xl"], mapping["xr"]] if layout == "intervals" else [mapping["x"]]
    df = tvc._numeric(df, [*time_cols, mapping["c"]])
    columns = _used_columns(df, [mapping["i"], *time_cols, mapping["c"], mapping.get("n"),
                                 *(covariates or [])], formula)
    data, read = _data_lines(df, columns)
    z = f"formula={formula!r}" if formula else f"Z_cols={list(covariates)!r}"
    n = f", n_col={mapping['n']!r}" if mapping.get("n") else ""
    fitter = fitter_code(distribution)
    if layout == "intervals":
        call = (f"model = {fitter}.fit_tvc_from_df(data, {mapping['i']!r}, {mapping['xl']!r}, "
                f"{mapping['xr']!r}, {mapping['c']!r}, {z}{n})")
        shape = ("Each row is a stretch of one item's life with the covariate values that held over it: "
                 "its start, its stop and whether it ended in a failure (0) or not (1).")
    else:
        zs = "None" if formula else repr(list(covariates))
        extra = f", formula={formula!r}" if formula else ""
        call = (f"model = {fitter}.fit_tvc_timeline_from_df(data, {mapping['i']!r}, {mapping['x']!r}, "
                f"{zs}, {mapping['c']!r}{extra}{n})")
        shape = ("Each row is the time an item's covariate values took effect; an item's last row is when "
                 "it failed (0) or was last seen running (1).")
    covs = ", ".join(covariates or []) or (formula or "")
    lines = _common_head(model, spec, results,
                         f"{entry['name']} with covariates that change over time ({covs})", notes)
    lines += [
        "# ---- The data ----",
        *px.comment(shape),
        *data,
        read,
        "",
        "# ---- The fit: the same SurPyval call the app made ----",
        call,
        "print(model)",
    ]
    lines += _effect_lines(entry, distribution, results)
    lines += _metrics_lines(results, _shown_unit(spec, results))
    return px.assemble(lines)

