"""Products: design trees, and the items built from them.

A *product* is a design: a top-level position tree flagged as a design (its
functional hierarchy: Airframe › Propulsion › Motor 1), with the catalogue part
it is (its physical structure, the bill of materials, lives on that part). It is
a template. Nothing is ever fitted to a design's positions and no failure is
reported there.

An *item* built from a product is the serial-numbered thing (the existing Item):
building one copies the design's tree to a new top-level tree named by the
serial, makes the item (of the product's part, with that serial), fits it into
the new tree's top position, and stamps every copied position with the design
position it implements (``position.implements``). That provenance survives a
rename or a move inside the item's tree; a design position retired later shows
as "design node gone", never silently unlinked.

Design-level answers are reads that group the built positions by the design
position they implement: the roll-up (items, what's fitted, pooled life data,
failure reports across items). A change to the design never reaches a built item
by itself; applying one is a later, explicit step.

Events (new types only; older logs replay unchanged):

* ``design.declared {position_id, part_id?, rev, on}``: a top-level tree is a
  product's design (again: a new revision label, or another part);
* ``design.cleared {position_id, on}``: it isn't any more;
* ``position.implements {position_id, design_position_id, design_rev}``: a
  built position and the design position it came from; the built tree's top
  also carries ``item_id`` and ``serial`` (the item built into it).
"""

from __future__ import annotations

from backend.maintenance.store import GraphStore

MAX_ITEM_LIST = 500  # items in one page of the items overview
SHOWN_PATHS = 200  # positions listed in a build's preview


# ---- projectors ---------------------------------------------------------------------------

def _design_declared(s: GraphStore, org: str, p: dict) -> None:
    pid = p["position_id"]
    s.patch_node(org, pid, {"design": {"rev": p.get("rev") or "", "part_id": p.get("part_id"), "on": p.get("on")}})
    for part in s.out(org, pid, "DESIGN_OF"):
        s.delete_edge(org, "DESIGN_OF", pid, part["id"])
    if p.get("part_id"):
        s.put_edge(org, "DESIGN_OF", pid, p["part_id"])


def _design_cleared(s: GraphStore, org: str, p: dict) -> None:
    pid = p["position_id"]
    s.patch_node(org, pid, {"design": None})
    for part in s.out(org, pid, "DESIGN_OF"):
        s.delete_edge(org, "DESIGN_OF", pid, part["id"])


def _position_implements(s: GraphStore, org: str, p: dict) -> None:
    pid = p["position_id"]
    s.patch_node(org, pid, {"design_position_id": p["design_position_id"], "design_rev": p.get("design_rev") or ""}
                 | ({"built_item_id": p["item_id"]} if p.get("item_id") else {})
                 | ({"built_serial": p["serial"]} if p.get("serial") else {}))
    s.put_edge(org, "IMPLEMENTS", pid, p["design_position_id"])


PROJECTORS = {
    "design.declared": _design_declared,
    "design.cleared": _design_cleared,
    "position.implements": _position_implements,
}


def _sv():
    from backend.maintenance import service

    return service


# ---- the operations (a mixin of Maintenance) ----------------------------------------------

class ProductOps:
    """Methods added to ``Maintenance``."""

    # -- where a position sits

    def _top_of(self, position_id: str) -> dict:
        """The top of a position's own tree (up through positions only: a position
        carried by an item stops at its top-most position)."""
        node = self._get(position_id, "Position")
        seen = {node["id"]}
        while True:
            parent = self._parent(node["id"])
            if parent is None or parent["label"] != "Position" or parent["id"] in seen:
                return node
            seen.add(parent["id"])
            node = parent

    def _design_root_of(self, position_id: str) -> dict | None:
        """The product design a position belongs to (its top, flagged), or None."""
        top = self._top_of(position_id)
        return top if top.get("design") else None

    def _tree_positions(self, root_id: str) -> list[dict]:
        """Every position in a tree (retired ones too), the top first: positions
        inside positions only, not those carried by an item fitted there."""
        out, queue, seen = [], [root_id], {root_id}
        while queue:
            nid = queue.pop(0)
            node = self.s.node(self.org, nid)
            if node is None:
                continue
            out.append(node)
            for c in self.s.inn(self.org, nid, "PART_OF"):
                if c["label"] == "Position" and c["id"] not in seen:
                    seen.add(c["id"])
                    queue.append(c["id"])
        return out

    def _live_design(self, product_id) -> dict:
        node = self._get(str(product_id or ""), "Position")
        if not node.get("design"):
            raise _sv().Invalid(f"{node['name']} isn't a product: declare its tree as a design first, or pick a "
                                "product from the list.")
        if node.get("retired"):
            raise _sv().Invalid(f"{node['name']} has been retired: restore it first.")
        return node

    # -- declaring a design

    def _design_part(self, part_id, but: str | None = None) -> dict | None:
        """The part a design is, checked: live, and not already another product's."""
        if part_id in (None, ""):
            return None
        part = self._live_part(part_id)
        for other in self.s.inn(self.org, part["id"], "DESIGN_OF"):
            if other["id"] != but and other.get("design") and not other.get("retired"):
                raise _sv().Invalid(f"Part {part['part_number']} is already the product {other['name']}. A part is "
                                    "one product; make a new part number for a variant.")
        return part

    def declare_design(self, position_id: str, part_id=None, rev=None) -> dict:
        """Make a top-level position tree a product's design (or change its revision
        label or part when it is one already). Refused for a position inside another,
        a tree with items fitted (now or before: that's a plant or an item, not a
        design), or a tree built from a design."""
        sv = _sv()
        node = self._get(position_id, "Position")
        if node.get("retired"):
            raise sv.Invalid(f"{node['name']} has been retired: restore it first.")
        if self._parent(position_id) is not None:
            raise sv.Invalid(f"{node['name']} sits inside another position. A product's design is a whole tree: "
                             "declare its top-level position.")
        tree = self._tree_positions(position_id)
        if any(p.get("design_position_id") for p in tree):
            raise sv.Invalid(f"{node['name']} was built from a product's design: it's an item's tree, not a design.")
        fitted = next((p for p in tree if self._fitments_at(p["id"])), None)
        if fitted:
            raise sv.Invalid(f"Items have been fitted in {node['name']} (at {fitted['name']}): it's a plant or an "
                             "item, not a design. A design has no items; build items from it instead.")
        now = node.get("design") or {}
        # part_id: None keeps the part it has; "" or "none" takes it off.
        part = self._design_part(part_id, but=position_id) if part_id not in (None, "", "none") else None
        rev_text = sv._text(now.get("rev", "") if rev is None else rev, "revision")[:sv.SHORT_TEXT]
        part_ref = part["id"] if part else (now.get("part_id") if part_id is None else None)
        self._emit("design.declared", {"position_id": position_id, "part_id": part_ref, "rev": rev_text,
                                       "on": self.today()})
        return self.product(position_id)

    def clear_design(self, product_id: str) -> dict:
        """The tree isn't a product's design any more (it becomes a plain tree). Refused
        while items built from it are in use: their provenance points at it."""
        sv = _sv()
        node = self._get(product_id, "Position")
        if not node.get("design"):
            raise sv.Invalid(f"{node['name']} isn't a product's design: nothing to clear.")
        built = [p for p in self._built_tops(product_id) if not p.get("retired")]
        if built:
            raise sv.Invalid(f"{len(built)} item{'s were' if len(built) != 1 else ' was'} built from {node['name']}: "
                             "it stays a product while they're in use (retire their trees first).")
        self._emit("design.cleared", {"position_id": product_id, "on": self.today()})
        return {"id": product_id, "name": node["name"], "design": None}

    def create_product(self, name, part_number="", rev="", description="", part_id=None) -> dict:
        """A new product: its design's top position and the part it is (a new part
        numbered part_number, or an existing part_id; neither: no part yet), declared
        together. Everything is checked before anything is written."""
        sv = _sv()
        name = sv._text(name, "product's name", required=True)
        description = sv._text(description, "description")
        rev = sv._text(rev, "revision")[:sv.SHORT_TEXT]
        number = sv._text(part_number, "part number")[:120]
        if number and part_id:
            raise sv.Invalid("Give part_number for a new part or part_id for one in the catalogue, not both.")
        part = self._design_part(part_id) if part_id else None
        if number and any(pt["part_number"].lower() == number.lower() for pt in self.s.nodes(self.org, "Part")):
            raise sv.Invalid(f"Part number {number} is already in the catalogue: pass its part_id to make it this "
                             "product, or choose another number.")
        self._quota("Position", sv.MAX_POSITIONS)
        if number:
            part = self.create_part(number, name)
        root = self.create_position(name, description=description)
        self._emit("design.declared", {"position_id": root["id"], "part_id": part["id"] if part else None,
                                       "rev": rev, "on": self.today()})
        return self.product(root["id"])

    # -- reading products

    def _built_tops(self, product_id: str) -> list[dict]:
        """The tops of the trees built from a product (retired ones too)."""
        return [p for p in self.s.inn(self.org, product_id, "IMPLEMENTS")
                if p["label"] == "Position" and self._parent(p["id"]) is None]

    def _top_item(self, top_id: str) -> dict | None:
        """The item fitted at a built tree's top now."""
        f = self.current_fitment(top_id)
        item = f and self.s.inn(self.org, f["id"], "IN")
        return item[0] if item else None

    def _built_serial(self, top: dict) -> str:
        item = self._top_item(top["id"])
        return (item or {}).get("serial") or top.get("built_serial") or ""

    def _open_report_ids(self, top_id: str | None = None, item_id: str | None = None) -> set[str]:
        """The open failure reports anywhere in a built tree (top_id), and those
        involving an item (item_id)."""
        wanted = set(self._report_scope(top_id)) if top_id else set()
        return {r["id"] for r in self.s.nodes(self.org, "FailureReport")
                if r["status"] in _sv().OPEN_REPORT_STATUSES
                and (r.get("position_id") in wanted or (item_id and r.get("item_id") == item_id))}

    def _open_reports_in(self, top_id: str) -> int:
        return len(self._open_report_ids(top_id))

    def _hours(self, item: dict | None, top_id: str) -> dict | None:
        """The item's hours: the latest reading of an hours counter on the item, else on
        its built tree's top position. None when neither has one (never guessed)."""
        sv = _sv()
        for node_id in ([item["id"]] if item else []) + [top_id]:
            counter = sv._counter_on(self.s, self.org, node_id, "hours")
            if counter:
                return {"value": self._latest_value(counter), "unit": counter.get("unit") or "hours",
                        "point_id": counter["id"]}
        return None

    def _part_view(self, part_id) -> dict | None:
        part = part_id and self.s.node(self.org, part_id, "Part")
        return {"id": part["id"], "part_number": part.get("part_number") or "", "name": part.get("name") or ""} \
            if part else None

    def _product_row(self, node: dict) -> dict:
        design = node.get("design") or {}
        tops = [p for p in self._built_tops(node["id"]) if not p.get("retired")]
        return {
            "id": node["id"], "name": node["name"], "description": node.get("description", ""),
            "part": self._part_view(design.get("part_id")), "rev": design.get("rev", ""),
            "declared_on": design.get("on"), "retired": bool(node.get("retired")),
            "positions": sum(1 for p in self._tree_positions(node["id"]) if not p.get("retired")),
            "items_built": len(tops), "open_reports": sum(self._open_reports_in(t["id"]) for t in tops),
        }

    def products(self) -> dict:
        """Every product (a design tree), by name: its part, revision, how many
        positions its design has, the items built from it and their open failure
        reports."""
        rows = [self._product_row(p) for p in self.s.nodes(self.org, "Position")
                if p.get("design") and not p.get("retired") and self._parent(p["id"]) is None]
        return {"products": sorted(rows, key=lambda r: r["name"].lower())}

    def product(self, product_id: str) -> dict:
        """One product: as in the list."""
        node = self._get(product_id, "Position")
        if not node.get("design"):
            raise _sv().Invalid(f"{node['name']} isn't a product.")
        return self._product_row(node)

    def product_items(self, product_id: str) -> dict:
        """The items built from a product, by serial: each with its revision, the day
        it was built, where it is, its hours (when it has an hours counter), open
        failure reports in its tree, its tree's top position and the item."""
        design = self._get(product_id, "Position")
        if not design.get("design"):
            raise _sv().Invalid(f"{design['name']} isn't a product.")
        rows = []
        for top in self._built_tops(product_id):
            if top.get("retired"):
                continue
            item = self._top_item(top["id"])
            where = self._location_view(top["id"])
            rows.append({
                "serial": self._built_serial(top), "rev": top.get("design_rev", ""), "built_on": top.get("created"),
                "item": {k: item.get(k) for k in ("id", "name", "serial")} if item else None,
                "top_position_id": top["id"], "name": top["name"],
                "location": where and {"id": where["id"], "name": where["name"], "display": where["display"]},
                "hours": self._hours(item, top["id"]), "open_reports": self._open_reports_in(top["id"]),
                "out_of_service": self._service_view(top["id"]),
            })
        rows.sort(key=lambda r: (r["serial"].lower(), r["name"].lower()))
        return {"product": {"id": design["id"], "name": design["name"]}, "items": rows}

    # -- building an item

    def _product_serials(self, design: dict) -> set[str]:
        """Serials already used by an item of this product: of its part, or built from it."""
        out = set()
        part_id = (design.get("design") or {}).get("part_id")
        if part_id:
            out |= {_key(i.get("serial")) for i in self.s.inn(self.org, part_id, "OF_PART") if i["label"] == "Item"}
        for top in self._built_tops(design["id"]):
            out.add(_key(self._built_serial(top)))
            for f in self._fitments_at(top["id"]):
                out |= {_key(i.get("serial")) for i in self.s.inn(self.org, f["id"], "IN")}
        return out - {""}

    def build_item(self, product_id: str, serial, rev=None, name=None, dry_run: bool = True) -> dict:
        """Build an item from a product: copy the design's tree to the top level (named
        name, default "<product> · <serial>"), make the item (of the product's part,
        with this serial), fit it into the new tree's top and stamp every copied position
        with the design position it implements. rev: the revision it's built to (default
        the design's). dry_run (the default) only says what it would make."""
        sv = _sv()
        design = self._live_design(product_id)
        serial = sv._text(serial, "serial", required=True)
        if _key(serial) in self._product_serials(design):
            raise sv.Invalid(f"Serial {serial} is already used by an item of {design['name']}.")
        info = design.get("design") or {}
        rev_text = sv._text(info.get("rev", "") if rev is None else rev, "revision")[:sv.SHORT_TEXT]
        top_name = sv._text(name or f"{design['name']} · {serial}", "item's name", required=True)
        part = self._live_part(info["part_id"]) if info.get("part_id") else None
        new = sv.new_id()
        plan = self._copy_read(design, new, top_name, None)
        names: dict[str, list[str]] = {}
        rows = []
        for src, pid, label, parent, modes, tasks, listings, _ in plan:
            names[pid] = (names[parent] if parent else []) + [label]
            rows.append({"path": " › ".join(names[pid]), "design_position_id": src["id"],
                         "retired": bool(src.get("retired"))})
        counts = {"positions": len(plan), "failure_modes": sum(len(x[4]) for x in plan),
                  "tasks": sum(len(x[5]) for x in plan), "parts_list": sum(len(x[6]) for x in plan)}
        out = {"dry_run": dry_run, "product": {"id": design["id"], "name": design["name"]}, "serial": serial,
               "rev": rev_text, "name": top_name,
               "item": {"name": top_name, "serial": serial, "part": self._part_view(part and part["id"])},
               "counts": counts, "positions": rows[:SHOWN_PATHS], "top_position_id": None}
        if dry_run:
            return out
        self._quota("Item", sv.MAX_ITEMS)
        self._quota("Position", sv.MAX_POSITIONS, adding=len(plan))
        mapping = {src["id"]: pid for src, pid, *_ in plan}
        self._copy_write(plan, new, None, self.today())
        item = self.create_item(top_name, serial=serial, part_id=part["id"] if part else None)
        self.fit(new, item_id=item["id"])
        for src_id, pid in mapping.items():
            self._emit("position.implements", {"position_id": pid, "design_position_id": src_id, "design_rev": rev_text}
                       | ({"item_id": item["id"], "serial": serial} if pid == new else {}))
        for row in rows:
            row["id"] = mapping[row["design_position_id"]]
        out |= {"positions": rows[:SHOWN_PATHS], "top_position_id": new,
                "item": {"id": item["id"], "name": item["name"], "serial": item.get("serial", ""),
                         "part": self._part_view(part and part["id"])}}
        return out

    # -- a built position's provenance, for the position and tree reads

    def _provenance(self, node: dict) -> dict | None:
        """What a built position implements: the design position (gone when it's been
        retired or isn't there), the revision it was built to, and the product."""
        dpid = node.get("design_position_id")
        if not dpid:
            return None
        dnode = self.s.node(self.org, dpid, "Position")
        root = dnode and self._design_root_of(dpid)
        return {"design_position_id": dpid, "design_rev": node.get("design_rev", ""),
                "name": dnode and dnode["name"], "gone": dnode is None or bool(dnode.get("retired")),
                "product": {"id": root["id"], "name": root["name"]} if root else None}

    def _design_view(self, node: dict) -> dict | None:
        """A design root's flag, as a position read shows it."""
        design = node.get("design")
        if not design:
            return None
        return {"rev": design.get("rev", ""), "part": self._part_view(design.get("part_id")),
                "declared_on": design.get("on")}

    def _item_product(self, item_id: str) -> dict | None:
        """The product an item is: built from it (fitted at the top of a tree built from
        it), else of its part."""
        f = self._current_fitment_of_item(item_id)
        if f:
            top = self.s.out(self.org, f["id"], "AT")[0]
            if top.get("design_position_id") and self._parent(top["id"]) is None:
                design = self.s.node(self.org, top["design_position_id"], "Position")
                if design and design.get("design"):
                    return {"id": design["id"], "name": design["name"], "top_position_id": top["id"], "built": True}
        part = self._item_part(item_id)
        for design in (self.s.inn(self.org, part["id"], "DESIGN_OF") if part else []):
            if design.get("design") and not design.get("retired"):
                return {"id": design["id"], "name": design["name"], "top_position_id": None, "built": False}
        return None

    # -- the design roll-up

    def design_rollup(self, position_id: str) -> dict:
        """A design position (or a product's top) across every item built from the
        product: the items implementing it (serial, revision, built, where, hours, what's
        fitted there now), the life of everything fitted there pooled (the rows of
        class_life_data: x days, c 0 failed / 1 censored / 2 interval), and the failure
        reports there and below on each item."""
        sv = _sv()
        node = self._get(position_id, "Position")
        root = self._design_root_of(position_id)
        if root is None:
            raise sv.Invalid(f"{node['name']} isn't in a product's design. For one item's data read its own "
                             "position.")
        path = [a["name"] for a in self._position_path(position_id) if a["kind"] == "Position"] + [node["name"]]
        implementing = [p for p in self.s.inn(self.org, position_id, "IMPLEMENTS") if p["label"] == "Position"]
        items, life, scopes = [], [], {}
        for p in implementing:
            top = self._top_of(p["id"])
            top_item = self._top_item(top["id"])
            serial = self._built_serial(top)
            fitted = self.current_fitment(p["id"])
            fitted_item = fitted and self.s.inn(self.org, fitted["id"], "IN")
            where = self._location_view(p["id"])
            unit = {"item_id": top_item and top_item["id"], "serial": serial, "top_position_id": top["id"]}
            items.append({
                **unit, "position": {"id": p["id"], "name": p["name"], "retired": bool(p.get("retired"))},
                "rev": top.get("design_rev", ""), "built_on": top.get("created"),
                "location": where and {"id": where["id"], "name": where["name"], "display": where["display"]},
                "hours": self._hours(top_item, top["id"]),
                "fitted": self._item_brief(fitted_item[0]) | {"since": fitted["from"]} if fitted_item else None,
            })
            life += [{**r, "position": p["name"], "position_id": p["id"], "serial": serial}
                     for r in self.life_data(p["id"])]
            if not p.get("retired"):
                for pid in self._report_scope(p["id"]):
                    scopes.setdefault(pid, (p["id"], unit))
        reports, cache = [], {}
        for r in self.s.nodes(self.org, "FailureReport"):
            at = scopes.get(r.get("position_id"))
            if at:
                reports.append(self._report_brief(r, at[0], cache) | {"unit": at[1]})
        reports.sort(key=lambda r: (r["occurred_on"], r["number"]), reverse=True)
        items.sort(key=lambda r: r["serial"].lower())
        by_rev: dict[str, int] = {}
        for row in items:
            by_rev[row["rev"]] = by_rev.get(row["rev"], 0) + 1
        info = root.get("design") or {}
        return {
            "design_position": {"id": node["id"], "name": node["name"], "path": path,
                                "position_class": node.get("position_class", ""), "retired": bool(node.get("retired"))},
            "product": {"id": root["id"], "name": root["name"], "rev": info.get("rev", ""),
                        "part": self._part_view(info.get("part_id"))},
            "items": items, "counts": {"items": len(items), "by_rev": by_rev},
            "life_data": {"rows": sorted(life, key=lambda r: r["from"]),
                          "failures": sum(1 for r in life if r["c"] != 1),
                          "suspensions": sum(1 for r in life if r["c"] == 1),
                          "uncertain": sum(1 for r in life if "xl" in r)},
            "reports": reports[:sv.MAX_REPORT_LIST], "reports_total": len(reports),
            "open_reports": sum(1 for r in reports if r["status"] in sv.OPEN_REPORT_STATUSES),
        }

    # -- the items landing

    def items_overview(self, product_id=None, item_class_id=None, q=None, limit=100, offset=0) -> dict:
        """Every item in the workspace (not retired), by name: its product (built from
        one, or of a product's part), type (its item class), serial, the position it's
        fitted to (with the path), whether it's fitted, a spare or neither, out of service,
        and open failure reports (involving it, and for an item built from a product,
        anywhere in its tree). product_id ('none': items of no product), item_class_id
        (that class or one inside it; 'none') and q (name, serial, part number, product)
        filter; limit (1 to 500) and offset page it."""
        sv = _sv()
        try:
            limit, offset = int(limit), int(offset)
        except (TypeError, ValueError):
            raise sv.Invalid("limit and offset are whole numbers.")
        if not 1 <= limit <= MAX_ITEM_LIST or offset < 0:
            raise sv.Invalid(f"limit is 1 to {MAX_ITEM_LIST}; offset is 0 or more.")
        if product_id not in (None, "", "none"):
            self._live_design(product_id)
        classes, _ = self._filter_ids(item_class_id, None)
        s, org = self.s, self.org
        designs = {p["id"]: p for p in s.nodes(org, "Position") if p.get("design") and not p.get("retired")}
        by_part = {(d.get("design") or {}).get("part_id"): d for d in designs.values()
                   if (d.get("design") or {}).get("part_id")}
        holder = {dst: src for src, dst in s.pairs(org, "IN")}
        at = dict(s.pairs(org, "AT"))
        fitted_at = {}
        for f in s.nodes(org, "Fitment"):
            if not f.get("voided") and f.get("to") is None and holder.get(f["id"]) and at.get(f["id"]):
                fitted_at[holder[f["id"]]] = at[f["id"]]
        part_of = dict(s.pairs(org, "OF_PART"))
        positions = {p["id"]: p for p in s.nodes(org, "Position")}
        parented = {src for src, _ in s.pairs(org, "PART_OF")}

        def product_of(item_id: str) -> tuple[dict | None, str | None]:
            top = positions.get(fitted_at.get(item_id, ""))
            if top and top.get("design_position_id") in designs and top["id"] not in parented:
                return designs[top["design_position_id"]], top["id"]
            return by_part.get(part_of.get(item_id)), None

        rows = []
        words = " ".join(str(q or "").lower().split())
        for item in s.nodes(org, "Item"):
            if item.get("retired") or (classes is not None and not self._kept(item, classes, None)):
                continue
            design, top_id = product_of(item["id"])
            if product_id == "none" and design is not None:
                continue
            if product_id not in (None, "", "none") and (design is None or design["id"] != product_id):
                continue
            if words and not any(words in str(x or "").lower() for x in (
                    item.get("name"), item.get("serial"), item.get("part_number"), design and design["name"])):
                continue
            rows.append((item, design, top_id))
        rows.sort(key=lambda r: (r[0].get("name") or "").lower())
        open_by_item: dict[str, set] = {}
        for r in s.nodes(org, "FailureReport"):
            if r["status"] in sv.OPEN_REPORT_STATUSES and r.get("item_id"):
                open_by_item.setdefault(r["item_id"], set()).add(r["id"])
        page = []
        for item, design, top_id in rows[offset:offset + limit]:
            pid = fitted_at.get(item["id"])
            where = self.whereabouts(item["id"])
            cls = self._effective_class(item)[0]
            path = pid and [a["name"] for a in self._position_path(pid)] + [positions[pid]["name"]]
            own = open_by_item.get(item["id"], set())
            page.append({
                "id": item["id"], "name": item.get("name") or "", "serial": item.get("serial") or "",
                "part_number": item.get("part_number") or "",
                "product": {"id": design["id"], "name": design["name"], "built": top_id is not None}
                if design else None,
                "item_class": cls and {"id": cls["id"], "name": cls["name"]},
                "position": {"id": pid, "name": positions[pid]["name"], "path": " › ".join(path)} if pid else None,
                "top_position_id": top_id,
                "status": "fitted" if pid else ("spare" if where["location"] else "not placed"),
                "location": where["location"] and {k: where["location"][k] for k in ("id", "name", "display")},
                "out_of_service": self._service_view(item["id"]),
                "open_reports": len(own | self._open_report_ids(top_id)) if top_id else len(own),
            })
        return {"items": page, "total": len(rows), "limit": limit, "offset": offset}


def _key(text) -> str:
    return " ".join(str(text or "").lower().split())
