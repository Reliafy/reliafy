"""Generic method labels in results, never internal solver or engine names.

A result says how it was computed by what the user chose: a fit by its
method ("MLE", "MPP", ...), a simulation as "simulation". It never names the
solver or engine the libraries happened to use for it. Those identifiers are
implementation details that can change between versions and deployments,
and a result shouldn't change with them.

* Fits. SurPyval records the solver behind a fit as ``model.optimizer``.
  :func:`note_fit` replaces it with the fit method's label as soon as the
  model is fitted, and the fit entry points (decorated with
  :func:`hides_solver_names`) keep the original identifier out of everything
  they return, warnings and notes included.
* Simulations. RePyability's ``analysis_routes()`` can name the engine a
  simulation would run on (``AnalysisRoute.engine``). :func:`route_reason`
  gives a route's reason without it, and :func:`hide_engine_names` and
  :func:`generic_engine_fields` keep engine identifiers out of an analysis
  payload, a saved one included.

None of this touches a number: only labels and text.
"""

from __future__ import annotations

import functools
import re
from contextvars import ContextVar
from typing import Any, Callable, Iterable, Optional

# The method a fit reports when its model doesn't say (SurPyval's default).
DEFAULT_FIT_METHOD = "MLE"
# What a simulation engine is reported as.
GENERIC_ENGINE = "simulation"
# Engine names that are also ordinary words: left alone in text (the
# ``engine`` fields themselves are still made generic).
_ORDINARY_WORDS = frozenset({"python", "auto"})
# Payload keys that would carry an internal identifier: ``None`` drops the key.
_SOLVER_KEYS = {"optimizer": None, "optimiser": None}
_ENGINE_KEYS = {"engine": GENERIC_ENGINE, "engine_reason": None}

# The solver identifiers seen (identifier -> generic label) during the
# current call of a function decorated with ``hides_solver_names``.
_seen: ContextVar[Optional[dict]] = ContextVar("reliafy_solver_names", default=None)


# ---- Fits ---------------------------------------------------------------------

def fit_method_label(model: Any, how: Optional[str] = None) -> str:
    """The stable label of a fit: the method chosen (``how``, else the
    model's ``method``), e.g. "MLE"; :data:`DEFAULT_FIT_METHOD` if neither
    says."""
    for value in (how, getattr(model, "method", None)):
        if isinstance(value, str) and value.strip():
            return value.strip()
    return DEFAULT_FIT_METHOD


def _with_parts(model: Any) -> Iterable[Any]:
    """The model and the fitted models it holds directly (a mixture's
    components, an ALT model's distribution, ...)."""
    yield model
    try:
        values = list(vars(model).values())
    except TypeError:
        return
    for value in values:
        items = value.values() if isinstance(value, dict) else value if isinstance(value, (list, tuple)) else (value,)
        for item in items:
            try:
                fitted = item is not model and isinstance(getattr(item, "optimizer", None), str)
            except Exception:  # noqa: BLE001 - a property that raises: not a fitted model
                fitted = False
            if fitted:
                yield item


def note_fit(model: Any, how: Optional[str] = None) -> Any:
    """Report a freshly fitted model's solver as the generic label of its fit
    method (``model.optimizer``, and its parts'), remembering the identifier
    it replaced so the enclosing :func:`hides_solver_names` call keeps it out
    of the result. Returns the model."""
    if model is None:
        return model
    seen = _seen.get()
    for part in _with_parts(model):
        name = getattr(part, "optimizer", None)
        if not isinstance(name, str):
            continue
        label = fit_method_label(part, how if part is model else None)
        if name != label:
            if seen is not None and name.strip():
                seen[name] = label
            try:
                part.optimizer = label
            except (AttributeError, TypeError):  # read-only: the result is still scrubbed
                pass
    return model


def hides_solver_names(fn: Callable) -> Callable:
    """Decorate a fit entry point: whatever it returns carries no solver
    identifier that :func:`note_fit` saw during the call (replaced by the fit
    method's label) and no ``optimizer`` field."""

    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        names: dict = {}
        token = _seen.set(names)
        try:
            out = fn(*args, **kwargs)
        finally:
            _seen.reset(token)
        return scrub(out, names, _SOLVER_KEYS)

    return wrapper


# ---- Simulation engines ------------------------------------------------------

def engine_names(*extra: Any) -> list[str]:
    """The engine identifiers to keep out of text: those registered with
    RePyability by other packages, plus ``extra``; longest first, without
    the ones that are ordinary words."""
    names = {n for n in extra if isinstance(n, str)}
    try:
        from repyability.rbd import engines

        names.update(n for n in engines.registered() if isinstance(n, str))
    except Exception:  # noqa: BLE001 - no registry: only the names given
        pass
    return sorted((n for n in names if n.strip() and n.strip().lower() not in _ORDINARY_WORDS),
                  key=len, reverse=True)


def _pattern(name: str) -> re.Pattern:
    return re.compile(r"(?<![\w-])" + re.escape(name) + r"(?![\w-])")


def _replace_names(text: str, names: dict) -> str:
    for name in sorted(names, key=len, reverse=True):
        if name in text:
            text = _pattern(name).sub(names[name], text)
    return text


def hide_engine_names(text: Any, *extra: Any) -> Any:
    """``text`` with any engine identifier (see :func:`engine_names`)
    replaced by :data:`GENERIC_ENGINE`; anything but a string as is."""
    if not isinstance(text, str):
        return text
    return _replace_names(text, {n: GENERIC_ENGINE for n in engine_names(*extra)})


def route_reason(route: Any) -> str:
    """A RePyability ``AnalysisRoute``'s reason, without the name of the
    engine it would simulate on."""
    return hide_engine_names(getattr(route, "reason", "") or "", getattr(route, "engine", None))


def generic_engine_fields(payload: Any) -> Any:
    """An analysis payload with any ``engine`` field reported as
    :data:`GENERIC_ENGINE`, no ``engine_reason`` and no registered engine's
    name in its text (a saved result's too)."""
    return scrub(payload, {n: GENERIC_ENGINE for n in engine_names()}, _ENGINE_KEYS)


# ---- Both ---------------------------------------------------------------------

def scrub(value: Any, names: dict, keys: Optional[dict] = None) -> Any:
    """``value`` (JSON-like, or a tuple of them) with each identifier in
    ``names`` replaced by its label in every string, and each key in
    ``keys`` replaced by its value there (dropped where that is None).
    Numbers and everything else are returned as they are."""
    keys = keys or {}
    if not names and not keys:
        return value

    def walk(v: Any) -> Any:
        if isinstance(v, str):
            return _replace_names(v, names) if names else v
        if isinstance(v, dict):
            out = {}
            for k, item in v.items():
                if k in keys:
                    if keys[k] is not None:
                        out[k] = keys[k]
                    continue
                out[k] = walk(item)
            return out
        if isinstance(v, list):
            return [walk(item) for item in v]
        if isinstance(v, tuple):
            return tuple(walk(item) for item in v)
        return v

    return walk(value)
