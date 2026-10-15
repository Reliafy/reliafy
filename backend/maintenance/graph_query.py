"""Named graph queries: each answered as one Cypher round trip when Neo4j holds
the workspace's graph up to date, else by the Python walks over the store.

Neo4j holds it when it is the store (``MAINTENANCE_GRAPH=neo4j``), or when a
mirror (``mirror.py``) is attached with queries on and is up to date for the
organisation: the query itself checks that (the mirror's position against the
last event that changed the organisation's graph here), so a stale mirror
costs the round trip and the Python answer, never a wrong one. Neo4j being
unreachable is logged and answered in Python too.

Both ways give the same result (tests hold them to it):

* :func:`downstream` - what loses supply if a position fails: every position
  downstream of it through live connections, nearest first, each with the
  connection it's reached by (Maintenance.impact).
* :func:`location_rollup` - a location and the locations inside it, the
  positions there (set on them or inherited) and the items placed there.
* :func:`class_members` - an item class, the live classes inside it, and the
  items and parts whose class (their own, or an item's part's) is one of them.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


class Stale(Exception):
    """Neo4j doesn't hold the organisation's graph up to date (``use="cypher"``)."""


def _cypher_target(m):
    """(connection, namespace, freshness check or None) when Cypher may answer, else None."""
    from backend.maintenance.neo4j_store import Neo4jGraphStore

    s = m.s
    if isinstance(s, Neo4jGraphStore):
        return s.conn, s.ns, None
    mirror = getattr(s, "mirror", None)
    if mirror is None or not mirror.queries or not mirror.in_scope(m.org):
        return None  # (a workspace outside the mirror's scope is never in Neo4j)
    return mirror.conn, mirror.ns, {"need": s.org_mark(m.org), "version": mirror.version}


_FRESH = """
OPTIONAL MATCH (mm:MaintenanceMirror {ns: $ns, org: $org})
WITH coalesce(mm.applied >= $need AND mm.version = $version, false) AS fresh
"""


def _run(m, name: str, body: str, params: dict, python, use: str):
    """Answer by Cypher (``body`` returns ``rows``) or Python. ``use``: "auto"
    (Cypher when it can, else Python), "python", or "cypher" (raise
    :class:`Stale` rather than answer in Python)."""
    target = None if use == "python" else _cypher_target(m)
    if target is None:
        if use == "cypher":
            raise Stale(f"{name}: no Neo4j graph to ask")
        return python()
    conn, ns, check = target
    query = (_FRESH if check else "WITH true AS fresh\n") + "CALL (fresh) {\n  WITH fresh WHERE fresh\n" + body + \
        "\n}\nRETURN fresh, rows"
    try:
        rows = conn.run(query, {"ns": ns, "org": m.org, **(check or {}), **params}, timeout=10)
    except Exception as err:  # noqa: BLE001 - answered in Python instead
        if use == "cypher":
            raise
        logger.warning("graph query %s failed in Neo4j (%s: %s); answering in Python", name, type(err).__name__, err)
        return python()
    if not rows or not rows[0]["fresh"]:
        if use == "cypher":
            raise Stale(f"{name}: the Neo4j graph is behind for {m.org}")
        return python()
    return rows[0]["rows"]


# ---- downstream: what loses supply ------------------------------------------------------

_DOWNSTREAM = """
  MATCH (s:Node {ns: $ns, org: $org, id: $id})
  OPTIONAL MATCH p = SHORTEST 1 (s)((x)<-[:FROM]-(i:Interface WHERE NOT coalesce(i.retired = true, false))
                                    -[:TO]->(y)){1,}(t:Node)
  WHERE t <> s AND t.label IS NOT NULL
  WITH s, collect({t: t, d: length(p) / 2}) AS reached
  UNWIND reached AS r
  WITH s, reached, r WHERE r.t IS NOT NULL
  MATCH (a:Node)<-[:FROM]-(i:Interface)-[:TO]->(t:Node)
  WHERE t = r.t AND NOT coalesce(i.retired = true, false) AND a.label IS NOT NULL
    AND ((r.d = 1 AND a = s) OR any(q IN reached WHERE q.t = a AND q.d = r.d - 1))
  RETURN collect({id: t.id, name: t.name, depth: r.d, from_id: a.id, from_name: a.name,
                  interface: i.id, kind: i.kind}) AS rows
"""


def _downstream_python(m, position_id: str) -> list[dict]:
    """Breadth first through live connections: every (reached, from, interface)
    with the reached position one step further than the one it's from."""
    depth, frontier, rows, d = {position_id: 0}, [position_id], [], 0
    while frontier:
        d += 1
        found = []
        for current in frontier:
            for i in m._interfaces(current, "FROM"):
                nxt = i["to"]["id"]
                if depth.get(nxt, d) < d:
                    continue  # reached nearer (or the start)
                if nxt not in depth:
                    depth[nxt] = d
                    found.append(nxt)
                rows.append({"id": nxt, "name": i["to"]["name"], "depth": d, "from_id": current,
                             "from_name": i["from"]["name"], "interface": i["id"], "kind": i["kind"]})
        frontier = found
    return rows


def _downstream_view(rows: list[dict]) -> list[dict]:
    """One row per position reached: nearest first, then by name; reached by the
    first of its connections from a position one step nearer (by that position's
    name, then the kind of connection)."""
    best: dict[str, dict] = {}
    for r in rows:
        key = (r["from_name"] or "", r["from_id"], r["kind"] or "", r["interface"])
        if r["id"] not in best or key < best[r["id"]]["key"]:
            best[r["id"]] = {**r, "key": key}
    ordered = sorted(best.values(), key=lambda r: (r["depth"], (r["name"] or "").lower(), r["id"]))
    return [{"id": r["id"], "name": r["name"], "via": r["kind"], "from": r["from_name"], "depth": r["depth"]}
            for r in ordered]


def downstream(m, position_id: str, use: str = "auto") -> list[dict]:
    """The positions downstream of one: [{id, name, via, from, depth}]."""
    rows = _run(m, "downstream", _DOWNSTREAM, {"id": position_id},
                lambda: _downstream_python(m, position_id), use)
    return _downstream_view(rows)


# ---- a location's roll-up -------------------------------------------------------------------
# A position takes the location set on it, or inherits its parent's (a position
# inside an item: where the item is: its position's while it's fitted, where
# it's placed while it isn't). Walking down from the locations: the positions
# located there, and the items placed there now; then, step by step, positions
# inside them that don't set their own (and aren't retired), and the items
# fitted to those positions now.

_ROLLUP = """
  MATCH (root:Node {ns: $ns, org: $org, id: $id})
  MATCH (l:Location)((:Location)-[:PART_OF]->(:Location)){0,}(root)
  WITH collect(DISTINCT l) AS locs
  CALL (locs) {
    UNWIND locs AS l
    MATCH (it:Item)-[:IN]->(pl:Placement)-[:AT]->(l)
    WHERE pl.to IS NULL
      AND NOT EXISTS { (it)-[:IN]->(f:Fitment) WHERE f.to IS NULL AND NOT coalesce(f.voided = true, false) }
      AND NOT EXISTS { (it)-[:IN]->(p2:Placement) WHERE p2.to IS NULL AND p2.from > pl.from }
      AND NOT EXISTS { (it)-[:IN]->(f:Fitment) WHERE NOT coalesce(f.voided = true, false) AND f.to IS NOT NULL
                       AND f.to > pl.from }
    RETURN collect({item: it, loc: l, placement: pl}) AS loose
  }
  CALL (locs, loose) {
    CALL (locs, loose) {
      UNWIND locs AS l
      MATCH (src:Position)-[:LOCATED_AT]->(l) WHERE NOT coalesce(src.retired = true, false)
      RETURN src, l
      UNION
      UNWIND loose AS x
      RETURN x.item AS src, x.loc AS l
    }
    MATCH (src)((c)<-[r:PART_OF|AT|IN]-(x) WHERE
        (type(r) = 'PART_OF' AND x:Position AND NOT coalesce(x.retired = true, false)
         AND NOT EXISTS { (x)-[:LOCATED_AT]->(y) WHERE y.label IS NOT NULL })
        OR (type(r) = 'AT' AND x:Fitment AND c:Position AND x.to IS NULL AND NOT coalesce(x.voided = true, false))
        OR (type(r) = 'IN' AND x:Item AND c:Fitment)){0,}(p:Position)
    RETURN collect(DISTINCT [p.id, l.id, src.id]) AS positions
  }
  RETURN {locations: [l IN locs | l.id], positions: positions,
          items: [x IN loose | [x.item.id, x.loc.id, x.placement.id]]} AS rows
"""


def _rollup_python(m, location_id: str) -> dict:
    inside = m._location_ids_in(location_id)
    return {"locations": inside,
            "positions": [[p["id"], at["id"], source["id"]] for p, at, source in m._positions_at(inside)],
            "items": [[item["id"], at["id"], placement["id"]] for item, at, placement in m._loose_items(inside)]}


def location_rollup(m, location_id: str, use: str = "auto") -> dict:
    """{locations: [ids], positions: [[position, location it's at, where that's set
    (itself, an ancestor, or an item)]], items: [[item, location, placement]]},
    each sorted."""
    m._get(location_id, "Location")
    got = _run(m, "location_rollup", _ROLLUP, {"id": location_id}, lambda: _rollup_python(m, location_id), use)
    return {"locations": sorted(got["locations"]), "positions": sorted(list(r) for r in got["positions"]),
            "items": sorted(list(r) for r in got["items"])}


# ---- an item class's members ---------------------------------------------------------------

_CLASS = """
  MATCH (root:Node {ns: $ns, org: $org, id: $id})
  MATCH (c)((a:ItemClass WHERE NOT coalesce(a.retired = true, false))-[:PART_OF]->(:Node)){0,}(root)
  WITH collect(DISTINCT c) AS classes
  CALL (classes) {
    CALL (classes) {
      UNWIND classes AS c
      MATCH (x)-[:CLASSED_AS]->(c) WHERE x:Item OR x:Part
      RETURN x
      UNION
      UNWIND classes AS c
      MATCH (x:Item)-[:OF_PART]->(pt:Node)-[:CLASSED_AS]->(c)
      WHERE pt.label IS NOT NULL AND NOT EXISTS { (x)-[:CLASSED_AS]->(y) WHERE y.label IS NOT NULL }
      RETURN x
    }
    RETURN collect(DISTINCT x) AS members
  }
  RETURN {classes: [c IN classes | c.id], items: [x IN members WHERE x:Item | x.id],
          parts: [x IN members WHERE x:Part | x.id]} AS rows
"""


def _class_python(m, class_id: str) -> dict:
    ids = {c["id"] for c in m._class_subtree(class_id)}
    found = {"Item": [], "Part": []}
    for label in found:
        for node in m.s.nodes(m.org, label):
            if (m._effective_class(node)[0] or {}).get("id") in ids:
                found[label].append(node["id"])
    return {"classes": list(ids), "items": found["Item"], "parts": found["Part"]}


def class_members(m, class_id: str, use: str = "auto") -> dict:
    """{classes: [the class and the live classes inside it], items: [...], parts: [...]},
    each a sorted list of ids."""
    m._get(class_id, "ItemClass")
    got = _run(m, "class_members", _CLASS, {"id": class_id}, lambda: _class_python(m, class_id), use)
    return {k: sorted(got[k]) for k in ("classes", "items", "parts")}
