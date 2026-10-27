"""The maintenance graph in Neo4j: the same projection as the SQLite graph
(``store.GraphStore``), behind the same methods.

Nodes are ``(:Node:<Label> {ns, org, id, label, props, ...})``: ``props`` is the
node's properties as JSON (exactly as the SQLite graph keeps them, so the two
compare equal), and its plain values (text, numbers, true/false and lists of
one of them) are copied onto the node as well, so Cypher can match on them
(``n.name``, ``n.retired``, ``n.to``). Edges are relationships of their type,
``-[:PART_OF {id, props}]->``. ``ns`` is a namespace: one database can hold
several graphs (a projection version, a test) without their rows meeting.
Nodes are unique by ``(ns, org, id)``; an edge to a node that isn't there yet
holds a stub (``(:Node {ns, org, id})``, no label), which reads pass over, as
the SQLite graph's joins do.

Two uses:

* :class:`Neo4jGraphStore`, the graph itself, when Neo4j is the primary store
  (``MAINTENANCE_GRAPH=neo4j``). Events are applied one transaction each,
  advancing ``applied`` on ``(:MaintenanceGraph {ns})`` in the same statement
  with an optimistic check on its previous value, so several processes can
  apply one log and none applies an event twice or passes one over.
* A mirror (``mirror.py``) of the SQLite graph, kept in step in the background
  (``MAINTENANCE_GRAPH_MIRROR=neo4j``), for graph queries.

Needs Neo4j 5.26 or later (dynamic labels and relationship types).
"""

from __future__ import annotations

import json
import logging
import math
import threading
import time

from backend.maintenance import store as _store
from backend.maintenance.store import Projector, SqliteEventLog, UnknownEvent, _notify, _now, new_id, open_sqlite

logger = logging.getLogger(__name__)

# ---- the connection ---------------------------------------------------------------------

SCHEMA = (
    "CREATE CONSTRAINT maintenance_node_key IF NOT EXISTS FOR (n:Node) REQUIRE (n.ns, n.org, n.id) IS UNIQUE",
    "CREATE INDEX maintenance_node_label IF NOT EXISTS FOR (n:Node) ON (n.ns, n.org, n.label)",
    "CREATE INDEX maintenance_node_org IF NOT EXISTS FOR (n:Node) ON (n.ns, n.org)",
    "CREATE CONSTRAINT maintenance_graph_key IF NOT EXISTS FOR (m:MaintenanceGraph) REQUIRE m.ns IS UNIQUE",
    "CREATE CONSTRAINT maintenance_mirror_key IF NOT EXISTS FOR (m:MaintenanceMirror) REQUIRE (m.ns, m.org) IS UNIQUE",
)


class Neo4jConnection:
    """A driver and the database to use. Each call is one auto-commit statement
    (one round trip), retried once if the connection dropped. Sessions share
    the driver's bookmarks, so a read sees the writes before it in a cluster."""

    def __init__(self, driver, database: str | None = None):
        self.driver = driver
        self.database = database or None
        self._schema_done = False
        self._schema_lock = threading.Lock()

    def run(self, query: str, params: dict | None = None, write: bool = False,
            timeout: float | None = None) -> list[dict]:
        from neo4j import READ_ACCESS, WRITE_ACCESS, Query
        from neo4j.exceptions import ServiceUnavailable, SessionExpired

        for attempt in (1, 2):
            try:
                with self.driver.session(database=self.database,
                                         default_access_mode=WRITE_ACCESS if write else READ_ACCESS,
                                         bookmark_manager=self.driver.execute_query_bookmark_manager) as session:
                    return session.run(Query(query, timeout=timeout), params or {}).data()
            except (ServiceUnavailable, SessionExpired):
                if attempt == 2:
                    raise
                logger.info("neo4j connection dropped; retrying once")
        return []  # unreachable

    def transaction(self):
        """A session and an explicit transaction in it, for a write too large for
        one statement: ``with conn.transaction() as tx: tx.run(...)``."""
        return _Tx(self)

    def ensure_schema(self) -> None:
        """The constraints and indexes (once per connection)."""
        with self._schema_lock:
            if self._schema_done:
                return
            for statement in SCHEMA:
                self.run(statement, write=True)
            self._schema_done = True

    def ping(self) -> float:
        """One trivial query; returns the seconds it took (a keep-alive)."""
        t = time.monotonic()
        self.run("RETURN 1 AS ok")
        return time.monotonic() - t

    def close(self) -> None:
        self.driver.close()


class _Tx:
    def __init__(self, conn: Neo4jConnection):
        self._conn = conn

    def __enter__(self):
        from neo4j import WRITE_ACCESS

        self._session = self._conn.driver.session(
            database=self._conn.database, default_access_mode=WRITE_ACCESS,
            bookmark_manager=self._conn.driver.execute_query_bookmark_manager)
        self.tx = self._session.begin_transaction()
        return self

    def run(self, query: str, params: dict | None = None) -> list[dict]:
        return self.tx.run(query, params or {}).data()

    def commit(self) -> None:
        self.tx.commit()

    def __exit__(self, kind, err, tb):
        try:
            if self.tx.closed() is False:
                self.tx.rollback()
        finally:
            self._session.close()
        return False


def connect(uri: str | None = None, username: str | None = None, password: str | None = None,
            database: str | None = None) -> Neo4jConnection:
    """A connection from the arguments, else ``NEO4J_*`` in config. Makes no
    round trip: the first query connects."""
    from neo4j import GraphDatabase

    from backend import config

    uri = uri or config.NEO4J_URI
    if not uri:
        raise RuntimeError("NEO4J_URI isn't set.")
    driver = GraphDatabase.driver(
        uri, auth=(username or config.NEO4J_USERNAME, password or config.NEO4J_PASSWORD),
        connection_timeout=10, connection_acquisition_timeout=20, liveness_check_timeout=60,
        notifications_min_severity="OFF",
    )
    return Neo4jConnection(driver, database or config.NEO4J_DATABASE)


# ---- rows: what a node or edge is written as ------------------------------------------------

_RESERVED = {"ns", "org", "id", "label", "props", "_w"}
_INT64 = 2 ** 63


def _plain(value) -> bool:
    if isinstance(value, bool) or isinstance(value, str):
        return True
    if isinstance(value, int):
        return -_INT64 <= value < _INT64
    return isinstance(value, float)


def _list_kind(values: list):
    kinds = set()
    for v in values:
        if not _plain(v):
            return None
        kinds.add(bool if isinstance(v, bool) else int if isinstance(v, int) else type(v))
    return kinds.pop() if len(kinds) == 1 else None


def promoted(props: dict) -> dict:
    """The properties Neo4j can hold as they are: text, numbers, true/false, and
    non-empty lists of one of them. (Nested values stay in the JSON only.)"""
    out = {}
    for key, value in props.items():
        if key in _RESERVED or not isinstance(key, str) or value is None:
            continue
        if _plain(value) and not (isinstance(value, float) and math.isnan(value)):
            out[key] = value
        elif isinstance(value, list) and value and _list_kind(value) is not None:
            out[key] = value
    return out


def node_row(ns: str, org: str, id: str, label: str, props_json: str, props: dict | None, w: int) -> dict:
    """A node as the write statement takes it."""
    if props is None:
        props = json.loads(props_json)
    return {"org": org, "id": id, "label": label,
            "set": {**promoted(props), "ns": ns, "org": org, "id": id, "label": label, "props": props_json, "_w": w}}


# ---- the write statement ---------------------------------------------------------------------
# One statement writes a batch: nodes (replaced whole, their typed label kept in
# step), edges deleted, edges written. Each part runs only when ``ok``: the
# check a caller puts before it (an optimistic check on ``applied``). The node
# being checked is locked first (SET then REMOVE a property), so two writers
# take turns, and the second sees the first's ``applied``.

WRITE_BODY = """
CALL (ok) {
  WITH ok WHERE ok AND $full
  MATCH (n:Node {ns: $ns, org: $org})
  DETACH DELETE n
}
CALL (ok) {
  WITH ok WHERE ok
  UNWIND $nodes AS row
  MERGE (n:Node {ns: $ns, org: row.org, id: row.id})
  WITH n, row, n.label AS old
  SET n = row.set
  SET n:$(row.label)
  WITH n, old, row WHERE old IS NOT NULL AND old <> row.label
  REMOVE n:$(old)
}
CALL (ok) {
  WITH ok WHERE ok
  UNWIND $gone AS g
  MATCH (:Node {ns: $ns, org: g.org, id: g.src})-[r]->(:Node {ns: $ns, org: g.org, id: g.dst})
  WHERE type(r) = g.type AND (g.id IS NULL OR r.id = g.id)
  DELETE r
}
CALL (ok) {
  WITH ok WHERE ok
  UNWIND $edges AS e
  MERGE (a:Node {ns: $ns, org: e.org, id: e.src})
  MERGE (b:Node {ns: $ns, org: e.org, id: e.dst})
  MERGE (a)-[r:$(e.type) {id: e.id}]->(b)
  SET r.props = e.props, r._w = e.w
}
"""

# An event applied to the primary graph: only if ``applied`` is still the
# position the event follows (and the version this code projects).
GRAPH_EVENT = """
MATCH (m:MaintenanceGraph {ns: $ns})
SET m._lock = true
REMOVE m._lock
WITH m, (m.applied = $prev AND m.version = $version) AS ok
""" + WRITE_BODY + """
SET m.applied = CASE WHEN ok THEN $seq ELSE m.applied END,
    m.skipped = CASE WHEN ok AND $skipped IS NOT NULL THEN (coalesce(m.skipped, []) + [$skipped])[-100..]
                ELSE m.skipped END
RETURN ok, m.applied AS applied, m.version AS version
"""

# Writes with no check (a write outside an event; a chunk of a larger write
# whose first statement made the check).
UNCHECKED = "WITH true AS ok" + WRITE_BODY + "RETURN ok"


def write_params(ns: str, nodes=(), gone=(), edges=(), full: bool = False, org: str | None = None, **extra) -> dict:
    return {"ns": ns, "org": org, "full": full, "nodes": list(nodes), "gone": list(gone), "edges": list(edges),
            **extra}


# ---- reading -----------------------------------------------------------------------------------

_NODE = """
MATCH (n:Node {ns: $ns, org: $org, id: $id}) WHERE n.label IS NOT NULL
RETURN n.id AS id, n.label AS label, n.props AS props
"""
_NODES = """
MATCH (n:Node {ns: $ns, org: $org, label: $label})
RETURN n.id AS id, n.label AS label, n.props AS props ORDER BY n._w
"""
# The ends of a node's edges of one type, in the order they were written, and
# (for a projection's own edges not written yet) a few more nodes by id.
_ENDS = """
OPTIONAL MATCH (:Node {{ns: $ns, org: $org, id: $id}}){arrow}(n:Node)
WHERE type(r) = $type AND n.label IS NOT NULL
WITH r, n ORDER BY r._w
WITH collect(CASE WHEN n IS NULL THEN NULL ELSE {{id: n.id, label: n.label, props: n.props}} END) AS ends
OPTIONAL MATCH (x:Node {{ns: $ns, org: $org}}) WHERE x.id IN $extra AND x.label IS NOT NULL
RETURN ends, collect(CASE WHEN x IS NULL THEN NULL ELSE {{id: x.id, label: x.label, props: x.props}} END) AS extra
"""
_OUT = _ENDS.format(arrow="-[r]->")
_INN = _ENDS.format(arrow="<-[r]-")
# Every edge of one type in an organisation, by its ends' ids.
_PAIRS = """
MATCH (a:Node {ns: $ns, org: $org})-[r]->(b:Node {ns: $ns, org: $org})
WHERE type(r) = $type
RETURN a.id AS src, b.id AS dst
"""
# One edge's properties, found by its ends.
_EDGE = """
MATCH (:Node {ns: $ns, org: $org, id: $src})-[r]->(:Node {ns: $ns, org: $org, id: $dst})
WHERE type(r) = $type
RETURN r.props AS props LIMIT 1
"""


def _node(row) -> dict:
    return {"id": row["id"], "label": row["label"], **json.loads(row["props"])}


def graph_snapshot(conn: Neo4jConnection, ns: str, org: str | None = None) -> tuple[list, list]:
    """Every node and edge in a namespace (of one organisation, if given), in the
    shape and order of ``GraphStore.snapshot``."""
    params = {"ns": ns, "org": org}
    nodes = conn.run("MATCH (n:Node {ns: $ns}) WHERE n.label IS NOT NULL AND ($org IS NULL OR n.org = $org) "
                     "RETURN n.id AS id, n.org AS org, n.label AS label, n.props AS props", params)
    edges = conn.run("MATCH (a:Node {ns: $ns})-[r]->(b:Node) WHERE $org IS NULL OR a.org = $org "
                     "RETURN r.id AS id, a.org AS org, type(r) AS type, a.id AS src, b.id AS dst, r.props AS props",
                     params)
    return (sorted(((r["id"], r["org"], r["label"], r["props"]) for r in nodes), key=lambda t: (t[1], t[0])),
            sorted(((r["id"], r["org"], r["type"], r["src"], r["dst"], r["props"]) for r in edges),
                   key=lambda t: (t[1], t[0])))


def delete_namespace(conn: Neo4jConnection, ns: str, org: str | None = None) -> None:
    """Remove a namespace's graph (or one organisation's), with its bookkeeping."""
    conn.run("MATCH (n:Node {ns: $ns}) WHERE $org IS NULL OR n.org = $org "
             "CALL (n) { DETACH DELETE n } IN TRANSACTIONS OF 5000 ROWS", {"ns": ns, "org": org}, write=True)
    conn.run("MATCH (m:MaintenanceMirror {ns: $ns}) WHERE $org IS NULL OR m.org = $org DELETE m",
             {"ns": ns, "org": org}, write=True)
    if org is None:
        conn.run("MATCH (m:MaintenanceGraph {ns: $ns}) DELETE m", {"ns": ns}, write=True)


# ---- the graph -----------------------------------------------------------------------------------

class _Pending:
    """One event's writes, held until it's applied in one statement. Reads made
    while it's projected see them (the projectors read their own writes)."""

    def __init__(self, seq: int):
        self.seq = seq
        self.count = 0
        self.nodes: dict[tuple[str, str], dict] = {}  # (org, id) -> {label, props, w}
        self.edges: dict[tuple[str, str, str, str], dict] = {}  # (org, type, src, dst) -> {op, id, props, w}

    def w(self) -> int:
        # Written-order stamps: later events, then later writes, sort after.
        self.count += 1
        return self.seq * 100_000 + self.count


class Neo4jGraphStore:
    """The maintenance graph in Neo4j (see the module docstring). The methods and
    their results are those of ``store.GraphStore``; with no log given, the log
    (and the time series) live in an in-memory SQLite database (for tests)."""

    def __init__(self, conn: Neo4jConnection, projectors: dict[str, Projector], log=None, series=None,
                 version: int = 1, namespace: str = ""):
        self.conn = conn
        self.ns = namespace
        self.version = version
        conn.ensure_schema()
        self._lock = threading.RLock()
        self._projectors = projectors
        self._local = threading.local()  # the event being projected, per thread
        self._gap: tuple[int, float] | None = None
        self._event_counts: dict[str, int] = {}
        self.write_windows: dict = {}
        self.series_days: dict = {}
        self.listeners: list = []
        self.mirror = None
        if log is None or series is None:
            local = open_sqlite(":memory:")
        self.log = log if log is not None else SqliteEventLog(local, self._lock)
        from backend.maintenance.series import SqliteSeries

        self.series = series if series is not None else SqliteSeries(local, self._lock)
        rows = conn.run("MERGE (m:MaintenanceGraph {ns: $ns}) "
                        "ON CREATE SET m.applied = 0, m.version = $version, m.skipped = [] "
                        "RETURN m.applied AS applied, m.version AS version", {"ns": namespace, "version": version},
                        write=True)
        self._known = int(rows[0]["applied"])
        if rows[0]["version"] != version:
            if self._known:
                self.rebuild()
            else:
                conn.run("MATCH (m:MaintenanceGraph {ns: $ns}) SET m.version = $version",
                         {"ns": namespace, "version": version}, write=True)

    # ---- applied position ------------------------------------------------------------

    def _meta(self) -> tuple[int, int]:
        rows = self.conn.run("MATCH (m:MaintenanceGraph {ns: $ns}) RETURN m.applied AS applied, m.version AS version",
                             {"ns": self.ns})
        if not rows:
            raise RuntimeError(f"The maintenance graph {self.ns!r} has no bookkeeping node; was it deleted?")
        if rows[0]["version"] != self.version:
            raise RuntimeError(f"The maintenance graph {self.ns!r} is at projection version {rows[0]['version']}, "
                               f"and this process projects version {self.version}: restart it, or rebuild.")
        return int(rows[0]["applied"]), int(rows[0]["version"])

    def _applied(self) -> int:
        return self._meta()[0]

    def skipped(self) -> list[dict]:
        rows = self.conn.run("MATCH (m:MaintenanceGraph {ns: $ns}) RETURN m.skipped AS skipped", {"ns": self.ns})
        return [json.loads(x) for x in (rows[0]["skipped"] or [])] if rows else []

    # ---- writing: events -------------------------------------------------------------

    def _pending(self) -> _Pending | None:
        return getattr(self._local, "pending", None)

    def _commit(self, pending: _Pending, prev: int, seq: int, skipped: dict | None = None) -> bool:
        """Apply one event's writes and advance ``applied`` from ``prev`` to ``seq``,
        in one statement. False when ``applied`` wasn't ``prev`` (another process
        got there first): nothing was written."""
        from neo4j.exceptions import TransientError

        params = write_params(self.ns, *self._rows(pending), prev=prev, seq=seq, version=self.version,
                              skipped=json.dumps(skipped) if skipped else None)
        try:
            rows = self.conn.run(GRAPH_EVENT, params, write=True)
        except TransientError:  # a deadlock with another writer: try again from the top
            logger.info("maintenance event %s: transient Neo4j error; retrying", seq, exc_info=True)
            return False
        return bool(rows and rows[0]["ok"])

    def _rows(self, pending: _Pending) -> tuple[list, list, list]:
        nodes = [node_row(self.ns, org, id, n["label"], json.dumps(n["props"]), n["props"], n["w"])
                 for (org, id), n in pending.nodes.items()]
        gone = [{"org": org, "type": type, "src": src, "dst": dst, "id": None}
                for (org, type, src, dst), e in pending.edges.items() if e["op"] == "del"]
        edges = [{"org": org, "type": type, "src": src, "dst": dst, "id": e["id"], "props": e["props"], "w": e["w"]}
                 for (org, type, src, dst), e in pending.edges.items() if e["op"] == "put"]
        return nodes, gone, edges

    def _project(self, e: dict, prev: int) -> bool:
        """Project one event and apply it (see ``GraphStore._project``: an event that
        can't be projected is passed over and recorded in :meth:`skipped`). False
        when another process applied it first."""
        from neo4j.exceptions import DriverError, Neo4jError

        pending = _Pending(e["seq"])
        self._local.pending = pending
        try:
            projector = self._projectors.get(e["type"])
            if projector is None:
                raise UnknownEvent(e["type"])
            projector(self, e["org"], e["payload"])
        except (Neo4jError, DriverError):
            raise  # Neo4j's trouble, not the event's: stop here, and try it again later
        except Exception as err:  # noqa: BLE001 - see GraphStore._project
            self._local.pending = None
            logger.exception("maintenance event %s (%s) couldn't be projected; passed over", e["seq"], e["type"])
            ok = self._commit(_Pending(e["seq"]), prev, e["seq"],
                              {"seq": e["seq"], "why": f"{type(err).__name__} in {e['type']}"})
        else:
            self._local.pending = None
            ok = self._commit(pending, prev, e["seq"])
        finally:
            self._local.pending = None
        if ok and e["org"] in self._event_counts:
            self._event_counts[e["org"]] += 1
        return ok

    def sync(self) -> int:
        """Apply the log's events this graph hasn't seen yet, strictly in sequence
        (see ``GraphStore.sync``: gaps are waited for, then passed over; the
        timings are store.py's). Returns how many this process applied."""
        with self._lock:
            done = 0
            while True:
                applied = self._known = self._meta()[0]
                events = self.log.since(applied, _store.SYNC_BATCH)
                if not events:
                    return done
                raced = False
                for e in events:
                    if e["seq"] != applied + 1:
                        break
                    if not self._project(e, applied):
                        raced = True
                        break
                    applied = self._known = e["seq"]
                    done += 1
                if raced:
                    self._event_counts.clear()  # counted again from the log
                    continue
                if applied == events[-1]["seq"]:
                    continue
                missing = applied + 1
                now = time.monotonic()
                if self._gap is None or self._gap[0] != missing:
                    self._gap = (missing, now)
                age = now - self._gap[1]
                if age >= _store.GAP_TIMEOUT:
                    logger.warning("maintenance event %s never reached the log; passed over", missing)
                    self._commit(_Pending(missing), applied, missing, {"seq": missing, "why": "missing from the log"})
                    self._gap = None
                    continue
                if age >= _store.GAP_WAIT:
                    return done
                time.sleep(0.02)

    def apply(self, org: str, type: str, payload: dict, actor: str | None = None) -> dict:
        """Append an event and bring the graph up to date with it, after a dry run
        (the projector run with its writes held back and dropped)."""
        if type not in self._projectors:
            raise UnknownEvent(type)
        event = {"id": new_id(), "org": org, "type": type, "at": _now(), "actor": actor, "payload": payload}
        with self._lock:
            self.sync()
            self._local.pending = _Pending(self._known + 1)
            try:
                self._projectors[type](self, org, payload)
            finally:
                self._local.pending = None
            seq = self.log.append(event)
            self.sync()
        deadline = time.monotonic() + _store.GAP_TIMEOUT + 2
        while self._known < seq:
            if time.monotonic() > deadline:
                raise RuntimeError(f"Maintenance event {seq} is in the log but not applied yet.")
            time.sleep(0.05)
            self.sync()
        _notify(self.listeners, org)
        return event

    def event_count(self, org: str) -> int:
        with self._lock:
            if org not in self._event_counts:
                self.sync()
                self._event_counts[org] = self.log.count(org)
            return self._event_counts[org]

    def count(self, org: str, label: str) -> int:
        rows = self.conn.run("MATCH (n:Node {ns: $ns, org: $org, label: $label}) RETURN count(n) AS n",
                             {"ns": self.ns, "org": org, "label": label})
        return int(rows[0]["n"])

    def rebuild(self) -> int:
        """Clear the graph and replay the whole log. Returns the events replayed.
        Readers see the graph empty and refilling meanwhile: for a projection
        version, use a fresh namespace instead (the router does)."""
        with self._lock:
            self.conn.run("MATCH (n:Node {ns: $ns}) CALL (n) { DETACH DELETE n } IN TRANSACTIONS OF 5000 ROWS",
                          {"ns": self.ns}, write=True)
            self.conn.run("MERGE (m:MaintenanceGraph {ns: $ns}) SET m.applied = 0, m.version = $version, "
                          "m.skipped = []", {"ns": self.ns, "version": self.version}, write=True)
            self._known = 0
            self._gap = None
            self._event_counts.clear()
            return self.sync()

    def events(self, org: str, limit: int = 100, since: int | None = None, type: str | None = None) -> list[dict]:
        return self.log.recent(org, limit, since, type)

    # ---- writing: the graph (projectors only) -----------------------------------------

    def _write_now(self, pending: _Pending) -> None:
        """A write outside an event (tests): applied at once."""
        self.conn.run(UNCHECKED, write_params(self.ns, *self._rows(pending)), write=True)

    def _target(self) -> tuple[_Pending, bool]:
        pending = self._pending()
        return (pending, False) if pending is not None else (_Pending(self._known + 1), True)

    def put_node(self, org: str, id: str, label: str, props: dict) -> None:
        pending, now = self._target()
        # Through JSON, as the SQLite graph stores it: reads give back the same values.
        pending.nodes[(org, id)] = {"label": label, "props": json.loads(json.dumps(props)), "w": pending.w()}
        if now:
            self._write_now(pending)

    def patch_node(self, org: str, id: str, changes: dict) -> None:
        node = self.node(org, id)
        if node is None:
            raise KeyError(id)
        props = {k: v for k, v in node.items() if k not in ("id", "label")}
        props.update(changes)
        self.put_node(org, id, node["label"], props)

    def put_edge(self, org: str, type: str, src: str, dst: str, props: dict | None = None,
                 id: str | None = None) -> None:
        # The id, as in the SQLite graph, comes from the ends; an edge given its own
        # id is still found by its ends (keep one id to one pair of ends).
        pending, now = self._target()
        pending.edges[(org, type, src, dst)] = {"op": "put", "id": id or f"{type}:{src}:{dst}",
                                                "props": json.dumps(props or {}), "w": pending.w()}
        if now:
            self._write_now(pending)

    def delete_edge(self, org: str, type: str, src: str, dst: str) -> None:
        pending, now = self._target()
        pending.edges[(org, type, src, dst)] = {"op": "del"}
        if now:
            self._write_now(pending)

    # ---- reading ---------------------------------------------------------------------

    def node(self, org: str, id: str, label: str | None = None) -> dict | None:
        if not isinstance(id, str):
            return None
        pending = self._pending()
        if pending is not None and (org, id) in pending.nodes:
            held = pending.nodes[(org, id)]
            found = {"id": id, "label": held["label"], **held["props"]}
        else:
            rows = self.conn.run(_NODE, {"ns": self.ns, "org": org, "id": id})
            found = _node(rows[0]) if rows else None
        if found is None or (label and found["label"] != label):
            return None
        return found

    def nodes(self, org: str, label: str) -> list[dict]:
        rows = [_node(r) for r in self.conn.run(_NODES, {"ns": self.ns, "org": org, "label": label})]
        pending = self._pending()
        if pending is None or not pending.nodes:
            return rows
        held = {id: n for (o, id), n in pending.nodes.items() if o == org}
        rows = [r for r in rows if r["id"] not in held]
        return rows + [{"id": id, "label": n["label"], **n["props"]}
                       for id, n in sorted(held.items(), key=lambda kv: kv[1]["w"]) if n["label"] == label]

    def _ends(self, org: str, at: str, type: str, outgoing: bool) -> list[dict]:
        if not isinstance(at, str):
            return []
        pending = self._pending()
        mine = []
        if pending is not None:
            mine = [(key, e) for key, e in pending.edges.items()
                    if key[0] == org and key[1] == type and key[2 if outgoing else 3] == at]
        extra = [key[3 if outgoing else 2] for key, e in mine
                 if e["op"] == "put" and (org, key[3 if outgoing else 2]) not in pending.nodes]
        rows = self.conn.run(_OUT if outgoing else _INN,
                             {"ns": self.ns, "org": org, "id": at, "type": type, "extra": extra})
        ends = [_node(r) for r in rows[0]["ends"]] if rows else []
        if pending is None:
            return ends
        written = {key[3 if outgoing else 2] for key, _ in mine}  # replaced or deleted by this event
        known = {r["id"]: _node(r) for r in (rows[0]["extra"] if rows else [])}
        out = [n for n in ends if n["id"] not in written]
        for key, e in sorted(((k, e) for k, e in mine if e["op"] == "put"), key=lambda kv: kv[1]["w"]):
            other = key[3 if outgoing else 2]
            node = ({"id": other} if (org, other) in pending.nodes else
                    known.get(other) or next((n for n in ends if n["id"] == other), None))
            if node is not None:
                out.append(node)
        # Nodes this event wrote read as written.
        return [({"id": n["id"], "label": pending.nodes[(org, n["id"])]["label"],
                  **pending.nodes[(org, n["id"])]["props"]} if (org, n["id"]) in pending.nodes else n) for n in out]

    def out(self, org: str, src: str, type: str) -> list[dict]:
        """Nodes at the end of ``src``'s outgoing ``type`` edges."""
        return self._ends(org, src, type, True)

    def inn(self, org: str, dst: str, type: str) -> list[dict]:
        """Nodes at the start of ``dst``'s incoming ``type`` edges."""
        return self._ends(org, dst, type, False)

    def pairs(self, org: str, type: str) -> list[tuple[str, str]]:
        """(src, dst) for every ``type`` edge in the organisation: a whole tree's
        links in one read, rather than one ``out`` per node."""
        found = [(r["src"], r["dst"]) for r in self.conn.run(_PAIRS, {"ns": self.ns, "org": org, "type": type})]
        pending = self._pending()
        if pending is None or not pending.edges:
            return found
        mine = {(k[2], k[3]): e["op"] for k, e in pending.edges.items() if k[0] == org and k[1] == type}
        return [p for p in found if p not in mine] + [p for p, op in mine.items() if op == "put"]

    def edge(self, org: str, type: str, src: str, dst: str) -> dict | None:
        """The properties of the ``type`` edge from ``src`` to ``dst`` (None: there's none)."""
        if not isinstance(src, str) or not isinstance(dst, str):
            return None
        pending = self._pending()
        held = pending.edges.get((org, type, src, dst)) if pending is not None else None
        if held is not None:
            return json.loads(held["props"]) if held["op"] == "put" else None
        rows = self.conn.run(_EDGE, {"ns": self.ns, "org": org, "src": src, "dst": dst, "type": type})
        return json.loads(rows[0]["props"] or "{}") if rows else None

    def orgs_with(self, label: str) -> list[str]:
        rows = self.conn.run("MATCH (n:Node) WHERE n.ns = $ns AND n.label = $label "
                             "RETURN DISTINCT n.org AS org ORDER BY org", {"ns": self.ns, "label": label})
        return [r["org"] for r in rows]

    def snapshot(self, org: str | None = None) -> tuple[list, list]:
        return graph_snapshot(self.conn, self.ns, org)
