"""Ingestion API operations: automate the data Reliafy currently takes by hand.

Three write paths, all owner-scoped to the personal workspace and all
validate-then-apply (a bad batch changes nothing):

* fleet usage      — update failure-forecast items' current use (meter reads)
* measurements     — append degradation readings to a tracked fleet's items
* dataset lives    — append rows to a dataset, then refit its models in place

Each returns what changed plus the recomputed headline, so a cron job's log
shows the effect of every push.
"""

from __future__ import annotations

import io
from datetime import datetime, timezone

import pandas as pd

from backend import fitting
from backend.config import SAMPLE_OWNER
from backend.schema import Fleet
from backend.db import from_doc
from backend.services import datasets as datasets_service
from backend.services import degradation as degradation_service
from backend.services import fleet as fleet_service
from backend.services import models as models_service

MAX_ROWS = 5000
REFIT_CAP = 20


class IngestError(ValueError):
    def __init__(self, message: str, status: int = 422):
        super().__init__(message)
        self.status = status


def _now():
    return datetime.now(timezone.utc)


def _match(items: list[dict], entry: dict, where: str):
    """Match an ingest row to an item by id, then case-insensitive name."""
    key = str(entry.get("id") or "").strip()
    if key:
        for it in items:
            if it["id"] == key:
                return it
    name = str(entry.get("name") or entry.get("item") or "").strip()
    if name:
        low = name.lower()
        hits = [it for it in items if str(it.get("name", "")).strip().lower() == low]
        if len(hits) > 1:
            raise IngestError(f"{where}: item name '{name}' is ambiguous — use ids.")
        if hits:
            return hits[0]
    raise IngestError(
        f"{where}: no item matches "
        f"{'id ' + key if key else 'name ' + repr(name) if name else 'the row (no id or name)'}."
    )


def _float(value, field: str, where: str) -> float:
    try:
        f = float(value)
    except (TypeError, ValueError):
        raise IngestError(f"{where}: '{field}' must be a number (got {value!r}).")
    if not (f == f) or f in (float("inf"), float("-inf")):
        raise IngestError(f"{where}: '{field}' must be finite.")
    return f


# ---- fleet usage -------------------------------------------------------------

def update_fleet_usage(db, fleet_id: str, uid: str, entries: list[dict]) -> dict:
    """Set ``current_use`` (and optionally ``rate``) on forecast-fleet items."""
    doc = db.fleets.find_one({"_id": fleet_id, "owner_id": uid})
    if doc is None:
        raise IngestError("Fleet not found (or not yours — tokens are personal).", 404)
    if not entries:
        raise IngestError("No rows to apply.")
    if len(entries) > MAX_ROWS:
        raise IngestError(f"Too many rows ({len(entries)}); the limit is {MAX_ROWS}.")

    items = [dict(it) for it in (doc.get("items") or [])]
    updates: dict[str, dict] = {}
    for i, entry in enumerate(entries):
        where = f"row {i + 1}"
        item = _match(items, entry, where)
        update = {"current_use": _float(entry.get("current_use"), "current_use", where)}
        if entry.get("rate") not in (None, ""):
            update["rate"] = _float(entry.get("rate"), "rate", where)
        updates[item["id"]] = update

    for it in items:
        if it["id"] in updates:
            it.update(updates[it["id"]])

    now = _now()
    db.fleets.update_one(
        {"_id": fleet_id, "owner_id": uid},
        {"$set": {"items": items, "updated_at": now}},
    )
    fleet = from_doc(Fleet, db.fleets.find_one({"_id": fleet_id}))
    forecast = fleet_service.compute(db, fleet, [uid, SAMPLE_OWNER])
    return {
        "fleet": fleet.name,
        "updated_items": len(updates),
        "forecast": {
            k: forecast.get(k)
            for k in ("status", "expected", "interval", "periods", "period_label", "reason")
            if k in forecast
        },
    }


# ---- degradation measurements --------------------------------------------------

def append_measurements(db, tracked_fleet_id: str, uid: str, rows: list[dict]) -> dict:
    """Append (time, value) readings to a tracked fleet's items.

    Idempotent: a reading identical to one the item already has is skipped, so
    re-sending the same export is safe. Everything is validated before any
    write.
    """
    fleet = degradation_service.get_tracked_fleet(db, tracked_fleet_id, owner_id=uid)
    if fleet is None or fleet.owner_id != uid:
        raise IngestError("Tracked fleet not found (or not yours).", 404)
    if not rows:
        raise IngestError("No rows to apply.")
    if len(rows) > MAX_ROWS:
        raise IngestError(f"Too many rows ({len(rows)}); the limit is {MAX_ROWS}.")

    tracked = degradation_service.list_fleet_items(db, fleet, uid)
    items = [{"id": it.id, "name": it.name, "obj": it} for it in tracked if it.owner_id == uid]

    # Validate every row first, grouping per item in time order.
    plan: dict[str, list[tuple[float, float]]] = {}
    for i, row in enumerate(rows):
        where = f"row {i + 1}"
        item = _match(items, row, where)
        t = _float(row.get("time") if row.get("time") is not None else row.get("t"), "time", where)
        y = _float(row.get("value") if row.get("value") is not None else row.get("y"), "value", where)
        plan.setdefault(item["id"], []).append((t, y))

    results = []
    for item_id, readings in plan.items():
        obj = next(x["obj"] for x in items if x["id"] == item_id)
        existing = [(m["t"], m["y"]) for m in (obj.measurements or [])]
        last_t = existing[-1][0] if existing else float("-inf")
        added = 0
        for t, y in sorted(readings):
            if (t, y) in existing:
                continue  # idempotent re-send
            if t <= last_t:
                raise IngestError(
                    f"{obj.name}: reading at t={t:g} is not after the item's "
                    f"latest ({last_t:g}) and isn't an exact duplicate."
                )
            obj = degradation_service.append_measurement(
                db, obj.model_id, item_id, t, y, uid
            )
            existing.append((t, y))
            last_t = t
            added += 1
        results.append({
            "item": obj.name,
            "added": added,
            "health": degradation_service.health_of(obj.prediction),
            "prediction": {
                k: (obj.prediction or {}).get(k)
                for k in ("failure_time", "prob_failed", "method")
            },
        })
    return {"fleet": fleet.name, "items": results}


# ---- dataset lives -------------------------------------------------------------

def append_dataset_rows(db, dataset_id: str, uid: str, rows_df: pd.DataFrame, refit: bool = True) -> dict:
    """Append rows to a dataset and (by default) refit its models in place."""
    dataset = datasets_service.get_dataset(db, dataset_id, owner_id=uid)
    if dataset is None or dataset.owner_id != uid:
        raise IngestError("Dataset not found (or not yours).", 404)
    if rows_df.empty:
        raise IngestError("No rows to append.")
    if len(rows_df) > MAX_ROWS:
        raise IngestError(f"Too many rows ({len(rows_df)}); the limit is {MAX_ROWS}.")

    existing = datasets_service.load_dataframe(dataset)
    unknown = [c for c in rows_df.columns if c not in existing.columns]
    if unknown:
        raise IngestError(
            f"Unknown column(s): {', '.join(map(str, unknown))}. "
            f"The dataset's columns are: {', '.join(map(str, existing.columns))}."
        )

    combined = pd.concat([existing, rows_df], ignore_index=True)
    csv_bytes = combined.to_csv(index=False).encode()
    from backend import config, storage

    if len(csv_bytes) > config.MAX_UPLOAD_BYTES:
        raise IngestError("The dataset would exceed the size limit after this append.")

    digest = storage.checksum(csv_bytes)
    if digest == dataset.checksum:
        return {"dataset": dataset.name, "appended": 0, "n_rows": int(existing.shape[0]), "refit": []}

    db.datasets.update_one(
        {"_id": dataset_id, "owner_id": uid},
        {"$set": {
            "data": csv_bytes,
            "checksum": digest,
            "n_rows": int(combined.shape[0]),
        }},
    )

    refit_report = []
    if refit:
        models = [
            m for m in datasets_service.models_for_dataset(db, dataset_id, uid)
            if m.owner_id == uid and (m.spec or {}).get("mapping")
        ][:REFIT_CAP]
        for m in models:
            spec = m.spec or {}
            try:
                updated = models_service.update_fit(
                    db, m.id, uid,
                    spec.get("distribution_id", m.distribution_id),
                    spec.get("mapping", {}),
                    spec.get("covariates", []),
                    spec.get("formula"),
                    spec.get("unit"),
                    spec.get("options"),
                )
                refit_report.append({
                    "model": updated.name,
                    "id": updated.id,
                    "status": "refit",
                    "n": (updated.results or {}).get("n"),
                })
            except (fitting.FitError, models_service.ModelNotFound) as exc:
                refit_report.append({"model": m.name, "id": m.id, "status": "failed", "detail": str(exc)})

    return {
        "dataset": dataset.name,
        "appended": int(rows_df.shape[0]),
        "n_rows": int(combined.shape[0]),
        "refit": refit_report,
    }


# ---- request-body parsing -------------------------------------------------------

def rows_from_request(content_type: str, body: bytes, json_keys: tuple[str, ...]) -> list[dict]:
    """Rows from either a JSON body ({<key>: [...]}) or a raw text/csv body."""
    import json as _json

    if "csv" in (content_type or ""):
        try:
            df = pd.read_csv(io.BytesIO(body))
        except Exception as exc:
            raise IngestError(f"Couldn't parse the CSV body: {exc}")
        return df.to_dict(orient="records")
    try:
        payload = _json.loads(body or b"{}")
    except _json.JSONDecodeError:
        raise IngestError("Body must be JSON (or text/csv with a CSV body).")
    if isinstance(payload, list):
        return payload
    for key in json_keys:
        if isinstance(payload.get(key), list):
            return payload[key]
    raise IngestError(
        f"Provide rows as a JSON array or under one of: {', '.join(json_keys)}."
    )


def dataframe_from_request(content_type: str, body: bytes) -> pd.DataFrame:
    if "csv" in (content_type or ""):
        try:
            return pd.read_csv(io.BytesIO(body))
        except Exception as exc:
            raise IngestError(f"Couldn't parse the CSV body: {exc}")
    rows = rows_from_request(content_type, body, ("rows", "lives", "data"))
    if not rows:
        raise IngestError("No rows to append.")
    return pd.DataFrame(rows)
