"""The asset tree in a spreadsheet, both ways: export it (the whole tree or one
branch) to Excel or CSV, edit it, and import it again; or start a workspace from
a sheet made by hand.

One file format for both directions. The workbook's sheets:

* ``Hierarchy``: one row per position (the functional tree), with the item fitted
  there now. Columns: COLUMNS.
* ``Locations`` (optional): the physical tree, one row per location: ID, Path,
  Description. Locations no position names still come across.
* ``Classes`` (optional): the item class taxonomy: ID, Path, Code, Description.
* ``Read me``: what each column means (written on export, ignored on import).

A CSV is the Hierarchy sheet alone.

How a row finds its place and its match (the same rules the Read me sheet gives):

* Where it sits: its Path (``Plant 1 > Unit 2 > Feed pump A``; ``/`` also
  separates levels when the path has no ``>``). With no Path, its Parent ID (a
  row's ID in the file, or a position's id in Reliafy); blank is the top level.
  A parent that's neither in the file nor in Reliafy is a problem, never made up.
* Which position it is: its ID when that's a position in this workspace, else
  its Path. A match is updated with new events (name, tag, class, description,
  location) or left alone; anything else is made. A matched position moves only
  when its Path (or, with no Path, its Parent ID) puts it somewhere else.
* Nothing is ever deleted or cleared: a blank cell leaves the value as it is,
  and positions not in the file stay (the preview counts them).
* Items: a new position, or one with nothing fitted, gets the sheet's item
  fitted on Installed on (today when blank): an item.created and an item.fitted
  event, as fitting it by hand. An item already fitted is matched (Item ID, else
  serial, else name) and its details updated; a different item, or another
  date, is left alone with a note (fitments are history: change them through a
  work order or on the position's page).
* Locations and item classes named in the Hierarchy sheet are made when they
  don't exist yet, with the levels above them. Position classes are free text.

Every row is checked before anything is written; with any problem nothing is
written. ``dry_run`` reports what would happen. Redundancy sets, RCM, tasks and
measurements aren't in the file (export leaves them where they are; import
never touches them).
"""

from __future__ import annotations

import csv
import io
import re

from backend.maintenance.service import (
    MAX_ITEM_CLASSES, MAX_ITEMS, MAX_POSITIONS, Invalid, Maintenance, NotFound, _text, dated,
)

HIERARCHY, LOCATIONS, CLASSES, README = "Hierarchy", "Locations", "Classes", "Read me"
SEP = " > "
MAX_ROWS = 20_000  # a whole register's positions (MAX_POSITIONS) in one file
MAX_COLS = 50
MAX_CELL = 2000
MAX_PROBLEMS = 200  # listed; the count says how many in all

# The Hierarchy sheet's columns, in order: (field, heading, what it is).
COLUMNS = [
    ("id", "ID", "Reliafy's id for the position. Leave it as exported: it's how a row finds its position again "
                 "when a name or path changes. Blank for a new position (or your own codes: an ID only needs to "
                 "be unique in the file, for Parent ID)."),
    ("parent_id", "Parent ID", "The ID of the position it sits inside. Used only when Path is blank; written for "
                               "reference and for sheets from systems that list a parent rather than a path."),
    ("path", "Path", "Where it sits: every level from the top, separated by ' > ' (Plant 1 > Unit 2 > Feed pump A). "
                     "Change it to move a position. Its parent must be in the file or already in Reliafy."),
    ("name", "Name", "The position's name. Blank: the last part of the Path. Change it to rename (keep the Path "
                     "as it was, or change both)."),
    ("tag", "Tag", "Its tag or functional location code (P-101)."),
    ("position_class", "Position class", "What kind of position it is, to compare like with like "
                                         "(Centrifugal pump)."),
    ("description", "Description", "A short line on what it is."),
    ("location", "Location", "Where it physically is, as a path (Site A > Pump house), when set on the position "
                             "itself; positions inside it are there too. Made if it doesn't exist."),
    ("item_id", "Item ID", "Reliafy's id for the item fitted there now (as exported)."),
    ("item", "Fitted item", "The item fitted there now (its name)."),
    ("serial", "Item serial", "The item's serial number."),
    ("part_number", "Item part number", "The item's part number."),
    ("manufacturer", "Item manufacturer", "Who made it."),
    ("model", "Item model", "Its model."),
    ("item_class", "Item class", "The item's class, as a path in the class taxonomy (Rotating > Pump). Made if "
                                 "it doesn't exist."),
    ("installed_on", "Installed on", "When the item went in: a date (2024-03-15), or a month (2024-03) or year "
                                     "(2024) when that's all that's known. Blank: today."),
]
HEADINGS = [h for _, h, _ in COLUMNS]
LOCATION_COLUMNS = [("id", "ID", "Reliafy's id for the location."),
                    ("path", "Path", "Where it sits, every level from the top (Site A > Pump house)."),
                    ("description", "Description", "A short line on what it is.")]
CLASS_COLUMNS = [("id", "ID", "Reliafy's id for the item class."),
                 ("path", "Path", "Its place in the taxonomy (Rotating > Pump > Centrifugal)."),
                 ("code", "Code", "Your own code for it (to map to a standard you hold)."),
                 ("description", "Description", "A short line on what it is.")]

# Other names a column may go by in a sheet made elsewhere (matched without case or punctuation).
ALIASES = {
    "id": ("id", "position id", "floc id", "key"),
    "parent_id": ("parent id", "parent", "parent key", "superior", "superior floc"),
    "path": ("path", "position path", "position", "functional location", "floc", "hierarchy"),
    "name": ("name", "position name", "position name only", "title"),
    "tag": ("tag", "tag number", "floc code", "code"),
    "position_class": ("position class", "class", "equipment class", "type"),
    "description": ("description", "notes", "note"),
    "location": ("location", "location path", "site", "physical location"),
    "item_id": ("item id",),
    "item": ("fitted item", "item", "equipment", "item name"),
    "serial": ("item serial", "serial", "serial number", "serial no", "sn"),
    "part_number": ("item part number", "part number", "part no", "pn"),
    "manufacturer": ("item manufacturer", "manufacturer", "make", "oem"),
    "model": ("item model", "model", "model number"),
    "item_class": ("item class",),
    "installed_on": ("installed on", "installed", "install date", "fitted", "fitted on", "in service"),
}
SIDE_ALIASES = {"id": ("id",), "path": ("path", "location", "class", "name"), "code": ("code",),
                "description": ("description", "notes")}


def _norm(text) -> str:
    return re.sub(r"[^a-z0-9]+", " ", str(text or "").lower()).strip()


def split_path(value) -> list[str]:
    """A path's levels. ``>`` (or ``›``) separates them; in a path with neither,
    ``/`` or ``\\`` does. So ``Plant > I/O panel`` keeps its slash."""
    text = str(value or "")
    pattern = r"\s*[>›]\s*" if re.search(r"[>›]", text) else r"\s*[/\\]\s*"
    return [p.strip() for p in re.split(pattern, text) if p.strip()]


def _key(parts) -> str:
    return "\x1f".join(_norm(p) or p.lower() for p in parts)


def _columns(header, aliases) -> dict[str, str]:
    """Which sheet column feeds each field: the exact heading first, then an alias."""
    normed: dict[str, str] = {}
    for h in header:
        normed.setdefault(_norm(h), h)
    out: dict[str, str] = {}
    taken: set[str] = set()
    for field, names in aliases.items():
        for name in names:
            h = normed.get(_norm(name))
            if h is not None and h not in taken:
                out[field] = h
                taken.add(h)
                break
    return out


# ---- the workspace as the sheet sees it -------------------------------------------------

class Register:
    """The workspace's tree read in bulk: the positions a sheet can hold (live,
    not a product's design or a built unit's, not carried by an item), the places
    you look after, the item classes, and what's fitted where now."""

    def __init__(self, m: Maintenance):
        s, org = m.s, m.org
        self.m = m
        every = {p["id"]: p for p in s.nodes(org, "Position")}
        items = {i["id"]: i for i in s.nodes(org, "Item")}
        part_of: dict[str, str] = {}
        for src, dst in s.pairs(org, "PART_OF"):
            part_of.setdefault(src, dst)
        self.part_of = part_of
        product = m._product_position_ids()

        kept: dict[str, bool] = {}

        def keep(pid: str) -> bool:
            chain, ok = [], True
            node = pid
            while node is not None:
                if node in kept:
                    ok = kept[node]
                    break
                p = every.get(node)
                if p is None or p.get("retired") or node in product or node in chain:
                    ok = False
                    chain.append(node)
                    break
                chain.append(node)
                up = part_of.get(node)
                if up is not None and up not in every:  # inside an item (or something else): not a plain position
                    ok = False
                    break
                node = up
            for n in chain:
                kept[n] = ok
            return ok

        self.positions = {pid: every[pid] for pid in every if keep(pid)}
        self.retired = {pid for pid, p in every.items() if p.get("retired")}
        self.parent = {pid: part_of.get(pid) if part_of.get(pid) in self.positions else None
                       for pid in self.positions}
        self.children: dict[str | None, list[str]] = {}
        for pid, up in self.parent.items():
            self.children.setdefault(up, []).append(pid)
        for kids in self.children.values():
            kids.sort(key=lambda k: (self.positions[k]["name"].lower(), k))
        self._paths: dict[str, list[str]] = {}
        self.by_key: dict[str, list[str]] = {}
        for pid in self.positions:
            self.by_key.setdefault(_key(self.path(pid)), []).append(pid)

        # Places you look after (not a product's layout, not a built unit's).
        locs = {x["id"]: x for x in s.nodes(org, "Location")
                if not x.get("retired") and not x.get("design_of") and not x.get("carried_by")}
        self.locations = locs
        self.loc_parent = {lid: part_of.get(lid) if part_of.get(lid) in locs else None for lid in locs}
        self._loc_paths: dict[str, list[str]] = {}
        self.loc_by_key: dict[str, str] = {}
        for lid in sorted(locs):
            self.loc_by_key.setdefault(_key(self.loc_path(lid)), lid)
        self.own_location: dict[str, str] = {}
        for src, dst in s.pairs(org, "LOCATED_AT"):
            if src in self.positions:
                self.own_location.setdefault(src, dst)

        classes = {c["id"]: c for c in s.nodes(org, "ItemClass") if not c.get("retired")}
        self.classes = classes
        self.class_parent = {cid: part_of.get(cid) if part_of.get(cid) in classes else None for cid in classes}
        self._class_paths: dict[str, list[str]] = {}
        self.class_by_key: dict[str, str] = {}
        for cid in sorted(classes):
            self.class_by_key.setdefault(_key(self.class_path(cid)), cid)
        self.item_class: dict[str, str] = {}
        for src, dst in s.pairs(org, "CLASSED_AS"):
            if src in items:
                self.item_class.setdefault(src, dst)

        # What's fitted where now, and the latest day an item came out of each position.
        self.items = items
        fitments = {f["id"]: f for f in s.nodes(org, "Fitment") if not f.get("voided")}
        at = dict(s.pairs(org, "AT"))
        holder = {dst: src for src, dst in s.pairs(org, "IN")}
        self.fitted: dict[str, tuple[dict, dict]] = {}  # position -> (item, fitment)
        self.fitted_at: dict[str, str] = {}  # item -> position (anywhere)
        self.last_out: dict[str, str] = {}  # position -> latest removal day
        for fid, f in fitments.items():
            item_id, pos_id = holder.get(fid), at.get(fid)
            if not item_id or not pos_id or item_id not in items:
                continue
            if f.get("to") is None:
                self.fitted_at[item_id] = pos_id
                if pos_id in self.positions:
                    self.fitted[pos_id] = (items[item_id], f)
            elif pos_id in self.positions and f["to"] > self.last_out.get(pos_id, ""):
                self.last_out[pos_id] = f["to"]

    def path(self, pid: str) -> list[str]:
        if pid not in self._paths:
            chain, node = [], pid
            while node is not None and node not in self._paths:
                chain.append(node)
                node = self.parent.get(node)
            base = list(self._paths[node]) if node is not None else []
            for n in reversed(chain):
                base = base + [self.positions[n]["name"]]
                self._paths[n] = base
        return self._paths[pid]

    def loc_path(self, lid: str) -> list[str]:
        if lid not in self._loc_paths:
            up = self.loc_parent.get(lid)
            seen = self._loc_paths.setdefault(lid, [self.locations[lid]["name"]])  # a guard against loops
            self._loc_paths[lid] = (self.loc_path(up) if up else []) + seen[-1:]
        return self._loc_paths[lid]

    def class_path(self, cid: str) -> list[str]:
        if cid not in self._class_paths:
            up = self.class_parent.get(cid)
            seen = self._class_paths.setdefault(cid, [self.classes[cid]["name"]])
            self._class_paths[cid] = (self.class_path(up) if up else []) + seen[-1:]
        return self._class_paths[cid]

    def inside(self, pid: str) -> list[str]:
        """pid and every position below it, depth first, siblings by name."""
        out, stack = [], [pid]
        while stack:
            node = stack.pop()
            out.append(node)
            stack.extend(reversed(self.children.get(node, [])))
        return out


# ---- export -----------------------------------------------------------------------------------

def _installed(f: dict) -> str:
    day = f.get("from") or ""
    precision = f.get("from_precision")
    return day[:4] if precision == "year" else day[:7] if precision == "month" else day


def export(m: Maintenance, position_id: str | None = None) -> dict:
    """The tree as the sheet's rows: {hierarchy, locations, classes, counts,
    branch}. With position_id, that branch alone (full paths, so it imports back
    to where it is), with the locations and classes its rows name."""
    reg = Register(m)
    if position_id:
        if position_id not in reg.positions:
            node = m.s.node(m.org, position_id)
            if node is None or node.get("label") != "Position":
                raise NotFound(f"Position {position_id}")
            raise Invalid("That position can't be exported on its own: it's retired, part of a product's design "
                          "or an item built from one, or sits on an item. Export the tree it's in.")
        tops = [position_id]
    else:
        tops = reg.children.get(None, [])
    pids = [p for top in tops for p in reg.inside(top)]
    rows = []
    used_locs: set[str] = set()
    used_classes: set[str] = set()
    for pid in pids:
        p = reg.positions[pid]
        loc = reg.own_location.get(pid)
        loc = loc if loc in reg.locations else None
        row = {"id": pid, "parent_id": reg.parent[pid] or "", "path": SEP.join(reg.path(pid)), "name": p["name"],
               "tag": p.get("tag", ""), "position_class": p.get("position_class", ""),
               "description": p.get("description", ""),
               "location": SEP.join(reg.loc_path(loc)) if loc else ""}
        if loc:
            used_locs.add(loc)
        fitted = reg.fitted.get(pid)
        if fitted:
            item, f = fitted
            cid = reg.item_class.get(item["id"])
            cid = cid if cid in reg.classes else None
            if cid:
                used_classes.add(cid)
            row |= {"item_id": item["id"], "item": item.get("name", ""), "serial": item.get("serial", ""),
                    "part_number": item.get("part_number", ""), "manufacturer": item.get("manufacturer", ""),
                    "model": item.get("model", ""), "item_class": SEP.join(reg.class_path(cid)) if cid else "",
                    "installed_on": _installed(f)}
        rows.append({field: row.get(field, "") for field, _, _ in COLUMNS})

    def tree(parent_of, ids, path_of, wanted=None):
        if wanted is not None:  # with the levels above each
            keep = set()
            for x in wanted:
                while x and x not in keep:
                    keep.add(x)
                    x = parent_of.get(x)
            ids = [x for x in ids if x in keep]
        return sorted(ids, key=lambda x: [s.lower() for s in path_of(x)] + [x])

    loc_ids = tree(reg.loc_parent, list(reg.locations), reg.loc_path, used_locs if position_id else None)
    class_ids = tree(reg.class_parent, list(reg.classes), reg.class_path, used_classes if position_id else None)
    locations = [{"id": lid, "path": SEP.join(reg.loc_path(lid)),
                  "description": reg.locations[lid].get("description", "")} for lid in loc_ids]
    classes = [{"id": cid, "path": SEP.join(reg.class_path(cid)), "code": reg.classes[cid].get("code", ""),
                "description": reg.classes[cid].get("description", "")} for cid in class_ids]
    return {"hierarchy": rows, "locations": locations, "classes": classes,
            "counts": {"positions": len(rows), "items": sum(1 for r in rows if r["item"]),
                       "locations": len(locations), "classes": len(classes)},
            "branch": {"id": position_id, "path": SEP.join(reg.path(position_id))} if position_id else None}


def _readme_rows() -> list[list[str]]:
    out = [["Reliafy asset tree", ""],
           ["", ""],
           ["How to use this file", "Edit the Hierarchy sheet (and Locations and Classes if you like), then import it "
                                    "in the Explorer: the tree's ⋯ menu, Import from Excel. You see what will change "
                                    "before anything is written, and it all goes in or nothing does."],
           ["Matching", "A row finds its position by ID, else by Path. Matching rows are updated; new rows are added. "
                        "Importing the same file twice changes nothing the second time."],
           ["Moving", "Change a row's Path to move it (its parent must be in the file or already in Reliafy)."],
           ["Nothing is deleted", "Positions missing from the file stay as they are, and a blank cell never clears a "
                                  "value. Delete or clear things in the app."],
           ["Items", "An item is fitted where nothing is fitted yet. A different item, or another Installed on date, "
                     "for an item already fitted is left alone: replace items through a work order, and correct "
                     "dates on the position's page."],
           ["Dates", "Year-month-day (2024-03-15), or 2024-03 or 2024 when that's all that's known."],
           ["Not in this file", "Redundancy sets, RCM, tasks, measurements and history. An import leaves them as "
                                "they are."],
           ["", ""],
           ["Hierarchy sheet", "One row per position (the functional tree), with the item fitted there now."]]
    out += [[h, what] for _, h, what in COLUMNS]
    out += [["", ""], ["Locations sheet", "The physical tree. Locations named in the Hierarchy sheet are made too."]]
    out += [[h, what] for _, h, what in LOCATION_COLUMNS]
    out += [["", ""], ["Classes sheet", "The item class taxonomy. Classes named in the Hierarchy sheet are made too."]]
    out += [[h, what] for _, h, what in CLASS_COLUMNS]
    out += [["", ""], ["CSV", "A CSV file holds the Hierarchy sheet alone, with the same columns."]]
    return out


def to_xlsx(data: dict) -> bytes:
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font
    from openpyxl.utils import get_column_letter

    wb = Workbook()
    bold = Font(bold=True)

    def sheet(ws, columns, rows):
        ws.append([h for _, h, _ in columns])
        for r in rows:
            # Text cells throughout: a tag of 0012 or a date stays as written.
            ws.append([str(r.get(field, "") or "") for field, _, _ in columns])
        for cell in ws[1]:
            cell.font = bold
        ws.freeze_panes = "A2"
        for i, (field, heading, _) in enumerate(columns, start=1):
            longest = max([len(heading)] + [len(str(r.get(field, "") or "")) for r in rows[:500]])
            ws.column_dimensions[get_column_letter(i)].width = min(60, max(10, longest + 2))
            for row in ws.iter_rows(min_row=2, min_col=i, max_col=i):
                for cell in row:
                    cell.number_format = "@"

    ws = wb.active
    ws.title = HIERARCHY
    sheet(ws, COLUMNS, data["hierarchy"])
    sheet(wb.create_sheet(LOCATIONS), LOCATION_COLUMNS, data["locations"])
    sheet(wb.create_sheet(CLASSES), CLASS_COLUMNS, data["classes"])
    readme = wb.create_sheet(README)
    for r in _readme_rows():
        readme.append(r)
    readme["A1"].font = Font(bold=True, size=14)
    for row in readme.iter_rows(min_row=2):
        if row[0].value and not row[1].value:
            row[0].font = bold
        row[1].alignment = Alignment(wrap_text=True, vertical="top")
        row[0].alignment = Alignment(vertical="top")
    readme.column_dimensions["A"].width = 24
    readme.column_dimensions["B"].width = 100
    out = io.BytesIO()
    wb.save(out)
    return out.getvalue()


def to_csv(data: dict) -> bytes:
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\r\n")
    w.writerow(HEADINGS)
    for r in data["hierarchy"]:
        w.writerow([r.get(field, "") for field, _, _ in COLUMNS])
    return buf.getvalue().encode("utf-8-sig")  # the BOM: Excel opens it as UTF-8


def filename(data: dict, fmt: str, today: str) -> str:
    branch = (data.get("branch") or {}).get("path") or ""
    stem = re.sub(r"[^A-Za-z0-9 _-]+", "", branch.split(SEP)[-1] if branch else "").strip() or "Asset tree"
    return f"{stem} {today}.{fmt}"


# ---- reading a file ---------------------------------------------------------------------------

def _cell(v) -> str:
    if v is None:
        return ""
    if isinstance(v, float) and v.is_integer():
        v = int(v)
    return str(v).strip()


def _table(header, rows, numbers) -> list[tuple[int, dict]]:
    header = [str(h or "").strip() for h in header]
    if len(header) > MAX_COLS:
        raise Invalid(f"The sheet has {len(header)} columns; at most {MAX_COLS}. Keep the columns the Read me "
                      "sheet lists.")
    out = []
    for n, r in zip(numbers, rows):
        cells = [_cell(v) for v in r]
        if not any(cells):
            continue
        if any(len(c) > MAX_CELL for c in cells):
            raise Invalid(f"Row {n} has a cell over {MAX_CELL} characters.")
        out.append((n, dict(zip(header, cells + [""] * (len(header) - len(cells))))))
        if len(out) > MAX_ROWS:
            raise Invalid(f"At most {MAX_ROWS:,} rows at a time.")
    return out


def read_file(data: bytes, name: str = "") -> dict:
    """A workbook or CSV as {hierarchy, locations, classes}: each a list of
    (sheet row number, {heading: text})."""
    from backend.services import excel

    if excel.is_excel(data, name):
        try:
            sheets = [s["name"] for s in excel.inspect(data, name)["sheets"]]
            lower = {s.strip().lower(): s for s in sheets}
            main = lower.get(HIERARCHY.lower()) or next(
                (s for s in sheets if s.strip().lower() not in (LOCATIONS.lower(), CLASSES.lower(), README.lower())),
                None)
            if main is None:
                raise Invalid("The workbook has no Hierarchy sheet.")
            out = {}
            for key, sheet in (("hierarchy", main), ("locations", lower.get(LOCATIONS.lower())),
                               ("classes", lower.get(CLASSES.lower()))):
                if sheet is None:
                    out[key] = []
                    continue
                try:
                    t = excel.read_table(data, sheet=sheet, header_row=1, filename=name, max_rows=MAX_ROWS + 1)
                except excel.ExcelError:
                    if key == "hierarchy":
                        raise
                    out[key] = []  # an empty Locations or Classes sheet
                    continue
                out[key] = _table(t.header, t.rows, t.row_numbers)
            return out
        except excel.ExcelError as err:
            raise Invalid(str(err)) from None
    header = data.split(b"\n", 1)[0]
    if len(header) > 64 * 1024:
        raise Invalid("The first line is over 64 KB; it should be the column names.")
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = data.decode("latin-1")
    try:
        lines = list(csv.reader(io.StringIO(text, newline="")))
    except csv.Error as err:
        from backend.fitting import csv_error_message
        raise Invalid(csv_error_message(err, text)) from None
    if not lines:
        raise Invalid("The file is empty.")
    return {"hierarchy": _table(lines[0], lines[1:], range(2, len(lines) + 1)), "locations": [], "classes": []}


def rows_from_records(records: list[dict], first_row: int = 2) -> list[tuple[int, dict]]:
    """Rows given directly ({heading: value}, an MCP call's) as read_file's."""
    if not isinstance(records, list):
        raise Invalid("rows is a list of {column: value}.")
    if len(records) > MAX_ROWS:
        raise Invalid(f"At most {MAX_ROWS:,} rows at a time.")
    out = []
    for i, r in enumerate(records, start=first_row):
        if not isinstance(r, dict):
            raise Invalid(f"Row {i}: each row is an object of column: value.")
        if len(r) > MAX_COLS:
            raise Invalid(f"Row {i} has {len(r)} columns; at most {MAX_COLS}.")
        cells = {str(k).strip(): _cell(v) for k, v in r.items()}
        if any(len(v) > MAX_CELL for v in cells.values()):
            raise Invalid(f"Row {i} has a cell over {MAX_CELL} characters.")
        if any(cells.values()):
            out.append((i, cells))
    return out


def rows_from_csv(text: str) -> list[tuple[int, dict]]:
    return read_file(str(text or "").encode("utf-8"), "rows.csv")["hierarchy"]


# ---- the plan: every row checked, nothing written ------------------------------------------------

class _Row:
    __slots__ = ("n", "raw", "id", "parent_ref", "path", "path_given", "name", "match", "parent", "new_id",
                 "fields", "item", "parts", "bad")

    def __init__(self, n, raw):
        self.n, self.raw = n, raw
        self.match = None  # an existing position's id
        self.parent = None  # ("row", _Row) | ("pos", id) | None (the top)
        self.new_id = None
        self.parts = None
        self.bad = False


class _Plan:
    def __init__(self, m: Maintenance):
        self.m = m
        self.reg = Register(m)
        self.problems: list[dict] = []
        self.notes: list[dict] = []
        self.n_problems = 0
        self.rows: list[_Row] = []
        self.loc_new: dict[str, dict] = {}  # key -> {parts, description, row}
        self.loc_update: dict[str, dict] = {}  # id -> changes
        self.class_new: dict[str, dict] = {}
        self.class_update: dict[str, dict] = {}
        self.cols: dict[str, str] = {}
        self.matched: dict[str, _Row] = {}

    def problem(self, sheet: str, n: int | None, text: str) -> None:
        self.n_problems += 1
        if len(self.problems) < MAX_PROBLEMS:
            self.problems.append({"sheet": sheet, "row": n, "text": text})

    def note(self, sheet: str, n: int | None, text: str) -> None:
        if len(self.notes) < MAX_PROBLEMS:
            self.notes.append({"sheet": sheet, "row": n, "text": text})

    # -- locations and classes: found by path, made with the levels above them

    def location(self, parts: list[str], n: int, sheet: str = HIERARCHY, description: str = "") -> str | None:
        """The key of the location at parts (existing or to be made)."""
        reg = self.reg
        for depth in range(1, len(parts) + 1):
            k = _key(parts[:depth])
            if k in reg.loc_by_key or k in self.loc_new:
                continue
            try:
                _text(parts[depth - 1], "location's name", required=True)
            except Invalid as err:
                self.problem(sheet, n, f"{err}")
                return None
            self.loc_new[k] = {"parts": parts[:depth], "description": "", "row": n}
        k = _key(parts)
        if description and k in self.loc_new:
            self.loc_new[k]["description"] = description
        return k

    def item_class(self, parts: list[str], n: int, sheet: str = HIERARCHY, code: str = "",
                   description: str = "") -> str | None:
        reg = self.reg
        for depth in range(1, len(parts) + 1):
            k = _key(parts[:depth])
            if k in reg.class_by_key or k in self.class_new:
                continue
            try:
                self.m._class_name_text(parts[depth - 1])
            except Invalid as err:
                self.problem(sheet, n, f"{err}")
                return None
            self.class_new[k] = {"parts": parts[:depth], "code": "", "description": "", "row": n}
        k = _key(parts)
        if k in self.class_new:
            self.class_new[k]["code"] = code or self.class_new[k]["code"]
            self.class_new[k]["description"] = description or self.class_new[k]["description"]
        return k

    def side_sheets(self, sheets: dict) -> None:
        reg = self.reg
        for sheet, rows, is_loc in ((LOCATIONS, sheets.get("locations") or [], True),
                                    (CLASSES, sheets.get("classes") or [], False)):
            if not rows:
                continue
            cols = _columns(list(rows[0][1].keys()), SIDE_ALIASES)
            if "path" not in cols:
                self.problem(sheet, None, f"The {sheet} sheet has no Path column.")
                continue
            for n, raw in rows:
                get = lambda f: raw.get(cols[f], "") if f in cols else ""  # noqa: E731
                parts = split_path(get("path"))
                if not parts:
                    self.problem(sheet, n, "The path is blank.")
                    continue
                rid = get("id")
                known = reg.locations if is_loc else reg.classes
                path_of = reg.loc_path if is_loc else reg.class_path
                by_key = reg.loc_by_key if is_loc else reg.class_by_key
                existing = rid if rid in known else by_key.get(_key(parts))
                desc = get("description")
                code = get("code")
                try:
                    _text(desc, "description")
                    _text(code, "code")
                except Invalid as err:
                    self.problem(sheet, n, str(err))
                    continue
                what = "location" if is_loc else "item class"
                if existing:
                    if _key(path_of(existing)) != _key(parts):
                        self.note(sheet, n, f"The {what} {SEP.join(path_of(existing))} isn't renamed or moved by an "
                                            "import: do that in the app.")
                    node = known[existing]
                    changes = {}
                    if desc and desc != node.get("description", ""):
                        changes["description"] = desc
                    if not is_loc and code and code != node.get("code", ""):
                        changes["code"] = code
                    if changes:
                        (self.loc_update if is_loc else self.class_update)[existing] = changes
                elif is_loc:
                    self.location(parts, n, sheet, desc)
                else:
                    self.item_class(parts, n, sheet, code, desc)

    # -- the hierarchy rows

    def hierarchy(self, rows: list[tuple[int, dict]]) -> None:
        reg, m = self.reg, self.m
        if not rows:
            self.problem(HIERARCHY, None, "The Hierarchy sheet has no rows.")
            return
        header: dict[str, None] = {}
        for _, raw in rows:  # rows given directly may each name a few columns
            header.update(dict.fromkeys(raw))
        cols = _columns(list(header), ALIASES)
        self.cols = cols
        if "path" not in cols and "name" not in cols:
            self.problem(HIERARCHY, None, "There's no Path column (Plant 1 > Unit 2 > Feed pump A), or Name with "
                                          "Parent ID.")
            return
        for n, raw in rows:
            r = _Row(n, raw)
            get = lambda f: raw.get(cols[f], "") if f in cols else ""  # noqa: E731
            r.id = get("id")
            r.parent_ref = get("parent_id")
            r.path = split_path(get("path"))
            r.path_given = bool(r.path)
            r.name = get("name") or (r.path[-1] if r.path else "")
            r.fields = {f: get(f) for f in ("tag", "position_class", "description")}
            r.fields["location"] = split_path(get("location"))
            r.item = {f: get(f) for f in ("item_id", "item", "serial", "part_number", "manufacturer", "model",
                                         "installed_on")}
            r.item["class"] = split_path(get("item_class"))
            try:
                if not r.name:
                    raise Invalid("The position's name is blank: give a Path or a Name.")
                _text(r.name, "position's name", required=True)
                for part in r.path:
                    _text(part, "position's name")
                _text(r.fields["tag"], "tag")
                _text(r.fields["position_class"], "class")
                _text(r.fields["description"], "description")
                for f, what in (("item", "item's name"), ("serial", "serial"), ("part_number", "part number"),
                                ("manufacturer", "manufacturer"), ("model", "model")):
                    _text(r.item[f], what)
                if any(r.item[f] for f in ("serial", "part_number", "manufacturer", "model", "installed_on")) \
                        and not (r.item["item"] or r.item["item_id"]):
                    raise Invalid("item details without a Fitted item: name the item.")
                if r.item["installed_on"]:
                    r.item["installed_on"] = _installed_text(r.item["installed_on"])
                    day, _ = dated(r.item["installed_on"], None, "Installed on date", today=m.today())
                    if day > m.latest_day():
                        raise Invalid(f"Installed on ({day}) is in the future.")
            except Invalid as err:
                self.problem(HIERARCHY, n, str(err).rstrip(".") + ".")
                r.bad = True
            self.rows.append(r)

        by_id: dict[str, _Row] = {}
        for r in self.rows:
            if r.id:
                if r.id in by_id:
                    self.problem(HIERARCHY, r.n, f"The ID {r.id} is on row {by_id[r.id].n} too: each row's ID must "
                                                 "be unique.")
                    r.bad = True
                else:
                    by_id[r.id] = r
        self.by_id = by_id

        # Each row's own path: given, or built from its Parent ID chain.
        def parts_of(r: _Row, seen=()) -> list[str] | None:
            if r.parts is not None:
                return r.parts
            if r.path_given:
                r.parts = r.path[:-1] + [r.path[-1]]
                return r.parts
            if r.parent_ref:
                if r.parent_ref in by_id and r.parent_ref not in seen and by_id[r.parent_ref] is not r:
                    up = parts_of(by_id[r.parent_ref], seen + (r.id,))
                    r.parts = None if up is None else up + [r.name]
                elif r.parent_ref in reg.positions:
                    r.parts = reg.path(r.parent_ref) + [r.name]
                else:
                    r.parts = None
            else:
                r.parts = [r.name]
            return r.parts

        for r in self.rows:
            parts_of(r)
        by_key: dict[str, list[_Row]] = {}
        for r in self.rows:
            if r.parts:
                by_key.setdefault(_key(r.parts), []).append(r)

        # Which position each row is.
        matched: dict[str, _Row] = {}
        for r in self.rows:
            if r.id and r.id in reg.positions:
                r.match = r.id
            elif r.id and (m.s.node(m.org, r.id) or {}).get("label") == "Position":
                self.problem(HIERARCHY, r.n, f"ID {r.id} is a position that's been deleted, or that sits on an item "
                                             "or in a product's design: restore it first, or clear the ID to make "
                                             "a new one.")
                r.bad = True
                continue
            elif r.parts:
                found = reg.by_key.get(_key(r.parts), [])
                found = [f for f in found if f not in by_id]  # positions their own rows (by ID) are about
                if len(found) == 1:
                    r.match = found[0]
                elif len(found) > 1:
                    self.problem(HIERARCHY, r.n, f"{len(found)} positions in Reliafy have the path "
                                                 f"{SEP.join(r.parts)}: add the ID column (export the tree to get "
                                                 "it) so each row says which.")
                    r.bad = True
            if r.match:
                if r.match in matched:
                    self.problem(HIERARCHY, r.n, f"Row {matched[r.match].n} is the same position "
                                                 f"({SEP.join(reg.path(r.match))}).")
                    r.bad = True
                else:
                    matched[r.match] = r
        self.matched = matched

        # Two new rows with one path can't be told apart (with different IDs they can).
        for k, rs in by_key.items():
            if len(rs) > 1:
                ids = [x.id for x in rs]
                if any(not i for i in ids):
                    for x in rs[1:]:
                        self.problem(HIERARCHY, x.n, f"Same path as row {rs[0].n} ({SEP.join(rs[0].parts)}): "
                                                     "positions side by side need different names (or each row "
                                                     "an ID, with Parent ID on the rows inside them).")
                        x.bad = True

        # Where each row sits.
        for r in self.rows:
            if r.bad:
                continue
            ref = None
            if r.parent_ref:
                if r.parent_ref in by_id and by_id[r.parent_ref] is not r:
                    ref = ("row", by_id[r.parent_ref])
                elif r.parent_ref in reg.positions:
                    ref = ("pos", r.parent_ref)
            if r.path_given:
                up = r.parts[:-1]
                if not up:
                    r.parent = None
                    continue
                if ref is not None:
                    ref_parts = ref[1].parts if ref[0] == "row" else reg.path(ref[1])
                    if ref_parts is not None and _key(ref_parts) == _key(up):
                        r.parent = ref
                        continue
                if r.match and _key(reg.path(r.match)) == _key(r.parts):
                    # Where it is now: unchanged (whatever its parent's own row says).
                    cur = reg.parent[r.match]
                    r.parent = ("row", matched[cur]) if cur in matched else ("pos", cur) if cur else None
                    continue
                options: list = [("row", x) for x in by_key.get(_key(up), [])]
                taken = {x[1].match for x in options if x[1].match}
                options += [("pos", p) for p in reg.by_key.get(_key(up), []) if p not in taken and p not in matched]
                if len(options) == 1:
                    r.parent = options[0]
                elif not options:
                    self.problem(HIERARCHY, r.n, f"Its parent {SEP.join(up)} isn't in the file or in Reliafy: add a "
                                                 "row for it, or correct the path.")
                    r.bad = True
                else:
                    self.problem(HIERARCHY, r.n, f"More than one position is {SEP.join(up)}: give this row a Parent "
                                                 "ID to say which.")
                    r.bad = True
            elif r.parent_ref:
                if ref is None:
                    self.problem(HIERARCHY, r.n, f"Its Parent ID {r.parent_ref} isn't a row in the file or a "
                                                 "position in Reliafy.")
                    r.bad = True
                else:
                    r.parent = ref
            else:
                r.parent = None

        # The tree that results must be a tree: no position inside itself.
        def canon(node):
            """A node as one identity: a matched row is its position."""
            if node is None:
                return None
            if node[0] == "row":
                return ("pos", node[1].match) if node[1].match else ("row", id(node[1]))
            return node

        rows_by_obj = {id(r): r for r in self.rows}

        def up(ident):
            kind, x = ident
            r = rows_by_obj[x] if kind == "row" else matched.get(x)
            if r is not None:
                return "stop" if r.bad else canon(r.parent)
            p = reg.parent.get(x)
            return ("pos", p) if p else None

        for r in self.rows:
            if r.bad or r.parent is None:
                continue
            me = canon(("row", r))
            node, steps = canon(r.parent), 0
            while node is not None and node != "stop" and steps <= len(self.rows) + len(reg.positions):
                if node == me:
                    self.problem(HIERARCHY, r.n, f"{r.name} would end up inside itself: check its Path.")
                    r.bad = True
                    break
                node = up(node)
                steps += 1

        # A bad parent makes the rows inside it bad too (their place is unknown).
        changed = True
        while changed:
            changed = False
            for r in self.rows:
                if not r.bad and r.parent and r.parent[0] == "row" and r.parent[1].bad:
                    r.bad = True
                    changed = True
                    self.problem(HIERARCHY, r.n, f"Row {r.parent[1].n} (its parent) has a problem: fix that first.")

        # Locations and item classes the rows name.
        for r in self.rows:
            if r.bad:
                continue
            if r.fields["location"]:
                r.fields["location_key"] = self.location(r.fields["location"], r.n)
            if r.item["class"]:
                r.item["class_key"] = self.item_class(r.item["class"], r.n)

        # Items.
        today = m.today()
        for r in self.rows:
            if r.bad:
                continue
            it = r.item
            it["action"] = None
            if not (it["item"] or it["item_id"]):
                if r.match and r.match in reg.fitted and "item" in cols:
                    pass  # blank: left as it is (an import never takes an item out)
                continue
            fitted = reg.fitted.get(r.match) if r.match else None
            if fitted:
                item, f = fitted
                same = (it["item_id"] == item["id"]) if it["item_id"] else (
                    (it["serial"] and it["serial"] == item.get("serial")) or
                    (not it["serial"] or not item.get("serial")) and it["item"].lower() == item.get("name", "").lower())
                if not same:
                    self.note(HIERARCHY, r.n, f"{item.get('name')} is fitted at {r.name} now; the sheet's "
                                              f"{it['item'] or it['item_id']} wasn't fitted (replace it through a "
                                              "work order).")
                    continue
                changes = {k: it[k] for k in ("serial", "part_number", "manufacturer", "model")
                           if it[k] and it[k] != item.get(k, "")}
                if it["item"] and it["item"] != item.get("name"):
                    changes["name"] = it["item"]
                it["action"] = ("update", item["id"], changes)
                if it["installed_on"] and _installed(f) and it["installed_on"] != _installed(f):
                    self.note(HIERARCHY, r.n, f"{item.get('name')} went in on {_installed(f)} by the record; the "
                                              f"sheet's {it['installed_on']} wasn't applied (correct a date on the "
                                              "position's page).")
                continue
            if it["item_id"] and it["item_id"] not in reg.items:
                # Another workspace's id (an export brought here): a new item, by its name.
                if not it["item"]:
                    self.problem(HIERARCHY, r.n, f"Item ID {it['item_id']} isn't an item in Reliafy: give the "
                                                 "Fitted item's name to make it.")
                    r.bad = True
                    continue
                it["item_id"] = ""
            if it["item_id"]:
                node = reg.items.get(it["item_id"])
                if node.get("retired"):
                    self.problem(HIERARCHY, r.n, f"{node['name']} (Item ID {it['item_id']}) has been retired: "
                                                 "restore it first, or clear the Item ID to make a new item.")
                    r.bad = True
                    continue
                if it["item_id"] in reg.fitted_at:
                    where = reg.fitted_at[it["item_id"]]
                    where = SEP.join(reg.path(where)) if where in reg.positions else "another position"
                    self.problem(HIERARCHY, r.n, f"{node['name']} is fitted at {where}: an import doesn't move "
                                                 "items (move it in the app).")
                    r.bad = True
                    continue
            day = it["installed_on"] or today
            last = reg.last_out.get(r.match, "") if r.match else ""
            if last and dated(day, None, "Installed on date", today=today)[0] < last:
                self.problem(HIERARCHY, r.n, f"Installed on {day} is before the last item came out "
                                             f"({last}).")
                r.bad = True
                continue
            if not it["installed_on"]:
                it["defaulted"] = True
            it["action"] = ("fit", it["item_id"] or None, None)

    def updates(self, r: _Row) -> dict:
        """What changes on a matched position (blank cells change nothing)."""
        node = self.reg.positions[r.match]
        out = {}
        if "name" in self.cols or r.path_given:
            if r.name and r.name != node["name"]:
                out["name"] = r.name
        for f in ("tag", "position_class", "description"):
            if r.fields[f] and r.fields[f] != node.get(f, ""):
                out[f] = r.fields[f]
        return out

    def report(self, dry_run: bool) -> dict:
        reg = self.reg
        good = [r for r in self.rows if not r.bad]
        created = [r for r in good if not r.match]
        moved, updated, unchanged = [], [], []
        for r in good:
            if not r.match:
                continue
            cur = reg.parent[r.match]
            target = r.parent
            target_id = (target[1].match or "new") if target and target[0] == "row" else target[1] if target else None
            changes = self.updates(r)
            loc_change = self._location_change(r)
            if target_id != cur:
                moved.append(r)
            if changes or loc_change:
                updated.append(r)
            if target_id == cur and not changes and not loc_change:
                unchanged.append(r)
        # Positions under the file's top rows that the file leaves out.
        tops = {r.match for r in good if r.match and not (r.parent and r.parent[0] == "row")}
        inside = set()
        for t in tops:
            inside.update(reg.inside(t))
        not_in_file = len(inside - set(self.matched))
        items_new = sum(1 for r in good if r.item.get("action") and r.item["action"][0] == "fit"
                        and not r.item["action"][1])
        items_fitted = sum(1 for r in good if r.item.get("action") and r.item["action"][0] == "fit")
        items_updated = sum(1 for r in good if r.item.get("action") and r.item["action"][0] == "update"
                            and (r.item["action"][2] or self._class_change(r)))
        defaulted = sum(1 for r in good if r.item.get("defaulted") and r.item.get("action"))
        m = self.m
        limits = {
            "positions": {"now": m.s.count(m.org, "Position"), "adding": len(created),
                          "max": MAX_POSITIONS},
            "items": {"now": m.s.count(m.org, "Item"), "adding": items_new, "max": MAX_ITEMS},
            "item_classes": {"now": m.s.count(m.org, "ItemClass"), "adding": len(self.class_new),
                             "max": MAX_ITEM_CLASSES},
        }
        for k, lim in limits.items():
            lim["room"] = max(0, lim["max"] - lim["now"])
            lim["fits"] = (not m.limited) or lim["adding"] <= lim["room"]
            if not lim["fits"]:
                what = {"positions": "positions", "items": "items", "item_classes": "item classes"}[k]
                self.problem(HIERARCHY, None, f"This workspace can hold {lim['max']:,} {what}; it has "
                                              f"{lim['now']:,}, so there's room for {lim['room']:,} and the file "
                                              f"adds {lim['adding']:,}.")
        if defaulted:
            self.note(HIERARCHY, None, f"{defaulted} item{'s' if defaulted != 1 else ''} with no Installed on date "
                                       f"go in as fitted today ({m.today()}).")
        counts = {
            "rows": len(self.rows),
            "positions_created": len(created), "positions_updated": len(updated), "positions_moved": len(moved),
            "positions_unchanged": len(unchanged), "not_in_file": not_in_file,
            "locations_created": len(self.loc_new), "locations_updated": len(self.loc_update),
            "classes_created": len(self.class_new), "classes_updated": len(self.class_update),
            "items_created": items_new, "items_fitted": items_fitted, "items_updated": items_updated,
        }
        out = {"dry_run": dry_run, "ok": self.n_problems == 0, **counts,
               "problems": self.problems, "problem_count": self.n_problems, "notes": self.notes,
               "limits": limits, "moves": [{"row": r.n, "name": r.name, "from": SEP.join(reg.path(r.match)),
                                            "to": SEP.join(self.final_path(r))} for r in moved[:50]],
               "summary": summary_text(counts, self.n_problems, dry_run)}
        return out

    def final_path(self, r: _Row) -> list[str]:
        out, node, guard = [r.name], r.parent, 0
        while node is not None and guard < 10_000:
            guard += 1
            if node[0] == "row":
                out.append(node[1].name)
                node = node[1].parent
            else:
                return self.reg.path(node[1]) + list(reversed(out))
        return list(reversed(out))

    def _location_change(self, r: _Row) -> bool:
        k = r.fields.get("location_key")
        if not k:
            return False
        lid = self.reg.loc_by_key.get(k)
        return lid is None or self.reg.own_location.get(r.match) != lid

    def _class_change(self, r: _Row) -> bool:
        k = r.item.get("class_key")
        if not k:
            return False
        cid = self.reg.class_by_key.get(k)
        action = r.item.get("action")
        return cid is None or (action and action[0] == "update" and self.reg.item_class.get(action[1]) != cid)

    # -- writing (only after a clean plan)

    def apply(self) -> None:
        m, reg = self.m, self.reg
        m.check_limits()  # one change, however many events
        loc_ids = dict(reg.loc_by_key)
        for k, spec in sorted(self.loc_new.items(), key=lambda kv: len(kv[1]["parts"])):
            parent = loc_ids.get(_key(spec["parts"][:-1])) if len(spec["parts"]) > 1 else None
            loc_ids[k] = m.create_location(spec["parts"][-1], parent, spec["description"])["id"]
        for lid, changes in self.loc_update.items():
            m.update_location(lid, **changes)
        class_ids = dict(reg.class_by_key)
        for k, spec in sorted(self.class_new.items(), key=lambda kv: len(kv[1]["parts"])):
            parent = class_ids.get(_key(spec["parts"][:-1])) if len(spec["parts"]) > 1 else None
            class_ids[k] = m.create_item_class(spec["parts"][-1], parent, code=spec["code"],
                                               description=spec["description"])["id"]
        for cid, changes in self.class_update.items():
            m.update_item_class(cid, **changes)

        # Positions, parents before what's inside them (in the tree that results).
        done: set[int] = set()
        order: list[_Row] = []

        def visit(r: _Row, depth=0):
            if id(r) in done or depth > 10_000:
                return
            if r.parent and r.parent[0] == "row":
                visit(r.parent[1], depth + 1)
            elif r.parent and r.parent[1] in self.matched:
                visit(self.matched[r.parent[1]], depth + 1)
            done.add(id(r))
            order.append(r)

        for r in self.rows:
            visit(r)

        def parent_id(r: _Row):
            if r.parent is None:
                return None
            if r.parent[0] == "row":
                x = r.parent[1]
                return x.match or x.new_id
            return r.parent[1]

        for r in order:
            loc = loc_ids.get(r.fields.get("location_key")) if r.fields.get("location_key") else None
            if not r.match:
                r.new_id = m.create_position(r.name, tag=r.fields["tag"], parent_id=parent_id(r),
                                             position_class=r.fields["position_class"],
                                             description=r.fields["description"], location_id=loc)["id"]
                continue
            changes = self.updates(r)
            pid = parent_id(r)
            if pid != reg.parent[r.match]:
                changes["parent_id"] = pid
            if loc and reg.own_location.get(r.match) != loc:
                changes["location_id"] = loc
            if changes:
                m.update_position(r.match, **changes)

        for r in self.rows:
            action = r.item.get("action")
            if not action:
                continue
            pid = r.match or r.new_id
            cid = class_ids.get(r.item.get("class_key")) if r.item.get("class_key") else None
            kind, item_id, changes = action
            if kind == "update":
                if changes:
                    m.update_item(item_id, **changes)
                if cid and reg.item_class.get(item_id) != cid:
                    m.assign_item_class(item_id, cid)
                continue
            it = r.item
            if not item_id:
                item_id = m.create_item(it["item"], serial=it["serial"], part_number=it["part_number"],
                                        manufacturer=it["manufacturer"], model=it["model"])["id"]
            m.fit(pid, item_id=item_id, on=it["installed_on"] or None)
            if cid:
                m.assign_item_class(item_id, cid)


def _installed_text(text: str) -> str:
    """Installed on as fit takes it: a year or a month kept rough, any other date to its day."""
    text = text.strip()
    if re.fullmatch(r"\d{4}(-\d{2})?", text):
        return text
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}([ T].*)?", text):
        return text[:10]
    import pandas as pd

    try:
        return pd.to_datetime(text, dayfirst=True).date().isoformat()
    except (ValueError, TypeError, OverflowError):
        raise Invalid(f"Installed on '{text}' isn't a date (write it as 2024-03-15).") from None


def _n(count: int, one: str, many: str | None = None) -> str:
    return f"{count:,} {one if count == 1 else many or one + 's'}"


def summary_text(c: dict, problems: int, dry_run: bool) -> str:
    """One line: 'Will create 312 positions, 40 locations, 18 classes and 290 items; 3 problems.'"""
    made = [_n(c[k], one, many) for k, one, many in (
        ("positions_created", "position", None), ("locations_created", "location", None),
        ("classes_created", "class", "classes"), ("items_created", "item", None)) if c.get(k)]
    changed = [verb + " " + _n(c[k], one) for k, verb, one in (
        ("positions_updated", "update", "position"), ("positions_moved", "move", "position"),
        ("items_updated", "update", "item")) if c.get(k)]
    if not dry_run:
        changed = [x.replace("update ", "updated ").replace("move ", "moved ") for x in changed]
    words = (["create " + _join(made)] if made and dry_run else ["created " + _join(made)] if made else []) + changed
    if not words:
        line = "Nothing to change: everything in the file is already in Reliafy" if not problems else "Nothing to import"
    else:
        line = ("Will " if dry_run else "") + _join(words)
        line = line[0].upper() + line[1:]
    if problems:
        return f"Fix {_n(problems, 'problem')} first: nothing is imported until then."
    return line + "."


def _join(xs: list[str]) -> str:
    return xs[0] if len(xs) == 1 else ", ".join(xs[:-1]) + " and " + xs[-1]


def run(m: Maintenance, sheets: dict, dry_run: bool = True) -> dict:
    """Check every row, then (not dry_run, and only with no problem) write it all.
    sheets: {hierarchy, locations?, classes?} as read_file gives them."""
    plan = _Plan(m)
    plan.side_sheets(sheets)
    plan.hierarchy(sheets.get("hierarchy") or [])
    out = plan.report(dry_run)
    if dry_run:
        return out
    if plan.n_problems:
        first = "; ".join((f"Row {p['row']}: " if p["row"] else "") + p["text"] for p in plan.problems[:5])
        raise Invalid(f"Nothing imported: {_n(plan.n_problems, 'problem')} to fix first. {first}")
    plan.apply()
    out["dry_run"] = False
    out["summary"] = summary_text({k: out[k] for k in out if isinstance(out[k], int)}, 0, False)
    return out
