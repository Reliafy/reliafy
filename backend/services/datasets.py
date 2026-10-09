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
from backend.fitting import read_csv_capped, read_dataframe
from backend.schema import Dataset, Model



def _list_query(owner_id, shared=frozenset()):
    """Owner-scoped filter, optionally unioned with directly-shared ids."""
    query = {"owner_id": {"$in": access.owner_in(owner_id)}}
    if shared:
        return {"$or": [query, {"_id": {"$in": sorted(shared)}}]}
    return query

def normalize_pasted(content: str) -> bytes:
    """Parse pasted tabular text (CSV or TSV) into canonical CSV bytes.

    The delimiter is chosen from a fixed set (tab / comma / semicolon / pipe)
    by counting occurrences in the header row — so spreadsheet paste (tabs)
    and CSV both work — rather than letting pandas sniff any character (which
    can wrongly split on letters in single-column data). Everything downstream
    then sees a plain CSV.
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
                             engine="python", skipinitialspace=True)
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
    return df.to_csv(index=False).encode()


def _apply_generic_header(file_bytes: bytes) -> bytes:
    """No-header upload: parse the file with ``header=None``, name the columns
    ``col 1``, ``col 2``, … and re-serialise, so the first row (which would
    otherwise be consumed as column names) is kept as data."""
    import io

    try:
        df = read_csv_capped(io.BytesIO(file_bytes), header=None,
                             width_text=bytes(file_bytes[:1024 * 1024]).decode("utf-8", "replace"))
    except FitError:
        raise
    except Exception as exc:  # pragma: no cover - pandas raises many types
        raise FitError(f"Could not parse the file as CSV: {exc}") from exc
    if df.empty or df.shape[1] == 0:
        raise FitError("The uploaded CSV is empty.")
    df.columns = [f"col {i + 1}" for i in range(df.shape[1])]
    return df.to_csv(index=False).encode()


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
    from backend import config

    def _check_size(data: bytes) -> None:
        if len(data) > config.MAX_UPLOAD_BYTES:
            mb = config.MAX_UPLOAD_BYTES / (1024 * 1024)
            raise FitError(
                f"That file is too large ({len(data) / (1024 * 1024):.1f} MB). "
                f"The limit is {mb:.0f} MB — try trimming unused columns or rows."
            )

    # Checked before parsing, and again after the header rewrite (which can
    # lengthen the file).
    _check_size(file_bytes)
    if no_header:
        file_bytes = _apply_generic_header(file_bytes)
        _check_size(file_bytes)

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
    Shared sample datasets are visible to every owner.
    """
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


def preview_rows(dataset: Dataset, rows: int = 8) -> dict:
    """Column names + a small sample of rows for the dataset detail view."""
    return _preview(bytes(dataset.data), rows)


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
        for d in db[collection].find(
            {"dataset_id": dataset_id, "owner_id": {"$in": access.owner_in(owner_id)}}
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
            {"owner_id": {"$in": access.owner_in(owner_id)}}, {"dataset_id": 1}
        ):
            ds_id = d.get("dataset_id")
            if ds_id and d["_id"] not in hidden:
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
