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

Open **Decisions → Strategy → Failure finding**. Under **Non-repairable model of the hidden
function**, choose where the non-repairable model comes from:

- **Saved model** — a fit from your own failure data.
- **Parameters** — a distribution and its parameters typed in, for a handbook
  or vendor figure.

For a protective device the vendor figure is usually a constant failure rate.
Choose **Parameters**, set the **Distribution** to **Exponential**, and enter
the **Failure rate λ**. For a trip that fails, on average, once a year (8,760
hours), that's 1 ÷ 8,760 = 0.000114 per hour.

Then set the **Target availability**, as a percentage: the share of time the
device must be able to work when demanded. 99 is a common starting point; your
safety study may set a stricter one. Type 99, not 0.99: a value of 1 or less
asks "Did you mean 99%?" before anything is computed. A saved model brings its
time unit; with parameters typed in, add the **Unit** (hours here) so the
answer reads in it.

Three optional inputs follow:

- **Each test takes** — time the device is off-line for the test, in the
  model's unit. It counts as unavailable, so a long test pushes the interval
  out (testing too often then costs availability).
- **Cost per test** — adds what the tests cost a year.
- **Each test renews the device** — on (the default) when a test overhauls or
  replaces the device, as a bench-tested relief valve is; off when a test only
  checks it and leaves a working one as it was.

Press **Compute**.

![The failure-finding interval: test every 176 hours for 99% availability](/guides/img/ff-01-result.png)

## Read the answer

The answer is one sentence: *Test every ≈ 176 hours to keep average
availability at 99%.* Beside it is the device's mean life, the **MTTF**, here
8,760 hours. For a model fitted to data, a second figure is the **cautious
end**: the interval at the fit's 90% one-sided bound, the shorter one. Use it
when the decision is close, for example between six-monthly and yearly tests.

In plain words: if the device fails at a random moment between tests, it sits
failed and unnoticed until the next test finds it. Reliafy works out, from the
device's own life curve, the share of each interval it sits failed, and finds
the longest interval that keeps that share within 1%.

You may know the shortcut *interval = 2 × (1 − availability) × MTTF*
(2 × 0.01 × 8,760 ≈ 175 hours). It holds only for a constant failure rate,
and only near 100%. For a device that wears out, or whose failures come early,
it can be badly wrong: on a Weibull life it can ask for nearly three times as
many tests as needed, or too few. Reliafy shows it under **Details** for
reference and warns when it is far from the real answer.

Two things follow:

- **Halving the unavailability about halves the interval.** Going from 99% to
  99.5% means testing about twice as often.
- **A more reliable device can be tested less often.** Double the MTTF and the
  interval about doubles.

The answer assumes the test finds every failure and that a failure it finds is
repaired at once. If the test doesn't find every failure, or the device sits in
a redundant arrangement, model it as a block in a
[reliability block diagram](/guides/verify-a-safety-function) instead. There a
proof-tested block's interval, test coverage and test duration all count.

You can also open this tool from a saved model: **Use this model › Set a test
interval (hidden failure)**.

## Save it as evidence

Press **Save analysis** under the answer, give it a name, and press **Save**.
The result is recomputed on the server from your inputs and stored, and it
appears on the [Strategy](/strategy) page.

A saved failure-finding analysis is the evidence an RCM study expects for a
*Failure-finding task*. In the study's decision dialog, choose the failure mode's
consequence (**Hidden**), the decision **Failure-finding task**, the task and its
interval, and link this analysis. The decision then reads **Supported**: *Check
every ~176 hours for 99% availability.* See
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
