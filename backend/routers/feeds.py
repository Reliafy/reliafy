"""RSS feeds for What's new and the blog, date-filtered per request.

The frontend build (``frontend/scripts/prerender.mjs``) writes every feed item
— future-dated ones included — to ``frontend/dist/feeds.json``. Serving the XML
here instead of as a static file means a queued item enters its feed on its
(UTC) date with no rebuild or redeploy, so an RSS→LinkedIn automation publishes
it that day on its own.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from email.utils import format_datetime
from pathlib import Path
from typing import Optional
from xml.sax.saxutils import escape

from fastapi import APIRouter
from fastapi.responses import Response

router = APIRouter()

FEEDS_FILE = Path(__file__).resolve().parents[2] / "frontend" / "dist" / "feeds.json"

# Short CDN/browser cache: Firebase Hosting fronts the service, and a feed
# poller (Zapier ~15 min) should see a newly-dated item within minutes.
CACHE = "public, max-age=300, s-maxage=900"


def _today() -> str:
    return datetime.now(timezone.utc).date().isoformat()


def _load(path: Path = FEEDS_FILE) -> Optional[dict]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _rfc822(iso: str) -> str:
    try:
        d = datetime.strptime(iso, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return ""
    return format_datetime(d, usegmt=True)


def render_feed(feed: dict, site: str, today: str) -> str:
    """RSS 2.0 for one feed, keeping only items dated on or before ``today``."""
    items = [
        it for it in (feed.get("items") or [])
        if not it.get("date") or str(it["date"]) <= today
    ]
    items.sort(key=lambda it: str(it.get("date") or ""), reverse=True)

    def el(tag: str, value: str, indent: str = "      ", attrs: str = "") -> str:
        return f"{indent}<{tag}{attrs}>{escape(str(value or ''))}</{tag}>"

    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<rss version="2.0" xmlns:atom="http://www.w3.org/2005/Atom">',
        "  <channel>",
        el("title", feed.get("title", ""), "    "),
        el("link", feed.get("link", ""), "    "),
        el("description", feed.get("description", ""), "    "),
        "    <language>en</language>",
        f'    <atom:link href="{escape(site + feed.get("path", ""))}" rel="self" type="application/rss+xml" />',
    ]
    if items and items[0].get("date"):
        lines.append(el("lastBuildDate", _rfc822(items[0]["date"]), "    "))
    for it in items:
        lines.append("    <item>")
        lines.append(el("title", it.get("title", "")))
        lines.append(el("link", it.get("link", "")))
        lines.append(el("guid", it.get("guid") or it.get("link", ""), attrs=' isPermaLink="true"'))
        if it.get("date"):
            lines.append(el("pubDate", _rfc822(it["date"])))
        lines.append(el("description", it.get("summary", "")))
        lines.append("    </item>")
    lines += ["  </channel>", "</rss>", ""]
    return "\n".join(lines)


def _feed_response(path: str) -> Response:
    # Look _load/_today up at call time (not as default args) so tests — and
    # anything else — can swap them.
    data = _load()
    feed = next((f for f in (data or {}).get("feeds", []) if f.get("path") == path), None)
    if feed is None:
        return Response("Feed not available.", status_code=404, media_type="text/plain")
    body = render_feed(feed, (data or {}).get("site", "https://reliafy.com"), _today())
    return Response(body, media_type="application/rss+xml; charset=utf-8",
                    headers={"Cache-Control": CACHE})


@router.get("/whats-new/feed.xml", include_in_schema=False)
def whats_new_feed() -> Response:
    return _feed_response("/whats-new/feed.xml")


@router.get("/blog/feed.xml", include_in_schema=False)
def blog_feed() -> Response:
    return _feed_response("/blog/feed.xml")
