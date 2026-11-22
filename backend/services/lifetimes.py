"""A dataset's lifetimes: one line per unit (or per system), read the way a
fit reads it, for the dataset page's Lifetimes view.

The rows are read with the dataset's reading (or a draft of one, while the
user changes it): the status column with its meanings (``c_map`` /
``c_invert``), ranges, truncation, counts and the item column, as a fit
from the dataset does. They become SurPyval's own ``SurpyvalData``, and the
lines are read off that object the way ``SurpyvalData.plot_lifetimes``
draws them, so the view shows exactly what a fit will see:

- a line from where the unit came under observation (its left truncation,
  "entered late", or 0) to its last time;
- ``failed`` at an exact failure time, ``running`` where it was last seen
  working (right censored), ``before`` where it was found already failed
  (left censored: the failure lies before), ``window`` the inspection
  interval a failure lies in, and ``bound`` a finite right truncation (for
  repairable data, where the record ends);
- a row standing for ``n`` units is one line with its count;
- where the data has item ids, the rows of one item share a line, each
  event marked (a repairable system's failures, an item's periods).

The view only displays the one dataset: datasets are atomic.
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from backend.fitting import FitError

#: The most lines sent to the browser; past it an even sample of the lines
#: (in time order) is sent and the payload says so. The counts are always of
#: every unit.
MAX_LINES = 5000
#: A covariate with at most this many values can sort and colour the lines.
MAX_GROUP_LEVELS = 12
ROW_COLUMN = "__lifetimes_row__"
STATUS_COLUMN = "__lifetimes_status__"

_KIND = {0: "failed", 1: "running", -1: "before", 2: "window"}


class LifetimesError(ValueError):
    """Why the rows can't be drawn, in words for the user (what a fit would say)."""


def _finite(v) -> float | None:
    v = float(v)
    return v if np.isfinite(v) else None


def lines_of(data, rows: list | None = None) -> dict:
    """The lines of a ``SurpyvalData``, as ``SurpyvalData.plot_lifetimes``
    draws them: ``{"lines": [...], "floor", "ceiling"}``. Each line is
    ``{"id", "start", "end", "entered", "n", "marks", "rows"}``: ``entered``
    the late entry (left truncation) where there is one; ``marks`` one per
    row, ``{"kind", "at"}`` (``"from"`` too for a window) plus a ``bound``
    mark for a finite right truncation; ``rows`` the data rows (1-based)
    where they are known (``rows``: the row of each of the data's rows)."""
    x = np.asarray(data.x, dtype=float)
    c = np.asarray(data.c).astype(int)
    n = np.asarray(data.n).astype(int)
    t = np.asarray(data.t, dtype=float)
    k = len(c)
    lo, hi = (x[:, 0], x[:, 1]) if x.ndim == 2 else (x, x)
    finite = np.concatenate([lo[np.isfinite(lo)], hi[np.isfinite(hi)]])
    floor = min(0.0, float(finite.min())) if len(finite) else 0.0
    ceiling = float(finite.max()) if len(finite) else 1.0
    hi = np.where(np.isfinite(hi), hi, ceiling)
    lo = np.where(np.isfinite(lo), lo, floor)
    start = np.where(np.isfinite(t[:, 0]), t[:, 0], floor)
    tr = t[:, 1]
    ids = data.ids
    if ids is None:
        groups = [[r] for r in range(k)]
    else:
        order: dict = {}
        for r, key in enumerate(ids):
            order.setdefault(key, []).append(r)
        groups = list(order.values())
    out = []
    for rows_of in groups:
        first = rows_of[0]
        s = float(start[rows_of].min())
        marks = []
        for r in rows_of:
            kind = _KIND[int(c[r])]
            mark: dict[str, Any] = {"kind": kind, "at": float(hi[r])}
            if kind == "window":
                mark["from"] = float(lo[r])
            if n[r] > 1:
                mark["n"] = int(n[r])
            marks.append(mark)
            if np.isfinite(tr[r]) and not any(m["kind"] == "bound" and m["at"] == float(tr[r]) for m in marks):
                marks.append({"kind": "bound", "at": float(tr[r])})
        line = {
            "id": str(ids[first]) if ids is not None else None,
            "start": s,
            "end": float(max(hi[rows_of].max(), s)),
            # Late entry: the first row came under observation after the window opened.
            "entered": _finite(t[first, 0]) if np.isfinite(t[first, 0]) and t[first, 0] > floor else None,
            "n": int(n[rows_of].max()) if ids is None else 1,
            "marks": marks,
        }
        if rows is not None:
            line["rows"] = [int(rows[r]) for r in rows_of]
        out.append(line)
    return {"lines": out, "floor": floor, "ceiling": ceiling}


def _status(df: pd.DataFrame, reading: dict) -> pd.DataFrame:
    from backend import fitting

    c = reading.get("c")
    if not c:
        return df
    if reading.get("c_map"):
        return fitting.map_censor_column(df, c, reading["c_map"])
    if reading.get("c_invert"):
        return fitting.invert_censor_column(df, c)
    if c in df.columns and not pd.api.types.is_numeric_dtype(df[c]):
        # Words with no meanings saved ("Failed", "Running"): what each says, as the dataset's count reads them.
        from backend.services.datasets import status_code

        codes = df[c].map(lambda v: None if pd.isna(v) else status_code(str(v).strip(), c))
        return df.assign(**{c: pd.to_numeric(codes, errors="coerce")})
    return df


def _units(df: pd.DataFrame, reading: dict) -> tuple[pd.DataFrame, str | None]:
    """Every time in the reading's unit, where a column gives each row's unit."""
    from backend import unit_column

    col = reading.get("u")
    if not col:
        return df, None
    mapping = {k: reading[k] for k in ("x", "xl", "xr", "tl", "tr") if reading.get(k)}
    try:
        df, done = unit_column.convert(df, mapping, col, reading.get("unit"))
    except ValueError as exc:
        raise LifetimesError(str(exc)) from exc
    return df, done.get("note")


def _numbers(df: pd.DataFrame, col: str | None) -> np.ndarray | None:
    if not col:
        return None
    return pd.to_numeric(df[col], errors="coerce").to_numpy(dtype=float)


def _surpyval(**kwargs):
    from surpyval import SurpyvalData

    try:
        return SurpyvalData(**{k: v for k, v in kwargs.items() if v is not None})
    except (ValueError, TypeError) as exc:
        raise LifetimesError(str(exc)) from exc


def life_data(df: pd.DataFrame, reading: dict):
    """``(SurpyvalData, rows, left_out)`` for life data with no item
    column: each row as a fit reads it (``fitting.build_fit_inputs``), in
    the data's order (no grouping). ``rows``: each kept row's number, from 1;
    ``left_out``: rows with no time, which a fit refuses."""
    from backend import fitting

    mapping = {k: reading.get(k) for k in ("x", "xl", "xr", "c", "n", "tl", "tr") if reading.get(k)}
    df = df.assign(**{ROW_COLUMN: np.arange(1, len(df) + 1)})
    try:
        kw = fitting.build_fit_inputs(df, mapping)
    except FitError as exc:
        raise LifetimesError(str(exc)) from exc
    # combine_exact_and_ranges may drop rows (x and a range both filled): its frame keeps the row numbers.
    kept_df, _ = fitting.combine_exact_and_ranges(df, mapping)
    rows = kept_df[ROW_COLUMN].to_numpy()
    first = kw.get("x") if kw.get("x") is not None else kw.get("xl")
    size = len(first)
    keep = np.isfinite(first)
    if kw.get("xr") is not None:
        keep &= np.isfinite(kw["xr"]) | np.isfinite(first)
    for key in ("c", "n"):
        if kw.get(key) is not None:
            keep &= np.isfinite(kw[key])
    left_out = int(size - keep.sum())
    if not keep.any():
        raise LifetimesError("No row has a number in the time column, so there is nothing to draw.")
    kw = {k: (v[keep] if isinstance(v, np.ndarray) and len(v) == size else v) for k, v in kw.items()}
    if kw.get("c") is not None:
        kw["c"] = kw["c"].astype(int)
    if kw.get("n") is not None:
        kw["n"] = kw["n"].astype(int)
    data = _surpyval(x=kw.get("x"), xl=kw.get("xl"), xr=kw.get("xr"), c=kw.get("c"), n=kw.get("n"),
                     tl=kw.get("tl"), tr=kw.get("tr"), group_and_sort=False)
    return data, rows[keep], left_out


def item_data(df: pd.DataFrame, reading: dict):
    """``(SurpyvalData, None, left_out)`` for rows that follow an item over
    time (an item column, not repairable): start and stop rows each a stretch
    of the item's line (from xl, or the item's previous row, to xr or x),
    ending in its status on that row (blank: carries on)."""
    i, c = reading["i"], reading.get("c")
    end_col = reading.get("xr") or reading.get("x")
    start_col = reading.get("xl") or reading.get("tl")
    if not end_col:
        raise LifetimesError("Say which column holds each row's time (x), or the end of its stretch (xr).")
    frame = pd.DataFrame({"i": df[i], "end": _numbers(df, end_col)})
    frame["start"] = _numbers(df, start_col) if start_col else np.nan
    frame["c"] = _numbers(df, c) if c else (np.nan if not reading.get("all_failed") else 0.0)
    frame["n"] = _numbers(df, reading.get("n")) if reading.get("n") else 1.0
    keep = frame["i"].notna() & np.isfinite(frame["end"])
    left_out = int((~keep).sum())
    frame = frame[keep].sort_values(["i", "end"], kind="mergesort")
    if frame.empty:
        raise LifetimesError(f"No row has both an item in “{i}” and a time in “{end_col}”.")
    prev = frame.groupby("i", sort=False)["end"].shift(1)
    frame["start"] = frame["start"].where(frame["start"].notna(), prev)
    # A blank status carries on to the next row (on an item's last row: still running).
    frame["c"] = frame["c"].fillna(1).astype(int)
    tl = frame["start"].to_numpy(dtype=float)
    data = _surpyval(x=frame["end"].to_numpy(dtype=float), c=frame["c"].to_numpy(),
                     n=np.nan_to_num(frame["n"].to_numpy(dtype=float), nan=1.0).astype(int),
                     tl=np.where(np.isfinite(tl), tl, 0.0) if np.isfinite(tl).any() else None,
                     i=frame["i"].astype(str).to_numpy())
    return data, None, left_out


def repairable_data(df: pd.DataFrame, reading: dict):
    """``(SurpyvalData, None, left_out)`` for repairable data: each system's
    events on its line, as the repairable fit reads them
    (``recurrent.build_inputs``, after one stream and the end of record),
    with where its record ends as a right bound."""
    from backend import recurrent

    mapping = {k: reading.get(k) for k in ("x", "c", "n", "tl", "tr", "i") if reading.get(k)}
    mapping["one_stream"] = bool(reading.get("one_stream"))
    df, mapping = recurrent.one_stream(df, mapping)
    try:
        df, mapping = recurrent.with_record_end(df, mapping, reading.get("record_end"))
        inputs = recurrent.build_inputs(df, {k: v for k, v in mapping.items() if k != "one_stream"})
    except FitError as exc:
        raise LifetimesError(str(exc)) from exc
    left_out = int(len(df) - len(inputs["x"]))
    order = np.lexsort((inputs["x"], inputs["i"]))
    pick = {k: (np.asarray(v)[order] if np.size(v) == len(order) else v) for k, v in inputs.items()}
    return _surpyval(x=pick["x"], c=pick.get("c"), n=pick.get("n"), tl=pick.get("tl"), tr=pick.get("tr"),
                     i=pick["i"]), None, left_out


def _summary(lines: list, mode: str) -> dict:
    """Counts of what the lines say: units (a row's count included), and how
    each one ended."""
    out = {"units": 0, "failed": 0, "running": 0, "before": 0, "window": 0, "late": 0, "events": 0}
    for line in lines:
        marks = [m for m in line["marks"] if m["kind"] != "bound"]
        if mode == "repairable":
            out["units"] += 1
            out["events"] += sum(m.get("n", 1) for m in marks if m["kind"] == "failed")
            continue
        if mode == "items":
            weight, ends = 1, [m for m in marks if m["kind"] != "step"][-1:]
        else:
            weight, ends = line["n"], marks
        out["units"] += weight
        for m in ends:
            out[m["kind"]] += weight
        if line["entered"] is not None:
            out["late"] += weight
    return out


def _groups(df: pd.DataFrame, reading: dict, lines: list, mode: str) -> dict:
    """``{column: [value per line]}`` for the covariates with few values, to
    sort or colour the lines by."""
    cols = [c for c in reading.get("z") or [] if c in df.columns
            and 1 < df[c].nunique(dropna=True) <= MAX_GROUP_LEVELS]
    if not cols:
        return {}
    if mode == "rows":
        index = [line["rows"][0] - 1 for line in lines]
        return {c: [None if pd.isna(v) else str(v) for v in df[c].to_numpy()[index]] for c in cols}
    item = reading.get("i")
    if not item:
        return {}
    first = df.drop_duplicates(item).set_index(df.drop_duplicates(item)[item].astype(str))
    return {c: [None if line["id"] not in first.index or pd.isna(first.at[line["id"], c])
                else str(first.at[line["id"], c]) for line in lines] for c in cols}


def _thin(lines: list, groups: dict, limit: int) -> tuple[list, dict]:
    """An even sample of ``limit`` lines across their time order."""
    order = sorted(range(len(lines)), key=lambda j: (lines[j]["end"], j))
    pick = sorted(order[int(round(s))] for s in np.linspace(0, len(order) - 1, limit))
    return [lines[j] for j in pick], {c: [v[j] for j in pick] for c, v in groups.items()}


def for_frame(df: pd.DataFrame, reading: dict, *, repairable: bool = False, limit: int = MAX_LINES) -> dict:
    """The Lifetimes payload for a table read with ``reading``:
    ``{mode, lines, summary, floor, ceiling, unit, total, sampled, groups,
    left_out, notes}``. ``mode``: "rows" (one line per row, a row with a
    count for several units), "items" (an item's rows on its line) or
    "repairable" (a system's events on its line). Raises LifetimesError."""
    reading = dict(reading or {})
    if not (reading.get("x") or reading.get("xl")):
        raise LifetimesError("Say which column holds x (the time each unit failed or was last seen), then the "
                             "lifetimes show here.")
    df = df.dropna(how="all").reset_index(drop=True)
    notes = []
    df, note = _units(df, reading)
    if note:
        notes.append(note)
    try:
        df = _status(df, reading)
    except FitError as exc:
        raise LifetimesError(str(exc)) from exc
    e = reading.get("e")
    if e and e in df.columns and not reading.get("c") and not reading.get("xl") and not reading.get("m"):
        # A failure-mode column with no status column: a blank mode is a unit
        # still running (as the reading's summary says, and the fits read it).
        from backend.services.compare_groups import _label

        df = df.assign(**{STATUS_COLUMN: [1 if _label(v) is None else 0 for v in df[e].tolist()]})
        reading = {**reading, "c": STATUS_COLUMN, "c_map": None, "c_invert": False, "all_failed": False}
    stream = bool(reading.get("one_stream")) and not reading.get("i")
    if repairable or stream:
        mode = "repairable"
        data, rows, left_out = repairable_data(df, reading)
    elif reading.get("i"):
        mode = "items"
        data, rows, left_out = item_data(df, reading)
    else:
        mode = "rows"
        data, rows, left_out = life_data(df, reading)
    drawn = lines_of(data, rows)
    lines = drawn["lines"]
    for line in lines:
        bounds = [m["at"] for m in line["marks"] if m["kind"] == "bound"]
        if mode == "repairable" and bounds:
            # A system is watched up to where its record ends, past its last event.
            line["end"] = max(line["end"], max(bounds))
        if mode == "items":
            # An item's earlier stretches end where the next begins (its values change), not "still running".
            ends = [m for m in line["marks"] if m["kind"] != "bound"]
            for m in ends[:-1]:
                if m["kind"] == "running":
                    m["kind"] = "step"
    summary = _summary(lines, mode)
    groups = _groups(df, reading, lines, mode)
    total = len(lines)
    sampled = total > limit
    if sampled:
        lines, groups = _thin(lines, groups, limit)
    return {
        "mode": mode, "lines": lines, "summary": summary, "floor": drawn["floor"], "ceiling": drawn["ceiling"],
        "unit": reading.get("unit") or "", "total": total, "sampled": sampled, "groups": groups,
        "left_out": left_out, "notes": notes,
    }


def for_dataset(dataset, reading: dict) -> dict:
    """``for_frame`` for a saved dataset's life table, repairable when the
    reading tags it Repairable (as the dataset's page and the fits do)."""
    from backend.services import datasets as datasets_service

    df = datasets_service.load_dataframe(dataset)
    try:
        tags = datasets_service.detect_tags(df, reading).get("tags") or []
    except Exception:  # noqa: BLE001 - tags only choose the layout
        tags = []
    return for_frame(df, reading, repairable="Repairable" in tags)
