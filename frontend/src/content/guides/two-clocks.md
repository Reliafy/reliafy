---
title: "Parts that wear by two measures of use, such as hours and starts"
task: "How do I model a part that wears both while it runs and every time it starts, lands or cycles?"
category: "Life data"
prerequisites: "A dataset with one row per unit: its first measure of use (running hours, say) and its second (starts, cycles, landings...) at its failure (or now, if still running), and a status column. Units used at different rates."
related_href: "/models/new"
related_label: "Fit a model"
order: 47
---

Some parts wear on two clocks at once. A motor or a gas turbine wears while it
runs, and every start wears it too. An aircraft part wears by flight hours and
by landings; a press by hours and by cycles; a vehicle part by hours and by
kilometres. Two units with the same hours aren't equally worn if one made ten
times as many starts (or landings, or cycles).

Reliafy fits these lives on one combined clock, **first clock plus k × second
clock**, and learns **k**, what one unit of the second clock is worth on the
first (one landing in flight hours, say), from your failures. It then gives the
life of a unit used at any steady rate, such as 1 landing every 3 flight hours,
as an ordinary life on the first clock, with bounds that include how sure it is
about k.

Every sentence uses your units: "One landing wears it as much as 4.2 flight
hours", "Landings per flight hour".

## What your data needs

One row per unit, with:

- its **first clock** (running hours, say) at its failure, or now if it's still
  running;
- its **second clock** (starts, cycles, landings, shots, km) at the same moment;
- a **status**: failed or still running, as for any life data.

Units must be used at **different** rates: a peaking unit beside a base-load
one, say. That difference is how Reliafy tells what the second clock costs. If
every unit has the same rate, the fit says so and stops.

## Fit it

1. Open **Models → Non-repairable** and choose **New model**, then **Fit to data**.
2. Pick the dataset. In its reading, give the first clock's column the role
   **x**. Open **More columns** and give the second clock's column the role
   **second clock**. Its **unit** fills in from the column's name ("Landings"
   gives landings); type your own if it's wrong.
3. On the **Model** step, the list now offers the models on two clocks:
   **Weibull on two clocks** (the usual choice), lognormal or exponential.
4. Choose **Fit**.

## Read the answer

The **Life at a rate** tab opens with the answer in plain words: what one unit
of the second clock costs ("One cycle wears it as much as 18.4 hours"), then the
life at the fleet's typical rate, for example "At 1 cycle every 20 hours, its
B10 life is 6,290 hours (at least 5,810 hours, 90% one-sided)".

Type any other rate in the rate box (it is named in your units, such as
**Cycles per hour**): 0.125, or 1/8 for one every 8 hours. The B-lives, the mean
life and the reliability curve with its 90% band follow.

**Model characteristics** says whether the second clock matters at all (a test
that it doesn't: a small p-value means it does), and the life at the fleet's
low, typical and high rates side by side.

## Use it

- **In a block diagram**, pick the saved model for a block and set its rate.
  The block is the life at that rate, and the diagram's 90% band includes the
  model's own uncertainty, the worth of the second clock too.
- **In the Explorer**, link the model to a position.
  - When the second clock is **starts** or **runs**, the rate comes from the
    position's **operating plan**: its runs and hours over the next 12 months
    give its starts per hour, and the panel says so.
  - For any other unit (landings, cycles), the plan can't know it: it counts
    runs, not landings. The panel says so and uses the fleet's typical rate
    until you type this position's own.
  - Type a rate to override either; the button beside it goes back.
- **In Strategy and the RCM interval calculators**, a model on two clocks is
  used at its typical rate (change it in the picker).
- **Download as Python** on the model's page gives a script that refits it with
  SurPyval and prints the same numbers.

## What it assumes

- **Steady use per unit.** Each unit is taken to have used its two clocks at a
  steady ratio over its life. A unit that changed duty a lot has the right
  totals, but its second clock is spread evenly.
- **The clocks add.** One start (or landing, or cycle) wears the part the same
  whatever its age.
- Inspection ranges, late entry and covariates aren't taken.

The arithmetic is [SurPyval](https://github.com/derrynknife/SurPyval)'s
equivalent time scale.
