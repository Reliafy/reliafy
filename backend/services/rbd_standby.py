"""k-of-n standby (#84): a standby block with ``k`` units running and its
spares idle, e.g. a 2-of-3 duty/standby pump train.

The block holds ``k`` (the units that must run, by default 1) beside its
``spares``; it has ``k + spares`` units. RePyability's ``StandbyModel(units,
k)`` and a repairable diagram's standby group (``"standby": {"units", "k"}``)
take any ``k``. What RePyability 0.13 works out, and so what Reliafy offers:

* **Cold** spares (not ageing while idle), any ``k``: exactly for identical
  exponential units (an Erlang life), numerically otherwise — for identical
  units of any life, and for a spare model of its own with ``k = 2``. With a
  spare model of its own and ``k >= 3`` it has no exact reliability (only
  simulated lives), so Reliafy refuses it, saying so.
* **Warm** spares with ``k >= 2`` have no exact reliability either: refused,
  saying so. (One running, they're numerical, as before.)
* **Hot** spares: exactly an ordinary k-out-of-n of the units.
* **Imperfect switching** (a spare that may fail to start) applies to cold
  standby only — RePyability refuses it with warm or hot spares — so a
  start-success probability on a warm or hot block is left out, with a
  warning.

In a repairable diagram the group's units are identical (as before); its
exact long-run values need exponential lives and repairs (RePyability's
Markov chain), otherwise it is simulated, whatever ``k``.
"""

from __future__ import annotations

from typing import Optional

from backend.services.rbd_analysis import AnalysisError

MAX_UNITS = 1000


class StandbyLimit(AnalysisError):
    """A non-repairable standby arrangement RePyability can't work out
    exactly (a repairable diagram's standby group isn't one)."""

    nonrepairable_only = True


def operating(data: dict, label: str) -> int:
    """How many of the block's units must run (``k``), by default 1."""
    raw = data.get("k")
    if raw in (None, ""):
        return 1
    if isinstance(raw, bool):
        raise AnalysisError(f"“{label}”: the units running must be a whole number, 1 or more.")
    try:
        value = float(raw)
    except (TypeError, ValueError):
        raise AnalysisError(f"“{label}”: the units running must be a whole number, 1 or more.") from None
    if value != int(value) or not 1 <= value <= MAX_UNITS:
        raise AnalysisError(f"“{label}”: the units running must be a whole number from 1 to {MAX_UNITS:,}.")
    return int(value)


def _plural(n: int, word: str) -> str:
    return f"{n} {word}{'' if n == 1 else 's'}"


def limit_message(label: str, k: int, dormancy: float, own_spare_model: bool) -> Optional[str]:
    """Why a non-repairable standby block has no exact reliability (an
    upstream limit), or None when it has one."""
    if k < 2:
        return None
    if 0.0 < dormancy < 1.0:
        return (f"“{label}”: warm standby with {_plural(k, 'unit')} running can't be worked out exactly yet, only "
                "simulated. Make the spares cold or hot, or run one unit at a time.")
    if dormancy == 0.0 and own_spare_model and k >= 3:
        return (f"“{label}”: cold standby with {_plural(k, 'unit')} running and a spare model of its own can't be "
                "worked out exactly yet, only simulated. Give the spares the running units' model, or run at most "
                "2 units.")
    return None


def nonrepairable_model(data: dict, label: str, primary, spare, spares: int, dormancy: float,
                        switch: float = 1.0):
    """The ``StandbyModel`` of a non-repairable standby block with ``k``
    units running (``k = 1`` hot standby stays the caller's parallel block).
    Raises :class:`AnalysisError` where RePyability has no exact reliability."""
    from repyability.rbd.standby_node import StandbyModel

    k = operating(data, label)
    own = data.get("standbyModel") not in (None, data.get("model"))
    reason = limit_message(label, k, dormancy, own)
    if reason:
        raise StandbyLimit(reason)
    units = [primary] * k + [spare] * max(spares, 0)
    if dormancy == 0.0:
        return StandbyModel(units, k=k, switching_probability=switch)
    return StandbyModel(units, k=k, dormancy_factor=dormancy)


def switching_warning(data: dict, label: str, dormancy: float) -> Optional[str]:
    """A warning when a start-success probability is set on a warm or hot
    block, which RePyability doesn't take (it switches perfectly)."""
    raw = data.get("startProb")
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return None
    if dormancy > 0.0 and value < 1.0:
        return (f"“{label}”: a spare's start-success probability applies to cold standby only, so this "
                f"{'warm' if dormancy < 1.0 else 'hot'} standby switches perfectly.")
    return None


def warnings(graph: dict) -> list[str]:
    """The Validate step's notes on standby blocks."""
    from backend.services.rbd_analysis import _standby_dormancy

    out = []
    for node in graph.get("nodes") or []:
        if node.get("type") != "standby":
            continue
        data = node.get("data") or {}
        label = data.get("label") or node.get("id")
        try:
            note = switching_warning(data, label, _standby_dormancy(data, label))
        except AnalysisError:
            continue
        if note:
            out.append(note)
    return out


def from_document(k, units: int) -> Optional[int]:
    """A standby group's ``k`` from a RePyability document, or None when it
    isn't a whole number from 1 to fewer than its units."""
    if isinstance(k, bool):
        return None
    try:
        value = float(k)
    except (TypeError, ValueError):
        return None
    if value != int(value) or not 1 <= value < units:
        return None
    return int(value)
