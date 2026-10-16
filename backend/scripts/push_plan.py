"""Store the operators' plan (a markdown file) for the Admin page's Plan tab.

    # What would be stored: the size and the number of mermaid blocks only.
    python -m backend.scripts.push_plan path/to/PLAN.md --dry-run

    # Store it, saying where it came from.
    python -m backend.scripts.push_plan path/to/PLAN.md --source "org/repo@<sha>"

It writes through the same function as ``PUT /api/admin/plan``
(:func:`backend.services.admin_plan.store`), to the database in the
MONGODB_URI environment of wherever it runs (the repo's ``.env`` when run
from a checkout). It never prints the plan or the connection string.
"""

from __future__ import annotations

import argparse
import pathlib
import sys

PUSHED_BY = "push_plan script"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m backend.scripts.push_plan",
        description="Store a markdown plan for the Admin page's Plan tab.",
    )
    parser.add_argument("path", type=pathlib.Path, help="the markdown file")
    parser.add_argument("--source", default="", help='where it came from, e.g. "org/repo@<sha>"')
    parser.add_argument("--dry-run", action="store_true", help="print its size and mermaid block count; store nothing")
    args = parser.parse_args(argv)

    from backend.services import admin_plan

    try:
        markdown = args.path.read_text(encoding="utf-8")
    except OSError as exc:
        print(f"Can't read {args.path}: {exc.strerror or exc}", file=sys.stderr)
        return 2
    n = admin_plan.size(markdown)
    blocks = admin_plan.mermaid_blocks(markdown)
    print(f"{n:,} bytes, {blocks} mermaid block{'' if blocks == 1 else 's'}")
    if n > admin_plan.MAX_BYTES:
        print(f"Too large: the limit is {admin_plan.MAX_BYTES:,} bytes.", file=sys.stderr)
        return 1
    if args.dry_run:
        print("Dry run: nothing stored.")
        return 0

    from backend import db as db_module

    stored = admin_plan.store(db_module.get_db(), markdown, args.source, PUSHED_BY)
    where = " (in-memory simulator: MONGODB_URI is not set, so nothing persists)" if db_module._simulated else ""
    print(f"Stored at {stored['updated_at']}{where}.")
    return 0


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
