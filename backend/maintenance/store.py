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

This SQLite graph is the Python backend. ``neo4j_store.Neo4jGraphStore``
implements the same methods in Neo4j, and the maintenance tests run against
both. The SQLite graph also keeps, for each node and edge, the last event that
changed it (``changes``): a Neo4j mirror (``mirror.py``) copies what changed
since it was last brought up to date, without replaying events itself.

Nodes have an ``id``, a ``label`` (Position, Item, Fitment, ...) and
``props``; edges have a ``type`` and run from ``src`` to ``dst``. Every row
carries the organisation (``org``) it belongs to, and every read is scoped
to one.
"""

from __future__ import annotations

import json
import logging
import os
import sqlite3
import threading
import time
import uuid
from datetime import datetime, timezone
from typing import Callable

logger = logging.getLogger(__name__)

Projector = Callable[["GraphStore", str, dict], None]

# Events are read from the log in batches of this many, so catching up with a
# long log never holds all of it in memory at once.
SYNC_BATCH = 5000
# A missing sequence number (a gap) is usually another process between taking
# its number and writing its event: wait up to GAP_WAIT seconds for it. A gap
# still open GAP_TIMEOUT seconds after it was first seen is an append that
# never completed, and is passed over.
GAP_WAIT = 0.5
GAP_TIMEOUT = 30.0

# Nodes and edges are keyed by (org, id): an id is only unique within its
# organisation, so a write in one organisation can never replace a row of
# another's, whatever id it carries.
_NODES_EDGES_SCHEMA = """
CREATE TABLE IF NOT EXISTS nodes (
    id    TEXT NOT NULL,
    org   TEXT NOT NULL,
    label TEXT NOT NULL,
    props TEXT NOT NULL,
    PRIMARY KEY (org, id)
);
CREATE TABLE IF NOT EXISTS edges (
    id    TEXT NOT NULL,
    org   TEXT NOT NULL,
    type  TEXT NOT NULL,
    src   TEXT NOT NULL,
    dst   TEXT NOT NULL,
    props TEXT NOT NULL,
    PRIMARY KEY (org, id)
);
CREATE INDEX IF NOT EXISTS nodes_label ON nodes (org, label);
CREATE INDEX IF NOT EXISTS edges_src ON edges (org, src, type);
CREATE INDEX IF NOT EXISTS edges_dst ON edges (org, dst, type);
"""

# The last event that wrote each node and edge (an edge deleted keeps its row,
# with its ends, so a mirror can delete it too). Cleared with the graph.
_CHANGES_SCHEMA = """
CREATE TABLE IF NOT EXISTS changes (
    org   TEXT NOT NULL,
    kind  TEXT NOT NULL,
    id    TEXT NOT NULL,
    seq   INTEGER NOT NULL,
    type  TEXT,
    src   TEXT,
    dst   TEXT,
    PRIMARY KEY (org, kind, id)
);
CREATE INDEX IF NOT EXISTS changes_seq ON changes (org, seq);
"""

_GRAPH_SCHEMA = _NODES_EDGES_SCHEMA + _CHANGES_SCHEMA + """
CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
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


def open_sqlite(path: str) -> sqlite3.Connection:
    """A SQLite connection as the store uses it: shared across threads (behind
    a lock), committing each statement unless a transaction is begun, rows by
    name, and WAL for a file."""
    if path != ":memory:":
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    conn = sqlite3.connect(path, check_same_thread=False, isolation_level=None)
    conn.row_factory = sqlite3.Row
    if path != ":memory:":
        conn.execute("PRAGMA journal_mode=WAL")
    return conn


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

    def since(self, seq: int, limit: int | None = None) -> list[dict]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT seq, org, type, payload FROM events WHERE seq > ? ORDER BY seq LIMIT ?",
                (seq, -1 if limit is None else int(limit)),
            ).fetchall()
        return [{"seq": r["seq"], "org": r["org"], "type": r["type"], "payload": json.loads(r["payload"])}
                for r in rows]

    def count(self, org: str) -> int:
        with self._lock:
            return int(self._conn.execute("SELECT COUNT(*) FROM events WHERE org = ?", (org,)).fetchone()[0])

    def recent(self, org: str, limit: int, since: int | None = None, type: str | None = None) -> list[dict]:
        """The organisation's newest events (``since``: only those after that
        sequence number, oldest first; ``type``: only that event type)."""
        where, args = ["org = ?"], [org]
        if since is not None:
            where.append("seq > ?")
            args.append(int(since))
        if type:
            where.append("type = ?")
            args.append(type)
        order = "ASC" if since is not None else "DESC"
        with self._lock:
            rows = self._conn.execute(
                f"SELECT seq, id, type, at, actor, payload FROM events WHERE {' AND '.join(where)} "
                f"ORDER BY seq {order} LIMIT ?", (*args, limit),
            ).fetchall()
        return [{"seq": r["seq"], "id": r["id"], "type": r["type"], "at": r["at"], "actor": r["actor"],
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

    def since(self, seq: int, limit: int | None = None) -> list[dict]:
        cursor = self._events.find({"seq": {"$gt": seq}}).sort("seq", 1)
        if limit is not None:
            cursor = cursor.limit(int(limit))
        return [{"seq": d["seq"], "org": d["org"], "type": d["type"], "payload": d["payload"]} for d in cursor]

    def count(self, org: str) -> int:
        return int(self._events.count_documents({"org": org}))

    def recent(self, org: str, limit: int, since: int | None = None, type: str | None = None) -> list[dict]:
        query: dict = {"org": org}
        if since is not None:
            query["seq"] = {"$gt": int(since)}
        if type:
            query["type"] = type
        cursor = self._events.find(query).sort("seq", 1 if since is not None else -1).limit(limit)
        return [{"seq": d["seq"], "id": d["_id"], "type": d["type"], "at": d["at"], "actor": d.get("actor"),
                 "payload": d["payload"]} for d in cursor]


# ---- the graph -------------------------------------------------------------------------

class GraphStore:
    """The graph projected from an event log, in SQLite (``":memory:"`` for a
    copy rebuilt from a shared log, or for tests). With no log given, the log
    lives in the same SQLite file."""

    def __init__(self, path: str, projectors: dict[str, Projector], log=None, series=None, version: int = 1):
        self._conn = open_sqlite(path)
        tracked = bool(self._conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'changes'").fetchall())
        self._conn.executescript(_GRAPH_SCHEMA)
        self._lock = threading.RLock()
        self._projectors = projectors
        self._gap: tuple[int, float] | None = None  # (missing seq, when first seen)
        self._event_counts: dict[str, int] = {}
        self._seq = 0  # the event being projected, recorded against what it writes
        # Per-process counters the service keeps its write limits in.
        self.write_windows: dict = {}
        self.series_days: dict = {}
        # Called with the organisation after each event this process appends
        # (a mirror's trigger), and the mirror itself when one is attached.
        self.listeners: list[Callable[[str], None]] = []
        self.mirror = None
        self.log = log if log is not None else SqliteEventLog(self._conn, self._lock)
        from backend.maintenance.series import SqliteSeries

        self.series = series if series is not None else SqliteSeries(self._conn, self._lock)
        # When the projectors change what they build, or the tables change
        # shape, a stored graph is rebuilt from the log (the log never changes).
        rows = self._all("SELECT value FROM meta WHERE key = 'version'", ())
        stored = int(rows[0]["value"]) if rows else 1
        if not self._schema_current() or (stored != version and self._applied()):
            self.rebuild()
        elif not tracked:
            # A graph stored before changes were kept: they're complete only
            # from here on.
            self._set_meta("changes_from", str(self._applied()))
        self._conn.execute("INSERT OR REPLACE INTO meta (key, value) VALUES ('version', ?)", (str(version),))
        self.version = version

    def _schema_current(self) -> bool:
        """Whether the nodes and edges tables are keyed by (org, id)."""
        for table in ("nodes", "edges"):
            keys = {r["name"] for r in self._all(f"PRAGMA table_info({table})", ()) if r["pk"]}
            if keys != {"org", "id"}:
                return False
        return True

    # ---- applied position -----------------------------------------------------------

    def _applied(self) -> int:
        rows = self._all("SELECT value FROM meta WHERE key = 'applied'", ())
        return int(rows[0]["value"]) if rows else 0

    def _set_applied(self, seq: int) -> None:
        self._set_meta("applied", str(seq))

    def _set_meta(self, key: str, value: str) -> None:
        self._conn.execute("INSERT OR REPLACE INTO meta (key, value) VALUES (?, ?)", (key, value))

    def _note_skipped(self, seq: int, why: str) -> None:
        rows = self._all("SELECT value FROM meta WHERE key = 'skipped'", ())
        skipped = (json.loads(rows[0]["value"]) if rows else []) + [{"seq": seq, "why": why}]
        self._conn.execute("INSERT OR REPLACE INTO meta (key, value) VALUES ('skipped', ?)",
                           (json.dumps(skipped[-100:]),))

    def skipped(self) -> list[dict]:
        """Sequence numbers passed over by :meth:`sync` (most recent 100), and why."""
        rows = self._all("SELECT value FROM meta WHERE key = 'skipped'", ())
        return json.loads(rows[0]["value"]) if rows else []

    # ---- writing: events --------------------------------------------------------------

    def _project(self, e: dict) -> None:
        """Project one event from the log, inside the open transaction.

        An event that can't be projected (a projector error, or a type this
        version doesn't know, as during a rolling deploy) is logged and passed
        over by its sequence number, with anything it half-wrote rolled back.
        Raising instead would stop the graph at that event, and every request
        that syncs would fail with it."""
        self._conn.execute("SAVEPOINT event")
        self._seq = e["seq"]
        try:
            projector = self._projectors.get(e["type"])
            if projector is None:
                raise UnknownEvent(e["type"])
            projector(self, e["org"], e["payload"])
        except Exception as err:  # noqa: BLE001 - see the docstring
            self._conn.execute("ROLLBACK TO event")
            self._conn.execute("RELEASE event")
            logger.exception("maintenance event %s (%s) couldn't be projected; passed over", e["seq"], e["type"])
            self._note_skipped(e["seq"], f"{type(err).__name__} in {e['type']}")
        else:
            self._conn.execute("RELEASE event")
        if e["org"] in self._event_counts:
            self._event_counts[e["org"]] += 1

    def _apply_run(self, applied: int, events: list[dict]) -> int:
        """Project the events that follow ``applied`` without a break; returns
        the new applied position."""
        self._conn.execute("BEGIN")
        try:
            for e in events:
                if e["seq"] != applied + 1:
                    break
                self._project(e)
                applied = e["seq"]
            self._set_applied(applied)
            self._conn.execute("COMMIT")
        except BaseException:
            self._conn.execute("ROLLBACK")
            raise
        return applied

    def sync(self) -> int:
        """Apply the log's events this graph hasn't seen yet. Returns how many.

        Events are applied strictly in sequence: only ``applied + 1`` is ever
        next. In a shared log, a process takes its sequence number and then
        writes its event, so another process's later event can be in the log
        before it. On such a gap the graph stops short of it (waiting up to
        GAP_WAIT the first time it's seen), rather than step past an event it
        hasn't read yet and never read it. A gap still open GAP_TIMEOUT after
        it was first seen is an append that never completed: it's recorded in
        :meth:`skipped` and passed over."""
        with self._lock:
            done = 0
            while True:
                applied = self._applied()
                events = self.log.since(applied, SYNC_BATCH)
                if not events:
                    return done
                now_at = self._apply_run(applied, events)
                done += now_at - applied
                if now_at == events[-1]["seq"]:
                    continue  # the whole batch: read on
                missing = now_at + 1
                now = time.monotonic()
                if self._gap is None or self._gap[0] != missing:
                    self._gap = (missing, now)
                age = now - self._gap[1]
                if age >= GAP_TIMEOUT:
                    logger.warning("maintenance event %s never reached the log; passed over", missing)
                    self._conn.execute("BEGIN")
                    self._note_skipped(missing, "missing from the log")
                    self._set_applied(missing)
                    self._conn.execute("COMMIT")
                    self._gap = None
                    continue
                if age >= GAP_WAIT:
                    return done
                time.sleep(0.02)

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
            seq = self.log.append(event)
            self.sync()
        # An earlier event still on its way to the log: wait (without the lock)
        # until this one is applied, so the caller reads its own write.
        deadline = time.monotonic() + GAP_TIMEOUT + 2
        while self._applied() < seq:
            if time.monotonic() > deadline:
                raise RuntimeError(f"Maintenance event {seq} is in the log but not applied yet.")
            time.sleep(0.05)
            self.sync()
        _notify(self.listeners, org)
        return event

    def event_count(self, org: str) -> int:
        """How many events the organisation has in the log (kept up to date as
        events are applied, after a first count from the log)."""
        with self._lock:
            if org not in self._event_counts:
                self.sync()
                self._event_counts[org] = self.log.count(org)
            return self._event_counts[org]

    def count(self, org: str, label: str) -> int:
        """How many nodes of ``label`` the organisation has."""
        return int(self._all("SELECT COUNT(*) AS n FROM nodes WHERE org = ? AND label = ?", (org, label))[0]["n"])

    def rebuild(self) -> int:
        """Clear the graph and replay the whole log. Returns the events replayed.

        The tables are dropped and made again, so a graph stored with an older
        table layout comes back in the current one."""
        with self._lock:
            self._conn.execute("DROP TABLE IF EXISTS nodes")
            self._conn.execute("DROP TABLE IF EXISTS edges")
            self._conn.execute("DROP TABLE IF EXISTS changes")
            self._conn.executescript(_NODES_EDGES_SCHEMA + _CHANGES_SCHEMA)
            self._conn.execute("BEGIN")
            self._set_applied(0)
            self._set_meta("changes_from", "0")
            self._conn.execute("COMMIT")
            self._gap = None
            self._event_counts.clear()
            return self.sync()

    def events(self, org: str, limit: int = 100, since: int | None = None, type: str | None = None) -> list[dict]:
        return self.log.recent(org, limit, since, type)

    def load_snapshot(self, nodes: list, edges: list) -> None:
        """Fill an empty graph with the rows of another store's :meth:`snapshot`
        (for a throwaway copy: see :func:`scratch_copy`). Not a projection: the
        copy's log stays empty and its applied position 0."""
        with self._lock:
            self._conn.execute("BEGIN")
            try:
                self._conn.executemany("INSERT OR REPLACE INTO nodes (id, org, label, props) VALUES (?, ?, ?, ?)",
                                       [(n[0], n[1], n[2], n[3]) for n in nodes])
                self._conn.executemany(
                    "INSERT OR REPLACE INTO edges (id, org, type, src, dst, props) VALUES (?, ?, ?, ?, ?, ?)",
                    [(e[0], e[1], e[2], e[3], e[4], e[5]) for e in edges])
                self._conn.execute("COMMIT")
            except BaseException:
                self._conn.execute("ROLLBACK")
                raise

    # ---- writing: the graph (projectors only) ---------------------------------------

    def _changed(self, org: str, kind: str, id: str, type=None, src=None, dst=None) -> None:
        self._conn.execute(
            "INSERT OR REPLACE INTO changes (org, kind, id, seq, type, src, dst) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (org, kind, id, self._seq, type, src, dst),
        )

    def put_node(self, org: str, id: str, label: str, props: dict) -> None:
        self._conn.execute(
            "INSERT OR REPLACE INTO nodes (id, org, label, props) VALUES (?, ?, ?, ?)",
            (id, org, label, json.dumps(props)),
        )
        self._changed(org, "node", id)

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
        self._changed(org, "edge", eid, type, src, dst)

    def delete_edge(self, org: str, type: str, src: str, dst: str) -> None:
        gone = self._conn.execute(
            "SELECT id FROM edges WHERE org = ? AND type = ? AND src = ? AND dst = ?", (org, type, src, dst),
        ).fetchall()
        self._conn.execute(
            "DELETE FROM edges WHERE org = ? AND type = ? AND src = ? AND dst = ?",
            (org, type, src, dst),
        )
        for row in gone:
            self._changed(org, "edge", row["id"], type, src, dst)

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
        if not isinstance(id, str):
            return None
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
        if not isinstance(src, str):
            return []
        rows = self._all(
            "SELECT n.id, n.label, n.props FROM edges e JOIN nodes n ON n.id = e.dst AND n.org = e.org "
            "WHERE e.org = ? AND e.src = ? AND e.type = ?", (org, src, type))
        return [self._node(r) for r in rows]

    def inn(self, org: str, dst: str, type: str) -> list[dict]:
        """Nodes at the start of ``dst``'s incoming ``type`` edges."""
        if not isinstance(dst, str):
            return []
        rows = self._all(
            "SELECT n.id, n.label, n.props FROM edges e JOIN nodes n ON n.id = e.src AND n.org = e.org "
            "WHERE e.org = ? AND e.dst = ? AND e.type = ?", (org, dst, type))
        return [self._node(r) for r in rows]

    def pairs(self, org: str, type: str) -> list[tuple[str, str]]:
        """(src, dst) for every ``type`` edge in the organisation: a whole tree's
        links in one read, rather than one ``out`` per node."""
        rows = self._all("SELECT src, dst FROM edges WHERE org = ? AND type = ?", (org, type))
        return [(r["src"], r["dst"]) for r in rows]

    def edge(self, org: str, type: str, src: str, dst: str) -> dict | None:
        """The properties of the ``type`` edge from ``src`` to ``dst`` (None: there's none)."""
        if not isinstance(src, str) or not isinstance(dst, str):
            return None
        rows = self._all("SELECT props FROM edges WHERE org = ? AND type = ? AND src = ? AND dst = ? LIMIT 1",
                         (org, type, src, dst))
        return json.loads(rows[0]["props"]) if rows else None

    def orgs_with(self, label: str) -> list[str]:
        """Every organisation with at least one node of ``label``."""
        return [r["org"] for r in self._all("SELECT DISTINCT org FROM nodes WHERE label = ? ORDER BY org", (label,))]

    def snapshot(self, org: str | None = None) -> tuple[list, list]:
        """Every node and edge (of one organisation, if given), sorted: for checking
        a rebuild, or another backend, gives the same graph."""
        where, args = ("WHERE org = ? ", (org,)) if org is not None else ("", ())
        nodes = [tuple(r) for r in self._all(f"SELECT id, org, label, props FROM nodes {where}ORDER BY org, id", args)]
        edges = [tuple(r) for r in self._all(
            f"SELECT id, org, type, src, dst, props FROM edges {where}ORDER BY org, id", args)]
        return nodes, edges

    # ---- what changed: for a mirror ---------------------------------------------------

    def change_marks(self) -> tuple[int, dict[str, int]]:
        """The applied position, and for each organisation the last event that
        changed its graph."""
        with self._lock:
            rows = self._all("SELECT org, MAX(seq) AS seq FROM changes GROUP BY org", ())
            return self._applied(), {r["org"]: int(r["seq"]) for r in rows}

    def org_mark(self, org: str) -> int:
        """The last event that changed the organisation's graph (0: none yet)."""
        rows = self._all("SELECT MAX(seq) AS seq FROM changes WHERE org = ?", (org,))
        return int(rows[0]["seq"] or 0)

    def changes_from(self) -> int:
        """The event from which ``changes`` is complete (0: the whole log)."""
        rows = self._all("SELECT value FROM meta WHERE key = 'changes_from'", ())
        return int(rows[0]["value"]) if rows else 0

    def org_changes(self, org: str, since: int | None) -> dict:
        """What a copy of the organisation's graph as at event ``since`` needs to be
        brought up to date: the nodes and edges written since, and the edges deleted
        since (by their ends). ``since`` None: the whole graph. Rows carry ``w``, the
        order they were written in (reads list nodes and edges in it).

        {"applied": the position the copy is then up to date with,
         "nodes": [(id, label, props, w)], "edges": [(id, type, src, dst, props, w)],
         "gone": [(id, type, src, dst)]}"""
        with self._lock:
            applied = self._applied()
            if since is None:
                nodes = self._all("SELECT id, label, props, rowid AS w FROM nodes WHERE org = ?", (org,))
                edges = self._all("SELECT id, type, src, dst, props, rowid AS w FROM edges WHERE org = ?", (org,))
                gone = []
            else:
                nodes = self._all(
                    "SELECT n.id, n.label, n.props, n.rowid AS w FROM changes c JOIN nodes n ON n.org = c.org "
                    "AND n.id = c.id WHERE c.org = ? AND c.kind = 'node' AND c.seq > ?", (org, since))
                rows = self._all(
                    "SELECT c.id AS cid, c.type AS ctype, c.src AS csrc, c.dst AS cdst, e.id, e.type, e.src, e.dst, "
                    "e.props, e.rowid AS w FROM changes c LEFT JOIN edges e ON e.org = c.org AND e.id = c.id "
                    "WHERE c.org = ? AND c.kind = 'edge' AND c.seq > ?", (org, since))
                edges = [r for r in rows if r["id"] is not None]
                gone = [(r["cid"], r["ctype"], r["csrc"], r["cdst"]) for r in rows if r["id"] is None]
            return {"applied": applied,
                    "nodes": [(r["id"], r["label"], r["props"], r["w"]) for r in nodes],
                    "edges": [(r["id"], r["type"], r["src"], r["dst"], r["props"], r["w"]) for r in edges],
                    "gone": gone}


def scratch_copy(store, org: str) -> GraphStore:
    """A throwaway in-memory copy of one organisation's graph, with the same
    projectors and an empty log of its own: changes made on it are checked
    and projected as on the real store, and never reach the real log. For a
    batch's dry run. Works from the SQLite graph and from Neo4j (both give the
    same :meth:`GraphStore.snapshot` shape)."""
    nodes, edges = store.snapshot(org)
    copy = GraphStore(":memory:", store._projectors, version=getattr(store, "version", 1))
    copy.load_snapshot(nodes, edges)
    return copy


def _notify(listeners, org: str) -> None:
    """Tell the listeners (a mirror's trigger) about a write; never fail the write."""
    for listener in listeners:
        try:
            listener(org)
        except Exception:  # noqa: BLE001 - a listener's trouble isn't the writer's
            logger.exception("maintenance store listener failed")
