---
title: "Predict how long repairs will take"
task: "How long will corrective maintenance take on this design, and which parts drive it?"
category: "Maintenance strategy"
prerequisites: "A parts list (typed, pasted from a spreadsheet, or a product's), and a rough idea of how long each repair takes."
related_href: "/maintainability"
related_label: "Open Maintainability prediction"
order: 26
---

A maintainability prediction answers one question early, while a design can
still change: **how long will repairs take?** Not for one part, but for the
whole system, weighted by what actually fails. It is the maintainability twin
of a reliability prediction: that one adds up how often things fail, this one
adds up how long they take to put right.

You get three numbers and a list:

- **Mct**, the mean corrective maintenance time: the average repair, over all
  the failures the system will have.
- **M_max**, the time by which most repairs (95% by default) are done: the
  figure a support contract or a turnaround target is written against.
- **Inherent availability**, MTBF ÷ (MTBF + Mct): the share of time the system
  is up, counting only repair time, with no waiting for parts or people.
- **What takes the time**: the lines, largest share first, so you know which
  repairs to make quicker, or which parts to make fail less often.

## Start from a parts list

Open **Modelling → Maintainability prediction** and press **New prediction**.
The lines table is the parts list: one row per thing that can fail.

- With Reliafy Maintenance, **Start from a product** fills the rows from the
  product's parts list: every lowest-level part with its part number, how many
  go into one product and the assembly it sits in. The times are yours to add.
- **Paste a parts list** takes rows from a spreadsheet: `part number, name,
  quantity`, or just names. A header row names the columns, so a sheet with
  `failure rate`, `MTTR` or the elements fills those too.
- Or type the rows. A blank row is always waiting at the end.

**Quantity** is how many of that line are in one system. Four motors are one
row with quantity 4.

## Enter each line's repair time

Each line takes one **MTTR** (its mean time to repair), in the unit chosen at
the top (**Repair times in**: minutes or hours). If you know how a repair
breaks down, tick **Split repair times into elements** and enter the elements
the way handbooks split them, so they can be compared and the slow ones found:

| Element | What it covers |
|---|---|
| **Isolate** | Finding what failed: diagnostics, fault isolation. |
| **Access** | Getting to it: covers off, disassembly. |
| **Replace** | Taking the failed part out and fitting the new one, or repairing it in place. |
| **Restore** | Putting everything back together. |
| **Check out** | Proving it works: tests, alignment, calibration. |

The line's MTTR is then the sum of its elements. Every time in the table and in
the results is in the unit chosen at the top.

**Most done by** is optional: the time 95% of that line's repairs are done by,
say twice its MTTR when repairs vary a lot, 1.3× when they're routine. It is
the line's spread, and it's what makes M_max possible (see below).

## Give each line a failure rate

Each line counts by how often it's the one being repaired: its **failure rate ×
quantity**. A part that fails ten times as often weighs ten times as much in the
average, however long or short its repair.

- Type a failure rate per line, in the unit chosen at the top (**Failure rates
  in**: per million hours by default, or per hour).
- With a product chosen, a saved **reliability prediction** for that product
  supplies the rates where a line's part number or name matches, and the
  result says so.
- With no rates at all, every line counts the same. The result says that too,
  and availability isn't available: it needs the system's MTBF, which comes from
  the rates (1 ÷ their sum, times quantities) or from the **System MTBF** box.

## Read the answer

Press **Compute**. The answer comes first, in one sentence, then the tiles:
Mct, M_max, inherent availability and the MTBF behind it.

![The sample quadcopter's prediction: Mct, M_max, availability and the lines that take the time](/guides/img/mp-01-result.png)

Below it:

- **Where the repair time goes**: each element's share of Mct across every
  line. If most of it is *Access*, the design needs better access, not faster
  technicians.
- **What takes the time**: the lines, largest share first, with the running
  total. The top few lines are where a shorter repair, or a more reliable part,
  brings Mct down most.
- **By assembly**, when the lines name their assemblies (`Propulsion › Arm 1`
  counts under *Propulsion* and under *Arm 1*): each assembly's own Mct and
  share.
- **Every line's figures**, folded away: the elements, MTTR, spread and M_max
  per line.

Numbers are shown to three or four figures with their unit. Open the sample,
*Survey quadcopter — maintainability prediction (sample)*, to see a finished
one. With Reliafy Maintenance, adding the sample UAV product also saves the
same prediction among your own, as *Survey quadcopter (sample) —
maintainability*, with the sample product as its product.

## How the numbers are worked out

In plain words: the average repair is the average of the lines' repair times,
each counted as often as that line fails.

> Mct = Σ(λ · q · MTTR) ÷ Σ(λ · q)

where λ is the line's failure rate, q its quantity and MTTR the sum of its
elements. With no failure rates, λ is 1 for every line.

M_max is the time by which 95% of repairs are done (change the percentage in
**Most repairs done by**). Each line's repair time is taken as **lognormal**, the usual
shape for repair times: most are near the typical value, a few take much
longer. Its mean is the line's MTTR and its spread comes from **Most done by**,
the 95% point you gave. The system's repair time is the mix of the lines'
distributions, each weighted by λ · q, and M_max is the 95% point of that mix,
found numerically.

If no line has a spread, M_max isn't available and the result says so; Mct
still is. If some lines have one and others don't, the others count as always
taking exactly their MTTR, which makes M_max a little low: the result says
how many.

Inherent availability is

> A_i = MTBF ÷ (MTBF + Mct)

with both in hours. MTBF is 1 ÷ the summed failure rates (× quantities), or the
**System MTBF** you typed.

## What it leaves out

- **Logistics and administrative delay.** Waiting for a spare, a technician or
  a permit isn't repair time. Inherent availability is the best the design can
  do; operational availability is lower.
- **Preventive maintenance.** Only corrective repairs are counted. Planned work
  belongs in a [replacement interval](/guides/optimal-replacement-interval)
  or an RBD's maintenance policy.
- **Redundancy.** A failed part in a redundant pair may not take the system
  down. For availability with redundancy, model it in a
  [repairable block diagram](/guides/repairable-availability).
- **Guessed spreads.** M_max is only as good as the "most done by" figures.
  Where you have repair records, fit them: the lognormal's spread (σ) is
  typically 0.3 to 1.0 for repair times.

## Save it

Press **Save prediction** under the answer and give it a name. The lines are
kept with the result, recomputed on the server when saved, and the prediction
appears on the [Maintainability prediction](/maintainability) page. Open one
and press **Edit a copy** to change its lines and save a new version.

The Free plan keeps **1 saved maintainability prediction** (the shared sample
doesn't count); computing without saving has no limit. To save another, delete
the one you have or [upgrade to Pro](/billing), which removes the limit.

## From an agent or the command line

The same calculation is the `analyse` tool's `maintainability` action (and
`change maintainability_save` to keep it); over REST it's
`POST /api/v1/analyse/maintainability`, and on the command line
`reliafy analyse maintainability --lines '[…]'`. See
[use the API and command line](/guides/use-the-api-and-cli).
