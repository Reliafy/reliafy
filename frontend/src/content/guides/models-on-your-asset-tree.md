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

- **Fit a life model…** fits a life distribution to history. It opens in
  the table's place, the tree still beside it; **×** or Esc takes you back
  to the table. Choose the
  **data**: this position's own history (each item's days in service, ended
  by a failure or still running), its class's pooled history (every position
  of the class: it says how many, with their failures and
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
- **From the data library…** attaches a published record (Models ›
  Library). Every input a record needs before it gives a rate is one of its
  **covariates**, and they open in **Fix covariates** beside the tree: a
  pipe's length, the clock (calendar hours or hours of running, and the
  running hours a year to change it), the demands a year for a probability
  per demand, a handbook part's environment and quality grade. Fix them all
  and it's an exponential at the record's rate under them, with the source's
  5–95% range as its interval; leave some open and they're set in an RBD
  built from the tree. The row's source reads, for example, "Library: NRC/INL
  2020, Motor-operated valve spurious operation (INL/EXT-21-65055, Table 1,
  p. 6)", and the record stays cited. A library life model of your own is
  attached as it is.

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
**Covariate models at a position.** A data library record or an NSWC-11
covariate model (from **Life model › From the data library…**), an
accelerated life model or a proportional-hazards model opens **Fix
covariates** beside the tree. Each covariate is grouped Design, Use or
Environment, with **Fix at this position** and a value. Design inputs start
ticked for a library record (a pipe's length, a part's quality grade); an accelerated
life model's stresses and a covariate model's covariates start open, and you
say what each one is. What you leave open is set where the model is used: in
an RBD built from the tree, on each block, or once for the whole diagram under
the calculator's **Covariates…** (its Use and Environment values, which every
block with a covariate of that name and unit takes unless it sets its own).
Until every block has its values, the calculator says which blocks need what.
Fix every covariate and it's a constant-rate model at that position. Change
them later with **Fix covariates at this position…** on the row's ⋯ menu.

**Prediction › Add a prediction (parts count)…** works
out a parts count from the position's parts list and those of the positions
inside it. On a product's design it also counts the parts of the bill of
materials that aren't on a parts list, so a part you add never takes the
other lines away; a part on both is counted once, from the parts lists. Set the environment once, the place the equipment works; the next
prediction below it starts from the same one. Give each part a handbook part
type (and a quality factor where the handbook has one): each part's rate is
its base rate times the factors, and the rates add up as if every part were
needed. A mechanical part (a bearing, a seal, a pump) takes an NSWC-11 part
type and its **Conditions…**, the conditions it works in, in place of a
quality factor. Tick **Not electronic** on a part neither handbook has (an
airframe) to leave it out, and give a part they don't have (a battery) a rate
of your own. It opens in the table area
beside the tree, the parts table across it, and the result beside the parts
updates as you go: the failure rate per million hours, the MTBF, the chance of
getting through the mission time with no failure (when you give one), and the
parts left out. **×** or Esc goes back to the table.

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
gets a placeholder, flagged: the row warns until each has a model. The diagram
opens in the RBD builder, filling the table area beside the tree, with the
whole diagram in view (a long chain is folded into rows); edit its blocks and
connections there and **Save**, just as on the diagram's own page. **×** or Esc
goes back to the table (it asks first if there are changes you haven't saved).
**RBD › Link an existing RBD…** links one you've already drawn, and opens it
the same way.

A position has one diagram built this way. Once it has one, the menu reads
**RBD › Open the RBD**, which opens it, so using the menu again never makes a
second diagram.

Blocks built from the tree are in series unless the tree says otherwise, so
the Calculator may note that like blocks ("Motor 1" to "Motor 4") are in
series. Several such notes fold into one line; open it to see each group, and
make a group redundant in the builder only if the system can run without one
of them.

The RBD row shows the system's MTBF and B10, and its panel lists every block
with its model and the position it came from; type an age to see the
system's reliability there. Double-click the row (or **Open in the pane**) to
edit the diagram beside the tree; **Open full page** opens it on its own page.
**Rebuild from what's inside…** (on the row, or under **RBD ›**) opens the
diagram and asks first; **Rebuild** then adds the positions inside that have
no block yet, keeping your edits.

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
   record, numbers you know, or a B10 you believe. A **library record** shows
   its covariates under it (a pipe's length, the clock and running hours, the
   demands a year): the prior is the record's under them, so a 200 ft pipe's
   prior is 200 times a foot's. Its gamma on the rate is the prior exactly for
   an exponential (the update is
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
attaches it; later, **Update with new failures…** on its row opens the same
fit with that model as the prior (its own prior and trust kept), adds the
failures recorded since, and saving replaces the row.

Use it when the data are sparse and the baseline is credible. With plenty of
failures, fit the history instead: the data then speak for themselves. With no
history at all the baseline stands as given.

## Risk now for a class of equipment

A [condition and life model](/guides/condition-based-risk) attached to a
position gives that position's **risk now**: the chance its fitted item fails
in the next 30, 90 and 365 days, from the item's age and its own condition
readings.

To see it for every item of a kind, arrange the
Explorer by **Classes** (beside
**Positions** and **Locations**, above the tree) and choose an item class. It
opens on its one tab, **Condition monitoring**. The table there lists every
position whose fitted item is of that class, or of a class inside it, highest
risk first: the position, its position class, the item and its serial, its
age, its last reading, the three chances and the **Median life left**. Choose
a row for that item's two charts: its survival from now and its reading's
path.

**Classes** covers one asset at a time: the one the row you have picked is in
(the place it's at, as on the **Assets** page, or else its top position), or
the asset's tree you have open. The **One tree** note shows above the tree, and
the classes, their counts and the table list the positions inside that asset
and nothing else. With nothing picked, or after **Show every asset**, it's the
whole register.

A position has the **Condition monitoring** tab too, however the tree is
arranged (**Positions**, **Locations** or **Classes**). It shows that one
position's risk now: a line in words (its age, its readings, the three
chances and the median life left), then the same two charts. The tab stays
picked as you go from a class to one of its positions, and from one position
to the next. A position with no condition and life model says so, with a link
to its **Modelling** tab; one whose model can't score it yet says what is
missing. A product's design has no such tab: nothing is fitted or read there.

Each position is scored with its own model: the condition and life model
attached to it, or else its position class's. So one class can hold positions
on different models, and positions with none. For a number, a position needs:

- **A model.** A position with none shows a dash. Attach one on its
  **Modelling** tab.
- **Readings.** A condition point on the position or its item, in the model's
  unit (mm/s for a model fitted on mm/s), with at least one reading since the
  item went into service. Readings taken on the position before that belonged
  to an earlier item and aren't used.
- **The model's covariates.** For each one, a value condition of the same name
  applied to the position (or above it), such as **Load** with the value 1.
- **A model in calendar time.** An item's age is counted in days from its
  in-service date (or the day it was first fitted), so the model's ages must
  be in days, weeks, months or years.

When one of these is missing the row says which, and what to do, in place of a
number.

## Use the models in the RCM

On the **RCM** tab, a failure mode's **Based
on: Link…** offers the position's models first, those attached for that
failure mode at the top (one attached for that mode is picked for you when
nothing is linked yet). The interval calculators on a task card start from the
decision's evidence, else from the position's model: a Weibull for a
replacement interval, a failure rate for failure finding, a degradation model
for the P-F interval.
