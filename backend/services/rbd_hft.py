"""A safety function's hardware fault tolerance (HFT), from its diagram alone.

HFT is how many dangerous block failures a part of the function can take and
still trip: one less than the fewest failures that defeat it. Here that is
read off the minimal cut sets: blocks that share a cut set belong to one
subsystem (two transmitters voting 1oo2, three voting 2oo3), and the
subsystem's HFT is its smallest cut set's order minus one. The function's own
HFT is the smallest of them.

It is architecture only: common cause and the failure rates don't enter it
(IEC 61508-2, 7.4.4). Safe failure fraction and the spurious trip rate need
each block's safe and detected failure rates, which the blocks don't take.
"""

from __future__ import annotations

from typing import Any, Optional

from backend.services import rbd_analysis as ra


def fault_tolerance(rbd, graph: dict) -> Optional[dict]:
    """``{"function": int, "at_least": bool, "subsystems": [{"blocks": [label], "ids": [id],
    "hft": int, "at_least": bool}]}`` in the diagram's order, or None when the
    cut sets can't be listed. ``at_least`` marks a subsystem no cut set of up to
    the listed order reaches (its HFT is at least that order)."""
    sets = ra._structure_sets(rbd)
    cuts = [frozenset(c) for c in sets.get("cuts") or []]
    complete = bool(sets.get("cuts_complete"))
    junctions = rbd._junctions() if hasattr(rbd, "_junctions") else frozenset()
    nodes = [n for n in graph.get("nodes") or [] if n.get("type") not in ("input", "output")]
    labels = {n.get("id"): (n.get("data") or {}).get("label") or n.get("id") for n in nodes}
    blocks = [n.get("id") for n in nodes
              if n.get("id") in rbd.nodes and n.get("id") not in junctions]
    if not blocks:
        return None
    # Union-find: blocks sharing a cut set are one subsystem.
    parent = {b: b for b in blocks}

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for cut in cuts:
        members = [b for b in cut if b in parent]
        for other in members[1:]:
            parent[find(other)] = find(members[0])
    groups: dict[Any, list] = {}
    for b in blocks:
        groups.setdefault(find(b), []).append(b)
    order_cap = ra._LOW_ORDER_CUT_MAX
    subsystems = []
    for members in groups.values():
        orders = [len(c) for c in cuts if c & set(members)]
        if orders:
            subsystems.append({"ids": members, "blocks": [labels[b] for b in members],
                               "hft": min(orders) - 1, "at_least": False})
        else:
            # No listed cut set reaches it: its smallest one is longer than the listing goes.
            if complete:
                continue  # never defeats the function (a block in no cut set)
            subsystems.append({"ids": members, "blocks": [labels[b] for b in members],
                               "hft": order_cap, "at_least": True})
    if not subsystems:
        return None
    lowest = min(subsystems, key=lambda s: s["hft"])
    return {"function": lowest["hft"], "at_least": lowest["at_least"], "subsystems": subsystems}
