---
title: "See what's due, open work orders and close them"
task: "How do I see the maintenance due soon, raise work orders, and record what was done when the work is finished?"
category: "Maintenance strategy"
prerequisites: "A position in your asset tree with some tasks on it (from its RCM decisions, or added by hand)."
order: 28
# Reliafy Maintenance is operators-only for now: this guide is linked from the
# Maintenance pages themselves and stays out of the index until Maintenance opens.
hidden: true
---

**Maintenance** opens on **Orders**, where the work is run. The RCM on your
asset tree says what should be done and how often; Orders shows what that means
in practice, and the work orders that carry it out. **Packages**, beside it,
lists the work packages: tasks done together on one visit.

The line above the tabs gives the answer first: how many work orders are open,
how many are late, and how much is due soon.

## Open work orders

The **Open** tab lists what's still to do. Anything overdue comes first, the
latest at the top, with how many days late it is. The rest follow by due date.
A work order from a package shows how many of its lines are answered so far.

Pick a location to see only the work there and in the places inside it, or a
kind to see only the work raised by tasks, by packages or added by hand. Type
in the search box to find one by its number, title or what it's on.

## What's due

**Due soon** lists every scheduled task coming due in the next 7, 30 or 90
days: the task, what it's on (a position, an item or a location), when it's
due, and its work order if it has one. Tasks in a package are grouped under it;
the rest come last, under "Not in a package".

**Create N work orders** raises what's missing in one click, and says what it
will make: one work order for each package visit, and one for each task that
isn't in a package.

## Open a work order

Use **New work order** at the top of the page for work nobody scheduled:
something broke, or someone noticed a problem. Choose the position, say in a
few words what needs doing, pick the type (corrective, preventive, inspection
or other) and, if you know it, when it's due. You can also open one from a
position's own page.

A spreadsheet of past work (one row per item per position, with when it was
fitted, removed or failed) goes in with **Import from a spreadsheet**. Every
row is checked first; if any row is wrong, nothing is imported.

## Close it: say what was done

On a work order, **Close it** asks what was done. It starts from the task the
work order came from:

- a check (an on-condition task, a failure-finding test, or a task that asks
  for a reading) starts at **Checked, nothing done**;
- a fixed-interval task starts at **Replaced it**;
- work with no task starts at a replacement on a position, or a repair
  elsewhere.

Change it to what really happened: **Replaced it**, **Repaired it**,
**Inspected it** (with what you found: OK, degraded or found failed) or
**Other work**. Only a replacement asks for the new item and whether the old
one failed, and it ends the old item's time at the position. Add another
action when you did more than one thing. Values filled in under **Readings and
settings** are recorded when you close it.

## Look back: closed work orders

The **Closed** tab holds every closed and cancelled work order, newest first,
with what was done on each. Search it by number, title, notes or what it was
on.

## Packages

**Packages** lists each work package with what it's on, its timing in words
("every Saturday"), its next visit (or its open visit, marked when late), how
many tasks it holds and whether it's active or paused. Open one to see its
tasks, its next visits and its recent work orders. Packages are made from the
tasks on the Explorer's LSA tab: tick the tasks, then package them.

## Dates follow your time zone

"Today", due dates and overdue are worked out in the workspace's time zone.
Until one is set, they follow UTC. When your device is somewhere else, the page
offers to use your device's time zone in one click, or you can choose one on
**Settings**.
