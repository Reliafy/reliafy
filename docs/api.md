# Reliafy ingestion API

Automate the data Reliafy otherwise takes by hand: push meter readings,
degradation measurements, and new failure data from scripts, cron jobs, or
your CMMS export pipeline.

> **Pro feature.** On Reliafy Cloud the programmatic API requires a Pro plan.
> (Self-hosted instances have it unconditionally — there are no plans.)

## Authentication

Create a personal token in the app under **API access** (sidebar → Account).
Send it as a bearer header:

```
Authorization: Bearer rlf_XXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX
```

Tokens are **write-only**: they authenticate the `/api/ingest/*` endpoints
and nothing else — a leaked token can push data but can never read your
analyses or touch your account. Revoke tokens any time from the same page.

Rate limit: 120 requests/minute. Row limit: 5,000 rows/request.

## Request bodies

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

## 1. Fleet usage — update meter readings

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

## 2. Degradation measurements — append inspection readings

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

## 3. Dataset lives — append failure data, refit models

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

## 4. Import a model — push from SurPyval

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

## Python example (scheduled job)

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
