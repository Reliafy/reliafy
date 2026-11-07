"""Put each failure mode's decision notes into its notes and rationale (Nov 2026).

A failure mode's decision used to keep notes of its own (``decision_notes``),
beside the mode's notes and rationale; there is now one place for both. Reads
already show the two together (the mode's notes, then a "Decision" line and the
decision's notes), so this changes nothing a user sees: it records the merge in
the log (``failure_mode.decision_notes_merged``, one per failure mode that still
has decision notes of its own) so the old field can go quiet. Nothing in the log
is rewritten, and running it again merges nothing.

    # What it would merge, per organisation (a dry run: nothing is written).
    python -m backend.scripts.merge_decision_notes [--org ORG]

    # Write the merge events.
    python -m backend.scripts.merge_decision_notes [--org ORG] --apply

It uses the app's own store (MongoDB, or the local SQLite file, as the app
chooses), so run it with the same environment as the app.
"""

from __future__ import annotations

import argparse
import json


def merge(store, org: str | None = None, apply: bool = False) -> dict:
    """Each organisation with a failure mode: what merge_decision_notes found (and wrote, with apply)."""
    from backend.maintenance.service import Maintenance

    orgs = [org] if org else store.orgs_with("FailureMode")
    out = {}
    for o in orgs:
        result = Maintenance(store, o, "merge_decision_notes", limited=False).merge_decision_notes(dry_run=not apply)
        if result["modes"]:
            out[o] = result
    return {"dry_run": not apply, "orgs": out, "modes": sum(r["modes"] for r in out.values())}


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
