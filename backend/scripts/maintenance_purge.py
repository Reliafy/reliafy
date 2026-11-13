"""Erase part of a maintenance workspace with its history (see backend/maintenance/purge.py).

Only on the workspace owner's request: a delete in the app keeps the history;
this doesn't. A dry run (the default) lists what would go and writes nothing.

    # Everything connected to these roots, and the events that name only it.
    python -m backend.scripts.maintenance_purge --org ORG --root ID [--root ID ...] [--barrier ID ...]

    # Erase them (refused while any event names both something that goes and
    # something kept). Then replays the log and checks the rest is unchanged,
    # and copies the workspace whole to the Neo4j mirror when it has one.
    python -m backend.scripts.maintenance_purge --org ORG --root ID ... --apply [--on YYYY-MM-DD]

``--barrier``: a node never entered (kept) while finding what's connected.
``--json FILE``: also write the full plan (ids and sequence numbers) there.
Uses the app's log (MongoDB, or the local SQLite file), as ``maintenance_graph`` does.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from collections import Counter
from datetime import date


def _store():
    from backend.scripts.maintenance_graph import replay

    return replay()


def _db():
    from backend.db import get_db
    from backend.routers.maintenance import _use_mongo

    return get_db() if _use_mongo() else None


def main(argv=None) -> int:
    from backend.maintenance import purge

    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--org", required=True)
    parser.add_argument("--root", action="append", required=True, help="a node to purge with all connected to it")
    parser.add_argument("--barrier", action="append", default=[], help="a node never entered (kept)")
    parser.add_argument("--apply", action="store_true", help="erase (default: a dry run)")
    parser.add_argument("--on", default=date.today().isoformat(), help="the date the tombstones carry")
    parser.add_argument("--json", help="write the full plan to this file")
    args = parser.parse_args(argv)

    store = _store()
    before = store.snapshot(args.org)
    gone = purge.closure(store, args.org, args.root, args.barrier)
    kept = {row[0] for row in before[0]} - gone
    labels = Counter(row[2] for row in before[0] if row[0] in gone)
    the_plan = purge.plan(store, args.org, gone)
    db = _db()
    others = purge.other_records(db, args.org, gone, kept) if db is not None else {}
    report = {
        "org": args.org, "dry_run": not args.apply,
        "nodes": len(gone), "by_label": dict(labels.most_common()),
        "edges": sum(1 for e in before[1] if e[3] in gone or e[4] in gone),
        "nodes_kept": len(kept),
        "events": len(the_plan["seqs"]), "event_types": the_plan["types"],
        "events_naming_no_node": the_plan["unnamed"],
        "mixed": the_plan["mixed"],
        "other_records": {k: {"only": len(v["only"]), "shared": len(v["shared"])} for k, v in others.items()},
    }
    if args.json:
        with open(args.json, "w") as fh:
            json.dump({**report, "ids": sorted(gone), "seqs": the_plan["seqs"],
                       "other_ids": {k: [str(x) for x in v["only"]] for k, v in others.items()}}, fh, indent=1)
    if the_plan["mixed"]:
        print(json.dumps(report, indent=2, default=str))
        print(f"Refused: {len(the_plan['mixed'])} events name both what goes and what's kept. Nothing written.",
              file=sys.stderr)
        return 2
    if not args.apply:
        print(json.dumps(report, indent=2, default=str))
        return 0

    erased = store.log.purge(args.org, the_plan["seqs"], args.on)
    removed = {}
    for name, found in others.items():
        if found["only"]:
            removed[name] = db[name].delete_many({"_id": {"$in": found["only"]}}).deleted_count
    started = time.monotonic()
    after_store = _store()
    report["replay_seconds"] = round(time.monotonic() - started, 2)
    report["erased"] = erased
    report["other_removed"] = removed
    report["check"] = purge.compare(before, after_store.snapshot(args.org), gone)
    report["skipped"] = after_store.skipped()
    try:
        from backend.scripts.maintenance_graph import mirror_of

        mirror = mirror_of(after_store)
        report["mirror"] = mirror.rebuild(orgs=[args.org]) if mirror.in_scope(args.org) else "not mirrored"
    except Exception as err:  # noqa: BLE001 - the purge is done; the mirror can be rebuilt later
        report["mirror"] = f"not rebuilt ({type(err).__name__}: {err}); run maintenance_graph rebuild --apply"
    print(json.dumps(report, indent=2, default=str))
    check = report["check"]
    return 0 if not check["left"] and not check["nodes_changed"] and not check["edges_changed"] \
        and not report["skipped"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
