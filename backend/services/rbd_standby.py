"""k-of-n standby (#84): a standby block with ``k`` units running and its
spares idle, e.g. a 2-of-3 duty/standby pump train.

The block holds ``k`` (the units that must run, by default 1) beside its
``spares``; it has ``k + spares`` units. RePyability's ``StandbyModel(units,
k)`` and a repairable diagram's standby group (``"standby": {"units", "k"}``)
take any ``k``.

"Chance a spare starts" (``startProb``) is RePyability's ``start_probability``
(0.17): a spare that fails to start is skipped and the next one is tried, on
cold, warm and hot standby alike. (Until RePyability 0.17 the app sent it as a
failed switch, which ends the arrangement, and left it out on warm and hot
blocks.)

What RePyability 0.18 works out, and so what Reliafy offers: exactly or
numerically every arrangement of exponential units (a Markov chain), cold
standby of identical units or with at most 2 running, and warm or hot standby
with one running. Where it has no exact reliability (warm standby with
``k >= 2`` of other lives, cold standby with a spare model of its own and
``k >= 3``, hot standby with ``k >= 2`` and spares that may fail to start) it
only simulates, and Reliafy refuses the block, saying so: the library's own
``is_simulated`` decides, so the refusals follow it.

In a repairable diagram the group's units are identical (as before); its
exact long-run values need exponential lives and repairs (RePyability's
Markov chain), otherwise it is simulated, whatever ``k``. There the library's
group takes only a switch that may fail (``switching_probability``).
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


def start_probability(data: dict) -> float:
    """The block's "Chance a spare starts", 1 when unset or unreadable."""
    raw = data.get("startProb")
    if raw in (None, ""):
        return 1.0
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return 1.0
    return value if 0.0 <= value <= 1.0 else 1.0


def limit_message(label: str, k: int, dormancy: float, own_spare_model: bool, start: float = 1.0) -> str:
    """Why a non-repairable standby block has no exact reliability, for an
    arrangement RePyability only simulates (``StandbyModel.is_simulated``)."""
    if 0.0 < dormancy < 1.0 and k >= 2:
        return (f"“{label}”: warm standby with {_plural(k, 'unit')} running can be worked out exactly only when "
                "every unit has a constant failure rate (exponential); otherwise it can only be simulated. Make "
                "the spares cold, run one unit at a time, or use exponential lives.")
    if dormancy >= 1.0 and k >= 2 and start < 1.0:
        return (f"“{label}”: hot standby with {_plural(k, 'unit')} running and spares that may fail to start can "
                "be worked out exactly only when every unit has a constant failure rate (exponential); otherwise "
                "it can only be simulated. Set the chance a spare starts to 100%, run one unit at a time, or use "
                "exponential lives.")
    if dormancy == 0.0 and own_spare_model and k >= 3:
        return (f"“{label}”: cold standby with {_plural(k, 'unit')} running and a spare model of its own can be "
                "worked out exactly only when every unit has a constant failure rate (exponential); otherwise it "
                "can only be simulated. Give the spares the running units' model, or run at most 2 units.")
    return (f"“{label}”: this standby arrangement has too many different units to work out exactly, only "
            "simulated. Give more of its units one model, or use fewer spares.")


def nonrepairable_model(data: dict, label: str, primary, spare, spares: int, dormancy: float,
                        start: Optional[float] = None):
    """The ``StandbyModel`` of a non-repairable standby block, ``k`` units
    running, its spares cold, warm or hot, each starting with the block's
    "Chance a spare starts" (``start_probability``). Raises
    :class:`StandbyLimit` where RePyability has no exact reliability."""
    from repyability.rbd.standby_node import StandbyModel

    k = operating(data, label)
    start = start_probability(data) if start is None else start
    units = [primary] * k + [spare] * max(spares, 0)
    model = StandbyModel(units, k=k, dormancy_factor=dormancy, start_probability=start)
    if model.is_simulated:
        own = data.get("standbyModel") not in (None, data.get("model"))
        raise StandbyLimit(limit_message(label, k, dormancy, own, start))
    return model


def limit_for(data: dict, label: str) -> Optional[str]:
    """Why a non-repairable standby block (its stored data) has no exact
    reliability, or None when it has one (or its lives can't be read here)."""
    from backend.services import rbd_analysis as ra

    try:
        dormancy = ra._standby_dormancy(data, label)
        primary = ra._build_distribution(data.get("model"), label)
        spare = ra._build_distribution(data.get("standbyModel") or data.get("model"), label)
        nonrepairable_model(data, label, primary, spare, int(data.get("spares") or 1), dormancy)
    except StandbyLimit as exc:
        return str(exc)
    except Exception:  # noqa: BLE001 - unreadable lives are reported where they're built
        return None
    return None


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
