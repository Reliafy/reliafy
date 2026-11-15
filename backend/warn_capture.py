"""Collect and quieten library warnings for one piece of work at a time.

``warnings.catch_warnings`` swaps process-wide state (the filter list and the
function that shows a warning). Sync endpoints run in a thread pool, so two
requests inside ``catch_warnings`` at once see each other's filters, and a
``record=True`` block records whatever any thread warns while it is open.

This module keeps that state per execution context instead:

- :func:`collect_warnings` yields a list that receives the warnings raised in
  the current context (``.message``, ``.category``, ``.filename``,
  ``.lineno``: :class:`warnings.WarningMessage` objects), every time, not once
  per place.
- :func:`ignore_warnings` drops warnings (by category, optionally by message)
  in the current context only.

How: one hook replaces ``warnings._showwarnmsg`` (the function every warning
that passes the filters goes through, from Python or C code), and one
``"always"`` filter is kept at the front of ``warnings.filters`` so every
warning reaches the hook. The hook applies the current context's rules first;
when none match it applies the rest of the global filter list itself
(``ignore``, ``error``, ``default``/``once``/``module`` de-duplication), so
code outside these helpers, and the test suite's ``filterwarnings`` settings,
behave as before.

Context travels with :mod:`contextvars`: ``run_in_threadpool`` and
``anyio.to_thread`` copy it into the worker thread. Code that hands work to
its own thread or executor inside one of these blocks must submit
``contextvars.copy_context().run`` for the warnings to be collected.

A ``warnings.catch_warnings(record=True)`` opened *inside* one of these blocks
(a library collecting its own warnings) keeps getting the warnings it asked
for: once the show function has changed since the block began, warnings go to
it rather than to this block's list.
"""
from __future__ import annotations

import contextvars
import re
import sys
import threading
import warnings
from contextlib import contextmanager
from typing import Iterator, NamedTuple, Optional, Pattern, Tuple, Type

# Matches every message; its identity marks our entry in ``warnings.filters``.
_SENTINEL_RE = re.compile("")
_SENTINEL = ("always", _SENTINEL_RE, Warning, None, 0)


class _Rule(NamedTuple):
    action: str
    category: Type[Warning]
    message: Optional[Pattern[str]]

    def matches(self, msg) -> bool:
        if not issubclass(msg.category, self.category):
            return False
        return self.message is None or bool(self.message.match(str(msg.message)))


class _Frame(NamedTuple):
    rules: Tuple[_Rule, ...]
    sink: Optional[list]
    # The show functions current when the block began: a different one at
    # warning time means a ``catch_warnings(record=True)`` opened since.
    impl: object
    showwarning: object


_FRAMES: contextvars.ContextVar[Tuple[_Frame, ...]] = contextvars.ContextVar(
    "reliafy_warning_frames", default=())

_lock = threading.Lock()
_original_showwarnmsg = None
# Set while a warning is being handed on to ``_original_showwarnmsg``.
_forwarding = threading.local()
# De-duplication for "default"/"once"/"module" outside any block, reset when the
# filter list is replaced (as ``catch_warnings`` does).
_seen_for: Optional[int] = None
_seen: set = set()


def _rule(action: str, category, message) -> _Rule:
    pattern = re.compile(message, re.I) if isinstance(message, str) else message
    return _Rule(action, category, pattern)


def _module_name(filename: str) -> str:
    """The warning's module, for module-specific global filters."""
    frame = sys._getframe(2)
    while frame is not None:
        if frame.f_code.co_filename == filename:
            name = frame.f_globals.get("__name__")
            if isinstance(name, str):
                return name
            break
        frame = frame.f_back
    module = filename or "<unknown>"
    return module[:-3] if module.lower().endswith(".py") else module


def _global_action(msg) -> str:
    text = str(msg.message)
    module = None
    for entry in list(warnings.filters):
        if entry[1] is _SENTINEL_RE:
            continue
        action, mpat, cat, mod, ln = entry
        if mpat is not None:
            if isinstance(mpat, str):
                mpat = re.compile(mpat, re.I)
            if not mpat.match(text):
                continue
        if not issubclass(msg.category, cat):
            continue
        if mod is not None:
            if module is None:
                module = _module_name(msg.filename)
            if isinstance(mod, str):
                mod = re.compile(mod)
            if not mod.match(module):
                continue
        if ln and ln != msg.lineno:
            continue
        return action
    return getattr(warnings, "defaultaction", "default")


def _first_time(action: str, msg) -> bool:
    global _seen_for
    if action == "once":
        key = (str(msg.message), msg.category)
    elif action == "module":
        key = (str(msg.message), msg.category, msg.filename)
    else:
        key = (str(msg.message), msg.category, msg.filename, msg.lineno)
    with _lock:
        if _seen_for != id(warnings.filters):
            _seen_for = id(warnings.filters)
            _seen.clear()
        if key in _seen:
            return False
        _seen.add(key)
    return True


def _raise(msg):
    if isinstance(msg.message, Warning):
        raise msg.message
    raise msg.category(msg.message)


def _display(msg) -> None:
    """Show ``msg`` as the standard library's ``_showwarnmsg`` does: through a
    replaced ``warnings.showwarning`` if there is one, else the current
    ``_showwarnmsg_impl`` (a ``catch_warnings(record=True)`` list included)."""
    shown = warnings.showwarning
    if shown is not getattr(warnings, "_showwarning_orig", shown):
        shown(msg.message, msg.category, msg.filename, msg.lineno, msg.file, msg.line)
        return
    warnings._showwarnmsg_impl(msg)


def _forward(msg) -> None:
    """Hand ``msg`` (already judged by the filters) to the hook we replaced.

    Another library's hook installed after ours may have wrapped ours, and
    ours it in turn (SurPyval 0.27's thread-local warning collector does,
    the first time one of its collecting blocks runs): the chain then comes
    back to :func:`_show`, which would loop and lose the warning. A warning
    that comes back is shown directly instead."""
    if getattr(_forwarding, "on", False) or _original_showwarnmsg is None:
        _display(msg)
        return
    _forwarding.on = True
    try:
        _original_showwarnmsg(msg)
    finally:
        _forwarding.on = False


def _show(msg) -> None:
    if getattr(_forwarding, "on", False):
        # Back from the hook we forwarded to: it has had its say.
        _display(msg)
        return
    frames = _FRAMES.get()
    if frames:
        inner = frames[-1]
        if (getattr(warnings, "_showwarnmsg_impl", None) is not inner.impl
                or getattr(warnings, "showwarning", None) is not inner.showwarning):
            # A ``catch_warnings(record=True)`` opened inside this block: its
            # filters have already been applied; it gets the warning.
            _forward(msg)
            return
    action = None
    for frame in reversed(frames):
        for rule in frame.rules:
            if rule.matches(msg):
                action = rule.action
                break
        if action is not None:
            break
    if action is None:
        action = _global_action(msg)
    if action == "ignore":
        return
    if action == "error":
        _raise(msg)
    for frame in reversed(frames):
        if frame.sink is not None:
            frame.sink.append(msg)
            return
    if action in ("default", "once", "module") and not _first_time(action, msg):
        return
    _forward(msg)


def _install() -> None:
    """Route every warning through :func:`_show` (idempotent; re-checked on each
    block, as ``catch_warnings`` elsewhere replaces the filter list)."""
    global _original_showwarnmsg
    filters = warnings.filters
    if warnings._showwarnmsg is _show and filters and filters[0][1] is _SENTINEL_RE:
        return
    with _lock:
        if warnings._showwarnmsg is not _show:
            _original_showwarnmsg = warnings._showwarnmsg
            warnings._showwarnmsg = _show
        filters = warnings.filters
        if not (filters and filters[0][1] is _SENTINEL_RE):
            filters[:] = [_SENTINEL] + [f for f in filters if f[1] is not _SENTINEL_RE]
            warnings._filters_mutated()


@contextmanager
def _frame(rules, sink) -> Iterator[None]:
    _install()
    frame = _Frame(tuple(rules), sink, getattr(warnings, "_showwarnmsg_impl", None),
                   getattr(warnings, "showwarning", None))
    token = _FRAMES.set(_FRAMES.get() + (frame,))
    try:
        yield
    finally:
        _FRAMES.reset(token)


@contextmanager
def collect_warnings(category: Type[Warning] = Warning, message: Optional[str] = None) -> Iterator[list]:
    """Collect the warnings raised in this context, every time.

    Like ``catch_warnings(record=True)`` with ``filterwarnings("always",
    message, category)``, for this context only. Warnings the rule doesn't
    name follow the global filters and, unless those ignore them, are
    collected too. An enclosing or nested :func:`ignore_warnings` still drops
    what it names."""
    caught: list = []
    with _frame([_rule("always", category, message)], caught):
        yield caught


@contextmanager
def ignore_warnings(*categories: Type[Warning], message: Optional[str] = None) -> Iterator[None]:
    """Drop warnings of these categories (all, when none are named), and only
    those whose message matches ``message`` (a regular expression matched at
    the start, ignoring case) when it is given, in this context only."""
    with _frame([_rule("ignore", c, message) for c in (categories or (Warning,))], None):
        yield

