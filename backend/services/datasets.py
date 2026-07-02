"""Dataset persistence: store uploaded CSVs (in MongoDB) and read them back as
DataFrames."""

from __future__ import annotations

import uuid

import pandas as pd

from backend import storage
from backend.config import SAMPLE_OWNER
from backend.db import from_doc, to_doc
from backend.fitting import preview as _preview
from backend.fitting import read_dataframe
from backend.schema import Dataset, Model


def create_dataset(db, name: str, file_bytes: bytes, owner_id: str) -> Dataset:
    """Persist a CSV (content-addressed) and return the Dataset.

    Datasets are de-duplicated by checksum *per owner* so saving several models
    from the same upload reuses one dataset, while different users keep their
    own isolated copies.
    """
    digest = storage.checksum(file_bytes)
    existing = db.datasets.find_one({"checksum": digest, "owner_id": owner_id})
    if existing is not None:
        return from_doc(Dataset, existing)

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
    return dataset


def get_dataset(db, dataset_id: str, owner_id: str | None = None) -> Dataset | None:
    """Fetch a dataset by id, optionally scoped to its owner.

    ``owner_id`` is optional so internal callers (the re-fit path) can fetch by
    id; external/API callers always pass it so a non-owner gets ``None`` (404).
    Shared sample datasets are visible to every owner.
    """
    query = {"_id": dataset_id}
    if owner_id is not None:
        query["owner_id"] = {"$in": [owner_id, SAMPLE_OWNER]}
    return from_doc(Dataset, db.datasets.find_one(query))


def list_datasets(db, owner_id: str, hidden=frozenset()) -> list[Dataset]:
    """The owner's datasets plus the shared samples, newest first.

    ``hidden`` is the set of sample ids this user has dismissed; they're left
    out so a "deleted" sample stays gone for them.
    """
    return [
        from_doc(Dataset, d)
        for d in db.datasets.find(
            {"owner_id": {"$in": [owner_id, SAMPLE_OWNER]}}
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
            {"dataset_id": dataset_id, "owner_id": {"$in": [owner_id, SAMPLE_OWNER]}}
        ).sort("created_at", -1)
        if m["_id"] not in hidden
    ]


def delete_dataset(db, dataset_id: str, owner_id: str) -> bool:
    """Remove an owned dataset. Returns False if it does not exist / not owned.

    Callers should refuse deletion while models still reference the dataset.
    """
    result = db.datasets.delete_one({"_id": dataset_id, "owner_id": owner_id})
    return result.deleted_count > 0
