---
title: "Use Reliafy from scripts: the API and the command line"
task: "How do I fit models, run analyses and push data from a script, a notebook or a nightly job?"
category: "API and automation"
prerequisites: "A Pro plan (for an API token), and Python 3.8 or later for the command line and the Python client."
related_href: "/settings?tab=api"
related_label: "Create an API token"
order: 42
---

Everything you can ask Reliafy's Claude connector to do, you can also do from a
script. The same tools (fit a model, analyse a diagram, plan a test, work out a
replacement interval) answer over plain HTTPS, from the `reliafy` command line,
and from Python. Use them when a job should run without anyone clicking: a fit
that refreshes every week, meter readings pushed every night, results pulled
into a notebook or a report.

This guide walks through the common jobs, start to finish. The
[API reference](/api-docs) has every detail; each step below links to the page
that covers it.

## 1. Create a token

A script signs in with a personal API token. Open **Settings →**
[API access](/settings?tab=api), give the token a name you'll recognise later
("Nightly meter export"), and choose what it can do:

- **Read**: reads and calculations, the tools that change nothing.
- **Write**: anything that saves, changes, shares or deletes.
- **Push data**: the ingest routes only. A token that only pushes data can
  never read your analyses, which makes it the safe choice for a job on a
  shared server.

Press **Create token** and copy it: it starts `rlf_` and is shown only once.
Revoke it on the same page at any time. Scopes, limits and error codes are on
[Tokens and errors](/api-docs/authentication).

## 2. Install the command line and sign in

The command line and the Python client come in one package, with no other
dependencies:

```bash
pip install reliafy-client
reliafy login        # paste the token when asked
reliafy whoami       # your account and plan
```

`reliafy login` saves the token in a file only you can read, so later commands
and scripts need nothing more. On a server, set `RELIAFY_TOKEN` instead. (If
another program called `reliafy` is already on your path, the same command is
installed as `reliafy-client`.)

## 3. Fit a model from a CSV

Take a CSV of failure times with a censoring column, `hours,censored`, where 0
means the unit failed and 1 means it was still running:

```bash
reliafy fit bearings.csv --dist weibull --unit hours --save "Bearing life"
```

```
Fitting 10 rows: times from 'hours', censoring from 'censored' (0 = failed, 1 = still running).
saved: true
model_id: …
url: https://reliafy.com/models/m/…
…
alpha  996.3
beta   3.82
```

The model is saved in your workspace, with its data, exactly as if you'd fitted
it in the app: open the `url` to see the probability plot. Leave out `--save` to
fit without saving, and `--dist` to let Reliafy pick the best distribution.

Two things the command never guesses:

- **Which column is the flag.** A column called `censored` (or `c`) is read as
  0 = failed, 1 = still running. Anything else, such as `status`, needs
  `--censor-column status`.
- **Which way round it is.** If your flag uses 1 for failed, add `--c-invert`
  rather than editing the file.

Every other tool works the same way: `reliafy tools` lists them, and
`reliafy <tool> <action> --help` shows one action's arguments. More on the
[command line](/api-docs/cli) page.

## 4. The same from Python

The package you installed is also a Python client. `Client()` picks up the
token `reliafy login` saved:

```python
from reliafy import Client

rf = Client()
times = [412, 587, 655, 731, 790, 868, 944, 1010, 1105, 1190]
flags = [0, 0, 1, 0, 0, 1, 0, 0, 1, 0]      # 0 = failed, 1 = still running

result = rf.fit(times, distribution="weibull", censored=flags, unit="Hours",
                save_as="Bearing life")
print(result["url"])
```

`rf.call(tool, action, ...)` reaches every tool, with the same arguments the
command line takes:

```python
rf.call("strategy", "optimal_replacement", distribution_id="weibull",
        params=[{"name": "alpha", "value": 996}, {"name": "beta", "value": 3.8}],
        planned_cost=1000, unplanned_cost=8000)
```

A refused call raises `reliafy.ReliafyError` with Reliafy's reason in plain
words. If you fit with [SurPyval](https://github.com/derrynknife/SurPyval) in
your own code, `reliafy.push(model, name=...)` saves that fit, data and all.
More on the [Python client](/api-docs/python) page, and complete scripts on
[Examples](/api-docs/examples).

## 5. Push fleet usage every night

A [fleet forecast](/guides/forecast-fleet-failures-and-spares) is only as good
as each item's current use. Rather than typing meter readings in, let your
maintenance system's nightly export send them. The CSV needs the item's name
(as it appears in the forecast) and its meter reading, and can say when it was
read:

```
name,current_use,read_at
Truck 01,5230,2026-10-21T22:00:00+10:00
Truck 02,4817,2026-10-21T22:00:00+10:00
```

Copy the fleet's ID from its page (**⋯ → Copy ID**), then send the file:

```bash
reliafy ingest usage meters.csv --fleet FLEET_ID
```

Reliafy updates each item, recomputes the forecast, estimates each item's usage
rate from the change since its last reading, and checks the fleet's alerts. A bad
row stops the whole file with a message, and nothing is changed.

To run it every night, add a line to the crontab of the user who ran
`reliafy login` (`crontab -e`). This one sends the export at 2:15 am:

```
15 2 * * * /usr/local/bin/reliafy ingest usage /data/exports/meters.csv --fleet FLEET_ID >> $HOME/reliafy-ingest.log 2>&1
```

Use the full path to `reliafy` (`which reliafy` shows it), because cron runs
with a short `PATH`. A token with only **Push data** is enough. Degradation
readings (`reliafy ingest measurements`) and new failures for a dataset
(`reliafy ingest lives`) work the same way; see
[Original routes and ingest](/api-docs/v1-routes).

## Files and photos

`reliafy upload` sends a CSV or Excel file as a dataset. `reliafy import rbd`
brings in a diagram from BlockSim, Open-PSA, Galileo or RePyability JSON, and
`reliafy import excel` reads an .xlsx workbook: a sheet as a dataset, an FMEA or
RCM worksheet as an RCM study, or Reliafy's RBD template as a diagram. The details are on [Files and photos](/api-docs/files); to import
from the app instead, see [import a diagram](/guides/import-a-diagram).

## Where to go next

- The [tools API](/api-docs/tools) lists every tool and action, live, with the
  OpenAPI spec for generating your own client.
- To work through the same tools in conversation, connect
  [Claude (MCP)](/api-docs/mcp).
- To pass a model to a colleague rather than a script, see
  [share your work](/guides/share-your-work).
