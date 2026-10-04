"""The time to a repairable diagram's next failure from now, and its likely
cause (#220), with its mean, the mean residual life (#221).

RePyability 0.12 starts ``simulate_timelines`` from the blocks' current
states (``state=``, its #163): each simulation's system history then runs
from the plant as it is, and the first unplanned change down in it is the
next system failure, its cause the block whose failure made it. A history
whose system is down now starts down, with no change at 0, so its next
failure is the one after the system is restored.

These are the simulations ``availability(state=...)`` runs with the same
seed, so they are the app's simulation gate's to give (Pro or credits).

The window starts as the availability run's and is lengthened (by
:data:`NEXT_FAILURE_GROWTH`, up to :data:`NEXT_FAILURE_MAX_GROWTH` times)
until no more than :data:`NEXT_FAILURE_MAX_CENSORED` of the histories have
not yet failed, within :data:`NEXT_FAILURE_TIME_BUDGET` seconds. The mean is
then that of the histories' next failures; while some still haven't failed
it is the mean of ``min(T, window)``, a lower bound, and is said to be one.

The functions below use only numpy and ``time``, and "Download as Python"
copies their source into its script (:func:`export_source`), so the script
gives the app's numbers.
"""

from __future__ import annotations

import inspect
import time
from typing import Optional

import numpy as np

NEXT_FAILURE_SIMS = 2000  # the most histories (the time budget may give fewer)
NEXT_FAILURE_MIN_SIMS = 100
NEXT_FAILURE_PILOT = 20  # histories timed first, to size the run
NEXT_FAILURE_MAX_CENSORED = 0.01  # lengthen the window until 99% have failed
NEXT_FAILURE_GROWTH = 4.0
NEXT_FAILURE_MAX_GROWTH = 256.0  # the longest window, in availability windows
NEXT_FAILURE_TIME_BUDGET = 10.0  # seconds; None (the script's default) for no limit
NEXT_FAILURE_CONFIDENCE = 0.95
NEXT_FAILURE_Z = 1.959963984540054  # the two-sided 95% normal quantile
NEXT_FAILURE_CURVE_POINTS = 201
NEXT_FAILURE_CURVE_END = 0.995  # the curve's end, as a share failed
NEXT_FAILURE_SEED = 1  # the availability simulation's seed


def timelines_run(rbd, window, n, overrides):
    """``(runs, antithetic)``: ``n`` seeded histories over ``window``, in
    antithetic pairs when every block's draws can be replayed, as the
    availability simulation runs them."""
    try:
        runs = rbd.simulate_timelines(float(window), mc_samples=int(n) + int(n) % 2, seed=NEXT_FAILURE_SEED,
                                      antithetic=True, **overrides)
        return runs, True
    except NotImplementedError:
        runs = rbd.simulate_timelines(float(window), mc_samples=int(n), seed=NEXT_FAILURE_SEED, **overrides)
        return runs, False


def next_failure_simulation(rbd, window, overrides, max_n=NEXT_FAILURE_SIMS,
                            budget=NEXT_FAILURE_TIME_BUDGET):
    """``(runs, antithetic, window, n, time_limited)``.

    With a time ``budget`` (seconds), a pilot of :data:`NEXT_FAILURE_PILOT`
    histories sizes the run to half of it (at most ``max_n``, at least
    :data:`NEXT_FAILURE_MIN_SIMS`) and the window is lengthened only while
    the next run is expected to fit what is left. With none, ``max_n``
    histories and the window lengthened as far as the rule goes."""
    start = time.perf_counter()
    n = int(max_n)
    if budget is not None:
        timelines_run(rbd, window, NEXT_FAILURE_PILOT, overrides)
        per = max((time.perf_counter() - start) / NEXT_FAILURE_PILOT, 1e-9)
        n = int(min(max_n, max(NEXT_FAILURE_MIN_SIMS, 0.5 * budget / per)))
    n -= n % 2
    longest = float(window) * NEXT_FAILURE_MAX_GROWTH * (1.0 + 1e-9)
    window = float(window)
    limited = False
    while True:
        began = time.perf_counter()
        runs, antithetic = timelines_run(rbd, window, n, overrides)
        took = time.perf_counter() - began
        censored = float(np.mean(~np.isfinite(np.asarray(runs.system.first_failure, dtype=float))))
        if censored <= NEXT_FAILURE_MAX_CENSORED or window * NEXT_FAILURE_GROWTH > longest:
            break
        if budget is not None and time.perf_counter() - start + took * NEXT_FAILURE_GROWTH > budget:
            limited = True
            break
        window *= NEXT_FAILURE_GROWTH
    return runs, antithetic, window, len(runs.system), limited


def first_failures(runs):
    """``(times, causes, up_now)``: each history's next system failure (inf
    if none in the window), the block that caused it (None if none), and
    whether the system is up now."""
    times = np.asarray(runs.system.first_failure, dtype=float)
    up_now = np.asarray(runs.system.up, dtype=bool)
    causes = []
    for s, t in enumerate(times):
        cause = None
        if np.isfinite(t):
            history = runs.system[s]
            up, planned, who = history.up, history.planned, history.causes
            for i in range(len(planned)):
                # After change i the state has flipped i + 1 times.
                after_up = up != (i % 2 == 0)
                if not after_up and not planned[i]:
                    cause = who[i]
                    break
        causes.append(cause)
    return times, causes, up_now


def next_failure_summary(times, causes, up_now, window, antithetic, labels):
    """The next failure's distribution, mean (with its interval, or as a
    lower bound while some histories haven't failed) and causes."""
    times = np.asarray(times, dtype=float)
    n = int(times.size)
    failed = np.isfinite(times)
    censored = not bool(failed.all())
    restricted = np.minimum(times, window)
    mean = float(np.mean(restricted))
    # Antithetic pairs are negatively correlated: their means are the
    # independent units of the standard error.
    units = restricted.reshape(-1, 2).mean(axis=1) if antithetic and n % 2 == 0 else restricted
    se = float(np.std(units, ddof=1) / np.sqrt(units.size)) if units.size > 1 else None
    ordered = np.sort(times)

    def percentile(q):
        v = ordered[max(int(np.ceil(q * n)) - 1, 0)]
        return float(v) if np.isfinite(v) else None

    # P(failed by t) up to the 99.5th percentile (the window while it isn't reached).
    end = percentile(NEXT_FAILURE_CURVE_END) or float(window)
    grid = np.linspace(0.0, end, NEXT_FAILURE_CURVE_POINTS)
    cdf = np.searchsorted(ordered, grid, side="right") / n
    counts = {}
    for cause in causes:
        if cause is not None:
            counts[cause] = counts.get(cause, 0) + 1
    total = sum(counts.values())
    rows = [{"id": str(c), "label": labels.get(c, str(c)), "count": k, "share": k / total}
            for c, k in counts.items()]
    rows.sort(key=lambda r: (-r["count"], r["label"]))
    # The interval is the mean's; while some histories haven't failed, the
    # mean is of min(T, window), a lower bound of the next failure's.
    interval = se is not None
    return {
        "window": float(window),
        "n_simulations": n,
        "antithetic": bool(antithetic),
        "down_now": float(np.mean(~np.asarray(up_now, dtype=bool))),
        "failed_share": float(np.mean(failed)),
        "mean": mean if mean > 0 else None,
        "mean_is_lower_bound": censored,
        "mean_lower": max(mean - NEXT_FAILURE_Z * se, 0.0) if interval else None,
        "mean_upper": mean + NEXT_FAILURE_Z * se if interval else None,
        "standard_error": se,
        "confidence": NEXT_FAILURE_CONFIDENCE,
        "percentiles": {"p10": percentile(0.1), "p50": percentile(0.5), "p90": percentile(0.9)},
        "curve": {"t": grid.tolist(), "cdf": cdf.tolist()},
        "causes": rows,
    }


def next_failure(rbd, labels: dict, overrides: dict, node_states: dict, window: float,
                 budget: Optional[float] = NEXT_FAILURE_TIME_BUDGET, max_n: int = NEXT_FAILURE_SIMS) -> dict:
    """The app's ``next_failure`` block: the time to the next system failure
    from the blocks' states now (``node_states``), its mean (the mean
    residual life) and its causes. ``overrides`` are the availability run's
    pins (working / broken nodes); ``max_n`` caps the histories."""
    runs, antithetic, window, _, limited = next_failure_simulation(
        rbd, window, {**overrides, "state": node_states}, max_n=min(int(max_n), NEXT_FAILURE_SIMS), budget=budget)
    times, causes, up_now = first_failures(runs)
    out = next_failure_summary(times, causes, up_now, window, antithetic, labels)
    return {"from": "now", "method": "simulated", **out, "time_limited": limited}


_EXPORTED = (timelines_run, next_failure_simulation, first_failures, next_failure_summary)
_CONSTANTS = ("NEXT_FAILURE_SIMS", "NEXT_FAILURE_MIN_SIMS", "NEXT_FAILURE_PILOT", "NEXT_FAILURE_MAX_CENSORED",
              "NEXT_FAILURE_GROWTH", "NEXT_FAILURE_MAX_GROWTH", "NEXT_FAILURE_CONFIDENCE", "NEXT_FAILURE_Z",
              "NEXT_FAILURE_CURVE_POINTS", "NEXT_FAILURE_CURVE_END", "NEXT_FAILURE_SEED")


def export_source() -> str:
    """The constants and functions above, as "Download as Python" copies
    them into its script (with no time budget: every history, the window
    lengthened as far as the rule goes)."""
    consts = "\n".join(f"{name} = {globals()[name]!r}" for name in _CONSTANTS)
    budget = ("# Reliafy stops lengthening the window after a time budget, and sizes the run to it;\n"
              "# its result gives the histories and window it used. None: no limit.\n"
              "NEXT_FAILURE_TIME_BUDGET = None")
    funcs = "\n\n".join(inspect.getsource(f).rstrip() for f in _EXPORTED)
    return f"{consts}\n{budget}\n\n\n{funcs}\n"
