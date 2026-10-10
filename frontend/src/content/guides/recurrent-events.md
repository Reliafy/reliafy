---
title: "Analyse repairable systems and reliability growth"
task: "How do I tell whether a fleet is getting better or worse over time?"
category: "Life data modelling"
prerequisites: "A long-format history of repair events: which system, when it failed."
related_href: "/modelling/recurrent/new"
related_label: "Open recurrent events"
order: 16
---

Life-data analysis models **time to a single failure** — an item is born, it
lives, it dies, and that's the end of its story. That's the wrong frame for a
repairable system, which fails, gets fixed, goes back into service, and fails
again. A compressor that's been repaired eleven times doesn't have "a life"; it
has a *history*.

The questions change too. Not "how long will it last?" but: **is it getting
better or worse?** How often will it fail next year? Are the repairs actually
helping?

That's the recurrent-events section, and it's the honest home for MTBF on
repairable equipment.

## What your data looks like

Long format: one row per event, saying which system failed and when.

```
compressor,hours,test_end
CMP-1,1150,5000
CMP-1,2050,5000
CMP-2,1400,5000
```

The key columns are **i** (the system identifier — this is what groups events
into per-machine histories) and **x** (the event time, measured from that
system's start, not a calendar date).

You should also give each system's **observation window** — how long you watched
it, whether or not it failed again — mapped to `tr`. Without it the analysis
can't tell the difference between a machine that stopped failing and a machine
you stopped watching, and it will quietly conclude your fleet is improving.

Three optional columns add more:

- **Cause of each failure** (a failure mode such as seal or bearing): the MCF of
  each cause, and a growth projection.
- **Covariates** (site, duty, operating condition), constant for each system: what
  drives the repair rate.
- **Observation windows**, when a system wasn't watched for a while (mothballed,
  records lost): a window-start and window-end column, or type them in as
  `system, start, end`, one a line. A failure has to fall inside one of its
  system's windows.

## Fitting

Go to **Modelling → Recurrent events → New model**, pick your data, map the
columns, and choose a model:

- **Crow-AMSAA (NHPP)** — the standard reliability-growth model, and the right
  default.
- **Duane** — the classic log-log formulation of the same idea.
- **Homogeneous Poisson (HPP)** — a constant failure rate with no trend. Useful
  mainly as a null model to compare against.
- **Cox-Lewis (log-linear NHPP)** — a rate that changes by a fixed proportion
  per unit time. An alternative when the trend doesn't follow a power law.

Two more kinds sit beside these:

- **Covariates — proportional intensity.** One baseline failure rate (Crow-AMSAA by
  default) scaled up or down for each system by its covariates. It answers "which
  site, or how much duty, drives the repair rate?"
- **Imperfect repair — generalized renewal (Kijima I and II), ARA, ARI and G1.**
  Crow-AMSAA assumes each repair puts the system back as it was just before the
  failure ("as bad as old"). These models estimate how much a repair really
  restores, somewhere between that and "as good as new".

You can also build one **from parameters** if you already know α and β and just
want the calculator — handy for growth planning before you have data.

![Mapping a repair history and choosing a growth model](/guides/img/recurrent-01-new.png)

## Reading the result

The **mean cumulative function (MCF)** plot is the heart of it: cumulative
failures against time, with the observed step function and the fitted curve. Its
*shape* is the finding. Curving upward means failures are accelerating; flattening
means they're slowing; a straight line means a steady rate.

![The mean cumulative function: observed steps against the fitted curve](/guides/img/recurrent-02-mcf.png)

The number that formalises this is **β**:

- **β < 1** — improving. Failures are getting rarer. Reliability growth is real.
- **β = 1** — stable. A constant rate; repairs are restoring the system to
  roughly where it was.
- **β > 1** — deteriorating. Failures are accelerating. The system is wearing out
  faster than repairs restore it, and there's usually a decision waiting at the
  end of that trend.

β comes with its **95% confidence interval**, and the verdict is read from the
interval rather than the point estimate: *deteriorating* only when the whole
interval is above 1, *improving* only when it's all below, and *stable* when it
includes 1 — the data can't tell the trend from a constant rate.

Reliafy states the verdict in words alongside the number, plus the **ROCOF**
(rate of occurrence of failures) and the instantaneous **MTBF** at the end of
observation, each with 95% bounds — the honest MTBF for a repairable system,
which is a *current* rate rather than a lifetime average. For a growth test it
also gives the **demonstrated MTBF** as a 90% lower bound ("MTBF ≥ X at 90%"),
using Crow's exact bounds from MIL-HDBK-189C when the test design allows.

Under **Fit statistics** in the panel beside the plot, two **trend tests** —
Laplace and MIL-HDBK-189C — tell you whether the trend is statistically
significant or whether you're reading noise. Worth checking before you take a
deteriorating verdict to a capital-expenditure meeting. A **Cramér-von Mises
goodness-of-fit test** checks the fitted model against the event times, and with
several systems the **Systems against the model** table shows the ones failing
more often than the fleet model expects — your bad actors.

**By cause** shows the MCF of each cause with its 95% band, and each cause's own
growth shape β: often one failure mode is accelerating while the rest are steady.

**Covariates** (proportional intensity) gives each covariate's effect as a rate
ratio, in words: "at site Inland, failures come about 2.2× as often as at
Coastal". A text covariate is compared with the level most systems have; an
interval that includes 1 means the data can't rule out no effect.

**Imperfect repair** leads with the repair effectiveness in words — "each repair
takes away about 79% of the age gained since the last repair", with 100% as good
as new and 0% as bad as old — and the **repair test**'s verdict: perfect repair,
minimal repair, or in between. **Next failure** shows each system's chance of
running a further time without failing, from where its own history leaves it.

## The calculator

The calculator answers the planning questions directly: expected cumulative
failures by a future time, the failure rate at a given point, and how many
failures to expect in a specific window — which is the number that sizes a
spares order or a maintenance budget.

## Where to go next

If the same equipment also has a wear-out story at the component level, fit those
as ordinary [life models](/guides/fit-your-first-model) — the two views answer
different questions and are complementary, not competing.

If you're deciding whether to keep repairing or replace outright, a recurrent
model built from parameters feeds that comparison directly, and the **Overhaul**
tab finds the overhaul interval for a minimal-repair model.
