"""An FMEA / RCM worksheet (Excel or CSV) added to one position's RCM.

The sheet is read and mapped exactly as the RCM study import reads it
(:func:`backend.services.rcm_import.build_tree`: one row per failure mode,
function and functional failure carried down, consequence and decision-type
cells mapped onto Reliafy's categories), then added to the position through
the service's own methods, so every change is an ordinary event:
``add_function`` › ``add_functional_failure`` › ``add_failure_mode`` (under
its functional failure), ``update_failure_mode`` (effects, notes) and
``decide_failure_mode`` (consequence and decision; a scheduled decision with
an interval gets its task, as when it's decided by hand).

Only ever adds. Every function and functional failure in the sheet is on the
position afterwards: one already there with the same text (case and spacing
aside; a functional failure under the same function) is used as it is. A
failure mode already on the position is left as it is, wherever it is (a
position's failure modes are unique by text). Nothing on the position is
changed or removed, so importing the same sheet again adds nothing.

As every maintenance import: every row is checked first (:func:`plan`), and
with any error nothing is written; ``dry_run`` only reports what would be
added.
"""

from __future__ import annotations

from backend.maintenance.service import (
    BASIS_TEXT, LONG_TEXT, MAX_EVENTS, MAX_TASKS, SCHEDULED_OUTCOMES, SHORT_TEXT, Invalid, LimitReached, Maintenance,
    _basis_text, _interval, _norm_unit, _same_text, shortened,
)
from backend.services import excel, rcm_import

MAX_MODES = 500  # failure modes one import adds (each is a few events; a big FMEA goes in by system)
MAX_ROWS = 5000  # rows read from the sheet
SHOWN = 50  # errors, functions in the preview, rows listed in a message


def read_table(data: bytes, filename: str = "", sheet: str | None = None, header_row: int | None = None):
    """The sheet (an Excel sheet, or a CSV file) as an ``excel.Table``. Raises
    ``excel.ExcelError`` (user-facing) when it can't be read, or is too long."""
    if excel.is_excel(data, filename):
        table = excel.read_table(data, sheet, header_row, filename, max_rows=MAX_ROWS + 1)
    else:
        table = excel.read_csv(data, filename, max_rows=MAX_ROWS + 1)
    if len(table.rows) > MAX_ROWS:
        raise excel.ExcelError(f"The sheet has more than {MAX_ROWS:,} rows. Split it into smaller sheets, or "
                               "import one system at a time.")
    return table


def default_options(table) -> dict:
    """The column mapping guessed from the header, with the FMEA scoring columns
    kept in each mode's notes (what the import modal starts from)."""
    guess = excel.guess_mapping(table.header, rcm_import.FIELDS)
    return {"mapping": guess, "extra_columns": rcm_import.default_extra_columns(table.header, guess)}


def _rows(rows: list[int]) -> str:
    listed = ", ".join(str(n) for n in rows[:8])
    return f"row{'s' if len(rows) != 1 else ''} {listed}{' …' if len(rows) > 8 else ''}"


def _plural(n: int, one: str, many: str | None = None) -> str:
    return f"{n:,} {one if n == 1 else (many or one + 's')}"


def plan(m: Maintenance, position_id: str, table, options: dict | None) -> dict:
    """What the sheet adds to the position (nothing is written). Raises
    NotFound for a position that isn't in this workspace, Invalid for a
    mapping or sheet that can't be imported at all; problems with single rows
    are in ``errors`` (any error: nothing may be written) and ``warnings``."""
    position = m._get(position_id, "Position")
    if position.get("retired"):
        raise Invalid(f"{position['name']} has been retired: pick a position that's still in use.")
    try:
        built = rcm_import.build_tree(table.header, table.rows, options or {}, table.row_numbers, keep_rows=True)
    except rcm_import.RcmImportError as err:
        raise Invalid(str(err)) from None

    errors: list[str] = []
    warnings: list[str] = list(built["warnings"])
    here = {" ".join(fm["text"].lower().split()): fm for fm in m._modes_on(position_id)}
    existing_fns = m._functions_of(position_id)
    seen: dict[str, int] = {}  # failure mode text -> the row it's first added from
    already: list[int] = []  # rows whose failure mode is on the position already
    repeated: list[int] = []
    no_unit: list[int] = []
    shortened_rows: list[int] = []
    standards_kept: list[str] = []
    workings_kept: list[str] = []
    functions: list[dict] = []
    counts = {"functions": 0, "failures": 0, "modes": 0, "decisions": 0, "tasks": 0,
              "functions_existing": 0, "failures_existing": 0, "modes_existing": 0}

    for fn in built["functions"]:
        match = next((f for f in existing_fns if _same_text(f["text"], fn["text"])), None)
        if match and fn.get("standard") and not _same_text(match.get("standard"), fn["standard"]):
            standards_kept.append(match["text"])
        basis = fn.get("standard_basis") or ""
        if len(basis) > BASIS_TEXT:
            errors.append(f"“{fn['text'][:60]}”: the standard working is {len(basis):,} characters; at most "
                          f"{BASIS_TEXT:,}. Shorten it in the sheet, or attach it as a PDF after the import.")
            basis = ""
        elif basis:
            try:
                basis = _basis_text(basis)
            except Invalid as err:
                errors.append(f"“{fn['text'][:60]}”: {err}")
                basis = ""
        if match and basis and not _same_text(match.get("standard_basis"), basis):
            workings_kept.append(match["text"])
        fn_plan = {"text": fn["text"], "standard": fn.get("standard") or "", "standard_basis": basis,
                   "id": match and match["id"], "failures": []}
        existing_ffs = m._failures_of(match["id"]) if match else []
        for ff in fn["failures"]:
            ff_match = next((f for f in existing_ffs if _same_text(f["text"], ff["text"])), None)
            ff_plan = {"text": ff["text"], "id": ff_match and ff_match["id"], "modes": []}
            for mode in ff["modes"]:
                row, text = mode["row"], mode["text"]
                full = ""
                if len(text) > SHORT_TEXT:
                    text, _ = shortened(text, SHORT_TEXT)
                    full = mode["text"]
                    shortened_rows.append(row)
                key = " ".join(text.lower().split())
                if key in here:
                    already.append(row)
                    continue
                if key in seen:
                    repeated.append(row)
                    continue
                seen[key] = row
                notes = mode.get("notes") or ""
                if full:
                    notes = f"Failure mode in full: {full}" + (f"\n{notes}" if notes else "")
                notes, cut = shortened(notes, LONG_TEXT) if len(notes) > LONG_TEXT else (notes, False)
                decision = mode.get("decision")
                task = False
                if decision and decision["outcome"] in SCHEDULED_OUTCOMES and decision.get("interval"):
                    unit = _norm_unit(decision.get("interval_unit")) or "days"
                    if not decision.get("interval_unit"):
                        no_unit.append(row)
                    try:
                        _interval(decision["interval"], unit, "interval")
                    except Invalid as err:
                        errors.append(f"Row {row}: {err} Change it in the sheet and try again.")
                    task = True
                ff_plan["modes"].append({
                    "row": row, "text": text, "effects": mode.get("effects") or "", "notes": notes,
                    "consequence": mode.get("consequence"), "decision": decision, "task": task,
                })
                counts["modes"] += 1
                counts["decisions"] += bool(decision)
                counts["tasks"] += task
            if not ff_match and not ff_plan["modes"] and ff["text"] == rcm_import.IMPORTED:
                continue  # a stand-in name for modes with none above them, and they're all here already
            counts["failures_existing" if ff_match else "failures"] += 1
            fn_plan["failures"].append(ff_plan)
        if not match and not fn_plan["failures"] and fn["text"] == rcm_import.IMPORTED:
            continue
        counts["functions_existing" if match else "functions"] += 1
        functions.append(fn_plan)
    counts["modes_existing"] = len(already)
    if counts["modes"] > MAX_MODES:
        raise Invalid(f"The sheet would add {counts['modes']:,} failure modes; one import adds at most {MAX_MODES:,} "
                      "to a position. Split the sheet (by system or function) and import each part.")

    name = position["name"]
    if already:
        warnings.append(f"{_plural(len(already), 'failure mode is', 'failure modes are')} on {name} already, so "
                        f"{'it was' if len(already) == 1 else 'they were'} left as {'it is' if len(already) == 1 else 'they are'} "
                        f"({_rows(already)}).")
    if repeated:
        warnings.append(f"{_plural(len(repeated), 'row repeats', 'rows repeat')} a failure mode from earlier in the "
                        f"sheet; only the first is added ({_rows(repeated)}).")
    if shortened_rows:
        warnings.append(f"{_plural(len(shortened_rows), 'failure mode is', 'failure modes are')} over {SHORT_TEXT} "
                        f"characters, so the name was shortened and the full text kept in its notes "
                        f"({_rows(shortened_rows)}).")
    if no_unit:
        warnings.append(f"{_plural(len(no_unit), 'interval has', 'intervals have')} no unit, so "
                        f"{'its task is' if len(no_unit) == 1 else 'their tasks are'} in days ({_rows(no_unit)}). "
                        "Map an Interval unit column to say otherwise.")
    for text in standards_kept[:5]:
        warnings.append(f"“{text[:80]}” is on {name} already with another performance standard; it was left as it is.")
    for text in workings_kept[:5]:
        warnings.append(f"“{text[:80]}” is on {name} already with another working behind its standard; it was left as it is.")

    if m.limited:
        events = counts["functions"] + counts["failures"] + 4 * counts["modes"] + counts["tasks"]
        if m.s.event_count(m.org) + events > MAX_EVENTS:
            raise LimitReached(f"This maintenance workspace can't take {events:,} more recorded changes "
                               f"(its limit is {MAX_EVENTS:,}).")
        m._quota("Task", MAX_TASKS, adding=counts["tasks"])
    return {"position": {"id": position_id, "name": name}, "functions": functions, "counts": counts,
            "built": built, "errors": errors, "warnings": warnings}


def _write(m: Maintenance, position_id: str, functions: list[dict]) -> None:
    for fn in functions:
        fn_id = fn["id"] or m.add_function(position_id, fn["text"], fn["standard"], standard_basis=fn["standard_basis"])["id"]
        for ff in fn["failures"]:
            ff_id = ff["id"] or m.add_functional_failure(fn_id, ff["text"])["id"]
            for mode in ff["modes"]:
                mode_id = m.add_failure_mode(position_id, mode["text"], functional_failure_id=ff_id)["id"]
                if mode["effects"] or mode["notes"]:
                    m.update_failure_mode(mode_id, effects=mode["effects"] or None, notes=mode["notes"] or None)
                if mode["consequence"] or mode["decision"]:
                    m.decide_failure_mode(mode_id, mode["consequence"] or None,
                                          mode["decision"] if mode["decision"] else ...)


def run(m: Maintenance, position_id: str, table, options: dict | None, dry_run: bool = True) -> dict:
    """Add the sheet to the position's RCM (see :func:`plan`). With any error,
    or ``dry_run``, nothing is written. The answer is the same either way:
    what is (or would be) added, what's there already, and why rows were
    skipped."""
    p = plan(m, position_id, table, options)
    write = not dry_run and not p["errors"]
    if write:
        _write(m, position_id, p["functions"])
    built = p["built"]
    counts = {**p["counts"], "rows": len(table.rows), "skipped_rows": built["counts"]["skipped_rows"],
              "errors": len(p["errors"])}
    preview = [{
        "text": fn["text"], "new": not fn["id"],
        "failures": [{"text": ff["text"], "new": not ff["id"], "modes": len(ff["modes"])} for ff in fn["failures"]],
    } for fn in p["functions"][:SHOWN]]
    out = {
        "dry_run": not write, "ok": not p["errors"], "position": p["position"],
        "sheet": table.sheet, "header_row": table.header_row,
        "counts": counts, "functions": preview,
        "errors": p["errors"][:SHOWN], "warnings": p["warnings"], "notes": table.notes,
        "values": built["values"], "outcome_source": built["outcome_source"],
    }
    return out
