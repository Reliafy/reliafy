---
title: "Replace it at the shut, or let it run?"
date: 2026-11-09
author: The Reliafy Team
image: /blog/shutdown-replacement-card.png
summary: A site changes conveyor pulleys when the belt is down anyway. The textbook "best replacement age" assumes a part can be changed on any day, so it answers the wrong question. The right one is a threshold at each shut. In a worked example it costs 20% less than running to failure and 11% less than the best fixed age.
linkedin: |
  A site changes conveyor pulleys at its six-monthly shut, when the belt is down anyway. So "what's the best replacement age?" is the wrong question: the part can't be changed at that age.

  The right question is a threshold: at this shut, is it old enough to change? In a worked example (Weibull life, scale 365 days, shape 2; a failure costing four times a change at the shut) the answer is 138 days. That rule costs 20% less than running to failure and 11% less than the best fixed age.

  The maths, the chart, and what moves the answer, on the Reliafy blog. The calculation is free in Reliafy.

  #ReliabilityEngineering #MaintenancePlanning
---

An overland conveyor on a mine site has dozens of pulleys and thousands of
idler sets. The site changes them at two kinds of stop: a weekly stop of a few
hours, and a six-monthly shut, when the belt is down for days and the crews,
cranes and access are all there anyway. Stopping the belt between shuts to
change a pulley is possible, but it costs production and a call-out. Nobody
changes a pulley on a Tuesday because a spreadsheet said it had reached its
best age.

So the planner's question is not "what is the best age to change a pulley?"
It is "at this shut, do we change this one, or let it run to the next?" They
have different answers, and the first, the one most textbooks and tools give,
is a number the planner can't act on.

## Why the best age is the wrong question

Age replacement is the classic result: replace the part at age *T*, or at
failure if that comes first. The cost of a planned change is traded against the
rising chance of a failure, and there is an age where the long-run cost a year
is lowest. It is the right answer when a planned change costs the same on any
day.

At a site with shuts it doesn't. For the pulley below, with a planned change
costing 150 and a failure 400, the best fixed age is 298 days. But a pulley
fitted at a shut is 180 days old at the next shut and 360 at the one after.
Change it at 180 days and you give up a third of the life you planned to use.
Wait for 360 and you run it well past the point where the risk justified a
change. Stop the belt at 298 days and you pay extra for the privilege. The age
answers a question the calendar won't let you act on.

## The rule: a threshold at each shut

When changes are cheap only at a shut, the best rule takes a different form:
at each shut, replace the part if it is older than a threshold age, and
otherwise leave it until the next one. The threshold trades off the price of a
new part now against the chance the old one fails before the next shut, plus
the cost of arriving at that shut with a part that is 180 days older. The rule
can also have a second line for the days between shuts ("stop the belt for a
part older than *X*"). Often that line says never.

## A worked example

Take a pulley whose life follows a Weibull distribution with a scale of 365
days and a shape of 2, so it wears out (its mean life is 323 days). The plant
shuts every 180 days. Call a change at the shut 100. A failure costs 400: the
belt stops when it chooses, and takes production and a call-out with it. A
planned change between shuts, stretching a weekly stop, costs 150. With a life
measured in hundreds of days, a stop every week is as good as any day.

The answer: **at the shut, replace the pulley if it is older than 138 days.**
Between shuts, don't; wait for a shut or a failure. The rule costs about 362 a
year in the long run.

![Long-run cost a year against the threshold age at the shut. The curve falls from 386 at a threshold of zero to its lowest, 362, at 138 days, stays nearly flat to 180 days, then jumps to 377 and climbs, because a threshold past the shut spacing leaves a part fitted at a shut for the shut after next. Dashed lines mark the alternatives: run to failure at 452, a fixed age of 298 days at 408, and a change at every shut at 386.](/blog/shutdown-replacement-cost.png)

Against the simpler rules:

| Rule | Cost a year | More than the threshold rule |
| :-- | --: | --: |
| Run to failure | 452 | +25% |
| Fixed age of 298 days, ignoring the shuts | 408 | +13% |
| Change it at every shut | 386 | +7% |
| **At the shut, replace if older than 138 days** | **362** | — |

Read the other way round, the rule is 20% below running to failure, 11% below
the best fixed age and 6% below changing at every shut.

Two things stand out in the chart. The bottom is flat: any threshold from 100
to 180 days costs within 1 a year of the minimum, so the exact number matters
less than having one. And the cost jumps at 180 days: past the shut spacing, a
pulley fitted at a shut is never old enough at the next one, so it waits for
the one after, at 360 days old.

Where the money goes under the rule: about 1.6 shut changes a year (158) and
0.5 failures a year (204). Failures are still 56% of the cost, because the
shuts are too far apart to prevent them all at a price worth paying. About 78%
of shuts need the change.

## What changes the answer

**The failure cost.** The ratio of failure to planned cost drives everything,
and it is the number most people undercount (lost production, the 3 am
call-out, the freight). If a failure cost only twice the shut price (200), the threshold moves to 324
days (change it at the second shut) and the rule beats running to failure by
just 3%. At eight times (800), the threshold drops to 59 days, which means
nearly every shut, and changing it at every shut costs only 2% more.

**The shut spacing.** Shuts every 90 days give a threshold of 178 days and
361 a year: the same cycle as before, for almost no gain, because 180 days is
already close to the best age at the shut price. A shut only once a year gives
a threshold of 133 days (nearly every shut) at 385 a year, and now a second
line appears: stop between shuts for a part older than 228 days.

**The shape.** With a shape of 1.5 the threshold is 231 days and the rule is
only 7% below running to failure. With a shape of 3 it is 112 days and 37%
below. With a shape of 1 nothing pays: a new part is no more reliable than the
old one, and the honest answer is run to failure. That too is a decision with a
number behind it, which a later post takes up.

## One unit now

The long-run rule covers the fleet. The pulley in front of you today is one
question, and the same model answers it.

Say today is a shut. A pulley fitted 120 days ago: keep it. Leaving it to the
next shut costs about 88 in expectation, against 100 to change it now. One
fitted 150 days ago: change it; keeping it would cost about 107. The
break-even is 139 days, the rule's threshold to within a day of the
calculation's grid.

Say instead the next shut is 60 days away and a pulley is 300 days old, well
past the threshold. Don't stop the belt. Waiting for the shut costs about 126
in expectation, against 150 to stop now. Replacing it today only wins from an
age of about 416 days.

## Doing it in Reliafy

Open [Optimal replacement in Shutdown calendar mode](/strategy/replacement?mode=calendar).
Give it the life model (saved, or a distribution's parameters), each kind of
shut with its cost and when it comes, the failure cost and, if you'd ever do
it, the cost of a change between shuts. Compute gives the rule in words, the
cost a year against the simpler rules, where the cost goes, the coming shuts
by date with the chance each needs a change, and **One unit now** for the part
in service.
The exact methods are free. [The guide](/guides/optimal-replacement-interval)
walks through this example.

The maths is in [RePyability](https://github.com/derrynknife/RePyability), the
open-source system reliability library under Reliafy
(`optimal_calendar_policy`). Every figure above comes from the released version
and is unchanged on its development branch.

## The formula

> **In words.** A rule's long-run cost a year is the shut changes it causes
> each year times their price, plus the failures each year times theirs. For
> one pulley, the rule fixes when it comes out: the first shut at which it is
> older than the threshold, unless it fails first. The cost rate is the expected
> cost of one pulley's time in service over its expected length, averaged over
> the moments in the shut cycle at which pulleys get fitted.
>
> **In symbols.** Shuts come every *P*; the threshold is *a\**; a change at the
> shut costs *c*<sub>s</sub> and a failure *c*<sub>f</sub>; *R*(*t*) is the chance
> a new pulley lasts beyond age *t*. A pulley fitted *s* after a shut sees shuts
> at ages *P* − *s*, 2*P* − *s*, …, and comes out at the first of those, τ(*s*),
> that is at least *a\**:
>
> E[*L* | *s*] = ∫<sub>0</sub><sup>τ(*s*)</sup> *R*(*t*) d*t*
>
> E[*C* | *s*] = *c*<sub>s</sub> *R*(τ(*s*)) + *c*<sub>f</sub> [1 − *R*(τ(*s*))]
>
> *g*(*a\**) = E<sub>*s*</sub>[*C*] / E<sub>*s*</sub>[*L*]
>
> where *s* follows the long-run spread of fitting moments under the rule (a
> shut change fits a pulley at *s* = 0, a failure at whatever moment it struck).
> That spread depends on the rule itself, so there is no closed form: the
> calculation solves it as a dynamic programme on a fine grid of ages and
> positions in the shut cycle, exact for the grid, and picks the threshold with
> the lowest *g*. Run to failure is *c*<sub>f</sub> over the mean life.
