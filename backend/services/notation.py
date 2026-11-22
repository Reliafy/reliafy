"""Life data typed in as text, in SurPyval's notation, and back.

``120, 310, [400, 450], 1000+`` is five lives: plain numbers failed there,
``[a, b]`` failed some time in that window, ``1000+`` is still running at
1000, ``<50`` (or ``50-``) failed some time before 50, ``3*200`` three units
alike, and ``| (tl, tr]`` after an entry the window it was observed in. One
history per line, ``P1: 120, 310, 1000+``, is a unit's repeated failures
(repairable data). The grammar is SurPyval's own
(``surpyval.utils.notation``): this module reads it with SurPyval, says
where it stops reading, and writes the result as the CSV a spreadsheet of the
same data would be, with the reading that names each column, so a typed
dataset is an ordinary dataset to everything downstream.

The CSV's columns are SurPyval's names, in the order the New dataset form
writes them: ``x`` (``xl`` and ``xr`` instead when any entry is a window,
the others with the same value twice), ``c`` (0 failed, 1 still running, -1
failed before, 2 in a window), ``n`` when any entry counts several units,
``tl`` / ``tr`` when any entry has a window it was observed in (blank: no
limit), and ``i`` first for histories. Rows keep the order they were typed.

``dataset_text`` goes the other way, for "Show as text": the dataset read as
its reading says, written with ``SurpyvalData.to_notation()``.
"""

from __future__ import annotations

import csv
import io
import math
import re
from typing import Any

#: Most text a typed dataset takes; past it, a file is the way in.
MAX_CHARS = 100_000
#: Most rows "Show as text" writes out.
MAX_TEXT_ROWS = 200

_ITEM_LINE = re.compile(r"^\s*[^\s:\[\(<|][^:\[\(|]*:")


class NotationError(ValueError):
    """Text that can't be read, in SurPyval's words, with where: ``entry`` (the
    text of the entry it stopped at), ``line`` and ``column`` (1-based), and
    ``start`` / ``end`` (character offsets into the text) where known."""

    def __init__(self, message: str, *, entry: str | None = None, line: int | None = None,
                 column: int | None = None, start: int | None = None, end: int | None = None):
        super().__init__(message)
        self.entry, self.line, self.column, self.start, self.end = entry, line, column, start, end

    def payload(self) -> dict:
        out: dict[str, Any] = {"message": str(self)}
        for key in ("entry", "line", "column", "start", "end"):
            value = getattr(self, key)
            if value is not None:
                out[key] = value
        return out


def _entries(text: str, offset: int = 0) -> list[tuple[str, int, int]]:
    """``(entry, start, end)`` for each entry of a line of observations, split
    as SurPyval splits them: on commas, semicolons and new lines outside an
    interval ``[a, b]`` or a window ``(a, b]``."""
    out: list[tuple[str, int, int]] = []
    depth, begin = 0, 0
    for k, ch in enumerate(text + "\n"):
        if ch in "[(":
            depth += 1
        elif ch in "])":
            depth -= 1
        if (ch in ",;\n" and depth <= 0) or k == len(text):
            raw = text[begin:k]
            if raw.strip():
                lead = len(raw) - len(raw.lstrip())
                out.append((raw.strip(), offset + begin + lead, offset + begin + lead + len(raw.strip())))
            begin = k + 1
    return out


def _where(text: str, start: int) -> tuple[int, int]:
    """1-based (line, column) of a character offset."""
    before = text[:start]
    return before.count("\n") + 1, start - (before.rfind("\n") + 1) + 1


def _located(exc: Exception, text: str, entry: str, start: int, end: int, label: str) -> NotationError:
    line, column = _where(text, start)
    return NotationError(f"{label} (line {line}, “{entry}”): {exc}", entry=entry, line=line, column=column,
                         start=start, end=end)


def is_histories(text: str) -> bool:
    """Whether the text is unit histories (``P1: …`` lines) rather than one
    list of lives."""
    return any(_ITEM_LINE.match(ln) for ln in (text or "").splitlines() if ln.strip())


def _check_text(text: Any) -> str:
    if not isinstance(text, str) or not text.strip():
        raise NotationError("Nothing to read yet: type the lives, for example 120, 310, [400, 450], 1000+.")
    if len(text) > MAX_CHARS:
        raise NotationError(f"That's too much to type in ({len(text):,} characters; at most {MAX_CHARS:,}). "
                            "Upload it as a file instead.")
    return text


def _parse_lives(text: str):
    from surpyval.utils.notation import Observations

    try:
        return Observations.parse(text)
    except ValueError as whole:
        # Read entry by entry to say which one stopped it.
        for k, (entry, start, end) in enumerate(_entries(text)):
            try:
                Observations.parse(entry)
            except ValueError as exc:
                raise _located(exc, text, entry, start, end, f"Entry {k + 1}") from None
        raise NotationError(str(whole)) from None


def _parse_histories(text: str):
    from surpyval.utils.notation import Items

    offset = 0
    lines = []
    for raw in text.splitlines(keepends=True):
        body = raw.rstrip("\r\n")
        if body.strip():
            lead = len(body) - len(body.lstrip())
            lines.append((body.strip(), offset + lead))
        offset += len(raw)
    for k, (line, start) in enumerate(lines):
        if not _ITEM_LINE.match(line):
            row, _ = _where(text, start)
            raise NotationError(
                f"Line {row} (“{line}”) has no unit id, but other lines do. Write every line as a unit's history, "
                "its id, a colon and its events (P2: 200, 900+), or take the ids off every line for one list of "
                "lives.", entry=line, line=row, column=1, start=start, end=start + len(line))
        try:
            Items.parse(line)
        except ValueError as exc:
            raise _located(exc, text, line, start, start + len(line), "Line " + str(_where(text, start)[0])) from None
    try:
        return Items.parse(text)
    except ValueError as exc:
        raise NotationError(str(exc)) from None


def _number(value: float) -> str:
    """A time as a CSV cell: blank for no limit, else in full."""
    if value is None or not math.isfinite(value):
        return ""
    out = repr(float(value))
    return out[:-2] if out.endswith(".0") else out


def _fmt(value: float) -> str:
    """A time for people: up to 4 significant figures, thousands separated."""
    if not math.isfinite(value):
        return "no limit"
    rounded = float(f"{value:.4g}")
    if rounded == int(rounded) and abs(rounded) < 1e15:
        return f"{int(rounded):,}"
    whole, _, frac = f"{rounded:,.6f}".partition(".")
    frac = frac.rstrip("0")
    return f"{whole}.{frac}" if frac else whole


def _rows(obs_list, ids=None) -> tuple[list[str], list[list[str]], dict]:
    """The CSV header and rows for a list of observations (one row each, in
    order), with ``ids`` as the item column where given."""
    window = any(o.code == 2 for o in obs_list)
    counted = any(o.n != 1 for o in obs_list)
    tl = any(o.truncation is not None and math.isfinite(o.truncation.left) for o in obs_list)
    tr = any(o.truncation is not None and math.isfinite(o.truncation.right) for o in obs_list)
    header = (["i"] if ids is not None else []) + (["xl", "xr"] if window else ["x"]) + ["c"]
    header += (["n"] if counted else []) + (["tl"] if tl else []) + (["tr"] if tr else [])
    rows = []
    for k, o in enumerate(obs_list):
        lo, hi = o._bounds() if o.code == 2 else (o.x, o.x)
        row = ([str(ids[k])] if ids is not None else []) + ([_number(lo), _number(hi)] if window else [_number(lo)])
        row.append(str(o.code))
        if counted:
            row.append(str(int(o.n)))
        if tl:
            row.append(_number(o.truncation.left if o.truncation else -math.inf))
        if tr:
            row.append(_number(o.truncation.right if o.truncation else math.inf))
        rows.append(row)
    roles = {r: r for r in header}
    return header, rows, roles


def _lives_summary(obs_list) -> tuple[str, dict]:
    failed = [o for o in obs_list if o.code == 0]
    before = [o for o in obs_list if o.code == -1]
    windows = [o for o in obs_list if o.code == 2]
    running = [o for o in obs_list if o.code == 1]
    late = [o for o in obs_list if o.truncation is not None]

    def units(group):
        return int(sum(o.n for o in group))

    counts = {"units": units(obs_list), "failed": units(failed), "failed_before": units(before),
              "in_window": units(windows), "running": units(running), "observed_in_window": units(late)}
    parts = []
    if failed:
        parts.append(f"{counts['failed']} failed")
    if windows:
        k = counts["in_window"]
        if len(windows) == 1:
            lo, hi = windows[0]._bounds()
            parts.append(f"{k} in a window {_fmt(lo)}–{_fmt(hi)}" if k == 1 else f"{k} in the window {_fmt(lo)}–{_fmt(hi)}")
        else:
            parts.append(f"{k} in windows")
    if before:
        k = counts["failed_before"]
        parts.append(f"{k} failed before {_fmt(before[0].x)}" if len(before) == 1 else f"{k} failed before a first look")
    if running:
        k = counts["running"]
        if len(running) == 1:
            parts.append(f"{k} still running at {_fmt(running[0].x)}")
        else:
            xs = [o.x for o in running]
            parts.append(f"{k} still running ({_fmt(min(xs))} to {_fmt(max(xs))})")
    n = counts["units"]
    text = f"{n} unit{'' if n == 1 else 's'}: " + ", ".join(parts)
    if late:
        k = counts["observed_in_window"]
        text += f"; {k} observed only within a window (truncated)"
    return text, counts


def _histories_summary(items) -> tuple[str, dict]:
    events = [e for it in items for e in it.events]
    failures = [e for e in events if e.code != 1]
    ends = [e for e in events if e.code == 1]
    windows = [e for e in failures if e.code == 2]
    n_fail = int(sum(e.n for e in failures))
    counts = {"units": len(items), "failures": n_fail, "in_window": int(sum(e.n for e in windows)),
              "still_watched": len(ends), "late_entry": sum(1 for it in items if it.truncation is not None)}
    n = len(items)
    text = f"{n} unit{'' if n == 1 else 's'}' histories: {n_fail} failure{'' if n_fail == 1 else 's'}"
    if windows:
        if len(windows) == 1:
            lo, hi = windows[0]._bounds()
            text += f" (1 in a window {_fmt(lo)}–{_fmt(hi)})"
        else:
            text += f" ({counts['in_window']} in windows)"
    if ends:
        if len(ends) == 1:
            text += f"; watched to {_fmt(ends[0].x)}" + ("" if n == 1 else " on one unit")
        else:
            text += f"; {len(ends)} watched to an end time"
    if counts["late_entry"]:
        text += f"; {counts['late_entry']} came under observation late"
    return text, counts


def read(text: str, unit: str | None = None) -> dict:
    """What the text says, and the dataset it makes: ``{"kind": "lives" |
    "histories", "summary", "counts", "csv", "columns", "rows" (the first
    few, as cells), "n_rows", "reading", "notation"}``, or a
    :class:`NotationError` saying where it stopped and what to write."""
    text = _check_text(text)
    reading: dict[str, Any] = {}
    if is_histories(text):
        items = _parse_histories(text)
        obs, ids = [], []
        for it in items:
            # One row per event, as a work-order log has them: a failure counted several times (3*200) is
            # that many rows. The item's window is its late entry, on its first row (as SurPyval's data has it).
            rows_of = [e._copy() for e in it.events for _ in range(int(e.n))]
            for e in rows_of:
                e.n = 1
            for k, e in enumerate(rows_of):
                obs.append(e / it.truncation if (k == 0 and it.truncation is not None and e.truncation is None) else e)
                ids.append(it.id)
        if not obs:
            raise NotationError("No events to read: give each unit at least one, e.g. P1: 120, 1000+.")
        header, rows, roles = _rows(obs, ids)
        summary, counts = _histories_summary(items)
        kind, canonical = "histories", items.text()
    else:
        lives = _parse_lives(text)
        if not len(lives):
            raise NotationError("Nothing to read yet: type the lives, for example 120, 310, [400, 450], 1000+.")
        header, rows, roles = _rows(list(lives))
        summary, counts = _lives_summary(list(lives))
        kind, canonical = "lives", lives.text()
    reading.update(roles)
    reading["unit"] = (unit or "").strip()
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(header)
    w.writerows(rows)
    return {"kind": kind, "summary": summary, "counts": counts, "csv": buf.getvalue(), "columns": header,
            "rows": rows[:8], "n_rows": len(rows), "reading": reading, "notation": canonical}


def dataset_text(df, reading: dict) -> dict:
    """``{"text", "kind", "n_rows"}``: a dataset's life data written in the
    notation (``SurpyvalData.to_notation()``), read as its reading says; or a
    :class:`NotationError` saying why it can't be (too many rows, covariates,
    readings, a status column it can't read)."""
    import numpy as np

    from backend import fitting

    n_rows = int(len(df))
    if n_rows > MAX_TEXT_ROWS:
        raise NotationError(f"This dataset has {n_rows:,} rows; the text is offered up to {MAX_TEXT_ROWS}. "
                            "Download the CSV instead.")
    held = [name for role, name in (("z", "covariates"), ("m", "readings"), ("e", "failure modes"),
                                    ("s", "states"), ("x2", "a second clock"), ("u", "a unit column"))
            if reading.get(role)]
    if held:
        raise NotationError("The text holds times, status, counts and windows; this dataset also has "
                            + " and ".join(held) + ", which it would leave out. Download the CSV instead.")
    from backend.services.dataset_reading import life_mapping

    mapping, options = life_mapping(reading)
    if not mapping.get("x") and not mapping.get("xl"):
        raise NotationError("Say which column holds x first (Change, beside how the columns are read).")
    work = df
    if options.get("c_map"):
        work = fitting.map_censor_column(work, mapping["c"], options["c_map"])
    elif options.get("c_invert") and mapping.get("c"):
        work = fitting.invert_censor_column(work, mapping["c"])
    try:
        kw = fitting.build_fit_inputs(work, mapping)
    except fitting.FitError as exc:
        raise NotationError(str(exc)) from None
    from surpyval import SurpyvalData

    if "xl" in kw:
        x = np.column_stack([kw["xl"], kw["xr"]])
    else:
        x = kw["x"]
    c = kw.get("c")
    args: dict[str, Any] = {"x": x}
    if c is not None:
        args["c"] = np.asarray(c, dtype=int)
    for key in ("n", "tl", "tr"):
        if key in kw:
            args[key] = kw[key] if key != "n" else np.asarray(kw[key], dtype=int)
    item = reading.get("i")
    if item and item in df.columns:
        args["i"] = [str(v) for v in df[item].tolist()]
    if reading.get("unit"):
        args["unit"] = str(reading["unit"])
    try:
        data = SurpyvalData(**args)
        notation = data.to_notation()
    except (ValueError, TypeError) as exc:
        raise NotationError(f"This dataset can't be written as text: {exc}") from None
    return {"text": notation.text(), "kind": "histories" if item else "lives", "n_rows": n_rows}
