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
NEO4J_URI=neo4j+s://<id>.databases.neo4j.io
NEO4J_USERNAME=<user>
NEO4J_PASSWORD=<password>          # Secret Manager
NEO4J_DATABASE=<database>          # optional (the user's default)
```

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
  --update-env-vars "^;^NEO4J_URI=neo4j+s://<id>.databases.neo4j.io;NEO4J_USERNAME=<user>;NEO4J_DATABASE=<database>;MAINTENANCE_GRAPH_MIRROR=neo4j"
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
python -m backend.scripts.maintenance_graph status     # how far behind, per workspace
python -m backend.scripts.maintenance_graph sync [--org ORG]
python -m backend.scripts.maintenance_graph rebuild [--org ORG]           # dry run: what would be copied
python -m backend.scripts.maintenance_graph rebuild [--org ORG] --apply [--prune]
python -m backend.scripts.maintenance_graph verify [--org ORG] [--target mirror|graph]
```

Each replays the log (Mongo when `MONGODB_URI` is set, else the local file)
into a fresh in-memory SQLite graph first. `rebuild --apply` copies each
workspace whole, in one transaction each; `--prune` also removes workspaces
Neo4j holds that the log doesn't. `verify` compares the replay with Neo4j node
for node and exits 1 on any difference: the check before trusting a copy.

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
