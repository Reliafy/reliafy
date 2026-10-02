"""Free quick availability simulations (#147): the per-user daily cap.

Users without premium compute may run a quick, time-capped availability
simulation in the app, ``FREE_SIMS_PER_DAY`` per UTC day. Counted in
``free_sim_usage``, one document per user per day (TTL-dropped a day after
the reset), like the MCP quota in :mod:`backend.services.billing`.
"""

from __future__ import annotations

from datetime import timedelta

from backend import config
from backend.services import billing


def _id(uid: str, day: str) -> str:
    return f"{uid}:{day}"


def used_today(db, uid: str) -> int:
    doc = db.free_sim_usage.find_one({"_id": _id(uid, billing._day())})
    return int((doc or {}).get("count", 0))


def summary(db, uid: str) -> dict:
    """What the app shows next to the quick-run button."""
    per_day = int(config.FREE_SIMS_PER_DAY)
    used = used_today(db, uid)
    return {
        "seconds": float(config.FREE_SIM_SECONDS),
        "per_day": per_day,
        "used_today": used,
        "remaining_today": max(per_day - used, 0),
        "resets_at": billing.next_day_start().isoformat(),
    }


def consume(db, uid: str) -> str | None:
    """Count one quick simulation against today's cap. Returns the UTC day it
    was counted on (for :func:`refund`), or None when the cap is reached.
    Atomic: the increment only matches while ``count`` is under the cap."""
    day = billing._day()
    key = _id(uid, day)
    db.free_sim_usage.update_one(
        {"_id": key},
        {"$setOnInsert": {"uid": uid, "day": day, "count": 0,
                          "expires_at": billing.next_day_start() + timedelta(days=1)}},
        upsert=True,
    )
    res = db.free_sim_usage.update_one(
        {"_id": key, "count": {"$lt": int(config.FREE_SIMS_PER_DAY)}}, {"$inc": {"count": 1}}
    )
    return day if getattr(res, "modified_count", 0) else None


def refund(db, uid: str, day: str | None) -> None:
    """Give back a run that never produced a result (it couldn't start, or the
    diagram couldn't be analysed)."""
    if not day:
        return
    db.free_sim_usage.update_one({"_id": _id(uid, day), "count": {"$gt": 0}}, {"$inc": {"count": -1}})


def cap_message() -> str:
    reset = billing.next_day_start()
    return (
        f"You've used today's {int(config.FREE_SIMS_PER_DAY)} free quick simulations. They reset at "
        f"00:00 UTC ({reset.strftime('%d %b %H:%M')} UTC). Reliafy Pro runs full-precision "
        "simulations with no daily limit — or download the diagram and run it yourself with RePyability."
    )


def options() -> dict:
    """The run options of a quick simulation."""
    return {
        "time_budget_s": float(config.FREE_SIM_SECONDS),
        "max_replications": int(config.FREE_SIM_MAX_REPLICATIONS) or None,
    }
