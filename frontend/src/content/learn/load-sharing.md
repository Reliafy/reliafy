---
title: "Load-sharing redundancy: when losing a unit stresses the rest"
description: "In a load-sharing system, surviving units pick up the load of failed ones and fail faster as a result — so parallel-redundancy math overstates reliability. Here's the load-life mechanism, a worked example, and how it differs from standby."
cta_text: "Reliafy models load-sharing on a reliability block diagram — the units are an accelerated-failure-time model of load versus life, and the shared load accelerates the survivors as siblings fail."
cta_label: "Model load-sharing redundancy"
cta_href: "/reliability-block-diagram-software"
---

**In a load-sharing arrangement, several units carry a total load together, and
when one fails the survivors must carry more — so they age faster.** Think of
three pumps sharing a duty, bolts in a flange, strands in a cable, or power
supplies feeding a rail. As long as all are healthy each carries its share; the
moment one drops out, the rest are stressed harder and their remaining life
shortens. The failures are not independent, and they're not identical over time
either — the danger climbs as the group thins out.

Ordinary parallel-redundancy math assumes each unit ages at a fixed rate
regardless of how its siblings are doing. For load-sharing systems that
assumption is optimistic, sometimes badly so, because it ignores the very effect
that makes these systems fail — the cascade, where each failure raises the load
and hastens the next.

## The load-life mechanism

Load-sharing couples two ideas you can model separately and then combine:

1. **A load-life relationship.** How does a single unit's life depend on the
   load it carries? More load means shorter life, captured by an
   accelerated-failure-time (AFT) model with load as the stress — often an
   inverse-power relationship, `life ∝ load^(−n)`, the same family used in
   accelerated life testing.

2. **Load redistribution.** A total load *L* shared by *s* working units means
   each carries *L / s*. Start with *n* units at *L/n* each; when one fails the
   remaining *n−1* jump to *L/(n−1)*; and so on. Each step up the load ladder
   accelerates the survivors according to the load-life relationship.

The group is considered working while at least *k* of the *n* units survive
(k-of-n). Put those pieces together and you get the system's reliability —
including the accelerating hand-off that plain parallel redundancy can't see.

## A worked example

Three identical pumps share a duty; the group works as long as any one of them
runs (k = 1 of 3). Each pump follows an inverse-power load-life law, so carrying
double the load cuts its characteristic life by 2ⁿ.

- All three healthy: each carries a third of the load and ages slowly.
- One fails: the two survivors now carry half the load each — noticeably faster
  wear.
- Two failed: the last pump carries the *entire* duty and burns through its
  remaining life quickly.

The result is a reliability curve that starts out looking like ordinary triple
redundancy but **falls away faster in the tail**, because the last survivors are
running far harder than the design assumed. Requiring more survivors (say k = 2
of 3, so the group fails on the second unit lost) lowers reliability further —
there's less slack before the accelerating cascade bites.

## Load-sharing vs standby vs independent parallel

Three redundancy patterns that are easy to conflate but behave differently:

- **Independent parallel** — every unit runs from the start and ages at a fixed
  rate, unaffected by the others. The most optimistic model; correct only when
  units genuinely don't share load.
- **Standby** — spare units are dormant (cold) or lightly loaded (hot) until
  switched in on a failure. Redundancy here is about *switching* successfully,
  not about survivors being stressed.
- **Load-sharing** — all units are active and share the load, and survivors are
  stressed *more* as siblings fail. The realistic model for pumps, cables,
  fasteners, and power supplies that split a common duty.

Choosing the wrong one of these silently changes your answer. If your units
split a load, model load-sharing; using independent parallel there will credit
you with reliability the physics won't deliver.

## What you need to model it

Because the effect is driven by how life responds to load, the input is a
**load-life model** — an accelerated-failure-time fit with load as its single
covariate — plus the total shared load, the number of units, and the k-of-n
survival requirement. Fit the load-life relationship from failures gathered at a
few different loads (the same data you'd use for a load-based accelerated life
test), then drop it into the diagram as a load-sharing block.

## Frequently asked questions

### What is load-sharing redundancy?
A redundant arrangement where all units are active and share a common load, so
when one fails the survivors carry more and fail faster. Unlike independent
parallel redundancy, the units' failure rates rise as the group thins, producing
a cascade.

### Why doesn't ordinary parallel math work for load-sharing?
Parallel redundancy assumes each unit ages at a constant rate no matter what its
neighbours do. In a load-sharing system the survivors are stressed harder after
each failure, so their remaining life shortens — an acceleration the constant-
rate model ignores, making it optimistic in the tail where it matters.

### What's the difference between load-sharing and standby redundancy?
In standby, spares are dormant or lightly loaded until switched in, and the risk
is switching reliability. In load-sharing, all units are working and sharing the
load from the start, and the risk is the survivors being over-stressed as
others fail. Different mechanisms, different math.

### What input does a load-sharing model need?
A load-life relationship — how a single unit's life depends on the load,
expressed as an accelerated-failure-time model with load as the covariate — plus
the total shared load, the number of units, and how many must survive (k-of-n).
