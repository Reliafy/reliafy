"""Small cached JSON fetches from GitHub and PyPI, for the admin page.

The Libraries and Content tabs read a dozen GitHub API URLs and two PyPI
ones. Each answer is kept in memory for ``TTL`` seconds; after that it's
revalidated with its ETag (GitHub doesn't count a ``304 Not Modified``
against the rate limit, which is 60 requests an hour per IP without a token).
``GITHUB_TOKEN``, when set, authenticates the GitHub calls (5,000 an hour).

Every call times out after ``TIMEOUT`` seconds and never raises: a failure
returns :class:`Result` with ``error`` set (and the last good answer, marked
stale, if there is one), so one slow or failing source shows as
"unavailable" on its own.
"""

from __future__ import annotations

import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import Any, Callable

import httpx

TTL = 12 * 60          # seconds an answer is reused without asking again
TIMEOUT = 3.0          # seconds per request
GITHUB_API = "https://api.github.com"
PYPI = "https://pypi.org/pypi"


@dataclass
class Result:
    data: Any = None
    error: str | None = None
    fetched_at: float | None = None
    stale: bool = False


@dataclass
class _Entry:
    data: Any
    etag: str | None
    fetched_at: float


_cache: dict[str, _Entry] = {}
_lock = threading.Lock()


def clear() -> None:
    with _lock:
        _cache.clear()


def _headers(url: str, etag: str | None) -> dict:
    h = {"Accept": "application/json", "User-Agent": "reliafy-admin"}
    if url.startswith(GITHUB_API):
        h["Accept"] = "application/vnd.github+json"
        h["X-GitHub-Api-Version"] = "2022-11-28"
        token = (os.environ.get("GITHUB_TOKEN") or "").strip()
        if token:
            h["Authorization"] = f"Bearer {token}"
    if etag:
        h["If-None-Match"] = etag
    return h


def _describe(status: int, headers) -> str:
    if status in (403, 429) and (headers.get("x-ratelimit-remaining") == "0" or status == 429):
        return "rate limited"
    if status == 404:
        return "not found"
    return f"HTTP {status}"


def _http_get(url: str, headers: dict) -> tuple[int, dict, Any]:
    """(status, headers, json or None). The one network call; tests swap it."""
    r = httpx.get(url, headers=headers, timeout=TIMEOUT, follow_redirects=True)
    body = None
    if r.status_code == 200:
        body = r.json()
    return r.status_code, {k.lower(): v for k, v in r.headers.items()}, body


def get(url: str, *, refresh: bool = False, now: Callable[[], float] = time.time) -> Result:
    """The JSON at ``url``, from the cache when it's younger than ``TTL``
    (``refresh`` revalidates regardless)."""
    with _lock:
        hit = _cache.get(url)
    t = now()
    if hit and not refresh and t - hit.fetched_at < TTL:
        return Result(hit.data, None, hit.fetched_at)
    try:
        status, headers, body = _http_get(url, _headers(url, hit.etag if hit else None))
    except (httpx.HTTPError, ValueError) as exc:
        err = "timed out" if isinstance(exc, httpx.TimeoutException) else "unreachable"
        return Result(hit.data, err, hit.fetched_at, stale=True) if hit else Result(error=err)
    if status == 304 and hit:
        with _lock:
            _cache[url] = _Entry(hit.data, hit.etag, t)
        return Result(hit.data, None, t)
    if status != 200:
        err = _describe(status, headers)
        return Result(hit.data, err, hit.fetched_at, stale=True) if hit else Result(error=err)
    with _lock:
        _cache[url] = _Entry(body, headers.get("etag"), t)
    return Result(body, None, t)


def get_many(urls: list[str], *, refresh: bool = False) -> dict[str, Result]:
    """Several URLs at once, in parallel (so the slowest bounds the wait)."""
    unique = list(dict.fromkeys(urls))
    with ThreadPoolExecutor(max_workers=min(8, max(1, len(unique)))) as pool:
        results = list(pool.map(lambda u: get(u, refresh=refresh), unique))
    return dict(zip(unique, results))


def github(path: str) -> str:
    return f"{GITHUB_API}/{path.lstrip('/')}"


def pypi(package: str) -> str:
    return f"{PYPI}/{package}/json"


def github_authenticated() -> bool:
    return bool((os.environ.get("GITHUB_TOKEN") or "").strip())
