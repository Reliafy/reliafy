---
title: "Let the Reliability Agent build models and RBDs for you"
task: "How do I get the AI agent to analyse data and create models in my workspace?"
category: "Reliability Agent"
prerequisites: "A Pro plan or AI credits. Data is optional — the agent can research a system instead."
related_href: "/agent"
related_label: "Open the Reliability Agent"
order: 40
---

The Reliability Agent is a different thing from the assistant in the corner of
the screen. The assistant answers questions about the app. The agent **does the
work**: it runs Python in a sandbox with surpyval and repyability installed,
analyses your data for real, and then writes the results into your workspace as
saved datasets, life models, and reliability block diagrams.

It's genuinely useful for the case where you know what you want but not how to
get there — "here's a messy CSV of failures, work out the best distribution and
save it", or "research a duplex pump station and build me an RBD".

## Starting a run

Open **Reliability Agent** from the sidebar. You'll land on your saved
conversations; **New chat** at the top right starts a fresh one.

Attach a CSV if you have one and describe what you want. Be specific about the
outcome rather than the method — *"fit the best distribution to this and save it
as a model"* works better than *"run a Weibull fit"*, because it lets the agent
compare candidates and justify a choice.

**Data is optional.** If you ask it to research a type of equipment and build an
RBD from typical component reliabilities, it will — no upload required. Life
models still need data to fit, but a diagram built from researched values is
often a perfectly good starting point.

## Watch it work

The agent narrates as it goes, and you can expand each step to see the actual
code it ran and the output it got. This isn't decoration: it's how you check that
it cleaned the data the way you'd have cleaned it, and that the numbers it's
reporting came from a computation rather than a confident guess.

If it makes a chart, it renders inline.

## Nothing is created without your approval

This is the important part. When the agent has finished its analysis and is ready
to build something, it lays out a plan — every dataset, model, and diagram it
intends to create — and then asks permission. An **Approve & build** control
appears inline in the conversation.

Until you click it, **nothing has been written to your workspace**. The agent's
create tools are held. If the plan isn't right, don't approve it — just reply and
say what to change, and it'll revise and ask again.

Once approved, it runs the whole batch and reports what it made, with links.
Everything it creates is an ordinary Reliafy object: a model it saved is a model
you can open, re-fit, plot, put in a diagram, or run a replacement analysis
against.

## What it can and can't build

It creates **datasets**, **life models** (the full range — censoring, truncation,
covariates, the offset/zero-inflation/limited-failure-population modifiers), and
**RBDs** — including repairable diagrams that report availability, and
common-cause groups on redundant stages.

It doesn't create degradation models, RCM studies, or fleet objects yet. If you
ask, it'll say so rather than improvising.

## Conversations are saved

Every run is kept. The landing page lists them, and opening one restores the full
transcript — and lets you **continue it**, with all the earlier context intact.
That matters more than it sounds: a week later you can reopen an analysis, ask a
follow-up, and the agent still knows what it found and why.

## Cost

The agent runs a real sandbox on a frontier model, so it consumes AI credits
based on the work it does — meaningfully more than the assistant. Viewing past
conversations is free; only sending a message costs anything. Your credit
balance is shown at the top of the page.
