"""Repairable fits, system by system: which systems a fit covers, where each
system's record ends, and each system's downtime and cost.

* :func:`only_systems` keeps the rows of the chosen systems (``spec["systems"]``),
  so one system (or a chosen set) is fitted alone, by the same SurPyval fitters
  as the whole fleet. The result says which systems it covers, of how many.
* :func:`record_ends` groups the systems by where their record ends, as the
  fitter reads it (each system's end of record, or its own ``c = 1`` row), so
  a result can say "6 systems to 1,096 days; CV-03 to 995 days" rather than
  only the latest end.
* :func:`system_costs` totals each system's downtime and cost from columns of
  the data (one value per failure row; ``mapping["downtime"]`` and
  ``mapping["cost"]``). Nothing is read from free text: a value that isn't a
  number is refused, and a blank one is counted as missing and said.
"""

from __future__ import annotations

import json
import re

import numpy as np
import pandas as pd

from backend.fitting import FitError

_LISTED = 8  # system ids named in a refusal before "and N more"


def _natural(s: str):
    return [int(p) if p.isdigit() else p.lower() for p in re.split(r"(\d+)", str(s))]


def parse_systems(value) -> list[str]:
    """The chosen systems as a list of ids, in the order given, without blanks
    or repeats. Takes a list (a form's repeated field, a saved spec) or text: a
    JSON list, or one id a line. Empty means every system."""
    if value is None:
        return []
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return []
        if text.startswith("["):
            try:
                value = json.loads(text)
            except ValueError:
                raise FitError("Systems must be a list of system ids, e.g. [\"P-01\", \"P-02\"], or one id "
                               "a line.") from None
        else:
            value = text.splitlines()
    out: list[str] = []
    for item in value if isinstance(value, (list, tuple)) else [value]:
        sid = str(item).strip()
        if sid and sid not in out:
            out.append(sid)
    return out


def only_systems(df: pd.DataFrame, mapping: dict, systems) -> tuple[pd.DataFrame, dict | None]:
    """``(df, chosen)``: the rows of the chosen systems, and ``{systems, of}``
    (the ids fitted, of how many systems in the data); ``(df, None)`` when every
    system is fitted. A chosen id that isn't in the data is refused, naming the
    systems there are."""
    ids = parse_systems(systems)
    col = mapping.get("i")
    if not ids or not col or col not in df.columns:
        return df, None  # build_inputs says what's missing
    have = df[col].where(df[col].notna()).dropna().astype(str)
    every = sorted(set(have), key=_natural)
    unknown = [s for s in ids if s not in set(every)]
    if unknown:
        shown = ", ".join(every[:_LISTED]) + (f" and {len(every) - _LISTED} more" if len(every) > _LISTED else "")
        raise FitError(f"{unknown[0]} isn't a system in this data. Pick from its systems: {shown}.")
    keep = df[col].astype(str).isin(ids) & df[col].notna()
    chosen = {"systems": sorted(ids, key=_natural), "of": len(every)}
    return df[keep].copy(), chosen


def record_ends(inputs: dict) -> list[dict] | None:
    """Where each system's record ends, as the fitter reads it, grouped by the
    end: ``[{end, systems: [ids]}]``, most systems first. ``None`` without a
    system or a time."""
    x = inputs.get("x")
    i = inputs.get("i")
    if x is None or i is None or not np.size(x):
        return None
    tr = inputs.get("tr")
    end = np.maximum(x, tr) if tr is not None and np.size(tr) else np.asarray(x, dtype=float)
    per = pd.Series(end, dtype=float).groupby(pd.Series(i).astype(str).to_numpy()).max()
    groups: dict[float, list[str]] = {}
    for sid, e in per.items():
        groups.setdefault(float(e), []).append(str(sid))
    out = [{"end": e, "systems": sorted(ids, key=_natural)} for e, ids in groups.items()]
    return sorted(out, key=lambda g: (-len(g["systems"]), -g["end"]))


def _amounts(df: pd.DataFrame, col: str, what: str, rows: pd.Series) -> pd.Series:
    """A column's values on the failure rows as numbers: blank stays missing;
    text or a negative number is refused (never read out of words)."""
    if col not in df.columns:
        raise FitError(f"Column '{col}' is not in the dataset.")
    raw = df.loc[rows, col]
    blank = raw.isna() | raw.astype(str).str.strip().eq("")
    vals = pd.to_numeric(raw.where(~blank), errors="coerce")
    bad = vals.isna() & ~blank
    if bad.any():
        first = raw[bad].iloc[0]
        raise FitError(f"The {what} column '{col}' must hold numbers (one per failure); it has “{first}”. "
                       "Put each failure's number in it, or leave it blank where it isn't known.")
    if (vals < 0).any():
        raise FitError(f"The {what} column '{col}' has a negative number: each failure's {what} is 0 or more.")
    return vals


def system_costs(df: pd.DataFrame, mapping: dict, chosen: dict | None = None) -> dict | None:
    """Each system's failures, total downtime and total cost (with the cost
    per failure) from the mapped downtime (``mapping["downtime"]``, hours
    stopped per failure) and cost (``mapping["cost"]``, per failure) columns:
    ``{columns, systems: [...], total, missing}``, most cost (else most
    downtime) first. ``None`` when neither column is mapped. Only failure rows
    count (an end-of-record row, ``c = 1``, has no failure)."""
    cols = {k: mapping.get(k) for k in ("downtime", "cost") if mapping.get(k)}
    if not cols or not mapping.get("i") or not mapping.get("x"):
        return None
    x = pd.to_numeric(df[mapping["x"]], errors="coerce")
    rows = x.notna() & df[mapping["i"]].notna()
    if mapping.get("c") and mapping["c"] in df.columns:
        rows &= ~pd.to_numeric(df[mapping["c"]], errors="coerce").eq(1)
    n = pd.Series(1, index=df.index)
    if mapping.get("n") and mapping["n"] in df.columns:
        n = pd.to_numeric(df[mapping["n"]], errors="coerce").fillna(1).clip(lower=1)
    ids = df.loc[rows, mapping["i"]].astype(str)
    frame = pd.DataFrame({"system": ids, "failures": n[rows]})
    missing = {}
    for key, col in cols.items():
        vals = _amounts(df, col, "downtime" if key == "downtime" else "cost", rows)
        frame[key] = vals
        frame[f"{key}_missing"] = vals.isna().astype(int)
        missing[key] = int(vals.isna().sum())
    out_rows = []
    for sid, g in frame.groupby("system", sort=False):
        row = {"system": str(sid), "failures": int(g["failures"].sum())}
        for key in cols:
            row[key] = float(g[key].sum(skipna=True))
            row[f"{key}_missing"] = int(g[f"{key}_missing"].sum())
            if key == "cost" and row["failures"]:
                row["cost_per_failure"] = row["cost"] / row["failures"]
        out_rows.append(row)
    order = "cost" if "cost" in cols else "downtime"
    out_rows.sort(key=lambda r: (-r[order], -r["failures"], _natural(r["system"])))
    total = {"failures": int(frame["failures"].sum())}
    for key in cols:
        total[key] = float(frame[key].sum(skipna=True))
    if "cost" in cols and total["failures"]:
        total["cost_per_failure"] = total["cost"] / total["failures"]
    for row in out_rows:  # each system's share of the whole
        if "cost" in cols and total.get("cost"):
            row["cost_share"] = row["cost"] / total["cost"]
        if "downtime" in cols and total.get("downtime"):
            row["downtime_share"] = row["downtime"] / total["downtime"]
    return {"columns": cols, "systems": out_rows, "total": total, "missing": missing,
            **({"of_systems": chosen["of"]} if chosen else {})}
