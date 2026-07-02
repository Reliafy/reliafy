---
title: Reliafy is now open source
date: 2026-07-03
author: The Reliafy Team
summary: The full reliability-engineering toolkit — modelling, RBDs, and maintenance strategy — is now AGPL-licensed and self-hostable with one command. Here's what changed, why we did it, and exactly how the open-source and cloud versions differ.
---

Today we're making Reliafy open source. The complete core product — life-data
modelling, reliability block diagrams, maintenance strategy, and dataset
management — is now available under the AGPL-3.0 license, and you can run the
whole thing on your own hardware with a single command:

```
git clone https://github.com/Reliafy/reliafy
cd reliafy
docker compose up --build
```

Open http://localhost:8000 and you're in. No account, no sign-up, no telemetry
— a persistent database in a Docker volume, sample datasets and a worked
reliability block diagram already seeded, and every feature of the core
toolkit ready to use.

## Why open source?

Reliability engineering happens in places the cloud can't always reach.

If you've worked in this field, you know the pattern: the failure data that
matters most lives inside defense contractors, mining operations, utilities,
rail networks, and manufacturing plants — organisations with strict rules
about where data goes. Sometimes it's policy. Sometimes it's an air-gapped
network. Sometimes it's simply that the data describes critical infrastructure
and nobody wants it on someone else's servers, however good the encryption
story.

A cloud-only tool tells those engineers: *sorry, not for you.* We think that's
the wrong answer. The people with the strictest environments are often the
ones who need good reliability tooling the most.

There's a second reason, and it matters just as much: **you should be able to
check the statistics.** When a tool tells you the optimal replacement interval
for a component, or that a Weibull shape parameter is 1.8 with a given
confidence bound, that number feeds real maintenance decisions with real
costs. With Reliafy you can now read exactly how every figure is computed —
the fitting is built on [SurPyval](https://github.com/derrynknife/SurPyval)
and [RePyability](https://github.com/derrynknife/RePyability), both open
source, and now the application around them is too. No black boxes between
your data and your decisions.

## What's in the open-source version

Everything that makes Reliafy useful, with no feature gates:

- **Life-distribution modelling.** Fit Weibull, Lognormal, Exponential, Gamma,
  Normal, and proportional-hazards models to exact, censored, and truncated
  data. Probability plots on distribution-specific paper, confidence bounds,
  goodness-of-fit, and a survival calculator.
- **Reliability block diagrams.** A drag-and-drop canvas for series, parallel,
  k-out-of-n, and standby structures, computing system reliability, MTTF,
  importance measures, and minimal path and cut sets.
- **Maintenance strategy.** Rank candidate distributions against your data,
  compare two designs head-to-head, and find the cost-optimal preventive
  replacement interval.
- **Datasets.** Upload a CSV once, reuse it across models, and keep everything
  organised.

There are no artificial limits in the self-hosted version — no capped model
counts, no locked features, no nag screens. It runs in single-user mode: your
instance, your data, your machine.

One honest note on the AI assistant: the open-source build ships without it by
default, because it needs a large-language-model behind it. If you drop your
own OpenAI or Anthropic API key into the configuration, the assistant lights
up on your instance too, talking to your key. Without one, the feature simply
stays hidden.

## What the cloud version is for

[Reliafy Cloud](https://reliafy-290759058830.australia-southeast1.run.app) is
the same codebase, hosted and operated by us. It exists for teams and
individuals who want zero setup, and it adds the things that only make sense
hosted: user accounts, a metered AI assistant that works out of the box on
prepaid credits (no API key required), a Pro plan with unlimited saves and
1,000 AI credits included each month — and team workspaces, which are coming
next.

We want to be straightforward about the model, because open-core projects
sometimes aren't: **it's one repository.** The billing code, the AI metering,
the account system — it's all in the open repo you can read, and all of it
stays dormant unless configured with keys. The open-source version isn't a
stripped-down community edition maintained on the side; it's the same code we
deploy to production, gated by nothing but environment variables. When we fix
a bug in the cloud, the fix lands in the public repository, because they are
the same place.

## Why AGPL?

We chose the GNU Affero General Public License deliberately. For you as a
user, it means the four freedoms with no fine print: use it, study it, modify
it, share it — free forever, for any purpose, commercial included.

The "Affero" part adds one condition that protects the project: if someone
offers a modified Reliafy as a network service, they must publish their
modifications. You can self-host for your team, your plant, or your entire
company without sharing anything. What the license discourages is a third
party taking the code, improving it privately, and selling it back as a
closed competing service. Plausible, Metabase, and Cal.com made the same
choice for the same reason, and we think it's the honest middle ground:
genuinely open for users, defensible as a project.

## Getting started, contributing, and what's next

The [README](https://github.com/Reliafy/reliafy) covers the details: the
docker-compose quickstart, the full configuration reference for self-hosting,
and the development setup if you want to hack on it — the backend is FastAPI
and the frontend is React, and the test suite runs with plain pytest.

Bug reports and pull requests are welcome. If you find a security issue,
please use the private reporting path in SECURITY.md rather than a public
issue. And if Reliafy is useful to you, starring the repository genuinely
helps other engineers find it.

Next on the roadmap: team workspaces for the cloud, more distribution and
strategy tooling in the core, and continued polish on the RBD builder. The
best way to influence what comes after that is to open an issue and tell us
what your reliability workflow actually needs.

Run it, break it, tell us what's missing. It's yours now too.
