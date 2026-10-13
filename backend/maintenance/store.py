"""The maintenance graph store: an event log, and the graph projected from it.

Every change is an event in the log, which is the source of truth. The graph
(nodes and edges) is a projection of the log, kept in SQLite: it records the
last event it applied (``applied``) and catches up with :meth:`GraphStore.sync`,
so several processes can share one log and each keep its own copy of the
graph. ``rebuild`` clears the graph and replays the whole log.

Two logs:

* :class:`SqliteEventLog` — in the graph's own SQLite file, for a local
  install with no database server.
* :class:`MongoEventLog` — a MongoDB collection, for a deployment: Cloud Run's
  disk doesn't last, so the graph lives in memory and is rebuilt from the log
  when an instance starts.

The graph is the Python backend; a Neo4j backend will implement the same
methods, and the same tests will run against both.

Nodes have an ``id``, a ``label`` (Position, Item, Fitment, ...) and
``props``; edges have a ``type`` and run from ``src`` to ``dst``. Every row
carries the organisation (``org``) it belongs to, and every read is scoped
to one.
"""

from __future__ import annotations

import json
import os
import sqlite3
import threading
import uuid
from datetime import datetime, timezone
from typing import Callable

Projector = Callable[["GraphStore", str, dict], None]

_GRAPH_SCHEMA = """
CREATE TABLE IF NOT EXISTS nodes (
    id    TEXT PRIMARY KEY,
    org   TEXT NOT NULL,
    label TEXT NOT NULL,
    props TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS edges (
    id    TEXT PRIMARY KEY,
    org   TEXT NOT NULL,
    type  TEXT NOT NULL,
    src   TEXT NOT NULL,
    dst   TEXT NOT NULL,
    props TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS nodes_label ON nodes (org, label);
CREATE INDEX IF NOT EXISTS edges_src ON edges (org, src, type);
CREATE INDEX IF NOT EXISTS edges_dst ON edges (org, dst, type);
"""

_EVENTS_SCHEMA = """
CREATE TABLE IF NOT EXISTS events (
    seq     INTEGER PRIMARY KEY AUTOINCREMENT,
    id      TEXT NOT NULL UNIQUE,
    org     TEXT NOT NULL,
    type    TEXT NOT NULL,
    at      TEXT NOT NULL,
    actor   TEXT,
    payload TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS events_org ON events (org, seq);
"""


def new_id() -> str:
    return uuid.uuid4().hex


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class UnknownEvent(ValueError):
    """An event type with no projector."""


# ---- event logs ----------------------------------------------------------------------

class SqliteEventLog:
    """The log as a table beside the graph, in the same file."""

    def __init__(self, conn: sqlite3.Connection, lock=None):
        self._conn = conn
        self._lock = lock or threading.RLock()
        conn.executescript(_EVENTS_SCHEMA)

    def append(self, event: dict) -> int:
        with self._lock:
            cur = self._conn.execute(
                "INSERT INTO events (id, org, type, at, actor, payload) VALUES (?, ?, ?, ?, ?, ?)",
                (event["id"], event["org"], event["type"], event["at"], event["actor"],
                 json.dumps(event["payload"])),
            )
            return int(cur.lastrowid)

    def since(self, seq: int) -> list[dict]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT seq, org, type, payload FROM events WHERE seq > ? ORDER BY seq", (seq,)
            ).fetchall()
        return [{"seq": r["seq"], "org": r["org"], "type": r["type"], "payload": json.loads(r["payload"])}
                for r in rows]

    def recent(self, org: str, limit: int) -> list[dict]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT id, type, at, actor, payload FROM events WHERE org = ? ORDER BY seq DESC LIMIT ?",
                (org, limit),
            ).fetchall()
        return [{"id": r["id"], "type": r["type"], "at": r["at"], "actor": r["actor"],
                 "payload": json.loads(r["payload"])} for r in rows]


class MongoEventLog:
    """The log as a MongoDB collection, numbered by an atomic counter so every
    process replays the events in the same order."""

    def __init__(self, db, collection: str = "maintenance_events"):
        self._events = db[collection]
        self._counters = db["maintenance_counters"]
        self._counter_id = collection
        self._events.create_index("seq", unique=True)
        self._events.create_index([("org", 1), ("seq", -1)])

    def append(self, event: dict) -> int:
        from pymongo import ReturnDocument

        counter = self._counters.find_one_and_update(
            {"_id": self._counter_id}, {"$inc": {"seq": 1}}, upsert=True,
            return_document=ReturnDocument.AFTER,
        )
        seq = int(counter["seq"])
        self._events.insert_one({"_id": event["id"], "seq": seq, "org": event["org"], "type": event["type"],
                                 "at": event["at"], "actor": event["actor"], "payload": event["payload"]})
        return seq

    def since(self, seq: int) -> list[dict]:
        return [{"seq": d["seq"], "org": d["org"], "type": d["type"], "payload": d["payload"]}
                for d in self._events.find({"seq": {"$gt": seq}}).sort("seq", 1)]

    def recent(self, org: str, limit: int) -> list[dict]:
        return [{"id": d["_id"], "type": d["type"], "at": d["at"], "actor": d.get("actor"),
                 "payload": d["payload"]}
                for d in self._events.find({"org": org}).sort("seq", -1).limit(limit)]


# ---- the graph -------------------------------------------------------------------------

class GraphStore:
    """The graph projected from an event log, in SQLite (``":memory:"`` for a
    copy rebuilt from a shared log, or for tests). With no log given, the log
    lives in the same SQLite file."""

    def __init__(self, path: str, projectors: dict[str, Projector], log=None):
        if path != ":memory:":
            os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        self._conn = sqlite3.connect(path, check_same_thread=False, isolation_level=None)
        self._conn.row_factory = sqlite3.Row
        if path != ":memory:":
            self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.executescript(_GRAPH_SCHEMA)
        self._lock = threading.RLock()
        self._projectors = projectors
        self.log = log if log is not None else SqliteEventLog(self._conn, self._lock)

    # ---- applied position -----------------------------------------------------------

    def _applied(self) -> int:
        rows = self._all("SELECT value FROM meta WHERE key = 'applied'", ())
        return int(rows[0]["value"]) if rows else 0

    def _set_applied(self, seq: int) -> None:
        self._conn.execute("INSERT OR REPLACE INTO meta (key, value) VALUES ('applied', ?)", (str(seq),))

    # ---- writing: events --------------------------------------------------------------

    def sync(self) -> int:
        """Apply the log's events this graph hasn't seen yet. Returns how many."""
        with self._lock:
            events = self.log.since(self._applied())
            if not events:
                return 0
            self._conn.execute("BEGIN")
            try:
                for e in events:
                    self._projectors[e["type"]](self, e["org"], e["payload"])
                    self._set_applied(e["seq"])
                self._conn.execute("COMMIT")
            except Exception:
                self._conn.execute("ROLLBACK")
                raise
            return len(events)

    def apply(self, org: str, type: str, payload: dict, actor: str | None = None) -> dict:
        """Append an event and bring the graph up to date with it.

        The event is first projected and rolled back (a dry run, on a graph that
        is up to date), so a payload that can't be applied never reaches the
        log; then it's appended and the graph catches up, in log order."""
        if type not in self._projectors:
            raise UnknownEvent(type)
        event = {"id": new_id(), "org": org, "type": type, "at": _now(), "actor": actor, "payload": payload}
        with self._lock:
            self.sync()
            self._conn.execute("BEGIN")
            try:
                self._projectors[type](self, org, payload)
            finally:
                self._conn.execute("ROLLBACK")
            self.log.append(event)
            self.sync()
        return event

    def rebuild(self) -> int:
        """Clear the graph and replay the whole log. Returns the events replayed."""
        with self._lock:
            self._conn.execute("BEGIN")
            self._conn.execute("DELETE FROM nodes")
            self._conn.execute("DELETE FROM edges")
            self._set_applied(0)
            self._conn.execute("COMMIT")
            return self.sync()

    def events(self, org: str, limit: int = 100) -> list[dict]:
        return self.log.recent(org, limit)

    # ---- writing: the graph (projectors only) ---------------------------------------

    def put_node(self, org: str, id: str, label: str, props: dict) -> None:
        self._conn.execute(
            "INSERT OR REPLACE INTO nodes (id, org, label, props) VALUES (?, ?, ?, ?)",
            (id, org, label, json.dumps(props)),
        )

    def patch_node(self, org: str, id: str, changes: dict) -> None:
        node = self.node(org, id)
        if node is None:
            raise KeyError(id)
        props = {k: v for k, v in node.items() if k not in ("id", "label")}
        props.update(changes)
        self.put_node(org, id, node["label"], props)

    def put_edge(self, org: str, type: str, src: str, dst: str, props: dict | None = None,
                 id: str | None = None) -> None:
        # An edge's id is derived from its ends, so replaying an event gives the
        # same edge, and adding it twice is a no-op.
        eid = id or f"{type}:{src}:{dst}"
        self._conn.execute(
            "INSERT OR REPLACE INTO edges (id, org, type, src, dst, props) VALUES (?, ?, ?, ?, ?, ?)",
            (eid, org, type, src, dst, json.dumps(props or {})),
        )

    def delete_edge(self, org: str, type: str, src: str, dst: str) -> None:
        self._conn.execute(
            "DELETE FROM edges WHERE org = ? AND type = ? AND src = ? AND dst = ?",
            (org, type, src, dst),
        )

    # ---- reading -------------------------------------------------------------------

    @staticmethod
    def _node(row) -> dict:
        return {"id": row["id"], "label": row["label"], **json.loads(row["props"])}

    # Reads take the lock too: threads share the one connection, and with it
    # its cached statements, so two reads at once could cut each other off.

    def _all(self, sql: str, args: tuple) -> list:
        with self._lock:
            return self._conn.execute(sql, args).fetchall()

    def node(self, org: str, id: str, label: str | None = None) -> dict | None:
        rows = self._all("SELECT id, label, props FROM nodes WHERE org = ? AND id = ?", (org, id))
        row = rows[0] if rows else None
        if row is None or (label and row["label"] != label):
            return None
        return self._node(row)

    def nodes(self, org: str, label: str) -> list[dict]:
        rows = self._all("SELECT id, label, props FROM nodes WHERE org = ? AND label = ?", (org, label))
        return [self._node(r) for r in rows]

    def out(self, org: str, src: str, type: str) -> list[dict]:
        """Nodes at the end of ``src``'s outgoing ``type`` edges."""
        rows = self._all(
            "SELECT n.id, n.label, n.props FROM edges e JOIN nodes n ON n.id = e.dst AND n.org = e.org "
            "WHERE e.org = ? AND e.src = ? AND e.type = ?", (org, src, type))
        return [self._node(r) for r in rows]

    def inn(self, org: str, dst: str, type: str) -> list[dict]:
        """Nodes at the start of ``dst``'s incoming ``type`` edges."""
        rows = self._all(
            "SELECT n.id, n.label, n.props FROM edges e JOIN nodes n ON n.id = e.src AND n.org = e.org "
            "WHERE e.org = ? AND e.dst = ? AND e.type = ?", (org, dst, type))
        return [self._node(r) for r in rows]

    def snapshot(self) -> tuple[list, list]:
        """Every node and edge, sorted: for checking a rebuild gives the same graph."""
        nodes = [tuple(r) for r in self._all("SELECT id, org, label, props FROM nodes ORDER BY id", ())]
        edges = [tuple(r) for r in self._all("SELECT id, org, type, src, dst, props FROM edges ORDER BY id", ())]
        return nodes, edges
