---
title: "Parts that wear by running hours and by starts"
task: "How do I model a motor or turbine that wears both while it runs and every time it starts?"
category: "Life data"
prerequisites: "A dataset with one row per unit: its running hours and its number of starts at its failure (or now, if still running), and a status column. Units run at different starts per hour."
related_href: "/models/new"
related_label: "Fit a model"
order: 47
---

Some parts wear on two clocks at once. A motor, a gas turbine or a pump wears
while it runs, and every start wears it too: a start heats and stresses it the
way some hours of steady running would. Two units with the same hours aren't
equally worn if one was started ten times as often. An aircraft engine is the
same with flight hours and cycles.

Reliafy fits these lives on one combined clock, **hours plus k × starts**, and
learns **k**, what one start is worth in hours, from your failures. It then
gives the life of a unit run at any steady number of starts per hour as an
ordinary life in hours, with bounds that include how sure it is about k.

## What your data needs

One row per unit, with:

- its **running hours** at its failure, or now if it's still running;
- its **starts** (or cycles) at the same moment;
- a **status**: failed or still running, as for any life data.

Units must run at **different** starts per hour: a peaking unit beside a
base-load one, say. That difference is how Reliafy tells what a start costs.
If every unit makes the same starts per hour, the fit says so and stops.

## Fit it

1. Open **Models → Non-repairable** and choose **New model**, then **Fit to data**.
2. Pick the dataset. In its reading, give the hours column the role **x** and
   the starts column the role **starts** (under x).
3. On the **Model** step, the list now offers the models on hours and starts:
   **Weibull on hours and starts** (the usual choice), lognormal or exponential.
4. Choose **Fit**.

## Read the answer

The **Life at a rate** tab opens with the answer in plain words: what one start
costs ("one start wears it as much as 18 hours of running"), then the life at
the fleet's typical starts per hour, for example "At 1 start every 20 hours, its
B10 life is 6,290 hours (at least 5,810 hours, 90% one-sided)".

Type any other rate under **Starts per hour**: 0.125, or 1/8 for one start
every 8 hours. The B-lives, the mean life and the reliability curve with its
90% band follow.

**Model characteristics** says whether starts matter at all (a test that they
don't: a small p-value means they do), and the life at the fleet's low,
typical and high rates side by side.

## Use it

- **In a block diagram**, pick the saved model for a block and set its
  **Starts per hour**. The block is the life at that rate, and the diagram's
  90% band includes the model's own uncertainty, the worth of a start too.
- **In the Explorer**, link the model to a position. The rate comes from the
  position's **operating plan**: its runs and hours over the next 12 months
  give its starts per hour, and the panel says so. Type another rate to
  override it; **Use the operating plan's rate** goes back.
- **In Strategy and the RCM interval calculators**, a model on hours and starts
  is used at its typical rate (change it in the picker).
- **Download as Python** on the model's page gives a script that refits it with
  SurPyval and prints the same numbers.

## What it assumes

- **Steady use per unit.** Each unit is taken to have used its two clocks at a
  steady ratio over its life. A unit that changed duty a lot has the right
  totals, but its starts are spread evenly.
- **The clocks add.** A start wears the part the same whatever its age.
- Inspection ranges, late entry and covariates aren't taken.

The arithmetic is [SurPyval](https://github.com/derrynknife/SurPyval)'s
equivalent time scale.
