"""Owner-only graph queries in Cypher (#423), as far as they go without a Neo4j:
who may (graph_query_allowed, everywhere: MCP's tool list and calls, the guide,
the REST routes), the check that only reads get through, the caps, the rows as
JSON, and run_query's steps on a stand-in session. (With a Neo4j:
test_maintenance_graph_cypher_neo4j.py.)"""

import types

import anyio
import httpx2
import mongomock
import pytest
from mcp import Client
from mcp.client.streamable_http import streamable_http_client

from backend import config
from backend import mcp_server  # noqa: F401 - imported before the tests switch Maintenance on (see env)
from backend.maintenance import graph_cypher
from backend.maintenance.access import graph_query_allowed
from backend.maintenance.graph_cypher import Refused, check
from backend.maintenance.service import PROJECTORS, Maintenance
from backend.maintenance.store import GraphStore

# Graph queries run on the mirror of a SQLite graph: the parity run (Neo4j as the
# graph) leaves these be.
pytestmark = pytest.mark.sqlite_only

OWNER, OTHER = "owner-1", "other-1"
GRAPH_TOOLS = {"maintenance_graph_query", "maintenance_graph_schema"}


# ---- who may ---------------------------------------------------------------------------

def _user(email, verified=True):
    return {"uid": "u", "email": email, "email_verified": verified}


def test_only_the_listed_addresses_with_maintenance_and_never_by_default(monkeypatch):
    monkeypatch.setattr(config, "AUTH_DISABLED", False)
    monkeypatch.setattr(config, "BILLING_ENABLED", False)
    monkeypatch.setattr(config, "MAINTENANCE_ENABLED", True)
    monkeypatch.setattr(config, "MAINTENANCE_EMAILS", {"owner@example.org", "m@example.org"})
    monkeypatch.setattr(config, "ADMIN_EMAILS", {"admin@example.org"})
    owner = _user("Owner@Example.org")
    # Empty: off for everyone, the owner and operators included.
    monkeypatch.setattr(config, "GRAPH_QUERY_EMAILS", set())
    assert not graph_query_allowed(owner) and not graph_query_allowed(_user("admin@example.org"))
    monkeypatch.setattr(config, "GRAPH_QUERY_EMAILS", {"owner@example.org", "nomaint@example.org"})
    assert graph_query_allowed(owner)
    assert not graph_query_allowed(_user("m@example.org"))  # Maintenance, but not listed
    assert not graph_query_allowed(_user("admin@example.org"))  # an operator, not listed
    assert not graph_query_allowed(_user("nomaint@example.org"))  # listed, without Maintenance
    assert not graph_query_allowed(_user("owner@example.org", verified=False))
    assert not graph_query_allowed(None) and not graph_query_allowed({"uid": "u"})
    monkeypatch.setattr(config, "MAINTENANCE_ENABLED", False)
    assert not graph_query_allowed(owner)


# ---- the check: one statement, reads only -----------------------------------------------

@pytest.mark.parametrize("query, named", [
    ("CREATE (n:X) RETURN n", "CREATE"),
    ("INSERT (n:X)", "INSERT"),
    ("MERGE (n:X {id: 1}) RETURN n", "MERGE"),
    ("MATCH (n) SET n.x = 1", "SET"),
    ("match (n) set n.x = 1", "SET"),
    ("MATCH (n) DELETE n", "DELETE"),
    ("MATCH (n) DETACH DELETE n", "DETACH"),
    ("MATCH (n) NODETACH DELETE n", "NODETACH"),
    ("MATCH (n) REMOVE n.x", "REMOVE"),
    ("DROP INDEX maintenance_node_org", "DROP"),
    ("LOAD CSV FROM 'https://example.org/x.csv' AS row RETURN row", "LOAD"),
    ("FOREACH (x IN [1] | CREATE ())", "FOREACH"),
    ("USE system MATCH (n) RETURN n", "USE"),
    ("SHOW DATABASES", "SHOW"),
    ("GRANT ROLE admin TO bob", "GRANT"),
    ("DENY READ {*} ON GRAPH * TO bob", "DENY"),
    ("REVOKE ROLE admin FROM bob", "REVOKE"),
    ("ALTER USER bob SET PASSWORD 'x'", "ALTER"),
    ("RENAME USER bob TO rob", "RENAME"),
    ("START DATABASE neo4j", "START"),
    ("STOP DATABASE neo4j", "STOP"),
    ("TERMINATE TRANSACTIONS 'neo4j-transaction-1'", "TERMINATE"),
    ("CALL db.labels()", "CALL"),
    ("CALL { MATCH (n) RETURN n } RETURN n", "CALL"),
    ("MATCH (n) CALL (n) { RETURN 1 AS x } RETURN x", "CALL"),
    ("MATCH (n) RETURN apoc.text.join(['a'], ',')", "apoc.text.join()"),
    ("RETURN db.nameFromElementId('x')", "db.nameFromElementId()"),
    ("RETURN dbms.components()", "dbms.components()"),
    ("RETURN gds.version()", "gds.version()"),
    ("CYPHER 5 MATCH (n) RETURN n", "CYPHER"),
    ("EXPLAIN MATCH (n) RETURN n", "EXPLAIN"),
    ("PROFILE MATCH (n) RETURN n", "PROFILE"),
    ("MATCH (n) WHERE n.x = 1. SET n.y = 2", "SET"),  # after a number, '.' isn't a property's
    ("UNWIND [1] AS x WITH x AS y, 1 AS z SET y.a = 1", "SET"),
])
def test_each_forbidden_construct_is_refused_by_name(query, named):
    with pytest.raises(Refused, match="Not allowed in a graph query") as refused:
        check(query)
    assert named in str(refused.value)


def test_more_than_one_statement_is_refused_and_comments_and_strings_cant_smuggle_one():
    for query in ("MATCH (n) RETURN n; MATCH (m) RETURN m", "RETURN 1;;", "RETURN 1 /* ; */ ; RETURN 2",
                  "RETURN 'it\\'s' ; RETURN 2", 'RETURN "a\\"" ; RETURN 2', "RETURN 1 AS `x;y`; RETURN 2"):
        with pytest.raises(Refused, match="One statement at a time"):
            check(query)
    # In a string, a quoted name or a comment, ';' and clause words are only text.
    for query in ("RETURN 'a; CREATE (n)' AS x", 'RETURN "a\\"; CREATE (n) //" AS x', "RETURN 1 AS `x; CREATE`",
                  "RETURN 1 // ; CREATE (n)\n", "RETURN 1 /* ; DELETE n */", "MATCH (n:`SET`) RETURN n"):
        assert check(query) == query
    assert check("MATCH (n) RETURN n;") == "MATCH (n) RETURN n"
    assert check("MATCH (n) RETURN n ; // done") == "MATCH (n) RETURN n  // done"
    # A word broken by a comment isn't the word (Neo4j reads the comment as a space too).
    assert check("RETURN 1 AS CRE/**/ATE") == "RETURN 1 AS CRE/**/ATE"
    for query, why in (("RETURN 'open", "string isn't closed"), ("RETURN 1 /* open", "comment isn't closed"),
                       ("RETURN `open", "quoted name"), ("", "Cypher text"), (";", "empty"), (None, "Cypher text"),
                       ("RETURN 1" + " " * graph_cypher.MAX_QUERY_CHARS, "characters")):
        with pytest.raises(Refused, match=why):
            check(query)


def test_reads_that_look_like_writes_go_through():
    for query in (
        "MATCH (t:Task {ns: $ns, org: $org}) RETURN t.start AS start, t {.start, set: t.name} AS x",
        "MATCH (p:Position {ns: $ns, org: $org}) WHERE p.name STARTS WITH 'Pump' RETURN p.name",
        "RETURN date.truncate('month', date()) AS m, duration.between(date('2020-01-01'), date()) AS d, "
        "datetime.fromEpoch(0, 0) AS e, point.distance(point({x: 0, y: 0}), point({x: 3, y: 4})) AS km",
        "MATCH (n:Node {ns: $ns, org: $org}) WHERE EXISTS { (n)-[:PART_OF]->() } "
        "RETURN COUNT { (n)<-[:PART_OF]-() } AS kids, COLLECT { MATCH (n)-->(x) RETURN x.id } AS ids",
        "MATCH p = SHORTEST 1 (a:Position {ns: $ns, org: $org, id: $id})(()<-[:FROM]-(:Interface)-[:TO]->()){1,}(b) "
        "RETURN b.name, length(p)",
        "MATCH (n:Node {ns: $ns, org: $org}) RETURN n.label AS label, count(*) AS n ORDER BY n DESC SKIP 0 LIMIT 5 "
        "UNION ALL RETURN 'x' AS label, 0 AS n",
    ):
        assert check(query) == query
    for example in graph_cypher.EXAMPLES:
        assert check(example["cypher"]) == example["cypher"], example["name"]


def test_parameters_and_the_row_limit():
    assert graph_cypher.check_params(None) == {} and graph_cypher.check_params({"id": "x", "n": [1]}) == {
        "id": "x", "n": [1]}
    for params, why in (({"org": "someone"}, r"\$org is set for you"), ({"ns": "x"}, r"\$ns is set for you"),
                        ({"bad name": 1}, "plain identifier"), ([1], "must be an object"),
                        ({"x": float("nan")}, "plain JSON"), ({"x": object()}, "plain JSON"),
                        ({"x": "y" * 200_000}, "over 100 KB")):
        with pytest.raises(Refused, match=why):
            graph_cypher.check_params(params)
    assert graph_cypher.row_limit(None) == 1000 and graph_cypher.row_limit(20_000) == 5000
    assert graph_cypher.row_limit(0) == 1 and graph_cypher.row_limit("7") == 7
    with pytest.raises(Refused):
        graph_cypher.row_limit("many")


# ---- rows as JSON, capped ---------------------------------------------------------------------

def test_rows_are_capped_by_count_and_by_size():
    rows = [{"i": i, "text": "x" * 100} for i in range(50)]
    got, cut = graph_cypher.collect(iter(rows), 10, 10**6, lambda v: v)
    assert len(got) == 10 and cut == "rows"
    got, cut = graph_cypher.collect(iter(rows), 50, 10**6, lambda v: v)
    assert len(got) == 50 and cut is None
    got, cut = graph_cypher.collect(iter(rows), 50, 1000, lambda v: v)
    assert 0 < len(got) < 10 and cut == "bytes"
    assert "first 10 rows" in graph_cypher._truncation_note("rows", 10, 10, 1000)
    assert "about 1 KB" in graph_cypher._truncation_note("bytes", 7, 50, 1000)


def test_nodes_relationships_paths_and_dates_as_plain_json():
    import datetime

    from neo4j.graph import Graph, Node, Path
    from neo4j.spatial import CartesianPoint
    from neo4j.time import Date, DateTime, Duration

    g = Graph()
    a = Node(g, "e1", 1, ["Node", "Position"], {"ns": "mirror", "org": OWNER, "id": "p1", "label": "Position",
                                                 "name": "Pump", "retired": False, "_w": 7,
                                                 "props": '{"name": "Pump", "checklist": [{"text": "x"}]}'})
    b = Node(g, "e2", 2, ["Node", "Position"], {"ns": "mirror", "org": OWNER, "id": "p0", "label": "Position",
                                                 "name": "Plant", "props": "{}"})
    r = g.relationship_type("PART_OF")(g, "r1", 3, {"id": "PART_OF:p1:p0", "props": "{}", "_w": 9})
    r._start_node, r._end_node = a, b
    elsewhere = Node(g, "e3", 4, ["Node", "Item"], {"ns": "mirror", "org": OTHER, "id": "i9", "label": "Item"})
    scope = ("mirror", frozenset({OWNER}))
    got = graph_cypher.serialise({"a": a, "r": r, "path": Path(a, r), "x": elsewhere,
                                  "when": Date(2026, 10, 15), "at": DateTime(2026, 10, 15, 9, 30),
                                  "span": Duration(months=3), "py": datetime.date(2026, 1, 2),
                                  "nan": float("nan"), "pt": CartesianPoint((1.0, 2.0)), "raw": b"abc"},
                                 scope=scope)
    assert got["a"] == {"label": "Position", "id": "p1", "name": "Pump", "retired": False}
    assert got["r"] == {"type": "PART_OF", "id": "PART_OF:p1:p0", "from": "p1", "to": "p0"}
    assert got["path"] == {"nodes": [got["a"], {"label": "Position", "id": "p0", "name": "Plant"}],
                           "relationships": [got["r"]]}
    assert got["x"] == {"redacted": True}  # not this caller's workspace
    assert (got["when"], got["at"][:16], got["span"], got["py"]) == ("2026-10-15", "2026-10-15T09:30", "P3M",
                                                                      "2026-01-02")
    assert got["nan"] is None and got["pt"] == {"srid": 7203, "coordinates": [1.0, 2.0]} and got["raw"] == "<3 bytes>"
    full = graph_cypher.serialise(a, include_props=True)
    assert full["props"] == {"name": "Pump", "checklist": [{"text": "x"}]}


# ---- run_query's steps, on a stand-in session ---------------------------------------------------

class _Result:
    def __init__(self, data=None, keys=(), summary=None):
        self._data, self._keys, self._summary = data or [], list(keys), summary

    def data(self):
        return self._data

    def keys(self):
        return self._keys

    def __iter__(self):
        return iter(self._data)

    def consume(self):
        return self._summary


class _Session:
    def __init__(self, fresh, query_type="r", estimate=10.0, rows=()):
        self.fresh, self.query_type, self.estimate, self.rows, self.ran = fresh, query_type, estimate, rows, []

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def run(self, query, params):
        self.ran.append((query.text, query.timeout, params))
        if query.text == graph_cypher._FRESHNESS:
            return _Result([self.fresh])
        if query.text.startswith("EXPLAIN "):
            plan = {"args": {"EstimatedRows": 1.0}, "children": [{"args": {"EstimatedRows": self.estimate}}]}
            return _Result(summary=types.SimpleNamespace(query_type=self.query_type, plan=plan))
        return _Result(list(self.rows), keys=["n"])


class _Mirror:
    ns, version, conn = "mirror", 1, None

    def __init__(self, scope):
        self.scope, self.asked = frozenset(scope), []

    def in_scope(self, org):
        return org in self.scope

    def notify(self, org=None):
        self.asked.append(org)


@pytest.fixture()
def fake(monkeypatch):
    store = GraphStore(":memory:", PROJECTORS)
    m = Maintenance(store, OWNER, "owner")
    m.create_position("Pump")
    store.mirror = _Mirror({OWNER})
    sessions = []

    def use(**kw):
        kw.setdefault("fresh", {"applied": store.org_mark(OWNER), "version": 1, "synced": "2026-10-15T00:00:00+00:00",
                                "foreign": False})
        sessions.append(_Session(**kw))
        monkeypatch.setattr(graph_cypher, "_session", lambda conn: sessions[-1])
        return sessions[-1]

    return types.SimpleNamespace(store=store, m=m, use=use)


def test_a_query_runs_read_only_with_its_limits_and_says_how_current_the_mirror_is(fake, monkeypatch):
    monkeypatch.setattr(config, "GRAPH_QUERY_TIMEOUT_S", 7)
    session = fake.use(rows=[{"n": i} for i in range(5)])
    got = graph_cypher.run_query(fake.store, OWNER, "MATCH (n:Node {ns: $ns, org: $org}) RETURN 1 AS n;",
                                 {"id": "x"}, limit=3, readable=[OWNER, "team:t1"])
    assert got["columns"] == ["n"] and got["rows"] == [{"n": 0}, {"n": 1}, {"n": 2}] and got["truncated"]
    assert "first 3 rows" in got["note"] and "hint" not in got and got["estimated_rows"] == 10
    assert got["freshness"]["up_to_date"] and got["freshness"]["latest_event"] == fake.store.org_mark(OWNER)
    (fresh, _, fresh_params), (explain, _, params), (statement, timeout, _) = session.ran
    assert fresh_params["orgs"] == [OWNER]  # the team isn't mirrored: anything of it in Neo4j is foreign
    assert explain.startswith("EXPLAIN MATCH") and statement == "MATCH (n:Node {ns: $ns, org: $org}) RETURN 1 AS n"
    assert params == {"id": "x", "org": OWNER, "ns": "mirror"} and timeout == 7

    # Behind: it still runs, says so, and asks for a sync.
    fake.m.create_position("Newer")
    fake.use(fresh={"applied": 1, "version": 1, "synced": "then", "foreign": False}, rows=[{"n": 1}])
    behind = graph_cypher.run_query(fake.store, OWNER, "MATCH (n) RETURN 1 AS n", readable=[OWNER])
    assert behind["rows"] == [{"n": 1}] and not behind["freshness"]["up_to_date"]
    assert "behind" in behind["freshness"]["note"] and fake.store.mirror.asked == [OWNER]
    assert "org: $org" in behind["hint"]


def test_refused_before_running(fake, monkeypatch):
    query = "MATCH (n:Node {ns: $ns, org: $org}) RETURN count(n) AS n"
    session = fake.use(query_type="rw")
    with pytest.raises(Refused, match="Only reads"):
        graph_cypher.run_query(fake.store, OWNER, query, readable=[OWNER])
    assert len(session.ran) == 2  # never run
    monkeypatch.setattr(config, "GRAPH_QUERY_MAX_ESTIMATED_ROWS", 1000)
    session = fake.use(estimate=5000.0)
    with pytest.raises(Refused, match="estimates about 5,000 rows"):
        graph_cypher.run_query(fake.store, OWNER, query, readable=[OWNER])
    assert len(session.ran) == 2
    session = fake.use(fresh={"applied": 1, "version": 1, "synced": None, "foreign": True})
    with pytest.raises(Refused, match="outside your mirrored workspaces"):
        graph_cypher.run_query(fake.store, OWNER, query, readable=[OWNER])
    assert len(session.ran) == 1
    with pytest.raises(Refused, match=r"workspace \(other-1\) isn't copied"):
        graph_cypher.run_query(fake.store, OTHER, query, readable=[OTHER])
    with pytest.raises(Refused, match="SET"):
        graph_cypher.run_query(fake.store, OWNER, "MATCH (n) SET n.x = 1", readable=[OWNER])
    fake.store.mirror = None
    with pytest.raises(graph_cypher.Unavailable, match="mirror"):
        graph_cypher.run_query(fake.store, OWNER, query, readable=[OWNER])
    with pytest.raises(graph_cypher.Unavailable):
        graph_cypher.graph_schema(fake.store, OWNER, [OWNER])


# ---- MCP and REST: listed, answered and routed only for graph_query_allowed ---------------------

@pytest.fixture()
def env(monkeypatch):
    from backend import db
    from backend.maintenance import mcp_tools
    from backend.routers import maintenance as router
    from backend.services import tokens

    monkeypatch.setattr(config, "AUTH_DISABLED", False)
    monkeypatch.setattr(config, "BILLING_ENABLED", False)
    monkeypatch.setattr(config, "MAINTENANCE_ENABLED", True)
    monkeypatch.setattr(config, "MAINTENANCE_EMAILS", {"owner@example.org", "m@example.org"})
    monkeypatch.setattr(config, "ADMIN_EMAILS", {"m@example.org"})
    monkeypatch.setattr(config, "GRAPH_QUERY_EMAILS", {"owner@example.org"})
    test_db = mongomock.MongoClient()["reliafy_graph_cypher"]
    monkeypatch.setattr(db, "_db", test_db)
    monkeypatch.setattr(db, "_simulated", True)
    monkeypatch.setattr(router, "_store", GraphStore(":memory:", PROJECTORS))
    for uid, email in ((OWNER, "owner@example.org"), (OTHER, "m@example.org")):
        test_db.users.insert_one({"_id": uid, "email": email, "name": uid, "email_verified": True})
    mcp_tools.register()
    yield {"db": test_db, "owner": tokens.create_token(test_db, OWNER, "mcp")["token"],
           "other": tokens.create_token(test_db, OTHER, "mcp")["token"]}
    mcp_tools.unregister()


def _session(token, fn):
    from backend.main import app
    from backend.mcp_server import mcp_http_app

    out = {}

    async def main():
        async with mcp_http_app.lifespan():
            async with httpx2.AsyncClient(transport=httpx2.ASGITransport(app=app), base_url="http://testserver",
                                          headers={"Authorization": f"Bearer {token}"}) as hc:
                async with Client(streamable_http_client("http://testserver/mcp", http_client=hc),
                                  mode="legacy") as client:
                    out["value"] = await fn(client)

    anyio.run(main)
    return out["value"]


async def _look(client):
    tools = {t.name: t for t in (await client.list_tools()).tools}
    return {"tools": tools, "instructions": client.instructions,
            "query": await client.call_tool("maintenance_graph_query", {"cypher": "MATCH (n) RETURN n LIMIT 1"}),
            "schema": await client.call_tool("maintenance_graph_schema", {}),
            "guide": await client.call_tool("maintenance_guide", {"topic": "graph"}),
            "index": await client.call_tool("maintenance_guide", {})}


def _topics(tool) -> list:
    topic = tool.input_schema["properties"]["topic"]
    return next(x["enum"] for x in topic.get("anyOf", [topic]) if "enum" in x)


def test_mcp_hides_and_refuses_the_graph_tools_for_everyone_else(env, monkeypatch):
    from backend.maintenance import mcp_guide

    # A Maintenance user (an operator, even) who isn't listed: no tools, no topic, no instructions.
    other = _session(env["other"], _look)
    assert not GRAPH_TOOLS & set(other["tools"]) and "maintenance_overview" in other["tools"]
    assert "graph" not in _topics(other["tools"]["maintenance_guide"])
    assert other["query"].is_error and other["query"].content[0].text.endswith("Unknown tool: maintenance_graph_query")
    assert other["schema"].is_error and "Unknown tool" in other["schema"].content[0].text
    assert other["guide"].is_error and "graph" not in other["index"].structured_content["topics"]
    assert "maintenance_graph" not in other["instructions"]

    # The owner: listed, the topic and the instructions line; the call reaches the mirror (none here).
    owner = _session(env["owner"], _look)
    assert GRAPH_TOOLS <= set(owner["tools"]) and "graph" in _topics(owner["tools"]["maintenance_guide"])
    assert all(owner["tools"][n].annotations.read_only_hint for n in GRAPH_TOOLS)
    assert owner["query"].is_error and "Neo4j mirror" in owner["query"].content[0].text
    assert owner["guide"].structured_content["guide"] == mcp_guide.GRAPH_TOPIC[1]
    assert mcp_guide.GRAPH_INSTRUCTIONS.strip() in owner["instructions"]

    # An empty list: off for the owner too.
    monkeypatch.setattr(config, "GRAPH_QUERY_EMAILS", set())
    off = _session(env["owner"], _look)
    assert not GRAPH_TOOLS & set(off["tools"]) and off["query"].is_error and off["guide"].is_error
    assert "Unknown tool" in off["query"].content[0].text


def test_mcp_graph_calls_take_a_heavy_slot_and_are_logged(env, monkeypatch):
    monkeypatch.setattr(config, "USAGE_LOGGING", True)
    env["db"].teams.insert_one({"_id": "t1", "name": "T", "owner_uid": OWNER, "members": [{"uid": OWNER}]})
    calls = []
    monkeypatch.setattr(graph_cypher, "run_query", lambda *a, **k: (calls.append(a), {"rows": [{"n": 1}]})[1])
    monkeypatch.setattr(graph_cypher, "graph_schema", lambda *a: {"nodes": []})
    heavy_calls = []
    real = mcp_server._run_in_slot

    async def spy(uid, body, heavy=False):
        heavy_calls.append(heavy)
        return await real(uid, body, heavy=heavy)

    monkeypatch.setattr(mcp_server, "_run_in_slot", spy)

    async def flow(client):
        q = await client.call_tool("maintenance_graph_query", {
            "cypher": "MATCH (n:Node {ns: $ns, org: $org}) RETURN count(n) AS n", "params": {"x": 1}, "limit": 5,
            "include_props": True})
        s = await client.call_tool("maintenance_graph_schema", {})
        return q, s

    q, s = _session(env["owner"], flow)
    assert q.structured_content == {"rows": [{"n": 1}]} and s.structured_content == {"nodes": []}
    store, org, cypher, params, limit, include_props, readable = calls[0]
    assert (org, params, limit, include_props) == (OWNER, {"x": 1}, 5, True)
    assert readable == [OWNER, "team:t1"]
    assert heavy_calls == [True, True]
    features = {e["feature"] for e in env["db"].usage_events.find({"channel": "mcp", "uid": OWNER})}
    assert {"maintenance_graph_query", "maintenance_graph_schema"} <= features


def test_rest_routes_answer_404_to_everyone_else(env, monkeypatch):
    from fastapi.testclient import TestClient

    from backend.auth import get_current_user
    from backend.main import app

    who = {"user": {"uid": OTHER, "email": "m@example.org", "name": "M", "email_verified": True}}
    app.dependency_overrides[get_current_user] = lambda: who["user"]
    try:
        client = TestClient(app)
        body = {"cypher": "MATCH (n:Node {ns: $ns, org: $org}) RETURN n LIMIT 1"}
        assert client.post("/api/maintenance/graph/query", json=body).status_code == 404
        assert client.get("/api/maintenance/graph/schema").status_code == 404
        assert client.get("/api/maintenance/overview").status_code == 200  # Maintenance itself, yes

        who["user"] = {"uid": OWNER, "email": "owner@example.org", "name": "O", "email_verified": True}
        r = client.post("/api/maintenance/graph/query", json=body)
        assert r.status_code == 503 and "mirror" in r.json()["detail"]  # allowed; no mirror here
        assert client.post("/api/maintenance/graph/query", json={**body, "extra": 1}).status_code == 422
        assert client.post("/api/maintenance/graph/query", json={"cypher": "MATCH (n) DELETE n"}).status_code == 422
        seen = []
        monkeypatch.setattr(graph_cypher, "run_query", lambda *a: (seen.append(a), {"rows": []})[1])
        monkeypatch.setattr(graph_cypher, "graph_schema", lambda *a: (seen.append(a), {"nodes": []})[1])
        assert client.post("/api/maintenance/graph/query", json={**body, "params": {"id": "x"}, "limit": 9}).json() \
            == {"rows": []}
        assert client.get("/api/maintenance/graph/schema").json() == {"nodes": []}
        assert seen[0][1:] == (OWNER, body["cypher"], {"id": "x"}, 9, False, [OWNER])
        assert seen[1][1:] == (OWNER, [OWNER])

        monkeypatch.setattr(config, "GRAPH_QUERY_EMAILS", set())
        assert client.post("/api/maintenance/graph/query", json=body).status_code == 404
        assert client.get("/api/maintenance/graph/schema").status_code == 404
    finally:
        app.dependency_overrides.clear()
