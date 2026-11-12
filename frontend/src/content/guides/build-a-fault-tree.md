---
title: "Build a fault tree"
task: "How do I work out how likely something bad is, from the failures that cause it?"
category: "Reliability block diagrams"
prerequisites: "A list of the failures that can cause the event, with a failure rate, a saved model or a probability for each. A guess is fine to start with, if you mark it."
related_href: "/systems/fault-trees"
related_label: "Open Fault trees"
order: 12
---

A fault tree starts from the thing that must not happen, the **top event**
("loss of thrust in flight", "no water to the tank"), and works down to its
causes. The answer it gives first is **how likely the top event is**. Then it
tells you **which combinations of failures cause it** and **which failures
matter most**.

A fault tree and a [reliability block diagram](/systems/rbds) describe the same
system from opposite sides: the diagram says when the system works, the tree
when it fails. Use whichever matches how you think about the system. You can
turn a tree into a diagram at any time.

## The pieces

- **Basic events** are the failures at the bottom of the tree: "Motor 1 fails",
  "Pump seal leaks". Each one needs its failure data.
- **Gates** combine them:
  - an **OR** gate occurs when **any** of its inputs occurs (one motor failing
    brings a quadcopter down);
  - an **AND** gate occurs only when **all** of its inputs occur (both pumps
    must fail before there's no flow);
  - a **vote** gate occurs when **at least k** of its inputs occur (two of
    three sensors failing, say). Switching a gate to vote starts k at a
    majority of its inputs (2 of 3), or at what its name says ("2 of 3 pumps
    down"); a vote of 1 is an OR, and the editor says so. A name that states
    the vote follows k when you change it.
- The **top event** is the gate at the very top.

A basic event can sit under more than one gate: a shared power supply that
feeds two pumps, for example. It's a **repeated event**, and Reliafy counts it
once, so the shared cause isn't hidden.

## Build the tree

Open [Fault trees](/systems/fault-trees) under System models and press
**New fault tree**. The tree shows as an outline: the top event first, and each
gate's inputs indented beneath it.

1. Select the top event and give it a name that says what must not happen
   ("Loss of thrust in flight"). Choose its gate: OR, AND or vote.
2. Use **Add gate** and **Add basic event** to build the tree downwards. Every
   row has a **⋯** menu (or right-click the row) to add, rename, change the
   gate, move a row up or down, move it into the gate above or out of its
   gate, or delete it. Deleting a gate deletes its whole branch.
3. Select a basic event to give it its **failure data**:
   - **Life model**: a model you've saved under Models, a failure rate or a
     mean life (MTBF), or Weibull parameters, just as an RBD block takes;
   - **Fixed probability**: a probability that doesn't change with time, such
     as a failure on demand or an unavailability (q);
   - **Not yet**: you can save a tree that isn't finished.
4. If a number is a guess, tick **This is a guess (placeholder)**. Every result
   then says which events are guesses, so nobody mistakes them for data.
5. Set the **Time unit** your rates and models are in, and press **Save**. The
   first save asks for the tree's name, starting from the top event's.

The sample [quadcopter tree](/systems/fault-trees/sample-fault-tree-quadcopter)
is a worked example: loss of thrust on any of four arms (each a motor or its
speed controller), a battery that wears out, and a flight controller that
carries on with either of its two IMUs, so it loses attitude only when both
fail.
Open it, change anything, and **Save a copy** to keep your version.

## Read the results

The results appear under the tree as soon as every gate has inputs and every
basic event has data: the answer in one sentence, then the figures.

- **Top event probability**: the chance the top event has happened by the
  time shown, with the **reliability** (the chance it hasn't) beside it.
  Reliafy picks the time where it reaches about 10% (reliability about 90%);
  type another time in **Evaluate at t** and press **Evaluate**. When every
  event is a fixed probability, time doesn't matter and there's one number.
- **Top event probability over time**: the same, as a curve.
- **The tree, drawn**: the gates and events with each one's probability.
- **Cut sets**: each smallest group of basic events that, failing together,
  cause the top event. A cut set of one event is a single point of failure.
  They're listed most likely first, with each one's share of the top event.
  Cut sets overlap, so the shares can add to more than 100%.
- **Importance**: how much each basic event matters. **Criticality** is the
  share of the top event it accounts for; it's the place to start improving.
  Birnbaum, Fussell–Vesely, RAW and RRW are the standard measures, explained
  on each column's heading.

Every figure is exact, worked out by the same engine as an RBD's fault tree
view. It's free on every plan.

## Turn it into an RBD, or export it

- **Open as RBD** saves the tree as a new block diagram: an OR gate becomes
  blocks in series, an AND gate blocks in parallel, and a vote gate a *k*-of-*n*
  block. Its numbers match the tree's. A fixed-probability event becomes a
  block with no model (a block needs a life), and a note says so: set its model
  in the builder before you calculate. The RBD doesn't follow later edits to
  the tree.
- **Export Open-PSA XML** (in the **⋯** menu) writes the tree in the Open-PSA
  format other fault-tree tools read. Exponential and Weibull events keep their
  models; any other model is written as its probability at the time shown, and
  the file says which.
- **Import** on the Fault trees page reads Open-PSA XML and Galileo `.dft`
  files as fault trees. See [Import a diagram](/guides/import-a-diagram).

## Limits

- Gates are AND, OR and vote. **NOT, XOR and INHIBIT gates aren't supported**,
  and neither are **dynamic gates** (priority-AND, spare, functional
  dependency, sequence): a file that uses them is refused with a note. A spare
  (standby) arrangement can be modelled in an [RBD](/systems/rbds).
- A tree holds up to **500 gates and basic events**. For a bigger system,
  build an RBD with sub-systems.
- Basic events are independent apart from repeated events. Common-cause groups
  are in RBDs, not fault trees yet.
- Repair isn't modelled: a fixed probability can stand for a steady-state
  unavailability.
