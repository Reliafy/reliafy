# The Reliafy Maintenance graph: SQLite and Neo4j

Every change in Reliafy Maintenance is an event in the log (MongoDB in a
deployment, the local SQLite file otherwise). The graph — positions,
locations, items, fitments, tasks, work orders and the edges between them — is
a projection of the log, and can always be rebuilt from it.

## Backends

| | Where the graph lives | Reads |
|---|---|---|
| **SQLite** (default) | In each process: in memory, replayed from the Mongo log at start (or in the local SQLite file) | Local: microseconds |
| **Neo4j mirror** | SQLite as above, plus a copy in Neo4j kept in step in the background | Requests read SQLite; graph queries may read Neo4j |
| **Neo4j** (primary) | One shared graph in Neo4j; no replay at start | Every read is a round trip to Neo4j |

Both backends implement the same methods (`backend/maintenance/store.py`
`GraphStore`, `backend/maintenance/neo4j_store.py` `Neo4jGraphStore`), and the
maintenance tests pass on both.

In Neo4j a node is `(:Node:<Label> {ns, org, id, label, props, ...})`: `props`
is the node's JSON (as SQLite keeps it, so the two compare equal), and its
plain values (`name`, `retired`, `to`, ...) are on the node too, for Cypher.
Edges are relationships of their type (`-[:PART_OF {id, props}]->`). `ns` is a
namespace, so one database can hold several graphs. Constraints and indexes on
`(ns, org, id)` and `(ns, org, label)` are made on first use. Needs Neo4j 5.26
or later (AuraDB is).

## Latency: why Neo4j isn't on the request path

The AuraDB Free instance is in Google Cloud asia-southeast1 (Singapore);
Cloud Run is in australia-southeast1 (Sydney). One query is about 370 ms from
Brisbane and 150–200 ms from Sydney, and a maintenance page makes dozens of
reads. So production uses the **mirror**: requests read and write SQLite as
before, and Neo4j is only written in the background and read by graph queries
that are switched on.

## Mirror mode (production now)

```
MAINTENANCE_GRAPH_MIRROR=neo4j
MAINTENANCE_GRAPH_MIRROR_ORGS=<org id>[,<org id>...]   # the workspaces copied; empty: none
NEO4J_URI=neo4j+s://<id>.databases.neo4j.io
NEO4J_USERNAME=<user>
NEO4J_PASSWORD=<password>          # Secret Manager
NEO4J_DATABASE=<database>          # optional (the user's default)
```

- **Only the workspaces in `MAINTENANCE_GRAPH_MIRROR_ORGS` are copied** (empty,
  the default: none). Every other one is passed over by the background sync,
  the hourly catch-up and the command, even when asked for by name, and the
  hourly catch-up removes any the mirror holds (copied before the list
  narrowed). An org id is a user's uid (their personal workspace) or
  `team:<team id>`; `status` (below) lists them with their sizes, and
  `status --email <address>` marks the ones that address owns or is in a team
  of. While Neo4j has no access control (AuraDB Free), this is what keeps graph
  queries in Cypher to the owner's own data (below).
- The SQLite graph records the last event that wrote each node and edge.
  For each workspace, Neo4j holds the position its copy is up to date with
  (`(:MaintenanceMirror {ns, org, applied, version})`). A sync sends what
  changed since then and the new position in **one statement** (one round
  trip); more than 2,000 rows go as several statements in one transaction.
- The statement writes only if the position is still the one it read (the
  bookkeeping node is locked first): syncing is idempotent and resumable, and
  several Cloud Run instances can sync at once — one writes, the others find it
  done.
- A copy at another projection version (`PROJECTION_VERSION`), or older than the
  SQLite graph's change records go back, is copied whole.
- **When it syncs:** after each write this process makes, a background thread
  is woken (a queue of one: a burst of writes is one sync; the request never
  waits); at start-up (in the background); and in the content job each hour it
  runs (10:05–17:05 Brisbane). Cloud Run gives a process little CPU between
  requests, so a background sync may finish on the next request or the next
  hourly run.
- **Keep-alive:** AuraDB Free pauses when idle. The hourly step (a ping and the
  catch-up) keeps it awake. Neo4j unreachable is logged and reported in the
  job's result; it never fails the job or a request.

To turn it on in Cloud Run (the password as a secret; the rest as plain
settings):

```
printf '%s' "<password>" | gcloud secrets create reliafy-neo4j-password --project "$PROJECT" --data-file=-
gcloud secrets add-iam-policy-binding reliafy-neo4j-password --project "$PROJECT" \
  --member "serviceAccount:$WEB_SA" --role roles/secretmanager.secretAccessor
gcloud run services update reliafy --project "$PROJECT" --region "$REGION" \
  --update-secrets "NEO4J_PASSWORD=reliafy-neo4j-password:latest" \
  --update-env-vars "^;^NEO4J_URI=neo4j+s://<id>.databases.neo4j.io;NEO4J_USERNAME=<user>;NEO4J_DATABASE=<database>;MAINTENANCE_GRAPH_MIRROR=neo4j;MAINTENANCE_GRAPH_MIRROR_ORGS=<org id>"
```

Then `rebuild --apply` and `verify` (below) once, from a machine with the
production environment. Turning it off is `--remove-env-vars
MAINTENANCE_GRAPH_MIRROR`.

Graph queries (`backend/maintenance/graph_query.py`) — `downstream` (what loses
supply if a position fails; used by Maintenance's impact), `location_rollup`
(positions and items in a location and the locations inside it) and
`class_members` (an item class's subtree and the items and parts in it) — run as
one Cypher round trip when `MAINTENANCE_GRAPH_QUERIES=neo4j` and the mirror is
up to date for the workspace (the query checks), else in Python. Both answer
the same; the tests hold them to it. Off by default: in Python they're faster
than a round trip to Singapore.

## Commands

```
python -m backend.scripts.maintenance_graph ping       # one round trip, timed
python -m backend.scripts.maintenance_graph status [--email EMAIL]   # every workspace's size, which are mirrored, how far behind
python -m backend.scripts.maintenance_graph sync [--org ORG]
python -m backend.scripts.maintenance_graph rebuild [--org ORG]           # dry run: what would be copied
python -m backend.scripts.maintenance_graph rebuild [--org ORG] --apply [--prune]
python -m backend.scripts.maintenance_graph verify [--org ORG] [--target mirror|graph]
```

Each replays the log (Mongo when `MONGODB_URI` is set, else the local file)
into a fresh in-memory SQLite graph first. `rebuild --apply` copies each
workspace in scope whole, in one transaction each; `--prune` also removes
workspaces Neo4j holds that the log doesn't, or that are outside
`MAINTENANCE_GRAPH_MIRROR_ORGS`. `verify` compares the replay with Neo4j node
for node and exits 1 on any difference: the check before trusting a copy.

## Owner-only graph queries in Cypher (#423)

An agent (or the owner, through the API) can run its own read-only Cypher on the
mirror: questions across the structures that no other tool answers in one call
(what's downstream of a position; items of a class fitted in an area; open work
with no redundancy; failures by class; critical spares short).

**Owner-only, for now.** The mirror lives on the existing AuraDB **Free**
instance, which has no access control: a query can read whatever the database
holds. So:

- Only the addresses in `GRAPH_QUERY_EMAILS` may run graph queries, and only
  with Maintenance (`backend/maintenance/access.py` `graph_query_allowed`, the
  one check every way in uses; operator status alone is never enough). Empty,
  the default, is off for everyone, the owner included.
- Only the owner's workspaces are mirrored (`MAINTENANCE_GRAPH_MIRROR_ORGS`,
  above), so there is nothing else in the database to reach. Before every query
  the database is checked to hold nothing outside the caller's mirrored
  workspaces (their own and their teams', in the list); if it does, queries are
  refused until it's pruned (`rebuild --apply --prune`, or the hourly job). A
  query can only be run for a workspace in the list.
- They run on the mirror only, never on Neo4j as the primary graph
  (`MAINTENANCE_GRAPH=neo4j`, which holds every workspace): there they're
  unavailable.
- For everyone else the tools and routes don't exist: MCP leaves them out of
  `tools/list` (and the guide's `graph` topic out of `maintenance_guide`'s
  choices) and answers a call with "Unknown tool"; the REST routes answer 404.

**Settings** (as well as the mirror's, above):

```
GRAPH_QUERY_EMAILS=<owner's address>             # empty (default): off for everyone
MAINTENANCE_GRAPH_MIRROR_ORGS=<owner's org id>   # empty (default): nothing mirrored
GRAPH_QUERY_TIMEOUT_S=10                         # transaction timeout
GRAPH_QUERY_MAX_ESTIMATED_ROWS=1000000           # refuse plans bigger than this at any step
GRAPH_QUERY_MAX_BYTES=1000000                    # rows returned, about
```

To find the owner's org id: `python -m backend.scripts.maintenance_graph status
--email <address>` from a machine with the production environment (it lists
each workspace in the log with its nodes, edges and events, marking that
address's), or set `GRAPH_QUERY_EMAILS` first and call the schema: a workspace
that isn't mirrored is refused with its id.

**The surface** (`backend/maintenance/graph_cypher.py`):

| | MCP (read tools, heavy slot, usage logged by name) | REST |
|---|---|---|
| Schema | `maintenance_graph_schema()` | `GET /api/maintenance/graph/schema` |
| Query | `maintenance_graph_query(cypher, params?, limit?, include_props?)` | `POST /api/maintenance/graph/query` `{cypher, params?, limit?, include_props?}` |

The query runs for the caller's workspace: over MCP their personal one, over
REST the active one (`X-Workspace-Id`). `$org` (that workspace) and `$ns` (the
mirror's namespace) are always passed, and queries should match on them:
`MATCH (p:Position {ns: $ns, org: $org})`. A query that doesn't mention `$org`
gets a hint saying so. `maintenance_guide` topic `graph` (allowed users only)
has the rules for agents.

**What gets through.** Three layers:

1. The query is read as tokens, with comments, strings and `quoted names` set
   aside (so none can hide a second statement or a clause), and refused, naming
   what isn't allowed, if it has more than one statement or any of: `CREATE`,
   `INSERT`, `MERGE`, `SET`, `DELETE`, `DETACH`, `NODETACH`, `REMOVE`, `DROP`,
   `LOAD` (CSV), `FOREACH`, `USE`, `SHOW`, `GRANT`, `DENY`, `REVOKE`, `ALTER`,
   `RENAME`, `START`, `STOP`, `TERMINATE`, `ENABLE`, `DEALLOCATE`,
   `REALLOCATE`, `DRYRUN`, `CALL` (procedures and subqueries alike: `EXISTS`,
   `COUNT` and `COLLECT { }` subqueries remain), query options (`CYPHER`,
   `EXPLAIN`, `PROFILE`), and any dotted function that isn't Cypher's own
   (`apoc.`, `db.`, `dbms.`, `gds.`...; `date.`, `datetime.`, `duration.`,
   `point.` and the like are allowed). The words are fine as properties
   (`t.start`), map keys and aliases (`AS start`).
2. It runs in a READ access-mode session: Neo4j refuses any write (tested).
3. `EXPLAIN` first: a plan that isn't read-only, or that estimates more rows
   than `GRAPH_QUERY_MAX_ESTIMATED_ROWS` at any step, is refused before it runs.

**Limits.** A `GRAPH_QUERY_TIMEOUT_S` (10 s) transaction timeout; 1,000 rows by
default (`limit` up to 5,000) and about `GRAPH_QUERY_MAX_BYTES` (1 MB), cut off
with a note; the query text at most 20,000 characters, its parameters 100 KB.

**What comes back.** `{columns, rows, row_count, truncated, note?,
estimated_rows, hint?, freshness}`. A node is `{label, id, ...its plain
properties}`, without the mirror's bookkeeping (`ns`, `org`, `_w`) or the
stored JSON (`props`, which `include_props` adds, parsed: nested values such as
checklists and stock moves live only there); a relationship `{type, id, from,
to}` (its ends' ids, when the ends are in the result); a path `{nodes,
relationships}`; dates and durations ISO strings.

**Freshness.** Every answer (and the schema) says how current the mirror is
for the workspace: the last event it holds and when it synced, against the
workspace's latest change in the log and its time. When it's behind (a change
made seconds ago), `freshness.note` says so, a sync is asked for, and the query
still runs on the copy as it is.

**The schema** lists, for the caller's workspace, each label with its count and
property keys (types, how many nodes have each), each relationship type with
its count and the labels it connects, the conventions (dates are ISO text,
open statuses, retired flags, how the structures link), the limits, and 11
worked examples, each tested on a mirrored plant:

| Example | Asks |
|---|---|
| `downstream` | What loses supply if a position fails, nearest first (`$id`) |
| `upstream` | What feeds a position (`$id`) |
| `class_in_location` | Items of an item class subtree fitted now in a location subtree (`$class_id`, `$location_id`) |
| `open_work_without_redundancy` | Positions with open work and no redundancy to carry them |
| `failures_by_class` | Failures in the last 3 years by position class, from fitments |
| `critical_spares_short` | Critical spares below their minimum (counting successors and alternatives) |
| `unmitigated_failure_modes` | Failure modes no live task mitigates |
| `spares_placed` | Items not fitted, by where they're placed now |
| `item_history` | Every position an item has been in, and why each fitment ended (`$item_id`) |
| `subtree_fitted` | A position's branch, depth, and what's fitted to each (`$id`) |
| `failures_by_manufacturer` | Items and failures by manufacturer |

For example, what loses supply if a position fails:

```
MATCH (s:Position {ns: $ns, org: $org, id: $id})
MATCH p = SHORTEST 1 (s)((a)<-[:FROM]-(i:Interface WHERE NOT coalesce(i.retired, false))-[:TO]->(b)){1,}(t:Position)
WHERE t <> s AND NOT coalesce(t.retired, false)
RETURN t.id AS id, t.name AS name, length(p) / 2 AS hops
ORDER BY hops, name
```

**Tests.** `backend/tests/test_maintenance_graph_cypher.py` (no Neo4j: who may,
the check, caps, serialisation, MCP and REST gating) runs in the suite.
`backend/tests/test_maintenance_graph_cypher_neo4j.py` runs only with
`NEO4J_TEST_URI` (like #417's), on its own (graph queries refuse while the
database holds anything else, so not beside the parity run): every example on
a mirrored plant and its answers against the app's, the three read-only layers,
the limits, freshness, and a workspace outside the list never reaching Neo4j
(and pruned when it does). Each test keeps to its own namespace and removes it.

**The Data model page** (`/data-model`, `frontend/src/views/DataModelPage.jsx`)
draws the schema for the same people: one circle per label (sized by count),
one arrow per relationship type between two labels, loops for a label linked
to itself, with a table of the same rows for keyboards, screen readers and
phones. `GET /api/maintenance/access` says who may (`graph`), and the menu
links it only where the menu preview is on. It can also draw an intended
design next to what's built: `GET /api/maintenance/graph/design` returns the
`data_model` document in `app_settings`, checked by
`backend/maintenance/graph_design.py` (its docstring has the shape; plain text
only, sizes capped), or `{available: false, reason}`. The app never writes that
document. The page then shows "What's built", "What's designed" (proposed
edges dashed) and "Both" (designed but not built dashed, built but not designed
amber), and downloads the diagram as a PNG or an Arrows (arrows.app) JSON file.
cytoscape.js (MIT) draws it, loaded only on that page.

**Later: paying users.** Graph queries for Pro users (an optional extra) will
use a **per-workspace subgraph sandbox**: each query runs on a throwaway graph
holding only that workspace's data, so isolation doesn't depend on what else
the database holds or on Neo4j's commercial access control (Aura Business
Critical, about US$290 a month at its minimum, or a self-managed Enterprise
licence; Community Edition has none). Not built. Until then, keep both lists to
the owner alone.

## Making Neo4j the primary store later

Worth it when Neo4j is close to Cloud Run (AuraDB Professional in
australia-southeast1, or a VM there): then start-up no longer replays the log,
and every instance shares one graph.

1. Create the instance; put its settings in Secret Manager and the service's
   environment as above.
2. `MAINTENANCE_GRAPH=neo4j` (and drop `MAINTENANCE_GRAPH_MIRROR`). The graph
   lives in namespace `graph-v<PROJECTION_VERSION>` (prefixed by
   `MAINTENANCE_GRAPH_NAMESPACE`), built from the log by the first instance to
   start. A new projection version builds a new namespace beside the old one,
   which instances still on the old version keep using; remove old ones with
   `neo4j_store.delete_namespace`.
3. Each event is one statement: its writes and `applied` advanced together,
   only if `applied` was still the event before. Two instances never apply one
   event twice or pass one over (tested).
4. Check with `verify --target graph` before switching traffic.

Rolling back is the config: unset `MAINTENANCE_GRAPH`, and instances replay the
log into SQLite as before. The log stays in Mongo throughout; Neo4j is only
ever a projection of it.
