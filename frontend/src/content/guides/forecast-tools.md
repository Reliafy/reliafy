---
title: "Quick forecasts: spares, labour hours and costs"
task: "How many spares will these units use next year, how many maintenance hours will they need, and what will they cost? I want a quick answer, not a saved forecast."
category: "Maintenance strategy"
prerequisites: "How often the work is done, or a life model of the part (a saved non-repairable model, or its distribution and parameters) and roughly how old the units are. Both if you have them."
related_href: "/forecasts/spares"
related_label: "Open the spares forecast"
order: 23
---

**Decisions › Forecasts** has one quick forecast tool with three answers:

- [Spares forecast](/forecasts/spares): how many spares the units will use, and
  how many to hold.
- [Hours forecast](/forecasts/hours): the maintenance hours they will need.
- [Cost forecast](/forecasts/costs): what they will cost to maintain.

It's a scratch pad: nothing is saved. There is no Forecast button: the answer
follows as you type. The three views share the same inputs, so you can switch
between **Spares**, **Labour hours** and **Costs** at the top without typing
anything twice.

For a forecast you keep, with each item named and its own usage, use
[Fleet forecasts](/forecasts) instead.

## Fill in the sentence

The inputs read as one sentence: *[1] unit, running [12] [h a week], over [the
next 12 months]*. **Running** is all the time (24 hours a day), so many hours a
day, or so many hours a week. Then fill in one or both of these:

- **Work on a schedule**: what the work is, how often (every so many hours,
  days, weeks, months or years) and what it needs **each time**. No model is
  needed. Its count comes from the schedule, so it's **certain**: no range, no
  chance involved. It's assumed just done at the start. Work by hours goes
  through the running hours; work on the calendar counts on dates whatever the
  running.
- **A part that fails**: its life (a saved model, or a distribution with its
  parameters), how old it is **now** and what a failure needs (**if it fails**).
  Its failures are a chance, so they come with a likely range.

Each view asks only its own extra: on **Labour hours**, the hours each time and
the hours if it fails; on **Costs**, the cost each time and the cost if it
fails; on **Spares**, how many of which spare each time (a failure uses a like
part). A value typed in one view is kept in the others.

With both filled in, say what the work does to the part: it **doesn't change
the part's life** (an oil change, a test), or it **replaces the part** (a
planned replacement at that age, so the failures left are those before it).

**More options** holds the rest: a different age for each unit, the cost of a
spare (added to each failure and replacement), the use a unit adds a day for a
life in cycles or kilometres, and the other views' figures.

## Read the answer

Each view leads with one sentence, for example *12 times in the next 12
months: 2.4 h* for work alone, or *64% chance it fails in the next 12 months:
$124,000 expected* for one part with less than one failure expected. Then:

- **The lines**: one row for each owner, the work and the part's failures, with
  how many times, the view's figure and the **kind of number**: *certain* (from
  a schedule), *worked out* (exact arithmetic) or *simulated* (from many seeded
  runs, the same every time).
- **Ranges** are **90% two-sided**: in nine years out of ten the number falls
  inside it. A certain line has none; in a total it's added to both ends of the
  range. "90% chance of no failure before month 2" is **90% one-sided**, the
  lower bound on life.
- **Not counted**: anything a figure leaves out because it wasn't given (no
  cost if it fails, no hours each time). The total then says it's the known
  total. Nothing is guessed.

The chart shows each period with its likely range as whiskers, and **By
month** gives the same numbers in a table. **Export CSV** saves them. On
**Spares**, **When next** gives the period by which each of the first spares is
likely used, and **Spares: how many to hold** takes the part's lead time and
your service level.

## Start from the Explorer

On the Explorer's **Maintenance** tab, a position, a task or a work package has
**Open in ›** in its menu: **Optimise**, **Spares forecast**, **Hours forecast**
and **Cost forecast**. Each opens the tool filled in from that row and
everything below it, with a line naming where it came from and a link back:

- the life model in use on the positions there (the one most of them use);
- the units, each with its fitted item's age (from its counter, or the days
  since it was fitted);
- the hours a day from the duty set in **Operations**;
- a task as the work on a schedule: its interval, its labour hours and its
  cost each time (a replacing task replaces the part), and the cost of a
  failure there.

Only what's recorded is filled in. With no duty, the running is left for
you to set, and an age that can't be read is left out and listed. Nothing is
written back to the Explorer.

**Open in › Optimise** opens [Optimal replacement](/strategy/replacement) with
the task's model and costs filled in, to try other intervals. To change a
task's interval, use **Optimise…** on the task itself.
