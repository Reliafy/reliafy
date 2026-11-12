# Reliafy API

Everything Reliafy's AI tools (MCP) can do, over plain HTTPS, from Python or
from the command line; plus pushing data from scripts, cron jobs or your CMMS
export pipeline, and sending files and photos.

> **Pro feature.** On Reliafy Cloud, API tokens need a Pro plan.
> (Self-hosted instances have it unconditionally — there are no plans.)

The same reference, page by page, is on the website: <https://reliafy.com/api-docs>.

## Authentication

Create a personal token in the app under **API access** (sidebar → Account).
Send it as a bearer header:

```
Authorization: Bearer rlf_XXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX
```

Each token has **scopes**, chosen when you create it:

| Scope | Allows |
|---|---|
| `ingest` (Push data) | the `/api/ingest/*` endpoints and `/api/import/models` |
| `read` | `/api/v1` reads and calculations: the read-only tools (`guide`, `get`, `list`, `analyse`, and Reliafy Maintenance's reads) |
| `write` | `/api/v1` creates; every tool that saves, changes, deletes or shares (`change`, `report_problem`, Reliafy Maintenance's writes and `maintenance apply`), and photo uploads |

A request outside the token's scopes gets `403`. A token that only has
`ingest` can push data but can never read your analyses; no token can touch
your account, billing or tokens. Tokens created before scopes existed keep
all three. Revoke tokens any time from the same page.

Rate limit: 120 requests/minute. Row limit: 5,000 rows/request.

---

## Every tool, over REST

Every action of every Reliafy MCP tool is also a REST call:

```
POST /api/v1/{tool}/{action}     # a tool with actions (or kinds): body = the action's arguments
POST /api/v1/{tool}              # a tool without actions (guide)
```

The body is a JSON object of the action's arguments, exactly as the MCP tool
takes them (the action itself is in the path). The answer is the tool's
result, the same JSON an AI assistant gets.

```bash
curl -X POST https://reliafy.com/api/v1/analyse/fit \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"data": [120, 340, 510, 700, 980], "censored": [0, 0, 1, 0, 0]}'

curl -X POST https://reliafy.com/api/v1/list/models -H "Authorization: Bearer $TOKEN"
```

- `GET /api/v1/tools`: the tools and actions you may call, each with its
  required and optional arguments.
- `GET /api/v1/openapi.json`: an OpenAPI 3.1 spec of every tool action, with
  its argument schema. Without credentials it covers the core tools; with
  them, everything that account may call. Generate a client from it, or use
  the Python client and command line below.

The earlier fixed routes (`GET /api/v1/models`, `POST /api/v1/fit`,
`POST /api/v1/strategy/optimal-replacement` and the rest) keep working as
they were.

There is one source of truth: the REST calls are built from the MCP tools
themselves, so a new tool action is on REST, in the spec and on the command
line as soon as it ships.

### Plans, limits and refusals

The REST calls are gated exactly as over MCP:

| Who | Gets |
|---|---|
| Pro, operators, self-hosted | every tool, no allowance |
| A signed-in Free account (session) | the same monthly allowance of tool calls as over MCP, without fitting, fleets and simulations; `guide`, `get account`, `get upgrade_link` and the data library's lookups (`list library`, `get library_record`, `list library_sources`) aren't counted |
| An API token on an account without Pro | `402` |
| Reliafy Maintenance tools | only accounts with Reliafy Maintenance (today: operators); everyone else gets `404` and doesn't see them in `/api/v1/tools` or the spec |

Statuses: `401` no or bad credentials · `402` a Pro-only tool or feature ·
`403` outside the token's scopes · `404` no such tool, action or item ·
`422` the arguments (the detail says which) · `429` the monthly allowance, the
rate limit, or too many calculations running at once · `503` busy, try again
in a minute · `504` the call ran out of time. The body is always
`{"detail": "…"}`, said plainly.

### Long-running calculations

As over MCP, a long simulation or search answers at once with a `job_id` and
`status` (`queued` or `running`). Poll it:

```bash
curl -X POST https://reliafy.com/api/v1/get/job -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" -d '{"id": "JOB_ID"}'
```

until `status` is `done` (with the result) or `failed`. The Python client and
the command line wait for you.

### Many maintenance changes in one call

Reliafy Maintenance's write actions can run as one batch, `POST
/api/v1/maintenance/apply`: a list of the `maintenance` tool's actions (`positions.create` and so on) with
their own arguments, in order, with `@ref`s between them (`"@p"` is op p's
id; `"@p.fitted.item.id"` a field of its result). Every operation is first run
on a throwaway copy of the workspace, so with any failure nothing is written
and the answer names the operation. A delete-type operation (`retire`,
`remove_*`, `void`, `cancel`, `merge`, `disconnect`, `unlink`,
`clear_coordinates`) needs `confirm`: the thing's name as it is now. The
answer has each operation's result, counts, the events written and `undo`,
the reverse operations.

```bash
curl -X POST https://reliafy.com/api/v1/maintenance/apply \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"operations": [
        {"ref": "p", "do": "positions.create", "args": {"name": "Feed pump A"}},
        {"ref": "f", "do": "failure_modes.add_function", "args": {"position_id": "@p", "text": "Deliver 40 L/s"}},
        {"ref": "ff", "do": "failure_modes.add_functional_failure", "args": {"function_id": "@f", "text": "No flow"}},
        {"ref": "m", "do": "failure_modes.add", "args": {"position_id": "@p", "functional_failure_id": "@ff", "text": "Bearing worn"}},
        {"do": "failure_modes.decide", "args": {"failure_mode_id": "@m", "consequence": "operational",
             "decision": {"outcome": "on_condition", "task": "Vibration check", "interval": 3, "interval_unit": "months"}}}
      ], "dry_run": false}'
```

A decision can combine tasks (RCM II's "combination of tasks": a regular
inspection plus a fixed-time replacement). Send `decision.outcomes` in place of
`outcome`, `task` and `interval`, one entry per task, and each one that
schedules work gets a task of its own on the position:

```json
{"do": "failure_modes.decide", "args": {"failure_mode_id": "@m", "consequence": "safety",
   "decision": {"outcomes": [
     {"outcome": "on_condition", "task": "Vibration check", "interval": 1, "interval_unit": "months"},
     {"outcome": "fixed_interval", "task": "Replace the bearing", "interval": 24, "interval_unit": "months"}]}}}
```

The entries are two or more tasks of `on_condition`, `fixed_interval` and
`failure_finding` (one kind may come more than once, each with its own task:
a weekly top-up and an annual deep clean), optionally with one `redesign`
beside them as the interim measure; `rtf` and `accept` stand alone. Reads add
`decision.outcomes` (each with its task, interval and `task_id`) beside the
first entry's `outcome` and `task`. Entries are told apart by their task: to
change a combination, send every entry back with the `task_id` it was read
with; an entry left out has its task taken off.
The app's own route takes the same body (`PUT
/api/maintenance/failure-modes/{id}/decision`).

An `on_condition` or `failure_finding` task says what's done when the check
finds something: `decision.on_found` ("Replace the bearing within 2 weeks"), or
a member's `on_found` in `decision.outcomes`. Left out of a `decide`, it is
kept while the kind of task stays; `""` clears it; it's refused on any other
kind of task. Reads return it in the same places. A failure mode's rationale
has one place, its notes (`failure_modes.update notes`, or `PATCH
/api/maintenance/failure-modes/{id}`): `decision.notes` on a `decide` is
deprecated and is added to those notes, and reads give `decision.notes` as the
mode's notes for older callers.

`decide` follows the RCM decision diagram (SAE JA1011, RCM II). `hidden`
(true or false) says whether the failure would go unnoticed in normal
operation; `consequence` is one of `safety`, `environmental`, `operational` or
`non_operational` (for a hidden failure, what the multiple failure would do).
`consequence: "hidden"` is still accepted as a deprecated alias for `hidden:
true`. A decision the diagram forbids is refused: `rtf` or `accept` on a safety
or environmental consequence, `failure_finding` on an evident failure, a
combination on an operational or non-operational one. Decisions saved before
are kept; their reads carry `advice`.

The evidence check covers every task of a combination. The decision's
`evidence` counts for each entry it fits (a degradation model for
`on_condition`, a replacement analysis for `fixed_interval`, a failure-finding
analysis for `failure_finding`; a report or a function's notes for any), and an
entry can link its own `evidence` where one piece can't cover them all:

```json
{"outcomes": [
   {"outcome": "on_condition", "task": "Vibration check", "interval": 1, "interval_unit": "months"},
   {"outcome": "fixed_interval", "task": "Replace the bearing", "interval": 24, "interval_unit": "months",
    "evidence": {"type": "strategy_analysis", "id": "<analysis id>"}}],
 "evidence": {"type": "degradation_model", "id": "<model id>"}}
```

The read's `status` is then `supported` (or `linked`) when every scheduled
task is evidenced, `partly` when some are ("Partly evidenced: the
fixed-interval task has none."), `unevidenced` when none are, or the worst
task's (`contradicted`, `stale`, `inconclusive`, named in `reason`). Each entry
of `decision.outcomes` carries its own check (`status`, `reason` or `summary`,
`evidence_from`: `own` or `decision`).

`dry_run` true checks and reports without writing; it's the default when a
batch deletes or has over 25 operations. `on_error` (`stop`, the default, or
`continue`) says what to do if an operation fails during the real run (rare:
a change made meanwhile). `idempotency_key` (yours, up to 64 characters):
the same key and operations within 24 hours answer with the first run's
result. At most 200 operations and 50 deletes per batch; `fit_class_model`,
`generate_rbd`, the imports and the workspace settings stay single calls.
The Python client has `Client.apply(...)`, the command line
`reliafy apply ops.json [--run]`, and `maintenance guide` topic `apply` the
worked examples.

A failure mode's FMEA and FMECA fields live on the same record as its RCM:
`maintenance failure_modes.score` (`failure_mode_id` plus any of `severity`,
`occurrence`, `detection` (whole numbers 1–10), `cause`, `effect_local`,
`effect_next`, `effects` (the end effect, the RCM's failure effects),
`detection_method`, `action`, `action_owner`, `action_due` (YYYY-MM-DD),
`action_status` (open, in_progress, done), `failure_rate`, `time_unit`,
`rate_source` (entered, model, data), `mode_ratio` and `loss_probability`
(0–1), `operating_time`, `severity_class` (I–IV); `clear` lists fields to
blank). Reads answer with the computed `rpn` (S × O × D), `ap` (the action
priority, H, M or L) and `cm` (β × α × λ × t), never stored, and each position
in `get.rcm` carries an `fmea` summary (scored, high, medium, low, max_rpn,
cr). A mode may sit directly under a function with no functional failure yet
(`function_id` on `failure_modes.add`, `assign` and `move`); the RCM reads list
it in the function's `modes`. `products.add_sample` adds the Survey
quadcopter, a ready-made product with invented numbers: its design fully
scored (on Products, not in the asset tree), and the life models and analyses
it stands on saved in the workspace as its own (`own_records`; `kept_shared`
names any the plan's storage had no room for).

How often to do a task: `maintenance rcm.pf_interval` needs only
the P-F interval (`pf_interval` with `pf_unit`): it answers half the P-F
interval, or the net P-F interval (less `act_time`, the time needed to act)
when that's tighter. Costs are optional and never change it: with
`inspection_cost`, `found_cost`, `failure_cost` and `onset_rate` (failures a
year), `cost_optimal` adds the cheapest interval and whether the check pays.
`maintenance rcm.ff_interval` (a protective device's
`failure_rate` a year, a `model_id`, or `distribution_id` + `params` +
`model_unit`) gives the longest test interval that meets
`target_unavailability`; the costs `test_cost`, `repair_cost`, `demand_rate`,
`consequence_cost` are optional and add `cost_optimal` (alone, they give the
cheapest). Both take `current_interval` and `current_unit` for the task's
numbers now, answer with `recommended` rounded down to hours, days, weeks,
months or years, and are free on every plan. The fixed-interval one is `analyse optimal_replacement`. The
app's own routes are `POST /api/maintenance/rcm/interval/on-condition` and
`/failure-finding`; a saved strategy analysis of kind `on_condition_interval`
or `failure_finding_interval` stands as an on-condition or failure-finding
decision's evidence (contradicted when the task's interval is longer than the
P-F interval, or than the longest that meets the target).

```bash
reliafy maintenance rcm.pf_interval --pf-interval 10 --pf-unit weeks --act-time 1
reliafy maintenance rcm.ff_interval --failure-rate 0.1 --target-unavailability 0.01
```

(These two were `rcm.interval_on_condition` and `rcm.interval_failure_finding`
until Nov 2026; `parts.build_positions` was `parts.positions_from_structure`.)

Life models on positions (the Explorer's Modelling tab): `maintenance
models.link` attaches a model to a position (a link, never a copy): a saved one
(`model_id`, with `model_type` `model` (the default), `recurrent_model`,
`degradation_model` or `alt_model`), the position class's (`from_class: true`)
or a new fit from its failure history (`fit: true`, Pro; `distribution`,
`scope` `auto` (its own, else its class's pooled history), `position` or
`class`). `failure_mode_ids` names the failure modes it describes (none: every
failure there; a fit then counts failures by other modes as suspensions);
`replace_link_id` swaps one model for another. Accelerated-life and covariate
models attach as they are (their stress is set where they're used, an RBD block
or a calculation). `prediction: {environment?, mission_time?, assign?}` (an
`assign` entry for an NSWC-11 part type carries `conditions` and, for a rate per
cycle, `cycles_per_hour`) makes a
parts-count prediction from the position's parts list (and those inside it; on a
product design, plus the bill-of-materials parts they don't list), `assign` giving each
part number a handbook `record_id` (and `quality_factor`): it's saved as a
reliability prediction (its page links back to the position) and as an
exponential model at its rate, and attached with role `prediction`. The app
previews it with `POST /api/maintenance/positions/{id}/prediction`.

`bind: {source: nswc | alt | ph, ref, fixed?: {input: value}, roles?: {input:
design | use | environment}}` links a covariate model (an NSWC-11 record, an
accelerated life model or a proportional-hazards model) with some, all or none
of its covariates fixed at the position. An NSWC-11 model with every input
fixed is saved as a constant-rate exponential; otherwise the link keeps the
binding and an RBD built from the tree gets a bound block. A bound block takes
each open input from its own `covariate_values`, else the diagram's
`conditions` (`[{name, role: use | environment, unit, value}]`, matched by the
input's key, symbol or label and unit, or named by the block's
`covariate_map`), else a default the model gives; an analysis with one still
missing is refused, naming each block and what it needs. `POST
/api/rbds/binding-inputs {binding}` lists a model's inputs (the same shape for
every source) and `POST /api/rbds/bound-blocks {graph}` each bound block's
open inputs, the value each takes and where it came from.
An RBD row: `rbd_id` links an existing diagram; `new_rbd: {repairable, start}`
starts one of the position's own on any position, a leaf included (`start`:
`blank`, just In and Out, or `self`, one block for the position with its life
model in use, a flagged placeholder where it has none); `build_rbd: true` makes a new
one from the positions one level inside (each block the child's model in use;
else its class's fitted model; else, for a sub-assembly with positions inside,
its own RBD built from them, as a sub-system block; a flagged placeholder only
where there's none of these; each block's `model_source` says which), wired
by their connections and redundancy groups, in series where there are none,
saved under Design › Systems as "<position> (from the tree)". A position has
one built diagram: `build_rbd` where it already has one saves nothing and
answers with that row and `existing: true`. With `replace_link_id` (its RBD
row) it's rebuilt into the same diagram, adding new positions, giving a block
still on a placeholder the model its position has now, and keeping edits.
A repairable RBD linked to a position takes each tree-linked block's
maintenance from that position's tasks, read at calculation time (nothing is
copied into the diagram): `POST /api/maintenance/rbd-tree-plan {rbd_id, graph?}`
gives, per block, the position, its tasks, the one modelled (kind, interval in
the diagram's unit, time off-line, cost, package) and what's blank, and
`GET /api/maintenance/rbd-plan-uses?task_ids=` the RBDs whose plans read those
tasks. An availability answer for such a diagram carries `tree_plan` (the
task versions used); when the saved simulation used older versions,
`simulation_status.tasks_changed` names the tasks and it isn't rerun unasked. `POST /api/rbds/validate` (and `GET /api/rbds/{id}/validate`) also
answer `series_hints`: which of the `warnings` are the "like blocks wired in
series" hints (one per run of like blocks), where there are any. `use_link_id` makes one of the position's rows
its model in use (by default its own life model, else its RBD, else its
prediction): what its roll-up reports, what the RCM offers first and what a
parent's RBD block takes. `GET /api/maintenance/position-models/{id}?age=`
adds an RBD's system reliability at that age.

An item class's fleet (the Explorer arranged by Classes): `GET
/api/maintenance/item-classes/{id}/fleet` lists the positions whose fitted
item is of the class or a class inside it, as `members`: `{position: {id,
name, tag, position_class}, item: {id, name, serial}, item_class, in_service,
age` (days)`, model` (the condition and life model linked to the position, or
its position class's; null with none)`, point, last_reading: {on, value,
unit}, n_readings, covariates, scored, why}`. A scored member adds `risk`
(the chance of failing within each of `horizons`: 30, 90 and 365 days from
`today`), `survival`, `median_remaining` (days; `median_reached` false means
at least that long) and `marker_now`; members come highest 90-day risk first.
Each is scored from its own data: the item's age from its in-service date
(else its first fitting), the readings of its condition point in the model's
reading unit since then, and the model's covariates from value conditions of
the same name. `scored` false with a model carries `why` in plain words and
what to do. `?position_id=` answers that one `member` with `unit` (its
survival curve from now and its reading's path, in its model's own time
unit) and the `model`. `?within=` (one asset, as the Explorer opened on it
shows it: a position id for that position's tree, positions its fitted items
carry included; or a location id for every position at that place or a place
inside it) keeps only the members inside it; the counts, `models`,
`position_classes` and `note` are then that asset's alone (404 for an unknown
id). The same read for the whole
register is `maintenance get.item_class` with `fleet: true` (`POST
/api/v1/maintenance/get.item_class`; `reliafy maintenance get.item_class
--id … --fleet true`).

One position on its own (the Explorer's Condition monitoring tab on a
position): `GET /api/maintenance/positions/{id}/condition` answers `{position,
item_class, today, age_unit, horizons, member, model, why}`. `member` is the
position's row as above, with `unit` when it is scored, whatever its item's
class (`item_class` null with none); with nothing fitted `member` is null and
`why` says so. `model` is the condition and life model that scores it, null
with none linked. It is a read for the page, with no tool or CLI twin.

Missions (the Explorer's Missions tab): a non-repairable RBD can carry several
named phased missions over the same blocks, in `graph.missions` (`[{id, name,
phases}]`; the diagram's own `phases` reads as one more mission, id `mission`,
named by `mission_name`). A phase is `{name, duration, not_needed?: [block
id], standby?: [block id], votes?: {vote node id: inputs needed}, values?:
{covariate name: value}, block_values?: {block id: {input key: value}}}`:
each block is working in a phase unless listed. `not_needed`: the phase works
without it, while its clock keeps running (a failure then is found by a later
phase that needs it). `standby`: it is there but not running, so its clock
stops for the phase (it neither ages nor fails in it) and it counts as working
if it was working when the phase began; switching over is taken as perfect.
A block is in one list or neither. `values` sets a Use or Environment
covariate once for every bound block it feeds in that phase, `block_values`
one block's own. The blocks age across the whole mission; a block whose
covariates change from phase to phase carries its age into the next (and
can't also stand by). A calculation's phase rows add `not_needed` and
`standby` (block labels) and its `notes` say what each state means.

One RBD per mission: `POST /api/maintenance/positions/{id}/missions {name?}`
adds a mission to a position with an RBD of its own, built from the positions
inside (as Build from what's inside builds it: placeholders flagged), or,
where it has nothing inside, copied from the position's non-repairable RBD, or
else one block, the position's own model in use (refused when it has none).
It is saved as "<position> — <mission>" with `graph.mission_of:
{position_id}` and answers `{rbd: {id, name, updated_at}, mission, position_id,
notes, placeholders, built_from` (`tree`, `copy` or `model`)`}`. In `GET
/api/rbds` such a diagram carries `mission: {name, position_id, position}`. The mission is that RBD's own (id `mission`, named by
`mission_name`, kept with no phases); it isn't linked as one of the position's
models. Deleting it (`DELETE /api/rbds/{id}/missions/mission`) deletes its
RBD. Missions stored on a position's RBD keep working as before.
`GET /api/maintenance/position-missions?position_ids=` lists each
position's RBDs and their missions (a position has its own RBDs' missions,
never a parent's); a mission's own RBD is a row with `link_id` null and
`rbd.mission_rbd` true. `has_model` lists the positions whose model in use can
be a mission's one block. A mission in a list is `{id, name, phases` (how many)`,
phase_names, phase_durations` (each phase's own length, in the same
order)`, duration` (the whole mission)`, unit, result?}`. On an RBD: `GET /api/rbds/{id}/missions`, `POST
/api/rbds/{id}/missions {name?, phases?}`, `GET|PUT|DELETE
/api/rbds/{id}/missions/{mission}` (`PUT {name?, phases?,
expected_updated_at?}`; `GET` adds the blocks, vote nodes and every open
covariate with the blocks it feeds and, per phase, the value each block uses
and where it comes from), and `POST /api/rbds/{id}/missions/{mission}/calculate
{phases?}`: the chance of completing it, each phase's failure probability,
reliability at its end and weakest block (the one whose failures end the most
missions in that phase). A phase missing a value waits: `reliability` is null,
`through` says how far the mission was worked out and `needs` which blocks need
what. Over MCP: `analyse rbd_mission` and `change rbd_mission`.
`fit: true` with `data` (`position`, `class`, or `both`: the position's history
with its class's other positions' history as the prior) and `method` (`mle`:
a plain fit with 95% confidence bounds; `bayes`: with a `prior`, 90% credible
intervals) is "Fit a life model…": `prior` is `{kind: class}` (the class's
history as a power prior, SurPyval's `prior.from_data`, weighed by `trust`:
`close` all of its evidence, `guide` half, `start` a fifth), `{kind: model,
model_id}`, `{kind: params, distribution, params, unit}`, `{kind: around,
distribution, unit, params: {alpha: {about: 4, between: [3, 6]}, beta:
{between: [1.5, 3]}}}` (90% between the bounds, "about" optional; a parameter
left out is the data's), `{kind: library, record_id, covariates?, shape?: [low, high]}` (a
data library record under its covariates: a pipe's length, the clock and
running hours, the demands a year for a probability per demand; on an
exponential the record's gamma, scaled by them, is the prior exactly, a
closed-form update; on a Weibull or lognormal a prior on the mean
life, `around(1/rate, between=(1/p95, 1/p05))`, with the shape between the
bounds, 0.5 to 5 by default; a handbook rate has no spread and is refused) or
`{kind: b10, …}`.
`library_record_id` attaches a data library failure rate as the position's
model (role `library`) with every one of its `covariates` given (a pipe's
length, the clock, the demands a year, a handbook part's environment): an
exponential at the record's mean rate per hour under them, saved in Models
with the source's 5–95% range as its interval and the record id, citation and
covariates kept. To fix some at the position and set the rest in an RBD, use
`bind` with `source: library` (any record) or `component`.
The class can't be both the data and the prior. The app previews with
`POST /api/maintenance/positions/{id}/fit-preview` (a refusal comes back as
`{refused: words}`). `analyse bayes_update` takes `baseline:
{class_power_prior: true, position_id}` for the same prior.
`fit: true` with `baseline` or
`trust` saves a Bayesian update instead (below). `maintenance models.unlink`
(`link_id`) takes one off; the model stays in Models. `get.position` lists
them (`models`). A built item takes its product design's links when it's
built, as it takes the RCM. The app's own routes:
`GET /api/maintenance/position-models` (every link with its model's kind,
headline numbers with bounds, data counts, a one-word quality and what uses
it), `GET /api/maintenance/position-models/{id}`,
`POST /api/maintenance/positions/{id}/models` and
`DELETE /api/maintenance/position-models/{id}`. A failure mode's interval
calculators start from the position's model for that mode (else one for every
failure there) when the decision has no evidence of its own.

```bash
reliafy maintenance models.link --position-id P --model-id sample-model-bearings-weibull
reliafy maintenance models.link --position-id P --fit --scope auto
reliafy maintenance models.link --position-id P --library-record-id nrc-inl-2020:mov-sop
reliafy maintenance models.unlink --link-id L
```

A Bayesian update of a baseline with a few failures: `analyse bayes_update`
(Pro) takes a `baseline` (`{model_id}`, `{distribution, params, unit}` or a
belief `{b10: {value, low, high}, shape: {low, high}, unit}`), `trust`
(`close`, `guide` or `start`: each number within about 10, 30 or 60%; a
fitted baseline counts as all, half or a fifth of its evidence), `x` and `c`
in the baseline's unit, and optional `age`. It returns what the prior says,
the posterior medians with 90% credible intervals, B10 and mean life, and what
moved the baseline, in words; it saves nothing. With no data the baseline
stands as given. On a position, `maintenance models.link` with `fit: true` and
`baseline` / `trust` (and `exclude`: fitment ids to leave out) updates the
baseline with the position's history, saves it as a non-repairable model
(`method: "bayesian_update"`, its bounds credible intervals) and attaches it;
the app previews with `POST /api/maintenance/positions/{id}/bayes` and saves
with `/bayes/save`. It's computed by SurPyval's `fit_bayes`.

```bash
reliafy analyse bayes_update --baseline '{"model_id": "M"}' --trust guide --x 1400,1900,2500 --c 0,0,1
```

A function's notes and rationale (`notes` on `failure_modes.add_function` /
`update_function`, up to 25,000 characters on a function) hold the working
behind its performance standards. `standard_basis`, the separate working
before Nov 2026, is still accepted but deprecated: it is added to the notes
under a "Working" line. Reads keep `standard_basis`, `has_basis` and
`basis_preview` describing the notes, and a working written before reads as
part of the notes. Evidence `{type: "working", id}` on a decision links that
function's notes and rationale.

A functional failure's causes (`failure_modes.link_cause`,
`functional_failure_id` the effect and `cause_id` the cause) may be on any
position of the same tree: inside the effect's position, beside it or on the
same one. A failure causing itself, a loop and a cause on another tree are
refused; a move that takes either end to another tree drops the link and says
so. Things put on the wrong position move with their history intact:
`failure_modes.move`, `move_function`, `move_functional_failure`,
`tasks.move` (a task's open work orders go with it, listed in
`work_orders_moved`; a task with work done stays) and
`measurements.move_point` (`point_id`, `position_id`: a position's
measurement point with its readings and any open alarm work order; the app's
route is `POST /api/maintenance/points/{id}/move`).

A value someone sets rather than measures (a chlorinator's output %, a pump
timer's hours a day) is a **setting**: `measurements.add_point` with
`kind: "setting"` (optional `range_min` / `range_max`, a sanity check), or an
existing point changed with `measurements.update_point` `kind: "setting"`. Its
reads carry `changes` (each change, what it changed `from`, and the work order
it was set at). Readings and settings taken during a work order go in
`work_orders.close` or `work_orders.update` as `readings: [{point_id, value,
unit?, on?, task_id?, note?}]`, or one at a time with `measurements.record`
and `work_order_id` (`task_id`); readings read back with `work_order_id`,
`task_id`, `work_order` and `task`. `get.work_order` lists what it asks for
in `reading_points` and what was taken in `readings_taken`. Example: the
seasonal change-over records the new chlorinator output with
`reliafy maintenance work_orders.close --work-order-id W --actions '[{"kind":
"other"}]' --readings '[{"point_id": "CHL", "value": 60}]'`.

What doing a task needs (its LSA record: the how, where the RCM gives the what
and why) is `tasks.set_resources` (`task_id`, `resources`): `labour`
[{trade, people, hours}], `tools` [{name, qty?, note?, point_id?}] (point_id:
the measuring point or signal channel an instrument reads), `spares`
[{part_id? | name, qty}], `consumables` [{name, qty, unit, cost?}], `access`
{downtime_hours?, permits, isolation?, access_equipment?}, `method` and
`duration_hours`. Each section sent replaces that one; null clears it. Every
task read carries `resources` (with `labour_hours`, `people`,
`materials_cost`), and each package in `list packages` its `rollup` (labour by
trade, tools, spares, consumables: what a visit brings). The app's routes are
`PATCH /api/maintenance/tasks/{id}` with `resources`, and
`GET /api/maintenance/tasks/{id}/lsa` (the task, the failure modes it serves,
and the points, channels and parts its lines can pick from).

When a calendar task first falls due is its `start`: `tasks.create`,
`tasks.update` and `failure_modes.add_task` take `start` (a date like
`2027-10-01`), and the task falls due then and every interval after (a
12-monthly summer task made in November can first fall due next October).
Left out, it falls due one interval from today (or from `last_done`);
`tasks.update start ''` clears a date set. Task reads carry `next_due` and
`first_due` (the date set, while it stands: until the task is done on or
after the day it was set). The app's routes take `start` too:
`POST /api/maintenance/positions/{id}/tasks`,
`POST /api/maintenance/failure-modes/{id}/tasks` and
`PATCH /api/maintenance/tasks/{id}` (null clears it).

Everything in the tree can be taken out of use and brought back (`retire` /
`restore` on positions, locations, items, parts, manufacturers, measurement
points, tasks, failure modes, classes, conditions, groups, connections and
document links): nothing is erased, and `maintenance list.events`
shows what changed, with the ids to restore.

Failure reports (the `failure_reports` area: `file`, `update`, `set_status`,
`investigate`, `add_action`, `update_action`, `verify`; reads `get
failure_report` and `list failure_reports`) record what failed at a position
and what was done about it, from the report through investigation, corrective
actions and verification to closure. A list is scoped to a position (and, by
default, every position inside it), a location, an item or a part number, or
the whole workspace, with filters by status, consequence, failure mode and
date; `maintenance guide` topic `failures` has the loop.

Work packages (the `packages` area: `propose`, `create`, `update`,
`add_task`, `remove_task`, `pause`, `resume`, `retire`, `restore`; reads `get
package` and `list packages`) bundle the tasks done on one visit, so each
visit raises one work order. `packages.propose` drafts them from the tasks in
no package (`position_id` or `location_id` for one branch or area); with
`weekday` (`monday` … `sunday`) the drafts visit on that day and the longer
cadences are layers on the shortest in each area and trade (monthly on the
first Saturday, quarterly on the first Saturday of every 3 months). Each draft
then has a `ref`, `layer_of` and `cadence_text`, and a layer's `create` has
`parent_id: "@<its top's ref>"`, so the agreed drafts go straight into one
`maintenance apply` (each operation's `ref` set to its draft's). The app's
own routes do the same: `GET /api/maintenance/packages/propose?weekday=`,
`POST /api/maintenance/packages/batch` (`packages`: the creates, all or
nothing) and `GET /api/maintenance/packages?position_id=` (those there or
inside it, or holding a task there). `GET /api/maintenance/task-table?position_id=` (or
`location_id=`) is the Explorer's Packages tab: every task there and below, one
row each, with its failure modes, kind, interval, trade, next due and package.

### Things only the API can do

MCP tool calls carry JSON, not files, and an agent calls an action when it wants it done, not later. These
have no MCP twin, on purpose:

| Call | Does |
|---|---|
| `POST /api/v1/maintenance/photos?target_id=…&caption=…` | Adds a photo to a maintenance position, item, location or work order. The body is the image (JPEG, PNG, WebP or HEIC; at most 20 MB), or multipart with a `file` field. Cleaned and stripped of camera and location metadata, like a photo added in the app. Reliafy Maintenance only; `write` scope. |
| `PUT /api/uploads/{upload_id}?t=…` | Sends a file's bytes to the single-use link from `change upload_create` (no other credentials; at most 30 MB). Then import it: `change dataset_upload`, `change import_rbd`, `change import_excel` or `change rbd_upload_outage_log` with that `upload_id`; a PDF (purpose `document`, at most 20 MB) goes on a maintenance item, position or class with `maintenance attachments.add_document`. |
| `POST /api/v1/maintenance/sync/push` | Sends up to 50 changes a device queued while it had no connection, in the order it made them: the maintenance tool's own work-order and reading actions, each with an id the device made, so one sent twice is recorded once. See [maintenance-sync.md](maintenance-sync.md). Reliafy Maintenance only; `write` scope. |
| `POST /api/v1/maintenance/sync/photo?op=…` | Sends one queued photo (the image as the body), recorded once however often it is sent. Reliafy Maintenance only; `write` scope. |
| `POST /api/v1/maintenance/sync/pack` | Everything a device needs to work with no connection, in one answer: the open work orders in full, their list rows and the parts catalogue. Reliafy Maintenance only; `read` scope. |

#### Field reports

A field report is what someone saw, as they recorded it: notes, photos, sound
recordings and PDFs, optionally about positions, locations, items or work
orders. It changes nothing else and proposes nothing; a person or their agent
reads it later and makes any changes with the ordinary tools, then marks it
`parsed` and `done`. Reliafy Maintenance only. These routes are REST and CLI
only: a report and its attachments are sent together, and bytes can't travel
in an MCP tool call.

| Call | Does |
|---|---|
| `PUT /api/v1/maintenance/captures/{capture_id}` | Makes a report under an id the sender made (a UUID). Body: `notes`, `taken_at` (device time with offset), `device_tz`, `about` (ids), `location` (`{lat, lon, accuracy_m}`, only when its author chose to add it), `media_expected`. Sending it again answers the same report, unchanged (`created: false`). |
| `POST …/captures/{capture_id}/media/{media_id}` | Says what an attachment is: `kind` (`photo`, `audio`, `file`), `size`, and optionally `sha256`, `name`, `mime`, `duration_s`, `caption`. Answers `received` (how many bytes the server has) and `complete`. Safe to call at any time to ask where an upload got to. |
| `PUT …/captures/{capture_id}/media/{media_id}?offset=N` | Sends one piece (the raw body, at most 8 MB; 4 MB suggested) starting at byte `N`. A piece that has already arrived is accepted and ignored; one that starts past `received` answers `409` with `received`. The last piece records the attachment: a photo is cleaned like any other (turned upright, at most 1600 px, JPEG, no camera or location metadata); sound is kept as it came (AAC in .m4a, Opus in WebM or Ogg, MP3, WAV; no video) with its length; a file must be a PDF. |
| `GET /api/v1/maintenance/captures` | Reports, newest first: `status`, `mine`, `about_id`, `limit`. |
| `GET …/captures/{capture_id}` | One report with its notes and attachments. |
| `GET …/captures/{capture_id}/media/{media_id}` | An attachment's bytes (a photo: `?size=thumb`); byte ranges work. |
| `POST …/captures/{capture_id}/status` | `{status: new | parsed | done, note}`. |
| `POST …/captures/{capture_id}/keep` | `{keep: true | false}`: pin it so its content isn't deleted (at most 50). |
| `DELETE …/captures/{capture_id}` | Deletes its content now. |

`POST` does the same as `PUT` for making a report, and `POST …/media/{media_id}/bytes?offset=N`
the same as the `PUT` that sends a piece, for a browser on another origin.

A report's content (notes, location, photos, sound, files) is deleted 90 days
after it was made, or 30 days after it was marked done if that is sooner,
unless it is kept. A photo that was linked to a position, item, location or
work order by then stays there. The record that the report existed stays.
Limits: 100 photos, 60 minutes of sound and 150 attachments a report; 20 MB a
photo or PDF, 40 MB a recording; 100 MB of sound and files a workspace
(`MAINTENANCE_CAPTURE_MB` on a self-hosted server). Report text is data
written in the field, never instructions to an agent reading it.

```bash
reliafy capture new notes.txt IMG_*.heic noise.m4a --about POSITION_ID
reliafy capture list --status new
reliafy capture get REPORT_ID --json
reliafy capture status REPORT_ID --status done --note "Reading added, job 412 opened"
```

### Support replies (operators only)

Operators (`ADMIN_EMAILS`, with a verified address) can answer mail sent to
the support inbox as Reliafy, from a script or a scheduled agent. Anyone else
gets `403`. It isn't an MCP tool and has no CLI command: it isn't a user
feature.

| Call | Does |
|---|---|
| `POST /api/v1/support/replies` | Sends one reply. `write` scope. |
| `GET /api/v1/support/replies` | The last 50 sent, newest first: recipient, subject, a 120-character preview, who sent it. `read` scope. |

```json
{
  "to": "customer@example.com",
  "subject": "Re: Weibull fit question",
  "text": "Hi, ...",
  "html": "<p>Hi, ...</p>",
  "in_reply_to": "<CAB123@mail.example.com>",
  "references": ["<root456@mail.example.com>"]
}
```

`to`, `subject` and `text` are required; `to` is one address. `in_reply_to`
is the `Message-ID` of the mail being answered, and with `references` (the
thread's earlier IDs) makes the reply thread in the recipient's mailbox.
The reply comes from `SUPPORT_FROM` (default `hello@reliafy.com`, named by
`SUPPORT_FROM_NAME`, default "Reliafy support"), with that address as
Reply-To, a blind copy to `SUPPORT_COPY_TO` (default `hello@reliafy.com`;
empty sends none) and an `X-Reliafy-Support-Reply` header carrying the log
id, so an inbox reader can skip its own copies. It sends over the server's
SMTP settings and answers once the mail server has taken it: `200` with the
log entry (including the new `message_id`), `502` if the mail server refused,
`503` if the server has no SMTP settings, `429` past
`SUPPORT_REPLIES_PER_HOUR` (default 20, shared by every caller), `422` for a
bad body. Every attempt is logged in `support_replies` without the message
body.

### The reliability data library

Published generic failure data (failure rates and probabilities of failure
on demand), each record cited with its source and licence. It's the same for
everyone, so it's readable without an account:

| Call | Does |
|---|---|
| `GET /api/library/search?q=…&source=…&equipment_type=…&kind=…&failure_mode=…&use=…&facets=true&page=1&page_size=25` | Matching records, best first, 25 a page (at most 100), with `total`, `pages` and `counts` by equipment type, kind and source. `kind` is `rate`, `per_demand`, `life` or `covariate_model`; `failure_mode` is a failure mode's name (any case). `facets=true` adds `facets`: for equipment type, failure mode and kind, how many records each choice would give with the other filters (and `use`) kept. `use` (`model` or `prior`) keeps only the records usable as that once their covariates are given (a model: every record but a covariate model, which goes on a position; a prior: those with a spread, so no handbook rate), and `left_out` counts what it hid, by why. |
| `GET /api/library/records/{id}?environment=…` | One record in full (values, spread, evidence, conditions, citation, licence and notes), its `covariates` (below), the `components` it's a mode of, and `block_model`: the model an RBD block would use. A handbook rate (MIL-HDBK-217F) depends on the environment the part works in: give `environment` (e.g. `GF`, ground, fixed) for its block model; without it, `environments` lists the rate in each. |
| `POST /api/library/records/{id}/evaluate` | A record's rate under its covariates, or a component's chance of failing over a period (`id` a component id): body `{covariates: {key: value}}` (`values` is the old name; a missing covariate takes its default). Answers `{ok: true, result, warnings}` or `{ok: false, problems, missing}`. A covariate model's (NSWC-11) `result` is `{total, unit, modes, derived}`, each problem or warning naming the limit and the handbook's page; any other record's is `{failure_rate, unit, clock, bounds, rate_uncertainty, assumptions, covariates}` (a probability per demand adds `probability`, and is a rate only with `demands_per_year`). Saves nothing. |
| `GET /api/library/components?source=…&q=…` | The components (NRC/INL): an equipment type in one of the report's pooling groups (normally standby, normally running, a system), its failure modes together. |
| `GET /api/library/components/{id}` | One component: its `modes` (each a record with its `trigger`: per demand, per hour of running (first hour, after the first hour) or per calendar hour; and whether it's added), its `inputs` and `how` they combine. |
| `GET /api/library/sources` | The sources, their licences and what each holds. |

The same reads are on the tools API: `POST /api/v1/list/library`
(`query`, `source`, `equipment_type`, `record_kind`, `components`, `page`, `page_size`), `POST
/api/v1/get/library_record` (`id`, a record or component id; `covariates`, adding `evaluation`; `conditions` and `environment` are the old names) and `POST
/api/v1/list/library_sources`, and on the command line `reliafy list library --query "motor-driven pump"`. Library lookups are never counted against the
Free plan's tool calls. These are generic estimates (today: U.S. nuclear
power plant industry averages, and base failure rates for electronic parts
from the MIL-HDBK-217F prediction handbook, and covariate models for mechanical
parts from the U.S. Navy's NSWC-11 handbook: a base rate × condition factors,
each input with the handbook's limits; CDNSWC and the Navy did not take part in
or approve Reliafy), not your own equipment's data;
show each record's `licence.attribution` with its numbers. In the app the
library's handbooks are built-in, read-only libraries under Libraries (`/libraries`, one page per source and
per record). Its **Use as a model…** is `POST /api/models/from-library`
(`record_id`, a record or component id; `covariates`; `name?`: an exponential model under them, counted against the Free
plan's saved models; `length_ft` is the old name of the pipe's length) and **Use as a prior…** on a dataset is `POST
/api/models/fit-with-prior` (`dataset_id`, `time_column`, `censor_column`,
`c_invert`, `unit`, `distribution`, `prior: {kind: library, record_id,
covariates?, shape?}`, `save` with `name` to keep it).

**A record's covariates.** Every input a record needs before it gives a rate is
a covariate of the record, in the shape NSWC-11's inputs have (`key`, `label`,
`unit`, `kind` number or choice, `role` design, use or environment, `default`,
`limits`, `help`; `needed_if` asks for one only when another has a value, and
`needed_when`, a list of `{key, op, value}`, only while every comparison holds):

| Record | Covariates |
|---|---|
| NRC/INL pipe leak, per foot | `length_ft` (design; no default) |
| NRC/INL rate per hour | `clock` (use: `calendar` or `operating`, the record's own by default); `running_hours_per_year` (use, 0 to 8,760; asked for only when the clock is changed) |
| NRC/INL probability per demand | `demands_per_year` (use; no default): the probability × demands a year is its rate per calendar hour |
| MIL-HDBK-217F | `environment` (environment: a handbook symbol, with its πE or generic rate; no default); `quality` (design: a parts-count part's grade, its lowest by default) or `quality_factor` (design: πQ as a number, 1, not applied, by default) |
| NSWC-11 | its own inputs (its conditions), and `cycles_per_hour` (use) for a rate per cycle or operation |
| NRC/INL component | `demands`, `running_hours` and `calendar_hours` (8,760 by default) over a period, and `length_ft` for a pipe |

A covariate with no value and no default is never guessed: the answer says
which are `missing`. A component's modes are independent competing risks:
P(fails over the period) = 1 − Π(1 − q)^demands × exp(−Σ λ × its hours), each
run's first hour at the first-hour rate where the source gives one; the plain
sum (the rare-event approximation the NRC's risk models use for a mission) and
the constant rate −ln(R) ÷ calendar hours come with it. `GET /api/library/used` lists the
records behind the user's latest library models. The record format
and the sources: [library.md](library.md).

**Libraries.** A library holds datasets and models, each a **snapshot** taken
when it was added (a dataset's rows, measurements and reading; a model's whole
saved document), so later edits in the workspace don't change it; the owner
can take a new one with *Update from the original* (the entry's `version` goes
up). Nothing is added unless someone asks. A model needn't be fitted to data
(from parameters, a handbook, a published source: its `basis_text` says which);
a model whose dataset is also in the library names it (`fitted_on`). A
library belongs to one workspace and counts as one saved item toward the Free
plan's storage limit, whatever it holds. It is **private** (its workspace),
**shared with workspaces** (their IDs: a personal workspace's is the user id, a
team's the team id; read-only for them) or **public** (anyone can read it,
signed out too). Making it public needs a licence (`public-domain`, `cc0`,
`cc-by-4.0` or `own-cc-by-4.0`: your own data under CC BY 4.0), a source or
citation, and `rights_confirmed: true`. Only the owner changes a library;
anyone who can read it can **use** an entry: a copy in their own workspace
(counted as that dataset or model) whose `from_library` names the library,
entry and version. The built-in handbooks are listed as read-only public
libraries. Reads take an optional sign-in and are never cached.

| Call | Does |
|---|---|
| `GET /api/libraries` | Every library you can see: yours, shared with you, public (others', then the built-in handbooks); with your `workspace_id` and the `licences`. |
| `GET /api/libraries/entries?type=data\|model&q=` | Every dataset (or model) in any library you can see. |
| `GET /api/libraries/{id}` | One library with its entries. |
| `GET /api/libraries/{id}/entries/{entry_id}` | One entry: a dataset's first 50 rows and reading, a model's parameters. |
| `POST /api/libraries` | Make one: `name`, `description?`, `notes?`, `source?`, `citation?`. 402 past the Free limit. |
| `PATCH /api/libraries/{id}` | Change `name`, `description`, `notes`, `source` or `citation`. |
| `PUT /api/libraries/{id}/visibility` | `visibility` (`private`, `workspaces`, `public`), `workspaces?`, `licence?`, `source?`, `citation?`, `rights_confirmed?`. |
| `DELETE /api/libraries/{id}` | Delete it and its entries (what they were taken from, and copies, stay). |
| `POST /api/libraries/{id}/entries` | Add `dataset_id`, or `model_id` with `collection?` (`models`, `recurrent_models`, `alt_models`); `source?`: the entry's own source. |
| `DELETE /api/libraries/{id}/entries/{entry_id}` | Take an entry out. |
| `POST /api/libraries/{id}/entries/{entry_id}/refresh` | Update from the original. |
| `POST /api/libraries/{id}/entries/{entry_id}/use` | Copy it into your workspace: `name?`, `with_dataset?` (a model's dataset too, when it's in the library). |

The older `/api/library/mine` calls still work for life-model records. Over
MCP and `/api/v1`: `list kind libraries` (`scope?`), `get kind library` (`id`,
`entry_id?`) and the `change` actions `library_create`, `library_update` (also
`visibility`, `workspaces`, `licence`, `source`, `citation`,
`rights_confirmed`), `library_delete`, `library_add` (`library_id`,
`dataset_id` or `model_id`, `model_collection?`, `source?`), `library_remove`
and `library_use` (`library_id`, `entry_id`); on the command line `reliafy
change library_create --name "Site pumps"` and `reliafy change library_add
--library-id … --model-id …`. A life-model entry is also a record of kind
`life` in the library search: **Use as a model…** and **Use as a prior…**
work on it as on any other.

### Reliability prediction (a parts count)

A design's failure rate from its parts list and the library's handbook base
rates (MIL-HDBK-217F), before there's any failure data. Each line is a part,
how many there are and its handbook part type (a library record id); its
rate is λb × πE (the environment's factor) × πQ (a quality factor per line,
1 unless given) × quantity, and the system is the sum: MTBF, R(t) at a
mission time, the rate per assembly and a Pareto. Free and exact.

| Call | Does |
|---|---|
| `POST /api/v1/analyse/prediction` | The parts count, saving nothing: `lines` (`[{name, record_id, quantity, quality_factor?, assembly?, reference?}]`; a mechanical part's NSWC-11 `record_id` takes `conditions` (its inputs) and, for a rate per cycle, `cycles_per_hour` instead of `quality_factor`, and a line still missing one is listed in `needs_conditions` and left out of the total), `environment` (`GB`, `GF`, `GM`, `NS`, `NU`, `AIC`, `AIF`, `AUC`, `AUF`, `ARW`, `SF`, `MF`, `ML`, `CL`), `mission_time` (hours, default 1,000). Reliafy Maintenance users may give `product_id` instead of lines: the product's bill of materials comes back as lines to assign. |
| `POST /api/v1/change/prediction_save` | Save one: `name` and the same arguments; the results are computed on save and kept as they were. `change/prediction_update` (`prediction_id`, any of `name`, `lines`, `environment`, `mission_time`, `notes`) computes them again; `change/prediction_delete` deletes one of yours. |
| `POST /api/v1/list/predictions`, `POST /api/v1/get/prediction` (`id`) | The saved predictions, and one in full (inputs and results). |

On the command line: `reliafy analyse prediction --lines '[{"name": "Ceramic
capacitors", "record_id": "mil-hdbk-217f-n2:10-1-ck-11015", "quantity": 48}]'
--environment GF`. The app's own routes are `POST /api/predictions/compute`,
`GET /api/predictions/from-product/{product_id}` and the saved predictions at
`/api/predictions`.

### Datasets: life data and measurements

A dataset is one document holding its **life data** (one row per unit) and,
when added, its **measurements**: readings on the same units at ages since
new, one row per reading (unit id, age, value). A condition and life model is
fitted to one such dataset; a degradation model reads its measurements. See
[datasets.md](datasets.md).

| Call | Does |
|---|---|
| `POST /api/v1/change/dataset_add_measurements` | `dataset_id` with `csv` (text), `upload_id` (a file sent to an upload link; `sheet` for a workbook) or `from_dataset_id` (another dataset's table, copied in). Adds the measurements, or replaces them; refused while a model reads them. |
| `POST /api/v1/change/dataset_remove_measurements` | `dataset_id`: takes the measurements off (the life data stays). |
| `POST /api/v1/change/dataset_split` | `dataset_id` whose one table holds life data and readings together (a reading per row, the censoring flag filled in once per unit): splits it into the two parts in place. Columns are guessed; `unit_column`, `age_column`, `censor_column`, `life_columns` and `measurement_columns` override them. |
| `POST /api/v1/get/dataset` | `id` with `part: "measurements"` pages the readings; without it, the life data (and a `measurements` summary where there is one). `list/datasets` shows each dataset's `measurements`. |

On the command line: `reliafy upload readings.csv --measurements-for
DATASET_ID`; in Python, `rf.add_measurements(dataset_id, "readings.csv")`.

---

## Python client and command line

```bash
pip install reliafy-client
```

The package is `reliafy-client`; you import it as `reliafy`, and it installs
the `reliafy` command (also as `reliafy-client`, the same command, for when
some other program called `reliafy` is already on your path). The client needs a Reliafy server with the
tools API above (`GET /api/v1/tools` answers); against an older server it
says so, and the 0.2 functions keep working.

```python
from reliafy import Client

rf = Client(token="rlf_...")                    # or RELIAFY_TOKEN, or `reliafy login`
rf.call("list", "models")
rf.call("analyse", "fit", data=[120, 340, 510], censored=[0, 0, 1])
rf.call("analyse", "rbd", rbd_id="…", wait=True)   # waits for a job
rf.upload_dataset("bearings.xlsx", name="Bearings")
rf.add_photo("nameplate.jpg", target_id="…")
rf.add_document("manual.pdf", target_id="…", kind="manual")
rf.push_usage(fleet_id, [{"name": "Truck 01", "current_use": 5230}])
```

```bash
reliafy login                                    # saves the token in your config folder
reliafy tools                                    # every tool and action you may call
reliafy analyse fit --help            # one action's arguments
reliafy analyse maintainability --unit minutes \
    --lines '[{"name": "Motor", "quantity": 4, "failure_rate": 180, "elements": {"isolation": 10, "replace": 15}}]'
reliafy analyse optimal_replacement --distribution-id weibull \
    --params '[{"name":"alpha","value":1200},{"name":"beta","value":2.5}]' \
    --planned-cost 200 --unplanned-cost 1500
reliafy models list
reliafy fit failures.csv --dist weibull --censor-column status
reliafy fit failures.csv --dist best --criterion bic   # rank every distribution by BIC (aic, aic_c, bic, neg_ll)
reliafy push model.json
reliafy upload bearings.xlsx --name Bearings
reliafy import rbd plant.xml
reliafy photo add IMG_*.jpg --to POSITION_ID --caption "Nameplate"
reliafy photo link PHOTO_ID --to LOCATION_ID      # show it there too
reliafy photo move PHOTO_ID --to POSITION_ID      # only there
reliafy document add manual.pdf --to ITEM_ID --kind manual
reliafy document get DOCUMENT_ID -o manual.pdf
reliafy ingest usage meters.csv --fleet FLEET_ID
reliafy ingest readings readings.csv
reliafy ingest snapshot burst.json     # a signal channel's snapshot (Maintenance): see signal-snapshots.md
reliafy maintenance progression.time_to_limit --point-id BAND_POINT_ID   # when a watched band reaches its limit, with the uncertainty
reliafy maintenance progression.series --point-id BAND_POINT_ID --json   # the band as unit, age_days, value rows (and CSV)
```

Add `--json` to any command for JSON instead of the readable summary. See
[python/README.md](../python/README.md) for more.

---

## Ingestion

### Request bodies

Every endpoint accepts either **JSON** or a **raw CSV body**:

```bash
# JSON
curl -X POST "$URL" -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" -d '{"items": [...]}'

# CSV (exactly what your CMMS exports)
curl -X POST "$URL" -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: text/csv" --data-binary @export.csv
```

Item matching is by `id` when given, otherwise case-insensitive `name`.
Batches are validated before anything is applied — a bad row means a `422`
and **no changes**.

---

### 1. Fleet usage — update meter readings

`POST /api/ingest/fleets/{fleet_id}/usage`

Updates `current_use` (and optionally the per-item usage `rate`) on a
failure-forecast fleet, then recomputes the forecast. The fleet id is in the
app URL: `/forecasts/<fleet_id>`.

CSV columns: `name` (or `id`), `current_use`, optional `rate`.

```bash
curl -X POST https://reliafy.com/api/ingest/fleets/$FLEET/usage \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: text/csv" \
  --data-binary @meter_readings.csv
```

```json
{"items": [{"name": "Truck 01", "current_use": 5230},
           {"name": "Truck 02", "current_use": 4980, "rate": 520}]}
```

Response: `{"fleet": "...", "updated_items": 2, "forecast": {"status": "ok", "expected": 3.4, ...}}`

### 2. Degradation measurements — append inspection readings

`POST /api/ingest/tracking/{tracked_fleet_id}/measurements`

Appends `(time, value)` readings to items in a tracked fleet and re-predicts
each item's remaining life. The id is in the app URL:
`/risk/<tracked_fleet_id>` (Decisions › Risk › Condition monitoring).

CSV columns: `item` (name or `id`), `time`, `value`.

```json
{"measurements": [{"item": "Pump 7", "time": 5300, "value": 6.1}]}
```

**Idempotent**: readings the item already has are skipped, so re-sending the
same export is safe. Readings must be after the item's latest (out-of-order
data is rejected with a clear message).

Response includes each item's new health bucket and prediction.

### 3. Dataset lives — append failure data, refit models

`POST /api/ingest/datasets/{dataset_id}/lives`

Appends rows to a dataset (columns must match) and then **refits every model
built from it, in place** — RCM evidence, RBD blocks, and fleet forecasts
that reference those models see the new fits immediately. Pass `?refit=false`
to append without refitting.

```bash
curl -X POST "https://reliafy.com/api/ingest/datasets/$DS/lives" \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: text/csv" \
  --data-binary @new_failures.csv
```

Response reports what was appended and each model's refit outcome.

---

### 4. Import a model — push from SurPyval

`POST /api/import/models`

Upload a model fit elsewhere (a SurPyval notebook) so it becomes a full
Reliafy model — shareable, editable, citable as RCM evidence. Easiest via
the [`reliafy`](../python/README.md) helper (`pip install reliafy-client`):

```python
import surpyval as sp
import reliafy

model = sp.Weibull.fit(x=failures, c=censoring_flags)

reliafy.configure(token="rlf_...")
url = reliafy.push(model, name="Pump bearings", unit="hours")
print(url)
```

`push()` uploads the fitted data too (so Reliafy shows the probability plot
and the model stays editable); offset / LFP / zero-inflated fits are detected
and reproduced. Pass `data=False` for a parameters-only model.

Raw request (JSON body): `name`, `distribution` (SurPyval name or Reliafy id),
optional `unit`, then either `data` (`{"x": [...], "c": [...], "n": [...]}`)
or `params` (`[{"name": ..., "value": ...}]`) with optional `options`
(offset/zi/lfp) or `extras` (gamma/p/f0). Returns `{id, name, url, ...}`.

### Python example (scheduled job)

```python
import requests

TOKEN = "rlf_..."          # from Settings -> API access
FLEET = "your-fleet-id"

with open("meter_readings.csv", "rb") as f:
    r = requests.post(
        f"https://reliafy.com/api/ingest/fleets/{FLEET}/usage",
        headers={"Authorization": f"Bearer {TOKEN}", "Content-Type": "text/csv"},
        data=f.read(),
        timeout=60,
    )
r.raise_for_status()
print(r.json()["forecast"])
```

Run it from cron / Task Scheduler after your CMMS export lands, and the
forecasts and RUL predictions in Reliafy stay current without anyone
touching the UI.
