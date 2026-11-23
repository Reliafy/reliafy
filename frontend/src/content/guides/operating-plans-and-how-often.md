---
title: "Say how equipment runs, so tasks by hours land on dates (Maintenance › Operating plan)"
task: "How do I tell Reliafy when a pump or a vehicle runs, so a task every 2,000 running hours, a pattern like the first Saturday of the month, or a task at the next shutdown falls due on the right date, in my time zone?"
category: "Maintenance strategy"
prerequisites: "A position in your asset tree with a task on it. An hours counter helps, but isn't needed."
order: 29
# Reliafy Maintenance is operators-only for now: this guide is linked from the
# Operating plan pane itself and stays out of the index until Maintenance opens.
hidden: true
---

A task counted in running hours ("every 2,000 hours") has no date of its own.
Reliafy needs to know *when the equipment runs* to turn hours into a date. A
duty pump that runs around the clock reaches 2,000 hours in about 12 weeks. A
standby pump that runs two hours every Saturday takes about 19 years. The
**operating plan** is where you say which of the two you have.

## Open a position's plan

In the Explorer, open a position. Its **Summary** has an **Operating plan**
line: it reads the plan in words (*Monday to Friday, 06:00 to 22:00 · about 80
hours a week*), with **Open**, or **Set one** if there is none. You can also
choose **Operating plan…** in the position's row menu. The plan opens in the
table area, with the tree still beside it.

A position with no plan of its own runs as the nearest position above it that
has one, inside the asset you opened. The plan says so (*From Pump station 1:
it has no plan of its own, so it runs as that does*) and offers **Give this its
own plan**. An item runs as the position it's fitted to, so you set the plan on
the position, never on the item.

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
history. **Change it** edits the current plan; **End this plan…** stops it, and
the position runs to the plan above it again.

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

Every task and every work package has the same **How often** control. First
pick its type, then fill a short sentence:

- **Running hours**: *Every 2,000 operating hours* (or km, or cycles). It falls
  due through the operating plan, as above.
- **Days, weeks or months**: *Every 3 months after it was last done*.
- **Calendar rule**: set dates that don't move when the work is late:
  - *On the first Saturday of every month*;
  - *On Tuesday, every 2 weeks* (every second Tuesday);
  - *On a date, day 1, of every 6 months from March*: 1 March and 1 September
    each year (every 2, 3, 4 or 6 months falls in the same months each year,
    from the month you pick);
  - *On the last day of every 3 months from March*: the last day of each
    quarter;
  - *On the first Tuesday of November, every year*.

  A fifth Saturday exists in only some months, and the rest are skipped. A day
  past a short month's end (the 31st) falls on its last day.
- **At shutdowns** (a position's task): *At the first planned shutdown 12
  months after it was last done*. The task waits for the next planned shutdown
  of its position, or of a position above it, once the time has passed. The
  shutdowns are the shutdown packages there (a package made a shutdown, with
  its set dates). With none planned, the task says so and has no date.

A task's first two types can take a second limit: *or every 6 months,
whichever comes first*. "Every 2,000 hours or every 6 months" falls due at the
sooner of the two.

Under the sentence it always shows the rule in words and its next five dates,
worked out as you choose, so a wrong rule shows before you save it. Where work
management is off, a task has an optional **Last done**, so the next date
counts from then.

On the **Maintenance** tab, the **Interval** column says the rule in words
(*The first Saturday of every month*), and each task's **Forecast** row counts
its dates over the year, whatever the type.

**Optimise…** on a task with a calendar rule gives its answer in the task's
unit, and offers two ways to use it: the plain interval, or the nearest rule
like the one it has (*every 8 weeks on Monday* in place of *every Monday*).

"The last working day of each quarter" can't be said yet: use the last day,
or the last Friday, of every 3 months.

## The time zone

Plans are clock times at the site, and "today" is the site's today. Set the
time zone in **Settings › Time zone** (a team's is on its **Team** page, set by
the owner). Not set, dates follow UTC: a day ends at midnight UTC, not where
you are. Maintenance shows a line with **Use** (your device's zone) while the
zone isn't set and your device isn't on UTC.

Once saved, the hours are worked out in that zone with daylight saving
counted. The preview before you save is a quick one in plain clock hours.

## Where to go next

The dates feed the forecasts: the **Forecast** view of the **Maintenance** tab
gives the work, failures and costs by month, and says where its hours came from.
