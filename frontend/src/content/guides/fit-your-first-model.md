---
title: "Fit your first non-repairable model from a CSV"
task: "How do I turn a spreadsheet of failure times into a fitted reliability model?"
category: "Getting started"
prerequisites: "A CSV with a column of failure times. Censored units are welcome but not required."
related_href: "/models/new"
related_label: "Fit a model"
order: 1
---

Everything else in Reliafy is built on a fitted non-repairable model, so this is the place
to start. The input is modest: a column of numbers saying how long things lasted.
The output is a distribution you can ask questions of — what fraction survive to
5,000 hours, when will 10% have failed, what's the mean life, and is this thing
wearing out or failing randomly.

## What your data needs to look like

One row per unit, and a column of times. That's the minimum:

```
hours
312
420
506
```

The units can be anything — hours, cycles, kilometres, months — as long as
you're consistent. What matters far more is the second column most real datasets
need: **censoring**.

A censored unit is one that hasn't failed yet. If you pulled 30 pumps from
service and 18 had failed while 12 were still running fine when you stopped
looking, those 12 are not "failures at the time I stopped looking" — they're
units that survived *at least* that long. Throwing them away, or worse, treating
them as failures, will make your equipment look considerably worse than it is.
Reliafy handles them properly if you tell it which is which. Any two codes will
do (you say which means what when you map the columns), but the convention is
`0` for a failure and `1` for a still-running unit:

```
hours,censored
312,0
420,0
2000,1
```

If you have interval data (the unit failed *somewhere between* two inspections),
or counts, or truncation, those are supported too — but exact times plus
censoring covers most real cases.

## Loading it in

Reliafy opens on [Home](/home): what changed, what needs attention and your
recent work, with **Start here** cards while your workspace is new. Your data
goes in once, as a dataset, and the dataset remembers how its columns are read.
Every model you build from it then asks nothing about columns.

Upload it under [Data](/data) → **New dataset**: drop a CSV or Excel file (for
a workbook, choose the sheet and the header row), or **Paste or type the
data**. Reliafy shows the first rows, then asks once how the columns are read.

### How the columns are read

One selector for each thing a model can use, labelled with SurPyval's name for
it and a few plain words. Reliafy fills them in from the column names and
values, so for most files you only check them.

- **x**: *the value when it failed or was removed*. Required: every model is
  built on it. It needn't be time: days, operating hours, cycles, kilometres,
  volts or a load all work. Beside it, the **unit** (pick one or type your
  own; guessed from the column name where it can be), or **no unit** if the
  values really have none. The unit flows through to every chart and result.
- **where x is blank, a range: xl to xr**: for failures found at an
  inspection. **xl** is the last value the unit was seen working, **xr** the
  value it was found failed (blank **xr**: still running). Map only the range
  when every row is one. Map **x** as well when some rows have an exact value
  and others only a range: each row is read on its own.
- **c**: *failed or still running*, `0` = failed and `1` = still running.
  Required too: pick the column, or tick **No status column: every row
  failed**, because without it a model can't tell failures from units still
  running. If your column uses `1` for a failure, tick **my column uses 1 =
  failed**. A column of words (*Failed*, *Running*) is read for you, and the
  line under **c** shows how (*Failed → 0, Running → 1*), with a switch to
  flip any one.
- **n**: *how many units the row stands for*, if one row represents several
  identical units.
- **tl**: *late entry, observed only from this value*, for units already in
  service when records began (*Entered at (h)*).
- **tr**: *observed only up to this value*, when records stop (*Observed
  until*). Same unit as **x**; a blank cell is no limit on that row.
- **i**: *which item each row belongs to* (a tag, a serial). Optional: a
  repairable model, readings and rows that follow an item over time need it.
- **m**: *a measured value*, for readings (wear, vibration), with its unit.
- **failure mode**: when units fail in more than one way, each mode is a
  competing risk (see [competing risks](/guides/competing-risks)).
- **s**: *the state the unit was in during this row*, for data that moves
  between several states. Optional; it is kept with the dataset for later.
- **Z**, the covariates: every column not used above, such as a load, a site
  or a duty. A plain life model ignores them; a regression offers them. Columns
  that are rarely covariates start as **not used**, greyed, each with why (*an
  id*, *a date*, *free text*, *one value*), and one tap includes any of them.
  A line sums it up: *Z: Load, Site, Duty (3 covariates) · not used: Remarks,
  Commissioning date*. Give a covariate a unit if you like.

Anything that needs settling is said beside the selector it concerns, and when
**Create dataset** is greyed the reason is beside it. Blank rows are skipped.

If your file has no header row, tick **No header row**: Reliafy names the
columns `col 1`, `col 2`, … so the first row stays data.

A dataset can also carry **measurements**: readings taken on the same units
over time, one row per reading. They sit beside the life data on the
dataset's page, on its **Measurements** tab, and feed a
[condition and life model](/guides/condition-based-risk).

### One sheet, several datasets

A sheet often holds more than one kind of thing: transformers, coal mills and
boiler feed pumps, each row naming its class in a column. Once the file is
chosen, pick that column in **Split into datasets by**. Each value becomes its
own dataset, named by the value (*Transformer*, *Coal mill*). If you already
have a dataset with that name, the file's name is added (*Transformer – plant*).

- Before anything is saved, the box lists what it will make, with each
  dataset's rows: *Transformer · 24 rows*.
- Rows with no value in that column are left out, and the box says how many.
- The column itself isn't kept: every row of a dataset holds the same value.
- The one reading you set applies to every dataset the split makes.
- On the Free plan every saved dataset counts towards the limit; if they won't
  all fit, the box says how many more you can save, and nothing is saved.
- **Save 3 datasets** saves them all at once, then lists them with a link to
  each.

Over the API and MCP, `change dataset_upload` takes `dataset_col`, and the
reading as `x_col`, `c_col`, … `z_cols`; columns you don't name are guessed,
and the answer says how they were read.

## Building the model

Go to **Modelling → Models → Non-repairable**, press **New model** and choose
**Fit to data**. The fit runs in three steps: **Source**, **Model** and
**Result**. The source step asks where the data comes from:

- **Saved data** lists every dataset you've saved (yours first, then the
  samples), with its rows, what it holds and when it was added. Pick one to
  see its first rows and how its columns are read. Datasets that hold other
  kinds of data (repeated failures of the same units, or readings alone) are
  greyed out, with what to fit them with instead.
- **Paste or type** takes a column of times, with an optional 0/1 status
  column.
- **Upload a file** takes a CSV or Excel file.

Pasted values and a new file are saved as a dataset first, through the same
**New dataset** screen, so they're read the same way; then the fit goes on.

![The new-model flow: pick a saved dataset, see its first rows and how its columns are read](/guides/img/fit-01-new.png)

The **Model** step opens with the dataset's reading in one line, for example
*x = Age (hours) · c = Status · i = Tag · failure mode = Mode · Z: Load, Site*,
with the failures and units still running counted under it. Roles this model
doesn't use are shown quieter. **Change** opens the same selectors as the
upload: what you keep there is saved with the dataset and used by every later
model. Models already made keep the reading they were fitted with, so a refit
gives the same answer.

![The Model step: how the dataset's columns are read, in one line, with Change](/guides/img/fit-04-data-step.png)

A dataset saved before readings existed is read the way its last model read
it, or guessed, and the line says *guessed — check it*: press **Looks right**
(or **Change**) once, and the reading is kept.

If the dataset has covariates (Z), choose **Life model, no covariates** or
**Regression on Z**: a regression starts with every covariate ticked; untick
any you don't want (see [covariates](/guides/covariates-and-regression)). When
the rows follow each item over time (start and stop rows), a regression fits
the covariates over time, and a life model reads one life per item: its last
time and its status then.

## Choosing a distribution

Then, still in the **Model** step, pick the model. Weibull is the default. If you
don't know which distribution you want — and often you genuinely don't — choose
**Best fit (auto)** and Reliafy will fit every candidate
and keep the one with the lowest AIC, showing you the full ranking so you can
see how close the runners-up were. **Rank by** changes the score: **AICc** for
few failures (under about 40), **BIC** to favour simpler distributions, or the
negative log-likelihood, which charges nothing for extra parameters and so
always leans to the most flexible. The ranking shows each candidate's number of
parameters and how far it is behind the best; **within 2, the data can't tell
them apart**, so prefer the one with fewer parameters. Distributions that can't
be fitted to your data (a negative time, say) are skipped, and the ranking says
which and why. Reliafy also warns when a three-parameter winner rests on very
few failures.

If you do want to choose: **Weibull** is the workhorse and handles wear-out,
infant mortality and random failure through its shape parameter. **Exponential**
assumes a constant failure rate — simple, and right more rarely than people
assume. **Lognormal** suits repair times and fatigue. There's also a full set of
discrete distributions for cycles-to-failure data, non-parametric estimators
(Kaplan-Meier and friends) when you don't want to assume a shape at all, and
regression models when failure depends on covariates like temperature or load.

## A few failures: fit with a prior

With only a few failures, the data alone says little. Often you already trust
something else: a model you saved earlier, a record in the data library, the
vendor's numbers, or a belief such as "the B10 is about 5,000 hours". In the
**Model** step, set **Method** to **With a prior**. Your failures and running
units then move that prior.

1. Choose the **prior**: a saved model, a library record (picked from the
   library search), numbers you know, a range ("around a value, between two
   bounds") or a B10 you believe. Typed numbers are in your data's unit, shown
   beside them.
2. For a saved model or typed numbers, choose **how much to trust it**: *Trust
   it closely* (each number within about 10%), *Use it as a guide* (about 30%)
   or *Only a starting point* (about 60%).
3. Press **Fit with the prior**.

The result says what moved and how far. The chart shows the prior as a dashed
line under the fitted curve, with its 90% credible band. The table puts the
prior's numbers beside the fitted ones. A credible interval means there's a 90%
chance the value lies in it, given the prior and the data. It isn't a
confidence bound. Save it like any other model. It keeps its prior: what the
prior was and how far it was trusted.

A fit with a prior takes one time column and a status column. Counts,
interval times, truncation, covariates and failure-mode columns are for a plain
fit.

## Reading the fit

The answer comes first, in one line under the model's name: the failure
pattern, the shape β with its interval, the B10 life with its lower bound, the
mean life and the data. Under it are five tabs, each fitting on the screen:
**Probability plot**, **Calculator**, **Model characteristics**,
**Diagnostics** and **Data**. **Use this model**, top right, opens a list of the
tools that take this model: a replacement interval, a fleet forecast, a
demonstration test and a block in an RBD, each with a line on what you get
there.

The panel beside the probability plot has:

- **Parameters** — each fitted parameter with its 90% interval, the number of
  observations, and **Fit statistics** (the AIC, which opens the Diagnostics
  tab).
- **Failure pattern** — what the fit means in a word: for a Weibull, wear-out,
  early-life failures or random failures, judged on β's interval. Click it for
  the reading in a sentence. (For a distribution with no shape to read, such as
  the lognormal, the row gives the **Median life** instead.)

The **Model characteristics** tab has the mean life (MTTF) and the B-lives (B1,
B5, B10 and B50), each with its lower bound at one confidence you choose.
**Diagnostics** asks whether you can trust the fit: the fitted curve over the
data's own estimate, a P-P plot of where the failures fell against where the
model expects them, the ranking of every other distribution on the same data,
and the fit statistics (log-likelihood, AIC, AICc and BIC). **Data** lists the
failures, how the model was fitted and every parameter.

![A fitted Weibull model: probability plot, parameters and the failure pattern](/guides/img/fit-02-result.png)

The **probability plot** is the one to look at first. It puts your data on paper
where a good fit is a straight line. If the points track the line, the
distribution is a reasonable description of your data. If they curve away
systematically, or fall into two distinct groups, that's telling you something
real — often that you have two failure modes mixed together and would be better
off splitting the data.

For the sample bearing model, 30 failures fit a Weibull with shape **β = 2.50**
(90% 1.96–3.17) and scale **α = 1,440 hours**. For a Weibull fit, **β is the
number worth understanding**:

- **β < 1** — failures are *decreasing* over time. Infant mortality: bad
  installs, manufacturing defects, teething problems. Replacing on a schedule
  makes things *worse*, because new units are the risky ones.
- **β ≈ 1** — a constant failure rate. Failures are random, age tells you
  nothing, and scheduled replacement buys you nothing either.
- **β > 1** — wear-out. Risk rises with age, and preventive replacement starts
  to make sense.

That single parameter often changes the maintenance decision more than anything
else on the page, which is why the panel spells it out. The bearings' whole
interval sits above 1, so the **Failure pattern** row reads *Wear-out*, and
clicking it says *β is above 1 at 90% confidence*.

The **Calculator** tab lets you ask the model direct questions: reliability (or
any other function) at a given time, or, with **Time at reliability**, the time
by which a given fraction will have failed — the B-lives, with **B1**, **B5**,
**B10** and **B50** one click each. Every answer comes with a confidence bound,
stated in words. The
[B-lives and confidence bounds](/guides/b-lives-and-confidence-bounds) guide
reads them in detail.

![The model calculator, reading reliability off the fitted curve](/guides/img/fit-03-calculator.png)

## No data yet: a model from the data library

The reliability data library has moved from Data to **Models › Library**
([open it](/models/library)). It holds published failure data, each record
cited: industry-average failure rates and probabilities on demand (NRC/INL
2020, from U.S. nuclear plants) and handbook base rates for electronic parts.
Open a source to filter its records by equipment type, failure mode and kind,
and a record to see its distribution written out and plotted.

A record's **Use as a model…** saves it as an exponential model, cited on the
model. First it asks for the record's **covariates**: what it needs before it
gives a rate. A pipe's rate is per foot, so it asks for the pipe's length; a
rate per hour of running can be moved to calendar hours with the hours a year
it runs; a probability per demand becomes a rate with the demands a year; a
handbook part needs its environment (and takes its quality grade). Left blank,
a covariate takes its default; one with no default is needed, never guessed.
The model keeps the source's gamma on the rate: the rate varies from plant to
plant, and times to failure are exponential at a given rate. So the model's
Model characteristics and Calculator show each value with its 5–95% range
across plants (the spread between plants, not a fit's confidence bound), and
an RBD's band draws the block's rate from it.
**Use as a prior…** fits one of your datasets with the record as the prior,
under the same covariates: on an exponential the record's gamma is the prior
exactly; on a Weibull or lognormal it becomes a prior on the mean life, with
the shape between bounds you give. A handbook rate is a single value with no
spread, so it can't be a prior.

**Components.** The NRC/INL source's page has **By component**: an equipment
type in one of the report's groups, such as a motor-driven pump that's
normally on standby, with its failure modes together (fails to start on each
demand, fails to run in the first hour and after it, leaks every calendar
hour). Give the demands, running hours and calendar hours of the period you
have in mind and the component page says the chance it fails over it, each
mode's share, and the constant rate an RBD block would use.

## Build your own library

A model you fit is in no library until you put it there. Open a saved
non-repairable model and choose **Add to a library…** from its ⋯ menu (or,
in the Explorer's Modelling tab, **Life model › Add to a library…** for a
position's life model). Pick one of your libraries or make a new one there
(a name and one line on what it holds), then give the record a label (the
model's name to start with), its equipment type, the failure mode it's for
and any notes; the time unit comes from the model.

Adding takes a snapshot: the distribution, its parameters with their bounds,
the unit, how many units were observed and how the model was fitted. The
record links back to the model, but a later refit doesn't change the record,
so a library stays what you reviewed. Your libraries show first under
**Yours** on the [Library page](/models/library), with **New library…**,
and in the library pickers; a library's page has **Edit…** and **Delete…**
(deleting a library never deletes the models), and a record's page has
**Remove from library**. A library's notes or licence text shows with every
record in it.

A record of yours works like a published one: **Use as a model…** saves a
model of the same family with the record's parameters and bounds, and **Use
as a prior…** (or **A library record** in the Fit dialog) fits your data in
the record's family with each parameter about the record's value, between
its bounds (within about 30% when the record has none, and the result says
so). One library counts as one saved item on the Free plan, however many
records it holds.

## Run it yourself in Python

**Download as Python**, first in the model page's **⋯** menu, gives a script that refits the model with
SurPyval on your own computer. It holds the data the model was fitted to, makes the same fit the app made
(the same method, censoring, options and units) and prints the numbers on the page: the parameters with
their 90% intervals, and the B-lives and mean life with their 90% lower bounds. The first lines of the script
say which SurPyval version to install. It's free for everyone who can open the model, including from a
public link.

## Where to go next

Name the model in the "This fit isn't saved yet" bar above the result and
press **Save this model** (**Save this model and its data** for a file you
uploaded). It then becomes available everywhere else: as a block in a
[reliability block diagram](/guides/build-an-rbd), as the input to an
[optimal replacement interval](/guides/optimal-replacement-interval), as the
basis of a [fleet failure forecast](/guides/forecast-fleet-failures-and-spares),
and as the evidence for a
[requirement or a demonstration test](/guides/check-a-requirement-and-plan-a-test).

For the theory behind the fit — how censoring is handled in the likelihood, what
the parameters mean, and how to read the plots — see the Learn article on
[Weibull analysis](/learn/weibull-analysis).

The fitting is done by [SurPyval](https://github.com/derrynknife/SurPyval), an
open-source Python library; its
[parametric modelling docs](https://surpyval.readthedocs.io/en/latest/Parametric%20SurPyval%20Modelling.html) show
the same fit in code.
