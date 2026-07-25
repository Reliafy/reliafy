---
title: "Common-cause failure and the beta-factor model"
description: "Redundancy only helps if the redundant units fail independently. Common-cause failures break that assumption. Here's the beta-factor model, a worked example of how much it erodes redundancy, and when to use MGL instead."
cta_text: "Reliafy models common-cause groups on a reliability block diagram — select the redundant components, set a beta-factor, and see the honest system reliability with the shared cause included."
cta_label: "Model common-cause failures"
cta_href: "/reliability-block-diagram-software"
---

**A common-cause failure is a single event that fails several components at
once** — and it's the reason real redundant systems are less reliable than the
textbook parallel formula promises. Two pumps in parallel look almost
unfailable on paper. But if they came from the same bad batch, share a power
supply, sit in the same flood zone, or were miscalibrated by the same
technician, one cause can take *both* out together. The redundancy you paid for
quietly evaporates.

Standard RBD math assumes components fail **independently**. Common-cause
failure (CCF) is the correction for when they don't.

## Why independent redundancy overstates reliability

For two identical units in parallel, each with reliability *R*, the independent
formula is:

```
R_parallel = 1 − (1 − R)²
```

If each pump has R = 0.9, that's `1 − 0.1² = 0.99` — the failure probability
drops from 10% to 1%. Beautiful, and often too good to be true. It only holds if
the two 10% failure risks are *unrelated*. Any shared cause puts a floor under
the system's failure probability that redundancy can't lower.

## The beta-factor model

The beta-factor model is the standard, minimal way to put that floor in. It
splits each component's total failure probability into two parts:

```
independent part  = (1 − β) · Q
common-cause part =      β  · Q
```

where *Q* is the component's failure probability and **β** (0–1) is the fraction
attributed to causes shared across the whole redundant group. The independent
part still benefits from redundancy; the common-cause part fails *every* member
of the group simultaneously, so it behaves like a single series element that no
amount of parallelism can remove.

Typical β values run from about **1% to 20%**, depending on how much the units
share (design, manufacturing, environment, maintenance, power). β = 0 recovers
the independent case; the closer β gets to 1, the more the redundant units
behave like one.

## A worked example

Two identical redundant pumps, each with reliability R = 0.90 (so Q = 0.10), at
some design point. Independent redundancy says:

```
R = 1 − 0.10² = 0.9900   (1.00% system failure)
```

Now attribute β = 10% of each pump's failures to a shared cause. Roughly, the
common-cause part (β·Q = 0.01) fails both pumps together and acts in series,
while the independent part (0.09 each) still enjoys redundancy:

```
R ≈ (1 − β·Q) · [1 − ((1−β)·Q)²]
  ≈ 0.99      · [1 − 0.09²]
  ≈ 0.99      · 0.9919
  ≈ 0.982      (1.8% system failure — nearly double)
```

A β of just 10% **almost doubled** the system failure probability versus the
independent estimate — and no change to the pumps themselves would have revealed
it. This is why CCF matters most in exactly the places redundancy is used for
safety: shutdown systems, protective trips, backup power.

## Beyond two units: MGL

The beta-factor model treats a group as all-or-nothing: a common cause either
spares everyone or fails everyone. For groups of three or more, the **Multiple
Greek Letter (MGL)** model refines this with additional parameters (γ, δ, …)
that capture causes failing *exactly two* of three, *exactly three* of four, and
so on. Use the beta-factor model as the default and reach for MGL when you have
a group larger than two and data (or a CCF database) to justify the extra
parameters.

## Getting β without perfect data

You rarely have a clean estimate of β from your own fleet — common-cause events
are, by design, rare. Practitioners lean on published CCF databases, industry
defaults for the equipment class, and a checklist-style assessment of the
defences against shared causes (diversity of design, separation, staggered
maintenance). The honest move is to *include a plausible β and see whether the
system still meets its target* — a redundant design that only passes at β = 0 is
a design that's trusting its redundancy further than the physics allows.

## Frequently asked questions

### What is a common-cause failure?
A single root cause that fails two or more components at the same time —
defeating the independence that redundancy relies on. Common sources are shared
design flaws, a common manufacturing batch, a shared environment or utility, and
common maintenance errors.

### What is the beta-factor in reliability?
β is the fraction of a component's failures attributed to causes shared with the
rest of its redundant group. `(1 − β)` of failures are independent (and benefit
from redundancy); β of them are common-cause and fail the whole group together.
Values of 1–20% are typical.

### How much does common-cause failure reduce redundancy?
It can dominate. Once you add a common cause, the system's failure probability
can't drop below roughly β times a single unit's failure probability, no matter
how many units you add in parallel. A β of 10% often doubles the system failure
probability compared with the independent estimate.

### When should I model common-cause failure?
Whenever redundancy is doing safety-critical work and the redundant units share
anything — the same design, batch, location, power, or maintenance crew.
Ignoring CCF there produces a reliability number that is optimistic in exactly
the situations where being wrong is most expensive.
