---
title: "Spares for the year: what to hold, order and buy (Maintenance › Forecast…)"
task: "How many of each spare will we use next year, how many should we keep given how long each takes to arrive, and what do I order now and when?"
category: "Maintenance strategy"
prerequisites: "Positions with items fitted and a life model in use (their own or their class's), parts on their parts lists, and the spares each task uses set in What it needs."
order: 28
# Reliafy Maintenance is operators-only for now: this guide is linked from the
# Maintenance tab's Forecast… pane and stays out of the index until Maintenance opens.
hidden: true
---

Open the Explorer's **Maintenance** tab, then **Forecast…** in a position's
**⋯** menu (on a location, **Spares for the year…**). The table area shows the
forecast for that level and everything inside it, and under it **Spares for the
year**: one row for each part that a failure or a task uses, here and inside it:

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

For one task or one package, open its **Forecast** row in the table instead:
its **Parts and spares** line says what that task (or every task in the
package) will use over the same months, from what its LSA names.

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
  class's), from each item's age. A position with neither but a rate in a saved
  parts count (its parts at their rates there) fails at that constant rate, and
  the position's line says the rate is from the prediction. A failed item is replaced and can fail again.
  A planned replacement renews the item, so failures after it count from new. An
  item renewed on a schedule counts its age from its last replacement.
- **Hold** is the smallest stock with at least the service level's chance of
  covering the demand over the lead time.

A part on no parts list still shows if a task uses it: a diaphragm kit named on
the dosing pump's diaphragm change shows with its changes and the odd early
failure.

## The forecast counts the maintenance

The forecast above the spares, in the same pane, gives the work, failures and
costs to come here and inside it, by month. Its **Expected failures** count what the
tasks do, so two plans for the same equipment give different failures. A
ride-on mower on its maker's 25-hour plan, where the spark plugs are only
inspected (a plug gives no warning to act on), expects about 3.3 breakdowns
per 600 operating hours. On a 50-hour plan that replaces the plugs every 100
hours, it expects about 1.5.

Each life is forecast with the tasks of the failure modes it's for:

- **A fixed-interval replacement** (restoring the item as new, the default)
  is a planned replacement at its interval, from the date it next falls due.
  It's done on its dates, failed or not, and failures after it count from new.
  Where two replacements cover the same failure modes, the sooner one counts.
- **An on-condition check** counts through its warning period: the saved P-F
  calculation linked as its evidence gives the share of warnings the check
  finds in time, and the failures left are the warnings it misses. These are
  expected values only, with no 90% range yet, and the notes say so.

Some tasks don't change the failures, and each life's line in **Failures: the
life models used** says which were counted and which weren't, with why
(*not counted: Grease spindle bearings (it restores none of the item's age, so
the failures are as they would be without it)*):

- a fixed-interval task that restores none of the age (greasing a bearing)
  leaves the failures as they are;
- a partial restoration isn't counted yet;
- an on-condition check with no P-F interval linked isn't counted, because
  without it there's nothing to say how many warnings it catches;
- a task whose interval and the life are in different kinds of unit (a
  calendar task on a life in operating hours) isn't counted yet;
- failure-finding tests, redesigns and run to failure leave the failures as
  they are.

When a position's failure modes each have a life of their own, each is
forecast with its own tasks, and the position's whole-life model is listed
under **Not placed**, so no failure is counted twice.

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

On a product's design, **Spares for the year…** in a row's **⋯** menu counts the items built from it.
With none built, enter a **planned fleet size** (and hours a day for lives by
use) to size the spares for that many new units.
