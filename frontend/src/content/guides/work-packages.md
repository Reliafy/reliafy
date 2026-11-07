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
**Packages** tab. It lists the packages planned there and inside it, and any
package that holds a task there, each with its layers indented under it:

- how often it visits ("Every Saturday", "The first Saturday of every month");
- its trade and how many tasks it holds;
- the next visit, or the work order open for it;
- **Late by N days** when a visit is past its tolerance (how many days after
  the date still counts as on time), and **Paused** with the return date.

Late packages come first, then the soonest visit.

## Package the tasks

From the panel's **More actions (…)**, choose **Package the tasks…** (the empty
tab has the same link). Reliafy reads the tasks here and below that aren't in
a package yet and groups them by how often they're due and by trade:

- the weekly tasks become a package that visits on the day you pick;
- monthly and longer tasks become layers on it (the first Saturday of the
  month, of every third month, of every twelfth month);
- a cadence that can't fall on those visits (a monthly task with only a
  fortnightly package) becomes a package of its own.

Untick any you don't want (unticking a package unticks its layers), rename
them, set how many days after the visit is still on time, and choose **Make**.
They're all made together, or none are.

Tasks on an item (they follow the serial number), tasks counted by use (run
hours) and rounds stay on their own; the dialog lists them and says why.

To make one by hand, choose **Add a package…** and give it a name, how often
it visits and its trade, then add its tasks.

## Look after a package

Click a package to open it in the tab. You see its tasks, each with where it
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
