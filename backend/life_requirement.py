"""Check a B-life requirement on a fitted life model (#295).

A design engineer's requirement reads "B10 ≥ 50,000 cycles at 90%
confidence": the time by which 10% have failed must be at least 50,000, and
the data must show it with 90% confidence. The B-life and its one-sided lower
bound are SurPyval's (:func:`backend.life_bounds.time_at_reliability`); this
module compares the bound with the requirement and says so in a sentence.

The verdict turns on the lower bound, never the estimate: a best estimate
above the requirement whose bound is below it does NOT meet it yet (more
data, or a demonstration test, could show it). A model with no bounds (no
covariance, not a maximum-likelihood fit) gets ``unknown``, with the
estimate for what it's worth.
"""

from __future__ import annotations

import math
from typing import Optional

from backend import life_bounds

VERDICTS = ("meets", "does_not_meet", "unknown")


def check_b(b) -> float:
    """The x in Bx (the percent failed, 10 for B10) as a float in (0, 100)."""
    try:
        v = float(b)
    except (TypeError, ValueError):
        raise ValueError("The B-life must be a percentage failed, e.g. 10 for B10.") from None
    if not (math.isfinite(v) and 0.0 < v < 100.0):
        raise ValueError("The B-life must be between 0 and 100 (exclusive), e.g. 10 for B10.")
    return v


def b_label(b: float) -> str:
    """'B10', 'B0.1', 'B2.5'."""
    return f"B{float(b):g}"


def check_life(life) -> float:
    try:
        v = float(life)
    except (TypeError, ValueError):
        raise ValueError("The required life must be a positive number.") from None
    if not (math.isfinite(v) and v > 0):
        raise ValueError("The required life must be a positive number.")
    return v


def _with_unit(v: float, unit: str) -> str:
    from backend.services.strategy import fmt_num
    from backend.units import unit_in_text

    u = unit_in_text(unit) if unit else ""
    return f"{fmt_num(v)} {u}".rstrip()


def summary(check: dict, unit: str = "") -> str:
    """The verdict in one plain sentence (the app builds its own, with bold
    numbers, from the same fields)."""
    from backend.services.strategy import fmt_num

    label, life, conf = check["label"], check["life"], f"{check['confidence'] * 100:g}%"
    est, lo = check["estimate"], check["lower"]
    best = f" Best estimate {fmt_num(est)}." if est is not None else ""
    if check["verdict"] == "meets":
        return (f"Meets: at {conf} confidence {label} ≥ {_with_unit(lo, unit)}, at or above the "
                f"{fmt_num(life)} required.{best}")
    if check["verdict"] == "does_not_meet":
        s = (f"Does not meet: at {conf} confidence {label} ≥ {_with_unit(lo, unit)}, below the "
             f"{fmt_num(life)} required.{best}")
        if check["estimate_meets"]:
            s += (f" The best estimate meets it, but these data can't show it at {conf} confidence: "
                  "more data or a demonstration test could.")
        return s
    if est is None:
        return f"Can't check: the model gives no {label}."
    side = "at or above" if check["estimate_meets"] else "below"
    return (f"Can't check at {conf} confidence: this model has no confidence bounds. The best estimate of "
            f"{label} is {_with_unit(est, unit)}, {side} the {fmt_num(life)} required.")


def check_requirement(model, b, life, confidence: float = life_bounds.DEFAULT_CONFIDENCE,
                      no_finite_maximum: bool = False, unit: str = "") -> dict:
    """Does ``model`` meet "B``b`` ≥ ``life`` at ``confidence``"?

    Returns ``{"b", "label", "life", "confidence", "estimate", "lower",
    "verdict", "meets", "estimate_meets", "bounds_note", "summary"}``:
    ``verdict`` is ``meets`` (the one-sided lower bound on the B-life is at
    least ``life``), ``does_not_meet`` (it is below) or ``unknown`` (no
    bound); ``meets`` is the same as a boolean, or None. Raises ValueError on
    a bad requirement."""
    b = check_b(b)
    life = check_life(life)
    confidence = life_bounds.check_confidence(confidence)
    at = life_bounds.time_at_reliability(model, [1.0 - b / 100.0], confidence, "lower",
                                         with_bounds=not no_finite_maximum)
    pt = at["points"][0]
    est: Optional[float] = pt["time"]
    lo: Optional[float] = pt["lower"]
    if lo is not None:
        verdict = "meets" if lo >= life else "does_not_meet"
    else:
        verdict = "unknown"
    out = {
        "b": b,
        "label": b_label(b),
        "life": life,
        "confidence": confidence,
        "estimate": est,
        "lower": lo,
        "verdict": verdict,
        "meets": None if verdict == "unknown" else verdict == "meets",
        "estimate_meets": None if est is None else est >= life,
        "bounds_note": at["bounds_note"],
    }
    out["summary"] = summary(out, unit)
    return out
