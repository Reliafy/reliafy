"""Compare groups of life data: is A better than B? (#175)

Split one dataset by a column (supplier, site, design revision) and compare
the groups non-parametrically, with SurPyval:

* a Kaplan-Meier survival curve per group, overlaid;
* the k-sample log-rank test (with the Gehan-Wilcoxon and Tarone-Ware
  weightings alongside) of whether the groups share one survival curve;
* each group's restricted mean survival time (RMST: the average life over the
  first ``tau`` time units) and the difference from a reference group, with
  its confidence interval — the plain-words "how much longer";
* Gray's test, per failure mode, when a failure-mode column gives competing
  risks;
* a one-sentence verdict.

Nothing here is fitted: every figure is a non-parametric estimate or a test.
"""

from __future__ import annotations

import warnings
from typing import Optional

import numpy as np
import pandas as pd

from backend import fitting
from backend.services.strategy import fmt_num
from surpyval import KaplanMeier, gray_test, logrank, rmst_diff

ALPHA = 0.05
MAX_GROUPS = 12
MAX_CAUSES = 8
_CURVE_POINTS = 600  # per group; longer curves are thinned for the plot
_WEIGHTINGS = (
    ("log-rank", "Log-rank"),
    ("gehan", "Gehan–Wilcoxon"),
    ("tarone-ware", "Tarone–Ware"),
)
_UNSPECIFIED = "(no mode given)"


class CompareGroupsError(ValueError):
    """The comparison can't be run with these inputs (a message for the user)."""


# ---------------------------------------------------------------------------
# Inputs
# ---------------------------------------------------------------------------

def _label(value) -> Optional[str]:
    """A group (or failure-mode) label as text: 30.0 reads "30", blanks are
    missing."""
    if value is None or (isinstance(value, float) and not np.isfinite(value)):
        return None
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    if isinstance(value, (bool, np.bool_)):
        return str(bool(value))
    if isinstance(value, (int, float, np.integer, np.floating)):
        return f"{float(value):g}"
    text = str(value).strip()
    return text or None


def _natural_order(labels) -> list[str]:
    """Numbers in numeric order, then text alphabetically."""
    def key(s):
        try:
            return (0, float(s), "")
        except ValueError:
            return (1, 0.0, s.lower())
    return sorted(labels, key=key)


def _columns_check(df: pd.DataFrame, **columns) -> None:
    names = [str(c) for c in df.columns]
    for role, col in columns.items():
        if col and col not in df.columns:
            raise CompareGroupsError(
                f"Column '{col}' ({role.replace('_', ' ')}) isn't in the data. Columns: {', '.join(names)}.")


def prepare(
    df: pd.DataFrame,
    *,
    time_column: str,
    group_column: str,
    censor_column: Optional[str] = None,
    count_column: Optional[str] = None,
    cause_column: Optional[str] = None,
    c_invert: bool = False,
    names: Optional[dict] = None,
) -> dict:
    """Pull times, flags, counts, group labels (and failure modes) out of a
    dataset, dropping rows with no time or no group. Only right-censoring
    (0 = failed, 1 = still running) is accepted: the log-rank test needs it.
    ``names`` says how a column reads in an error message (for inline data,
    the argument that filled it, e.g. ``{"c": "`censored`"}``, #211)."""
    names = names or {}

    def called(col: str, role: str) -> str:
        return names.get(col) or f"{role} column '{col}'"
    if not time_column:
        raise CompareGroupsError("Choose the column that holds the times.")
    if not group_column:
        raise CompareGroupsError("Choose the column to split the data by.")
    _columns_check(df, time_column=time_column, group_column=group_column,
                   censor_column=censor_column, count_column=count_column, cause_column=cause_column)
    if group_column == time_column:
        raise CompareGroupsError("Split by a column other than the time column.")
    if c_invert:
        if not censor_column:
            raise CompareGroupsError("'1 = failed' flips the censor column: choose one too.")
        try:
            df = fitting.invert_censor_column(df, censor_column)
        except fitting.FitError as exc:
            text = str(exc)
            if censor_column in names:
                text = text.replace(f"Censor column '{censor_column}'", names[censor_column])
            raise CompareGroupsError(text) from exc

    x = pd.to_numeric(df[time_column], errors="coerce").to_numpy(dtype=float)
    labels = np.array([_label(v) for v in df[group_column]], dtype=object)
    keep = np.isfinite(x) & np.array([lab is not None for lab in labels])
    dropped = int((~keep).sum())

    if censor_column:
        c = pd.to_numeric(df[censor_column], errors="coerce").to_numpy(dtype=float)
        bad = keep & ~np.isin(c, (0, 1))
        if bad.any():
            shown = ", ".join(pd.unique(df[censor_column][bad].astype(str))[:5])
            raise CompareGroupsError(
                f"{called(censor_column, 'Censor')} must hold 0 (failed) or 1 (still running) on every row; "
                f"found: {shown}. These tests need right-censored data only.")
    else:
        c = np.zeros_like(x)
    if count_column:
        n = pd.to_numeric(df[count_column], errors="coerce").to_numpy(dtype=float)
        bad = keep & ~(np.isfinite(n) & (n > 0))
        if bad.any():
            raise CompareGroupsError(f"{called(count_column, 'Count')} must hold a positive number on every row.")
    else:
        n = np.ones_like(x)
    cause = None
    if cause_column:
        cause = np.array([_label(v) for v in df[cause_column]], dtype=object)

    x, c, n, labels = x[keep], c[keep].astype(int), n[keep], labels[keep]
    if (x < 0).any():
        raise CompareGroupsError("Times must not be negative.")
    out = {"x": x, "c": c, "n": n, "group": labels, "dropped": dropped}
    if cause is not None:
        out["cause"] = cause[keep]
    return out


# ---------------------------------------------------------------------------
# The comparison
# ---------------------------------------------------------------------------

def _p_text(p: float) -> str:
    if p is None or not np.isfinite(p):
        return "p = n/a"
    if p < 0.001:
        return "p < 0.001"
    return f"p = {p:.2g}" if p < 0.01 else f"p = {p:.2f}"


def _curve(km) -> dict:
    """The Kaplan-Meier step curve from (0, 1), thinned for plotting."""
    xs = np.concatenate([[0.0], np.asarray(km.x, dtype=float)])
    R = np.concatenate([[1.0], np.asarray(km.R, dtype=float)])
    if xs.size > _CURVE_POINTS:
        idx = np.unique(np.linspace(0, xs.size - 1, _CURVE_POINTS).round().astype(int))
        xs, R = xs[idx], R[idx]
    return {"x": [float(v) for v in xs], "R": [float(v) for v in R]}


def _median(km) -> Optional[float]:
    R = np.asarray(km.R, dtype=float)
    hit = np.nonzero(R <= 0.5)[0]
    return float(np.asarray(km.x, dtype=float)[hit[0]]) if hit.size else None


def _num(v) -> Optional[float]:
    v = float(v)
    return v if np.isfinite(v) else None


def _bounded(v, tau: float) -> Optional[float]:
    v = _num(v)
    return None if v is None else min(max(v, 0.0), float(tau))


def compare_groups(
    data: dict,
    *,
    groups: Optional[list] = None,
    reference: Optional[str] = None,
    tau: Optional[float] = None,
    unit: Optional[str] = None,
    group_column: Optional[str] = None,
) -> dict:
    """Compare the groups in ``data`` (from :func:`prepare`).

    ``groups`` picks and orders the groups to compare (default: every group,
    numbers in numeric order); ``reference`` is the group the RMST differences
    are measured from (default: the first); ``tau`` is the RMST horizon
    (default: the shortest group's longest observed time, so every curve is
    backed by data up to it). A longer ``tau`` is capped there, with a note
    (#211): past it a curve would be held flat and the average life — and
    the verdict on it — extrapolated."""
    x, c, n, lab = data["x"], data["c"], data["n"], data["group"]
    present = _natural_order(set(lab.tolist()))
    if groups:
        wanted = [g for g in (_label(g) for g in groups) if g is not None]
        missing = [g for g in wanted if g not in present]
        if missing:
            raise CompareGroupsError(
                f"No rows in group(s) {', '.join(repr(g) for g in missing)}. Groups: {', '.join(present)}.")
        order = list(dict.fromkeys(wanted))
    else:
        order = present
    if len(order) < 2:
        what = f" '{group_column}'" if group_column else ""
        raise CompareGroupsError(
            f"The column{what} has only one group ({order[0] if order else 'none'}) — choose a column that "
            "splits the data into two or more groups." if not groups else "Choose at least two groups.")
    if len(order) > MAX_GROUPS:
        raise CompareGroupsError(
            f"That column splits the data into {len(order)} groups; compare at most {MAX_GROUPS} at once. "
            "A column with a different value on almost every row (a continuous measurement) isn't a "
            "grouping — to see its effect on life, fit a proportional-hazards model on it instead.")
    sel = np.isin(lab, order)
    x, c, n, lab = x[sel], c[sel], n[sel], lab[sel]
    if reference is not None:
        reference = _label(reference)
        if reference not in order:
            raise CompareGroupsError(f"The reference group '{reference}' isn't one of: {', '.join(order)}.")
    else:
        reference = order[0]

    kms: dict = {}
    for g in order:
        m = lab == g
        try:
            kms[g] = KaplanMeier.fit(x[m], c=c[m], n=n[m])
        except Exception as exc:  # noqa: BLE001 - surfaced as a user message
            raise CompareGroupsError(f"Group '{g}': {exc}") from exc

    longest = {g: float(np.max(x[lab == g])) for g in order}
    horizon = min(longest.values())
    notes: list[str] = []
    if tau is None:
        tau = horizon
    else:
        tau = float(tau)
        if not np.isfinite(tau) or tau <= 0:
            raise CompareGroupsError("The RMST horizon must be a positive time.")
        if tau > horizon:
            short = min(longest, key=longest.get)
            notes.append(
                f"The horizon {fmt_num(tau)} goes past the last time in group '{short}' "
                f"({fmt_num(horizon)}), so it was capped there: beyond it that group's curve has no data, "
                "and its average life would be extrapolated.")
            tau = horizon
    if tau <= 0:
        raise CompareGroupsError("Every time in one group is 0: there is no window to average life over.")

    # With no unit, say "time units" rather than leave a bare number (#211).
    us = f" {unit.strip()}" if unit and unit.strip() else " time units"
    summaries = []
    for g in order:
        m = lab == g
        failures = int(n[m][c[m] == 0].sum())
        units = int(round(n[m].sum()))
        r = kms[g].rmst(tau=tau, alpha_ci=ALPHA)
        summaries.append({
            "group": g,
            "units": units,
            "failures": failures,
            "censored": units - failures,
            "median": _median(kms[g]),
            "rmst": _num(r["rmst"]),
            # An average life over [0, tau] lies in [0, tau]: the normal
            # interval's bounds are clipped to it (#211).
            "rmst_lower": _bounded(r["lower"], tau),
            "rmst_upper": _bounded(r["upper"], tau),
            "curve": _curve(kms[g]),
        })
        if failures == 0:
            notes.append(f"Group '{g}' has no failures, so its curve stays at 1.")
        elif failures < 5:
            notes.append(f"Group '{g}' has only {failures} failure{'s' if failures > 1 else ''}: "
                         "the tests have little power to find a difference.")

    # The k-sample log-rank test and its weighted variants.
    tests = []
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        for wid, label in _WEIGHTINGS:
            r = logrank(x, lab, c=c, n=n, weighting=wid)
            tests.append({"id": wid, "label": label, "statistic": float(r.statistic), "dof": int(r.dof),
                          "p_value": float(r.p_value)})
    primary = tests[0]

    differences = []
    for g in order:
        if g == reference:
            continue
        d = rmst_diff(kms[g], kms[reference], tau=tau, alpha_ci=ALPHA)
        differences.append({
            "group": g, "reference": reference,
            "difference": _num(d["difference"]), "lower": _num(d["lower"]), "upper": _num(d["upper"]),
            "p_value": None if not np.isfinite(d["p_value"]) else float(d["p_value"]),
        })

    out = {
        "unit": (unit or "").strip(),
        "group_column": group_column,
        "groups": summaries,
        "reference": reference,
        "tau": float(tau),
        "alpha": ALPHA,
        "logrank": primary,
        "tests": tests,
        "rmst_differences": differences,
        "rows_used": int(len(x)),
        "rows_dropped": int(data.get("dropped") or 0),
    }
    if data.get("dropped"):
        notes.append(f"{data['dropped']} row{'s' if data['dropped'] != 1 else ''} with no time or no group "
                     "left out.")
    if "cause" in data:
        out["competing_risks"] = _gray(x, c, n, lab, data["cause"][sel], order)
    # No failure while two groups are both still observed (all of one group
    # censored before the other's first failure, or no failures at all):
    # the log-rank test has no degrees of freedom and nothing to compare.
    out["comparable"] = primary["dof"] > 0
    if not out["comparable"]:
        notes.append("No failure happens while the groups are all still under observation, so the log-rank "
                     "test has nothing to compare (0 degrees of freedom; its p = 1 means nothing).")
    out["verdict"] = _verdict(out, us)
    out["notes"] = notes
    return out


def _gray(x, c, n, lab, cause, order) -> dict:
    """Gray's test per failure mode: does each group's chance of failing BY
    THAT MODE differ, with the other modes competing?"""
    failed = c == 0
    e = np.array([(cause[i] or _UNSPECIFIED) if failed[i] else None for i in range(len(x))], dtype=object)
    modes = pd.Series(n[failed], index=e[failed]).groupby(level=0).sum().sort_values(ascending=False)
    if len(modes) < 2:
        return {"available": False,
                "reason": "Every failure has the same mode, so there are no competing risks: "
                          "the log-rank test above already answers the question."}
    results = []
    for mode in list(modes.index)[:MAX_CAUSES]:
        try:
            r = gray_test(x, e, lab, event=mode, c=c, n=n)
        except Exception as exc:  # noqa: BLE001 - one mode failing shouldn't sink the rest
            results.append({"mode": mode, "failures": int(modes[mode]), "error": str(exc)})
            continue
        p = float(r.p_value)
        results.append({"mode": mode, "failures": int(modes[mode]), "statistic": float(r.statistic),
                        "dof": int(r.df), "p_value": p, "significant": p < ALPHA})
    out = {"available": True, "results": results}
    if len(modes) > MAX_CAUSES:
        out["note"] = f"The {MAX_CAUSES} most common of {len(modes)} failure modes are tested."
    return out


def _named(column: Optional[str]):
    """How a group reads in a sentence: a number or a code of a letter or two
    takes the column's name ('kV 30', 'supplier B'); a word reads alone
    ('Maintained', not 'arm Maintained')."""
    def name(label: str) -> str:
        if not column or label.lower().startswith(str(column).lower()):
            return label
        try:
            float(label)
        except ValueError:
            if len(label) > 2:
                return label
        return f"{column} {label}"
    return name


def _verdict(out: dict, us: str) -> dict:
    """One plain-words sentence, from the log-rank p-value and the RMSTs.
    ``better`` / ``worse`` are group labels, set only when the groups differ."""
    name = _named(out.get("group_column"))
    p = out["logrank"]["p_value"]
    significant = p < ALPHA
    tau_s = f"{fmt_num(out['tau'])}{us}"
    groups = out["groups"]
    if not out.get("comparable", True):
        who = (f"{name(groups[0]['group'])} and {name(groups[1]['group'])}" if len(groups) == 2
               else f"The {len(groups)} groups")
        return {"significant": False, "better": None, "worse": None,
                "text": (f"{who} can't be compared over a common window: no failure happens while "
                         f"{'both' if len(groups) == 2 else 'they all'} still have units under observation. "
                         "Collect data that overlaps in time.")}
    if len(groups) == 2:
        d = out["rmst_differences"][0]
        ref, other = d["reference"], d["group"]
        diff, lo, hi = d["difference"], d["lower"], d["upper"]
        if diff is None or lo is None or hi is None:
            return {"significant": significant, "better": None, "worse": None,
                    "text": f"Log-rank {_p_text(p)}."}
        if diff >= 0:
            best, worst, lo_b, hi_b = other, ref, lo, hi
        else:
            best, worst, lo_b, hi_b = ref, other, -hi, -lo
        gain = abs(diff)
        ci = f"(95% CI {fmt_num(lo_b)} to {fmt_num(hi_b)}{us})"
        # The two halves are judged separately (#211): the curves by the
        # log-rank p, the average life by whether its CI excludes 0.
        clear_gain = lo_b > 0
        if significant:
            # Starts with the group's name as written (a column name keeps its case).
            text = (f"{name(best)} lasts longer: log-rank {_p_text(p)}; on average {fmt_num(gain)}{us} more "
                    f"over the first {tau_s} {ci}.")
            if not clear_gain:
                text += (" The average gain over that window isn't clear-cut, though: the curves may cross. "
                         "Check the plot.")
        elif clear_gain:
            text = (f"Over the first {tau_s}, {name(best)} averages {fmt_num(gain)}{us} more {ci}, a clear "
                    f"difference in average life — but the curves as a whole don't differ clearly (log-rank "
                    f"{_p_text(p)}), which usually means they cross. Check the plot.")
        else:
            text = (f"No clear difference between {name(ref)} and {name(other)}: log-rank {_p_text(p)}. "
                    f"Over the first {tau_s}, {name(best)} averages {fmt_num(gain)}{us} more {ci}, which could "
                    "be chance.")
        return {"significant": significant, "better": best if significant else None,
                "worse": worst if significant else None, "text": text}

    ranked = sorted((g for g in groups if g["rmst"] is not None), key=lambda g: g["rmst"], reverse=True)
    k = len(groups)
    if significant and ranked:
        best, worst = ranked[0], ranked[-1]
        text = (f"The {k} groups differ: log-rank {_p_text(p)}. Over the first {tau_s}, {name(best['group'])} "
                f"lasts longest ({fmt_num(best['rmst'])}{us} on average) and {name(worst['group'])} shortest "
                f"({fmt_num(worst['rmst'])}{us}).")
        return {"significant": True, "better": best["group"], "worse": worst["group"], "text": text}
    return {"significant": False, "better": None, "worse": None,
            "text": f"No clear difference between the {k} groups: log-rank {_p_text(p)}."}


def lean(result: dict, include_curves: bool = False) -> dict:
    """The comparison without its plotting curves (for an agent)."""
    if include_curves:
        return result
    out = {**result, "groups": [{k: v for k, v in g.items() if k != "curve"} for g in result["groups"]]}
    out["curves_omitted"] = "Pass include_curves=true for each group's Kaplan–Meier curve."
    return out
