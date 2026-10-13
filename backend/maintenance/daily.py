"""The daily maintenance run: raise work orders for tasks coming due, and email
each person a digest when there's new work.

Called from the scheduled content job (backend/services/content_jobs.py), so
it needs no scheduler of its own. Runs once a day: a ``maintenance_runs``
document per date makes a repeat a no-op. The run's time is the same for
everyone; each workspace's dates (what's due, what's overdue, the day a work
order is opened) are worked out in its own time zone.
"""

from __future__ import annotations

import logging
from datetime import date

from backend import config
from backend.maintenance import loop
from backend.maintenance.access import allowed
from backend.maintenance.service import Maintenance
from backend.services import time_zones

logger = logging.getLogger(__name__)

HORIZON_DAYS = 14


def _digest(work_orders: list[dict], overdue: list[dict], proposals=(), short_spares=()) -> tuple[str, str]:
    n = len(work_orders)
    parts = [f"{n} new work order{'s' if n != 1 else ''}"] if n else []
    if proposals:
        parts.append(f"{len(proposals)} proposed change{'s' if len(proposals) != 1 else ''}")
    subject = "Reliafy Maintenance: " + " and ".join(parts)
    lines = ["New work orders for tasks coming due:", ""] if n else []
    for w in work_orders:
        where = (w.get("position") or {}).get("name", "")
        lines.append(f"  #{w['number']} {w['title']} ({where}), due {w.get('due') or 'now'}")
    if overdue:
        lines += ["", f"Overdue: {len(overdue)} task{'s' if len(overdue) != 1 else ''}."]
        for t in overdue[:10]:
            lines.append(f"  {t['name']} ({(t.get('position') or {}).get('name', '')}), due {t['next_due']}")
    if proposals:
        lines += ["", "The records changed a life model, and it proposes:"]
        for pr in proposals:
            to = pr.get("proposed")
            change = f"every {to['interval']:g} {to['unit']}" if to else "run to failure"
            lines.append(f"  {(pr.get('task') or {}).get('name', '')} ({(pr.get('position') or {}).get('name', '')}): {change}")
        lines.append("  Accept or reject them on the Maintenance page.")
    if short_spares:
        lines += ["", "Critical spares below the minimum kept on hand:"]
        for v in short_spares[:10]:
            lines.append(f"  {v['part']['part_number']} {v['part']['name']} for {v['position']['name']}: "
                         f"{v['usable_on_hand']:g} usable, keep {v['min_on_hand'] or 0:g}")
    base = (config.PUBLIC_BASE_URL or "https://reliafy.com").rstrip("/")
    lines += ["", f"Open them: {base}/maintenance", "",
              "Turn these emails off on the Maintenance page.", "", "— Reliafy"]
    return subject, "\n".join(lines)


def _run_org(db, store, org: str, result: dict, dry_run: bool, email_service) -> None:
    """The daily run for one organisation: its work orders, refits and digest."""
    m = Maintenance(store, org, "scheduler", limited=False, time_zone=time_zones.of_owner(db, org))
    if dry_run:
        due = [t for t in m.due_tasks(HORIZON_DAYS) if not t["open_work_order"]]
        result["orgs"] += 1
        result["work_orders"] += len(due)
        return
    made = m.generate_work_orders(HORIZON_DAYS)
    result["orgs"] += 1
    result["work_orders"] += len(made)
    before = {pr["id"] for pr in m.proposals("pending")}
    try:
        refitted = loop.refit_stale(m, db)
    except Exception:  # noqa: BLE001 - a bad refit mustn't stop the run
        logger.exception("maintenance refit failed for %s", org)
        refitted = []
    new_proposals = [pr for pr in m.proposals("pending") if pr["id"] not in before]
    result["refitted"] = result.get("refitted", 0) + len(refitted)
    if (not made and not new_proposals) or org.startswith("team:"):
        return
    user = db.users.find_one({"_id": org}) or {}
    if not allowed({**user, "uid": org}) or user.get("maintenance_digest_off") or not user.get("email"):
        return
    overdue = [t for t in m.due_tasks(0) if t["overdue"]]
    # Spares short ride along with an email that's going anyway; on their own they'd
    # repeat every day until restocked.
    subject, body = _digest(made, overdue, new_proposals, m.critical_spares_short())
    email_service.send(user["email"], subject, body)
    result["emails"] += 1


def run(db, store, *, today: date | None = None, dry_run: bool = False) -> dict:
    """One daily run over every organisation with tasks."""
    from backend.services import email as email_service

    day = (today or time_zones.today()).isoformat()
    if db.maintenance_runs.find_one({"_id": day}):
        return {"step": "maintenance", "skipped": "already ran today"}
    store.sync()
    result = {"step": "maintenance", "date": day, "orgs": 0, "work_orders": 0, "emails": 0}
    for org in store.orgs_with("Task"):
        # One organisation's trouble (a record the date maths can't place, a
        # failed email) mustn't stop the run for the others.
        try:
            _run_org(db, store, org, result, dry_run, email_service)
        except Exception:  # noqa: BLE001
            logger.exception("maintenance daily run failed for %s", org)
            result["failed"] = result.get("failed", 0) + 1
    if not dry_run:
        db.maintenance_runs.insert_one({"_id": day, "result": result})
    logger.info("maintenance daily run: %s", result)
    return result
