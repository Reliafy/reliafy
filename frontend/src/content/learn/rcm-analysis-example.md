---
title: "RCM analysis example: a pump system, worked end to end"
description: "A complete reliability centred maintenance example — functions, functional failures, failure modes, consequences, and task selection for a cooling-water pump — with the worksheet filled in and the reasoning shown."
cta_text: "Reliafy's RCM worksheets link every decision to the life model or analysis that justifies it — and flag the decision when new data contradicts it. The sample study is a pump system just like this one."
cta_label: "Open the RCM sample study"
cta_href: "/rcm-software"
---

Reliability centred maintenance is easier to grasp from one honest worked
example than from any amount of theory. So here is one: a cooling-water pump
set, taken through the full RCM logic — functions, functional failures,
failure modes, consequences, and task selection — with the worksheet filled
in at the end and, more importantly, the *reasoning* for each entry shown.

The method below follows the standard RCM logic (the SAE JA1011 lineage:
seven questions, consequence-driven task selection). Nothing is
software-specific; you could run this in a workshop with a whiteboard.

## The system

**CWP-101A/B** — two centrifugal cooling-water pumps, one duty, one standby,
feeding the condenser cooling loop of a small process plant. Motor-driven,
mechanical seals, rolling-element bearings. Loss of cooling flow trips the
process within minutes and costs roughly $40,000 per unplanned shutdown;
a planned pump overhaul during a scheduled outage costs about $3,000.

## Step 1 — Functions

Write functions with performance standards, not just verbs. "Pump water"
hides the failure you care about; "deliver ≥ 850 m³/h at ≥ 3.2 bar" exposes
it.

- **F1 (primary):** Deliver ≥ 850 m³/h of cooling water at ≥ 3.2 bar
  discharge pressure, continuously.
- **F2 (secondary):** Contain the pumped fluid (no external leakage beyond
  seal-flush design rate).
- **F3 (protective, standby unit):** Start automatically on duty-pump trip
  and reach full flow within 30 seconds.

## Step 2 — Functional failures

Each function fails in specific, distinguishable ways:

- **FF1a:** Delivers no flow. **FF1b:** Delivers flow below 850 m³/h.
- **FF2a:** Leaks pumped fluid externally.
- **FF3a:** Standby pump fails to start on demand.

## Step 3 — Failure modes, effects, and the evidence

The core discipline: one row per *mode* (the physical cause), not per
symptom, with an honest note on what the failure data actually shows. This
is where most binder-RCM goes soft — the pattern of each mode gets asserted
from memory rather than fitted from data, and every decision downstream
inherits the guess. Fit a life model per mode where the records allow it
([with the suspensions counted](/learn/censored-data-suspensions), or the
fit is worthless).

| # | Failure mode | Functional failure | What the data shows |
|---|---|---|---|
| M1 | Bearing wear-out (spalling) | FF1b → FF1a | Weibull β ≈ 2.8, η ≈ 19,000 h — clear wear-out |
| M2 | Mechanical seal face wear | FF2a | Weibull β ≈ 2.1, η ≈ 14,000 h — wear-out, wide scatter |
| M3 | Motor winding insulation failure | FF1a | β ≈ 1.0 — random; no age pattern in 11 events |
| M4 | Impeller erosion (silt seasons) | FF1b | Gradual, measurable as falling discharge head |
| M5 | Standby fails to start (seized/control fault) | FF3a | Hidden — only revealed on demand or test |

## Step 4 — Consequences

- **M1, M2, M3** on the *duty* pump are **operational** consequences, not
  safety: the standby should pick up the load. But that sentence is doing a
  lot of work — it's only true if M5 is managed. Note the coupling; RCM
  finds these dependencies constantly.
- **M2** has a **non-operational/environmental** angle even with standby
  cover (leakage cleanup, housekeeping).
- **M5** is the classic **hidden failure**: it has no consequence *of its
  own* until a duty-pump failure demands the standby — then it converts an
  operational hiccup into the $40,000 trip.

## Step 5 — Task selection, mode by mode

**M1 — Bearing wear-out (β ≈ 2.8).** Wear-out with a strong age pattern
makes age-based renewal viable — and worth checking economically. With
planned cost $3,000 against $40,000 unplanned, the cost-optimal replacement
calculation on the fitted Weibull gives an interval around 8,000–9,000
hours. Vibration monitoring is the alternative if you'd rather buy the
remaining life: **on-condition task** (monthly velocity/envelope readings)
with renewal on alert. Either is defensible; pick one and *cite the
analysis*. Decision: **fixed-interval renewal at 8,500 h**, evidence: the
replacement-interval analysis on the bearing model.

**M2 — Seal wear (β ≈ 2.1, wide scatter).** Wear-out, but the scatter makes
a fixed interval wasteful — you'd replace many good seals to catch the few
early ones. Seal distress telegraphs itself (flush-line temperature, drip
rate). Decision: **on-condition task** — weekly visual + flush monitoring,
renewal on onset. Evidence: the seal life model plus the observability of
the mode.

**M3 — Motor windings (β ≈ 1.0).** Random failures. This is the entry that
surprises people: *no* scheduled task can help, because a rewound motor is
statistically identical to the incumbent — scheduled replacement spends
money to reset a clock that isn't running. Decision: **no scheduled
maintenance (run to failure)**, standby covers the operational consequence.
Evidence: the fitted β ≈ 1. If later data pushes β up, this decision is the
first that should be flagged for review.

**M4 — Impeller erosion.** Measurable degradation with a defined failure
point (head below spec). Decision: **on-condition task** — quarterly
discharge-head trending against the degradation curve, impeller change when
the trend approaches the limit. During silt season, monthly.

**M5 — Standby fails to start (hidden).** For hidden failures the task is a
**failure-finding test**: start the standby pump on a schedule and prove it
still works. The interval isn't folklore — it comes from the required
availability: to keep the probability of "duty fails while standby is
secretly dead" acceptably low given the standby's failure-to-start rate, the
failure-finding interval calculation gives roughly a **monthly test** here.
Alternate duty/standby monthly and you get the test for free, plus even
ageing on both units.

## The finished worksheet

| Mode | Pattern (evidence) | Consequence | Decision | Interval |
|---|---|---|---|---|
| M1 Bearing wear | Wear-out, β 2.8 (life model + cost analysis) | Operational | Fixed-interval renewal | 8,500 h |
| M2 Seal wear | Wear-out, β 2.1, high scatter (life model) | Env./operational | On-condition (flush + visual) | Weekly check |
| M3 Motor windings | Random, β 1.0 (life model) | Operational | Run to failure | — |
| M4 Impeller erosion | Measurable degradation (head trend) | Operational | On-condition (head trend) | Quarterly / monthly in season |
| M5 Standby start | Hidden (demand data) | Hidden → operational | Failure-finding test (alternate duty) | Monthly |

Five modes, four different task types, and one deliberate decision to do
*nothing* — which is RCM working as designed. The worksheet's value isn't
the table; it's that every row can answer "why?" with an analysis rather
than a recollection.

One last thing the binder version can't do: **these decisions are claims
about β**, and β moves as data accumulates. M3's run-to-failure is only
right while the windings keep failing randomly; M1's interval is only
optimal while the bearing model holds. A worksheet that stays linked to the
live models — and flags the decision when the evidence turns — is the
difference between an RCM study and an RCM archive.

## Frequently asked questions

### What are the seven questions of RCM?

Per SAE JA1011: (1) What are the functions and performance standards? (2)
How can it fail to fulfil them? (3) What causes each functional failure?
(4) What happens when each failure occurs? (5) In what way does each
failure matter (consequences)? (6) What can be done to predict or prevent
it? (7) What if no suitable proactive task exists (default actions)?

### What's the difference between a functional failure and a failure mode?

A functional failure is the *state* of not meeting the function ("delivers
below 850 m³/h"); a failure mode is the *physical cause* of that state
("impeller erosion"). One functional failure typically has several modes,
and tasks are selected per mode — because bearing wear and impeller erosion
need entirely different responses.

### When is run-to-failure the correct RCM decision?

When the failure pattern is random (no age relationship, Weibull β ≈ 1) so
scheduled replacement can't reduce risk, and the consequences are tolerable
— no safety impact and an acceptable operational cost. It's a positive,
evidence-backed decision, not neglect; document the β that justifies it.

### How do you set a failure-finding interval for a hidden failure?

From the required availability of the protective function: the interval
follows from the protected system's demand rate, the protective device's
failure rate, and the tolerable probability of a coincident failure. Halve
the interval and you roughly halve the unavailability window. It's a
calculation, not a convention — "test quarterly" without the numbers is a
guess.
