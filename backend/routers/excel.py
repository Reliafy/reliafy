"""Excel (.xlsx) upload helpers shared by every spreadsheet import.

The frontend's sheet picker calls :func:`inspect_workbook` to list sheets and
guess the header row, then either :func:`workbook_table` (to map columns for
an RCM worksheet or an RBD template) or :func:`workbook_csv` (life data: the
chosen sheet becomes a CSV that goes down the existing CSV path unchanged).
Nothing is stored.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, File, Form, UploadFile
from fastapi.responses import JSONResponse, Response

from backend.auth import get_current_user
from backend.services import excel, import_guard

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/excel")

# Rows returned for a column-mapping preview.
TABLE_PREVIEW_ROWS = 200


def read_upload(file: UploadFile) -> bytes:
    """The upload's bytes, reading at most one byte past the size cap (so an
    oversized file is refused without buffering all of it)."""
    return file.file.read(excel.MAX_FILE_BYTES + 1)


def guarded(uid: str, fn, *args, **kwargs):
    """Run a file parser under the user's import guard (one at a time, within
    the time budget — see :mod:`backend.services.import_guard`)."""
    from backend.db import get_db

    with import_guard.guard(get_db(), uid):
        return fn(*args, **kwargs)


def guard_error(exc: Exception) -> JSONResponse | None:
    """The response for the import guard's refusals (None for anything else)."""
    if isinstance(exc, import_guard.ImportBusy):
        return JSONResponse(status_code=429, content={"detail": str(exc)}, headers={"Retry-After": "15"})
    if isinstance(exc, import_guard.ImportBudgetExceeded):
        return JSONResponse(status_code=422, content={"detail": str(exc)})
    return None


def excel_error(exc: Exception, what: str, data: bytes, filename: str) -> JSONResponse:
    """422 for a workbook that can't be read — never a 500 on untrusted input."""
    refused = guard_error(exc)
    if refused is not None:
        return refused
    if isinstance(exc, excel.ExcelError):
        return JSONResponse(status_code=422, content={"detail": str(exc)})
    logger.exception("Excel %s failed: bytes=%d", what, len(data))
    return JSONResponse(
        status_code=422,
        content={"detail": "Couldn't read this workbook — it may be damaged. Try opening it in Excel and saving it again."},
    )


def header_row_param(value: str | None) -> int | None:
    """Form value -> header row: blank = guess, ``0`` = no header row."""
    if value is None or str(value).strip() == "":
        return None
    try:
        return int(str(value).strip())
    except ValueError:
        raise excel.ExcelError("The header row must be a row number.") from None


@router.post("/inspect")
def inspect_workbook(
    file: UploadFile = File(...),
    user: dict = Depends(get_current_user),
) -> JSONResponse:
    """The workbook's sheets with a preview and a guessed header row each."""
    data = read_upload(file)
    try:
        return JSONResponse(content=guarded(user["uid"], excel.inspect, data, file.filename or ""))
    except Exception as exc:
        return excel_error(exc, "inspect", data, file.filename or "")


def target_fields(target: str) -> list[dict] | None:
    """The column-mapping fields of an import target (one list, shared by the
    server-side importers and the frontend's column mapper)."""
    if target == "rcm":
        from backend.services import rcm_import

        return rcm_import.FIELDS
    if target in ("rbd_blocks", "rbd_connections"):
        from backend.services.rbd_import import excel as rbd_excel

        return rbd_excel.BLOCK_FIELDS if target == "rbd_blocks" else rbd_excel.CONNECTION_FIELDS
    return None


@router.post("/table")
def workbook_table(
    file: UploadFile = File(...),
    sheet: str | None = Form(default=None),
    header_row: str | None = Form(default=None),
    target: str | None = Form(default=None),
    user: dict = Depends(get_current_user),
) -> JSONResponse:
    """One sheet's header and first rows (as text) for a column mapper.

    With ``target`` (``rcm``, ``rbd_blocks``, ``rbd_connections``) the
    response adds that importer's ``fields`` and a ``guess`` at the mapping
    from the header names (and, for ``rcm``, the columns suggested for the
    notes)."""
    data = read_upload(file)
    try:
        table = guarded(user["uid"], excel.read_table, data, sheet, header_row_param(header_row),
                        file.filename or "")
    except Exception as exc:
        return excel_error(exc, "table", data, file.filename or "")
    extra: dict = {}
    fields = target_fields(target or "")
    if fields is not None:
        guess = excel.guess_mapping(table.header, fields)
        extra = {"fields": fields, "guess": guess}
        if target == "rcm":
            from backend.services import rcm_import

            extra["extra_columns"] = rcm_import.default_extra_columns(table.header, guess)
    return JSONResponse(content={
        **extra,
        "sheet": table.sheet,
        "header_row": table.header_row,
        "columns": table.header,
        "rows": [[excel.display(v) for v in r] for r in table.rows[:TABLE_PREVIEW_ROWS]],
        "row_numbers": table.row_numbers[:TABLE_PREVIEW_ROWS],
        "n_rows": len(table.rows),
        "notes": table.notes,
    })


@router.post("/csv")
def workbook_csv(
    file: UploadFile = File(...),
    sheet: str | None = Form(default=None),
    header_row: str | None = Form(default=None),
    user: dict = Depends(get_current_user),
) -> Response:
    """One sheet as CSV text — so a workbook can go wherever a CSV does."""
    data = read_upload(file)
    try:
        table = guarded(user["uid"], excel.read_table, data, sheet, header_row_param(header_row),
                        file.filename or "")
    except Exception as exc:
        return excel_error(exc, "csv", data, file.filename or "")
    name = excel.csv_filename(file.filename or "", table.sheet)
    headers = {"Cache-Control": "no-store", "X-Excel-Rows": str(len(table.rows))}
    if table.notes:
        # Plain ASCII in a header: the notes are fixed English text.
        headers["X-Excel-Notes"] = " | ".join(table.notes).encode("ascii", "replace").decode()
    return Response(
        content=excel.to_csv(table),
        media_type="text/csv; charset=utf-8",
        headers={**headers, "Content-Disposition": f'attachment; filename="{_ascii(name)}"'},
    )


def _ascii(name: str) -> str:
    return "".join(ch if 32 <= ord(ch) < 127 and ch not in '"\\' else "_" for ch in name)
