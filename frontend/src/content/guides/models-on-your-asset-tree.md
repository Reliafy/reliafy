---
title: "Put life models on your asset tree"
task: "How do I attach a life model to a position, fit one from its history (or its class's), with a prior when failures are few, and use it in the RCM?"
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

The heading's **…** (and a position's **⋯**) has three groups, **Life
model**, **RBD** and **Prediction**; point at one (or press →) to see its
items. Under **Life model**:

- **Fit a life model…** fits a life distribution to history. Choose the
  **data**: this position's own history (each item's days in service, ended
  by a failure or still running), its class's pooled history (every position
  of the class: the dialog says how many, with their failures and
  suspensions), or **both**: this position's history, with the class's other
  positions' history as a prior. Choose the **method**: a plain fit (the
  numbers that make the data most likely, with 95% confidence bounds) or
  **with a prior** (what you already believed, moved by the data, with 90%
  credible intervals). The prior can be the class's history, a saved model,
  numbers you know or a B10 you believe, and you say how much to trust it
  (the class's history then counts as all, half or a fifth of its
  evidence). The class's history can't be both the data and the prior. Tick
  the failure modes it's for; failures by other modes count as still running.
- **Assign a saved model…** links a model from your library, or a sample.
- **From the class…** links the model fitted to the position's class.
- **Enter parameters…** saves a model from numbers you have (a data sheet, a
  handbook) and attaches it.
- **From the data library…** attaches a published failure rate (Models ›
  Library): an exponential at the record's mean rate per hour, with the
  source's 5–95% range as its interval. The row's source reads, for example,
  "Library: NRC/INL 2020, Motor-operated valve spurious operation
  (INL/EXT-21-65055, Table 1, p. 6)", and the record stays cited. A probability per demand can't be a
  life model, and the dialog says why.

A row's **⋯** has **Refit…** (a fitted model), **Replace with…** and
**Unlink…**. Unlinking takes it off the position; the model stays in Models.

A product's design carries models too. An item built from the product takes
its design's models when it's built, as it takes the RCM.

## Accelerated-life and covariate models

An accelerated-life model (how life shortens with temperature, voltage or
load) or a covariate model such as proportional hazards attaches like any
saved model: pick it under **Accelerated life** or **Non-repairable** in
**Assign a saved model…**. Its row shows the model as it was fitted: the life
at its lowest tested stress, or at the average covariates of its data. The
stress at this position isn't set here: it's set where the model is used, in
an RBD block or a calculation.

## Predict the failure rate from the parts list

Reliability predictions live here, on the position they're for.
**Prediction › Add a prediction (parts count)…** works
out a parts count from the position's parts list and those of the positions
inside it (on a product's design, its bill of materials where they list
none). Set the environment once, the place the equipment works; the next
prediction below it starts from the same one. Give each part a handbook part
type (and a quality factor where the handbook has one): each part's rate is
its base rate times the factors, and the rates add up as if every part were
needed. The handbook covers electronic parts only: tick **Not electronic** on
a mechanical part (an airframe, a propeller) to leave it out, and give a part
it doesn't have (a battery) a rate of your own. The result is a failure rate
and an MTBF, with each part's share, and it names what was left out.

Saved, it's a row of kind **Prediction**, an exponential model at the
predicted rate, so the RCM, the calculators and RBDs can use it, and it's on
the **Reliability prediction** page too, with **Open on the asset** back to
the position. **Refresh the prediction…** works it out again from the parts
list as it is now, keeping the part types. An item built from a product takes
its design's prediction. A parts count compares designs early: it doesn't say
how the item will fail in service, so replace it with a fitted model once
there are failures.

## An RBD for a position made of others

Every position can have a life model, an RBD or a prediction. For a system
made of the positions inside it, **RBD › Build from what's inside…** makes a
reliability block diagram (under Design › Systems) whose blocks are the
positions one level down, each taking its model in use (a position with its
own RBD comes in as a sub-system). They're wired by their connections and
redundancy groups, in series where there are none. A position with no model
gets a placeholder, flagged: the row warns until each has a model. **RBD › Link an
existing RBD…** links one you've already drawn.

The RBD row shows the system's MTBF and B10, and its panel lists every block
with its model and the position it came from; type an age to see the
system's reliability there. **Open the RBD** edits the diagram;
**Rebuild from what's inside…** adds positions added since, keeping your edits.

## The model in use

When a position has more than one row (say its own life model and an RBD), one
is marked **In use**: by default its own life model, else its RBD, else its
prediction. **Use this one** on a row's ⋯ changes it. The model in use is what
the position's row reports, what the RCM offers first as evidence, and what a
parent's RBD takes for its block.

## A few failures: fit with a prior

With one or two failures a position's own history says little. But there's
often something you'd trust beside it: the class's other positions, the
vendor's numbers, a handbook model, or a belief such as "the B10 is about
5,000 hours". In **Fit a life model…**, choose **With a prior** (or **Both**,
for the class's history as the prior) and the position's own failures and
running units move that prior.

1. Choose the **prior**: the class's history, a saved model, a library
   record, numbers you know, or a B10 you believe. A **library record**'s
   gamma on the rate is the prior exactly for an exponential (the update is
   then exact, in closed form); for a Weibull or lognormal the rate becomes a
   prior on the mean life, with the shape between bounds you set (0.5 to 5
   unless you change them).
2. Choose **how much to trust it**:
   - *Trust it closely*: each number within about 10%, or all of the class's
     (or a fitted model's) evidence;
   - *Use it as a guide*: within about 30%, or half of it;
   - *Only a starting point*: within about 60%, or a fifth of it.
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
