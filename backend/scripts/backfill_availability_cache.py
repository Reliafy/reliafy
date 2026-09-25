"""Precompute saved availability results for existing repairable RBDs.

Availability simulation (repairable diagrams) became a paid feature: free
users and public links only see a *saved* result. This backfills that result
for diagrams whose owner is entitled (admin, Pro, purchased credits, or
billing off) and which have no saved result matching their current graph, so
their public links and read-only viewers keep showing numbers.

    # Dry run (default): list what would be computed.
    python -m backend.scripts.backfill_availability_cache

    # Compute and save.
    python -m backend.scripts.backfill_availability_cache --apply [--limit N]

Sample diagrams are skipped (startup seeding handles them). It uses the
MONGODB_URI environment of wherever it runs.
"""

from __future__ import annotations

import argparse
import pathlib
import sys
import time

COMPUTED_BY = "backfill"


def _owner_user(db, owner_id: str) -> dict | None:
    """A minimal ``{uid, email}`` user for the entitlement check. A team
    diagram is judged by the team owner's entitlement."""
    from backend.services import access

    uid = owner_id
    if access.is_team_owner(owner_id):
        team = db.teams.find_one({"_id": owner_id[len(access.TEAM_PREFIX):]}) or {}
        uid = team.get("owner_uid")
        if not uid:
            return None
    doc = db.users.find_one({"_id": uid}) or {}
    return {"uid": uid, "email": doc.get("email")}


def candidates(db) -> list[dict]:
    """Repairable, non-sample RBDs with an entitled owner and no matching
    saved result. Each row: ``{id, name, owner_id, key, n_nodes}``."""
    from backend.config import SAMPLE_OWNER
    from backend.services import billing
    from backend.services import rbds as rbds_service

    out = []
    entitled: dict[str, bool] = {}
    for doc in db.rbds.find({"graph.repairable": True}).sort("created_at", 1):
        owner_id = doc.get("owner_id")
        if not owner_id or owner_id == SAMPLE_OWNER:
            continue
        key = rbds_service.availability_cache_key(doc.get("graph") or {})
        if rbds_service.cached_availability(doc, key) is not None:
            continue
        if owner_id not in entitled:
            user = _owner_user(db, owner_id)
            entitled[owner_id] = bool(user) and billing.premium_compute_allowed(db, user)
        if not entitled[owner_id]:
            continue
        out.append({
            "id": doc["_id"],
            "name": doc.get("name") or "",
            "owner_id": owner_id,
            "key": key,
            "n_nodes": len((doc.get("graph") or {}).get("nodes") or []),
        })
    return out


def backfill(db, rows: list[dict], log=print) -> dict:
    """Compute and save each row's availability result. Failures (an
    unanalysable diagram is "skipped"; anything else "failed") never stop
    the run."""
    from backend.services import rbds as rbds_service
    from backend.services.rbd_analysis import AnalysisError

    tally = {"computed": 0, "skipped": 0, "failed": 0}
    for row in rows:
        doc = db.rbds.find_one({"_id": row["id"]})
        if doc is None:
            continue
        graph = doc.get("graph") or {}
        started = time.monotonic()
        try:
            result = rbds_service.analyze_graph(db, graph, doc["owner_id"])
        except AnalysisError as exc:
            tally["skipped"] += 1
            log(f"  skip {row['id']}: {exc}")
            continue
        except Exception as exc:  # noqa: BLE001 - keep going
            tally["failed"] += 1
            log(f"  FAIL {row['id']}: {exc}")
            continue
        key = rbds_service.availability_cache_key(graph)
        rbds_service.store_availability(db, row["id"], key, result, COMPUTED_BY)
        tally["computed"] += 1
        log(f"  saved {row['id']} ({time.monotonic() - started:.1f}s)")
    return tally


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m backend.scripts.backfill_availability_cache",
        description="Precompute saved availability results for entitled owners' repairable RBDs.",
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true", default=True,
                      help="list what would be computed (default)")
    mode.add_argument("--apply", action="store_true", help="compute and save")
    parser.add_argument("--limit", type=int, default=None, help="process at most N diagrams")
    args = parser.parse_args(argv)

    from backend import db as db_module

    db = db_module.get_db()
    rows = candidates(db)
    if args.limit is not None:
        rows = rows[: max(args.limit, 0)]
    print(f"Repairable RBDs needing a saved availability result: {len(rows)}")
    for row in rows:
        print(f"  {row['id']}  owner={row['owner_id']}  nodes={row['n_nodes']}  {row['name']!r}")
    if not args.apply:
        print("Dry run — nothing computed. Re-run with --apply to save results.")
        return 0
    tally = backfill(db, rows)
    print(f"Done: {tally['computed']} saved, {tally['skipped']} unanalysable, "
          f"{tally['failed']} failed.")
    return 1 if tally["failed"] else 0


if __name__ == "__main__":
    # Operators run this from a checkout: pick up the repo's .env so the script
    # talks to the configured database. Must happen before backend.config is
    # imported, which main() does lazily. python-dotenv is optional.
    try:
        from dotenv import load_dotenv

        load_dotenv(pathlib.Path(__file__).resolve().parents[2] / ".env")
    except ImportError:  # pragma: no cover
        pass
    sys.exit(main())
