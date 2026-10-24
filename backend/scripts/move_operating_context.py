"""Move the paragraph an RCM study left in a position's description into the position's operating context.

Moving RCM studies onto the positions used to append the study's description
(how the system is used) to the position's description, after a blank line.
Positions now keep that in a field of its own, the operating context, and the
description stays a short line on what the thing is. For the positions named
by id, this finds the appended paragraph and moves it:

* by default, the text after the first blank line of the description;
* with ``--study``, the text that equals that study's description (also when
  it was shortened to fit, ending in "…").

The paragraph goes into the operating context (after what's there, if
anything, and never twice), and the description keeps what's left. A position
with nothing to move is reported and left alone, so running it again changes
nothing.

A dry run unless --apply: the same steps on a throwaway copy of the graph
(``rcm_migrate.scratch_copy``), printing what each position would get. Run the
dry run first, read it, then run again with --apply.

    python -m backend.scripts.move_operating_context --org ORG POSITION_ID [POSITION_ID ...]
    python -m backend.scripts.move_operating_context --org ORG --study STUDY_ID POSITION_ID ...
    python -m backend.scripts.move_operating_context --apply --org ORG POSITION_ID ...

It reads the app's database and maintenance log as the app is configured
(MONGODB_URI, or the local files). --apply writes events to that log.
"""

from __future__ import annotations

import argparse
import re
import sys

ACTOR = "operating-context-move"
_BLANK = re.compile(r"\n[ \t]*\n")


def _one_line(text: str) -> str:
    return " ".join(str(text or "").split())


def _is_study_text(tail: str, said: str) -> bool:
    """``tail`` is the study's text: as it is, or shortened to fit (ending in "…",
    its lines joined)."""
    tail, said = tail.strip(), said.strip()
    if not tail or not said:
        return False
    if tail == said:
        return True
    if not tail.endswith("…"):
        return False
    head = _one_line(tail[:-1])
    return len(head) >= 20 and _one_line(said).startswith(head)


def split(description: str, study_text: str | None = None) -> tuple[str, str] | None:
    """(what stays in the description, the paragraph to move), or None when
    there's nothing to move. Without ``study_text`` the paragraph is everything
    after the first blank line; with it, the trailing text that is the study's
    description (or the whole description, when that's all it is)."""
    text = str(description or "").strip()
    if not text:
        return None
    if study_text is None:
        found = _BLANK.search(text)
        if not found:
            return None
        keep, moved = text[:found.start()].strip(), text[found.end():].strip()
        return (keep, moved) if moved else None
    if _is_study_text(text, study_text):
        return "", text
    for found in _BLANK.finditer(text):
        tail = text[found.end():]
        if _is_study_text(tail, study_text):
            return text[:found.start()].strip(), tail.strip()
    return None


def move(m, position_ids, study_text: str | None = None) -> list[dict]:
    """Move the paragraph on each position (``m``: a Maintenance on the graph to
    write to). Returns one row per position: {id, name, moved, description,
    operating_context} or {id, skipped}."""
    from backend.maintenance.rcm_migrate import present
    from backend.maintenance.service import LONG_TEXT, NotFound

    out = []
    for pid in position_ids:
        try:
            p = m._get(pid, "Position")
        except NotFound:
            out.append({"id": pid, "skipped": "no such position in this workspace"})
            continue
        parts = split(p.get("description") or "", study_text)
        if parts is None:
            out.append({"id": pid, "name": p["name"], "skipped": "nothing to move (no paragraph found)"})
            continue
        keep, moved = parts
        had = (p.get("operating_context") or "").strip()
        if present(moved, had):
            context = had
        elif had:
            context = f"{had}\n\n{moved}"
        else:
            context = moved
        if len(context) > LONG_TEXT:
            out.append({"id": pid, "name": p["name"],
                        "skipped": f"the operating context would be over {LONG_TEXT} characters; move it by hand"})
            continue
        changes = {"description": keep}
        if context != had:
            changes["operating_context"] = context
        m.update_position(pid, **changes)
        out.append({"id": pid, "name": p["name"], "moved": moved, "description": keep, "operating_context": context})
    return out


def run(store, org: str, position_ids, *, study_text: str | None = None, dry_run: bool = True,
        actor: str = ACTOR, time_zone=None) -> list[dict]:
    """Move the paragraphs, on a throwaway copy of the graph unless ``dry_run`` is False."""
    from backend.maintenance.rcm_migrate import scratch_copy
    from backend.maintenance.service import Maintenance

    work = scratch_copy(store) if dry_run else store
    m = Maintenance(work, org, actor, limited=False, time_zone=time_zone)
    return move(m, position_ids, study_text)


def report(rows: list[dict], dry_run: bool) -> str:
    """The rows in words, one block per position."""
    lines = [("DRY RUN: nothing was written. " if dry_run else "Written. ")
             + f"{len(rows)} position{'' if len(rows) == 1 else 's'}."]
    for r in rows:
        lines.append("")
        lines.append(f"Position {r['id']}" + (f" “{r['name']}”" if r.get("name") else ""))
        if r.get("skipped"):
            lines.append(f"  skipped: {r['skipped']}")
            continue
        lines.append(f"  {'would move' if dry_run else 'moved'} {len(r['moved'])} characters to the operating context")
        lines.append(f"  description now: {r['description'] or '(empty)'}")
        lines.append(f"  operating context starts: {_one_line(r['operating_context'])[:120]}")
    return "\n".join(lines)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("position_ids", nargs="+", metavar="POSITION_ID", help="the positions to change")
    parser.add_argument("--org", required=True, help="the workspace the positions are in (a user id, or team:<id>)")
    parser.add_argument("--study", help="move the text that equals this RCM study's description")
    parser.add_argument("--apply", action="store_true", help="write (default: a dry run that writes nothing)")
    args = parser.parse_args(argv)

    from backend.db import get_db
    from backend.routers.maintenance import get_store
    from backend.services import time_zones

    db = get_db()
    study_text = None
    if args.study:
        doc = db.rcm_studies.find_one({"_id": args.study}, {"description": 1})
        if doc is None:
            print(f"No RCM study {args.study}.", file=sys.stderr)
            return 1
        study_text = str(doc.get("description") or "").strip()
        if not study_text:
            print(f"RCM study {args.study} has no description to move.", file=sys.stderr)
            return 1
    rows = run(get_store(), args.org, args.position_ids, study_text=study_text, dry_run=not args.apply,
               time_zone=time_zones.of_owner(db, args.org))
    print(report(rows, dry_run=not args.apply))
    return 0


if __name__ == "__main__":
    sys.exit(main())
