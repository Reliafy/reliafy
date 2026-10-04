"""Read uploaded Excel workbooks (``.xlsx``) as plain tables.

One reader shared by every spreadsheet import — life-data datasets, RCM
worksheets and RBD templates. Two calls:

* :func:`inspect` — the sheets in a workbook, each with its size, a preview of
  its first rows (as display strings) and a guess at which row holds the
  column headers;
* :func:`read_table` — one sheet as ``header + rows`` from a chosen header
  row, with :func:`to_csv` / :func:`to_dataframe` to hand it to code that
  already speaks CSV.

Workbooks are untrusted input. They are opened with openpyxl in read-only,
values-only mode (``data_only=True``: a formula cell reads as the value Excel
last calculated and saved — nothing is ever evaluated), after checking the
raw size, the zip's declared uncompressed size (zip bombs) and the format;
openpyxl parses the XML with ``defusedxml`` (installed), so no entity
expansion or external fetches. Rows and columns are capped.

Spreadsheet quirks handled here, so every importer sees a clean table:

* the header needn't be on row 1 (title rows above it) — :func:`inspect`
  guesses, the user picks;
* merged cells: a vertically merged block (a "Function" cell spanning the
  rows below it) fills down; a blank header cell inside a horizontally merged
  header takes the merged header's name (de-duplicated: "Effect", "Effect (2)");
* blank rows are skipped, blank trailing columns dropped, blank or repeated
  header names made unique;
* dates become ISO text, whole numbers stay whole, Excel error values
  (``#DIV/0!``, ``#N/A``) read as blank (with a note);
* formulas that were never calculated (files written by scripts, not Excel)
  have no saved value — they read as blank, and a note says so.

Legacy ``.xls``, binary ``.xlsb``, OpenDocument and password-protected files
are refused with a message saying what to do.
"""

from __future__ import annotations

import csv
import io
import math
import re
import zipfile
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from typing import Any, Iterator, Optional

# Same ceilings as the RBD importer (backend/services/rbd_import/types.py):
# the raw upload, and everything the zip would inflate to.
MAX_FILE_BYTES = 50 * 1024 * 1024
MAX_UNCOMPRESSED_BYTES = 200 * 1024 * 1024
# A table bigger than this isn't a dataset, a worksheet or a diagram.
MAX_ROWS = 100_000
MAX_COLS = 200
MAX_SHEETS = 100
PREVIEW_ROWS = 20
# Merged ranges read per sheet; a sheet with more is read without merge fill.
MAX_MERGES = 10_000

EXCEL_EXTENSIONS = (".xlsx", ".xlsm", ".xltx", ".xltm")
REFUSED_EXTENSIONS = {
    ".xls": "legacy Excel 97–2003 (.xls)",
    ".xlsb": "Excel binary (.xlsb)",
    ".ods": "OpenDocument (.ods)",
}

_ZIP_MAGIC = b"PK\x03\x04"
_CFB_MAGIC = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"   # OLE compound file (.xls, encrypted .xlsx)
_ENCRYPTED_MARKER = "EncryptionInfo".encode("utf-16-le")

_SAVE_AS = "Open it in Excel (or LibreOffice / Google Sheets) and save it as .xlsx, then upload that."


class ExcelError(ValueError):
    """A workbook that can't be read (user-facing text)."""


# ---------------------------------------------------------------------------
# Format checks
# ---------------------------------------------------------------------------


def _ext(filename: str) -> str:
    name = (filename or "").lower().rsplit("/", 1)[-1]
    return "." + name.rsplit(".", 1)[-1] if "." in name else ""


def is_excel(data: bytes, filename: str = "") -> bool:
    """Whether an upload is (or claims to be) a spreadsheet workbook rather
    than CSV text — by extension, or by content (an OOXML zip or an OLE
    compound file). Refused formats count: :func:`inspect` explains them."""
    ext = _ext(filename)
    if ext in EXCEL_EXTENSIONS or ext in REFUSED_EXTENSIONS:
        return True
    head = data[:8] if data else b""
    return head.startswith(_ZIP_MAGIC) or head.startswith(_CFB_MAGIC)


def _check(data: bytes, filename: str) -> None:
    """Refuse anything that isn't a readable .xlsx before openpyxl sees it."""
    if not data:
        raise ExcelError("The file is empty.")
    if len(data) > MAX_FILE_BYTES:
        raise ExcelError(
            f"The workbook is larger than {MAX_FILE_BYTES // (1024 * 1024)} MB. "
            "Copy just the sheet you need into a new workbook and upload that."
        )
    if data.startswith(_CFB_MAGIC):
        if _ENCRYPTED_MARKER in data[:4 * 1024 * 1024] or _ext(filename) in EXCEL_EXTENSIONS:
            raise ExcelError(
                "This workbook is password-protected (encrypted), so it can't be read. "
                "Remove the password in Excel (File › Info › Protect Workbook › Encrypt "
                "with Password, clear it) and save it again."
            )
        raise ExcelError(f"This is a legacy Excel 97–2003 (.xls) file. {_SAVE_AS}")
    ext = _ext(filename)
    if not data.startswith(_ZIP_MAGIC):
        if ext in REFUSED_EXTENSIONS:
            raise ExcelError(f"This is an {REFUSED_EXTENSIONS[ext]} file. {_SAVE_AS}")
        raise ExcelError("This isn't an Excel .xlsx workbook. Upload a .xlsx file (or a CSV).")
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            infos = zf.infolist()
    except zipfile.BadZipFile:
        raise ExcelError("The workbook is damaged (it isn't a valid .xlsx archive).") from None
    names = {i.filename for i in infos}
    if "xl/workbook.bin" in names:
        raise ExcelError(f"This is an Excel binary (.xlsb) workbook. {_SAVE_AS}")
    if "content.xml" in names and "mimetype" in names:
        raise ExcelError(f"This is an OpenDocument (.ods) spreadsheet. {_SAVE_AS}")
    if "xl/workbook.xml" not in names and not any(n.endswith("/workbook.xml") for n in names):
        raise ExcelError("This isn't an Excel workbook (no workbook inside the file). Upload a .xlsx file.")
    if len(infos) > 10_000 or sum(i.file_size for i in infos) > MAX_UNCOMPRESSED_BYTES:
        raise ExcelError(
            "The workbook expands to more data than Reliafy reads in one upload. "
            "Copy just the sheet you need into a new workbook and upload that."
        )


def _open(data: bytes, filename: str):
    _check(data, filename)
    import openpyxl

    try:
        return openpyxl.load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    except ExcelError:
        raise
    except Exception:
        raise ExcelError(
            "Couldn't read this workbook — it may be damaged, or saved by a program "
            "that writes non-standard .xlsx. Try opening it in Excel and saving it again."
        ) from None


def _worksheets(wb) -> list:
    # Chart sheets have no cells.
    return [ws for ws in wb.worksheets if hasattr(ws, "iter_rows")][:MAX_SHEETS]


def _sheet(wb, sheet: Optional[str]):
    sheets = _worksheets(wb)
    if not sheets:
        raise ExcelError("The workbook has no worksheets.")
    if sheet is None or sheet == "":
        return sheets[0]
    for ws in sheets:
        if ws.title == sheet:
            return ws
    for ws in sheets:
        if ws.title.strip().lower() == str(sheet).strip().lower():
            return ws
    raise ExcelError(f"The workbook has no sheet named “{sheet}”.")


# ---------------------------------------------------------------------------
# Cell values
# ---------------------------------------------------------------------------


_ERROR_CODES: Optional[frozenset] = None


def _error_codes() -> frozenset:
    global _ERROR_CODES
    if _ERROR_CODES is None:
        from openpyxl.cell.cell import ERROR_CODES

        _ERROR_CODES = frozenset(ERROR_CODES)
    return _ERROR_CODES


def _clean(value: Any, stats: dict) -> Any:
    """A cell value as a plain Python value: str / int / float / None."""
    if value is None:
        return None
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            return None
        return int(value) if value.is_integer() and abs(value) < 2**53 else value
    if isinstance(value, datetime):
        if value.time() == time(0, 0):
            return value.date().isoformat()
        return value.replace(microsecond=0).isoformat(sep=" ")
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, time):
        return value.replace(microsecond=0).isoformat()
    if isinstance(value, timedelta):
        return value.total_seconds() / 3600.0
    text = str(value).strip()
    if not text:
        return None
    if text in _error_codes():
        stats["error_cells"] = stats.get("error_cells", 0) + 1
        return None
    return text


def display(value: Any) -> str:
    """A cleaned cell value as text (CSV cells, previews)."""
    if value is None:
        return ""
    if isinstance(value, float):
        return repr(value)
    return str(value)


# ---------------------------------------------------------------------------
# Merged cells and never-calculated formulas: read from the sheet XML
# ---------------------------------------------------------------------------


@dataclass
class _SheetMeta:
    merges: list[tuple[int, int, int, int]] = field(default_factory=list)  # r1, c1, r2, c2
    uncached_formulas: int = 0
    # More merged ranges than MAX_MERGES: merge fill is skipped.
    merges_skipped: bool = False
    # Whether any cell sits right of MAX_COLS (None: unknown — the pass
    # failed, or a cell had no reference), and whether one holds a value.
    wide: Optional[bool] = None
    wide_values: bool = False


def _sheet_meta(ws) -> _SheetMeta:
    """One streaming pass over the sheet XML for what read-only mode doesn't
    expose: merged ranges, formula cells with no saved value, and whether any
    cell lies beyond the columns read.

    Merged ranges that start below :data:`MAX_ROWS` or right of
    :data:`MAX_COLS` can't affect the table and are dropped; past
    :data:`MAX_MERGES` the rest are ignored and the sheet is read without
    merge fill (with a note)."""
    from defusedxml.ElementTree import iterparse
    from openpyxl.utils import get_column_letter
    from openpyxl.utils.cell import range_boundaries

    from backend.services import import_guard

    meta = _SheetMeta()
    try:
        src = ws._get_source()
    except Exception:  # pragma: no cover - openpyxl internals moved
        return meta
    last = get_column_letter(MAX_COLS)
    limit = (len(last), last)
    wide = False
    unknown = False
    events = 0
    try:
        for _event, el in iterparse(src, events=("end",)):
            events += 1
            if not events % 10_000:
                import_guard.check()
            tag = el.tag.rsplit("}", 1)[-1]
            if tag == "c":
                has_f = has_v = False
                for child in el:
                    ctag = child.tag.rsplit("}", 1)[-1]
                    if ctag == "f":
                        has_f = True
                    elif ctag in ("v", "is"):
                        has_v = has_v or bool(child.text) or ctag == "is"
                if has_f and not has_v:
                    meta.uncached_formulas += 1
                ref = el.get("r")
                if not ref:
                    unknown = True
                else:
                    letters = ref.rstrip("0123456789").upper()
                    if (len(letters), letters) > limit:
                        wide = True
                        meta.wide_values = meta.wide_values or has_v or has_f
            elif tag == "row":
                el.clear()
            elif tag == "mergeCell":
                if meta.merges_skipped:
                    continue
                ref = el.get("ref") or ""
                try:
                    c1, r1, c2, r2 = range_boundaries(ref)
                except (TypeError, ValueError):
                    continue
                if None in (c1, r1, c2, r2) or r1 > MAX_ROWS or c1 > MAX_COLS:
                    continue
                if len(meta.merges) >= MAX_MERGES:
                    meta.merges_skipped = True
                    meta.merges = []
                    continue
                meta.merges.append((r1, c1, r2, c2))
        meta.wide = None if unknown else wide
    except import_guard.ImportBudgetExceeded:
        raise
    except Exception:
        # A sheet openpyxl can read but this pass can't: carry on without
        # merge fill / formula notes rather than refusing the file.
        pass
    finally:
        src.close()
    return meta


# ---------------------------------------------------------------------------
# Rows
# ---------------------------------------------------------------------------


def _raw_rows(ws, meta: _SheetMeta, stats: dict, max_rows: Optional[int]) -> Iterator[tuple[int, list]]:
    """``(sheet row number, cleaned values)`` for every row, capped."""
    from backend.services import import_guard

    # Stored dimensions are often wrong (or claim the whole grid); read what's there.
    ws.reset_dimensions()
    # A sheet with cells right of MAX_COLS (or that the metadata pass
    # couldn't place) is read only that far: openpyxl otherwise pads every
    # such row out to its last cell, up to column XFD.
    bounded = meta.wide is not False
    rows = ws.iter_rows(max_col=MAX_COLS + 1, values_only=True) if bounded else ws.iter_rows(values_only=True)
    if meta.wide_values:
        stats["truncated_cols"] = True
    for i, row in enumerate(rows, start=1):
        if max_rows is not None and i > max_rows:
            stats["truncated_rows"] = True
            return
        if not i % 1000:
            import_guard.check()
        values = list(row[:MAX_COLS])
        if len(row) > MAX_COLS and any(v not in (None, "") for v in row[MAX_COLS:]):
            stats["truncated_cols"] = True
        if bounded:
            # Padded to MAX_COLS: drop the blank tail, as an unpadded row has none.
            if values.count(None) == len(values):
                values = []
            else:
                while values[-1] is None:
                    values.pop()
        yield i, [_clean(v, stats) for v in values]


def _fill_merges(meta: _SheetMeta) -> list[tuple[int, int, int, int]]:
    """The merged ranges that fill down: those spanning more than one row,
    and at most one at a time in any column (overlapping ranges are invalid
    in Excel; the first one wins)."""
    out = []
    reach: dict[int, int] = {}  # column -> last row covered so far
    for m in sorted((m for m in meta.merges if m[2] > m[0]), key=lambda m: (m[1], m[0])):
        r1, c1, r2, _c2 = m
        if r1 <= reach.get(c1, 0):
            continue
        reach[c1] = r2
        out.append(m)
    return out


def _filled_rows(ws, meta: _SheetMeta, stats: dict, max_rows: Optional[int]) -> Iterator[tuple[int, list, list]]:
    """``(row number, filled values, raw values)``: vertically merged blocks
    fill down their first column (the value Excel shows across the block)."""
    anchors: dict[tuple, Any] = {}
    by_start: dict[int, list] = {}
    for m in _fill_merges(meta):
        by_start.setdefault(m[0], []).append(m)
    active: list = []
    for rnum, raw in _raw_rows(ws, meta, stats, max_rows):
        values = list(raw)
        for m in by_start.get(rnum, ()):
            c = m[1] - 1
            anchors[m] = raw[c] if c < len(raw) else None
            active.append(m)
        if active:
            still = []
            for m in active:
                r1, c1, r2, _c2 = m
                if rnum > r2:
                    continue
                still.append(m)
                if rnum > r1 and c1 - 1 < MAX_COLS:
                    c = c1 - 1
                    if c >= len(values):
                        values.extend([None] * (c + 1 - len(values)))
                    if values[c] is None:
                        values[c] = anchors[m]
            active = still
        yield rnum, values, raw


def _is_blank(values: list) -> bool:
    return all(v is None for v in values)


def _is_text(v: Any) -> bool:
    if not isinstance(v, str):
        return False
    try:
        float(v.replace(",", ""))
        return False
    except ValueError:
        return True


def guess_header_row(rows: list[list]) -> int:
    """1-based index into ``rows`` of the likely header row, or 0 when the
    data seems to have none (every row mostly numbers).

    The header is the first row that is at least half as wide as the widest
    row and mostly text — so a title line above the table (one cell) or a
    units row below it doesn't win."""
    widths = [sum(v is not None for v in r) for r in rows]
    widest = max(widths, default=0)
    if widest == 0:
        return 1
    for i, r in enumerate(rows):
        filled = [v for v in r if v is not None]
        # At least half the table's width (and 2 cells, unless the table has
        # one column) — so a one-cell title line above the table doesn't win.
        if len(filled) < max(min(2, widest), math.ceil(widest / 2)):
            continue
        texts = sum(_is_text(v) for v in filled)
        if texts >= 0.8 * len(filled):
            # A text row with only numbers below it, or the first text row.
            return i + 1
    return 0


def _column_letter(i: int) -> str:
    from openpyxl.utils import get_column_letter

    return get_column_letter(i + 1)


def _header_names(header_raw: list, header_filled: list, width: int, header_row: int,
                  meta: _SheetMeta) -> list[str]:
    """Unique, non-blank column names for ``width`` columns."""
    names: list[str] = []
    horiz = [m for m in meta.merges if m[0] <= header_row <= m[2] and m[3] > m[1]]
    for c in range(width):
        v = header_filled[c] if c < len(header_filled) else None
        if v is None:
            # Inside a horizontally merged header: take the merged name.
            for r1, c1, _r2, c2 in horiz:
                if c1 - 1 < c <= c2 - 1:
                    anchor = header_filled[c1 - 1] if c1 - 1 < len(header_filled) else None
                    v = anchor
                    break
        name = " ".join(display(v).split()) if v is not None else ""
        names.append(name or f"Column {_column_letter(c)}")
    seen: dict[str, int] = {}
    out = []
    for n in names:
        key = n.lower()
        seen[key] = seen.get(key, 0) + 1
        out.append(n if seen[key] == 1 else f"{n} ({seen[key]})")
    return out


def _notes(stats: dict, meta: _SheetMeta, max_rows: int) -> list[str]:
    notes = []
    if meta.uncached_formulas:
        n = meta.uncached_formulas
        notes.append(
            f"{n} formula cell{'s' if n != 1 else ''} {'have' if n != 1 else 'has'} no saved result "
            "(the workbook was written by a program that doesn't calculate formulas) and "
            "read as blank. Open it in Excel, let it recalculate, save, and upload it again."
        )
    if stats.get("error_cells"):
        n = stats["error_cells"]
        notes.append(f"{n} cell{'s' if n != 1 else ''} with an Excel error (#DIV/0!, #N/A, …) read as blank.")
    if meta.merges_skipped:
        notes.append(
            f"The sheet has more than {MAX_MERGES:,} merged cell ranges, so merged cells weren't "
            "filled in: a value merged across several rows appears in its first row only.")
    if stats.get("truncated_rows"):
        notes.append(f"Only the first {max_rows:,} rows were read.")
    if stats.get("truncated_cols"):
        notes.append(f"Only the first {MAX_COLS} columns were read.")
    return notes


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def inspect(data: bytes, filename: str = "") -> dict:
    """The workbook's sheets, for a sheet / header-row picker::

        {"sheets": [{"name", "rows", "cols", "preview": [[str]], "row_numbers": [int],
                     "guessed_header_row", "notes": [str]}]}

    ``rows`` counts non-blank rows (capped at :data:`MAX_ROWS`); ``preview``
    is the first :data:`PREVIEW_ROWS` sheet rows (blank ones included, so
    ``row_numbers`` match Excel's); ``guessed_header_row`` is a sheet row
    number (0 = no header row).
    """
    wb = _open(data, filename)
    try:
        out = []
        for ws in _worksheets(wb):
            stats: dict = {}
            meta = _sheet_meta(ws)
            preview, raw_preview, numbers = [], [], []
            n_rows = width = 0
            for rnum, values, raw in _filled_rows(ws, meta, stats, MAX_ROWS):
                if not _is_blank(values):
                    n_rows += 1
                    last = max(i for i, v in enumerate(values) if v is not None) + 1
                    width = max(width, last)
                if rnum <= PREVIEW_ROWS:
                    preview.append(values)
                    raw_preview.append(raw)
                    numbers.append(rnum)
            width = min(width, MAX_COLS)
            guessed = guess_header_row(raw_preview)
            out.append({
                "name": ws.title,
                "rows": n_rows,
                "cols": width,
                "preview": [[display(v) for v in (r + [None] * width)[:width]] for r in preview],
                "row_numbers": numbers,
                "guessed_header_row": numbers[guessed - 1] if guessed else 0,
                "notes": _notes(stats, meta, MAX_ROWS),
            })
        if not out:
            raise ExcelError("The workbook has no worksheets.")
        return {"sheets": out}
    finally:
        wb.close()


@dataclass
class Table:
    """One sheet as a table. ``rows`` hold cleaned values (str / int / float /
    None), each as long as ``header``; ``row_numbers`` are the sheet rows."""

    sheet: str
    header: list[str]
    rows: list[list]
    row_numbers: list[int]
    header_row: int
    notes: list[str] = field(default_factory=list)


def read_table(data: bytes, sheet: Optional[str] = None, header_row: Optional[int] = None,
               filename: str = "", max_rows: Optional[int] = None) -> Table:
    """One sheet as ``header + rows``.

    ``sheet`` defaults to the first sheet; ``header_row`` is a 1-based sheet
    row number, ``0`` for "no header row" (columns named ``col 1``,
    ``col 2``, … as for a header-less CSV), or ``None`` to use the guess.
    Rows above the header and blank rows are skipped.
    """
    if max_rows is None:
        max_rows = MAX_ROWS
    wb = _open(data, filename)
    try:
        ws = _sheet(wb, sheet)
        meta = _sheet_meta(ws)
        stats: dict = {}
        if header_row is not None:
            try:
                header_row = int(header_row)
            except (TypeError, ValueError):
                raise ExcelError("The header row must be a row number.") from None
            if header_row < 0:
                raise ExcelError("The header row must be a row number.")
        header_filled: list = []
        header_raw: list = []
        rows: list[list] = []
        numbers: list[int] = []
        head: list[tuple[int, list, list]] = []
        limit = (header_row or 0) + max_rows if header_row is not None else None
        for rnum, values, raw in _filled_rows(ws, meta, stats, limit if limit is not None else max_rows + PREVIEW_ROWS):
            if header_row is None:
                # Guess from the first rows, then continue as if it were given.
                if rnum <= PREVIEW_ROWS:
                    head.append((rnum, values, raw))
                    continue
                header_row = _resolve_guess(head)
                header_filled, header_raw, rows, numbers = _split(head, header_row)
                head = []
            if rnum < header_row:
                continue
            if rnum == header_row:
                header_filled, header_raw = values, raw
                continue
            if _is_blank(values):
                continue
            if len(rows) >= max_rows:
                stats["truncated_rows"] = True
                break
            rows.append(values)
            numbers.append(rnum)
        if header_row is None:
            header_row = _resolve_guess(head)
            header_filled, header_raw, rows, numbers = _split(head, header_row)
        if len(rows) > max_rows:  # the guessed-header path buffers a few rows
            rows, numbers = rows[:max_rows], numbers[:max_rows]
            stats["truncated_rows"] = True

        width =max([len(header_filled) if header_row else 0] + [len(r) for r in rows] + [0])
        width = min(width, MAX_COLS)
        # Drop trailing columns with neither a header nor any data.
        while width and (header_filled[width - 1] if width - 1 < len(header_filled) else None) is None \
                and all((r[width - 1] if width - 1 < len(r) else None) is None for r in rows):
            width -= 1
        if header_row == 0:
            header = [f"col {i + 1}" for i in range(width)]
        else:
            header = _header_names(header_raw, header_filled, width, header_row, meta)
        rows = [(r + [None] * width)[:width] for r in rows]
        if not header or not rows:
            where = f"below row {header_row}" if header_row else ""
            raise ExcelError(
                f"Sheet “{ws.title}” has no data {where}".rstrip() + ". Pick the sheet and "
                "header row that hold the table."
            )
        return Table(sheet=ws.title, header=header, rows=rows, row_numbers=numbers,
                     header_row=header_row, notes=_notes(stats, meta, max_rows))
    finally:
        wb.close()


def _resolve_guess(head: list) -> int:
    idx = guess_header_row([raw for _, _, raw in head])
    return head[idx - 1][0] if idx and head else 0


def _split(head: list, header_row: int):
    header_filled, header_raw, rows, numbers = [], [], [], []
    for rnum, values, raw in head:
        if rnum < header_row:
            continue
        if rnum == header_row:
            header_filled, header_raw = values, raw
        elif not _is_blank(values):
            rows.append(values)
            numbers.append(rnum)
    return header_filled, header_raw, rows, numbers


def to_csv(table: Table) -> bytes:
    """The table as CSV bytes (what a CSV upload of the same data would be)."""
    buf = io.StringIO()
    writer = csv.writer(buf, lineterminator="\n")
    writer.writerow(table.header)
    for row in table.rows:
        writer.writerow([display(v) for v in row])
    return buf.getvalue().encode("utf-8")


def to_dataframe(table: Table):
    """The table as a pandas DataFrame, parsed exactly as its CSV would be."""
    import pandas as pd

    return pd.read_csv(io.BytesIO(to_csv(table)))


def csv_filename(filename: str, sheet: str, n_sheets: int = 1) -> str:
    """``Plant.xlsx`` -> ``Plant.csv`` (``Plant - Sheet2.csv`` when the
    workbook has several sheets)."""
    stem = (filename or "workbook").rsplit("/", 1)[-1]
    if "." in stem:
        stem = stem.rsplit(".", 1)[0]
    stem = stem or "workbook"
    return f"{stem} - {sheet}.csv" if n_sheets > 1 else f"{stem}.csv"


# ---------------------------------------------------------------------------
# Column-mapping guesses (shared by every importer)
# ---------------------------------------------------------------------------


def norm(text: Any) -> str:
    """Lower-case words separated by single spaces ("Non-Operational" ->
    "non operational", "MTTF (h)" -> "mttf h"). Greek letters are kept, so a
    "β" header matches a "β" synonym."""
    return " ".join(re.sub(r"[^0-9a-zα-ω]+", " ", str(text or "").lower()).split())


def has_words(text: str, phrase: str) -> bool:
    """Whether normalised ``phrase`` appears in normalised ``text`` as whole words."""
    return bool(phrase) and f" {phrase} " in f" {text} "


def guess_mapping(header: list[str], fields: list[dict]) -> dict[str, str]:
    """Field id -> column name, matching headers against each field's label
    and ``synonyms``: an exact match beats a header that merely contains a
    synonym ("Failure mode (cause)"), longer synonyms beat shorter ones, and
    each column and field is used once."""
    scored = []
    for order, f in enumerate(fields):
        syns = [norm(s) for s in [f.get("label", ""), *f.get("synonyms", [])]]
        for ci, col in enumerate(header):
            h = norm(col)
            best = 0
            for s in syns:
                if not s:
                    continue
                if h == s:
                    best = max(best, 1000 + len(s))
                elif len(s) > 2 and has_words(h, s):
                    best = max(best, 500 + len(s))
            if best:
                scored.append((-best, order, ci, f["id"], col))
    scored.sort()
    out: dict[str, str] = {}
    used: set[str] = set()
    for _score, _order, _ci, fid, col in scored:
        if fid in out or col in used:
            continue
        out[fid] = col
        used.add(col)
    return out
