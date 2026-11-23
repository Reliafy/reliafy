---
title: "Say what each task needs, and package tasks into visits (Maintenance tab)"
task: "How do I record the labour, tools, spares and consumables each task needs, and bundle the tasks of an area so each visit raises one work order?"
category: "Maintenance strategy"
prerequisites: "A position or location in your asset tree with some tasks on it (from its RCM decisions, or added by hand)."
order: 27
# Reliafy Maintenance is operators-only for now: this guide is linked from the
# Maintenance tab itself and stays out of the index until Maintenance opens.
hidden: true
---

The LSA (logistic support analysis) holds the *how* of your maintenance. In
the Explorer it's part of the **Maintenance** tab: a **What it needs** section in each task's details. The RCM says what is done and why; the LSA says what each task
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

The **Maintenance** tab is one table (it has no views to switch between). It shows your tasks **in the tree**:
under each position (or place) hang its own maintenance tasks, one row each,
with **Interval**, **Next due**, **Cost each time**, **Trade**, **Packaged**,
**From** and **Kind** beside them. Every level says how many tasks are on it and below it
(*2 here · 7 tasks at and below · 1 overdue*), so the top of an asset adds up
its whole programme; open or close a level with its arrow. Only the asset you
opened is shown, and retired tasks aren't.

Click a task to open it beside the table: change how often, its cost or what
it prevents, and see the repairable RBDs that use it. **Add task…** on a row's
**More actions (…)** adds one to that position. **Trade rates…** in the
heading's **…** prices every task's labour.

**Filter a column** with the funnel in its heading: tick the values to keep
(an interval, a trade, a package, "In no package", a kind). The values listed
come from the tasks in the part of the tree you have open, each with how many
tasks have it. Tasks that don't match are hidden, the positions above the ones
that do stay so the tree still reads, and every level's count follows the
filter. The tree's heading says **Filtered by …** while one is on; **Clear**
there turns them all off. On a phone, the **Filter** button under the search
box holds every column's.

**Package tasks from the tree.** Click a task, then **Shift-click** another to
pick every task between them, or **Ctrl-click** (**⌘-click** on a Mac) to add
or take one; **Space** picks the task you're on and **Shift+↑/↓** extends the
pick. The tree's heading says how many are picked, with **Clear**. On a phone,
open a task's **⋯** menu and choose **Select**, then tap more tasks until
**Done**. Right-click one of them (or
press its **⋯**; on a phone, press and hold) and choose:

- **Package…** — a new work package with them, in the table area beside the
  tree. Its name, interval and unit start from the tasks' (a 50 h service for
  tasks every 50 operating hours). When their intervals differ it says so: a
  task at a whole multiple of the interval you choose comes on every Nth visit
  (a 100 h oil change on every second 50 h service), and any other on every
  visit.
- **Add to package…** — one of the packages on this asset, the ones that can
  take them first. One that can't is greyed and says why (a calendar package
  can't hold a task counted in operating hours, for example). Each task comes
  on every visit, or every Nth when its interval is a multiple of the
  package's; change it if you like.

Tasks already in a package, and rounds or tasks on a meter other than
operating hours, stay where they are and the pane says so. The **Packaged**
column then names each task's package; click it to open the package.

## Where a package sits

A package shows as a row in the tree **at the lowest level all its tasks sit
under**: a 50 h service with engine and deck tasks sits at the mower; one with
only engine tasks sits at the engine. Its tasks are listed under it (each says
which position it's on), and they still show under their own positions too,
their **Packaged** cell naming the package. Where it sits is worked out from
its tasks each time, so adding a task to it, or taking one out, moves it to the
new meeting point. A package with none of its tasks on this asset yet sits
where it was made. Only the asset you opened is shown: a package that also
holds tasks on another asset says how many, and never shows them.

## Forecasts under a task and a package

Each task and each package has a **Forecast** row under it. Open it: its lines
say when it's next due (a package: its next visit), how many times it comes in
each month, the labour, the **Parts and spares** it uses (from what its LSA
names) and what it costs, with the total over the next year. **Open the full
forecast…** on that row opens the forecast for the level it sits at.

**Forecast…** on a position's **…** runs the forecast for that level and
everything inside it (the work, the expected failures and the costs to come,
by month, quarter or year) in the table area, with the tree still beside it,
and the **spares for the year** under it: what failures and tasks there will
use, against stock and lead time. On a location, and on a product's design,
it's the spares for the year alone, under **Forecast…**.

## Say what a task needs

Open a task (double-click its row, or choose **Open…** from its **⋯**). Its
details have a **What it needs** section, folded to one line of totals (the
labour hours, people and materials cost) until you choose **Show**. Opened, it
lists the failure modes the task serves, then a group for each thing it needs.
There is no Save of its own: change what you like and use the details' **Save**
at the foot, which saves the task and what it needs together:

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

To take the tasks into a spreadsheet, choose **Export CSV** from the heading's
**More actions (…)**: every task here and below, with the labour, tools,
spares and consumables named.

## Packages by operating hours

Tasks counted in **operating hours** make a package by hours, such as a 50 h
service: select them together (not with calendar tasks). The visit goes by the
shortest interval, and a task at a whole multiple of it goes on every Nth
visit, so a 100 h oil change comes on every second 50 h service. The package
counts from the position's hour meter reading now, and its page shows each
visit's hours and the date it's expected, from the operating plan (else the
meter's recent rate; with neither, running all the time, 24 hours a day, and
it says so, with a link to set a duty). It needs an hour meter on its position.

## Let Reliafy draft the packages

Right-click a position in the tree (or press its **⋯**), or open the heading's
**More actions (…)**, and choose **Package the tasks…**. The drafts open in the
table area. It groups every task there and below that isn't in a package by
how often it's due and by trade: the weekly ones visit on the day you pick,
and monthly and longer ones become layers on those visits (the first of that
day in the month). Untick or rename the drafts, then **Make** them, all together
or none.

## Look after a package

Click a package's row (or a task's **Packaged** cell) to open it beside the
table. A product's design has no packages: they belong to the built items. You
see where it sits and why, its tasks, each with where it
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
  spares each task uses also count in the **spares for the year** under a
  level's **Forecast…**, against stock and lead time.
