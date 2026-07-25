---
title: "Fit your first life model from a CSV"
task: "How do I turn a spreadsheet of failure times into a fitted reliability model?"
category: "Getting started"
prerequisites: "A CSV with a column of failure times. Censored units are welcome but not required."
related_href: "/modelling/new"
related_label: "Fit a model"
order: 1
---

Everything else in Reliafy is built on a fitted life model, so this is the place
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
Reliafy handles them properly if you tell it which is which, conventionally with
a `0` for a failure and `1` for a still-running unit:

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

Go to **Modelling → New model** and choose **Fit to data**. You can drop a CSV
straight onto the page, or pick a dataset you've already uploaded — datasets are
reusable, so once a CSV is in Reliafy you can fit as many models to it as you
like without re-uploading.

If your file has no header row, tick **No header row** when you upload it and
Reliafy will name the columns `col 1`, `col 2`, … so the first row stays data
rather than being eaten as titles.

## Mapping the columns

Next you tell Reliafy what each column means. The mapping uses the standard
survival-analysis letters, and you only need the ones your data has:

- **x** — the failure/censoring time. Required.
- **c** — the censoring flag.
- **n** — a count, if one row represents several identical units.
- **xl / xr** — lower and upper bounds, for interval-censored data (use these
  *instead of* x).
- **tl / tr** — left and right truncation.

Set the **unit** here too. It's optional, but it flows through to every chart
and result afterwards, and it stops you comparing a model in hours against one
in cycles later on.

## Choosing a distribution

Then pick the model. If you don't know which distribution you want — and often
you genuinely don't — choose **best fit** and Reliafy will fit every candidate
and keep the one with the lowest AIC, showing you the full ranking so you can
see how close the runners-up were.

If you do want to choose: **Weibull** is the workhorse and handles wear-out,
infant mortality and random failure through its shape parameter. **Exponential**
assumes a constant failure rate — simple, and right more rarely than people
assume. **Lognormal** suits repair times and fatigue. There's also a full set of
discrete distributions for cycles-to-failure data, non-parametric estimators
(Kaplan-Meier and friends) when you don't want to assume a shape at all, and
regression models when failure depends on covariates like temperature or load.

## Reading the fit

The result page gives you the fitted parameters with confidence intervals, a
probability plot, goodness-of-fit statistics, and a calculator.

The **probability plot** is the one to look at first. It puts your data on paper
where a good fit is a straight line. If the points track the line, the
distribution is a reasonable description of your data. If they curve away
systematically, or fall into two distinct groups, that's telling you something
real — often that you have two failure modes mixed together and would be better
off splitting the data.

For a Weibull fit, **β (beta) is the number worth understanding**:

- **β < 1** — failures are *decreasing* over time. Infant mortality: bad
  installs, manufacturing defects, teething problems. Replacing on a schedule
  makes things *worse*, because new units are the risky ones.
- **β ≈ 1** — a constant failure rate. Failures are random, age tells you
  nothing, and scheduled replacement buys you nothing either.
- **β > 1** — wear-out. Risk rises with age, and preventive replacement starts
  to make sense.

That single parameter often changes the maintenance decision more than anything
else on the page.

The **calculator** lets you ask the model direct questions: reliability at a
given time, the time by which a given fraction will have failed (B10, B50), and
the mean life — all with confidence bounds.

## Where to go next

Save the model and it becomes available everywhere else: as a block in a
[reliability block diagram](/guides/build-an-rbd), as the input to an
[optimal replacement interval](/guides/optimal-replacement-interval), and as a
basis for fleet forecasting.

For the theory behind the fit — how censoring is handled in the likelihood, what
the parameters mean, and how to read the plots — see the Learn article on
[Weibull analysis](/learn/weibull-analysis).
