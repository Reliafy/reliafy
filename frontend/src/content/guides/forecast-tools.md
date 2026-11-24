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

It's a scratch pad: nothing is saved. Fill in the inputs and press
**Calculate** (bottom right of the inputs, or Enter in any field). The three
views share the same inputs and the same answer, so you can switch between
**Spares**, **Labour hours** and **Costs** at the top without typing anything
twice or calculating again. Change an input after an answer and it says
**Inputs changed: Calculate again**; the answer stays until you do.

If something is missing when you press **Calculate**, it says what beside the
field and goes there: "Enter how old it is now", "Pick the unit of its age and
its life".

For a forecast you keep, with each item named and its own usage, use
[Fleet forecasts](/forecasts) instead.

## Fill in the inputs

At the top: **Units**, **Running** (all the time, so many hours a day, or so
many hours a week) and the **Horizon**. Then add one or both of these
sections (each has **Add** and **Remove** at its right):

- **Work on a schedule**: what the work is, how often (every so many hours,
  days, weeks, months or years) and what it needs **each time**. No model is
  needed. Its count comes from the schedule, so it's **certain**: no range, no
  chance involved. It's assumed just done at the start. Work by hours goes
  through the running hours; work on the calendar counts on dates whatever the
  running.
- **A part that fails**: its life, **Saved model** (it brings its own unit) or
  **Type parameters** (the distribution, its parameters such as **Scale α** and
  **Shape β**, and the **Unit**, hours unless you pick another: days, weeks,
  months, years, cycles, starts, km, miles or operations); its **Age now**, in
  the same unit; and what a failure needs (**if it fails**). Its failures are a chance, so they
  come with a likely range. They're *worked out* (exact arithmetic, the same
  as a forecast opened from the Explorer), not simulated; only a list of more
  than 60 different ages is simulated, and the answer says so.

Each view asks only its own extra: on **Labour hours**, the hours each time and
the hours if it fails; on **Costs**, the cost each time and the cost if it
fails; on **Spares**, how many of which spare each time (a failure uses a like
part). A value typed in one view is kept in the others.

With both filled in, say what the work does to the part: it **doesn't change
the part's life** (an oil change, a test), or it **replaces the part** (a
planned replacement at that age, so the failures left are those before it).
**When the part is replaced** (under More options) is **Restart its
schedule** by default (age replacement: a failure restarts its clock, so the
planned count is a chance) or **Keep its schedule** (block replacement: on its
dates, failures or not). Work that doesn't change the part's life and restarts
when it's replaced shows its scheduled count with a note on how many fewer
replacements may make it.

**More options**, at the bottom, holds the rest: a different age for each unit,
the cost of a spare (added to each failure and replacement), and the other
views' figures. A life in cycles or kilometres asks how many a unit adds a day,
beside its age.

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

## Supporting work: what if it isn't done?

Choose **keeps the part on its life (supporting)** for work like greasing or
an oil change, and say what not doing it does: **If it isn't done: failure
rate × 2** (twice as likely to fail in any hour while it isn't done). The
answer then gives its **Worth**: the failures (and their cost) it avoids in the
horizon, for its own cost. That's a comparison of two forecasts, so it's
added to no total; the work's cost stays on the work, the failures on the part.

**What if it's** stretched to a longer interval, or not done, shows the answer
with that change beside the plan: not done, the failure rate × 2 the whole
time; stretched from every 250 h to every 500 h, it's overdue half the time,
so the failure rate is × 1.5 on average. A shorter interval than the one the
life assumes has no modelled benefit, and says so. When the interval is more
than a fifth of the part's mean life, the averaged rate is a rough guide and
the answer says **Approximate**. **Grace** (under More options) is how far
overdue it may run before the impact starts. Several supporting tasks on one
part multiply. Nothing is saved.

## Start from the Explorer

On the Explorer's **Maintenance** tab, a position, a task or a work package has
**Open in ›** in its menu: **Optimise**, **Spares forecast**, **Hours forecast**
and **Cost forecast**. Each opens the tool on that row and everything below it,
with a line naming where it came from and a link back. There is no form: the
records are the inputs, and the answer is set out **by owner**:

- **Each task** has its own line: how many times it falls due in the horizon
  (from its schedule, so *certain*), its labour hours and its cost each time.
  A task in a package is counted once, through the package; a package's visit
  cost (call-out, set-up) is its own line.
- **Each failure mode** with a life model has its line: the failures expected
  with the plan in place and their likely range (*worked out*). Under it, the
  **corrective** line (after a failure: its hours, spares and cost from the
  failure mode's response if it fails; a cost of a failure typed on the mode
  overrides the response's cost, and the position class's figure is used when
  neither is there) and, when a check with a P-F interval finds
  some in time, the **follow-on** line (found at an inspection: its hours,
  spares and cost from the failure mode's follow-on task, **Follow-on: when
found**, on the Maintenance tab). The same
  failure mode on several positions at the same cost is one owner.
- **Supporting tasks: what if** lists each supporting task with an impact, its
  **Worth** (the failures it avoids in the horizon, for its cost), and a
  what-if: stretch it or mark it not done to see the forecast **With your
  changes** in a column beside the plan as recorded. Nothing is written. A
  supporting task whose own interval is already longer than the one its life
  assumes counts its impact in the plan as recorded too.
- **A supporting task** (greasing, an oil change) reads *Keeps it on its life*:
  the life model already assumes it, so it changes no failure while it's done
  as planned. An assumed impact carries an **Assumed** chip.
- **The total** is the sum of the lines, each counted once, with its 90%
  two-sided range; on **Costs** it splits into planned, follow-on and
  corrective.

**Not counted** lists every gap with a link to where it's fixed: a failure mode
with no cost of a failure (its failures are still counted, their cost isn't), a
check with no P-F interval (its finds aren't counted, so every failure goes to
the corrective line), a fitted position with no life model, a task that can't
be put on dates, a task with no cost or no labour, and a failure mode with no
response if it fails (**Add** opens the form for it on the Maintenance tab),
and one whose finds have nothing recorded for them (**Add** opens the form for
a follow-on there). A total
with a gap says it's the **known** total; nothing is guessed.

The horizon is from today, 12 months unless you choose 2, 3 or 5 years. The
running hours come from the position's duty, else the rate of its hours
readings, else 24 hours a day, and the line under the title says which. **By
month** gives the tasks, labour hours, planned cost, failures and unplanned cost
for each month. Nothing is written back to the Explorer.

**Open in › Optimise** opens [Optimal replacement](/strategy/replacement) with
the task's model and costs filled in, to try other intervals. To change a
task's interval, use **Optimise…** on the task itself.
