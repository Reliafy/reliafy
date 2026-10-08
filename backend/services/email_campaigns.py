"""What each email brought in (#269): the operator dashboard's report.

One row per campaign — a What's-new update (``utm_medium=update``, the
campaign is its slug) or a lifecycle email (``utm_medium=lifecycle``, the
campaign is ``welcome`` / ``day3``):

* ``sent`` — recipients, from the send logs (``update_sends``,
  ``lifecycle_emails``);
* ``visitors`` / ``pageviews`` / ``top_pages`` / ``events`` — first-party
  analytics events carrying the email's tags. The site keeps the tags for the
  rest of a visit, so pages reached after the landing page count too.
  Visitors are daily-hashed, so this is visitor-days (one person on two days
  counts twice) and no event is linked to a recipient;
* ``active`` — recipients who used the app (any signed-in request, or a
  sign-in) within ``ACTIVE_DAYS`` of their send. Not shown for the welcome
  email, which goes out at a sign-in.

Plain Python over projected cursors, like ``metrics.traffic``.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone

ACTIVE_DAYS = 3
_MEDIA = ("update", "lifecycle")


def _aware(value):
    if not isinstance(value, datetime):
        return None
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def _active(db, recipients: list[tuple[str, datetime]], window: timedelta) -> int:
    """How many recipients were active in [sent, sent + window]."""
    if not recipients:
        return 0
    sent_at = {uid: at for uid, at in recipients}
    uids = list(sent_at)
    lo, hi = min(sent_at.values()), max(sent_at.values()) + window
    active = set()
    for e in db.usage_events.find({"uid": {"$in": uids}, "ts": {"$gte": lo, "$lte": hi}},
                                  {"_id": 0, "uid": 1, "ts": 1}):
        ts, at = _aware(e.get("ts")), sent_at.get(e.get("uid"))
        if ts and at and at <= ts <= at + window:
            active.add(e["uid"])
    for u in db.users.find({"_id": {"$in": uids}}, {"last_login": 1}):
        ts, at = _aware(u.get("last_login")), sent_at.get(u["_id"])
        if ts and at and at <= ts <= at + window:
            active.add(u["_id"])
    return len(active)


def report(db, days: int = 90) -> dict:
    days = max(1, min(int(days or 90), 365))
    now = datetime.now(timezone.utc)
    since = now - timedelta(days=days)

    rows: dict[tuple[str, str], dict] = defaultdict(lambda: {
        "sent": 0, "first_sent": None, "_recipients": [], "_visitors": set(),
        "pageviews": 0, "_pages": Counter(), "_events": Counter(),
    })

    for e in db.metrics_events.find(
        {"utm_source": "email", "utm_medium": {"$in": list(_MEDIA)}, "created_at": {"$gte": since}},
        {"_id": 0, "name": 1, "path": 1, "utm_medium": 1, "utm_campaign": 1, "visitor": 1, "day": 1},
    ):
        row = rows[(e.get("utm_medium") or "", e.get("utm_campaign") or "")]
        if e.get("name") == "pageview":
            row["pageviews"] += 1
            row["_visitors"].add((e.get("day"), e.get("visitor")))
            row["_pages"][e.get("path") or "/"] += 1
        else:
            row["_events"][e.get("name") or "?"] += 1

    def add_send(key, uid, at):
        at = _aware(at)
        if at is None or at < since:
            return
        row = rows[key]
        row["sent"] += 1
        row["_recipients"].append((uid, at))
        if row["first_sent"] is None or at < row["first_sent"]:
            row["first_sent"] = at

    for r in db.update_sends.find({"status": "sent", "sent_at": {"$gte": since}}, {"update_slug": 1, "uid": 1, "sent_at": 1}):
        add_send(("update", r.get("update_slug") or ""), r.get("uid"), r.get("sent_at"))
    for r in db.lifecycle_emails.find({"status": "sent", "sent_at": {"$gte": since}}, {"kind": 1, "uid": 1, "sent_at": 1}):
        add_send(("lifecycle", r.get("kind") or ""), r.get("uid"), r.get("sent_at"))

    window = timedelta(days=ACTIVE_DAYS)
    out = []
    for (medium, campaign), row in rows.items():
        welcome = medium == "lifecycle" and campaign == "welcome"
        out.append({
            "medium": medium,
            "campaign": campaign,
            "sent": row["sent"],
            "first_sent": row["first_sent"].isoformat() if row["first_sent"] else None,
            "visitors": len(row["_visitors"]),
            "pageviews": row["pageviews"],
            "top_pages": [{"key": k, "count": v} for k, v in row["_pages"].most_common(5)],
            "events": [{"key": k, "count": v} for k, v in row["_events"].most_common(5)],
            "active": None if welcome else _active(db, row["_recipients"], window),
        })
    out.sort(key=lambda r: (r["first_sent"] or "", r["campaign"]), reverse=True)
    return {"days": days, "active_days": ACTIVE_DAYS, "campaigns": out}
