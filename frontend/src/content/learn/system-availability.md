---
title: "System availability: uptime from an RBD, with repair"
description: "Availability is the fraction of time a repairable system is up. Here's the inherent-availability formula from MTBF and MTTR, how it composes through a reliability block diagram, why redundancy helps, and how to read per-component downtime."
cta_text: "Reliafy computes steady-state availability for a repairable RBD — give each block a failure and a repair distribution and read the uptime, mean up/down time, and which components drive the downtime."
cta_label: "Model system availability"
cta_href: "/reliability-block-diagram-software"
---

**Availability is the fraction of time a repairable system is doing its job** —
up and functioning, rather than failed or under repair. Where *reliability*
asks "will it survive to time *t* without failing?", availability asks the
question that matters for a system you *fix and put back into service*: "over
the long run, what share of the time is it working?"

The two are different questions with different answers. A pump that fails often
but is repaired in minutes can have higher availability than one that fails
rarely but takes a week to fix. Reliability can't see that — availability can.

## Inherent availability, from MTBF and MTTR

For a single repairable component that alternates between working and being
repaired, the long-run (steady-state) **inherent availability** is:

```
A = MTBF / (MTBF + MTTR)
```

- **MTBF** — mean time *between* failures: the average length of an up period.
- **MTTR** — mean time to repair: the average length of a down period.

So availability is simply *uptime / (uptime + downtime)*. A component with a
1,000-hour MTBF and an 8-hour MTTR has

```
A = 1000 / (1000 + 8) = 0.9921  →  99.21% uptime
```

The unavailability is the complement, `U = 1 − A = MTTR / (MTBF + MTTR)` — here
0.79%, or about **69 hours of downtime a year**.

Both MTBF and MTTR are means of *distributions*, not fixed numbers. Repair times
are usually right-skewed (most repairs are quick, a few drag on), which is why a
**lognormal** is the standard model for time-to-repair.

## Availability through a reliability block diagram

Real systems are arrangements of components, and availability composes through
the structure exactly the way reliability does — with each component's
availability *A* in place of its reliability *R*, provided the components fail
and are repaired independently:

- **Series** (all required): `A_sys = A₁ · A₂ · … · Aₙ`. Availabilities multiply,
  so a long series chain is only as available as the product of its parts.
- **Parallel** (any one suffices): `A_sys = 1 − (1 − A₁)(1 − A₂)…`. Redundancy
  multiplies the *un*availabilities, which are small — so it pushes availability
  up fast.

A controller (A = 0.992) in series with two redundant pumps (A = 0.99 each):

```
A_pumps = 1 − (1 − 0.99)² = 0.9999
A_sys   = 0.992 × 0.9999 = 0.9919
```

The redundant pump stage is essentially never the bottleneck; the single
controller sets the system availability. That's the point of the calculation —
**it tells you where the downtime actually comes from**, which is rarely where
intuition points.

## Time-dependent availability and downtime drivers

The steady-state figure is the headline, but a repairable system also has a
*point availability* A(t) that starts at 1 (everything new and working) and
settles toward the steady-state value as the system reaches its long-run mix of
up and down time. Simulating the up/down history also yields the pieces that
make availability actionable:

- **Mean up time** and **mean down time** for the whole system.
- **Failure frequency** — how often the system drops out.
- **Per-component downtime** — each component's share of the total system
  downtime. This is the number that tells you where to spend: cut the MTTR (or
  raise the MTBF) of the biggest contributor and the system availability moves;
  touch a minor contributor and it won't.

## When to model availability instead of reliability

Reach for availability when the system is **repairable and returned to
service** and the question is about uptime, throughput, or a service-level
target — production lines, pumping stations, data-centre power, fleets in
continuous use. Reach for reliability (a survival curve, MTTF, B-lives) when the
item is **run to failure or replaced**, and the question is about surviving a
mission or setting a replacement interval.

In a reliability block diagram this is a single up-front choice: a *repairable*
diagram wants a failure distribution **and** a repair distribution on every
block, and reports availability; a *non-repairable* diagram wants only a life
model and reports reliability over time.

## Frequently asked questions

### What's the difference between availability and reliability?
Reliability is the probability of surviving to a time *t* without failing —
appropriate for items that are run to failure. Availability is the long-run
fraction of time a *repairable* system is up, accounting for both how often it
fails and how long repairs take. A frequently-failing but quickly-repaired
system can be more available than a rarely-failing but slowly-repaired one.

### What is inherent vs operational availability?
Inherent availability `A = MTBF / (MTBF + MTTR)` counts only active repair time.
Operational availability also folds in logistic and administrative delays —
waiting for spares, technicians, or access — so it's always lower and is what an
operator actually experiences. Modelling the repair-time distribution with a
realistic MTTR (including those delays) closes the gap.

### Why does MTTR matter as much as MTBF?
Because availability depends on the *ratio* of downtime to uptime. Halving the
repair time improves availability exactly as much as doubling the time between
failures. When failures are already rare, reducing MTTR (better spares, faster
diagnosis, hot-swap design) is often the cheaper lever.

### How does redundancy affect availability?
Parallel redundancy multiplies the components' *un*availabilities, which are
small numbers, so it raises system availability sharply — but only for the
redundant stage. If a single non-redundant component dominates the downtime,
adding pumps in parallel elsewhere does nothing. Find the driver first.
