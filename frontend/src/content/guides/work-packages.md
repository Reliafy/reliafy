---
title: "Group the tasks done on one visit into work packages"
task: "How do I bundle the weekly, monthly and quarterly tasks of an area so each visit raises one work order?"
category: "Maintenance strategy"
prerequisites: "A position or location in your asset tree with some tasks on it (from its RCM decisions, or added by hand)."
order: 27
# Reliafy Maintenance is operators-only for now: this guide is linked from the
# Packages tab itself and stays out of the index until Maintenance opens.
hidden: true
---

A work package is the tasks done together on one visit: the weekly check of
the pool, the Saturday walk round the plant room. Each visit raises **one**
work order with a line per task, instead of one work order per task. The tasks
keep their instructions, checklists and failure modes; the package only
decides when they're done.

A package can have **layers**: a monthly check is the weekly visit plus a few
more lines on the first Saturday of the month, and a quarterly one adds more
on every third month. A layer has its own name and tasks, but its lines go on
the weekly visit's work order that day, so there's still one work order per
visit.

## See the packages here

Open **Assets → Explorer**, pick a position or a location and choose the
**Packages** tab. It's a table of every task on that row and everything
inside it, set out like the RCM table, one row per task:

- **Position** — where the task is done;
- **Failure mode** — what it prevents, with its function and functional
  failure under it;
- **Task**, **Kind** (on condition, fixed interval or failure finding; a task
  raised by an event says which), **Interval**, **Trade** and **Next due**;
- **Package** — the package it's done in, or blank when it's done on its own.

Pick a higher row in the tree to see more of it. Choose which columns show
from the panel's **More actions (…)** › **Columns…**.

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
  day of the week, the trade and how many days after the visit still count as
  on time.
- **Add to a package…** puts them in a package already on this part of the
  tree, on every visit or every Nth one.
- **Clear** unticks them.

The **Package** column fills in at once. Tasks counted by use (run hours) and
rounds stay on their own, so their boxes can't be ticked; tasks already in a
package stay where they are.

To let Reliafy draft the packages for you, choose **Package the tasks…** from
**More actions (…)**. It groups every task here that isn't in a package by
how often it's due and by trade: the weekly ones visit on the day you pick,
and monthly and longer ones become layers on those visits (the first Saturday
of the month). Untick or rename the drafts, then **Make** them, all together
or none.

## Look after a package

Click a package's name in the **Package** column to open it in the tab (**← All packages here** goes back to the table). You see its tasks, each with where it
is, its visit rule ("every visit", "every 4th visit"), what it covers and
**Owed** when it wasn't done on the last visit (it goes on the next one), and
its layers. Its **⋯** has:

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
