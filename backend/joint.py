"""Condition and life: joint models of a marker's readings and units' lives.

A joint model (SurPyval's ``JointPH``) fits two things together: how a
measurement read again and again on each unit (vibration, wear, oil debris)
drifts with age, and how the unit's risk of failing rises with that
measurement. Each unit gets its own path; its failure rate is Weibull
proportional hazards in the path's current value and its covariates. A
running unit's readings so far then give its own updating survival curve
(``JointModel.predict`` → ``DynamicPrediction``).

The data are two tables: one row per unit (its id, its age at failure or
when last seen running, the censoring flag, optional entry age and
covariates) and one row per reading (unit id, age, value). Ages are since
new, in the model's time unit. Readings are grouped here into each unit's
``{age: value}``.

This module holds no database code: the compute service runs :func:`run_fit`
on a self-contained request (:func:`fit_request`), and the web app saves
what comes back (``backend.services.joint``).
"""

from __future__ import annotations

import io
import math
import warnings
from typing import Any, Optional

import numpy as np
import pandas as pd

from backend.fitting import FitError
from backend.units import canonical_unit, normalize_unit, unit_in_text

#: The path models offered, by id: (SurPyval's class name, label, formula,
#: a plain description). Linear first: the default.
PATHS: dict[str, tuple[str, str, str, str]] = {
    "linear": ("LinearPath", "Linear", "a + b t", "The reading rises (or falls) at a steady rate."),
    "exponential": ("ExponentialPath", "Exponential", "a exp(b t)",
                    "The reading grows by a fixed proportion per unit of time (positive readings)."),
    "power": ("PowerPath", "Power", "a t^b", "The reading grows as a power of age (positive ages)."),
    "logarithmic": ("LogarithmicPath", "Logarithmic", "a + b log(t)",
                    "The reading rises quickly at first, then levels off (positive ages)."),
    "quadratic": ("QuadraticPath", "Quadratic", "a + b t + c t^2",
                  "The rate of change itself changes with age. Slower to fit."),
}
DEFAULT_PATH = "linear"

#: The most units and readings one fit takes: the request travels to the
#: compute service whole (Cloud Tasks caps a task near 1 MB).
MAX_UNITS = 2000
MAX_READINGS = 20000
#: The quadratic path's three varying parameters make a fit about 30 times
#: slower: fewer units, so a fit stays within the compute job's deadline.
MAX_UNITS_QUADRATIC = 600
#: The running units whose risk the fit works out (each a prediction).
MAX_RISK_UNITS = 500
#: The confidence level of every interval shown.
ALPHA_CI = 0.05
#: The risk table's horizons in days, for a calendar time unit.
HORIZON_DAYS = (30, 90, 365)
_DAYS_PER = {"second": 1 / 86400, "minute": 1 / 1440, "hour": 1 / 24, "day": 1.0, "week": 7.0,
             "month": 365.25 / 12, "year": 365.25}

LIFE_KEYS = ("id", "x", "c", "xl", "xr", "tl")
READING_KEYS = ("id", "age", "value")


def options() -> dict:
    """What the new-model form offers."""
    return {
        "paths": [{"id": k, "name": v[1], "formula": v[2], "description": v[3]} for k, v in PATHS.items()],
        "default_path": DEFAULT_PATH,
        "limits": {"units": MAX_UNITS, "readings": MAX_READINGS},
    }


def path_label(path_id: str) -> str:
    return PATHS.get(path_id, PATHS[DEFAULT_PATH])[1]


def _path_class(path_id: str):
    from surpyval.degradation import path_models

    if path_id not in PATHS:
        raise FitError(f"Unknown path model {path_id!r}: use one of {', '.join(PATHS)}.")
    return getattr(path_models, PATHS[path_id][0])


def fitter(path_id: str = DEFAULT_PATH):
    """The SurPyval joint fitter for a path: the Weibull baseline (the one
    SurPyval's joint models have for now)."""
    from surpyval import JointPH, Weibull

    return JointPH(Weibull, _path_class(path_id))


# ---- The data ------------------------------------------------------------------


def _column(df: pd.DataFrame, name: Optional[str], what: str) -> Optional[pd.Series]:
    if not name:
        return None
    if name not in df.columns:
        raise FitError(f"The {what} column {name!r} isn't in the table (it has {', '.join(map(str, df.columns))}).")
    return df[name]


def _numbers(series: pd.Series, what: str) -> np.ndarray:
    values = pd.to_numeric(series, errors="coerce")
    bad = series[values.isna() & series.notna() & (series.astype(str).str.strip() != "")]
    if len(bad):
        raise FitError(f"The {what} column must hold numbers; it has {str(bad.iloc[0])!r}.")
    return values.to_numpy(dtype=float)


def _ids(series: pd.Series) -> list[str]:
    def one(v) -> str:
        if isinstance(v, float) and v.is_integer():
            v = int(v)
        return str(v).strip()

    return [one(v) for v in series]


def build_items(
    life: pd.DataFrame,
    readings: pd.DataFrame,
    mapping: dict,
    readings_mapping: dict,
    covariates: Optional[list] = None,
    c_invert: bool = False,
) -> tuple[list[dict], dict]:
    """Each unit as a plain record, with its readings grouped, and a summary.

    ``mapping`` names the lifetimes table's columns: ``id``, ``x`` (age at
    failure or censoring) or ``xl`` and ``xr`` (an interval: found failed
    between two ages), ``c`` (the censoring flag: 0 failed, 1 still running,
    -1 failed by x, 2 failed in [xl, xr]) and ``tl`` (the age it came under
    observation). ``readings_mapping`` names the readings table's ``id``,
    ``age`` and ``value``. Ages are since new. ``covariates`` are numeric
    columns of the lifetimes table. ``c_invert`` flips 0 and 1 (a sheet
    with 1 = failed).

    A record: ``{"id", "x" | "xl"+"xr", "c", "tl", "z", "markers": [[age,
    value], ...]}``. Raises :class:`FitError` with what to fix."""
    mapping = {k: v for k, v in (mapping or {}).items() if v}
    rmap = {k: v for k, v in (readings_mapping or {}).items() if v}
    covariates = [str(c) for c in (covariates or []) if c]
    for key in ("id",):
        if key not in mapping:
            raise FitError("Pick the lifetimes table's unit id column: it links each unit to its readings.")
    for key in READING_KEYS:
        if key not in rmap:
            raise FitError("Pick the readings table's unit id, age and value columns.")
    interval = "xl" in mapping or "xr" in mapping
    if interval and not ("xl" in mapping and "xr" in mapping):
        raise FitError("An interval needs both ends: pick the lower and the upper age columns.")
    if not interval and "x" not in mapping:
        raise FitError("Pick the lifetimes table's age column: each unit's age at failure, or when last seen running.")
    if "c" not in mapping:
        raise FitError("Pick the censoring column (0 = failed, 1 = still running): the risk of the units still "
                       "running is what this model is for.")
    if len(covariates) != len(set(covariates)):
        raise FitError("Each covariate once, please.")
    if len(life) > MAX_UNITS:
        raise FitError(f"A condition-based model takes up to {MAX_UNITS:,} units; this table has {len(life):,}.")
    if len(readings) > MAX_READINGS:
        raise FitError(f"A condition-based model takes up to {MAX_READINGS:,} readings; this table has "
                       f"{len(readings):,}.")

    ids = _ids(_column(life, mapping["id"], "unit id"))
    seen: set = set()
    twice = [i for i in ids if i in seen or seen.add(i)]
    if twice:
        raise FitError(f"The lifetimes table has one row per unit, but unit {twice[0]!r} appears more than once.")
    if interval:
        xl = _numbers(_column(life, mapping["xl"], "lower age"), "lower age")
        xr = _numbers(_column(life, mapping["xr"], "upper age"), "upper age")
    else:
        x = _numbers(_column(life, mapping["x"], "age"), "age")
    raw_c = _numbers(_column(life, mapping["c"], "censoring"), "censoring")
    if np.isnan(raw_c).any():
        raise FitError("Every unit needs a censoring flag (0 = failed, 1 = still running).")
    c = raw_c.astype(int)
    if not np.all(np.isin(c, (0, 1, -1, 2))) or not np.allclose(raw_c, c):
        bad = raw_c[~np.isin(raw_c, (0, 1, -1, 2))][0]
        raise FitError(f"Censoring flags are 0 (failed), 1 (still running), -1 (failed by that age) or 2 (failed "
                       f"between two ages); the column has {bad:g}.")
    if c_invert:
        c = np.where(c == 0, 1, np.where(c == 1, 0, c))
    tl = _numbers(_column(life, mapping["tl"], "entry age"), "entry age") if "tl" in mapping else None
    Z = []
    for name in covariates:
        col = _column(life, name, "covariate")
        values = pd.to_numeric(col, errors="coerce")
        if values.isna().all() and col.notna().any():
            raise FitError(f"Covariate {name!r} isn't numeric. Use numbers (0/1 for a yes/no).")
        Z.append(values.to_numpy(dtype=float))
    Z = np.column_stack(Z) if Z else np.zeros((len(life), 0))

    # The readings, grouped by unit (duplicate ages averaged).
    r_ids = _ids(_column(readings, rmap["id"], "reading unit id"))
    r_age = _numbers(_column(readings, rmap["age"], "reading age"), "reading age")
    r_val = _numbers(_column(readings, rmap["value"], "reading value"), "reading value")
    frame = pd.DataFrame({"id": r_ids, "age": r_age, "value": r_val}).dropna()
    blank = len(r_ids) - len(frame)
    if (frame["age"] < 0).any():
        raise FitError("Reading ages are since new, 0 or more; the readings table has a negative age.")
    doubled = int(frame.duplicated(["id", "age"]).sum())
    frame = frame.groupby(["id", "age"], sort=True, as_index=False)["value"].mean()
    grouped = {k: g[["age", "value"]].to_numpy(dtype=float).tolist() for k, g in frame.groupby("id", sort=False)}
    known = set(ids)
    unmatched = sorted(k for k in grouped if k not in known)

    items: list[dict] = []
    dropped_missing: list[str] = []
    late: list[str] = []
    for k, uid in enumerate(ids):
        if np.isnan(Z[k]).any():
            dropped_missing.append(uid)
            continue
        flag = int(c[k])
        rec: dict = {"id": uid, "c": flag}
        if interval:
            lo, hi = float(xl[k]), float(xr[k])
            if np.isfinite(lo) and not np.isfinite(hi) and flag != 2:
                hi = lo  # a failed or running unit: its one age (the upper column left blank)
            if not (np.isfinite(lo) and np.isfinite(hi)):
                raise FitError(f"Unit {uid!r} needs both ages of its interval.")
            if lo > hi:
                raise FitError(f"Unit {uid!r}: its lower age {lo:g} is after its upper age {hi:g}.")
            if lo == hi and flag == 2:
                flag = rec["c"] = 0
            if lo < hi and flag in (0, 1):
                raise FitError(f"Unit {uid!r} has an interval ({lo:g} to {hi:g}) but a censoring flag of {flag}: "
                               "use 2 for a unit found failed between two ages.")
            rec["xl"], rec["xr"] = lo, hi
            end = hi
        else:
            if flag == 2:
                raise FitError(f"Unit {uid!r} is interval-censored (2): pick the lower and upper age columns "
                               "instead of a single age.")
            if not np.isfinite(x[k]):
                raise FitError(f"Unit {uid!r} has no age.")
            rec["x"] = float(x[k])
            end = float(x[k])
        if end <= 0:
            raise FitError(f"Unit {uid!r} has age {end:g}: ages are since new and must be above 0.")
        if tl is not None and np.isfinite(tl[k]):
            if tl[k] < 0 or tl[k] >= end:
                raise FitError(f"Unit {uid!r}: its entry age {tl[k]:g} must be 0 or more and before its age {end:g}.")
            rec["tl"] = float(tl[k])
        rec["z"] = [float(v) for v in Z[k]]
        markers = grouped.get(uid, [])
        if markers and markers[-1][0] > end + 1e-9 * max(1.0, abs(end)):
            late.append(f"{uid} (a reading at {markers[-1][0]:g}, its age is {end:g})")
        rec["markers"] = markers
        items.append(rec)
    if late:
        more = f" and {len(late) - 3} more" if len(late) > 3 else ""
        raise FitError("A unit's readings are those taken while it was in service: these units have a reading "
                       f"after their age: {'; '.join(late[:3])}{more}. Check the ages, or extend a running "
                       "unit's age to its last reading.")
    if not items:
        raise FitError("No units are left to fit.")
    with_readings = sum(1 for it in items if it["markers"])
    summary = {
        "n_units": len(items),
        "n_failed": sum(1 for it in items if it["c"] in (0, -1, 2)),
        "n_running": sum(1 for it in items if it["c"] == 1),
        "n_readings": int(sum(len(it["markers"]) for it in items)),
        "n_with_readings": with_readings,
        "unmatched_ids": unmatched[:20],
        "n_unmatched": len(unmatched),
        "notes": [],
    }
    notes = summary["notes"]
    if dropped_missing:
        notes.append(f"{len(dropped_missing)} unit(s) left out for a missing covariate value "
                     f"({', '.join(dropped_missing[:3])}{'…' if len(dropped_missing) > 3 else ''}).")
    if unmatched:
        notes.append(f"{len(unmatched)} unit id(s) in the readings aren't in the lifetimes table, so their "
                     f"readings are left out ({', '.join(unmatched[:3])}{'…' if len(unmatched) > 3 else ''}).")
    if doubled:
        notes.append(f"{doubled} reading(s) at an age a unit already had a reading at were averaged with it.")
    if blank:
        notes.append(f"{blank} reading row(s) with no id, age or value were skipped.")
    if summary["n_failed"] == 0:
        raise FitError("Every unit is still running: the model needs at least one failure.")
    return items, summary


def items_frame(items: list[dict], covariates: list[str]) -> pd.DataFrame:
    """The records as the DataFrame ``fit_from_df`` takes: one row per
    unit, its readings as ``{age: value}`` in ``readings``."""
    interval = any("xl" in it for it in items)
    rows = []
    for it in items:
        row: dict = {"id": it["id"], "censored": int(it["c"])}
        if interval:
            row["age_lower"], row["age_upper"] = it.get("xl", it.get("x")), it.get("xr", it.get("x"))
        else:
            row["age"] = it["x"]
        row["entry_age"] = it.get("tl", 0.0)
        for name, v in zip(covariates, it.get("z") or []):
            row[name] = v
        row["readings"] = {float(a): float(v) for a, v in it.get("markers") or []}
        rows.append(row)
    return pd.DataFrame(rows)


def _check_parts(covariates: list[str], hazard: Optional[list], path: Any) -> tuple[Optional[list], Any]:
    """The covariate parts as SurPyval takes them: None (every covariate in
    both), else lists of known names."""
    if hazard is None and path is None:
        return None, None
    known = set(covariates)
    hazard = list(covariates) if hazard is None else [str(h) for h in hazard]
    bad = [h for h in hazard if h not in known]
    if isinstance(path, dict):
        path = {str(k): [str(v) for v in (vs or [])] for k, vs in path.items()}
        bad += [v for vs in path.values() for v in vs if v not in known]
        in_path = {v for vs in path.values() for v in vs}
    else:
        path = list(covariates) if path is None else [str(p) for p in path]
        bad += [p for p in path if p not in known]
        in_path = set(path)
    if bad:
        raise FitError(f"{bad[0]!r} isn't one of the model's covariates ({', '.join(covariates) or 'none'}).")
    orphan = [c for c in covariates if c not in hazard and c not in in_path]
    if orphan:
        raise FitError(f"Covariate {orphan[0]!r} is in neither the risk nor the reading's path: put it in one "
                       "(or both), or leave it out.")
    return hazard, path


def fit_model(items: list[dict], covariates: list[str], path_model: str = DEFAULT_PATH,
              hazard_covariates: Optional[list] = None, path_covariates: Any = None):
    """Fit the joint model to the records. Returns ``(model, warnings)``."""
    hazard, path = _check_parts(covariates, hazard_covariates, path_covariates)
    df = items_frame(items, covariates)
    interval = "age_lower" in df.columns
    kwargs: dict = {
        "markers_col": "readings",
        "c_col": "censored",  # always: 0 = failed, 1 = still running
        **({"xl_col": "age_lower", "xr_col": "age_upper"} if interval else {"x_col": "age"}),
    }
    if (df["entry_age"] > 0).any():
        kwargs["tl_col"] = "entry_age"
    if covariates:
        kwargs["Z_cols"] = list(covariates)
        if hazard is not None:
            kwargs["hazard_covariates"] = hazard
            kwargs["path_covariates"] = path
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        try:
            with np.errstate(all="ignore"):
                model = fitter(path_model).fit_from_df(df, **kwargs)
        except (ValueError, np.linalg.LinAlgError) as exc:
            raise FitError(str(exc)) from exc
    notes = []
    for w in caught:
        text = " ".join(str(w.message).split())
        if text and text not in notes and not issubclass(w.category, DeprecationWarning):
            notes.append(text)
    return model, notes


# ---- What a fit shows ----------------------------------------------------------------


def _f(v) -> Optional[float]:
    try:
        v = float(v)
    except (TypeError, ValueError):
        return None
    return v if math.isfinite(v) else None


def horizons(unit: Optional[str], alpha: Optional[float] = None) -> dict:
    """The risk table's horizons: 30, 90 and 365 days in the model's unit for
    a calendar unit; otherwise a tenth, a quarter and half of the Weibull
    scale, in the model's own unit (cycles, km, ...)."""
    key = normalize_unit(unit)
    if key in _DAYS_PER:
        per = _DAYS_PER[key]
        return {"values": [d / per for d in HORIZON_DAYS], "labels": [f"{d} days" for d in HORIZON_DAYS],
                "basis": "days"}
    base = float(alpha) if alpha and math.isfinite(alpha) and alpha > 0 else 100.0
    vals = [_nice(base * f) for f in (0.1, 0.25, 0.5)]
    shown = unit_in_text(unit) or "time units"
    return {"values": vals, "labels": [f"{v:g} {shown}" for v in vals], "basis": "scale"}


def _nice(v: float) -> float:
    if v <= 0:
        return v
    p = 10 ** math.floor(math.log10(v))
    for m in (1, 2, 2.5, 5, 10):
        if v <= m * p * 1.12:
            return float(m * p)
    return float(10 * p)


_PARTS = {
    "path": "Reading path",
    "spread": "Spread between units",
    "noise": "Reading noise",
    "survival": "Survival (Weibull)",
    "link": "Link: reading to risk",
}


def _part(heading: str) -> str:
    h = heading.lower()
    for key in ("path", "spread", "noise", "survival", "link"):
        if h.startswith(key):
            return key
    return "path"


def parameter_rows(model) -> list[dict]:
    """Each parameter with its standard error and 95% interval (and, for the
    risk coefficients, the hazard ratio), and what it means in plain words."""
    table = model.summary(alpha_ci=ALPHA_CI).reset_index()
    path_names = list(model.path_model.parameter_names)
    out = []
    for row in table.to_dict("records"):
        part = _part(str(row["part"]))
        name = str(row["name"])
        rec = {
            "part": part,
            "part_label": _PARTS[part],
            "name": name,
            "value": _f(row.get("coef")),
            "se": _f(row.get("se(coef)")),
            "lower": _f(row.get("coef lower 95%")),
            "upper": _f(row.get("coef upper 95%")),
            "p": _f(row.get("p")),
        }
        if part in ("survival", "link") and name not in ("alpha", "beta"):
            rec.update(hr=_f(row.get("exp(coef)")), hr_lower=_f(row.get("exp(coef) lower 95%")),
                       hr_upper=_f(row.get("exp(coef) upper 95%")))
        rec["meaning"] = _meaning(part, name, path_names, model)
        out.append(rec)
    return out


def _meaning(part: str, name: str, path_names: list, model) -> str:
    if part == "path":
        base, _, cov = name.partition("_")
        if cov and base in path_names:
            return f"How {cov} shifts the path's {base} (per unit of {cov})."
        return {"a": "The path's starting level (the reading at age 0, for a linear path).",
                "b": "The path's rate: how fast the reading changes with age.",
                "c": "The path's curvature: how the rate itself changes with age."}.get(
            name, f"The path's {name}, averaged over units.")
    if part == "spread":
        if name.startswith("sd_"):
            return f"How much {name[3:]} differs from unit to unit (a standard deviation)."
        return "How the units' path parameters move together (a correlation, -1 to 1)."
    if part == "noise":
        return "Scatter of single readings about a unit's own path (a standard deviation)."
    if name == "alpha":
        return (f"Weibull scale: the characteristic life of a unit whose reading stays at "
                f"{model.marker_reference:.4g}, with covariates at 0.")
    if name == "beta":
        return "Weibull shape: below 1 early failures, near 1 random, above 1 wear-out (before the reading's effect)."
    if part == "link":
        return "Change in the log failure rate per 1 unit of the reading; exp of it is the hazard ratio."
    return f"Change in the log failure rate per 1 unit of {name}, at the same reading."


def hazard_ratios(rows: list[dict], marker: str) -> list[dict]:
    """The risk coefficients as hazard ratios, each said in plain words."""
    out = []
    for r in rows:
        if r.get("hr") is None:
            continue
        what = f"1 unit higher {marker}" if r["part"] == "link" else f"1 unit higher {r['name']}"
        hr = r["hr"]
        lo, hi = r.get("hr_lower"), r.get("hr_upper")
        if hr >= 1:
            text = f"Each {what} multiplies the failure rate by {hr:.3g}"
        else:
            text = f"Each {what} cuts the failure rate to {hr:.3g} times"
        if r["part"] != "link":
            text += f" at the same {marker}"
        if lo is not None and hi is not None:
            text += f" (95% CI {lo:.3g} to {hi:.3g})"
            if lo <= 1 <= hi:
                text += "; the interval includes 1, so the data can't rule out no effect"
        out.append({"name": r["name"], "kind": "marker" if r["part"] == "link" else "covariate",
                    "hr": hr, "lower": lo, "upper": hi, "text": text + "."})
    return out


def _covariate_dict(model, z) -> dict:
    return {n: float(v) for n, v in zip(model.feature_names, np.ravel(z))}


def _mean_covariates(model) -> dict:
    """The covariates at the fitted units' means (an aliased one at 0)."""
    names = list(model.feature_names)
    if not names:
        return {}
    zbar = np.zeros(len(names))
    kept = np.setdiff1d(np.arange(len(names)), np.asarray(model.aliased, dtype=int))
    zbar[kept] = np.asarray(model._zbar, dtype=float)
    return dict(zip(names, zbar.tolist()))


def _sample_paths(items: list[dict], limit_units: int = 40, limit_points: int = 2000) -> list[dict]:
    """Some units' readings for the path chart: running units first."""
    order = sorted(items, key=lambda it: (it["c"] != 1, it["id"]))
    out, points = [], 0
    for it in order:
        m = it.get("markers") or []
        if not m:
            continue
        if len(out) >= limit_units or points + len(m) > limit_points:
            break
        out.append({"id": it["id"], "status": "running" if it["c"] == 1 else "failed",
                    "ages": [a for a, _ in m], "values": [v for _, v in m]})
        points += len(m)
    return out


def _end(it: dict) -> float:
    return float(it.get("xr", it.get("x")))


def unit_inputs(items: list[dict], covariates: list[str]) -> dict:
    """The running units' inputs to a prediction, by id: what an RBD block
    or the unit view needs (``{"age", "covariates", "markers"}``)."""
    return {
        it["id"]: {"age": _end(it), "covariates": dict(zip(covariates, it.get("z") or [])),
                   "markers": it.get("markers") or []}
        for it in items if it["c"] == 1
    }


def predict(model, covariates: Optional[dict], markers, age: Optional[float]):
    """The unit's ``DynamicPrediction`` (markers as ``[[age, value]]`` or
    ``{age: value}``). Raises :class:`FitError` with the library's reason."""
    if isinstance(markers, dict):
        readings = {float(a): float(v) for a, v in markers.items()}
    else:
        readings = {float(a): float(v) for a, v in (markers or [])}
    names = list(model.feature_names)
    Z = None
    if names:
        given = dict(covariates or {})
        missing = [n for n in names if given.get(n) is None]
        if missing:
            raise FitError(f"Give the unit's {', '.join(missing)}: the model was fitted with "
                           f"{', '.join(names)}.")
        extra = [n for n in given if n not in names]
        if extra:
            raise FitError(f"{extra[0]!r} isn't one of this model's covariates ({', '.join(names)}).")
        try:
            Z = {n: float(given[n]) for n in names}
        except (TypeError, ValueError) as exc:
            raise FitError("Covariate values must be numbers.") from exc
    elif covariates:
        raise FitError("This model has no covariates: leave them out.")
    if age is None and readings:
        age = max(readings)
    try:
        return model.predict(Z, readings or None, given=None if age is None else float(age))
    except (TypeError, ValueError) as exc:
        raise FitError(str(exc)) from exc


def risk_row(pred, h: list[float]) -> dict:
    """A running unit's risk over the horizons ``h`` and its median remaining
    life (None where the curve never falls to a half: shown as not reached,
    never as an infinite mean)."""
    with np.errstate(all="ignore"):
        sf = np.asarray(pred.sf(pred.age + np.asarray(h, dtype=float)), dtype=float)
        median = float(pred.remaining_life(0.5))
        now = pred.marker(np.array([pred.age]))
    return {
        "survival": [_f(v) for v in sf],
        "risk": [_f(1 - v) for v in sf],
        "median_remaining": _f(median),
        "median_reached": bool(math.isfinite(median)),
        "marker_now": _f(np.ravel(now)[0]),
    }


def risk_table(model, inputs: dict, h: list[float], limit: int = MAX_RISK_UNITS) -> tuple[list[dict], list[str]]:
    """The running units' risk, highest first over the middle horizon."""
    rows, notes = [], []
    for k, (uid, inp) in enumerate(inputs.items()):
        if k >= limit:
            notes.append(f"Risk is listed for the first {limit} running units; open any other in the unit view.")
            break
        try:
            pred = predict(model, inp.get("covariates"), inp.get("markers"), inp.get("age"))
            row = risk_row(pred, h)
        except FitError as exc:
            notes.append(f"Unit {uid}: {exc}")
            continue
        last = (inp.get("markers") or [None])[-1]
        rows.append({"id": uid, "age": inp.get("age"), "covariates": inp.get("covariates") or {},
                     "n_readings": len(inp.get("markers") or []), "last_reading": last, **row})
    mid = 1 if len(h) > 1 else 0
    rows.sort(key=lambda r: -(r["risk"][mid] if r["risk"][mid] is not None else -1))
    return rows, notes


def results_payload(model, items: list[dict], covariates: list[str], *, path_model: str, unit: str,
                    marker: str, marker_unit: str = "", notes: Optional[list] = None,
                    summary: Optional[dict] = None) -> dict:
    """What the results page and MCP show for a fitted model."""
    unit = canonical_unit(unit)
    marker = (marker or "").strip() or "reading"
    rows = parameter_rows(model)
    alpha = next((r["value"] for r in rows if r["name"] == "alpha"), None)
    h = horizons(unit, alpha)
    inputs = unit_inputs(items, covariates)
    risk, risk_notes = risk_table(model, inputs, h["values"])
    max_age = max(_end(it) for it in items)
    # A new unit at the fleet's mean covariates: the population's path and
    # survival curve.
    typical = _mean_covariates(model)
    new = predict(model, typical, None, None)
    grid = np.linspace(0.0, max_age * 1.25, 101)
    with np.errstate(all="ignore"):
        new_dict = new.to_dict(x=grid, alpha_ci=ALPHA_CI)
    all_notes = list(summary.get("notes") or []) if summary else []
    all_notes += list(notes or []) + risk_notes
    if model.maximum != "verified":
        all_notes.insert(0, "The fit didn't reach a verified maximum of the likelihood: treat these numbers with "
                            "care, and check the data (enough failures, enough readings per unit).")
    return {
        "kind": "joint",
        "distribution": f"Condition and life (Weibull, {path_label(path_model).lower()} path)",
        "distribution_id": f"joint_weibull_{path_model}",
        "path_model": path_model,
        "path_label": path_label(path_model),
        "path_formula": PATHS[path_model][2],
        "varying": list(model.varying),
        "unit": unit,
        "marker": marker,
        "marker_unit": (marker_unit or "").strip(),
        "marker_reference": _f(model.marker_reference),
        "covariates": list(model.feature_names),
        "hazard_covariates": list(model.hazard_covariates) if model.hazard_covariates is not None
        else list(model.feature_names),
        "path_covariates": model.path_covariates,
        "typical_covariates": typical,
        "n": int(round(model.n_items)),
        "n_items": int(round(model.n_items)),
        "n_events": int(round(model.n_events)),
        "n_readings": int(round(model.n_readings)),
        "n_running": len(inputs),
        "maximum": model.maximum,
        "fit_ok": model.maximum == "verified",
        "log_likelihood": _f(-model.neg_ll()) if hasattr(model, "neg_ll") else None,
        "aic": _f(model.aic()) if hasattr(model, "aic") else None,
        "confidence": 1 - ALPHA_CI,
        "params": rows,
        "hazard_ratios": hazard_ratios(rows, marker),
        "path": {"sample": _sample_paths(items), **new_dict["marker"]},
        "survival_new": {"x": new_dict["x"], "sf": new_dict["sf"], "sf_lower": new_dict["sf_lower"],
                         "sf_upper": new_dict["sf_upper"], "remaining_life": new_dict["remaining_life"]},
        "horizons": h,
        "risk": risk,
        "notes": all_notes,
    }


def unit_view(model, covariates: Optional[dict], markers, age: Optional[float], unit: str,
              h: Optional[dict] = None) -> dict:
    """One unit's updating prediction: its survival curve from its age now
    with bounds, its remaining-life quantiles, and its marker's smoothed and
    projected path with an interval (``DynamicPrediction.to_dict``)."""
    pred = predict(model, covariates, markers, age)
    if h is None:
        alpha = float(model.params[model.parameter_names.index("alpha")])
        h = horizons(unit, alpha)
    with np.errstate(all="ignore"):
        d = pred.to_dict(alpha_ci=ALPHA_CI)
    row = risk_row(pred, h["values"])
    return {
        "age": pred.age,
        "covariates": _covariate_dict(model, pred.covariates),
        "markers": [[float(a), float(v)] for a, v in pred.markers.items()],
        "horizons": h,
        **row,
        "prediction": d,
    }


# ---- The compute request -----------------------------------------------------------


def fit_request(items: list[dict], covariates: list[str], *, path_model: str, hazard_covariates=None,
                path_covariates=None, unit: str = "", marker: str = "", marker_unit: str = "",
                summary: Optional[dict] = None) -> dict:
    """A self-contained fit request: everything :func:`run_fit` needs."""
    if path_model not in PATHS:
        raise FitError(f"Unknown path model {path_model!r}: use one of {', '.join(PATHS)}.")
    if path_model == "quadratic" and len(items) > MAX_UNITS_QUADRATIC:
        raise FitError(f"The quadratic path takes up to {MAX_UNITS_QUADRATIC:,} units (its three varying "
                       f"parameters make each unit's fit slow); this fit has {len(items):,}. Use another path, "
                       "or fewer units.")
    _check_parts(covariates, hazard_covariates, path_covariates)
    return {
        "items": items,
        "covariates": list(covariates),
        "options": {"path_model": path_model, "hazard_covariates": hazard_covariates,
                    "path_covariates": path_covariates, "unit": unit or "", "marker": marker or "",
                    "marker_unit": marker_unit or ""},
        "summary": summary or {},
    }


def run_fit(request: dict) -> dict:
    """Fit a :func:`fit_request` and return ``{"model": JointModel.to_dict(),
    "results": ..., "units": ...}`` (plain JSON)."""
    if not isinstance(request, dict) or not isinstance(request.get("items"), list):
        raise FitError("The request needs the units.")
    items = request["items"]
    covariates = [str(c) for c in request.get("covariates") or []]
    opts = request.get("options") or {}
    path_model = opts.get("path_model") or DEFAULT_PATH
    model, notes = fit_model(items, covariates, path_model, opts.get("hazard_covariates"),
                             opts.get("path_covariates"))
    results = results_payload(model, items, covariates, path_model=path_model, unit=opts.get("unit") or "",
                              marker=opts.get("marker") or "", marker_unit=opts.get("marker_unit") or "",
                              notes=notes, summary=request.get("summary"))
    return {"model": model.to_dict(), "results": results, "units": unit_inputs(items, covariates)}


def restore(model_dict: dict):
    """A saved ``JointModel.to_dict()`` back as the live model."""
    import surpyval

    return surpyval.from_dict(model_dict)


# ---- Download as Python ---------------------------------------------------------------


def _csv(df: pd.DataFrame) -> str:
    buf = io.StringIO()
    df.to_csv(buf, index=False, float_format="%.10g")
    return buf.getvalue()


def python_script(name: str, items: list[dict], covariates: list[str], *, path_model: str,
                  hazard_covariates=None, path_covariates=None, unit: str = "", marker: str = "",
                  horizon: Optional[float] = None, versions: Optional[dict] = None) -> str:
    """A standalone script that refits the model with ``fit_from_df`` from
    the data it was fitted to (embedded), and predicts the riskiest running
    unit."""
    frame = items_frame(items, covariates).drop(columns=["readings"])
    if not (frame["entry_age"] > 0).any():
        frame = frame.drop(columns=["entry_age"])
    readings = pd.DataFrame([{"id": it["id"], "age": a, "value": v}
                             for it in items for a, v in (it.get("markers") or [])],
                            columns=["id", "age", "value"])
    interval = "age_lower" in frame.columns
    cls = PATHS[path_model][0]
    args = ['    markers_col="readings",', '    c_col="censored",  # 0 = failed, 1 = still running']
    args.insert(0, '    xl_col="age_lower", xr_col="age_upper",' if interval else '    x_col="age",')
    if "entry_age" in frame.columns:
        args.append('    tl_col="entry_age",  # the age each unit came under observation')
    if covariates:
        args.append(f"    Z_cols={covariates!r},")
        hazard, path = _check_parts(covariates, hazard_covariates, path_covariates)
        if hazard is not None:
            args.append(f"    hazard_covariates={hazard!r},")
            args.append(f"    path_covariates={path!r},")
    shown_unit = unit_in_text(unit) or "the model's time unit"
    versions = versions or {}
    pins = " ".join(f"{k}=={v}" for k, v in versions.items() if v) or "surpyval"
    title = " ".join(str(name or "Condition and life").split())
    lines = [
        f'"""{title}: condition and life (a joint model of readings and failures).',
        "",
        "Exported from Reliafy. It refits the model with SurPyval from the data it was",
        "fitted to, then predicts the running unit at the highest risk.",
        "",
        f"Install: pip install {pins}",
        f"Ages are since new, in {shown_unit}. Censoring: 0 = failed, 1 = still running,",
        "-1 = failed by that age, 2 = failed between two ages.",
        '"""',
        "",
        "import io",
        "",
        "import numpy as np",
        "import pandas as pd",
        "from surpyval import JointPH, Weibull",
        f"from surpyval.degradation import {cls}",
        "",
        "# One row per unit.",
        f'LIFETIMES = """{_csv(frame)}"""',
        "",
        f"# One row per reading of the {marker or 'marker'}.",
        f'READINGS = """{_csv(readings)}"""',
        "",
        'life = pd.read_csv(io.StringIO(LIFETIMES), dtype={"id": str})',
        'readings = pd.read_csv(io.StringIO(READINGS), dtype={"id": str})',
        "",
        "# Each unit's readings as {age: value}.",
        'by_unit = {uid: dict(zip(g["age"], g["value"])) for uid, g in readings.groupby("id")}',
        'life["readings"] = [by_unit.get(uid, {}) for uid in life["id"]]',
        "",
        f"model = JointPH(Weibull, {cls}).fit_from_df(",
        "    life,",
        *args,
        ")",
        "print(model)",
        "",
        "# Each running unit's dynamic prediction: its survival from its age now,",
        "# given its readings so far.",
        'running = life[life["censored"] == 1]',
        "risk = {}",
        "for _, unit in running.iterrows():",
        f"    Z = {{name: unit[name] for name in {covariates!r}}} or None",
        f'    age = unit["{"age_upper" if interval else "age"}"]',
        '    pred = model.predict(Z, unit["readings"] or None, given=age)',
        "    risk[unit[\"id\"]] = pred",
        "if risk:",
        f"    horizon = {float(horizon if horizon else horizons(unit, None)['values'][1]):.6g}  # in {shown_unit}",
        '    worst = max(risk, key=lambda uid: 1 - float(risk[uid].sf(risk[uid].age + horizon)))',
        "    pred = risk[worst]",
        '    print(f"Highest risk: unit {worst}, age {pred.age:g}")',
        '    print(f"  chance of failing in the next {horizon:g}: {1 - float(pred.sf(pred.age + horizon)):.1%}")',
        "    median = float(pred.remaining_life(0.5))",
        '    print(f"  median remaining life: {median:.4g}" if np.isfinite(median) else "  median remaining life: not reached")',
        "",
    ]
    return "\n".join(lines)
