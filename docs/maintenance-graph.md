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
  `tools/list` (and the guide's `graph` topic out of `maintenance guide`'s
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
gets a hint saying so. `maintenance guide` topic `graph` (allowed users only)
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

## RCM on the positions

The position tree is the spine of RCM. A position performs functions, each
function fails in one or more ways (functional failures), and each functional
failure is caused by some of the position's failure modes:

```
(:Position)-[:PERFORMS]->(:Function {text, standard, standard_basis?, basis_on?})
(:Function)-[:HELD_TO]->(:Standard {text, parameter?, comparator?, value?, unit?, when?, source?, order})
(:Function)-[:FAILS_AS]->(:FunctionalFailure {text})
(:FunctionalFailure)-[:BREACHES]->(:Standard)       # optional: none means the whole function
(:FunctionalFailure)-[:CAUSED_BY]->(:FailureMode)
(:Function)-[:FAILS_DIRECTLY_AS]->(:FailureMode)    # an FMEA row: no functional failure written yet
(:FunctionalFailure)-[:RESULTS_FROM]->(:FunctionalFailure)   # effect -> cause, on a position inside
(:Position)-[:CAN_FAIL_AS]->(:FailureMode)          # as before
(:Task)-[:MITIGATES]->(:FailureMode)                # many-to-many: see below
(:Task)-[:WATCHES]->(:MeasurementPoint)            # a reading trigger (task.trigger_set)
(:LoggedEvent {event_type, note, when})-[:LOGGED_ON]->(:Position)   # position.event_logged
```

A failure mode's analysis and decision are properties on the mode
(`effects`, `notes`, `consequence`, `outcome`, `rtf_basis`, `decision_notes`,
`task_note` for a decision with no scheduled task, `task_id`: the decision's
own task, and `evidence`: the saved model or analysis behind it, `{type,
id}`). The interval and unit of a scheduled decision are its task's. A
failure mode under no functional failure still belongs to its position (the
app lists it as unassigned).

A failure mode may also sit directly under a function, with no performance
standard or functional failure between (`FAILS_DIRECTLY_AS`): that is how an
FMEA worksheet reads, function › failure mode. `failure_mode.placed {id,
function_id}` makes the edge (`function_id` null drops it); assigning the mode
to a functional failure drops it too. The RCM reads list these in the
function's `modes`; the Explorer's RCM tab shows them under **No functional
failure yet**, and a function with such modes and no functional failure is not
analysed. The mode is one record either way: the scores, effects and decision
stay with it when it is assigned.

The FMEA and FMECA fields are properties on the mode too, written by
`failure_mode.scored {id, changes}` (a field set to null is cleared):
`severity`, `occurrence`, `detection` (1–10), `cause`, `effect_local`,
`effect_next` (`effects` is the end effect), `detection_method`, `action`,
`action_owner`, `action_due`, `action_status`, and for criticality
`failure_rate`, `time_unit`, `rate_source`, `mode_ratio`, `loss_probability`,
`operating_time`, `severity_class`. The risk priority number, the action
priority and the mode criticality are computed on every read
(`backend/maintenance/fmea.py`), never stored.

Events: `function.added` / `updated` / `removed`, `functional_failure.added`
/ `updated` / `removed`, `failure_mode.assigned` (under a functional failure,
or none), `failure_mode.placed` (directly under a function, or not),
`failure_mode.analysed`, `failure_mode.scored` and `failure_mode.retired`. Deleting a
function or a functional failure leaves its failure modes on the position,
unassigned; deleting a failure mode retires the tasks that serve it alone and
unlinks the ones that serve other modes too.

### Several tasks for one failure mode, one task for several

`MITIGATES` is many-to-many. A failure mode's decision may be a combination
of tasks (an inspection that catches the slow failures and a replacement at a
hard life; the classic RCM sources expect this for safety, environmental and
hidden consequences), and one act of work may be the task for several modes
(one monthly water sample for five chemistry modes). A task on a position may
serve failure modes on that position and on the positions inside it, never
the other way: a round at the pool covers the chlorinator's modes.

- The decision's own task is the first of the mode's tasks: the one its
  decision made or adopted, recorded as `task_id` on the mode
  (`failure_mode.analysed`, `changes.task_id`; older code stores the key
  unused). Without one, the first live task by outcome, start and name.
- The task owns its interval. `decide` changes a task's name and interval
  only while that task serves this mode alone; once it serves others, those
  change on the task (`maintenance tasks.update`), for every mode, or the mode
  gets a task of its own. The evidence on a decision applies to its own task.
- Events: `task.linked` and `task.unlinked` (`id`: the task, `failure_mode_id`,
  `on`) add or remove one link, the task's other links kept. `task.added` may
  carry `failure_mode_ids` beside `failure_mode_id` (the first of them): the
  projector links every one; code from before the field links the one it
  knows. `task.updated` with `failure_mode_id` still means "the only link", so
  every event in the log replays as it did. `PROJECTION_VERSION` stays.
- Reads: `decision.tasks` lists every live task serving the mode, its own
  first, each with `shared_with` (how many other modes it serves);
  `decision.task`, `interval`, `interval_unit` and `task_id` stay the first
  one's, so older readers see what they saw. A task's view lists
  `failure_modes`, `failure_mode` being the first. The roll-up's `tasks`
  counts modes with at least one live task; `scheduled_without_task` counts
  decisions that schedule work with no live task to do it (shown, never a
  gate: `analysed` rests on decisions, as before).
- A combination of tasks (RCM II): one decision with several outcomes, a
  regular inspection plus a fixed-time replacement, each scheduled one with a
  task of its own. The members are `outcomes` on the mode, `[{outcome,
  task_id}]`, set whole by `failure_mode.outcomes_set` (`[]` ends it); the
  first is the decision's own (`outcome`, `task_id`), so readers of one
  outcome read the combination's first. A plain decision on a mode that never
  had a combination emits only what it always did. Reads add
  `decision.outcomes` (each with its task, interval and `task_id`, null when
  its task has gone), and `scheduled_without_task` counts a combination any
  of whose scheduled tasks has gone. Copying a position copies it.
  `PROJECTION_VERSION` stays: a new event, no existing shape changed.
- Retiring a mode retires its sole tasks and unlinks shared ones; restoring
  it brings its sole tasks back (`tasks_restored`), not the shared links.
  Merging a mode moves every link across. Moving a mode (or a function) takes
  the tasks serving only the moving modes; a shared task stays and keeps
  serving a moved mode while the new position is inside the task's, else that
  link is unlinked and the move says so (`tasks_unlinked`, `note`). Moving a
  task is allowed when every mode it serves is on the target or inside it.
  Copying a position copies every link, the decision's own task re-pointed to
  the copy; a task serving a mode on a position inside the branch is linked
  once that position's copy exists (`task.linked`).
- The worksheet import: a row that repeats a failure mode (same text, same
  function and functional failure) with another task adds that task to the
  mode; a task named on several rows, or on the position already, is one task
  linked to each (a row asking it to have another interval is a row error).
  The CSV export writes one row per task, so it reads back as written.

### Several performance standards on one function

A function is one job (one verb, one object); how well it must do it can be
several numbers (pH, alkalinity and hardness; flow and pressure). Each is a
`Standard` node the function is `HELD_TO`: `text` (what people read: "pH
7.2-7.8", required), and optionally the structured limit (`parameter`,
`comparator`, `value`, `unit`, for the day readings are checked against it),
`when` it applies (a condition, never a standard of its own) and its `source`.
A functional failure may `BREACH` one of its function's standards (none: the
whole function, as a total loss does). A standard with no functional failure
is reported (`standards_without_failure` on the function), never a gate:
`analysed` rests on decisions, as before.

- Events: `standard.added` (`id, function_id, text, order, on` and the
  optional fields), `standard.updated` (`changes`, `order` among them),
  `standard.removed` (flagged, history kept; the `BREACHES` edges into it go).
  `functional_failure.added` may carry `standard_id`; `functional_failure.updated`
  takes `standard_id` in `changes` (None: the whole function), re-pointing the
  edge. Code from before standards stores that key on the node, unused, and
  logs the three new types and passes over them. `PROJECTION_VERSION` stays.
- The function's old single `standard` text stays on the node. Reads give
  `standards` (the list, each with how many failures breach it) and `standard`
  as the list's texts joined with "; " once there is a list, else the old
  text, so older readers, the worksheet and the CSV see one line;
  `legacy_standard` shows the old text while a list stands in for it. The
  first list operation (`add_standard`, or a sheet adding a second standard)
  keeps that text as the list's first item, verbatim. `update_function`
  refuses `standard` once the list exists. Nothing is split by the app:
  `split_standard` proposes lines from ";" and line breaks (a dry run) and
  writes the user's edited lines.
- Standards hang off the function, so they move with it (`function.moved`)
  and are flagged with it (`remove_function` emits `standard.removed` for
  each). A copied position copies them (`standard.added` after each
  `function.added`), and each failure's breach re-pointed to the copy.
- The worksheet: every distinct "Performance standard" cell under a function
  is one standard (a row with the function and a standard alone lists one);
  when a function has a list, a functional failure's own row names the one
  it breaches. The CSV export writes a function's standards as such rows,
  then each failure's rows with the standard it breaches (blank: the whole
  function); a function with its one text (no list) reads and writes as
  before, the text on every row.
- The app's Explorer shows the standards as a level of the RCM tree
  (`frontend/src/explorerRcm.js`, `graftRcm`): position › function ›
  standard › functional failure › failure mode. Each functional failure sits
  under the standard it `BREACHES`; the ones that breach none sit under one
  "No standard" row after the standards (a total loss, or a link not made
  yet); a function with no standard at all has its failures right under it.
  A function that still has its one `standard` text (no list) shows that
  text as one standard row with every functional failure under it: a display
  rule only (with one standard there is nothing else to breach), so nothing
  is written to read it that way, and the first list operation keeps the
  rule's meaning (the text becomes the first item). The rows' menus call the
  same routes as the dialogs (`add_standard`, `update_standard`,
  `reorder_standards`, `remove_standard`, `update_functional_failure
  standard_id`); the one text's row edits the function's `standard`.

### The working behind a performance standard

Some performance standards are worked out from the operating context (a
dosing rate from a tank's volume and its demand, a flow from a turnover
time). `standard_basis` on the Function keeps that working: Markdown text, LF
line endings, at most 20,000 characters (`BASIS_TEXT`), no control characters.
The server stores it as text and never renders it.

- `function.added` carries `standard_basis` and `on` only when there is a
  working, so older events replay to the same node. `function.updated` carries
  it in `changes` like `text` and `standard` (`""` clears it), plus a
  top-level `on`; the projector keeps that day as `basis_on` ("updated
  <date>"). A copied position carries the working (and its date).
- Code from before the field: its `function.added` projector reads named keys,
  so it projects the function without the working; its `function.updated`
  projector (`_patch`) stores `changes.standard_basis` on the node, unused and
  unshown; the top-level `on` is ignored. Nothing fails.
- Reads: the full text is only in per-position reads (`rcm_worksheet`: `GET
  /positions/{id}/rcm` and `maintenance get.rcm`) and in one function's
  read (`GET /functions/{id}`, `maintenance get.function`). The bulk
  `rcm_all` (the asset tree's RCM tab) gives each function `has_basis` and
  `basis_preview` (its first 240 characters as one plain line) instead.
- **Merged into the notes (Nov 2026).** The working is now written in the
  function's notes and rationale; nothing new writes `standard_basis`. Reads
  merge a working still on the node into the notes (`merged_notes`: the notes,
  a "Working" line, then the working; the working alone when there are no
  notes), and `standard_basis` / `has_basis` / `basis_preview` describe those
  notes for older readers. The first save of such a function's notes emits
  `function.working_merged` (`id, notes`): the projector replaces `notes` and
  clears `standard_basis` on the node (`working_merged: true`); the old events
  stay as written. `merge_workings(dry_run=True)` and
  `python -m backend.scripts.merge_function_workings [--org ORG] [--apply]`
  emit it once for every live function that still has a separate working.
  `standard_basis` on add/update is a deprecated alias that writes the notes.
  A function's notes may run to 25,000 characters (`FUNCTION_NOTES`).
- A PDF of the working is a Document with its `OF` edge to the Function (no
  new event, edge or kind; at most 5 on one function). It moves with the
  function (the edge is on the node), isn't copied with a position (no
  document is), and is removed with the function: `remove_function` emits
  `document.removed` for each, and the app deletes a kept PDF's bytes.

### Notes and rationale on every RCM row

Every function, performance standard, functional failure and failure mode has
its title (`text`) and its notes: a long description where the rationale for
it is written (why the standard is set where it is, what a mode rests on).
Plain text, line breaks kept as LF, trimmed, at most 4,000 characters
(`LONG_TEXT`); a function's, which hold the working behind its standards, at
most 25,000 (`FUNCTION_NOTES`).

- `function.notes_set`, `standard.notes_set` and `functional_failure.notes_set`
  (`id, notes`) replace the row's `notes` whole (`""` clears them). The add and
  update methods take `notes` and emit the event after the row's own; a copied
  position copies them. Older code has no projector for them, so it skips them.
- A failure mode's notes are its `notes` from `failure_mode.analysed`, as
  before (no new event).
- Reads: `notes` is on every row kind in `rcm_worksheet`, `rcm_all`, one
  function's read and the FME(C)A read built on them.

### A higher functional failure caused by lower ones

A functional failure can result from functional failures on positions inside
its own position, at any depth: "Free chlorine below 1 ppm" on the pool
results from "No output" on the salt chlorinator inside it. The failure-mode
questions for it are then answered on the lower position, and it needs no
failure modes of its own. The edge points from effect to cause, as `CAUSED_BY`
does, so what explains a failure is always a walk out of it. Many to many: a
failure may have several causes below, a lower failure may cause several above,
and a failure may have causes below and failure modes of its own. At most 50
causes per failure; the edge has no properties.

| Event | Payload | Projector |
|---|---|---|
| `functional_failure.linked` | `id, cause_id, position_id, cause_position_id, on` | `put_edge("RESULTS_FROM", id, cause_id)` |
| `functional_failure.unlinked` | `id, cause_id, position_id, cause_position_id, on` | `delete_edge("RESULTS_FROM", id, cause_id)` |

`id` is the effect (the higher failure), `cause_id` the lower one; the two
position ids are for the event feed and the audit, and the projectors read only
the failure ids. Linking twice, or unlinking what isn't linked, writes nothing.
A link is refused, saying what to do, when either failure (or its function) was
deleted, either position is retired, the two are the same failure or on the
same position, the cause isn't on a position inside the effect's, the link
would close a loop, or the effect already has 50 causes. Another workspace's
failure is not found.

Links are analysis, not history, so nothing is refused for having them; they
go, with an `unlinked` event each, when:

- either failure is deleted, or its function is (`links_removed` in the result);
- the cause's position is retired (`links_removed`);
- a function moves, or a position is moved to another parent, so that a cause
  would no longer be on a position inside its effect's (`links_removed` and a
  `note` in the result). Links that still run downwards stay.

Retiring or merging failure modes leaves links alone. Copying a position
copies the links between failures inside the copied branch, and a link from a
failure above the branch when that failure is still above where the copy goes
(otherwise it's counted in `links_skipped`).

**Covered and analysed.** A functional failure is *covered* when it has at
least one failure mode of its own or one counted cause, every one of its own
failure modes has a decision, and every counted cause is covered in turn. A
cause counts while it is live, on a live position strictly inside the effect's
position; the walk skips failures already on it, so a loop (only possible from
two links written at the same moment) never hangs a read. A position is
*analysed* when it has a function, every function has a functional failure,
every functional failure is covered, and every failure mode on the position has
a decision. The cause's position need not be analysed, only the linked failure.

The RCM reads (`rcm_all`, `rcm_worksheet`, `functional_failure`) give each
functional failure `covered`, `explained_below` (counted causes and no failure
modes of its own), `causes` (each with `position`, `inside`: whether it counts,
`covered` and `chain`: the counts over every failure mode reachable through it),
`effects` (each with `position` and `inside`) and `below` (the counts over every
failure mode under its counted causes, or null). A chain counts each failure
mode once however many paths reach it, and a position's own counts stay its
own failure modes only, so nothing is counted twice.

The events are new types: `PROJECTION_VERSION` stays, and code from before them
passes them over, so there a failure explained only below reads as not covered
until it's replaced.

Where to write them: `POST /api/maintenance/functional-failures/{ff_id}/causes`
`{cause_id}` and `DELETE /api/maintenance/functional-failures/{ff_id}/causes/{cause_id}`
in the app (both answer with the functional failure, its causes and effects);
`maintenance failure_modes.link_cause` / `unlink_cause`
(`functional_failure_id`, `cause_id`) over MCP, with their REST twins
(`POST /api/v1/maintenance/failure_modes.link_cause`) and CLI commands
(`reliafy maintenance failure_modes.link_cause --functional-failure-id … --cause-id …`)
built from the same table. The graph schema's examples `failure_causes` and
`failure_effects` walk the links in Cypher.

### Moving RCM to another position

RCM written on the wrong position can be moved, keeping every id, decision,
effect, note, evidence link and task date. Three events re-point the edges
that tie a thing to its position (`PERFORMS`, `CAN_FAIL_AS`, `ON`); each names
everything that moved with it, so a replay never works the rule out again:

| Event | Payload | What moves |
|---|---|---|
| `function.moved` | `id, position_id, from_position_id, order, failure_mode_ids, task_ids, on, task_changes?` | the function, its functional failures, the live failure modes under them and those modes' live tasks |
| `failure_mode.moved` | `id, position_id, from_position_id, functional_failure_id, order?, task_ids, on, task_changes?` | one mode with its decision and live tasks, under one of the new position's functional failures (or none) |
| `task.moved` | `id, position_id, from_position_id, on, task_changes?` | one position's task |
| `functional_failure.moved` | `id, function_id, from_function_id, position_id, from_position_id, order, standard_id?, failure_mode_ids, task_ids, on, task_changes?` | one functional failure under another function (same position or another) with the modes named and their live tasks; the standard it breached stays with the old function, `standard_id` names one of the new function's |
| `standard.moved` | `id, function_id, from_function_id, position_id, from_position_id, order, functional_failure_ids, unlinked_functional_failure_ids, on` | one performance standard to another function, alone: the functional failures that breached it stay with their function under no standard (`unlinked_functional_failure_ids` names them); `functional_failure_ids` are the new function's failures that breach it now (an undo puts the breaches back this way) |

Who moved it and when are the event's `actor` and `at`, as for every event.
A functional failure moving on its own position names every mode under it
(deleted and merged ones too), so they stay under it; moving to another
position names the live ones, as `function.moved` does.
A deleted or merged mode still under a moved functional failure stays on the
old position (it's history there) and is taken from under the functional
failure, so no edge crosses positions. Retired tasks stay where they were.

A move is refused, with a message saying what to do instead, when:

- the target isn't a position in the workspace, is retired, or is where the
  thing already is; or the thing itself was deleted, merged or retired;
- a failure mode has failures (fitments ended by it, not voided) or
  inspection findings recorded against it, or other modes were merged into it:
  that history belongs to the old position, so add the mode on the new one
  instead;
- the target already has a live mode of the same name;
- a task has an open work order (close or cancel it first) or work done on it
  (retire it and add a new task on the target); cancelled work orders don't
  count;
- a task prevents a failure mode that isn't moving with it and isn't on the
  target. It isn't unlinked silently: move the mode (its tasks go with it), or
  unlink the task first;
- only an item's or a location's task: those don't move between positions.

A task by use isn't refused. It keeps counting the measurement it counted
(`_task_point` at the moment of the move, pinned as its `point_id`) and its
last-done reading while that measurement fits the target: on it, on a position
above or below it, or on the item fitted to one of those. When it doesn't, the
move raises `NeedsChoice` (HTTP 409, `needs_choice`: each such task with what
it counts and the counters in its unit at the target) until `measurement` says,
per task: `keep`, `switch` (`point_id`; `last_done_reading`, or worked out from
the last-done date and marked `last_done_reading_estimated`) or `calendar`
(`interval`, `unit`). What changes is carried in the move event's
`task_changes` ({task_id: fields}), so replaying it never works anything out
again; moves logged before it have none and replay as they did.

After a move, failures and work orders on the new position name the mode as
usual (`_mode_ref` finds it there); naming it on the old position says where it
went.

The events are new types, so no existing projection changes meaning and
`PROJECTION_VERSION` stays. Code from before them logs an event it doesn't
know and passes over it (see `GraphStore._project`), so during a rolling
deploy an older instance shows the thing where it was until it's replaced.

**Order and undo.** A moved thing goes last among its new siblings.
`reorder_rcm(parent_id, ids)` (`PUT /rcm/order`; `maintenance failure_modes.reorder
) places a position's functions, a function's functional failures or a
functional failure's failure modes, emitting the existing `*.updated` events
with `order`, as `reorder_standards` does. Each move's result names where the
thing came from (`from_position_id`, `from_functional_failure_id`,
`from_function_id`, `from_standard_id`; reorders give `previous_ids`), so a
`maintenance apply` batch of moves answers with an `undo` list that puts them
back. The app's RCM tab sends one batch per drag-and-drop through `POST
/rcm/apply` (the arranging actions only, `apply.ARRANGE`, run through the
service directly; the same checked-on-a-copy-first rule, the same answer).
`move_standard(standard_id, function_id, functional_failure_ids)` (`POST
/standards/{id}/move`; `maintenance failure_modes.move_standard`) moves a
standard to another function on any position: a workshop rearranges the
analysis as it talks it through. The new function's old single text becomes its
list's first item first, as `add_standard` does. Its undo moves it back with
the failures that breached it (`ids`); the app adds a `reorder_standards` to put
it back in its place.

Dragging a standard in the app carries everything under it: one batch of
`move_standard` then `move_functional_failure` for each functional failure that
breached it (`function_id` the same, `standard_id` the moved standard), so they
and their failure modes, decisions and tasks go with it, by `move_function`'s
rules across positions. No new event: `standard.moved` and
`functional_failure.moved`, all or nothing (the trial run first). Its undo list,
newest first, moves each failure back (breaching nothing), then the standard
back with them breaching it again; the app adds the old order of the standards
and of the function's failures. Links dropped because they would no longer run
downwards are said in the answer and aren't put back by Undo, as for a
function's move.

The evidence check (`backend/maintenance/rcm_decisions.py`, applied by
`rcm_graph.resolve`) is done on every read, never stored. A task with no unit
given runs in days, so days are checked against the linked analysis's unit.

The app's Assets › Explorer shows it on its RCM tab, where the asset tree and
the RCM are one table: the tree (by positions) is the first column, each
position's functions, functional failures and failure modes are nested in it,
and every row has the RCM's columns. Adding a function, failure or mode there
adds a row to the tree. A position that isn't analysed (above) is marked "not
analysed" in the tree.

### Reading the RCM as an agent

Besides `maintenance get.rcm` (a position, or its branch), two reads
answer an agent's questions in one call: `maintenance get.failure_mode`
(one mode by its id: decision with its evidence check, tasks, where it sits,
and the tasks on its position or above it that could serve it too, as
`GET /api/maintenance/failure-modes/{id}/tasks` lists them) and
`maintenance list.rcm_gaps` (`rcm_graph.gaps`: modes undecided, with no
task, hidden without a failure-finding task, or with evidence to check;
functions, performance standards and functional failures with nothing under
them; the whole workspace or one branch with `target_id`). The RCM reads over
MCP list a mode's tasks once, on the mode, not again under its decision.

### Importing an FMEA / RCM worksheet onto a position

`backend/maintenance/rcm_sheet.py` adds a worksheet (Excel or CSV, one row per
failure mode) to one position's RCM: `POST
/api/maintenance/positions/{id}/rcm/import/preview` (nothing written) and
`…/rcm/import`, MCP `change import_excel target=rcm position_id` (`dry_run`
true: the preview), and the
RCM tab's "Import worksheet…". The sheet is read and mapped by the worksheet
parser (`services/rcm_import.build_tree`), and written through the
service's methods (`add_function`, `add_functional_failure`,
`add_failure_mode`, `update_failure_mode`, `decide_failure_mode`), so it is
ordinary events and no new event type.

It only adds. A function with the same text (case and spacing aside) is used
as it is, and so is a functional failure with the same text under it; a
failure mode already on the position is left as it is, wherever it is. So the
same sheet imported twice adds nothing the second time, and the RCM tab's
Export CSV (named as the import reads it) imports back adding nothing. Every
row is checked first; a row in error (an interval over the task limits) means
nothing is written. Limits: 5,000 rows read, 500 new failure modes per import
(each is a few events); a failure mode over 200 characters gets a shortened
name with the full text in its notes.

### Fields left by the earlier RCM studies

Before RCM was built on the positions, it was kept in separate study
documents and applied onto positions. Events written then (`function.added`,
`functional_failure.added`, `failure_mode.added`, `task.added`) may carry
`study_id` and `rcm_function_id` / `rcm_failure_id` / `rcm_mode_id` fields.
The projectors tolerate them, nothing reads or writes them any more, and the
log is never rewritten, so those events replay as they always did.

### A position's description and operating context

A position has two text fields: `description`, a short line on what it is,
and `operating_context`, how it's used (the load, the environment, the hours
it runs). Both are plain text of at most 4,000 characters. `operating_context`
is optional on `position.created` (left out when empty, so older events replay
to the same node) and set or cleared ("") through `position.updated`.

### Retiring the rest of the tree, and restoring anything

Nothing is erased. Every level can be taken out of use with a flag event and
brought back with its reverse: `location.retired`, `item.retired`,
`part.retired`, `manufacturer.retired` and `point.retired` join the retires
that were there (positions, tasks, failure modes, classes, conditions, groups,
connections), each projected by `_flag("retired")`; `<node>.restored`
(`position`, `location`, `item`, `task`, `failure_mode`, `part`,
`manufacturer`, `point`, `item_class`, `condition`, `group`, `interface`) and
`document.restored` (a link; a deleted PDF's bytes are gone) are projected by
`_unflag`, which turns the flag off and keeps `restored_on`. The service
refuses a retire while something depends on the thing (fitted, located,
placed, stocked, listed, an open work order, a task going by a point) and a
restore while what it needs is still retired (its parent, its subject, its
failure mode), so the graph is consistent after either. `positions retire`
and `locations retire` take `cascade`: a delete (`tree_delete.py`), which
never refuses. The live subtree goes (a location's locations inside and the
positions located at them, with everything inside those). It never retires an
item: items fitted there are taken out (`item.removed`, reason `other`) and
kept as loose items, and items stored at a deleted location lose their place
(`placement.ended`; `placement.reinstated` on undo). Open work orders are
cancelled; tasks and work packages are retired.
It's built from those existing events, plus `tree.deleted` (a `Deletion` node
recording everything it took, numbered `n` per workspace) so that `restore`
with `cascade` undoes it as a unit: `fitment.reinstated` reopens a fitment the
delete ended, `work_order.uncancelled` puts a work order back at the status
it had, and `tree.restored` marks the record. What changed since (an item
fitted elsewhere) is skipped and listed. `dry_run` with `cascade` counts what
would go and writes nothing.
In a position's RCM, `remove_function`, `remove_standard`,
`remove_functional_failure` and `retire_failure_mode` take `cascade` the same
way (`rcm_delete.py`): everything under the row goes (a function's standards,
functional failures, the modes under them or placed directly under it, the
documents on it; a standard's breaching failures; their tasks, a task serving
a mode outside what goes being unlinked instead; the cause links of every
failure that goes). It's built from the existing events plus `rcm.deleted` (an
`RcmDeletion` node recording it all) so that `restore_rcm` undoes it as a
unit, with `function.restored`, `functional_failure.restored` and
`standard.restored` (which also re-points the failures that breached it) and
`rcm.restored` marking the record. Without `cascade` the removes keep their
old meaning (the modes stay on the position, unassigned). Reads leave retired locations, items, parts,
makers and points out of lists and matches; a direct read answers with
`retired: true`.

Edits that had no event before: `interface.updated` (kind, medium, name,
rating, and the position that realises it), `document.updated` (title, kind),
`photo.updated` (caption), `coordinates.cleared`, `part.supersession_cleared`
and `parts.not_interchangeable`. All of these are new event types:
`PROJECTION_VERSION` stays, and code from before them passes over each
(logged, skipped) and projects the rest.

`maintenance apply` (backend/maintenance/apply.py) runs a list of the typed
tools' actions as one call. Every operation first runs on a throwaway copy of
the organisation's graph (`store.scratch_copy`: an in-memory `GraphStore`
filled from `snapshot(org)`, with an empty log of its own), so a failure
anywhere refuses the batch before the live log is touched; then the same
operations run on the live store in order. The log records each operation's
events as it always would; a batch isn't one event.

## Failure reports: from a failure to its closure

A failure report (FRACAS: failure reporting, analysis and corrective action)
is an event-sourced record like everything else: seven `failure_report.*`
event types, one `FailureReport` node per report, and every change kept on
the node with who and when (`history`), the way a work order keeps its notes.

- `FailureReport` {number (shown as FR-n), position_id, title, description,
  occurred_on, found_by, consequence (the RCM vocabulary, or null), status
  (reported, investigating, corrective_action, verifying, closed, rejected),
  filed_on, failure_mode_id, the item as it was when filed (item_id,
  item_name, item_serial, part_id, part_number, part_name, item_class_id,
  item_class_name: a snapshot, so the report still says what was there after
  a replacement), investigation, actions ([{id, what, owner, due, status,
  done_on, work_order_id, work_order_ref, added}]), verification, closed,
  rejected, history}.
- `FailureReport REPORTED_AT Position` (the key: every read goes by the
  position), `INVOLVES Item` while the item exists, `FOUND FailureMode`.
- The repeat check (reports at the same position since the fix) is worked
  out on read, never stored. "This level and below" is one function,
  `Maintenance._report_scope`, which the list reads and the tree roll-up
  (`open_reports` on each row and inside it) follows.

## Products: design trees and the items built from them

For a user who designs and builds things, not only runs a plant. A product is
a design: a top-level position tree (the functional hierarchy) flagged as a
design, with the catalogue part it is (its bill of materials hangs on that
part). An item built from it is the existing serial-numbered `Item`, fitted at
the top of a copy of the design's tree. Three event types, all new (older logs
replay unchanged; no projection version bump):

- `design.declared {position_id, part_id?, rev, on}` sets `design` {rev,
  part_id, on} on the top position and `Position DESIGN_OF Part`. Declared
  again, it changes the revision label or the part. Refused for a position
  inside another, a tree with any fitment (a plant or an item, not a design)
  or a tree built from a design.
- `design.cleared {position_id, on}` sets `design` to null and drops
  `DESIGN_OF`. Refused while items built from it are in use.
- `position.implements {position_id, design_position_id, design_rev}` on
  every position of a built tree: `design_position_id`, `design_rev` and
  `Position IMPLEMENTS Position` (the design's). The built tree's top also
  carries `item_id` and `serial` (`built_item_id`, `built_serial`): the item
  built into it, kept when that item is later swapped.

Building (`Maintenance.build_item`) is `copy_position` to the top level, then
`create_item` (the product's part, the serial), `fit` at the new top, then one
`position.implements` per copied position. The provenance survives renames
and moves inside the item's tree; a design position retired later reads as
"gone" (`implements.gone` on a position, `design_gone` on a tree row), never
unlinked. A design change never reaches a built item by itself.

Reads group built positions by the design position they implement
(`design_rollup`: items, what's fitted there, pooled life rows in
`class_life_data`'s shape, failure reports there and below on each item).
Failure reports can't be filed on a design's positions: a report is about an
item. The tree rows carry `design` (a design's top), `design_position_id`
(a built position) and `built_from` (a built tree's top), so the app can keep
designs and built items out of the Assets landing.

### A product's physical layout (design locations)

A product has locations of its own (Forward left arm, Centre body › Battery
bay): ordinary `Location` nodes marked as the design's. Two more event types,
new (no projection version bump):

- `location.design_declared {id, product_id}`, straight after the location's
  `location.created`, sets `design_of` (the product's top position id). A
  location made inside a design location gets one too.
- `location.carried {id, position_id, design_location_id?}` sets `carried_by`
  (a built tree's top position) and `design_location_id` (the design location
  it copies).

Design locations are never assets: `places`, `location_tree`, `locations` and
the app's Explorer leave them (and carried ones) out; `location_tree(of=…)` /
`locations(of=…)` (`GET /locations?of=`, MCP `list.locations product_id`) list
a product's or a built unit's own. A design's positions may be placed only at
its own design locations (inheritance as for assets); an asset's never; a
built unit's at the places you look after or its own carried ones. Design
locations hold no items, stock, tasks or work orders. Moving a location keeps
it in its own layout.

`build_item` copies the design locations (parents first) as `location.created`
+ `location.carried`, and each copied position's `location_id` is the copy of
its design position's. A carried location's top has no parent: it is wherever
its unit is, so its path (`_location_path`) starts with the location of the
unit's top position, and moving the unit moves it with no event of its own. A
location's read counts the positions on the units kept there through their
carried locations.

Deleting a design or carried location (`delete_tree`, kind location) takes the
locations inside it but not the positions placed there: each gets
`position.updated {location_id: null}` and the record's `unplaced` keeps the
[position, location] pairs, which an undo puts back. Deleting a product's top
position, or a built tree's, takes its locations with it.

## Signal channels and derived points

A `SignalChannel` node sits on a position or an item (an `ON` edge) and holds a
sensor's settings (unit, axes, sample rate, running speed, tag). Its events are
`signal_channel.added`, `.updated`, `.retired` and `.restored`. The snapshots a
channel receives are *not* in the event log or the graph: they live in the
snapshot store (`maintenance_snapshots` in Mongo; a table beside the graph
locally), keyed by channel and time, because a burst of raw samples is far too big
for an event. Re-sending a snapshot (same channel, same millisecond) is a no-op.

A watch band or an overall level is a **derived point** (`derived_point.added`): a
`MeasurementPoint` (condition, read from the time-series store like a feed's) with a
`derived` property `{from, rule}` and a `DERIVED_FROM` edge to its source. Every new
snapshot adds one value to each live derived point of its channel (`derived.py`),
and a new one is backfilled from the snapshots already stored. A new kind of derived
point (a formula over other points, say) is a new rule registered with
`derived.register`. Its values are appended to the series store, which can't take a
value back, so a rule is fixed when the point is made. Editing a band's range
therefore makes a new *version*: `derived_point.added` carries `supersedes` (the old
point) and `applies_after` (the time of the latest stored snapshot), the new point is
not backfilled, and the old one is retired with its values untouched. Replay gives the
same chain; the channel view joins a chain into one band with its change points. Name
and limits change in place (`point.updated`); warning levels are `signal_band.limits`
(drawn, no work opened). `signal_settings.set` holds the workspace's optional storage
warning level. A channel may name a speed channel (`speed_channel_id`); each snapshot
takes its rpm from that channel's nearest reading within an hour and keeps where it
came from (`speed_from`). Everything is kept; `signals.apply_retention` is the place a
thinning policy would go.

## Work packages: tasks done on one visit

A work package bundles tasks done together on one visit (the weekly check of
one area) so each visit raises **one** work order, not one per task. Tasks keep
everything they have (interval, instructions, checklist, failure-mode links);
a package changes how their work orders are raised, never what a task is.

Nodes and edges:

- `WorkPackage` {name, timing (`fixed` or `from_last_visit`), every, unit,
  pattern ({weekday}, {weekday, nth} or {day}; or none), anchor, tolerance
  ({amount, unit}: days, or hours kept but not yet enforced), trade, notes,
  created, members ([{task_id, visit_rule, every_nth?, suppresses?}]),
  paused, retired}.
- `WorkPackage PLANNED_FOR Position` or `WorkPackage PLANNED_AT Location`: what
  a top package is on. Its tasks are on that position or positions inside it,
  or at that location (positions located there, or the location itself).
- `WorkPackage BUNDLES Task`, one per member. A task has at most one home
  package that isn't retired. Items' tasks (they follow the serial number),
  tasks by use and rounds (`include_positions`) stay on their own.
- `WorkPackage LAYERED_ON WorkPackage`: a layer. It has no position or
  location of its own and visits on some of its parent's visits (the first
  Saturday of the month on a package every Saturday); its tasks go on the top
  package's work order that day. Layers have fixed dates, and each of a
  layer's next dates is checked to be one of its parent's when it's made or
  changed.
- `WorkOrder RAISED_FROM WorkPackage` (the top package), `FOR` each task on it.
  The work order carries `visit_on`, `visit_number`, `covers_to` (the latest
  visit whose lines it holds), `lines` ([{task_id, name, package_id,
  position_id or location_id, instructions, trade?, point_id?}]) and `released`
  ([{task_id, reason, on}]). Its `checklist` stays one flat list, so
  `work_order.check` by index works as before: each task's line ({text, done,
  task_id, position_id?}) followed by its own steps ({..., step: true}).

Why layers are packages of their own: a monthly check is the weekly visit plus
extra lines on the first Saturday, and a quarterly one adds to the monthly.
Modelled as a package on another, each layer keeps its own name, cadence,
trade and member list (so it can be paused, listed and proposed like any
package), while the work order, the tolerance and the next-visit rules stay
the top package's alone: there is never more than one work order per visit.
A rule per member ("every 4th visit") alone couldn't say "the first Saturday",
since some months have five.

When things are due, worked out on read (nothing about visits is projected):

- A fixed package visits on its cadence (`schedule.Cadence`: every N days,
  weeks, months or years from the anchor; a weekday every N weeks; the nth
  weekday or a day of every N months). After its work order closes, the next
  visit is the next date after the close; missed visits aren't made up, and a
  visit already past its tolerance before anything was raised for it is
  skipped. A `from_last_visit` package's next visit is the close date plus the
  interval.
- A member task is due on its package's visits by its visit rule (`every`, or
  `nth`: the first visit and every Nth after), not on its own interval, which
  stays for tasks outside a package and for a paused package's tasks. A task
  on a visit may cover others (`suppresses`): they're left off that visit, are
  not marked done, and aren't overdue because of it. The task view gains
  `package` and `due_by: "package"`; its `next_due` is the visit it's due on.
- A work order is late once today is past its `visit_on` plus the tolerance
  (`late`, `days_late`, `visits_missed`). Only one is open per package: while
  it's open, tasks due on later visits whose dates have come are added to it
  as lines (`work_order.package_lines_added`).
- At close, each ticked task line is done. Each line not ticked must be listed
  as not done: `work_order.task_released` takes the task off the work order
  (the `FOR` edge) and sets `owed_from` on the task, so it goes on the next
  visit whatever its visit rule, until it's done. The unchanged
  `work_order.closed` then renews the tasks still on it. An action may name a
  line's `position_id`, so a replacement or a failure found there is recorded
  at that position with the usual `action.recorded`, `item.removed` and
  `item.fitted` events.
- Lines can be marked during the visit, saved at once so a lost signal or a
  refresh loses nothing (`work_order.line_marked`): done, not_done with a
  reason, problem with a finding (an action, at the line's position), or todo
  to clear it. The tick follows the mark; a line's state is read from both
  (a mark the tick no longer matches is ignored). At close, a line marked
  not_done needs no repeating, and a problem's finding is recorded then,
  after any actions given, through the same action events: so all of a
  close's checks still run before anything is written, and a replacement is
  dated the day the work order closes.

Events (all new; no existing event changed meaning or shape, and
`PROJECTION_VERSION` stays):

| Event | Payload | Projects |
|---|---|---|
| `package.created` | id, name, timing, every, unit, pattern, anchor, tolerance?, season?, trade, notes, tasks, on; position_id, subject {kind: location, id} or parent_id | the node, its `PLANNED_FOR` / `PLANNED_AT` or `LAYERED_ON` edge, a `BUNDLES` per task |
| `package.updated` | id, changes, on | a plain patch (members' visit rules as the whole `members` list) |
| `package.task_added` / `package.task_removed` | id, task_id, visit_rule?, every_nth?, suppresses?, on | `BUNDLES` and `members` |
| `package.paused` | id, on, reason, until?, full_visit, by? | `paused`, `paused_until`, a `pauses` entry |
| `package.resumed` | id, on, full_visit?, by? | `paused` false, the last pause's `ended` |
| `package.retired` / `package.restored` | id, on, reason? | `retired` (retiring a top package retires its layers) |
| `work_order.package_opened` | id, number, title, type, package_id, position_id or subject, due, visit_on, visit_number, notes, on, trade?, lines | the work order, `ON`, `RAISED_FROM`, a `FOR` per line |
| `work_order.package_lines_added` | id, lines, through, on | lines appended, more `FOR`, `covers_to` |
| `work_order.task_released` | id, task_id, reason, on, visit_on | `FOR` removed, `released`, the task's `owed_from` |
| `service.stopped` | id (a position or an item), from, until?, reason, on, by? | `out_of_service`, a `service_history` entry |
| `service.resumed` | id, on, by? | `out_of_service` cleared, the entry's `ended` |
| `work_order.line_marked` | id, task_id, state (todo, done, not_done, problem), reason?, finding?, on | the task line's `done` and `mark` {state, reason?, finding?, on} (replaced each time; todo and done clear it) |

Projectors write only through `put_node`, `patch_node`, `put_edge` and
`delete_edge`, so both stores stay in step; no store method was added.

Pauses, seasons and equipment out of service (nothing about them runs on a
clock: each is worked out on read from its dates and the workspace's today):

- **A pause** says why, by whom and until when. It's over by itself on its
  return date; open-ended is allowed and flagged (`no_return_date`), and one
  back by itself is flagged `past_return_date` until a resume acknowledges it.
  While paused, the package and its layers raise nothing and their tasks are
  held: not raised on their own and not overdue. An open work order from it is
  frozen: still open, shown `paused`, and not late. Its late clock counts only
  days outside pauses (and seasons), so it carries on from the return.
  Missed visits aren't made up. With `full_visit` (the default), the first work
  order raised after the pause also carries every task due on a visit during
  it (a layer's day and an every-Nth task's turn included); without it the
  package carries on from its next visit.
- **A season** (`season`: {months} or {start, end} as MM-DD, across the new
  year allowed; `schedule.Season`) limits a package or layer to part of the
  year. Its visits outside it don't exist, nothing is raised, and an open work
  order isn't late while out of season. It isn't a pause: nothing needs
  pausing or resuming.
- **Out of service** is kept on the position or item node itself
  (`out_of_service` {from, until?, reason}, with `service_history`): the
  smallest model, since the node is what's out and every read already has it.
  A task on it, or on a position inside it, isn't due, raised or late while it
  holds (its next due is the return date), and a package leaves those lines
  off its visits and raises the rest. An item's mark covers the item's own
  tasks and positions inside the item, not the position it's fitted to.

Generating: `generate` first gives every active top package its turn (one work
order for the next visit inside the horizon, with a line per task due that day,
or lines added to the open one), then raises the other tasks one by one as
before, skipping every task in an active package. A workspace with no packages
generates exactly as before, with the same result. With packages, the result
also has `packages`, `lines_added` and `packages_skipped`.

`packages.propose` (a read) drafts packages from the live tasks on positions and
locations in no package, grouped by cadence bucket (within 10%: weekly,
fortnightly, monthly, quarterly, 6-monthly, yearly, multi-year), area (the
location, else the top of the position tree) and trade, each with a ready
`create` and warnings (intervals mixed in one bucket, a task with its own open
work order).

Not built yet: tolerance in hours, packages by use, shutdown packages, review
flags when a member changes after packaging, planned hours, and turning rounds
into packages.

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
