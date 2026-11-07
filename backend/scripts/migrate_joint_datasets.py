"""Move condition and life (joint) models onto one dataset each.

A joint model saved before datasets held their measurements names two
datasets in its spec (``lifetimes_dataset_id`` and ``readings_dataset_id``:
two different ones, or the same one twice for a table holding both). Such
models still open and refit as they are. This script brings them onto the
one-dataset spec (``dataset_id``) so they look and behave like new ones:

- the same dataset twice: ``spec.dataset_id`` is set to it and the two keys
  are dropped (the dataset is left as it is; its one table is read as both
  parts, and its page offers to split it);
- two different datasets: the readings dataset's table is copied into the
  lifetimes dataset as its measurements part (when it has none, or already
  holds that exact table), the spec is pointed at the lifetimes dataset, and
  the readings dataset is left alone, reported as no longer used by this
  model (delete it by hand once nothing else uses it);
- a lifetimes dataset that already holds different measurements, or a
  dataset that is missing: reported and skipped.

A refit of a moved model reads exactly the rows it read before (the life data
and the readings are the same bytes), so its results don't change.

    # Dry run (default): report what would change.
    python -m backend.scripts.migrate_joint_datasets

    # Apply.
    python -m backend.scripts.migrate_joint_datasets --apply

It uses the MONGODB_URI environment of wherever it runs.
"""

from __future__ import annotations

import argparse
import sys


def plan(db) -> list[dict]:
    """What each joint model with a two-dataset spec needs: a row per model
    with ``action`` (``set_id``, ``copy_readings``, ``skip``) and why."""
    from backend import storage

    rows = []
    for m in db.models.find({"kind": "joint", "spec.dataset_id": {"$in": [None, ""]}}).sort("created_at", 1):
        spec = m.get("spec") or {}
        life_id, read_id = spec.get("lifetimes_dataset_id"), spec.get("readings_dataset_id")
        row = {"model_id": m["_id"], "name": m.get("name") or "", "owner_id": m.get("owner_id"),
               "lifetimes_dataset_id": life_id, "readings_dataset_id": read_id}
        if not life_id or not read_id:
            rows.append({**row, "action": "skip", "why": "the spec names no datasets"})
            continue
        if life_id == read_id:
            rows.append({**row, "action": "set_id", "why": "the same dataset twice: one table holding both"})
            continue
        life = db.datasets.find_one({"_id": life_id})
        reads = db.datasets.find_one({"_id": read_id})
        if life is None or reads is None:
            rows.append({**row, "action": "skip",
                         "why": "the " + ("lifetimes" if life is None else "readings") + " dataset is missing"})
            continue
        have = life.get("measurements") or None
        reads_checksum = reads.get("checksum") or storage.checksum(bytes(reads.get("data") or b""))
        if have and have.get("checksum") != reads_checksum:
            rows.append({**row, "action": "skip",
                         "why": f"dataset {life_id} already holds different measurements"})
            continue
        rows.append({**row, "action": "copy_readings",
                     "why": ("its measurements already are the readings dataset's table" if have
                             else f"copy the readings dataset's table ({reads.get('n_rows')} rows) in"),
                     "readings_name": reads.get("name") or "", "readings_rows": reads.get("n_rows"),
                     "already_copied": bool(have)})
    return rows


def apply(db, rows: list[dict]) -> int:
    """Carry the plan out. Returns the number of models moved."""
    from backend.services import datasets as datasets_service

    moved = 0
    for row in rows:
        if row["action"] == "skip":
            continue
        if row["action"] == "copy_readings" and not row.get("already_copied"):
            life = datasets_service.get_dataset(db, row["lifetimes_dataset_id"])
            reads = datasets_service.get_dataset(db, row["readings_dataset_id"])
            datasets_service.set_measurements(db, life, bytes(reads.data), life.owner_id)
        db.models.update_one({"_id": row["model_id"]}, {
            "$set": {"spec.dataset_id": row["lifetimes_dataset_id"], "dataset_id": row["lifetimes_dataset_id"]},
            "$unset": {"spec.lifetimes_dataset_id": "", "spec.readings_dataset_id": ""},
        })
        moved += 1
    return moved


def report(rows: list[dict], applied: bool) -> str:
    lines = [("APPLIED" if applied else "DRY RUN: nothing was written") + f". {len(rows)} joint model(s) on the "
             "two-dataset spec."]
    for r in rows:
        lines.append(f"\nModel {r['model_id']} “{r['name']}” (owner {r['owner_id']})")
        lines.append(f"  {r['action']}: {r['why']}")
        if r["action"] == "copy_readings":
            lines.append(f"  lifetimes dataset {r['lifetimes_dataset_id']} gets the readings; readings dataset "
                         f"{r['readings_dataset_id']} “{r.get('readings_name')}” is then unused by this model")
    if not rows:
        lines.append("Nothing to do.")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--apply", action="store_true", help="write the changes (default: dry run)")
    args = parser.parse_args(argv)
    from backend.db import get_db

    db = get_db()
    rows = plan(db)
    moved = apply(db, rows) if args.apply else 0
    print(report(rows, args.apply))
    if args.apply:
        print(f"\nMoved {moved} model(s).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
