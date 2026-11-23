"""Reads worked out from the graph, kept per process until the graph changes.

Some reads walk most of a workspace's graph (the RCM of every position, a
position's running clock from its duty plan) and are asked for on every load
of Home and the Explorer. The graph changes only by events, so such a read is
the same until the store's :meth:`read_token` moves: the applied sequence (any
organisation's event) and a generation bumped by every rebuild. A read cached
under a token is never used once the token has moved.

Only reads of the graph alone (and of things given in the key, such as the
workspace's "today") may go through here: nothing kept in MongoDB, nothing from
the clock. Each process (each Cloud Run instance) keeps its own.
"""

from __future__ import annotations

import contextvars
import copy
import threading
from collections import OrderedDict
from typing import Callable, Hashable

SIZE = 256


class ReadCache:
    def __init__(self, size: int = SIZE):
        self._d: OrderedDict = OrderedDict()
        self._lock = threading.Lock()
        self.size = size
        self.hits = 0
        self.misses = 0

    def get(self, key):
        with self._lock:
            if key not in self._d:
                return _MISS
            self._d.move_to_end(key)
            return self._d[key]

    def put(self, key, value) -> None:
        with self._lock:
            self._d[key] = value
            self._d.move_to_end(key)
            while len(self._d) > self.size:
                self._d.popitem(last=False)

    def clear(self) -> None:
        with self._lock:
            self._d.clear()


_MISS = object()

# The time-series reads a cached computation made (``series=True``): each as
# (what, org, point, days) with what it found: a point's latest reading, or the
# fingerprint of its history (series.py ``fingerprint``). A kept answer is used only
# while every one of those is still the same.
_SERIES_READS: contextvars.ContextVar = contextvars.ContextVar("read_cache_series", default=None)


def series_recording() -> bool:
    return _SERIES_READS.get() is not None


def note_series_read(read: tuple, found) -> None:
    """Called by the series stores on every read (series.py)."""
    reads = _SERIES_READS.get()
    if reads is not None:
        reads.append((read, found))


def _series_still(store, reads) -> bool:
    series = getattr(store, "series", None)
    if series is None:
        return False
    token = _SERIES_READS.set(None)
    try:
        for (what, org, point, days), found in reads:
            now = series.latest(org, point) if what == "latest" else series.fingerprint(org, point, days)
            if now != found:
                return False
        return True
    finally:
        _SERIES_READS.reset(token)


def cached(store, key: Hashable, compute: Callable, *, frozen: bool = False, series: bool = False):
    """``compute()``, or what it gave last time for ``key`` on this store while its
    graph hasn't changed. A store without a token (the Neo4j store) always
    computes. Unless ``frozen`` (an immutable value), the cache keeps its own copy
    and each caller gets one of its own, so nobody can change what others read.
    A value is kept only if the graph didn't change while it was worked out.
    ``series``: the computation may read the time series too (automated readings):
    what it read of them is kept with it and checked on every use."""
    token_of = getattr(store, "read_token", None)
    cache = getattr(store, "read_cache", None)
    token = token_of() if token_of is not None and cache is not None else None
    if token is None:
        return compute()
    full = (token, key)
    hit = cache.get(full)
    if hit is not _MISS:
        value, reads = hit
        if not reads or _series_still(store, reads):
            cache.hits += 1
            return value if frozen else copy.deepcopy(value)
    cache.misses += 1
    reads: list | None = [] if series else None
    recorder = _SERIES_READS.set(reads)
    try:
        value = compute()
    finally:
        _SERIES_READS.reset(recorder)
    if token_of() == token:
        cache.put(full, (value if frozen else copy.deepcopy(value), tuple(reads or ())))
    return value
