"""Decision-support tools for reliability engineering ("Strategy").

Two tools built on SurPyval + RePyability:

* ``compare_models`` — fit every parametric distribution to a dataset, rank
  them by information criteria, and return reliability curves overlaid on the
  non-parametric (Kaplan-Meier / Turnbull) empirical estimate, plus decision
  metrics (B-life, median life, MTTF) for each.
* ``optimal_replacement`` — the age-based preventive-replacement interval that
  minimises the long-run cost rate given planned vs. unplanned costs, with the
  saving versus a run-to-failure policy.
"""

from __future__ import annotations

from typing import Optional

import numpy as np
import pandas as pd

from backend.fitting import (
    DISTRIBUTIONS,
    _goodness_of_fit,
    build_fit_inputs,
)
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


def _model_from_params(distribution_id: str, params: list):
    entry = DISTRIBUTIONS.get(distribution_id)
    if entry is None:
        raise StrategyError(
            f"'{distribution_id}' isn't a supported parametric distribution."
        )
    dist = entry["dist"]
    by_name = {p["name"]: float(p["value"]) for p in (params or []) if "name" in p}
    names = list(getattr(dist, "param_names", []) or [])
    if names and all(n in by_name for n in names):
        values = [by_name[n] for n in names]
    else:
        values = [float(p["value"]) for p in (params or [])]
    if not values:
        raise StrategyError("The model is missing its parameters.")
    try:
        return dist.from_params(values), entry["name"]
    except Exception as exc:
        raise StrategyError(str(exc)) from exc


def compare_models(df: pd.DataFrame, mapping: dict, unit: Optional[str] = None) -> dict:
    """Fit every parametric distribution and rank them against the data.

    Returns the fitted models (ranked best-first by AIC) with their parameters,
    goodness-of-fit metrics, life metrics and reliability curves, plus the
    non-parametric empirical survival to overlay.
    """
    try:
        kwargs = build_fit_inputs(df, mapping)
    except Exception as exc:
        raise StrategyError(str(exc)) from exc
    if "x" not in kwargs and not ("xl" in kwargs and "xr" in kwargs):
        raise StrategyError(
            "Map a column to 'x' (or to both 'xl' and 'xr' for interval data)."
        )

    fitted: list = []
    for dist_id, entry in DISTRIBUTIONS.items():
        try:
            model = entry["dist"].fit(**kwargs)
            gof = _goodness_of_fit(model)
            aic = next((g["value"] for g in gof if g["id"] == "aic"), None)
            param_names = (
                getattr(model, "param_names", None)
                or getattr(entry["dist"], "param_names", None)
                or [f"p{i}" for i in range(len(model.params))]
            )
            params = [
                {"name": name, "value": float(value)}
                for name, value in zip(param_names, model.params)
            ]
            fitted.append(
                {
                    "model": model,
                    "id": dist_id,
                    "name": entry["name"],
                    "params": params,
                    "gof": gof,
                    "aic": aic,
                    "metrics": _life_metrics(model),
                }
            )
        except Exception:
            continue  # a distribution that won't fit this data is simply skipped

    if not fitted:
        raise StrategyError("None of the distributions could be fit to this data.")

    # Common time grid out to the largest 99th percentile (fallback: data max).
    his = [m for f in fitted if (m := _scalar(f["model"].qf(0.99)))]
    if not his:
        x = kwargs.get("x")
        his = [float(np.nanmax(x))] if x is not None and len(x) else [1.0]
    grid = np.linspace(0.0, max(his), _GRID_POINTS)

    for f in fitted:
        with np.errstate(all="ignore"):
            f["sf"] = _clean(f["model"].sf(grid))

    # Non-parametric empirical survival (Turnbull for left/interval censoring,
    # else Nelson-Aalen) taken from SurPyval's plotting positions.
    empirical = _empirical_survival(fitted[0]["model"])

    fitted.sort(
        key=lambda f: (f["aic"] is None, f["aic"] if f["aic"] is not None else 0)
    )
    best = fitted[0]

    n = 0
    try:
        n = int(np.sum(best["model"].data["n"]))
    except Exception:
        pass

    return {
        "unit": (unit or "").strip(),
        "time": grid.tolist(),
        "n": n,
        "best_id": best["id"],
        "recommendation": _comparison_recommendation(fitted),
        "models": [{k: v for k, v in f.items() if k != "model"} for f in fitted],
        "empirical": empirical,
    }


def _empirical_survival(model) -> dict:
    try:
        c = np.asarray(model.data["c"])
        heuristic = "Turnbull" if np.any((c == -1) | (c == 2)) else "Nelson-Aalen"
        data = model.get_plot_data(heuristic=heuristic)
        x = np.asarray(data["x_"], dtype=float)
        R = 1.0 - np.asarray(data["F"], dtype=float)
        return {"x": _clean(x), "R": _clean(R)}
    except Exception:
        return {"x": [], "R": []}


def _comparison_recommendation(fitted: list) -> str:
    best = fitted[0]
    if best["aic"] is None:
        return f"{best['name']} is the recommended fit."
    msg = f"{best['name']} fits best (lowest AIC)."
    if len(fitted) > 1 and fitted[1]["aic"] is not None:
        gap = fitted[1]["aic"] - best["aic"]
        if gap < 2:
            msg += (
                f" {fitted[1]['name']} is statistically comparable "
                f"(ΔAIC = {gap:.1f}); prefer the simpler/physically-motivated one."
            )
    return msg


def optimal_replacement(
    distribution_id: str,
    params: list,
    planned_cost: Optional[float],
    unplanned_cost: Optional[float],
    unit: Optional[str] = None,
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

    model, name = _model_from_params(distribution_id, params)
    nr = NonRepairable(model)
    nr.set_costs_planned_and_unplanned(cp, cu)

    try:
        t_opt = _scalar(nr.find_optimal_replacement())
    except Exception:
        t_opt = None

    mttf = _scalar(model.mean())
    rtf_rate = cu / mttf if mttf and mttf > 0 else None

    # Time grid for the cost-rate curve: focus around the optimum / 95th pct.
    hi = _scalar(model.qf(0.95)) or (mttf * 2 if mttf else 1.0)
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

    if beneficial:
        unit_s = f" {unit}" if unit else ""
        recommendation = (
            f"Replace preventively at about {t_opt:,.0f}{unit_s}. "
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
    model, _ = _model_from_params(spec.get("distribution_id"), spec.get("params"))
    return _scalar(model.qf(0.99))


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
    model, name = _model_from_params(spec.get("distribution_id"), spec.get("params"))
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
            f"The reliability curves cross at about {cross:,.0f}{us}: "
            f"{early} is more reliable before it, {late} after."
            if cross is not None
            else f"{la} and {lb} cross over the range."
        )

    # Headline metric: median life (robust for both parametric and KM).
    da, db = a["metrics"].get("median"), b["metrics"].get("median")
    if da and db:
        higher = la if da >= db else lb
        text += (
            f" Median life: {la} {da:,.0f}{us} vs {lb} {db:,.0f}{us} "
            f"(longer: {higher})."
        )
    return {"more_reliable": more, "crossover_time": cross, "text": text}
