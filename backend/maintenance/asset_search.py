"""Finding things on the Assets list, and deleting an item.

``asset_search``: the Assets list's search box finds the assets by name, and this
finds what's inside them: positions by name or tag (P-101), and items by name,
serial or part number, each with the asset it's at (its site), so a planner who
knows only a tag or a serial gets to the right page. Items built from products
are found too (their serials), and ``product_items_list`` lists every item of a
product, so they're reachable from Assets as well as from Products.

``delete_item``: Delete… on an item's page. Nothing is erased: the item is
retired (``item.retired``), so its fitments, work orders and readings stay in the
history, and Restore brings it back. An item built from a product, still at the
top of its own tree, takes that tree with it (the same delete as the Explorer's,
so the tree comes back with the item). Refused, with what to do, while it's fitted
to any other position, has positions inside it in use, or has open work orders.
"""

from __future__ import annotations

MAX_SEARCH = 50  # results of each kind one search returns


def _sv():
    from backend.maintenance import service

    return service


def _words(q) -> list[str]:
    return str(q or "").lower().split()


def _rank(words: list[str], exact: list) -> int:
    """0 for an exact tag or serial, 1 for one starting with the query, else 2."""
    whole = " ".join(words)
    keys = [str(x or "").lower() for x in exact if x]
    if whole in keys:
        return 0
    if any(k.startswith(whole) for k in keys):
        return 1
    return 2


class AssetSearchOps:
    """Mixed into Maintenance."""

    # -- where a position is, as the Assets list names it

    def _built_top(self, top: dict) -> bool:
        return bool(top.get("design_position_id")) and self._parent(top["id"]) is None

    def _site_of_position(self, position_id: str, path: list[dict] | None = None) -> dict:
        """The asset a position is at: its location's top place, else the top of its tree
        (an asset with no place yet), else (the top itself, with no place) none.
        {name, id, kind ("location" | "position" | None), unit: a built item's tree}."""
        loc = self._located(position_id)[0]
        path = path if path is not None else self._position_path(position_id)
        top_pos = next((n for n in path if n.get("kind") == "Position"), None)
        top = self.s.node(self.org, top_pos["id"]) if top_pos else self.s.node(self.org, position_id)
        unit = top["name"] if top and self._built_top(top) else None
        if loc:
            places = self._location_path(loc["id"]) + [{"id": loc["id"], "name": loc["name"]}]
            first = places[0]
            node = self.s.node(self.org, first["id"]) or {}
            if not self._location_realm(node):
                return {"id": first["id"], "name": first["name"], "kind": "location", "unit": unit}
        if top and top["id"] != position_id:
            return {"id": top["id"], "name": top["name"], "kind": "position", "unit": unit}
        return {"id": None, "name": "", "kind": None, "unit": unit}

    # -- the search

    def asset_search(self, q, limit: int = MAX_SEARCH) -> dict:
        """Positions (name or tag) and items (name, serial, part number, maker, model)
        holding every word of q, in any order and case: exact tags and serials first,
        then ones starting with q, then the rest by name. Each with the asset it's at
        (site) and the way down to it. A product's design isn't an asset (it's under
        Products); the items and trees built from one are. positions_total and
        items_total: how many matched before the limit."""
        words = _words(q)
        if not words:
            return {"q": "", "positions": [], "items": [], "positions_total": 0, "items_total": 0}
        try:
            limit = max(1, min(int(limit), MAX_SEARCH))
        except (TypeError, ValueError):
            raise _sv().Invalid("limit is a whole number.")
        designs = self._design_ids()

        def hit(*texts) -> bool:
            text = " ".join(str(t or "") for t in texts).lower()
            return all(w in text for w in words)

        found_pos = []
        for p in self.s.nodes(self.org, "Position"):
            if p.get("retired") or p["id"] in designs or not hit(p.get("name"), p.get("tag")):
                continue
            found_pos.append((_rank(words, [p.get("tag"), p.get("name")]), (p.get("name") or "").lower(), p))
        found_pos.sort(key=lambda r: (r[0], r[1]))

        found_items = []
        for it in self.s.nodes(self.org, "Item"):
            if it.get("retired") or not hit(it.get("name"), it.get("serial"), it.get("part_number"),
                                            it.get("manufacturer"), it.get("model")):
                continue
            found_items.append((_rank(words, [it.get("serial"), it.get("part_number"), it.get("name")]),
                                (it.get("name") or "").lower(), it))
        found_items.sort(key=lambda r: (r[0], r[1]))

        positions = []
        for _, _, p in found_pos[:limit]:
            path = self._position_path(p["id"])
            fitted = self.current_fitment(p["id"])
            item = fitted and (self.s.inn(self.org, fitted["id"], "IN") or [None])[0]
            positions.append({
                "id": p["id"], "name": p["name"], "tag": p.get("tag") or "",
                "path": " › ".join(n["name"] for n in path),
                "site": self._site_of_position(p["id"], path),
                "item": item and {"id": item["id"], "name": item.get("name") or "", "serial": item.get("serial") or ""},
            })
        items = [self._item_hit(it) for _, _, it in found_items[:limit]]
        return {"q": " ".join(words), "positions": positions, "items": items,
                "positions_total": len(found_pos), "items_total": len(found_items)}

    # -- the one search for everything (backend/services/global_search.py)

    def search_records(self, tier, kinds, limit: int = 5) -> dict:
        """The register's records for the app's one search: {kind: (total, hits)}, each hit
        {kind, id, name, tier, context, path}, best first, the first ``limit`` of each.
        ``tier(keys, extra)`` ranks a record (None: no match; global_search.Matcher.tier).
        Kinds: asset (a top place), location, position (a product's design positions too,
        opening on the product), item, part, product, work_order. Each opens where it lives:
        a place, position or item in the Explorer on its own asset (?root=) with it picked;
        a design's position on its product's page; a part, product or work order on its page."""
        designs = self._design_ids()
        found: dict[str, list] = {k: [] for k in kinds}

        def keep(kind, node, keys, extra=()):
            if kind in found:
                t = tier(keys, extra)
                if t is not None:
                    found[kind].append((t, (node.get("name") or node.get("title") or "").lower(), node))

        if "asset" in found or "location" in found:
            for loc in self.s.nodes(self.org, "Location"):
                if loc.get("retired") or self._location_realm(loc):
                    continue
                ups = self._location_path(loc["id"])
                keep("location" if ups else "asset", loc, [loc.get("name")],
                     [loc.get("description"), *(a["name"] for a in ups)])
        if "position" in found:
            for p in self.s.nodes(self.org, "Position"):
                if p.get("retired") or (p.get("design") and self._parent(p["id"]) is None):
                    continue
                keep("position", p, [p.get("name"), p.get("tag")])
        if "item" in found:
            for it in self.s.nodes(self.org, "Item"):
                if not it.get("retired"):
                    keep("item", it, [it.get("name"), it.get("serial"), it.get("part_number")],
                         [it.get("manufacturer"), it.get("model")])
        if "part" in found:
            for pt in self.s.nodes(self.org, "Part"):
                if not pt.get("retired"):
                    keep("part", pt, [pt.get("part_number"), pt.get("name")], [pt.get("manufacturer"), pt.get("notes")])
        if "product" in found:
            for p in self.s.nodes(self.org, "Position"):
                if p.get("design") and not p.get("retired") and self._parent(p["id"]) is None:
                    part = self._part_view((p.get("design") or {}).get("part_id")) or {}
                    keep("product", p, [p.get("name"), part.get("part_number")], [p.get("description")])
        if "work_order" in found:
            for w in self.s.nodes(self.org, "WorkOrder"):
                keep("work_order", w, [w.get("title"), str(w.get("number") or "")])

        out = {}
        for kind, rows in found.items():
            rows.sort(key=lambda r: (r[0], r[1]))
            hits = []
            for t, _, node in rows[:limit]:
                hit = self._search_hit(kind, node, designs)
                if hit:
                    hits.append({"kind": kind, "id": node["id"], "tier": t, "updated_at": None, "sample": False, **hit})
            out[kind] = (len(rows), hits)
        return out

    def _search_hit(self, kind: str, node: dict, designs: set) -> dict | None:
        """A record's name, the line under it and where it opens, for search_records."""
        from urllib.parse import urlencode

        def explorer(arrange, root, sel):
            q = {"arrange": arrange, **({"root": root} if root else {}), "sel": sel}
            return "/asset-register/explorer?" + urlencode(q)

        def at_position(pos_id: str, sel: str) -> str:
            site = self._site_of_position(pos_id)
            if site.get("id"):
                return explorer("locations" if site["kind"] == "location" else "positions", site["id"], sel)
            return explorer("positions", pos_id, sel)

        name = node.get("name") or "(no name)"
        if kind == "asset":
            return {"name": name, "context": "Asset", "path": explorer("locations", node["id"], node["id"])}
        if kind == "location":
            path = self._location_path(node["id"])
            top = path[0]["id"] if path else node["id"]
            return {"name": name, "context": " › ".join(a["name"] for a in path),
                    "path": explorer("locations", top, node["id"])}
        if kind == "position":
            way = self._position_path(node["id"])
            tag = node.get("tag") or ""
            title = f"{tag} · {name}" if tag and tag != name else name
            if node["id"] in designs:
                top = next((n for n in way if n.get("kind") == "Position"), None)
                product = top or node
                return {"name": title, "context": f"In product {product['name']}"
                        + (" · " + " › ".join(n["name"] for n in way[1:]) if len(way) > 1 else ""),
                        "path": f"/products/{product['id']}?sel={node['id']}"}
            site = self._site_of_position(node["id"], way)
            where = site.get("unit") or site.get("name") or "Not at an asset yet"
            down = " › ".join(n["name"] for n in way)
            return {"name": title, "context": " · ".join(x for x in (where, down) if x and x != name),
                    "path": at_position(node["id"], node["id"])}
        if kind == "item":
            hit = self._item_hit(node)
            w = hit["where"]
            if w.get("how") == "fitted":
                path, where = at_position(w["position"]["id"], w["position"]["id"]), f"fitted to {w['position']['name']}"
            elif w.get("how") == "placed":
                site = hit["site"]
                path = explorer("locations", site.get("id"), node["id"])
                where = f"kept at {w['location']['name']}"
            else:
                path, where = f"/asset-register/items/{node['id']}", "not fitted or placed"
            serial = hit["serial"] and hit["serial"] not in name and f"serial {hit['serial']}"
            product = hit["product"] and f"{'built from' if hit['product']['built'] else 'a'} {hit['product']['name']}"
            return {"name": name, "context": " · ".join(x for x in (serial, where, product) if x), "path": path}
        if kind == "part":
            pt = self.part(node["id"])
            stock = f"{pt['on_hand']:g} on hand" + (" · low" if pt.get("low") else "") if pt.get("stock") else "no stock kept"
            by = pt.get("superseded_by") and f"superseded by {pt['superseded_by']['part_number']}"
            title = f"{pt['part_number']} · {pt['name']}" if pt.get("name") and pt["name"] != pt["part_number"] else pt["part_number"]
            return {"name": title, "context": " · ".join(x for x in ("Part", stock, by) if x),
                    "path": f"/asset-register/parts/{node['id']}"}
        if kind == "product":
            row = self._product_row(node)
            part = (row.get("part") or {}).get("part_number")
            built = row["items_built"]
            return {"name": name, "context": " · ".join(x for x in (
                "Product", part and f"part {part}", f"{built} built" if built else "none built yet") if x),
                    "path": f"/products/{node['id']}"}
        if kind == "work_order":
            due = node.get("due") and f"due {node['due']}"
            return {"name": node.get("title") or node.get("number") or "Work order",
                    "context": " · ".join(str(x) for x in (node.get("number") and f"No. {node['number']}",
                                                            node.get("status"), due) if x),
                    "path": f"/maintenance/work-orders/{node['id']}"}
        return None

    def _item_hit(self, it: dict) -> dict:
        """An item as a search result: its serial and part number, the product it is, and
        where it is: fitted (the position, and its site), placed (the location's top
        place), or neither."""
        f = self._current_fitment_of_item(it["id"])
        where: dict = {"how": None}
        site = {"id": None, "name": "", "kind": None, "unit": None}
        if f:
            pos = self.s.out(self.org, f["id"], "AT")[0]
            where = {"how": "fitted", "position": {"id": pos["id"], "name": pos["name"]}}
            site = self._site_of_position(pos["id"])
            if not site["name"] and self._parent(pos["id"]) is None and not self._built_top(pos):
                site = {"id": pos["id"], "name": pos["name"], "kind": "position", "unit": None}
        else:
            placed = self._placement_now(it["id"])
            if placed:
                brief = self._location_brief(placed[1])
                where = {"how": "placed", "location": {"id": placed[1]["id"], "name": placed[1]["name"]}}
                first = (brief["path"] or [{"id": placed[1]["id"], "name": placed[1]["name"]}])[0]
                site = {"id": first["id"], "name": first["name"], "kind": "location", "unit": None}
        product = self._item_product(it["id"])
        return {"id": it["id"], "name": it.get("name") or "", "serial": it.get("serial") or "",
                "part_number": it.get("part_number") or "", "where": where, "site": site,
                "product": product and {"id": product["id"], "name": product["name"], "built": product["built"]}}

    def product_items_list(self) -> dict:
        """Every item (not retired) of a product: built from one (at the top of a tree
        built from it) or of a product's part (a spare, or one whose tree was deleted),
        by product then serial, each as a search result."""
        out = []
        for it in self.s.nodes(self.org, "Item"):
            if it.get("retired"):
                continue
            product = self._item_product(it["id"])
            if product:
                out.append(self._item_hit(it))
        out.sort(key=lambda r: (r["product"]["name"].lower(), r["serial"].lower(), r["name"].lower()))
        return {"items": out}

    # -- deleting an item

    def _item_delete_plan(self, item_id: str) -> dict:
        sv = _sv()
        item = self._get(item_id, "Item")
        if item.get("retired"):
            raise sv.Invalid(f"{item['name']} is already deleted. Restore it from its page to use it again.")
        f = self._current_fitment_of_item(item_id)
        tree = None
        if f:
            pos = self.s.out(self.org, f["id"], "AT")[0]
            if self._built_top(pos) and not pos.get("retired"):
                tree = self.delete_preview("position", pos["id"])
            else:
                raise sv.Invalid(f"{item['name']} is fitted to {pos['name']}. Take it out first (Remove on "
                                 f"{pos['name']}'s page, or a work order's Replace), then delete it.")
        own = [c for c in self.s.inn(self.org, item_id, "PART_OF") if c["label"] == "Position" and not c.get("retired")]
        if own:
            names = ", ".join(sorted(c["name"] for c in own)[:3])
            raise sv.Invalid(f"Positions inside {item['name']} are still in use ({names}). Delete or move them "
                             "first, then delete the item.")
        open_wos = [w for w in self.s.inn(self.org, item_id, "ON")
                    if w["label"] == "WorkOrder" and w["status"] in sv.OPEN_STATUSES]
        if open_wos:
            n = len(open_wos)
            raise sv.Invalid(f"{item['name']} has {n} open work order{'' if n == 1 else 's'}. Close or cancel "
                             f"{'it' if n == 1 else 'them'} first, then delete the item.")
        tasks = [t["id"] for t in self._tasks_on(item_id)]
        return {"item": item, "tree": tree, "tasks": tasks}

    def delete_item(self, item_id: str, dry_run: bool = True, reason="") -> dict:
        """Delete an item (see the module docstring): dry_run (the default) only says
        what would go, or why it can't. {id, name, tree: the tree going with it (a
        built item's: its positions inside, tasks and open work orders, cancelled) or
        None, tasks: its own tasks retired with it, history: what it keeps}."""
        plan = self._item_delete_plan(str(item_id or ""))
        item, tree = plan["item"], plan["tree"]
        out = {"id": item["id"], "name": item["name"], "dry_run": bool(dry_run),
               "tree": tree and {"id": tree["id"], "name": tree["name"],
                                 "positions": tree.get("positions_inside", 0), "tasks": tree.get("tasks", 0),
                                 "open_work_orders": tree.get("open_work_orders", 0)},
               "tasks": len(plan["tasks"]),
               "history": {"fitments": len(self._fitments_of(item["id"])),
                           "work_orders": sum(1 for w in self.s.inn(self.org, item["id"], "ON")
                                              if w["label"] == "WorkOrder")}}
        if dry_run:
            return out
        if tree:
            self.delete_tree("position", tree["id"], reason or f"Deleted with {item['name']}.")
        self.retire_item(item["id"], reason or "Deleted.")
        return out | {"deleted": item["id"]}

    def restore_deleted_item(self, item_id: str) -> dict:
        """Undo delete_item: the item back, and the tree that went with it (back at the
        top of it, as it was)."""
        sv = _sv()
        item = self._get(str(item_id or ""), "Item")
        if not item.get("retired"):
            raise sv.Invalid(f"{item['name']} isn't deleted.")
        # The tree deleted with it: the latest delete that took this item out of a built top.
        tree = None
        for d in sorted(self.s.nodes(self.org, "Deletion"), key=lambda d: d.get("n") or 0, reverse=True):
            if d.get("restored") or d.get("kind") != "position":
                continue
            if any(f.get("item_id") == item["id"] and f.get("position_id") == d.get("root_id")
                   for f in d.get("fitments") or []):
                tree = d
                break
        out = self.restore_item(item["id"])
        if tree:
            self.restore_deletion(tree["root_id"])
            out = self.item(item["id"])
        return out
