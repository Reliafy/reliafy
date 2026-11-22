---
title: "Say what each task needs, and package tasks into visits (Maintenance › What it needs)"
task: "How do I record the labour, tools, spares and consumables each task needs, and bundle the tasks of an area so each visit raises one work order?"
category: "Maintenance strategy"
prerequisites: "A position or location in your asset tree with some tasks on it (from its RCM decisions, or added by hand)."
order: 27
# Reliafy Maintenance is operators-only for now: this guide is linked from the
# Maintenance › What it needs view itself and stays out of the index until Maintenance opens.
hidden: true
---

The LSA (logistic support analysis) holds the *how* of your maintenance. In
the Explorer it's the **What it needs** view of the **Maintenance** tab. The RCM says what is done and why; the LSA says what each task
needs to be done: who does it and for how long, the tools and instruments, the
spares and consumables to bring, access and downtime, and the method. It's
also where tasks are packaged into visits.

A work package is the tasks done together on one visit: the weekly check of
the pool, the Saturday walk round the plant room. Each visit raises **one**
work order with a line per task, instead of one work order per task. The tasks
keep their instructions, checklists and failure modes; the package only
decides when they're done. Where work management is turned off, a package is a
grouping of tasks and dates in a hypothetical plan, which the forecasts use:
nothing is raised.

A package can have **layers**: a monthly check is the weekly visit plus a few
more lines on the first Saturday of the month, and a quarterly one adds more
on every third month. A layer has its own name and tasks, but its lines go on
the weekly visit's work order that day, so there's still one work order per
visit.

## Every task here and below

The **Tasks** view of the **Maintenance** tab shows your tasks **in the tree**:
under each position (or place) hang its own maintenance tasks, one row each,
with **Interval**, **Next due**, **Cost each time**, **Package**, **From** and
**Kind** beside them. Every level says how many tasks are on it and below it
(*2 here · 7 tasks at and below · 1 overdue*), so the top of an asset adds up
its whole programme; open or close a level with its arrow. Only the asset you
opened is shown, and retired tasks aren't.

Click a task to open it beside the table: change how often, its cost or what
it prevents, and see the repairable RBDs that use it. **Add task…** on a row's
**More actions (…)** adds one to that position. **Trade rates…** in the
heading's **…** prices every task's labour.

**Forecast…** on a position's **…** runs the forecast for that level and
everything inside it (the work, the expected failures and the costs to come,
by month, quarter or year) in the table area, with the tree still beside it.
It's the same forecast as the **Forecast** view, for whichever level you pick.

## See the tasks here

Open **Assets → Explorer**, pick a position or a location, choose the
**Maintenance** tab and then **What it needs**. It's a table of every task on that row and everything
inside it, set out like the RCM table, one row per task:

- **Position** — where the task is done;
- **Failure mode** — what it prevents, with its function and functional
  failure under it;
- **Task**, **Kind** (on condition, fixed interval or failure finding; a task
  raised by an event says which), **Interval**, **Trade** and **Next due**;
- **Package** — the package it's done in, or blank when it's done on its own;
- **Labour** (hours by trade: people × hours, added up), **People**, **Tools**,
  **Spares** and **Consumables** (the first names and how many more; hover for
  the full list) and **Method**.

Pick a higher row in the tree to see more of it. Choose which columns show
from the panel's **More actions (…)** › **Columns…**.

## Say what a task needs

Click a task (its row or its name) to open its LSA in the view (**← All tasks
here** goes back). It shows the task's kind, interval, position and the
failure modes it serves, then a section for each thing it needs. Each section
saves when you leave it and says **✓ Saved**:

- **Labour** — a line per trade: how many people and the hours each, plus the
  elapsed hours of the job.
- **Tools and instruments** — tools and test equipment. An instrument can name
  the measuring point or channel it reads (the free-chlorine point for a
  photometer), so which sensor does the monitoring is part of the how, not the
  RCM decision.
- **Spares** — pick a part from the parts register (its part number shows), or
  type a name for one that isn't in it.
- **Consumables** — what the job uses up, with a quantity, a unit and, if you
  know it, the cost for that quantity.
- **Access and downtime** — downtime hours, permits, isolation and access
  equipment.
- **Method** — how it's done, in a line ("Shop sample to the pool shop", "Home
  kit"), and the task's **Instructions**, which go on its work orders.

A position's **Summary** shows a line under Work, such as "Annual labour: 34 h;
spares: 2 lines": each task's labour hours times how many times a year it's
due. Tasks raised by an event, or counted by run hours, have no yearly count,
so they're left out and the line says how many.

To take the table into a spreadsheet, choose **Export CSV** from **More
actions (…)**: every column, with the tools, spares and consumables named.

## Find the tasks that go together

Type in the search box to narrow the table: every word must appear somewhere
in the row (the pump's name, "bearing", "fitter", a package's name). Click a
column's heading to sort by it, again to sort the other way. **Shift-click**
another heading to sort by it second: Trade, then Interval puts each trade's
weekly tasks together. The search and the sort stay in the address, so a link
opens the table as you left it.

## Package them

Tick the tasks done on the same visit (the box in the heading ticks every
task shown). A bar at the foot of the table says how many you've ticked:

- **Package selected…** makes a new package with them. Give it a name, how
  often it visits (it starts at the ticked tasks' commonest interval), the
  day of the week (Monday to start with), the trade and how many days after
  the visit still count as on time (1 to start with).
- **Add to a package…** puts them in a package already on this part of the
  tree, on every visit or every Nth one.
- **Clear** unticks them.

The bar also adds up what the ticked tasks need: labour hours by trade, the
tools (each once), the spares to stage and the consumables. So when you
package a visit, you can see what to bring.

The **Package** column fills in at once. Rounds, and tasks counted on a meter
other than operating hours (km, cycles), stay on their own, so their boxes
can't be ticked; tasks already in a package stay where they are.

Tasks counted in **operating hours** make a package by hours, such as a 50 h
service: tick them together (not with calendar tasks). The visit goes by the
shortest interval, and a task at a whole multiple of it goes on every Nth
visit, so a 100 h oil change comes on every second 50 h service. The package
counts from the position's hour meter reading now, and its page shows each
visit's hours and the date it's expected, from the operating plan (else the
meter's recent rate; with neither, the reading it's due at, such as "due at
150 h"). It needs an hour meter on its position.

To let Reliafy draft the packages for you, right-click the row in the tree (or
press its **⋯**) and choose **Package the tasks here…**, the first item on
this view. **Package the tasks…** in **More actions (…)** does the same for the
row you're on. The drafts open in the view, in place of the table (**← All
tasks here** goes back). It groups every task here that isn't in a package by
how often it's due and by trade: the weekly ones visit on the day you pick,
and monthly and longer ones become layers on those visits (the first of that
day in the month). Untick or rename the drafts, then **Make** them, all together
or none.

## Look after a package

Click a package's name in the **Package** column to open it in the view (**← All packages here** goes back).
**Maintenance › Packages** lists every package on that part of the tree and
below (how often, trade, how many tasks, and whether it's paused); click a
name there to open it the same way. A product's design has no packages: they
belong to the built items. You see its tasks, each with where it
is, its visit rule ("every visit", "every 4th visit"), what it covers and
**Owed** when it wasn't done on the last visit (it goes on the next one), and
its layers, and **Each visit needs**: its tasks' labour, tools, spares and
consumables added up. Its **⋯** has:

- **Add tasks…**: the tasks where the package is, and below, that aren't in a
  package; on every visit or every Nth one.
- **Pause…**: with a reason and a return date. Nothing is raised while it's
  paused and its tasks aren't overdue; the first visit back can catch up on
  everything missed.
- **Resume** and **Retire…** (its tasks go back to being raised on their own).

A task's own **⋯** has **Remove from package…**.

## Where else packages show

- On the **RCM** tab, a task in a package shows **In:** and the package's name; click
  it to open the package.
- A position's **Summary** shows **Next visit** under Work when its tasks are
  in a package.
- A package's own page and its view here list **Parts for the visit**: each part
  against the stock usable now, and when an order placed today lands. The
  spares each task uses also count in **Maintenance › Spares**: spares for the
  year, against stock and lead time.
