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
| `read` | `/api/v1` reads and calculations: the read-only tools (`guide`, `get`, `list`, `life_data_analysis`, `repairable_analysis`, `strategy`, `rbd_analysis`, `upgrade_link`, and Reliafy Maintenance's reads) |
| `write` | `/api/v1` creates; every tool that saves, changes, deletes or shares (`models`, `datasets`, `rbd`, `uploads`, `rcm`, `sharing`, `fleet`, Reliafy Maintenance's writes), and photo uploads |

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
| A signed-in Free account (session) | the same monthly allowance of tool calls as over MCP, without fitting, fleets and simulations |
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

### Things only the API can do

MCP tool calls carry JSON, not files. These have no MCP twin, on purpose:

| Call | Does |
|---|---|
| `POST /api/v1/maintenance/photos?target_id=…&caption=…` | Adds a photo to a maintenance position, item, location or work order. The body is the image (JPEG, PNG, WebP or HEIC; at most 20 MB), or multipart with a `file` field. Cleaned and stripped of camera and location metadata, like a photo added in the app. Reliafy Maintenance only; `write` scope. |
| `PUT /api/uploads/{upload_id}?t=…` | Sends a file's bytes to the single-use link from `uploads create` (no other credentials; at most 30 MB). Then import it: `datasets upload`, `uploads import_rbd`, `uploads import_excel` or `rbd upload_outage_log` with that `upload_id`; a PDF (purpose `document`, at most 20 MB) goes on a maintenance item, position or class with `maintenance_attachments add_document`. |

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
reliafy life_data_analysis fit --help            # one action's arguments
reliafy strategy optimal_replacement --distribution-id weibull \
    --params '[{"name":"alpha","value":1200},{"name":"beta","value":2.5}]' \
    --planned-cost 200 --unplanned-cost 1500
reliafy models list
reliafy fit failures.csv --dist weibull --censor-column status
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
app URL: `/fleet/forecasts/<fleet_id>`.

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
`/fleet/tracking/<tracked_fleet_id>`.

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
