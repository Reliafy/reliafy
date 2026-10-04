"""Decision-support tools for reliability engineering ("Strategy").

Built on SurPyval + RePyability:

* ``optimal_replacement`` — the age-based preventive-replacement interval that
  minimises the long-run cost rate given planned vs. unplanned costs, with the
  saving versus a run-to-failure policy.
* ``compare_two`` — put two models side by side on the decision metrics.
* ``failure_finding`` — the inspection interval for a hidden failure.
"""

from __future__ import annotations

from typing import Optional

import numpy as np
import pandas as pd

from backend.fitting import DISTRIBUTIONS, FitError, param_values, surpyval_extras
from repyability.non_repairable import NonRepairable
from surpyval import KaplanMeier, logrank

_GRID_POINTS = 200
_EPS = 1e-12
_TRAPZ = getattr(np, "trapezoid", None) or np.trapz


class StrategyError(ValueError):
    """Raised when a strategy tool can't be run with the given inputs."""


def _clean(arr) -> list:
    out = []
    for v in np.atleast_1d(np.asarray(arr, dtype=float)):
        out.append(float(v) if np.isfinite(v) else None)
    return out


def fmt_num(value) -> str:
    """A number for a sentence: 3 significant figures, with thousands
    separators for everyday magnitudes (whole units from 1,000) and scientific
    notation for very small or large ones — never rounded to "0" as a fixed
    ``,.0f`` would ("check about every 0 hours")."""
    v = float(value)
    if not np.isfinite(v) or v == 0:
        return f"{v:g}"
    if abs(v) < 1e-3 or abs(v) >= 1e9:
        return f"{v:.3g}"
    if abs(float(f"{v:.3g}")) >= 1000:
        return f"{v:,.0f}"
    return f"{v:.3g}"


def _scalar(value) -> Optional[float]:
    try:
        v = float(np.atleast_1d(value)[0])
        return v if np.isfinite(v) else None
    except Exception:
        return None


def _life_metrics(model) -> dict:
    """B10 / median / MTTF for a fitted model (the numbers engineers quote)."""
    metrics = {"b10": None, "median": None, "mttf": None}
    try:
        metrics["b10"] = _scalar(model.qf(0.10))
    except Exception:
        pass
    try:
        metrics["median"] = _scalar(model.qf(0.50))
    except Exception:
        pass
    try:
        metrics["mttf"] = _scalar(model.mean())
    except Exception:
        pass
    return metrics


def _model_from_params(distribution_id: str, params: list, extras: dict | None = None):
    entry = DISTRIBUTIONS.get(distribution_id)
    if entry is None:
        raise StrategyError(
            f"'{distribution_id}' isn't a supported parametric distribution."
        )
    dist = entry["dist"]
    if not params:
        raise StrategyError("The model is missing its parameters.")
    try:
        # By SurPyval name; an unrecognised name is refused, never read by position.
        values = param_values(distribution_id, params)
    except FitError as exc:
        raise StrategyError(str(exc)) from None
    # Extra fitted quantities from fit options (offset gamma, LFP p, ZI f0)
    # rebuild the model exactly as it was fitted (LFP p is SurPyval's lfp_p).
    try:
        return dist.from_params(values, **surpyval_extras(extras)), entry["name"]
    except Exception as exc:
        raise StrategyError(str(exc)) from exc


def optimal_replacement(
    distribution_id: str,
    params: list,
    planned_cost: Optional[float],
    unplanned_cost: Optional[float],
    unit: Optional[str] = None,
    extras: Optional[dict] = None,
) -> dict:
    """Age-based preventive-replacement interval that minimises the cost rate.

    ``planned_cost`` (cp) is the cost of a planned replacement, ``unplanned_cost``
    (cu) the cost of an unplanned (failure) replacement; cp must be < cu.
    """
    if planned_cost is None or unplanned_cost is None:
        raise StrategyError("Enter both the planned and unplanned costs.")
    cp, cu = float(planned_cost), float(unplanned_cost)
    if cp < 0 or cu < 0:
        raise StrategyError("Costs must be non-negative.")
    if cp >= cu:
        raise StrategyError("The planned cost must be less than the unplanned cost.")

    model, name = _model_from_params(distribution_id, params, extras)
    # A limited failure population: a fraction 1 - p never fails. RePyability
    # (0.9+) handles it: no replacement age beats running to failure, whose
    # long-run cost rate is 0 — the units still running are, more and more,
    # the ones that never will fail.
    # Read as the model was built (``p`` or SurPyval 0.23's ``lfp_p``).
    p_fail = surpyval_extras(extras).get("lfp_p", 1.0)
    lfp = p_fail < 1.0
    nr = NonRepairable(model)
    nr.set_costs_planned_and_unplanned(cp, cu)

    try:
        t_opt = _scalar(nr.find_optimal_replacement())
    except Exception:
        t_opt = None

    mttf = None if lfp else _scalar(model.mean())
    if lfp:
        rtf_rate = 0.0
    else:
        rtf_rate = cu / mttf if mttf and mttf > 0 else None

    # Time grid for the cost-rate curve: focus around the optimum / 95th pct
    # (of the units that fail, for a limited failure population).
    try:
        hi = _scalar(model.qf(0.95 * p_fail))
    except Exception:
        hi = None
    hi = hi or (mttf * 2 if mttf else 1.0)
    if t_opt and 0 < t_opt < hi * 5:
        hi = max(hi, t_opt * 1.6)
    if not hi or hi <= 0:
        hi = (mttf * 2) if mttf else 1.0
    grid = np.linspace(hi / 100.0, hi, _GRID_POINTS)
    with np.errstate(all="ignore"):
        cost = np.asarray(nr.cost_rate(grid), dtype=float)

    opt_rate = None
    if t_opt and np.isfinite(t_opt):
        with np.errstate(all="ignore"):
            opt_rate = _scalar(nr.cost_rate(t_opt))

    savings = 0.0
    if opt_rate is not None and rtf_rate:
        savings = (rtf_rate - opt_rate) / rtf_rate
    # Preventive replacement only helps with a wear-out (increasing-hazard)
    # trend; otherwise the "optimum" is spurious (e.g. the memoryless
    # exponential) and run-to-failure is correct.
    beneficial = bool(t_opt and np.isfinite(t_opt) and savings > 0.005)

    if lfp and not beneficial:
        recommendation = (
            f"No replacement age pays off: {1 - p_fail:.0%} of units never fail (a limited "
            "failure population), so the longer a unit runs, the likelier it's one of them. "
            "Over the long run, replacing on failure costs next to nothing per unit time — "
            "replace on failure (run-to-failure)."
        )
    elif beneficial:
        unit_s = f" {unit}" if unit else ""
        recommendation = (
            f"Replace preventively at about {fmt_num(t_opt)}{unit_s}. "
            f"This lowers the long-run cost rate by {savings:.0%} versus "
            f"run-to-failure."
        )
    else:
        recommendation = (
            "Preventive replacement isn't worthwhile here — there's no wear-out "
            "trend, so replace on failure (run-to-failure)."
        )

    return {
        "distribution": name,
        "unit": (unit or "").strip(),
        "planned_cost": cp,
        "unplanned_cost": cu,
        "mttf": mttf,
        "beneficial": beneficial,
        "optimal_time": t_opt if beneficial else None,
        "optimal_cost_rate": opt_rate if beneficial else None,
        "run_to_failure_cost_rate": rtf_rate,
        "savings": savings if beneficial else 0.0,
        "recommendation": recommendation,
        "curve": {"t": grid.tolist(), "cost_rate": _clean(cost)},
    }


# ---------------------------------------------------------------------------
# Compare two models (which item is more reliable?)
# ---------------------------------------------------------------------------


def _crossing(grid: np.ndarray, sf: np.ndarray, level: float) -> Optional[float]:
    """First time the (decreasing) survival curve drops to ``level``."""
    sf = np.asarray(sf, dtype=float)
    below = np.where(sf <= level)[0]
    if below.size == 0:
        return None
    i = int(below[0])
    if i == 0:
        return float(grid[0])
    s0, s1, t0, t1 = sf[i - 1], sf[i], grid[i - 1], grid[i]
    if s0 == s1:
        return float(t1)
    return float(t0 + (s0 - level) / (s0 - s1) * (t1 - t0))


def _side_hi(spec: dict) -> Optional[float]:
    if spec.get("kind") == "nonparametric":
        x = np.asarray(spec.get("x") or [], dtype=float)
        x = x[np.isfinite(x)]
        return float(x.max()) if x.size else None
    model, _ = _model_from_params(spec.get("distribution_id"), spec.get("params"), spec.get("extras"))
    try:
        return _scalar(model.qf(0.99))
    except NotImplementedError:
        return None  # LFP models have no quantile function; grid falls back.


def _eval_side(spec: dict, grid: np.ndarray) -> dict:
    """Evaluate one side of a comparison (parametric model or KM of raw data)."""
    label = spec.get("label") or "Model"
    if spec.get("kind") == "nonparametric":
        x = np.asarray(spec.get("x") or [], dtype=float)
        x = x[np.isfinite(x)]
        if x.size == 0:
            raise StrategyError(f"{label}: no usable data values.")
        fit_kwargs: dict = {"x": x}
        c = spec.get("c")
        if c is not None:
            c = np.asarray(c, dtype=float)
            if c.size == x.size:
                fit_kwargs["c"] = c.astype(int)
        try:
            km = KaplanMeier.fit(**fit_kwargs)
        except Exception as exc:
            raise StrategyError(f"{label}: {exc}") from exc
        with np.errstate(all="ignore"):
            sf = np.clip(np.asarray(km.sf(grid), dtype=float), 0.0, 1.0)
        xs = np.asarray(km.x, dtype=float)
        Rs = np.asarray(km.R, dtype=float)
        return {
            "label": label,
            "kind": "nonparametric",
            "n": int(x.size),
            "sf": _clean(sf),
            "metrics": {
                "b10": _crossing(grid, sf, 0.9),
                "median": _crossing(grid, sf, 0.5),
                "mttf": float(_TRAPZ(Rs, xs)),
                "mttf_restricted": True,
            },
        }
    model, name = _model_from_params(spec.get("distribution_id"), spec.get("params"), spec.get("extras"))
    with np.errstate(all="ignore"):
        sf = np.clip(np.asarray(model.sf(grid), dtype=float), 0.0, 1.0)
    metrics = _life_metrics(model)
    metrics["mttf_restricted"] = False
    return {
        "label": spec.get("label") or name,
        "kind": "parametric",
        "distribution": name,
        "sf": _clean(sf),
        "metrics": metrics,
    }


def compare_two(spec_a: dict, spec_b: dict, unit: Optional[str] = None) -> dict:
    """Compare two models' reliability so an engineer can see which item is
    more reliable. Each side is a parametric model (distribution + params) or a
    non-parametric Kaplan-Meier fit of raw data (``x`` with optional ``c``).
    """
    his = [h for h in (_side_hi(spec_a), _side_hi(spec_b)) if h]
    hi = max(his) if his else 1.0
    grid = np.linspace(0.0, hi, _GRID_POINTS)
    a = _eval_side(spec_a, grid)
    b = _eval_side(spec_b, grid)
    return {
        "unit": (unit or "").strip(),
        "time": grid.tolist(),
        "a": a,
        "b": b,
        "verdict": _reliability_verdict(grid, a, b, unit),
        "tests": _difference_tests(spec_a, spec_b, a["label"], b["label"]),
    }


_ALPHA = 0.05
_WEIGHTINGS = [
    ("log-rank", "Log-rank", "log-rank"),
    ("gehan", "Gehan–Wilcoxon", "gehan"),
    ("tarone-ware", "Tarone–Ware", "tarone-ware"),
]


def _prep_sample(spec: dict):
    """Right-censored sample (x, c) from a non-parametric spec, or None."""
    if spec.get("kind") != "nonparametric":
        return None
    x = np.asarray(spec.get("x") or [], dtype=float)
    finite = np.isfinite(x)
    x = x[finite]
    if x.size == 0:
        return None
    c = spec.get("c")
    if c is not None:
        c = np.asarray(c, dtype=float)
        c = c[finite] if c.size == finite.size else np.zeros_like(x)
    else:
        c = np.zeros_like(x)
    return x, c


def _difference_tests(spec_a: dict, spec_b: dict, la: str, lb: str) -> dict:
    """Weighted log-rank tests of whether the two samples differ significantly.

    Needs raw (right-censored) data on both sides — a parametric model alone
    has no sample to test.
    """
    sample_a = _prep_sample(spec_a)
    sample_b = _prep_sample(spec_b)
    if sample_a is None or sample_b is None:
        return {
            "available": False,
            "reason": (
                "Use raw data (non-parametric) on both sides to test whether the "
                "difference is statistically significant."
            ),
        }
    xa, ca = sample_a
    xb, cb = sample_b
    if not (np.isin(ca, [0, 1]).all() and np.isin(cb, [0, 1]).all()):
        return {
            "available": False,
            "reason": (
                "The log-rank test supports only right-censored data "
                "(censor flags 0 or 1)."
            ),
        }

    x = np.concatenate([xa, xb])
    c = np.concatenate([ca, cb]).astype(int)
    z = np.array([0] * len(xa) + [1] * len(xb))

    results = []
    for wid, label, weighting in _WEIGHTINGS:
        try:
            r = logrank(x, z, c=c, weighting=weighting)
            results.append(
                {
                    "id": wid,
                    "label": label,
                    "statistic": float(r.statistic),
                    "dof": int(r.dof),
                    "p_value": float(r.p_value),
                }
            )
        except Exception:
            continue
    if not results:
        return {"available": False, "reason": "The test could not be computed."}

    primary = next((r for r in results if r["id"] == "log-rank"), results[0])
    p = primary["p_value"]
    significant = p < _ALPHA
    if significant:
        summary = (
            f"The difference is statistically significant "
            f"(log-rank p = {p:.3g} < {_ALPHA}). The reliability gap between "
            f"{la} and {lb} is unlikely to be due to chance."
        )
    else:
        summary = (
            f"No statistically significant difference (log-rank p = {p:.3g} "
            f"≥ {_ALPHA}). The data don't establish that {la} and {lb} differ."
        )
    return {
        "available": True,
        "alpha": _ALPHA,
        "primary": "log-rank",
        "significant": significant,
        "summary": summary,
        "results": results,
    }


def _reliability_verdict(grid: np.ndarray, a: dict, b: dict, unit) -> dict:
    sfa = np.array([np.nan if v is None else v for v in a["sf"]])
    sfb = np.array([np.nan if v is None else v for v in b["sf"]])
    diff = sfa - sfb
    valid = np.isfinite(diff)
    g, d = grid[valid], diff[valid]
    la, lb = a["label"], b["label"]
    us = f" {unit}" if unit else ""
    cross = None

    # Ignore differences smaller than 1 reliability-point so near-equal regions
    # (and floating-point noise near t=0) don't read as a crossover.
    tol = 0.01
    sig = np.where(np.abs(d) < tol, 0.0, d)
    nz = np.nonzero(sig)[0]

    if nz.size == 0:
        more, text = "tie", f"{la} and {lb} are effectively the same."
    elif np.all(sig[nz] >= 0):
        more, text = "a", f"{la} is more reliable than {lb} across the range."
    elif np.all(sig[nz] <= 0):
        more, text = "b", f"{lb} is more reliable than {la} across the range."
    else:
        more = "mixed"
        s = np.sign(d)
        flips = np.where(s[:-1] * s[1:] < 0)[0]
        if flips.size:
            k = int(flips[0])
            cross = (
                float(np.interp(0.0, [d[k + 1], d[k]], [g[k + 1], g[k]]))
                if d[k] != d[k + 1]
                else float(g[k])
            )
        early, late = (la, lb) if sig[nz][0] > 0 else (lb, la)
        text = (
            f"The reliability curves cross at about {fmt_num(cross)}{us}: "
            f"{early} is more reliable before it, {late} after."
            if cross is not None
            else f"{la} and {lb} cross over the range."
        )

    # Headline metric: median life (robust for both parametric and KM).
    da, db = a["metrics"].get("median"), b["metrics"].get("median")
    if da and db:
        higher = la if da >= db else lb
        text += (
            f" Median life: {la} {fmt_num(da)}{us} vs {lb} {fmt_num(db)}{us} "
            f"(longer: {higher})."
        )
    return {"more_reliable": more, "crossover_time": cross, "text": text}


def failure_finding(
    distribution_id: str,
    params: list,
    target_availability: float,
    unit: Optional[str] = None,
    extras: Optional[dict] = None,
) -> dict:
    """Failure-finding interval for a hidden failure (protective device).

    Uses the standard first-order approximation FFI = 2 x (1 - A) x MTTF,
    where A is the target availability of the protective function. It follows
    from the average unavailability of an inspected hidden function being
    ~T / (2 x MTTF); accurate for A >= ~0.9, conservative below that.
    """
    try:
        availability = float(target_availability)
    except (TypeError, ValueError):
        raise StrategyError("Target availability must be a number between 0 and 1.")
    if not (0.0 < availability < 1.0):
        raise StrategyError("Target availability must be strictly between 0 and 1 (e.g. 0.99).")

    model, name = _model_from_params(distribution_id, params, extras)
    mttf = _scalar(model.mean())
    if mttf is None or not np.isfinite(mttf) or mttf <= 0:
        raise StrategyError("Couldn't compute a finite MTTF for this model.")

    interval = 2.0 * (1.0 - availability) * mttf
    unit_s = f" {unit.strip()}" if unit and unit.strip() else ""
    return {
        "distribution": name,
        "unit": (unit or "").strip(),
        "mttf": float(mttf),
        "target_availability": availability,
        "interval": float(interval),
        "method": "approx_2(1-A)MTTF",
        "note": (
            f"Check the hidden function about every {fmt_num(interval)}{unit_s} to keep its "
            f"availability near {availability * 100:.10g}%. Uses the standard approximation "
            "FFI = 2 x (1 - A) x MTTF, accurate for availability targets above ~90%."
        ),
    }


# ---------------------------------------------------------------------------
# Demonstration test planning (RePyability's ``demonstration`` module, #129)
# ---------------------------------------------------------------------------

DEMO_METHODS = ("attribute", "mtbf")
_DEMO_FAILURE_COLUMNS = (0, 1, 2, 3)
_DEMO_MULTIPLES = (1.0, 1.5, 2.0, 2.5, 3.0)
_DEMO_UNIT_FACTORS = (0.5, 0.75, 1.0, 1.5, 2.0)
_DEMO_MAX_FAILURES = 100
_DEMO_MAX_UNITS = 1_000_000
_DEMO_MIN_MULTIPLE = 0.01
_DEMO_MAX_MULTIPLE = 100.0
_DEMO_MAX_SHAPE = 20.0
# The operating-characteristic curve: points, and how far into each tail.
_DEMO_OC_POINTS = 81
_DEMO_OC_TAIL = 0.005


def _demo_two_risk_plan(plan, *args, **kwargs):
    """RePyability's two-risk plan (#184 there, #223 here), its refusals in
    the calculator's words."""
    try:
        return plan(*args, **kwargs)
    except ValueError as exc:
        text = str(exc)
        if text.startswith("No test of"):
            raise StrategyError(
                "No test of these units keeps both risks: test more units, allow a larger producer's "
                "risk, or give a better good design.") from None
        if text.startswith("No plan allowing"):
            raise StrategyError(
                f"No plan allowing up to {_DEMO_MAX_FAILURES} failures keeps both risks: the good design is "
                "too close to the target. Give a better good design, or allow larger risks.") from None
        raise StrategyError(text) from None


def _demo_oc_attribute(demo, R, design, n, r, ext, consumer_risk, pass_prob) -> dict:
    """The test's operating characteristic: the chance of passing against the
    design's true mission reliability, from 1 down to where it all but never
    passes (a grid even in the chance of failing a mission)."""
    q_hi = max(1.0 - R, 1.0 - design if design is not None else 0.0)
    for _ in range(60):
        if q_hi >= 1.0 - 1e-9 or float(demo.demonstration_pass_probability(1.0 - q_hi, n, r, **ext)) <= _DEMO_OC_TAIL:
            break
        q_hi *= 1.25
    q_hi = min(q_hi, 1.0 - 1e-9)
    q = np.linspace(q_hi / (_DEMO_OC_POINTS - 1), q_hi, _DEMO_OC_POINTS - 1)
    passes = np.atleast_1d(demo.demonstration_pass_probability(1.0 - q, n, r, **ext))
    points = [{"label": "Target", "x": R, "pass_probability": consumer_risk}]
    if design is not None:
        points.append({"label": "Good design", "x": design, "pass_probability": pass_prob})
    return {
        "x_kind": "reliability",
        "x": [1.0, *(1.0 - q).tolist()],
        "pass_probability": [1.0, *(float(p) for p in passes)],
        "points": points,
    }


def _demo_oc_mtbf(demo, target, design, total, r, consumer_risk, pass_prob) -> dict:
    """The MTBF test's operating characteristic: the chance of passing against
    the design's true MTBF (log-spaced), across the tails."""
    lo = target
    for _ in range(60):
        if float(demo.mtbf_pass_probability(lo, total, r)) <= _DEMO_OC_TAIL:
            break
        lo /= 1.25
    hi = max(target, design or target)
    for _ in range(60):
        if float(demo.mtbf_pass_probability(hi, total, r)) >= 1.0 - _DEMO_OC_TAIL:
            break
        hi *= 1.25
    x = np.geomspace(lo, hi, _DEMO_OC_POINTS)
    passes = np.atleast_1d(demo.mtbf_pass_probability(x, total, r))
    points = [{"label": "Target", "x": target, "pass_probability": consumer_risk}]
    if design is not None:
        points.append({"label": "Good design", "x": design, "pass_probability": pass_prob})
    return {
        "x_kind": "mtbf",
        "x": x.tolist(),
        "pass_probability": [float(p) for p in passes],
        "points": points,
    }


def _demo_risks_sentence(design_text: str, pass_prob: float, producer_target, consumer_risk: float,
                         c: float) -> str:
    """The plan's two risks in a sentence: what the good design's chance of
    passing means, and (for a two-risk plan) that both are kept."""
    if producer_target is None:
        return f" A design whose true {design_text} passes this test {pass_prob:.0%} of the time."
    return (
        f" The plan keeps both risks: a design at the target passes "
        f"{consumer_risk:.1%} of the time (consumer's risk, at most {_pct(1 - c)}), and one whose true "
        f"{design_text} fails {1 - pass_prob:.1%} of the time (producer's risk, at most {_pct(producer_target)})."
    )


def _pct(p: float) -> str:
    """A probability as a percentage for a sentence, as given: 0.95 -> '95%',
    0.999999 -> '99.9999%' (never rounded up to 100%, #215)."""
    return f"{float(p) * 100:.10g}%"


def _blank(value) -> bool:
    return value is None or (isinstance(value, str) and not value.strip())


def _demo_prob(value, label: str) -> float:
    try:
        v = float(value)
    except (TypeError, ValueError):
        raise StrategyError(f"{label} must be a number between 0 and 1 (e.g. 0.95).") from None
    if not (0.0 < v < 1.0):
        raise StrategyError(f"{label} must be strictly between 0 and 1 (e.g. 0.95); got {v:g}.")
    return v


def _demo_positive(value, label: str, maximum: Optional[float] = None) -> float:
    try:
        v = float(value)
    except (TypeError, ValueError):
        raise StrategyError(f"{label} must be a positive number.") from None
    if not (np.isfinite(v) and v > 0):
        raise StrategyError(f"{label} must be a positive number; got {v:g}.")
    if maximum is not None and v > maximum:
        raise StrategyError(f"{label} must be at most {fmt_num(maximum)}; got {fmt_num(v)}.")
    return v


def _demo_count(value, label: str, minimum: int, maximum: int) -> int:
    try:
        v = float(value)
    except (TypeError, ValueError):
        raise StrategyError(f"{label} must be a whole number.") from None
    if not np.isfinite(v) or v != int(v):
        raise StrategyError(f"{label} must be a whole number; got {value}.")
    v = int(v)
    if v < minimum or v > maximum:
        raise StrategyError(f"{label} must be between {minimum} and {maximum:,}; got {v}.")
    return v


def _failures_phrase(r: int) -> str:
    if r == 0:
        return "with no failures"
    return f"with at most {r} failure{'s' if r != 1 else ''}"


def _time_phrase(t: float, unit: str) -> str:
    return f"{fmt_num(t)} {unit}" if unit else fmt_num(t)


def _multiple_phrase(k: float) -> str:
    return f"{float(f'{k:.3g}'):g}×"


def demonstration_test(
    reliability=None,
    confidence=0.95,
    mission_time=None,
    failures=0,
    test_multiple=1.0,
    shape=None,
    units=None,
    method: str = "attribute",
    mtbf=None,
    design_reliability=None,
    design_mtbf=None,
    unit: Optional[str] = None,
    producer_risk=None,
) -> dict:
    """Plan a reliability demonstration test with RePyability (#129).

    ``method='attribute'`` (binomial / success run): each unit runs for
    ``test_multiple`` missions of ``mission_time`` and passes or fails; the
    test passes with at most ``failures`` failures. Gives the units to test
    (``demonstration_sample_size``) — or, when ``units`` is given, the test
    time per unit (``demonstration_test_multiple``, which needs the Weibull
    ``shape``). A ``test_multiple`` other than 1 also needs ``shape`` (the
    extended success run, or Weibayes: a unit surviving k missions shows
    ``R ** (k ** shape)``). ``mission_time`` is optional — without it the
    plan is in missions (or cycles / demands).

    ``method='mtbf'`` (constant failure rate, chi-squared): the total
    time-terminated test time that demonstrates ``mtbf`` with at most
    ``failures`` failures (``mtbf_test_time``), split over ``units`` if given.

    ``design_reliability`` / ``design_mtbf`` (optional): the chance a design
    that good passes the planned test (its operating characteristic).

    ``producer_risk`` (optional, with the good design's ``design_reliability``
    or ``design_mtbf``): plan a test that keeps both risks (#223, RePyability
    0.12's ``demonstration_plan`` / ``mtbf_demonstration_plan``) — a design at
    the target passes at most ``1 - confidence`` of the time, and the good
    design fails at most ``producer_risk`` of the time. The plan chooses the
    failures allowed (``failures`` is ignored) and the fewest units (or, given
    ``units``, the shortest test; for an MTBF test, the least test time).

    Every plan carries its operating characteristic (``oc_curve``): the
    chance of passing against the design's true reliability (or MTBF).
    """
    from repyability import demonstration as demo

    method = (method or "attribute").strip().lower()
    if method not in DEMO_METHODS:
        raise StrategyError(f"method must be one of: {', '.join(DEMO_METHODS)}.")
    unit_s = (unit or "").strip()
    c = _demo_prob(confidence, "Confidence")
    r = _demo_count(0 if _blank(failures) else failures, "Allowed failures", 0, _DEMO_MAX_FAILURES)
    n_given = None if _blank(units) else _demo_count(units, "Units on test", 1, _DEMO_MAX_UNITS)
    pr = None if _blank(producer_risk) else _demo_prob(producer_risk, "Producer's risk")

    if method == "mtbf":
        return _demo_mtbf(demo, mtbf, c, r, n_given, design_mtbf, unit_s, pr)

    R = _demo_prob(reliability, "Target reliability")
    t = None if _blank(mission_time) else _demo_positive(mission_time, "Mission time")
    beta = None if _blank(shape) else _demo_positive(shape, "Weibull shape (beta)", _DEMO_MAX_SHAPE)
    k = 1.0 if _blank(test_multiple) else _demo_positive(
        test_multiple, "Test length (multiple of the mission)", _DEMO_MAX_MULTIPLE)
    if k < _DEMO_MIN_MULTIPLE:
        raise StrategyError(f"Test length must be at least {_DEMO_MIN_MULTIPLE:g} missions.")
    design = None if _blank(design_reliability) else _demo_prob(design_reliability, "Design reliability")
    if pr is not None:
        if design is None:
            raise StrategyError(
                "A producer's risk needs the good design's reliability: the true reliability of a design "
                "that should pass (e.g. 0.99).")
        if design <= R:
            raise StrategyError(
                f"The good design's reliability ({_pct(design)}) must be above the target ({_pct(R)}): no "
                "test passes a design no better than the target more often than the target.")

    solve_for = "test_time" if n_given is not None else "units"
    if solve_for == "test_time":
        if beta is None:
            raise StrategyError(
                "To solve for the test time per unit, give the Weibull shape (beta) of the lifetime — "
                "trading test time for units depends on it."
            )
        n = n_given
        if pr is not None:
            plan = _demo_two_risk_plan(demo.demonstration_plan, R, design, c, pr, n=n, shape=beta,
                                       max_failures=_DEMO_MAX_FAILURES)
            k, r = float(plan.test_multiple), int(plan.failures)
        else:
            if n_given <= r:
                raise StrategyError(f"Units on test ({n_given}) must be more than the failures allowed ({r}).")
            k = float(demo.demonstration_test_multiple(R, n, c, r, shape=beta))
    else:
        if k != 1.0 and beta is None:
            raise StrategyError(
                "A test longer or shorter than one mission needs the Weibull shape (beta) of the "
                "lifetime: give shape, or set the test length to 1 mission."
            )
        if pr is not None:
            plan = _demo_two_risk_plan(demo.demonstration_plan, R, design, c, pr, test_multiple=k, shape=beta,
                                       max_failures=_DEMO_MAX_FAILURES)
            n, r = int(plan.n), int(plan.failures)
        else:
            n = int(demo.demonstration_sample_size(R, c, r, test_multiple=k, shape=beta))
        if pr is not None and n > _DEMO_MAX_UNITS:
            raise StrategyError(
                f"The plan needs {n:,} units, more than {_DEMO_MAX_UNITS:,}: give a better good design, allow "
                "larger risks, or test each unit for longer.")

    ext = {"test_multiple": k, "shape": beta} if k != 1.0 else {}
    demonstrated = float(demo.demonstrated_reliability(n, c, r, **ext))
    consumer_risk = float(demo.demonstration_pass_probability(R, n, r, **ext))
    pass_prob = (
        float(demo.demonstration_pass_probability(design, n, r, **ext)) if design is not None else None
    )

    per_unit = k * t if t is not None else None
    if t is not None:
        target = f"R({_time_phrase(t, unit_s)}) ≥ {_pct(R)}"
        duration = f"{_time_phrase(per_unit, unit_s)} each"
        if k != 1.0:
            duration += f" ({_multiple_phrase(k)} the mission)"
    else:
        target = f"a mission reliability ≥ {_pct(R)}"
        duration = "one mission each" if k == 1.0 else f"{_multiple_phrase(k)} the mission each"
    summary = (
        f"Test {n:,} unit{'s' if n != 1 else ''} for {duration} {_failures_phrase(r)} "
        f"to show {target} at {_pct(c)} confidence"
        + (f", assuming a Weibull shape of {fmt_num(beta)}" if k != 1.0 else "")
        + "."
    )
    if pass_prob is not None:
        summary += _demo_risks_sentence(f"reliability is {_pct(design)}", pass_prob, pr, consumer_risk, c)

    assumptions = [
        "Each unit passes or fails independently with the same reliability (a binomial, attribute "
        "test); test units are representative of production and run under use conditions.",
        (f"The test passes only if none of the {n:,} units fails; it fails at the first failure."
         if r == 0 else
         f"The test passes if at most {r} of the {n:,} units fail; it fails at failure {r + 1}."),
    ]
    if k != 1.0:
        assumptions.append(
            f"Lifetimes are Weibull with known shape β = {fmt_num(beta)} (the extended success run, or "
            f"Weibayes): a unit that survives k = {_multiple_phrase(k)} the mission shows R^(k^β)."
        )
        assumptions.append(
            "The plan is sensitive to β: if the true shape is "
            + ("lower" if k > 1.0 else "higher")
            + " than assumed, the test demonstrates less than it claims."
        )
    assumptions.append(
        f"A design exactly at the {_pct(R)} target still passes {consumer_risk:.1%} of the time "
        f"(the consumer's risk, at most {_pct(1 - c)})."
    )
    if pass_prob is not None:
        assumptions.append(
            f"A design whose true reliability is {_pct(design)} fails {1 - pass_prob:.1%} of the time (the "
            "producer's risk" + (f", at most {_pct(pr)})." if pr is not None else ").")
        )

    return {
        "method": "attribute",
        "solve_for": solve_for,
        "unit": unit_s,
        "reliability": R,
        "confidence": c,
        "mission_time": t,
        "failures": r,
        "shape": beta,
        "test_multiple": k,
        "units": n,
        "test_time_per_unit": per_unit,
        "total_test_time": per_unit * n if per_unit is not None else None,
        "demonstrated_reliability": demonstrated,
        "consumer_risk": consumer_risk,
        "design_reliability": design,
        "pass_probability": pass_prob,
        "producer_risk": None if pass_prob is None else 1.0 - pass_prob,
        "producer_risk_target": pr,
        "two_risk": pr is not None,
        "summary": summary,
        "assumptions": assumptions,
        "tradeoff": _demo_attribute_tradeoff(demo, R, c, r, k, beta, t, unit_s, solve_for, n),
        "oc_curve": _demo_oc_attribute(demo, R, design, n, r, ext, consumer_risk, pass_prob),
    }


def _demo_attribute_tradeoff(demo, R, c, r, k, beta, t, unit_s, solve_for, n) -> dict:
    """Units (or test time per unit) against allowed failures 0..3 — and
    against the test length (or the units on test) when the Weibull shape is
    known. Each row is one test length (or unit count); ``values`` line up
    with ``failures``."""
    cols = sorted(set(_DEMO_FAILURE_COLUMNS) | {r})

    def length_label(m: float) -> str:
        if t is not None:
            return f"{_time_phrase(m * t, unit_s)} ({_multiple_phrase(m)})"
        return f"{_multiple_phrase(m)} mission"

    rows = []
    if solve_for == "units":
        multiples = sorted(set(_DEMO_MULTIPLES) | {k}) if beta is not None else [k]
        for m in multiples:
            ext = {"test_multiple": m, "shape": beta} if m != 1.0 else {}
            rows.append({
                "key": m,
                "x": m * t if t is not None else m,
                "label": length_label(m),
                "values": [int(demo.demonstration_sample_size(R, c, f, **ext)) for f in cols],
                "selected": m == k,
            })
        if t is None:
            x_label = "test length (missions)"
        else:
            x_label = f"test length per unit ({unit_s})" if unit_s else "test length per unit"
        return {
            "solve_for": "units",
            "row_label": "Test length per unit",
            "x_label": x_label,
            "value_label": "Units to test",
            "failures": cols,
            "rows": rows,
        }

    counts = sorted({max(1, int(round(n * f))) for f in _DEMO_UNIT_FACTORS} | {n})
    for count in counts:
        values = []
        for f in cols:
            if count <= f:
                values.append(None)
                continue
            m = float(demo.demonstration_test_multiple(R, count, c, f, shape=beta))
            values.append(m * t if t is not None else m)
        rows.append({
            "key": count,
            "x": count,
            "label": f"{count:,} unit{'s' if count != 1 else ''}",
            "values": values,
            "selected": count == n,
        })
    if t is None:
        value_label = "Test length per unit (missions)"
    else:
        value_label = f"Test time per unit ({unit_s})" if unit_s else "Test time per unit"
    out = {
        "solve_for": "test_time",
        "row_label": "Units on test",
        "x_label": "units on test",
        "value_label": value_label,
        "failures": cols,
        "rows": rows,
    }
    if any(v is None for row in rows for v in row["values"]):
        # #215: say why a cell is empty rather than leave a bare null.
        out["note"] = ("A null value is a unit count no larger than the failures allowed: with every unit "
                       "allowed to fail, no test time demonstrates anything, so the test needs more units.")
    return out


def _demo_mtbf(demo, mtbf, c, r, n_given, design_mtbf, unit_s, pr=None) -> dict:
    """Constant-failure-rate (chi-squared) time-terminated test; with a
    producer's risk, MIL-HDBK-781's fixed-length plan keeping both risks."""
    if _blank(mtbf):
        raise StrategyError("Enter the MTBF to demonstrate.")
    target = _demo_positive(mtbf, "Target MTBF")
    design = None if _blank(design_mtbf) else _demo_positive(design_mtbf, "Design MTBF")
    if pr is not None:
        if design is None:
            raise StrategyError(
                "A producer's risk needs the good design's MTBF: the true MTBF of a design that should pass.")
        if design <= target:
            raise StrategyError(
                f"The good design's MTBF ({_time_phrase(design, unit_s)}) must be above the target "
                f"({_time_phrase(target, unit_s)}).")
        plan = _demo_two_risk_plan(demo.mtbf_demonstration_plan, target, design, c, pr,
                                   max_failures=_DEMO_MAX_FAILURES)
        r = int(plan.failures)
        total = float(plan.test_time)
    else:
        total = float(demo.mtbf_test_time(target, c, r))
    per_unit = total / n_given if n_given else None
    consumer_risk = float(demo.mtbf_pass_probability(target, total, r))
    pass_prob = float(demo.mtbf_pass_probability(design, total, r)) if design is not None else None

    summary = (
        f"Run {_time_phrase(total, unit_s)} of total test time {_failures_phrase(r)} to show "
        f"MTBF ≥ {_time_phrase(target, unit_s)} at {_pct(c)} confidence"
        + (f" — about {_time_phrase(per_unit, unit_s)} on each of {n_given:,} units" if per_unit else "")
        + "."
    )
    if pass_prob is not None:
        summary += _demo_risks_sentence(f"MTBF is {_time_phrase(design, unit_s)}", pass_prob, pr,
                                        consumer_risk, c)
    assumptions = [
        "Constant failure rate (exponential lifetimes): only the total unit time on test matters, "
        "not how it is split across units.",
        "Time-terminated test: failed units are repaired or replaced and testing continues; the test "
        f"passes with at most {r} failure{'s' if r != 1 else ''} in the total time (chi-squared bound).",
        "Not for wear-out: if the failure rate rises with age, an MTBF test on young units overstates "
        "reliability — use an attribute test with a Weibull shape instead.",
        f"A design exactly at the target MTBF still passes {consumer_risk:.1%} of the time "
        f"(the consumer's risk, at most {_pct(1 - c)}).",
    ]
    if pass_prob is not None:
        assumptions.append(
            f"A design whose true MTBF is {_time_phrase(design, unit_s)} fails {1 - pass_prob:.1%} of the "
            "time (the producer's risk" + (f", at most {_pct(pr)})." if pr is not None else ").")
        )
        if pr is not None:
            assumptions.append(
                f"A fixed-length plan (MIL-HDBK-781) for a discrimination ratio of "
                f"{fmt_num(design / target)}: the shortest test keeping both risks.")
    cols = sorted(set(_DEMO_FAILURE_COLUMNS) | {r})
    totals = [float(demo.mtbf_test_time(target, c, f)) for f in cols]
    rows = [{"key": None, "x": None, "label": "Total test time", "values": totals, "selected": True}]
    if n_given:
        rows.append({
            "key": n_given, "x": None, "label": f"Per unit ({n_given:,} units)",
            "values": [v / n_given for v in totals], "selected": False,
        })
    return {
        "method": "mtbf",
        "solve_for": "test_time",
        "unit": unit_s,
        "mtbf": target,
        "confidence": c,
        "failures": r,
        "units": n_given,
        "total_test_time": total,
        "test_time_per_unit": per_unit,
        "consumer_risk": consumer_risk,
        "design_mtbf": design,
        "pass_probability": pass_prob,
        "producer_risk": None if pass_prob is None else 1.0 - pass_prob,
        "producer_risk_target": pr,
        "two_risk": pr is not None,
        "summary": summary,
        "assumptions": assumptions,
        "oc_curve": _demo_oc_mtbf(demo, target, design, total, r, consumer_risk, pass_prob),
        "tradeoff": {
            "solve_for": "total_test_time",
            "row_label": "",
            "x_label": "",
            "value_label": f"Test time ({unit_s})" if unit_s else "Test time",
            "failures": cols,
            "rows": rows,
        },
    }
