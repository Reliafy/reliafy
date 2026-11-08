---
title: "Put life models on your asset tree"
task: "How do I attach a life model to a position, fit one from its history or update a baseline with a few failures, and use it in the RCM?"
category: "Maintenance strategy"
prerequisites: "A position in your asset tree (or a product's design), and a saved model or some failure history."
order: 27
# Reliafy Maintenance is operators-only for now: this guide is linked from the
# Modelling tab itself and stays out of the index until Maintenance opens.
hidden: true
---

A life model on a position says how that functional location fails over time:
how long it usually lasts, whether it wears out, and how sure we are. In
Reliafy it's the **Modelling** tab of the Explorer. Each position can carry
several models, for example one for every failure there and one for a single
failure mode.

A model on a position is a **link**, not a copy. The model stays in
[Models](/models), so a refit or a rename there shows on every position that
uses it, and one model can sit on many positions.

## See the models on your tree

Open **Assets → Explorer**, pick a position and choose the **Modelling** tab.
The tree stays in the first column; under each position are the models attached
to it, before the positions inside it. Each row shows:

- **Kind**: Weibull, exponential, lognormal, repairable, degradation, or
  condition and life.
- **Source**: where it came from, such as "Fitted from this position's
  history: 7 failures, 12 suspensions", "From the class Centrifugal pump" or
  "Assigned: Bearing life".
- **Headline**: the main numbers in the model's unit, with their bounds. For a
  Weibull that's the characteristic life and the shape; for an exponential the
  MTBF; for a repairable model the failure rate now and whether it's getting
  worse.
- **Mean life** (or **B10 life**, from **Columns…**).
- **Confidence**: how much data is behind it, in one word (Rough, Fair, Good;
  Assumed for typed-in numbers; Stale when failures have been recorded since
  it was fitted).
- **Used by**: the RCM decisions that link it as evidence, and RBD blocks on it.

A position's own row sums up its models ("3 models · 1 stale"). Click a model
to see its details beside the table; double-click to spread them across it:
the reliability (or hazard) plot with its bounds, the parameters, the data
behind it and where its time starts, and what uses it. **Open in Models** goes
to the model's own page.

## Attach a model

Use the heading's **…** menu:

- **Fit from history…** fits a life distribution to the position's own
  failures: each item's days in service, ended by a failure or still running.
  With fewer than two failures of its own it pools its class's positions
  instead (or choose which). Tick the failure modes it's for; failures by
  other modes then count as still running at that age.
- **Assign a saved model…** links a model from your library, or a sample.
- **Assign from class…** links the model fitted to the position's class.
- **Update a baseline with this position's history…** is for a position with
  only one or two failures (below).

A row's **⋯** has **Refit…** (a fitted model), **Replace with…** and
**Unlink…**. Unlinking takes it off the position; the model stays in Models.

A product's design carries models too. An item built from the product takes
its design's models when it's built, as it takes the RCM.

## A few failures: update a baseline

With one or two failures a position's own history says little. But there's
often a baseline you'd trust: the class's model, the vendor's numbers, a
handbook model, or a belief such as "the B10 is about 5,000 hours". A
**Bayesian update** starts from that baseline and lets the position's own
failures and running units move it.

1. Choose what to **start from**: its class's model, a saved model, numbers you
   know, or a B10 you believe.
2. Choose **how much to trust it**:
   - *Trust it closely*: each number within about 10% (a fitted baseline
     counts as all its evidence);
   - *Use it as a guide*: within about 30% (half its evidence);
   - *Only a starting point*: within about 60% (a fifth of its evidence).
3. Check the history it will use, and untick anything that doesn't belong.

The result says first what moved and how far, for example "2 failures at 1,400
and 1,900 hours pulled the characteristic life from 3,000 hours to about 2,600
hours; the shape barely moved". Then the numbers before and after, each with
a **90% credible interval**: there's a 90% chance the value lies in it, given
the baseline and the data. The plot shows the baseline dashed and the update
with its band. **Save as this position's model** keeps it in Models and
attaches it; later, **Update with new failures…** on its row adds the
failures recorded since.

Use it when the data are sparse and the baseline is credible. With plenty of
failures, fit the history instead: the data then speak for themselves. With no
history at all the baseline stands as given.

## Use the models in the RCM

On the [RCM tab](/guides/rcm-on-your-asset-tree), a failure mode's **Based
on: Link…** offers the position's models first, those attached for that
failure mode at the top (one attached for that mode is picked for you when
nothing is linked yet). The interval calculators on a task card start from the
decision's evidence, else from the position's model: a Weibull for a
replacement interval, a failure rate for failure finding, a degradation model
for the P-F interval.
