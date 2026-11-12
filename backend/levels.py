"""The one level for every interval the app shows.

One rule everywhere, stated on every result:

* life quantities (B-lives, mean or median life, remaining life, the time to
  a limit) get a 90% one-sided **lower** bound: "at least 2,200 hours (90%)";
* a probability of failure (unreliability, a per-demand failure probability)
  gets a 90% one-sided **upper** bound, and a reliability a 90% one-sided
  lower bound;
* everything else (parameters, hazard and rate ratios, plot bands, rates,
  forecast ranges, availability) gets a 90% two-sided interval: "90% range".

SurPyval's ``alpha_ci`` is the same 0.10 for both: a two-sided interval at
``1 - alpha_ci``, or one bound at ``1 - alpha_ci``. A page that lets the user
pick another level keeps the user's choice; this is its default.

Hypothesis tests (p-values, trend tests), test-plan inputs other than the
demonstrated confidence, spares service levels and a source's published
5–95% spread aren't intervals the app works out, so they don't follow it.
"""

from __future__ import annotations

LEVEL = 0.90
#: SurPyval's ``alpha_ci`` for a 90% two-sided interval or a 90% one-sided bound.
ALPHA = 0.10
#: The two-sided 90% normal quantile (also the one-sided 95% one).
Z = 1.6448536269514722
#: The two-sided 95% normal quantile: intervals stored before the rule were at 95%.
Z95 = 1.959963984540054
#: Quantiles of a simulated 90% range (the 5th and 95th percentiles).
Q_LOW, Q_HIGH = 0.05, 0.95
#: The bound a life quantity gets, and the one a probability of failure gets.
LIFE_BOUND = "lower"
FAILURE_BOUND = "upper"


def pct(level: float = LEVEL) -> str:
    """'90%' (or '95%', '99.5%' for a level someone chose)."""
    v = round(float(level) * 100, 1)
    return f"{v:g}%"


#: Words for a two-sided interval and a one-sided bound, as results say them.
RANGE_WORDS = f"{pct()} range"
INTERVAL_WORDS = f"{pct()} interval"
ONE_SIDED_WORDS = f"{pct()} one-sided"


def rescale(value, lo, hi, *, log=False, z_from: float = Z95, z_to: float = Z):
    """A stored Wald interval ``[lo, hi]`` at ``z_from`` moved to ``z_to``: its
    standard error is read back from its width, on the log scale when ``log``
    (a ratio, or a positive parameter's interval taken on the log scale);
    ``log=None`` picks the log scale for a positive interval that isn't
    symmetric about the value. None when it can't be (a missing or
    non-finite end)."""
    import math

    try:
        v, a, b = float(value), float(lo), float(hi)
    except (TypeError, ValueError):
        return None
    if not all(math.isfinite(x) for x in (v, a, b)) or b < a:
        return None
    k = z_to / z_from
    if log is None:
        log = a > 0 and abs((a + b) / 2.0 - v) > 1e-9 * max(abs(v), b - a, 1e-300)
    if log:
        if v <= 0 or a <= 0 or b <= 0:
            return None
        lv = math.log(v)
        return [math.exp(lv - (lv - math.log(a)) * k), math.exp(lv + (math.log(b) - lv) * k)]
    return [v - (v - a) * k, v + (b - v) * k]
