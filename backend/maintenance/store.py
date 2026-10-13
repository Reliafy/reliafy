"""The maintenance graph store: an event log, and the graph projected from it.

Every change is an event: ``apply`` appends it to the log and, in the same
transaction, runs its projector, which writes nodes and edges. The log is
the source of truth: ``rebuild`` clears the graph and replays every event,
and must give the same graph back.

This is the Python backend: SQLite in one file, no server. A Neo4j backend
will implement the same methods, and the same tests will run against both.

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

_SCHEMA = """
CREATE TABLE IF NOT EXISTS events (
    seq     INTEGER PRIMARY KEY AUTOINCREMENT,
    id      TEXT NOT NULL UNIQUE,
    org     TEXT NOT NULL,
    type    TEXT NOT NULL,
    at      TEXT NOT NULL,
    actor   TEXT,
    payload TEXT NOT NULL
);
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
CREATE INDEX IF NOT EXISTS events_org ON events (org, seq);
CREATE INDEX IF NOT EXISTS nodes_label ON nodes (org, label);
CREATE INDEX IF NOT EXISTS edges_src ON edges (org, src, type);
CREATE INDEX IF NOT EXISTS edges_dst ON edges (org, dst, type);
"""


def new_id() -> str:
    return uuid.uuid4().hex


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class UnknownEvent(ValueError):
    """An event type with no projector."""


class GraphStore:
    """The event log and its graph, in one SQLite file (``":memory:"`` for
    tests)."""

    def __init__(self, path: str, projectors: dict[str, Projector]):
        if path != ":memory:":
            os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        self._conn = sqlite3.connect(path, check_same_thread=False, isolation_level=None)
        self._conn.row_factory = sqlite3.Row
        if path != ":memory:":
            self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.executescript(_SCHEMA)
        self._lock = threading.RLock()
        self._projectors = projectors

    # ---- writing: events ---------------------------------------------------------

    def apply(self, org: str, type: str, payload: dict, actor: str | None = None) -> dict:
        """Append an event and project it, atomically."""
        if type not in self._projectors:
            raise UnknownEvent(type)
        event = {"id": new_id(), "org": org, "type": type, "at": _now(),
                 "actor": actor, "payload": payload}
        with self._lock:
            self._conn.execute("BEGIN")
            try:
                self._conn.execute(
                    "INSERT INTO events (id, org, type, at, actor, payload) VALUES (?, ?, ?, ?, ?, ?)",
                    (event["id"], org, type, event["at"], actor, json.dumps(payload)),
                )
                self._projectors[type](self, org, payload)
                self._conn.execute("COMMIT")
            except Exception:
                self._conn.execute("ROLLBACK")
                raise
        return event

    def rebuild(self) -> int:
        """Clear the graph and replay the whole log. Returns the events replayed."""
        with self._lock:
            self._conn.execute("BEGIN")
            try:
                self._conn.execute("DELETE FROM nodes")
                self._conn.execute("DELETE FROM edges")
                rows = self._conn.execute("SELECT org, type, payload FROM events ORDER BY seq").fetchall()
                for row in rows:
                    self._projectors[row["type"]](self, row["org"], json.loads(row["payload"]))
                self._conn.execute("COMMIT")
            except Exception:
                self._conn.execute("ROLLBACK")
                raise
        return len(rows)

    def events(self, org: str, limit: int = 100) -> list[dict]:
        rows = self._conn.execute(
            "SELECT id, type, at, actor, payload FROM events WHERE org = ? ORDER BY seq DESC LIMIT ?",
            (org, limit),
        ).fetchall()
        return [{"id": r["id"], "type": r["type"], "at": r["at"], "actor": r["actor"],
                 "payload": json.loads(r["payload"])} for r in rows]

    # ---- writing: the graph (projectors only) --------------------------------------

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

    # ---- reading ----------------------------------------------------------------

    @staticmethod
    def _node(row) -> dict:
        return {"id": row["id"], "label": row["label"], **json.loads(row["props"])}

    def node(self, org: str, id: str, label: str | None = None) -> dict | None:
        row = self._conn.execute(
            "SELECT id, label, props FROM nodes WHERE org = ? AND id = ?", (org, id)
        ).fetchone()
        if row is None or (label and row["label"] != label):
            return None
        return self._node(row)

    def nodes(self, org: str, label: str) -> list[dict]:
        rows = self._conn.execute(
            "SELECT id, label, props FROM nodes WHERE org = ? AND label = ?", (org, label)
        ).fetchall()
        return [self._node(r) for r in rows]

    def out(self, org: str, src: str, type: str) -> list[dict]:
        """Nodes at the end of ``src``'s outgoing ``type`` edges."""
        rows = self._conn.execute(
            "SELECT n.id, n.label, n.props FROM edges e JOIN nodes n ON n.id = e.dst AND n.org = e.org "
            "WHERE e.org = ? AND e.src = ? AND e.type = ?", (org, src, type)
        ).fetchall()
        return [self._node(r) for r in rows]

    def inn(self, org: str, dst: str, type: str) -> list[dict]:
        """Nodes at the start of ``dst``'s incoming ``type`` edges."""
        rows = self._conn.execute(
            "SELECT n.id, n.label, n.props FROM edges e JOIN nodes n ON n.id = e.src AND n.org = e.org "
            "WHERE e.org = ? AND e.dst = ? AND e.type = ?", (org, dst, type)
        ).fetchall()
        return [self._node(r) for r in rows]

    def snapshot(self) -> tuple[list, list]:
        """Every node and edge, sorted: for checking a rebuild gives the same graph."""
        nodes = [tuple(r) for r in self._conn.execute(
            "SELECT id, org, label, props FROM nodes ORDER BY id").fetchall()]
        edges = [tuple(r) for r in self._conn.execute(
            "SELECT id, org, type, src, dst, props FROM edges ORDER BY id").fetchall()]
        return nodes, edges
