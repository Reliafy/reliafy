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
