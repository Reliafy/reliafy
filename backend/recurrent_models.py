"""Recurrent-event models beyond minimal repair (#65).

:mod:`backend.recurrent` fits the minimal-repair (Poisson-process) models:
Crow-AMSAA, Duane, HPP and Cox-Lewis. This module adds, from
:mod:`surpyval.recurrent`:

- **intensity regression**: ``ProportionalIntensityNHPP``, the failure
  intensity of each system scaled by its covariates (site, duty, ...);
- **imperfect repair**: the generalized renewal process (Kijima I and II),
  ARA and ARI (Doyen and Gaudoin) and the G1 renewal process, each with its
  repair-effectiveness parameter in words, ``repair_test()`` as a verdict and
  each system's next-failure distribution;
- **gapped observation**: each system's observation windows (``windows=``),
  for the Poisson-process models;
- **cause marks**: ``CauseSpecificMCF`` and ``CauseSpecificNHPP`` when the
  data has a cause (failure-mode) column: the MCF of each cause with its
  95% band and a Crow-AMSAA fit per cause.

Every statistic comes from SurPyval; this module only prepares the inputs
and puts the results in words.
"""

from __future__ import annotations

import warnings

import numpy as np
import pandas as pd

from backend.fitting import FitError, _json_safe
from backend.services.method_labels import note_fit
from backend.units import canonical_unit
from surpyval.recurrent import (
    ARA,
    ARI,
    CauseSpecificMCF,
    CauseSpecificNHPP,
    CoxLewis,
    CrowAMSAA,
    Duane,
    GeneralizedOneRenewal,
    GeneralizedRenewal,
    NonParametricCounting,
    ProportionalIntensityNHPP,
)

# The models this module fits, by family. ``regression``: a Poisson process
# whose intensity is scaled by covariates; ``renewal``: imperfect repair.
EXTRA_MODELS = {
    "pi_nhpp": {
        "name": "Proportional intensity (covariates)", "short": "Proportional intensity", "family": "regression",
        "desc": "Each system's failure rate is a shared baseline (Crow-AMSAA by default) scaled by its "
                "covariates: which site, duty or condition drives the repair rate.",
    },
    "grp_i": {
        "name": "Generalized renewal (Kijima I)", "short": "GRP Kijima I", "family": "renewal",
        "desc": "Imperfect repair: each repair takes off part of the age gained since the last repair "
                "(Weibull time to failure).",
    },
    "grp_ii": {
        "name": "Generalized renewal (Kijima II)", "short": "GRP Kijima II", "family": "renewal",
        "desc": "Imperfect repair: each repair takes off part of the system's whole age (Weibull time to failure).",
    },
    "ara": {
        "name": "Arithmetic reduction of age (ARA)", "short": "ARA", "family": "renewal",
        "desc": "Imperfect repair that takes off part of the age of the last few failures (Weibull time to "
                "failure). With a memory of 1 it is Kijima I; with all repairs, Kijima II.",
    },
    "ari": {
        "name": "Arithmetic reduction of intensity (ARI)", "short": "ARI", "family": "renewal",
        "desc": "Imperfect repair that lowers the failure rate itself after each repair, on a Crow-AMSAA "
                "baseline.",
    },
    "g1": {
        "name": "G1 renewal (geometric gaps)", "short": "G1 renewal", "family": "renewal",
        "desc": "Each time between failures is a fixed multiple of the one before: shrinking gaps mean "
                "deterioration (Weibull time to failure).",
    },
}

BASELINES = {"crow_amsaa": CrowAMSAA, "duane": Duane, "cox_lewis": CoxLewis}
BASELINE_NAMES = {"crow_amsaa": "Crow-AMSAA", "duane": "Duane", "cox_lewis": "Cox-Lewis"}

CI_LEVEL = 0.95
_MAX_LEVELS = 12        # levels of one categorical covariate
_MAX_CAUSES = 12        # causes shown, most failures first
_UNIT_ROWS = 50         # systems in the next-failure table
_UNIT_CURVES = 8        # systems drawn in the next-failure chart
_GRID = 200
_SLOW_CVM_BOOT = 40     # bootstrap refits for the families whose refit is slow
_SLOW_CVM_EVENTS = 600  # ... skipped past this many events
_NO_CAUSE = "No cause given"


def family(model_id: str) -> str:
    """``nhpp``, ``regression`` or ``renewal``."""
    return EXTRA_MODELS.get(model_id, {}).get("family", "nhpp")


def model_name(model_id: str, options: dict | None = None) -> str:
    entry = EXTRA_MODELS[model_id]
    opts = options or {}
    if model_id == "pi_nhpp" and opts.get("baseline", "crow_amsaa") != "crow_amsaa":
        return f"{entry['name']}, {BASELINE_NAMES[opts['baseline']]} baseline"
    if model_id in ("ara", "ari"):
        return f"{entry['name'].split(' (')[0]} ({entry['short']}{_memory_label(opts.get('m'))})"
    return entry["name"]


def _memory_label(m) -> str:
    return "∞" if m in (None, "all") or (isinstance(m, float) and not np.isfinite(m)) else str(int(m))


# ---------------------------------------------------------------------------
# Options
# ---------------------------------------------------------------------------

def clean_options(model_id: str, options: dict | None) -> dict:
    """The model's options, validated: ``baseline`` (proportional intensity,
    ARI) and ``m``, the memory of ARA / ARI (a whole number of repairs, or
    ``"all"``)."""
    opts = dict(options or {})
    out: dict = {}
    if model_id in ("pi_nhpp", "ari"):
        baseline = opts.get("baseline") or "crow_amsaa"
        if baseline not in BASELINES:
            raise FitError(f"Unknown baseline '{baseline}'. Choose one of: {', '.join(BASELINES)}.")
        out["baseline"] = baseline
    if model_id in ("ara", "ari"):
        m = opts.get("m")
        if m in (None, ""):
            m = 2 if model_id == "ara" else 1
        if isinstance(m, str) and m.strip().lower() in ("all", "inf", "infinity", "∞"):
            out["m"] = "all"
        else:
            try:
                m = int(float(m))
            except (TypeError, ValueError):
                raise FitError("The memory must be a whole number of repairs (1, 2, …) or 'all'.")
            if m < 1:
                raise FitError("The memory must be at least 1 repair.")
            out["m"] = m
    return out


def _memory(opts: dict):
    m = opts.get("m", 1)
    return np.inf if m == "all" else int(m)


# ---------------------------------------------------------------------------
# Inputs: covariates, end-of-observation rows, windows, causes
# ---------------------------------------------------------------------------

def keep_mask(df: pd.DataFrame, mapping: dict) -> pd.Series:
    """The event rows: a numeric event time and a system id."""
    x = pd.to_numeric(df[mapping["x"]], errors="coerce")
    return x.notna() & df[mapping["i"]].notna()


def covariates(df: pd.DataFrame, mapping: dict, keep: pd.Series) -> tuple[np.ndarray, list, list]:
    """``(Z, names, meta)`` for the mapped covariate columns (``mapping['z']``),
    on the event rows. A numeric column is used as it is; a text column
    becomes one indicator per level against its reference level, the level
    most systems have (``"site: Inland"`` is Inland against the reference).
    ``meta`` describes each column: ``{column, kind, reference?, levels?,
    mean?}``."""
    cols = mapping.get("z") or []
    if isinstance(cols, str):
        cols = [c for c in cols.split(",") if c.strip()]
    if not cols:
        raise FitError("Choose at least one covariate column (e.g. site or duty) for proportional intensity.")
    systems = df[mapping["i"]][keep].astype(str)
    blocks, names, meta = [], [], []
    for col in cols:
        if col not in df.columns:
            raise FitError(f"Column '{col}' is not in the dataset.")
        if col in (mapping.get("i"), mapping.get("x")):
            raise FitError(f"'{col}' is the system or time column, so it can't be a covariate too.")
        raw = df[col][keep]
        missing = int(raw.isna().sum())
        if missing:
            raise FitError(f"Covariate '{col}' is blank on {missing} event row{'s' if missing != 1 else ''}: "
                           "fill it in for every row of each system.")
        num = pd.to_numeric(raw, errors="coerce")
        if num.notna().all():
            blocks.append(num.to_numpy(dtype=float)[:, None])
            names.append(str(col))
            meta.append({"column": str(col), "kind": "number", "mean": float(num.mean())})
            continue
        labels = raw.astype(str).str.strip()
        # The reference is the level most systems have (ties: alphabetical).
        per_level = labels.groupby(systems.values).first().value_counts()
        levels = sorted(per_level.index.tolist(), key=lambda lv: (-int(per_level[lv]), lv))
        if len(levels) < 2:
            raise FitError(f"Covariate '{col}' has one value only ({levels[0]}), so there is nothing to compare.")
        if len(levels) > _MAX_LEVELS:
            raise FitError(f"Covariate '{col}' has {len(levels)} different values; group them into "
                           f"{_MAX_LEVELS} or fewer first.")
        ref = levels[0]
        for lv in levels[1:]:
            blocks.append((labels == lv).to_numpy(dtype=float)[:, None])
            names.append(f"{col}: {lv}")
        meta.append({"column": str(col), "kind": "category", "reference": ref, "levels": levels})
    return np.hstack(blocks), names, meta


def with_end_rows(inputs: dict) -> dict:
    """The renewal fitters take each system's end of observation as a
    ``c = 1`` row, not ``tr``: add one at its window's end for each system
    that has no ``c = 1`` row and was watched past its last failure."""
    x, i = np.asarray(inputs["x"], dtype=float), np.asarray(inputs["i"])
    c = np.asarray(inputs.get("c", np.zeros(x.size, dtype=int)), dtype=int)
    n = inputs.get("n")
    tr = inputs.get("tr")
    out = {"x": x, "i": i, "c": c}
    if n is not None:
        out["n"] = np.asarray(n, dtype=int)
    if inputs.get("tl") is not None:
        out["tl"] = np.asarray(inputs["tl"], dtype=float)
    if tr is None:
        return out
    tr = np.asarray(tr, dtype=float)
    closed = set(i[c == 1].tolist())
    add_x, add_i, add_tl = [], [], []
    for sys_id in dict.fromkeys(i.tolist()):
        if sys_id in closed:
            continue
        rows = i == sys_id
        end = float(np.nanmax(tr[rows]))
        if end > float(np.max(x[rows])):
            add_x.append(end)
            add_i.append(sys_id)
            if "tl" in out:
                add_tl.append(float(out["tl"][rows][0]))
    if add_x:
        out["x"] = np.concatenate([x, add_x])
        out["i"] = np.concatenate([i, np.asarray(add_i, dtype=i.dtype)])
        out["c"] = np.concatenate([c, np.ones(len(add_x), dtype=int)])
        if "n" in out:
            out["n"] = np.concatenate([out["n"], np.ones(len(add_x), dtype=int)])
        if "tl" in out:
            out["tl"] = np.concatenate([out["tl"], add_tl])
    return out


def parse_windows(value) -> dict:
    """``{system: [[start, end], ...]}`` from a dict, or from text with one
    window a line: ``system, start, end``."""
    if value in (None, "", {}):
        return {}
    if isinstance(value, str):
        out: dict = {}
        for k, line in enumerate(value.splitlines(), 1):
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parts = [p.strip() for p in line.replace("\t", ",").replace(";", ",").split(",")]
            if len(parts) != 3:
                raise FitError(f"Window line {k}: write it as system, start, end (e.g. P-01, 0, 3000).")
            try:
                start, end = float(parts[1]), float(parts[2])
            except ValueError:
                raise FitError(f"Window line {k}: start and end must be numbers.")
            out.setdefault(parts[0], []).append([start, end])
        return out
    if not isinstance(value, dict):
        raise FitError("Windows must map each system to its [start, end] observation windows.")
    out = {}
    for sys_id, spans in value.items():
        rows = []
        for span in spans or []:
            try:
                start, end = float(span[0]), float(span[1])
            except (TypeError, ValueError, IndexError):
                raise FitError(f"System {sys_id}: each window is [start, end].")
            rows.append([start, end])
        if rows:
            out[str(sys_id)] = rows
    return out


def windows_from(df: pd.DataFrame, mapping: dict, manual=None) -> dict:
    """Each system's observation windows: the window-start / window-end
    columns (``ws`` / ``we``; a row with both and no event time is a window
    with no failures in it), plus any entered by hand. Validated: start
    before end, no overlaps."""
    out: dict = {k: list(v) for k, v in parse_windows(manual).items()}
    ws, we = mapping.get("ws"), mapping.get("we")
    if bool(ws) != bool(we):
        raise FitError("Map both the window start and the window end columns, or neither.")
    if ws:
        for col in (ws, we):
            if col not in df.columns:
                raise FitError(f"Column '{col}' is not in the dataset.")
        s = pd.to_numeric(df[ws], errors="coerce")
        e = pd.to_numeric(df[we], errors="coerce")
        ids = df[mapping["i"]]
        ok = s.notna() & e.notna() & ids.notna()
        for sys_id, a, b in zip(ids[ok].astype(str), s[ok], e[ok]):
            out.setdefault(sys_id, []).append([float(a), float(b)])
    clean = {}
    for sys_id, spans in out.items():
        spans = sorted({(float(a), float(b)) for a, b in spans})
        for a, b in spans:
            if not (np.isfinite(a) and np.isfinite(b)) or b <= a or a < 0:
                raise FitError(f"System {sys_id}: a window must start at 0 or later and end after it starts "
                               f"(got {a:g} to {b:g}).")
        for (a1, b1), (a2, b2) in zip(spans, spans[1:]):
            if a2 < b1:
                raise FitError(f"System {sys_id}: windows {a1:g}–{b1:g} and {a2:g}–{b2:g} overlap.")
        clean[sys_id] = [list(w) for w in spans]
    return clean


def apply_windows(inputs: dict, windows: dict) -> tuple[dict, dict]:
    """Inputs for a gapped fit: the events only (the windows give each
    system's ends) and every system's windows. A system with failures but no
    window is watched from its entry (or 0) to its end of observation (or its
    last failure). Returns ``(inputs, summary)``."""
    x, i = np.asarray(inputs["x"], dtype=float), np.asarray(inputs["i"]).astype(str)
    c = np.asarray(inputs.get("c", np.zeros(x.size, dtype=int)), dtype=int)
    if np.any((c != 0) & (c != 1)):
        raise FitError("With observation windows, rows are failures (c = 0) or end-of-observation rows (c = 1) "
                       "only; left- or interval-censored counts can't be used.")
    tl, tr = inputs.get("tl"), inputs.get("tr")
    full = dict(windows)
    defaulted = []
    for sys_id in dict.fromkeys(i.tolist()):
        if sys_id in full:
            continue
        rows = i == sys_id
        start = float(np.nanmin(np.asarray(tl, dtype=float)[rows])) if tl is not None else 0.0
        end = float(np.nanmax(np.asarray(tr, dtype=float)[rows])) if tr is not None else float(np.max(x[rows]))
        full[sys_id] = [[start, end]]
        defaulted.append(sys_id)
    ev = c == 0
    out = {"x": x[ev], "i": i[ev], "windows": {k: [tuple(w) for w in v] for k, v in full.items()}}
    if inputs.get("n") is not None:
        out["n"] = np.asarray(inputs["n"])[ev]
    observed = sum(b - a for spans in full.values() for a, b in spans)
    span = sum(max(b for _, b in spans) - min(a for a, _ in spans) for spans in full.values())
    summary = {
        "systems_with_gaps": int(sum(1 for spans in full.values() if len(spans) > 1)),
        "windows": int(sum(len(spans) for spans in full.values())),
        "observed_time": float(observed),
        "gap_time": float(span - observed),
        "defaulted": defaulted[:20],
        "n_defaulted": len(defaulted),
    }
    return out, summary


def plain_error(exc: Exception) -> str:
    """SurPyval's message, with its "item" read as a system."""
    msg = str(exc)
    return msg.replace("item ", "system ").replace("Item ", "System ")


def _first(values) -> float | None:
    v = float(np.asarray(values, dtype=float).ravel()[0])
    return v if np.isfinite(v) else None


def _estimates(model) -> np.ndarray:
    """Every parameter's estimate in ``parameter_names`` order: a
    proportional-intensity model keeps its baseline in ``params`` and its
    covariate coefficients in ``coeffs`` (SurPyval 0.23)."""
    params = np.ravel(np.asarray(model.params, dtype=float))
    coeffs = getattr(model, "coeffs", None)
    if coeffs is not None and params.size < len(model.parameter_names):
        params = np.concatenate([params, np.ravel(np.asarray(coeffs, dtype=float))])
    return params


def _param_cb_rows(model) -> dict:
    """``{name: (estimate, lower, upper)}`` from SurPyval's ``param_cb`` on
    each parameter, for a model whose ``summary()`` SurPyval doesn't have
    (0.23's proportional-intensity model); estimates only where it has no
    interval either."""
    out = {}
    for name, value in zip(model.parameter_names, _estimates(model)):
        lo = hi = None
        try:
            with warnings.catch_warnings(), np.errstate(all="ignore"):
                warnings.simplefilter("ignore")
                cb = np.asarray(model.param_cb(name, alpha_ci=1 - CI_LEVEL), dtype=float).ravel()
            if cb.size == 2 and np.all(np.isfinite(cb)):
                lo, hi = float(cb[0]), float(cb[1])
        except Exception:  # noqa: BLE001 - no likelihood: the estimate alone
            pass
        out[str(name)] = (float(value), lo, hi)
    return out


def _summary_rows(model) -> dict:
    """``{name: (estimate, lower, upper)}`` from SurPyval's ``summary()``, or
    its ``param_cb`` where the model has no ``summary()``."""
    if not callable(getattr(model, "summary", None)):
        return _param_cb_rows(model)
    try:
        with warnings.catch_warnings(), np.errstate(all="ignore"):
            warnings.simplefilter("ignore")
            table = model.summary(alpha_ci=1 - CI_LEVEL)
    except Exception:  # noqa: BLE001 - no likelihood: estimates only
        return {n: (float(v), None, None) for n, v in zip(model.parameter_names, _estimates(model))}
    lo_col = next(c for c in table.columns if str(c).startswith("lower"))
    hi_col = next(c for c in table.columns if str(c).startswith("upper"))
    out = {}
    for name, row in table.iterrows():
        lo, hi = float(row[lo_col]), float(row[hi_col])
        ok = np.isfinite(lo) and np.isfinite(hi)
        out[str(name)] = (float(row["estimate"]), lo if ok else None, hi if ok else None)
    return out


def _param_rows(rows: dict, names: list) -> list:
    out = []
    for name in names:
        est, lo, hi = rows.get(name, (None, None, None))
        if est is None:
            continue
        out.append({"name": name, "value": est, **({"ci": [lo, hi]} if lo is not None else {})})
    return out


def _pct(v: float) -> str:
    return f"{round(v * 100):.0f}%"


# ---------------------------------------------------------------------------
# Cause marks
# ---------------------------------------------------------------------------

def cause_labels(df: pd.DataFrame, mapping: dict, keep: pd.Series) -> np.ndarray:
    from backend.recurrent import _mode_label

    return np.asarray([_mode_label(v) for v in df[mapping["mode"]][keep].tolist()], dtype=object)


def by_cause(inputs: dict, causes: np.ndarray, unit: str = "") -> dict | None:
    """The MCF of each cause with its 95% band (``CauseSpecificMCF``) and a
    Crow-AMSAA fit per cause (``CauseSpecificNHPP``): its growth shape with
    the 95% interval, and its failures. Failures with no cause count under
    "No cause given"; end-of-observation rows carry none. The most frequent
    causes first, at most 12 (the MCFs of the rest are left out, the fit
    still uses them)."""
    from backend.recurrent import growth_verdict

    x, i = np.asarray(inputs["x"], dtype=float), np.asarray(inputs["i"])
    c = np.asarray(inputs.get("c", np.zeros(x.size, dtype=int)), dtype=int)
    if np.any((c != 0) & (c != 1)):
        return {"causes": [], "reason": "Failures by cause need exact failure times: the data has left- or "
                                        "interval-censored rows."}
    n = inputs.get("n")
    e = np.asarray(causes, dtype=object).copy()
    e[(c == 0) & np.asarray([v is None for v in e])] = _NO_CAUSE
    e[c == 1] = None
    kw = {k: inputs[k] for k in ("tl", "tr") if inputs.get(k) is not None}
    if n is not None and np.any(np.asarray(n) > 1):
        reps = np.maximum(np.asarray(n, dtype=int), 1)
        x, i, c, e = np.repeat(x, reps), np.repeat(i, reps), np.repeat(c, reps), np.repeat(e, reps)
        kw = {k: np.repeat(v, reps) for k, v in kw.items()}
    labels = [v for v in e[c == 0]]
    counts = pd.Series(labels).value_counts()
    if len(counts) < 2:
        return {"causes": [], "reason": "Only one cause in the data: the MCF by cause is the MCF."}
    try:
        with warnings.catch_warnings(), np.errstate(all="ignore"):
            warnings.simplefilter("ignore")
            mcf = CauseSpecificMCF.fit(x, i=i, c=c, e=e, **kw)
            para = CauseSpecificNHPP.fit(x, i=i, c=c, e=e, dist=CrowAMSAA, **kw)
    except Exception as exc:  # noqa: BLE001 - surface SurPyval's reason, keep the rest of the fit
        return {"causes": [], "reason": f"Couldn't fit by cause: {exc}"}
    total = int(counts.sum())
    rows = []
    for label in sorted(counts.index, key=lambda k: (-int(counts[k]), str(k)))[:_MAX_CAUSES]:
        np_model = mcf.models[label]
        nx = np.asarray(np_model.x, dtype=float)
        est = np.asarray(np_model.mcf_hat, dtype=float)
        try:
            cb = np.asarray(mcf.mcf_cb(nx, label, alpha_ci=1 - CI_LEVEL), dtype=float)
            lower, upper = np.minimum(cb[:, 0], cb[:, 1]).tolist(), np.maximum(cb[:, 0], cb[:, 1]).tolist()
        except Exception:  # noqa: BLE001 - bounds are optional
            lower = upper = None
        row = {"label": str(label), "failures": int(counts[label]), "share": int(counts[label]) / total,
               "mcf": {"x": nx.tolist(), "mcf": est.tolist(), "lower": lower, "upper": upper}}
        model = para.models.get(label)
        if model is not None:
            params = np.asarray(model.params, dtype=float)
            cis = {}
            for name in ("alpha", "beta"):
                try:
                    with warnings.catch_warnings(), np.errstate(all="ignore"):
                        warnings.simplefilter("ignore")
                        lo, hi = (float(v) for v in np.asarray(model.param_cb(name, alpha_ci=1 - CI_LEVEL)))
                    if np.isfinite(lo) and np.isfinite(hi):
                        cis[name] = [lo, hi]
                except Exception:  # noqa: BLE001 - no interval
                    pass
            growth, basis = growth_verdict("crow_amsaa", params, cis)
            row["fit"] = {"alpha": float(params[0]), "beta": float(params[1]), "alpha_ci": cis.get("alpha"),
                          "beta_ci": cis.get("beta"), "growth": growth, "growth_basis": basis}
        rows.append(row)
    try:
        # The causes' likelihoods are separate, so the joint AIC is the sum
        # of each cause's (what CauseSpecificNHPP.aic() gives where it has one).
        aic = float(para.aic()) if callable(getattr(para, "aic", None)) else float(
            sum(m.aic() for m in para.models.values()))
    except Exception:  # noqa: BLE001
        aic = None
    return {"causes": rows, "n_causes": int(len(counts)), "failures": total, "aic": aic,
            "model": "Crow-AMSAA per cause", "unit": canonical_unit(unit),
            "note": None if len(counts) <= _MAX_CAUSES else
            f"The {_MAX_CAUSES} most frequent of {len(counts)} causes are shown."}


# ---------------------------------------------------------------------------
# Fitting
# ---------------------------------------------------------------------------

def fit(df: pd.DataFrame, mapping: dict, model_id: str, unit: str = "", gof_test: bool = True,
        options: dict | None = None, windows=None) -> tuple[dict, object]:
    """Fit a proportional-intensity or imperfect-repair model; returns
    ``(payload, live model)``."""
    from backend.recurrent import build_inputs

    if windows:
        raise FitError("Observation gaps (windows) work with the Crow-AMSAA, Duane, HPP and Cox-Lewis models; "
                       f"{EXTRA_MODELS[model_id]['short']} needs each system watched without a break.")
    opts = clean_options(model_id, options)
    inputs = build_inputs(df, mapping)
    keep = keep_mask(df, mapping)
    np_inputs = {k: v for k, v in inputs.items() if k != "tr"}
    try:
        with warnings.catch_warnings(), np.errstate(all="ignore"):
            warnings.simplefilter("ignore", RuntimeWarning)
            np_model = note_fit(NonParametricCounting.fit(**np_inputs))
            warnings.simplefilter("ignore", UserWarning)  # an unverified maximum is reported in the payload
            if family(model_id) == "regression":
                Z, names, meta = covariates(df, mapping, keep)
                live = note_fit(_fit_regression(inputs, Z, names, opts))
            else:
                live = note_fit(_fit_renewal(model_id, inputs, opts))
    except FitError:
        raise
    except Exception as exc:  # noqa: BLE001 - surface SurPyval's message
        raise FitError(plain_error(exc)) from exc
    if family(model_id) == "regression":
        payload = regression_payload(np_model, live, inputs, Z, meta, model_id, opts, unit, gof_test)
    else:
        payload = renewal_payload(np_model, live, inputs, model_id, opts, unit, gof_test)
    if getattr(live, "maximum", "verified") not in ("verified", "not applicable"):
        payload["fit_warning"] = ("The fit didn't reach a verified best fit (the likelihood may have no maximum, "
                                  "or the search stalled): treat these numbers with care, or try another model.")
    return payload, live


def _fit_regression(inputs: dict, Z: np.ndarray, names: list, opts: dict):
    frame = pd.DataFrame(Z, columns=names)
    kw = {k: inputs[k] for k in ("i", "c", "n", "tl", "tr") if inputs.get(k) is not None}
    # SurPyval 0.23 names the baseline process ``dist``.
    return ProportionalIntensityNHPP.fit(inputs["x"], frame, dist=BASELINES[opts["baseline"]], **kw)


def _fit_renewal(model_id: str, inputs: dict, opts: dict):
    ins = with_end_rows(inputs)
    kw = {k: ins[k] for k in ("i", "c", "n", "tl") if ins.get(k) is not None}
    if model_id == "grp_i":
        return GeneralizedRenewal.fit(ins["x"], kijima="i", **kw)
    if model_id == "grp_ii":
        return GeneralizedRenewal.fit(ins["x"], kijima="ii", **kw)
    if model_id == "g1":
        return GeneralizedOneRenewal.fit(ins["x"], **kw)
    if model_id == "ara":
        return ARA.fit(ins["x"], m=_memory(opts), **kw)
    return ARI.fit(ins["x"], m=_memory(opts), baseline=BASELINES[opts["baseline"]], **kw)


def _observed(np_model) -> dict:
    nx = np.asarray(np_model.x, dtype=float)
    try:
        cb = np.asarray(np_model.mcf_cb(nx, alpha_ci=1 - CI_LEVEL), dtype=float)
        lower, upper = np.minimum(cb[:, 0], cb[:, 1]).tolist(), np.maximum(cb[:, 0], cb[:, 1]).tolist()
    except Exception:  # pragma: no cover - bounds are optional
        lower = upper = None
    return {"x": nx.tolist(), "mcf": np.asarray(np_model.mcf_hat, dtype=float).tolist(), "lower": lower,
            "upper": upper}


def _diagnostics(live, n_events: int, n_systems: int, gof_test: bool, slow: bool) -> dict:
    from backend.recurrent import _gof, cramer_von_mises, system_residuals, trend_tests

    tests = trend_tests(live)
    cvm = None
    if gof_test:
        if slow and n_events > _SLOW_CVM_EVENTS:
            cvm = {"test": "Cramér-von Mises", "null": "the events follow the fitted intensity", "statistic": None,
                   "p_value": None, "n_boot": 0, "adequate": None,
                   "reason": f"Skipped: with {n_events:,} events the bootstrap p-value would take too long."}
        elif slow:
            # Each bootstrap replicate refits the model, which is slower for
            # these families: a fixed, smaller number of replicates.
            cvm = _cvm_fixed(live)
        else:
            cvm = cramer_von_mises(live, n_events)
    return {
        "trend": next((t for t in tests if t["id"] == "laplace"), None),
        "trend_tests": tests,
        "gof": _gof(live),
        "gof_test": cvm,
        "system_residuals": system_residuals(live) if n_systems > 1 else None,
    }


def _cvm_fixed(live) -> dict | None:
    base = {"test": "Cramér-von Mises", "null": "the events follow the fitted intensity"}
    try:
        with warnings.catch_warnings(), np.errstate(all="ignore"):
            warnings.simplefilter("ignore")
            g = live.cramer_von_mises(n_boot=_SLOW_CVM_BOOT, random_state=0)
    except Exception:  # noqa: BLE001
        return None
    p = float(g.p_value)
    return {**base, "statistic": float(g.statistic), "p_value": p, "n_boot": int(g.n_boot),
            "adequate": bool(p >= 0.05)}


def _base(np_model, inputs: dict, model_id: str, opts: dict, unit: str) -> dict:
    from backend.recurrent import end_of_observation

    x, i = inputs["x"], inputs["i"]
    return {
        "kind": "recurrent",
        "family": family(model_id),
        "unit": canonical_unit(unit),
        "n_systems": int(len(set(np.asarray(i).tolist()))),
        "n_events": int(len(x)),
        "model": {"id": model_id, "name": model_name(model_id, opts)},
        "options": opts,
        "end_of_observation": end_of_observation(inputs),
        "mcf": {"observed": _observed(np_model)},
    }


# ---- Proportional intensity -------------------------------------------------

def _ratio_reading(name: str, meta: list, ratio: float, ci) -> tuple[str, str]:
    """``(reading, effect)``: what a coefficient means, in words."""
    col = next((m for m in meta if name == m["column"] or name.startswith(m["column"] + ": ")), None)
    if col and col["kind"] == "category":
        level = name[len(col["column"]) + 2:]
        subject = f"{col['column']} {level}"
        versus = f" as at {col['reference']}"
    else:
        subject = f"each 1 more {name}"
        versus = ""
    effect = "unclear"
    if ci:
        effect = "higher" if ci[0] > 1 else "lower" if ci[1] < 1 else "unclear"
    if col and col["kind"] == "category":
        text = f"At {subject}, failures come about {ratio:.2g}× as often{versus}"
        if ci:
            text += f" (we're 95% sure it's {ci[0]:.2g}× to {ci[1]:.2g}×)"
    else:
        text = f"With {subject}, failures come {_change(ratio)}"
        if ci:
            text += f" (we're 95% sure: {_change(ci[0], short=True)} to {_change(ci[1], short=True)})"
    text += "." if effect != "unclear" else ", but the data can't rule out no effect."
    return text[0].upper() + text[1:], effect


def _change(ratio: float, short: bool = False) -> str:
    """A rate ratio as a change: "about 3.3% more often", "12% less"."""
    pct = (ratio - 1.0) * 100.0
    size = f"{abs(pct):.2g}%"
    word = "more" if pct >= 0 else "less"
    return f"{size} {word}" if short else f"about {size} {word} often"


def _profiles(meta: list, names: list, Z: np.ndarray, i: np.ndarray) -> tuple[np.ndarray, list]:
    """The fleet's average system (each covariate averaged over systems, so a
    system with many failures doesn't count more) and, for the first
    categorical covariate, one profile per level with the rest at that
    average: ``(average, [(label, z), ...])``."""
    ids = np.asarray(i)
    _, first = np.unique(ids, return_index=True)
    avg = Z[first].mean(axis=0)
    cat = next((m for m in meta if m["kind"] == "category"), None)
    groups = []
    if cat:
        cols = [k for k, nm in enumerate(names) if nm.startswith(cat["column"] + ": ")]
        for level in cat["levels"]:
            z = avg.copy()
            z[cols] = 0.0
            name = f"{cat['column']}: {level}"
            if name in names:
                z[names.index(name)] = 1.0
            groups.append((f"{cat['column']} {level}", z))
    return avg, groups


def regression_payload(np_model, live, inputs: dict, Z: np.ndarray, meta: list, model_id: str, opts: dict,
                       unit: str, gof_test: bool) -> dict:
    from backend.recurrent import growth_verdict

    out = _base(np_model, inputs, model_id, opts, unit)
    names = list(live.feature_names or [])
    rows = _summary_rows(live)
    baseline = opts["baseline"]
    rate_names = list(live._rate_names)
    params = _param_rows(rows, rate_names)
    cis = {p["name"]: p["ci"] for p in params if p.get("ci")}
    native = [p["value"] for p in params]
    growth, basis = growth_verdict(baseline, native, cis)
    coefs = []
    for name in names:
        est, lo, hi = rows.get(name, (None, None, None))
        if est is None or not np.isfinite(est):
            coefs.append({"name": name, "coef": None, "reading": f"{name}: the data can't estimate this effect "
                                                               "(it is constant or duplicates another)."})
            continue
        ratio = float(np.exp(est))
        ci = [float(np.exp(lo)), float(np.exp(hi))] if lo is not None else None
        reading, effect = _ratio_reading(name, meta, ratio, ci)
        coefs.append({"name": name, "coef": est, "coef_ci": [lo, hi] if lo is not None else None,
                      "ratio": ratio, "ratio_ci": ci, "effect": effect, "reading": reading})
    avg, groups = _profiles(meta, names, Z, np.asarray(inputs["i"]))
    t_end = out["end_of_observation"]
    grid = np.linspace(0.0, float(np.max(inputs["x"])) if len(inputs["x"]) else 1.0, _GRID)
    with np.errstate(all="ignore"):
        fitted = np.asarray(live.cif(grid, avg), dtype=float)
        curves = [{"label": label, "x": grid.tolist(), "mcf": np.asarray(live.cif(grid, z), dtype=float).tolist()}
                  for label, z in groups]
    rocof = mtbf = rocof_ci = mtbf_ci = None
    if t_end and t_end > 0:
        t = np.array([float(t_end)])
        with warnings.catch_warnings(), np.errstate(all="ignore"):
            warnings.simplefilter("ignore")
            rocof = _first(live.iif(t, avg))
            try:
                cb = np.asarray(live.iif_cb(t, avg, alpha_ci=1 - CI_LEVEL), dtype=float).ravel()
                rocof_ci = [float(cb[0]), float(cb[1])]
                mtbf_ci = [1.0 / rocof_ci[1], 1.0 / rocof_ci[0]] if rocof_ci[0] > 0 else None
            except Exception:  # noqa: BLE001 - no likelihood
                pass
        mtbf = 1.0 / rocof if rocof and rocof > 0 else None
    shape_name = "alpha" if baseline == "duane" else "beta"
    out.update({
        "params": params,
        "beta": dict((p["name"], p["value"]) for p in params).get(shape_name) if baseline != "cox_lewis" else None,
        "beta_ci": cis.get(shape_name) if baseline != "cox_lewis" else None,
        "growth": growth,
        "growth_basis": basis,
        "rocof": rocof, "mtbf": mtbf, "rocof_ci": rocof_ci, "mtbf_ci": mtbf_ci,
        "demonstrated_mtbf": None,
        "bounds_method": "wald" if rocof_ci else None,
        "rates_at": "the fleet's average system",
        "baseline": {"id": baseline, "name": BASELINE_NAMES[baseline]},
        "covariates": meta,
        "coefficients": coefs,
        "average_profile": dict(zip(names, avg.tolist())),
        "mcf": {**out["mcf"], "fitted": {"x": grid.tolist(), "mcf": fitted.tolist(), "label": "Average system"},
                "groups": curves},
        **_diagnostics(live, out["n_events"], out["n_systems"], gof_test, slow=True),
    })
    return _json_safe(out)


# ---- Imperfect repair --------------------------------------------------------

_RESTORATION = {
    "grp_i": ("q", "Restoration factor q", "kijima"),
    "grp_ii": ("q", "Restoration factor q", "kijima"),
    "ara": ("rho", "Repair efficiency ρ", "rho"),
    "ari": ("rho", "Repair efficiency ρ", "rho"),
    "g1": ("q", "Gap factor q", "g1"),
}


def restoration(model_id: str, opts: dict, value: float, ci) -> dict:
    """The repair-effectiveness parameter in words: how much of a system's
    age (or failure rate) each repair takes away, with its 95% interval."""
    param, label, kind = _RESTORATION[model_id]
    out = {"parameter": param, "label": label, "value": value, "ci": ci}
    if kind == "g1":
        ratio = 1.0 + value
        rci = [1.0 + ci[0], 1.0 + ci[1]] if ci else None
        trend = "shrinks" if ratio < 1 else "grows" if ratio > 1 else "stays the same"
        text = f"Each time between failures is about {ratio:.2f}× the one before"
        short = f"{text}: the gap {trend} with every repair."
        if rci:
            text += f" (we're 95% sure: {rci[0]:.2f}× to {rci[1]:.2f}×)"
        text += f": the gap {trend} with every repair"
        text += " (deterioration)." if ratio < 1 else " (improvement)." if ratio > 1 else "."
        out.update({"effectiveness": None, "ratio": ratio, "ratio_ci": rci, "sentence": text, "short": short,
                    "scale": "Below 1, failures come closer together; above 1, further apart."})
        return out
    if kind == "kijima":
        eff = 1.0 - value
        eci = [1.0 - ci[1], 1.0 - ci[0]] if ci else None
        what = "the age gained since the last repair" if model_id == "grp_i" else "the system's age"
    elif model_id == "ara":
        eff = value
        eci = list(ci) if ci else None
        what = ("the age gained since the last repair" if opts.get("m") == 1
                else "the system's age" if opts.get("m") == "all"
                else f"the age gained over the last {opts.get('m')} repairs")
    else:  # ARI
        eff = value
        eci = list(ci) if ci else None
        what = ("the rise in failure rate since the last repair" if opts.get("m") == 1
                else "the failure rate built up so far" if opts.get("m") == "all"
                else f"the rise in failure rate over the last {opts.get('m')} repairs")
    if eff < -0.005:
        text = (f"Each repair leaves the system older than before it failed: {_pct(-eff)} more than {what} "
                "is added (worse than a minimal repair)")
    else:
        text = f"Each repair takes away about {_pct(max(eff, 0.0))} of {what}"
    short = text + "."
    if eci:
        lo, hi = max(eci[0], -9.99), min(eci[1], 9.99)
        text += f" (we're 95% sure: {_pct(lo)} to {_pct(hi)})"
    text += "."
    scale = ("0% is a minimal repair (as bad as old)." if model_id == "ari"
             else "100% is as good as new, 0% as bad as old.")
    out.update({"effectiveness": eff, "effectiveness_ci": eci, "sentence": text, "short": short, "scale": scale})
    return out


def repair_verdict(model, model_id: str) -> dict | None:
    """``repair_test()`` as a verdict: are the repairs perfect (as good as
    new), minimal (as bad as old), or in between?"""
    try:
        with warnings.catch_warnings(), np.errstate(all="ignore"):
            warnings.simplefilter("ignore")
            rt = model.repair_test(alpha_ci=0.05)
    except Exception:  # noqa: BLE001 - no likelihood
        return None

    def part(fit):
        if fit is None:
            return None
        return {"hypothesis": fit.hypothesis, "value": float(fit.value), "p_value": float(fit.p_value),
                "statistic": float(fit.statistic), "rejected": bool(fit.p_value < 0.05)}

    best, worst = part(rt.perfect), part(rt.minimal)
    top = "maximal repair" if best and best["hypothesis"].startswith("maximal") else "perfect repair"
    if model_id == "g1":
        verdict = "renewal" if best and not best["rejected"] else "not_renewal"
        sentence = ("The gaps between failures don't change from repair to repair: an ordinary renewal "
                    "process (as good as new) fits." if verdict == "renewal" else
                    "The gaps between failures change from repair to repair: not as good as new.")
    elif best and worst:
        if best["rejected"] and worst["rejected"]:
            verdict = "partial"
            sentence = ("Repairs are partial: better than as bad as old, short of "
                        + ("the most an ARI repair can do." if top == "maximal repair" else "as good as new."))
        elif worst["rejected"]:
            verdict = "maximal" if top == "maximal repair" else "perfect"
            sentence = ("Consistent with the most an ARI repair can do; minimal repair is ruled out."
                        if verdict == "maximal" else
                        "Consistent with perfect repair: each repair leaves the system as good as new.")
        elif best["rejected"]:
            verdict = "minimal"
            sentence = ("Consistent with minimal repair: each repair leaves the system as it was just before "
                        "the failure, so a Crow-AMSAA-style model is enough.")
        else:
            verdict = "unclear"
            sentence = "The data can't tell perfect repair from minimal repair: more failures per system would."
    else:
        verdict, sentence = "unclear", str(rt.conclusion)
    return {"verdict": verdict, "sentence": sentence, "conclusion": str(rt.conclusion), "level": 0.05,
            "perfect": best, "minimal": worst}


def _gap_scale(model, inputs: dict) -> float:
    x, i = np.asarray(inputs["x"], dtype=float), np.asarray(inputs["i"])
    gaps = []
    for sys_id in np.unique(i):
        t = np.sort(x[i == sys_id])
        gaps.extend(np.diff(np.r_[0.0, t]).tolist())
    gaps = [g for g in gaps if g > 0]
    return float(np.median(gaps)) if gaps else max(float(np.max(x)) / 10.0, 1.0)


def next_failures(model, inputs: dict) -> dict | None:
    """Each system's next failure from where its history leaves it
    (``unit_states``, ``next_failure_sf``): its failures and age now, the
    median time to its next failure and the time by which there's a 10%
    chance of it, soonest first; and the survival curves of the soonest."""
    try:
        with warnings.catch_warnings(), np.errstate(all="ignore"):
            warnings.simplefilter("ignore")
            states = model.unit_states()
            h = _gap_scale(model, inputs)
            for _ in range(14):
                grid = np.linspace(0.0, h, _GRID)
                sf = np.atleast_2d(np.asarray(model.next_failure_sf(grid), dtype=float))
                if np.nanmax(sf[:, -1]) < 0.02:
                    break
                h *= 2.0
    except Exception:  # noqa: BLE001 - restored without data, or no prediction for this family
        return None
    sf = np.nan_to_num(sf, nan=0.0)
    units = []
    for k, (label, row) in enumerate(states.iterrows()):
        curve = sf[k]
        rev_s, rev_x = curve[::-1], grid[::-1]

        def at(p):
            return float(np.interp(1.0 - p, rev_s, rev_x)) if curve[-1] <= 1.0 - p else None

        unit = {"system": str(label), "age": float(row["time"]), "failures": int(row["failures"]),
                "since_failure": float(row["since_failure"]), "median": at(0.5), "b10": at(0.1),
                "mean": float(np.trapezoid(curve, grid)) if curve[-1] < 0.02 else None}
        if "virtual_age" in row:
            unit["virtual_age"] = float(row["virtual_age"])
        if "reduction" in row:
            unit["intensity_reduction"] = float(row["reduction"])
        units.append((unit, curve))
    units.sort(key=lambda uc: (uc[0]["median"] is None, uc[0]["median"] or 0.0))
    return {
        "x": grid.tolist(),
        "units": [u for u, _ in units[:_UNIT_ROWS]],
        "curves": [{"system": u["system"], "sf": c.tolist()} for u, c in units[:_UNIT_CURVES]],
        "n_systems": len(units),
        "note": ("From each system's state at the end of its history: its age now, its failures and how long "
                 "since the last one."),
    }


def renewal_payload(np_model, live, inputs: dict, model_id: str, opts: dict, unit: str, gof_test: bool) -> dict:
    out = _base(np_model, inputs, model_id, opts, unit)
    rows = _summary_rows(live)
    names = list(live.parameter_names)
    params = _param_rows(rows, names)
    rest_name = _RESTORATION[model_id][0]
    est, lo, hi = rows.get(rest_name, (None, None, None))
    rest = restoration(model_id, opts, float(est), [lo, hi] if lo is not None else None) if est is not None else None
    grid = np.linspace(0.0, float(out["end_of_observation"]) or 1.0, _GRID)
    with warnings.catch_warnings(), np.errstate(all="ignore"):
        warnings.simplefilter("ignore")
        fitted = np.asarray(live.mcf(grid, items=1000, random_state=0), dtype=float)
    shape = next((p for p in params if p["name"] == "beta"), None)
    out.update({
        "params": params,
        "beta": shape["value"] if shape and model_id != "ari" else None,
        "beta_ci": shape.get("ci") if shape and model_id != "ari" else None,
        "growth": None, "growth_basis": None,
        "rocof": None, "mtbf": None, "rocof_ci": None, "mtbf_ci": None, "demonstrated_mtbf": None,
        "bounds_method": None,
        "lifetime": "Weibull" if model_id != "ari" else None,
        "baseline": {"id": opts["baseline"], "name": BASELINE_NAMES[opts["baseline"]]} if model_id == "ari" else None,
        "restoration": rest,
        "repair_test": repair_verdict(live, model_id),
        "next_failure": next_failures(live, inputs),
        "mcf": {**out["mcf"], "fitted": {"x": grid.tolist(), "mcf": fitted.tolist(), "simulated": True}},
        **_diagnostics(live, out["n_events"], out["n_systems"], gof_test, slow=True),
    })
    return _json_safe(out)


# ---- A renewal model's next failure at a given age (MCP) ----------------------

def renewal_next_failure(model, age, within=None, quantiles=None) -> dict:
    """The next failure of a system that has run ``age`` since new without a
    failure, under a fitted imperfect-repair model (``next_failure_sf``)."""
    age = float(age)
    if not np.isfinite(age) or age < 0:
        raise FitError("The age must be zero or a positive time.")
    within = [float(w) for w in (within or [])]
    if any(not np.isfinite(w) or w <= 0 for w in within):
        raise FitError("Each 'within' time must be a positive time ahead.")
    quantiles = [0.1, 0.5, 0.9] if quantiles is None else [float(q) for q in quantiles]
    if any(not 0 < q < 1 for q in quantiles):
        raise FitError("Quantiles must be between 0 and 1 (e.g. 0.5 for the median).")
    with warnings.catch_warnings(), np.errstate(all="ignore"):
        warnings.simplefilter("ignore")
        h = max(age, 1.0)
        try:
            for _ in range(40):
                grid = np.linspace(0.0, h, 2000)
                sf = np.asarray(model.next_failure_sf(grid, age=[age]), dtype=float).reshape(-1)
                if sf[-1] < 1e-4:
                    break
                h *= 2.0
            hf0 = _first(model.next_failure_hf(0.0, age=[age]))
            at = (np.asarray(model.next_failure_sf(np.asarray(within), age=[age]), dtype=float).reshape(-1)
                  if within else [])
        except Exception as exc:  # noqa: BLE001
            raise FitError(f"Can't predict the next failure from this model: {exc}") from exc
    rev_s, rev_x = sf[::-1], grid[::-1]
    return _json_safe({
        "age": age,
        "rocof": hf0,
        "instantaneous_mtbf": (1.0 / hf0) if hf0 else None,
        "mean_time_to_next_failure": float(np.trapezoid(sf, grid)),
        "quantiles": [{"q": q, "time_ahead": float(np.interp(1 - q, rev_s, rev_x)),
                       "age_at": float(np.interp(1 - q, rev_s, rev_x)) + age} for q in quantiles],
        "within": [{"time_ahead": w, "prob_failure": float(1.0 - s)} for w, s in zip(within, at)],
        "assumption": ("Imperfect repair: the system has run this long since new without a failure; its next "
                       "failure follows the fitted model from that state."),
    })
