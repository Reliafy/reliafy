---
title: "Say how equipment runs, so tasks by hours land on dates (Explorer › Operations)"
task: "How do I tell Reliafy when a pump or a vehicle runs, so a task every 2,000 running hours, or a pattern like the first Saturday of the month, falls due on the right date, in my time zone?"
category: "Maintenance strategy"
prerequisites: "A position in your asset tree with a task on it. An hours counter helps, but isn't needed."
order: 29
# Reliafy Maintenance is operators-only for now: this guide is linked from the
# Operations pane itself and stays out of the index until Maintenance opens.
hidden: true
---

A task counted in running hours ("every 2,000 hours") has no date of its own.
Reliafy needs to know *when the equipment runs* to turn hours into a date. A
duty pump that runs around the clock reaches 2,000 hours in about 12 weeks. A
standby pump that runs two hours every Saturday takes about 19 years. The
**operating plan** is where you say which of the two you have.

## The Operations tab

In the Explorer, open an asset and pick the **Operations** tab. It shows the
tree with each position's operations beside it, one row a position:

- **Duty**: how it runs, in words (*Monday to Friday, 06:00 to 22:00 · about
  80 hours a week*), or *All the time (no duty set)*.
- **From**: *Own* when the duty is set on the position, or *From Site A* when it
  runs to the duty of a position above it.
- **Other use**: distance or counts a day (*400 km a day*), if any.
- **Shutdowns and outages**: the next window that takes it off-line, its own
  or one set above it, and how many more in the year ahead.
- **Time zone**: the zone the duty's clock times are in.

A position with no duty of its own runs to the nearest position above it that
has one, inside the asset you opened. So set the duty once, at the site or the
line, and every position below it takes it. To run one differently, give it
its own: that position, and the ones below it, use that instead. An item runs
as the position it's fitted to, so you set the duty on the position, never on
the item.

Click a position to open its **Operations** beside the table: its operating
plan, then its shutdowns and outages. A position's **Summary** keeps one line
about how it runs, with **Open in Operations**. Older links to a position's
operating plan open here too.

## Say how it runs

Under **It runs**, pick the kind that fits how the position really works:

- **Repeating week**: the same clock times every week, on the days you tick.
  Tick the days, then set a start and a stop. **+ Add a shift** adds another,
  for a short Saturday morning, say. A stop before the start ends the next
  morning, and the page says so. Two shifts can't overlap.
- **Roster**: a run of days on, then days off, over and over. Give the days on,
  the days off, the hours each day and the **First day on**. Four on and four
  off from 07:00 to 19:00 is about 42 hours a week.
- **Rate**: a rough amount of running, spread over each day: *About 3 hours a
  day*. Use it when you know the total but not the times.
- **Runs**: only the runs you list, one a line, each an on time then an off
  time (*2026-11-14 12:31, 2026-11-15 03:27*). Paste two columns from a
  spreadsheet or use **Import a CSV…**. It is off between the runs.
- **All the time**: around the clock, every day.

Under the controls, **Reads as** says what you have entered in words, so a
mistake (a stop time typed as a start) shows before you save. Beside it are
the hours in a typical week and a strip of the next two weeks, one bar a day.

Two optional parts:

- **Other use** is for use that isn't time: *About 400 km a day*, or cycles,
  or landings. A model counted in km or cycles meets the calendar through it.
  Hours and starts come from how it runs, so they are not entered here.
- **Set runs first (optional)** takes the runs you already know about, such as
  today's and tomorrow's. From the start of the first run's day to the end of
  the last, they are all the running there is. Then the plan you picked takes
  over with no gap, and no hours appear or vanish at the handover.

Set **From** (the date the plan starts) and, if you like, a **Name** (*Day
shifts*), then press **Save**. A new plan from a date ends the one before it
from that date. Nothing earlier is rewritten, and **Its own plans** keeps the
history. **Change it** edits the current plan. **Give this its own plan**
starts one on a position that takes its duty from above. **Clear (use Site
A's)** ends a position's own plan, and it runs to the duty above it again (with
nothing above, **Clear (run all the time)**). Set the **Time zone** if the
position isn't in the workspace's.

## Shutdowns and outages

Under the plan, **Shutdowns and outages** lists every window in the year ahead
that takes the position off-line, each saying where it's set:

- a **shutdown** is a work package made into a shutdown on the Maintenance tab
  (*Annual shut · 1 Mar 2027, 72 h*, with its cost each time). It takes its
  position, or the positions you chose inside it, off-line, so every position
  below shows it too. **Open the package** goes to it.
- an **outage** is a planned spell out of service: **Plan an outage…** takes a
  start date, an optional return date and why. Its tasks, and those of
  everything inside it, aren't due meanwhile. **Back in service…** ends it.

## Plan against actual

If the position has an hours counter, the pane compares the last 90 days of
the counter with the plan: *it ran about 82% of the planned hours*. If they
differ, it offers **Use 82%**. That saves the same plan with only that share of
the planned hours counted. It is never saved unasked.

## How hours become dates

For a task every 2,000 operating hours, Reliafy works out when the position
reaches the next multiple:

1. If the position has an hours counter with a reading, it starts from the
   latest reading and goes forward through the plan.
2. If it has a plan but no reading, it counts hours from the plan alone.
3. With no plan but a counter that has two readings at least a day apart, it
   uses the counter's recent rate.

Under the task's **How often**, a line says which it used and when the next one
falls due (*Due by use at 14:00 on 12 Feb 2027 ... Hours from the operating
plan*). If there is nothing to go on, the line says what is missing: say how it
runs, or record an hours reading.

### A position with no plan

Where a position has no plan above it either, and no readings, Reliafy does not
guess a date for a task in operating hours: the forecast lists it under **Left
out** and says *Say how this runs (an operating plan), or record an hours
reading, to put the tasks by use on dates.* Where it needs an age for a position that has no counter (for an RBD, or a
life in hours), it assumes the position runs all the time since it was fitted,
and says so in words (*running all the time since it was fitted (no counter or
duty): check it*). That is the longest the age can be, so check it.

## How often

Every task and every work package has the same **How often** control. It reads
as a sentence:

- *Every 1 month on the first Saturday*
- *Every 1 year on the first Tuesday of November*
- *Every 2,000 operating hours*
- *or every 6 months, whichever comes first* (a task's second limit)

Pick days, weeks, months or years, and for weeks and months the day: a weekday,
which one in the month (the first to the fifth, or the last) or a date. A fifth
Saturday exists in only some months, and the rest are skipped. Under the
sentence it always shows the next dates, so a wrong rule shows before you save
it. Where work management is off, a task has an optional **Last done**, so
the next date counts from then.

A task counted in operating hours falls due through the operating plan as
above. "Every 2,000 hours or every 6 months, whichever comes first" falls due at
the sooner of the two.

## The time zone

Plans are clock times at the site, and "today" is the site's today. A plan can
have its own **Time zone** (a site in another state); otherwise it uses the
workspace's. Set the workspace's time zone in **Settings › Time zone** (a team's is on its **Team** page, set by
the owner). Not set, dates follow UTC: a day ends at midnight UTC, not where
you are. Maintenance shows a line with **Use** (your device's zone) while the
zone isn't set and your device isn't on UTC.

Once saved, the hours are worked out in that zone with daylight saving
counted. The preview before you save is a quick one in plain clock hours.

## Where to go next

The dates feed the forecasts: the **Forecast** view of the **Maintenance** tab
gives the work, failures and costs by month, and says where its hours came from.
