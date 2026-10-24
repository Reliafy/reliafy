---
title: "Set a failure-finding (proof-test) interval"
task: "How often should I test a protective device whose failure I can't see until it's needed?"
category: "Maintenance strategy"
prerequisites: "A non-repairable model of the protective device, as a saved fit or a failure rate you can type in, and the availability you need from it."
related_href: "/strategy/failure-finding"
related_label: "Open failure finding"
order: 23
---

Some failures announce themselves: a pump stops and the line goes quiet. Others
don't. A relief valve that has seized, a trip that won't trip, a standby
generator that won't start: each looks fine until the day it's needed. These
are **hidden failures**, and the only way to find one before it matters is to
test for it.

A failure-finding interval answers *how often to test*. Test too rarely and the
device spends too long broken without anyone knowing. Test too often and you
pay for tests that find nothing. Reliafy works the interval out from the
device's non-repairable model and the availability you need from it.

## Enter the device's life

Open **Strategy → Failure finding**. Under **Non-repairable model of the hidden
function**, choose where the non-repairable model comes from:

- **Saved model** — a fit from your own failure data.
- **Parameters** — a distribution and its parameters typed in, for a handbook
  or vendor figure.

For a protective device the vendor figure is usually a constant failure rate.
Choose **Parameters**, set the **Distribution** to **Exponential**, and enter
the **Failure rate λ**. For a trip that fails, on average, once a year (8,760
hours), that's 1 ÷ 8,760 = 0.000114 per hour.

Then set the **Target availability (%)**: the fraction of time the device must
be able to work when demanded. 99% is a common starting point; your safety
study may set a stricter one. Add the **Unit** (hours here) so the answer reads
in it, and press **Compute**.

![The failure-finding interval: test every 175 hours for 99% availability](/guides/img/ff-01-result.png)

## Read the answer

The answer is one sentence: *Test every ≈ 175 hours to keep availability at
99%.* Beside it is the device's mean life, the **MTTF**, here 8,760 hours.

In plain words: if the device fails at a random moment between tests, it sits
failed and unnoticed for, on average, half the test interval. To keep that
hidden downtime to 1% of the time, the interval must be a small fraction of the
mean life.

**Details** shows the formula, the standard first-order approximation:

> Interval = 2 × (1 − availability) × MTTF = 2 × 0.01 × 8,760 ≈ 175 hours

It's accurate for targets above about 90%. Below that the answer is
conservative: the true interval can be longer, and the result says so.

Two things follow from the formula:

- **Halving the unavailability halves the interval.** Going from 99% to 99.5%
  means testing twice as often.
- **A more reliable device can be tested less often.** Double the MTTF and the
  interval doubles.

The approximation assumes the test is perfect and takes no time, and that a
failure it finds is repaired at once. If the test itself takes the device out
of service, or doesn't find every failure, or the device sits in a redundant
arrangement, model it as a block in a
[reliability block diagram](/guides/verify-a-safety-function) instead. There a
proof-tested block's interval, test coverage and test duration all count.

## Save it as evidence

Press **Save analysis** under the answer, give it a name, and press **Save**.
The result is recomputed on the server from your inputs and stored, and it
appears on the [Strategy](/strategy) page.

A saved failure-finding analysis is the evidence an RCM study expects for a
*Failure-finding task*. In the study's decision dialog, choose the failure mode's
consequence (**Hidden**), the decision **Failure-finding task**, the task and its
interval, and link this analysis. The decision then reads **Supported**: *Check
every ~175 hours for 99% availability.* See
[running an RCM study](/guides/rcm-study).

Keep the units the same in both places. If the task interval is in days and the
analysis is in hours, the decision is marked inconclusive rather than converted.

## Where to go next

If the item's failures are evident rather than hidden, the question is when to
replace it, not when to test it: see
[find the optimal replacement interval](/guides/optimal-replacement-interval).

For a repairable system that is repaired as it fails and overhauled from time
to time, **Plan ahead › Overhaul interval** on a repairable model finds the overhaul interval
that costs least. See [repairable systems](/guides/recurrent-events).

For a safety instrumented function, where several devices vote and each has its
own proof test, see [verify a safety function](/guides/verify-a-safety-function).
