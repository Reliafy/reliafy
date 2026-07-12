---
title: "B10 life: definition, formula, and a worked example"
description: "B10 life is the time by which 10% of a population has failed. Here's the exact Weibull formula, a worked calculation, how B10 relates to bearing L10, and why it beats MTBF for setting intervals."
cta_text: "Reliafy reports B10 (and any B-life) with confidence bounds on every fitted model — from your own failure data, suspensions included."
cta_label: "Calculate your B10 from real data"
cta_href: "/weibull-analysis-software"
---

**B10 life is the time by which 10% of a population is expected to have
failed** — equivalently, the time each individual unit survives with 90%
probability. It's the 10th percentile of the life distribution:

```
F(B10) = 0.10
```

The "B" convention generalises: B1 is the 1% point, B50 the median. Bearing
engineers know the same quantity as **L10** — the two are identical; "L"
(life) is simply the bearing industry's letter, from the rating-life
standards where the concept was born.

## The Weibull formula

Invert the Weibull CDF, F(t) = 1 − exp(−(t/η)^β), at F = 0.10:

```
B10 = η · (−ln 0.9)^(1/β)  =  η · (0.10536)^(1/β)
```

and in general, for any fraction q:

```
Bq = η · (−ln(1 − q))^(1/β)
```

## Worked example

A fitted Weibull for a population of conveyor bearings: **η = 6,000 hours,
β = 2.5** (wear-out).

```
B10 = 6000 × (0.10536)^(1/2.5)
    = 6000 × (0.10536)^0.4
    = 6000 × 0.4065
    ≈ 2,439 hours
```

For contrast, from the same model: the median (B50) is ≈ 5,182 hours and the
mean (MTTF) is ≈ 5,324 hours. Read those three numbers together: by the
"average life" of 5,324 hours, roughly **half the fleet is already dead**.
The B10 at 2,439 hours is the number that tells you when failures *start
arriving in earnest* — which is what a maintenance planner actually needs to
know. (More on that gap in [MTBF vs MTTF](/learn/mtbf-vs-mttf).)

The shape parameter matters enormously here. With the same η = 6,000 but
β = 1 (random failures), B10 = 6000 × 0.10536 ≈ **632 hours** — early
failures arrive four times sooner despite the identical characteristic life.
A mean can't see this difference; a B-life is built from it.

## Why B-lives beat means for decisions

- **They answer the real question.** "When do failures start?" is a
  percentile question. The mean answers "where's the balance point of the
  distribution?", which no maintenance decision actually hinges on.
- **They map to risk targets.** "No more than 10% failure probability
  before overhaul" translates directly to "interval ≤ B10". Warranty and
  safety cases work the same way with B1 or B0.1.
- **They come with uncertainty.** Fitted from data by maximum likelihood, a
  B10 carries confidence bounds. Eight failures might give you
  B10 ≈ 494 h with bounds wide enough to change the decision — better to
  know that than to discover it in the field.

One caution: a B10 is only as good as the fit behind it. It's an
extrapolation into the lower tail of the distribution, exactly where data is
thinnest — so the fit must use *all* the evidence, especially the
suspensions ([here's why that matters](/learn/censored-data-suspensions)),
and ideally more than a handful of failures.

## Frequently asked questions

### What's the difference between B10 and L10?

None — they're the same 10th-percentile life. L10 is the bearing industry's
notation (from rating-life standards such as ISO 281); B10 is the general
reliability-engineering term, reputedly from the German *Brucheinleitzeit*
era of bearing testing. Use whichever your audience expects.

### How is B10 related to reliability?

Directly: R(B10) = 0.90. A unit reaching its B10 age has a 90% chance of
having survived. In general R(Bq) = 1 − q/100 for a Bq life.

### Can B10 be longer than the MTBF?

For non-repairable items compare against MTTF: B10 is essentially always
shorter than the mean (it would take an extremely steep wear-out, β above
roughly 22, for 10% of failures to arrive later than the mean). If someone
quotes you a B10 above the mean life, one of the two numbers is wrong.

### What sample size do I need to estimate B10?

There's no magic minimum, but since B10 lives in the tail, small samples
give wide bounds. As a rule of thumb, with fewer than ~10 failures expect
the B10's confidence interval to span a factor of two or more — fit with
maximum likelihood, report the bounds, and let them inform how conservative
the interval should be.
