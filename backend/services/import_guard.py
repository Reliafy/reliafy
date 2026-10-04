"""Limits around reading uploaded files: one import (or inspection) at a time
per user, and a wall-clock budget for each.

Every file importer (RBD files, Excel workbooks, RCM worksheets) runs inside
:func:`guard`:

* **One at a time per user.** A lease document in ``import_locks`` (keyed by
  the user id, atomic insert / takeover of an expired lease) works across
  instances. A second request waits up to :data:`WAIT_SECONDS` for the first
  to finish (the web app can overlap a preview and an import), then is
  refused with :class:`ImportBusy`. The lease expires on its own after
  :data:`LEASE_SECONDS`, so an instance that died mid-import never blocks the
  user for long. Re-entrant: a guarded call inside a guarded call (an import
  that inspects first) just runs.
* **A wall-clock budget.** :func:`check` raises :class:`ImportBudgetExceeded`
  once :data:`BUDGET_SECONDS` have passed; the parsers call it in their loops
  (rows, statements, gates, blocks). Outside :func:`guard` it does nothing.

The parsers themselves cap what they build (rows, columns, merged ranges,
blocks, statement length, expression size), so the budget is a backstop, not
the main limit. It runs in-process: a worker process per parse would need a
fork of a threaded server holding database clients, or a fresh interpreter
importing pandas / openpyxl / numpy per request, for parsers that already
bound their work.
"""

from __future__ import annotations

import contextvars
import time
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from typing import Iterator, Optional

BUDGET_SECONDS = 120.0
WAIT_SECONDS = 15.0
LEASE_SECONDS = BUDGET_SECONDS + 60.0
_POLL_SECONDS = 0.25

_deadline: contextvars.ContextVar[Optional[float]] = contextvars.ContextVar("import_deadline", default=None)
_holder: contextvars.ContextVar[Optional[str]] = contextvars.ContextVar("import_holder", default=None)


class ImportBusy(ValueError):
    """The user already has an import running (user-facing text)."""


class ImportBudgetExceeded(ValueError):
    """Reading the file took longer than the budget (user-facing text)."""


BUSY_MESSAGE = ("Another import is still running for your account. Wait for it to finish, "
                "then try again.")
BUDGET_MESSAGE = ("This file is taking too long to read. Export just the part you need "
                  "(one diagram, one sheet) and import that.")


def ensure_indexes(db) -> None:
    """TTL: Mongo drops a lease once it has expired."""
    db.import_locks.create_index([("until", 1)], expireAfterSeconds=0)


def check() -> None:
    """Raise :class:`ImportBudgetExceeded` once the current import's budget
    has run out (no-op outside :func:`guard`)."""
    deadline = _deadline.get()
    if deadline is not None and time.monotonic() > deadline:
        raise ImportBudgetExceeded(BUDGET_MESSAGE)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _try_acquire(db, uid: str, nonce: str) -> bool:
    from pymongo.errors import DuplicateKeyError

    now = _now()
    until = now + timedelta(seconds=LEASE_SECONDS)
    try:
        db.import_locks.insert_one({"_id": uid, "nonce": nonce, "until": until})
        return True
    except DuplicateKeyError:
        pass
    taken = db.import_locks.find_one_and_update(
        {"_id": uid, "until": {"$lt": now}},
        {"$set": {"nonce": nonce, "until": until}},
    )
    return taken is not None


def _release(db, uid: str, nonce: str) -> None:
    db.import_locks.delete_one({"_id": uid, "nonce": nonce})


@contextmanager
def guard(db, uid: Optional[str], wait: Optional[float] = None,
          budget: Optional[float] = None) -> Iterator[None]:
    """Hold the user's import slot and start the budget for the block.

    Raises :class:`ImportBusy` when the slot stays taken for ``wait`` seconds
    (default :data:`WAIT_SECONDS`)."""
    if _holder.get() is not None:  # already inside a guarded import
        yield
        return
    key = str(uid or "")
    nonce = uuid.uuid4().hex
    wait = WAIT_SECONDS if wait is None else wait
    give_up = time.monotonic() + max(0.0, wait)
    while not _try_acquire(db, key, nonce):
        if time.monotonic() >= give_up:
            raise ImportBusy(BUSY_MESSAGE)
        time.sleep(_POLL_SECONDS)
    held = _holder.set(key)
    limit = _deadline.set(time.monotonic() + (BUDGET_SECONDS if budget is None else budget))
    try:
        yield
    finally:
        _deadline.reset(limit)
        _holder.reset(held)
        _release(db, key, nonce)
