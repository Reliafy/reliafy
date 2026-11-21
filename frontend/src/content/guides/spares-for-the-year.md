---
title: "Spares for the year: what to hold, order and buy (Maintenance › Spares)"
task: "How many of each spare will we use next year, how many should we keep given how long each takes to arrive, and what do I order now and when?"
category: "Maintenance strategy"
prerequisites: "Positions with items fitted and a life model in use (their own or their class's), parts on their parts lists, and the spares each task uses set in What it needs."
order: 28
# Reliafy Maintenance is operators-only for now: this guide is linked from the
# Maintenance › Spares view itself and stays out of the index until Maintenance opens.
hidden: true
---

Open a position or location in the Explorer, then **Maintenance › Spares**. You
get one row for each part that a failure or a task uses, here and inside it:

- **Needed over 12 months**: about how many, with the likely range (10th to
  90th percentile), split into failures and planned jobs.
- **Hold**: the stock that covers the part's lead time at its service level
  (95% unless you set another on the part).
- **Usable now**: the stock in every store, counting parts that supersede it or
  are interchangeable with it, and when it was last counted. A count more than
  12 weeks old is flagged.
- **Order**: what to order now (and when it lands), and the date to order by for
  each planned job the stock left over doesn't cover.
- **Buy for the year**: the expected use rounded up, plus the hold, less what's
  usable now. The high case uses the 90th percentile instead.

**Export spares for the year (CSV)** gives the table as plain numbers for your
budget sheet. Reliafy gives quantities and dates: price them with your own
supplier prices, and raise the orders in your purchasing system.

## How the demand is worked out

Demand over a window is the planned jobs falling due in it, plus the failures in
it.

- **Planned jobs** are the tasks falling due. A task in a work package falls due
  at its visits. A shutdown task set to run "only if older than" is counted on
  the item's age at the shut, so a seal that fails just before the shut is new
  again and skipped. Tasks by use go on dates through the position's operating
  plan. Each job uses the spares its task names in **What it needs**. A
  fixed-interval replacement that names none uses what a failure there uses.
- **Failures** come from the life model in use on each position (else its
  class's), from each item's age. A failed item is replaced and can fail again.
  A planned replacement renews the item, so failures after it count from new. An
  item renewed on a schedule counts its age from its last replacement.
- **Hold** is the smallest stock with at least the service level's chance of
  covering the demand over the lead time.

A part on no parts list still shows if a task uses it: a diaphragm kit named on
the dosing pump's diaphragm change shows with its changes and the odd early
failure.

## Count the stock

On a part's page, **Stock… › Counted** records what was on the shelf on the day
it was counted. Anything received or issued after that day still stands. So if
you count 3 on Friday and one was used on Monday, enter the count with Friday's
date and the issue with Monday's. The part then says when it was last counted.

## A shutdown's parts

A work package's page lists **Parts for the visit**. For each part it shows how
many the visit needs, how many are usable now, when an order placed today
lands, and the chance the part runs out before that order arrives. That chance
counts the visit's jobs and failures wherever the part is used. Untick a job
under **Which jobs to do at this visit** to compare choices before you change
the package.

## A product not built yet

On a product's design, **Maintenance › Spares** counts the items built from it.
With none built, enter a **planned fleet size** (and hours a day for lives by
use) to size the spares for that many new units.
