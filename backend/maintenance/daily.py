"""The daily maintenance run: raise work orders for tasks coming due, and email
each person a digest when there's new work.

Called from the scheduled content job (backend/services/content_jobs.py), so
it needs no scheduler of its own. Runs once a day: a ``maintenance_runs``
document per date makes a repeat a no-op.
"""

from __future__ import annotations

import logging
from datetime import date

from backend import config
from backend.maintenance.access import allowed
from backend.maintenance.service import Maintenance

logger = logging.getLogger(__name__)

HORIZON_DAYS = 14


def _digest(work_orders: list[dict], overdue: list[dict]) -> tuple[str, str]:
    n = len(work_orders)
    subject = f"Reliafy Maintenance: {n} new work order{'s' if n != 1 else ''}"
    lines = ["New work orders for tasks coming due:", ""]
    for w in work_orders:
        where = (w.get("position") or {}).get("name", "")
        lines.append(f"  #{w['number']} {w['title']} ({where}), due {w.get('due') or 'now'}")
    if overdue:
        lines += ["", f"Overdue: {len(overdue)} task{'s' if len(overdue) != 1 else ''}."]
        for t in overdue[:10]:
            lines.append(f"  {t['name']} ({(t.get('position') or {}).get('name', '')}), due {t['next_due']}")
    base = (config.PUBLIC_BASE_URL or "https://reliafy.com").rstrip("/")
    lines += ["", f"Open them: {base}/maintenance", "",
              "Turn these emails off on the Maintenance page.", "", "— Reliafy"]
    return subject, "\n".join(lines)


def run(db, store, *, today: date | None = None, dry_run: bool = False) -> dict:
    """One daily run over every organisation with tasks."""
    from backend.services import email as email_service

    day = (today or date.today()).isoformat()
    if db.maintenance_runs.find_one({"_id": day}):
        return {"step": "maintenance", "skipped": "already ran today"}
    store.sync()
    result = {"step": "maintenance", "date": day, "orgs": 0, "work_orders": 0, "emails": 0}
    for org in store.orgs_with("Task"):
        m = Maintenance(store, org, "scheduler")
        if dry_run:
            due = [t for t in m.due_tasks(HORIZON_DAYS) if not t["open_work_order"]]
            result["orgs"] += 1
            result["work_orders"] += len(due)
            continue
        made = m.generate_work_orders(HORIZON_DAYS)
        result["orgs"] += 1
        result["work_orders"] += len(made)
        if not made or org.startswith("team:"):
            continue
        user = db.users.find_one({"_id": org}) or {}
        if not allowed({**user, "uid": org}) or user.get("maintenance_digest_off") or not user.get("email"):
            continue
        overdue = [t for t in m.due_tasks(0) if t["overdue"]]
        subject, body = _digest(made, overdue)
        email_service.send(user["email"], subject, body)
        result["emails"] += 1
    if not dry_run:
        db.maintenance_runs.insert_one({"_id": day, "result": result})
    logger.info("maintenance daily run: %s", result)
    return result
