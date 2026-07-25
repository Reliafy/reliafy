---
title: "Build a reliability block diagram"
task: "How do I model a system of components and get its overall reliability?"
category: "Reliability block diagrams"
prerequisites: "Life models for the components — either saved fits or parameters you can type in."
related_href: "/rbds/b"
related_label: "Open the RBD builder"
order: 10
---

A life model tells you about one component. A reliability block diagram tells you
about the **system** those components make up — and the answer is frequently not
what people expect, because reliability composes in ways intuition handles badly.
Ten components in series, each 99% reliable, gives a system that's 90% reliable.
Two in parallel, each 90%, gives 99%. An RBD makes those interactions explicit.

The important thing to understand up front: an RBD is about **logical
dependency, not physical layout**. Blocks go in series if *both* are needed for
the system to work, and in parallel if *either one* is enough. Two pumps sitting
side by side in the plant room are in series on the diagram if you need them
both, and in parallel if either alone can carry the duty. Draw the logic, not the
pipework.

## Laying out the diagram

Open **RBDs → New diagram**. Every diagram runs from an **input** node to an
**output** node, and the system works whenever there's a complete path between
them.

Right-click the canvas to add a component, then drag from one block's handle to
another to connect them. Series is a straight chain; parallel is two blocks that
both branch from the same predecessor and both feed the same successor.

![A pump station diagram: input, controller, redundant pumps, output](/guides/img/rbd-01-builder.png)

Set the **unit** in the top-left. Everything in the diagram should share one time
base, and Reliafy will warn you if you drop in a saved model that was fitted in
different units.

## Giving blocks their life models

Double-click a block to set its model. You have two options, and both are
legitimate:

- **A saved model** — a fit from your own data. Best when you have it.
- **Parameters** — type a distribution and its parameters directly. This is how
  you use a handbook value, a vendor figure, or a researched estimate, and it
  means you can build a useful diagram before you have failure data for
  everything in it.

You don't need data for every block to get value out of a diagram. A model built
from typical values still tells you where the weak points are.

## Beyond series and parallel

Plain series/parallel covers a lot, but real systems need more, and the canvas
has block types for the common cases:

- **k-out-of-n voting** — the system needs at least *k* of the *n* branches
  feeding the gate. Three sensors where any two must agree is a 2-of-3.
- **Standby** — spares that sit dormant (cold) or lightly loaded (hot) until
  switched in. The risk here is the *switching*, which you can set a probability
  for.
- **Series / parallel blocks** — a shorthand for *n* identical units, so you
  don't draw twenty identical blocks by hand.
- **Sub-system** — embeds another saved RBD as a single block, so you can build
  a diagram of pumping stations where each station is its own diagram.
- **Load-sharing** — units that split a common load, where survivors get
  stressed as others fail. Covered in its own [guide](/guides/load-sharing).

There's also **common-cause grouping**, for redundant units that can fail
together from a shared cause — the correction that stops parallel redundancy from
flattering you. That has [its own guide](/guides/common-cause-group), and it's
worth reading if you're relying on redundancy for anything that matters.

## Validate before you calculate

Press **Validate**. This is a genuine structural check, not a formality: it will
tell you if the diagram has a loop, if blocks aren't wired to anything, if a
component is missing its life model, or if a k-of-n setting leaves no path
through the system at all. It also tells you whether the diagram can be solved in
closed form or needs simulation.

Fix anything it reports, then switch to the **Calculator** tab and press
**Calculate**.

## Reading the results

You get the system reliability curve over time, the **MTTF**, and system
**B-lives** (B10 is the time by which 10% of systems have failed) — the same
quantities you'd get from a single fitted model, but for the whole assembly.

Two things are worth more attention than they usually get:

**Importance measures** rank the components by how much each one actually
matters to system reliability. This is not the same as which component is least
reliable — a weak component behind good redundancy may matter far less than a
mediocre one sitting alone in series. Importance tells you where an improvement
would actually move the system, which is the question you're usually trying to
answer.

**Minimal cut sets** are the smallest groups of components whose combined failure
takes the system down. A cut set of size one is a single point of failure, and
seeing them listed explicitly is often the most immediately useful output of the
whole exercise.

![System reliability results with importance measures and cut sets](/guides/img/rbd-02-results.png)

## Where to go next

If your system is repaired and returned to service rather than replaced, build it
as a repairable diagram instead and you'll get uptime rather than a survival
curve — see [modelling system availability](/guides/repairable-availability).

You can also skip the drawing entirely: the
[Reliability Agent](/guides/reliability-agent) can research a system and build
the diagram for you, which you then review and adjust.
