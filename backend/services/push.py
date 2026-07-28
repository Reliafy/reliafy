"""Operator push notifications (Pushover).

For alerts the operator wants on their phone within seconds — a new signup, a
failed payment — where email is both slower and easier to miss. This is
**operator-only**: anything addressed to a *user* (team invites, share
notifications) stays on email in ``backend.services.email``, because you can't
push to someone who never gave you a device key.

Configured entirely by env vars; absent, every send is a logged no-op, so
self-hosted and dev instances need nothing:

    PUSHOVER_TOKEN   the application token from pushover.net
    PUSHOVER_USER    the operator's user or group key

Delivery runs on a daemon thread with a short timeout: a notification must
never add latency to — or fail — the request that triggered it.
"""

from __future__ import annotations

import logging
import threading

import httpx

from backend import config

logger = logging.getLogger(__name__)

_API = "https://api.pushover.net/1/messages.json"
_TIMEOUT = 10.0


def enabled() -> bool:
    return bool(config.PUSHOVER_TOKEN and config.PUSHOVER_USER)


def _deliver(payload: dict) -> None:
    try:
        r = httpx.post(_API, data=payload, timeout=_TIMEOUT)
        if r.status_code >= 400:
            # Pushover returns the reason in the body; log it, never the token.
            logger.warning("pushover rejected the message (%s): %s",
                           r.status_code, r.text[:200])
        else:
            logger.info("pushover sent: %s", payload.get("title"))
    except Exception:  # noqa: BLE001 - a notification must never escalate
        logger.exception("pushover delivery failed")


def send(title: str, message: str, url: str | None = None,
         url_title: str | None = None, priority: int = 0) -> bool:
    """Queue a push to the operator. Returns whether it was queued at all."""
    if not enabled():
        logger.info("push skipped (PUSHOVER_TOKEN/USER unset): %s", title)
        return False
    payload = {
        "token": config.PUSHOVER_TOKEN,
        "user": config.PUSHOVER_USER,
        "title": title,
        "message": message,
        "priority": priority,
    }
    if url:
        payload["url"] = url
        if url_title:
            payload["url_title"] = url_title
    threading.Thread(target=_deliver, args=(payload,), daemon=True).start()
    return True
