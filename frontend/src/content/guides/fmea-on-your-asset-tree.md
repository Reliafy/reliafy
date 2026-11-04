---
title: "Score failure modes as an FMEA or FMECA on your asset tree"
task: "How do I score severity, occurrence and detection for each failure mode, get an action priority and RPN, and work out criticality, on the same tree as my RCM?"
category: "Maintenance strategy"
prerequisites: "A position in your asset tree with failure modes, or the sample UAV or sample truck."
order: 26
---

A failure mode effects analysis (FMEA) asks three questions about every
failure mode: *how bad is it, how often does it happen, and would we catch it
first?* Each answer is a score from 1 to 10. Together they rank the modes, so
the design or maintenance effort goes where it matters. An FMECA adds the
*C*, criticality: a number built from the failure rate, so modes can be ranked
by how much loss they are expected to cause, not only by opinion.

In Reliafy, the FMEA sits on the same failure modes as your RCM. The
**FME(C)A** tab and the **RCM** tab of the Explorer are two views of one set of
records: a failure mode written on either tab is there on the other, and a
score or an effect edited on one shows on the other at once. Nothing is copied.

## Start from the sample UAV

Open **Operate → Assets → Explorer** and pick the **FME(C)A** tab. If your tree
is empty, press **Add the sample UAV** (or **Add the sample truck**; with
positions already there, both are in the tree's **⋯** menu). *Quadcopter UAV
(sample)* is a small fictional quadcopter: airframe, propulsion, power, flight
control, comms and a payload gimbal, with sixteen failure modes scored and
their criticality figures filled in.

![The FME(C)A tab on the sample UAV: each failure mode with its cause, effects, scores, RPN and action priority](/guides/img/fmea-01-worksheet.png)

The tree of positions is the first column, as on the RCM tab. Under each
position sit its functions, and under each function its failure modes, one
row each, the way an FMEA worksheet reads. The columns beside the tree are the
worksheet:

- **Functional failure** — the RCM's middle level, shown for information when
  the mode sits under one. A mode written on this tab has none yet.
- **Cause** — what brings the failure mode about: *bearing wear from dust
  ingress*.
- **Local effect**, **Next higher effect**, **End effect** — what happens at the
  position itself, at the assembly above it, and to the whole system or
  mission. *End effect* is the same field as the RCM tab's *Failure effects*.
- **Detection method** — how the failure, or its cause, would be noticed before
  it matters: a check, a telemetry alarm, a self-test.
- **S**, **O**, **D** — severity, occurrence and detection, each 1 to 10.
- **RPN** and **AP** — the risk priority number and the action priority, worked
  out from S, O and D (below).
- **Recommended action**, with its **Owner**, **Due** date and **Status**
  (Open, In progress, Done).

**Columns** adds the criticality columns (failure rate, mode ratio, loss
probability, operating time, mode criticality, severity class) and the RCM's
own (Consequence, Decision, Task). Double-click a cell to edit it in place;
click a row to open its **Details** beside the table, where the same fields
sit in two groups, **FME(C)A** and **Criticality**, and the RPN and action
priority update as you type.

## Score a failure mode

Each score is a whole number from 1 to 10. The hints beside each field say
what the ends of the scale mean:

- **Severity**: 1 is no noticeable effect; 10 is a hazard with no warning.
  Score the end effect, not the local one.
- **Occurrence**: 1 is almost never; 10 is almost certain over the life of the
  item. If you have failure data, let it set the score rather than a feeling.
- **Detection**: 1 means the current controls are almost certain to catch the
  cause or the failure before it matters; 10 means nothing would.

Two rankings come from the three scores:

- **RPN**, the risk priority number, is simply S × O × D, from 1 to 1,000. It
  is the classic FMEA number, and it is easy to misread: a 10 × 2 × 5 and a 2 ×
  10 × 5 score the same 100, though one is a rare catastrophe and the other a
  common nuisance.
- **AP**, the action priority, answers that weakness. It looks the three scores
  up in a table that puts severity first, then occurrence, then detection, and
  answers **High**, **Medium** or **Low**: *High* means act, *Medium* means act
  or write down why not, *Low* means you may. Reliafy's table follows the
  published AIAG-VDA (2019) action priority rule in its own words; the
  Details show the band each score fell in.

A failure mode with all three scores shows its RPN and AP; one with fewer
shows neither. Function and position rows add up what is inside them: *2 high ·
1 medium*, the highest RPN, and *3 of 5 scored*. The tree's **⋯** menu filters
with **Show only**: **High priority**, **Medium priority**, **Not scored** and
**Has an action open**. Click a column header to sort the rows under each
function by that column (RPN, AP, severity, criticality or the due date),
highest first; the tree stays as it is.

## Criticality (the C in FMECA)

Scores rank modes by judgement. Criticality ranks them by expected loss, in
the way MIL-STD-1629A describes. In plain words: *how often does the item
fail, what share of those failures is this mode, how likely is it that this
mode causes the loss we are worried about, and over how long?* Multiply the
four and you have the mode criticality number.

The fields, in the **Criticality** group of a failure mode's Details:

- **Failure rate** (λ): the item's failure rate, in failures per hour (or
  whichever unit you set). Say where it came from: entered by hand, read from a
  model, or from your own failure data.
- **Mode ratio** (α): the share of the item's failures that are this mode,
  from 0 to 1. The ratios of an item's modes should add up to about 1.
- **Loss probability** (β): the chance that, when this mode happens, the effect
  is the loss named by its severity class: 1 for certain, 0.5 for probable,
  0.1 for possible, 0 for none.
- **Operating time** (t): the hours the criticality is figured over, such as a
  mission, a year or the design life.
- **Severity class**: I Catastrophic, II Critical, III Marginal, IV Minor.

The formula is C<sub>m</sub> = β × α × λ × t. For the sample UAV's motor
bearing seizure that is 1.0 × 0.5 × 0.00008 per hour × 100 hours = 0.004: four
expected losses per thousand flight hours from that one mode. The **item
criticality** C<sub>r</sub> of a position is the sum of its modes'
C<sub>m</sub>, shown on the position's row and in its Details, with the sum
per severity class.

Pick a position row on the FME(C)A tab and its Details show the **criticality
matrix**: severity across, occurrence down, and in each cell how many of the
position's failure modes (and those of the positions inside it) fall there,
shaded by the worst action priority among them. Under it, the modes are
listed by criticality, highest first.

![A position's criticality matrix: severity across, occurrence down, the count of failure modes in each cell](/guides/img/fmea-02-matrix.png)

Reliafy does not read the failure rate from a linked model for you yet: when a
position's failure mode cites a non-repairable model as its evidence, read the
rate off the model's page at the operating time and enter it, choosing *From a
model* as the source.

## Start from a function, finish the RCM later

An FMEA worksheet goes straight from a function to its failure modes. An RCM
puts two levels between them: the performance standard the function is held
to, and the functional failure that is the loss of it. You don't have to
choose first.

On the FME(C)A tab, **Add failure mode** in a function's row menu (or the
**+ Add** row in its Details) writes the mode directly under the function. On
the RCM tab the same mode shows under that function in a grey **No functional
failure yet** row, with the quiet reminder that the RCM isn't finished there:
a function with modes but no functional failure counts as not analysed. When
you are ready, add the performance standard and the functional failure on the
RCM tab, then choose the functional failure in the mode's **Under** field, or
pick **Assign to a functional failure…** in the grey row's menu to move every
mode under it at once. It is the same record throughout: the scores, effects,
criticality and any decision stay with it.

Modes written on the RCM tab under a functional failure show on the FME(C)A
tab too, with the functional failure named in its own column.

## Bring in a worksheet, take one out

**Import worksheet…** in a position's row menu reads an FMEA worksheet the
same way it reads an RCM one, one row per failure mode, and now maps
**Severity**, **Occurrence**, **Detection**, **Cause**, **Local effect**,
**Next higher effect**, **Detection method**, **Recommended action**,
**Owner** and **Due date** columns onto the fields above. A score outside 1 to
10 stops the import with the row named. An **RPN** column is read only to
check: a value that doesn't equal S × O × D is reported, and Reliafy's own
RPN is used. Rows with no functional failure go directly under their
function, as on this tab. A worksheet imported before this scoring existed
kept its scores in each mode's notes; they are still there, and the fields
are blank until you fill them.

**Export CSV** and **Export Excel** write the position's worksheet (it and
everything inside it) one row per failure mode, with every column above, in
the layout the import reads back. **Print view** opens the same worksheet as
one plain page for printing or a PDF.

## Where to go next

The decisions an FMEA leads to are the RCM's: see [build RCM on your asset
tree](/guides/rcm-on-your-asset-tree). An occurrence score that should come
from data starts with [fitting a model](/guides/fit-your-first-model); a
detection score that depends on an inspection interval leads to the
[failure-finding interval](/guides/failure-finding-interval).
