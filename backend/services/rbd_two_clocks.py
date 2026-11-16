"""An RBD block on a saved life on hours and starts (two clocks), at the block's rate.

The block's model says how many starts per running hour the unit makes
(``usage_rate`` on the block's model; the Explorer fills it from the position's
operating plan). Its life is SurPyval's ``EquivalenceModel.at_usage(rate)``: an
ordinary life in hours.

How it reaches RePyability depends on the release pinned:

* with RePyability's native block (#415, the release after 0.19; found by
  :func:`repy_compat.native_usage_blocks`) the ``LifeAtUsage`` goes in as it is:
  every diagram takes it, saves it and offers its rate as a lever;
* on 0.19 it goes in as the plain SurPyval distribution it equals in hours (each
  distribution a two-clock fit takes is closed under a change of time scale, so
  the life at ``rate`` is the combined-clock distribution with time divided by
  ``1 + k rate``). The curve is exact; the block carries no parameter
  uncertainty of its own in that case.

When the app pins the release with #415, nothing here needs to change: the
capability check picks the native block. The fallback can then go.
"""

from __future__ import annotations

from typing import Optional

import surpyval as sp

from backend import two_clocks
from backend.services import repy_compat

NEEDS_RATE = ("{where} is a life on hours and starts: set how many starts per running hour the unit makes "
              "(0.125 is 1 start every 8 hours) on the block.")


class BlockError(ValueError):
    """A two-clock block that can't be built, said in words."""


def is_two_clock(model) -> bool:
    return isinstance(model, dict) and model.get("kind") == two_clocks.KIND


def rate_of(model: dict, where: str) -> float:
    raw = (model or {}).get("usage_rate")
    if raw in (None, ""):
        raise BlockError(NEEDS_RATE.format(where=where))
    try:
        return two_clocks.check_rate(raw)
    except two_clocks.TwoClockError as exc:
        raise BlockError(f"{where}: {exc}") from None


def plain_life(life):
    """The life at a rate as the plain SurPyval distribution it equals in hours."""
    dist = two_clocks.as_distribution(life)
    if dist is None:
        raise BlockError(f"A {life.model.dist.name} life on two clocks can't be a block with this RePyability yet.")
    cls = {"weibull": sp.Weibull, "exponential": sp.Exponential, "lognormal": sp.LogNormal}[dist["distribution_id"]]
    return cls.from_params([p["value"] for p in dist["params"]])


def block_life(model: dict, where: str, resolve_model) -> Optional[object]:
    """The block's life in hours at its rate; None in a structural check (no
    resolver), where any life will do."""
    if resolve_model is None:
        return None  # a diagram may be saved before its rate is set; the analysis asks for it
    rate = rate_of(model, where)
    model_id = model.get("modelId") or model.get("model_id")
    entry = resolve_model(model_id) if model_id else None
    live = (entry or {}).get("model")
    if not two_clocks.is_model(live):
        raise BlockError(f"{where}: its model on hours and starts wasn't found (deleted?).")
    life = live.at_usage(rate)
    # RePyability 0.20 / 0.19.1 (#415) takes the LifeAtUsage natively; 0.19 gets the plain distribution.
    if repy_compat.native_usage_blocks():
        return life
    return plain_life(life)
