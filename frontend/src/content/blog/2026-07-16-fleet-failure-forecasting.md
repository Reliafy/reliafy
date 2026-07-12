---
title: "How many failures next year? Forecasting spares from your own life model"
date: 2026-07-16
author: The Reliafy Team
summary: A fitted life model tells you how one component behaves. The question your planner actually asks is about the fleet — "how many of these fail in the next twelve months?" Here's the right way to answer it, and the new Fleet section in Reliafy that does it for you.
---

Every budget season, the same question comes down from planning: *how many
spares do we need next year?* And in most plants, the answer is produced by
one of two equally shaky methods: last year's consumption plus a safety
margin, or fleet size divided by MTBF.

Both ignore the thing your maintenance records know best: **how old each
item is right now.**

## Age is the whole game

Suppose your bearings follow a Weibull with characteristic life 6,000 hours
and shape β = 2.5 — a clear wear-out pattern, fitted from your own failure
and suspension data. Now take four trucks whose bearings have currently run
1,000, 2,500, 4,000, and 5,200 hours, each facing about 2,000 hours of
operation next year.

They are not facing the same risk. The probability that an item of age *a*
fails within the next *u* hours, given it's alive today, is:

```
p = [F(a + u) − F(a)] / R(a)
```

— the failure probability over the window, renormalised by the probability
of having survived to its current age. For our four trucks that gives:

| Current age | p(fail next 2,000 h) |
|---:|---:|
| 1,000 h | 15% |
| 2,500 h | 31% |
| 4,000 h | 47% |
| 5,200 h | 58% |

Expected failures: the sum — about **1.5**. The oldest truck is nearly four
times as likely to fail as the youngest, a difference that "fleet size ÷
MTBF" flattens to nothing. With a wear-out fleet skewed old, the naive
method understates demand; skewed young, it overstates it. It's only right
by coincidence.

## One failure each, or a stream of them?

There's a subtlety in "how many failures": what happens after the first one?

**If a failed item leaves the analysis** — the window is short, or you're
asking "which trucks will need the workshop" — each item fails at most once,
and the expected count is just the sum of the probabilities above. The
spread comes for free too: with independent items the count follows a
Poisson-binomial distribution, so you can report "1.5 expected, 0 to 3
plausible" instead of a bare number.

**If every failure is repaired with a new part and the clock restarts** —
which is exactly the spares question over a year or more — an old item can
fail, get a fresh part, and *that part* can fail too. This is a renewal
process, and for it Reliafy runs a Monte Carlo simulation: each item's first
failure is drawn from its age-conditional distribution, every subsequent
life is drawn fresh, and the failures are tallied per period across
thousands of fleet histories. Out comes the expected count, the P10–P90
range, and *when* in the year the failures land.

Short windows on young fleets: the two methods agree. Long windows: renewals
count the second and third failures that the at-most-one method can't see.
Reliafy lets you pick the counting mode per forecast, because both questions
are real.

## The new Fleet section

This is what the **Fleet** section, live now, does:

1. **Pick a saved life model** — any distribution you've fitted in Reliafy,
   suspensions and all.
2. **List your items with their current use** — ages in the model's own time
   units, straight from your meter readings.
3. **Set the horizon** — periods, a fleet-wide usage rate, per-item
   overrides for the odd duty cycle, and the counting method.

You get expected failures with an uncertainty range, a per-period breakdown
you can hold against next year's budget, per-item failure probabilities that
double as a replacement priority list, and CSV export for the planning
meeting. Forecasts stay linked to the model that powers them — refit it with
new data and the forecast updates, the same live-evidence behaviour as
everywhere else in Reliafy.

There's a worked sample fleet — eight trucks on the sample bearing model —
sitting in the app right now, on the free tier. Or just ask the assistant:
*"How many failures will my fleet see next year?"* is now a question it can
answer with your data, on your screen.

The gap between "fleet ÷ MTBF" and an age-aware forecast is routinely the
difference between a stock-out and a right-sized shelf. Your maintenance
records already know each item's age. Let them speak.
