# Changelog

## 0.10.0 (unreleased)

Needs a server on the same release.

- **`analyse schedule`**: a how-often rule's dates (`rule`, `start`, `end`), or an operating
  plan's hours by day, week or month (`plan`, `reading`, `read_at`, `period`), with the moment a
  meter reaches a reading (`due_at`) and the stop after it. Saves nothing: check a rule or a plan
  before saving it.
- **`maintenance get.forecast`** (Reliafy Maintenance): a position and everything inside it, from
  today: tasks on dates, work, expected failures and their cost per month, quarter or year
  (`period`, `periods`), with a 90% range and what each number rests on (`root`: the asset opened).
- Tasks by use in operating hours fall due through the position's operating plan where it has one
  (`limits[].due_moment`, `stop_after`, `basis`); `get operating_plan` adds `against_actual`, and
  a plan takes `utilisation`.

## 0.9.0 (13 Nov 2026)

Needs a server on the same release.

- **No ready-made product**: `maintenance products.add_sample` (and its
  `make_own`) is gone, with the shared survey quadcopter samples it stood on
  (its datasets, models, analyses, fault tree and predictions). Copies already
  in a workspace stay, as your own products.

## 0.8.0 (13 Nov 2026)

Needs a server on the same release.

- **Libraries of datasets and models**, shareable and public: `change
  library_add` (`library_id`, `dataset_id` or `model_id`, `model_collection`)
  replaces `library_add_model`, and `change library_remove` (`entry_id`)
  replaces `library_remove_record`. New `change library_use` copies an entry
  into your workspace. `change library_update` also sets `visibility`
  (`private`, `workspaces`, `public`) with `workspaces`, `licence`, `source`,
  `citation` and `rights_confirmed`. `list kind libraries` lists every library
  you can see (`scope`), and `get kind library` takes `entry_id`.
- **Upload into a library**: `change dataset_upload` (and `reliafy upload`)
  takes `library_id`: every dataset made, each part of a split too, is added
  to that library as a snapshot, all or nothing.

## 0.7.0 (14 Nov 2026)

Needs a server on this release.

- **Datasets keep their reading** (which column is x, c, n, xl/xr, tl, tr,
  i, m, e, s and the covariates Z): `change dataset_upload` (and `reliafy
  upload`, with `--x-col`, `--c-col`, … `--z-cols`, `--unit`) takes it;
  columns left out are guessed and the answer's `reading` says how
  (`source: guessed`). `change dataset_update` changes it, `get kind
  dataset` returns it, and `analyse fit` / `change model_fit` with a
  `dataset_id` and no `time_column` fit from it.

- **The asset tree as a sheet** (Reliafy Maintenance): `reliafy maintenance
  list.tree` (`position_id` for a branch, `format csv`) gives one row per
  position with its path, tag, class, location and fitted item; `reliafy
  maintenance workspace.import_history` with `sheet tree` takes the same rows
  back (a dry run by default; matched by ID, else Path; nothing deleted).

## 0.6.0 (13 Nov 2026)

Needs a server on this release.

- **Every interval is 90%** (server change): life bounds (B-lives, mean or
  median life, remaining life) are 90% one-sided lower bounds, and every other
  interval is 90% two-sided. Results carry `ci_level`; result keys that named
  a level are now level-free: `beta_ci_95` → `beta_ci`, `ci_95` → `ci`,
  `rocof_ci_95`, `mtbf_ci_95`, `rate_ratio_ci_95`, `effectiveness_ci_95`
  (now without `_95`) and `survival_95ci` → `survival_ci`. Forecast ranges are
  90% (P5–P95); demonstration tests and per-demand bounds default to 90%.
- **Split one sheet into several datasets**: dataset uploads take
  `dataset_col`; each value of that column becomes its own dataset.
- **Data mapping**: fits read `x` with an optional range (`xl`, `xr`) row by
  row; rows with `x` and a range both filled are left out with a warning.
  `tr` (observed only up to this value) is mapped like `tl`.
- **Download as Python for every model**: `reliafy analyse model_export_python
  --model-id ID` (or `POST /api/v1/analyse/model_export_python`) gives any
  saved model (non-repairable, regression, time-varying covariates,
  repairable, accelerated life, degradation, condition and life) as a
  SurPyval script that refits it and prints the page's numbers. The
  test-planning actions take `python: true` for the plan's script. Needs a
  server on this release.
- **Field reports** (Reliafy Maintenance): `reliafy capture new notes.txt
  IMG_*.heic noise.m4a --about POSITION_ID` sends notes, photos, sound
  recordings and PDFs as one report, in pieces that carry on after a dropped
  connection and never arrive twice; `capture list | get | status | keep |
  unkeep | delete | download`. In Python: `rf.new_capture(...)`,
  `rf.captures()`, `rf.capture(id)`, `rf.set_capture_status(...)`. Needs a
  server with `/api/v1/maintenance/captures`.

## 0.5.4 (11 Nov 2026)

No change to the client's own code: the tools, routes and flags below come
from the server, and need a server on this release.

- **Missions**: each mission can have an RBD of its own, built from what's
  inside its position (`POST /api/maintenance/positions/{id}/missions`). A
  phase can set blocks to `standby` (not running in that phase) beside
  `not_needed`; `change rbd_mission` keeps the new field.
- **Fit with a prior**: `POST /api/models/fit-with-prior` takes a saved
  model, a library record, numbers, a range or a B10 as the prior, on a saved
  dataset or on pasted data, and gives the result in the data's time unit.
- **Failure reports** on a design position list the reports on the items
  built from it.
- **Item class fleets** take `within` (a position or place) to keep to one
  asset.
- **Maintenance orders**: `GET /api/maintenance/work-orders` takes
  `status=done`, `q` and `limit`; `GET /api/maintenance/due` lists what falls
  due over a horizon.

## 0.5.3 (10 Nov 2026)

No change to the client's own code: the tools, routes and flags below come
from the server, and need a server on this release.

- **Data library records take their inputs as covariates**: every input a
  record needs before it gives a rate is a covariate of the record (a pipe's
  length, running hours a year, demands a year, a MIL-HDBK-217F part's
  environment and quality grade), given as `covariates` wherever the record
  is used: as a model or a prior (`{kind: library, record_id, covariates?}`),
  on a position's link and on a parts-count line. The earlier arguments
  still work as other names for the same thing. `list kind library` takes
  `components: true` for the NRC/INL components (an equipment type in one
  pooling group, its failure modes together), and `get kind library_record`
  takes a component's id.
- **Accelerated life**: `analyse alt_use_level` bounds now carry the range on
  the life at the use stress, as the app's card shows it.
- **RBD edits**: `change rbd_edit` no longer lists a "like blocks wired in
  series" warning as new when the edit only reworded it.
- **Survey quadcopter**: `maintenance products.add_sample` answers with
  `own_records` (the models and analyses saved in the workspace as its own),
  `kept_shared` and `kept_note`. Action names and arguments are unchanged.
- **A class's fleet**: `maintenance get.item_class` takes `fleet: true` (and
  `position_id` for one member): the positions whose fitted item is of the
  class, each with its risk now where a condition and life model is linked.
  `reliafy maintenance get.item_class --id … --fleet true`.

## 0.5.2 (10 Nov 2026)

- **Missions on an RBD**: `change rbd_mission` adds, changes or deletes a
  named phased mission (`rbd_id`, `mission_id` to change one, `name`,
  `phases`, `delete`); each phase takes `values` (a Use or Environment
  covariate's value for the phase, set once for every block it feeds) and
  `block_values` (one block's own). `analyse rbd_mission` works one out
  (`mission_id`) or every mission on the RBD: the chance of completing it,
  per phase, each phase's weakest block, and the covariates its phases can
  set. `get kind rbd` lists the missions. Over REST `POST
  /api/v1/change/rbd_mission` and `/api/v1/analyse/rbd_mission`; on the
  command line `reliafy analyse rbd_mission --rbd-id … --mission-id …`.

- **Libraries of your own**: `list kind libraries`, `get kind library`
  (`id`) and the `change` actions `library_create`, `library_update`,
  `library_delete`, `library_add_model` (a saved Weibull, exponential,
  lognormal, normal or gamma model snapshotted as a record of kind `life`,
  the model linked) and `library_remove_record`. Your records appear in
  `list kind library` and `get kind library_record` beside the published
  ones, usable as a model or a prior. Over REST `POST
  /api/v1/change/library_*`; on the command line `reliafy change
  library_create --name "Site pumps"`, `reliafy change library_add_model
  --library-id … --model-id …`.

## 0.5.1 (not published on its own; part of 0.5.2)

- **Data library records as models and priors**: `maintenance models.link`
  takes `library_record_id` (a published failure rate attached as an
  exponential model, its 5–95% range the interval, cited), and the fit's
  `prior` takes `{kind: "library", record_id, shape?}`. The CLI's
  `reliafy maintenance models.link --library-record-id …` follows.

- **Life models on positions** (the Explorer's Modelling tab): new actions
  `maintenance models.link` (a saved model, the class's model, a fit from the
  position's history, or a Bayesian update of a baseline with it) and
  `maintenance models.unlink`; `get.position` lists `models`. Over REST
  `POST /api/v1/maintenance/models.link` and `models.unlink`; the CLI has
  `reliafy maintenance models.link` and `models.unlink`.

- **A prior around a value, between two bounds**: the fit's `prior` takes
  `{kind: "around", distribution, unit, params: {alpha: {about: 4, between:
  [3, 6]}, beta: {between: [1.5, 3]}}}` (an exponential's as `mean` or
  `failure_rate`).

- **Fit a life model**: `maintenance models.link` with `fit` takes `data`
  (`position`, `class`, `both`), `method` (`mle`, `bayes`) and `prior`
  (`{kind: class | model | params | b10, ...}`; the class's history is a power
  prior). `analyse bayes_update` takes `baseline: {class_power_prior: true,
  position_id}`.

- **RBDs on positions, and the model in use**: `maintenance models.link`
  takes `build_rbd: true` (an RBD from the positions inside; with
  `replace_link_id`, rebuilt), `rbd_id` (link an existing RBD) and
  `use_link_id` (which of a position's rows is its model in use).

- **Predictions on positions**: `maintenance models.link` takes `prediction`
  (`{environment?, mission_time?, assign?}`), a parts-count prediction from
  the position's parts list, saved as a prediction and an exponential model.
  Accelerated-life and covariate models can be linked like any saved model.

- **More handbook part types, rates you give and lines left out**: the
  library's MIL-HDBK-217F source adds Appendix A's parts-count generic rates
  (microcircuits by complexity band, motors, synchros and resolvers, circuit
  boards, quartz crystals, lamps, laser diodes; `generic_rates` by
  environment, `quality_factors` with a default grade) and SAW devices and
  helium/argon lasers: 236 records, up from 158. A prediction line (in
  `analyse prediction` lines and `models.link` `assign`) takes
  `rate_per_million_hours` (a rate the user gives, for a part the handbook
  doesn't have, such as a battery: shown as user-given) or `excluded: true`
  (not an electronic part: left out, and the result's `excluded` and
  `left_out_note` say so). A line's `quality_factor` left out now means the
  part type's default grade (10 for a commercial microcircuit), not always 1.

- **A Bayesian update of a baseline**: new action `analyse bayes_update` (Pro):
  a baseline model, numbers or a B10 belief, how much to trust it, and a few
  failures give posterior medians with 90% credible intervals.

- **Renamed** (to make room for the above): `maintenance rcm.interval_on_condition`
  is now `rcm.pf_interval`, `rcm.interval_failure_finding` is `rcm.ff_interval`
  and `parts.positions_from_structure` is `parts.build_positions`. Their
  arguments and answers are unchanged; the old names are gone.

- **Make the sample product your own**: `maintenance products.add_sample`
  takes `make_own: true` (with `product_id`, the copy; default the only one)
  to turn a copy of the sample quadcopter into your own product in place:
  "(sample)" leaves its name, its part's and its built items' names, nothing
  inside changes, and the sample isn't added again beside it unless asked.
  Over REST it's also `POST /api/maintenance/products/{id}/make-own`; product
  reads carry `sample`. A product's design's tasks no longer fall due, open
  work orders or join work packages: they're its programme, and the items
  built from it carry the copies that do (`list.task_table` says so in
  `why_not`, with `design: true`). No new actions and no client code changed.

- **When a task first falls due**: `maintenance tasks.create`,
  `tasks.update` and `failure_modes.add_task` take `start`, the date a
  calendar task first falls due (then every interval after), so a 12-monthly
  summer task made in November can first fall due next October. Left out, it
  is one interval from today, as before; `tasks.update --start ''` clears
  it. Task reads carry `first_due`. No new actions and no client code
  changed.

- **Settings, and readings from a work order**: `maintenance
  measurements.add_point` takes `kind: "setting"` (a value someone sets, such
  as a chlorinator's output %: it holds until the next change, never alarms)
  with optional `range_min` / `range_max`; `measurements.update_point` takes
  `kind`, `range_min`, `range_max` and `clear_range`, so an existing point can
  become a setting. `work_orders.update` takes `readings` (as `close` does,
  each `{point_id, value, unit?, on?, task_id?, note?}`) and
  `measurements.record` takes `work_order_id` and `task_id`; readings read
  back with them, a setting's point with `changes`, and `get.work_order` with
  `reading_points`, `readings_taken` and `readings_by_task`. No new actions
  and no client code changed.

- **The P-F interval alone is enough**: `maintenance
  rcm.interval_on_condition` needs only `pf_interval` and `pf_unit` and
  answers half the P-F interval, or the net P-F interval (less the new
  `act_time`) when tighter. The costs and `onset_rate` are optional; given,
  `cost_optimal` holds the cheapest interval (the top-level `recommended` is
  now always the P-F one). `rcm.interval_failure_finding` with a target and
  the costs adds `cost_optimal` too. No client code changed.

- **How often to do an RCM task**: two new `maintenance` actions, both exact
  and free. `rcm.interval_on_condition` (the P-F calculator) gives the
  cheapest interval between checks for a warning that comes `pf_interval`
  before the failure, beside the rule of thumb of half the P-F interval;
  `rcm.interval_failure_finding` gives the longest test interval that keeps a
  hidden failure's unavailability within `target_unavailability`, or the
  cheapest from the costs. Both answer with `recommended`, rounded down to a
  unit people schedule in, and the task's numbers now with `current_interval`.
  The fixed-interval one stays `analyse optimal_replacement`. On the command
  line: `reliafy maintenance rcm.interval_on_condition --pf-interval 10
  --pf-unit weeks --onset-rate 0.5 --inspection-cost 20 --found-cost 200
  --failure-cost 2000`. No client code changed.

- **What each task needs (the LSA)**: the new `maintenance tasks.set_resources`
  (`task_id`, `resources`) records labour (trade, people, hours), tools and
  instruments (with the measuring point or channel read), spares (linked to
  the parts register), consumables, access and downtime, method and elapsed
  hours. Task reads gain `resources`, and each package in `maintenance
  list.packages` a `rollup` of what its visit needs. On the command line:
  `reliafy maintenance tasks.set_resources --task-id <id> --resources
  '{"labour": [{"trade": "Fitter", "people": 1, "hours": 2}]}'`. No client
  code changed.

- **What a check leads to, and one place for the rationale**: `maintenance
  failure_modes.decide` takes `decision.on_found` (and `on_found` on each of
  `decision.outcomes`) for an on-condition or failure-finding task: what's
  done when the check finds it. Left out, it's kept; `""` clears it. Reads
  return it. `decision.notes` is deprecated: it's added to the failure mode's
  notes and rationale (`failure_modes.update notes`), and reads give it as
  those notes. The FMECA and RCM exports gain an "On found" column, which the
  worksheet import reads. No client code changed.

- **Packages proposed as visits on a weekday**: `maintenance packages.propose`
  takes `weekday` (`monday` … `sunday`). The drafts then visit on that day,
  with the longer cadences as layers on the shortest in each area and trade;
  each draft gains `ref`, `layer_of` and `cadence_text`, and a layer's
  `create` has `parent_id: "@<ref>"`, ready for one `maintenance apply`. On
  the command line: `reliafy maintenance packages.propose --position-id <id>
  --weekday saturday`. No client code changed.

- **The RCM decision follows SAE JA1011 and RCM II**: `maintenance
  failure_modes.decide` takes `hidden` (`--hidden true`), and `consequence` is
  one of safety, environmental, operational, non_operational; `"hidden"` is a
  deprecated alias for `hidden: true`. Run to failure or accept on a safety or
  environmental consequence, failure finding on an evident failure and a
  combination of tasks on an operational one are refused. Reads add `hidden`,
  and `advice` on a decision saved before that the rules would refuse. Outcome
  labels lose the hyphen ("On condition", "Run to failure"). No client code
  changed.

- **Tasks raised by an event**: `maintenance tasks.create` and `tasks.update`
  take `trigger` (`{kind: "reading", point_id, above | below}` or `{kind:
  "event", event_type, note}`, with `with_interval` to keep the interval too;
  `tasks.update clear_trigger` removes it), and `tasks.create` needs no
  `interval` when a trigger raises it. The new `maintenance
  positions.log_event` (`position_id`, `event_type`, `note`, `on`) logs an
  event and returns `work_orders_raised`. On the command line: `reliafy
  maintenance positions.log_event --position-id <id> --event-type "Lightning
  strike"`.

- **A function's working is in its notes and rationale**: the working behind a
  performance standard now goes in the function's `notes` (`maintenance
  failure_modes.add_function` / `update_function`; up to 25,000 characters on
  a function, Markdown is fine; `--notes @working.md` reads a file).
  `standard_basis` is still accepted but deprecated: it is added to the notes
  under a "Working" line. Reads keep `standard_basis`, `has_basis` and
  `basis_preview`, now describing the notes, and a function's notes read with
  any working written before as one text. Evidence `{type: "working", id}` on
  a decision now means that function's notes and rationale; links made before
  still resolve. No client code changed.

- **Cause links anywhere on the same tree**: `maintenance
  failure_modes.link_cause` now takes a cause on any position of the effect's
  tree: inside it as before, beside it (the pool water's chlorine failure from
  the salt chlorinator next to it) or on the same position. Only a failure
  causing itself, a loop and a cause on another tree are refused. Moving a
  position, function or functional failure drops a link only when its two
  ends end up on different trees. The `inside` flag on causes and effects in
  RCM reads now means "on the same tree" (the link counts).

- **Move a measurement point**: the new `maintenance measurements.move_point`
  (`point_id`, `position_id`) moves a position's point to another position
  with its readings and any open alarm work order. Tasks by use that counted
  it as their position's counter keep counting it. A batch undoes it.

- **Move a task with open work orders**: `maintenance tasks.move` (and the
  RCM moves that carry tasks: `failure_modes.move`, `move_function`,
  `move_functional_failure`) no longer refuse a task with an open work order.
  The open work orders go with it and are listed in `work_orders_moved`. A
  task with work done is still refused.

- **A combination of tasks on one RCM decision**: `maintenance
  failure_modes.decide` takes `decision.outcomes`, a list of
  `{outcome, task, interval, interval_unit, task_id}` (a regular inspection
  plus a fixed-time replacement, say), in place of `outcome`, `task` and
  `interval`. Each scheduled entry gets a task of its own. Reads add
  `decision.outcomes`. A single-outcome decision works as before. Each entry
  may link its own `evidence` (`{type, id}`); the decision's evidence counts
  for every entry it fits. The evidence check covers every entry: `status`
  `partly` when some tasks have evidence and some don't, and each entry of
  `decision.outcomes` carries its own check.

- **Delete an RCM row with everything under it**: `maintenance
  failure_modes.remove_function`, `remove_standard`,
  `remove_functional_failure` and `retire` take `cascade` (everything under it
  goes: standards, functional failures, failure modes, their tasks and links)
  and `dry_run` (only count it). The new `failure_modes.undo_delete`
  (`deleted_id`) brings the lot back as a unit. Without `cascade` they behave
  as before.

- **A product's physical layout**: `maintenance locations.create` takes
  `design_of` (a product's id) for one of the product's design locations
  (Forward left arm, Battery bay), and `maintenance list.locations` takes
  `product_id` to list them (or, given a built item's top position, the copy
  that item carries). Building an item copies them, its positions placed the
  same way. Design locations never show among the places you look after.

- **One sample quadcopter**: `maintenance positions.add_sample_uav` is gone.
  The sample quadcopter is now the sample product only (`maintenance
  products.add_sample`): its design carries the same scored FME(C)A. Copies
  the old action made stay in a workspace as they are.

- **One sample for RCM and FME(C)A**: `maintenance positions.add_sample_truck`
  (and the app's `POST /api/maintenance/sample-truck`) is gone, with no alias.
  The sample product (`maintenance products.add_sample`) is now the one sample
  for both: its quadcopter design carries a full RCM, some decisions linked to
  sample evidence (supported, one contradicted on purpose, one inconclusive)
  and two failure modes left undecided on purpose. Copies of the sample truck
  already in a workspace stay as they are.

- **Maintainability prediction**: `analyse maintainability` gives the mean
  corrective maintenance time (Mct), M_max at a percentile, inherent
  availability, where the repair time goes by element, the Pareto of the lines
  and the roll-up by assembly, from a parts list with each line's repair
  elements and failure rate; `change maintainability_save`,
  `maintainability_update` and `maintainability_delete` keep them, and
  `get maintainability_prediction` / `list maintainability_predictions` read
  them (a sample included). On the command line:
  `reliafy analyse maintainability --lines '[{"name": "Motor", "quantity": 4,
  "failure_rate": 180, "elements": {"isolation": 10, "replace": 15}}]'
  --unit minutes`.

- **Reliability prediction**: a parts count from the library's handbook base
  rates (MIL-HDBK-217F) for a design with no failure data yet. `analyse
  prediction` (`lines`, `environment`, `mission_time`; Reliafy Maintenance
  users may start from a `product_id`), `change prediction_save`,
  `prediction_update` and `prediction_delete`, `get kind prediction` and `list
  kind predictions`; the guide topic `prediction`. On the command line:
  `reliafy analyse prediction --environment GF --lines @parts.json`.
- **Fault trees built by hand**: `get fault_tree`, `list fault_trees`, `analyse fault_tree` (top event,
  cut sets, importance; `export_openpsa` for Open-PSA XML), `change fault_tree_save` (with `make_rbd`) and
  `change fault_tree_delete`; `change import_rbd` takes `as_fault_tree` for Open-PSA and Galileo files.
  Listed by `reliafy tools`, e.g. `reliafy analyse fault_tree --fault-tree-id …`.

- **Products** (Reliafy Maintenance): a product is a design tree with its part;
  items are built from it by serial. `maintenance products.create`,
  `products.declare`, `products.clear` and `products.build` (a dry run by
  default); reads `maintenance get.product`, `get.design_rollup` (a design
  position across every item built: items, what's fitted, pooled life data,
  failure reports), `list.products`, `list.product_items` and
  `list.items_overview` (every item with its product, class, position and open
  reports). On the command line: `reliafy maintenance products.build
  --product-id … --serial …`.
- **Time to the limit**: `maintenance progression.time_to_limit` and `progression.series` for a watched
  band's trend (listed by `reliafy tools`).
- **Signal channels** (Reliafy Maintenance): `push_snapshot` and `reliafy ingest snapshot FILE.json` send a
  vibration burst, a device spectrum or a scalar value to a channel; the new `maintenance signals.*` and
  `signal_data.*` actions are listed by `reliafy tools`, including `signals.update_band` (change a band
  without losing its history), `signals.set_storage_cap` and `signal_data.storage`.
- **Six tools instead of sixteen.** The server's core tools are now `get`,
  `list`, `analyse` (every calculation: fits, evaluations, test plans,
  repairable systems, strategy, fleet forecasts and RBD analyses, saving
  nothing), `change` (every write), `guide` and `report_problem`. Actions
  that moved get the area as a prefix: `life_data_analysis fit` is
  `analyse fit`, `rbd_analysis analyze` is `analyse rbd`, `models save` is
  `change model_save`, `uploads create` is `change upload_create`,
  `sharing create_link` is `change share_link`, `library search` is
  `list library` (its `kind` argument is `record_kind`), `upgrade_link` is
  `get upgrade_link`. `guide --action analyse.fit` prints one action's full
  argument schema. Client helpers (`fit`, `reliability`, `upload_dataset`,
  `import_rbd`, …) call the new names; their signatures are unchanged.
  **The earlier tool names are removed** (over MCP, REST and the CLI), and
  this client needs a server from the November 2026 release. Every earlier
  tool and action, and where it went:

  | Earlier | Now |
  |---|---|
  | `life_data_analysis X`, `repairable_analysis X`, `strategy X` | `analyse X` |
  | `rbd_analysis analyze`, `rbd_analysis X` | `analyse rbd`, `analyse rbd_X` |
  | `models X`, `datasets X`, `rbd X` | `change model_X`, `change dataset_X`, `change rbd_X` |
  | `uploads create`, `send_part`, `import_rbd`, `import_excel` | `change upload_create`, `upload_send_part`, `import_rbd`, `import_excel` |
  | `sharing create_link`, `create_report`, `revoke_link` | `change share_link`, `share_report`, `share_revoke` |
  | `fleet create_alert` | `change fleet_create_alert` |
  | `library search` (`kind`), `get`, `sources` | `list library` (`record_kind`), `get library_record`, `list library_sources` |
  | `upgrade_link` | `get upgrade_link` |
  | `get`, `list`, `guide`, `report_problem` | unchanged |

  Reliafy Maintenance's 22 `maintenance_*` tools are one `maintenance` tool
  (operators only): `maintenance_positions create` is `maintenance
  positions.create`, `maintenance_get kind position` is `maintenance
  get.position`, `maintenance_overview` / `_guide` / `_apply` are `maintenance
  overview` / `guide` / `apply`. On the command line:
  `reliafy maintenance positions.create --name …`; in Python:
  `rf.call("maintenance", "positions.create", name=…)`. `Client.apply`,
  `add_document`, `download_document` and `reliafy photo` call the new names.
  Over MCP each tool now takes its action and an `args` object; REST bodies
  and CLI flags are as before.

- Work packages (Reliafy Maintenance). Tasks done together on one visit raise
  one work order per visit: `maintenance packages.propose` (drafts, saves
  nothing), `create`, `update`, `add_task`, `remove_task`, `pause`, `resume`,
  `retire` and `restore`; reads `maintenance get.package` and
  `list.packages`. A package visits on fixed dates (every Saturday, the first
  Saturday of the month) or counted from the last visit, with a tolerance in
  days; layers add lines on some visits. `maintenance work_orders.close` takes
  `not_done` ([{task_id, reason}]) and an action's `position_id` on a
  package's work order; `work_orders.generate` answers with `packages`,
  `lines_added` and `packages_skipped` once a workspace has packages.
  `maintenance work_orders.mark` saves a line's state during the visit
  (done, not_done with a reason, problem with a finding, or todo); close
  counts the saved marks. `packages.pause` takes a reason and a return date
  (`until`; back by itself then) and `full_visit`; `season` on create and
  update keeps a package to part of the year; `positions.out_of_service` /
  `items.out_of_service` and `back_in_service` hold the tasks on them. On the
  command line: `reliafy maintenance packages.create --name …`.

- RCM for agents. `maintenance_get kind failure_mode` reads one failure mode by
  its id: its decision with the evidence check, its tasks, where it sits
  (position, function, functional failure) and `available`, the tasks on its
  position or above it it could share. `maintenance_list kind rcm_gaps` says
  what an RCM still lacks (modes with no decision or no task, hidden failures
  with no failure-finding task, evidence to check, and functions, performance
  standards and functional failures with nothing under them), for the whole
  workspace or a branch (`target_id`). `uploads import_excel target=rcm` takes
  `dry_run` true for a preview; a `mapping` of only `consequence_map` /
  `outcome_map` keeps the guessed column mapping. `split_standard` keeps each
  line's structured limit (`parameter`, `comparator`, `value`, `unit`).
  `maintenance_apply` undoes `link_cause` / `unlink_cause`; their results say
  `changed`. `decide` answers with `advice` when the outcome is unusual for the
  consequence. Over MCP, an RCM read lists a mode's tasks once, on the mode
  (not again under `decision.tasks`). Refusals name what wasn't found and what
  the id is instead.

- A task by use keeps counting the same measurement when it moves
  (`maintenance_tasks move`, and the `maintenance_failure_modes` moves that
  take tasks with them), as long as that measurement is on the new position, a
  position above or below it, or the item fitted there. When it isn't, the move
  answers with what it needs to know; send it again with `measurement`
  (`{task_id: choice}` or one choice: `keep`, `switch` with `point_id` and
  optionally `last_done_reading`, or `calendar` with `interval` and `unit`).
  `maintenance_get kind task_measurement` reads what a task counts and the
  measurements it could count (`position_id`: at a position it would move to).
  `maintenance_tasks update` takes `last_done_reading` with a new `point_id`;
  left out, it's worked out from the last-done date and marked an estimate
  (`last_done_reading_estimated` on the task).

- `maintenance_failure_modes move_standard` moves a performance standard to
  another function (on the same position or another). It moves alone: the
  functional failures that breached it stay with their function, under no
  standard, and the result names them (`unlinked_functional_failure_ids`).
  `ids` names failures of the new function that breach it from now on.
  `maintenance_apply` undoes it.

- Rearranging the RCM tree. `maintenance_failure_modes move_functional_failure`
  moves a functional failure under another function (on the same position or
  another) with its failure modes and their tasks; the standard it breached
  stays with the old function, `standard_id` names one of the new function's.
  `reorder` places a position's functions, a function's functional failures or
  a functional failure's failure modes (`parent_id`, `ids`). Every move's
  result says where the thing came from (`from_position_id`,
  `from_functional_failure_id`, `from_function_id`, `from_standard_id`;
  reorders give `previous_ids`), and `maintenance_apply` now lists the reverse
  of moves, assigns and reorders in `undo`, so several moves sent as one batch
  are all or nothing and can be undone as one.

- A function may have several performance standards, as a list.
  `maintenance_failure_modes add_standard` (text, and optionally parameter,
  comparator, value, unit, when, source), `update_standard`, `remove_standard`,
  `reorder_standards` and `split_standard` (a dry run proposing lines from a
  single text, then the edited lines); `add_functional_failure` and
  `update_functional_failure` take `standard_id`, the standard a failure
  breaches. A function's `standards` lists them; its `standard` is their texts
  joined with "; " once it has a list. In a worksheet every distinct standard
  cell under a function is one standard.

- A failure mode may have several tasks, and one task may serve several
  failure modes. `maintenance_failure_modes add_task` adds another task to a
  mode (its decision's task stays first); `decide` takes `task_id` to make an
  existing task the decision's; `maintenance_tasks link` / `unlink` add or
  remove one link (`create` takes `failure_mode_ids`); a task on a position
  may serve modes on positions inside it. A decision's `tasks` lists them all
  with `shared_with`; a task's `failure_modes` lists its modes. Shared tasks
  keep their own interval: change it with `maintenance_tasks update`.
  `maintenance_apply` undoes `tasks.link` with `tasks.unlink` (and back) and
  `failure_modes.add_task` with `tasks.retire`. A worksheet row that repeats a
  failure mode with another task adds that task; a task named on several rows
  is one task, linked.

- A dataset holds its life data and, when added, its measurements (readings
  on the same units at ages since new) in one place. `Client.add_measurements
  (dataset_id, "readings.csv")` and `reliafy upload readings.csv
  --measurements-for DATASET_ID` add them (or replace them); the `datasets`
  tool gains `add_measurements` (`csv`, `upload_id` or `from_dataset_id`),
  `remove_measurements` and `split` (one table of life data and readings into
  the two parts); `get kind dataset` takes `part: "measurements"`, and `list
  kind datasets` shows each dataset's `measurements`.
- Condition and life: `life_data_analysis fit_joint` and `models fit_joint`
  take one `dataset_id` (its life data with its measurements, or one table
  holding both) in place of `lifetimes_dataset_id` and `readings_dataset_id`.
  Saved models keep working; `reliafy datasets add_measurements --dataset-id
  LIVES --from-dataset-id READINGS` brings an old pair onto one dataset.
- FMEA and FMECA on the asset tree (Reliafy Maintenance). `maintenance
  failure_modes.score` keeps a failure mode's severity, occurrence and
  detection (1–10), cause, local and next-higher effects, detection method,
  recommended action (owner, due date, status) and criticality figures
  (failure rate, mode ratio, loss probability, operating time, severity
  class); `clear` names fields to blank. Reads (`get.rcm`, `get.failure_mode`)
  answer with `rpn`, the action priority `ap` (H, M or L) and the mode
  criticality `cm`, and each position's `fmea` summary. `failure_modes.add`,
  `assign` and `move` take `function_id` for a mode directly under a function
  (no functional failure yet); `positions.add_sample_uav` copies a scored
  sample quadcopter into the tree.

## 0.4.0

- Best fit takes a score: `reliafy fit FILE --criterion bic` (or `criterion=`
  on `life_data_analysis fit` / `models fit`; aic, aic_c, bic or neg_ll). The
  result's `selection` now gives each candidate's parameter count and delta to
  the best, and guidance in words. Shared-frailty models take
  `frailty_family` (`gamma` or `lognormal`). New model ids `loglogistic_ph`,
  `loglogistic_aft`, `loglogistic_po` and `loglogistic_ah`, and regression
  fits report `diagnostics.model_checks`. No client code changed beyond the
  `--criterion` flag: the rest comes from the server's tool list.
- `maintenance_apply`: many Reliafy Maintenance changes in one call. A list
  of the `maintenance_<area>` actions (`{"do": "failure_modes.add", "args":
  {...}, "ref": "m1"}`), run in order with `@ref`s between them, checked on
  a copy of the workspace before anything is written; deletes name what they
  delete (`confirm`); the answer has every operation's result and the reverse
  operations (`undo`). `Client.apply(operations, dry_run=…, on_error=…,
  idempotency_key=…)`, and `reliafy apply ops.json [--run] [--key K]` (a dry
  run unless `--run`; the undo list is written beside the file).
- Every level of the maintenance tree can be taken out of use and brought
  back: `maintenance_locations retire / restore`, `maintenance_items create /
  retire / restore`, `maintenance_parts retire / restore / unlink`,
  `maintenance_manufacturers retire / restore`, `maintenance_measurements
  retire_point / restore_point`, `maintenance_topology update / reconnect /
  retire_group / restore_group`, `maintenance_positions restore` (and `retire
  --cascade`), `maintenance_tasks restore`, `maintenance_failure_modes
  restore`, `maintenance_item_classes restore / restore_condition`,
  `maintenance_attachments update_document / restore_document / update_photo
  / clear_coordinates`; `maintenance_parts update --clear` and `reorder
  --clear-reorder-point`; `maintenance_list --kind events`. No client code
  changed for these: the commands come from the server's tool list.

- RCM studies are gone from Reliafy: RCM lives on the asset tree, on each
  position. The `rcm` tool (study-based RCM worksheets as JSON) is gone, with
  `list` kind `rcm_studies` and `get` kind `rcm_study`. RCM is built on a
  position (`maintenance_failure_modes`), and a worksheet file goes in with
  `reliafy import excel FILE --target rcm --position ID`. `--target rcm` now
  needs the position.
- `sharing create_link` and `reports` no longer take kind `rcm_study`, and
  `maintenance_positions from_rcm` / `apply_rcm` are gone: RCM is built on
  the position (`maintenance_failure_modes`, or `maintenance_positions
  add_sample_truck` for the sample) or imported from a worksheet.
- These remove tools and actions, so this client ships with the app release
  that removes them, never before.
- `reliafy import excel FILE --target rcm --position ID` (and
  `Client.import_excel(path, target="rcm", position_id=…)`) adds an FMEA /
  RCM worksheet, .xlsx or .csv, to a Reliafy Maintenance position's RCM. It
  only adds: importing the same file again adds nothing.
- `maintenance_failure_modes add_function` / `update_function` take
  `standard_basis`, the working behind a performance standard (Markdown;
  `--standard-basis @working.md` reads a file), and `maintenance_get kind
  function` reads one function in full. No client code changed: the commands
  come from the server's tool list.

## 0.3.1

- PDFs in Reliafy Maintenance: `Client.add_document(path, target_id=…)` keeps
  a PDF (at most 20 MB) on an item, a position or (`position_class=…`) a
  position class; `Client.download_document(document_id, path)` saves one.
  On the command line: `reliafy document add FILE.pdf --to ID` (or
  `--class NAME`, with `--title` and `--kind`) and `reliafy document get ID
  -o FILE.pdf`.
- `upload_file` takes the purpose `document` (a PDF).

## 0.3.0

Needs a Reliafy server with the tools API (`GET /api/v1/tools` answers) for
the new calls; against an older one they stop with `reliafy.ServerTooOld`,
and everything from 0.2 keeps working.

- `reliafy.Client` and `Client.call(tool, action, **args)`: every Reliafy
  tool action, with the same arguments and results as Reliafy's MCP tools.
  `wait=True` polls a long-running job until it finishes.
- `reliafy.call(...)`, plus shortcuts: `list`, `get`, `fit`, `reliability`,
  `guide`.
- Files and photos, streamed from disk: `upload_dataset`, `import_rbd`,
  `import_excel`, `upload_file`, `add_photo`.
- Ingest helpers: `push_usage`, `push_readings`, `push_measurements`,
  `push_lives`.
- The `reliafy` command (also installed as `reliafy-client`): `login`,
  `tools`, any `<tool> <action>` with `--help`, `--json` or table output, and
  `push`, `fit`, `upload`, `import`, `photo add` (JPEG, PNG, WebP, HEIC), `photo
  link`, `photo move`, `photo unlink`, `ingest`, `models list`.
- `reliafy.push` and `reliafy.push_params` work as the README always showed.
- The token and server can come from `reliafy login`'s saved config.

## 0.2.0

- Read models and reliability, create datasets and fit, fleet forecasts and
  the strategy calculators (`reliafy.models.*`, `reliafy.data.*`,
  `reliafy.strategy.*`, `reliafy.fleet.*`).

## 0.1.0

- `push` and `push_params`: send SurPyval models to Reliafy.
