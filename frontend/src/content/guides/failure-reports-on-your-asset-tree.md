---
title: "Record a failure, find its cause and check the fix worked"
task: "How do I report a failure at a position, investigate it, record the corrective action, verify it worked and close the loop?"
category: "Maintenance strategy"
prerequisites: "A position in your asset tree, or the sample truck."
order: 26
# Reliafy Maintenance is operators-only for now: this guide is linked from the
# Failure reports tab itself and stays out of the index until Maintenance opens.
hidden: true
---

A failure report records one thing that went wrong, at one position in your
asset tree, and follows it until it can't happen again. Engineers call the
whole loop FRACAS (failure reporting, analysis and corrective action system);
in Reliafy it's the **Failure reports** tab of the Explorer, and the loop has
five stages:

1. **Reported** — what happened, where, when, who found it, and how bad it was.
2. **Investigating** — what was found, and the root cause (ask *why* until the
   answer is something you can change).
3. **Corrective action** — what will be done so it doesn't happen again, by
   whom and by when.
4. **Verifying** — did it work? Reliafy checks whether the failure has come
   back at that position since.
5. **Closed** — signed off. A report that wasn't a failure, or repeats another,
   is **rejected** instead.

Every change is kept with who made it and when, so the history is the record.

## See what has failed, here and below

Open **Assets → Explorer**, pick a position in the tree and choose
the **Failure reports** tab. The list shows every report at that position and
at everything inside it, open ones first, with the level each sits at under
the row you picked. Pick a higher row to see more of the tree; pick a location
to see the reports at the positions there; pick an item to see the failures it
was involved in.

![The Explorer's Failure reports tab on the sample truck: the open reports at the truck and below it, with their stage and consequence](/guides/img/reports-01-list.png)

The chips above the list narrow it to one stage, or show everything that has
ever been reported. Search finds a report by what happened, who found it, the
failure mode or the position. The tree marks each position with the number of
open reports at it and inside it, so a branch with trouble stands out.

## Report a failure

Right-click a position in the tree (on a phone, press its **⋯** button) and
choose **Add failure report…**, or press **Add failure report** at the top of
the tab. Say what happened in a line, and add the detail if there is any. The
date is today unless you change it, and the person signed in is who found it.
The item fitted at the position is recorded with the report, so the report
still says what was there even if the item is replaced later.

Choose the consequence in the same words RCM uses (safety, environmental,
operational, non-operational, or hidden), so a report can be compared with
what the RCM expected of that failure mode. Pick the failure mode from the
position's own list, or describe a new one.

## Follow the loop

The report opens with its stage shown across the top. Each stage has a card
under the facts, and the card for the current stage is open.

![One failure report: its stage, the facts, the investigation, the corrective actions and the verification, with the repeat check](/guides/img/reports-02-report.png)

- **Investigation** — write what was found, pick a root cause category and say
  the cause in a line. The *whys* are a short list: add one each time you ask
  why, up to seven.
- **Corrective actions** — add each action with its owner and due date. If it
  becomes a work order, note the number in the work order field. Mark an
  action **Done** when it is, or **Drop** it if it isn't needed after all.
- **Verification** — say whether the action worked. Beside it Reliafy shows
  the repeat check: whether the same position has failed again since the
  action was done, and whether it was the same failure mode.
- **Close** — sign off with a note. A report can't be closed until it's
  verified, and if the verification says the fix didn't work, add another
  action and verify again, or reject the report.

A closed or rejected report can be reopened at any stage; its sign-off stays in
the history. Photos can be added to a report as they can to a work order.

## What the list tells you over time

Reports at the same position with the same failure mode are the signal that a
maintenance decision needs another look: the RCM tab shows the decision for
each failure mode, and the failure reports show whether it is holding. Use the
**Rejected** chip to find reports that turned out to be duplicates, and the
**All** chip to see the whole history of a position before you change its
strategy.
