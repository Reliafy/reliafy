---
title: Series, parallel, and where redundancy actually helps
date: 2026-04-10
author: The Reliafy Team
summary: Two blocks, two rules — and a quick intuition for when adding a spare is worth it.
---

Every reliability block diagram is built from two primitives. Get the intuition
for these and the rest is just bookkeeping.

## Series: the weakest link

Components in **series** all have to work for the system to work. Reliabilities
multiply:

```
R_system = R1 × R2 × ... × Rn
```

Because each R is below 1, a long series chain erodes fast — ten components at
99% each give a system around 90%. In series, your system is never more reliable
than its worst block.

## Parallel: share the load

Components in **parallel** give redundancy — the system survives as long as *one*
path works. It's easiest to reason about the failure probabilities, which
multiply instead:

```
F_system = F1 × F2 × ... × Fn
R_system = 1 − F_system
```

Two units at 90% in parallel reach 99%; three reach 99.9%. Redundancy buys the
most when each unit is already fairly reliable and the units fail independently.

## The catch

Parallel maths assumes **independent** failures. Shared power, a common
controller, the same corrosive environment — any of these can take out both
"redundant" paths at once, and the real reliability falls short of the formula.
Model the common element explicitly as its own series block rather than trusting
the redundancy to cover it.

In Reliafy you can wire all of this on the canvas — series, parallel, k-of-n, and
standby — and read off system reliability, MTTF, and which block matters most.
