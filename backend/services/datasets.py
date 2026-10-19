"""Dataset persistence: store uploaded CSVs (in MongoDB) and read them back as
DataFrames."""

from __future__ import annotations

import re
import uuid

import pandas as pd

from backend import storage
from backend.services import access
from backend.db import from_doc, to_doc
from backend.fitting import FitError
from backend.fitting import preview as _preview
from backend.fitting import header_guess, read_csv_capped, read_dataframe, with_generic_header
from backend.schema import Dataset, Model



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
        raise FitError(f"Couldn't read the pasted data: {exc}") from exc
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
    return read_dataframe(bytes(dataset.data))


def preview_rows(dataset: Dataset, rows: int = 8, distinct: bool = False) -> dict:
    """Column names + a small sample of rows for the dataset detail view
    (``distinct``: with each column's distinct-value count, see preview)."""
    return _preview(bytes(dataset.data), rows, distinct=distinct)


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
        # A condition-based (joint) model is fitted to a second dataset too,
        # its readings (``spec.readings_dataset_id``).
        uses = ({"$or": [{"dataset_id": dataset_id}, {"spec.readings_dataset_id": dataset_id}]}
                if collection == "models" else {"dataset_id": dataset_id})
        for d in db[collection].find(
            {**uses, "owner_id": {"$in": access.owner_in(owner_id)}}
        ).sort("created_at", -1):
            if d["_id"] in hidden:
                continue
            out.append({"kind": kind, "collection": collection, "id": d["_id"], "name": d.get("name") or "",
                        "owner_id": d.get("owner_id")})
    return out


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

    ``{"column": <unit column>, "kind": "recurrent" | "degradation"}`` when a
    unit-like text column (an id-ish name, or values that carry digits, e.g.
    "CMP-1") repeats, and some numeric column rises within every unit in file
    order — the events of a repairable system ("recurrent"), or measurements
    on a shared time grid ("degradation"). Comparing groups or fitting a life
    distribution to such rows would treat each event as a separate unit.
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


# What a dataset holds, as tags on the Data list (planning #261). Detected
# from the columns; the "use for" line says which analyses take it.
TAGS = ("Non-repairable", "Repairable", "Covariates", "Time-varying covariates", "Measurements")
_CENSOR_NAME_RE = re.compile(r"(^c$|censor|status|failed|event|^c_)", re.IGNORECASE)
_TIME_NAME_RE = re.compile(
    r"(^x$|^t$|^xl$|^xr$|^tl$|^tr$|hour|time|age|day|week|month|year|cycle|km|mile|start|stop|end|date|observ)",
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
    start_stop = any(_START_RE.search(t) for t in times) and any(_STOP_RE.search(t) for t in times)
    # A text column unique on every row names the rows (a serial, a tag): not a covariate.
    extra = [str(c) for c in df.columns if str(c) not in (unit, censor, *times)
             and not (not pd.api.types.is_numeric_dtype(df[c]) and df[c].nunique(dropna=True) == len(df))]
    # Events of a repairable unit: its time rises row by row and the rows are
    # events, not start/stop periods (repeated_units tells them from readings).
    ru = repeated_units(df) if unit else None
    repeat = bool(ru and ru["kind"] == "recurrent" and not start_stop
                  and (censor or not any(pd.api.types.is_numeric_dtype(df[c]) for c in extra
                                         if (df.groupby(unit)[c].nunique(dropna=True) > 1).any())))
    for c in extra:
        varies = bool(unit) and bool((df.groupby(unit)[c].nunique(dropna=True) > 1).any())
        if varies and repeat and not pd.api.types.is_numeric_dtype(df[c]):
            continue  # an event's own detail (its cause or failure mode)
        if not varies:
            tags.add("Covariates")
        elif censor:
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
        use_for += ["Degradation", "Condition monitoring (the readings)"]
    elif censor and unit and ("Time-varying covariates" in tags or start_stop):
        use_for.append("Life model with time-varying covariates")
    elif repeat:
        use_for.append("Repairable model" + (" with covariates" if covs else ""))
    elif censor or times:
        use_for.append("Life model" + (" with covariates" if covs else ""))
        use_for.append("Condition monitoring (the lifetimes)")
    out_tags = [t for t in TAGS if t in tags]
    idc = _id_column(df, unit)
    ids = frozenset(df[idc].dropna().astype(str).head(20_000)) if idc else frozenset()
    return {"tags": out_tags, "use_for": use_for, "summary": _summary(df, unit, censor, out_tags),
            "time_unit": _time_unit(times), "_ids": ids}


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


def _summary(df: pd.DataFrame, unit: str | None, censor: str | None, tags: list[str]) -> str:
    """The list's count: units of the dataset's own noun, and what happened to them,
    e.g. "40 pumps · 19 failed", "10 trucks · 71 failures", "30 bearings · 193 readings"."""
    idc = _id_column(df, unit)
    noun = _noun(idc)
    n_units = int(df[unit].nunique(dropna=True)) if unit else len(df)
    units = f"{n_units:,} {_plural(noun, n_units)}"
    failed = int((df[censor] == 0).sum()) if censor else None
    if "Measurements" in tags:
        return f"{units} · {len(df):,} readings"
    if "Repairable" in tags:
        n = failed if failed is not None else len(df)
        return f"{units} · {n:,} {_plural('failure', n)}"
    if failed is None:
        return f"{units} · all failed" if "Non-repairable" in tags else units
    return f"{units} · {failed:,} failed"


_TAG_CACHE: dict[str, dict] = {}


def dataset_tags(dataset: Dataset) -> dict:
    """``detect_tags`` for a saved dataset, cached by its content (datasets
    are content-addressed, so the checksum names the file)."""
    key = dataset.checksum or dataset.id
    if key not in _TAG_CACHE:
        try:
            _TAG_CACHE[key] = detect_tags(load_dataframe(dataset))
        except Exception:  # noqa: BLE001 - an unreadable file just has no tags
            _TAG_CACHE[key] = {"tags": [], "use_for": [], "summary": "", "time_unit": None, "_ids": frozenset()}
        if len(_TAG_CACHE) > 5000:
            _TAG_CACHE.pop(next(iter(_TAG_CACHE)))
    return {k: v for k, v in _TAG_CACHE[key].items() if not k.startswith("_")}


def _unit_ids(dataset: Dataset) -> frozenset:
    dataset_tags(dataset)
    return _TAG_CACHE[dataset.checksum or dataset.id].get("_ids", frozenset())


def condition_pairs(datasets: list[Dataset]) -> dict[str, list[dict]]:
    """Which lifetimes and readings datasets go together for condition
    monitoring: a Non-repairable set and a Measurements set whose unit ids mostly
    match (at least half of the smaller set's). ``{dataset id: [{id, name}]}``,
    both ways round; a dataset with no partner isn't in it."""
    lives, reads = [], []
    for d in datasets:
        tags = dataset_tags(d)["tags"]
        if "Measurements" in tags:
            reads.append(d)
        elif "Non-repairable" in tags:
            lives.append(d)
    out: dict[str, list[dict]] = {}
    for life in lives:
        a = _unit_ids(life)
        if not a:
            continue
        for read in reads:
            b = _unit_ids(read)
            if b and len(a & b) >= 0.5 * min(len(a), len(b)):
                out.setdefault(life.id, []).append({"id": read.id, "name": read.name})
                out.setdefault(read.id, []).append({"id": life.id, "name": life.name})
    return out


def profile(dataset: Dataset) -> dict:
    """What the dataset page needs beyond the preview: each column's count of
    distinct values (to pick a sensible "split by") and whether the rows are
    unit histories (``repeated_units``)."""
    df = load_dataframe(dataset)
    return {
        "distinct": {str(c): int(df[c].nunique(dropna=True)) for c in df.columns},
        "repeated_units": repeated_units(df),
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
