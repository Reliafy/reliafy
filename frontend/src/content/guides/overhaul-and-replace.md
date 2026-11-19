---
title: "Overhaul every so often, and replace after so many overhauls"
task: "How often should I overhaul a repairable unit, and after how many overhauls should I replace it instead?"
category: "Maintenance strategy"
prerequisites: "A repairable model of the unit with minimal repair (Crow-AMSAA, Duane, HPP or Cox-Lewis), saved or typed in, and what a repair, an overhaul and a replacement cost."
related_href: "/strategy/overhaul-replace"
related_label: "Open overhaul and replace"
order: 24
---

A gearbox, an engine or a pump is repaired when it fails and carries on, a
little worse each time: its failures come more often as it ages. An overhaul
takes off part of that age but doesn't make it new. A replacement does. So the
question is two numbers: **overhaul every X**, and **replace after N
overhauls**. Overhaul too rarely and you pay for repairs; too often and you pay
for overhauls. Replace too soon and you throw away a working unit; too late and
the age the overhauls leave behind piles up.

Reliafy finds the X and N with the lowest long-run cost, and puts the plan
beside the simpler ones, so you can see what each choice costs.

## Choose the model and enter the costs

Open **Decisions → Strategy → Overhaul and replace**. Under **Repairable model**,
choose **Saved model** for a model from Models › Repairable, or **Parameters**
to type in a Crow-AMSAA or Duane model's scale alpha and shape beta (with its
unit). The model must be a minimal-repair one: an imperfect-repair model can't
say how often an overhauled unit fails, so it's refused with that reason. Times
stay in the model's unit, so a model in flight hours gives an answer in flight
hours.

Then enter:

- **Repair cost, per failure**: fixing one failure.
- **Overhaul cost**: more than a repair, or you'd overhaul at every failure.
- **Replacement cost**: a new unit fitted.
- **An overhaul takes off (% of its age)**: 100% makes it as good as new; 50%
  takes off half its age. There's no default: ask whoever does the overhaul.
- **Most overhauls to search** (19 if left blank).

**Downtime (optional)** takes the hours a repair, an overhaul and a replacement
keep the unit down, and the cost of an hour down. Each event's cost then
includes its downtime. The model's clock stops while the unit is down, so
downtime adds cost, not time.

Press **Compute**.

## Read the answer

The answer is the plan in one sentence, with four figures beside it: how often
to overhaul, after how many overhauls to replace, the cost per unit of time and
the repairs expected between replacements. For a gearbox modelled as a power
law with alpha 500 and beta 2.2 flight hours, a repair at 2,000, an overhaul at
15,000 that takes off 60% of its age, and a replacement at 60,000, it says:
overhaul every **805 flight hours** and replace after **19 overhauls**.

The chart shows the cost rate against the overhaul interval for no overhauls
(replace only) and for a few numbers of overhauls, with the best plan marked.

**Against the other plans** puts the best plan beside three simpler ones,
each at its own best:

- **Run to failure**: repair each failure and replace the unit at the n-th
  failure (the best n), with no planned work.
- **Overhaul only, never replace.**
- **Replace only, no overhauls.**

Read this table before acting. The cheapest plan of another kind can beat the
best overhaul-and-replace plan, and when it does, the answer says so. In the
gearbox example, overhauling every 737 flight hours and never replacing costs
about 5% less again, because each overhaul takes off so much age that the unit
never gets old enough for a replacement to pay. A best plan at the most
overhauls searched points the same way: search more and compare.

**The best X for each number of overhauls** lists every N with its own best
interval and cost rate, and **How it's worked out** gives the method and its
assumptions.

## Save it, or work from a position

Press **Save analysis** to keep the answer. It's worked out again on the server
from the inputs, so it can be evidence for an RCM decision.

On a repairable model's own page the same tool is under **Plan ahead →
Overhaul and replace**. In the Explorer's **Models › Life models**, a model's ⋯ menu
has **Add a strategy…**: the strategy tools for that kind of model open beside
the tree, the position's class costs filled in where they're set. Once you save
one there, the model has a **Strategy** row under it.

## What it assumes

- Each failure is repaired back to how it was just before it failed (minimal
  repair), so the failure rate follows the unit's age.
- An overhaul takes off a fixed share of the unit's age; a replacement makes it
  new.
- Costs are long-run averages over many replacement cycles.
- It's exact, worked out from the model's failure intensity, so it's free.
