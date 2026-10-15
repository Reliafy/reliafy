"""A copy of the maintenance graph in Neo4j, kept in step in the background.

The SQLite graph (``store.GraphStore``) stays the graph every request reads and
writes. The mirror copies it to Neo4j for graph queries (``graph_query.py``):
Neo4j is a round trip away (150-400 ms for AuraDB in another region), so it's
never on a request's path.

How it keeps up: the SQLite graph records the last event that wrote each node
and edge (``changes``). For each organisation the mirror holds, in Neo4j, the
position it is up to date with (``(:MaintenanceMirror {ns, org, applied,
version})``); a sync sends what changed since then, and the new position, in
one statement (one round trip; a large change is one transaction of several).
The statement writes only if the position is still the one it read (an
optimistic check, with the node locked first), so it's idempotent, resumes
where it stopped, and several Cloud Run instances can sync at once: the first
writes, the others see they're behind or already covered. A mirror at another
projection version, or older than the SQLite graph's changes go back
(``changes_from``), is copied whole.

When it runs:

* after this process appends an event: :meth:`Neo4jMirror.notify` wakes a
  background thread (a queue of one, so a burst of writes is one sync);
* in the hourly content job (:func:`catch_up`), which also keeps AuraDB Free
  from pausing when idle;
* ``python -m backend.scripts.maintenance_graph`` (status, sync, rebuild from
  the log, verify).
"""

from __future__ import annotations

import logging
import queue
import threading
import time
from datetime import datetime, timezone

from backend.maintenance.neo4j_store import (
    UNCHECKED, WRITE_BODY, Neo4jConnection, graph_snapshot, node_row, write_params,
)

logger = logging.getLogger(__name__)

# Rows (nodes, edges and deleted edges) sent in one statement; a larger change
# is sent as several statements in one transaction.
CHUNK = 2000

MIRROR_PUSH = """
MERGE (m:MaintenanceMirror {ns: $ns, org: $org})
SET m._lock = true
REMOVE m._lock
WITH m, (coalesce(m.applied, -1) = $prev AND coalesce(m.version, -1) = $prev_version) AS ok
""" + WRITE_BODY + """
SET m.applied = CASE WHEN ok AND $last THEN $to ELSE m.applied END,
    m.version = CASE WHEN ok AND $last THEN $version ELSE m.version END,
    m.synced = CASE WHEN ok AND $last THEN $now ELSE m.synced END
RETURN ok, m.applied AS applied, m.version AS version
"""

MIRROR_FINISH = """
MATCH (m:MaintenanceMirror {ns: $ns, org: $org})
SET m.applied = $to, m.version = $version, m.synced = $now
RETURN true AS ok, m.applied AS applied, m.version AS version
"""


class Neo4jMirror:
    """Keeps ``store``'s graph copied to Neo4j, in namespace ``namespace``.

    ``conn``: a connection, or a function that makes one (called on first use, so
    attaching the mirror costs no round trip). ``queries``: graph queries may be
    answered from it (``graph_query.py``)."""

    def __init__(self, store, conn, namespace: str = "", queries: bool = False, chunk: int = CHUNK):
        self.store = store
        self._conn = conn
        self.ns = namespace
        self.version = store.version
        self.queries = queries
        self.chunk = chunk
        self._remote: dict[str, tuple[int, int]] | None = None  # org -> (applied, version) in Neo4j
        self._sync_lock = threading.Lock()
        self._wake: queue.Queue = queue.Queue(maxsize=1)
        self._thread: threading.Thread | None = None
        self._thread_lock = threading.Lock()
        self._newer_noted: set[str] = set()
        self.last_error: str | None = None
        self.last_sync: dict | None = None

    @property
    def conn(self) -> Neo4jConnection:
        if callable(self._conn):
            self._conn = self._conn()
        return self._conn

    def attach(self) -> "Neo4jMirror":
        """Hang the mirror on its store: the store's writes wake it, and graph
        queries find it."""
        self.store.mirror = self
        self.store.listeners.append(self.notify)
        return self

    # ---- in the background --------------------------------------------------------------

    def notify(self, org: str | None = None) -> None:
        """Ask for a sync soon, without waiting for it."""
        with self._thread_lock:
            if self._thread is None or not self._thread.is_alive():
                self._thread = threading.Thread(target=self._run, name="maintenance-mirror", daemon=True)
                self._thread.start()
        try:
            self._wake.put_nowait(org)
        except queue.Full:
            pass  # a sync is already asked for: it will take this write too

    def _run(self) -> None:
        delay = 1.0
        while True:
            self._wake.get()
            try:
                self.sync()
                delay = 1.0
            except Exception as err:  # noqa: BLE001 - logged; the next write or the hourly job retries
                self.last_error = f"{type(err).__name__}: {err}"
                logger.warning("maintenance mirror sync failed: %s", self.last_error)
                time.sleep(delay)
                delay = min(delay * 2, 60.0)

    # ---- syncing --------------------------------------------------------------------------

    def remote_marks(self, refresh: bool = False) -> dict[str, tuple[int, int]]:
        """Each organisation's position and version in Neo4j (read once, then kept
        up to date by this process's own syncs)."""
        if self._remote is None or refresh:
            self.conn.ensure_schema()
            rows = self.conn.run("MATCH (m:MaintenanceMirror {ns: $ns}) WHERE m.applied IS NOT NULL "
                                 "RETURN m.org AS org, m.applied AS applied, m.version AS version", {"ns": self.ns})
            self._remote = {r["org"]: (int(r["applied"]), int(r["version"] or -1)) for r in rows}
        return self._remote

    def pending(self) -> dict[str, dict]:
        """The organisations whose copy is behind: {org: {local, mirror, full}}."""
        _, marks = self.store.change_marks()
        remote = self.remote_marks()
        changes_from = self.store.changes_from()
        out = {}
        for org, mark in sorted(marks.items()):
            applied, version = remote.get(org, (-1, -1))
            full = self._needs_full(applied, version, changes_from)
            if full or applied < mark:
                out[org] = {"local": mark, "mirror": applied if applied >= 0 else None, "full": full}
        return out

    def _needs_full(self, applied: int, version: int, changes_from: int) -> bool:
        return applied < 0 or version != self.version or applied < changes_from

    def sync(self, orgs=None, full: bool = False) -> dict:
        """Bring the copy up to date (for these organisations, or every one).
        ``full``: copy them whole whatever their position. Returns what was sent."""
        with self._sync_lock:
            _, marks = self.store.change_marks()
            remote = self.remote_marks(refresh=self._remote is None)
            changes_from = self.store.changes_from()
            result = {"orgs": 0, "full": 0, "nodes": 0, "edges": 0, "gone": 0, "conflicts": 0, "skipped": 0}
            for org in sorted(orgs if orgs is not None else marks):
                self._sync_org(org, marks.get(org, 0), changes_from, result, full)
            self.last_sync = {**result, "at": _now()}
            self.last_error = None
            return result

    def _sync_org(self, org: str, mark: int, changes_from: int, result: dict, force_full: bool) -> None:
        for _ in range(5):
            applied, version = self.remote_marks().get(org, (-1, -1))
            if version > self.version:
                if org not in self._newer_noted:  # a newer deploy owns it now
                    self._newer_noted.add(org)
                    logger.info("maintenance mirror: %s is at projection version %s; leaving it", org, version)
                result["skipped"] += 1
                return
            full = force_full or self._needs_full(applied, version, changes_from)
            if not full and applied >= mark:
                return  # up to date (or another process got it further)
            changes = self.store.org_changes(org, None if full else applied)
            ok, now = self._push(org, changes, applied, version, full)
            self._remote[org] = now
            if ok:
                result["orgs"] += 1
                result["full"] += int(full)
                for key in ("nodes", "edges", "gone"):
                    result[key] += len(changes[key])
                return
            result["conflicts"] += 1
            force_full = False
        raise RuntimeError(f"maintenance mirror: {org} kept changing under the sync")

    def _push(self, org: str, changes: dict, prev: int, prev_version: int, full: bool) -> tuple[bool, tuple]:
        """Send one organisation's changes; (ok, its (applied, version) now)."""
        ns = self.ns
        nodes = [node_row(ns, org, id, label, props, None, w) for id, label, props, w in changes["nodes"]]
        gone = [{"org": org, "id": id, "type": type, "src": src, "dst": dst} for id, type, src, dst in changes["gone"]]
        edges = [{"org": org, "id": id, "type": type, "src": src, "dst": dst, "props": props, "w": w}
                 for id, type, src, dst, props, w in changes["edges"]]
        parts = [p for p in _chunks(nodes, gone, edges, self.chunk)] or [([], [], [])]
        params = {"org": org, "prev": prev, "prev_version": prev_version, "to": changes["applied"],
                  "version": self.version, "now": _now()}
        first = write_params(ns, *parts[0], full=full, last=len(parts) == 1, **params)
        if len(parts) == 1:
            rows = self.conn.run(MIRROR_PUSH, first, write=True)
            return bool(rows[0]["ok"]), (int(rows[0]["applied"] if rows[0]["applied"] is not None else -1),
                                         int(rows[0]["version"] if rows[0]["version"] is not None else -1))
        with self.conn.transaction() as tx:
            rows = tx.run(MIRROR_PUSH, first)
            if not rows[0]["ok"]:
                return False, (int(rows[0]["applied"] if rows[0]["applied"] is not None else -1),
                               int(rows[0]["version"] if rows[0]["version"] is not None else -1))
            for part in parts[1:]:
                tx.run(UNCHECKED, write_params(ns, *part))
            rows = tx.run(MIRROR_FINISH, {"ns": ns, **params})
            tx.commit()
        return True, (int(rows[0]["applied"]), int(rows[0]["version"]))

    # ---- whole copies, checks ---------------------------------------------------------------

    def rebuild(self, orgs=None) -> dict:
        """Copy these organisations (or every one in the store) whole, replacing
        what Neo4j holds for them."""
        return self.sync(orgs=orgs, full=True)

    def verify(self, org: str) -> dict:
        """Whether Neo4j holds exactly the store's graph for the organisation."""
        local, remote = self.store.snapshot(org), graph_snapshot(self.conn, self.ns, org)
        return {"org": org, "nodes": len(local[0]), "edges": len(local[1]),
                "same": local == remote,
                "missing_nodes": len(set(local[0]) - set(remote[0])), "extra_nodes": len(set(remote[0]) - set(local[0])),
                "missing_edges": len(set(local[1]) - set(remote[1])), "extra_edges": len(set(remote[1]) - set(local[1]))}

    def status(self) -> dict:
        remote = self.remote_marks(refresh=True)
        return {"namespace": self.ns, "version": self.version, "orgs_in_neo4j": len(remote),
                "behind": self.pending(), "last_sync": self.last_sync, "last_error": self.last_error}


def _chunks(nodes: list, gone: list, edges: list, size: int):
    """(nodes, gone, edges) parts of at most ``size`` rows, in the order they're
    written: nodes, then deleted edges, then edges."""
    part: tuple[list, list, list] = ([], [], [])
    room = size
    for i, rows in enumerate((nodes, gone, edges)):
        at = 0
        while at < len(rows):
            take = rows[at:at + room]
            part[i].extend(take)
            at += len(take)
            room -= len(take)
            if room == 0:
                yield part
                part, room = ([], [], []), size
    if any(part):
        yield part


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def catch_up(store) -> dict:
    """The hourly job's step: bring the mirror up to date (which also keeps an
    idle AuraDB Free instance from pausing). Never raises: Neo4j being
    unreachable is logged and reported."""
    mirror = getattr(store, "mirror", None)
    if mirror is None:
        return {"step": "maintenance_mirror", "skipped": "no mirror"}
    started = time.monotonic()
    try:
        mirror.conn.ping()
        result = mirror.sync()
        return {"step": "maintenance_mirror", **result, "seconds": round(time.monotonic() - started, 2)}
    except Exception as err:  # noqa: BLE001 - see the docstring
        logger.warning("maintenance mirror catch-up failed: %s: %s", type(err).__name__, err)
        return {"step": "maintenance_mirror", "error": f"{type(err).__name__}: {err}"}


def mirror_namespace() -> str:
    from backend import config

    return f"{config.MAINTENANCE_GRAPH_NAMESPACE}mirror"


def attach_from_config(store) -> Neo4jMirror | None:
    """Attach a mirror to the store when ``MAINTENANCE_GRAPH_MIRROR=neo4j``. No
    round trip: the connection is made on the first sync."""
    from backend import config
    from backend.maintenance.neo4j_store import connect

    if config.MAINTENANCE_GRAPH_MIRROR != "neo4j" or not hasattr(store, "change_marks"):
        return None
    mirror = Neo4jMirror(store, connect, namespace=mirror_namespace(),
                         queries=config.MAINTENANCE_GRAPH_QUERIES == "neo4j").attach()
    mirror.notify()  # catch up after a start (in the background)
    return mirror
