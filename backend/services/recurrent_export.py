"""Download as Python for a repairable (recurrent-event) model.

The script embeds the events exactly as the app hands them to SurPyval: each
system's end of observation already added as a ``censored = 1`` row (see
``backend.recurrent_models.observed``), covariates already coded (a text
column as one 0/1 column per level against its reference level), and any
observation windows. It then makes the same SurPyval call the app made and
prints the numbers the model page shows, at the app's levels (90% two-sided
intervals; the demonstrated MTBF's 90% one-sided lower bound).

Every saved kind is covered: the minimal-repair processes (Crow-AMSAA,
Duane, HPP, Cox-Lewis; with observation gaps too), proportional intensity
(covariates), the imperfect-repair models (Kijima I and II, ARA, ARI, G1)
and a model built from typed-in parameters (rebuilt from them).
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from backend import recurrent as rec
from backend import recurrent_models as extra
from backend.fitting import FitError
from backend.services import datasets as datasets_service
from backend.services import python_export as px
from backend.units import unit_in_text

_NHPP_CLASS = {"crow_amsaa": "CrowAMSAA", "duane": "Duane", "hpp": "HPP", "cox_lewis": "CoxLewis"}
_BASELINE_CLASS = {"crow_amsaa": "CrowAMSAA", "duane": "Duane", "cox_lewis": "CoxLewis"}


def _unit_words(doc) -> str:
    unit = (doc.results or {}).get("unit") or (doc.spec or {}).get("unit") or ""
    return unit_in_text(unit) or ""


def _frame(data: dict, extra_cols: pd.DataFrame | None = None) -> pd.DataFrame:
    """The fitter's per-row inputs as a table: system, time, censored and,
    when given, count and entry (left truncation)."""
    out = pd.DataFrame({"system": np.asarray(data["i"]).astype(str),
                        "time": np.asarray(data["x"], dtype=float),
                        "censored": np.asarray(data["c"], dtype=int)})
    if data.get("n") is not None:
        out["count"] = np.asarray(data["n"], dtype=int)
    if data.get("tl") is not None:
        out["entry"] = np.asarray(data["tl"], dtype=float)
    if extra_cols is not None:
        out = pd.concat([out, extra_cols.reset_index(drop=True)], axis=1)
    return out


_READ = '''
events = pd.read_csv(io.StringIO(EVENTS), dtype={"system": str}, keep_default_na=False)
data = {
    "x": events["time"].to_numpy(dtype=float),   # when each event happened
    "i": events["system"].to_numpy(),            # which system it happened to
    "c": events["censored"].to_numpy(dtype=int),  # 0 = a failure, 1 = end of observation
}
if "count" in events.columns:
    data["n"] = events["count"].to_numpy(dtype=int)  # failures on that row
if "entry" in events.columns:
    data["tl"] = events["entry"].to_numpy(dtype=float)  # when the system came under observation
'''.strip("\n").splitlines()


_SUMMARY = '''

def parameter_table(model):
    """Each parameter's estimate and 90% two-sided interval, as the app reads
    them: SurPyval's summary() where the model has one, else param_cb."""
    params = np.ravel(np.asarray(model.params, dtype=float))
    coeffs = getattr(model, "coeffs", None)
    if coeffs is not None and params.size < len(model.parameter_names):
        params = np.concatenate([params, np.ravel(np.asarray(coeffs, dtype=float))])
    rows = {}
    if callable(getattr(model, "summary", None)):
        try:
            with warnings.catch_warnings(), np.errstate(all="ignore"):
                warnings.simplefilter("ignore")
                table = model.summary(alpha_ci=1 - LEVEL)
        except Exception:
            return {str(n): (float(v), None, None) for n, v in zip(model.parameter_names, params)}
        lo_col = next(c for c in table.columns if str(c).startswith("lower"))
        hi_col = next(c for c in table.columns if str(c).startswith("upper"))
        for name, row in table.iterrows():
            lo, hi = float(row[lo_col]), float(row[hi_col])
            ok = np.isfinite(lo) and np.isfinite(hi)
            rows[str(name)] = (float(row["estimate"]), lo if ok else None, hi if ok else None)
        return rows
    for name, value in zip(model.parameter_names, params):
        lo = hi = None
        try:
            with warnings.catch_warnings(), np.errstate(all="ignore"):
                warnings.simplefilter("ignore")
                cb = np.asarray(model.param_cb(name, alpha_ci=1 - LEVEL), dtype=float).ravel()
            if cb.size == 2 and np.all(np.isfinite(cb)):
                lo, hi = float(cb[0]), float(cb[1])
        except Exception:
            pass
        rows[str(name)] = (float(value), lo, hi)
    return rows
'''.splitlines()


def _common_head(doc, what: str, notes: list[str], imports: list[str]) -> list[str]:
    unit = _unit_words(doc)
    lines = px.header(doc.name or "Repairable model", what, notes=notes, unit=unit)
    lines += [
        "import io",
        "import warnings",
        "",
        "import numpy as np",
        "import pandas as pd",
        "import surpyval",
        f"from surpyval.recurrent import {', '.join(sorted(set(imports)))}",
        "",
        *px.PRINT_HELPERS,
        "",
        "LEVEL = 0.90  # every interval is 90% two-sided; the demonstrated MTBF's bound is 90% one-sided",
        f"UNIT = {unit!r}",
        "",
    ]
    return lines


# ---- Minimal repair: Crow-AMSAA, Duane, HPP, Cox-Lewis -------------------------------


def _nhpp_script(doc, df: pd.DataFrame) -> str:
    spec = doc.spec or {}
    mapping = spec.get("mapping") or {}
    model_id = spec.get("model_id", "crow_amsaa")
    inputs = rec.build_inputs(df, mapping)
    windows = None
    if spec.get("windows") or mapping.get("ws"):
        spans = extra.windows_from(df, mapping, spec.get("windows"))
        if spans:
            inputs, _ = extra.apply_windows(inputs, spans)
            windows = inputs["windows"]
    t_end = rec.end_of_observation(inputs)
    data = extra.observed(inputs)[0]
    cls = _NHPP_CLASS[model_id]
    twin = model_id == "duane" and rec.duane_needs_twin()
    notes = [
        f"Model: {rec.MODELS[model_id]['name']}, a minimal-repair model: each repair puts the system back as "
        "it was just before the failure, and the failure rate follows a trend over the system's age.",
        "Each row is one event: a failure (censored = 0), or where a system's record ends with no failure "
        "(censored = 1).",
    ]
    if windows:
        notes.append("Each system was watched over the windows in WINDOWS; time outside them is a gap.")
    imports = [cls] + (["CrowAMSAA"] if (model_id == "crow_amsaa" or twin) else [])
    lines = _common_head(doc, "a repairable-system model (failures over time)", notes, imports)
    lines += ["# The events, after the app's preparation.", *px.csv_block("EVENTS", _frame(data)), ""]
    lines += _READ
    if windows:
        lines += ["", "# Each system's observation windows: [start, end] pairs.",
                  f"WINDOWS = {px.literal({str(k): [list(map(float, w)) for w in v] for k, v in windows.items()})}",
                  'data["windows"] = {k: [tuple(w) for w in v] for k, v in WINDOWS.items()}']
    lines += ["", "# The latest time any system was watched: the rates below are worked out here.",
              f"END = {px.num(t_end)}", ""]
    if model_id == "crow_amsaa":
        lines += _CROW_FIT
    else:
        lines += ["# Fit the model by maximum likelihood.",
                  "with warnings.catch_warnings():",
                  '    warnings.simplefilter("ignore")',
                  f"    model = {cls}.fit(**data)"]
    if twin:
        lines += _DUANE_TWIN
    else:
        lines += ["bounds_model = model"]
    lines += ["", f"MODEL_ID = {model_id!r}", *_NHPP_REPORT]
    return px.assemble(lines)


_CROW_FIT = '''
# Fit Crow-AMSAA by maximum likelihood. When the search doesn't reach a
# verified best fit (it can wander when systems are watched for different
# lengths), the app starts it again from the same fit to the times rescaled
# to 0..1, and keeps whichever fits the data better. This does the same.
with warnings.catch_warnings():
    warnings.simplefilter("ignore", UserWarning)
    model = CrowAMSAA.fit(**data)
if getattr(model, "maximum", "verified") != "verified":
    scale = float(np.max(data["x"])) if np.size(data["x"]) else 0.0
    if np.isfinite(scale) and scale > 0:
        scaled = dict(data, x=np.asarray(data["x"], dtype=float) / scale)
        if data.get("tl") is not None:
            scaled["tl"] = np.asarray(data["tl"], dtype=float) / scale
        if data.get("windows"):
            scaled["windows"] = {k: [(a / scale, b / scale) for a, b in v] for k, v in data["windows"].items()}
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                unit_fit = CrowAMSAA.fit(**scaled)
            a0, b0 = (float(v) for v in np.asarray(unit_fit.params, dtype=float))
            if np.isfinite(a0) and np.isfinite(b0):
                retry = CrowAMSAA.fit(**data, init=[a0 * scale, b0])
                if -retry.neg_ll() >= -model.neg_ll() or not np.all(np.isfinite(model.params)):
                    model = retry
        except Exception:
            pass'''.strip("\n").splitlines()


_DUANE_TWIN = '''
# SurPyval 0.26's Duane fit gives standard errors that are too small (its
# numerical step is too big for the rate constant b). Duane is the same
# power-law process as Crow-AMSAA, with the same likelihood, so the app takes
# Duane's intervals from the Crow-AMSAA fit to the same data. Fixed in later
# SurPyval releases, where this step isn't needed.
twin = None
if tuple(int(p) for p in surpyval.__version__.split(".")[:2]) < (0, 27):
    try:
        with warnings.catch_warnings(), np.errstate(all="ignore"):
            warnings.simplefilter("ignore")
            twin = CrowAMSAA.fit(**data)
        if not np.all(np.isfinite(np.asarray(twin.params, dtype=float))):
            twin = None
    except Exception:
        twin = None
bounds_model = twin if twin is not None else model'''.strip("\n").splitlines()


_NHPP_REPORT = '''

def interval(m, name):
    """A parameter's 90% two-sided interval (None when there isn't one)."""
    with warnings.catch_warnings(), np.errstate(all="ignore"):
        warnings.simplefilter("ignore")
        lo, hi = (float(v) for v in np.asarray(m.param_cb(name, alpha_ci=1 - LEVEL), dtype=float))
    return [lo, hi] if np.isfinite(lo) and np.isfinite(hi) and lo <= hi else None


names = list(model.parameter_names)
values = [float(v) for v in np.asarray(model.params, dtype=float)]
intervals = {}
if bounds_model is not model:
    # Duane from its Crow-AMSAA twin: Duane's alpha is the twin's beta, and
    # b = scale ** -beta, its interval by the delta method on the log scale.
    from statistics import NormalDist

    z = NormalDist().inv_cdf(1 - (1 - LEVEL) / 2)
    intervals["alpha"] = interval(twin, "beta")
    scale_, beta_ = (float(v) for v in np.asarray(twin.params, dtype=float))
    b = scale_ ** (-beta_)
    J = np.array([[0.0, 1.0], [-beta_ * b / scale_, -b * np.log(scale_)]])
    var = float((J @ np.asarray(twin.covariance(), dtype=float) @ J.T)[1, 1])
    if b > 0 and np.isfinite(var) and var >= 0:
        se_log = np.sqrt(var) / b
        intervals["b"] = [b * np.exp(-z * se_log), b * np.exp(z * se_log)]
else:
    try:
        for name in names:
            ci = interval(model, name)
            if ci is not None:
                intervals[name] = ci
    except Exception:
        intervals = {}

print(f"{MODEL_ID} fitted to {len(set(data['i'].tolist()))} systems")
for name, value in zip(names, values):
    ci = intervals.get(name)
    print_interval(f"Parameter {name}", value, *(ci or (None, None)))

# The growth shape: above 1 the failures come faster as the systems age
# (deteriorating), below 1 slower (improving). The verdict follows its 90%
# interval: a trend is called only when the interval leaves out 1.
GROWTH = {"crow_amsaa": ("beta", 1.0), "duane": ("alpha", 1.0), "cox_lewis": ("beta", 0.0)}
if MODEL_ID in ("crow_amsaa", "duane"):
    shape = GROWTH[MODEL_ID][0]
    ci = intervals.get(shape)
    print_interval("Growth shape (beta)", values[names.index(shape)], *(ci or (None, None)))
if MODEL_ID in GROWTH:
    shape, no_trend = GROWTH[MODEL_ID]
    value, ci = values[names.index(shape)], intervals.get(shape)
    if ci:
        verdict = "deteriorating" if ci[0] > no_trend else "improving" if ci[1] < no_trend else "stable"
    else:
        verdict = "deteriorating" if value > no_trend else "improving" if value < no_trend else "stable"
    print(f"Trend: {verdict}")

# The failure rate (ROCOF) and the MTBF (its reciprocal) at the end of
# observation, with 90% two-sided intervals, and the demonstrated MTBF: the
# MTBF we can be 90% sure is at least this. Crow-AMSAA uses Crow's exact
# bounds where they apply (every system watched over the same time), else
# the Wald (delta-method) bounds.
t = np.array([float(END)])
with np.errstate(all="ignore"):
    rocof = float(np.ravel(np.asarray(model.iif(t), dtype=float))[0])
mtbf = 1.0 / rocof if np.isfinite(rocof) and rocof > 0 else None
rocof_ci = mtbf_ci = demonstrated = None
for method in (("crow", "wald") if MODEL_ID == "crow_amsaa" else ("wald",)):
    try:
        with warnings.catch_warnings(), np.errstate(all="ignore"):
            warnings.simplefilter("ignore")
            mtbf_ci = np.ravel(np.asarray(bounds_model.mtbf_cb(t, alpha_ci=1 - LEVEL, method=method), dtype=float))
            rocof_ci = np.ravel(np.asarray(bounds_model.iif_cb(t, alpha_ci=1 - LEVEL, method=method), dtype=float))
            lower = float(np.ravel(np.asarray(bounds_model.mtbf_cb(t, alpha_ci=1 - LEVEL, bound="lower",
                                                                   method=method), dtype=float))[0])
            point = float(np.ravel(np.asarray(bounds_model.iif(t), dtype=float))[0])
    except Exception:
        rocof_ci = mtbf_ci = None
        continue
    demonstrated = (1.0 / point if point > 0 else None, lower if np.isfinite(lower) else None)
    print(f"Bounds method: {method}")
    break
print_value("End of observation", END, UNIT)
print_interval("ROCOF at end", rocof, *(rocof_ci if rocof_ci is not None else (None, None)))
print_interval("MTBF at end", mtbf, *(mtbf_ci if mtbf_ci is not None else (None, None)), unit=UNIT)
if demonstrated:
    print_bound("Demonstrated MTBF", demonstrated[0], demonstrated[1], unit=UNIT)

# Two trend tests of "no trend" (a constant failure rate): a small p-value
# (below 0.05) says the rate is changing.
for test_id, label in (("laplace", "Laplace"), ("mil_hdbk_189c", "MIL-HDBK-189C")):
    try:
        with warnings.catch_warnings(), np.errstate(all="ignore"):
            warnings.simplefilter("ignore")
            tt = model.trend_test(test_id)
    except Exception:
        continue
    print_value(f"{label} trend test p-value", float(tt.p_value))'''.splitlines()


# ---- Proportional intensity (covariates) --------------------------------------------


def _regression_script(doc, df: pd.DataFrame) -> str:
    spec = doc.spec or {}
    mapping = spec.get("mapping") or {}
    opts = extra.clean_options("pi_nhpp", spec.get("options"))
    inputs = rec.build_inputs(df, mapping)
    keep = extra.keep_mask(df, mapping)
    Z, names, meta = extra.covariates(df, mapping, keep)
    data, src = extra.observed(inputs)
    zf = pd.DataFrame(np.asarray(Z)[src], columns=names)
    t_end = rec.end_of_observation(inputs)
    base = opts["baseline"]
    cat = next((m for m in meta if m["kind"] == "category"), None)
    groups = None
    if cat:
        groups = {"column": cat["column"], "levels": cat["levels"]}
    coding = [f"{m['column']}: a number, used as it is" if m["kind"] == "number"
              else f"{m['column']}: text, one 0/1 column per level against {m['reference']} (the level most "
                   "systems have)" for m in meta]
    notes = [
        "Model: proportional intensity. Each system's failure rate is a shared baseline "
        f"({extra.BASELINE_NAMES[base]}) multiplied by exp(coefficient x covariate) for each covariate: which "
        "site, duty or condition drives the repair rate.",
        "Covariates: " + "; ".join(coding) + ".",
        "Each row is one event: a failure (censored = 0), or where a system's record ends (censored = 1).",
    ]
    cls = _BASELINE_CLASS[base]
    lines = _common_head(doc, "a repairable-system model with covariates", notes,
                         ["ProportionalIntensityNHPP", cls])
    lines += ["# The events, after the app's preparation; the covariate columns are as coded above.",
              *px.csv_block("EVENTS", _frame(data, zf)), ""]
    lines += _READ
    lines += [
        f"COVARIATES = {px.literal(list(names))}",
        "Z = events[COVARIATES].astype(float)",
        f"END = {px.num(t_end)}  # the latest time any system was watched",
        f"GROUPS = {px.literal(groups)}  # the first text covariate's levels, for the MTBF of each",
        "",
        "# Fit by maximum likelihood.",
        "with warnings.catch_warnings(), np.errstate(all='ignore'):",
        "    warnings.simplefilter('ignore')",
        "    kw = {k: data[k] for k in ('i', 'c', 'n', 'tl') if data.get(k) is not None}",
        f"    model = ProportionalIntensityNHPP.fit(data['x'], Z, baseline={cls}, **kw)",
        *_SUMMARY,
        *_REGRESSION_REPORT,
    ]
    return px.assemble(lines)


_REGRESSION_REPORT = '''

rows = parameter_table(model)
features = list(model.feature_names or [])
for name in model.parameter_names:
    if str(name) in features:
        continue
    est, lo, hi = rows.get(str(name), (None, None, None))
    if est is not None:
        print_interval(f"Parameter {name}", est, lo, hi)

# Each covariate's effect. The rate ratio exp(coefficient) is how many
# times as often failures come: for a level, against the reference level;
# for a number, for each 1 more of it.
for name in features:
    est, lo, hi = rows.get(name, (None, None, None))
    if est is None or not np.isfinite(est):
        print(f"{name.replace(':', ' =')} - the data can't estimate this effect")
        continue
    label = name.replace(":", " =")  # "site: Inland" reads "site = Inland"
    print_interval(f"Coefficient {label}", est, lo, hi)
    print_interval(f"Rate ratio {label}", np.exp(est), *((np.exp(lo), np.exp(hi)) if lo is not None else (None, None)))

# The fleet's average system: each covariate averaged over systems (so a
# system with many failures doesn't count more).
ids = np.asarray(data["i"])
_, first = np.unique(ids, return_index=True)
average = Z.to_numpy(dtype=float)[first].mean(axis=0)
t = np.array([float(END)])


def rates(z):
    """The failure rate at the end of observation for covariates z, its 90%
    interval, and the MTBF's 90% one-sided lower bound."""
    with warnings.catch_warnings(), np.errstate(all="ignore"):
        warnings.simplefilter("ignore")
        r = float(np.ravel(np.asarray(model.iif(t, z), dtype=float))[0])
        try:
            cb = np.ravel(np.asarray(model.iif_cb(t, z, alpha_ci=1 - LEVEL), dtype=float))
            up = float(np.ravel(np.asarray(model.iif_cb(t, z, alpha_ci=1 - LEVEL, bound="upper"), dtype=float))[0])
        except Exception:
            cb, up = None, None
    if cb is not None and not np.all(np.isfinite(cb)):
        cb = None  # no interval (the fit gives no usable covariance)
    return r, cb, up


print_value("End of observation", END, UNIT)
r, cb, _ = rates(average)
mtbf = 1.0 / r if np.isfinite(r) and r > 0 else None
ok = cb is not None and cb[0] > 0
print_interval("ROCOF at end (average system)", r, *(cb if cb is not None else (None, None)))
print_interval("MTBF at end (average system)", mtbf, *((1.0 / cb[1], 1.0 / cb[0]) if ok else (None, None)), unit=UNIT)

# Each level of the first text covariate (the others at the fleet's average).
if GROUPS:
    cols = [k for k, nm in enumerate(COVARIATES) if nm.startswith(GROUPS["column"] + ": ")]
    for level in GROUPS["levels"]:
        z = average.copy()
        z[cols] = 0.0
        name = f"{GROUPS['column']}: {level}"
        if name in COVARIATES:
            z[COVARIATES.index(name)] = 1.0
        r, cb, up = rates(z)
        label = f"{GROUPS['column']} {level}"
        mtbf = 1.0 / r if r and r > 0 else None
        ok = cb is not None and cb[0] > 0
        print_interval(f"MTBF at end, {label}", mtbf, *((1.0 / cb[1], 1.0 / cb[0]) if ok else (None, None)), unit=UNIT)
        if up and up > 0:
            print_bound(f"MTBF at end at least, {label}", mtbf, 1.0 / up, unit=UNIT)'''.splitlines()


# ---- Imperfect repair: Kijima I/II, ARA, ARI, G1 --------------------------------------

_RENEWAL_CALL = {
    "grp_i": ("GeneralizedRenewal", "GeneralizedRenewal.fit(data['x'], kijima='i', **kw)"),
    "grp_ii": ("GeneralizedRenewal", "GeneralizedRenewal.fit(data['x'], kijima='ii', **kw)"),
    "g1": ("GeneralizedOneRenewal", "GeneralizedOneRenewal.fit(data['x'], **kw)"),
    "ara": ("ARA", "ARA.fit(data['x'], m=MEMORY, **kw)"),
    "ari": ("ARI", "ARI.fit(data['x'], m=MEMORY, baseline=BASELINE, **kw)"),
}
_RESTORE_WORDS = {
    "grp_i": "q: 0 = as good as new, 1 = as bad as old; each repair takes off part of the age gained since "
             "the last repair",
    "grp_ii": "q: 0 = as good as new, 1 = as bad as old; each repair takes off part of the system's whole age",
    "ara": "rho: the share of the recent age each repair takes off (1 = as good as new, 0 = as bad as old)",
    "ari": "rho: the share of the recent rise in failure rate each repair takes off",
    "g1": "q: each time between failures is (1 + q) times the one before",
}


def _renewal_script(doc, df: pd.DataFrame) -> str:
    spec = doc.spec or {}
    mapping = spec.get("mapping") or {}
    model_id = spec["model_id"]
    opts = extra.clean_options(model_id, spec.get("options"))
    inputs = rec.build_inputs(df, mapping)
    data = extra.with_end_rows(inputs)
    if "c" not in data:
        data["c"] = np.zeros(np.size(data["x"]), dtype=int)
    cls, call = _RENEWAL_CALL[model_id]
    imports = [cls]
    head = []
    if model_id in ("ara", "ari"):
        m = opts.get("m", 1)
        head.append(f"MEMORY = {'np.inf' if m == 'all' else int(m)}  # how many past repairs each repair reaches back")
    if model_id == "ari":
        b = _BASELINE_CLASS[opts["baseline"]]
        imports.append(b)
        head.append(f"BASELINE = {b}  # the failure rate before any repair")
    rest_name = extra._RESTORATION[model_id][0]
    notes = [
        f"Model: {extra.model_name(model_id, opts)}, an imperfect-repair model: each repair puts the system "
        "somewhere between as good as new and as bad as old.",
        "Repair parameter " + _RESTORE_WORDS[model_id] + ".",
        "Each row is one event: a failure (censored = 0), or where a system's record ends (censored = 1).",
    ]
    lines = _common_head(doc, "a repairable-system model (imperfect repair)", notes, imports)
    lines += ["# The events, after the app's preparation.", *px.csv_block("EVENTS", _frame(data)), ""]
    lines += _READ
    lines += [*head, f"MODEL_ID = {model_id!r}", f"REPAIR_PARAMETER = {rest_name!r}", "",
              "# Fit by maximum likelihood.",
              "with warnings.catch_warnings(), np.errstate(all='ignore'):",
              "    warnings.simplefilter('ignore')",
              "    kw = {k: data[k] for k in ('i', 'c', 'n', 'tl') if data.get(k) is not None}",
              f"    model = {call}",
              *_SUMMARY, *_RENEWAL_REPORT]
    return px.assemble(lines)


_RENEWAL_REPORT = '''

rows = parameter_table(model)
# The repair parameter's interval is the profile-likelihood one (it agrees
# with the likelihood-ratio repair test), the Wald one when that can't be had.
est, lo, hi = rows.get(REPAIR_PARAMETER, (None, None, None))
repair_ci = [lo, hi] if lo is not None else None
try:
    with warnings.catch_warnings(), np.errstate(all="ignore"):
        warnings.simplefilter("ignore")
        cb = np.ravel(np.asarray(model.param_cb(REPAIR_PARAMETER, alpha_ci=1 - LEVEL, method="lr"), dtype=float))
    if cb.size == 2 and np.all(np.isfinite(cb)) and cb[0] <= cb[1]:
        repair_ci = [float(cb[0]), float(cb[1])]
except Exception:
    pass
for name in model.parameter_names:
    value, low, high = rows.get(str(name), (None, None, None))
    if value is None:
        continue
    if str(name) == REPAIR_PARAMETER and repair_ci:
        low, high = repair_ci
    print_interval(f"Parameter {name}", value, low, high)

# How much each repair restores, in words the page uses.
if est is not None:
    ci = repair_ci
    if MODEL_ID == "g1":
        print_interval("Gap ratio (each gap / the one before)", 1.0 + est, *((1.0 + ci[0], 1.0 + ci[1]) if ci else (None, None)))
    elif MODEL_ID in ("grp_i", "grp_ii"):
        print_interval("Share restored by each repair", 1.0 - est, *((1.0 - ci[1], 1.0 - ci[0]) if ci else (None, None)))
    else:
        print_interval("Share restored by each repair", est, *(ci or (None, None)))'''.splitlines()


# ---- Built from parameters (no data) ---------------------------------------------------


def _params_script(doc) -> str:
    spec = doc.spec or {}
    model_id = spec.get("model_id", "crow_amsaa")
    values = [float(p["value"]) for p in spec.get("params") or []]
    horizon = float(spec.get("horizon") or (doc.results or {}).get("horizon") or 0)
    cls = _NHPP_CLASS[model_id]
    notes = [
        f"Model: {rec.MODELS[model_id]['name']}, built from parameters typed in (no data, so no intervals).",
        "The parameters were entered as Crow-AMSAA's alpha (scale) and beta (shape).",
    ]
    lines = _common_head(doc, "a repairable-system model from known parameters", notes, [cls])
    lines += [f"ALPHA, BETA = {px.num(values[0])}, {px.num(values[1])}  # as entered: scale and shape",
              f"HORIZON = {px.num(horizon)}  # the rates are worked out at this time"]
    if model_id == "duane":
        lines += ["# SurPyval's Duane takes (shape, b) with b = scale ** -shape.",
                  "params = [BETA, ALPHA ** (-BETA)]"]
    else:
        lines += ["params = [ALPHA, BETA]"]
    lines += [
        f"model = {cls}.from_params(params)",
        "for name, value in zip(model.parameter_names, params):",
        '    print_value(f"Parameter {name}", value)',
        "with np.errstate(all='ignore'):",
        "    rocof = float(np.ravel(np.asarray(model.iif(np.array([HORIZON])), dtype=float))[0])",
        'print_value("ROCOF at horizon", rocof)',
        'print_value("MTBF at horizon", 1.0 / rocof if rocof > 0 else None, UNIT)',
    ]
    return px.assemble(lines)


def export_python(db, model, owners=None) -> tuple[str, str]:
    """``(filename, source)``: a script that refits the saved repairable
    model ``model`` (a ``RecurrentModelDoc``) from its data and prints the
    page's numbers. Raises :class:`FitError` when its data is gone."""
    spec = model.spec or {}
    name = px.filename(model.name, "repairable_model")
    if spec.get("params_only") or not model.dataset_id:
        return name, _params_script(model)
    dataset = datasets_service.get_dataset(db, model.dataset_id, owner_id=model.owner_id)
    if dataset is None:
        raise FitError("This model's dataset is gone, so there's no data to put in the script.")
    df = datasets_service.load_dataframe(dataset)
    model_id = spec.get("model_id", "crow_amsaa")
    if model_id in rec.MODELS:
        return name, _nhpp_script(model, df)
    if model_id == "pi_nhpp":
        return name, _regression_script(model, df)
    if model_id in _RENEWAL_CALL:
        return name, _renewal_script(model, df)
    raise FitError(f"Download as Python doesn't cover “{model_id}” models yet.")
