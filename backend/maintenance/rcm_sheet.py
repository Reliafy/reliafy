"""An FMEA / RCM worksheet (Excel or CSV) added to one position's RCM.

The sheet is read and mapped by :func:`backend.services.rcm_import.build_tree`
(one row per failure mode,
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

A function may have several performance standards: every distinct standard
cell under it is one (a row with the function and a standard alone lists one;
an existing function's old single text becomes the first), and, when the
function has more than one, a functional failure's own row names the one it
breaches. The export writes them that way. A failure mode may have several tasks: a second row for the same failure mode
(the same text, under the same function and functional failure) whose task
differs is that mode's next task, so the export's one-row-per-task layout
reads back. A task named in the sheet that is on the position already (the
same name, case and spacing aside) is linked, not made again: one task then
serves several modes. A shared task keeps its own interval: a row that names
it with another interval is a row error.

As every maintenance import: every row is checked first (:func:`plan`), and
with any error nothing is written; ``dry_run`` only reports what would be
added.
"""

from __future__ import annotations

import re

from backend.maintenance.service import (
    BASIS_TEXT, LONG_TEXT, MAX_CAUSES, MAX_EVENTS, MAX_TASKS, SCHEDULED_OUTCOMES, SHORT_TEXT, Invalid, LimitReached,
    Maintenance, _basis_text, _interval, _norm_unit, _same_text, shortened,
)
from backend.services import excel, rcm_import

MAX_MODES = 500  # failure modes one import adds (each is a few events; a big FMEA goes in by system)
MAX_LINKS = 500  # links between functional failures one import adds
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


def counts_new(links: list[dict]) -> int:
    return sum(1 for k in links if not k["existing"])


def _rows(rows: list[int]) -> str:
    listed = ", ".join(str(n) for n in rows[:8])
    return f"row{'s' if len(rows) != 1 else ''} {listed}{' …' if len(rows) > 8 else ''}"


def _plural(n: int, one: str, many: str | None = None) -> str:
    return f"{n:,} {one if n == 1 else (many or one + 's')}"


_SPLIT_CAUSES = re.compile(r"[;\n\r]+")
_SPLIT_PLACE = re.compile(r"\s*[›>|]\s*")


def _norm(text) -> str:
    return " ".join(str(text or "").lower().split())


class _Places:
    """The positions inside the one a sheet is imported onto, found by name or
    tag, for the "Caused by (below)" cells."""

    def __init__(self, m: Maintenance, target_id: str):
        self.m, self.target_id = m, target_id
        kids: dict[str, list[str]] = {}
        for src, dst in m.s.pairs(m.org, "PART_OF"):
            kids.setdefault(dst, []).append(src)
        self.nodes = {p["id"]: p for p in m.s.nodes(m.org, "Position") if not p.get("retired")}
        self.inside: set[str] = set()
        stack = list(kids.get(target_id, []))
        while stack:
            at = stack.pop()
            if at not in self.inside:
                self.inside.add(at)
                stack.extend(kids.get(at, []))

    def find(self, name: str) -> tuple[dict | None, str | None]:
        """The one position inside the target with that name or tag, or why not."""
        key = _norm(name)
        named = [p for p in self.nodes.values() if key in (_norm(p["name"]), _norm(p.get("tag")))]
        here = [p for p in named if p["id"] in self.inside]
        if len(here) == 1:
            return here[0], None
        if len(here) > 1:
            tags = " and ".join(f"{p['name']} ({p.get('tag') or 'no tag'})" for p in here[:3])
            return None, f"two positions inside the target are called “{name}”: {tags}. Put the tag in the cell"
        if any(p["id"] == self.target_id for p in named):
            return None, f"“{name}” is the position this sheet is imported onto: a cause is on a position inside it"
        if named:
            return None, f"“{name}” isn't inside {self.nodes[self.target_id]['name']}"
        return None, f"there is no position “{name}” inside {self.nodes[self.target_id]['name']}"


def _resolve_causes(m: Maintenance, places: _Places, ff_match: dict | None, causes: list[dict],
                    errors: list[str]) -> list[dict]:
    """The links one functional failure's "Caused by (below)" cells name: each
    ``{row, cause_id, position, text, existing}``. A cell that can't be resolved
    is a row error (nothing is written); the lower failure must be there already."""
    out: list[dict] = []
    linked = {c["id"] for c in m.s.out(m.org, ff_match["id"], "RESULTS_FROM")} if ff_match else set()
    for cell in causes:
        for part in _SPLIT_CAUSES.split(cell["text"]):
            part = part.strip()
            if not part:
                continue
            row = cell["row"]
            bits = _SPLIT_PLACE.split(part, maxsplit=1)
            if len(bits) != 2 or not bits[0].strip() or not bits[1].strip():
                errors.append(f"Row {row}: “{shortened(part, 80)[0]}” should read Position › Functional failure.")
                continue
            place, text = bits[0].strip(), bits[1].strip()
            pos, why = places.find(place)
            if pos is None:
                errors.append(f"Row {row}: {why}.")
                continue
            found = next((f for fn in m._functions_of(pos["id"]) for f in m._failures_of(fn["id"])
                          if _same_text(f["text"], text)), None)
            if found is None:
                errors.append(f"Row {row}: no functional failure ‘{shortened(text, 80)[0]}’ on {pos['name']} yet. "
                              "Import that position's rows first, or correct the cell.")
                continue
            if any(o["cause_id"] == found["id"] for o in out):
                continue
            out.append({"row": row, "cause_id": found["id"], "position": pos["name"], "text": found["text"],
                        "existing": found["id"] in linked})
    return out


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
    seen: dict[str, dict] = {}  # failure mode text -> the mode planned from its first row
    # Tasks by name: on the position already, and (as the sheet is read) the ones
    # it will make, so a name used on several rows is one task serving them all.
    live_tasks = {_norm(t["name"]): {"id": t["id"], "name": t["name"], "interval": t["interval"], "unit": t["unit"]}
                  for t in m._tasks_on(position_id)}
    sheet_tasks: dict[str, dict] = {}
    already: list[int] = []  # rows whose failure mode is on the position already
    repeated: list[int] = []
    no_unit: list[int] = []
    shortened_rows: list[int] = []
    standards_kept: list[str] = []
    workings_kept: list[str] = []
    functions: list[dict] = []
    counts = {"functions": 0, "failures": 0, "modes": 0, "decisions": 0, "tasks": 0, "tasks_linked": 0, "standards": 0,
              "functions_existing": 0, "failures_existing": 0, "modes_existing": 0, "links": 0, "links_existing": 0}
    places = _Places(m, position_id)

    for fn in built["functions"]:
        match = next((f for f in existing_fns if _same_text(f["text"], fn["text"])), None)
        # Its standards: the sheet's list, less the ones the function has (its old
        # single text counts as one, and becomes the list's first when more join it).
        listed = fn.get("standards") or ([fn["standard"]] if fn.get("standard") else [])
        have = [st["text"] for st in m._standards_of(match["id"])] if match else []
        if match and not have and match.get("standard"):
            have = [match["standard"]]
        new_standards = [x for x in listed if not any(_same_text(x, h) for h in have)]
        if match and new_standards and have:
            standards_kept.append(match["text"])
        # A new function with one standard keeps the one text (no list yet).
        counts["standards"] += len(new_standards) if (match or len(listed) > 1) else 0
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
                   "id": match and match["id"], "failures": [], "standards": new_standards,
                   # Every standard the sheet lists (to name the one a failure breaches).
                   "standards_listed": listed}
        existing_ffs = m._failures_of(match["id"]) if match else []
        for ff in fn["failures"]:
            ff_match = next((f for f in existing_ffs if _same_text(f["text"], ff["text"])), None)
            ff_plan = {"text": ff["text"], "id": ff_match and ff_match["id"], "modes": [], "links": [],
                       "breaches": ff.get("breaches") or ""}
            if ff.get("causes"):
                ff_plan["links"] = _resolve_causes(m, places, ff_match, ff["causes"], errors)
                counts["links_existing"] += sum(1 for k in ff_plan["links"] if k["existing"])
                counts["links"] += sum(1 for k in ff_plan["links"] if not k["existing"])
                have = len(m.s.out(m.org, ff_match["id"], "RESULTS_FROM")) if ff_match else 0
                if have + counts_new(ff_plan["links"]) > MAX_CAUSES:
                    errors.append(f"“{shortened(ff['text'], 80)[0]}” would have more than {MAX_CAUSES} causes below it.")
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
                decision = mode.get("decision")
                if key in seen:
                    # The same failure mode again: another task for it (the export
                    # writes one row per task), or a repeat to pass over.
                    extra = _extra_task(decision, seen[key], live_tasks, sheet_tasks, row, errors)
                    if extra is None:
                        repeated.append(row)
                    else:
                        seen[key]["extra_tasks"].append(extra)
                        counts["tasks_linked" if extra["shared"] else "tasks"] += 1
                    continue
                notes = mode.get("notes") or ""
                if full:
                    notes = f"Failure mode in full: {full}" + (f"\n{notes}" if notes else "")
                notes, cut = shortened(notes, LONG_TEXT) if len(notes) > LONG_TEXT else (notes, False)
                task = False
                shared = False  # a task on the position already (or an earlier row's), linked instead of made
                if decision and decision["outcome"] in SCHEDULED_OUTCOMES and decision.get("interval"):
                    unit = _norm_unit(decision.get("interval_unit")) or "days"
                    if not decision.get("interval_unit"):
                        no_unit.append(row)
                    try:
                        _interval(decision["interval"], unit, "interval")
                    except Invalid as err:
                        errors.append(f"Row {row}: {err} Change it in the sheet and try again.")
                    task = True
                    shared = _shared_task(decision, live_tasks, sheet_tasks, row, errors)
                planned = {
                    "row": row, "text": text, "effects": mode.get("effects") or "", "notes": notes,
                    "consequence": mode.get("consequence"), "decision": decision, "task": task,
                    "shared": shared, "extra_tasks": [],
                }
                seen[key] = planned
                ff_plan["modes"].append(planned)
                counts["modes"] += 1
                counts["decisions"] += bool(decision)
                counts["tasks" if not shared else "tasks_linked"] += task
            if not ff_match and not ff_plan["modes"] and not ff_plan["links"] and ff["text"] == rcm_import.IMPORTED:
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

    if counts["links"] > MAX_LINKS:
        raise Invalid(f"The sheet would add {counts['links']:,} links between functional failures; one import adds "
                      f"at most {MAX_LINKS:,}. Split the sheet and import each part.")

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
        warnings.append(f"“{text[:80]}” is on {name} already with a performance standard; the sheet's "
                        "went beside it, in its list of standards.")
    for text in workings_kept[:5]:
        warnings.append(f"“{text[:80]}” is on {name} already with another working behind its standard; it was left as it is.")

    if m.limited:
        events = counts["functions"] + counts["failures"] + 4 * counts["modes"] + counts["tasks"] + counts["links"] \
            + counts["standards"]
        if m.s.event_count(m.org) + events > MAX_EVENTS:
            raise LimitReached(f"This maintenance workspace can't take {events:,} more recorded changes "
                               f"(its limit is {MAX_EVENTS:,}).")
        m._quota("Task", MAX_TASKS, adding=counts["tasks"])
    return {"position": {"id": position_id, "name": name}, "functions": functions, "counts": counts,
            "built": built, "errors": errors, "warnings": warnings}


def _shared_task(decision: dict, live_tasks: dict, sheet_tasks: dict, row: int, errors: list[str]) -> bool:
    """Whether a scheduled decision's task is one the position has already, or
    one an earlier row of the sheet makes (then it's linked, not made again).
    Such a task keeps its interval: a row asking for another is a row error."""
    name = str(decision.get("task") or "").strip()
    if not name:
        return False
    unit = _norm_unit(decision.get("interval_unit")) or "days"
    try:
        interval = _interval(decision["interval"], unit, "interval")
    except Invalid:
        return False  # said already
    key = _norm(name)
    task = live_tasks.get(key) or sheet_tasks.get(key)
    if task is None:
        sheet_tasks[key] = {"name": name, "interval": interval, "unit": unit, "row": row}
        return False
    if (interval, unit) != (task["interval"], task["unit"]):
        where = "a task on the position already" if key in live_tasks else f"the task row {task['row']} makes"
        errors.append(f"Row {row}: “{task['name']}” is {where}, every {task['interval']:g} {task['unit']}; this "
                      f"row says every {interval:g} {unit}. Use the task's interval (it is shared), or give this "
                      "task another name.")
    return True


def _extra_task(decision, planned: dict, live_tasks: dict, sheet_tasks: dict, row: int,
                errors: list[str]) -> dict | None:
    """A repeat row's task for a failure mode planned already: its next task
    ({name, interval, unit, outcome, shared}), or None when the row brings no
    new task (the same task again, or none)."""
    if not decision or decision["outcome"] not in SCHEDULED_OUTCOMES or not decision.get("interval"):
        return None
    name = str(decision.get("task") or "").strip()
    first = planned["decision"] or {}
    have = [_norm(first.get("task"))] + [_norm(x["name"]) for x in planned["extra_tasks"]]
    if not name or _norm(name) in have:
        return None
    unit = _norm_unit(decision.get("interval_unit")) or "days"
    try:
        interval = _interval(decision["interval"], unit, "interval")
    except Invalid as err:
        errors.append(f"Row {row}: {err} Change it in the sheet and try again.")
        return None
    shared = _shared_task(decision, live_tasks, sheet_tasks, row, errors)
    return {"name": shortened(name, SHORT_TEXT)[0], "interval": interval, "unit": unit,
            "outcome": decision["outcome"], "shared": shared}


def _write(m: Maintenance, position_id: str, functions: list[dict]) -> None:
    def task_named(name) -> str | None:
        """A live task on the position with that name (one the sheet made just now too)."""
        key = _norm(name)
        return next((t["id"] for t in m._tasks_on(position_id) if _norm(t["name"]) == key), None) if key else None

    for fn in functions:
        # A new function with one standard keeps the one text; with several, the list.
        one = fn["standard"] if len(fn.get("standards_listed") or []) <= 1 else ""
        fn_id = fn["id"] or m.add_function(position_id, fn["text"], one, standard_basis=fn["standard_basis"])["id"]
        for text in fn.get("standards") or []:
            if fn["id"] or len(fn.get("standards_listed") or []) > 1:
                m.add_standard(fn_id, text)
        by_text = {_norm(st["text"]): st["id"] for st in m._standards_of(fn_id)}
        for ff in fn["failures"]:
            breach = by_text.get(_norm(ff.get("breaches")))
            if ff["id"]:
                ff_id = ff["id"]
                if breach and not [st for st in m.s.out(m.org, ff_id, "BREACHES") if not st.get("removed")]:
                    m.update_functional_failure(ff_id, standard_id=breach)
            else:
                ff_id = m.add_functional_failure(fn_id, ff["text"], standard_id=breach)["id"]
            for mode in ff["modes"]:
                mode_id = m.add_failure_mode(position_id, mode["text"], functional_failure_id=ff_id)["id"]
                if mode["effects"] or mode["notes"]:
                    m.update_failure_mode(mode_id, effects=mode["effects"] or None, notes=mode["notes"] or None)
                if mode["consequence"] or mode["decision"]:
                    decision = mode["decision"]
                    # A task the position has (or an earlier row made) is the decision's, linked.
                    shared = task_named(decision.get("task")) if mode.get("shared") and decision else None
                    m.decide_failure_mode(mode_id, mode["consequence"] or None, decision if decision else ...,
                                          task_id=shared)
                for extra in mode.get("extra_tasks") or []:
                    have = task_named(extra["name"])
                    if have:
                        m.link_task(have, mode_id)
                    else:
                        m.add_mode_task(mode_id, extra["name"], extra["interval"], extra["unit"], extra["outcome"])
            for link in ff["links"]:
                if not link["existing"]:
                    m.link_cause(ff_id, link["cause_id"])


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
