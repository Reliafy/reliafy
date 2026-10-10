"""A safety function's PFD over time, from RePyability's own unavailability
(#322, RePyability 0.13's ``point_unavailability`` /
``mission_unavailability``, its #237).

A safety function's probability of failure on demand is its unavailability,
and a good one is small: 1e-4 and below. One less the availability, worked
out near 1, keeps only the digits left after the subtraction, so the SIF
card's PFD(t) chart and the margin to a SIL band's limit read the
library's unavailability instead, which keeps its precision:

* :func:`over_time` — the ``exact`` block's ``curve.unavailability``
  (``point_unavailability`` on the same grid as A(t)) and
  ``mission_unavailability`` (its mean over the window), for a diagram
  marked as a safety function;
* :func:`margin` — the PFDavg (``mean_unavailability``, the long run) against
  the target SIL's limit, or the achieved band's: the margin the safety card
  states.
"""

from __future__ import annotations

from typing import Optional

import numpy as np


def over_time(rbd, grid: np.ndarray, window: float, overrides: dict, state_kw: dict) -> dict:
    """``{"unavailability": [...], "mission_unavailability"}``: the system's
    point unavailability at each time of ``grid`` and its mean over
    ``[0, window]``, from the same start as A(t) (new, or ``state_kw``'s
    states). Raises as ``point_availability`` does (the caller has checked
    its route)."""
    from backend.services.rbd_analysis import _clean, _f

    with np.errstate(all="ignore"):
        down = np.asarray(rbd.point_unavailability(grid, **overrides, **state_kw), dtype=float)
        mission = rbd.mission_unavailability(float(window), **overrides, **state_kw)
    return {"unavailability": _clean(down), "mission_unavailability": _f(mission)}


def sil_limit(sil: int) -> float:
    """The upper limit of SIL ``sil``'s low-demand band, ``10 ** -sil``
    (IEC 61508-1: SIL n is ``[10^-(n+1), 10^-n)``)."""
    return 10.0 ** -int(sil)


def margin(pfd: Optional[float], target: Optional[int], sil: Optional[int]) -> Optional[dict]:
    """The PFDavg against a SIL band's limit — the target's, or with no
    target the achieved band's: ``{"sil", "limit", "ratio", "of"}``
    (``ratio`` below 1 is inside the band; ``of`` says which band). None
    without a PFDavg or a band."""
    ref = target if target is not None else sil
    if pfd is None or not np.isfinite(pfd) or ref is None:
        return None
    limit = sil_limit(ref)
    return {"sil": int(ref), "limit": limit, "ratio": float(pfd) / limit,
            "of": "target" if target is not None else "achieved"}
