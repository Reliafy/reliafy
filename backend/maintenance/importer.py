"""Bringing an existing history in from a spreadsheet: one row per item per
position, and the positions, items, fitments and failures follow.

Columns (names are matched loosely; only ``position`` is required):

==============  ================================================================
position        the position's path: ``House > Pool > Pump`` (or ``/``)
class           its position class (to pool and compare)
item            what was fitted (a new item is created per row)
serial, manufacturer, model, part number   the item's details
fitted          when it went in
removed         when it came out (blank: still fitted)
failed          yes / no: did it come out because it failed?
failure mode    how it failed (added to the position's failure modes)
==============  ================================================================

Every row is checked before anything is written; with any error, nothing is
written (fix the sheet and run it again). ``dry_run`` reports what would be
made. A position that already exists (same name, same parent) is reused.
"""

from __future__ import annotations

import csv
import io
import re
from datetime import date

from backend.maintenance.service import MAX_ITEMS, MAX_POSITIONS, Invalid, Maintenance, _text, new_id

MAX_ROWS = 5000
MAX_COLS = 50
MAX_CELL = 1000  # characters in one cell
MAX_LINE = 64 * 1024  # bytes in the header line

ALIASES = {
    "position": ("position", "position path", "path", "functional location", "floc", "asset", "equipment position"),
    "class": ("class", "position class", "type", "equipment class"),
    "item": ("item", "equipment", "component", "unit", "item name"),
    "serial": ("serial", "serial number", "serial no", "sn"),
    "manufacturer": ("manufacturer", "make", "brand", "oem"),
    "model": ("model", "model number"),
    "part_number": ("part number", "part no", "part", "pn"),
    "fitted": ("fitted", "installed", "install date", "fitted on", "in service", "start"),
    "removed": ("removed", "removal date", "removed on", "out of service", "end"),
    "failed": ("failed", "failure", "failed?", "removed because it failed", "reason"),
    "failure_mode": ("failure mode", "mode", "cause", "failure cause"),
}

_TRUE = {"yes", "y", "true", "1", "failed", "failure", "fail"}
_FALSE = {"no", "n", "false", "0", "planned", "", "preventive", "pm", "upgrade"}


def _norm(text) -> str:
    return re.sub(r"[^a-z0-9]+", " ", str(text or "").lower()).strip()


def map_columns(header: list[str]) -> dict[str, str]:
    """Which sheet column feeds each field."""
    out = {}
    normed = {_norm(h): h for h in header}
    for field, names in ALIASES.items():
        for name in names:
            if _norm(name) in normed:
                out[field] = normed[_norm(name)]
                break
    return out


def _too_wide(n: int) -> Invalid:
    return Invalid(f"The sheet has {n} columns; at most {MAX_COLS} can be imported. Keep just the columns "
                   "listed in the help.")


def check_csv(data: bytes) -> None:
    """Check a CSV's size before it's parsed in full: the header line's length,
    at most MAX_COLS columns, MAX_ROWS rows and MAX_CELL characters a cell.
    Raises Invalid, saying which."""
    header = data.split(b"\n", 1)[0]
    if len(header) > MAX_LINE:
        raise Invalid(f"The first line is over {MAX_LINE // 1024} KB; it should be the column names.")
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = data.decode("latin-1")
    rows = 0
    try:
        for i, row in enumerate(csv.reader(io.StringIO(text, newline=""))):
            if len(row) > MAX_COLS:
                raise _too_wide(len(row)) if i == 0 else Invalid(
                    f"Row {i + 1} has {len(row)} cells; at most {MAX_COLS}.")
            if any(len(cell) > MAX_CELL for cell in row):
                raise Invalid(f"Row {i + 1} has a cell over {MAX_CELL} characters.")
            if i and any(cell.strip() for cell in row):
                rows += 1
                if rows > MAX_ROWS:
                    raise Invalid(f"At most {MAX_ROWS} rows at a time.")
    except csv.Error as err:
        raise Invalid(f"That file couldn't be read as CSV: {err}.") from None


def check_rows(rows: list[dict]) -> None:
    """The same limits for rows given directly (an MCP tool's rows)."""
    if len(rows) > MAX_ROWS:
        raise Invalid(f"At most {MAX_ROWS} rows at a time.")
    for i, r in enumerate(rows, start=2):
        if not isinstance(r, dict):
            raise Invalid(f"Row {i}: each row is an object of column: value.")
        if len(r) > MAX_COLS:
            raise _too_wide(len(r))
        if any(len(str(k)) > MAX_CELL or len(str(v)) > MAX_CELL for k, v in r.items()):
            raise Invalid(f"Row {i} has a cell over {MAX_CELL} characters.")


def rows_from_file(data: bytes, filename: str) -> list[dict]:
    """A CSV or Excel sheet as a list of {column: value} rows (strings)."""
    import pandas as pd

    from backend.services import excel

    if excel.is_excel(data, filename):
        df = excel.to_dataframe(excel.read_table(data, filename=filename, max_rows=MAX_ROWS))
        if len(df.columns) > MAX_COLS:
            raise _too_wide(len(df.columns))
    else:
        check_csv(data)
        df = pd.read_csv(io.BytesIO(data), dtype=str, keep_default_na=False, nrows=MAX_ROWS + 1)
    df = df.fillna("")
    if len(df) > MAX_ROWS:
        raise Invalid(f"At most {MAX_ROWS} rows at a time.")
    rows = [{str(k): ("" if v is None else str(v)).strip() for k, v in r.items()} for r in df.to_dict("records")]
    check_rows(rows)
    return rows


def _date(value, what: str, row: int) -> str | None:
    text = str(value or "").strip()
    if not text:
        return None
    import pandas as pd

    try:
        return pd.to_datetime(text, dayfirst=not re.match(r"^\d{4}-", text)).date().isoformat()
    except (ValueError, TypeError, OverflowError):
        raise Invalid(f"Row {row}: the {what} date '{text}' isn't a date.")


def _path(value) -> list[str]:
    return [part.strip() for part in re.split(r"\s*(?:>|/|\\|›)\s*", str(value or "")) if part.strip()]


def parse(rows: list[dict]) -> list[dict]:
    """Check and normalise every row; raises Invalid listing the first problems."""
    if not rows:
        raise Invalid("The sheet has no rows.")
    check_rows(rows)
    cols = map_columns(list(rows[0].keys()))
    if "position" not in cols:
        raise Invalid("There's no position column (a path like 'House > Pool > Pump').")
    out, errors = [], []
    for i, raw in enumerate(rows, start=2):
        get = lambda f: raw.get(cols[f], "") if f in cols else ""
        try:
            path = _path(get("position"))
            if not path:
                raise Invalid(f"Row {i}: the position is blank.")
            # The same limits as adding each by hand, checked before anything is written.
            try:
                for part in path:
                    _text(part, "position's name")
                for f, what in (("class", "class"), ("item", "item's name"), ("serial", "serial"),
                                ("manufacturer", "manufacturer"), ("model", "model"),
                                ("part_number", "part number"), ("failure_mode", "failure mode")):
                    _text(get(f), what)
            except Invalid as err:
                raise Invalid(f"Row {i}: {err}") from None
            fitted, removed = _date(get("fitted"), "fitted", i), _date(get("removed"), "removed", i)
            item = get("item")
            if (fitted or removed) and not item:
                raise Invalid(f"Row {i}: dates without an item.")
            if item and not fitted:
                raise Invalid(f"Row {i}: {item} needs the date it was fitted.")
            if removed and removed < fitted:
                raise Invalid(f"Row {i}: it can't come out ({removed}) before it went in ({fitted}).")
            flag = _norm(get("failed"))
            if flag not in _TRUE and flag not in _FALSE:
                raise Invalid(f"Row {i}: 'failed' should be yes or no, not '{get('failed')}'.")
            out.append({"row": i, "path": path, "class": get("class"), "item": item,
                        "details": {k: get(k) for k in ("serial", "manufacturer", "model", "part_number")},
                        "fitted": fitted, "removed": removed,
                        "failed": flag in _TRUE and bool(removed), "failure_mode": get("failure_mode")})
        except Invalid as err:
            errors.append(str(err))
            if len(errors) >= 10:
                break
    if errors:
        raise Invalid("; ".join(errors))
    # Within one position, an item can't go in before the previous one came out.
    by_path: dict = {}
    for r in out:
        if r["item"]:
            by_path.setdefault(" > ".join(r["path"]).lower(), []).append(r)
    for rs in by_path.values():
        rs.sort(key=lambda r: r["fitted"])
        for prev, nxt in zip(rs, rs[1:]):
            if prev["removed"] and prev["removed"] > nxt["fitted"]:
                errors.append(f"Rows {prev['row']} and {nxt['row']}: {' > '.join(nxt['path'])} has two items "
                              f"fitted at once ({nxt['fitted']} is before {prev['removed']}).")
    if errors:
        raise Invalid("; ".join(errors[:10]))
    return out


def run(m: Maintenance, rows: list[dict], dry_run: bool = False) -> dict:
    if not dry_run:
        # Every check first: a sheet that can't all go in writes nothing.
        preview = run(m, rows, dry_run=True)
        m._quota("Position", MAX_POSITIONS, adding=preview["positions_created"])
        m._quota("Item", MAX_ITEMS, adding=preview["items_created"])
    parsed = parse(rows)
    existing = {}
    for p in m.s.nodes(m.org, "Position"):
        if p.get("retired"):
            continue
        parent = m._parent(p["id"])
        existing[(parent["id"] if parent and parent["label"] == "Position" else None, p["name"].lower())] = p["id"]

    report = {"rows": len(parsed), "positions_created": 0, "items_created": 0, "fitments": 0, "failures": 0,
              "dry_run": dry_run}
    planned: dict = {}

    def ensure(path: list[str], cls: str) -> str:
        parent = None
        for depth, name in enumerate(path):
            key = (parent, name.lower())
            pid = existing.get(key) or planned.get(key)
            if pid is None:
                report["positions_created"] += 1
                if dry_run:
                    pid = planned[key] = f"new-{len(planned)}"
                else:
                    last = depth == len(path) - 1
                    pid = m.create_position(name, parent_id=parent, position_class=cls if last else "")["id"]
                    existing[key] = pid
            parent = pid
        return parent

    # Oldest first within each position, so each fit finds the slot as history left it.
    for r in sorted(parsed, key=lambda r: (" > ".join(r["path"]).lower(), r["fitted"] or "")):
        pid = ensure(r["path"], r["class"])
        if not r["item"]:
            continue
        report["items_created"] += 1
        report["fitments"] += 1
        report["failures"] += r["failed"]
        if dry_run:
            current = m.current_fitment(pid) if not pid.startswith("new-") else None
            if current and current["from"] > r["fitted"]:
                raise Invalid(f"Row {r['row']}: {' > '.join(r['path'])} already has an item fitted since "
                              f"{current['from']}, after this row's {r['fitted']}.")
            continue
        if r["class"]:
            node = m.s.node(m.org, pid)
            if not node.get("position_class"):
                m.update_position(pid, position_class=r["class"])
        current = m.current_fitment(pid)
        if current:
            if current["from"] > r["fitted"]:
                raise Invalid(f"Row {r['row']}: {' > '.join(r['path'])} already has an item fitted since "
                              f"{current['from']}, after this row's {r['fitted']}.")
            m.remove(pid, on=r["fitted"], reason="planned")
        m.fit(pid, new_item={"name": r["item"], **r["details"]}, on=r["fitted"])
        if r["removed"]:
            mode_id = None
            if r["failed"] and r["failure_mode"]:
                modes = {fm["text"].lower(): fm["id"] for fm in m._modes_on(pid)}
                mode_id = modes.get(r["failure_mode"].lower())
                if mode_id is None:
                    mode_id = new_id()
                    m._emit("failure_mode.added", {"id": mode_id, "position_id": pid, "text": r["failure_mode"],
                                                   "function": "", "failure": "", "consequence": None,
                                                   "outcome": None, "rcm_mode_id": None, "study_id": None})
            m.remove(pid, on=r["removed"], reason="failure" if r["failed"] else "planned",
                     failure_mode_id=mode_id)
    return report
