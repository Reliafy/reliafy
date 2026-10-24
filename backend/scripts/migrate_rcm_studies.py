"""Move RCM studies onto the maintenance positions (backend/maintenance/rcm_migrate.py).

A dry run unless --apply: the same steps on a throwaway copy of the graph,
printing what each study would add (functions, functional failures, failure
modes put under them, decisions and evidence copied, positions made). Run the
dry run first, read it, then run again with --apply.

    python -m backend.scripts.migrate_rcm_studies [--owner OWNER] [--study STUDY_ID]
    python -m backend.scripts.migrate_rcm_studies --apply [--owner OWNER] [--study STUDY_ID]

It reads the app's database and maintenance log as the app is configured
(MONGODB_URI, or the local files). --apply writes events to that log and marks
each study moved; run it twice and the second run changes nothing.
"""

from __future__ import annotations

import argparse
import sys


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--apply", action="store_true", help="write (default: a dry run that writes nothing)")
    parser.add_argument("--owner", help="only this owner's studies (a user id, or team:<id>)")
    parser.add_argument("--study", help="only this study")
    args = parser.parse_args(argv)

    from backend.db import get_db
    from backend.maintenance import rcm_migrate
    from backend.routers.maintenance import get_store

    results = rcm_migrate.migrate(get_db(), get_store(), owner=args.owner, study_id=args.study,
                                  dry_run=not args.apply)
    print(rcm_migrate.report(results, dry_run=not args.apply))
    return 0


if __name__ == "__main__":
    sys.exit(main())
