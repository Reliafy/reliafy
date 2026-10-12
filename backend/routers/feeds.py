"""RSS feeds for What's new, the blog and LinkedIn, date-filtered per request.

The frontend build (``frontend/scripts/prerender.mjs``) writes every feed item
— future-dated ones included — to ``frontend/dist/feeds.json``. Serving the XML
here instead of as a static file means a queued item enters its feed on its
(UTC) date with no rebuild or redeploy, so an RSS→LinkedIn automation publishes
it that day on its own (UTC midnight is 10:00 in Brisbane).

``/social/feed.xml`` is the LinkedIn feed (#367, ``frontend/src/contentFeed.js``):
short posts plus an announcement of each blog post and update. It's the only
feed the Zapier → LinkedIn Zap watches. An item there may carry ``hold_until``
(the date the page it links to goes live) and is held until then too.

A feed with ``utm`` in feeds.json gets campaign tags on each item's link
(``utm_source``/``utm_medium`` from the feed, ``utm_campaign`` the item's
``campaign``, its slug). The guid stays the untagged identity, so a reader or
Zapier never sees an old item as new.
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

from backend.services import content_gate, email_links

router = APIRouter()

DIST = Path(__file__).resolve().parents[2] / "frontend" / "dist"
FEEDS_FILE = DIST / "feeds.json"

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


def is_live(item: dict, today: str) -> bool:
    """Whether a feed item is out: its date (and any ``hold_until``) reached."""
    return all(not item.get(k) or str(item[k]) <= today for k in ("date", "hold_until"))


def item_link(feed: dict, item: dict) -> str:
    """The item's link, campaign-tagged when the feed has ``utm``."""
    link = str(item.get("link") or "")
    utm = feed.get("utm") or {}
    if not link or not utm.get("source"):
        return link
    return email_links.tag_url(link, source=str(utm["source"]), medium=str(utm.get("medium") or ""),
                               campaign=str(item.get("campaign") or ""))


_IMAGE_TYPES = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
                ".gif": "image/gif", ".webp": "image/webp"}


def render_feed(feed: dict, site: str, today: str) -> str:
    """RSS 2.0 for one feed, keeping only items that are live on ``today``."""
    items = [it for it in (feed.get("items") or []) if is_live(it, today)]
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
        permalink = "false" if it.get("permalink") is False else "true"
        lines.append("    <item>")
        lines.append(el("title", it.get("title", "")))
        lines.append(el("link", item_link(feed, it)))
        lines.append(el("guid", it.get("guid") or it.get("link", ""), attrs=f' isPermaLink="{permalink}"'))
        if it.get("date"):
            lines.append(el("pubDate", _rfc822(it["date"])))
        lines.append(el("description", it.get("summary", "")))
        image = str(it.get("image") or "")
        if image:
            kind = _IMAGE_TYPES.get(Path(image.split("?")[0]).suffix.lower(), "image/png")
            url = escape(image, {'"': "&quot;"})
            lines.append(f'      <enclosure url="{url}" type="{kind}" length="0" />')
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


@router.get("/social/feed.xml", include_in_schema=False)
def social_feed() -> Response:
    """The LinkedIn feed: the only one the Zapier → LinkedIn Zap watches."""
    return _feed_response("/social/feed.xml")


@router.get("/sitemap.xml", include_in_schema=False)
def sitemap() -> Response:
    """The build's sitemap without pages that aren't live yet (#367): a post
    prerendered ahead of its date joins the sitemap on that date."""
    try:
        xml = (DIST / "sitemap.xml").read_text(encoding="utf-8")
    except OSError:
        return Response("Not found.", status_code=404, media_type="text/plain")
    body = content_gate.filter_sitemap(xml, content_gate.pages(DIST), _today())
    return Response(body, media_type="application/xml; charset=utf-8",
                    headers={"Cache-Control": CACHE})
