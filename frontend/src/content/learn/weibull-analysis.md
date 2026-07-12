---
title: "Weibull analysis: a complete, practical guide"
order: 1
description: "What Weibull analysis is, what the shape and scale parameters actually tell you, how fitting works (with a worked example), how censored data changes everything, and how the results turn into maintenance decisions."
cta_text: "Everything on this page — MLE fitting, censored data, probability plots, confidence bounds, B-lives — is what Reliafy does from a CSV upload. Free to start, open source at the core."
cta_label: "Run a Weibull analysis on your data"
cta_href: "/weibull-analysis-software"
---

Weibull analysis is the workhorse of reliability engineering: a method for
taking a list of failure times and turning it into answers — *how* do these
things fail, *when* will they fail, and *what should we do about it?* It has
held that position for seventy years for one reason: the Weibull
distribution is flexible enough to describe almost every failure behaviour
that occurs in practice, using just two numbers.

This guide is the whole method, honestly told: what the parameters mean, how
fitting actually works, the censoring issue that invalidates most quick
analyses, a worked example with real numbers, and what to do with the
results. Nothing here requires more than engineering-school statistics.

## The distribution in one equation

The Weibull distribution says the probability that an item has failed by
time *t* is:

```
F(t) = 1 − exp(−(t/η)^β)
```

Two parameters, each with a direct physical reading:

- **β — the shape parameter.** *How* things fail. It's the exponent on
  time, so it controls whether the failure rate falls, holds steady, or
  climbs as the item ages.
- **η — the scale parameter, or characteristic life.** *When* things fail:
  the time by which 63.2% of the population has failed, whatever β is.
  (Set t = η and F = 1 − 1/e ≈ 0.632 falls out of the equation.)

From F(t) come the other three functions you'll meet, all equivalent views
of the same fit: the reliability (survival) function R(t) = 1 − F(t), the
density f(t), and the **hazard rate** h(t) = f(t)/R(t) — the instantaneous
failure rate of survivors, the curve maintenance decisions actually hinge on:

```
h(t) = (β/η) · (t/η)^(β−1)
```

## β is the diagnosis

The reason engineers reach for Weibull rather than any other distribution is
what β tells you before you've done anything else:

- **β < 1 — infant mortality.** The hazard *falls* with age: survivors are
  the good ones. Think manufacturing defects, bad installs, workmanship.
  Scheduled replacement is actively harmful here — you'd be swapping proven
  survivors for risky new units. Fix the process, screen with burn-in.
- **β ≈ 1 — random failures.** Constant hazard; age carries no information.
  This is the exponential distribution as a special case. Scheduled
  replacement buys *nothing* — run to failure, or monitor condition if the
  consequence is severe.
- **β > 1 — wear-out.** Hazard climbs with age: fatigue, wear, corrosion,
  erosion. Now age-based replacement can pay, and the steeper the β, the
  more predictable the failure and the stronger the case. β of 2–4 is
  typical mechanical wear-out; β above ~6 is so sharply timed you can almost
  schedule around it.

The three regimes are the three phases of the classic bathtub curve — but a
single fitted β tells you which phase *your* failure mode actually lives in,
which is worth more than the generic picture. One caution: a fleet mixing
two failure modes (say, some infant mortality plus some wear-out) can fit to
a meaningless in-between β. If the probability plot bends or the physics
says two mechanisms, separate the modes and fit them individually.

## How fitting works

Two families of methods, and knowing which to use matters more than most
tutorials let on.

**Median rank regression (MRR)** is the classical, spreadsheet-friendly
approach: sort the failures, assign each an estimated failure probability
(Bernard's approximation), transform so a Weibull becomes a straight line,
and fit the line — the slope is β. It's transparent, it pairs naturally
with the probability plot, and [you can do it in
Excel](/learn/weibull-analysis-in-excel) in ten minutes.

**Maximum likelihood estimation (MLE)** asks instead: *which (β, η) makes
the observed data most probable?* Each observation contributes what you
actually know about it to a likelihood function, and an optimiser finds the
parameters that maximise it. This is what modern software uses by default,
for two hard-nosed reasons: it handles censored data correctly (next
section — this is the decisive one), and its confidence bounds are
well-founded rather than improvised.

On a clean, complete sample the two agree reasonably; on small or censored
samples they can differ noticeably, and MLE is the defensible choice.

## Censoring: the part that invalidates quick analyses

Everything above quietly assumed every unit ran until it failed. Real
maintenance data is never like that — most of your fleet *hasn't* failed:
units preventively replaced, still running, or removed for other reasons.
These **suspensions** are right-censored observations, and they are not
missing data. A bearing that ran 9,000 hours without failing is strong
evidence about bearing life.

Leave suspensions out and your analysis studies only the weakest units in
the population — the ones that failed — and generalises their frailty to
the whole fleet. The bias is always pessimistic and routinely a factor of
two on life estimates.
[The worked demonstration is here](/learn/censored-data-suspensions); the
one-line summary is that MLE fixes it naturally (a failure at *t*
contributes its density f(t); a suspension at *t* contributes its survival
probability R(t)) and plotting methods don't.

The practical rule: **if your data came from a CMMS, it has suspensions,
and the analysis must include them.**

## A worked example

Eight seal failures, in operating hours:

```
410, 780, 1120, 1400, 1680, 1970, 2300, 2750
```

Fit a Weibull by MLE and you get **β = 2.27, η = 1,753 hours**. Reading it:

- **β = 2.27 — wear-out.** Seals degrade with age; age-based replacement is
  on the table. (The [Excel walkthrough](/learn/weibull-analysis-in-excel)
  fits this same dataset by median rank regression and gets β ≈ 1.74 —
  a good illustration of how much method choice matters at n = 8.)
- **Characteristic life 1,753 h**: 63% of seals are gone by then.
- **[B10 life](/learn/b10-life) ≈ 650 h** — failures start arriving in
  earnest around 650 hours. The median (B50) is ≈ 1,490 h and the mean
  ≈ 1,550 h — note how much later the "average" is than the number a
  planner actually needs.
- **The hazard curve quantifies the wear-out**: a survivor at 500 h is
  failing at ~0.26 per 1,000 h; at 2,000 h, ~1.5 per 1,000 h — six times
  the risk. That gradient is what justifies replacing old seals first.

Eight failures is a small sample, and the honest fit says so: confidence
bounds on that B10 span roughly a factor of two. That width isn't a defect
of the method — it's the true state of your knowledge, and it should shape
how conservative the maintenance interval is until more data arrives.

## Always look at the plot

A Weibull probability plot — the data on transformed axes where a true
Weibull falls on a straight line — is the analysis's lie detector. Points
hugging the line: the model fits. A curve or elbow: something's wrong, and
the *shape* of wrong is diagnostic. A downward bow at early times often
means a failure-free period (a three-parameter Weibull with a location
offset, common in fatigue). A kink suggests two failure modes mixed
together. Never report parameters from a plot you haven't looked at.

## From parameters to decisions

The fit is the means, not the end:

- **Choose the policy by β** — run-to-failure for β ≈ 1, age-based
  replacement for wear-out, process fixes for infant mortality.
- **Set the interval by economics, not eyeball**: with the fitted model and
  the cost ratio of planned vs unplanned replacement, the cost-optimal
  preventive interval is a standard calculation (Reliafy runs it directly
  from any saved model).
- **Set risk limits with B-lives** — "interval ≤ B10" style targets for
  warranty, safety cases, and inspection planning.
- **Feed system models**: fitted component Weibulls are the inputs to
  reliability block diagrams and to
  [MTBF/MTTF figures](/learn/mtbf-vs-mttf) that actually mean something.

## Frequently asked questions

### What is Weibull analysis used for?

Fitting a life distribution to failure data in order to identify the
failure pattern (infant mortality, random, or wear-out), estimate lifetimes
with confidence bounds, and set maintenance, replacement, warranty, and
spares policies. It's the standard first analysis in reliability
engineering because the Weibull distribution can represent all three
failure regimes with one shape parameter.

### How many failures do I need for a Weibull analysis?

You can fit with as few as 2–3 failures plus suspensions, but expect very
wide confidence bounds. Around 6–10 failures the picture firms up; beyond
~20 the parameters are usually stable. The right response to a small sample
isn't to skip the analysis — it's to fit by MLE, report the bounds, and let
their width temper the decision.

### What does a Weibull shape parameter of exactly 1 mean?

β = 1 reduces the Weibull to the exponential distribution: constant hazard
rate, failures arriving at random regardless of age. Preventive replacement
has zero benefit — a new unit is exactly as likely to fail tomorrow as the
old one it replaced.

### What's the difference between the two-parameter and three-parameter Weibull?

The three-parameter form adds a location parameter γ: no failures can occur
before time γ. It suits mechanisms with a genuine failure-free period, like
fatigue crack initiation. Use it only when the physics supports it and the
probability plot shows the characteristic early-time curvature — an
unjustified γ is an easy way to flatter the fit.

### Weibull analysis vs lognormal — which should I use?

Fit both and compare (probability plots plus a criterion like AIC). Weibull
usually wins for wear-out and weakest-link mechanisms; lognormal often fits
degradation processes that multiply, like crack growth. If they disagree
materially in the region your decision lives in (say, the lower tail),
that's a sign the data doesn't yet settle the question — widen the bounds
you act on.
