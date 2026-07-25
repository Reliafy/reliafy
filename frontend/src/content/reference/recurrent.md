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

Reliafy fits all three models below to the same event history, so the comparison
between them is direct.

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
