"""The Explorer's Summary roll-up: how much sits on a tree node and on everything
below it, at any depth (the Explorer aggregates downwards, Derryn 22 Nov 2026).

One read for the node, never one per position: the positions below it, the items
fitted to them, the tasks on those positions and items (and on the places, for a
location), the failure modes and the models linked to them, and the failure
reports filed at them. Each count is split into ``here`` (the node's own: a
position and the item fitted there, or a place itself) and ``inside`` (everything
below it). "Below" is the Explorer's own (``Maintenance.subtree_ids``), cut to the
asset opened (``within``: the Explorer's ``?root=``), so another asset's records
never count.

Only things are counted, never quantities: stock held for several positions is
shared between them, so adding it up per position would count it more than once.
"""

from __future__ import annotations

KEYS = ("positions", "items", "tasks", "failure_modes", "models", "failure_reports", "open_reports")


def _blank() -> dict:
    return {k: 0 for k in KEYS}


def rollup(m, node_id: str, within: str | None = None) -> dict:
    """{node: {id, kind, name}, here: {...}, inside: {...}}, each with the counts in KEYS.
    positions and items are what's inside (a position's own fitted item is a fact about it,
    on its Summary); ``here.items`` is 1 when an item is fitted to the node itself."""
    from backend.maintenance import service as sv

    ids = m.subtree_ids(node_id, within)
    node = m.s.node(m.org, node_id)
    read = m._tree_read()
    rows = read["positions"]
    positions = {pid for pid in ids if pid in rows}
    # What's fitted to each position in the branch: an item's tasks count where it's fitted.
    fitted = {rows[pid]["item"]["id"]: pid for pid in positions if rows[pid].get("item")}
    here, inside = _blank(), _blank()

    def side(where: str | None) -> dict | None:
        """The counts a record at ``where`` (a position, place or item id) goes to."""
        where = fitted.get(where, where)
        if where == node["id"]:
            return here
        return inside if where in ids else None

    inside["positions"] = len(positions - {node["id"]})
    for item_id, pid in fitted.items():
        (here if pid == node["id"] else inside)["items"] += 1

    on: dict[str, str] = {}
    for src, dst in m.s.pairs(m.org, "ON"):
        on.setdefault(src, dst)
    for t in m.s.nodes(m.org, "Task"):
        bucket = None if t.get("retired") else side(on.get(t["id"]))
        if bucket is not None:
            bucket["tasks"] += 1

    modes = {fm["id"] for fm in m.s.nodes(m.org, "FailureMode") if not fm.get("retired") and not fm.get("merged_into")}
    counted: set[str] = set()
    for pid, mode_id in m.s.pairs(m.org, "CAN_FAIL_AS"):
        bucket = side(pid) if mode_id in modes and pid in positions and mode_id not in counted else None
        if bucket is not None:
            counted.add(mode_id)
            bucket["failure_modes"] += 1

    # Life models and predictions linked to positions (an RBD is a mission's: the Missions view counts those).
    for link in m.s.nodes(m.org, "ModelLink"):
        if link.get("removed") or link.get("model_type") == "rbd" or link.get("position_id") not in positions:
            continue
        side(link["position_id"])["models"] += 1

    design = node["label"] == "Position" and m._design_root_of(node["id"])
    if design:
        # A design position has no reports of its own: its reports are those on the items
        # built from the product (the Failure reports tab's own scope), all counted as here.
        counts = m.failure_reports(position_id=node["id"], limit=1)["counts"]
        here["failure_reports"] = sum(counts[s] for s in sv.REPORT_STATUSES)
        here["open_reports"] = counts["open"]
    else:
        for r in m.s.nodes(m.org, "FailureReport"):
            bucket = side(r.get("position_id")) if r.get("position_id") in positions else None
            if bucket is not None:
                bucket["failure_reports"] += 1
                bucket["open_reports"] += r.get("status") in sv.OPEN_REPORT_STATUSES

    return {"node": {"id": node["id"], "kind": node["label"].lower(), "name": node.get("name") or ""},
            "design": bool(design), "here": here, "inside": inside}
