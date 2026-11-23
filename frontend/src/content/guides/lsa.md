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
the Explorer it's part of the **Maintenance** tab: each task's details have **Labour**, **Parts** and **Tools and method**. The RCM says what is done and why; the LSA says what each task
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

Click a task to open it beside the table. Its details read top to bottom:

- **Kind of task**, then **What's done** (the action alone: *Replace the seal*).
- **How often**: one line, *Every [50] [operating hours]*, with its next dates
  and **Next due** under it. **More scheduling options** (folded) holds a second
  limit (*or every 6 months, whichever comes first*), set calendar dates, at
  planned shutdowns, and **When the item is replaced** (*Restart* or *Keep*,
  the default named). Folded with something set, it says what in one line.
- **Cost**, **Labour** and **Parts**, each folded with a line saying what's set
  (*$40 each time*, *1.5 h mechanic*, *Spindle kit × 1*).

A task from an RCM decision shows what the RCM owns in one line under its name,
*From RCM: Drive belt cracked and breaks · Check condition · Open in RCM ›*: its
failure modes, why it's done and its kind are changed on the RCM tab only. A
task added directly has its kind, **Why it's done** and the failure modes it
prevents here.

A task's labour, parts and a typed cost also show as rows under it in the tree
(*Labour · 1.5 h mechanic*, *Part · Spindle kit × 1*, *Cost · $40 each time*),
only when they're set; open the task's arrow to see them. Click one to open the
task at that part. They aren't tasks: no count includes them.

**Add task…** on a row's **More actions (…)** adds one to that position.
**Trade rates…** in the heading's **…** prices every task's labour.

### What's done if it fails, or when it's found

What's done when a failure mode happens anyway (*replace the drive belt*), and
when an inspection finds it early, are tasks too, raised by that event rather
than a schedule. They sit under their position like any other task, with the
kind **Corrective: on failure** or **Follow-on: when found**, their failure mode
named, and no **Next due**. Their details have the same parts, with the trigger
(*Raised when Drive belt cracked and breaks fails*) in place of How often. A
corrective one also has **Cost of the failure itself (besides the repair)**:
how long a failure keeps it out of use, what an hour out of use costs, or a
failure's whole cost typed (which overrides the repair's).

Add one from the heading's **…** (**Add response if it fails…** or **Add
follow-on…**, then pick the failure mode), or from a failure mode's menu on the
RCM tab. The forecast uses their hours, parts and cost for each failure (or
find) it expects; with none, it lists the gap under **Not counted**, with **Add**
opening the form here.

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
only engine tasks sits at the engine. It's one row: its tasks show under their
own positions, each one's **Packaged** cell naming the package (click it to open
the package). Open the package (click its row, or double-click it to see its
details across the table) to see its tasks listed; a task's name there picks it
in the tree. Where it sits is worked out from
its tasks each time, so adding a task to it, or taking one out, moves it to the
new meeting point. A package with none of its tasks on this asset yet sits
where it was made. Only the asset you opened is shown: a package that also
holds tasks on another asset says how many, and never shows them.

## Next due, and forecasts

The **Next due** column comes first and says when each task is next due, only
when that's known: from when it was last done, a start date set on it, or a
calendar rule. A task by running hours shows the reading it falls due at ("at
1,250 h"), with a date only when the position has a duty or measured readings;
the tooltip says what the date rests on. A task with no record shows a dash,
and its tooltip says why. A position shows the soonest next due at and below
it. Click the column's heading to sort by it: soonest first, then latest first;
blanks always come last.

There are no forecasts in the table. **Open in ›** in a position's, task's or
package's menu opens the quick **Spares**, **Hours** or **Cost forecast** in
**Decisions › Forecasts**, filled in from that row and everything below it
([Quick forecasts](/guides/forecast-tools)).

## Say what a task needs

Open a task (double-click its row, or choose **Open…** from its **⋯**). Its
**Labour** (a line per trade: how many people and the hours each, plus the
elapsed hours of the job) and **Parts** (pick a part from the parts register,
or type a name) are fold-outs of their own. The rest is in **Tools and
method**, folded to one line saying what's set. Opened, it lists the failure
modes the task serves, then a group for each other thing it needs. There is no
Save of its own: change what you like and use the details' **Save** at the
foot, which saves the task and what it needs together:

- **Tools and instruments** — tools and test equipment. An instrument can name
  the measuring point or channel it reads (the free-chlorine point for a
  photometer), so which sensor does the monitoring is part of the how, not the
  RCM decision.
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
  against the stock usable now, and when an order placed today lands. 
