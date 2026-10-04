"""Fixed-window request limits kept in Mongo, so they hold across instances.

One atomic upsert per counted request: ``{_id: "<key>:<window>", n}``; a TTL
index on ``expires_at`` drops finished windows. Keys carry their own prefix
(``"oauth-register:ip:…"``, ``"invite:user:…"``) so limits never collide.
"""

from __future__ import annotations

import hashlib
import time
from datetime import datetime, timezone

from pymongo import ReturnDocument

from backend import config


def ip_key(scope: str, ip: str) -> str:
    """A rate-limit key for a client IP: a salted hash, never the IP itself."""
    digest = hashlib.sha256(f"{config.METRICS_SALT}|{scope}|{ip}".encode()).hexdigest()[:24]
    return f"{scope}:ip:{digest}"


def consume(db, key: str, limit: int, window_seconds: int) -> bool:
    """Count one request against ``key`` in the current window; False once
    the window's ``limit`` is used up."""
    bucket = int(time.time() // window_seconds)
    doc = db.rate_limits.find_one_and_update(
        {"_id": f"{key}:{window_seconds}:{bucket}"},
        {
            "$inc": {"n": 1},
            "$setOnInsert": {
                "expires_at": datetime.fromtimestamp((bucket + 1) * window_seconds, timezone.utc)
            },
        },
        upsert=True,
        return_document=ReturnDocument.AFTER,
    )
    return int(doc["n"]) <= limit


def retry_after(window_seconds: int) -> int:
    """Seconds until the current window ends."""
    return int(window_seconds - time.time() % window_seconds) + 1
