---
title: "The RCM binder is wrong and nobody knows which page"
date: 2026-07-23
author: The Reliafy Team
summary: Every mature RCM programme has the same artifact — a thorough, expensive study that was true the day it was written and has been quietly diverging from reality ever since. The fix isn't more discipline. It's making the worksheet check itself.
---

Somewhere near you is an RCM binder. It was produced by a serious team over
several months, it was reviewed and signed, and it directs the maintenance of
equipment your operation depends on. Some of its decisions are now wrong.

Nobody knows which ones.

That's not a criticism of the team. It's the nature of the artifact. An RCM
study is a snapshot of the evidence available on the day it was written: this
failure mode looked random, so run to failure; that one wore out, so replace
at 4,000 hours; this protective function is hidden, so test it quarterly.
Then the study is filed, the equipment keeps operating, and the evidence
keeps accumulating — new failures, new suspensions, new inspection data —
none of which the binder can hear.

## Decisions decay silently

The standard defence is the periodic review: revisit the study every few
years, re-examine every decision. Reviews are better than nothing, and
they're also why the binder problem persists — because a full review is so
expensive that it happens rarely, and when it happens, most of its effort is
spent re-confirming decisions that were still fine. The few decisions that
had actually gone stale get the same attention as the many that hadn't.
There's no triage, because nothing tells you *which* decisions the new data
disagrees with.

But notice what an RCM decision actually is: a claim about a life
distribution. "Run to failure" claims the failure mode is random — a Weibull
shape parameter near 1, where scheduled replacement buys nothing. "Replace on
a fixed interval" claims wear-out at a specific, cost-justified interval.
"Monitor condition" claims degradation is observable and predictable enough
to act on. These are statistical statements. They can be *checked* — by
exactly the models you'd fit from the failure data you've collected since.

## Worksheets with live evidence

That's how RCM works in Reliafy. A study is the classic decomposition —
functions, functional failures, failure modes, decisions — but every decision
**cites the analysis that justifies it**. A run-to-failure call links to the
fitted life model whose β says failures are random. A fixed interval links to
the cost-optimal replacement analysis that produced it. An on-condition task
links to the degradation model; a failure-finding interval links to the
availability calculation for the hidden function.

And the citations are live. When you refit that life model with another
year of data and the β that justified run-to-failure has crept from 1.0 to
2.3, the study doesn't stay serenely confident. The decision is flagged
**contradicted**, the moment the evidence turns — with the model one click
away, showing exactly what changed. The study's dashboard rolls it up:
so-many decisions supported, so-many awaiting evidence, so-many contradicted.

The periodic review doesn't disappear — it becomes triage instead of
excavation. You walk straight to the contradicted decisions, and the review
that took a week of workshops becomes an afternoon.

## The units check, too

A small thing that caught us during development: a surprising number of
stale RCM decisions aren't statistically wrong, they're *dimensionally*
wrong — an interval in months justified by a model fitted in operating
hours, drifted apart by a change in shift patterns. Reliafy checks the units
of every cited analysis against the decision that cites it, and refuses to
call a decision supported when they disagree. Pedantry, weaponised.

## Evidence you already have

The prerequisite isn't exotic: fitted models from your own failure data,
which is what the rest of Reliafy is for. Fit the life model with your
suspensions counted, run the replacement-interval analysis, and the RCM
study consumes them as evidence — same platform, same datasets, no export
dance between a statistics tool and a worksheet tool.

There's a complete sample study in the app — a pump system with linked
evidence, including one decision the sample data contradicts, so you can see
the flag without waiting for your own data to turn on you. It's on the free
tier, along with one study of your own with full live validation.

The binder was never the deliverable. The deliverable was maintenance that
matches how the equipment actually fails — *keeps* matching it. Paper can't
do that. A worksheet wired to the data can.
