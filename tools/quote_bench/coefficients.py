"""The quote engine's coefficients (#286), from timed runs.

Fits SurPyval's log-normal AFT on the minimal features (replications, events
per replication, blocks; unstandardised, so the coefficients apply as they
are) and prints the JSON the web app reads
(``backend/services/runtime_quote.json``), keeping its machine factors.

A run the alarm stopped is right-censored at its cap. A run that finished
after the cap (the pilot's cap couldn't interrupt the engine's compiled
loops) is an observed time: it really took that long.

    python -m tools.quote_bench.coefficients tools/quote_bench/data/pilot-dev-laptop.jsonl [--write]
"""

from __future__ import annotations

import argparse
import json
import math
import os
import warnings

import numpy as np
import surpyval as sv

TARGET = os.path.join(os.path.dirname(__file__), "..", "..", "backend", "services", "runtime_quote.json")


def load(path: str):
    rows = [json.loads(line) for line in open(path) if line.strip()]
    keep = [r for r in rows if r["result"].get("status") in ("ok", "censored")]
    x = np.array([max(float(r["result"]["seconds"]), 1e-3) for r in keep])
    c = np.array([1 if r["result"]["status"] == "censored" else 0 for r in keep])
    Z = np.array([[math.log(f["n_simulations"]), math.log1p(f["events_per_rep"]), math.log(max(f["n_blocks"], 1))]
                  for f in (r["features"] for r in keep)])
    return keep, x, c, Z


def fit(path: str) -> dict:
    keep, x, c, Z = load(path)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        model = sv.LogNormalAFT.fit(x=x, Z=Z, c=c)
    mu, sigma, *beta = (float(v) for v in model.params)
    # SurPyval's AFT: ln T = mu - Z·beta.
    return {
        "intercept": round(mu, 3),
        "sigma": round(sigma, 3),
        "coefficients": {
            "log_replications": round(-beta[0], 3),
            "log1p_events_per_replication": round(-beta[1], 3),
            "log_blocks": round(-beta[2], 3),
        },
        "fitted_on": {
            "data": os.path.relpath(path, os.path.join(os.path.dirname(__file__), "..", "..")),
            "points": len(x),
            "censored": int(c.sum()),
            "machine": keep[0].get("machine") if keep else None,
        },
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("runs")
    ap.add_argument("--write", action="store_true", help="update backend/services/runtime_quote.json")
    a = ap.parse_args()
    with open(TARGET, encoding="utf-8") as fh:
        current = json.load(fh)
    out = {**current, **fit(a.runs)}
    text = json.dumps(out, indent=2, ensure_ascii=False) + "\n"
    print(text)
    if a.write:
        with open(TARGET, "w", encoding="utf-8") as fh:
            fh.write(text)


if __name__ == "__main__":
    main()
