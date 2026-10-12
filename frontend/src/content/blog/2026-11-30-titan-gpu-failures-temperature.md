---
title: "30,000 GPUs, 5,000 failures and a temperature nobody recorded"
date: 2026-11-30
author: The Reliafy Team
image: /blog/titan-gpu-failures-card.png
summary: Oak Ridge published the failure record of every GPU in the Titan supercomputer. We worked through it. A rework fixed most of the problem; only 41% of the original GPUs were ever going to fail; and where a GPU sat in its cabinet decided both how likely it was to fail and how soon. There's no temperature column in the data, but the pattern points to heat.
linkedin: |
  Oak Ridge published the failure record of every GPU in the Titan supercomputer: about 30,000 GPUs and 100,000 GPU-years of running time.

  We worked through it. Only 41% of the original GPUs were ever going to fail. In the bottom cage of each cabinet that was 33%; in the top cage, 73%. The data has no temperature column, but the pattern points to heat.

  The full analysis, with every model reproduced in Reliafy.

  #ReliabilityEngineering #SurvivalAnalysis #DataCentres
---

Titan was the US Department of Energy's flagship supercomputer at Oak Ridge
National Laboratory from 2012 until it was switched off in August 2019. Each of
its 18,688 compute nodes carried an NVIDIA GPU, and Oak Ridge kept a record of
every GPU that went in, came out, moved, or logged an error.

That record is public. The
[TitanGPULife dataset](https://github.com/olcf/TitanGPULife) accompanies the SC20
paper by Ostrouchov et al., *GPU Lifetimes on Titan Supercomputer: Survival
Analysis and Reliability*. It is about as good as real-world failure data gets:
large, complete, and honest about what wasn't observed. We used it to see how
much a careful life data analysis can say about a fleet, and what the numbers
mean for the people who have to keep one running.

Every fit below was done with [SurPyval](https://github.com/derrynknife/SurPyval),
the open-source library under Reliafy, and reproduced in Reliafy itself.

## The data, and why most of it says "still running"

There are 30,207 GPUs in the record, with about 100,889 GPU-years of running time
between them. The time axis is each GPU's accumulated operating life, not the
calendar, so a GPU that spent a year on the shelf doesn't age while it sits there.

What counts as a failure matters more than anything else here. Following the
original authors, a GPU has failed only if it was removed from service **and** had
logged a double-bit ECC memory error (DBE) or dropped "off the bus" (OTB).
Everything else is right-censored: GPUs pulled for unrelated reasons, and the
GPUs still working when Titan was switched off. 101 GPUs logged a DBE or OTB but
were left in service, and they count as censored too.

That leaves 5,089 failures and 83% of the records censored. This is where naive
analyses quietly go wrong. Average the failure times and you get the life of the
GPUs that failed early. Drop the censored records and you throw away most of what
the data knows: that most GPUs ran for years without failing.

## Two machines in one

Titan's GPUs came in two batches: the original install, and replacements fitted
from 2016 onwards after a manufacturing problem was traced. The two behave like
different products.

| batch | GPUs | failures | GPU-years | failures per GPU-year |
| :-- | --: | --: | --: | --: |
| original | 18,837 | 5,027 (26.7%) | 75,746 | 0.066 |
| reworked | 11,370 | 62 (0.55%) | 25,144 | 0.0025 |

Over their whole service the originals failed at 27 times the reworked batch's
rate. Part of that is age: the reworked GPUs were removed with Titan before they
reached the age when the originals started failing in numbers. Compared at the
same age the gap is smaller but still large. By 2.5 years of operation, 4.8% of
the originals had failed against 0.6% of the reworked GPUs, about eight times
fewer.

Either way, pooling the two batches would describe a machine that never existed.
The reworked batch has too few failures to support much of a model; it is
characterised well enough by its low rate. The rest of this analysis is about the
originals, where 5,027 of the 5,089 failures live.

## Wear-out, not random failure

The first question for any life model is whether failures are random in time or
build up with age. The Kaplan–Meier estimate for the originals answers it
visually: 99.1% were still running at two years, and then the curve turns
sharply down. That is wear-out.

The fits agree. The exponential distribution, which assumes a constant failure
rate, scores an AIC of 37,328. A Weibull scores 32,901, with a shape parameter of
2.6, and the lognormal does better still at 32,512. A constant-rate model is not
in the running, and any MTBF figure quoted for these GPUs would be misleading.

## Two ways to fail

Splitting failures by cause gives the two signatures in the event definition:

- **DBE** (double-bit memory errors): 3,819 of the original batch's failures.
- **OTB** (off the bus): 1,475.

Those add to more than 5,027 because 267 GPUs logged both before they were pulled.
DBE is the dominant mode, about two and a half times as common. The two modes
struck at similar ages: the median failure age was 3.4 years for DBE-only
failures and 3.0 years for OTB-only ones. By five years, roughly a quarter of the
original GPUs had failed with a DBE and a tenth with an OTB. Any cause-specific
plan, such as a memory-error early warning, should be sized against the DBE
mode first.

## Most of them were never going to fail

Here is the finding that changes the picture. Even the best plain distributions
miss the tail of the original batch. The Kaplan–Meier curve is flattening, as if
a large share of GPUs will simply never fail. A standard distribution can't
follow that: every one of them insists that, given enough time, everything
fails.

A limited failure population model (sometimes called a cure model) says what the
data does: a fraction *p* of the GPUs carries the defect and will eventually fail,
and the rest don't. Fitted to the original batch, it gives:

- *p* = **0.407**: only about 41% of the original GPUs were ever going to fail.
- For those susceptible GPUs, a Weibull life with scale 4.20 years and shape 3.71.
- AIC 32,221, clearly better than the lognormal (32,512) and the plain Weibull
  (32,901).

That one parameter reframes the fleet. The originals were not wearing out
uniformly. A defective subpopulation was working its way through, against a
healthy majority, which is what you'd expect of a manufacturing defect rather
than of age-related wear in every part.

## A temperature nobody recorded

The dataset also records where each GPU lived: cabinet column and row, and within
each cabinet the cage (0 at the bottom, 2 at the top), the slot and the node. Fit
the limited failure population model separately for each cage and the effect is
stark:

| cage | GPUs | susceptible fraction *p* | Weibull scale (susceptible GPUs) | still running at 5 years (data) |
| :-- | --: | --: | --: | --: |
| 0, bottom | 6,240 | 33% | 5.7 years | 86% |
| 1, middle | 6,275 | 50% | 4.5 years | 62% |
| 2, top | 6,322 | 73% | 3.6 years | 29% |

![Survival by cage, model versus data. Three cages, bottom to top, each with the Weibull limited-failure-population model (thick line) over the Kaplan–Meier estimate from the data (thin line). They track closely; the top cage's curve flattens onto its plateau near 27%.](/blog/titan-cage-survival.png)

The thick lines are the models and the thin lines are the raw data. They track
closely in every cage, with the top cage's model running a little ahead of the
data between three and five years.

There is no temperature column in the data, so this is inference. But air moves
up through Titan's cabinets, the top cage is the warmest, and the pattern is what
heat would do. Position changed both how many GPUs carried the defect (33% to
73%) and how quickly the defect showed (a scale of 5.7 years down to 3.6).

That second point has a practical consequence. The usual tool for "does this
covariate matter?" is a Cox proportional hazards model, which summarises the
effect of cage in one hazard ratio. Here the ratio doesn't hold still. From the
fitted models, the top cage's failure rate is about 10 times the bottom cage's
at one year and about 18 times at three years. By five years it is lower than the
bottom cage's, because the top cage has nearly run out of susceptible GPUs to
lose. A single hazard ratio averages over all of that. Stratifying by cage, as
above, keeps it.

## What a planner does with the model

A fitted curve isn't the end product; a decision is. With the original batch's
model saved in Reliafy, the reliability of a GPU at any age reads straight off it.
At four years, R = 0.770 (95% confidence interval 0.763 to 0.776), on a curve
that settles towards a plateau of about 0.59.

![Reliafy's calculator on the fitted model: reliability at four years is 0.770 (95% CI 0.763–0.776), read off a survival curve that flattens onto a plateau around 0.59.](/blog/titan-calc.png)

The question a maintenance planner asks is about the fleet, not one part. Point
the model at a set of in-service GPUs, each with its own running time, and it
becomes a forecast. For 150 original-batch GPUs at about three years, Reliafy
expects about 1.5 failures in the next month and about 21 over the next year, with
a P10 to P90 range of 0 to 3.1 for the month. That is the number that sizes a
spares order or a maintenance window.

![Reliafy fleet forecast: 150 in-service GPUs, one-month horizon. Expected failures 1.5, with a P10–P90 range of 0 to 3.1, and a per-item table of each GPU's age and its probability of failing in the window.](/blog/titan-fleet.png)

Done by cage, the forecast changes sharply. At three years, the bottom cage's
6,240 original GPUs would be expected to lose about 14 a month; the top cage's
6,322, about 250.

## Next: should you replace them before they fail?

The limited failure population has a strange consequence for maintenance. Its
failure rate rises, peaks, and then falls, because the GPUs still running are
more and more likely to be the ones that never fail. A top-cage GPU that reaches
five years is almost certainly one of the good ones.

So when does it pay to replace a GPU before it fails? On a schedule, by cage, or
only by swapping the originals for the reworked batch? The answer depends on how
long the machine has left to run, and the textbook method gives a misleading one
here. That is the next post.

Reliafy is [open source](https://github.com/Reliafy/reliafy), and every model
here can be fitted from the public data in a free account.
