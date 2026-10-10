---
title: "Verify a safety function (SIL / PFDavg)"
task: "How do I check that a safety instrumented function reaches its SIL?"
category: "Reliability block diagrams"
prerequisites: "The function's elements, their dangerous undetected failure rates (λDU) and proof-test intervals."
related_href: "/rbds"
related_label: "Open the RBDs page"
order: 33
---

A safety instrumented function (SIF) is a loop that brings a process to a safe
state on demand: sensors that see the hazard, a logic solver that decides, and
a final element — usually a valve — that acts. For a low-demand function,
IEC 61511 (and IEC 61508 behind it) asks for its **average probability of
failure on demand, PFDavg**, and the **SIL** band that figure falls in.

Reliafy works it out from a block diagram of the function: each element's
dangerous undetected failures, the proof tests that find them, the voting
between redundant channels and their common cause.

## Start from the starter

On the Modelling, RBDs or Strategy page, choose **Verify a safety function
(SIL / PFDavg) → Open the starter**. It opens a diagram, unsaved, of the usual
shape:

- two pressure transmitters voting **1oo2** (either one can trip), in a
  common-cause group with β = 5%;
- a logic solver;
- a shutdown valve, the final element.

Each element fails dangerously undetected at a constant rate (λDU), is
proof-tested every 8,760 hours (yearly) and is repaired at once when a test
finds it failed. The diagram is a **Safety function**, with a target of SIL 2:
the switch on the builder's toolbar is on, and the chip beside it holds the
target. Calculate it as it is to see the results, then make it yours.

To turn an existing diagram into a safety function instead, switch on
**Safety function** in its toolbar. A safety function is a repairable diagram,
so the switch makes it one.

## Describe each element

Double-click a block to open it, or double-click its name to rename it in place
(or select it and press F2).

- **Name** — the tag or description your report will use: every result calls
  the block by it.
- **Failure** — the dangerous undetected failures. Enter them as a **Mean**
  (the mean time to a dangerous failure, 1/λDU) or as **Parameters**
  (Exponential, failure rate λ per hour). In a safety function the life model is
  labelled λDU.
- **Proof test** — how often the element is tested, when its first test is (to
  stagger redundant channels' tests) and the test's coverage (below 100% when
  a test can't find every dangerous failure).

Failures that are found at once by diagnostics aren't part of λDU. **Every
block repaired instantly** in the toolbar's ⋯ menu repairs every element as
soon as its failure is found, the usual assumption for a PFDavg.

## Voting and common cause

Two channels side by side, both feeding the next stage, are a **1oo2**: either
one is enough. For **2oo3** and other votes, add a **Voting node (MooN)** from
**+ Add block**: at least M of its N branches must work.

Redundant channels rarely fail independently. Select them (shift-click) and
choose **Common-cause group**, then give **β as a percentage** of each one's
dangerous failures that take out the whole group at once. IEC 61508-6 puts β
between about 1% and 10% for sensors and final elements, depending on the
defences (separation, diversity, testing). The common cause usually sets a
floor under a redundant pair's PFDavg.

## Read the results

Open the **Calculator** and calculate. A safety function's results lead with:

- the **PFDavg** and the **SIL** band it falls in (low demand: SIL 1 below 0.1,
  SIL 2 below 0.01, SIL 3 below 0.001, SIL 4 below 0.0001), and whether it
  meets the target, with the margin to the band's limit;
- the **risk reduction factor** (RRF = 1 / PFDavg);
- **PFD(t)**, which climbs between proof tests as hidden failures build up and
  drops at each test. Its average is the PFDavg.

Under **Details**, **Where the PFDavg comes from** lists each element's share:

- **Share of PFDavg** — the share of the PFDavg in which the element is one of
  the failed elements (its Fussell–Vesely importance). Both channels of a 1oo2
  are in the same failure, so these shares add up to more than 100%. A common
  cause is in its members' shares.
- **Share of dangerous failures** — each element's share of the function's
  failures, with each common-cause group on a row of its own. These add up to
  100%.

The element at the top is where a shorter test interval, a better element or
more redundancy does the most good. In the starter it is the single shutdown
valve.

## What it doesn't check

The PFDavg is one requirement of a SIL. Reliafy doesn't check the
architectural constraints (hardware fault tolerance and safe failure fraction),
systematic capability or the demand rate, so confirm those against
IEC 61511 separately. With no proof tests at all, every failure counts as found
at once and the SIL is marked optimistic.

## Where to go next

The **Design** tab's **Maintenance and proof-test intervals** chooses the
proof-test intervals, staggered or together, that reach a target SIL at the
least cost. **Download as Python** in the Save menu exports the diagram as a
script that prints the same PFDavg and SIL.
