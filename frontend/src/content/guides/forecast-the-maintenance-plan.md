---
title: "Forecast the maintenance plan: the work, failures and cost to come"
task: "What will the plan I have set up do next year: how many tasks and labour hours, how many failures, and what will it cost? And what would change if I changed the plan?"
category: "Maintenance strategy"
prerequisites: "Positions with tasks on them and items fitted, and a life model in use on the positions whose failures you want counted. An operating plan for any task counted in running hours."
order: 30
# Reliafy Maintenance is operators-only for now: this guide stays out of the index until
# Maintenance opens.
hidden: true
---

The Explorer doesn't forecast any more (23 Nov 2026): a quick forecast is a tool
in the left menu, and a deliberate, saved one is a mission on the Models tab.

On the Explorer's **Maintenance** tab, choose **Open in ›** in a position's, a
task's or a work package's menu, then **Spares forecast**, **Hours forecast** or
**Cost forecast**. The tool in **Decisions › Forecasts** opens filled in from
that row and everything below it: the life model in use, the units and their
ages, the hours a day from the duty, and a task's interval, hours and cost. It
shows the spares, the labour hours (planned plus corrective) and the costs
(planned, corrective and spares) by period, each with its 90% two-sided range.
Nothing is saved.

See [Quick forecasts: spares, labour hours and costs](/guides/forecast-tools).

The table's **Next due** column says when each task is next due, only when
that's known: from when it was last done, a start date set on it, or a calendar
rule. A task by running hours shows the reading it falls due at ("at 1,250 h"),
with a date only when the position has a duty or measured readings. A task with
no record of when it was last done shows a dash, and its tooltip says why.

**When the item is replaced** (in a task's details, under **How often**) says
whether a new item restarts the task's schedule or not:

- **Restart the schedule** (the default for a task on its own): a new item
  fitted at the task's position, or at a position above it, counts the
  interval again from the day it went in, so **Next due** moves. Replacing one
  spindle doesn't restart the deck's greasing: only a new item at the task's
  position or above it does.
- **Keep the schedule** (the default for a calendar pattern, such as the first
  Tuesday, and for a task in a package, whose visits set its dates): it runs on
  from when it was last done, whatever is fitted.

In forecasts, a task that replaces the part follows the same setting: restart
is age replacement (a failure restarts its clock, so how many planned changes
it takes is a chance, worked out), keep is block replacement (on its dates,
failures or not). A servicing task that restarts shows its scheduled count with
a note on how many fewer replacements may make it: about the interval ÷ (2 ×
the part's mean life), half a task for each replacement.
