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
from datetime import datetime, timezone
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


def _field(value, limit: int) -> str:
    """A stored text field: bounded, with CR/LF escaped."""
    return str(value or "")[:limit].replace("\r", "\\r").replace("\n", "\\n")


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
    walkthrough: str = "",
    step: int | None = None,
    filter_bots: bool = True,
) -> bool:
    """Store one event; returns False when filtered (bots). A guided
    walkthrough's events (#32) also carry its id and, for a step, the step.
    ``filter_bots=False`` keeps an event whatever the user agent (the
    server-side signup: an account is real however it was made)."""
    if filter_bots and user_agent and _BOT_RE.search(user_agent):
        return False
    now = datetime.now(timezone.utc)
    day = now.strftime("%Y-%m-%d")
    doc = {
        "name": _field(name or "pageview", 100),
        "path": _field(path, _CLIP),
        "ref_host": _field(_referrer_host(str(referrer or "")), _CLIP),
        "utm_source": _field(utm_source, 100),
        "utm_medium": _field(utm_medium, 100),
        "utm_campaign": _field(utm_campaign, 100),
        "visitor": _visitor_hash(day, ip, user_agent),
        "day": day,
        "created_at": now,
    }
    if walkthrough:
        doc["walkthrough"] = _field(walkthrough, 40)
        if step is not None:
            doc["step"] = int(step)
    db.metrics_events.insert_one(doc)
    return True
