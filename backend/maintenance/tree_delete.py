"""Deleting a branch of the tree, and undoing it.

"Delete" in the Explorer takes a position, a location or an item out of use with
everything below it, and never refuses: the positions inside go, items fitted
there are taken out (they stay in Items, unfitted), open work orders on them are
cancelled, their tasks and work packages are retired; a location takes the
locations inside it and the positions located there (with everything inside
those). Nothing is erased: the log keeps every event, so the history stays and
the whole branch can be brought back as a unit.

It's built from the events each step already has (``position.retired``,
``item.removed``, ``work_order.cancelled``, ``task.retired``, ...), so every view
treats a deleted branch the way it treats one retired by hand. Three new events
make the undo possible (older logs replay unchanged):

* ``tree.deleted {id, n, root_id, kind, name, on, reason, positions, locations,
  items, tasks, packages, fitments, work_orders, links}``: the record of one
  delete (a ``Deletion`` node; ``n`` numbers them, so the latest of a root is
  the one restored);
* ``tree.restored {id, on}``: that delete was undone;
* ``fitment.reinstated {id, on}``: a fitment ended by a delete is open again
  (the item back where it was, as if never taken out);
* ``work_order.uncancelled {id, status, on}``: a work order cancelled by a delete
  is back at the status it had.
"""

from __future__ import annotations

from backend.maintenance.store import GraphStore, new_id

MAX_DELETE_POSITIONS = 5000  # positions one delete takes (a guard against a runaway tree)
KINDS = ("position", "location", "item")


# ---- projectors ---------------------------------------------------------------------------

_RECORD = ("root_id", "kind", "name", "on", "reason", "positions", "locations", "items", "tasks", "packages",
           "fitments", "work_orders", "links")


def _tree_deleted(s: GraphStore, org: str, p: dict) -> None:
    s.put_node(org, p["id"], "Deletion", {k: p.get(k) for k in _RECORD} | {"n": p["n"], "restored": False})


def _tree_restored(s: GraphStore, org: str, p: dict) -> None:
    s.patch_node(org, p["id"], {"restored": True, "restored_on": p.get("on")})


def _fitment_reinstated(s: GraphStore, org: str, p: dict) -> None:
    s.patch_node(org, p["id"], {"to": None, "end_reason": None, "failure_mode_id": None, "to_precision": None})


def _work_order_uncancelled(s: GraphStore, org: str, p: dict) -> None:
    wo = s.node(org, p["id"])
    history = list(wo.get("status_history") or []) + [{"status": p["status"], "on": p["on"],
                                                       "note": "Cancel undone."}]
    s.patch_node(org, p["id"], {"status": p["status"], "closed": None, "cancel_reason": "",
                                "status_history": history})


PROJECTORS = {
    "tree.deleted": _tree_deleted,
    "tree.restored": _tree_restored,
    "fitment.reinstated": _fitment_reinstated,
    "work_order.uncancelled": _work_order_uncancelled,
}


def _sv():
    from backend.maintenance import service

    return service


def _plural(n: int, one: str, many: str | None = None) -> str:
    return f"{n} {one if n == 1 else (many or one + 's')}"


# ---- the operations (a mixin of Maintenance) ----------------------------------------------

class TreeDeleteOps:
    """Methods added to ``Maintenance``."""

    def _delete_plan(self, kind: str, root_id: str) -> dict:
        """Everything one delete would take, worked out before anything is written."""
        sv = _sv()
        if kind not in KINDS:
            raise sv.Invalid(f"Delete a {', '.join(KINDS[:-1])} or {KINDS[-1]}.")
        root = self._get(str(root_id or ""), kind.capitalize())
        if root.get("retired"):
            raise sv.Invalid(f"{root.get('name') or 'That'} was already deleted (retired).")
        live_kids = self._live_children

        def subtree(top: str, label: str) -> list[str]:
            out, stack, seen = [], [top], set()
            while stack:
                nid = stack.pop()
                if nid in seen:
                    continue
                seen.add(nid)
                out.append(nid)
                stack.extend(c["id"] for c in live_kids(nid, label))
            return out

        locations: list[str] = subtree(root["id"], "Location") if kind == "location" else []
        tops: list[str] = []
        if kind == "position":
            tops = [root["id"]]
        elif kind == "location":
            tops = [n["id"] for lid in locations for n in self.s.inn(self.org, lid, "LOCATED_AT")
                    if n["label"] == "Position" and not n.get("retired")]
        else:
            tops = [c["id"] for c in live_kids(root["id"], "Position")]
        positions: list[str] = []
        seen: set[str] = set()
        for top in tops:
            for pid in subtree(top, "Position"):
                if pid not in seen:
                    seen.add(pid)
                    positions.append(pid)
                    if len(positions) > MAX_DELETE_POSITIONS:
                        raise sv.Invalid(f"More than {MAX_DELETE_POSITIONS:,} positions would go at once: delete "
                                         "the systems inside it one at a time.")
        # Deepest first: what's inside goes before what holds it (and comes back after).
        depth = {pid: len(self._ancestor_ids(pid)) for pid in positions}
        positions.sort(key=lambda pid: -depth[pid])
        ldepth = {lid: len(self._ancestor_ids(lid)) for lid in locations}
        locations.sort(key=lambda lid: -ldepth[lid])
        nodes = positions + locations + ([root["id"]] if kind == "item" else [])

        fitments = []
        for pid in positions:
            f = self.current_fitment(pid)
            if f:
                item = self.s.inn(self.org, f["id"], "IN")[0]
                fitments.append({"id": f["id"], "position_id": pid, "item_id": item["id"], "from": f["from"]})
        if kind == "item":
            f = self._current_fitment_of_item(root["id"])
            if f:
                at = self.s.out(self.org, f["id"], "AT")[0]
                fitments.append({"id": f["id"], "position_id": at["id"], "item_id": root["id"], "from": f["from"]})
        work_orders, tasks, packages, seen_wo = [], [], [], set()
        for nid in nodes:
            for w in self.s.inn(self.org, nid, "ON"):
                if w["label"] == "WorkOrder" and w["status"] in sv.OPEN_STATUSES and w["id"] not in seen_wo:
                    seen_wo.add(w["id"])
                    work_orders.append({"id": w["id"], "status": w["status"]})
            tasks += [t["id"] for t in self._tasks_on(nid)]
            for edge in ("PLANNED_FOR", "PLANNED_AT"):
                for pkg in self.s.inn(self.org, nid, edge):
                    if pkg["label"] == "WorkPackage" and not pkg.get("retired"):
                        packages += [x["id"] for x in reversed(self._package_tree(pkg)) if x["id"] not in packages]
        gone = set(positions)
        links, functions, modes = [], 0, 0
        for pid in positions:
            fns = self._functions_of(pid)
            functions += len(fns)
            modes += sum(1 for fm in self.s.out(self.org, pid, "CAN_FAIL_AS")
                         if not fm.get("retired") and not fm.get("merged_into"))
            for fn in fns:
                for ff in self._failures_of(fn["id"]):
                    # Its functional failures stop explaining failures above it (outside what goes).
                    for e in self.s.inn(self.org, ff["id"], "RESULTS_FROM"):
                        if self._ff_position_id(e["id"]) not in gone:
                            links.append([e["id"], ff["id"]])
        placed = len(self._loose_items(locations)) if locations else 0
        stock = sum(1 for lid in locations for st in self.s.inn(self.org, lid, "AT")
                    if st["label"] == "Stock" and (st.get("quantity") or 0) > 0)
        carried = sum(len(live_kids(f["item_id"], "Position")) for f in fitments if f["item_id"] != root["id"])
        return {
            "root": root, "kind": kind, "positions": positions, "locations": locations, "fitments": fitments,
            "work_orders": work_orders, "tasks": tasks, "packages": packages, "links": links,
            "counts": {
                "positions": len(positions),
                "positions_inside": len(positions) - (1 if kind == "position" else 0),
                "locations": len(locations),
                "locations_inside": max(len(locations) - 1, 0),
                "items_unfitted": sum(1 for f in fitments if f["item_id"] != root["id"]),
                "positions_on_unfitted_items": carried,
                "items_placed": placed, "stock_lines": stock,
                "tasks": len(tasks), "work_packages": len(packages), "open_work_orders": len(work_orders),
                "functions": functions, "failure_modes": modes, "links": len(links),
                # An item deleted: the position it's taken out of, if it's fitted.
                **({"fitted_to": next(((self.s.node(self.org, f["position_id"]) or {}).get("name")
                                       for f in fitments if f["item_id"] == root["id"]), None)}
                   if kind == "item" else {}),
            },
        }

    @staticmethod
    def _delete_summary(plan: dict) -> str:
        """What goes, in a sentence: "Delete Propulsion and everything inside it? ..."."""
        c, root, kind = plan["counts"], plan["root"], plan["kind"]
        parts = []
        n = c["positions_inside"] if kind == "position" else c["positions"]
        if n:
            parts.append(_plural(n, "position"))
        if c["locations_inside"]:
            parts.append(_plural(c["locations_inside"], "location"))
        if c["items_unfitted"]:
            parts.append(f"{_plural(c['items_unfitted'], 'fitted item')} (kept, unfitted)")
        if c["tasks"]:
            parts.append(_plural(c["tasks"], "task"))
        if c["open_work_orders"]:
            parts.append(f"{_plural(c['open_work_orders'], 'open work order')} (cancelled)")
        what = f"Delete {root.get('name') or 'it'}" + (" and everything inside it" if parts else "") + "?"
        return what + (" " + ", ".join(parts) + "." if parts else "") + " Its history stays in the log."

    def delete_preview(self, kind: str, root_id: str) -> dict:
        """What deleting a position, location or item would take (nothing written)."""
        plan = self._delete_plan(kind, root_id)
        return {"dry_run": True, "kind": kind, "id": plan["root"]["id"], "name": plan["root"].get("name"),
                **plan["counts"], "summary": self._delete_summary(plan)}

    def delete_tree(self, kind: str, root_id: str, reason="") -> dict:
        """Delete a position, location or item and everything below it (see the module
        docstring). Never refuses for what's inside; undo with :meth:`restore_deletion`."""
        sv = _sv()
        plan = self._delete_plan(kind, root_id)
        root = plan["root"]
        reason = sv._text(reason, "reason")
        why = reason or f"Deleted with {root.get('name') or 'its parent'}."
        today = self.today()
        for w in plan["work_orders"]:
            self._emit("work_order.cancelled", {"id": w["id"], "on": today, "reason": why})
        for pkg in plan["packages"]:
            self._emit("package.retired", {"id": pkg, "on": today, "reason": why})
        for f in plan["fitments"]:
            self._emit("item.removed", {"fitment_id": f["id"], "on": max(today, f["from"] or today),
                                        "reason": "other", "failure_mode_id": None})
        for t in plan["tasks"]:
            self._emit("task.retired", {"id": t, "on": today, "reason": why})
        for effect_id, cause_id in plan["links"]:
            self._link_event("functional_failure.unlinked", effect_id, cause_id)
        for pid in plan["positions"]:
            self._emit("position.retired", {"id": pid, "on": today, "reason": reason})
        for lid in plan["locations"]:
            self._emit("location.retired", {"id": lid, "on": today, "reason": reason})
        items = [root["id"]] if kind == "item" else []
        for iid in items:
            self._emit("item.retired", {"id": iid, "on": today, "reason": reason})
        did = new_id()
        self._emit("tree.deleted", {
            "id": did, "n": self.s.count(self.org, "Deletion") + 1, "root_id": root["id"], "kind": kind,
            "name": root.get("name") or "", "on": today, "reason": reason,
            "positions": plan["positions"], "locations": plan["locations"], "items": items,
            "tasks": plan["tasks"], "packages": plan["packages"],
            "fitments": [{k: f[k] for k in ("id", "position_id", "item_id")} for f in plan["fitments"]],
            "work_orders": plan["work_orders"], "links": plan["links"],
        })
        return {"deleted": root["id"], "deletion_id": did, "kind": kind, "name": root.get("name"),
                **plan["counts"], "summary": self._delete_summary(plan).replace("?", ".", 1).replace(
                    "Delete ", "Deleted ", 1),
                "positions_retired": plan["positions"], "locations_retired": plan["locations"],
                "tasks_retired": plan["tasks"],
                "items_unfitted": [f["item_id"] for f in plan["fitments"] if f["item_id"] != root["id"]],
                "work_orders_cancelled": [w["id"] for w in plan["work_orders"]]}

    def _latest_deletion(self, root_id: str) -> dict | None:
        found = [d for d in self.s.nodes(self.org, "Deletion") if d.get("root_id") == root_id and not d.get("restored")]
        return max(found, key=lambda d: d.get("n") or 0) if found else None

    def restore_deletion(self, root_id: str) -> dict:
        """Undo the latest delete of a position, location or item: everything it took
        comes back as it was (what has changed since, such as an item fitted
        elsewhere, is left and listed in ``skipped``)."""
        sv = _sv()
        d = self._latest_deletion(str(root_id or ""))
        if d is None:
            raise sv.Invalid("Nothing deleted there to bring back.")
        root = self.s.node(self.org, d["root_id"])
        if d["kind"] in ("position", "location"):
            parent = self._parent(root["id"])
            if parent and parent.get("retired"):
                raise sv.Invalid(f"{parent['name']} (what it sits inside) is deleted: restore that first.")
        today = self.today()
        skipped: list[str] = []

        def back(ids, event):
            done = []
            for nid in ids:
                node = self.s.node(self.org, nid)
                if node and node.get("retired"):
                    self._emit(event, {"id": nid, "on": today})
                    done.append(nid)
            return done

        items = back(d.get("items") or [], "item.restored")
        locations = back(list(reversed(d.get("locations") or [])), "location.restored")
        positions = back(list(reversed(d.get("positions") or [])), "position.restored")
        fitments = []
        for f in d.get("fitments") or []:
            fit = self.s.node(self.org, f["id"])
            if not fit or fit.get("to") is None or fit.get("voided"):
                continue
            item = self.s.node(self.org, f["item_id"]) or {}
            pos = self.s.node(self.org, f["position_id"]) or {}
            if self._current_fitment_of_item(f["item_id"]) or self.current_fitment(f["position_id"]) \
                    or item.get("retired") or pos.get("retired"):
                skipped.append(f"{item.get('name') or 'An item'} wasn't refitted to {pos.get('name') or 'its position'}: "
                               "it (or the position) has changed since.")
                continue
            self._emit("fitment.reinstated", {"id": f["id"], "on": today})
            fitments.append(f["id"])
        tasks = back(d.get("tasks") or [], "task.restored")
        packages = back(list(reversed(d.get("packages") or [])), "package.restored")
        work_orders = []
        for w in d.get("work_orders") or []:
            wo = self.s.node(self.org, w["id"])
            if wo and wo.get("status") == "cancelled":
                self._emit("work_order.uncancelled", {"id": w["id"], "status": w["status"], "on": today})
                work_orders.append(w["id"])
        links = 0
        for effect_id, cause_id in d.get("links") or []:
            ends = [self._ff_position_id(effect_id), self._ff_position_id(cause_id)]
            nodes = [self.s.node(self.org, x) for x in ends if x]
            if len(nodes) == 2 and not any(n.get("retired") for n in nodes) and not any(
                    c["id"] == cause_id for c in self.s.out(self.org, effect_id, "RESULTS_FROM")):
                self._link_event("functional_failure.linked", effect_id, cause_id)
                links += 1
        self._emit("tree.restored", {"id": d["id"], "on": today})
        return {"restored": d["root_id"], "deletion_id": d["id"], "kind": d["kind"], "name": d.get("name"),
                "positions_restored": len(positions), "locations_restored": len(locations),
                "items_restored": len(items), "items_refitted": len(fitments), "tasks_restored": len(tasks),
                "work_packages_restored": len(packages), "work_orders_reopened": len(work_orders),
                "links_restored": links, "skipped": skipped}
