"""Graph queries in Cypher, the agent's own (#423): owner-only, read-only, on the
Neo4j mirror.

Who: only :func:`backend.maintenance.access.graph_query_allowed` (the addresses
in ``GRAPH_QUERY_EMAILS``, with Maintenance); everyone else is never shown the
tools or routes. What: the mirror (``mirror.py``), which copies only the
workspaces in ``MAINTENANCE_GRAPH_MIRROR_ORGS``. Neo4j AuraDB Free has no access
control, so that is the isolation for now: there is nothing else in the
database to reach, and :func:`run_query` checks it is so before every query.
(For paying users later, each query would run on a throwaway graph holding only
that workspace: not built.)

A query passes three layers before it runs:

1. :func:`check`: one statement, reads only. Write and admin clauses, ``CALL``
   (procedures and subqueries), plugin functions (``apoc.``, ``db.``,
   ``dbms.``...) and query options are refused by name, read from the query's
   tokens with comments and strings set aside, so neither can hide a second
   statement or a clause.
2. A READ access-mode session: Neo4j itself refuses any write.
3. ``EXPLAIN`` first: a plan that isn't read-only, or that estimates more rows
   at any step than ``GRAPH_QUERY_MAX_ESTIMATED_ROWS``, is refused.

Then it runs with a transaction timeout (``GRAPH_QUERY_TIMEOUT_S``), and the
rows come back as plain JSON (nodes as their label, id and plain properties;
dates as ISO strings), at most ``limit`` (1,000 by default, 5,000 at most) and
about ``GRAPH_QUERY_MAX_BYTES``, cut off with a note beyond that. Each answer
says how current the mirror is for the workspace (:func:`freshness`).

``$org`` (the caller's workspace) and ``$ns`` (the mirror's namespace) are
always passed: queries match on ``{ns: $ns, org: $org}``.
"""

from __future__ import annotations

import datetime as _dt
import json
import math
import re

from backend import config

MAX_ROWS = 1000
HARD_MAX_ROWS = 5000
MAX_QUERY_CHARS = 20_000
MAX_PARAM_BYTES = 100_000

# Clauses that write or administer, and the ways round them, refused wherever
# they stand as a word (not a property after '.', a map key, or an alias after AS).
FORBIDDEN = {
    "CREATE", "INSERT", "MERGE", "SET", "DELETE", "DETACH", "NODETACH", "REMOVE", "DROP", "LOAD", "FOREACH",
    "USE", "SHOW", "GRANT", "DENY", "REVOKE", "ALTER", "RENAME", "START", "STOP", "TERMINATE", "ENABLE",
    "DEALLOCATE", "REALLOCATE", "DRYRUN", "CALL", "CYPHER", "EXPLAIN", "PROFILE",
}
# Namespaces of Cypher's own functions (date.truncate, duration.between, point.distance...):
# any other dotted function (apoc., db., dbms., gds., genai.: plugins and procedures) is refused.
BUILTIN_NAMESPACES = {"date", "datetime", "localdatetime", "localtime", "time", "duration", "point", "vector"}

# Node properties that are the mirror's own bookkeeping, not the record's.
_INTERNAL = {"ns", "org", "props", "_w"}


class GraphQueryError(Exception):
    """A graph query that can't be answered; ``status`` is the HTTP status."""

    status = 422


class Refused(GraphQueryError):
    """Not run (or stopped): the query, its parameters or its plan aren't allowed,
    or Neo4j refused it (syntax, timeout). The message says why."""


class Unavailable(GraphQueryError):
    """No mirror to ask, or Neo4j can't be reached."""

    status = 503


# ---- 1. the query itself: one statement, reads only ---------------------------------------

_WORD = re.compile(r"[^\W\d]\w*")
_NUMBER = re.compile(r"0[xX][0-9a-fA-F_]+|0[oO][0-7_]+|\d[\d_]*(?:\.\d[\d_]*)?(?:[eE][+-]?\d+)?")


def _tokens(text: str) -> list[tuple[str, str, int]]:
    """(kind, text, offset) for each token: word, name (`quoted`), param, string,
    number, punct. Comments are dropped; strings and quoted names are kept whole,
    so nothing inside them is read as Cypher."""
    out: list[tuple[str, str, int]] = []
    i, n = 0, len(text)
    while i < n:
        c = text[i]
        if c.isspace():
            i += 1
        elif text.startswith("//", i):
            end = text.find("\n", i)
            i = n if end < 0 else end + 1
        elif text.startswith("/*", i):
            end = text.find("*/", i + 2)
            if end < 0:
                raise Refused("A /* comment isn't closed.")
            i = end + 2
        elif c in "'\"":
            j = i + 1
            while j < n and text[j] != c:
                j += 2 if text[j] == "\\" else 1
            if j >= n:
                raise Refused("A string isn't closed.")
            out.append(("string", text[i:j + 1], i))
            i = j + 1
        elif c == "`" or (c == "$" and text.startswith("`", i + 1)):
            start = i
            j = i + (2 if c == "$" else 1)
            while True:
                k = text.find("`", j)
                if k < 0:
                    raise Refused("A `quoted name` isn't closed.")
                if text.startswith("``", k):
                    j = k + 2
                    continue
                break
            out.append(("param" if c == "$" else "name", text[start:k + 1], start))
            i = k + 1
        elif c == "$":
            m = _WORD.match(text, i + 1) or re.compile(r"\d+").match(text, i + 1)
            if not m:
                raise Refused("A $ must be followed by a parameter's name.")
            out.append(("param", text[i:m.end()], i))
            i = m.end()
        elif (m := _WORD.match(text, i)) is not None:
            out.append(("word", m.group(), i))
            i = m.end()
        elif (m := _NUMBER.match(text, i)) is not None:
            out.append(("number", m.group(), i))
            i = m.end()
        else:
            out.append(("punct", c, i))
            i += 1
    return out


def _is(token, text: str) -> bool:
    return token is not None and token[0] == "punct" and token[1] == text


def check(cypher) -> str:
    """The statement to run, or :class:`Refused` naming what isn't allowed: more
    than one statement, a write or admin clause, CALL, a plugin function, query
    options."""
    if not isinstance(cypher, str) or not cypher.strip():
        raise Refused("Give the query as Cypher text.")
    if len(cypher) > MAX_QUERY_CHARS:
        raise Refused(f"The query is over {MAX_QUERY_CHARS:,} characters.")
    toks = _tokens(cypher)
    semis = [t for t in toks if _is(t, ";")]
    if semis and (len(semis) > 1 or semis[-1] is not toks[-1]):
        raise Refused("One statement at a time: a ';' may only end the query.")
    statement = cypher
    if semis:
        at = semis[-1][2]
        statement = cypher[:at] + cypher[at + 1:]
        toks = toks[:-1]
    if not toks:
        raise Refused("The query is empty.")

    words, calls = [], []
    for idx, (kind, text, _) in enumerate(toks):
        if kind != "word":
            continue
        prev = toks[idx - 1] if idx else None
        nxt = toks[idx + 1] if idx + 1 < len(toks) else None
        if _is(prev, ".") and idx >= 2 and (toks[idx - 2][0] in ("word", "name", "param")
                                            or toks[idx - 2][1] in (")", "]", "}", "{", ",")):
            continue  # a property (n.start, list[0].start, n {.start}) or a namespace's member; not "1. SET"
        if text.upper() in FORBIDDEN:
            map_key = _is(nxt, ":") and (_is(prev, "{") or _is(prev, ","))
            alias = prev is not None and prev[0] == "word" and prev[1].upper() == "AS"
            if not (map_key or alias) and text.upper() not in words:
                words.append(text.upper())
        # A dotted name called as a function: only Cypher's own.
        if _is(nxt, "."):
            parts, j = [text], idx
            while _is(toks[j + 1] if j + 1 < len(toks) else None, ".") and j + 2 < len(toks) \
                    and toks[j + 2][0] == "word":
                parts.append(toks[j + 2][1])
                j += 2
            if _is(toks[j + 1] if j + 1 < len(toks) else None, "(") and parts[0].lower() not in BUILTIN_NAMESPACES:
                name = ".".join(parts)
                if name not in calls:
                    calls.append(name)
    if words or calls:
        why = []
        if words:
            why.append(", ".join(words))
        if calls:
            why.append("procedures and plugin functions (" + ", ".join(f"{c}()" for c in calls) + ")")
        hint = ""
        if "CALL" in words:
            hint = " For a subquery, use EXISTS { }, COUNT { } or COLLECT { }."
        raise Refused(f"Not allowed in a graph query, which only reads: {'; '.join(why)}.{hint}")
    return statement


def check_params(params) -> dict:
    """The caller's parameters: named like Cypher identifiers, plain JSON, not
    ``org`` or ``ns`` (those are set for them)."""
    if params is None:
        return {}
    if not isinstance(params, dict):
        raise Refused("params must be an object: {name: value}.")
    for name in params:
        if not isinstance(name, str) or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name):
            raise Refused(f"Parameter name {name!r} isn't a plain identifier.")
        if name in ("org", "ns"):
            raise Refused(f"${name} is set for you (your workspace and the mirror's namespace): don't pass it.")
    try:
        size = len(json.dumps(params, allow_nan=False))
    except (TypeError, ValueError):
        raise Refused("Parameters must be plain JSON values.") from None
    if size > MAX_PARAM_BYTES:
        raise Refused(f"The parameters are over {MAX_PARAM_BYTES // 1000} KB.")
    return dict(params)


def row_limit(limit) -> int:
    if limit is None:
        return MAX_ROWS
    try:
        return max(1, min(int(limit), HARD_MAX_ROWS))
    except (TypeError, ValueError):
        raise Refused("limit must be a whole number.") from None


# ---- rows: what comes back --------------------------------------------------------------

def serialise(value, include_props: bool = False, scope: tuple[str, frozenset] | None = None):
    """A value from Neo4j as plain JSON. A node is {label, id, its plain
    properties} (with ``props``, the whole record as stored, nested values
    and all, only when ``include_props``); a relationship {type, id, from, to}
    (its ends' ids, when the ends are in the result); a path {nodes,
    relationships}; dates and durations ISO strings. With ``scope`` (namespace,
    orgs), a node from anywhere else is given as {redacted: true}."""
    from neo4j.graph import Node, Path, Relationship
    from neo4j.spatial import Point
    from neo4j.time import Date, DateTime, Duration, Time

    def node(n) -> dict:
        props = dict(n.items())
        if scope is not None and props.get("org") is not None and (
                props.get("ns") != scope[0] or props.get("org") not in scope[1]):
            return {"redacted": True}
        label = props.get("label") or next((x for x in sorted(n.labels) if x != "Node"), None)
        out = {"label": label, "id": props.get("id")}
        for key in sorted(props):
            if key not in _INTERNAL and key not in ("id", "label"):
                out[key] = conv(props[key])
        if include_props and isinstance(props.get("props"), str):
            out["props"] = _json(props["props"])
        return out

    def rel(r) -> dict:
        props = dict(r.items())
        ends = [(x.get("id") if x is not None else None) for x in (r.start_node, r.end_node)]
        out = {"type": r.type, "id": props.get("id"), "from": ends[0], "to": ends[1]}
        if include_props and isinstance(props.get("props"), str):
            out["props"] = _json(props["props"])
        return out

    def conv(v):
        if v is None or isinstance(v, (bool, int, str)):
            return v
        if isinstance(v, float):
            return v if math.isfinite(v) else None
        if isinstance(v, Node):
            return node(v)
        if isinstance(v, Relationship):
            return rel(v)
        if isinstance(v, Path):
            return {"nodes": [node(x) for x in v.nodes], "relationships": [rel(x) for x in v.relationships]}
        if isinstance(v, (Date, DateTime, Time, Duration)):
            return v.iso_format()
        if isinstance(v, (_dt.date, _dt.datetime, _dt.time)):
            return v.isoformat()
        if isinstance(v, _dt.timedelta):
            return v.total_seconds()
        if isinstance(v, Point):
            return {"srid": v.srid, "coordinates": [conv(c) for c in v]}
        if isinstance(v, dict):
            return {str(k): conv(x) for k, x in v.items()}
        if isinstance(v, (list, tuple)):
            return [conv(x) for x in v]
        if isinstance(v, (bytes, bytearray)):
            return f"<{len(v)} bytes>"
        return str(v)

    return conv(value)


def _json(text: str):
    try:
        return json.loads(text)
    except ValueError:
        return text


def collect(records, limit: int, max_bytes: int, convert) -> tuple[list[dict], str | None]:
    """At most ``limit`` rows and about ``max_bytes`` of them; and why it stopped
    early ("rows" or "bytes"), or None when every row is there."""
    rows: list[dict] = []
    size = 2
    for record in records:
        if len(rows) >= limit:
            return rows, "rows"
        row = {key: convert(value) for key, value in record.items()}
        n = len(json.dumps(row, ensure_ascii=False, default=str)) + 1
        if size + n > max_bytes:
            return rows, "bytes"
        rows.append(row)
        size += n
    return rows, None


def _truncation_note(why: str | None, shown: int, limit: int, max_bytes: int) -> str | None:
    if why == "rows":
        return (f"Only the first {shown:,} rows are shown (limit {limit:,}; at most {HARD_MAX_ROWS:,}): there are "
                "more. Aggregate, filter, or ORDER BY and page with SKIP / LIMIT.")
    if why == "bytes":
        return (f"Cut off after {shown:,} rows, at about {max_bytes // 1000:,} KB: return fewer or smaller columns "
                "(n.name rather than n), or aggregate.")
    return None


# ---- the mirror: where, how current, and nothing else there --------------------------------

def mirror_of(store):
    """The store's Neo4j mirror, or :class:`Unavailable`. Graph queries run on the
    mirror only (never on Neo4j as the primary graph, which holds every
    workspace)."""
    mirror = getattr(store, "mirror", None)
    if mirror is None:
        raise Unavailable("Graph queries run on the Neo4j mirror, and it isn't on here "
                          "(MAINTENANCE_GRAPH_MIRROR=neo4j).")
    return mirror


def _check_scope(mirror, org: str) -> None:
    if not mirror.in_scope(org):
        raise Refused(f"This workspace ({org}) isn't copied to Neo4j: add its id to MAINTENANCE_GRAPH_MIRROR_ORGS "
                      "(and restart), and it's copied within the hour.")


def _session(conn):
    from neo4j import READ_ACCESS

    return conn.driver.session(database=conn.database, default_access_mode=READ_ACCESS,
                               bookmark_manager=conn.driver.execute_query_bookmark_manager)


# Where the mirror is for the workspace, and whether anything outside the
# caller's mirrored workspaces is in the database at all (refused if so).
_FRESHNESS = """
OPTIONAL MATCH (m:MaintenanceMirror {ns: $ns, org: $org})
WITH m, EXISTS { MATCH (n) WHERE NOT coalesce(n.ns = $ns AND n.org IN $orgs, false) } AS foreign
RETURN m.applied AS applied, m.version AS version, m.synced AS synced, foreign
"""


def freshness(row: dict, mirror, store, org: str) -> dict:
    """How current the mirror is for the workspace: the last event it holds and
    when it was synced, against the workspace's latest change in the log. When
    behind, a note says so, and a sync is asked for (the query still runs)."""
    latest = int(store.org_mark(org))
    recent = store.log.recent(org, 1) if hasattr(store, "log") else []
    latest_at = recent[0].get("at") if recent else None
    applied, version = row.get("applied"), row.get("version")
    out = {"mirror_event": applied, "mirror_synced_at": row.get("synced"), "latest_event": latest,
           "latest_event_at": latest_at}
    if applied is None:
        out.update(up_to_date=False, note="This workspace hasn't been copied to Neo4j yet: the query ran on an "
                                          "empty graph. A copy has been asked for; try again in a minute.")
    elif version != mirror.version:
        out.update(up_to_date=False, note=f"The mirror holds this workspace at projection version {version} "
                                          f"(this deployment projects {mirror.version}): it's being copied again.")
    elif applied < latest:
        out.update(up_to_date=False, note=f"The mirror is behind this workspace: it holds changes up to event "
                                          f"{applied} (synced {row.get('synced')}), and the latest change is event "
                                          f"{latest} ({latest_at}). The query ran on the copy as it is; a sync has "
                                          "been asked for.")
    else:
        out["up_to_date"] = True
    if not out["up_to_date"]:
        try:
            mirror.notify(org)
        except Exception:  # noqa: BLE001 - asking for a sync never fails the query
            pass
    return out


def _orgs(mirror, org: str, readable) -> list[str]:
    """The workspaces the database may hold for this caller: those mirrored that
    they may read (their own and their teams'), the current one included."""
    return sorted((set(readable or ()) | {org}) & set(mirror.scope))


def _max_estimate(plan: dict | None) -> float:
    best, stack = 0.0, [plan] if plan else []
    while stack:
        p = stack.pop()
        est = (p.get("args") or {}).get("EstimatedRows")
        if isinstance(est, (int, float)):
            best = max(best, float(est))
        stack.extend(p.get("children") or [])
    return best


def _neo4j_trouble(err) -> GraphQueryError:
    from neo4j.exceptions import Neo4jError

    if isinstance(err, Neo4jError):
        code = getattr(err, "code", "") or ""
        message = getattr(err, "message", None) or str(err)
        if "TransactionTimedOut" in code or "Terminated" in code:
            return Refused(f"The query ran past the {config.GRAPH_QUERY_TIMEOUT_S:g} s limit and was stopped: "
                           "narrow it (start from an id, bound variable-length paths).")
        if "AccessMode" in code or "Forbidden" in code or "Security" in code:
            return Refused(f"Neo4j refused the query: it only reads here. ({message})")
        if code.startswith("Neo.ClientError"):
            return Refused(f"Neo4j refused the query: {message}")
        return Unavailable(f"Neo4j couldn't answer the query just now: {message}")
    return Unavailable(f"Neo4j can't be reached just now ({type(err).__name__}); try again shortly.")


def run_query(store, org: str, cypher, params=None, limit=None, include_props: bool = False,
              readable=()) -> dict:
    """Run the caller's Cypher on the mirror, for workspace ``org`` (``$org``).
    ``readable``: the workspaces the caller may read (theirs and their teams'):
    the database must hold nothing else. See the module docstring."""
    from neo4j import Query
    from neo4j.exceptions import DriverError, Neo4jError

    statement = check(cypher)
    values = check_params(params)
    limit = row_limit(limit)
    mirror = mirror_of(store)
    _check_scope(mirror, org)
    orgs = _orgs(mirror, org, readable)
    values.update(org=org, ns=mirror.ns)
    timeout = config.GRAPH_QUERY_TIMEOUT_S
    max_bytes = config.GRAPH_QUERY_MAX_BYTES
    try:
        with _session(mirror.conn) as session:
            row = session.run(Query(_FRESHNESS, timeout=timeout), {"ns": mirror.ns, "org": org, "orgs": orgs}).data()
            row = row[0] if row else {}
            if row.get("foreign"):
                raise Refused("The Neo4j database holds data outside your mirrored workspaces (another namespace or "
                              "workspace), and nothing stops a query reaching it: graph queries are off until it's "
                              "removed (python -m backend.scripts.maintenance_graph rebuild --apply --prune).")
            fresh = freshness(row, mirror, store, org)
            summary = session.run(Query("EXPLAIN " + statement, timeout=timeout), values).consume()
            if summary.query_type not in (None, "r"):
                raise Refused("Only reads: Neo4j's plan for this query would write.")
            estimated = _max_estimate(summary.plan)
            cap = config.GRAPH_QUERY_MAX_ESTIMATED_ROWS
            if estimated > cap:
                raise Refused(f"Neo4j's plan estimates about {estimated:,.0f} rows at one step, over the {cap:,} "
                              "allowed: narrow it (start from an id or a name, bound variable-length paths, avoid "
                              "MATCHing two unconnected patterns).")
            result = session.run(Query(statement, timeout=timeout), values)
            columns = list(result.keys())
            rows, cut = collect(result, limit, max_bytes,
                                lambda v: serialise(v, include_props, (mirror.ns, frozenset(orgs))))
    except GraphQueryError:
        raise
    except (Neo4jError, DriverError, OSError) as err:
        raise _neo4j_trouble(err) from None
    out = {"columns": columns, "rows": rows, "row_count": len(rows), "truncated": cut is not None,
           "estimated_rows": round(estimated), "freshness": fresh}
    note = _truncation_note(cut, len(rows), limit, max_bytes)
    if note:
        out["note"] = note
    if not any(t[0] == "param" and t[1] == "$org" for t in _tokens(statement)):
        out["hint"] = "This query doesn't match on org: $org. Match on {ns: $ns, org: $org} to stay in this workspace."
    return out


# ---- the schema, and examples that run on it -------------------------------------------------

_SCHEMA = """
CALL () {
  MATCH (n:Node {ns: $ns, org: $org}) WHERE n.label IS NOT NULL
  WITH n.label AS label, count(*) AS count ORDER BY label
  RETURN collect({label: label, count: count}) AS labels
}
CALL () {
  MATCH (n:Node {ns: $ns, org: $org}) WHERE n.label IS NOT NULL
  UNWIND [k IN keys(n) WHERE NOT k IN $internal] AS key
  WITH n.label AS label, key, valueType(n[key]) AS type, count(*) AS count
  RETURN collect({label: label, key: key, type: type, count: count}) AS properties
}
CALL () {
  MATCH (a:Node {ns: $ns, org: $org})-[r]->(b:Node)
  WITH type(r) AS type, a.label AS from, b.label AS to, count(*) AS count
  RETURN collect({type: type, from: from, to: to, count: count}) AS relationships
}
RETURN labels, properties, relationships
"""

CONVENTIONS = [
    "Every record is (:Node:<Label> {ns, org, id, label, ...}). Match on {ns: $ns, org: $org} (both always "
    "passed) and the label: MATCH (p:Position {ns: $ns, org: $org}).",
    "Plain values (text, numbers, true/false, lists of one kind) are properties on the node. Nested values "
    "(a work order's checklist and status_history, stock moves, nameplates, attributes) are only in the record "
    "as stored: return the node with include_props true to read them.",
    "Dates are ISO text ('2026-10-15'; a rough one '2022' or '2022-03'), so compare them as text: "
    "f.to >= '2023-10-15', or toString(date() - duration({years: 3})).",
    "Retired or struck out: coalesce(x.retired, false), coalesce(f.voided, false). A fitment with to IS NULL "
    "is the item fitted now; end_reason 'failure' / 'planned' / 'other' says why it came out.",
    "Open work: w.status IN ['open', 'planned', 'in_progress', 'waiting'].",
    "Positions: (child)-[:PART_OF]->(parent), the functional tree; (p)-[:LOCATED_AT]->(location) where set "
    "(positions inside inherit it). Locations and item classes nest by PART_OF too.",
    "Items: (item)-[:IN]->(f:Fitment)-[:AT]->(position); (item)-[:IN]->(pl:Placement)-[:AT]->(location) while "
    "not fitted (pl.to IS NULL: placed there now). (item)-[:CLASSED_AS]->(ItemClass), else its part's: "
    "(item)-[:OF_PART]->(Part)-[:CLASSED_AS]->(ItemClass).",
    "Connections: (i:Interface)-[:FROM]->(upstream), (i)-[:TO]->(downstream); live unless i.retired. "
    "Redundancy: (position)-[:IN_GROUP]->(g:RedundancyGroup {k}); k of the members are needed.",
    "Tasks, work orders and measurement points: (x)-[:ON]->(position | item | location); (w)-[:FOR]->(task); "
    "(task)-[:MITIGATES]->(FailureMode)<-[:CAN_FAIL_AS]-(position).",
    "Parts: (listing:PartListing)-[:LISTED_AT]->(position), (listing)-[:LISTS]->(part); (s:Stock)-[:OF]->(part), "
    "(s)-[:AT]->(location); (part)-[:SUPERSEDED_BY]->(part); (part)-[:INTERCHANGEABLE]->(part).",
    "Product structure: (assembly:Part)-[r:CONTAINS]->(component:Part), one line per pair, its qty (how many in one "
    "assembly) and ref in r.props (JSON text); no loops. part.level is its indenture level. Whole BOM below a part: "
    "(top)-[:CONTAINS]->{1,}(x); totals multiply along the path, so take them from maintenance_get kind "
    "part_structure.",
    "Conditions: (x)-[r:EXPOSED_TO]->(c:Condition) where a location, position, item or connection is exposed to "
    "c, (x)-[:NOT_EXPOSED_TO]->(c) where one inherited from above is excluded; conditions nest by PART_OF; skip "
    "c.retired. These are only what's set on x itself: what x inherits (from the locations around it, the "
    "positions above it, a fitted item's position) comes from maintenance_get kind conditions. The value and note "
    "are in the relationship's stored record (r.props, as JSON text).",
    "Variable-length paths: quantified patterns, e.g. (l:Location)-[:PART_OF]->{0,}(root); for the shortest "
    "route, MATCH p = SHORTEST 1 (a)(...)+(b).",
    "Not allowed (reads only): CREATE, MERGE, SET, DELETE, REMOVE, DROP, LOAD CSV, FOREACH, CALL (use EXISTS, "
    "COUNT or COLLECT { } subqueries), procedures and plugin functions (apoc., db., dbms.), USE, SHOW, admin "
    "commands, query options (CYPHER, EXPLAIN, PROFILE), and more than one statement.",
]

# Each runs on the mirror as it is (the tests run every one on a mirrored plant).
# params: what to fill in ($org and $ns are passed for you).
EXAMPLES = [
    {"name": "downstream",
     "question": "What loses supply if this position fails: everything downstream through live connections, "
                 "nearest first.",
     "params": {"id": "<a position id>"},
     "cypher": """MATCH (s:Position {ns: $ns, org: $org, id: $id})
MATCH p = SHORTEST 1 (s)((a)<-[:FROM]-(i:Interface WHERE NOT coalesce(i.retired, false))-[:TO]->(b)){1,}(t:Position)
WHERE t <> s AND NOT coalesce(t.retired, false)
RETURN t.id AS id, t.name AS name, length(p) / 2 AS hops
ORDER BY hops, name"""},
    {"name": "upstream",
     "question": "What feeds this position, directly or further up, through live connections.",
     "params": {"id": "<a position id>"},
     "cypher": """MATCH (t:Position {ns: $ns, org: $org, id: $id})
MATCH p = SHORTEST 1 (s:Position)((a)<-[:FROM]-(i:Interface WHERE NOT coalesce(i.retired, false))-[:TO]->(b)){1,}(t)
WHERE s <> t
RETURN s.id AS id, s.name AS name, length(p) / 2 AS hops
ORDER BY hops, name"""},
    {"name": "class_in_location",
     "question": "Items of an item class (or a class inside it; their own class, else their part's) fitted now "
                 "at positions in a location or a location inside it (the location set on the position or "
                 "the nearest position above it).",
     "params": {"class_id": "<an item class id>", "location_id": "<a location id>"},
     "cypher": """MATCH (c:ItemClass {ns: $ns, org: $org, id: $class_id})
MATCH (root:Location {ns: $ns, org: $org, id: $location_id})
MATCH (it:Item {ns: $ns, org: $org})-[:IN]->(f:Fitment)-[:AT]->(p:Position)
WHERE f.to IS NULL AND NOT coalesce(f.voided, false) AND NOT coalesce(p.retired, false)
OPTIONAL MATCH (it)-[:CLASSED_AS]->(own:ItemClass)
OPTIONAL MATCH (it)-[:OF_PART]->(:Part)-[:CLASSED_AS]->(byPart:ItemClass)
WITH c, root, it, p, coalesce(own, byPart) AS cls
WHERE cls IS NOT NULL AND EXISTS { (cls)-[:PART_OF]->{0,}(c) }
MATCH path = (p)-[:PART_OF]->{0,}(:Position)-[:LOCATED_AT]->(at:Location)
WITH root, it, p, at ORDER BY length(path)
WITH root, it, p, head(collect(at)) AS at
WHERE EXISTS { (at)-[:PART_OF]->{0,}(root) }
RETURN it.id AS item_id, it.name AS item, p.name AS position, at.name AS location
ORDER BY location, position"""},
    {"name": "open_work_without_redundancy",
     "question": "Positions with open work and no redundancy to carry them (in no live group with a spare "
                 "member).",
     "params": {},
     "cypher": """MATCH (p:Position {ns: $ns, org: $org})<-[:ON]-(w:WorkOrder)
WHERE w.status IN ['open', 'planned', 'in_progress', 'waiting'] AND NOT coalesce(p.retired, false)
  AND NOT EXISTS {
    MATCH (p)-[:IN_GROUP]->(g:RedundancyGroup)
    WHERE NOT coalesce(g.retired, false) AND COUNT { (g)<-[:IN_GROUP]-(:Position) } - 1 >= g.k
  }
RETURN p.id AS id, p.name AS position, collect(w.number) AS open_work_orders
ORDER BY position"""},
    {"name": "failures_by_class",
     "question": "Failures in the last 3 years by position class, from the fitment history.",
     "params": {},
     "cypher": """MATCH (p:Position {ns: $ns, org: $org})<-[:AT]-(f:Fitment)
WHERE f.end_reason = 'failure' AND NOT coalesce(f.voided, false)
  AND f.to >= toString(date() - duration({years: 3}))
RETURN CASE WHEN p.position_class = '' THEN '(no class)' ELSE p.position_class END AS position_class,
       count(f) AS failures, count(DISTINCT p) AS positions
ORDER BY failures DESC, position_class"""},
    {"name": "critical_spares_short",
     "question": "Critical spares below their position's minimum, counting the part, what supersedes it and "
                 "their interchangeable alternatives in every store.",
     "params": {},
     "cypher": """MATCH (pos:Position {ns: $ns, org: $org})<-[:LISTED_AT]-(l:PartListing)-[:LISTS]->(pt:Part)
WHERE l.critical = true AND NOT coalesce(l.removed, false) AND NOT coalesce(pos.retired, false)
WITH pos, l, pt, COLLECT {
  MATCH (pt)-[:SUPERSEDED_BY]->{0,}(s:Part)
  OPTIONAL MATCH (s)-[:INTERCHANGEABLE]->(alt:Part)
  UNWIND [s, alt] AS u
  WITH DISTINCT u WHERE u IS NOT NULL
  OPTIONAL MATCH (st:Stock)-[:OF]->(u)
  RETURN coalesce(st.quantity, 0.0)
} AS quantities
WITH pos, l, pt, reduce(total = 0.0, q IN quantities | total + q) AS usable
WHERE usable < coalesce(l.min_on_hand, 0)
RETURN pos.name AS position, pt.part_number AS part, l.min_on_hand AS keep, usable
ORDER BY position, part"""},
    {"name": "unmitigated_failure_modes",
     "question": "Failure modes of positions in the plant that no live task mitigates (gaps in the plan).",
     "params": {},
     "cypher": """MATCH (p:Position {ns: $ns, org: $org})-[:CAN_FAIL_AS]->(fm:FailureMode)
WHERE NOT coalesce(p.retired, false) AND fm.merged_into IS NULL AND NOT coalesce(fm.retired, false)
  AND NOT EXISTS { (fm)<-[:MITIGATES]-(t:Task) WHERE NOT coalesce(t.retired, false) }
RETURN p.name AS position, fm.text AS failure_mode
ORDER BY position, failure_mode"""},
    {"name": "spares_placed",
     "question": "Items not fitted anywhere, by where they're placed now (spares in stores, items away for "
                 "repair).",
     "params": {},
     "cypher": """MATCH (it:Item {ns: $ns, org: $org})-[:IN]->(pl:Placement)-[:AT]->(l:Location)
WHERE pl.to IS NULL
  AND NOT EXISTS { (it)-[:IN]->(f:Fitment) WHERE f.to IS NULL AND NOT coalesce(f.voided, false) }
RETURN l.name AS location, collect(it.name) AS items
ORDER BY location"""},
    {"name": "item_history",
     "question": "Every position an item has been fitted to, in order, and why each fitment ended.",
     "params": {"item_id": "<an item id>"},
     "cypher": """MATCH (it:Item {ns: $ns, org: $org, id: $item_id})-[:IN]->(f:Fitment)-[:AT]->(p:Position)
WHERE NOT coalesce(f.voided, false)
RETURN p.name AS position, f.from AS fitted, f.to AS removed, f.end_reason AS why
ORDER BY fitted"""},
    {"name": "subtree_fitted",
     "question": "The positions inside a position (the whole branch), how deep, and what's fitted to each now.",
     "params": {"id": "<a position id>"},
     "cypher": """MATCH (root:Position {ns: $ns, org: $org, id: $id})
MATCH path = (p:Position)-[:PART_OF]->{0,}(root)
WHERE NOT coalesce(p.retired, false)
OPTIONAL MATCH (it:Item)-[:IN]->(f:Fitment)-[:AT]->(p)
WHERE f.to IS NULL AND NOT coalesce(f.voided, false)
RETURN p.name AS position, length(path) AS depth, it.name AS fitted
ORDER BY depth, position"""},
    {"name": "failures_by_manufacturer",
     "question": "Items and their failures by manufacturer (the register's, else the item's own text).",
     "params": {},
     "cypher": """MATCH (it:Item {ns: $ns, org: $org})-[:IN]->(f:Fitment)
WHERE NOT coalesce(f.voided, false)
OPTIONAL MATCH (it)-[:MADE_BY]->(mf:Manufacturer)
WITH CASE WHEN mf IS NOT NULL THEN mf.name WHEN it.manufacturer <> '' THEN it.manufacturer
          ELSE '(unknown)' END AS manufacturer, it, f
RETURN manufacturer, count(DISTINCT it) AS items,
       sum(CASE WHEN f.end_reason = 'failure' THEN 1 ELSE 0 END) AS failures
ORDER BY failures DESC, manufacturer"""},
]


def limits() -> dict:
    return {"rows_default": MAX_ROWS, "rows_max": HARD_MAX_ROWS, "bytes_max": config.GRAPH_QUERY_MAX_BYTES,
            "timeout_seconds": config.GRAPH_QUERY_TIMEOUT_S,
            "plan_estimated_rows_max": config.GRAPH_QUERY_MAX_ESTIMATED_ROWS}


def _type_name(t) -> str:
    return (t or "").replace(" NOT NULL", "")


def graph_schema(store, org: str, readable=()) -> dict:
    """The workspace's graph as the mirror holds it: each label with its count and
    property keys (their types and how many nodes have them), each relationship
    type with its count and the labels it connects; the conventions, worked
    examples and limits; and how current the mirror is."""
    from neo4j import Query
    from neo4j.exceptions import DriverError, Neo4jError

    mirror = mirror_of(store)
    _check_scope(mirror, org)
    orgs = _orgs(mirror, org, readable)
    params = {"ns": mirror.ns, "org": org}
    try:
        with _session(mirror.conn) as session:
            row = session.run(Query(_FRESHNESS, timeout=config.GRAPH_QUERY_TIMEOUT_S), {**params, "orgs": orgs}).data()
            fresh = freshness(row[0] if row else {}, mirror, store, org)
            got = session.run(Query(_SCHEMA, timeout=config.GRAPH_QUERY_TIMEOUT_S),
                              {**params, "internal": sorted(_INTERNAL | {"id", "label"})}).data()
    except (Neo4jError, DriverError, OSError) as err:
        raise _neo4j_trouble(err) from None
    got = got[0] if got else {"labels": [], "properties": [], "relationships": []}
    props: dict[str, dict] = {}
    for p in got["properties"]:
        entry = props.setdefault(p["label"], {}).setdefault(p["key"], {"types": [], "count": 0})
        entry["count"] += p["count"]
        if _type_name(p["type"]) not in entry["types"]:
            entry["types"].append(_type_name(p["type"]))
    nodes = [{"label": x["label"], "count": x["count"],
              "properties": {k: {"type": " | ".join(sorted(v["types"])), "count": v["count"]}
                             for k, v in sorted(props.get(x["label"], {}).items())}}
             for x in sorted(got["labels"], key=lambda x: x["label"])]
    rels: dict[str, dict] = {}
    for r in got["relationships"]:
        entry = rels.setdefault(r["type"], {"type": r["type"], "count": 0, "connects": []})
        entry["count"] += r["count"]
        entry["connects"].append({"from": r["from"], "to": r["to"], "count": r["count"]})
    for entry in rels.values():
        entry["connects"].sort(key=lambda c: (-c["count"], c["from"] or "", c["to"] or ""))
    return {"org": org, "namespace": mirror.ns,
            "every_node": {"labels": ":Node and its own label", "properties": "ns, org, id, label, and its plain "
                           "values; the whole record as stored in props (include_props)"},
            "nodes": nodes, "relationships": [rels[k] for k in sorted(rels)],
            "conventions": CONVENTIONS, "examples": EXAMPLES, "limits": limits(), "freshness": fresh}
