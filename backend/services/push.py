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
import time
import traceback

import httpx

from backend import config

logger = logging.getLogger(__name__)

_API = "https://api.pushover.net/1/messages.json"
_TIMEOUT = 10.0

# Error alerting: throttles, because the failure mode of crash alerts is a bad
# deploy emptying its stack traces into someone's pocket. Two limits — the same
# fault is only reported once per window, and there is a hard ceiling per hour
# regardless of how many *distinct* faults appear.
_REPEAT_WINDOW = 30 * 60      # same fault: at most once per 30 minutes
_HOURLY_CAP = 8               # distinct faults: at most 8 pushes per hour
_seen: dict[str, float] = {}
_recent: list[float] = []
_lock = threading.Lock()


def _expected_types() -> tuple[type, ...]:
    """Exceptions that mean "the user gave us something we can't use".

    These are the product working correctly — a censored-only dataset, an
    invalid RBD, a bad fit option — and they already produce a 422 with a
    readable message. Alerting on them would bury the real crashes in noise,
    which is the standard way an alerting channel gets ignored.

    Imported lazily: this module is deliberately cheap to import.
    """
    from backend.fitting import FitError
    from backend.services.fleet import FleetValidationError, FleetNotFound
    from backend.services.rbd_analysis import AnalysisError
    from backend.services.strategy import StrategyError

    return (FitError, AnalysisError, StrategyError,
            FleetValidationError, FleetNotFound)


_EXPECTED_CACHE: tuple[type, ...] | None = None


def _is_expected(exc: BaseException) -> bool:
    global _EXPECTED_CACHE
    if _EXPECTED_CACHE is None:
        try:
            _EXPECTED_CACHE = _expected_types()
        except Exception:  # noqa: BLE001 - never let this break logging
            return False
    return isinstance(exc, _EXPECTED_CACHE)


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


def _should_alert(key: str) -> tuple[bool, bool]:
    """(send it?, is this the last one before we go quiet?) for a fault key."""
    now = time.monotonic()
    with _lock:
        last = _seen.get(key)
        if last is not None and now - last < _REPEAT_WINDOW:
            return False, False
        _recent[:] = [t for t in _recent if now - t < 3600]
        if len(_recent) >= _HOURLY_CAP:
            return False, False
        _seen[key] = now
        _recent.append(now)
        return True, len(_recent) == _HOURLY_CAP


def alert_error(where: str, exc: BaseException | None, detail: str = "") -> bool:
    """Push an operator alert about a crash. Never raises, always throttled.

    Deliberately carries the fault, not the data: exception type, where it
    happened, and the log message — enough to know something broke and go and
    read the real traceback. The traceback itself, and anything the user
    uploaded, stays in Cloud Logging.
    """
    kind = type(exc).__name__ if exc is not None else "error"
    key = f"{where}:{kind}"
    ok, last_before_quiet = _should_alert(key)
    if not ok:
        return False

    line = ""
    if exc is not None:
        tb = traceback.extract_tb(exc.__traceback__)
        if tb:
            frame = tb[-1]
            line = f"\n{frame.filename.split('/')[-1]}:{frame.lineno} in {frame.name}()"
    body = f"{kind}: {str(exc)[:160]}" if exc is not None else detail[:160]
    if detail and exc is not None:
        body = f"{detail[:100]}\n{body}"
    if last_before_quiet:
        body += "\n\n(alert limit reached — further alerts suppressed for an hour)"

    return send(f"Reliafy error · {where}", body + line, priority=1)


class PushErrorHandler(logging.Handler):
    """Routes logger.exception(...) calls to an operator push.

    Attached to the root logger rather than wired into each call site: there
    are two dozen of those and any new one should be covered automatically.
    Only records carrying exception info are alerted — a plain logger.error is
    usually a handled condition, not a crash.
    """

    def emit(self, record: logging.LogRecord) -> None:
        try:
            if not record.exc_info:
                return
            exc = record.exc_info[1]
            if exc is None or _is_expected(exc):
                return
            alert_error(record.name.replace("backend.", ""), exc, record.getMessage())
        except Exception:  # noqa: BLE001 - alerting must never break logging
            pass


def install_error_alerts() -> bool:
    """Attach the handler once. Returns whether alerting is now active."""
    if not (enabled() and config.PUSH_ERROR_ALERTS):
        return False
    root = logging.getLogger()
    if any(isinstance(h, PushErrorHandler) for h in root.handlers):
        return True
    handler = PushErrorHandler(level=logging.ERROR)
    root.addHandler(handler)
    logger.info("operator error alerts enabled (Pushover)")
    return True
