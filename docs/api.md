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
| `read` | `/api/v1` reads and calculations: the read-only tools (`guide`, `get`, `list`, `life_data_analysis`, `repairable_analysis`, `strategy`, `rbd_analysis`, `library`, `upgrade_link`, and Reliafy Maintenance's reads) |
| `write` | `/api/v1` creates; every tool that saves, changes, deletes or shares (`models`, `datasets`, `rbd`, `uploads`, `sharing`, `fleet`, Reliafy Maintenance's writes and `maintenance apply`), and photo uploads |

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
POST /api/v1/{tool}              # a tool without actions (guide, upgrade_link, …)
```

The body is a JSON object of the action's arguments, exactly as the MCP tool
takes them (the action itself is in the path). The answer is the tool's
result, the same JSON an AI assistant gets.

```bash
curl -X POST https://reliafy.com/api/v1/life_data_analysis/fit \
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
| A signed-in Free account (session) | the same monthly allowance of tool calls as over MCP, without fitting, fleets and simulations; `guide`, `get account`, `upgrade_link` and `library` lookups aren't counted |
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
/api/v1/maintenance/apply`: a list of the `maintenance_<area>` actions with
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

The entries are two or more of `on_condition`, `fixed_interval` and
`failure_finding`, or `redesign` beside one of them as the interim measure;
`rtf` and `accept` stand alone. Reads add `decision.outcomes` (each with its
task, interval and `task_id`) beside the first entry's `outcome` and `task`.
The app's own route takes the same body (`PUT
/api/maintenance/failure-modes/{id}/decision`).

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
it in the function's `modes`. `products.add_sample` adds the sample
quadcopter product, its design fully scored (on Products, not in the asset
tree).

A function's notes and rationale (`notes` on `failure_modes.add_function` /
`update_function`, up to 25,000 characters on a function) hold the working
behind its performance standards. `standard_basis`, the separate working
before Nov 2026, is still accepted but deprecated: it is added to the notes
under a "Working" line. Reads keep `standard_basis`, `has_basis` and
`basis_preview` describing the notes, and a working written before reads as
part of the notes. Evidence `{type: "working", id}` on a decision links that
function's notes and rationale.

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

### Things only the API can do

MCP tool calls carry JSON, not files. These have no MCP twin, on purpose:

| Call | Does |
|---|---|
| `POST /api/v1/maintenance/photos?target_id=…&caption=…` | Adds a photo to a maintenance position, item, location or work order. The body is the image (JPEG, PNG, WebP or HEIC; at most 20 MB), or multipart with a `file` field. Cleaned and stripped of camera and location metadata, like a photo added in the app. Reliafy Maintenance only; `write` scope. |
| `PUT /api/uploads/{upload_id}?t=…` | Sends a file's bytes to the single-use link from `change upload_create` (no other credentials; at most 30 MB). Then import it: `change dataset_upload`, `change import_rbd`, `change import_excel` or `change rbd_upload_outage_log` with that `upload_id`; a PDF (purpose `document`, at most 20 MB) goes on a maintenance item, position or class with `maintenance attachments.add_document`. |

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
| `GET /api/library/search?q=…&source=…&equipment_type=…&kind=…&page=1&page_size=25` | Matching records, best first, 25 a page (at most 100), with `total`, `pages` and `counts` by equipment type, kind and source. `kind` is `rate`, `per_demand` or `life`. |
| `GET /api/library/records/{id}?environment=…` | One record in full (values, spread, evidence, conditions, citation, licence and notes) and `block_model`: the model an RBD block would use. A handbook rate (MIL-HDBK-217F) depends on the environment the part works in: give `environment` (e.g. `GF`, ground, fixed) for its block model; without it, `environments` lists the rate in each. |
| `GET /api/library/sources` | The sources, their licences and what each holds. |

The same reads are the `library` tool: `POST /api/v1/library/search`
(`query`, `source`, `equipment_type`, `kind`, `page`, `page_size`), `POST
/api/v1/library/get` (`id`, `environment`) and `POST
/api/v1/library/sources`, and on the command line `reliafy list kind library
--query "motor-driven pump"`. Library lookups are never counted against the
Free plan's tool calls. These are generic estimates (today: U.S. nuclear
power plant industry averages, and base failure rates for electronic parts
from the MIL-HDBK-217F prediction handbook), not your own equipment's data;
show each record's `licence.attribution` with its numbers. The record format
and the sources: [library.md](library.md).

### Reliability prediction (a parts count)

A design's failure rate from its parts list and the library's handbook base
rates (MIL-HDBK-217F), before there's any failure data. Each line is a part,
how many there are and its handbook part type (a library record id); its
rate is λb × πE (the environment's factor) × πQ (a quality factor per line,
1 unless given) × quantity, and the system is the sum: MTBF, R(t) at a
mission time, the rate per assembly and a Pareto. Free and exact.

| Call | Does |
|---|---|
| `POST /api/v1/analyse/prediction` | The parts count, saving nothing: `lines` (`[{name, record_id, quantity, quality_factor?, assembly?, reference?}]`), `environment` (`GB`, `GF`, `GM`, `NS`, `NU`, `AIC`, `AIF`, `AUC`, `AUF`, `ARW`, `SF`, `MF`, `ML`, `CL`), `mission_time` (hours, default 1,000). Reliafy Maintenance users may give `product_id` instead of lines: the product's bill of materials comes back as lines to assign. |
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
| `POST /api/v1/datasets/add_measurements` | `dataset_id` with `csv` (text), `upload_id` (a file sent to an upload link; `sheet` for a workbook) or `from_dataset_id` (another dataset's table, copied in). Adds the measurements, or replaces them; refused while a model reads them. |
| `POST /api/v1/datasets/remove_measurements` | `dataset_id`: takes the measurements off (the life data stays). |
| `POST /api/v1/datasets/split` | `dataset_id` whose one table holds life data and readings together (a reading per row, the censoring flag filled in once per unit): splits it into the two parts in place. Columns are guessed; `unit_column`, `age_column`, `censor_column`, `life_columns` and `measurement_columns` override them. |
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
some other program called `reliafy` is already on your path). Version 0.3 needs a Reliafy server with the
tools API above (`GET /api/v1/tools` answers); against an older server it
says so, and the 0.2 functions keep working.

```python
from reliafy import Client

rf = Client(token="rlf_...")                    # or RELIAFY_TOKEN, or `reliafy login`
rf.call("list", "models")
rf.call("life_data_analysis", "fit", data=[120, 340, 510], censored=[0, 0, 1])
rf.call("rbd_analysis", "analyze", rbd_id="…", wait=True)   # waits for a job
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
