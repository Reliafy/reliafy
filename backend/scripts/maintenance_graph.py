"""The maintenance graph in Neo4j: status, sync, rebuild from the log, verify.

The log (MongoDB, or the local SQLite file: as the app chooses) is replayed
into a fresh in-memory SQLite graph, which is then compared with, or copied
to, Neo4j. Neo4j settings come from NEO4J_URI / NEO4J_USERNAME /
NEO4J_PASSWORD / NEO4J_DATABASE (docs/maintenance-graph.md).

    # How far behind the mirror is, per organisation.
    python -m backend.scripts.maintenance_graph status

    # Rebuild the mirror from the log: a dry run (counts) unless --apply.
    python -m backend.scripts.maintenance_graph rebuild [--org ORG] [--apply] [--prune]

    # Bring the mirror up to date (only what changed).
    python -m backend.scripts.maintenance_graph sync [--org ORG]

    # Compare a replay of the log with Neo4j, per organisation: the mirror, or
    # (--target graph) the graph when Neo4j is the store (MAINTENANCE_GRAPH=neo4j).
    python -m backend.scripts.maintenance_graph verify [--org ORG] [--target mirror|graph]

    # One round trip, timed.
    python -m backend.scripts.maintenance_graph ping
"""

from __future__ import annotations

import argparse
import json
import sys
import time


def replay():
    """A fresh SQLite graph replayed from the app's log."""
    from backend import config
    from backend.db import get_db
    from backend.maintenance.service import PROJECTION_VERSION, PROJECTORS
    from backend.maintenance.store import GraphStore, MongoEventLog, SqliteEventLog, open_sqlite
    from backend.routers.maintenance import _use_mongo

    log = MongoEventLog(get_db()) if _use_mongo() else SqliteEventLog(open_sqlite(config.MAINTENANCE_DB_PATH))
    store = GraphStore(":memory:", PROJECTORS, log, version=PROJECTION_VERSION)
    started = time.monotonic()
    events = store.sync()
    print(f"replayed {events} events in {time.monotonic() - started:.1f} s", file=sys.stderr)
    return store


def mirror_of(store):
    from backend.maintenance.mirror import Neo4jMirror, mirror_namespace
    from backend.maintenance.neo4j_store import connect

    return Neo4jMirror(store, connect(), namespace=mirror_namespace())


def _orgs(store, org: str | None) -> list[str]:
    return [org] if org else sorted(store.change_marks()[1])


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("command", choices=("status", "sync", "rebuild", "verify", "ping"))
    parser.add_argument("--org", help="one organisation (default: every one)")
    parser.add_argument("--apply", action="store_true", help="rebuild: write (default: a dry run)")
    parser.add_argument("--prune", action="store_true",
                        help="rebuild --apply: also remove organisations Neo4j holds that the log hasn't")
    parser.add_argument("--target", choices=("mirror", "graph"), default="mirror")
    args = parser.parse_args(argv)

    if args.command == "ping":
        from backend.maintenance.neo4j_store import connect

        conn = connect()
        print(json.dumps({"first": round(conn.ping(), 3), "second": round(conn.ping(), 3)}))
        return 0

    store = replay()
    if args.command == "verify" and args.target == "graph":
        from backend import config
        from backend.maintenance.neo4j_store import connect, graph_snapshot
        from backend.maintenance.service import PROJECTION_VERSION

        conn, ns = connect(), f"{config.MAINTENANCE_GRAPH_NAMESPACE}graph-v{PROJECTION_VERSION}"
        rows = [{"org": o, "same": store.snapshot(o) == graph_snapshot(conn, ns, o)} for o in _orgs(store, args.org)]
        print(json.dumps({"namespace": ns, "orgs": rows}, indent=2))
        return 0 if all(r["same"] for r in rows) else 1

    mirror = mirror_of(store)
    orgs = _orgs(store, args.org)
    if args.command == "status":
        print(json.dumps(mirror.status(), indent=2, default=str))
    elif args.command == "sync":
        print(json.dumps(mirror.sync(orgs=orgs), indent=2))
    elif args.command == "verify":
        rows = [mirror.verify(o) for o in orgs]
        print(json.dumps(rows, indent=2))
        return 0 if all(r["same"] for r in rows) else 1
    elif args.command == "rebuild":
        remote = mirror.remote_marks(refresh=True)
        extra = sorted(set(remote) - set(store.change_marks()[1])) if not args.org else []
        plan = [{"org": o, "nodes": len(store.snapshot(o)[0]), "edges": len(store.snapshot(o)[1]),
                 "in_neo4j_at": (remote.get(o) or (None,))[0]} for o in orgs]
        if not args.apply:
            print(json.dumps({"dry_run": True, "copy": plan, "in_neo4j_not_in_log": extra}, indent=2))
            return 0
        result = mirror.rebuild(orgs=orgs)
        if args.prune:
            from backend.maintenance.neo4j_store import delete_namespace

            for org in extra:
                delete_namespace(mirror.conn, mirror.ns, org)
            result["pruned"] = extra
        print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
