"""A demonstration test's B-life requirement and its Weibull shape's
uncertainty (#295).

A B-life requirement, "B10 ≥ 50,000 cycles at 90% confidence", is the
reliability requirement R(50,000 cycles) ≥ 90% at 90% confidence: the
attribute test that shows one shows the other.

Testing each unit longer than one mission trades units for test time through
the Weibull shape β, assumed known. A β taken from a fit to a handful of
failures is anything but: five failures can give β a 95% interval of
[1.0, 5.1], and a plan sized at the estimate can then show much less than it
claims. :func:`shape_sensitivity` re-reads the plan at each end of β's
interval (RePyability's ``demonstrated_reliability`` and sample size / test
length) and warns when the unsafe end needs materially more testing.
"""

from __future__ import annotations

import math
from typing import Optional

# β's interval is "poorly known" for a plan when its unsafe end needs at least
# this much more testing (units, or test time per unit) than the plan has.
POORLY_KNOWN = 1.25
_MAX_SHAPE_BOUND = 100.0


def b_life_reliability(b_life, error) -> float:
    """The reliability a "Bx" requirement asks for: 1 − x/100. ``error`` is
    the exception class to raise on a bad x."""
    try:
        b = float(b_life)
    except (TypeError, ValueError):
        raise error("The B-life must be a percentage failed, e.g. 10 for B10.") from None
    if not (math.isfinite(b) and 0.0 < b < 100.0):
        raise error(f"The B-life must be between 0 and 100 (exclusive), e.g. 10 for B10; got {b:g}.")
    return 1.0 - b / 100.0


def check_interval(interval, error) -> Optional[tuple[float, float]]:
    """``(lower, upper)`` of β's interval, or None when not given."""
    if interval is None or (isinstance(interval, (list, tuple)) and len(interval) == 0):
        return None
    try:
        lo, hi = (float(v) for v in interval)
    except (TypeError, ValueError):
        raise error("shape_interval must be [lower, upper], e.g. [1.0, 5.1].") from None
    if not (math.isfinite(lo) and math.isfinite(hi) and 0 < lo <= hi <= _MAX_SHAPE_BOUND):
        raise error(f"shape_interval must be two positive numbers, lower first, at most "
                    f"{_MAX_SHAPE_BOUND:g}; got [{lo:g}, {hi:g}].")
    return lo, hi


def fmt_shape(v: float) -> str:
    """β to three figures, keeping a decimal: 1.0, 2.35, 5.1."""
    s = f"{float(v):.3g}"
    return s if ("." in s or "e" in s) else f"{s}.0"


def shape_sensitivity(demo, *, R: float, c: float, r: int, k: float, n: int, beta: float,
                      interval: tuple[float, float], solve_for: str, t: Optional[float],
                      unit: str, fmt, time_phrase) -> dict:
    """The plan at each end of β's interval.

    ``{"interval", "uses", "relevant", "at_lower", "at_upper", "unsafe",
    "warning"}``. ``at_*``: the reliability the planned test shows if β is
    that end (``demonstrated``) and what it would need there (``units``, or
    ``test_multiple`` when solving for test time). ``unsafe`` is the end that
    shows less ("lower" when each unit runs longer than the mission). The
    ``warning`` (or None) says so in words when that end needs at least
    :data:`POORLY_KNOWN` times the testing. ``relevant`` is False for a test
    one mission long, where β changes nothing."""
    lo, hi = interval
    rel_tol = 1e-6
    uses = ("lower" if math.isclose(beta, lo, rel_tol=rel_tol)
            else "upper" if math.isclose(beta, hi, rel_tol=rel_tol)
            else "estimate")
    block: dict = {"interval": [lo, hi], "uses": uses, "relevant": k != 1.0,
                   "at_lower": None, "at_upper": None, "unsafe": None, "warning": None}
    if k == 1.0:
        return block

    def at(b: float) -> dict:
        ext = {"test_multiple": k, "shape": b}
        out = {"beta": b, "demonstrated": float(demo.demonstrated_reliability(n, c, r, **ext))}
        if solve_for == "units":
            out["units"] = int(demo.demonstration_sample_size(R, c, r, **ext))
        else:
            out["test_multiple"] = float(demo.demonstration_test_multiple(R, n, c, r, shape=b))
        return out

    block["at_lower"], block["at_upper"] = at(lo), at(hi)
    unsafe = "lower" if block["at_lower"]["demonstrated"] <= block["at_upper"]["demonstrated"] else "upper"
    block["unsafe"] = unsafe
    end = block[f"at_{unsafe}"]
    if solve_for == "units":
        need, have = end["units"], n
    else:
        need, have = end["test_multiple"], k
    if need < POORLY_KNOWN * have or end["demonstrated"] >= R:
        return block

    pct = lambda p: f"{p * 100:.3g}%"  # noqa: E731
    low_high = "low" if unsafe == "lower" else "high"
    shows = f"shows only {pct(end['demonstrated'])} reliability, not {pct(R)}"
    if solve_for == "units":
        what = f"this test {shows}: it would need {need:,} units, not {n:,}"
    else:
        each = (time_phrase(need * t, unit) if t is not None else f"{fmt(need)}× the mission")
        what = f"this test {shows}: each unit would need {each}"
    block["warning"] = (
        f"β is poorly known: its interval is {fmt_shape(lo)}–{fmt_shape(hi)}. If it's as {low_high} as "
        f"{fmt_shape(end['beta'])}, {what}. Plan with β's {unsafe} bound to be safe, or pin β down with "
        "more failure data.")
    return block
