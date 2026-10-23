# The reliability data library

Published generic failure data — failure rates, probabilities of failure on
demand and life distributions — that anyone can search and use as a starting
point in a reliability block diagram. Every record says where it came from
and under what licence, so it can be cited.

- Code: `backend/library/` (`schema.py`, `service.py`, `convert.py`), data in
  `backend/library/data/<source>.json`, one importer per source in
  `backend/scripts/import_<source>.py`.
- Reads: `GET /api/library/*` (public), the MCP `library` tool, `POST
  /api/v1/library/{search,get,sources}` and `reliafy library …` (see
  [api.md](api.md#the-reliability-data-library)).
- Tests: `backend/tests/test_library.py`.

## What may go in

Only data whose licence allows republishing: public-domain government work,
open-government licences, or CC BY. Each record carries its licence and the
attribution text to show with it. A source under any other licence is a link
at most, with no numbers. Data is never scraped from a site whose terms ban
automated extraction: a source's files are downloaded by hand and imported by
a script. Records from different bases (counted field data, handbook
prediction models, certified figures) are kept apart by `basis` and never
combined.

The importer checks every record with `schema.problems` before it writes a
data file, and the tests run the same check over every shipped record: a
record without a source, licence or citation, with an unknown basis or unit,
with parameters that don't match its distribution family, or with a mean or
percentile that disagrees with its parameters, fails the build.

## Sources

| Source | Records | Basis | Licence |
|---|---|---|---|
| `nrc-inl-2020`: NRC / INL industry-average parameter estimates, 2020 update (INL/EXT-21-65055, Table 1) | 300 | field data | U.S. Government work |
| `mil-hdbk-217f-n2`: MIL-HDBK-217F with Notice 2, base failure rates and environment factors | 158 | prediction model | U.S. Government work (Distribution Statement A) |

### NRC / INL industry averages (2020 update)

*Industry-Average Performance for Components and Initiating Events at U.S.
Commercial Nuclear Power Plants: 2020 Update* (Idaho National Laboratory for
the U.S. NRC, November 2021). Table 1 gives, for each component and failure
mode, the failures and demands (or hours) counted at U.S. plants from 2006 to
2020 (some rows older), and the industry-average distribution: beta for a
probability per demand, gamma for a rate per hour, with the 5th percentile,
median, mean, 95th percentile and the parameters.

- Import: download `AvgPara2020.pdf` from
  <https://nrcoe.inl.gov/publicdocs/AvgPerf/AvgPara2020.pdf> by hand, then
  `python -m backend.scripts.import_nrc_inl AvgPara2020.pdf --retrieved
  YYYY-MM-DD` (needs `pdfplumber`, which the app doesn't). The script checks
  the PDF's SHA-256 against the reviewed copy, so a revised report is a
  reviewed change. The PDF isn't committed.
- Kept: 300 of the table's 303 rows. Left out, each with its reason in the
  data file's `skipped`: two point estimates of relief valves opening during
  plant events (event frequencies, not component failures) and one row given
  only as a mean and an error factor.
- Not imported: the report's other tables (train unavailability for test and
  maintenance, special events, initiating-event frequencies). They describe
  plants, not components.
- Rates for leaks, spurious operation, plugging and similar modes are per
  calendar hour (the plant running or shut down); fail-to-run rates are per
  hour of running. Each record says which (`units.time_basis`).
- Where the source's text or its d-or-h column disagrees with the code or the
  distribution, the record keeps the source's text and says so in `notes`.

### MIL-HDBK-217F, Notice 2

*Military Handbook: Reliability Prediction of Electronic Equipment*
(MIL-HDBK-217F, U.S. Department of Defense, 2 December 1991) as amended by
Notice 2 (28 February 1995). Both carry Distribution Statement A: approved
for public release, distribution unlimited. Its part stress models give each
electronic part type a base failure rate λb (failures per million hours) and
multiply it by factors: temperature, electrical stress, quality and the
environment the equipment works in (πE, for 14 environments from ground,
benign to cannon, launch).

- Import: download "Revision F" and "Revision F Change Notice 2" of
  MIL-HDBK-217 from ASSIST
  (<https://quicksearch.dla.mil/qsDocDetails.aspx?ident_number=53939>) by
  hand into one folder as `MIL-HDBK-217F.pdf` and
  `MIL-HDBK-217F-NOTICE-2.pdf`, then `python -m
  backend.scripts.import_mil_hdbk_217f FOLDER --retrieved YYYY-MM-DD` (needs
  `pdfplumber`). The PDFs aren't committed.
- The handbook is a scanned 1990s document whose OCR text misreads digits,
  so the importer doesn't parse it: its tables were typed from the page
  images. Before writing, the script checks each PDF's content fingerprint
  (ASSIST stamps every download with its time, so the file's own SHA-256
  changes from one download to the next; the fingerprint leaves out only that
  stamp) and that every typed number appears in the OCR text of its page,
  apart from the misreads it lists, each checked by eye.
- One record per part type (a resistor or capacitor style, a diode type, a
  switch type...): the base rate, stored per hour, and the section's πE
  table in `environment_factors`. Reliafy uses λb × πE and nothing more; each
  record names the handbook's full model and the factors it leaves out
  (`prediction.not_applied`), and says so in its notes. For connections,
  fuses and a few miscellaneous parts λb × πE (or a fixed rate) is the
  handbook's whole model.
- Kept: 158 part types from sections 6 (diodes, transistors, thyristors,
  optoelectronics), 9 to 15 (resistors, capacitors, transformers and coils,
  elapsed time meters, solid state relays, switches, circuit breakers,
  connectors, sockets), 17 (connections) and 18, 21 to 23 (panel meters,
  filters, fuses, miscellaneous parts). Left out, each with its reason in the
  data file's `skipped`: parts whose base rate isn't one number (a formula of
  temperature, frequency, voltage or complexity: microcircuits, mechanical
  relays, high-frequency transistors, crystals, lamps, motors and others) or
  is per junction, hole or kilometre; tubes and lasers; and the parts count
  method (Appendix A).
- The handbook's spelling and words stay in `source_text`; names are in
  British spelling.

## A record

```json
{
  "id": "nrc-inl-2020:mdp-fts-ns",
  "version": 1,
  "source": "nrc-inl-2020",
  "source_code": "MDP-FTS-NS",
  "name": "Motor-driven pump",
  "label": "Motor-driven pump: fails to start (normally standby)",
  "equipment_type": "pump",
  "kind": "per_demand",
  "basis": "field_data",
  "failure_mode": {"code": "FTS", "name": "Fails to start", "meaning": "Does not start when demanded."},
  "distribution": {"family": "beta", "params": [{"name": "alpha", "value": 2.07}, {"name": "beta", "value": 3520.0}]},
  "summary": {"mean": 0.000588, "median": 0.000496, "p05": 0.000109, "p95": 0.00138, "error_factor": 2.8},
  "units": {"value": "per_demand", "time_basis": null, "as_given": "per demand"},
  "evidence": {"failures": 227, "demands": 410593, "exposure": null, "exposure_unit": null, "components": 1311,
               "sites": null, "period": "2006–2020", "data_source": "EPIX/RADS",
               "method": "Empirical Bayes at plant level, with the Kass-Steffey adjustment"},
  "conditions": {"industry": "U.S. commercial nuclear power plants", "operating_mode": "standby"},
  "source_text": "Motor-Driven Pump Fails To Start, Normally Standby",
  "citation": {"title": "Industry-Average Performance for Components and Initiating Events at U.S. Commercial Nuclear Power Plants: 2020 Update",
               "publisher": "Idaho National Laboratory, for the U.S. Nuclear Regulatory Commission",
               "report": "INL/EXT-21-65055", "edition": "2020 update", "year": 2021, "table": "Table 1",
               "page": "8", "data_sheet": "Appendix A-2.1, p. A-26",
               "url": "https://nrcoe.inl.gov/publicdocs/AvgPerf/AvgPara2020.pdf", "retrieved": "2026-10-23"},
  "licence": {"id": "us-government-work", "name": "U.S. Government work (no copyright asserted)",
              "attribution": "Source: … A U.S. Government work; republished by Reliafy."},
  "notes": []
}
```

| Field | What it is |
|---|---|
| `id` | `<source>:<the source's code, lower case>`. Stable: a later edition is a new source id. |
| `version` | The record's version within its source's data file; bumped when a record is corrected. |
| `source`, `source_code` | The source's id, and the source's own code for the row. |
| `name`, `label` | The component in plain words; the component, failure mode and conditions in one line. |
| `equipment_type` | The library's own equipment types (`schema.EQUIPMENT_TYPES`): valve, pump, generator, electrical, … |
| `kind` | `rate` (failures per unit of exposure), `per_demand` (a probability on each demand) or `life` (a life distribution such as Weibull). |
| `basis` | `field_data`, `prediction_model` or `certificate`. Never mixed. |
| `failure_mode` | The mode's code, plain name and what "failed" means. Rates differ by mode, so a record is one mode. |
| `distribution` | `family` and `params` (SurPyval names). gamma: `alpha` shape, `beta` rate (mean alpha / beta). beta: mean a / (a + b). lognormal: `mu`, `sigma`. point: `value` (no spread). weibull: `alpha` (eta), `beta`. exponential: `failure_rate`. |
| `summary` | `mean` (required), and where the source gives them `median`, `p05`, `p95`, `error_factor`. |
| `units` | `value`: `per_hour`, `per_hour_per_foot` (pipe), `per_demand`, or a life's time unit (`hours`, `cycles`). `time_basis` for a rate: `operating` (hours of running) or `calendar`. `as_given`: the source's unit in words. |
| `evidence` | What the estimate rests on, where the source gives it: failures, demands or exposure (with its unit), components, sites, period, data source, estimation method. |
| `conditions` | Where and how it applies: industry, operating mode (standby / running), system, plant type, rating, service; a handbook's section, specification and style. |
| `environment_factors` | A handbook record only: `symbol` (πE), the `table` and `page`, `values` by environment symbol (`schema.ENVIRONMENTS`: GB ground, benign … CL cannon, launch) and `not_given`, the environments the handbook has no factor for. |
| `prediction` | A prediction model only (required): the handbook's `formula`, the number as printed (`per_million_hours`), `not_applied` (each factor left out, symbol and name; empty when λb × πE is the whole model) and `quality_factor_range`. |
| `source_text` | The source's own description of the row, as given (short; never more than the row). |
| `citation` | Title, publisher, report number, edition, year, table, page (the report's printed page), data sheet, URL, the date retrieved. |
| `licence` | The licence's id (one of `schema.LICENCES`), its name and the attribution text to show with the numbers. |
| `notes` | Anything a careful reader should know about this row: estimated rather than counted, a corrected unit, a source typo. |

A MIL-HDBK-217F record has the same shape: `kind: rate`, `basis:
prediction_model`, `distribution.family: point` (the base rate per hour, no
spread), `units.as_given: failures per million hours`, `failure_mode` "Any
failure" (the handbook's rate covers every mode), with `prediction` and
`environment_factors` as above.

### Later sources, same shape

- **NSWC-11** (mechanical, prediction model): the same, with the model's
  reference and its correction factors in `conditions`.
- **A Weibull table**: `kind: life`, `distribution.family: weibull` with
  `alpha` (eta) and `beta`; a published range goes in `notes` or a record per
  end of it.

## Using a record in a block (`convert.py`)

Pure functions from a record to a model a block can use. Each result names
its record (id, version, citation, licence) and carries a badge saying it's
a generic estimate, so a block never presents it as the user's own data.

- `rate_to_exponential(record, time_unit, time_basis, operating_hours_per_year, length_ft, point, environment)`:
  an exponential with `failure_rate` in the block's time unit, and the rate
  at the 5th and 95th percentiles. Moving between a calendar rate and a
  running-hours rate needs the hours a year the component runs; a pipe's
  rate needs its length; a handbook rate with environment factors needs
  `environment` (a symbol such as `GF`), and is then λb × πE, with an
  assumption naming the factors left out.
- `spread(record, point)`: the point value (mean, or median) and the 5th and
  95th percentiles, computed from the parameters.
- `demand_to_per_demand(record, demands_per_year, time_unit, point)`: the
  probability per demand with its spread, the per-demand reliability and a
  cold-standby spare's start-success probability; with `demands_per_year`, an
  equivalent rate in calendar time.
- `life_to_model(record)`: a Weibull record as a Weibull.
- `to_block_model(record, **options)`: whichever of these fits the record.

A combination that can't convert (a rate as a per-demand probability, a
calendar rate as running hours without the hours a year, a handbook rate
without an environment or in one the handbook gives no factor for) raises
`ConversionError`, saying what to give or use instead. `library get` (and
`GET /api/library/records/{id}`) takes `environment` too; without it, a
handbook record's `environments` lists the rate in each.

## Plans

Library lookups (`library search`, `get` and `sources`) are never counted
against the Free plan's monthly tool calls, or any other plan's allowance:
they're published reference data, readable without an account at
`/api/library`, not calculations.
