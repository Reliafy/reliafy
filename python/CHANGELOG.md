# Changelog

## 0.4.0

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
