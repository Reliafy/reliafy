# Changelog

## Unreleased (0.5.0)

- **Time to the limit**: `maintenance progression.time_to_limit` and `progression.series` for a watched
  band's trend (listed by `reliafy tools`).
- **Signal channels** (Reliafy Maintenance): `push_snapshot` and `reliafy ingest snapshot FILE.json` send a
  vibration burst, a device spectrum or a scalar value to a channel; the new `maintenance signals.*` and
  `signal_data.*` actions are listed by `reliafy tools`.
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
