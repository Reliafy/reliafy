"""First-party visitor analytics, stored in our own database.

Events land in ``metrics_events`` with a privacy budget of zero: no raw IP,
no raw user-agent, no cookie, no cross-day identifier. Daily unique visitors
come from a salted hash of (day, ip, user-agent) — the salt plus the day in
the hash means yesterday's hash can't be joined to today's, and nothing
stored can be reversed to an address. This keeps the privacy-policy promise
("first-party only, no third parties") while still answering the questions
that matter: how many people, from where, looking at what.
"""

from __future__ import annotations

import hashlib
import re
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse

from backend import config

# Crawlers and headless browsers aren't visitors.
_BOT_RE = re.compile(
    r"bot|crawl|spider|slurp|preview|headless|python-requests|curl/|wget/",
    re.IGNORECASE,
)

# Referrers from ourselves (any deploy alias) are navigation, not acquisition.
_SELF_HOSTS = {"reliafy.com", "www.reliafy.com", "localhost", "127.0.0.1"}

_CLIP = 300
RETENTION_DAYS = 90


def _visitor_hash(day: str, ip: str, user_agent: str) -> str:
    raw = f"{config.METRICS_SALT}|{day}|{ip}|{user_agent}"
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


def _referrer_host(referrer: str) -> str:
    """External referrer host, or '' for none/own-site/junk."""
    if not referrer:
        return ""
    try:
        host = (urlparse(referrer).netloc or "").split(":")[0].lower()
    except ValueError:
        return ""
    if not host or host in _SELF_HOSTS or host.endswith(".run.app"):
        return ""
    return host[:_CLIP]


def record_event(
    db,
    *,
    name: str,
    path: str,
    referrer: str = "",
    utm_source: str = "",
    utm_medium: str = "",
    utm_campaign: str = "",
    ip: str = "",
    user_agent: str = "",
) -> bool:
    """Store one event; returns False when filtered (bots)."""
    if user_agent and _BOT_RE.search(user_agent):
        return False
    now = datetime.now(timezone.utc)
    day = now.strftime("%Y-%m-%d")
    db.metrics_events.insert_one(
        {
            "name": str(name or "pageview")[:100],
            "path": str(path or "")[:_CLIP],
            "ref_host": _referrer_host(str(referrer or "")),
            "utm_source": str(utm_source or "")[:100],
            "utm_medium": str(utm_medium or "")[:100],
            "utm_campaign": str(utm_campaign or "")[:100],
            "visitor": _visitor_hash(day, ip, user_agent),
            "day": day,
            "created_at": now,
        }
    )
    return True


def traffic(db, days: int = 14) -> dict:
    """Aggregate the last ``days`` of events for the operator dashboard.

    Aggregation is plain Python over a projected cursor: volumes are small at
    this stage, and it keeps mongomock (tests, self-host fallback) fully
    supported without worrying about aggregation-pipeline coverage.
    """
    days = max(1, min(int(days or 14), RETENTION_DAYS))
    since = datetime.now(timezone.utc) - timedelta(days=days)
    cursor = db.metrics_events.find(
        {"created_at": {"$gte": since}},
        {
            "_id": 0, "name": 1, "path": 1, "ref_host": 1,
            "utm_source": 1, "visitor": 1, "day": 1,
        },
    )

    daily_views: Counter = Counter()
    daily_visitors: dict[str, set] = defaultdict(set)
    pages: Counter = Counter()
    referrers: Counter = Counter()
    sources: Counter = Counter()
    events: Counter = Counter()

    for e in cursor:
        day = e.get("day", "")
        if e.get("name") == "pageview":
            daily_views[day] += 1
            daily_visitors[day].add(e.get("visitor"))
            pages[e.get("path") or "/"] += 1
            if e.get("ref_host"):
                referrers[e["ref_host"]] += 1
            if e.get("utm_source"):
                sources[e["utm_source"]] += 1
        else:
            events[e["name"]] += 1

    # A continuous day axis (oldest first), zero-filled.
    today = datetime.now(timezone.utc).date()
    axis = [(today - timedelta(days=i)).strftime("%Y-%m-%d") for i in range(days - 1, -1, -1)]
    daily = [
        {"day": d, "pageviews": daily_views.get(d, 0), "visitors": len(daily_visitors.get(d, ()))}
        for d in axis
    ]

    top = lambda c, n=10: [{"key": k, "count": v} for k, v in c.most_common(n)]
    return {
        "days": days,
        "pageviews": sum(daily_views.values()),
        "visitors_daily_sum": sum(len(v) for v in daily_visitors.values()),
        "daily": daily,
        "top_pages": top(pages),
        "top_referrers": top(referrers),
        "top_sources": top(sources),
        "events": top(events),
    }
