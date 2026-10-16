"""A bill of materials in, from CSV or Excel: one row per parent -> child line (#435).

Columns are matched by their names, as the other spreadsheet imports match them
(``excel.guess_mapping``): the parent's part number (also "NHA", "Next higher
assembly", "Parent PN", "Assembly"), the part number of what goes in it ("PN",
"Part no", "Component"), the quantity in one parent ("Qty"), its nomenclature
("Description", "Name"), its indenture level ("Level"), its manufacturer ("Mfr",
"Make") and a reference ("Ref", "Ref des", "Find number"). Only the part number is
needed: a row with no parent just describes a part (the top assembly, say).

An indented BOM (the usual export from PLM, ERP and LSA tools) has no parent column: its
rows come in tree order with a level on each ("Level", "Lvl", "Indenture", "BOM level",
"LCN"). Which kind of level it is comes from the column's name and values (``detect``),
and the result says which:
  - level numbers (0, 1, 2... or 1, 2, 3...; the smallest is the top): a row's parent is
    the nearest row above it one level up;
  - dotted levels (".1", "..2"): the same, by the number after the dots;
  - outline numbers ("1", "1.1", "1.1.2"): the parent is the number without its last part,
    so the rows can come in any order;
  - LCN-style codes (a column named LCN, or other codes mapped to the BOM level): each
    part's code extends its parent's, so the parent is the longest code in the file that
    this one starts with.
A row more than one level below its parent is an error naming the row, as is a level-
numbered file whose first row isn't at the top. Several top rows are several top parts.
A sub-assembly listed in two places of an indented BOM usually lists its parts at both:
they say the same line twice, so it's one line and the quantities don't add up (different
quantities are an error). A numeric level names the parts' indenture levels only when asked
(``level_names``: names for the top, the level below it...); otherwise an indenture text
column is used as it is. A parent column, when the file has one, wins over a level column.

Parts are matched by part number (case and spacing aside). One not in the catalogue is
created, named by its nomenclature (else its number). One already there only gains what
it lacks (a level, a manufacturer); a different value is left alone and reported as a
conflict. The same parent and child on two rows make one line: their quantities add up
and their refs join. A line already in the structure takes the file's quantity and ref.
Lines the file doesn't name are left as they are. An indenture level that isn't on the
workspace's list is added to the end of it.

Every row is checked first, then the structure the file would make together with what's
there (no loops: one is reported with its path; at most MAX_STRUCTURE_LEVELS deep). With
any error nothing is written. A dry run only reports, and running the same file again
changes nothing.
"""

from __future__ import annotations

import csv
import io
import re

from backend.maintenance import importer
from backend.maintenance.service import (
    MAX_AMOUNT, MAX_COMPONENTS_EACH, MAX_PART_LEVELS, MAX_STRUCTURE_LEVELS, Invalid, Maintenance, _key, _number,
    _text, new_id, structure_heights, structure_path,
)
from backend.services import excel

MAX_ROWS = importer.MAX_ROWS
SHOWN = 200  # entries of each kind listed in a result (the counts cover all)

# The import's fields, for guessing which column is which (excel.guess_mapping) and
# for a column mapper (routers/excel.py, target "bom").
FIELDS = [
    {"id": "parent", "label": "Parent part number",
     "help": "The assembly this row's part goes into. Blank: a part on its own (a top assembly).",
     "synonyms": ["parent", "parent pn", "parent part", "parent part no", "parent number", "nha",
                  "next higher assembly", "higher assembly", "assembly", "assy", "parent assy", "assembly part number",
                  "used on"]},
    {"id": "part_number", "label": "Part number", "required": True,
     "help": "The part that goes into the parent.",
     "synonyms": ["pn", "p n", "part no", "part", "child", "child pn", "child part number", "component",
                  "component part number"]},
    {"id": "quantity", "label": "Quantity", "help": "How many go into one parent (default 1).",
     "synonyms": ["qty", "qty per", "quantity per", "qty per assembly", "quantity per assembly", "count", "units per"]},
    {"id": "name", "label": "Nomenclature", "help": "The part's name.",
     "synonyms": ["name", "description", "part name", "part description", "item name", "title"]},
    {"id": "level", "label": "Indenture level", "help": "System, Subsystem, Assembly, LRU, SRU, Component...",
     "synonyms": ["level", "indenture", "indenture code", "indenture level code"]},
    {"id": "bom_level", "label": "BOM level",
     "help": "An indented BOM's level, in place of a parent column: 0/1/2, .1/..2, 1.1.2 or an LCN.",
     "synonyms": ["level", "lvl", "indenture", "bom level", "level no", "level number", "indent", "indent level",
                  "indented level", "indentation", "indenture number", "structure level", "lcn",
                  "logistics control number", "logistic control number", "outline number", "outline level"]},
    {"id": "manufacturer", "label": "Manufacturer", "synonyms": ["mfr", "manufacturer name", "make", "maker", "oem",
                                                                "vendor", "supplier"]},
    {"id": "ref", "label": "Reference",
     "help": "A reference designator or position-in-assembly label (B1, B2).",
     "synonyms": ["ref", "refs", "ref des", "reference designator", "reference designators", "designator",
                  "find number", "find no", "position in assembly"]},
]


# ---- reading a file ----------------------------------------------------------------------

def _cell(value) -> str:
    """A cell as text; a whole number from a spreadsheet without its ".0" (part numbers)."""
    if value is None:
        return ""
    if isinstance(value, float) and value.is_integer() and abs(value) < 1e15:
        return str(int(value))
    return str(value).strip()


def table_from_file(data: bytes, filename: str = "", sheet: str | None = None,
                    header_row: int | None = None) -> tuple[list[str], list[dict]]:
    """A CSV or Excel sheet as (header, rows): each row {"row": its number in the sheet,
    "cells": {column: text}}. Excel's header row is guessed unless given."""
    if excel.is_excel(data, filename):
        table = excel.read_table(data, sheet, header_row, filename, max_rows=MAX_ROWS + 1)
        header = [str(h) for h in table.header]
        rows = [{"row": n, "cells": {h: _cell(v) for h, v in zip(header, r)}}
                for n, r in zip(table.row_numbers, table.rows)]
    else:
        importer.check_csv(data)
        try:
            text = data.decode("utf-8-sig")
        except UnicodeDecodeError:
            text = data.decode("latin-1")
        reader = csv.reader(io.StringIO(text, newline=""))
        header = [h.strip() for h in next(reader, [])]
        if not any(header):
            raise Invalid("The file is empty: the first row should name the columns.")
        rows = [{"row": n, "cells": {h: (r[i].strip() if i < len(r) else "") for i, h in enumerate(header)}}
                for n, r in enumerate(reader, start=2) if any(c.strip() for c in r)]
    if len(rows) > MAX_ROWS:
        raise Invalid(f"At most {MAX_ROWS} rows at a time.")
    return header, rows


def table_from_rows(rows) -> tuple[list[str], list[dict]]:
    """Rows given directly (an MCP tool's): a list of {column: value}."""
    if not isinstance(rows, list) or not rows:
        raise Invalid("Give the BOM as a list of rows, each {column: value}.")
    importer.check_rows(rows)
    header: list[str] = []
    for r in rows:
        for k in r:
            if str(k) not in header:
                header.append(str(k))
    return header, [{"row": n, "cells": {str(k): _cell(v) for k, v in r.items()}} for n, r in enumerate(rows, start=2)]


def columns(header: list[str], mapping: dict | None = None, rows: list[dict] | None = None) -> dict[str, str]:
    """Which column feeds each field: the guess from the header's names, with any
    ``mapping`` ({field: column}) given instead. With the rows, a guessed level column
    goes by its values: numbers or an LCN make it the BOM level, words (System, LRU) the
    indenture level."""
    cols = excel.guess_mapping(header, FIELDS)
    for field, column in (mapping or {}).items():
        if field not in {f["id"] for f in FIELDS}:
            raise Invalid(f"There's no field {field!r} to map a column to.")
        if column in (None, ""):
            cols.pop(field, None)
        elif column not in header:
            raise Invalid(f"There's no column {column!r} in the file.")
        else:
            cols[field] = column
    if rows is not None:
        given = set(mapping or {})

        def structural(column: str) -> bool:
            return _lcn_header(column) or _level_kind(_values(rows, column)) is not None

        if "level" in cols and "level" not in given and "bom_level" not in cols and structural(cols["level"]):
            cols["bom_level"] = cols.pop("level")
        if "bom_level" in cols and "bom_level" not in given and not structural(cols["bom_level"]):
            column = cols.pop("bom_level")
            if "level" not in cols:
                cols["level"] = column  # words: indenture levels after all
        if ("level" in cols and "level" not in given and not _lcn_header(cols["level"])
                and _level_kind(_values(rows, cols["level"])) is not None):
            del cols["level"]  # numbers aren't indenture level names
    if "part_number" not in cols:
        raise Invalid("There's no part number column (PN, Part number). Each row needs the part number of what "
                      "goes into the parent, and the parent's part number (NHA, Parent part number) or, for an "
                      "indented BOM, its level (Level, LCN).")
    return cols


# ---- indented BOMs: the format, and each row's parent from the levels ---------------------------------

FORMATS = {
    "parent": "Parent and child columns (one row per line)",
    "list": "A list of parts (no parent or level column, so no structure)",
    "levels": "Indented, by level number",
    "dotted": "Indented, by dotted level (.1, ..2)",
    "outline": "Indented, by outline number (1, 1.1, 1.1.2)",
    "lcn": "Indented, by LCN (each part's code extends its parent's)",
}
_PLAIN = re.compile(r"\d{1,3}")
_DOTTED = re.compile(r"\.*(\d{1,3})")
_OUTLINE = re.compile(r"\d{1,6}(?:\.\d{1,6})+")


def _values(rows: list[dict], column: str) -> list[str]:
    return [v for v in (r["cells"].get(column, "").strip() for r in rows) if v]


def _lcn_header(column: str) -> bool:
    h = excel.norm(column)
    return excel.has_words(h, "lcn") or any(excel.has_words(h, w) for w in ("logistics control number",
                                                                             "logistic control number"))


def _level_kind(values: list[str]) -> str | None:
    """"levels", "dotted" or "outline" when (most of) a column's values are levels of
    that kind; None for words. A few odd values among many are errors on their rows."""
    if not values:
        return None
    plain = sum(1 for v in values if _PLAIN.fullmatch(v))
    dotted = sum(1 for v in values if _DOTTED.fullmatch(v) and v.startswith("."))
    outline = sum(1 for v in values if _OUTLINE.fullmatch(v))
    if dotted and plain + dotted > len(values) / 2:
        return "dotted"
    if outline and plain + outline > len(values) / 2:
        return "outline"
    if plain > len(values) / 2:
        return "levels"
    return None


def detect(cols: dict, rows: list[dict]) -> dict:
    """The BOM's format: {id, label, column} (see FORMATS). A parent column with any
    parent in it wins; else a BOM level column makes it indented."""
    has_parent = "parent" in cols and bool(_values(rows, cols["parent"]))
    if "bom_level" in cols and not has_parent:
        column = cols["bom_level"]
        kind = "lcn" if _lcn_header(column) else (_level_kind(_values(rows, column)) or "lcn")
    else:
        kind, column = ("parent", cols["parent"]) if "parent" in cols else ("list", None)
    return {"id": kind, "label": FORMATS[kind], "column": column}


def _outline_text(segs: tuple) -> str:
    return ".".join(str(s) for s in segs)


def _read_level(kind: str, code: str):
    """A row's level as the format reads it, or Invalid."""
    if not code:
        raise Invalid("The level is blank.")
    if kind == "levels" and _PLAIN.fullmatch(code):
        return int(code)
    if kind == "dotted" and _DOTTED.fullmatch(code):
        return int(_DOTTED.fullmatch(code).group(1))
    if kind == "outline" and (_OUTLINE.fullmatch(code) or _PLAIN.fullmatch(code)):
        return tuple(int(s) for s in code.split("."))
    if kind == "lcn":
        lcn = re.sub(r"\s+", "", code).upper()
        if len(lcn) > 40:
            raise Invalid("The LCN is over 40 characters.")
        return lcn
    like = {"levels": "a whole number (0, 1, 2)", "dotted": "dots and a number (.1, ..2)",
            "outline": "an outline number (1, 1.1, 1.1.2)"}[kind]
    raise Invalid(f"The level {code!r} isn't {like} like the others.")


def _by_level_number(entries: list[dict]) -> list[dict]:
    """Levels in tree order: a row's parent is the nearest row above it one level up."""
    errors: list[dict] = []
    top = min(e["at"] for e in entries)
    last: dict[int, dict] = {}
    prev = None
    for e in entries:
        lv = e["at"]
        e["depth"] = lv - top
        if lv > top:
            if prev is None:
                errors.append({"row": e["row"], "error": f"It's at level {lv}, but the first row has to be at the "
                                                         f"top level ({top})."})
            elif lv > prev + 1:
                errors.append({"row": e["row"], "error": f"It's at level {lv} straight after a row at level {prev}: "
                                                         f"a level is skipped (one level down at a time)."})
            elif lv - 1 not in last:
                errors.append({"row": e["row"], "error": f"It's at level {lv}, but no row above it is at level "
                                                         f"{lv - 1} to hold it."})
            else:
                e["up"] = last[lv - 1]
        last[lv] = e
        prev = lv
    return errors


def _by_outline(entries: list[dict]) -> list[dict]:
    """Outline numbers: 1.1.2's parent is 1.1, wherever it is in the file."""
    errors: list[dict] = []
    seen: dict[tuple, dict] = {}
    for e in entries:
        if e["at"] in seen:
            errors.append({"row": e["row"], "error": f"Outline number {_outline_text(e['at'])} is on row "
                                                     f"{seen[e['at']]['row']} too. (In Excel, keep the column as "
                                                     "text so 1.10 isn't read as 1.1.)"})
        else:
            seen[e["at"]] = e
    top = min(len(e["at"]) for e in entries)
    for e in entries:
        segs = e["at"]
        e["depth"] = len(segs) - top
        if len(segs) == top:
            continue
        if segs[:-1] in seen:
            e["up"] = seen[segs[:-1]]
            continue
        nearest = next((segs[:k] for k in range(len(segs) - 2, top - 1, -1) if segs[:k] in seen), None)
        missing = _outline_text(segs[:-1])
        errors.append({"row": e["row"], "error": (
            f"It's {_outline_text(segs)}, but there's no {missing}: that's more than one level below "
            f"{_outline_text(nearest)}." if nearest else f"It's {_outline_text(segs)}, but there's no {missing} to "
                                                         "hold it.")})
    return errors


def _by_lcn(entries: list[dict]) -> list[dict]:
    """LCN-style codes: the parent is the longest code in the file this one starts with.
    The codes at one level are one length; a longer one has lost the level above it."""
    errors: list[dict] = []
    seen: dict[str, dict] = {}
    for e in entries:
        if e["at"] in seen:
            errors.append({"row": e["row"], "error": f"LCN {e['at']} is on row {seen[e['at']]['row']} too."})
        else:
            seen[e["at"]] = e
    for e in entries:
        code = e["at"]
        e["up"] = next((seen[code[:k]] for k in range(len(code) - 1, 0, -1) if code[:k] in seen), None)
    for e in entries:  # depth: parents first (each parent's code is shorter)
        e["depth"] = 0 if e["up"] is None else None
    for e in sorted(entries, key=lambda x: len(x["at"])):
        if e["depth"] is None:
            e["depth"] = e["up"]["depth"] + 1
    shortest: dict[int, dict] = {}
    for e in entries:
        s = shortest.get(e["depth"])
        if s is None or len(e["at"]) < len(s["at"]):
            shortest[e["depth"]] = e
    flagged: set[int] = set()  # rows reported, and the rows under them (not reported again)
    for e in sorted(entries, key=lambda x: len(x["at"])):
        if e["up"] is not None and id(e["up"]) in flagged:
            flagged.add(id(e))
            continue
        s = shortest[e["depth"]]
        if len(e["at"]) <= len(s["at"]):
            continue
        flagged.add(id(e))
        if e["up"] is None:
            errors.append({"row": e["row"], "error": f"LCN {e['at']} doesn't extend any other LCN in the file and "
                                                     f"is longer than the top's ({s['at']}): its parent is missing."})
        else:
            errors.append({"row": e["row"], "error": f"LCN {e['at']} is longer than others at its level ({s['at']}): "
                                                     f"the level between it and {e['up']['at']} is missing."})
    return errors


def _tree(kind: str, entries: list[dict], level_names: list[str] | None) -> list[dict]:
    """Each row's parent in an indented BOM (entries in file order, each with its "code"):
    sets "parent" (the parent row's part number) and "occurrence" (its row); errors."""
    errors: list[dict] = []
    coded = []
    for e in entries:
        try:
            e["at"] = _read_level(kind, e["code"])
            coded.append(e)
        except Invalid as err:
            errors.append({"row": e["row"], "error": str(err)})
    if not coded:
        return errors
    errors += {"levels": _by_level_number, "dotted": _by_level_number, "outline": _by_outline,
               "lcn": _by_lcn}[kind](coded)
    for e in coded:
        up = e.get("up")
        if up is not None:
            e["parent"], e["occurrence"] = up.get("number") or "", up["row"]
        if level_names and not e.get("level") and e.get("number"):
            if e["depth"] < len(level_names):
                e["level"] = level_names[e["depth"]]
            else:
                errors.append({"row": e["row"], "error": f"It's {e['depth']} levels below the top: deeper than the "
                                                         f"{len(level_names)} level names."})
    return errors


# ---- planning and importing -------------------------------------------------------------

def _parse(m: Maintenance, rows: list[dict], cols: dict, fmt: dict,
           level_names: list[str] | None = None) -> tuple[list[dict], list[dict]]:
    """Each row checked, and its parent found from the levels in an indented BOM:
    (lines, errors)."""
    indented = fmt["id"] not in ("parent", "list")
    if level_names and not indented:
        raise Invalid("Naming indenture levels by depth needs an indented BOM: a level column (Level, LCN) and "
                      "no parent column.")
    entries, errors = [], []
    for r in rows:
        get = lambda f: r["cells"].get(cols[f], "").strip() if f in cols else ""  # noqa: E731
        if not any(get(f) for f in cols):
            continue
        e = {"row": r["row"], "code": get("bom_level"), "parent": "", "occurrence": None}
        entries.append(e)
        try:
            e["number"] = _text(get("part_number"), "part number", max_len=120)
            if not indented:
                e["parent"] = _text(get("parent"), "parent part number", max_len=120)
            if not e["number"]:
                raise Invalid("The part number is blank.")
            e.update(qty=get("quantity"), name=_text(get("name"), "nomenclature"),
                     level=_text(get("level"), "indenture level", max_len=60),
                     manufacturer=_text(get("manufacturer"), "manufacturer", max_len=120),
                     ref=_text(get("ref"), "reference"))
        except Invalid as err:
            e["bad"] = True
            errors.append({"row": r["row"], "error": str(err)})
    if indented:
        errors += _tree(fmt["id"], entries, level_names)
    out = []
    for e in entries:
        if e.get("bad"):
            continue
        try:
            parent, number, qty = e["parent"], e["number"], e["qty"]
            if parent and _key(parent) == _key(number):
                raise Invalid(f"{number} can't contain itself.")
            out.append({"row": e["row"], "parent": parent, "occurrence": e["occurrence"], "number": number,
                        "qty": m._per_one(qty) if parent else None, "name": e["name"], "level": e["level"],
                        "manufacturer": e["manufacturer"], "ref": e["ref"]})
            if not parent and qty:
                _number(qty, "quantity", 0, MAX_AMOUNT)  # checked, though a part on its own has no line
        except Invalid as err:
            errors.append({"row": e["row"], "error": str(err)})
    errors.sort(key=lambda x: x["row"] or 0)
    return out, errors


def plan(m: Maintenance, header: list[str], rows: list[dict], mapping: dict | None = None,
         level_names: list[str] | None = None) -> dict:
    """What importing the rows would do (see the module's notes)."""
    cols = columns(header, mapping, rows)
    fmt = detect(cols, rows)
    lines, errors = _parse(m, rows, cols, fmt, level_names)
    existing = {_key(pt["part_number"]): pt for pt in m.s.nodes(m.org, "Part")}
    levels = m.part_levels()
    level_keys = {_key(n): n for n in levels}
    new_levels: list[str] = []
    conflicts: list[dict] = []

    # The parts: each part number once, with what the file says about it.
    parts: dict[str, dict] = {}

    def part(number: str, row) -> dict:
        key = _key(number)
        if key not in parts:
            node = existing.get(key)
            parts[key] = {"key": key, "number": node["part_number"] if node else number, "node": node, "row": row,
                          "fields": {}}
        return parts[key]

    for ln in lines:
        p = part(ln["number"], ln["row"])
        if ln["parent"]:
            part(ln["parent"], ln["row"])
        if ln["level"]:
            canonical = level_keys.get(_key(ln["level"]))
            if canonical is None:
                canonical = level_keys[_key(ln["level"])] = ln["level"]
                new_levels.append(canonical)
            ln["level"] = canonical
        for field in ("name", "level", "manufacturer"):
            value = ln[field]
            if not value:
                continue
            given = p["fields"].get(field)
            if given is None:
                p["fields"][field] = (value, ln["row"])
            elif _key(given[0]) != _key(value):
                conflicts.append({"part_number": p["number"], "field": field, "row": ln["row"],
                                  "why": f"row {given[1]} says {given[0]!r}: kept that"})
    if len(levels) + len(new_levels) > MAX_PART_LEVELS:
        errors.append({"row": None, "error": f"That would make more than {MAX_PART_LEVELS} indenture levels."})

    creates, updates = [], []
    for p in parts.values():
        fields = {f: v for f, (v, _) in p["fields"].items()}
        node = p["node"]
        if node is None:
            creates.append({"key": p["key"], "part_number": p["number"], "name": fields.get("name") or p["number"],
                            "level": fields.get("level", ""), "manufacturer": fields.get("manufacturer", "")})
            continue
        changes = {}
        for f, v in fields.items():
            now = node.get(f) or ""
            if not now:
                changes[f] = v
            elif _key(now) != _key(v):
                conflicts.append({"part_number": p["number"], "field": f, "row": p["fields"][f][1],
                                  "why": f"it's already {now!r}: kept as it is"})
        if changes:
            updates.append({"id": node["id"], "part_number": p["number"], "changes": changes})

    # The lines: one per parent and child. Two rows of one add up; in an indented BOM, only
    # two under the same row of the parent (a sub-assembly listed in two places says its
    # lines again, so they're the same lines).
    placed: dict[tuple, dict] = {}
    for ln in lines:
        if not ln["parent"]:
            continue
        key = (_key(ln["parent"]), _key(ln["number"]), ln["occurrence"])
        if key in placed:
            c = placed[key]
            c["qty"] = round(c["qty"] + ln["qty"], 9)
            c["ref"] = ", ".join(x for x in (c["ref"], ln["ref"]) if x)
            c["rows"].append(ln["row"])
        else:
            placed[key] = {"parent": key[0], "child": key[1], "qty": ln["qty"], "ref": ln["ref"], "rows": [ln["row"]]}
    combined: dict[tuple, dict] = {}
    for c in placed.values():
        key = (c["parent"], c["child"])
        first = combined.get(key)
        if first is None:
            combined[key] = c
        elif first["qty"] != c["qty"]:
            errors.append({"row": c["rows"][0], "error": (
                f"{parts[c['parent']]['number']} holds {c['qty']:g} of {parts[c['child']]['number']} here, but "
                f"{first['qty']:g} at row {first['rows'][0]}: one part has one structure.")})
        else:
            first["rows"] += c["rows"]
    adds, changes_, unchanged = [], [], 0
    for c in combined.values():
        parent, child = parts[c["parent"]], parts[c["child"]]
        c["ref"] = c["ref"][:200]
        line = (m.s.edge(m.org, "CONTAINS", parent["node"]["id"], child["node"]["id"])
                if parent["node"] and child["node"] else None)
        if line is None:
            adds.append(c)
        elif line.get("qty") != c["qty"] or (line.get("ref") or "") != c["ref"]:
            changes_.append({**c, "was": {"qty": line.get("qty"), "ref": line.get("ref") or ""}})
        else:
            unchanged += 1

    # The structure as it would be: no loops, not too deep, not too many lines on one part.
    def node_id(key: str) -> str:
        p = parts.get(key)
        return p["node"]["id"] if p and p["node"] else f"new:{key}"

    children: dict[str, list[str]] = {}
    for key, p in parts.items():
        if p["node"]:
            children[p["node"]["id"]] = list(m._component_ids(p["node"]["id"]))
    for c in adds:
        children.setdefault(node_id(c["parent"]), []).append(node_id(c["child"]))

    def kids(pid: str) -> list[str]:
        if pid not in children:
            children[pid] = [] if pid.startswith("new:") else list(m._component_ids(pid))
        return children[pid]

    def number_of(pid: str) -> str:
        if pid.startswith("new:"):
            return parts[pid[4:]]["number"]
        node = m.s.node(m.org, pid)
        return node["part_number"] if node else pid

    for c in adds:
        parent, child = node_id(c["parent"]), node_id(c["child"])
        if len(kids(parent)) > MAX_COMPONENTS_EACH:
            errors.append({"row": c["rows"][0], "error": f"{number_of(parent)} would have more than "
                                                         f"{MAX_COMPONENTS_EACH} lines."})
            break
        path = structure_path(child, parent, kids)
        if path:
            names = " › ".join(number_of(pid) for pid in [parent, *path])
            errors.append({"row": c["rows"][0], "error": f"That makes a loop: {names}. A part can't contain a part "
                                                        "it's inside."})
            break
    if not any("loop" in e["error"] for e in errors):
        # From every part, so a structure above one in the file counts too.
        heights = structure_heights([pt["id"] for pt in existing.values()] + [node_id(k) for k in parts], kids)
        if heights and max(heights.values()) + 1 > MAX_STRUCTURE_LEVELS:
            errors.append({"row": None, "error": f"The structure would be more than {MAX_STRUCTURE_LEVELS} levels "
                                                 "deep."})
    return {"columns": cols, "format": fmt, "rows": len(lines), "errors": errors, "conflicts": conflicts,
            "levels": new_levels,
            "create": creates, "update": updates, "add": adds, "change": changes_, "unchanged": unchanged,
            "parts": parts}


def run(m: Maintenance, header: list[str], rows: list[dict], dry_run: bool = True, mapping: dict | None = None,
        level_names: list[str] | None = None) -> dict:
    """Import a BOM (see plan). With any error, or dry_run, nothing is written.
    level_names: an indented BOM's indenture level by depth (top first), for rows
    without one of their own."""
    p = plan(m, header, rows, mapping, level_names)
    write = not dry_run and not p["errors"]
    if write:
        today = m.today()
        if p["levels"]:
            m._emit("part_levels.set", {"levels": m.part_levels() + p["levels"], "renamed": {}, "on": today})
        ids = {key: q["node"]["id"] for key, q in p["parts"].items() if q["node"]}
        for c in p["create"]:
            ids[c["key"]] = pid = new_id()
            m._emit("part.created", {"id": pid, "part_number": c["part_number"], "name": c["name"][:200],
                                     "manufacturer": c["manufacturer"], "unit": "each", "unit_cost": None,
                                     "notes": "", "on": today})
            if c["level"]:
                m._emit("part.updated", {"id": pid, "changes": {"level": c["level"]}})
        for u in p["update"]:
            m._emit("part.updated", {"id": u["id"], "changes": u["changes"]})
        for c in p["add"]:
            m._emit("part.component_added", {"parent_id": ids[c["parent"]], "child_id": ids[c["child"]],
                                             "qty": c["qty"], "ref": c["ref"], "on": today})
        for c in p["change"]:
            m._emit("part.component_updated", {"parent_id": ids[c["parent"]], "child_id": ids[c["child"]],
                                               "changes": {"qty": c["qty"], "ref": c["ref"]}, "on": today})
    number = lambda key: p["parts"][key]["number"]  # noqa: E731
    line = lambda c: {"parent": number(c["parent"]), "part_number": number(c["child"]), "qty": c["qty"],  # noqa: E731
                      **({"ref": c["ref"]} if c["ref"] else {}), "rows": c["rows"]}
    return {
        "dry_run": not write, "ok": not p["errors"], "columns": p["columns"], "format": p["format"],
        "counts": {"rows": p["rows"], "parts_created": len(p["create"]), "parts_updated": len(p["update"]),
                   "lines_added": len(p["add"]), "lines_changed": len(p["change"]), "unchanged": p["unchanged"],
                   "levels_added": len(p["levels"]), "conflicts": len(p["conflicts"]), "errors": len(p["errors"])},
        "levels_added": p["levels"],
        "parts_created": [{k: c[k] for k in ("part_number", "name", "level") if c[k]} for c in p["create"][:SHOWN]],
        "parts_updated": [{k: u[k] for k in ("part_number", "changes")} for u in p["update"][:SHOWN]],
        "lines_added": [line(c) for c in p["add"][:SHOWN]],
        "lines_changed": [{**line(c), "was": c["was"]} for c in p["change"][:SHOWN]],
        "conflicts": p["conflicts"][:SHOWN], "errors": p["errors"][:SHOWN],
    }
