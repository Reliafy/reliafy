"""Download as Python for an accelerated life (ALT) model.

The script embeds the rows the model was fitted to as the app reads them
(:func:`backend.alt.build_inputs`: unusable rows dropped, a temperature typed
in °C or °F already in kelvin, blank inspection bounds and truncation read
as the fit reads them), makes the same ``AcceleratedLife(dist, life model)
.fit`` call, and prints the page's numbers: the distribution's shape and
the life-stress coefficients with their 90% two-sided intervals (the same
Wald intervals, a positive coefficient's on the log scale), and the
characteristic life at each tested stress level. Setting ``USE_STRESS``
adds the Calculator's numbers at that stress: the life there with its 90%
two-sided interval, and B50, B10 and B1 with B10's and B1's 90% one-sided
lower bounds.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from backend import alt as alt_fit
from backend.fitting import DISTRIBUTIONS, FitError
from backend.services import datasets as datasets_service
from backend.services import python_export as px
from backend.units import unit_in_text

# The SurPyval class each ALT distribution id fits with.
_DIST_CLASS = {"weibull": "Weibull", "lognormal": "LogNormal", "normal": "Normal", "exponential": "Exponential",
               "gamma": "Gamma"}


def _surpyval_life_model(life_model_id: str) -> str:
    """SurPyval's own name for the app's life-stress model (its key in
    ``accelerated_life.LIFE_MODELS``)."""
    target = alt_fit.LIFE_MODELS[life_model_id]["model"]
    for key, value in alt_fit._LM.items():
        if value is target:
            return key
    raise FitError("This life-stress model can't be exported.")  # pragma: no cover - every model is in the table


def _frame(inputs: dict, n_stress: int) -> tuple[pd.DataFrame, bool]:
    """The fit's inputs as one table, one row per data row."""
    x = np.asarray(inputs["x"], dtype=float)
    interval = x.ndim == 2
    cols: dict = {}
    if interval:
        cols["time_lower"], cols["time_upper"] = x[:, 0], x[:, 1]
    else:
        cols["time"] = x
    Z = np.asarray(inputs["Z"], dtype=float)
    for j in range(n_stress):
        cols[f"stress_{j + 1}"] = Z[:, j]
    if inputs.get("c") is not None:
        cols["censored"] = np.asarray(inputs["c"], dtype=int)
    if inputs.get("n") is not None:
        cols["count"] = np.asarray(inputs["n"], dtype=int)
    if inputs.get("t") is not None:
        t = np.asarray(inputs["t"], dtype=float)
        cols["entered_at"], cols["left_by"] = t[:, 0], t[:, 1]
    return pd.DataFrame(cols), interval


def python_script(name: str, df: pd.DataFrame, spec: dict) -> str:
    """The standalone script for an ALT model fitted to ``df`` by ``spec``."""
    spec = spec or {}
    distribution_id = spec.get("distribution_id", "weibull")
    life_model_id = spec.get("life_model_id", "arrhenius")
    if distribution_id not in _DIST_CLASS or life_model_id not in alt_fit.LIFE_MODELS:
        raise FitError("This model's distribution or life-stress model can't be exported.")
    entry = alt_fit.LIFE_MODELS[life_model_id]
    stress_cols = list(spec.get("stress_cols") or [])
    n_stress = len(stress_cols)
    kelvin_from = (list(spec.get("kelvin_from") or []) + [""] * n_stress)[:n_stress]
    inputs = alt_fit.build_inputs(df, spec.get("mapping", {}), stress_cols, kelvin_from)
    table, interval = _frame(inputs, n_stress)

    given = [str(v or "") for v in (spec.get("stress_labels") or [])]
    labels = [given[j] if j < len(given) and given[j] else stress_cols[j] for j in range(n_stress)]
    units = alt_fit.clean_stress_units(spec.get("stress_units"), n_stress)
    for j, src in enumerate(kelvin_from):
        if src:
            units[j] = "K"
            if labels[j] == stress_cols[j]:
                labels[j] = "Temperature"  # as the page names it (alt.fit)
    unit = unit_in_text(spec.get("unit") or "") or ""
    shown_unit = unit or "the model's time unit"
    dist_cls = _DIST_CLASS[distribution_id]
    sp_model = _surpyval_life_model(life_model_id)
    mapping = {k: v for k, v in (spec.get("mapping") or {}).items() if v}

    # What each column of the embedded table is, in the user's own names.
    described = []
    if interval:
        described.append(f"time_lower, time_upper: the inspection interval each unit failed in (from "
                         f"“{mapping.get('xl')}” and “{mapping.get('xr')}”); equal ends are a failure seen at "
                         "that time, and a unit never found failed has both ends at its last inspection")
    else:
        described.append(f"time: the time to failure or removal (from “{mapping.get('x')}”), in {shown_unit}")
    for j in range(n_stress):
        conv = (f", converted from {kelvin_from[j]} to kelvin as the app does (the "
                f"{entry['name']} model needs absolute temperature)" if kelvin_from[j] else "")
        u = f" in {units[j]}" if units[j] else ""
        described.append(f"stress_{j + 1}: {labels[j]}{u} (from “{stress_cols[j]}”){conv}")
    if "censored" in table:
        described.append(f"censored: 0 = failed, 1 = still running, -1 = failed before that time, "
                         f"2 = failed in the interval (from “{mapping.get('c') or 'the interval ends'}”)")
    if "count" in table:
        described.append(f"count: how many units the row stands for (from “{mapping.get('n')}”)")
    if "entered_at" in table:
        described.append("entered_at, left_by: the window each unit was watched in (truncation); "
                         "-inf / inf mean no limit")

    fit_args = ['    x=data[["time_lower", "time_upper"]].to_numpy()' if interval else '    x=data["time"].to_numpy()',
                "    Z=data[STRESS_COLUMNS].to_numpy(dtype=float)"]
    if "censored" in table:
        fit_args.append('    c=data["censored"].to_numpy()')
    if "count" in table:
        fit_args.append('    n=data["count"].to_numpy()')
    if "entered_at" in table:
        fit_args.append('    t=data[["entered_at", "left_by"]].to_numpy()')

    stress_words = ", ".join(f"{labels[j]}{(' (' + units[j] + ')') if units[j] else ''}" for j in range(n_stress))
    use_example = ", ".join("..." for _ in range(n_stress))
    lines = px.header(
        name or "Accelerated life model",
        f"an accelerated life model ({DISTRIBUTIONS[distribution_id]['name']} life, "
        f"{entry['name']} life-stress relationship).",
        unit=shown_unit,
        notes=[
            "An accelerated life model says how a unit's life changes with the stress it runs at "
            f"({stress_words}). The life at each stress follows the {entry['name']} relationship; "
            f"how spread out the failures are around that life follows a "
            f"{DISTRIBUTIONS[distribution_id]['name']} distribution.",
            "Intervals are 90% two-sided; the B-lives' bounds are 90% one-sided lower bounds "
            "(the life you can be 90% sure is at least that long).",
        ],
    )
    lines += [
        "import io",
        "import math",
        "",
        "import numpy as np",
        "import pandas as pd",
        "from scipy.stats import norm",
        f"from surpyval import AcceleratedLife, {dist_cls}",
        "from surpyval.univariate.regression.accelerated_life import LIFE_MODELS",
        "",
        *px.PRINT_HELPERS,
        "",
        "",
        f'UNIT = "{shown_unit}"',
        "",
        "# The use stress to work the life out at (the page's Calculator), one value per",
        f"# stress, in the units below: e.g. USE_STRESS = [{use_example}]. None skips it.",
        "USE_STRESS = None",
        "",
        "# The data the model was fitted to, one row per unit (or group of units):",
        *[ln for d in described for ln in px.comment("- " + d)],
        *px.csv_block("DATA", table),
        "data = pd.read_csv(io.StringIO(DATA))",
        f"STRESS_COLUMNS = {[f'stress_{j + 1}' for j in range(n_stress)]!r}",
        f"STRESS_NAMES = {[labels[j] for j in range(n_stress)]!r}",
        "",
        f"# Fit: a {DISTRIBUTIONS[distribution_id]['name']} life whose scale follows the "
        f"{entry['name']} life-stress relationship",
        "# (SurPyval's name for it is in quotes), by maximum likelihood.",
        f'model = AcceleratedLife({dist_cls}, LIFE_MODELS["{sp_model}"]).fit(',
        *[a + "," for a in fit_args],
        ")",
        "",
        "Z90 = norm.ppf(0.95)  # a 90% two-sided interval is the estimate plus or minus 1.645 standard errors",
        "names = list(model.parameter_names)",
        "values = np.asarray(model.params, dtype=float)",
        "k_dist = int(model.k_dist)  # the distribution's own parameters come first",
        "",
        "",
        "def support(i):",
        '    """(lower, upper) limits SurPyval declares for parameter i (None: no limit)."""',
        "    bounds = list(model.distribution.bounds)",
        "    phi = model.reg_model.phi_bounds",
        "    bounds += list(phi(np.asarray(model.data.Z)) if callable(phi) else phi)",
        "    b = bounds[i] if i < len(bounds) else None",
        "    return tuple(b) if b is not None else (None, None)",
        "",
        "",
        "def interval(i):",
        '    """The 90% two-sided interval on parameter i, as the app gives it."""',
        "    name = names[i]",
        "    lower, upper = support(i) if i >= k_dist else (None, None)",
        "    if i >= k_dist and (lower is not None or upper is not None):",
        "        # A coefficient that must stay on one side of a limit (positive, say): the",
        "        # interval is taken on the log of its distance to that limit, so it never crosses it.",
        "        if lower is not None and upper is not None:",
        "            return None",
        "        se = math.sqrt(float(np.asarray(model.covariance(), dtype=float)[i, i]))",
        "        v = float(values[i])",
        "        d = (v - lower) if lower is not None else (upper - v)",
        "        if not (np.isfinite(se) and d > 0):",
        "            return None",
        "        if lower is not None:",
        "            return [lower + d * math.exp(-Z90 * se / d), lower + d * math.exp(Z90 * se / d)]",
        "        return [upper - d * math.exp(Z90 * se / d), upper - d * math.exp(-Z90 * se / d)]",
        "    # Otherwise SurPyval's own Wald interval (a shape parameter's stays positive).",
        "    try:",
        '        ci = np.ravel(model.param_cb(name, alpha_ci=0.1, bound="two-sided", method="wald"))',
        "        if ci.size == 2 and np.all(np.isfinite(ci)):",
        "            return [float(ci[0]), float(ci[1])]",
        "    except Exception:",
        "        pass",
        "    se = np.ravel(model.standard_errors())",
        "    if se.size == values.size and np.isfinite(se[i]):",
        "        return [values[i] - Z90 * se[i], values[i] + Z90 * se[i]]",
        "    return None",
        "",
        "",
        "def show(i):",
        "    ci = interval(i)",
        '    print_interval(names[i], values[i], *(ci if ci else (None, None)))',
        "",
        "",
        "print(model)",
        "print()",
        'print("Shape of the life distribution:")',
        "for i in range(1, k_dist):  # parameter 0 is the life itself, which the stress sets",
        "    show(i)",
        'print("Life-stress coefficients:")',
        "for i in range(k_dist, len(names)):",
        "    show(i)",
        "",
        "# The characteristic life at each stress level tested (the scale of the life",
        "# distribution there; for a Weibull, the time by which 63.2% have failed).",
        'print("Characteristic life at each tested level:")',
        "levels = np.unique(data[STRESS_COLUMNS].to_numpy(dtype=float), axis=0)",
        "for row in levels:",
        "    life = float(np.ravel(model.phi(np.atleast_2d(row)))[0])",
        '    where = ", ".join(f"{n} {fmt(v)}" for n, v in zip(STRESS_NAMES, row))',
        '    print_value(f"Life at {where}", life, UNIT)',
        "",
        "if USE_STRESS is not None:",
        "    Zuse = np.atleast_2d(np.asarray(USE_STRESS, dtype=float))",
        "    life_use = float(np.ravel(model.phi(Zuse))[0])",
        "    # Its 90% two-sided interval by the delta method on the log of the life, so",
        "    # both ends stay positive (the slope of the log life in each coefficient,",
        "    # by central differences, against the coefficients' covariance).",
        "    coeffs = values[k_dist:]",
        "    cov = np.asarray(model.covariance(), dtype=float)[k_dist:, k_dist:]",
        "",
        "    def log_life(q):",
        "        return math.log(float(np.ravel(model.reg_model.phi(Zuse, *q))[0]))",
        "",
        "    grad = np.zeros(coeffs.size)",
        "    for i, value in enumerate(coeffs):",
        "        h = float(np.finfo(float).eps) ** (1.0 / 3.0) * (abs(float(value)) or 1.0)",
        "        up, down = coeffs.copy(), coeffs.copy()",
        "        up[i], down[i] = value + h, value - h",
        "        grad[i] = (log_life(up) - log_life(down)) / (2.0 * h)",
        "    se = math.sqrt(float(grad @ cov @ grad))",
        '    print_interval("Life at the use stress", life_use, life_use * math.exp(-Z90 * se),',
        "                   life_use * math.exp(Z90 * se), UNIT)",
        "    # B-lives: the time by which 50%, 10% and 1% have failed at the use stress,",
        "    # B10 and B1 with the life you can be 90% sure they are at least.",
        "    b50, b10, b1 = np.ravel(model.qf(np.array([0.5, 0.1, 0.01]), Zuse))",
        '    lows = np.ravel(model.quantile_cb(np.array([0.1, 0.01]), Zuse, alpha_ci=0.1, bound="lower",',
        '                                      method="wald"))',
        '    print_value("B50 at the use stress", b50, UNIT)',
        '    print_bound("B10 at the use stress", b10, lows[0], unit=UNIT)',
        '    print_bound("B1 at the use stress", b1, lows[1], unit=UNIT)',
    ]
    return px.assemble(lines)


def export_python(db, model, owners) -> tuple[str, str]:
    """``(filename, source)`` for a saved ALT model (``AltModelDoc``): the
    script refits it from its dataset, embedded."""
    del owners  # the dataset is the model's own: read in its owner's scope, as a refit does
    dataset = datasets_service.get_dataset(db, model.dataset_id, owner_id=model.owner_id)
    if dataset is None:
        raise FitError("The data this model was fitted to was deleted, so it can't be exported as Python.")
    df = datasets_service.load_dataframe(dataset)
    source = python_script(model.name, df, model.spec or {})
    return px.filename(model.name, "accelerated_life_model"), source
