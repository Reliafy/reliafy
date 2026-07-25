---
family: nonparametric
title: "Non-parametric estimators"
description: "Empirical survival estimates that assume no distribution — Kaplan-Meier, Nelson-Aalen, Fleming-Harrington and Turnbull, and when each is the right choice."
---

These estimate the survival curve **directly from the data**, with no assumed
shape. That makes them the honest first look — and the right answer when no
distribution fits — but they can't extrapolate beyond your last observation, and
they give you a curve rather than parameters.

Use one when you want to *see* what the data says, to check a parametric fit
against, or when the shape is genuinely unknown. Use a distribution when you
need to predict past the data, or feed a model into an RBD or a replacement
calculation.

## kaplan_meier

**The standard empirical survival estimator.** A step function that drops at
each failure, with censored units correctly reducing the risk set without
causing a step.

```
R(t) = Π  (1 − dᵢ/nᵢ)   over failure times tᵢ ≤ t
```

**Use it as** the default non-parametric view, and as the backdrop to judge a
parametric fit against. **Watch out:** the curve stops at your last observation
— if that's a censoring time, the tail is simply unknown, not flat.

## nelson_aalen

**Estimates the cumulative hazard**, then converts to survival — often better
behaved than Kaplan-Meier in small samples or heavy censoring.

```
H(t) = Σ  dᵢ/nᵢ ,     R(t) = exp(−H(t))
```

**Use it when** samples are small, or when you want to read the cumulative
hazard directly — its slope is the failure rate, which makes trend easy to see.
**Watch out:** it and Kaplan-Meier converge as samples grow; disagreement is a
sign of thin data, not of one being wrong.

## fleming_harrington

**A tie-corrected refinement of Nelson-Aalen**, handling simultaneous failures
more carefully.

```
Adjusts each increment for the number of tied failures at that time
```

**Use it when** many units fail at exactly the same recorded time — common with
inspection-based data where everything lands on the same date. **Watch out:** if
you have no ties it gives you Nelson-Aalen, so it's not a decision worth
agonising over.

## turnbull

**The estimator for interval-censored data** — the general case where you know
only that failure fell between two inspections.

```
Iteratively assigns probability mass to the intervals it could have fallen in
```

**Use it when** failures were found at inspections rather than observed as they
happened, or when you have a mix of exact, interval, left- and right-censored
observations. **Watch out:** the result can have flat regions where the data
cannot distinguish *when* within an interval the failures occurred — that
ambiguity is real, not an artifact.
