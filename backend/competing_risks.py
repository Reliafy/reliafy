"""Competing risks: life data by failure mode (#177).

A unit that fails from one mode (bearing wear) can't then fail from another
(a seal leak): the modes compete. Fitting each mode on its own, with the
other modes' failures treated as still running, overstates every mode. The
cumulative incidence of a mode is the chance of failing *from it* by a time,
with the others still acting; the modes' incidences add up to the all-cause
failure probability (one minus the Kaplan-Meier survival).

Everything here is SurPyval's:

* ``CompetingRisks`` (Aalen-Johansen) gives each mode's cumulative incidence,
  ``cb`` its pointwise bounds (Aalen's variance) and, fitted with
  ``how="Kaplan-Meier"``, the all-cause failure probability and its bounds;
* ``gray_test`` compares one mode's incidence across groups of units (sites,
  suppliers) when a group column is given;
* ``CompetingRisksProportionalHazards`` (the advanced choice, with covariates)
  fits a cause-specific Cox model or a Fine-Gray model per mode.

The data: a time per unit, a failure-mode column that is blank for a unit
still running, and optionally the usual status and count columns. This
module only shapes SurPyval's numbers for the app and the agent tools, and
words them; it computes nothing itself.
"""

from __future__ import annotations

import math
import warnings
from typing import Optional

import numpy as np
import pandas as pd
from surpyval import CompetingRisks, CompetingRisksProportionalHazards, gray_test

from backend.services.compare_groups import _label, _named, _p_text
from backend.services.strategy import fmt_num
from backend.units import unit_in_text

# The mapping keys this model reads beyond x / c / n.
CAUSE_KEY = "e"
GROUP_KEY = "g"
EXTRA_KEYS = (CAUSE_KEY, GROUP_KEY)

NONPARAMETRIC_ID = "competing_risks"
CR_MODELS = {
    NONPARAMETRIC_ID: {"name": "Competing risks (by failure mode)", "regression": None},
    "competing_risks_cox": {"name": "Competing risks, cause-specific Cox (by failure mode)", "regression": "Cox"},
    "competing_risks_fine_gray": {"name": "Competing risks, Fine-Gray (by failure mode)", "regression": "Fine-Gray"},
}
RATIO_LABELS = {"Cox": "hazard ratio", "Fine-Gray": "subdistribution hazard ratio"}

ALPHA = 0.05  # 95% bounds on the incidence curves
MAX_CAUSES = 12
MAX_GROUPS = 12
CURVE_POINTS = 400
# A lead that holds for less than this share of the time range is noise.
_LEAD_MIN_SHARE = 0.1


class CompetingRisksError(ValueError):
    """The data can't be fitted by failure mode (a message for the user)."""


def is_competing_risks(distribution: str) -> bool:
    return distribution in CR_MODELS


def plain_mapping(mapping: dict) -> dict:
    """``mapping`` without the failure-mode and group columns, for every
    other model: a single distribution reads x / c / n / … only."""
    return {k: v for k, v in (mapping or {}).items() if k not in EXTRA_KEYS}


def _num(v) -> Optional[float]:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) else None


def _nums(a) -> list:
    return [_num(v) for v in np.asarray(a, dtype=float).ravel()]


def nice_time(t: float) -> float:
    """A round time at or just below ``t`` to read the result at: 5,320 →
    5,000, but 1,450 → 1,400 (5,000 or 1,000 would give away too much)."""
    if not t or t <= 0 or not math.isfinite(t):
        return t
    step = 10 ** math.floor(math.log10(t))
    one = math.floor(t / step) * step
    if one >= 0.75 * t:
        return float(f"{one:.12g}")
    step /= 10
    return float(f"{math.floor(t / step) * step:.12g}")


# ---------------------------------------------------------------------------
# Inputs
# ---------------------------------------------------------------------------

def _rows(n: int) -> str:
    return f"{n:,} row{'s' if n != 1 else ''}"


def prepare(df: pd.DataFrame, mapping: dict) -> dict:
    """Times, causes (None for a unit still running), censoring flags, counts
    and groups from the mapped columns. Raises CompetingRisksError with a
    plain reason."""
    mapping = {k: v for k, v in (mapping or {}).items() if v}
    for key in ("xl", "xr", "tl", "tr"):
        if mapping.get(key):
            raise CompetingRisksError(
                "Failure modes take one time per unit: inspection intervals and truncated data "
                "can't be split by mode. Use a single time column.")
    if not mapping.get("x"):
        raise CompetingRisksError("Pick the column that holds the time to failure or removal.")
    if not mapping.get(CAUSE_KEY):
        raise CompetingRisksError("Pick the column that names each failure's mode.")
    for key, col in mapping.items():
        if col not in df.columns:
            raise CompetingRisksError(f"The data has no column named '{col}'.")

    x = pd.to_numeric(df[mapping["x"]], errors="coerce").to_numpy(dtype=float)
    if not np.isfinite(x).all():
        raise CompetingRisksError(
            f"{_rows(int((~np.isfinite(x)).sum()))} no time in “{mapping['x']}”. Fill them in or delete "
            "those rows.")
    if (x < 0).any():
        raise CompetingRisksError(f"“{mapping['x']}” has negative times; life data starts at 0.")
    cause = [_label(v) for v in df[mapping[CAUSE_KEY]].tolist()]

    if mapping.get("c"):
        c = pd.to_numeric(df[mapping["c"]], errors="coerce").to_numpy(dtype=float)
        if not np.isfinite(c).all():
            raise CompetingRisksError(f"{_rows(int((~np.isfinite(c)).sum()))} no status in “{mapping['c']}”.")
        if not np.isin(c, (0, 1)).all():
            raise CompetingRisksError(
                "Failure modes take units that failed and units still running only: left- or "
                "interval-censored rows can't be split by mode.")
        c = c.astype(int)
        unnamed = int(sum(1 for i in range(len(c)) if c[i] == 0 and cause[i] is None))
        if unnamed:
            raise CompetingRisksError(
                f"{_rows(unnamed)} failed with no failure mode in “{mapping[CAUSE_KEY]}”. Fill in each "
                "failure's mode, or mark those units still running.")
        # A unit still running has no mode, whatever the column says.
        cause = [None if c[i] == 1 else cause[i] for i in range(len(c))]
    else:
        # No status column: a blank mode is a unit still running.
        c = np.array([1 if v is None else 0 for v in cause], dtype=int)

    if mapping.get("n"):
        n = pd.to_numeric(df[mapping["n"]], errors="coerce").to_numpy(dtype=float)
        if not np.isfinite(n).all() or (n <= 0).any():
            raise CompetingRisksError(f"Every count in “{mapping['n']}” must be a number above 0.")
    else:
        n = np.ones(len(x))

    failed = c == 0
    if not failed.any():
        raise CompetingRisksError(
            "No unit is marked failed, so there is nothing to fit. Check the failure-mode column: "
            "a blank mode means still running.")
    e = np.array(cause, dtype=object)
    counts = pd.Series(n[failed], index=e[failed]).groupby(level=0).sum()
    causes = sorted(counts.index, key=lambda k: (-counts[k], k))
    if len(causes) > MAX_CAUSES:
        raise CompetingRisksError(
            f"“{mapping[CAUSE_KEY]}” has {len(causes)} different failure modes; at most {MAX_CAUSES} can "
            "compete. Group the rare ones (as “other”), or pick the failure-mode column.")

    group = None
    if mapping.get(GROUP_KEY):
        group = [_label(v) for v in df[mapping[GROUP_KEY]].tolist()]
        blank = sum(1 for g in group if g is None)
        if blank:
            raise CompetingRisksError(
                f"{_rows(blank)} no value in “{mapping[GROUP_KEY]}”, the column to compare groups by.")
        group = np.array(group, dtype=object)
    return {"x": x, "e": e, "c": c, "n": n, "causes": causes, "group": group,
            "failures": {k: float(counts[k]) for k in causes}}


# ---------------------------------------------------------------------------
# The fit
# ---------------------------------------------------------------------------

def _grid(x: np.ndarray) -> np.ndarray:
    xs = np.unique(np.concatenate([[0.0], x[np.isfinite(x)]]))
    if xs.size > CURVE_POINTS:
        idx = np.unique(np.linspace(0, xs.size - 1, CURVE_POINTS).round().astype(int))
        xs = xs[idx]
    return xs


def _incidence(model, cause, t) -> np.ndarray:
    with np.errstate(all="ignore"):
        return np.asarray(model.cif(t, cause), dtype=float).ravel()


def _cif_bounds(model, cause, t) -> np.ndarray:
    with np.errstate(all="ignore"), warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        return np.asarray(model.cb(t, cause, on="cif", alpha_ci=ALPHA), dtype=float).reshape(-1, 2)


def _leads(grid: np.ndarray, cifs: dict) -> list[dict]:
    """Which mode has caused the most failures, and when that changes:
    ``[{"cause", "from"}]``. A lead held for under a tenth of the time
    range is folded into its neighbour."""
    names = list(cifs)
    stack = np.vstack([cifs[k] for k in names])
    on = stack.max(axis=0) > 0
    if not on.any():
        return []
    t = grid[on]
    lead = stack[:, on].argmax(axis=0)
    runs = []
    for i, k in enumerate(lead):
        if runs and runs[-1]["i"] == k:
            continue
        runs.append({"i": int(k), "from": float(t[i])})
    span = float(t[-1] - t[0]) or 1.0
    ends = [r["from"] for r in runs[1:]] + [float(t[-1])]
    held = [end - r["from"] for r, end in zip(runs, ends)]
    long = [r for r, h in zip(runs, held) if h >= _LEAD_MIN_SHARE * span] or [runs[int(np.argmax(held))]]
    kept = []
    for r in long:
        if not kept or kept[-1]["i"] != r["i"]:
            kept.append(r)
    return [{"cause": names[r["i"]], "from": r["from"]} for r in kept]


def _pct(p: Optional[float]) -> str:
    """A probability as a percentage, as the app writes one: whole numbers
    from 10%, two significant figures below."""
    if p is None:
        return "—"
    v = 100 * p
    if v == 0:
        return "0%"
    return f"{round(v):,}%" if abs(v) >= 10 else f"{float(f'{v:.2g}'):g}%"


def _reading(causes: list[dict], horizon: float, leads: list[dict], us: str) -> str:
    """The answer in words: which mode causes most failures by the horizon,
    and when the lead changes."""
    if not causes:
        return ""
    top = max(causes, key=lambda k: k["at"]["cif"] or 0)
    at = top["at"]
    when = f"{fmt_num(horizon)}{us}"
    if len(causes) == 1:
        text = (f"Every failure is {top['name']}: {_pct(at['cif'])} of units have failed from it by {when}. "
                "With one mode there are no competing risks.")
        return text
    text = (f"{top['name'][:1].upper()}{top['name'][1:]} causes {_pct(top['share'])} of failures by {when}: "
            f"{_pct(at['cif'])} of units fail from it by then")
    if at.get("lower") is not None and at.get("upper") is not None:
        text += f" (we're 95% sure it's between {_pct(at['lower'])} and {_pct(at['upper'])})"
    text += "."
    if len(leads) > 1:
        first, then = leads[0], leads[1]
        text += (f" {first['cause'][:1].upper()}{first['cause'][1:]} leads early; {then['cause']} overtakes it "
                 f"at about {fmt_num(then['from'])}{us}.")
    return text


def _gray(prep: dict, horizon: float, group_column: str, us: str) -> dict:
    """Gray's test per failure mode across the groups, with each group's
    incidence of that mode at the horizon, and a sentence."""
    x, e, c, n, group = prep["x"], prep["e"], prep["c"], prep["n"], prep["group"]
    labels = sorted(set(group.tolist()), key=lambda s: (len(s), s))
    if len(labels) < 2:
        return {"available": False, "group_column": group_column,
                "reason": f"“{group_column}” has one value only, so there are no groups to compare."}
    if len(labels) > MAX_GROUPS:
        return {"available": False, "group_column": group_column,
                "reason": f"“{group_column}” has {len(labels)} values; at most {MAX_GROUPS} groups can be "
                          "compared. Pick a column with a few repeated values."}
    if len(prep["causes"]) < 2:
        return {"available": False, "group_column": group_column,
                "reason": "Every failure has the same mode, so there are no competing risks to compare."}
    per_group = {}
    for g in labels:
        sel = group == g
        try:
            per_group[g] = CompetingRisks.fit(x[sel], e[sel], c[sel], n[sel], how="Kaplan-Meier")
        except Exception:  # noqa: BLE001 - a group with no failures has no curve
            per_group[g] = None
    results = []
    for cause in prep["causes"]:
        by_group = []
        for g in labels:
            m = per_group[g]
            v = None
            if m is not None:
                try:
                    v = _num(_incidence(m, cause, [horizon])[0])
                except ValueError:  # the mode never happened in this group
                    v = 0.0
            elif not ((group == g) & (c == 0)).any():
                v = 0.0
            by_group.append({"group": g, "cif": v})
        row = {"cause": cause, "by_group": by_group}
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", RuntimeWarning)
                r = gray_test(x, e, group, event=cause, c=c, n=n)
            p = _num(r.p_value)
            row.update({"statistic": _num(r.statistic), "df": int(r.df), "p_value": p,
                        "significant": p is not None and p < ALPHA})
        except Exception as exc:  # noqa: BLE001 - one mode failing shouldn't sink the rest
            row.update({"error": str(exc) or type(exc).__name__, "significant": False})
        results.append(row)
    name = _named(group_column)
    hits = sorted((r for r in results if r.get("significant")), key=lambda r: r["p_value"])
    when = f"{fmt_num(horizon)}{us}"
    if hits:
        r = hits[0]
        known = [b for b in r["by_group"] if b["cif"] is not None]
        hi = max(known, key=lambda b: b["cif"]) if known else None
        lo = min(known, key=lambda b: b["cif"]) if known else None
        text = (f"{r['cause'][:1].upper()}{r['cause'][1:]} differs by {group_column} "
                f"(Gray's test, {_p_text(r['p_value'])})")
        if hi and lo and hi is not lo:
            text += (f": by {when}, {_pct(hi['cif'])} of {name(hi['group'])}'s units fail from it, against "
                     f"{_pct(lo['cif'])} of {name(lo['group'])}'s")
        text += "."
        if len(hits) > 1:
            others = ", ".join(h["cause"] for h in hits[1:])
            text += f" So {'does' if len(hits) == 2 else 'do'} {others}."
    else:
        text = f"No failure mode differs clearly by {group_column} (Gray's test, every p ≥ 0.05)."
    return {"available": True, "group_column": group_column, "groups": labels, "results": results,
            "horizon": horizon, "sentence": text}


def _regression(kind: str, prep: dict, df: pd.DataFrame, covariates: list) -> dict:
    """Cause-specific Cox or Fine-Gray coefficients per failure mode, with
    their ratios, 95% intervals and p-values, from SurPyval's summary."""
    if not covariates:
        raise CompetingRisksError(
            "A regression by failure mode needs covariates: tick them under Advanced on the Data step.")
    frame = pd.DataFrame({"x": prep["x"], "e": prep["e"], "c": prep["c"], "n": prep["n"]})
    for col in covariates:
        if col not in df.columns:
            raise CompetingRisksError(f"The data has no column named '{col}'.")
        values = pd.to_numeric(df[col], errors="coerce")
        if values.isna().all():
            raise CompetingRisksError(
                f"“{col}” holds text; a regression by failure mode takes numeric covariates only.")
        frame[col] = values.to_numpy(dtype=float)
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        try:
            model = CompetingRisksProportionalHazards.fit_from_df(
                frame, x_col="x", e_col="e", Z_cols=list(covariates), c_col="c", n_col="n", model=kind)
            table = model.summary()
        except Exception as exc:  # noqa: BLE001 - SurPyval's reason, as the fit's error
            raise CompetingRisksError(str(exc) or type(exc).__name__) from exc
    from backend.fitting import reissue_deprecations  # local: fitting imports this module

    reissue_deprecations(caught)
    causes_sorted = sorted(getattr(model, "event_idx_map", {}), key=lambda k: model.event_idx_map[k])
    k = len(covariates)
    rows = table.to_dict("records")
    coefficients = []
    for i, row in enumerate(rows):
        cause = causes_sorted[i // k] if causes_sorted else None
        coefficients.append({
            "cause": cause, "covariate": covariates[i % k],
            "coef": _num(row.get("coef")), "se": _num(row.get("se(coef)")),
            "ratio": _num(row.get("exp(coef)")),
            "ratio_ci": [_num(row.get("exp(coef) lower 95%")), _num(row.get("exp(coef) upper 95%"))],
            "p_value": _num(row.get("p")),
        })
    out = {"model": kind, "ratio_label": RATIO_LABELS[kind], "covariates": list(covariates),
           "coefficients": coefficients, "maximum": getattr(model, "maximum", None)}
    if kind == "Cox":
        try:
            out["aic"] = _num(model.aic())
        except Exception:  # noqa: BLE001 - the coefficients stand without it
            pass
    notes = sorted({str(w.message).strip() for w in caught
                    if not issubclass(w.category, (DeprecationWarning, FutureWarning))})
    if notes:
        out["warnings"] = notes[:3]
    return out


def fit(distribution: str, df: pd.DataFrame, mapping: dict, covariates: Optional[list] = None,
        unit: Optional[str] = None) -> dict:
    """Fit life data by failure mode and build the payload: each mode's
    cumulative incidence with 95% bounds, the all-cause failure probability,
    each mode at a round horizon near the last failure, which mode leads
    when, Gray's test across groups (a ``g`` column), a sentence, and — for
    the regression ids — the coefficients per mode."""
    entry = CR_MODELS[distribution]
    prep = prepare(df, mapping)
    x, e, c, n = prep["x"], prep["e"], prep["c"], prep["n"]
    us = f" {unit_in_text(unit)}" if unit else ""
    try:
        with np.errstate(all="ignore"):
            model = CompetingRisks.fit(x, e, c, n, how="Kaplan-Meier")
    except Exception as exc:  # noqa: BLE001 - SurPyval's reason, as the fit's error
        raise CompetingRisksError(str(exc) or type(exc).__name__) from exc

    grid = _grid(x)
    causes = prep["causes"]
    cifs = {k: _incidence(model, k, grid) for k in causes}
    bounds = {k: _cif_bounds(model, k, grid) for k in causes}
    with np.errstate(all="ignore"), warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        everything = np.asarray(model.ff(grid), dtype=float).ravel()
        all_cb = np.asarray(model.cb(grid, on="ff", alpha_ci=ALPHA), dtype=float).reshape(-1, 2)

    last_failure = float(x[c == 0].max())
    horizon = nice_time(last_failure)
    total = float(np.ravel(model.ff([horizon]))[0])
    rows = []
    for k in causes:
        v = float(_incidence(model, k, [horizon])[0])
        lo, hi = _cif_bounds(model, k, [horizon])[0]
        rows.append({
            "name": k, "failures": prep["failures"][k],
            "share": _num(v / total) if total > 0 else None,
            "at": {"cif": _num(v), "lower": _num(lo), "upper": _num(hi)},
        })
    leads = _leads(grid, cifs)
    total_n = float(n.sum())
    result = {
        "distribution": entry["name"],
        "distribution_id": distribution,
        "kind": "competing_risks",
        "params": [],
        "gof": [],
        "n": int(round(total_n)),
        "failed": float(n[c == 0].sum()),
        "running": float(n[c == 1].sum()),
        "causes": rows,
        "horizon": horizon,
        "last_failure": last_failure,
        "leads": leads,
        "curves": {
            "x": _nums(grid),
            "cif": {k: _nums(cifs[k]) for k in causes},
            "lower": {k: _nums(bounds[k][:, 0]) for k in causes},
            "upper": {k: _nums(bounds[k][:, 1]) for k in causes},
            "all": _nums(everything),
            "all_lower": _nums(all_cb[:, 0]),
            "all_upper": _nums(all_cb[:, 1]),
        },
        "reading": _reading(rows, horizon, leads, us),
        "cause_column": mapping.get(CAUSE_KEY),
    }
    if prep["group"] is not None:
        result["gray"] = _gray(prep, horizon, mapping[GROUP_KEY], us)
    if entry["regression"]:
        result["regression"] = _regression(entry["regression"], prep, df, list(covariates or []))
    return result
