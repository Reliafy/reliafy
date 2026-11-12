"""A column that says each row's time unit ("hrs" on most rows, "days" on a
few logged by someone else).

Left unread, the rows in days go in as hours and the fit is quietly wrong (a
wear-out part reads as early-life failures). :func:`detect` finds such a
column; :func:`convert` brings every time column (x, xl, xr, tl, tr) to one
unit before the fit, row by row; :func:`ignored_warning` is the plain-words
warning for a fit that left a mixed column unread.

The column is a fit option (``u_col``), like ``c_invert``, so a saved model's
spec refits the data the same way.
"""

from __future__ import annotations

from typing import Optional

import pandas as pd

from backend.units import canonical_unit, normalize_unit, unit_in_text

UNIT_COLUMN_KEY = "u_col"

TIME_FIELDS = ("x", "xl", "xr", "tl", "tr")

_MINUTE_DAYS = 1 / 1440


def days_in(unit) -> Optional[float]:
    """Days in one of a calendar time unit (minutes to years); None otherwise."""
    from backend.services.rcm_intervals import DAYS_IN  # local: services import fitting

    key = normalize_unit(unit)
    if key == "minute":
        return _MINUTE_DAYS
    return DAYS_IN.get(key)


def _unit_counts(series: pd.Series) -> Optional[dict]:
    """``{"Hours": 22, "Days": 4}`` when every non-blank value is a time unit,
    else None."""
    values = series.dropna().astype(str).str.strip()
    values = values[values != ""]
    if values.empty:
        return None
    counts: dict = {}
    for v, n in values.value_counts().items():
        if days_in(v) is None:
            return None
        name = canonical_unit(v)
        counts[name] = counts.get(name, 0) + int(n)
    return counts


def detect(df: pd.DataFrame, mapping: dict) -> Optional[dict]:
    """The first column not in the mapping whose values are all time units,
    with more than one of them: ``{"column", "counts"}``; None without one."""
    used = {v for v in (mapping or {}).values() if isinstance(v, str) and v}
    for col in df.columns:
        if col in used or pd.api.types.is_numeric_dtype(df[col]):
            continue
        counts = _unit_counts(df[col])
        if counts and len(counts) > 1:
            return {"column": str(col), "counts": counts}
    return None


def _counts_words(counts: dict) -> str:
    parts = [f"{n} in {unit_in_text(u)}" for u, n in sorted(counts.items(), key=lambda t: -t[1])]
    return ", ".join(parts[:-1]) + (" and " if len(parts) > 1 else "") + parts[-1]


def convert(df: pd.DataFrame, mapping: dict, column: str, unit) -> tuple[pd.DataFrame, dict]:
    """A copy of ``df`` with every mapped time column in ``unit``, each row
    converted from the unit ``column`` gives it; and what was done:
    ``{"column", "to", "converted", "counts", "note"}``. Refuses (ValueError,
    in plain words) a target that isn't calendar time, a row with no unit or
    a unit it can't read."""
    if column not in df.columns:
        raise ValueError(f"Unit column '{column}' isn't in the data.")
    target = days_in(unit)
    if target is None:
        raise ValueError(f"“{column}” gives each row's unit, so the fit needs a unit to convert them to: "
                         "pick Minutes, Hours, Days, Weeks, Months or Years.")
    fields = [mapping[f] for f in TIME_FIELDS if (mapping or {}).get(f) and mapping[f] in df.columns]
    timed = df[fields].notna().any(axis=1) if fields else pd.Series(False, index=df.index)
    raw = df[column].astype(object).where(df[column].notna(), "").astype(str).str.strip()
    missing = int(((raw == "") & timed).sum())
    if missing:
        raise ValueError(f"{missing} {'row has' if missing == 1 else 'rows have'} a time but no unit in "
                         f"“{column}”. Fill them in, or stop using “{column}” as each row's unit.")
    bad = sorted({v for v in raw[timed] if days_in(v) is None})
    if bad:
        shown = ", ".join(f"“{v}”" for v in bad[:3])
        raise ValueError(f"“{column}” holds {shown}, which isn't a time unit Reliafy can convert "
                         "(minutes, hours, days, weeks, months or years).")
    factor = raw.map(lambda v: (days_in(v) / target) if v else 1.0).astype(float)
    out = df.copy()
    for f in fields:
        out[f] = pd.to_numeric(out[f], errors="coerce") * factor
    to = canonical_unit(unit)
    counts = _unit_counts(raw[timed]) or {}
    converted = int(sum(n for u, n in counts.items() if u != to))
    note = (f"“{column}” gives each row's unit ({_counts_words(counts)}): "
            f"{converted} {'row was' if converted == 1 else 'rows were'} converted to {unit_in_text(to)} "
            "before the fit.") if converted else ""
    return out, {"column": column, "to": to, "converted": converted, "counts": counts, "note": note}


def ignored_warning(df: pd.DataFrame, mapping: dict, unit) -> Optional[str]:
    """Plain words for a fit that left a mixed unit column unread; None when
    there is none."""
    found = detect(df, mapping)
    if not found:
        return None
    shown = unit_in_text(canonical_unit(unit)) or "one unit"
    return (f"“{found['column']}” says the rows are in different units ({_counts_words(found['counts'])}), "
            f"but every time was read as {shown}. Refit with “{found['column']}” as each row's unit, "
            "so they are converted first.")
