---
family: distributions
title: "Life distributions"
description: "Every continuous life distribution Reliafy fits — parameters, survival and hazard functions, when to use each, and what to watch for."
---

These describe **time to a single failure** for an item that is run to failure or
replaced. Parameterisations below are the ones Reliafy fits and reports, which
are SurPyval's — worth checking against your textbook, because conventions
differ (notably Gamma, whose second parameter here is a *rate*).

Throughout, `R(t)` is reliability (the survival function), `F(t) = 1 − R(t)` is
unreliability, and `h(t)` is the hazard rate.

Any of these can be fitted as a **mixture** of 2–4 components — several copies of
the same distribution with weights summing to 1 — for data holding more than one
failure mode. That is what curves the probability plot: no single distribution
can follow two modes at once. A mixture always fits better than a single
distribution because it has more parameters, so judge it on the AIC, not on the
plot. Mixture fits report no confidence bounds.

## weibull

**The workhorse of life-data analysis.** Its shape parameter spans
infant-mortality, random, and wear-out behaviour, which is why it fits so much
real equipment — and why β is usually the most decision-relevant number on the
page.

```
R(t) = exp(−(t/α)^β)
h(t) = (β/α)·(t/α)^(β−1)
```

`α` is the characteristic life (the 63.2% point); `β` is the shape.

**Reading β:** below 1, failures are *decreasing* — infant mortality, and
scheduled replacement makes things worse. Around 1 the rate is constant and age
tells you nothing. Above 1 it's wear-out, and preventive replacement can pay.

**Use it when** you have no strong reason to pick something else. **Watch for**
data that curves on the probability plot — that usually means two failure modes
mixed together, better split than forced into one Weibull.

## exponential

**Constant failure rate — the memoryless case.** A used unit is exactly as good
as a new one.

```
R(t) = exp(−λt)
h(t) = λ          (constant)
```

`λ` is the failure rate; the mean life is `1/λ`.

**Use it for** genuinely random, externally-driven failures, and as a null model
to test wear-out against. **Watch out:** it's assumed far more often than it's
true, usually because it's convenient. If the real β is 2, exponential will
badly misprice a replacement policy. Fit Weibull and look at β before accepting
it.

## normal

**Gaussian location–scale.** Symmetric, with a hazard that always increases.

```
R(t) = 1 − Φ((t − μ)/σ)
```

**Use it for** wear-out that clusters tightly around a mean — tool wear, some
mechanical fatigue. **Watch out:** its support is the whole real line, so it puts
non-zero probability on negative life. That's harmless when μ ≫ σ and misleading
when it isn't.

## lognormal

**Normal on the log scale** — right-skewed, with a hazard that rises then falls.

```
F(t) = Φ((ln t − μ)/σ)
```

`μ` and `σ` are the mean and standard deviation of `ln t`, *not* of `t`.

**Use it for** repair times (the standard choice for MTTR), fatigue crack growth,
and degradation-driven failures — anything produced by many multiplicative
effects. **Watch out** for the parameters being on the log scale; reading μ as a
mean life is a common and large error.

## gamma

**A sum of exponential stages.** Naturally models failure after a number of
independent shocks or phases.

```
F(t) = P(α, β·t)      (regularised lower incomplete gamma)
```

`α` is the shape; **`β` is a rate, not a scale** — mean life is `α/β`. Many texts
parameterise Gamma with a scale, so halve your attention here when comparing.

**Use it when** failure follows an accumulation of events. **Watch out:** it
often fits similarly to Weibull; prefer whichever the physics supports rather
than a marginal AIC difference.

## loglogistic

**Log-scale logistic** — like lognormal but with heavier tails, and a
closed-form survival function.

```
R(t) = 1 / (1 + (t/α)^β)
```

**Use it for** the same skewed situations as lognormal, especially when you want
a non-monotonic hazard in closed form. **Watch out:** the heavy tail implies a
meaningful chance of very long lives, which can flatter long-horizon
predictions.

## expo_weibull

**Exponentiated Weibull** — a third shape parameter that unlocks non-monotonic
hazards, including genuine bathtub curves.

```
R(t) = 1 − [1 − exp(−(t/α)^β)]^μ
```

**Use it when** a two-parameter Weibull visibly can't follow the data and you
have enough failures to justify a third parameter. **Watch out** for
overfitting: with small samples the extra flexibility buys fit, not insight.

## gumbel

**Smallest-extreme-value distribution.** The limiting distribution of the
*minimum* of many independent lives — a weakest-link system.

```
R(t) = exp(−exp((t − μ)/σ))
h(t) = (1/σ)·exp((t − μ)/σ)
```

**Use it for** weakest-link failure, and note the close relation to Weibull:
if `t` is Weibull, `ln t` is smallest-extreme-value. **Watch out:** support is
the whole real line, so like Normal it admits negative times.

## gumbel_lev

**Largest-extreme-value distribution** — the limit of the *maximum* of many
draws.

```
F(t) = exp(−exp(−(t − μ)/σ))
```

**Use it for** maxima rather than minima: peak loads, extreme temperatures,
worst-case demand. **Watch out:** it's rarely the right model for time-to-failure
itself, which is usually a minimum problem — reach for `gumbel` there.

## logistic

**Symmetric location–scale with heavier tails than Normal.**

```
R(t) = 1 / (1 + exp((t − μ)/σ))
```

**Use it as** a Normal alternative when the tails look too heavy for Gaussian.
**Watch out:** same real-line support caveat as Normal, and it's uncommon as a
primary life model — usually it appears as a regression baseline.

## rayleigh

**A single-parameter model with a linearly rising hazard** — exactly Weibull
with β = 2.

```
R(t) = exp(−t²/(2σ²))
h(t) = t/σ²
```

**Use it when** you have good reason to believe hazard grows linearly with age
and want to spend only one parameter — small samples benefit from the
constraint. **Watch out:** if β isn't really 2, you've hard-coded a wrong
assumption; fit Weibull first and check.

## beta

**Life as a fraction between 0 and 1** — a proportion degraded, a fraction of
rated life, a share of a mission.

```
f(x) = x^(α−1)·(1 − x)^(β−1) / B(α, β),   0 < x < 1
```

Both shapes `α` and `β` are positive; `α = β = 1` is the uniform.

**Use it when** the quantity you recorded is bounded at 0 and 1 by its nature.
**Watch out:** it can't fit times — anything at or past 1 is refused — so it
never enters Best fit or a mixture. Rescale only when the bound is real, not to
squeeze ordinary lifetimes into (0, 1).

## beta4

**A Beta on an interval of your data's own scale** — four parameters: the two
shapes and the end points `a` and `b`.

```
f(x) = (x − a)^(α−1)·(b − x)^(β−1) / (B(α, β)·(b − a)^(α+β−1)),   a < x < b
```

**Use it when** life is known to sit between a floor and a ceiling, as with a
part retired at a fixed limit. **Watch out:** the end points are estimated from
the sample, so the fit says every unit fails by `b` — a strong claim past the
largest observation. With shapes below 1 the likelihood has no maximum: fit by
maximum product of spacings (MPS) then. Not a Best-fit candidate.

## uniform

**Equally likely anywhere between `a` and `b`.**

```
R(t) = (b − t)/(b − a),   a ≤ t ≤ b
h(t) = 1/(b − t)
```

**Use it for** a quick bound when all you know is a range, or as a check on a
fitted shape. **Watch out:** the estimates are the smallest and largest
observations, and they carry no confidence bounds. Not a Best-fit candidate.

## royston_parmar

**A flexible spline for the survival curve** (Royston and Parmar): the log
cumulative hazard is a restricted cubic spline in log time, with three spline
terms on the proportional-hazards scale.

```
log H(t) = s(log t; γ₀, γ₁, γ₂, γ₃)
```

With one term it is exactly the Weibull. The coefficients `γ` have no physical
meaning on their own; read the curve instead, which Reliafy draws over the
data's Kaplan-Meier estimate.

**Use it when** no single distribution follows the data — a hazard that rises
and then falls, say — but you still want smooth curves, B-lives with bounds and
an AIC to compare with the plain distributions on the same data. **Watch out:**
like any spline, it follows the data closely inside their range and says little
beyond it.
