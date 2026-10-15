"""The condition register in and out: CSV or JSON, by path, as item classes are
(taxonomy.py).

A register is a list of conditions, each named by its path from the top ("Hazardous
area > Zone 1"), or by its name and its parent's path, or nested (a condition with
its ``children``), with an optional kind (presence, or value with a unit), code and
description. A site can load its own list this way; Reliafy ships none.

Importing is by path, so it can be run again: a condition already there is matched by
its path (case and spacing aside) and only gains what it lacks (a code, description or
unit it has none of). A different kind, or a field it already has with another value,
is left as it is and reported as a conflict. Every row is checked first; with any error
nothing is written. A dry run only reports. Only the register: where conditions apply
is recorded on the locations, positions and items themselves.
"""

from __future__ import annotations

import csv
import io
import json

from backend.maintenance.service import (
    MAX_CONDITION_DEPTH, MAX_CONDITIONS, Invalid, Maintenance, _key, _text, new_id,
)
from backend.maintenance.taxonomy import MAX_TEXT, SHOWN, _path

FORMAT = "reliafy-conditions"


# ---- reading a file -------------------------------------------------------------------

def _flatten(entries, parent: list[str], out: list[dict], where: str) -> None:
    for i, e in enumerate(entries):
        at = f"{where}{i + 1}"
        if not isinstance(e, dict):
            raise Invalid(f"Entry {at} isn't an object.")
        if e.get("path"):
            path = _path(e["path"])
        elif e.get("name"):
            path = (_path(e["parent"]) if e.get("parent") else list(parent)) + [str(e["name"]).strip()]
        else:
            raise Invalid(f"Entry {at} needs a path, or a name.")
        out.append({"row": at, "path": path, "kind": e.get("kind"), "unit": e.get("unit"), "code": e.get("code"),
                    "description": e.get("description")})
        if e.get("children"):
            if not isinstance(e["children"], list):
                raise Invalid(f"Entry {at}'s children must be a list.")
            _flatten(e["children"], path, out, at + ".")


def rows_from_json(data) -> list[dict]:
    """Conditions from JSON (text, or already parsed): a list, or {"conditions": [...]};
    each flat (path, or name with parent) or nested (children)."""
    if isinstance(data, (str, bytes)):
        if len(data) > MAX_TEXT:
            raise Invalid("That's over 2 MB of conditions. Split it up.")
        try:
            data = json.loads(data)
        except ValueError as err:
            raise Invalid(f"That isn't valid JSON: {err}") from None
    if isinstance(data, dict):
        data = data.get("conditions")
    if not isinstance(data, list):
        raise Invalid('Give a list of conditions, or {"conditions": [...]}.')
    out: list[dict] = []
    _flatten(data, [], out, "")
    return out


_COLUMNS = {"path": ("path", "condition path", "condition"), "name": ("name",),
            "parent": ("parent", "parent path"), "kind": ("kind",), "unit": ("unit",), "code": ("code",),
            "description": ("description",)}


def rows_from_csv(text) -> list[dict]:
    """Conditions from CSV with a header row: path (or name and parent), kind, unit,
    code, description."""
    if isinstance(text, bytes):
        text = text.decode("utf-8-sig", errors="replace")
    if len(text) > MAX_TEXT:
        raise Invalid("That's over 2 MB of conditions. Split it up.")
    reader = csv.reader(io.StringIO(text.lstrip("﻿")))
    header = next(reader, None)
    if not header:
        raise Invalid("The CSV is empty.")
    cols = {}
    for i, h in enumerate(header):
        name = _key(h).replace("_", " ")
        for field, names in _COLUMNS.items():
            if name in names and field not in cols:
                cols[field] = i
    if "path" not in cols and "name" not in cols:
        raise Invalid("The CSV needs a path column (Hazardous area > Zone 1), or name and parent columns.")
    out: list[dict] = []
    for n, row in enumerate(reader, start=2):
        if not any(c.strip() for c in row):
            continue
        get = lambda f: row[cols[f]].strip() if f in cols and cols[f] < len(row) else ""  # noqa: E731
        try:
            _flatten([{f: get(f) for f in _COLUMNS}], [], out, "")
        except Invalid as err:
            raise Invalid(f"Row {n}: {err}") from None
        out[-1]["row"] = f"row {n}"
    return out


# ---- planning and importing -------------------------------------------------------------

def _existing(m: Maintenance) -> dict[tuple, dict]:
    """Every live condition by its path's keys."""
    return {tuple(_key(x["name"]) for x in m._condition_chain(c["id"])): c
            for c in m.s.nodes(m.org, "Condition") if not c.get("retired")}


def plan(m: Maintenance, rows: list[dict]) -> dict:
    """What importing ``rows`` would do: conditions to create (with any parents a path
    names that aren't there), conditions to fill in, conflicts left alone, and errors."""
    errors, conflicts, creates, updates = [], [], [], []
    if len(rows) > MAX_CONDITIONS:
        return {"errors": [{"row": None, "error": f"At most {MAX_CONDITIONS:,} conditions at a time."}],
                "create": [], "update": [], "conflicts": [], "unchanged": 0}
    existing = _existing(m)
    seen: dict[tuple, str] = {}
    wanted: dict[tuple, dict] = {}
    for r in rows:
        try:
            names = [m._condition_name(n) for n in r["path"]]
            if not names:
                raise Invalid("It has no name.")
            if len(names) > MAX_CONDITION_DEPTH:
                raise Invalid(f"Conditions go at most {MAX_CONDITION_DEPTH} levels deep.")
            key = tuple(_key(n) for n in names)
            if key in seen:
                raise Invalid(f"{' > '.join(names)} is listed twice (also {seen[key]}).")
            seen[key] = r["row"]
            kind, unit = m._condition_kind(_text(r.get("kind"), "kind").lower() or None, r.get("unit"))
            wanted[key] = {"row": r["row"], "names": names, "kind": kind, "kind_given": bool(r.get("kind") or unit),
                           "fields": {"unit": unit, "code": _text(r.get("code"), "code"),
                                      "description": _text(r.get("description"), "description")}}
        except Invalid as err:
            errors.append({"row": r.get("row"), "error": str(err)})
    # Parents named only in a path are made too, with just their name.
    for key in list(wanted):
        for depth in range(1, len(key)):
            parent = key[:depth]
            if parent not in wanted and parent not in existing:
                wanted[parent] = {"row": wanted[key]["row"], "names": wanted[key]["names"][:depth],
                                  "kind": "presence", "kind_given": False,
                                  "fields": {"unit": "", "code": "", "description": ""}, "implied": True}
    unchanged = 0
    for key in sorted(wanted, key=lambda k: (len(k), k)):
        w = wanted[key]
        path = " > ".join(w["names"])
        node = existing.get(key)
        if node is None:
            creates.append({"path": path, "names": w["names"], "key": key, "kind": w["kind"], **w["fields"],
                            "implied": bool(w.get("implied"))})
            continue
        kind_now = node.get("kind") or "presence"
        if w["kind_given"] and w["kind"] != kind_now:
            conflicts.append({"path": path, "field": "kind", "why": f"it's already a {kind_now} condition: kept as it is"})
        fields = dict(w["fields"]) if w["kind"] == kind_now else {**w["fields"], "unit": ""}
        changes = {f: v for f, v in fields.items() if v and not node.get(f)}
        for f, v in fields.items():
            if v and node.get(f) and v != node.get(f):
                conflicts.append({"path": path, "field": f, "why": f"its {f} is already {node.get(f)!r}: kept as it is"})
        if changes:
            updates.append({"path": path, "id": node["id"], "changes": changes})
        else:
            unchanged += 1
    if len(existing) + len(creates) > MAX_CONDITIONS:
        errors.append({"row": None, "error": f"That would make more than {MAX_CONDITIONS:,} conditions."})
    return {"errors": errors, "create": creates, "update": updates, "conflicts": conflicts, "unchanged": unchanged}


def run(m: Maintenance, rows: list[dict], dry_run: bool = True, source: str = "") -> dict:
    """Import conditions (see plan). With any error, or dry_run, nothing is written."""
    p = plan(m, rows)
    write = not dry_run and not p["errors"]
    if write:
        made: dict[tuple, str] = {k: c["id"] for k, c in _existing(m).items()}
        today = m.today()
        source = _text(source, "source")
        for c in p["create"]:
            cid = new_id()
            m._emit("condition.created", {
                "id": cid, "name": c["names"][-1], "parent_id": made.get(c["key"][:-1]) if len(c["key"]) > 1 else None,
                "kind": c["kind"], "unit": c["unit"], "code": c["code"], "description": c["description"], "on": today}
                | ({"source": source} if source else {}))
            made[c["key"]] = cid
        for u in p["update"]:
            m._emit("condition.updated", {"id": u["id"], "changes": u["changes"], "on": today})
    brief = lambda c: {"path": c["path"], "kind": c["kind"],  # noqa: E731
                       **{k: c[k] for k in ("unit", "code") if c.get(k)}} | ({"implied": True} if c["implied"] else {})
    return {
        "dry_run": not write, "ok": not p["errors"],
        "counts": {"create": len(p["create"]), "update": len(p["update"]), "unchanged": p["unchanged"],
                   "conflicts": len(p["conflicts"]), "errors": len(p["errors"])},
        "create": [brief(c) for c in p["create"][:SHOWN]],
        "update": [{"path": u["path"], "changes": u["changes"]} for u in p["update"][:SHOWN]],
        "conflicts": p["conflicts"][:SHOWN], "errors": p["errors"][:SHOWN],
    }


# ---- exporting ------------------------------------------------------------------------

def export_rows(m: Maintenance) -> list[dict]:
    """Every live condition, parents before children: path, kind, unit, code and
    description. Imports back as it was."""
    out = []

    def walk(nodes, above):
        for c in sorted(nodes, key=lambda c: c["name"].lower()):
            path = above + [c["name"]]
            out.append({"path": " > ".join(path), "kind": c.get("kind") or "presence", "unit": c.get("unit", ""),
                        "code": c.get("code", ""), "description": c.get("description", "")})
            walk(m._condition_children(c["id"]), path)

    walk(m._condition_children(None), [])
    return out


def export_json(m: Maintenance) -> dict:
    return {"format": FORMAT, "version": 1, "conditions": export_rows(m)}


def export_csv(m: Maintenance) -> str:
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["path", "kind", "unit", "code", "description"])
    for r in export_rows(m):
        w.writerow([r["path"], r["kind"], r["unit"], r["code"], r["description"]])
    return buf.getvalue()
