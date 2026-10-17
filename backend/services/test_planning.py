"""Test planning beyond the demonstration test: SurPyval 0.25's
``surpyval.test_planning``, with the plain-language summary, assumptions and
chart data the Test planning page and the MCP actions show.

- :func:`sequential_test`: a sequential (Wald) test of an MTBF or a
  reliability, its accept/reject lines, its operating characteristic and how
  long it runs on average.
- :func:`life_test`: how precisely a life test estimates a B-life or the
  mean, or the units or test length for a precision.
- :func:`accelerated_test`: the stresses, units at each and expected failures
  of an accelerated life test (or the precision of a test you propose).
- :func:`comparison`: "did the change work?" planning: a log-rank test's
  events, units and power, or the exposure a before/after failure-rate
  comparison needs and the smallest change it can detect.
- :func:`simulate_precision`: checks a life or accelerated test's precision by
  simulating it (hundreds of fits): Pro, run as a compute job.

The demonstration test itself stays in :mod:`backend.services.strategy`
(``demonstration_test``), on the same library through
:mod:`backend.services.demo_engine`.

Every calculation here is exact or numerical (no simulation), so free;
refusals are :class:`~backend.services.strategy.StrategyError`, in the
calculator's words.
"""
from __future__ import annotations

from typing import Any, Optional

import numpy as np

from backend.services.strategy import (
    StrategyError,
    _blank,
    _demo_count,
    _demo_positive,
    _demo_prob,
    _pct,
    _time_phrase,
    fmt_num,
)

# The chart grids: points, and how far into each tail the OC curve runs.
_OC_POINTS = 41
_OC_TAIL = 0.005
_CURVE_POINTS = 25
_MAX_UNITS = 1_000_000
_MAX_SHAPE = 20.0

DISTRIBUTIONS = ("weibull", "lognormal")
_PARAM_NAMES = {"weibull": ("alpha", "beta"), "lognormal": ("mu", "sigma")}
# The life-stress models a plan takes: the app's single-stress, log-linear ones
# (backend.alt.LIFE_MODELS ids), with their parameters in the model's order.
ALT_LIFE_MODELS = ("arrhenius", "eyring", "inverse_power")

# The simulation check (Pro): how many simulated tests, at most.
SIM_DEFAULT = {"life": 500, "accelerated": 200}
SIM_MAX = {"life": 2_000, "accelerated": 400}
SIM_SEED = 20251022


def _alpha(confidence) -> float:
    return 1.0 - _demo_prob(0.9 if _blank(confidence) else confidence, "Confidence")


def _library_error(exc: ValueError) -> StrategyError:
    """A refusal from the library, passed on as the calculator's."""
    return StrategyError(str(exc))


def _r(value, digits: int = 6):
    """A number for JSON: finite floats rounded to ``digits`` significant
    figures, anything else None."""
    if value is None:
        return None
    v = float(value)
    if not np.isfinite(v):
        return None
    return float(f"{v:.{digits}g}")


def _plural(n: int, word: str) -> str:
    return f"{n:,} {word}{'' if n == 1 else 's'}"


# ---------------------------------------------------------------------------
# Sequential tests
# ---------------------------------------------------------------------------

def sequential_test(
    method: str = "mtbf",
    mtbf=None,
    good_mtbf=None,
    reliability=None,
    good_reliability=None,
    confidence=0.9,
    producer_risk=0.1,
    unit: Optional[str] = None,
    failures_seen=None,
    time_seen=None,
    units_seen=None,
) -> dict:
    """A truncated sequential test (Wald's SPRT, stopped at the fixed-length
    test with the same risks, as MIL-HDBK-781 does).

    ``method='mtbf'``: failures against total test time; ``mtbf`` is the
    target (lower test MTBF), ``good_mtbf`` a design that should pass.
    ``method='attribute'``: failures against units tested, for a mission
    reliability; ``reliability`` and ``good_reliability``. ``failures_seen``
    with ``time_seen`` (or ``units_seen``) adds what the test says now.
    """
    from surpyval import test_planning as tp

    method = (method or "mtbf").strip().lower()
    if method not in ("mtbf", "attribute"):
        raise StrategyError("method must be 'mtbf' or 'attribute'.")
    alpha = _alpha(confidence)
    beta = _demo_prob(0.1 if _blank(producer_risk) else producer_risk, "Producer's risk")
    unit_s = (unit or "").strip()

    if method == "mtbf":
        if _blank(mtbf) or _blank(good_mtbf):
            raise StrategyError("Give the MTBF to demonstrate and the MTBF of a good design.")
        lo = _demo_positive(mtbf, "Target MTBF")
        hi = _demo_positive(good_mtbf, "Good design's MTBF")
        if hi <= lo:
            raise StrategyError(f"The good design's MTBF ({_time_phrase(hi, unit_s)}) must be above the target "
                                f"({_time_phrase(lo, unit_s)}).")
        if hi / lo < 1.25:
            raise StrategyError("The good design's MTBF must be at least 1.25 times the target: closer than "
                                "that, no practical test tells them apart.")
        try:
            test = tp.sequential_mtbf_test(lo, hi, alpha_ci=alpha, producer_risk=beta)
        except ValueError as exc:
            raise _library_error(exc) from None
        out = _sequential_mtbf(tp, test, lo, hi, alpha, beta, unit_s)
        if not _blank(failures_seen) or not _blank(time_seen):
            r = _demo_count(0 if _blank(failures_seen) else failures_seen, "Failures so far", 0, 10_000)
            if _blank(time_seen):
                raise StrategyError("Give the total test time so far with the failures so far.")
            t = float(time_seen)
            if not (np.isfinite(t) and t >= 0):
                raise StrategyError("Total test time so far must be 0 or more.")
            out["decision"] = _decision(test.decide(r, t), f"{_plural(r, 'failure')} in "
                                        f"{_time_phrase(t, unit_s)} of total test time")
            out["decision"].update({"failures": r, "test_time": t})
        return out

    if _blank(reliability) or _blank(good_reliability):
        raise StrategyError("Give the reliability to demonstrate and the reliability of a good design.")
    lo = _demo_prob(reliability, "Target reliability")
    hi = _demo_prob(good_reliability, "Good design's reliability")
    if hi <= lo:
        raise StrategyError(f"The good design's reliability ({_pct(hi)}) must be above the target ({_pct(lo)}).")
    try:
        test = tp.sequential_demonstration_test(lo, hi, alpha_ci=alpha, producer_risk=beta)
    except ValueError as exc:
        raise _library_error(exc) from None
    out = _sequential_attribute(tp, test, lo, hi, alpha, beta)
    if not _blank(failures_seen) or not _blank(units_seen):
        r = _demo_count(0 if _blank(failures_seen) else failures_seen, "Failures so far", 0, 100_000)
        n = _demo_count(0 if _blank(units_seen) else units_seen, "Units tested so far", 0, _MAX_UNITS)
        if r > n:
            raise StrategyError("Failures so far can't be more than the units tested so far.")
        out["decision"] = _decision(test.decide(n, r), f"{_plural(r, 'failure')} in {_plural(n, 'unit')} tested")
        out["decision"].update({"failures": r, "units": n})
    return out


def _decision(word: str, seen: str) -> dict:
    text = {
        "accept": f"Accept: with {seen}, the test has shown the target. Stop testing.",
        "reject": f"Reject: with {seen}, the design is worse than the target. Stop testing.",
        "continue": f"Keep testing: {seen} isn't enough to decide either way yet.",
    }[word]
    return {"verdict": word, "text": text}


def _sequential_mtbf(tp, test, lo, hi, alpha, beta, unit_s) -> dict:
    table = test.to_dict()
    bounds = table["boundaries"]
    # The OC curve and the mean test time, against the design's true MTBF.
    x_lo, x_hi = lo, hi
    for _ in range(40):
        if float(test.pass_probability(x_lo)) <= _OC_TAIL:
            break
        x_lo /= 1.3
    for _ in range(40):
        if float(test.pass_probability(x_hi)) >= 1 - _OC_TAIL:
            break
        x_hi *= 1.3
    x = np.geomspace(x_lo, x_hi, _OC_POINTS)
    passes = np.atleast_1d(test.pass_probability(x))
    means = np.atleast_1d(test.expected_test_time(x))
    at_lo, at_hi = (float(v) for v in np.atleast_1d(test.expected_test_time([lo, hi])))
    fixed = tp.mtbf_demonstration_plan(lo, hi, alpha_ci=alpha, producer_risk=beta)
    fixed_time = float(fixed.test_time)
    u = f" {unit_s}" if unit_s else ""
    summary = (
        f"Run the test, adding up test time across units, and check after each failure. Accept once the total "
        f"time passes the accept line for the failures so far; reject if a failure comes before the reject "
        f"line. A good design (MTBF {_time_phrase(hi, unit_s)}) is decided after about "
        f"{_time_phrase(at_hi, unit_s)} on average, against {_time_phrase(fixed_time, unit_s)} for the "
        f"fixed-length test with the same risks. The test never runs past {_time_phrase(test.max_time, unit_s)} "
        f"or {_plural(int(test.max_failures), 'failure')}."
    )
    return {
        "method": "mtbf",
        "unit": unit_s,
        "mtbf": lo,
        "good_mtbf": hi,
        "confidence": 1 - alpha,
        "producer_risk_target": beta,
        "consumer_risk": float(test.consumer_risk),
        "producer_risk": float(test.producer_risk),
        "max_time": float(test.max_time),
        "max_failures": int(test.max_failures),
        "boundaries": {
            "x_label": f"Total test time{f' ({unit_s})' if unit_s else ''}",
            "y_label": "Failures",
            "failures": bounds["failures"],
            "accept": bounds["accept_time"],
            "reject": [None if v is None or v <= 0 else v for v in bounds["reject_time"]],
        },
        "expected": {"at_target": at_lo, "at_good": at_hi, "fixed_length": fixed_time,
                     "fixed_length_failures": int(fixed.failures)},
        "oc_curve": {
            "x_kind": "mtbf",
            "x": x.tolist(),
            "pass_probability": [float(p) for p in passes],
            "expected": [float(m) for m in means],
            "expected_label": f"Average test time{u}",
            "points": [{"label": "Target", "x": lo, "pass_probability": float(test.consumer_risk)},
                       {"label": "Good design", "x": hi, "pass_probability": 1 - float(test.producer_risk)}],
        },
        "summary": summary,
        "assumptions": [
            "Constant failure rate: only the total test time matters, not how it's split across units. Failed "
            "units are repaired or replaced and testing goes on.",
            f"A design exactly at the target passes {float(test.consumer_risk):.1%} of the time (consumer's risk, "
            f"asked for {_pct(alpha)}), and a good design fails {float(test.producer_risk):.1%} of the time "
            f"(producer's risk, asked for {_pct(beta)}). Stopping at the fixed-length test moves them a little "
            "from what was asked; these are the exact figures.",
            "A sequential test is usually much shorter than a fixed-length one, but how long it runs isn't known "
            "in advance: budget for the longest.",
        ],
    }


def _sequential_attribute(tp, test, lo, hi, alpha, beta) -> dict:
    table = test.to_dict()
    bounds = table["boundaries"]
    q_hi = 1 - lo
    for _ in range(40):
        if q_hi >= 1 - 1e-9 or float(test.pass_probability(1 - q_hi)) <= _OC_TAIL:
            break
        q_hi = min(q_hi * 1.3, 1 - 1e-9)
    q = np.linspace(q_hi / (_OC_POINTS - 1), q_hi, _OC_POINTS - 1)
    x = np.concatenate([[1.0], 1 - q])
    passes = np.concatenate([[1.0], np.atleast_1d(test.pass_probability(1 - q))])
    means = np.concatenate([[float(test.expected_units(1 - 1e-9))], np.atleast_1d(test.expected_units(1 - q))])
    at_lo, at_hi = (float(v) for v in np.atleast_1d(test.expected_units([lo, hi])))
    fixed = tp.demonstration_plan(lo, hi, alpha_ci=alpha, producer_risk=beta)
    summary = (
        f"Test units one at a time (or in small batches) and keep count. Accept once the units tested reach the "
        f"accept line for the failures so far; reject as soon as the failures reach the reject line. A good "
        f"design (reliability {_pct(hi)}) is decided after about {at_hi:,.0f} units on average, against "
        f"{int(fixed.n):,} for the fixed-length test with the same risks. The test never needs more than "
        f"{_plural(int(test.max_units), 'unit')}."
    )
    return {
        "method": "attribute",
        "unit": "",
        "reliability": lo,
        "good_reliability": hi,
        "confidence": 1 - alpha,
        "producer_risk_target": beta,
        "consumer_risk": float(test.consumer_risk),
        "producer_risk": float(test.producer_risk),
        "max_units": int(test.max_units),
        "max_failures": int(test.max_failures),
        "boundaries": {
            "x_label": "Units tested",
            "y_label": "Failures",
            "units": bounds["units"],
            "accept": [None if v < 0 else v for v in bounds["accept_failures"]],
            "reject": bounds["reject_failures"],
        },
        "expected": {"at_target": at_lo, "at_good": at_hi, "fixed_length": int(fixed.n),
                     "fixed_length_failures": int(fixed.failures)},
        "oc_curve": {
            "x_kind": "reliability",
            "x": x.tolist(),
            "pass_probability": [float(p) for p in passes],
            "expected": [float(m) for m in means],
            "expected_label": "Average units tested",
            "points": [{"label": "Target", "x": lo, "pass_probability": float(test.consumer_risk)},
                       {"label": "Good design", "x": hi, "pass_probability": 1 - float(test.producer_risk)}],
        },
        "summary": summary,
        "assumptions": [
            "Each unit passes or fails its mission independently, with the same chance (a binomial test); "
            "test units are representative of production.",
            f"A design exactly at the target passes {float(test.consumer_risk):.1%} of the time (consumer's risk, "
            f"asked for {_pct(alpha)}), and a good design fails {float(test.producer_risk):.1%} of the time "
            f"(producer's risk, asked for {_pct(beta)}). These are the exact figures for the test as run.",
            "Accepting needs a run of units without failures first: no test can accept before the accept line "
            "starts.",
        ],
    }


# ---------------------------------------------------------------------------
# Shared inputs: a distribution's planning values
# ---------------------------------------------------------------------------

def _distribution(distribution) -> tuple[str, Any]:
    import surpyval

    d = (distribution or "weibull").strip().lower()
    if d not in DISTRIBUTIONS:
        raise StrategyError("distribution must be 'weibull' or 'lognormal'.")
    return d, surpyval.Weibull if d == "weibull" else surpyval.LogNormal


def _params(d: str, params) -> tuple[float, float]:
    """``params`` as [{name, value}] (the app's way), a {name: value} dict or
    a pair, in SurPyval's order."""
    names = _PARAM_NAMES[d]
    if isinstance(params, dict):
        values = [params.get(n) for n in names]
    elif isinstance(params, (list, tuple)) and params and isinstance(params[0], dict):
        by = {str(p.get("name")): p.get("value") for p in params}
        values = [by.get(n) for n in names]
    elif isinstance(params, (list, tuple)):
        values = list(params)
    else:
        values = []
    if len(values) != 2 or any(_blank(v) for v in values):
        raise StrategyError(f"Give the planning values {names[0]} and {names[1]}.")
    try:
        a, b = float(values[0]), float(values[1])
    except (TypeError, ValueError):
        raise StrategyError(f"{names[0]} and {names[1]} must be numbers.") from None
    if not (np.isfinite(a) and np.isfinite(b)) or b <= 0 or (d == "weibull" and a <= 0):
        raise StrategyError(f"{names[0]} and {names[1]} must be positive numbers." if d == "weibull" else
                            "sigma must be a positive number and mu a number.")
    if d == "weibull" and b > _MAX_SHAPE:
        raise StrategyError(f"beta must be at most {_MAX_SHAPE:g}.")
    return a, b


def _quantity(quantity, b_life) -> tuple[Optional[float], str]:
    """The quantity estimated: ``(p, label)``; p is None for the mean."""
    q = (quantity or "b_life").strip().lower()
    if q == "mean":
        return None, "the mean life"
    if q not in ("b_life", "quantile"):
        raise StrategyError("quantity must be 'b_life' or 'mean'.")
    pct = 10.0 if _blank(b_life) else float(b_life)
    if not (0 < pct < 100):
        raise StrategyError("The B-life must be between 0 and 100 (10 for B10).")
    return pct / 100.0, f"B{pct:g}"


def _precision_factor(within) -> float:
    """"Within ±20%" as a precision factor: 1.2."""
    pct = _demo_positive(within, "Precision (within ± %)", 1000.0)
    return 1.0 + pct / 100.0


# ---------------------------------------------------------------------------
# Life tests: estimation precision
# ---------------------------------------------------------------------------

def life_test(
    solve_for: str = "precision",
    distribution: str = "weibull",
    params=None,
    units=None,
    precision=None,
    test_end: str = "time",
    censor_time=None,
    failure_fraction=None,
    quantity: str = "b_life",
    b_life=10,
    confidence=0.9,
    unit: Optional[str] = None,
) -> dict:
    """How precisely a life test estimates a B-life or the mean life, from
    planning values of a Weibull or lognormal.

    ``solve_for``: ``precision`` (of ``units`` units), ``units`` (the fewest
    for a ``precision``, given as "within ± %") or ``length`` (how long
    ``units`` units must run for a ``precision``). ``test_end``: ``time``
    (stop at ``censor_time``), ``failures`` (stop when ``failure_fraction``
    of the units have failed; for ``length``, at a failure) or ``all``
    (run every unit to failure).
    """
    from surpyval import test_planning as tp

    solve_for = (solve_for or "precision").strip().lower()
    if solve_for not in ("precision", "units", "length"):
        raise StrategyError("solve_for must be 'precision', 'units' or 'length'.")
    d, dist = _distribution(distribution)
    pv = _params(d, params)
    p, what = _quantity(quantity, b_life)
    alpha = _alpha(confidence)
    unit_s = (unit or "").strip()
    end = (test_end or "time").strip().lower()
    if end not in ("time", "failures", "all"):
        raise StrategyError("test_end must be 'time', 'failures' or 'all'.")
    kw = {"p": p if p is not None else 0.1, "quantity": "mean" if p is None else "quantile", "alpha_ci": alpha}

    def stop_args() -> dict:
        if end == "time":
            if _blank(censor_time):
                raise StrategyError("Give the test length (when the test stops).")
            return {"censor_time": _demo_positive(censor_time, "Test length")}
        return {}

    def share_failed() -> float:
        if _blank(failure_fraction):
            raise StrategyError("Give the share of units failed when the test stops (e.g. 50%).")
        try:
            v = float(failure_fraction)
        except (TypeError, ValueError):
            raise StrategyError("The share failed must be a number between 0 and 1.") from None
        if not 0 < v <= 1:
            raise StrategyError("The share failed must be above 0 and at most 1 (e.g. 0.5).")
        return v

    try:
        if solve_for == "precision":
            n = _demo_count(units, "Units on test", 2, _MAX_UNITS)
            args = stop_args()
            if end == "failures":
                args = {"failures": max(1, int(np.ceil(share_failed() * n - 1e-9)))}
            plan = tp.life_test_precision(dist, pv, n, **args, **kw)
        elif solve_for == "units":
            R = _precision_factor(precision)
            args = stop_args()
            if end == "failures":
                args = {"failure_fraction": share_failed()}
            plan = tp.life_test_sample_size(dist, pv, R, **args, **kw)
            if plan.n > _MAX_UNITS:
                raise StrategyError(f"That precision needs {plan.n:,} units: aim for a looser precision.")
        else:
            if end == "all":
                raise StrategyError("To solve for the test length, the test stops at a time or at a failure.")
            n = _demo_count(units, "Units on test", 2, _MAX_UNITS)
            R = _precision_factor(precision)
            plan = tp.life_test_length(dist, pv, n, R, failure_censored=end == "failures", **kw)
    except ValueError as exc:
        raise _library_error(exc) from None

    out = plan.to_dict()
    out.pop("result", None)
    out.pop("non_finite", None)
    lower, upper = plan.estimate / plan.precision, plan.estimate * plan.precision
    within = plan.precision - 1
    stops = (f"stops at {_time_phrase(plan.censor_time, unit_s)}" if plan.censor_time is not None else
             f"stops at failure {plan.failures}" if plan.failures is not None else "runs until every unit fails")
    summary = (
        f"Test {_plural(plan.n, 'unit')}; the test {stops} and expects about {plan.expected_failures:.1f} "
        f"failures. It estimates {what} ({_time_phrase(plan.estimate, unit_s)} on these planning values) to "
        f"within a factor of {plan.precision:.3g} at {_pct(1 - alpha)} confidence: the interval will be about "
        f"{_time_phrase(lower, unit_s)} to {_time_phrase(upper, unit_s)}, roughly ±{within:.0%}."
    )
    assumptions = [
        f"The planning values ({_PARAM_NAMES[d][0]} = {fmt_num(pv[0])}, {_PARAM_NAMES[d][1]} = {fmt_num(pv[1])}) "
        "are your best guess before the test. The shape matters most: take it from earlier tests or a similar part.",
        "The precision is a large-sample approximation. With few failures (under about 10) it can be optimistic: "
        "check it by simulation (Pro).",
        "Units are tested under use conditions and failures are independent.",
    ]
    # Precision against the units on test: where more units stop paying.
    curve = _life_curve(tp, dist, pv, plan, end, kw)
    out.update({
        "solve_for": solve_for,
        "distribution_id": d,
        "unit": unit_s,
        "quantity": "mean" if p is None else "b_life",
        "b_life": None if p is None else p * 100,
        "label": what,
        "confidence": 1 - alpha,
        "interval": [lower, upper],
        "test_end": end,
        "summary": summary,
        "assumptions": assumptions,
        "curve": curve,
    })
    return out


def _life_curve(tp, dist, pv, plan, end, kw) -> dict:
    n0 = plan.n
    grid = np.geomspace(max(2, n0 // 4), max(8, n0 * 4), _CURVE_POINTS).round()
    ns = sorted({int(v) for v in grid} | {n0})
    values = []
    for n in ns:
        args: dict = {}
        if plan.censor_time is not None:
            args["censor_time"] = plan.censor_time
        elif plan.failures is not None:
            args["failures"] = max(1, min(n, int(round(plan.failures / plan.n * n))))
        try:
            values.append(float(tp.life_test_precision(dist, pv, n, **args, **kw).precision))
        except ValueError:
            values.append(None)
    return {"x_label": "Units on test", "y_label": "Precision factor", "x": ns, "precision": values,
            "selected": n0}


# ---------------------------------------------------------------------------
# Accelerated life tests
# ---------------------------------------------------------------------------

def _life_model(life_model):
    from backend.alt import LIFE_MODELS

    lm = (life_model or "arrhenius").strip().lower()
    if lm not in ALT_LIFE_MODELS:
        raise StrategyError(f"life_model must be one of: {', '.join(ALT_LIFE_MODELS)}.")
    entry = LIFE_MODELS[lm]
    return lm, entry["model"], entry["name"]


def _life_values(model, life_params) -> dict:
    names = sorted(model.phi_param_map, key=model.phi_param_map.get)
    if isinstance(life_params, dict):
        by = life_params
    elif isinstance(life_params, (list, tuple)) and life_params and isinstance(life_params[0], dict):
        by = {str(p.get("name")): p.get("value") for p in life_params}
    elif isinstance(life_params, (list, tuple)) and len(life_params) == len(names):
        by = dict(zip(names, life_params))
    else:
        by = {}
    out = {}
    for n in names:
        v = by.get(n)
        if _blank(v):
            raise StrategyError(f"Give the life model's planning values: {', '.join(names)}.")
        try:
            out[n] = float(v)
        except (TypeError, ValueError):
            raise StrategyError(f"The life model's {n} must be a number.") from None
        if not np.isfinite(out[n]):
            raise StrategyError(f"The life model's {n} must be a finite number.")
    return out


def _stress(value, label: str) -> float:
    try:
        v = float(value)
    except (TypeError, ValueError):
        raise StrategyError(f"{label} must be a number.") from None
    if not np.isfinite(v):
        raise StrategyError(f"{label} must be a finite number.")
    return v


def accelerated_test(
    mode: str = "plan",
    distribution: str = "weibull",
    life_model: str = "arrhenius",
    life_params=None,
    shape=None,
    use_stress=None,
    high_stress=None,
    units=None,
    censor_time=None,
    levels=2,
    allocation=None,
    middle_fraction=0.2,
    stresses=None,
    units_at=None,
    b_life=10,
    confidence=0.9,
    unit: Optional[str] = None,
    stress_unit: Optional[str] = None,
) -> dict:
    """An accelerated life test: ``mode='plan'`` finds the lowest stress and
    the units at each (``levels`` stresses up to ``high_stress``; 2 is the
    optimum plan, 3 or more a compromise plan with ``middle_fraction`` of the
    units in between, or fixed shares in ``allocation``); ``mode='check'``
    gives the precision of the test you propose (``stresses`` and
    ``units_at``)."""
    from surpyval import test_planning as tp

    mode = (mode or "plan").strip().lower()
    if mode not in ("plan", "check"):
        raise StrategyError("mode must be 'plan' or 'check'.")
    d, dist = _distribution(distribution)
    lm, model, lm_name = _life_model(life_model)
    lp = _life_values(model, life_params)
    if _blank(shape):
        raise StrategyError("Give the planning value of the shape (Weibull beta, or lognormal sigma).")
    sh = _demo_positive(shape, "Shape", _MAX_SHAPE)
    if _blank(use_stress):
        raise StrategyError("Give the use stress: the stress the life is estimated at.")
    use = _stress(use_stress, "Use stress")
    if _blank(censor_time):
        raise StrategyError("Give the test length (when the test stops).")
    tc = _demo_positive(censor_time, "Test length")
    p, what = _quantity("b_life", b_life)
    alpha = _alpha(confidence)
    unit_s, su = (unit or "").strip(), (stress_unit or "").strip()
    common = dict(use_stress=use, censor_time=tc, p=p, alpha_ci=alpha)
    alternatives = []
    try:
        if mode == "plan":
            if _blank(high_stress):
                raise StrategyError("Give the highest stress the test may use.")
            hi = _stress(high_stress, "Highest stress")
            n = _demo_count(units, "Units on test", 2, 100_000)
            k = _demo_count(2 if _blank(levels) else levels, "Stress levels", 2, 6)
            shares = None
            if not _blank(allocation):
                if not isinstance(allocation, (list, tuple)) or len(allocation) != k:
                    raise StrategyError(f"Give one share per stress level ({k}), lowest stress first.")
                shares = [_demo_positive(a, "Share of units") for a in allocation]
                total = sum(shares)
                shares = [s / total for s in shares]
            mf = 0.2 if _blank(middle_fraction) else _demo_prob(middle_fraction, "Share at the middle stresses")
            plan = tp.accelerated_test_plan(dist, model, lp, sh, high_stress=hi, n=n, levels=k, allocation=shares,
                                            middle_fraction=mf, **common)
            if shares is None:
                for other in sorted({2, 3} - {k}):
                    alt = tp.accelerated_test_plan(dist, model, lp, sh, high_stress=hi, n=n, levels=other,
                                                   middle_fraction=mf, **common)
                    alternatives.append({"levels": other, "precision": float(alt.precision),
                                         "stresses": list(alt.stresses), "units": list(alt.units)})
        else:
            if not isinstance(stresses, (list, tuple)) or not isinstance(units_at, (list, tuple)) or not stresses:
                raise StrategyError("Give the test stresses and the units at each.")
            if len(stresses) != len(units_at):
                raise StrategyError("Give one unit count per test stress.")
            if len(stresses) > 10:
                raise StrategyError("A test takes up to 10 stresses.")
            levels_ = [_stress(s, "Test stress") for s in stresses]
            counts = [_demo_count(u, "Units at a stress", 0, 100_000) for u in units_at]
            plan = tp.accelerated_test_precision(dist, model, lp, sh, stresses=levels_, units=counts, **common)
    except ValueError as exc:
        raise _library_error(exc) from None

    out = plan.to_dict()
    out.pop("result", None)
    out.pop("non_finite", None)
    s_txt = (lambda v: f"{fmt_num(v)} {su}".strip())
    rows = [{"stress": float(s), "units": int(u), "share": float(u) / max(1, sum(plan.units)),
             "expected_failures": float(f)}
            for s, u, f in zip(plan.stresses, plan.units, plan.expected_failures)]
    expected = sum(plan.expected_failures)
    lower, upper = plan.estimate / plan.precision, plan.estimate * plan.precision
    lead = ("Test " + ", ".join(f"{r['units']} at {s_txt(r['stress'])}" for r in rows) +
            f", each for {_time_phrase(tc, unit_s)}.")
    summary = (
        f"{lead} Expect about {expected:.1f} failures in all. The test estimates {what} at the use stress "
        f"({s_txt(use)}: {_time_phrase(plan.estimate, unit_s)} on these planning values) to within a factor of "
        f"{plan.precision:.3g} at {_pct(1 - alpha)} confidence, about {_time_phrase(lower, unit_s)} to "
        f"{_time_phrase(upper, unit_s)}."
    )
    warnings = []
    few = [r for r in rows if r["units"] and r["expected_failures"] < 3]
    if few:
        warnings.append(
            "Some stresses expect fewer than 3 failures (" + ", ".join(s_txt(r["stress"]) for r in few) + "): "
            "the fit leans on the other stresses. Test longer, or check the plan by simulation (Pro).")
    if expected < 10:
        warnings.append(f"About {expected:.1f} failures in all is few: the precision above is optimistic. "
                        "Check it by simulation (Pro).")
    assumptions = [
        f"The {lm_name} life-stress model holds from the use stress up to the highest test stress, with the same "
        "failure mechanism throughout. Choose the highest stress below where a new mechanism could start.",
        "The shape (Weibull beta or lognormal sigma) is the same at every stress.",
        "Planning values are your best guess before the test: a similar part's ALT fit is a good source.",
        "The precision is a large-sample approximation from the test's expected information.",
    ]
    if mode == "plan" and plan.stresses and len(plan.stresses) == 2:
        assumptions.append("Two stresses is the most precise plan if the model is right, but it can't show the "
                           "model is wrong: a three-level compromise plan gives that up for a little precision.")
    out.update({
        "mode": mode,
        "distribution_id": d,
        "life_model_id": lm,
        "life_model_name": lm_name,
        "unit": unit_s,
        "stress_unit": su,
        "b_life": p * 100,
        "label": what,
        "confidence": 1 - alpha,
        "rows": rows,
        "total_expected_failures": float(expected),
        "interval": [lower, upper],
        "alternatives": alternatives,
        "warnings": warnings,
        "summary": summary,
        "assumptions": assumptions,
    })
    return out


# ---------------------------------------------------------------------------
# Comparison: did the change work?
# ---------------------------------------------------------------------------

def comparison(
    kind: str = "logrank",
    solve_for: str = "sample_size",
    hazard_ratio=None,
    event_probability=None,
    units_per_group=None,
    allocation_ratio=1.0,
    power=0.8,
    confidence=0.95,
    one_sided=False,
    failures_before=None,
    exposure_before=None,
    exposure_after=None,
    rate_ratio=None,
    unit: Optional[str] = None,
) -> dict:
    """Plan a comparison.

    ``kind='logrank'``: two groups (old and new design) followed together.
    ``solve_for='sample_size'`` gives the events and units per group to
    detect ``hazard_ratio`` (new over old) with ``power``; ``'power'`` the
    chance ``units_per_group`` detects it. ``event_probability``: the chance
    a unit fails during the study.

    ``kind='rate_ratio'``: one fleet's failure rate before and after a
    change, from ``failures_before`` in ``exposure_before``.
    ``solve_for='exposure'`` gives the exposure after the change needed to
    detect ``rate_ratio`` (after over before); ``'detectable'`` the smallest
    reduction ``exposure_after`` can detect; ``'power'`` the chance it
    detects ``rate_ratio``.
    """
    from surpyval import test_planning as tp

    kind = (kind or "logrank").strip().lower()
    alpha = _alpha(0.95 if _blank(confidence) else confidence)
    pw = _demo_prob(0.8 if _blank(power) else power, "Power")
    alternative = "one-sided" if one_sided else "two-sided"
    unit_s = (unit or "").strip()
    try:
        if kind == "logrank":
            return _logrank(tp, solve_for, hazard_ratio, event_probability, units_per_group, allocation_ratio,
                            pw, alpha, alternative)
        if kind == "rate_ratio":
            return _rate_ratio(tp, solve_for, failures_before, exposure_before, exposure_after, rate_ratio, pw,
                               alpha, alternative, unit_s)
    except ValueError as exc:
        raise _library_error(exc) from None
    raise StrategyError("kind must be 'logrank' or 'rate_ratio'.")


def _logrank(tp, solve_for, hazard_ratio, event_probability, units_per_group, allocation_ratio, pw, alpha,
             alternative) -> dict:
    solve_for = (solve_for or "sample_size").strip().lower()
    if solve_for not in ("sample_size", "power"):
        raise StrategyError("solve_for must be 'sample_size' or 'power' for a log-rank comparison.")
    if _blank(hazard_ratio):
        raise StrategyError("Give the hazard ratio to detect (new design's failure rate over the old's, e.g. 0.6).")
    hr = _demo_positive(hazard_ratio, "Hazard ratio", 100.0)
    if abs(hr - 1.0) < 1e-6:
        raise StrategyError("A hazard ratio of 1 is no change: give the change to detect (e.g. 0.6).")
    if _blank(event_probability):
        raise StrategyError("Give the chance a unit fails during the study (e.g. 50%).")
    pe = _demo_prob(event_probability, "Chance a unit fails during the study") if float(
        event_probability) < 1 else 1.0
    ratio = 1.0 if _blank(allocation_ratio) else _demo_positive(allocation_ratio, "Units in the new group per old",
                                                                100.0)
    events = int(tp.logrank_events(hr, pw, alpha_ci=alpha, ratio=ratio, alternative=alternative))
    change = f"{abs(1 - hr):.0%} {'lower' if hr < 1 else 'higher'}"
    if solve_for == "sample_size":
        n1, n2 = (int(v) for v in tp.logrank_sample_size(hr, pe, pw, alpha_ci=alpha, ratio=ratio,
                                                           alternative=alternative))
        power_now = float(tp.logrank_power(hr, (n1, n2), pe, alpha_ci=alpha, alternative=alternative))
        summary = (
            f"To detect a failure rate {change} in the new design (a hazard ratio of {fmt_num(hr)}) with "
            f"{pw:.0%} power at {_pct(1 - alpha)} confidence, you need about {events:,} failures in all: "
            f"{n1:,} new and {n2:,} old units, if {pe:.0%} of units fail during the study."
        )
    else:
        if _blank(units_per_group):
            raise StrategyError("Give the units in each group.")
        n2 = _demo_count(units_per_group, "Units per group", 2, _MAX_UNITS)
        n1 = max(2, int(round(ratio * n2)))
        power_now = float(tp.logrank_power(hr, (n1, n2), pe, alpha_ci=alpha, alternative=alternative))
        summary = (
            f"With {n1:,} new and {n2:,} old units, and {pe:.0%} of them failing during the study, a log-rank test "
            f"detects a failure rate {change} (hazard ratio {fmt_num(hr)}) {power_now:.0%} of the time at "
            f"{_pct(1 - alpha)} confidence."
            + ("" if power_now >= 0.8 else " That's below the usual 80%: more units, or a longer study (more "
                                           "failures), would help.")
        )
    # Power against units per group, for the chart.
    top = max(8, int(n2 * 3))
    xs = sorted({int(v) for v in np.unique(np.geomspace(2, top, _CURVE_POINTS).round())} | {n2})
    curve = [float(tp.logrank_power(hr, (max(2, int(round(ratio * x))), x), pe, alpha_ci=alpha,
                                    alternative=alternative)) for x in xs]
    return {
        "kind": "logrank",
        "solve_for": solve_for,
        "hazard_ratio": hr,
        "event_probability": pe,
        "allocation_ratio": ratio,
        "power_target": pw,
        "confidence": 1 - alpha,
        "alternative": alternative,
        "events": events,
        "units_new": n1,
        "units_old": n2,
        "power": power_now,
        "summary": summary,
        "assumptions": [
            "Old and new units run side by side over the same period, and are alike apart from the change.",
            "The change scales the failure rate by the same factor at every age (proportional hazards).",
            "The number of failures drives the answer, not the units: the units are the failures divided by the "
            "chance of a failure during the study.",
        ],
        "curve": {"x_label": "Units per group (old)", "y_label": "Power", "x": xs, "power": curve,
                  "selected": n2, "target": pw},
    }


def _rate_ratio(tp, solve_for, failures_before, exposure_before, exposure_after, rate_ratio, pw, alpha,
                alternative, unit_s) -> dict:
    solve_for = (solve_for or "exposure").strip().lower()
    if solve_for not in ("exposure", "detectable", "power"):
        raise StrategyError("solve_for must be 'exposure', 'detectable' or 'power' for a failure-rate comparison.")
    if _blank(failures_before) or _blank(exposure_before):
        raise StrategyError("Give the failures before the change and the operating time they came in.")
    nb = _demo_count(failures_before, "Failures before the change", 1, 1_000_000)
    eb = _demo_positive(exposure_before, "Operating time before the change")
    rate = nb / eb
    ratio = None
    if solve_for in ("exposure", "power"):
        if _blank(rate_ratio):
            raise StrategyError("Give the change to detect: the failure rate after over before (0.5 halves it).")
        ratio = _demo_positive(rate_ratio, "Rate after over before", 100.0)
        if abs(ratio - 1.0) < 1e-6:
            raise StrategyError("A ratio of 1 is no change: give the change to detect (0.5 halves the rate).")
    ea = None if _blank(exposure_after) else _demo_positive(exposure_after, "Operating time after the change")
    kw = {"alpha_ci": alpha, "alternative": alternative}
    t = (lambda v: _time_phrase(v, unit_s))
    seen = f"{_plural(nb, 'failure')} in {t(eb)} before the change"
    out: dict = {"kind": "rate_ratio", "solve_for": solve_for, "unit": unit_s, "failures_before": nb,
                 "exposure_before": eb, "rate_before": rate, "power_target": pw, "confidence": 1 - alpha,
                 "alternative": alternative, "rate_ratio": ratio}
    if solve_for == "exposure":
        need = float(tp.rate_ratio_exposure(ratio, rate, eb, pw, **kw))
        out["exposure_after"] = need if np.isfinite(need) else None
        change = f"a {abs(1 - ratio):.0%} {'drop' if ratio < 1 else 'rise'} in the failure rate"
        if np.isfinite(need):
            out["summary"] = (
                f"With {seen}, you need about {t(need)} of operation after it to detect {change} with {pw:.0%} "
                f"power at {_pct(1 - alpha)} confidence. Expect about {need * rate * ratio:.1f} failures in that "
                "time if the change works.")
        else:
            out["summary"] = (
                f"With {seen}, no amount of operation after the change can detect {change} with {pw:.0%} power: "
                "the failures before it leave too much doubt about the old rate. Collect more history before the "
                "change, or look for a bigger change.")
            out["note"] = "exposure_after is null: no finite exposure reaches the power."
        ea_curve = need if np.isfinite(need) else eb
    elif solve_for == "detectable":
        if ea is None:
            raise StrategyError("Give the operating time after the change.")
        r = float(tp.rate_ratio_detectable(rate, eb, ea, pw, **kw))
        out["exposure_after"] = ea
        out["detectable_ratio"] = r if np.isfinite(r) else None
        if np.isfinite(r) and r > 0:
            out["summary"] = (
                f"With {seen} and {t(ea)} after it, the smallest drop you can reliably detect ({pw:.0%} power, "
                f"{_pct(1 - alpha)} confidence) is {1 - r:.0%}: the failure rate falling to {r:.2f} times the old. "
                "Smaller improvements may be real but won't show clearly.")
        else:
            out["summary"] = (f"With {seen} and {t(ea)} after it, no drop in the failure rate can be detected "
                              f"with {pw:.0%} power. Run longer after the change.")
        ea_curve = ea
    else:
        if ea is None:
            raise StrategyError("Give the operating time after the change.")
        pwr = float(tp.rate_ratio_power(ratio, rate, eb, ea, **kw))
        out["exposure_after"] = ea
        out["power"] = pwr
        out["summary"] = (
            f"With {seen} and {t(ea)} after it, the test detects a failure rate {abs(1 - ratio):.0%} "
            f"{'lower' if ratio < 1 else 'higher'} {pwr:.0%} of the time at {_pct(1 - alpha)} confidence.")
        ea_curve = ea
    xs = np.geomspace(max(ea_curve / 10, eb / 100), max(ea_curve * 4, eb), _CURVE_POINTS)
    if ratio is not None:
        ys = np.atleast_1d(tp.rate_ratio_power(ratio, rate, eb, xs, **kw))
        out["curve"] = {"x_label": f"Operating time after the change{f' ({unit_s})' if unit_s else ''}",
                        "y_label": "Power", "x": xs.tolist(), "power": [float(v) for v in ys],
                        "selected": out.get("exposure_after"), "target": pw}
    else:
        ys = np.atleast_1d(tp.rate_ratio_detectable(rate, eb, xs, pw, **kw))
        out["curve"] = {"x_label": f"Operating time after the change{f' ({unit_s})' if unit_s else ''}",
                        "y_label": "Smallest detectable drop", "x": xs.tolist(),
                        "detectable_drop": [None if not np.isfinite(v) else float(1 - v) for v in ys],
                        "selected": ea}
    out["assumptions"] = [
        "Failures come at a steady rate before the change and a (possibly different) steady rate after it: no "
        "wear-out trend over the period.",
        "The exact conditional test of two Poisson rates (the test the Repairable systems pages run), not a "
        "normal approximation, so it holds for the few failures a change is usually judged on.",
        "Operating time is the fleet's total: ten units for 100 hours is 1,000 hours.",
    ]
    return out


# ---------------------------------------------------------------------------
# Simulation check (Pro, a compute job)
# ---------------------------------------------------------------------------

def simulation_request(kind: str, inputs: dict, n_sim=None, seed=None) -> dict:
    """A self-contained simulation request: the plan's inputs (checked now,
    by planning it, so a bad request fails before it's queued), the number
    of simulated tests and the seed."""
    kind = (kind or "").strip().lower()
    if kind not in SIM_DEFAULT:
        raise StrategyError("kind must be 'life' or 'accelerated'.")
    if not isinstance(inputs, dict):
        raise StrategyError("inputs must be the plan's inputs.")
    n = SIM_DEFAULT[kind] if _blank(n_sim) else _demo_count(n_sim, "Simulated tests", 20, SIM_MAX[kind])
    clean = {k: v for k, v in inputs.items() if k in _SIM_INPUTS[kind]}
    _plan_for(kind, clean)  # refuses bad inputs here, not on the compute service
    return {"kind": kind, "inputs": clean, "n_sim": n, "seed": SIM_SEED if _blank(seed) else int(seed)}


_SIM_INPUTS = {
    "life": ("solve_for", "distribution", "params", "units", "precision", "test_end", "censor_time",
             "failure_fraction", "quantity", "b_life", "confidence", "unit"),
    "accelerated": ("mode", "distribution", "life_model", "life_params", "shape", "use_stress", "high_stress",
                    "units", "censor_time", "levels", "allocation", "middle_fraction", "stresses", "units_at",
                    "b_life", "confidence", "unit", "stress_unit"),
}


def _plan_for(kind: str, inputs: dict):
    """The library plan object (it has ``simulate``) for checked inputs."""
    import surpyval
    from surpyval import test_planning as tp

    out = (life_test if kind == "life" else accelerated_test)(**inputs)
    alpha = 1 - out["confidence"]
    if kind == "life":
        dist = getattr(surpyval, out["distribution"])
        kw = {"p": (out["p"] if out["p"] is not None else 0.1), "alpha_ci": alpha,
              "quantity": "mean" if out["p"] is None else "quantile"}
        args = ({"censor_time": out["censor_time"]} if out["censor_time"] is not None else
                {"failures": out["failures"]} if out["failures"] is not None else {})
        return out, tp.life_test_precision(dist, tuple(out["params"]), out["n"], **args, **kw)
    _, model, _ = _life_model(out["life_model_id"])
    dist = getattr(surpyval, out["distribution"])
    plan = tp.accelerated_test_precision(dist, model, out["life_params"], out["shape"], use_stress=out["use_stress"],
                                         stresses=out["stresses"], units=out["units"], censor_time=out["censor_time"],
                                         p=out["p"], alpha_ci=alpha)
    return out, plan


def simulate_precision(request: dict) -> dict:
    """Run a :func:`simulation_request`: simulate the planned test, refit each
    simulated data set, and compare the estimates' spread with the plan's
    large-sample precision. Runs on the compute service (or in-process)."""
    if not isinstance(request, dict):
        raise StrategyError("The request must be an object.")
    kind = request.get("kind")
    if kind not in SIM_DEFAULT:
        raise StrategyError("kind must be 'life' or 'accelerated'.")
    out, plan = _plan_for(kind, request.get("inputs") or {})
    n_sim = int(request.get("n_sim") or SIM_DEFAULT[kind])
    sim = plan.simulate(min(n_sim, SIM_MAX[kind]), random_state=int(request.get("seed") or SIM_SEED))
    planned = float(plan.precision)
    got = sim.precision
    usable = sim.n_sim - sim.unusable
    if got is None or not np.isfinite(got):
        text = (f"Too few of the {sim.n_sim:,} simulated tests had enough failures to fit "
                f"({usable:,} did): the test is too small or too short to estimate anything reliably.")
    else:
        verdict = ("The plan holds up" if got <= planned * 1.1 else
                   "The plan is optimistic: the real precision is worse than the approximation says")
        text = (f"{verdict}. Across {usable:,} simulated tests the estimates spread by a factor of {got:.3g} "
                f"(the plan says {planned:.3g}), and {sim.within:.0%} landed within the planned factor of the "
                f"true value (about {out['confidence']:.0%} if the plan holds).")
        if sim.unusable:
            text += f" {_plural(sim.unusable, 'simulated test')} had too few failures to fit."
    return {
        "kind": kind,
        "simulated": sim.to_dict(),
        "planned_precision": planned,
        "summary": text,
    }
