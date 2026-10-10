# Runtime model comparison

800 design points: {'ok': 796, 'censored': 4}. Modelled: 800 (85 censored at the cap). Runtime median 1.90 s, 90th percentile 60.0 s, max 60.0 s. Exact-only part: median 0.032 s.


## Features: minimal

| model | C | error (×) | cover90 | over90 (×) | AIC |
|---|---|---|---|---|---|
| LogNormalAFT | 0.920 | 1.50 | 0.93 | 2.68 | 2266 |
| WeibullAFT | 0.915 | 1.53 | 0.96 | 3.45 | 2718 |
| GammaAFT | 0.916 | 1.56 | 0.95 | 3.10 | 2628 |
| LogisticAFT | 0.913 | 1.56 | 0.91 | 2.54 | 3062 |
| GumbelAFT | 0.833 | 2.31 | 0.97 | 7.12 | 5201 |
| ExponentialAFT | 0.915 | 1.51 | 0.96 | 3.67 | 2724 |
| LogNormalPH | 0.916 | 1.48 | 0.97 | 3.88 | 2683 |
| CoxPH | 0.915 | 1.45 | 0.96 | 3.52 | 7094 |

## Features: full

| model | C | error (×) | cover90 | over90 (×) | AIC |
|---|---|---|---|---|---|
| LogNormalAFT | 0.926 | 1.45 | 0.93 | 2.37 | 2110 |
| WeibullAFT | 0.908 | 1.57 | 0.93 | 2.77 | 2479 |
| GammaAFT | 0.914 | 1.55 | 0.92 | 2.55 | 2358 |
| LogisticAFT | 0.912 | 1.54 | 0.88 | 2.20 | 2642 |
| GumbelAFT | 0.872 | 1.92 | 0.93 | 3.63 | 3564 |
| ExponentialAFT | 0.913 | 1.52 | 0.96 | 3.19 | 2585 |
| LogNormalPH | 0.915 | 1.53 | 0.97 | 3.18 | 2537 |
| CoxPH | 0.910 | 1.53 | 0.95 | 2.61 | 6856 |

## Coefficients: LogNormalAFT, full features (standardised)

| parameter | value |
|---|---|
| mu | +0.929 |
| sigma | +0.613 |
| log n_sims | -1.118 |
| log1p events/rep | -1.646 |
| log blocks | +0.597 |
| log1p edges | -0.885 |
| branch pts/block | +0.126 |
| has vote | -0.002 |
| standby/block | +0.098 |
| has CCF | +0.012 |
| CCF in sim | -0.114 |
| bridge | -0.025 |
| limited crews | +0.137 |
| non-exp life | -0.030 |
| preventive/block | -0.181 |
| inspection/block | -0.101 |
| instant/block | -0.002 |
| costs | -0.081 |
| log horizon | +0.118 |
