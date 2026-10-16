"""A bill of materials in, from CSV or Excel: one row per parent -> child line (#435).

Columns are matched by their names, as the other spreadsheet imports match them
(``excel.guess_mapping``): the parent's part number (also "NHA", "Next higher
assembly", "Parent PN", "Assembly"), the part number of what goes in it ("PN",
"Part no", "Component"), the quantity in one parent ("Qty"), its nomenclature
("Description", "Name"), its indenture level ("Level"), its manufacturer ("Mfr",
"Make") and a reference ("Ref", "Ref des", "Find number"). Only the part number is
needed: a row with no parent just describes a part (the top assembly, say).

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


def columns(header: list[str], mapping: dict | None = None) -> dict[str, str]:
    """Which column feeds each field: the guess from the header's names, with any
    ``mapping`` ({field: column}) given instead."""
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
    if "part_number" not in cols:
        raise Invalid("There's no part number column (PN, Part number). Each row needs the part number of what "
                      "goes into the parent, and the parent's part number (NHA, Parent part number).")
    return cols


# ---- planning and importing -------------------------------------------------------------

def _parse(m: Maintenance, header: list[str], rows: list[dict], cols: dict) -> tuple[list[dict], list[dict]]:
    """Each row checked: (lines, errors)."""
    out, errors = [], []
    for r in rows:
        get = lambda f: r["cells"].get(cols[f], "").strip() if f in cols else ""  # noqa: E731
        try:
            number = _text(get("part_number"), "part number", max_len=120)
            parent = _text(get("parent"), "parent part number", max_len=120)
            if not number:
                if not any(get(f) for f in cols):
                    continue
                raise Invalid("The part number is blank.")
            if parent and _key(parent) == _key(number):
                raise Invalid(f"{number} can't contain itself.")
            qty = get("quantity")
            out.append({"row": r["row"], "parent": parent, "number": number,
                        "qty": m._per_one(qty) if parent else None,
                        "name": _text(get("name"), "nomenclature"), "level": _text(get("level"), "indenture level",
                                                                                    max_len=60),
                        "manufacturer": _text(get("manufacturer"), "manufacturer", max_len=120),
                        "ref": _text(get("ref"), "reference")})
            if not parent and qty:
                _number(qty, "quantity", 0, MAX_AMOUNT)  # checked, though a part on its own has no line
        except Invalid as err:
            errors.append({"row": r["row"], "error": str(err)})
    return out, errors


def plan(m: Maintenance, header: list[str], rows: list[dict], mapping: dict | None = None) -> dict:
    """What importing the rows would do (see the module's notes)."""
    cols = columns(header, mapping)
    lines, errors = _parse(m, header, rows, cols)
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

    # The lines: one per parent and child (two rows of one add up).
    combined: dict[tuple, dict] = {}
    for ln in lines:
        if not ln["parent"]:
            continue
        key = (_key(ln["parent"]), _key(ln["number"]))
        if key in combined:
            c = combined[key]
            c["qty"] = round(c["qty"] + ln["qty"], 9)
            c["ref"] = ", ".join(x for x in (c["ref"], ln["ref"]) if x)
            c["rows"].append(ln["row"])
        else:
            combined[key] = {"parent": key[0], "child": key[1], "qty": ln["qty"], "ref": ln["ref"], "rows": [ln["row"]]}
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
    return {"columns": cols, "rows": len(lines), "errors": errors, "conflicts": conflicts, "levels": new_levels,
            "create": creates, "update": updates, "add": adds, "change": changes_, "unchanged": unchanged,
            "parts": parts}


def run(m: Maintenance, header: list[str], rows: list[dict], dry_run: bool = True, mapping: dict | None = None) -> dict:
    """Import a BOM (see plan). With any error, or dry_run, nothing is written."""
    p = plan(m, header, rows, mapping)
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
        "dry_run": not write, "ok": not p["errors"], "columns": p["columns"],
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
