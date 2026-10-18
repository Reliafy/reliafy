# Changelog

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
