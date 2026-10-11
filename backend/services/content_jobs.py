"""The content pipeline's scheduled job (#367): approved What's new emails.

``POST /internal/content/run`` (``backend/routers/content_jobs.py``) calls
:func:`run`. Cloud Scheduler calls it daily (hourly 10:05–17:05 Brisbane, so a
long send or a failure is picked up the same day). Every step is idempotent,
so any extra call is harmless.

**What's new auto-send.** An update whose frontmatter says ``send: auto`` was
approved by merging it. For each such update dated D:

* from 10:00 Brisbane on the Friday before D (until D): one **test copy** to
  each operator address (``CONTENT_OPERATOR_EMAILS``, default
  ``ADMIN_EMAILS``), subject marked as a test, unsubscribe link inert;
* from 10:00 Brisbane on D (00:00 UTC, when its page goes live) for three
  days: the update to the list, through the CLI's own path
  (``send_update.recipients`` / ``send_batch``): the ``update_sends`` log
  (one row per update and user), opt-outs, test domains, and the addresses in
  ``UPDATE_EMAIL_EXCLUDE``. A run stops after ``UPDATE_AUTO_SECONDS``; the
  next continues. Once a run finishes with nothing failed the update is
  marked done and never sent again (so later sign-ups don't get it).

Each step is claimed in ``content_jobs`` (``_id`` = ``update-test:<slug>`` /
``update-send:<slug>``) with a lease, so overlapping calls can't both send.
The operator gets a Pushover note after each send. ``UPDATE_AUTO_SEND`` off
(the default) sends no update at all. ``dry_run`` reports what a run would do
and sends and records nothing.

Brisbane has no daylight saving, so it is a fixed UTC+10 here.
"""

from __future__ import annotations

import json
import logging
import pathlib
import time
from datetime import date, datetime, timedelta, timezone

from pymongo.errors import DuplicateKeyError

from backend import config

logger = logging.getLogger(__name__)

BRISBANE = timezone(timedelta(hours=10), "Australia/Brisbane")
SEND_HOUR = 10
SEND_WINDOW_DAYS = 3        # an update not sent within 3 days of its date isn't sent
SEND_DELAY = 0.5            # seconds between emails (the provider's rate limit)
LEASE = timedelta(minutes=30)
TEST_PREFIX = "[Test] "

DIST = pathlib.Path(__file__).resolve().parents[2] / "frontend" / "dist"


class EmailNotConfigured(RuntimeError):
    """SMTP isn't configured: the job refuses to run."""


def friday_before(d: date) -> date:
    """The last Friday strictly before ``d``."""
    back = (d.weekday() - 4) % 7 or 7
    return d - timedelta(days=back)


def _parse_date(value: str) -> date | None:
    try:
        return datetime.strptime(str(value or "").strip(), "%Y-%m-%d").date()
    except ValueError:
        return None


def load_updates(dist: pathlib.Path = DIST) -> list:
    """Every What's new update. In the runtime image the source files aren't
    present, so they come from the build's ``dist/content.json``; in a
    checkout, from ``frontend/src/content/updates``."""
    from backend.scripts import send_update

    try:
        items = json.loads((dist / "content.json").read_text(encoding="utf-8")).get("updates")
    except (OSError, ValueError, AttributeError):
        items = None
    if items is not None:
        return [send_update.update_from_build(it) for it in items if it.get("slug")]
    return [send_update.load_update(p) for p in sorted(send_update.UPDATES_DIR.glob("*.md"))]


# ---- Claims (the send log for the job's own steps) ---------------------------

def _claim(db, key: str, now: datetime, **fields) -> bool:
    """Take step ``key`` unless it's done or another run holds its lease."""
    now = now.astimezone(timezone.utc)
    doc = {"status": "running", "lease_until": now + LEASE, "started_at": now, **fields}
    try:
        db.content_jobs.insert_one({"_id": key, **doc})
        return True
    except DuplicateKeyError:
        r = db.content_jobs.update_one(
            {"_id": key, "status": {"$ne": "done"}, "lease_until": {"$lt": now}},
            {"$set": doc})
        return r.modified_count == 1


def _finish(db, key: str, status: str, now: datetime, **fields) -> None:
    # A step left unfinished releases its lease, so the next run retries it.
    now = now.astimezone(timezone.utc)
    db.content_jobs.update_one({"_id": key}, {"$set": {
        "status": status, "lease_until": now, "finished_at": now, **fields}})


def _done(db, key: str) -> bool:
    return bool(db.content_jobs.find_one({"_id": key, "status": "done"}, {"_id": 1}))


# ---- The update steps ---------------------------------------------------------

def _test_copy(db, update, now: datetime, dry_run: bool) -> dict:
    from backend.scripts import send_update
    from backend.services import email as email_service

    key = f"update-test:{update.slug}"
    action = {"step": "test copy", "slug": update.slug, "date": update.date}
    operators = list(config.CONTENT_OPERATOR_EMAILS)
    if _done(db, key):
        return {**action, "result": "already sent"}
    if not operators:
        return {**action, "result": "no operator address (CONTENT_OPERATOR_EMAILS / ADMIN_EMAILS)"}
    if dry_run:
        return {**action, "result": "would send", "to": len(operators)}
    if not _claim(db, key, now, kind="update-test", slug=update.slug):
        return {**action, "result": "another run has it"}
    sent, failed = 0, 0
    for to in operators:
        user = db.users.find_one({"email_lc": to}, {"name": 1}) or {}
        r = send_update.render(update, user.get("name"), send_update.TEST_TOKEN)
        try:
            email_service.send_now(to, TEST_PREFIX + r.subject, r.text, html=r.html,
                                   reply_to=send_update.REPLY_TO, headers=r.headers)
            sent += 1
        except Exception:  # noqa: BLE001 - logged; retried next run
            logger.exception("content job: test copy of %s failed", update.slug)
            failed += 1
    _finish(db, key, "failed" if failed else "done", now, sent=sent, failed=failed)
    return {**action, "result": "sent" if not failed else "failed", "sent": sent, "failed": failed}


def _send_list(db, update, now: datetime, dry_run: bool, *, sleep, clock) -> dict:
    from backend.scripts import send_update
    from backend.services import push

    key = f"update-send:{update.slug}"
    action = {"step": "send", "slug": update.slug, "date": update.date}
    if _done(db, key):
        return {**action, "result": "already sent"}
    exclude = set(config.UPDATE_EMAIL_EXCLUDE)
    eligible, skipped = send_update.recipients(db, update.slug, exclude)
    skipped = {("excluded (UPDATE_EMAIL_EXCLUDE)" if k == "--exclude" else k): n
               for k, n in skipped.items()}
    if dry_run:
        return {**action, "result": "would send", "eligible": len(eligible), "skipped": skipped}
    if not _claim(db, key, now, kind="update-send", slug=update.slug):
        return {**action, "result": "another run has it"}
    lines: list[str] = []
    tally = send_update.send_batch(
        db, update, eligible, SEND_DELAY, sleep,
        deadline=clock() + max(1, config.UPDATE_AUTO_SECONDS), clock=clock, log=lines.append)
    for line in lines:
        logger.info("content job: %s: %s", update.slug, line.strip())
    complete = not tally["failed"] and not tally["stopped"]
    totals = {"sent": tally["sent"], "failed": tally["failed"], "skipped": tally["skipped"],
              "eligible": len(eligible), "excluded": skipped}
    _finish(db, key, "done" if complete else "partial", now, **{
        f"last_{k}": v for k, v in totals.items() if k != "excluded"})
    if tally["sent"] or tally["failed"]:
        push.send(
            f"What's new sent: {update.slug}",
            f"{tally['sent']} sent, {tally['failed']} failed, {tally['skipped']} skipped"
            + ("" if complete else " — not finished, the next run continues."),
            priority=0 if complete else 1,
        )
    return {**action, "result": "sent" if complete else "partial", **totals}


def _update_steps(db, local: datetime, updates, dry_run: bool, *, sleep, clock) -> list[dict]:
    actions = []
    today = local.date()
    for update in updates:
        if (update.send or "") != "auto":
            continue
        day = _parse_date(update.date)
        if day is None:
            actions.append({"step": "skip", "slug": update.slug, "result": f"bad date {update.date!r}"})
            continue
        send_at = datetime(day.year, day.month, day.day, SEND_HOUR, tzinfo=BRISBANE)
        if local >= send_at:
            if today <= day + timedelta(days=SEND_WINDOW_DAYS):
                actions.append(_send_list(db, update, local, dry_run, sleep=sleep, clock=clock))
        elif today >= friday_before(day) and local.hour >= SEND_HOUR:
            actions.append(_test_copy(db, update, local, dry_run))
    return actions


def run(db, *, now: datetime | None = None, dry_run: bool = False, updates=None,
        sleep=time.sleep, clock=time.monotonic) -> dict:
    """One scheduled run. Raises :class:`EmailNotConfigured` (unless
    ``dry_run``) when SMTP isn't set up."""
    from backend.services import email as email_service

    if not dry_run and not email_service.enabled():
        raise EmailNotConfigured("SMTP isn't configured (SMTP_HOST / EMAIL_FROM).")
    now = now or datetime.now(timezone.utc)
    local = now.astimezone(BRISBANE)
    result: dict = {"ok": True, "dry_run": dry_run, "brisbane": local.isoformat(timespec="minutes"),
                    "auto_send": bool(config.UPDATE_AUTO_SEND), "actions": []}
    if config.UPDATE_AUTO_SEND:
        if updates is None:
            updates = load_updates()
        result["actions"] += _update_steps(db, local, updates, dry_run, sleep=sleep, clock=clock)
    for action in result["actions"]:
        logger.info("content job%s: %s", " (dry run)" if dry_run else "", json.dumps(action, default=str))
    return result
