---
title: "Spreadsheets: where reliability analysis quietly goes wrong"
date: 2026-10-19
author: The Reliafy Team
summary: Spreadsheets are the most common reliability tool, and their mistakes are quiet. They never return an error, only a number, and the wrong number often looks better than the right one. Five failure modes, each with a worked example you can reproduce.
linkedin: |
  Spreadsheets are the most common reliability tool, and their mistakes are quiet. They never return an error, only a number, and the wrong one often looks better than the right one.

  Fifteen pumps: ten failed, five still running. Drop the five and the Weibull characteristic life falls from 3,085 to 2,158 hours.

  Leave common cause out of a 1oo2 PFDavg and a SIL 2 pair reads as SIL 3.

  Five failure modes, each with numbers you can reproduce.

  #ReliabilityEngineering #FunctionalSafety
---

Most reliability analysis is done in a spreadsheet. That isn't a complaint:
a spreadsheet is visible, you can audit it cell by cell, and everyone has
one. The trouble is how it fails. A spreadsheet never says "this method
doesn't fit your data". It takes what you give it and returns a number to two
decimal places, and the wrong number often looks better than the right one:
tidier, more confident, or more comfortable.

Here are five ways that happens. The Weibull examples all use one dataset:
15 pumps, 10 of which failed at 410, 780, 1,120, 1,400, 1,680, 1,970, 2,300,
2,750, 3,100 and 3,600 hours, and 5 still running at 2,000, 2,500, 3,000,
3,500 and 4,000 hours. Every figure comes from
[SurPyval](https://github.com/derrynknife/SurPyval) or
[RePyability](https://github.com/derrynknife/RePyability), both open source,
so you can check them.

## 1. The units still running disappear

A spreadsheet has no natural place for "hasn't failed yet", so the five
running pumps tend to fall out. Fit a Weibull by maximum likelihood to all 15
and the characteristic life η is **3,085 hours** (β = 1.76, mean life 2,747
hours). Fit only the 10 failures and η is **2,158 hours**: 30% shorter, from
the same pumps. B10 falls from 860 to 721 hours.

Nothing flags it, and the failures-only fit even looks cleaner: β rises to
2.05, a neater wear-out story. What has happened is that you kept the weakest
units and called them the population. The
[Learn page on suspensions](/learn/censored-data-suspensions) shows why the
bias runs this way.

## 2. Common cause left out of a 1oo2 PFDavg

Two transmitters vote 1oo2, each with λDU = 5 × 10⁻⁶ per hour, proof-tested
once a year (8,760 hours), with perfect tests and instant repair. Treat them
as independent and the pair's PFDavg is **6.2 × 10⁻⁴**, in the SIL 3 band.
Add a common-cause group with a beta factor of 10% and it is
**2.7 × 10⁻³**: 4.3 times higher, and SIL 2.

The common-cause term alone, β·λDU·T/2, is bigger than the whole independent
figure. A spreadsheet built on the textbook (λDU·T)²/3 has every formula
right and still describes a different system, one in which nothing can fail
both channels at once. The guide to
[verifying a safety function](/guides/verify-a-safety-function) adds a
common-cause group to a 1oo2 pair step by step.

## 3. A mean where a parameter belongs

η is not the mean life. For the pumps, η is 3,085 hours and the mean is
2,747. Put η in an MTBF cell (the name "characteristic life" invites it) and
you have overstated the mean life by 12%, and every failure rate and spares
count built on it carries the error.

It goes wrong the other way with supplier data. Type a quoted MTTF of 2,747
hours into a template's scale cell, keep β = 1.76, and B10 comes out at 766
hours instead of 860. Each cell is labelled; the labels just don't say which
parameter they mean.

## 4. Hours that aren't the same hours

Suppose the pump times came from work-order dates, so they are calendar
hours, but the replacement is scheduled on the run-hour meter, and the pumps
run 16 hours a day. Set the interval at B10, 860 hours, on the meter. That is
1,290 calendar hours, by which time the model says **19.4%** have failed. You
planned for one in ten failing before replacement and got nearly one in five.
Every number is right in its own unit; nothing in the sheet knows which unit
is which.

## 5. A straight line through censored data

Keep the running units, and the usual spreadsheet method (median ranks, a
Weibull plot, `SLOPE` and `INTERCEPT`) still has to be told what to do with
them. A common shortcut ranks the 10 failures 1 to 10 but uses n = 15 in
Benard's formula, (i − 0.3)/(n + 0.4). That quietly assumes every running
unit outlived every failure, when four of the five here are younger than the
last failure. The line gives η = **3,499 hours**, 13% longer than maximum
likelihood's 3,085. The same data that came out 30% short in the first
example now comes out long, and the plot still looks like a straight line.

Johnson's adjusted ranks place the suspensions properly and give η = 3,188
hours, but β = 1.53 against maximum likelihood's 1.76: least squares on a
plot and maximum likelihood are different estimators. With censored data,
maximum likelihood is the standard, because it uses each running unit as what
it is: one that has lasted at least that long.

## What to do on Monday

Not "stop using spreadsheets". Make their assumptions visible:

- Keep a status column, failed or still running, beside every time, and
  count both before you fit.
- Write the unit beside every number, and which clock: calendar or operating.
- Name parameters (η, β, mean) and never paste one into a cell meant for
  another.
- In any redundant safety function, look for the common-cause term. If there
  isn't one, the PFDavg is for a system you don't have.
- Check the sheet once against an independent calculation. With the pump data
  above, maximum likelihood gives η ≈ 3,085 hours and β ≈ 1.76; if your sheet
  doesn't, find out why.

A spreadsheet's arithmetic is rarely the problem. The method is, and a
spreadsheet will never tell you when the method is wrong.
