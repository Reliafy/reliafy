"""The maintenance graph against a real Neo4j (skipped without NEO4J_TEST_URI:
backend/tests/neo4j_support.py). Each test keeps to namespaces and
organisations of its own and removes them after. Few tests, each doing a lot:
a round trip to a hosted Neo4j can take a third of a second."""

import threading

import pytest

from backend.maintenance import graph_query
from backend.maintenance.mirror import Neo4jMirror, catch_up
from backend.maintenance.neo4j_store import Neo4jGraphStore, graph_snapshot
from backend.maintenance.service import PROJECTION_VERSION, PROJECTORS, Maintenance
from backend.maintenance.store import GraphStore, SqliteEventLog, new_id, open_sqlite
from backend.tests import neo4j_support
from backend.tests.neo4j_support import needs_neo4j, plant, query_cases

pytestmark = needs_neo4j


@pytest.fixture()
def spaces():
    """Namespaces made by the test, removed after it."""
    made: list[str] = []

    def make() -> str:
        made.append(neo4j_support.namespace())
        return made[-1]

    yield make
    neo4j_support.drop(made)


def _org() -> str:
    return f"test-org-{new_id()[:10]}"


def _shared_log() -> SqliteEventLog:
    return SqliteEventLog(open_sqlite(":memory:"), threading.RLock())


def _ask(m, query: str, id: str, use: str):
    return getattr(graph_query, query)(m, id, use=use)


def test_neo4j_graph_is_the_sqlite_graph_and_writers_never_double_apply(spaces):
    conn, org, log = neo4j_support.connection(), _org(), _shared_log()
    sqlite = GraphStore(":memory:", PROJECTORS, log, version=PROJECTION_VERSION)
    p = plant(Maintenance(sqlite, org, "tester"))

    # The same log replayed into Neo4j gives the same graph, node for node.
    ns = spaces()
    a = Neo4jGraphStore(conn, PROJECTORS, log, version=PROJECTION_VERSION, namespace=ns)
    assert a.sync() == len(log.since(0))
    assert a.snapshot() == sqlite.snapshot() and a.skipped() == []

    # Graph queries on it are answered in Cypher, and agree with Python on SQLite.
    on_neo4j, on_sqlite = Maintenance(a, org), Maintenance(sqlite, org)
    for query, id in query_cases(p):
        assert _ask(on_neo4j, query, id, "cypher") == _ask(on_sqlite, query, id, "python"), (query, id)

    # Two processes writing at once through one log: every event applied once, none passed over.
    b = Neo4jGraphStore(conn, PROJECTORS, log, version=PROJECTION_VERSION, namespace=ns)
    errors = []

    def write(store, name):
        try:
            w = Maintenance(store, org, name)
            for i in range(4):
                w.create_position(f"{name} {i}", parent_id=p["elec"])
                w.update_position(p["f12"], description=f"{name} {i}")
        except Exception as err:  # noqa: BLE001
            errors.append(err)

    threads = [threading.Thread(target=write, args=(s, n)) for s, n in ((a, "A"), (b, "B"))]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert errors == []
    sqlite.sync()
    last = log.since(0)[-1]["seq"]
    assert a._applied() == b._applied() == last and a.skipped() == []
    assert a.snapshot() == sqlite.snapshot()
    assert len([n for n in a.nodes(org, "Position") if n["name"][:2] in ("A ", "B ")]) == 8

    # A rebuild replays the log to the same graph.
    assert a.rebuild() == last and a.snapshot() == sqlite.snapshot()


def test_the_mirror_keeps_up_in_step_across_instances(spaces):
    conn, org, log, ns = neo4j_support.connection(), _org(), _shared_log(), spaces()
    one = GraphStore(":memory:", PROJECTORS, log, version=PROJECTION_VERSION)
    m = Maintenance(one, org, "tester")
    p = plant(m)
    mirror = Neo4jMirror(one, conn, namespace=ns, queries=True)
    mirror.notify = lambda org=None: None  # synced by hand here
    mirror.attach()
    assert mirror.pending()[org]["full"]
    first = mirror.sync()
    assert (first["orgs"], first["full"]) == (1, 1) and mirror.verify(org)["same"]
    assert mirror.pending() == {}

    # Edges deleted and replaced: only what changed is sent.
    m.update_position(p["f12"], parent_id=p["elec"])
    m.update_group(m.groups_of(p["pump_a"])[0]["id"], add=[p["outlet"]])
    m.update_group(m.groups_of(p["pump_a"])[0]["id"], remove=[p["outlet"]])
    m.assign_item_class(p["spare"], p["rotating"])
    m.connect(p["outlet"], p["header"])
    second = mirror.sync()
    assert second["full"] == 0 and second["gone"] >= 3 and second["nodes"] < 10
    assert mirror.verify(org)["same"]

    # Graph queries: Cypher on the mirror agrees with Python; a mirror one write
    # behind isn't asked (Cypher refuses, the default answers in Python).
    for query, id in query_cases(p):
        assert _ask(m, query, id, "cypher") == _ask(m, query, id, "python"), (query, id)
    m.connect(p["header"], p["tank"])
    with pytest.raises(graph_query.Stale):
        graph_query.downstream(m, p["outlet"], use="cypher")
    assert [r["name"] for r in graph_query.downstream(m, p["outlet"])][:2] == ["Header", "Tank"]

    # A second instance (its own SQLite copy of the shared log) syncing at the same
    # time: one writes, the other finds it done or conflicts and re-reads.
    two = GraphStore(":memory:", PROJECTORS, log, version=PROJECTION_VERSION)
    two.sync()
    other = Neo4jMirror(two, conn, namespace=ns)
    m.create_position("Late")
    two.sync()
    results, errors = [], []

    def run(mx):
        try:
            results.append(mx.sync())
        except Exception as err:  # noqa: BLE001
            errors.append(err)

    threads = [threading.Thread(target=run, args=(mx,)) for mx in (mirror, other)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert errors == [] and sum(r["orgs"] for r in results) >= 1
    assert mirror.verify(org)["same"] and other.verify(org)["same"]
    assert mirror.remote_marks(refresh=True)[org][0] == one.change_marks()[0]

    # Copied whole: in parts in one transaction, and for a new projection version.
    small = Neo4jMirror(one, conn, namespace=ns, chunk=25)
    assert small.rebuild([org])["full"] == 1 and small.verify(org)["same"]
    one.version = PROJECTION_VERSION + 1
    newer = Neo4jMirror(one, conn, namespace=ns)
    assert newer.sync()["full"] == 1 and newer.verify(org)["same"]
    assert Neo4jMirror(two, conn, namespace=ns).sync()["skipped"] == 1  # older code leaves it alone

    # The hourly job's catch-up (and keep-alive) on a mirror with nothing to do.
    one.mirror = newer
    got = catch_up(one)
    assert "error" not in got and got["orgs"] == 0
    assert graph_snapshot(conn, ns, org) == one.snapshot(org)
