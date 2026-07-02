---
title: Weibull in five minutes
date: 2026-05-20
author: The Reliafy Team
summary: A quick, practical read on what the Weibull shape parameter is really telling you about how your parts fail.
---

The Weibull distribution earns its place as the workhorse of life-data analysis
because two numbers — a **shape** and a **scale** — describe a remarkable range
of failure behaviour.

## The shape parameter (β) is the story

The scale parameter just sets the time axis. The shape parameter, β, tells you
*how* things are failing:

- **β < 1** — failures are decreasing over time. This is **infant mortality**:
  manufacturing defects, bad installs, weak units dying early. Burn-in helps.
- **β ≈ 1** — a constant failure rate. Failures arrive randomly, independent of
  age (the Weibull collapses to the Exponential). Replacing on a schedule won't
  help much.
- **β > 1** — failures increase with age: **wear-out**. Bearings, seals,
  fatigue. This is exactly where preventive replacement pays off.

## Why it matters for maintenance

If β is at or below 1, a time-based replacement policy is wasted effort — you're
swapping good parts for ones just as likely to fail. If β is comfortably above 1,
there's a cost-optimal interval to be found, balancing the price of planned
replacement against the cost of failure.

In Reliafy, fit a Weibull to your data, read β off the results, and then take it
straight to the **optimal replacement** tool to turn that shape into a schedule.

> Rule of thumb: don't schedule replacements until you've confirmed β > 1.
