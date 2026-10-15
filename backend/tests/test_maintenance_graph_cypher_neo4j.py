"""Owner-only graph queries in Cypher (#423) against a real Neo4j: skipped without
NEO4J_TEST_URI (backend/tests/neo4j_support.py), like #417's.

Each test keeps to namespaces and organisations of its own and removes them
after: nothing else in the database is written or deleted. Graph queries
refuse to run while the database holds anything outside the caller's mirrored
workspaces, so run this module on its own (not beside the parity run), e.g.:

    NEO4J_TEST_URI=... python -m pytest backend/tests/test_maintenance_graph_cypher_neo4j.py
"""

import threading

import pytest

from backend import config
from backend.maintenance import graph_cypher, graph_query
from backend.maintenance.mirror import Neo4jMirror, catch_up
from backend.maintenance.neo4j_store import graph_snapshot
from backend.maintenance.service import PROJECTION_VERSION, PROJECTORS, Maintenance
from backend.maintenance.store import GraphStore, SqliteEventLog, new_id, open_sqlite
from backend.tests import neo4j_support
from backend.tests.neo4j_support import needs_neo4j, plant

pytestmark = [needs_neo4j, pytest.mark.sqlite_only]


def _org() -> str:
    return f"test-org-{new_id()[:10]}"


def _workspace(m) -> dict:
    """The plant, with work, failures, failure modes, spares and makers for the examples."""
    p = plant(m)
    p["wo_a"] = m.open_work_order(p["pump_a"], "Check Pump A")["number"]
    p["wo_filter"] = m.open_work_order(p["filter"], "Filter blocked")["number"]
    closed = m.open_work_order(p["tank"], "Tank inspection")
    m.close_work_order(closed["id"], notes="fine")
    pump_c = m.create_position("Pump C", position_class="Duty pump")["id"]
    m.fit(pump_c, new_item={"name": "Pump C1", "manufacturer": "Acme"})
    p["pump_c1"] = m.position(pump_c)["fitted"]["item"]["id"]
    m.remove(pump_c, reason="failure", failure_mode_text="Seal leak")
    m.fit(pump_c, new_item={"name": "Pump C2"})
    m.add_past_fitment(pump_c, "2015-01-01", "2016-01-01", reason="failure", new_item={"name": "Pump C0"},
                       failure_mode_text="Seal leak")  # over 3 years ago
    pump_d = m.create_position("Pump D", position_class="Duty pump")["id"]
    m.fit(pump_d, new_item={"name": "Pump D1"})
    m.remove(pump_d, reason="failure", failure_mode_text="Bearing worn")
    bearing = m.add_failure_mode(p["pump_a"], "Bearing worn")["id"]
    m.create_task(p["pump_a"], "Grease bearings", 3, failure_mode_id=bearing)
    p["pump_c"], p["pump_d"] = pump_c, pump_d

    short = m.create_part("P-200", "Seal kit")["id"]
    m.add_position_part(p["pump_b"], short, role="replacement", critical=True, min_on_hand=2)
    m.adjust_stock(short, p["store"], 1)
    old = m.create_part("P-300", "Filter element")["id"]
    new = m.create_part("P-301", "Filter element, new")["id"]
    m.supersede_part(old, new)
    m.add_position_part(p["filter"], old, role="replacement", critical=True, min_on_hand=1)
    m.adjust_stock(new, p["store"], 1)  # covered by what supersedes it
    alt = m.create_part("P-400", "Gasket")["id"]
    alt2 = m.create_part("P-401", "Gasket, other make")["id"]
    m.mark_interchangeable(alt, alt2)
    m.add_position_part(p["outlet"], alt, role="component", critical=True, min_on_hand=3)
    m.adjust_stock(alt2, p["store"], 2)  # 2 < 3: short
    p["parts"] = {"short": short, "old": old, "alt": alt}

    maker = m.create_manufacturer("KSB")["id"]
    m.link_manufacturer(p["pump_c1"], maker)
    return p


@pytest.fixture()
def env(monkeypatch):
    """A workspace mirrored to its own namespace (in scope), another in the same
    store that isn't (out of scope), and the mirror's queries' settings."""
    conn, ns, org, other = neo4j_support.connection(), neo4j_support.namespace(), _org(), _org()
    log = SqliteEventLog(open_sqlite(":memory:"), threading.RLock())
    store = GraphStore(":memory:", PROJECTORS, log, version=PROJECTION_VERSION)
    m = Maintenance(store, org, "owner")
    p = _workspace(m)
    Maintenance(store, other, "someone").create_position("Someone else's pump")
    monkeypatch.setattr(config, "MAINTENANCE_GRAPH_MIRROR_ORGS", frozenset({org}))
    mirror = Neo4jMirror(store, conn, namespace=ns)
    mirror.notify = lambda org=None: None  # synced by hand here
    mirror.attach()
    try:
        yield {"conn": conn, "ns": ns, "org": org, "other": other, "store": store, "m": m, "p": p,
               "mirror": mirror}
    finally:
        neo4j_support.drop([ns])


def _ask(env, name: str, **params):
    example = next(e for e in graph_cypher.EXAMPLES if e["name"] == name)
    return graph_cypher.run_query(env["store"], env["org"], example["cypher"], params, readable=[env["org"]])


def test_only_the_mirrored_workspace_reaches_neo4j_and_the_examples_run_on_it(env):
    mirror, conn, ns, org, other, m, p = (env[k] for k in ("mirror", "conn", "ns", "org", "other", "m", "p"))
    got = mirror.sync()
    assert got["orgs"] == 1 and got["out_of_scope"] == 1
    assert mirror.sync(orgs=[other])["orgs"] == 0  # asked for by name: still never sent
    assert graph_snapshot(conn, ns, other) == ([], [])
    assert graph_snapshot(conn, ns, org) == env["store"].snapshot(org)
    assert set(mirror.pending()) == set() and mirror.status()["outside_scope_in_neo4j"] == []

    # Every example runs as it is.
    fills = {"id": p["tank"], "class_id": p["pump"], "location_id": p["yard"], "item_id": p["pump_c1"]}
    for example in graph_cypher.EXAMPLES:
        params = {k: fills[k] for k in example["params"]}
        result = graph_cypher.run_query(env["store"], org, example["cypher"], params, readable=[org])
        assert result["freshness"]["up_to_date"], example["name"]
        assert "hint" not in result and result["truncated"] is False, example["name"]

    # ... and gives the answers the app does.
    down = _ask(env, "downstream", id=p["tank"])["rows"]
    assert [(r["name"], r["hops"]) for r in down] == [
        (r["name"], r["depth"]) for r in graph_query.downstream(m, p["tank"], use="python")]
    up = _ask(env, "upstream", id=p["outlet"])["rows"]
    assert {r["name"] for r in up} == {"Filter", "Pump A", "Pump B", "Tank"}
    fitted = _ask(env, "class_in_location", class_id=p["pump"], location_id=p["yard"])["rows"]
    assert [(r["item"], r["position"], r["location"]) for r in fitted] == [("Engine E1", "Truck 14", "Yard")]
    assert _ask(env, "class_in_location", class_id=p["pump"], location_id=p["site"])["rows"] == []
    open_work = _ask(env, "open_work_without_redundancy")["rows"]
    assert [(r["position"], r["open_work_orders"]) for r in open_work] == [("Filter", [p["wo_filter"]])]
    failures = _ask(env, "failures_by_class")["rows"]
    assert failures == [{"position_class": "Duty pump", "failures": 2, "positions": 2}]
    short = _ask(env, "critical_spares_short")["rows"]
    assert {r["part"] for r in short} == {v["part"]["part_number"] for v in m.critical_spares_short()} \
        == {"P-200", "P-400"}
    gaps = {(r["position"], r["failure_mode"]) for r in _ask(env, "unmitigated_failure_modes")["rows"]}
    assert gaps == {("Pump C", "Seal leak"), ("Pump D", "Bearing worn")}
    placed = {r["location"]: sorted(r["items"]) for r in _ask(env, "spares_placed")["rows"]}
    assert placed == {"Store": ["Engine E2", "Spare pump"], "Gallery": ["Spare motor"]}
    history = _ask(env, "item_history", item_id=p["pump_c1"])["rows"]
    assert [(r["position"], r["why"]) for r in history] == [("Pump C", "failure")]
    branch = graph_cypher.run_query(env["store"], org, next(e for e in graph_cypher.EXAMPLES
                                                             if e["name"] == "subtree_fitted")["cypher"],
                                    {"id": p["elec"]}, readable=[org])["rows"]
    assert [r["position"] for r in branch][:2] == ["Electrical", "MCC-3"]
    makers = {r["manufacturer"]: (r["items"], r["failures"]) for r in _ask(env, "failures_by_manufacturer")["rows"]}
    assert makers["KSB"] == (1, 1) and makers["(unknown)"][1] == 2

    # The schema: this workspace's labels, properties and relationships, the examples, the limits.
    schema = graph_cypher.graph_schema(env["store"], org, [org])
    labels = {n["label"]: n for n in schema["nodes"]}
    assert labels["Position"]["count"] == env["store"].count(org, "Position")
    assert labels["Position"]["properties"]["name"]["type"] == "STRING"
    assert "props" not in labels["Position"]["properties"] and "ns" not in labels["Position"]["properties"]
    rels = {r["type"]: r for r in schema["relationships"]}
    assert {(c["from"], c["to"]) for c in rels["AT"]["connects"]} == {
        ("Fitment", "Position"), ("Placement", "Location"), ("Stock", "Location")}
    assert {"PART_OF", "LOCATED_AT", "IN", "FROM", "TO", "IN_GROUP", "LISTED_AT", "SUPERSEDED_BY"} <= set(rels)
    assert 8 <= len(schema["examples"]) <= 12 and schema["freshness"]["up_to_date"]


def test_reads_only_three_ways_and_the_limits(env, monkeypatch):
    mirror, conn, org, store, p = (env[k] for k in ("mirror", "conn", "org", "store", "p"))
    mirror.sync()
    run = lambda q, **kw: graph_cypher.run_query(store, org, q, readable=[org], **kw)  # noqa: E731

    # 1. Refused by name before it's sent.
    with pytest.raises(graph_cypher.Refused, match="CREATE"):
        run("CREATE (n:GraphQueryProbe) RETURN n")
    # 2. Past the check, a READ session refuses a write; 3. the plan says it would write.
    monkeypatch.setattr(graph_cypher, "check", lambda q: q)
    with pytest.raises(graph_cypher.Refused, match="Only reads"):
        run("CREATE (n:GraphQueryProbe) RETURN n")
    from neo4j import Query
    from neo4j.exceptions import Neo4jError

    with graph_cypher._session(conn) as session, pytest.raises(Neo4jError) as refused:
        session.run(Query("CREATE (n:GraphQueryProbe) RETURN n")).consume()
    assert "AccessMode" in refused.value.code
    assert conn.run("MATCH (n:GraphQueryProbe) RETURN count(n) AS n")[0]["n"] == 0
    monkeypatch.undo()
    monkeypatch.setattr(config, "MAINTENANCE_GRAPH_MIRROR_ORGS", frozenset({org}))

    # Rows: capped, with a note; nodes, relationships and paths as plain JSON.
    many = run("MATCH (n:Node {ns: $ns, org: $org}) RETURN n.id AS id", limit=3)
    assert many["row_count"] == 3 and many["truncated"] and "first 3 rows" in many["note"]
    shapes = run("MATCH path = (c:Position {ns: $ns, org: $org, id: $id})-[r:PART_OF]->(parent) "
                 "RETURN c, r, parent, path, date('2026-10-15') AS day, duration('P3M') AS span",
                 params={"id": p["mcc"]}, include_props=True)["rows"][0]
    assert shapes["c"]["label"] == "Position" and shapes["c"]["name"] == "MCC-3" and shapes["c"]["id"] == p["mcc"]
    assert not {"ns", "org", "_w"} & set(shapes["c"]) and shapes["c"]["props"]["name"] == "MCC-3"
    assert shapes["r"] == {"type": "PART_OF", "id": f"PART_OF:{p['mcc']}:{p['elec']}", "from": p["mcc"],
                           "to": p["elec"], "props": {}}
    assert [n["name"] for n in shapes["path"]["nodes"]] == ["MCC-3", "Electrical"]
    assert shapes["day"] == "2026-10-15" and shapes["span"] == "P3M"
    plain = run("MATCH (c:Position {ns: $ns, org: $org, id: $id}) RETURN c", params={"id": p["mcc"]})["rows"][0]
    assert "props" not in plain["c"]
    assert "hint" in run("MATCH (n:Position) RETURN count(n) AS n")  # no org: $org

    # The plan's estimate, and the timeout.
    monkeypatch.setattr(config, "GRAPH_QUERY_MAX_ESTIMATED_ROWS", 50)
    with pytest.raises(graph_cypher.Refused, match="estimates about"):
        run("MATCH (a:Node {ns: $ns, org: $org}), (b:Node {ns: $ns, org: $org}) RETURN count(*) AS n")
    monkeypatch.setattr(config, "GRAPH_QUERY_MAX_ESTIMATED_ROWS", 10 ** 12)
    monkeypatch.setattr(config, "GRAPH_QUERY_TIMEOUT_S", 1)
    with pytest.raises(graph_cypher.Refused, match="ran past the 1 s limit"):
        run("UNWIND range(1, 300000000) AS x WITH x WHERE x < 0 RETURN count(*) AS n")
    # Syntax errors come back as Neo4j says them.
    with pytest.raises(graph_cypher.Refused, match="Neo4j refused the query"):
        run("MATCH (n RETURN n")


def test_freshness_and_the_database_holding_nothing_else(env, monkeypatch):
    mirror, conn, org, other, store, m, p = (env[k] for k in ("mirror", "conn", "org", "other", "store", "m", "p"))
    query = "MATCH (p:Position {ns: $ns, org: $org}) RETURN count(p) AS n"
    first = graph_cypher.run_query(store, org, query, readable=[org])
    assert first["rows"] == [{"n": 0}] and not first["freshness"]["up_to_date"]
    assert "hasn't been copied" in first["freshness"]["note"]
    mirror.sync()
    fresh = graph_cypher.run_query(store, org, query, readable=[org])
    assert fresh["freshness"]["up_to_date"] and fresh["freshness"]["mirror_event"] >= store.org_mark(org)
    asked = []
    mirror.notify = lambda o=None: asked.append(o)
    m.create_position("Not mirrored yet")
    behind = graph_cypher.run_query(store, org, query, readable=[org])
    assert behind["rows"] == fresh["rows"] and not behind["freshness"]["up_to_date"]
    assert "behind" in behind["freshness"]["note"] and asked == [org]  # it still ran, and a sync was asked for
    mirror.sync()
    assert graph_cypher.run_query(store, org, query, readable=[org])["rows"][0]["n"] == fresh["rows"][0]["n"] + 1

    # A workspace outside the scope can't be queried; and while the database holds one
    # (copied before the scope narrowed), nothing can be, until it's pruned.
    with pytest.raises(graph_cypher.Refused, match="isn't copied to Neo4j"):
        graph_cypher.run_query(store, other, query, readable=[other])
    Neo4jMirror(store, conn, namespace=env["ns"], orgs=[other]).sync()
    assert graph_snapshot(conn, env["ns"], other)[0]
    with pytest.raises(graph_cypher.Refused, match="outside your mirrored workspaces"):
        graph_cypher.run_query(store, org, query, readable=[org])
    got = catch_up(store)  # the hourly job prunes it
    assert got["pruned"] == 1 and graph_snapshot(conn, env["ns"], other) == ([], [])
    assert graph_cypher.run_query(store, org, query, readable=[org])["freshness"]["up_to_date"]
