"""Dataset persistence: store uploaded CSVs (in MongoDB) and read them back as
DataFrames.

A dataset is one document holding one table (``data``) and, when the user
adds them, its measurements (``measurements``: readings on the same units at
ages since new, as a second CSV in the same document). The two are linked by
unit id inside the dataset; a dataset never points at another. See
docs/datasets.md for the shape, the limits and why."""

from __future__ import annotations

import re
import uuid
from datetime import datetime, timezone

import pandas as pd

from backend import storage
from backend.services import access
from backend.db import from_doc, to_doc
from backend.fitting import FitError
from backend.fitting import preview as _preview
from backend.fitting import csv_error_message, header_guess, read_csv_capped, read_dataframe, with_generic_header
from backend.schema import Dataset, DatasetPart, Model


def _list_query(owner_id, shared=frozenset()):
    """Owner-scoped filter, optionally unioned with directly-shared ids."""
    query = {"owner_id": {"$in": access.owner_in(owner_id)}}
    if shared:
        return {"$or": [query, {"_id": {"$in": sorted(shared)}}]}
    return query

def pasted_header_guess(content: str) -> int:
    """:func:`backend.fitting.header_guess` for pasted text, split on the
    delimiter :func:`normalize_pasted` would choose."""
    from backend.fitting import first_row_is_data

    text = (content or "").strip()
    header = next((ln for ln in text.splitlines() if ln.strip()), "")
    delim = max("\t,;|", key=lambda d: header.count(d))
    return 0 if first_row_is_data(header, delim) else 1


def normalize_pasted(content: str, no_header: bool = False) -> bytes:
    """Parse pasted tabular text (CSV or TSV) into canonical CSV bytes.

    The delimiter is chosen from a fixed set (tab / comma / semicolon / pipe)
    by counting occurrences in the header row — so spreadsheet paste (tabs)
    and CSV both work — rather than letting pandas sniff any character (which
    can wrongly split on letters in single-column data). Everything downstream
    then sees a plain CSV. ``no_header``: the first row is data, and the
    columns are named ``col 1``, ``col 2``, ….
    """
    import io

    from backend import config

    text = (content or "").strip()
    if len(text) > config.MAX_UPLOAD_BYTES:
        raise FitError(
            f"That's too much data to paste ({len(text) / (1024 * 1024):.1f} MB). "
            f"The limit is {config.MAX_UPLOAD_BYTES / (1024 * 1024):.0f} MB — upload it as a file instead."
        )
    if not text:
        raise FitError("Nothing to import — paste some data first (with a header row).")

    header = next((ln for ln in text.splitlines() if ln.strip()), "")
    delim = max("\t,;|", key=lambda d: header.count(d))
    if header.count(delim) == 0:
        raise FitError(
            "Only one column was detected. Separate columns with commas or tabs "
            "and include a header row."
        )
    try:
        df = read_csv_capped(io.StringIO(text), sep=delim, width_text=header,
                             engine="python", skipinitialspace=True,
                             **({"header": None} if no_header else {}))
    except FitError:
        raise
    except Exception as exc:
        raise FitError(csv_error_message(exc, text, what="the pasted data")) from exc
    if df.empty or df.shape[1] == 0:
        raise FitError("Couldn't find any rows — data needs a header row and at least one data row.")
    if df.shape[1] == 1:
        raise FitError(
            "Only one column was detected. Separate columns with commas or tabs "
            "and include a header row."
        )
    if no_header:
        df.columns = [f"col {i + 1}" for i in range(df.shape[1])]
    return df.to_csv(index=False).encode()


def check_size(data: bytes) -> None:
    """Refuse a file over ``MAX_UPLOAD_BYTES`` in words."""
    from backend import config

    if len(data) > config.MAX_UPLOAD_BYTES:
        mb = config.MAX_UPLOAD_BYTES / (1024 * 1024)
        raise FitError(
            f"That file is too large ({len(data) / (1024 * 1024):.1f} MB). "
            f"The limit is {mb:.0f} MB — try trimming unused columns or rows."
        )


def apply_generic_header(file_bytes: bytes) -> bytes:
    """No-header upload: the first row is kept as data, the columns named
    ``col 1``, ``col 2``, … (see :func:`backend.fitting.with_generic_header`).
    The size is checked before parsing, and again after the rewrite (which
    lengthens the file)."""
    check_size(file_bytes)
    out = with_generic_header(file_bytes)
    check_size(out)
    return out


def resolve_no_header(file_bytes: bytes, no_header: bool | None) -> tuple[bool, int]:
    """Whether to read a CSV as having no header row, and the guess: the
    header row's number, 1 (the first row) or 0 (none). ``no_header`` None
    takes the guess, so a first row of only numbers is kept as data (#434)."""
    guess = header_guess(file_bytes)
    return (guess == 0 if no_header is None else bool(no_header)), guess


def create_dataset(db, name: str, file_bytes: bytes, owner_id: str, no_header: bool = False) -> Dataset:
    """Persist a CSV (content-addressed) and return the Dataset.

    Datasets are de-duplicated by checksum *per owner* so saving several models
    from the same upload reuses one dataset, while different users keep their
    own isolated copies. ``no_header`` treats the file as having no header row:
    generic ``col N`` names are added so the first data row isn't lost.
    """
    return create_or_reuse(db, name, file_bytes, owner_id, no_header=no_header)[0]


def create_or_reuse(db, name: str, file_bytes: bytes, owner_id: str,
                    no_header: bool = False) -> tuple[Dataset, bool]:
    """``create_dataset``, also saying whether identical data already existed
    (``True``: the existing dataset, under its own name, came back) — so the
    app can tell the user rather than silently dropping the new name."""
    check_size(file_bytes)
    if no_header:
        file_bytes = apply_generic_header(file_bytes)

    digest = storage.checksum(file_bytes)
    existing = db.datasets.find_one({"checksum": digest, "owner_id": owner_id})
    if existing is not None:
        return from_doc(Dataset, existing), True

    df = read_dataframe(file_bytes)
    columns = [{"name": str(c), "dtype": str(df[c].dtype)} for c in df.columns]

    dataset = Dataset(
        id=uuid.uuid4().hex,
        name=name,
        owner_id=owner_id,
        checksum=digest,
        n_rows=int(df.shape[0]),
        columns=columns,
        data=file_bytes,
    )
    db.datasets.insert_one(to_doc(dataset))
    return dataset, False


def preview_frame(db, owner_id, dataset_id: str | None, file_bytes: bytes | None) -> tuple[pd.DataFrame, str | None]:
    """The data for a preview fit and the saved dataset's id: a saved dataset
    by id (in ``owner_id``'s scope), or an upload parsed in memory, whose id is
    None. A preview stores nothing; saving the model stores the upload."""
    if dataset_id:
        dataset = get_dataset(db, dataset_id, owner_id=owner_id)
        if dataset is None:
            raise FitError("Dataset not found.")
        return load_dataframe(dataset), dataset.id
    if file_bytes is not None:
        return read_dataframe(file_bytes), None
    raise FitError("Provide a CSV file or a dataset_id.")


def upload_denial(db, ctx, dataset_id: str | None, file) -> tuple[int, dict] | None:
    """``store_denial`` for a save request that may carry an upload: None when
    it names a dataset instead. Reads the upload and rewinds it for the save."""
    if dataset_id or file is None:
        return None
    from backend.http_limits import read_upload

    contents = read_upload(file)
    file.file.seek(0)
    return store_denial(db, ctx, contents)


def store_denial(db, ctx, file_bytes: bytes) -> tuple[int, dict] | None:
    """Why this upload can't be stored as a new dataset in the active
    workspace, as ``(status, payload)``, or None when it can.

    The same checks as the dataset upload: a frozen team or view-only member
    can't write, and a personal workspace at its plan's dataset cap can only
    re-use data it already holds (same checksum)."""
    from backend.services import billing as billing_service

    denied = access.workspace_write_denial(ctx)
    if denied is not None:
        return denied
    if (
        not ctx.is_personal
        or billing_service.is_admin_user(ctx.user)
        or not billing_service.would_exceed_cap(db, ctx.uid, "datasets")
    ):
        return None
    if db.datasets.find_one({"checksum": storage.checksum(file_bytes), "owner_id": ctx.write_owner}) is not None:
        return None
    return 402, {"detail": billing_service.cap_message(db, ctx.uid, "datasets"), "code": "cap", "upgrade": True}


def default_name(filename: str | None) -> str:
    """A dataset's name from its file when none is given: "pump_test.csv" →
    "pump_test" (the extension adds nothing once it's a dataset)."""
    base = (filename or "").strip()
    stem = re.sub(r"\.(csv|tsv|txt|xlsx|xlsm|xls)$", "", base, flags=re.IGNORECASE).strip()
    return stem or base or "dataset"


def get_dataset(db, dataset_id: str, owner_id: str | list[str] | None = None) -> Dataset | None:
    """Fetch a dataset by id, optionally scoped to its owner.

    ``owner_id`` is optional so internal callers (the re-fit path) can fetch by
    id; external/API callers always pass it so a non-owner gets ``None`` (404).
    Shared sample datasets are visible to every owner. Ids are strings;
    anything else (e.g. from a JSON body) matches nothing.
    """
    if not isinstance(dataset_id, str):
        return None
    query = {"_id": dataset_id}
    if owner_id is not None:
        query["owner_id"] = {"$in": access.owner_in(owner_id)}
    return from_doc(Dataset, db.datasets.find_one(query))


def list_datasets(db, owner_id: str | list[str], hidden=frozenset(), shared=frozenset()) -> list[Dataset]:
    """The owner's datasets plus the shared samples, newest first.

    ``hidden`` is the set of sample ids this user has dismissed; they're left
    out so a "deleted" sample stays gone for them.
    """
    return [
        from_doc(Dataset, d)
        for d in db.datasets.find(
            _list_query(owner_id, shared)
        ).sort("created_at", -1)
        if d["_id"] not in hidden
    ]


def load_dataframe(dataset: Dataset) -> pd.DataFrame:
    """The dataset's table: its life data (or, for a dataset of readings
    alone, those readings). Every life-data fit reads this."""
    return read_dataframe(bytes(dataset.data))


def load_measurements(dataset: Dataset) -> pd.DataFrame:
    """The dataset's readings: its measurements part, or its one table when
    that is all it holds (a dataset of readings alone, as saved before
    measurements had a part of their own). Degradation and condition and
    life fits read this."""
    if dataset.measurements is not None:
        return read_dataframe(bytes(dataset.measurements.data))
    return load_dataframe(dataset)


def preview_rows(dataset: Dataset, rows: int = 8, distinct: bool = False) -> dict:
    """Column names + a small sample of rows for the dataset detail view
    (``distinct``: with each column's distinct-value count, see preview)."""
    return _preview(bytes(dataset.data), rows, distinct=distinct)


def preview_measurements(dataset: Dataset, rows: int = 8, distinct: bool = False) -> dict | None:
    """``preview_rows`` of the measurements part, or None without one."""
    if dataset.measurements is None:
        return None
    return _preview(bytes(dataset.measurements.data), rows, distinct=distinct)


# ---- The measurements part ---------------------------------------------------------

def _now() -> datetime:
    return datetime.now(timezone.utc)


def check_dataset_size(primary: bytes, measurements: bytes | None) -> None:
    """Refuse two tables that together don't fit one dataset document
    (``MAX_DATASET_BYTES``, well under Mongo's 16 MB), in words."""
    from backend import config

    n_life = len(primary)
    n_meas = len(measurements or b"")
    if n_life + n_meas > config.MAX_DATASET_BYTES:
        mb = 1024 * 1024
        raise FitError(
            f"Together, the life data ({n_life / mb:.1f} MB) and the measurements ({n_meas / mb:.1f} MB) are "
            f"too large for one dataset. The limit is {config.MAX_DATASET_BYTES / mb:.0f} MB: trim unused "
            "columns, or thin the readings (every other one, say)."
        )


def build_part(csv_bytes: bytes, no_header: bool = False) -> DatasetPart:
    """A dataset part (a table stored as the dataset's own is) from CSV
    bytes: size-checked, parsed once for its columns and row count."""
    check_size(csv_bytes)
    if no_header:
        csv_bytes = apply_generic_header(csv_bytes)
    df = read_dataframe(csv_bytes)
    return DatasetPart(
        checksum=storage.checksum(csv_bytes),
        n_rows=int(df.shape[0]),
        columns=[{"name": str(c), "dtype": str(df[c].dtype)} for c in df.columns],
        data=csv_bytes,
    )


def set_measurements(db, dataset: Dataset, csv_bytes: bytes, owner_id: str,
                     no_header: bool = False) -> Dataset:
    """Add the measurements (readings at ages: unit id, age, value, …) to an
    owned dataset, or replace them. The unit ids are matched to the life
    data's when a model is fitted (where the columns are mapped); here the
    table only has to read, and both tables have to fit one document."""
    part = build_part(csv_bytes, no_header)
    check_dataset_size(bytes(dataset.data), part.data)
    res = db.datasets.update_one({"_id": dataset.id, "owner_id": owner_id},
                                 {"$set": {"measurements": part.model_dump(), "updated_at": _now()}})
    if res.matched_count == 0:
        raise FitError("Dataset not found.")
    return get_dataset(db, dataset.id)


def remove_measurements(db, dataset: Dataset, owner_id: str) -> Dataset:
    """Take the measurements part off an owned dataset (the life data stays).
    Callers refuse while a model reads the part (``measurements_dependents``)."""
    res = db.datasets.update_one({"_id": dataset.id, "owner_id": owner_id},
                                 {"$unset": {"measurements": ""}, "$set": {"updated_at": _now()}})
    if res.matched_count == 0:
        raise FitError("Dataset not found.")
    return get_dataset(db, dataset.id)


def set_life_data(db, dataset: Dataset, csv_bytes: bytes, owner_id: str, no_header: bool = False) -> Dataset:
    """Give a dataset of readings alone its life data: the new table becomes
    the dataset's table and the readings it held become its measurements, so
    a degradation model fitted to the readings keeps reading them
    (``load_measurements``). A dataset that already has both parts keeps
    them: its life data is what its models were fitted to."""
    if dataset.measurements is not None:
        raise FitError("This dataset already has life data and measurements. To start from other life data, "
                       "make a new dataset.")
    others = [d for d in dependents_for_dataset(db, dataset.id, owner_id) if d["collection"] != "degradation_models"]
    if others:
        raise FitError(f"{dependents_message(others)} Those models read this table as it is, so its life data "
                       "can't be replaced; make a new dataset instead.")
    check_size(csv_bytes)
    if no_header:
        csv_bytes = apply_generic_header(csv_bytes)
    readings = DatasetPart(checksum=dataset.checksum, n_rows=dataset.n_rows, columns=list(dataset.columns),
                           data=bytes(dataset.data))
    check_dataset_size(csv_bytes, readings.data)
    df = read_dataframe(csv_bytes)
    res = db.datasets.update_one({"_id": dataset.id, "owner_id": owner_id}, {"$set": {
        "data": csv_bytes,
        "checksum": storage.checksum(csv_bytes),
        "n_rows": int(df.shape[0]),
        "columns": [{"name": str(c), "dtype": str(df[c].dtype)} for c in df.columns],
        "measurements": readings.model_dump(),
        "updated_at": _now(),
    }})
    if res.matched_count == 0:
        raise FitError("Dataset not found.")
    return get_dataset(db, dataset.id)


# ---- One table of life data and readings, split into the two parts ------------------

def split_plan(df: pd.DataFrame) -> dict | None:
    """How one long table of life data and readings would split into the
    two parts, or None when the table isn't one.

    Such a table has one row per reading, with each unit's outcome (its
    censoring flag) written once, on one of its rows (its last, usually).
    The plan: ``unit`` and ``age`` (both tables), ``censor`` (the life data),
    ``life_columns`` (constant within a unit: covariates) and
    ``measurement_columns`` (varying within a unit: the readings), plus the
    counts the notice shows."""
    unit = _unit_column(df)
    censor = _censor_column(df)
    if not unit or not censor:
        return None
    flagged = df[censor].notna()
    if flagged.sum() >= len(df) or flagged.groupby(df[unit]).sum().max() > 1:
        return None  # one flag per unit on some rows, readings on the rest
    numeric = [str(c) for c in df.columns if str(c) not in (unit, censor) and pd.api.types.is_numeric_dtype(df[c])]
    ages = [c for c in numeric if _TIME_NAME_RE.search(c)] or numeric[:1]
    if not ages:
        return None
    age = ages[0]
    life_columns, measurement_columns = [], []
    for c in map(str, df.columns):
        if c in (unit, censor, age):
            continue
        varies = bool((df.groupby(unit)[c].nunique(dropna=True) > 1).any())
        (measurement_columns if varies else life_columns).append(c)
    if not measurement_columns:
        return None
    n_units = int(df[unit].nunique(dropna=True))
    return {
        "unit": unit, "age": age, "censor": censor,
        "life_columns": life_columns, "measurement_columns": measurement_columns,
        "n_units": n_units, "n_readings": int(len(df)),
        # Units with no flagged row have no outcome: they'd be left out of the life data.
        "n_without_outcome": n_units - int(df.loc[flagged, unit].nunique(dropna=True)),
    }


def split_frames(df: pd.DataFrame, plan: dict) -> tuple[pd.DataFrame, pd.DataFrame]:
    """``(life, readings)`` as the plan says: the life data is each unit's
    flagged row (its age there is its age at failure or now), the readings
    are every row. The column names are kept, so a model fitted to the one
    table (its columns mapped) refits the same from the two."""
    for key in ("unit", "age", "censor"):
        if plan.get(key) not in df.columns:
            raise FitError(f"The {key} column {plan.get(key)!r} isn't in the table.")
    for c in [*(plan.get("life_columns") or []), *(plan.get("measurement_columns") or [])]:
        if c not in df.columns:
            raise FitError(f"Column {c!r} isn't in the table.")
    unit, age, censor = plan["unit"], plan["age"], plan["censor"]
    life = df.loc[df[censor].notna(), [unit, age, censor, *(plan.get("life_columns") or [])]]
    readings = df[[unit, age, *(plan.get("measurement_columns") or [])]]
    if life.empty:
        raise FitError("No row has the censoring flag filled in, so there is no life data to split off.")
    return life.reset_index(drop=True), readings.reset_index(drop=True)


def split_dataset(db, dataset: Dataset, owner_id: str, plan: dict | None = None) -> tuple[Dataset, dict]:
    """Split an owned dataset's one table of life data and readings into its
    two parts, in place: the life data becomes the dataset's table and the
    readings its measurements. ``plan`` overrides the guessed one (its
    columns). Models that read the one table as readings (degradation,
    condition and life) refit the same from the parts; any fitted to it as
    life data make the split refuse."""
    df = load_dataframe(dataset)
    guessed = split_plan(df)
    if plan:
        plan = {**(guessed or {}), **{k: v for k, v in plan.items() if v is not None}}
        if "measurement_columns" not in plan or "life_columns" not in plan:
            raise FitError("Say which columns are the readings (measurement_columns) and which describe the unit "
                           "(life_columns).")
    else:
        plan = guessed
    if not plan:
        raise FitError("This table doesn't look like life data and readings in one: it needs a unit id column, a "
                       "censoring flag filled in once per unit, and a reading column that changes along a unit's rows.")
    if dataset.measurements is not None:
        raise FitError("This dataset already has its measurements as a part of its own.")
    life_fits = [d for d in dependents_for_dataset(db, dataset.id, owner_id)
                 if d["collection"] in ("models", "alt_models", "recurrent_models")
                 and d.get("model_kind") != "joint"]
    if life_fits:
        raise FitError(f"{dependents_message(life_fits)} Those models read this table as life data, so it can't be "
                       "split under them; make a new dataset from the file instead.")
    life, readings = split_frames(df, plan)
    life_bytes = life.to_csv(index=False).encode()
    part = build_part(readings.to_csv(index=False).encode())
    check_dataset_size(life_bytes, part.data)
    res = db.datasets.update_one({"_id": dataset.id, "owner_id": owner_id}, {"$set": {
        "data": life_bytes,
        "checksum": storage.checksum(life_bytes),
        "n_rows": int(life.shape[0]),
        "columns": [{"name": str(c), "dtype": str(life[c].dtype)} for c in life.columns],
        "measurements": part.model_dump(),
        "updated_at": _now(),
    }})
    if res.matched_count == 0:
        raise FitError("Dataset not found.")
    return get_dataset(db, dataset.id), plan


def models_for_dataset(db, dataset_id: str, owner_id: str, hidden=frozenset()) -> list[Model]:
    """Models fitted from this dataset that this owner can see (newest first).

    Includes the owner's own models and any shared sample models, minus samples
    the user has hidden.
    """
    return [
        from_doc(Model, m)
        for m in db.models.find(
            {"dataset_id": dataset_id, "owner_id": {"$in": access.owner_in(owner_id)}}
        ).sort("created_at", -1)
        if m["_id"] not in hidden
    ]


# Every saved model kind that keeps a reference to the dataset it was fitted
# to, and refits from it (life and regression models, ALT, recurrent and
# degradation models).
DEPENDENT_COLLECTIONS = (
    ("models", "model"),
    ("alt_models", "ALT model"),
    ("recurrent_models", "recurrent model"),
    ("degradation_models", "degradation model"),
)


def dependents_for_dataset(db, dataset_id: str, owner_id, hidden=frozenset()) -> list[dict]:
    """``[{kind, collection, id, name}]``: every saved model of any kind fitted
    to this dataset that this owner can see — what deleting the dataset would
    leave unable to refit (#265). Hidden samples are left out."""
    out = []
    for collection, kind in DEPENDENT_COLLECTIONS:
        # A condition and life (joint) model saved before datasets held their
        # measurements was fitted to a second dataset too, its readings
        # (``spec.readings_dataset_id``); one saved since reads one dataset.
        uses = ({"$or": [{"dataset_id": dataset_id}, {"spec.readings_dataset_id": dataset_id}]}
                if collection == "models" else {"dataset_id": dataset_id})
        for d in db[collection].find(
            {**uses, "owner_id": {"$in": access.owner_in(owner_id)}}
        ).sort("created_at", -1):
            if d["_id"] in hidden:
                continue
            model_kind = d.get("kind") if collection == "models" else None
            out.append({"kind": "condition and life model" if model_kind == "joint" else kind,
                        "collection": collection, "id": d["_id"], "name": d.get("name") or "",
                        "owner_id": d.get("owner_id"), "model_kind": model_kind})
    return out


def measurements_dependents(db, dataset_id: str, owner_id, hidden=frozenset()) -> list[dict]:
    """The dependents that read the dataset's measurements: condition and
    life models fitted to it, and degradation models (which take the
    measurements part when there is one). Replacing or removing the part
    would leave them unable to refit."""
    return [d for d in dependents_for_dataset(db, dataset_id, owner_id, hidden)
            if d["collection"] == "degradation_models" or d.get("model_kind") == "joint"]


def dependent_counts(db, owner_id, hidden=frozenset()) -> dict[str, int]:
    """``{dataset_id: n}``: how many saved models of any kind (the
    ``DEPENDENT_COLLECTIONS``) this owner can see are fitted to each dataset —
    the list's "Used by N models"."""
    counts: dict[str, int] = {}
    for collection, _kind in DEPENDENT_COLLECTIONS:
        for d in db[collection].find(
            {"owner_id": {"$in": access.owner_in(owner_id)}}, {"dataset_id": 1, "spec.readings_dataset_id": 1}
        ):
            if d["_id"] in hidden:
                continue
            for ds_id in {d.get("dataset_id"), (d.get("spec") or {}).get("readings_dataset_id")}:
                if ds_id:
                    counts[ds_id] = counts.get(ds_id, 0) + 1
    return counts


# Column names that identify a unit (a system, an item, a serial number).
_UNIT_NAME_RE = re.compile(
    r"(^|[_\s])(id|unit|item|serial|sn|asset|system|equipment|machine|compressor|pump|"
    r"vehicle|truck|engine|component|tag|pad|part)s?($|[_\s\d])",
    re.IGNORECASE,
)


def repeated_units(df: pd.DataFrame) -> dict | None:
    """Rows that are histories of units rather than one row per unit, or None.

    ``{"column": <unit column>, "kind": "recurrent" | "degradation" |
    "time_varying"}`` when a unit-like text column (an id-ish name, or values
    that carry digits, e.g. "CMP-1") repeats, and some numeric column rises
    within every unit in file order — the events of a repairable system
    ("recurrent"), or measurements on a shared time grid ("degradation").
    Start and stop rows (each a stretch of a unit's life at one set of
    covariate values, the next starting where the last stopped) are
    "time_varying", with ``start`` and ``stop`` naming the columns: a
    non-repairable fit with covariates that change over time reads them, not
    a degradation fit, though their start times rise like readings do.
    Comparing groups or fitting a life distribution to such rows would treat
    each event as a separate unit.
    """
    n = len(df)
    if n < 4:
        return None
    numeric = [c for c in df.columns if pd.api.types.is_numeric_dtype(df[c])]
    for g in df.columns:
        if g in numeric:
            continue
        col = df[g].dropna().astype(str)
        if col.empty:
            continue
        sizes = col.groupby(col).size()
        if len(sizes) == len(col) or (sizes >= 2).mean() < 0.5:
            continue
        digits = sizes.index.to_series().str.contains(r"\d").mean()
        if not (_UNIT_NAME_RE.search(str(g)) or digits >= 0.8):
            continue
        periods = _start_stop_columns(df.loc[col.index], col, numeric)
        if periods:
            return {"column": str(g), "kind": "time_varying", "start": periods[0], "stop": periods[1]}
        for t in numeric:
            sub = df.loc[col.index, [t]].assign(_g=col)
            steps = sub.groupby("_g")[t].diff().dropna()
            if steps.empty or not (steps > 0).all():
                continue
            # A time grid shared by the units reads as measurements over time.
            seen_in = sub.groupby(t)["_g"].nunique()
            shared = sub[t].map(seen_in).gt(1).mean()
            return {"column": str(g), "kind": "degradation" if shared >= 0.5 else "recurrent"}
    return None


def _start_stop_columns(df: pd.DataFrame, unit: pd.Series, numeric: list) -> tuple[str, str] | None:
    """The (start, stop) columns of start-and-stop rows, or None.

    Two numeric columns where every row's start is at or before its stop, and
    either they're named like a start and a stop ("start_h", "stop_h";
    "entry", "exit") or, within each unit, most rows start where the unit's
    previous row stopped (the periods follow on from each other)."""
    for a in numeric:
        for b in numeric:
            if a == b:
                continue
            lo, hi = df[a], df[b]
            if lo.isna().any() or hi.isna().any() or not (lo <= hi).all() or not (lo < hi).any():
                continue
            if _START_RE.search(str(a)) and _STOP_RE.search(str(b)):
                return str(a), str(b)
            previous_stop = hi.groupby(unit).shift(1)
            follows = previous_stop.notna()
            if follows.sum() >= 2 and (lo[follows] == previous_stop[follows]).mean() >= 0.8:
                return str(a), str(b)
    return None


# What a dataset holds, as tags on the Data list (planning #261). Detected
# from the columns; the "use for" line says which analyses take it.
TAGS = ("Non-repairable", "Repairable", "Covariates", "Time-varying covariates", "Measurements")
_CENSOR_NAME_RE = re.compile(r"(^c$|censor|status|failed|event|^c_)", re.IGNORECASE)
# Flags that are 1 when the unit FAILED ("failed", "event", "status"), the
# other way round from Reliafy's 0 = failed. The same rule as the fit
# wizard's ``censorInverted`` (frontend/src/datasetGuess.js), so the Data
# list counts failures the way a fit from the dataset reads them.
_FAILED_NAME_RE = re.compile(
    r"(is_?)?(fail|failed|failure|failures|event|status|dead|death|broken)(_?flag)?",
    re.IGNORECASE,
)
# Interval-censored data has two time columns (the failure lies between them): SurPyval's xl / xr,
# the shortest / longest a saved Bayesian update writes, or a plain left / right, lower / upper.
_TIME_NAME_RE = re.compile(
    r"(^x$|^t$|^xl$|^xr$|^tl$|^tr$|hour|time|age|day|week|month|year|cycle|km|mile|start|stop|end|date|observ"
    r"|shortest|longest|^left$|^right$|^lower$|^upper$)",
    re.IGNORECASE)
_START_RE = re.compile(r"(start|entry|^tl$|from)", re.IGNORECASE)
_STOP_RE = re.compile(r"(stop|end|exit|^tr$|until)", re.IGNORECASE)


def _unit_column(df: pd.DataFrame) -> str | None:
    """A unit-like text column whose values repeat (several rows per unit)."""
    numeric = {c for c in df.columns if pd.api.types.is_numeric_dtype(df[c])}
    for g in df.columns:
        if g in numeric:
            continue
        col = df[g].dropna().astype(str)
        if col.empty:
            continue
        sizes = col.groupby(col).size()
        if len(sizes) == len(col) or (sizes >= 2).mean() < 0.5:
            continue
        digits = sizes.index.to_series().str.contains(r"\d").mean()
        if _UNIT_NAME_RE.search(str(g)) or digits >= 0.8:
            return str(g)
    return None


def _censor_column(df: pd.DataFrame) -> str | None:
    for c in df.columns:
        if not pd.api.types.is_numeric_dtype(df[c]):
            continue
        vals = set(df[c].dropna().unique().tolist())
        if vals and vals <= {0, 1, -1, 2} and (_CENSOR_NAME_RE.search(str(c)) or vals <= {0, 1}):
            return str(c)
    return None


def detect_tags(df: pd.DataFrame) -> dict:
    """``{"tags": [...], "use_for": [...]}`` for a dataset's columns."""
    tags: set[str] = set()
    unit = _unit_column(df)
    censor = _censor_column(df)
    times = [str(c) for c in df.columns
             if str(c) not in (unit, censor) and pd.api.types.is_numeric_dtype(df[c]) and _TIME_NAME_RE.search(str(c))]
    if not times:  # the first numeric column is the time
        times = [str(c) for c in df.columns if str(c) not in (unit, censor)
                 and pd.api.types.is_numeric_dtype(df[c])][:1]
    # Events of a repairable unit: its time rises row by row and the rows are
    # events, not start/stop periods (repeated_units tells them from readings,
    # and finds start and stop rows whatever their columns are called).
    ru = repeated_units(df) if unit else None
    start_stop = (any(_START_RE.search(t) for t in times) and any(_STOP_RE.search(t) for t in times)) or bool(
        ru and ru["kind"] == "time_varying")
    # A text column unique on every row names the rows (a serial, a tag): not a covariate.
    # A column of words that says failed or still running is the status, not a covariate.
    said = None if censor else _word_status(df, {unit} if unit else set())
    extra = [str(c) for c in df.columns if str(c) not in (unit, censor, *times) and not (said and str(c) == said[0])
             and not (not pd.api.types.is_numeric_dtype(df[c]) and df[c].nunique(dropna=True) == len(df))]
    repeat = bool(ru and ru["kind"] == "recurrent" and not start_stop
                  and (censor or not any(pd.api.types.is_numeric_dtype(df[c]) for c in extra
                                         if (df.groupby(unit)[c].nunique(dropna=True) > 1).any())))
    # The outcome written once per unit (on its last row) with readings on the
    # other rows is life data plus measurements, not changing covariates.
    outcome_once = bool(unit and censor) and bool(
        df[censor].notna().sum() < len(df) and df[censor].notna().groupby(df[unit]).sum().max() <= 1)
    for c in extra:
        varies = bool(unit) and bool((df.groupby(unit)[c].nunique(dropna=True) > 1).any())
        if varies and repeat and not pd.api.types.is_numeric_dtype(df[c]):
            continue  # an event's own detail (its cause or failure mode)
        if not varies:
            tags.add("Covariates")
        elif censor and not (outcome_once and pd.api.types.is_numeric_dtype(df[c])):
            tags.add("Time-varying covariates")
        elif pd.api.types.is_numeric_dtype(df[c]):
            tags.add("Measurements")
        else:
            tags.add("Time-varying covariates")
    # Several rows per unit with a status column are recurrent events, unless
    # the rows are periods of changing covariates (start/stop).
    if repeat:
        tags.add("Repairable")
    elif censor or (times and "Measurements" not in tags):
        # One life per unit (or per start/stop period). Readings alone have no
        # failure times, so they're only non-repairable life data when the file
        # also says which units failed (a status column).
        tags.add("Non-repairable")
    use_for: list[str] = []
    covs = "Covariates" in tags
    if "Measurements" in tags:
        if censor:
            # Life data and readings in one long table: the outcome once per
            # unit, a reading on every row (the split offered on its page).
            use_for += ["Condition and life model", "Degradation model", "Non-repairable model"]
        else:
            use_for += ["Degradation model", "Condition and life model (once life data is added)"]
    elif censor and unit and ("Time-varying covariates" in tags or start_stop):
        use_for.append("Non-repairable model with time-varying covariates")
    elif repeat:
        use_for.append("Repairable model" + (" with covariates" if covs else ""))
    elif censor or times:
        use_for.append("Non-repairable model" + (" with covariates" if covs else ""))
        use_for.append("Condition and life model (once measurements are added)")
    out_tags = [t for t in TAGS if t in tags]
    return {"tags": out_tags, "use_for": use_for, "summary": _summary(df, unit, censor, out_tags, times),
            "time_unit": _time_unit(times)}


def with_measurements(primary: dict, part: DatasetPart, readings: dict | None = None) -> dict:
    """The tags of a dataset with both parts: its table's, plus Measurements
    for the part; "use for" leads with condition and life; the summary adds
    the readings. ``readings`` is ``detect_tags`` of the part (for its time
    unit) when the table names none."""
    tags = [t for t in TAGS if t in set(primary.get("tags") or []) | {"Measurements"}]
    use_for = ["Condition and life model"]
    use_for += [u for u in primary.get("use_for") or [] if not u.startswith("Condition and life")]
    if "Degradation model" not in use_for:
        use_for.append("Degradation model")
    summary = primary.get("summary") or ""
    readings_text = f"{part.n_rows:,} readings"
    summary = f"{summary} · {readings_text}" if summary else readings_text
    return {"tags": tags, "use_for": use_for, "summary": summary,
            "time_unit": primary.get("time_unit") or (readings or {}).get("time_unit")}


# Units a life or usage axis is measured in, as SurPyval names them.
_TIME_UNITS = frozenset({"second", "minute", "hour", "day", "week", "month", "year",
                         "cycle", "kilometer", "mile", "meter"})


def _time_unit(times: list[str]) -> str | None:
    """The unit the time column names, as SurPyval normalises it ("engine_hours"
    → "hour"), or None. A suggestion for fitting; the model stores the unit."""
    try:
        from surpyval.utils.units import normalise_unit
    except ImportError:  # an older SurPyval: no units
        return None
    for col in times:
        for word in re.split(r"[_\s\-()/]+", col):
            try:
                u = normalise_unit(word) if word else None
            except Exception:  # noqa: BLE001 - not a unit
                u = None
            if u in _TIME_UNITS:
                return u
    return None


_GENERIC_ID_RE = re.compile(r"^(id|ids|unit|units|item|items|serial|sn|tag|no|number|name|asset_id|unit_id|item_id)$", re.IGNORECASE)


def _plural(word: str, n: int) -> str:
    if n == 1:
        return word
    if word.endswith("y") and word[-2:-1] not in "aeiou":
        return word[:-1] + "ies"
    if word.endswith(("s", "x", "ch", "sh")):
        return word + "es"
    return word + "s"


def _noun(col: str | None) -> str:
    """What a row's unit is called, from its ID column ("pump" → pumps)."""
    if not col:
        return "unit"
    word = re.sub(r"[_\s-]*(id|no|number|serial|sn|tag)$", "", str(col).strip(), flags=re.IGNORECASE)
    word = re.sub(r"[_-]+", " ", word).strip().lower()
    if not word or _GENERIC_ID_RE.match(word) or len(word) > 20:
        return "unit"
    return word[:-1] if word.endswith("s") and not word.endswith("ss") else word


def _id_column(df: pd.DataFrame, unit: str | None) -> str | None:
    if unit:
        return unit
    for c in df.columns:
        if not pd.api.types.is_numeric_dtype(df[c]) and df[c].nunique(dropna=True) == len(df):
            return str(c)
    return None


# A status column of words, read as the fit wizard reads it
# (frontend/src/datasetGuess.js): what each value means, by the value and,
# for yes / no, by the column's name.
_STATUS_NAME_RE = re.compile(
    r"\b(status|state|fail|failed|failure|failures|censor|censored|censoring|cens|event|events|suspend|suspended"
    r"|suspension|suspensions|running|outcome|survived|alive|dead)\b", re.IGNORECASE)
_NOT_STATUS_RE = re.compile(
    r"\b(mode|modes|cause|causes|type|code|description|desc|reason|date|time|hours?|comment|comments|notes?)\b",
    re.IGNORECASE)
_FAILED_VALUE_RE = re.compile(
    r"(f|fail|failed|failure|failures|fault|faulty|broken|broke|dead|died|event|down|u ?/ ?s|unserviceable|defect"
    r"|defective|tripped|failed in service)", re.IGNORECASE)
_RUNNING_VALUE_RE = re.compile(
    r"(s|r|run|running|still running|suspended|suspension|susp|censored|survived|survivor|alive|ok|okay|working"
    r"|operating|operational|in service|in-service|active|serviceable|good|healthy|removed|retired|planned"
    r"|preventive)", re.IGNORECASE)
_YES_RE = re.compile(r"(y|yes|true|t)", re.IGNORECASE)
_NO_RE = re.compile(r"(n|no|false)", re.IGNORECASE)
_RUNNING_NAME_RE = re.compile(r"\b(censor|censored|censoring|cens|suspend|suspended|suspension|running|survived|alive)\b",
                              re.IGNORECASE)
# A failure-mode column: a blank mode is a unit that hasn't failed.
_MODE_NAME_RE = re.compile(r"\b(mode|modes|cause|causes)\b", re.IGNORECASE)
_COUNT_NAME_RE = re.compile(r"(n|count|counts|qty|quantity|units|number of units)", re.IGNORECASE)
# The two times of inspection data: when the unit last worked and when it was found failed.
_EARLIEST_RE = re.compile(r"(^xl$|last[_ ]?ok|passed|earliest|shortest|lower|^left$|from)", re.IGNORECASE)
_LATEST_RE = re.compile(r"(^xr$|found|failed|latest|longest|upper|^right$|until)", re.IGNORECASE)


def _name_words(name) -> str:
    return re.sub(r"[_\-./()\[\]#:]+", " ", re.sub(r"([a-z])([A-Z])", r"\1 \2", str(name or ""))).strip()


def _word_status(df: pd.DataFrame, skip: set) -> tuple[str, pd.Series] | None:
    """A text column that says failed or still running on every row, and its
    values as censor codes (0 failed, 1 running); None when no column does."""
    for col in df.columns:
        if str(col) in skip or pd.api.types.is_numeric_dtype(df[col]):
            continue
        words = _name_words(col)
        if not _STATUS_NAME_RE.search(words) or _NOT_STATUS_RE.search(words):
            continue
        values = df[col].dropna().astype(str).str.strip()
        if values.empty or len(values) != len(df) or values.nunique() > 12:
            continue
        running_name = bool(_RUNNING_NAME_RE.search(words)) and not _FAILED_NAME_RE.fullmatch(str(col).strip())

        def code(v, running_name=running_name):
            if _FAILED_VALUE_RE.fullmatch(v):
                return 0
            if _RUNNING_VALUE_RE.fullmatch(v):
                return 1
            if _YES_RE.fullmatch(v):
                return 1 if running_name else 0
            if _NO_RE.fullmatch(v):
                return 0 if running_name else 1
            return None

        codes = values.map(code)
        if codes.notna().all():
            return str(col), codes.astype(int)
    return None


def _interval_pair(df: pd.DataFrame, times: list[str]) -> tuple[str, str] | None:
    """The earliest and latest possible failure time of inspection data: two
    time columns named like "last ok" and "found failed" (or xl / xr, lower /
    upper), the first never after the second."""
    for a in times:
        for b in times:
            if a == b or not (_EARLIEST_RE.search(a) and _LATEST_RE.search(b)):
                continue
            both = df[a].notna() & df[b].notna()
            if both.any() and bool((df[a][both] <= df[b][both]).all()) and not (df[a].isna() & df[b].isna()).any():
                return a, b
    return None


def life_counts(df: pd.DataFrame, censor: str | None = None, times: list[str] | None = None) -> dict | None:
    """How many units a table of life data holds and what happened to them:
    ``{units, failed, ranged, running}``. ``failed`` failed at a known time,
    ``ranged`` were found failed (between two inspections, or at the first
    one), ``running`` hadn't failed. Read from the status column (0 / 1 codes
    by the column's name, words by their meaning), the two times of
    inspection data, a failure-mode column whose blanks are units still
    running, and a count column. None when the table doesn't say which units
    failed: better no count than a guess."""
    from backend import fitting  # local: only the summary needs it

    n_rows = len(df)
    codes = None
    skip = {censor} if censor else set()
    if censor:
        raw = pd.to_numeric(df[censor], errors="coerce")
        if raw.isna().any():
            return None
        # A flag named "failed" / "status" is 1 = failed; left (-1) and interval (2) stay.
        flip = bool(_FAILED_NAME_RE.fullmatch(censor.strip()))
        codes = raw.where(~raw.isin((0, 1)), 1 - raw) if flip else raw
    else:
        words = _word_status(df, skip)
        if words:
            skip.add(words[0])
            codes = words[1]
    pair = _interval_pair(df, [t for t in (times or []) if t not in skip])
    if pair:
        try:
            read = fitting.read_interval_rows(
                df[pair[0]].to_numpy(dtype=float), df[pair[1]].to_numpy(dtype=float),
                None if codes is None else codes.to_numpy(dtype=float))
        except FitError:
            return None
        lo, hi = read["xl"], read["xr"]
        codes = pd.Series(read["c"] if "c" in read else [0 if a == b else 2 for a, b in zip(lo, hi)], index=df.index)
    if codes is None:
        modes = [c for c in df.columns if not pd.api.types.is_numeric_dtype(df[c])
                 and _MODE_NAME_RE.search(_name_words(c)) and 0 < df[c].isna().sum() < n_rows]
        if not modes:
            return None
        codes = df[modes[0]].isna().astype(int)
    weights = pd.Series(1.0, index=df.index)
    for col in df.columns:
        if str(col) in skip or not _COUNT_NAME_RE.fullmatch(str(col).strip()):
            continue
        values = pd.to_numeric(df[col], errors="coerce")
        if pd.api.types.is_numeric_dtype(df[col]) and values.notna().all() and (values == values.round()).all() \
                and (values >= 0).all():
            weights = values.astype(float)
            break

    def count(mask) -> int:
        return int(round(float(weights[mask].sum())))

    return {"units": count(codes.notna()), "failed": count(codes == 0), "ranged": count(codes.isin((-1, 2))),
            "running": count(codes == 1)}


def _summary(df: pd.DataFrame, unit: str | None, censor: str | None, tags: list[str],
             times: list[str] | None = None) -> str:
    """The list's count: units of the dataset's own noun, and what happened to them,
    e.g. "40 pumps · 19 failed", "10 trucks · 71 failures", "30 bearings · 193 readings".
    Life data that doesn't say which units failed gets the units alone, unless
    it is plain times with nothing else that could say ("all failed")."""
    idc = _id_column(df, unit)
    noun = _noun(idc)
    n_units = int(df[unit].nunique(dropna=True)) if unit else len(df)
    units = f"{n_units:,} {_plural(noun, n_units)}"
    if "Measurements" in tags:
        return f"{units} · {len(df):,} readings"
    if "Repairable" in tags:
        failed_flag = 1 if censor and _FAILED_NAME_RE.fullmatch(censor.strip()) else 0
        n = int((df[censor] == failed_flag).sum()) if censor else len(df)
        return f"{units} · {n:,} {_plural('failure', n)}"
    counts = None if unit else life_counts(df, censor, times)
    if counts is None:
        if censor:  # several rows per unit with a flag (start and stop rows)
            failed_flag = 1 if _FAILED_NAME_RE.fullmatch(censor.strip()) else 0
            return f"{units} · {int((df[censor] == failed_flag).sum()):,} failed"
        # No status, and nothing that looks like one left unread (a column
        # named like a status, a second time): every row is a failure.
        unsure = len(times or []) > 1 or any(
            _STATUS_NAME_RE.search(_name_words(c)) and not _NOT_STATUS_RE.search(_name_words(c))
            for c in df.columns if str(c) not in (times or []))
        return f"{units} · all failed" if "Non-repairable" in tags and not unsure else units
    units = f"{counts['units']:,} {_plural(noun, counts['units'])}"
    parts = [units]
    if counts["failed"] or not counts["ranged"]:
        parts.append(f"{counts['failed']:,} failed")
    if counts["ranged"]:
        parts.append(f"{counts['ranged']:,} failed between inspections")
    return " · ".join(parts)


_TAG_CACHE: dict[str, dict] = {}


def dataset_tags(dataset: Dataset) -> dict:
    """``detect_tags`` for a saved dataset (with its measurements part folded
    in), cached by its content (datasets are content-addressed, so the
    checksums name the tables)."""
    part = dataset.measurements
    key = (dataset.checksum or dataset.id) + (f"|{part.checksum}" if part is not None else "")
    if key not in _TAG_CACHE:
        try:
            out = detect_tags(load_dataframe(dataset))
            if part is not None:
                readings = None
                if not out.get("time_unit"):
                    try:
                        readings = detect_tags(read_dataframe(bytes(part.data)))
                    except Exception:  # noqa: BLE001 - its time unit is only a suggestion
                        readings = None
                out = with_measurements(out, part, readings)
            _TAG_CACHE[key] = out
        except Exception:  # noqa: BLE001 - an unreadable file just has no tags
            _TAG_CACHE[key] = {"tags": [], "use_for": [], "summary": "", "time_unit": None}
        if len(_TAG_CACHE) > 5000:
            _TAG_CACHE.pop(next(iter(_TAG_CACHE)))
    return _TAG_CACHE[key]


def profile(dataset: Dataset) -> dict:
    """What the dataset page needs beyond the preview: each column's count of
    distinct values (to pick a sensible "split by"), whether the rows are
    unit histories (``repeated_units``), and — for a dataset whose one table
    holds life data and readings together — how it would ``split``."""
    df = load_dataframe(dataset)
    return {
        "distinct": {str(c): int(df[c].nunique(dropna=True)) for c in df.columns},
        "repeated_units": repeated_units(df),
        "split": None if dataset.measurements is not None else split_plan(df),
    }


def dependents_message(dependents: list[dict]) -> str:
    """"Dataset is used by 2 model(s): “Seal ALT” (ALT model), …" — the
    refusal both delete paths give."""
    shown = ", ".join(f"“{d['name']}”" + ("" if d["kind"] == "model" else f" ({d['kind']})")
                      for d in dependents[:3])
    more = "" if len(dependents) <= 3 else f" and {len(dependents) - 3} more"
    return f"Dataset is used by {len(dependents)} model(s): {shown}{more}."


def update_details(db, dataset_id: str, owner_id: str, name: str | None = None,
                   notes: str | None = None) -> Dataset | None:
    """Rename an owned dataset and/or set its notes (``notes=""`` clears them).
    Never touches the data. Returns None if it doesn't exist or isn't owned
    (shared samples are read-only)."""
    fields: dict = {}
    if name is not None:
        fields["name"] = name
    if notes is not None:
        fields["notes"] = notes or None
    if fields:
        res = db.datasets.update_one({"_id": dataset_id, "owner_id": owner_id}, {"$set": fields})
        if res.matched_count == 0:
            return None
    return from_doc(Dataset, db.datasets.find_one({"_id": dataset_id, "owner_id": owner_id}))


def delete_dataset(db, dataset_id: str, owner_id: str) -> bool:
    """Remove an owned dataset. Returns False if it does not exist / not owned.

    Callers should refuse deletion while models still reference the dataset.
    """
    result = db.datasets.delete_one({"_id": dataset_id, "owner_id": owner_id})
    return result.deleted_count > 0
