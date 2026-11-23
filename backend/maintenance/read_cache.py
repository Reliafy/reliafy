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


def cached(store, key: Hashable, compute: Callable, *, frozen: bool = False):
    """``compute()``, or what it gave last time for ``key`` on this store while its
    graph hasn't changed. A store without a token (the Neo4j store) always
    computes. Unless ``frozen`` (an immutable value), the cache keeps its own copy
    and each caller gets one of its own, so nobody can change what others read.
    A value is kept only if the graph didn't change while it was worked out."""
    token_of = getattr(store, "read_token", None)
    cache = getattr(store, "read_cache", None)
    token = token_of() if token_of is not None and cache is not None else None
    if token is None:
        return compute()
    full = (token, key)
    hit = cache.get(full)
    if hit is not _MISS:
        cache.hits += 1
        return hit if frozen else copy.deepcopy(hit)
    cache.misses += 1
    value = compute()
    if token_of() == token:
        cache.put(full, value if frozen else copy.deepcopy(value))
    return value
