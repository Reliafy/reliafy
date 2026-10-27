# Datasets: life data and measurements

A dataset is one document. It holds one table (its **life data**: one row per
unit) and, when the user adds them, its **measurements**: readings taken on
those same units at ages since new, one row per reading. A condition and life
model is fitted to one dataset; a degradation model reads a dataset's
measurements; every life-data fit reads its table. Datasets never point at
each other.

## Why one document

Before this, condition and life took two datasets, one of lifetimes and one of
readings, picked separately. The rules that make a joint model work (the same
units, the same clock since new, the same time unit) are rules about one set
of data, and two separate datasets let them drift apart: a reading dataset
with no lifetimes is useless on its own, and the "Lifetimes / Readings" picker
asked the user to say twice what they said once when they uploaded. The data
is one thing, so it is one dataset: the life data in one part of the document,
the measurements in the other, linked by unit id inside it. "Pick one dataset
and make a joint model of it."

## Storage

`backend/schema.py`:

```
Dataset
  id, name, owner_id, created_at, notes, updated_by
  data        bytes   the table as CSV (life data, or readings alone)
  columns     [{name, dtype}]
  n_rows
  checksum    sha256 of data (datasets are content-addressed per owner)
  measurements           optional DatasetPart
    data      bytes   the readings as CSV
    columns   [{name, dtype}]
    n_rows
    checksum  sha256 of the part
```

Both parts are stored the way the one table always was: the raw CSV bytes,
read back with `read_dataframe` under the same shape limits. Nothing else in
the document changed, so every reader of `data`, `columns`, `n_rows` and
`checksum` works as before; a dataset without the part is exactly what was
stored before.

The dataset's own `checksum` stays the life data's. Uploading the same life
data again opens the dataset you already have (with its measurements); the
tag cache is keyed on both checksums.

## Limits

- Each part is held to `MAX_UPLOAD_BYTES` (5 MB) as a dataset always was.
- Together the two parts are held to `MAX_DATASET_BYTES` (12 MB): the
  document, with its columns and checksums, stays well under Mongo's 16 MB.
  A pair over it is refused in words ("Together, the life data (x MB) and the
  measurements (y MB) are too large for one dataset…"), nothing is written.
- The condition and life fit has its own limits (2,000 units, 20,000
  readings) because the request travels to the calculation service whole.
- On the shared free cluster (512 MB in all) the Free plan's dataset cap
  bounds what one account can store; a two-part dataset counts once.

## Which part an analysis reads

| Analysis | Reads |
|---|---|
| Non-repairable, regression, accelerated life, repairable, compare groups | the table (`load_dataframe`) |
| Degradation | the measurements part when there is one, else the table (`load_measurements`) |
| Condition and life | the table as life data and the measurements as readings; with no part, the one table as both (the rows whose censoring flag is filled in are the lifetimes, every row a reading) |

A dataset of readings alone (how readings were saved before measurements had
a part of their own, e.g. the brake-pad sample) keeps them in its table. Its
page shows them on the Measurements tab and offers **Add life data**: the
new table becomes the dataset's table and the readings become its
measurements, so a degradation model fitted to them keeps reading them.

## Tags

The tags are detected from the table as before, plus **Measurements** when
the part exists. "Use for" then leads with the condition and life model; the
summary adds the readings ("40 pumps · 35 failed · 314 readings").

## Creating a dataset with measurements

- **New dataset** (the app): the file, paste or typed-in table, with an
  optional second table of readings in the same dialog. The dataset is
  created, then the readings are added to it.
- **A dataset's page**: **Add measurements** / **Replace measurements** /
  **Remove measurements** in its menu, and the empty Measurements tab.
- **One long table** of life data and readings (one row per reading, the
  censoring flag filled in once per unit): its page offers to **split** it
  into the two parts. The split keeps the column names, so a model fitted to
  the one table refits the same from the two. A split is refused under a
  model that reads the table as life data.
- **API**: `PUT /api/datasets/{id}/measurements` (a file; `/paste` for text),
  `DELETE /api/datasets/{id}/measurements`, `PUT /api/datasets/{id}/life`
  (readings alone), `POST /api/datasets/{id}/split`. The dataset's detail
  carries `measurements` (columns, row count, preview, column facts) and
  `profile.split` (the plan for one table).
- **MCP, REST v1, CLI**: `datasets add_measurements` (`csv`, an `upload_id`,
  or `from_dataset_id` to copy another dataset's table in),
  `datasets remove_measurements`, `datasets split`; `get kind dataset` takes
  `part=measurements`; `list kind datasets` shows each dataset's
  `measurements`. On the command line, `reliafy upload readings.csv
  --measurements-for DATASET_ID`.

Measurements a model reads (a condition and life model fitted to the dataset,
a degradation model) can't be replaced or removed until the model is deleted,
as a dataset can't be deleted under its models.

## Condition and life models

`spec.dataset_id` names the one dataset, with `mapping` (the life data's
columns) and `readings_mapping` (the measurements'). The MCP `fit_joint`
actions take `dataset_id`; the app's `/api/joint/*` routes take `dataset_id`
and still accept the two ids as before.

Models saved before this carry `spec.lifetimes_dataset_id` and
`spec.readings_dataset_id` (two datasets, or the same one twice). They open,
refit and export as they always did (`services/joint.frames_for`), and
`dependents_for_dataset` still counts the readings dataset as theirs.
`backend/scripts/migrate_joint_datasets.py` (a dry run by default) brings
them onto `dataset_id`: the same id twice is simply renamed; two datasets have
the readings dataset's table copied into the lifetimes dataset as its
measurements, and the readings dataset is reported as no longer used by that
model. A migrated model reads exactly the rows it read before.
