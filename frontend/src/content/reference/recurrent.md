---
family: recurrent
title: "Recurrent-event models"
description: "Repairable systems — how often a fleet fails over time, whether it's improving or deteriorating, and how to read the reliability-growth parameter."
---

These describe **repairable systems**, which is a genuinely different problem
from the life distributions. A distribution asks *how long until this item
fails?* — one failure, then the item is gone or replaced. A recurrent-event
model asks *how often does this system fail, and is that rate changing?* — the
system is repaired and keeps running, accumulating failures over its life.

Using a Weibull where you need one of these is the most common serious mistake
in reliability analysis. The tell is in the data: if your records are
*times between failures on the same unit*, or a list of dates when a system was
repaired, you are here, not in life-data.

The central quantity is the **mean cumulative function**, `M(t)` — the expected
number of failures by time `t`. Its slope is the **rate of occurrence of
failures**, `λ(t)`. Whether that slope rises, falls or holds flat is usually the
whole answer:

* **falling** — reliability growth. Fixes are working; the system is maturing.
* **flat** — a stable system at a steady failure rate.
* **rising** — deterioration. Repairs are not restoring the system, and you're
  heading toward overhaul or replacement.

Reliafy fits any of the models below to the same event history, so the
comparison between them is direct.

**How Reliafy reads the trend.** A fit to data reports the growth parameter with
its 95% confidence interval, and the verdict comes from that interval, not from
the point estimate alone: *deteriorating* when the whole interval is above the
no-trend value (β = 1), *improving* when it is all below, and *stable* when it
includes it — the data don't show a trend either way. Two trend tests run
alongside, each testing every system over its own observation window: the
**Laplace** test and the **MIL-HDBK-189C** test (the chi-squared test of the
power-law shape). A **Cramér-von Mises** test, with a bootstrap p-value, checks
the fitted model against the event times; a small p-value means the model's
shape doesn't match the data.

The ROCOF and the instantaneous MTBF are reported at the end of observation
with 95% bounds, along with the **demonstrated MTBF** — its one-sided 90% lower
bound, "MTBF ≥ X at 90%". For a Crow-AMSAA fit to a time-terminated test (every
system from 0 to the same end) or one system run to its last failure these are
Crow's exact bounds, as tabulated in MIL-HDBK-189C; otherwise they are Wald
(delta-method) bounds.

## crow_amsaa

**The standard reliability-growth model** — a non-homogeneous Poisson process
with a power-law intensity, also known as the Crow-AMSAA or power-law process.

```
M(t) = λ · t^β
λ(t) = λ · β · t^(β−1)
```

`β` is the whole story, and it reads much like a Weibull shape — but means
something different, because it describes a *rate of events* rather than a
time to one failure:

* `β < 1` — failures are getting **less** frequent. Reliability growth.
* `β = 1` — constant rate; this reduces exactly to the HPP.
* `β > 1` — failures are getting **more** frequent. Deterioration.

**Use it as** the default for repairable-system event data, for tracking a
development programme, and for projecting how many failures a fleet will see
next year. **Watch out:** it assumes *minimal repair* — the system is returned
to the condition it was in just before the failure, not to new. It also assumes
one smooth trend, so a system that improved and then began wearing out will fit
a misleading average of the two; look at the MCF plot before trusting `β`.

## duane

**The original graphical reliability-growth method**, and the ancestor of
Crow-AMSAA. Plots cumulative MTBF against cumulative time on log-log axes, where
growth appears as a straight line.

```
Cumulative MTBF = t / M(t),   linear on log-log
```

**Use it for** the familiar Duane plot, and when reporting to an audience that
expects it — it remains the convention in defence and aerospace development
programmes. **Watch out:** it is the same power law as Crow-AMSAA, fitted by
regression on cumulative points rather than by maximum likelihood. Those
cumulative points are not independent, so the fit is less efficient and the
apparent tightness of the line overstates the confidence. Use it to communicate,
and Crow-AMSAA to decide.

## hpp

**A constant failure rate over time** — the homogeneous Poisson process, the
recurrent-event counterpart of the exponential distribution.

```
M(t) = λ · t
λ(t) = λ         (constant)
```

**Use it as** the null model. Fit it alongside Crow-AMSAA: if `β`'s interval
covers 1, the extra parameter isn't earning its place and you should report a
steady rate rather than a trend. It's also the right model for a mature system
in steady state, and the assumption behind most spares and availability
calculations.

**Watch out:** assuming an HPP when the rate is genuinely rising is how
deterioration gets missed until it's expensive. Always look at the trend before
settling on a constant rate.

## cox_lewis

**A log-linear trend in the failure rate** — the Cox-Lewis non-homogeneous
Poisson process, where the rate changes by a fixed *proportion* per unit time
rather than following a power of time.

```
λ(t) = exp(α + β·t)
M(t) = exp(α) · (exp(β·t) − 1) / β
```

Here `β` is a slope, not a shape: `β > 0` is deteriorating, `β < 0` improving,
and `β = 0` is the HPP. The verdict uses its 95% interval against 0.

**Use it as** the alternative to Crow-AMSAA when the trend doesn't look like a
power law — a rate that was already well above zero at the start and grows
steadily, as wear-out in an old system often does. Compare the two by AIC and
the goodness-of-fit test. **Watch out:** with `β < 0` the expected total number
of failures levels off at `exp(α) / −β`, so long-range predictions from an
improving fit can be optimistic; and growth projection and the demonstrated-MTBF
exact bounds are Crow-AMSAA methods only.
