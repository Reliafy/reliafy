---
title: "Predict a design's failure rate from its parts list"
task: "How reliable will this design be, before we have any failure data?"
category: "Life data modelling"
prerequisites: "A parts list: the part types in the design and how many of each."
related_href: "/predictions"
related_label: "Open Reliability prediction"
order: 60
---

A reliability prediction answers the question every new design gets asked
before it has run an hour: *how often will it fail?* With no failure data yet,
the only honest answer is an estimate from published base rates, and that's
what **Modelling → Reliability prediction** gives you: a parts count.

## What a parts count is

Every part type in a handbook has a **base failure rate** (λb): failures per
million hours for a ceramic capacitor, a film resistor, a rectangular connector,
a MOSFET. Reliafy's reliability data library carries these rates from
MIL-HDBK-217F, the U.S. military's prediction handbook, each one cited (browse
them under [Models › Library](/models/library)).

For microcircuits (logic, microprocessors, memories, GaAs devices), motors,
synchros and resolvers, circuit boards, quartz crystals, lamps and laser
diodes, the library carries the handbook's **parts-count** rates instead
(its Appendix A): a **generic failure rate** (λg) for each environment, with
the environment already in it. Microcircuits come in complexity bands (gates,
transistors, bits or memory size), so pick the band your part falls in.

A parts count adds them up. For each line of your parts list:

> failure rate = λb × πE × πQ × quantity

- **λb** is the handbook's base rate for that part type.
- **πE** is the handbook's **environment factor**: the same part fails more
  often in a helicopter than in a lab, so you pick where the equipment works
  (ground benign, ground fixed, ground mobile, naval, airborne, and so on) and
  every line uses its own factor for it.
- **πQ** is a **quality factor** for the part's grade, which you set per line.
  Left blank it's 1, except for the parts-count types, which take the lowest
  grade the handbook lists: 10 for a commercial microcircuit (class B is 1,
  class S 0.25), non-MIL for a crystal or a board. Each part type's grades
  show on the box.

For a parts-count type the line is simply λg × πQ × quantity: the handbook
worked out λg from its full model at its default temperature, package and
complexity, and the record says which defaults it holds.

The lines' rates add up (every part in series, each with a constant rate), and
from the total you get the **MTBF** (1 / failure rate) and the **reliability**
over a mission time (R(t) = exp(−λt)). A Pareto shows which lines and which
part categories drive the total, and if your lines sit in sub-assemblies, the
rate per assembly too.

## Make one

1. Open **Reliability prediction** and press [**New prediction**](/predictions/new).
2. Give it a name, pick the **environment**, and set the **mission time** in
   hours. The reliability figure is the chance of no failure over that long.
3. Build the **parts list**. **Paste a list** takes one part per line with its
   quantity after a comma (`Ceramic capacitor, 48, Flight controller`; the third
   column is the assembly it's in); **Add a line** adds one at a time.
4. Give each line a **handbook part type**: type a word or two (`capacitor
   ceramic`, `resistor film`, `microprocessor MOS`, `memory DRAM`, `motor`,
   `crystal`) and pick the match. Set the **quality factor** (πQ) on a line
   when its grade isn't the default.
5. Press **Calculate**, read the result, then **Save prediction**.

The Free plan keeps **1 saved reliability prediction** (the shared sample
doesn't count); calculating without saving has no limit. To save another,
delete the one you have or [upgrade to Pro](/billing), which removes the limit.

The handbook covers electronic parts only. It has no batteries and no
mechanical parts, so:

- Tick **Not electronic** on a mechanical part (an airframe, a propeller, a
  gimbal's mechanics). It's left out of the total, and the result lists what
  was left out, so the total is for the electronics.
- For a part the handbook doesn't have, such as a battery, choose **Give a rate
  of your own instead** in the part-type search and type its failure rate per
  million hours, from the maker's data or your own records. The line is marked
  **user-given** everywhere it shows.
- A line with neither stays in the list with no part type: it's shown and left
  out of the total, and the result says so. Don't give it the nearest
  electronic part type just to get a number.

The sample prediction, the sample quadcopter's electronics, shows a finished
one with lines in assemblies and two parts left out.

## Read the result honestly

Only three of the handbook's factors are applied: λb, πE and πQ (or λg and
πQ for a parts-count type, whose generic rate holds the rest at the
handbook's defaults). The handbook's full models also have temperature,
electrical stress, construction and power factors, and the result names which
ones it left out for your parts. Real rates
depend on them: temperature and stress alone can move a part's rate several
times over. So read a parts count as it's meant to be read:

- **For comparing designs early** (does the second design have half the failure
  rate of the first?) and for finding what to improve (the Pareto), it's useful.
- **As a measure of how your equipment will actually fail**, it isn't. The
  handbook's models date from 1995 and are known to be pessimistic for modern
  parts; a prediction is often several times the failure rate seen in service.

The moment you have failures of your own, fit a model to them instead
([fit a non-repairable model](/guides/fit-your-first-model)): data from your
equipment beats a handbook every time. Saved predictions keep the result they
were saved with; **Edit** computes it again from the parts list.
