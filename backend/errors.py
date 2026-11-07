"""What an error response may say.

Most errors the app answers with are refusals it raises on purpose (a fit that
can't run on this data, a name that's too long, a limit reached): their text
is written for the person using the app and goes back as is. Anything else (a
bug, a library failing somewhere unexpected) is logged in full here, and the
response says only that something went wrong, with a reference to find the
log entry by.

    try:
        ...
    except FitError as exc:
        return JSONResponse(status_code=422, content={"detail": client_message(exc)})
"""
from __future__ import annotations

import logging
import uuid

logger = logging.getLogger("reliafy.errors")

GENERIC = "Something went wrong on our side; it has been logged"
#: Longer than any message the app writes; a longer one isn't meant for a person.
MAX_MESSAGE = 2000

# Library exceptions whose text is a refusal about the input: SurPyval and
# RePyability raise ValueError for data or a setting they can't use, and
# NotImplementedError for an arrangement they don't support.
_USER_FACING = (ValueError, NotImplementedError)
_INTERNAL_MARKERS = ("Traceback (most recent call last)", 'File "')


def user_facing(exc: BaseException, also: tuple = ()) -> bool:
    """Whether ``exc``'s text is written for the user: one of the app's own
    exception classes (defined under ``backend``), a library's refusal of the
    input (ValueError, NotImplementedError), or one of ``also``."""
    if isinstance(exc, _USER_FACING) or (also and isinstance(exc, also)):
        return True
    return any((getattr(k, "__module__", "") or "").startswith("backend.") for k in type(exc).__mro__)


def _text(exc: BaseException) -> str:
    """The message an exception was raised with ('' for none)."""
    first = exc.args[0] if exc.args else ""
    if not isinstance(first, str):
        return ""
    text = first.strip()
    if len(text) > MAX_MESSAGE or any(m in text for m in _INTERNAL_MARKERS):
        return ""
    return text


def log_internal(exc: BaseException, where: str = "") -> str:
    """Log ``exc`` with its traceback; the reference id the log line carries."""
    ref = uuid.uuid4().hex[:10]
    logger.error("Unexpected error%s (ref %s)", f" in {where}" if where else "", ref, exc_info=exc)
    return ref


def client_message(exc: BaseException, fallback: str | None = None, *, also: tuple = (), where: str = "") -> str:
    """The text an error response (or a note in a result) may carry for
    ``exc``: its own message when it's written for the user (see
    :func:`user_facing`), otherwise ``fallback`` or a generic sentence with a
    reference, after logging the exception in full."""
    if user_facing(exc, also):
        text = _text(exc)
        if text:
            return text
        if fallback:
            return fallback
    ref = log_internal(exc, where)
    return fallback or f"{GENERIC} (reference {ref})."


def client_reason(exc: BaseException, fallback: str | None = None, *, also: tuple = (), where: str = "") -> str:
    """:func:`client_message` without its closing full stop, for a reason
    quoted inside a sentence ("No confidence bounds: <reason>.")."""
    return client_message(exc, fallback, also=also, where=where).rstrip(".")
