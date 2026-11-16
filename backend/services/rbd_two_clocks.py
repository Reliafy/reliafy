"""An RBD block on a saved life on two clocks (hours and starts, cycles, landings...), at the block's rate.

The block's model says how much of its second clock the unit uses per unit of the first (starts per
hour, landings per flight hour)
(``usage_rate`` on the block's model; the Explorer fills it from the position's
operating plan). Its life is SurPyval's ``EquivalenceModel.at_usage(rate)``: an
ordinary life in hours.

It reaches RePyability as it is: since RePyability 0.19.1 (found by
:func:`repy_compat.native_usage_blocks`) every diagram takes the ``LifeAtUsage``
as a block's life, saves it and offers its rate as a lever. The confidence band
on a diagram draws the two-clock fit's own parameters (``rbd_uncertainty``), so
the block carries its fit's uncertainty.

The plain-distribution stand-in that 0.19 needed is gone: a saved block holds
only the model id and the rate, never a distribution, so nothing saved
depended on it. With an older RePyability the block says so instead.
"""

from __future__ import annotations

from typing import Optional

from backend import two_clocks
from backend.services import repy_compat

NEEDS_RATE = "{where} is a life on two clocks: set its usage rate, {per}, on the block."


class BlockError(ValueError):
    """A two-clock block that can't be built, said in words."""


def is_two_clock(model) -> bool:
    return isinstance(model, dict) and model.get("kind") == two_clocks.KIND


def rate_of(model: dict, where: str, words: Optional[dict] = None) -> float:
    """The block's usage rate, or a BlockError in the model's units (``words``)."""
    words = words or (model or {}).get("clocks")
    raw = (model or {}).get("usage_rate")
    if raw in (None, ""):
        per = two_clocks.rate_help(words) if words else "its second clock per unit of the first (0.125 is 1 every 8)"
        raise BlockError(NEEDS_RATE.format(where=where, per=per))
    try:
        return two_clocks.check_rate(raw, words)
    except two_clocks.TwoClockError as exc:
        raise BlockError(f"{where}: {exc}") from None


def block_life(model: dict, where: str, resolve_model) -> Optional[object]:
    """The block's life in hours at its rate; None in a structural check (no
    resolver), where any life will do."""
    if resolve_model is None:
        return None  # a diagram may be saved before its rate is set; the analysis asks for it
    model_id = model.get("modelId") or model.get("model_id")
    entry = resolve_model(model_id) if model_id else None
    live = (entry or {}).get("model")
    if not two_clocks.is_model(live):
        raise BlockError(f"{where}: its model on two clocks wasn't found (deleted?).")
    rate = rate_of(model, where, two_clocks.words_of(live))
    if not repy_compat.native_usage_blocks():
        raise BlockError(f"{where}: a life on two clocks needs RePyability 0.19.1 or later as a block.")
    return live.at_usage(rate)
