---
title: "Forecast the maintenance plan: the work, failures and cost to come (Maintenance › Forecast)"
task: "What will the plan I have set up do next year: how many tasks and labour hours, how many failures, and what will it cost? And what would change if I changed the plan?"
category: "Maintenance strategy"
prerequisites: "Positions with tasks on them and items fitted, and a life model in use on the positions whose failures you want counted. An operating plan for any task counted in running hours."
order: 30
# Reliafy Maintenance is operators-only for now: this guide is linked from the
# Maintenance › Forecast view itself and stays out of the index until Maintenance opens.
hidden: true
---

The forecast reads the plan as you have recorded it (the tasks, how often each
falls due, the packages) and says what it will cause over the next year or
more: the tasks and labour hours, the failures to expect with a range, and the
costs. It saves nothing and changes nothing. Change the plan, open the forecast
again, and read the difference.

## Forecast at any level

Open **Assets → Explorer**, pick a position, then **Maintenance → Forecast**.
The forecast is for that position **and everything inside it**, inside the
asset you opened: nothing above it is used. So the same view gives you one
pump, a pump station or a whole plant, depending on the row you pick.

From the **Tasks** view, **Forecast…** in a row's **⋯** menu runs it for that
level with the tree still beside it. Choose **Months**, **Quarters** or
**Years** under **By**.

The answer comes first, in a sentence:

> To 30 Nov 2027: **58** tasks, about **46** labour hours, **$2,800** planned;
> **0.62** failures expected (0 to 1, 90% range), about **$2,990**; about
> **$5,790** in all (**$2,800** planned, **$2,990** unplanned).

Under it, a line says where the hours came from (the operating plan, or the
hours counter's recent rate). Then a table by month, quarter or year:
**Operating hours**, **Tasks**, **Labour hours**, **Planned cost**, **Expected
failures**, **Unplanned cost**, **Downtime** (when a failure's downtime is set),
**Total cost**, and **Besides the routine**, which names the jobs that fall
due only a few times in the forecast (a service, an overhaul), with their dates,
so the weekly round doesn't fill every row. Hover a column's heading to see what it rests
on. The table scrolls inside its card on a phone. Ranges are 90% of outcomes
(the 5th to 95th percentile), and the last row, **In all**, adds up the period
and gives the chance of at least one failure.

The forecast starts from today, so the first row is marked *(from 14 Nov)*: it
covers the rest of that month, not a whole one.

## Which tasks count

A task counts when it can be put on dates:

- A calendar task (*every 6 months*, or a pattern such as *the first Saturday*)
  falls due on its dates. A task in a work package falls due at the package's
  visits.
- A task counted in operating hours falls due through the position's operating
  plan, or its hours counter's recent rate.
- A task left out says why under **Left out**: for example a task by hours on a
  position with no operating plan and no hours reading. The answer says *Say how
  this runs (an operating plan), or record an hours reading, to put the tasks by
  use on dates.* The fix is on that position; see below.

Failures come from the life model in use on each position, from each item's
age. A degradation model linked to a failure mode counts too: each time the
reading crosses its limit (its time to the limit) is a failure of that mode. They count what the tasks do. A fixed-interval replacement renews the item
at its interval, so failures after it count from new. A check that finds a
warning in time counts through its P-F interval. A task that restores none of
the age (greasing a bearing) leaves the failures as they are. Each life's line
under **Failures: the life models used** says which tasks were counted and which
weren't, with the reason. A life model that was typed in, not fitted from data,
is flagged as a placeholder.

Other folds: **Tasks on dates** lists every task with its dates and cost each
time; **By position** splits the answer by what's inside; **Cost by kind** splits
the cost (below); **Left out** names everything not forecast.

## Planned and unplanned cost

The cost to come is in two parts, each saying what it rests on:

- **Planned:** each task's cost each time, times the times it falls due.
  **Cost by kind** splits it into **Labour** (the task's LSA labour at the
  trade rates), **Parts and consumables** (its LSA lines) and **Visits**: each
  visit's call-out and setup, set on the package (**Each visit's call-out and
  setup** in its Edit pane), or on a task in no package. Tasks due at the same
  time on the same position are one visit, charged once. A cost typed on a
  task that its LSA doesn't explain is **Other planned**.
- **Unplanned:** the expected failures times what one failure costs: its
  repair, plus the hours it keeps the asset out of use times the cost of an
  hour out of use.

**What a failure costs** is entered on the failure mode, on the **RCM** tab:
pick the failure mode, and under its consequence fill in **A failure costs**,
**Out of use per failure** and, if an hour out of use costs something on top,
**An hour out of use costs**. A figure left empty takes the one set on the
position's class, shown in the box. A life that covers several failure modes
takes the costliest of them, and says so. With no failure cost anywhere, the
failures still show, but the unplanned cost leaves them out and the total
shows **+ ?**.

## What to enter

When something would make the forecast count more, **What to enter** lists it,
each with a link straight to where you enter it:

- **Failure modes with no failure cost:** open the failure mode and enter what
  one failure costs.
- **Checks with no P-F interval:** an on-condition check counts once its
  failure mode's decision has a P-F calculation as its evidence (the check
  interval calculator saves one).
- **Tasks with no modelled effect on failures:** their cost counts, but the
  failures are as they would be without them. A task's line says why: it serves
  no failure mode, its failure mode has no life model, or it restores none of
  the item's age.

A fixed-interval task with nothing set for what it leaves the item as is taken
as a renewal (as good as new), except servicing work, whose name starts with
greasing, cleaning, adjusting, tightening and the like: that is taken to
restore none of the age. The task's **What it leaves the item as** says when
it's assumed, and you can change it there or on the failure mode's decision.

## Compare two plans

The forecast is worked out each time you open it, so comparing two plans is a
matter of changing one thing and reading again:

1. Open the forecast and write down the answer: the sentence, or the **In all** row.
2. Change the one thing: a task's interval, a package's visit, or a position's
   operating plan.
3. Open the forecast again at the same level and period. The difference is the
   effect of that one change.
4. Put it back, or keep it.

Two plans for the same equipment give different failures, not only different
costs. A ride-on mower on its maker's 25-hour plan, where the spark plugs are
only inspected, expects about 3.3 breakdowns per 600 operating hours. On a
50-hour plan that replaces the plugs every 100 hours, it expects about 1.5.
Read the **Expected failures** and **Unplanned cost** columns beside **Planned
cost**, and **Total cost** for both: a plan that does less work costs less in
tasks and more in failures. With a failure cost of $900 a spark plug and $900 a
spindle bearing, the 25-hour plan's failures cost about $2,900 per 600 hours
in the long run, and the 50-hour plan's about $1,400. A new mower fails less in
its first year than in the long run, so the first year's figures are lower.

The change is real while you try it, so put it back when you've read the
answer. A saved side by side of two plans isn't in the app yet.

## Packages, a 50 h and a 100 h service

Tasks counted in **operating hours** can be packaged into a visit by hours.
In the Explorer's **What it needs** view, tick tasks that are counted in
hours (not mixed with calendar tasks), then **Package selected…**. The visit
goes by the shortest interval, and a task at a whole multiple of it goes on
every Nth visit. So an oil change due every 50 hours and a gearbox check every
100 come together: the 50 h service has the oil change, and every second visit
adds the gearbox check. The package counts from the position's hours counter
reading now, and its page shows each visit's hours and the date it's expected,
through the operating plan.

The forecast counts that package's visits, task by task. To see what one
visit needs, open the package: **Parts for the visit** lists each part against
the stock usable now, and *Which jobs to do at this visit* lets you untick a job
to compare choices before you change the package.

## What the plan costs, by interval

Where a position class has a non-repairable model and its two costs (a planned
replacement and a failure), a **What the plan costs** card on the class panel
compares the options in a table: **Plan**, **Interval**, **Per year** and **Net
present cost**. It shows **current plan**, **best interval**, **run to
failure**, and a **what if** you type: *What if every [300] [days]*, over a
number of years at a discount rate. The cheapest plan is in bold. It is a
long-run cost across the positions in the class and rough when there are few
failures on record, and the card says so. The class panel is on the Explorer's
**Classes** tab, where that tab is switched on.

## Where to go next

The hours that put tasks on dates come from the position's operating plan: say how
a position runs there, and set the time zone so dates are the site's.
