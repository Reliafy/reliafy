# Simulation runtime quotes (#286)

How long will a repairable diagram's simulation take? Runtime is treated as a
survival time: a run stopped at a time cap is right-censored there. A SurPyval
regression model fitted to features a quote can see before running then gives
a predicted median runtime (the estimate) and a 90th percentile (the ceiling).

```
python -m tools.quote_bench.run --n 800 --workers 3 --cap 60 --out runs.jsonl   # resumable
python -m tools.quote_bench.analyse runs.jsonl --report report.md
```

- `generate.py`: design point *i* draws its factors and builds a random
  repairable diagram from them. The factors are size, architecture
  (parallel branches, k-of-n votes, bridges, standby), life and repair
  models, preventive replacement, proof tests, crews, common cause, costs,
  horizon and replications. It also records the features a quote can see.
  Deterministic for `(seed, i)`.
- `run.py` / `run_one.py`: time each point as the compute service runs it
  (`compute_core.run_availability`), each in its own process, after a warm-up.
  Also times the exact-only part.
- `analyse.py`: fits 8 SurPyval regression models on a minimal feature set
  (replications, events per replication, blocks) and on the full one, then
  scores each with 5-fold cross-validation.

Timings are machine-specific. Use a pilot to choose the model form, then
collect the data the quote's coefficients come from on the compute service's
own machine type.

## Pilot (dev laptop, 800 points, `data/`)

The **log-normal AFT** model is best on every measure:

| | full features | minimal features |
|---|---|---|
| Concordance | 0.922 | 0.916 |
| Typical error of the median | ×1.47 | ×1.53 |
| Coverage of the 90th percentile | 0.91 | 0.92 |
| AIC | 2844 | 2975 |

Weibull, gamma, exponential, logistic and Cox models rank jobs nearly as well,
but fit worse (higher AIC) and over-quote more. Gumbel is clearly worst.

What drives the runtime: the effect on the median of a unit change in each
feature, all else equal:

- **Replications:** runtime grows as *n*^0.58, not linearly. Replications are
  vectorised, and there is fixed set-up.
- **Expected failures per replication:** runtime grows as (1 + events)^0.58.
- **Structure:** edges matter more than blocks (×1.57 per unit of
  log(1 + edges)).
- **Maintenance:** proof tests and preventive replacement on every block make
  a run about ×2.5–2.8 slower.
- **Common cause:** a common-cause group included in the simulation makes it
  ×1.65 slower.
- **Little effect:** votes, bridges, non-exponential lives, costs and the
  horizon (beyond the events it implies).

The residual spread is σ ≈ 0.6 on the log scale, so the 90th percentile is
about 2.3× the median. Part of that noise comes from running 3 jobs at once
on mixed performance and efficiency cores. A dedicated machine should
tighten it.

The pilot's 60 s cap could not interrupt the engine's compiled loops (81 runs
finished later than 60 s; only 4 were stopped). The data is still sound, as
the late runs are observed times. In production, the time budget stops runs
between batches, and those runs are the censored ones.
