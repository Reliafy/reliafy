---
title: "See what's due, open work orders and close them"
task: "How do I see the maintenance due soon, raise work orders, and record what was done when the work is finished?"
category: "Maintenance strategy"
prerequisites: "A position in your asset tree with some tasks on it (from its RCM decisions, or added by hand)."
order: 28
# Reliafy Maintenance is operators-only for now: this guide is linked from the
# Maintenance page itself and stays out of the index until Maintenance opens.
hidden: true
---

The **Maintenance** page is where the work is run. The RCM on your asset tree
says what should be done and how often; this page shows what that means for the
next month, and the work orders that carry it out.

## What's due

**Due in the next 30 days** lists every scheduled task coming due: the task,
what it's on (a position, an item or a location), when it's due, and its work
order if it has one. Type in the search box to find a task by its name or by
what it's on.

Tasks with no work order yet are counted in the button at the top of the card,
**Create N work orders**. One click raises them all.

## Open a work order

Use **New work order** at the top of the page for work nobody scheduled:
something broke, or someone noticed a problem. Choose the position, say in a
few words what needs doing, pick the type (corrective, preventive, inspection
or other) and, if you know it, when it's due. You can also open one from a
position's own page.

A spreadsheet of past work (one row per item per position, with when it was
fitted, removed or failed) goes in with **Import from a spreadsheet**. Every
row is checked first; if any row is wrong, nothing is imported.

**Open work orders** lists what's still to do. Pick a location to see only the
work there and in the places inside it.

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

## Dates follow your time zone

"Today", due dates and overdue are worked out in the workspace's time zone.
Until one is set, they follow UTC. When your device is somewhere else, the page
offers to use your device's time zone in one click, or you can choose one on
**Settings**.
