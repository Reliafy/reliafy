# reliafy-client — Reliafy from Python and the command line

Fit a model anywhere with [SurPyval](https://github.com/derrynknife/SurPyval),
then make it a shareable, trackable, citable artifact in
[Reliafy](https://reliafy.com). Call any Reliafy tool from a script or a
shell, send files and photos, and push data from your CMMS.

```bash
pip install reliafy-client
```

The package installs as `reliafy-client`; you import it as `reliafy`. It
also installs the `reliafy` command, and the same command as
`reliafy-client`: if some other program called `reliafy` is already on your
path, use `reliafy-client`.

Pure standard library: no dependencies. You bring SurPyval to do your own fits.

## Which server

Version 0.3 calls Reliafy's tools API (`POST /api/v1/{tool}/{action}`). It's
on reliafy.com from the release that adds it; a self-hosted server needs a
build that includes it (`GET /api/v1/tools` answers). Against an older server,
the new calls stop with a clear message (`reliafy.ServerTooOld`), and
everything from 0.2 (`reliafy.push`, `reliafy.models.*`, `reliafy.data.*`,
`reliafy.strategy.*`, `reliafy.fleet.*`) keeps working.

## Quick start

```python
import surpyval as sp
import reliafy

# Fit however you like: censored data, offsets, whatever.
model = sp.Weibull.fit(x=failures, c=censoring_flags)

reliafy.configure(token="rlf_...")            # from Reliafy → API access (Pro)
url = reliafy.push(model, name="Pump bearings — 2026 refit", unit="hours")
print(url)                                    # open it in Reliafy
```

`push()` uploads the model **and its fitted data** by default, so Reliafy
shows the full probability plot with confidence bounds, and the model stays
editable and refittable in the app, and can be cited as RCM evidence, used in
RBD blocks, or tracked against a fleet. Offset, limited-failure-population and
zero-inflated fits are detected from the model and reproduced.

```python
# Parameters only (no data upload): functions and life metrics, no plot.
reliafy.push(model, name="From a report", data=False)

# No SurPyval object, just numbers:
reliafy.push_params("weibull", [1200.0, 2.3], name="Handbook value", unit="hours")
```

## Every tool: `Client.call`

Everything Reliafy's AI tools can do, with the same arguments and results:

```python
from reliafy import Client

rf = Client()                                   # token from RELIAFY_TOKEN or `reliafy login`
rf.call("list", "models")
rf.call("life_data_analysis", "fit", data=[120, 340, 510, 700], censored=[0, 0, 1, 0])
rf.call("strategy", "optimal_replacement", distribution_id="weibull",
        params=[{"name": "alpha", "value": 1200}, {"name": "beta", "value": 2.5}],
        planned_cost=200, unplanned_cost=1500)
rf.call("guide", topic="life_data")             # a tool without actions
rf.call("rbd_analysis", "analyze", rbd_id="…", wait=True)   # waits for a long job

rf.tools()                                      # what you may call
rf.spec()                                       # the OpenAPI spec
```

Published failure data from Reliafy's reliability data library, each record
cited with its licence:

```python
found = rf.call("library", "search", query="motor-driven pump fails to start")
record = rf.call("library", "get", id=found["results"][0]["id"])
record["block_model"]                           # the model an RBD block would use
```

Shortcuts for the common things: `rf.list(kind)`, `rf.get(kind, id)`,
`rf.fit(data, distribution=…, censored=…, save_as=…)`,
`rf.reliability(model_id, times)`, `rf.guide(topic)`.

`reliafy.call(tool, action, **args)` does the same with the configured token.
A refused call raises `reliafy.ReliafyError` with `status` (the HTTP status)
and `detail` (what Reliafy said, in plain words).

## Files, photos and data

```python
rf.upload_dataset("bearings.xlsx", name="Bearings")      # CSV or .xlsx
rf.add_measurements(dataset_id, "vibration.csv")         # readings on its units: unit id, age, value
rf.import_rbd("plant.xml")                               # BlockSim, Open-PSA, Galileo, RePyability
rf.import_excel("fmea.xlsx", target="rcm", position_id="…")  # onto a position's RCM
rf.add_photo("nameplate.jpg", target_id="…")             # Reliafy Maintenance
rf.add_document("manual.pdf", target_id="…", kind="manual")  # a PDF, at most 20 MB
rf.download_document(document_id, "manual.pdf")

reliafy.push_usage(fleet_id, [{"name": "Truck 01", "current_use": 5230}])
reliafy.push_readings([{"tag": "PT-101", "value": 4.2}])
reliafy.push_lives(dataset_id, file="new_failures.csv")
```

Files are streamed from disk, not read into memory.

## Many maintenance changes in one call

Reliafy Maintenance's tools can run as a batch: a list of their actions, in
order, with `@ref`s between them, checked on a copy of the workspace before
anything is written. Build a position with its RCM, tasks and parts in one
call:

```python
done = rf.apply([
    {"ref": "p", "do": "positions.create", "args": {"name": "Feed pump A", "parent_id": "…"}},
    {"ref": "f", "do": "failure_modes.add_function", "args": {"position_id": "@p", "text": "Deliver 40 L/s"}},
    {"ref": "ff", "do": "failure_modes.add_functional_failure", "args": {"function_id": "@f", "text": "No flow"}},
    {"ref": "m", "do": "failure_modes.add", "args": {"position_id": "@p", "functional_failure_id": "@ff",
                                                     "text": "Bearing worn"}},
    {"do": "failure_modes.decide", "args": {"failure_mode_id": "@m", "consequence": "operational",
             "decision": {"outcome": "on_condition", "task": "Vibration check", "interval": 3,
                          "interval_unit": "months"}}},
    {"do": "tasks.create", "args": {"position_id": "@p", "name": "Grease bearings", "interval": 500,
                                    "unit": "hours", "source": "oem"}},
], dry_run=False)
done["applied"], done["undo"]      # 6, and the operations that reverse it
```

A delete in a batch (`retire`, `remove_*`, `void`, `cancel`, `merge`,
`disconnect`) names what it deletes with `confirm`; a batch that deletes, or
has over 25 operations, is a dry run unless `dry_run=False`. From the command
line, `reliafy apply ops.json` dry-runs a file of operations and
`reliafy apply ops.json --run` writes them, leaving `ops.undo.json` beside it.

## The command line

```bash
reliafy login                                    # saves your token (only you can read the file)
reliafy tools                                    # every tool and action you may call
reliafy <tool> <action> --arg value …            # any of them; --help on each
reliafy models list
reliafy fit failures.csv --dist weibull --censor-column status --c-invert
reliafy fit failures.csv --dist best --criterion bic   # Best fit ranked by aic (default), aic_c, bic or neg_ll
reliafy push model.json                          # {distribution, params | data, name?, unit?}
reliafy upload bearings.xlsx --name Bearings
reliafy import rbd plant.xml
reliafy photo add IMG_*.jpg --to POSITION_ID --caption Nameplate
reliafy photo link PHOTO_ID --to LOCATION_ID      # show it there too
reliafy photo move PHOTO_ID --to POSITION_ID      # only there
reliafy document add manual.pdf --to ITEM_ID --kind manual
reliafy document get DOCUMENT_ID -o manual.pdf
reliafy ingest usage meters.csv --fleet FLEET_ID
reliafy ingest readings readings.csv
reliafy apply ops.json --run                     # maintenance changes in one call (dry run without --run)
reliafy library search --query "check valve" --kind rate   # published failure data
reliafy library get --id nrc-inl-2020:ckv-fto
reliafy library get --id mil-hdbk-217f-n2:9-1-rc-11 --environment GF   # a handbook rate, ground fixed
```

Values are read as their argument's type: text, numbers, `true`/`false`, JSON
for lists and objects (`--times 100,500,1000` works too), and `@file` reads a
file. `--args '{…}'` gives all the arguments as one JSON object. Add `--json`
for JSON output. `reliafy photo add` and `reliafy document add` report each
file and exit non-zero if any failed.

`reliafy fit` never guesses what a flag column means: Reliafy reads censoring
as 0 = failed, 1 = still running; if yours is 1 = failed, add `--c-invert`.

## Configuration

- `RELIAFY_TOKEN` and `RELIAFY_BASE_URL`, or `reliafy login`, which saves
  them in `~/.config/reliafy/config.json` (`%APPDATA%\reliafy` on Windows;
  `RELIAFY_CONFIG_DIR` to choose).
- Self-hosted: `reliafy.configure(token=…, base_url="https://reliafy.mycompany.com")`,
  `Client(base_url=…)` or `reliafy login --base-url …`. A local server with
  sign-in off needs no token.

## Notes

- The token is a personal API token, created on the **API access** page in
  Reliafy. On Reliafy Cloud this is a Pro feature; self-hosted instances have
  it unconditionally. A token's scopes (read, write, ingest) decide what it
  may do.
- Supported distributions for `push`: Weibull, Exponential, Normal, LogNormal,
  Gamma, LogLogistic, Exponentiated Weibull, Gumbel, Logistic.
- The API in full: [docs/api.md](https://github.com/Reliafy/reliafy/blob/main/docs/api.md),
  and online: [the Python client](https://reliafy.com/api-docs/python) and
  [the command line](https://reliafy.com/api-docs/cli).
- Changes: [CHANGELOG.md](https://github.com/Reliafy/reliafy/blob/main/python/CHANGELOG.md).
