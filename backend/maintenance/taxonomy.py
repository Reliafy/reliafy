"""Item class taxonomies in and out: CSV or JSON, and the optional starter taxonomy.

A taxonomy is a list of classes, each named by its path from the top
("Rotating equipment > Pump > Centrifugal"), or by its name and its parent's path,
or nested (a class with its ``children``), with an optional code, level label,
description and attributes. A company that holds a standard's classification under
licence can load its own copy this way; Reliafy ships none. The starter taxonomy
below is Reliafy's own, in its own words: a modest tree of common equipment, loaded
only when asked.

Importing is by path, so it can be run again: a class already there is matched by
its path (case and spacing aside) and only gains what it lacks (a code, level or
description it has none of; attributes it doesn't have). An attribute it already has
with a different definition is left as it is and reported as a conflict. Every row is
checked first; with any error nothing is written. A dry run only reports.
"""

from __future__ import annotations

import csv
import io
import json
import re

from backend.maintenance.service import (
    MAX_CLASS_DEPTH, MAX_ITEM_CLASSES, Invalid, Maintenance, _key, _text, new_id,
)

STARTER_SOURCE = "Reliafy starter taxonomy"
MAX_TEXT = 2 * 1024 * 1024  # characters of CSV or JSON in one import
SHOWN = 200  # entries of each kind listed in a result (the counts cover all)
_SPLIT = re.compile(r"\s*[>›]\s*")
_ATTRIBUTE = re.compile(r"^(?P<name>[^\[\]();|]+?)\s*(?:\((?P<unit>[^()]*)\))?\s*"
                        r"(?:\[\s*(?P<kind>number|text|choice)\s*(?::(?P<options>[^\]]*))?\])?$", re.I)


# ---- attributes as text (a CSV cell) ------------------------------------------------

def attributes_from_text(text: str) -> list[dict]:
    """Attributes written in one cell, separated by ``;``: ``Flow (m3/h)`` is a number
    in m3/h, ``Stages [number]`` a number with no unit, ``Refrigerant [text]`` text (as
    is a bare name), ``Frequency (Hz) [choice: 50 | 60]`` a choice."""
    out = []
    for part in (p.strip() for p in str(text or "").split(";")):
        if not part:
            continue
        got = _ATTRIBUTE.match(part)
        if not got:
            raise Invalid(f"Can't read the attribute {part[:60]!r}: write it like 'Flow (m3/h)', 'Stages [number]' "
                          "or 'Frequency (Hz) [choice: 50 | 60]'.")
        unit = (got.group("unit") or "").strip()
        kind = (got.group("kind") or ("number" if unit else "text")).lower()
        options = [o.strip() for o in (got.group("options") or "").split("|") if o.strip()]
        out.append({"name": got.group("name").strip(), "unit": unit, "kind": kind, "options": options})
    return out


def attributes_text(attrs: list[dict]) -> str:
    """The cell attributes_from_text reads back."""
    out = []
    for a in attrs or []:
        text = a["name"] + (f" ({a['unit']})" if a.get("unit") else "")
        if a["kind"] == "choice":
            text += f" [choice: {' | '.join(a.get('options') or [])}]"
        elif a["kind"] == "text" and a.get("unit") or a["kind"] == "number" and not a.get("unit"):
            text += f" [{a['kind']}]"
        out.append(text)
    return "; ".join(out)


# ---- reading a file -------------------------------------------------------------------

def _path(text) -> list[str]:
    return [p for p in _SPLIT.split(str(text or "").strip()) if p] if str(text or "").strip() else []


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
        attrs = e.get("attributes") or []
        if isinstance(attrs, str):
            attrs = attributes_from_text(attrs)
        out.append({"row": at, "path": path, "code": e.get("code"), "level": e.get("level"),
                    "description": e.get("description"), "attributes": attrs})
        if e.get("children"):
            if not isinstance(e["children"], list):
                raise Invalid(f"Entry {at}'s children must be a list.")
            _flatten(e["children"], path, out, at + ".")


def rows_from_json(data) -> list[dict]:
    """Classes from JSON (text, or already parsed): a list, or {"classes": [...]}; each
    flat (path, or name with parent) or nested (children)."""
    if isinstance(data, (str, bytes)):
        if len(data) > MAX_TEXT:
            raise Invalid("That's over 2 MB of taxonomy. Split it up.")
        try:
            data = json.loads(data)
        except ValueError as err:
            raise Invalid(f"That isn't valid JSON: {err}") from None
    if isinstance(data, dict):
        data = data.get("classes")
    if not isinstance(data, list):
        raise Invalid('Give a list of classes, or {"classes": [...]}.')
    out: list[dict] = []
    _flatten(data, [], out, "")
    return out


_COLUMNS = {"path": ("path", "class path", "item class", "class"), "name": ("name",),
            "parent": ("parent", "parent path"), "code": ("code",), "level": ("level", "level label"),
            "description": ("description",), "attributes": ("attributes",)}


def rows_from_csv(text) -> list[dict]:
    """Classes from CSV with a header row: path (or name and parent), code, level,
    description, attributes (as attributes_from_text reads them)."""
    if isinstance(text, bytes):
        text = text.decode("utf-8-sig", errors="replace")
    if len(text) > MAX_TEXT:
        raise Invalid("That's over 2 MB of taxonomy. Split it up.")
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
        raise Invalid("The CSV needs a path column (Rotating equipment > Pump), or name and parent columns.")
    entries = []
    for n, row in enumerate(reader, start=2):
        if not any(c.strip() for c in row):
            continue
        get = lambda f: row[cols[f]].strip() if f in cols and cols[f] < len(row) else ""  # noqa: E731
        entries.append({"path": get("path"), "name": get("name"), "parent": get("parent"), "code": get("code"),
                        "level": get("level"), "description": get("description"), "_row": n,
                        "attributes": get("attributes")})
    out = []
    for e in entries:
        try:
            _flatten([{k: v for k, v in e.items() if k != "_row"}], [], out, "")
        except Invalid as err:
            raise Invalid(f"Row {e['_row']}: {err}") from None
        out[-1]["row"] = f"row {e['_row']}"
    return out


# ---- planning and importing -------------------------------------------------------------

def _existing(m: Maintenance) -> dict[tuple, dict]:
    """Every live item class by its path's keys."""
    out = {}
    for c in m.s.nodes(m.org, "ItemClass"):
        if not c.get("retired"):
            out[tuple(_key(x["name"]) for x in m._class_chain(c["id"]))] = c
    return out


def plan(m: Maintenance, rows: list[dict]) -> dict:
    """What importing ``rows`` would do: classes to create (with any parents a path
    names that aren't there), classes to fill in, conflicts left alone, and errors."""
    errors, conflicts, creates, updates = [], [], [], []
    if len(rows) > MAX_ITEM_CLASSES:
        return {"errors": [{"row": None, "error": f"At most {MAX_ITEM_CLASSES:,} classes at a time."}],
                "create": [], "update": [], "conflicts": [], "unchanged": 0}
    existing = _existing(m)
    # Every path's planned own attributes (existing classes' first), to find an
    # attribute that would appear twice on the way down.
    attrs: dict[tuple, list[dict]] = {k: list(c.get("attributes") or []) for k, c in existing.items()}
    seen: dict[tuple, str] = {}
    wanted: dict[tuple, dict] = {}
    for r in rows:
        try:
            names = [m._class_name_text(n) for n in r["path"]]
            if not names:
                raise Invalid("It has no name.")
            if len(names) > MAX_CLASS_DEPTH:
                raise Invalid(f"Item classes go at most {MAX_CLASS_DEPTH} levels deep.")
            key = tuple(_key(n) for n in names)
            if key in seen:
                raise Invalid(f"{' > '.join(names)} is listed twice (also {seen[key]}).")
            seen[key] = r["row"]
            fields = {"code": _text(r.get("code"), "code"), "level": _text(r.get("level"), "level", max_len=60),
                      "description": _text(r.get("description"), "description")}
            wanted[key] = {"row": r["row"], "names": names, "fields": fields,
                           "attributes": m._attributes(r.get("attributes") or [], "attributes")}
        except Invalid as err:
            errors.append({"row": r.get("row"), "error": str(err)})
    # Parents named only in a path are made too, with just their name.
    for key in list(wanted):
        for depth in range(1, len(key)):
            parent = key[:depth]
            if parent not in wanted and parent not in existing:
                wanted[parent] = {"row": wanted[key]["row"], "names": wanted[key]["names"][:depth],
                                  "fields": {"code": "", "level": "", "description": ""}, "attributes": [],
                                  "implied": True}
    unchanged = 0
    for key in sorted(wanted, key=lambda k: (len(k), k)):
        w = wanted[key]
        path = " > ".join(w["names"])
        node = existing.get(key)
        above = {_key(a["name"]): key[:d] for d in range(1, len(key)) for a in attrs.get(key[:d], [])}
        below = {_key(a["name"]) for k, own in attrs.items() if len(k) > len(key) and k[:len(key)] == key
                 for a in own}
        own = {_key(a["name"]): a for a in attrs.get(key, [])}
        added = []
        for a in w["attributes"]:
            k = _key(a["name"])
            if k in own:
                if {x: own[k].get(x) for x in ("unit", "kind", "options")} != \
                        {x: a.get(x) for x in ("unit", "kind", "options")}:
                    conflicts.append({"path": path, "attribute": a["name"],
                                      "why": "it already has this attribute, defined differently: kept as it is"})
            elif k in above:
                conflicts.append({"path": path, "attribute": a["name"],
                                  "why": "a class above it has this attribute (it's inherited): not added"})
            elif k in below:
                conflicts.append({"path": path, "attribute": a["name"],
                                  "why": "a class inside it has this attribute: not added"})
            else:
                added.append(a)
                own[k] = a
        attrs[key] = list(own.values())
        if node is None:
            creates.append({"path": path, "names": w["names"], "key": key, **w["fields"], "attributes": added,
                            "implied": bool(w.get("implied"))})
            continue
        changes = {f: v for f, v in w["fields"].items() if v and not node.get(f)}
        differs = [f for f, v in w["fields"].items() if v and node.get(f) and v != node.get(f)]
        for f in differs:
            conflicts.append({"path": path, "field": f, "why": f"its {f} is already {node.get(f)!r}: kept as it is"})
        if changes or added:
            updates.append({"path": path, "id": node["id"], "changes": changes,
                            "attributes_added": added, "attributes": list(node.get("attributes") or []) + added})
        else:
            unchanged += 1
    if len(existing) + len(creates) > MAX_ITEM_CLASSES:
        errors.append({"row": None, "error": f"That would make more than {MAX_ITEM_CLASSES:,} item classes."})
    return {"errors": errors, "create": creates, "update": updates, "conflicts": conflicts, "unchanged": unchanged}


def run(m: Maintenance, rows: list[dict], dry_run: bool = True, source: str = "") -> dict:
    """Import classes (see plan). With any error, or dry_run, nothing is written."""
    p = plan(m, rows)
    write = not dry_run and not p["errors"]
    if write:
        made: dict[tuple, str] = {k: c["id"] for k, c in _existing(m).items()}
        today = m.today()
        source = _text(source, "source")
        for c in p["create"]:
            cid = new_id()
            m._emit("item_class.created", {
                "id": cid, "name": c["names"][-1], "parent_id": made.get(c["key"][:-1]) if len(c["key"]) > 1 else None,
                "code": c["code"], "level": c["level"], "description": c["description"],
                "attributes": c["attributes"], "on": today} | ({"source": source} if source else {}))
            made[c["key"]] = cid
        for u in p["update"]:
            changes = dict(u["changes"]) | ({"attributes": u["attributes"]} if u["attributes_added"] else {})
            m._emit("item_class.updated", {"id": u["id"], "changes": changes, "on": today})
    brief = lambda c: {"path": c["path"], **{k: c[k] for k in ("code", "level") if c.get(k)},  # noqa: E731
                       "attributes": [a["name"] for a in c["attributes"]]} | ({"implied": True} if c["implied"] else {})
    return {
        "dry_run": not write, "ok": not p["errors"],
        "counts": {"create": len(p["create"]), "update": len(p["update"]), "unchanged": p["unchanged"],
                   "conflicts": len(p["conflicts"]), "errors": len(p["errors"])},
        "create": [brief(c) for c in p["create"][:SHOWN]],
        "update": [{"path": u["path"], "changes": u["changes"],
                    "attributes_added": [a["name"] for a in u["attributes_added"]]} for u in p["update"][:SHOWN]],
        "conflicts": p["conflicts"][:SHOWN], "errors": p["errors"][:SHOWN],
    }


# ---- exporting ------------------------------------------------------------------------

def export_rows(m: Maintenance) -> list[dict]:
    """Every live class, parents before children: path, code, level, description and
    its own attributes. Imports back as it was."""
    out = []

    def walk(nodes, above):
        for c in sorted(nodes, key=lambda c: c["name"].lower()):
            path = above + [c["name"]]
            out.append({"path": " > ".join(path), "code": c.get("code", ""), "level": c.get("level", ""),
                        "description": c.get("description", ""), "attributes": c.get("attributes") or []})
            walk(m._class_children(c["id"]), path)

    walk(m._class_children(None), [])
    return out


def export_json(m: Maintenance) -> dict:
    return {"format": "reliafy-item-classes", "version": 1, "classes": export_rows(m)}


def export_csv(m: Maintenance) -> str:
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["path", "code", "level", "description", "attributes"])
    for r in export_rows(m):
        w.writerow([r["path"], r["code"], r["level"], r["description"], attributes_text(r["attributes"])])
    return buf.getvalue()


# ---- the starter taxonomy ----------------------------------------------------------------
# Reliafy's own, in its own words: common plant and building equipment, a few typical
# attributes each. Not ISO 14224 or OREDA (and no codes): a place to start, to rename,
# extend or retire. Levels: group > class > type.

def _n(name, unit=""):
    return {"name": name, "unit": unit, "kind": "number"}


def _t(name):
    return {"name": name, "kind": "text"}


def _c(name, *options, unit=""):
    return {"name": name, "unit": unit, "kind": "choice", "options": list(options)}


def _types(*names):
    return [{"name": n, "level": "type"} for n in names]


STARTER = [
    {"name": "Rotating equipment", "level": "group",
     "description": "Machines that turn: they move fluids or transmit power.", "children": [
         {"name": "Pump", "level": "class", "description": "Moves a liquid.",
          "attributes": [_n("Flow", "m3/h"), _n("Head", "m"), _n("Power", "kW"), _n("Speed", "rpm")],
          "children": [
              {"name": "Centrifugal", "level": "type", "description": "An impeller throws the liquid outwards.",
               "attributes": [_n("Stages"), _n("Impeller diameter", "mm"),
                              _c("Shaft seal", "mechanical seal", "packing", "sealless")],
               "children": _types("End-suction", "Split-case", "Vertical multistage", "Submersible")},
              {"name": "Positive displacement", "level": "type",
               "description": "Traps a fixed volume and pushes it through.",
               "attributes": [_n("Discharge pressure", "bar")],
               "children": _types("Progressive cavity", "Gear", "Diaphragm", "Piston or plunger")},
          ]},
         {"name": "Compressor", "level": "class", "description": "Raises the pressure of a gas.",
          "attributes": [_n("Free air delivery", "m3/min"), _n("Discharge pressure", "bar"), _n("Power", "kW")],
          "children": _types("Reciprocating", "Rotary screw", "Centrifugal")},
         {"name": "Fan", "level": "class", "description": "Moves air or gas at low pressure.",
          "attributes": [_n("Air flow", "m3/h"), _n("Static pressure", "Pa"), _n("Power", "kW"), _n("Speed", "rpm")],
          "children": _types("Axial", "Centrifugal")},
         {"name": "Gearbox", "level": "class", "description": "Changes speed and torque between shafts.",
          "attributes": [_n("Ratio"), _n("Rated power", "kW"), _n("Input speed", "rpm"), _t("Oil grade")]},
         {"name": "Diesel engine", "level": "class", "description": "A compression-ignition engine.",
          "attributes": [_n("Power", "kW"), _n("Speed", "rpm"), _n("Cylinders"), _n("Displacement", "L")]},
     ]},
    {"name": "Electrical equipment", "level": "group",
     "description": "Equipment that makes, converts, switches or uses electric power.", "children": [
         {"name": "Electric motor", "level": "class", "description": "Turns electric power into rotation.",
          "attributes": [_n("Power", "kW"), _n("Voltage", "V"), _n("Full-load current", "A"), _n("Speed", "rpm"),
                         _t("Frame"), _c("Phases", "1", "3")],
          "children": _types("AC induction", "Permanent magnet", "DC")},
         {"name": "Generator", "level": "class", "description": "Turns rotation into electric power.",
          "attributes": [_n("Rating", "kVA"), _n("Voltage", "V"), _c("Frequency", "50", "60", unit="Hz"),
                         _n("Power factor")]},
         {"name": "Transformer", "level": "class", "description": "Changes the voltage of AC power.",
          "attributes": [_n("Rating", "kVA"), _n("Primary voltage", "V"), _n("Secondary voltage", "V"),
                         _c("Cooling", "dry", "oil-filled"), _t("Vector group")]},
         {"name": "Switchgear", "level": "class", "description": "Switches and protects electrical circuits.",
          "attributes": [_n("Rated voltage", "V"), _n("Rated current", "A"), _n("Fault rating", "kA")],
          "children": _types("Circuit breaker", "Switchboard", "Motor control centre")},
     ]},
    {"name": "Static equipment", "level": "group",
     "description": "Equipment with no moving machinery that holds, carries or controls fluids.", "children": [
         {"name": "Valve", "level": "class", "description": "Starts, stops or regulates flow.",
          "attributes": [_n("Size", "mm"), _t("Pressure rating"),
                         _c("Actuation", "manual", "electric", "pneumatic", "hydraulic", "self-acting"),
                         _t("Body material")],
          "children": _types("Gate", "Globe", "Ball", "Butterfly", "Check", "Pressure relief", "Control")},
         {"name": "Pressure vessel", "level": "class", "description": "Holds a fluid under pressure.",
          "attributes": [_n("Volume", "L"), _n("Design pressure", "bar"), _n("Design temperature", "°C"),
                         _t("Material")]},
         {"name": "Heat exchanger", "level": "class", "description": "Moves heat from one fluid to another.",
          "attributes": [_n("Duty", "kW"), _n("Design pressure", "bar")],
          "children": _types("Shell and tube", "Plate", "Air-cooled")},
     ]},
    {"name": "Materials handling", "level": "group", "description": "Equipment that moves solids.", "children": [
        {"name": "Conveyor", "level": "class", "description": "Carries bulk material or items along a path.",
         "attributes": [_n("Length", "m"), _n("Belt width", "mm"), _n("Speed", "m/s"), _n("Capacity", "t/h")],
         "children": _types("Belt", "Screw", "Roller", "Chain")},
    ]},
    {"name": "Instruments", "level": "group", "description": "Equipment that measures, indicates or signals.",
     "children": [
         {"name": "Instrument", "level": "class", "description": "Measures a process variable.",
          "attributes": [_c("Measures", "pressure", "temperature", "flow", "level", "analysis", "other"),
                         _t("Range"), _c("Output", "4-20 mA", "digital", "switch", "none")],
          "children": _types("Transmitter", "Switch", "Gauge", "Analyser")},
     ]},
    {"name": "Building services", "level": "group",
     "description": "Heating, cooling and hot water for buildings.", "children": [
         {"name": "HVAC unit", "level": "class", "description": "Heats, cools or ventilates a space.",
          "attributes": [_n("Cooling capacity", "kW"), _n("Heating capacity", "kW"), _t("Refrigerant"),
                         _n("Supply voltage", "V")],
          "children": _types("Split system", "Packaged unit", "Air handling unit", "Chiller")},
         {"name": "Water heater", "level": "class", "description": "Heats and stores hot water.",
          "attributes": [_n("Capacity", "L"), _n("Heating power", "kW"),
                         _c("Energy source", "electric", "gas", "heat pump", "solar", "other")]},
     ]},
]


def load_starter(m: Maintenance, dry_run: bool = True) -> dict:
    """Load the starter taxonomy (only on request). Run again, it adds only what's
    missing: nothing, if it's all there."""
    return {**run(m, rows_from_json(STARTER), dry_run, STARTER_SOURCE), "source": STARTER_SOURCE}
