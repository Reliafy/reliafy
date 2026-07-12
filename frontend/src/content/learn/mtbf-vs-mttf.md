---
title: "MTBF vs MTTF: the difference, when each applies, and how both mislead"
description: "MTBF is for repairable systems, MTTF for non-repairable — that's the textbook line. Here's the full story: exact definitions, how to compute each from real data, and the ways both numbers routinely deceive."
cta_text: "A mean is one number; a fitted life distribution is the whole story — failure pattern, B-lives, and confidence bounds included. Reliafy fits them from your CSV in seconds."
cta_label: "Go beyond the mean with Reliafy"
cta_href: "/reliability-analysis-software"
---

The short version, if that's all you need:

- **MTTF — Mean Time To Failure** — applies to things you *replace*:
  bearings, seals, lamps, fuses. It's the expected lifetime of one unit.
- **MTBF — Mean Time Between Failures** — applies to things you *repair*:
  pumps, compressors, servers. It's the average operating time between
  successive failures of the same system.
- The divider is one question: **after the failure, is it the same item
  (repaired) or a new one (replaced)?**

That answer is correct and will pass any exam. The rest of this page is the
part that actually matters in practice: how each is computed, why the two
get conflated, and the three ways these numbers routinely mislead the people
they're reported to.

## MTTF: the mean of a life distribution

For a non-repairable item, life is a random variable with some distribution —
Weibull, Lognormal, whatever fits. MTTF is that distribution's mean:

```
MTTF = ∫₀^∞ R(t) dt        (the area under the reliability curve)
```

The right way to estimate it is to fit the life distribution to your data —
**including the units that haven't failed**, which is most of them in any
maintained fleet (see
[censored data and suspensions](/learn/censored-data-suspensions) for how
badly it goes wrong otherwise) — and take the fitted mean.

## MTBF: a rate, dressed as a time

For a repairable system, failures form a sequence in time. In its common
industrial use, MTBF is:

```
MTBF = total operating time / number of failures
```

Note what this is: the reciprocal of an average failure *rate*. It says
nothing about the *pattern* of failures — a system failing like clockwork
every 1,000 hours and a system alternating 100-hour and 1,900-hour intervals
both report MTBF = 1,000 hours. One of them is telling you something is
wrong with your overhauls; the average can't hear it. (Trend analysis of
repairable systems — is it degrading or improving? — is a Crow-AMSAA
question, not an MTBF question.)

## The three standard deceptions

**1. An MTBF of 100,000 hours does not mean it lasts 11 years.**
MTBF figures on datasheets describe the failure rate *during useful life*,
before wear-out. A hard drive with a million-hour MTBF isn't expected to run
for 114 years; it's expected to fail at a rate of about 1 per 114
drive-years *while within its (say) 5-year design life*. Fleet-level rate,
not unit-level lifetime — most datasheet-MTBF outrage dissolves once this
distinction lands.

**2. Most units are dead before the mean.**
For the exponential distribution (constant failure rate — the assumption
buried in most MTBF arithmetic), the probability of failing *before* the
MTBF is 1 − 1/e ≈ **63.2%**. For a wear-out mode (Weibull β = 2.5,
η = 6,000 h) the mean is 5,324 hours and about **52%** of units are dead by
then. The mean is not "when it fails"; it's the balance point of a skewed
distribution. If the question is "when should we intervene?", you want a
[B10 life](/learn/b10-life), not a mean.

**3. The mean hides the failure pattern — which decides your strategy.**
Two components, both MTTF = 5,000 hours. One has Weibull β = 0.9 (infant
mortality): replacing it on a schedule *increases* failures, because
replacements die young. The other has β = 3 (wear-out): scheduled
replacement is exactly right. Identical means, opposite maintenance
policies. The number everyone reports contains zero bits of the information
the decision needed.

## How to compute each honestly

| | MTTF (non-repairable) | MTBF (repairable) |
|---|---|---|
| Data | Lifetimes of units, **including suspensions** | Operating hours and failure count per system |
| Method | Fit a life distribution (MLE), take its mean | Total time / failures — *after checking the rate is stable* |
| Watch out for | Failures-only averaging (biases low, often 2×) | Trends: an improving or degrading system makes one number meaningless |
| Better companions | B10 life, full distribution, confidence bounds | Rate over time, Crow-AMSAA trend, Duane plot |

Both columns share one prerequisite people skip: the arithmetic is only as
good as the event data. "Total time / failures" silently assumes an
exponential world (constant rate). It's a fine screening number — it's just
not a lifetime, a guarantee, or a maintenance interval.

## Frequently asked questions

### Is MTBF the same as MTTF plus repair time?

In some standards MTBF is decomposed as MTBF = MTTF + MTTR (time between
failures = time to failure + time to repair). In practice repair time is
usually negligible against operating time, and industrial usage treats MTBF
simply as mean *operating* time between failures. What matters is knowing
which convention a number in front of you used.

### Can I convert MTBF to failure rate?

Under a constant-failure-rate (exponential) assumption, failure rate
λ = 1/MTBF. An MTBF of 50,000 hours is a rate of 2×10⁻⁵ failures per hour.
The conversion is only as valid as the constant-rate assumption — it fails
for wear-out and infant-mortality patterns.

### What's the probability of surviving to the MTBF?

With a constant failure rate, R(MTBF) = 1/e ≈ 36.8% — nearly two-thirds of
units fail before it. For wear-out modes the fraction failing before the
mean is typically 50–60%. Either way, the mean is not a "safe until" time.

### Which should I use for a maintenance interval?

Neither, directly. Intervals should come from the fitted life distribution —
a B-life for risk-based limits, or a cost-optimal replacement calculation
that weighs planned against unplanned replacement cost. A mean alone cannot
answer "when", only "how often on average".
