"""A small in-memory sliding-window rate limiter.

Per process (each Cloud Run instance counts on its own): a ceiling on how fast
one key can call an endpoint, not accounting. The number of keys tracked is
bounded, oldest first out, so the limiter's own memory can't grow without limit.
"""

from __future__ import annotations

import threading
import time
from collections import OrderedDict, deque


class SlidingWindowLimiter:
    def __init__(self, limit: int, window_seconds: float = 60.0, max_keys: int = 20_000):
        self.limit = limit
        self.window = window_seconds
        self.max_keys = max_keys
        self._hits: OrderedDict[str, deque] = OrderedDict()
        self._lock = threading.Lock()

    def allow(self, key: str) -> bool:
        """Count one call for ``key``; False once the window's limit is used."""
        now = time.monotonic()
        with self._lock:
            hits = self._hits.get(key)
            if hits is None:
                hits = self._hits[key] = deque()
            else:
                self._hits.move_to_end(key)
            while hits and now - hits[0] > self.window:
                hits.popleft()
            if len(hits) >= self.limit:
                return False
            hits.append(now)
            while len(self._hits) > self.max_keys:
                self._hits.popitem(last=False)
            return True

    def reset(self) -> None:
        with self._lock:
            self._hits.clear()
