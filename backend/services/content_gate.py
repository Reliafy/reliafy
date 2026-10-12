"""The date gate on prerendered blog and update pages (#367).

The build prerenders every blog post and What's new update, future-dated ones
included, and lists them all in ``sitemap.xml``. ``frontend/dist/content.json``
names each dated page with its date::

    {"pages": {"/blog/<slug>": "2026-10-19", "/whats-new/<slug>": "2026-11-02"}}

Until a page's date (UTC; 00:00 UTC is 10:00 in Brisbane) arrives, the server
answers its path exactly as for an unknown path — a 404 with the SPA shell,
whose date gate says "Post not found" (#374) — and leaves it out of
``/sitemap.xml``. On the day
it serves the prerendered HTML, with no rebuild or redeploy.

The build files that list queued items (``feeds.json``, ``content.json``) and
the prerendered files' own paths (``/static/...``) are never served directly.
"""

from __future__ import annotations

import json
import re
import threading
from datetime import datetime, timezone
from pathlib import Path

GATE_FILE = "content.json"
# Build outputs read by the server only: they list queued (future) items.
PRIVATE_BUILD_FILES = frozenset({"feeds.json", GATE_FILE})

_cache: dict[str, tuple[float, dict]] = {}
_lock = threading.Lock()


def today() -> str:
    return datetime.now(timezone.utc).date().isoformat()


def _key(path: str) -> str:
    return "/" + str(path or "").strip("/").lower()


def pages(dist: Path) -> dict[str, str]:
    """``{path: date}`` from ``dist/content.json`` (empty when absent or
    unreadable). Re-read only when the file changes."""
    file = Path(dist) / GATE_FILE
    try:
        mtime = file.stat().st_mtime
    except OSError:
        return {}
    with _lock:
        hit = _cache.get(str(file))
        if hit and hit[0] == mtime:
            return hit[1]
    try:
        raw = json.loads(file.read_text(encoding="utf-8")).get("pages") or {}
        data = {_key(k): str(v) for k, v in raw.items() if v}
    except (OSError, ValueError, AttributeError):
        data = {}
    with _lock:
        _cache[str(file)] = (mtime, data)
    return data


def indexed(dist: Path) -> bool:
    """Whether the build has its content index: a cloud build's prerender
    writes ``content.json`` alongside a prerendered page for every piece of
    public content, so a public path with no live page doesn't exist (#374).
    Self-host and dev builds have neither, and can't tell."""
    return (Path(dist) / GATE_FILE).is_file()


def held(path: str, dist: Path, on: str | None = None) -> bool:
    """Whether ``path``'s page is dated after ``on`` (default: today, UTC)."""
    date = pages(dist).get(_key(path))
    return bool(date) and date > (on or today())


def is_private(full_path: str) -> bool:
    """Build files and prerendered-file paths the server never serves as-is."""
    p = str(full_path or "").strip("/")
    return p in PRIVATE_BUILD_FILES or p == "static" or p.startswith("static/")


_URL_RE = re.compile(r"[ \t]*<url>\s*<loc>([^<]*)</loc>.*?</url>\n?", re.S)


def filter_sitemap(xml: str, dates: dict[str, str], on: str) -> str:
    """``sitemap.xml`` without the ``<url>`` entries of pages not yet live."""
    def keep(m: re.Match) -> str:
        loc = m.group(1).strip()
        path = re.sub(r"^https?://[^/]+", "", loc) or "/"
        date = dates.get(_key(path))
        return "" if date and date > on else m.group(0)
    return _URL_RE.sub(keep, xml)
