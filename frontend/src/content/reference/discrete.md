---
family: discrete
title: "Discrete distributions"
description: "Life measured in whole counts — cycles, shocks, or demands to failure. Parameters, forms, and when each applies."
---

Use these when life is a **count**, not a duration: cycles to failure, shocks
survived, demands before a failure. They take the same `x`/`c`/`n` mapping as
the continuous distributions, but there's no probability paper for them — you
get parameters, reliability functions and goodness-of-fit, without the plot.

## discrete_weibull

**The whole-count analogue of the Weibull**, with the same shape-driven
behaviour over a discrete support.

```
R(k) = q^(k^β)
```

**Use it for** cycles-to-failure or shocks-to-failure where you'd reach for a
Weibull if time were continuous. **Watch out:** if counts are large (thousands of
cycles), the continuous Weibull is usually easier to interpret and loses nothing.

## geometric

**The discrete memoryless model** — the counting analogue of the exponential.
Each trial fails independently with the same probability.

```
R(k) = (1 − p)^k
```

**Use it for** per-demand failures where history genuinely doesn't matter.
**Watch out:** as with the exponential, the memoryless assumption is often
assumed rather than checked — if failures cluster with age, this will hide it.

## beta_geometric

**Geometric with unit-to-unit variation.** The per-trial failure probability
isn't one number: it varies across the population, drawn from a Beta.

```
p ~ Beta(α, β),   then  k | p ~ Geometric(p)
```

**Use it when** a plain geometric under-predicts survivors — heterogeneity means
weak units fail early and the remainder are tougher than the average implies.
**Watch out:** you need a decent sample to separate real heterogeneity from noise.

## negative_binomial

**Trials until several failures**, rather than the first — more dispersed than
the geometric.

```
Number of trials until the r-th failure, each with probability p
```

**Use it for** counts that are over-dispersed relative to a simple model, or when
a unit tolerates several events before it's considered failed. **Watch out:** its
extra parameter can absorb over-dispersion that actually comes from mixing
distinct populations.

## poisson

**Counts of events in a fixed exposure** — the classic count model.

```
P(k) = e^(−λ)·λ^k / k!
```

`λ` is both the mean and the variance.

**Use it for** number of events per unit of time or usage. **Watch out:** the
mean-equals-variance property is a strong claim. If your data's variance clearly
exceeds its mean, prefer the negative binomial. Note too that this models a
*count*, not a time to failure — for repairable-system event histories, the
recurrent-event models are the right tool.
