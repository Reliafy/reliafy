---
title: "Missions: what will happen"
task: "How do I set up a mission on an asset (a 10-hour sortie or a year of use) and see the chance it completes and the failures to expect?"
category: "Maintenance strategy"
prerequisites: "A position with a model, an RBD, or positions inside it."
order: 28
# Reliafy Maintenance is operators-only for now: this guide is opened from the
# Explorer's Missions tab itself and stays out of the index until Maintenance opens.
hidden: true
---

A **mission** is a saved what-if: this system run through phases over a
stretch of time. It might be a 10-hour sortie, a summer peak, or a year of use.
Quick, one-off answers stay where the thing is (a model's Calculator, Optimise…,
the left menu's forecasts). A mission is the deliberate, detailed version you
keep and come back to. Nothing makes one for you.

## Where missions live

Open **Assets → Explorer** and choose the **Missions** tab. Pick a position,
and the tab lists every mission there and on the positions below it. Each
mission sits under the position it lives on, with its phases under it, then
each phase's covariates and node status rules. The heading counts them: "2 here
· 3 on 2 positions below".

Missions also still show under the model each runs on, on the **Models** tab.

## Make one

On a position, choose **New mission…** (in the heading, or the row's menu).
The form asks for:

- **Runs on:** a saved RBD on this position or one below it, or this
  position's own positions in series. The tree doesn't say which positions back
  each other up, so the series version says so until you rewire its RBD. Either
  way the mission gets an RBD of its own (a copy), so changing it never changes
  the original.
- **Clock:** **Operating time** or **Calendar time**.
  - **Operating time** is for a mission measured in use: a 10-flight-hour
    sortie, 500 cycles. Its length and every phase are in operating units:
    hours of operation (call them what you call them: "flight hours",
    "running hours"), or cycles or km where the models count in them. No date
    or calendar is needed; **On the calendar (optional)** puts it on the
    calendar if you want its dates.
  - **Calendar time** is for a stretch of the calendar: a summer, a year of
    use. Give a **start** (now or a date), a **length** in days, weeks, months
    or years, and its **calendar**: **Linked to Operations** uses this
    position's duty (its own, or the one from above; all the time with none),
    or give it its own duty, hours a day and days a week. The answers say how
    it converts: "12 months ≈ 2,087 operating hours at 8 h a day, 5 days a
    week". Its phases show in the same calendar unit.
- **Length:** in the clock's units. A length in cycles or km against models
  that count in hours needs a rate, and is refused with a message until it has
  one.
- **Starting state:** **New**, or **As today**, each block at its item's age
  now. A block with no age to read starts new, and the answers say which.

The mission starts with one phase covering its whole length. Add phases, give
each its covariates (a constant value, or a schedule over the phase) and say
which blocks each needs, just as in
the Missions and phases guide. The phases rule: the
mission's length is always their sum.

## The two answers

Open a mission (double-click it, or **Open** in its menu) to see two cards:

- **Chance of completing:** the chance the system gets through every phase
  without a system failure, in plain words first, on the mission's clock
  ("About 98 in 100 missions like this (10 flight hours) finish without a
  system failure"; "97.8% chance of completing a 10-flight-hour mission"). Its bound is **90% one-sided**: at
  least this chance, from the fitted models' uncertainty. A mission of several
  phases has no bound yet, and says so.
- **Failures to expect:** the part failures during the mission when each failed
  part is replaced at once with a like new one, with a **90% two-sided range**
  of outcomes ("in 90 of 100 missions like this, between 0 and 2"). The range
  comes from simulated missions, which is Pro. A mission whose phases switch
  blocks off or stand them by has no figure here yet.

Under the cards, it says what it assumed: its running time and dates, the
starting state, and that **planned maintenance isn't counted yet**. The current
maintenance plan on its positions is listed, read only.

A block with no model, or only a placeholder for one, stops both answers. They
name it: give it a model in its RBD, then open the mission again.

## Rename or delete

**Rename…** and **Delete…** are in a mission's menu. Deleting asks first; it
removes the mission and its own RBD, never the RBD it was copied from.
