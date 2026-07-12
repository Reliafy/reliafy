---
title: "How to do Weibull analysis in Excel (and where it breaks)"
description: "A complete, honest walkthrough of Weibull analysis in Excel using median rank regression — worked example included — and the exact point where Excel stops being the right tool."
cta_text: "When your data has suspensions — and real maintenance data always does — Excel runs out of road. Reliafy fits Weibull models by maximum likelihood with censored data, confidence bounds, and B-lives, free to start."
cta_label: "Try Weibull analysis in Reliafy"
cta_href: "/weibull-analysis-software"
---

You can do a legitimate [Weibull analysis](/learn/weibull-analysis) in
Excel. No add-ins, no macros — just a sorted column of failure times, one
transformation, and a straight-line fit. This guide walks through the whole
thing with real numbers, because the method is worth knowing even if you
later graduate to proper software: it's the same probability plot that every
reliability tool draws.

It also tells you, precisely, where Excel stops being the right tool. Not as
a sales pitch — as a statistical fact about what least-squares on ranked data
can and can't do.

## The idea: turn a Weibull into a straight line

The Weibull cumulative distribution function is

```
F(t) = 1 − exp(−(t/η)^β)
```

where **β** (the shape parameter) tells you *how* things fail — infant
mortality (β < 1), random (β = 1), or wear-out (β > 1) — and **η** (the scale
parameter, or characteristic life) tells you *when*: it's the time by which
63.2% of units have failed.

Take logs twice and it linearises:

```
ln(−ln(1 − F(t))) = β·ln(t) − β·ln(η)
```

So if you plot `ln(−ln(1−F))` against `ln(t)`, Weibull data falls on a
straight line with slope **β**. That's the entire trick.

## Worked example, step by step

Say eight seal failures came in at these operating hours:

```
410, 780, 1120, 1400, 1680, 1970, 2300, 2750
```

**Step 1 — sort and rank.** Sort ascending (already done) and number them
i = 1…8 in column A, times in column B.

**Step 2 — estimate F(t) for each failure with median ranks.** You can't use
i/n (the last point would be 100% failed, and `ln(−ln(0))` explodes). The
standard fix is **Bernard's approximation** to the median rank:

```
F_i ≈ (i − 0.3) / (n + 0.4)
```

In C2: `=(A2-0.3)/(8+0.4)`, filled down.

**Step 3 — transform.** In D2: `=LN(B2)` and in E2: `=LN(-LN(1-C2))`, filled
down. Your table should now look like this:

| i | t (h) | median rank F | ln t | ln(−ln(1−F)) |
|---|------:|------:|------:|------:|
| 1 | 410  | 0.083 | 6.016 | −2.442 |
| 2 | 780  | 0.202 | 6.659 | −1.487 |
| 3 | 1120 | 0.321 | 7.021 | −0.947 |
| 4 | 1400 | 0.440 | 7.244 | −0.544 |
| 5 | 1680 | 0.560 | 7.427 | −0.199 |
| 6 | 1970 | 0.679 | 7.586 | 0.127  |
| 7 | 2300 | 0.798 | 7.741 | 0.468  |
| 8 | 2750 | 0.917 | 7.919 | 0.910  |

**Step 4 — fit the line.** The slope is β, and η comes from the intercept:

```
β  =SLOPE(E2:E9, D2:D9)          → 1.74
c  =INTERCEPT(E2:E9, D2:D9)      → −13.03
η  =EXP(-c/β)                    → ≈ 1,803 hours
```

**Step 5 — read off what you need.** β ≈ 1.7 means wear-out (an age-based
replacement can pay off — a β near 1 would mean replacement is a waste of
money). Characteristic life ≈ 1,800 hours. And the
[B10 life](/learn/b10-life) — the time by which 10% have failed — is

```
B10 = η·(−LN(0.9))^(1/β) = 1803 × 0.10536^(1/1.74) ≈ 494 hours
```

Scatter-plot column E against D, add the trendline, and you have a genuine
Weibull probability plot. If the points bow away from the line, the Weibull
assumption itself deserves a second look. This method — **median rank
regression** — is not a hack; it was the standard approach for decades and
it's still what many textbooks teach first.

## Where Excel breaks

Here's the honest part. The method above has one hidden assumption doing all
the work: **every unit in the sample ran until it failed.**

Real maintenance data is never like that. Most of your fleet hasn't failed —
units were preventively replaced, are still running, or left service for
unrelated reasons. Those are **suspensions** (right-censored observations),
and they carry real information: a bearing that ran 9,000 hours without
failing is strong evidence against early failure, even though it gives you no
failure time to rank.

Median ranks have no honest place to put that evidence:

- **Drop the suspensions** and your life estimates bias badly low — you kept
  only the weakest units. With realistic maintenance data the error is not
  subtle; [it's routinely 2× or worse](/learn/censored-data-suspensions).
- **Adjusted-rank methods** (Johnson's rank adjustment) exist and can be
  built in a spreadsheet, but they're fiddly, error-prone at the exact
  moment nobody is checking your formulas, and they still only *approximate*
  what maximum likelihood does directly.
- **No confidence bounds.** `SLOPE` gives a point estimate. A B10 of 494
  hours from eight failures might really be "anywhere from 300 to 800" —
  and the maintenance interval you set hinges on that spread. Excel's
  regression statistics don't translate into valid bounds on β and η.
- **No interval censoring.** If failures are found at inspections, you only
  know the failure happened *between* two inspections. Median ranks can't
  express that at all.

The statistically defensible answer to all four problems is **maximum
likelihood estimation (MLE)**: each failure contributes its density, each
suspension contributes its survival probability, and the fit uses everything
you actually know. That's not practical in bare Excel — it needs an
optimiser and, for the bounds, the curvature of the likelihood. It's exactly
what purpose-built [Weibull analysis software](/weibull-analysis-software)
does in the background of the same probability plot you just built by hand.

Rule of thumb: **complete data, quick look — Excel is fine.** The moment your
dataset has suspensions in it (and if it came from a CMMS, it does), switch
tools.

## Frequently asked questions

### Can Excel handle censored data in Weibull analysis?

Not with the standard median-rank method — it assumes every unit failed.
Johnson's rank-adjustment method can incorporate suspensions in a
spreadsheet, but it's laborious, easy to get wrong, and still second-best to
maximum likelihood estimation, which spreadsheets can't do robustly without
add-ins.

### What is Bernard's approximation?

A closed-form estimate of the median rank of the i-th ordered failure in a
sample of n: F ≈ (i − 0.3)/(n + 0.4). It approximates the exact median rank
(from the beta distribution) to within a fraction of a percent, which is why
nearly every textbook plotting-position table uses it.

### Is median rank regression or MLE better?

For complete (uncensored) samples they give similar answers, and MRR pairs
naturally with probability plots. With censored data, small samples, or when
you need confidence bounds, MLE is the standard: it uses suspensions
correctly and its uncertainty estimates are well-founded. Modern reliability
software defaults to MLE for exactly these reasons.

### What do the Weibull parameters β and η mean?

β (shape) describes the failure pattern: β < 1 infant mortality, β ≈ 1
random failures at a constant rate, β > 1 wear-out. η (scale or
characteristic life) is the time by which 63.2% of the population has
failed, regardless of β.
