---
title: "Quick forecasts: spares, labour hours and costs"
task: "How many spares will these units use next year, how many maintenance hours will they need, and what will they cost? I want a quick answer, not a saved forecast."
category: "Maintenance strategy"
prerequisites: "A life model of the part (a saved non-repairable model, or its distribution and parameters), and roughly how old the units are and how much they run."
related_href: "/forecasts/spares"
related_label: "Open the spares forecast"
order: 23
---

**Decisions › Forecasts** has one quick forecast tool with three answers:

- [Spares forecast](/forecasts/spares): how many spares the units will use, and
  how many to hold.
- [Hours forecast](/forecasts/hours): the maintenance hours they will need,
  planned task hours plus the hours spent putting failures right.
- [Cost forecast](/forecasts/costs): what they will cost to maintain, planned
  work plus corrective work plus spares.

It's a scratch pad: nothing is saved. Change anything and press **Forecast**
again. The three views share the same inputs, so you can switch between
**Spares**, **Labour hours** and **Costs** at the top without typing anything
twice. One forecast feeds all three.

For a forecast you keep, with each item named and its own usage, use
[Fleet forecasts](/forecasts) instead.

## What to enter

- **Life model**: a saved non-repairable model, or a distribution with its
  parameters typed in (then also the unit of its times).
- **Units** and **Age now**: one age for them all with how many there are, or
  one age per unit (spaces or new lines between). Ages are in the model's unit.
- **How much they run**: the hours a unit runs a day (or, for a model in
  another unit, the use it adds a day) and the days a week it runs.
- **Replacement**: replace on failure, or preventive replacement at an age.
  With preventive replacement, each unit is replaced when it reaches that age,
  and the planned replacements count as spares too.
- **Hours and costs** (optional): the hours a failure takes to put right, the
  hours a planned replacement takes, the cost of a failure (besides the spare),
  the cost of a planned replacement and the cost of a spare. The Hours and Cost
  views say which of these they still need.
- **Horizon** and **Group by**: 12 months to 5 years, by month, quarter or year.

## Read the answer

Each view leads with one sentence, for example *≈ 14 spares used in the next 12
months*, then the likely range. Ranges are **90% two-sided**: in nine years out
of ten the number falls inside it. They come from simulating the units many
times, so they include the chance in which units fail and when. Failed units
are replaced, and the replacements can fail again inside the horizon.

The chart shows each period with its likely range as whiskers, and the table
below it gives the same numbers by period. **Export CSV** saves the table.

- **Spares** also lists **When next**: the period by which each of the first 20
  spares is likely used, from the expected counts. Under it, **Spares: how many
  to hold** takes the part's lead time and your service level and gives the
  stock to hold and when to reorder.
- **Labour hours** splits each period into planned and corrective hours.
- **Costs** splits each period into planned work, corrective work and spares.

## Start from the Explorer

On the Explorer's **Maintenance** tab, a position, a task or a work package has
**Open in ›** in its menu: **Optimise**, **Spares forecast**, **Hours forecast**
and **Cost forecast**. Each opens the tool filled in from that row and
everything below it, with a line naming where it came from and a link back:

- the life model in use on the positions there (the one most of them use);
- the units, each with its fitted item's age (from its counter, or the days
  since it was fitted);
- the hours a day from the duty set in **Operations**;
- a task's interval as the replacement age (when it's in the model's unit), its
  labour hours and its cost each time, and the cost of a failure there.

Only what's recorded is filled in. With no duty, the hours a day are left for
you to type, and an age that can't be read is left out and listed. Nothing is
written back to the Explorer.

**Open in › Optimise** opens [Optimal replacement](/strategy/replacement) with
the task's model and costs filled in, to try other intervals. To change a
task's interval, use **Optimise…** on the task itself.
