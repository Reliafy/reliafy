---
title: "With reliability software, the training is the product. So we put it in the box."
date: 2026-08-07
author: The Reliafy Team
image: /blog/training-comes-with-the-software.png
summary: Every serious reliability package assumes you'll take the course — the licence is the small half of what it costs to make an engineer productive. Reliafy ships the expertise inside the tool instead, as an assistant that helps you drive and an agent that does the analysis with you, then asks permission before it saves anything.
---

Here is a thing everyone in this field knows and nobody puts on the pricing
page: the licence is the cheap part.

Buy a seat of any serious reliability package and you have bought a lot of
menus. Somewhere in there is a maximum-likelihood fitter, a probability
plot, a block diagram tool — but between you and them stands an assumed
curriculum. You're expected to know that a censoring flag of 1 means the
unit *survived*. To know that times-between-failures on a repairable machine
must not go into a Weibull fit. To know which of five estimation methods is
defensible for your sample size, that temperature goes into an Arrhenius
model in kelvin, and that a curve on probability paper means two failure
modes are hiding in your data.

None of that is in the software. It's in the course. So vendors sell the
course — three days, a hotel conference room, a workbook — and companies
budget for it, because a licence without the course is a very expensive way
to produce wrong numbers. The real product has always been *licence plus
training*, and the training half is the one that doesn't scale: it fades
when people change roles, it leaves with them when they leave, and the new
graduate who inherits the seat inherits none of it.

We think that's the part worth attacking. Not the menus — the curriculum.

## Two different jobs

Reliafy has AI in two places, and they do deliberately different jobs.

The **assistant** sits inside the app and helps you drive it. It's the
colleague-at-the-next-desk role: how do I mark suspensions in this CSV,
what does this β mean for my replacement policy, why is this option greyed
out. It can see what you're working on, so its answers are about *your*
screen, not documentation in general. One of our earliest users spent
fifty minutes building a repairable block diagram of a power distribution
feeder and consulted the assistant twice, mid-build, without ever leaving
the canvas. That's the job: keep you moving.

The **Reliability Agent** is the bigger swing. You hand it a problem — a
CSV of failure records, or just a description of a system — and it does
what a junior reliability engineer with excellent training would do:
inspects the data, tries candidate models, checks the fits, and comes back
with a plan. Approve the plan and it builds everything in your workspace —
datasets, fitted life models, block diagrams — as ordinary objects you can
open, edit, recalculate, and delete, exactly as if you'd built them by
hand.

The distinction matters because "AI in engineering software" usually means
a chatbot bolted onto the help system. The assistant is roughly that, and
it's useful. The agent is a different claim: that the analysis itself — the
part you used to need the course for — can be done *with* you, visibly,
and land in the same artifacts you'd have produced yourself.

## What the agent actually does

Under the hood the agent runs in a sandbox with the same open-source
engines Reliafy itself uses — [SurPyval](https://github.com/derrynknife/SurPyval)
for survival analysis and RePyability for reliability block diagrams. When
it fits a Weibull to your data, it is running the same maximum-likelihood
estimation you would trigger from the UI, and this is the detail we care
most about: **the language model never invents a statistic.** It writes and
runs analysis code; the numbers come from the same deterministic libraries
every other number in Reliafy comes from. When the agent's work is saved,
Reliafy refits it server-side — so what lands in your workspace is
reproducible from your data, not a transcript of something a model said.

A run looks like this. The agent loads your CSV and looks at it — column
names, value ranges, how many rows look like suspensions. It builds the
analysis in its sandbox: candidate distributions, goodness-of-fit, the
comparisons you'd want made. Then it stops and shows you a numbered plan —
*one dataset, two candidate life models, one block diagram* — and asks for
approval. Nothing has been created yet. The approve button is a real gate,
not theatre: the tools that write to your workspace are disabled until you
click it, and the agent is told, firmly, to wait.

We built it that way because the failure mode of agentic software is not
wrong answers — you can check answers. It's *unrequested action*. An agent
that quietly creates thirty objects in your workspace is a mess to clean up
even when it's right. One that proposes, waits, and then does exactly what
it proposed is something you can learn to trust at your own pace.

## The curriculum, encoded

Here's what "the training comes with the software" means concretely. These
are things the three-day course teaches, and things the agent simply knows:

**Which kind of model your data needs.** The most common serious error in
this field — we'd defend that ranking — is fitting a life distribution to
times-between-failures on a repairable system. The numbers come out looking
plausible and mean almost nothing. The agent's instructions put this
distinction ahead of everything else: one failure per unit is life data;
repeated events on the same machines is a repair process; readings that
drift toward a limit are degradation; failures at elevated stress are an
accelerated test. Four different mathematics. The course spends its first
morning on this. The agent applies it to every dataset it sees.

**Censoring conventions.** A unit still running is information, not a
missing value — and encoding it backwards silently inverts your dataset.
We recently watched a new user upload a spreadsheet where 1 meant *failed*,
which is a perfectly reasonable thing to assume and the opposite of the
convention. Fitting proceeded on one failure and seven survivors instead of
seven failures and one survivor. A human expert glancing at the file spots
it instantly — *eight units and only one ever failed?* — and that glance is
exactly what the agent gives every file before it fits anything.

**The discipline around flexible models.** More parameters always fit
better; the course teaches you to be suspicious of that. When Reliafy fits
a mixture of failure modes, the UI says plainly: compare the AIC against a
single fit, and only a clear improvement is real. The agent works to the
same rule, because the rule is written into the system it operates in
rather than into a workbook in a drawer.

**The units, the conventions, the traps.** Kelvin for thermal acceleration
models. Turnbull for interval-censored data. Why a fit method that doesn't
support censoring is greyed out for your dataset rather than allowed to
fail. Each of these is a page of the course. Each is enforced or explained
at the moment it matters, which is the only moment anyone learns anything.

The point isn't that the software nags. It's that expertise stored in a
tool compounds, and expertise stored in people evaporates. When SurPyval
gains a capability, the agent gains it. When we learn from a user's
stumble, the fix lands in the product once and every subsequent user
benefits. No refresher course, no knowledge walking out the door at the
next reorganisation.

## Why the moment matters more than the material

There's a second problem with the course model, beyond cost and staff
turnover, and it's the one adult-learning research keeps confirming:
training decays fastest when it isn't used. The engineer who learned
interval censoring on day two of the workshop meets her first
interval-censored dataset eleven months later. What survives eleven months
is a vague memory that inspection data is somehow special, and a workbook
in a drawer two jobs ago.

Compare the sequence when the knowledge lives in the tool. She uploads the
inspection data. The mapping step offers interval bounds as first-class
columns. The fit picks the Turnbull estimator because the data demands it,
and says so. If she asks the assistant why, she gets the explanation *at
the moment she has the problem* — which is the one moment the explanation
will actually stick. The tool isn't just doing the work; it's teaching at
the point of need, which is the only kind of teaching with a decent
retention rate.

This is also, quietly, what changes for the senior engineer — the person
the course model treats as finished. Experts don't need the curriculum, but
they carry a different burden: they're the bottleneck everyone else's
questions route through. Every "which distribution should I use" that the
assistant answers is an interruption a senior engineer didn't absorb. The
agent doesn't replace the expert; it replaces the expert's Tuesday
afternoons.

And for the organisation, it changes what a reliability programme costs to
*start*. The traditional sequence is: buy licences, schedule training,
wait for the trained people to build confidence, hope they stay. The
sequence with expertise in the box is: bring data, get a defensible first
model the same afternoon, and let the team's judgement develop against
real analyses of their own equipment rather than workbook exercises about
imaginary pumps.

## A real run

The first serious thing our agent built wasn't a demo. We asked it to
model a GPU compute cluster as a reliability block diagram — power supplies,
cooling, network fabric, the compute sleds themselves — with realistic life
distributions for each component class. It researched typical failure
behaviour, chose distributions with reasoning attached, proposed the
structure, and, once approved, built the diagram with redundancy where the
architecture had it.

Afterwards we did the paranoid thing you should always do to an AI system:
we checked. The life model parameters it had produced were refit by hand
against the same data with SurPyval directly. They matched to the last
decimal place — because, as above, the agent's numbers *were* SurPyval's
numbers. The interesting work it did was the part that isn't arithmetic:
deciding what the system looked like, which components share failure
causes, where redundancy actually helps. That's the work the course was
always really about.

## What it doesn't replace

Honesty section. The agent is a very well-trained junior engineer, and that
is both the pitch and the limit.

It can be wrong the way a junior can be wrong: a defensible-looking model
choice that your knowledge of the physics overrules, a data quirk
misdiagnosed. Its output is statistics, not engineering judgement — our
terms of service say bluntly that decisions taken from the tool are yours,
and we mean it. Where a decision touches safety or serious money, a
qualified engineer checks the inputs and the assumptions. The agent makes
that review *faster* — everything it builds is inspectable, every model
shows its fit against the data — but it doesn't make it optional.

What it does replace is the blank page. The three days of training before
the first useful fit. The consultant engagement whose deliverable is a
model your own team can't maintain. The gap between "we have the data" and
"someone here knows what to do with it" — which, in most organisations, is
where reliability programmes go to stall.

## Try it

Reliafy is [open source](https://github.com/Reliafy/reliafy). On the cloud
version the assistant is there from your first session, with starter AI
credits included — bring a CSV of failure times and ask it anything. The
Reliability Agent is part of the Pro plan (and if you self-host, it runs on
your own API key). Hand it a real dataset, or just describe a system you
care about, and see what it proposes.

The menus are free. The course now comes with the seat.
