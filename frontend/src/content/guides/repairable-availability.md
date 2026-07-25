---
title: "Model system availability (repairable RBD)"
task: "How do I build a repairable reliability block diagram and read its availability?"
category: "Reliability block diagrams"
prerequisites: "A system you can sketch as blocks, and a failure and repair estimate for each block."
related_href: "/rbds/b"
related_label: "Open the RBD builder"
order: 30
---

Most reliability block diagrams answer the question *"will this survive to time
t?"*. That's the right question for something you run to failure and replace.
But if your system gets **fixed and put back into service** — a pumping
station, a production line, a data-centre power train — the question you
actually care about is different: *what fraction of the time is it up?*

That's availability, and Reliafy models it as a distinct kind of diagram. This
guide walks through building one.

## Choose the system type first

An RBD in Reliafy is either **non-repairable** (analysed for reliability over
time) or **repairable** (analysed for availability). It's a single choice made
up front, because it changes what each block needs and what the results mean —
you can't mix the two in one diagram.

Open **RBDs → New diagram**, and set the **System** selector in the top-left to
*Repairable*. (Non-repairable diagrams give you reliability over time; repairable
ones give you availability — hover the selector for the reminder.)

![The System selector set to Repairable](/guides/img/availability-02-system.png)

The moment you do, the diagram is in availability mode. You'll notice the
right-click menu offers fewer block types than usual — availability supports
plain component blocks and k-of-n voting gates, and nothing else. That's a
deliberate constraint, not an omission: standby, load-sharing and sub-system
blocks have no availability semantics, so Reliafy keeps them out of the way
rather than letting you build something it can't solve.

![The canvas right-click menu in repairable mode](/guides/img/availability-03-add.png)

## Every component needs two distributions

This is the part that's genuinely different from a normal RBD. A repairable
component is characterised by two things:

- **A life model** — how long it runs before it fails.
- **A repair-time distribution** — how long it takes to get back into service.

Availability depends on the *ratio* of those two, so the repair side matters
just as much as the failure side. A pump that fails monthly but is swapped in
twenty minutes can be more available than one that fails yearly but takes a
week to source parts for. A diagram with only life models can't tell you that,
which is why Reliafy insists on both.

Double-click a component to set them. Repair times are usually right-skewed —
most repairs are quick, a few drag on — so a **lognormal** is the conventional
choice for mean-time-to-repair.

![The component dialog with a Weibull life model and a lognormal repair-time distribution](/guides/img/availability-04-models.png)

Wire the diagram up as you normally would: drag from the input handle through
your components to the output, with redundant units in parallel.

![A controller in series with two redundant pumps](/guides/img/availability-05-wired.png)

## Validate, then calculate

Hit **Validate** on the Builder tab. In availability mode this checks the thing
that actually blocks the calculation — that every component has *both* a life
model and a repair time — and it will name any block that's missing one. It also
tells you that availability is **estimated by simulation** rather than solved in
closed form, which is expected: the up/down history of a repairable system is
simulated, not integrated.

![The validation panel confirming the diagram is valid](/guides/img/availability-06-validate.png)

Then switch to **Calculator** and press **Calculate**.

## Reading the results

![Availability results: 99.4% uptime, mean up/down time, and per-component downtime bars](/guides/img/availability-07-results.png)

The headline is **steady-state availability** — the long-run fraction of time
the system is up. Around it sit the numbers that make it actionable: mean up
time, mean down time, and how often the system drops out.

The part most people find useful, though, is **"what drives downtime"**. Each
component gets a share of the total system downtime. In the example above the
two redundant pumps dominate and the controller contributes far less — which
tells you where effort pays. Shaving the repair time off the biggest
contributor moves system availability; improving a minor one won't, however
satisfying it feels. Redundancy has the same asymmetry: it lifts availability
sharply for the stage it's applied to and does nothing anywhere else, so it's
worth knowing which stage is actually costing you uptime before you spend money
duplicating hardware.

## Where to go next

Save the diagram and it keeps its repairable setting, so you can come back and
re-run it as your failure and repair estimates improve.

If you want the theory behind the numbers — the MTBF/MTTR formula, how
availability composes through series and parallel structures, and the
distinction between inherent and operational availability — that's covered in
the Learn article on [system availability](/learn/system-availability).
