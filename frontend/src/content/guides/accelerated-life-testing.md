---
title: "Fit an accelerated life model and extrapolate to use conditions"
task: "How do I use high-stress test data to predict life at normal operating conditions?"
category: "Life data modelling"
prerequisites: "Failure times gathered at two or more stress levels (three is better), with the stress recorded per unit."
related_href: "/modelling/alt/new"
related_label: "Open accelerated life"
order: 15
---

You can't wait ten years to find out whether something lasts ten years. So you
run it hot, or at elevated voltage, or under heavier load, until it fails on a
timescale you can actually observe — and then work backwards to what it would
have done at normal conditions.

That's accelerated life testing, and it lives in its own section of Reliafy
because the workflow genuinely differs from an ordinary life fit. A normal fit
describes failures at *one* condition. ALT fits failures across *several* stress
levels plus a relationship tying life to stress, which is what lets it
extrapolate to a condition you never tested.

## What your data needs

One row per unit, with the failure time and the stress that unit was running at:

```
hours,temp_C,censored
1350,60,0
950,80,0
620,100,0
```

Two stress levels is the bare minimum; **three or more is much better**, because
with only two you're fitting a line through two points and have no way of
noticing it's the wrong line. Censored units are fine and common — tests get
stopped before everything fails.

You can also model **two stresses at once** (temperature and voltage, temperature
and humidity), which needs a crossed design so the two aren't confounded.

The assumption underneath all of this: raising the stress must **accelerate the
same failure mechanism**, not introduce a new one. Bake a component past the
point where a different mode kicks in and you're no longer learning anything
about field failures. Keep the stresses within the range where the physics is
the same.

## Choosing the model

Go to **Modelling → Accelerated life → New model**. The flow asks for the
**model before the data**, which is deliberate — the life-stress relationship
determines how many stress columns you'll be mapping.

You pick two things:

- **A life distribution** — Weibull, lognormal, normal, exponential or gamma.
  This describes the scatter in failure times at any fixed stress.
- **A life-stress relationship** — how the characteristic life shifts as stress
  changes.

Match the relationship to the physics:

- **Arrhenius** for thermal ageing. Use **absolute temperature (kelvin)** — this
  trips people up constantly, and using Celsius will give you a nonsense fit.
- **Inverse power law** for voltage, load, or pressure.
- **Eyring** as a physically-derived thermal alternative to Arrhenius.
- **Dual-exponential**, **temperature–nonthermal**, or **dual power** for two
  stresses together.

Then map your columns — the failure time, the stress column(s), and censoring if
you have it — and fit.

## Reading the fit

Two views matter, and they answer different questions.

The **life–stress plot** is the ALT signature: characteristic life against
stress, with each tested level marked and the fitted relationship drawn through
them, extended *below* your lowest test stress toward use conditions. This is
where you see whether the extrapolation is a short reach or a heroic one.

The **probability plot** is the honesty check. Each stress level's failures are
drawn on the distribution's probability paper. A trustworthy fit shows the levels
as **parallel straight lines** — parallel because the shape parameter is shared
across stresses, straight because the distribution is right. If they fan out or
curve, the shape isn't really constant across stress, and the extrapolation is
resting on an assumption your data doesn't support. Better to find that out here
than in the field.

## Extrapolating to use level

Save the model and open the **use-level calculator**. Enter the stress your
equipment actually runs at — below your tested range, which is the whole point —
and you get the extrapolated reliability curve, the characteristic life, mean
life, and B-lives at that condition.

Give it a reference stress as well and you get the **acceleration factor**: the
ratio of use life to test life. That's the number that makes test planning
concrete. At AF = 100, one hour on the bench stands for a hundred hours in
service, so demonstrating a 10,000-hour field life means surviving about 100
hours on test.

Treat the acceleration factor as a sanity check too. If it comes out
implausibly large, you're either extrapolating much further than the data
supports or you've fitted the wrong relationship.

## Where to go next

The relationships, the activation-energy interpretation, and a worked
temperature example are in the Learn article on
[accelerated life testing](/learn/accelerated-life-testing).

If your interest is the opposite direction — what happens as surviving units get
*more* stressed — see [load-sharing](/guides/load-sharing), which uses the same
kind of stress-life model in reverse.
