"""Put each function's separate working into its notes and rationale (Nov 2026).

The working behind a performance standard used to have its own section on a
function (``standard_basis``); it is now part of the function's notes and
rationale. Reads already show the two together, so this changes nothing a
user sees: it records the merge in the log (``function.working_merged``, one
per function that still has a separate working) so the old field can go
quiet. Nothing in the log is rewritten, and running it again merges nothing.

    # What it would merge, per organisation (a dry run: nothing is written).
    python -m backend.scripts.merge_function_workings [--org ORG]

    # Write the merge events.
    python -m backend.scripts.merge_function_workings [--org ORG] --apply

It uses the app's own store (MongoDB, or the local SQLite file, as the app
chooses), so run it with the same environment as the app.
"""

from __future__ import annotations

import argparse
import json


def merge(store, org: str | None = None, apply: bool = False) -> dict:
    """Each organisation with a function: what merge_workings found (and wrote, with apply)."""
    from backend.maintenance.service import Maintenance

    orgs = [org] if org else store.orgs_with("Function")
    out = {}
    for o in orgs:
        result = Maintenance(store, o, "merge_function_workings", limited=False).merge_workings(dry_run=not apply)
        if result["functions"]:
            out[o] = result
    return {"dry_run": not apply, "orgs": out, "functions": sum(r["functions"] for r in out.values())}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--org", help="one organisation (default: every one)")
    parser.add_argument("--apply", action="store_true", help="write the merge events (default: a dry run)")
    args = parser.parse_args(argv)

    from backend.routers.maintenance import get_store

    print(json.dumps(merge(get_store(), args.org, args.apply), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
