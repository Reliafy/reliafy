---
title: "Censored data and suspensions: why your MTBF is probably wrong"
description: "Most reliability datasets are dominated by units that haven't failed. Ignore those suspensions and your life estimates come out 2× wrong or worse. Here's what censoring is, with a worked example of the damage."
cta_text: "Reliafy fits Weibull and other life models by maximum likelihood with right-, left-, and interval-censored data — upload a CSV, mark the suspensions, and read the plot. Free to start."
cta_label: "Fit a model with your suspensions counted"
cta_href: "/weibull-analysis-software"
---

Here's a quiet scandal of industrial data analysis: the most common way of
computing MTBF — average the failure times you have — is not just imprecise
but *systematically biased*, and the bias always points the same way:
**pessimistic about life, and by a lot.**

The cause is what statisticians call **censoring** and reliability engineers
call **suspensions**: units whose failure time you don't know because they
haven't failed. In a maintenance dataset those are the majority — items
preventively replaced, items still running today, items removed for an
unrelated failure mode. If your analysis only uses the units that failed,
you've selected precisely the weakest members of the population and declared
them representative.

## The three kinds of censoring

- **Right-censored (a suspension).** The unit ran to time t without failing —
  it's still in service, or was replaced preventively. You know its life is
  *greater than* t. This is the overwhelmingly common case.
- **Left-censored.** The unit was already failed when first checked: life is
  *less than* t. Common when monitoring starts late.
- **Interval-censored.** The failure was discovered at an inspection: life is
  between the last good inspection and this one. Endemic to anything found
  on a walkdown rather than an alarm.

None of these give you a failure time to put in a spreadsheet column — and
all of them carry real information. A pump that has run 9,000 hours without
failing is strong evidence about pump life. Throwing it away because it
"hasn't got a data point yet" is exactly backwards: the *best* units in your
fleet are the ones that never make it into a failures-only analysis.

## A worked example of the damage

Twenty gearboxes. Six failed, at:

```
1,200   2,600   3,400   4,100   5,900   7,000  hours
```

Fourteen are suspensions — preventively overhauled or still running — at:

```
800  1,500  2,200  3,000  3,600  4,200  4,800
5,300  6,100  6,700  7,200  7,800  8,400  9,000  hours
```

**The naive MTBF** — average the six failure times — gives **4,033 hours**.
This number is on someone's KPI slide right now.

**Fit a Weibull to failures only** and you get β ≈ 2.2, η ≈ 4,560, a mean
life of **4,041 hours** and a [B10 life](/learn/b10-life) of **1,654 hours**.
Same bias, now with a distribution wrapped around it.

**Fit the same Weibull by maximum likelihood with all twenty units** — each
failure contributing its probability density, each suspension contributing
its probability of surviving that long — and the picture changes completely:
β ≈ 1.7, η ≈ 10,360, mean life **≈ 9,230 hours**, B10 **≈ 2,840 hours**.

The failures-only analysis understated mean life by **more than a factor of
two** and would have you replacing gearboxes nearly twice as often as the
evidence supports. Nothing about the example is contrived — 6 failures in 20
units is a *high* failure fraction for a maintained fleet. The sparser your
failures (i.e. the better your maintenance), the worse the naive numbers get.
It's one of engineering's crueler ironies: **the more effective your
preventive maintenance, the more wrong your failures-only statistics become.**

## How suspensions enter the math

Maximum likelihood handles this without any adjustment tricks. Each unit
contributes what you actually know about it to the likelihood:

```
failure at t:      f(t)        — the density at the failure time
suspension at t:   R(t)        — the probability of surviving past t
failed between a and b:  F(b) − F(a)
```

Maximise the product over all units and you get parameter estimates that use
every unit in the fleet, plus confidence bounds from the curvature of the
likelihood. This is what any serious
[Weibull analysis software](/weibull-analysis-software) does by default —
and what a spreadsheet doesn't. (If you're currently doing
[Weibull analysis in Excel](/learn/weibull-analysis-in-excel), that guide
shows exactly where the spreadsheet method runs out.)

## What to record so your data isn't hostage

The fix costs almost nothing at data-entry time:

1. **Log removals, not just failures.** Every component that leaves service
   gets a time and a reason — failed, preventive, cannibalised, upgrade.
2. **Keep "failed" honest.** A preventive replacement logged as a failure
   poisons the data in the *other* direction.
3. **Snapshot the survivors.** The current age of every unit still running
   is data — often most of your data.

Do that, and a CSV export from your CMMS is a complete life-data study
waiting to be fitted.

## Frequently asked questions

### What is a suspension in reliability analysis?

A unit removed from observation before it failed — preventively replaced,
still in service, or retired for an unrelated reason. Statistically it's a
right-censored observation: its failure time is known only to exceed its
removal time. Suspensions carry real information and must be included in a
life-data analysis.

### Why does ignoring suspensions bias life estimates low?

Because the units that failed are, by selection, the weakest in the
population. The strongest units are still running — so they appear in the
data only as suspensions. Analyse failures alone and you've studied the
worst performers and generalised to the fleet.

### Can I just add suspensions as if they were failures?

No — that biases the result in the same direction. A suspension at 5,000
hours says "life exceeds 5,000 hours", not "life equals 5,000 hours".
Treating it as a failure claims the unit died the moment you stopped
watching it.

### How much censored data is too much?

There's no cliff — maximum likelihood degrades gracefully. Even with 90%+
suspensions you get usable estimates; the confidence bounds simply widen to
reflect how few failures you observed. That widening is the honest answer,
and it's why bounds matter as much as the point estimate.
