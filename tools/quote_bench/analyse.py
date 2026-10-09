"""Which SurPyval regression model best predicts a job's runtime (#286)?

Runtime is a survival time: a run still going at the cap is right-censored
there. Each candidate model is fitted to the features a quote can see before
running (``generate._Builder.features``) and scored by 5-fold
cross-validation:

* **C**: Harrell's concordance of the predicted medians (ranking jobs right);
* **error**: the median factor between predicted median and actual runtime
  (uncensored jobs), e.g. 1.3 = typically within ±30 %;
* **cover90**: how often the actual runtime is within the predicted 90th
  percentile, the quote's ceiling (the target is 0.90);
* **over90**: the median factor the 90th percentile over-quotes by.

The AIC is of the fit to all the data.

    python -m tools.quote_bench.analyse runs.jsonl [--report report.md]
"""

from __future__ import annotations

import argparse
import json
import math
import warnings

import numpy as np
import surpyval as sv

MODELS = ["LogNormalAFT", "WeibullAFT", "GammaAFT", "LogisticAFT", "GumbelAFT", "ExponentialAFT",
          "LogNormalPH", "CoxPH"]


def _log(v):
    return math.log(max(float(v), 1e-12))


def feature_sets(f: dict, r: dict) -> dict[str, list[float]]:
    blocks = max(f["n_blocks"], 1)
    minimal = [_log(f["n_simulations"]), math.log1p(f["events_per_rep"]), _log(blocks)]
    full = minimal + [
        math.log1p(f["n_edges"]),
        f["n_branch_points"] / blocks,
        float(f["n_vote"] > 0),
        f["n_standby"] / blocks,
        float(f["n_ccf_groups"] > 0),
        float(bool(r.get("ccf_included"))),
        float(f["n_bridges"] > 0),
        float(f["crews"] > 0),
        f["frac_nonexp_life"],
        f["n_preventive"] / blocks,
        f["n_inspection"] / blocks,
        f["n_instant"] / blocks,
        float(f["costs"]),
        _log(f["horizon"]),
    ]
    return {"minimal": minimal, "full": full}


FULL_NAMES = ["log n_sims", "log1p events/rep", "log blocks", "log1p edges", "branch pts/block",
              "has vote", "standby/block", "has CCF", "CCF in sim", "bridge", "limited crews",
              "non-exp life", "preventive/block", "inspection/block", "instant/block", "costs",
              "log horizon"]


def load(path):
    rows = [json.loads(line) for line in open(path) if line.strip()]
    keep = [r for r in rows if r["result"].get("status") in ("ok", "censored")]
    x = np.array([max(r["result"]["seconds"], 1e-3) for r in keep])
    c = np.array([1 if r["result"]["status"] == "censored" else 0 for r in keep])
    Z = {k: np.array([feature_sets(r["features"], r["result"])[k] for r in keep]) for k in ("minimal", "full")}
    exact = np.array([r["result"].get("exact_seconds") or np.nan for r in keep])
    return rows, keep, x, c, Z, exact


class _Std:
    def __init__(self, Z):
        self.mu, self.sd = Z.mean(0), Z.std(0)
        self.sd[self.sd == 0] = 1.0

    def __call__(self, Z):
        return (Z - self.mu) / self.sd


_GRID = np.exp(np.linspace(math.log(1e-4), math.log(1e5), 400))


def quantiles(model, Z, ps):
    """Quantiles ``ps`` per row of Z: the model's own qf, or by inverting
    its survival function on a grid (semi-parametric models)."""
    out = np.empty((len(Z), len(ps)))
    if hasattr(model, "qf"):
        for j, p in enumerate(ps):
            out[:, j] = np.asarray(model.qf(p, Z), dtype=float).reshape(-1)
        return out
    for i, z in enumerate(Z):
        s = np.asarray(model.sf(_GRID, z[None, :]), dtype=float).reshape(-1)
        for j, p in enumerate(ps):
            hit = np.nonzero(s <= 1 - p)[0]
            out[i, j] = _GRID[hit[0]] if len(hit) else np.inf
    return out


def concordance(pred, x, c):
    """Harrell's C: of comparable pairs (the shorter one observed), the share
    ordered right by the prediction."""
    num = den = 0.0
    order = np.argsort(x)
    for a_i, a in enumerate(order):
        if c[a]:
            continue
        later = order[a_i + 1:]
        later = later[x[later] > x[a]]
        if not len(later):
            continue
        den += len(later)
        num += np.sum(pred[later] > pred[a]) + 0.5 * np.sum(pred[later] == pred[a])
    return num / den if den else float("nan")


def score(name, Z, x, c, folds=5, seed=0):
    rng = np.random.default_rng(seed)
    fold = rng.permutation(len(x)) % folds
    med = np.full(len(x), np.nan)
    q90 = np.full(len(x), np.nan)
    for k in range(folds):
        tr, te = fold != k, fold == k
        std = _Std(Z[tr])
        m = getattr(sv, name).fit(x=x[tr], Z=std(Z[tr]), c=c[tr])
        q = quantiles(m, std(Z[te]), [0.5, 0.9])
        med[te], q90[te] = q[:, 0], q[:, 1]
    obs = c == 0
    err = float(np.exp(np.nanmedian(np.abs(np.log(med[obs] / x[obs])))))
    # Covered: observed within q90; a censored run counts once q90 is below
    # the cap (it surely ran longer), and is unknown above it.
    known = obs | (q90 < x)
    covered = (x <= q90) & obs
    cover90 = float(covered[known].mean())
    over90 = float(np.exp(np.nanmedian(np.log(q90[obs] / x[obs]))))
    std = _Std(Z)
    full = getattr(sv, name).fit(x=x, Z=std(Z), c=c)
    aic = full.aic() if callable(getattr(full, "aic", None)) else getattr(full, "aic", None)
    return {"model": name, "C": concordance(med, x, c), "error": err, "cover90": cover90,
            "over90": over90, "aic": float(aic) if aic is not None else float("nan"), "fit": full}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("runs")
    ap.add_argument("--report")
    a = ap.parse_args()
    warnings.simplefilter("ignore")
    rows, keep, x, c, Z, exact = load(a.runs)
    status = {}
    for r in rows:
        status[r["result"].get("status")] = status.get(r["result"].get("status"), 0) + 1
    lines = [f"# Runtime model comparison\n",
             f"{len(rows)} design points: {status}. Modelled: {len(x)} "
             f"({int(c.sum())} censored at the cap). Runtime median {np.median(x):.2f} s, "
             f"90th percentile {np.quantile(x, 0.9):.1f} s, max {x.max():.1f} s. "
             f"Exact-only part: median {np.nanmedian(exact):.3f} s.\n"]
    results = []
    for fs in ("minimal", "full"):
        lines.append(f"\n## Features: {fs}\n")
        lines.append("| model | C | error (×) | cover90 | over90 (×) | AIC |")
        lines.append("|---|---|---|---|---|---|")
        for name in MODELS:
            try:
                s = score(name, Z[fs], x, c)
            except Exception as exc:  # noqa: BLE001
                lines.append(f"| {name} | failed: {type(exc).__name__}: {str(exc)[:60]} | | | | |")
                continue
            s["features"] = fs
            results.append(s)
            lines.append(f"| {name} | {s['C']:.3f} | {s['error']:.2f} | {s['cover90']:.2f} | "
                         f"{s['over90']:.2f} | {s['aic']:.0f} |")
    best = max((s for s in results if s["features"] == "full"), key=lambda s: s["C"] - abs(s["cover90"] - 0.9),
               default=None)
    if best is not None and hasattr(best["fit"], "params"):
        lines.append(f"\n## Coefficients: {best['model']}, full features (standardised)\n")
        params = list(np.asarray(best["fit"].params, dtype=float))
        names = getattr(best["fit"], "parameter_names", None) or []
        lines.append("| parameter | value |\n|---|---|")
        k_dist = len(params) - len(FULL_NAMES)
        for i, v in enumerate(params):
            label = names[i] if i < len(names) and i < k_dist else (
                FULL_NAMES[i - k_dist] if i >= k_dist else f"p{i}")
            lines.append(f"| {label} | {v:+.3f} |")
    text = "\n".join(lines) + "\n"
    print(text)
    if a.report:
        open(a.report, "w").write(text)


if __name__ == "__main__":
    main()
