---
title: "Run an RCM study with every decision backed by evidence"
task: "How do I record failure modes, choose a maintenance task for each, and show the analysis behind it?"
category: "Maintenance strategy"
prerequisites: "A system to study. Fitted models or saved strategy analyses to cite help, but you can start without them."
related_href: "/maintenance/rcm"
related_label: "Open RCM studies"
order: 25
---

Reliability-centred maintenance (RCM) asks one question per failure mode: *what
should we do about this?* The answer might be a scheduled replacement, a
condition check, a proof test, a redesign, or nothing at all. The trouble with
most RCM worksheets is that the answer is an opinion in a cell. Nobody can see
the analysis behind it, and nobody notices when the data change.

An RCM study in Reliafy keeps the usual worksheet, but each decision can link to
the analysis that justifies it: a non-repairable model, a degradation model or a saved
strategy analysis. Reliafy checks the link every time you open the study, and
marks each decision **Supported**, **Contradicted** or **Inconclusive**.

## Start from the sample

Open [RCM studies](/maintenance/rcm), under **Maintenance** in the menu. The
list shows the sample *Delivery truck — RCM demo*, with its evidence summarised
as chips: *3 supported, 1 contradicted*. Open it to see a finished study.

![The sample RCM study: functions, failures and modes, each decision with its evidence status](/guides/img/rcm-study-01.png)

The study opens on its **Worksheet**: a table whose first column is the
study's own tree, three levels deep:

- **Function** — what the system must do, ideally with a standard: *Stop the
  vehicle within the rated distance*.
- **Functional failure** — how it fails to do it: *Insufficient braking force*.
- **Failure mode** — what causes that failure: *Brake pad wear beyond the 8 mm
  limit*.

The columns beside it are the worksheet itself: **Failure effects**,
**Consequence**, **Decision**, **Task**, **Interval** and **Evidence check**.
A function or functional failure row sums up what's inside it, so you can
close it and still see what needs doing. Click a row to open its details on
the right: there you'll find the link to the evidence and one line saying what
it shows, for example *Optimal interval ≈ 580 hours (50% saving vs
run-to-failure)*.

To find your way around a big study, open or close a row with its arrow,
filter the rows by text or by what needs attention (failure modes still to
decide, hidden failures, evidence to look at), and choose which columns to
show.

The **Tree** tab shows the same study as a nested list, with each decision's
evidence written under it.

One decision in the sample is red on purpose. The old maintenance plan ran the
wheel bearings to failure, on the grounds that bearing failures are random. The
linked bearing model says otherwise: *β = 2.50 [1.88, 3.32] — the CI excludes 1:
this is wear-out.* That's the point of linking evidence. The worksheet says
what was decided; the check says whether the data still agree.

The sample is read-only. To work on your own, create a study.

## Create a study

On the RCM studies page, press **New study**. Give it a **Name**, and optionally the
**System** it covers and a **Description** of the scope, operating context and
assumptions. Press **Create study** and the empty worksheet opens.

Build the worksheet from the top down:

1. Add a function, and say what it must do.
2. Under the function, add a functional failure: a way it can fail.
3. Under the functional failure, add a failure mode: a cause. Add one per
   cause.

Change a row in its details: the description, effects, consequence, task,
interval or notes. Deleting a row removes everything inside it too. **Undo**
steps back through your changes.

Nothing is stored until you press **Save study** at the top right. Until then
the page shows an **Unsaved** chip.

On the Free plan you can keep one RCM study. Pro has no limit.

### Or import an existing worksheet

If your FMEA or RCM worksheet already lives in Excel, press **Import from
Excel** on the RCM studies page instead. Drop the workbook in, pick the sheet, and map
its columns: **Function**, **Functional failure**, **Failure mode**,
**Effects**, **Consequence**, **Decision / task type**, **Task**, **Interval**
and **Interval unit**. Only **Failure mode** is required. Blank function and
failure cells carry down from the row above, as most worksheets expect.

Reliafy lists the distinct values it finds in the consequence and decision
columns, guesses what each means, and lets you correct any guess. Other columns,
such as severity, occurrence and RPN, can be kept in each mode's notes. The
**Result** line counts what will be created before you press **Create study**.

To add a worksheet to a study you already have, use **Import from Excel** in
the study's **⋯** menu. **Append** adds the imported rows after the existing
ones; **Replace** swaps the whole worksheet, and asks you to confirm first.

## Make a decision for each failure mode

Click **To decide** in a failure mode's **Decision** column, or **Decide…** in
its details. The dialog walks through the classic RCM decision logic.

![The decision dialog: the consequence, the suggested decisions, the task and the linked evidence](/guides/img/rcm-study-02-decision.png)

**The consequence of failure.** Say what the failure does: **Safety**,
**Environmental**, **Operational** or **Non-operational**, and whether it is
**Hidden**. A hidden failure is one you can't see in normal operation, like a
trip that won't trip until it's needed. Each choice shows the rule it implies.
For *Operational*: a proactive task must cost less than the consequences it
prevents, or the answer is run-to-failure.

**The maintenance decision.** The dialog points to the decisions that suit
that consequence. Each kind of decision expects its own kind of evidence:

| Decision | Evidence it expects |
|---|---|
| On-condition task (monitoring) | A degradation model that shows the failure develops measurably |
| Fixed-interval replacement | A saved optimal-replacement analysis with a worthwhile interval |
| Run-to-failure, because failures are random | A Weibull fit whose β interval contains 1, or an exponential fit |
| Run-to-failure, because prevention isn't economic | A saved optimal-replacement analysis that finds no worthwhile interval |
| Failure-finding task | A saved failure-finding analysis |
| Redesign | None. Write the reason in the notes |
| Accept the risk (no scheduled maintenance) | None. Write the reason in the notes |

For a scheduled task, describe the task and give the interval and its
unit. Use the same unit as the analysis you link. If the units disagree, the
decision is marked inconclusive rather than converted. A fixed-interval
replacement or a failure-finding task needs its interval. An on-condition
decision can go without one, when another task already covers it: no task is
made, so say in the notes what covers it. While **Apply** can't be pressed, the
dialog says beside it what's missing.

**The evidence.** The dialog lists only the evidence the decision
expects: your non-repairable models with their β verdicts, your degradation models, or
your saved analyses of the right kind. Pick one and press **Apply**. Then press
**Save study**.

In the example, the gearbox bearing's *Fixed-interval replacement* every 580
hours links to the bearing replacement analysis. After saving, it reads
**Supported**: *Optimal interval ≈ 580 hours (50% saving vs run-to-failure)*.

If the evidence you need doesn't exist yet, the dialog says what to make, for
example *No saved failure-finding analyses (run the Strategy tool and save it)*.
Make it, then come back. A saved analysis comes from **Decisions → Strategy**: run
[optimal replacement](/guides/optimal-replacement-interval) or a
[failure-finding interval](/guides/failure-finding-interval), then press **Save
analysis**.

## Read the evidence status

Each decision's **Evidence check** shows one of these:

- **Supported** — the evidence agrees with the decision.
- **Contradicted** — the evidence points the other way. A run-to-failure
  decision linked to a wear-out model is the common case.
- **Inconclusive** — the evidence can't decide it. The line underneath says
  why: the wrong kind of analysis, mismatched units, or a fit with no
  confidence interval.
- **Stale link** — the linked analysis has been deleted.

A decision with nothing linked yet shows a quiet dash, not a warning: plenty of
decisions are made from judgement, and linking evidence is optional. Its details
offer **Link evidence…** when you're ready. Redesign and accept-risk decisions
need no evidence, so they show no status.

The chips under the study's title count the linked statuses for the whole study, a
function's row counts them for everything inside it, and
the RCM list shows the same counts for every study. A study with no red and no
amber is one whose every decision you can defend.

The check runs again every time the study opens. Refit a linked non-repairable model with
new failures and the status follows the new fit. A decision that was supported
last quarter can turn red this quarter, and the study tells you.

## Export the worksheet

**Export CSV** at the top of the study downloads the worksheet, one row per
failure mode, with each decision's evidence and status.

## Where to go next

The two analyses most RCM decisions cite have their own guides:
[find the optimal replacement interval](/guides/optimal-replacement-interval)
and [set a failure-finding interval](/guides/failure-finding-interval).
On-condition decisions cite a degradation model; see
[predict failure from condition measurements](/guides/degradation-modelling).

To work on a study with colleagues, create it in a
[team workspace](/guides/work-as-a-team). Everyone in the team can open it, and
the study shows who edited it last.
