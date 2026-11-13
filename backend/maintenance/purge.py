"""Erasing part of a workspace's history: an operator's tool, never a user's.

The log is never rewritten (CLAUDE.md, "Maintenance: event-sourced"), with one
exception: when a workspace's owner asks for something to be removed together
with its history. A delete (``tree_delete.py``) keeps the history; a purge
erases it.

A purge is worked out from the graph, not from names: given some root nodes,
it takes everything connected to them (:func:`closure`: every node reachable
along edges in either direction, or through an id held in a node's
properties), then every event whose payload names only nodes in that set
(:func:`plan`). An event that names a node in the set and a node outside it
would be needed by both: the purge refuses and lists them (``mixed``), and
nothing is written.

The events aren't deleted: the graph applies the log strictly in sequence, and
a missing number stalls every process for ``GAP_TIMEOUT``. Each one is
overwritten in place (``log.purge``): it keeps its id, sequence number,
organisation, time and actor, and becomes ``event.purged`` with the payload
``{"purged": true, "on": <date>}``, whose projector does nothing. The log's
purge count then goes up, and every graph built from it, in any process,
rebuilds on its next sync (``GraphStore._purged_since_built``); a Neo4j mirror
then copies every workspace whole (``Neo4jMirror.resync_full``).

Run it with ``python -m backend.scripts.maintenance_purge``.
"""

from __future__ import annotations

import json
import re
from collections import Counter

from backend.maintenance.store import PURGED, GraphStore

# ---- the projector -----------------------------------------------------------------------------


def _event_purged(s: GraphStore, org: str, p: dict) -> None:
    """An erased event: it wrote something once; now it writes nothing."""


PROJECTORS = {PURGED: _event_purged}


# ---- what goes ---------------------------------------------------------------------------------

_TOKEN = re.compile(r"[A-Za-z0-9_\-]+")


def _tokens(value) -> set[str]:
    """Every word in a value (strings anywhere inside it, split at punctuation:
    an edge id ``TYPE:src:dst`` gives both ends)."""
    return set(_TOKEN.findall(json.dumps(value, default=str)))


def closure(store, org: str, roots: list[str], barriers: list[str] = ()) -> set[str]:
    """Every node of the organisation connected to ``roots``: along edges either
    way, or through an id one node holds in its properties. ``barriers`` are never
    entered (they are kept; an event linking one to the set is then ``mixed``)."""
    nodes, edges = store.snapshot(org)
    ids = {row[0] for row in nodes}
    missing = [r for r in roots if r not in ids]
    if missing:
        raise KeyError(f"not in the graph of {org}: {', '.join(missing)}")
    near: dict[str, set[str]] = {}
    for _, _, _, src, dst, props in edges:
        near.setdefault(src, set()).add(dst)
        near.setdefault(dst, set()).add(src)
        for ref in _tokens(json.loads(props)) & ids:
            near.setdefault(ref, set()).update((src, dst))
            near.setdefault(src, set()).add(ref)
    for nid, _, _, props in nodes:
        for ref in (_tokens(json.loads(props)) & ids) - {nid}:
            near.setdefault(nid, set()).add(ref)
            near.setdefault(ref, set()).add(nid)
    stop = set(barriers)
    seen = set(roots) - stop
    todo = list(seen)
    while todo:
        for other in near.get(todo.pop(), ()):
            if other not in seen and other not in stop:
                seen.add(other)
                todo.append(other)
    return seen


def org_events(log, org: str, batch: int = 5000):
    """The organisation's events, oldest first, from any log."""
    at = 0
    while True:
        events = log.since(at, batch)
        if not events:
            return
        for e in events:
            if e["org"] == org:
                yield e
        at = events[-1]["seq"]


def plan(store, org: str, gone: set[str]) -> dict:
    """The events to erase so that nothing in ``gone`` is left, from the store's
    log; ``mixed``: events that name both a node in ``gone`` and one kept (the
    purge must not go ahead while there are any)."""
    nodes, _ = store.snapshot(org)
    kept = {row[0] for row in nodes} - gone
    erase, mixed, unnamed = [], [], 0
    types: Counter = Counter()
    for e in org_events(store.log, org):
        if e["type"] == PURGED:
            continue
        words = _tokens(e["payload"])
        mine, theirs = words & gone, words & kept
        if mine and theirs:
            mixed.append({"seq": e["seq"], "type": e["type"], "purged_ids": sorted(mine)[:5],
                          "kept_ids": sorted(theirs)[:5]})
        elif mine:
            erase.append(e["seq"])
            types[e["type"]] += 1
        elif not theirs:
            unnamed += 1  # names no node there now: neither side's; left alone
    return {"seqs": erase, "types": dict(types.most_common()), "mixed": mixed, "unnamed": unnamed}


# ---- other records keyed by what goes ---------------------------------------------------------

_LOG_COLLECTIONS = ("maintenance_events", "maintenance_counters")


def _words(doc) -> set[str]:
    """``_tokens`` of a stored record, its binary parts left out."""
    def plain(x):
        if isinstance(x, (bytes, bytearray, memoryview)):
            return ""
        return str(x)

    return set(_TOKEN.findall(json.dumps(doc, default=plain)))


def other_records(db, org: str, gone: set[str], kept: set[str]) -> dict:
    """Records outside the log (time series, photo and document files, links,
    runs, apply keys, ...: every ``maintenance_*`` collection) that name a node
    that goes. ``only``: their ids, for those that name no kept node and no other
    organisation (these go with the purge); ``shared``: the rest (left alone)."""
    out: dict = {}
    for name in sorted(db.list_collection_names()):
        if not name.startswith("maintenance_") or name in _LOG_COLLECTIONS:
            continue
        only, shared = [], []
        for doc in db[name].find({}):
            words = _words(doc)
            if not words & gone:
                continue
            meta = doc.get("m") if isinstance(doc.get("m"), dict) else {}  # a time series row's
            doc_org = doc.get("org") or meta.get("org")
            if words & kept or (doc_org and doc_org != org):
                shared.append(doc["_id"])
            else:
                only.append(doc["_id"])
        if only or shared:
            out[name] = {"only": only, "shared": shared}
    return out


# ---- checking the result ----------------------------------------------------------------------

def compare(before: tuple[list, list], after: tuple[list, list], gone: set[str]) -> dict:
    """The graph after a purge against the graph before it: what's left of
    ``gone``, and every other node and edge that differs (each should be empty)."""
    def keep_nodes(rows):
        return {r for r in rows if r[0] not in gone}

    def keep_edges(rows):
        return {r for r in rows if r[3] not in gone and r[4] not in gone}

    nodes_b, nodes_a = keep_nodes(before[0]), set(after[0])
    edges_b, edges_a = keep_edges(before[1]), set(after[1])
    return {
        "left": sorted(r[0] for r in after[0] if r[0] in gone)
        + sorted(r[0] for r in after[1] if r[3] in gone or r[4] in gone),
        "nodes_changed": len(nodes_b ^ nodes_a),
        "edges_changed": len(edges_b ^ edges_a),
        "nodes": len(after[0]), "edges": len(after[1]),
    }
