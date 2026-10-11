"""In-app guided walkthroughs (#32): their ids, the events they report, and
each user's one automatic start.

The steps themselves live in the frontend (``frontend/src/walkthroughs.js``);
the ids here are the allowlist for the events and must match it.

* Events go through ``/api/metrics/event`` like the first-run starts:
  ``walkthrough_started``, ``walkthrough_step`` (a step shown for the first
  time in a run, 1-based), ``walkthrough_completed`` and
  ``walkthrough_skipped``, each with the walkthrough's id. The operator's
  traffic report counts them per walkthrough (:func:`summarise`).
* A walkthrough starts automatically (from a first-run start) at most once
  per user: :func:`claim_auto_start` records the claim on the user's
  profile, atomically, so two tabs can't both run it.
"""

from __future__ import annotations

WALKTHROUGH_IDS = ("fit", "replacement", "rbd", "rcm", "fleet")
# No walkthrough has more steps than this.
MAX_STEPS = 10

STARTED = "walkthrough_started"
STEP = "walkthrough_step"
COMPLETED = "walkthrough_completed"
SKIPPED = "walkthrough_skipped"
EVENTS = (STARTED, STEP, COMPLETED, SKIPPED)


def is_walkthrough(walkthrough_id) -> bool:
    return isinstance(walkthrough_id, str) and walkthrough_id in WALKTHROUGH_IDS


def valid_event(name: str, walkthrough_id, step) -> bool:
    """Whether a walkthrough event carries what it must: a known id, and for
    a step a number from 1 to MAX_STEPS."""
    if name not in EVENTS or not is_walkthrough(walkthrough_id):
        return False
    if name == STEP:
        return isinstance(step, int) and 1 <= step <= MAX_STEPS
    return step is None or (isinstance(step, int) and 1 <= step <= MAX_STEPS)


def claim_auto_start(db, uid: str, walkthrough_id: str) -> bool:
    """True the first time ``uid`` claims ``walkthrough_id``'s automatic
    start, False ever after (and for an unknown id)."""
    if not is_walkthrough(walkthrough_id):
        return False
    result = db.users.update_one(
        {"_id": uid, "walkthroughs_auto": {"$ne": walkthrough_id}},
        {"$addToSet": {"walkthroughs_auto": walkthrough_id}},
    )
    return result.modified_count == 1


def summarise(events) -> list[dict]:
    """Per walkthrough, from event documents ({name, walkthrough, step}):
    runs started, completed and skipped, how many reached each step, and the
    completion rate. Every walkthrough is listed, in order, zeros included."""
    rows = {
        wid: {"key": wid, "started": 0, "completed": 0, "skipped": 0, "steps": {}}
        for wid in WALKTHROUGH_IDS
    }
    for e in events:
        row = rows.get(e.get("walkthrough"))
        name = e.get("name")
        if row is None:
            continue
        if name == STARTED:
            row["started"] += 1
        elif name == COMPLETED:
            row["completed"] += 1
        elif name == SKIPPED:
            row["skipped"] += 1
        elif name == STEP and isinstance(e.get("step"), int):
            key = str(e["step"])
            row["steps"][key] = row["steps"].get(key, 0) + 1
    for row in rows.values():
        row["completion_rate"] = round(row["completed"] / row["started"], 4) if row["started"] else None
    return list(rows.values())
