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
MIL-HDBK-217F, the U.S. military's prediction handbook, each one cited.

A parts count adds them up. For each line of your parts list:

> failure rate = λb × πE × πQ × quantity

- **λb** is the handbook's base rate for that part type.
- **πE** is the handbook's **environment factor**: the same part fails more
  often in a helicopter than in a lab, so you pick where the equipment works
  (ground benign, ground fixed, ground mobile, naval, airborne, and so on) and
  every line uses its own factor for it.
- **πQ** is a **quality factor** for the part's grade, which you set per line.
  It's 1 unless you say otherwise; each part type's handbook range is shown.

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
   ceramic`, `resistor film`, `connector rectangular`) and pick the match. Set
   **πQ** on a line when its grade isn't the handbook's default.
5. Press **Calculate**, read the result, then **Save prediction**.

A part the handbook has no type for, such as a motor, a propeller or a
microcircuit, stays in the list with no part type: it's shown and left out of
the total, and the result says so. Don't give it the nearest electronic part
type just to get a number.

The sample prediction, the sample quadcopter's electronics, shows a finished
one with lines in assemblies and two parts left out.

## Read the result honestly

Only three of the handbook's factors are applied: λb, πE and πQ. The handbook's
full models also have temperature, electrical stress, construction and power
factors, and the result names which ones it left out for your parts. Real rates
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
