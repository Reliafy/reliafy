---
title: "Build RCM on your asset tree, every decision backed by evidence"
task: "How do I record a position's functions, functional failures and failure modes, choose a maintenance task for each, and show the analysis behind it?"
category: "Maintenance strategy"
prerequisites: "A position in your asset tree, or the sample truck. Fitted models or saved strategy analyses to cite help, but you can start without them."
order: 25
---

Reliability-centred maintenance (RCM) asks one question per failure mode: *what
should we do about this?* The answer might be a scheduled replacement, a
condition check, a proof test, a redesign, or nothing at all. The trouble with
most RCM worksheets is that the answer is an opinion in a cell. Nobody can see
the analysis behind it, and nobody notices when the data change.

In Reliafy, RCM lives on your asset tree. Each position carries its functions,
the ways each function fails, and the failure modes that cause each failure.
Each failure mode gets a decision, and each decision can link to the analysis
that justifies it: a non-repairable model, a degradation model or a saved
strategy analysis. Reliafy checks the link every time you open the tree, and
marks each decision **Supported**, **Contradicted** or **Inconclusive**.

## Start from the sample truck

Open **Operate → Assets → Explorer** and pick the **RCM** tab. The tree of
positions is the first column, and under each position sit its functions,
functional failures and failure modes, with the RCM's columns beside every row.

If your tree is empty, press **Add the sample truck**. (With positions already
there, it's in the tree's **⋯** menu, under *Tree options*.) A position called
*Delivery truck (sample)* is added to your tree, with two functions, two
functional failures and five failure modes, each with its decision and the
evidence behind it, and the RCM tab opens on it.

![The Explorer's RCM tab on the sample truck: its functions, failures and modes, each decision with its evidence check](/guides/img/rcm-01-explorer.png)

The three levels under a position are:

- **Function** — what the position must do, ideally with a performance
  standard: *Stop the vehicle within the rated distance*.
- **Functional failure** — how it fails to do it: *Insufficient braking force*.
- **Failure mode** — what causes that failure: *Brake pad wear beyond the 8 mm
  limit*.

The columns beside the tree are the worksheet: **Failure effects**,
**Consequence**, **Decision**, **Task** and, once any decision has evidence
linked, **Evidence check**. On a narrower screen the interval folds into the
Task cell (*every 580 hours*). A position, function or functional failure row
counts what's inside it, for example *1 to decide*, so you can close it and
still see what needs doing. Click a row to open its **Details** beside the
tree: for a failure mode, that's its effects, consequence, notes, the decision,
and the link to the evidence with one line saying what it shows, for example
*Optimal interval ≈ 580 hours (50% saving vs run-to-failure)*.
Double-click a function, functional failure or failure mode (or choose
**Open…**, first in its row menu) to see all of it in one dialog: where it
sits, what's inside it and, for a failure mode, its decision. Changes there are
kept when you press **Save**; **Cancel** leaves it as it was.

To find your way around a big tree:

- The tree's **⋯** menu opens the tree to a level (**Open to level 1**, **2**,
  **3**, **Open everything**) and filters it with **Show only**: **Needs a
  decision**, **Hidden failures**, **Evidence to look at** and **Not analysed**
  (positions with no RCM yet). **Reset to the usual view** puts it all back.
- The search box filters the tree and its RCM: descriptions, effects, tasks
  and notes, keeping the rows each match sits inside.
- **Pin this branch** in a position's row menu shows that position and what's
  inside it on its own; **Show whole tree** brings the rest back.
- **Columns** shows or hides columns, such as **Performance standard**,
  **Evidence**, **What the evidence shows** and **Decision notes**. Drag a
  column's edge to resize it. The Explorer remembers these choices on this
  device.

One decision in the sample is red on purpose. The old maintenance plan ran the
wheel bearings to failure, on the grounds that bearing failures are random. The
linked bearing model says otherwise: *β = 2.50 [1.88, 3.32] — the CI excludes 1:
this is wear-out.* That's the point of linking evidence. The worksheet says
what was decided; the check says whether the data still agree.

The sample truck is yours to edit, so try things on it. Your own equipment goes
the same way: on any position.

## Build the RCM on a position

Pick a position in the tree on the RCM tab. Build from the top down:

1. **Add function** (at the top of the position's panel, or in the position's
   row menu: right-click the row, press its **⋯** button, or Shift+F10). Type
   what the position must do and press **Add function**.
2. In the function's row menu, **Add functional failure** adds a way it can
   fail; the function's **Details** has the same button.
3. In the functional failure's row menu, **Add failure mode** adds a cause.
   Add one per cause.

Each new row opens in **Details**, where you can change its **Description**,
and for a function its **Performance standard**, for a failure mode its
**Failure effects**, **Consequence** and **Mode notes**. **Edit description**
in a row's menu changes the text in the table itself. **Delete this function**
(or functional failure, or failure mode) in the Details removes a row and
everything inside it, after asking.

Every change is saved as you make it: there is no Save button, and what you
see is what everyone in the workspace sees.

## Make a decision for each failure mode

Click **To decide** in a failure mode's **Decision** column, choose **Decide…**
in its row menu, or press **Decide…** in its Details. The dialog walks through
the classic RCM decision logic in three steps.

![The decision dialog: the consequence, the suggested decisions, the task and its interval, and the linked evidence](/guides/img/rcm-02-decision.png)

**1. Consequence of failure.** Choose **Safety**, **Environmental**,
**Operational**, **Non-operational** or **Hidden**. A hidden failure is one you
can't see in normal operation, like a trip that won't trip until it's needed.
Each choice shows the rule it implies. For *Operational*: a proactive task must
cost less than the consequences it prevents, or the answer is run-to-failure.

**2. Maintenance decision.** The decisions that suit that consequence are
tagged **Suggested** and listed first:

| Decision | Evidence it expects |
|---|---|
| **On-condition (monitor)** | A degradation model that shows the failure develops measurably |
| **Fixed-interval replacement** | A saved optimal-replacement analysis with a worthwhile interval |
| **Run-to-failure** — *failures are random* | A Weibull fit whose β interval contains 1, or an exponential fit |
| **Run-to-failure** — *prevention isn't economic* | A saved optimal-replacement analysis that finds no worthwhile interval |
| **Failure-finding task** | A saved failure-finding analysis |
| **Redesign** | None. Write the reason in **Notes** |
| **Accept risk / no scheduled maintenance** | None. Write the reason in **Notes** |

For a scheduled task, describe it under **Task** and give the interval and its
unit. Use the same unit as the analysis you link. If the units disagree, the
decision is marked inconclusive rather than converted. A fixed-interval
replacement or a failure-finding task needs its interval. An on-condition
decision can go without one, when another task already covers it: no task is
made, so say in **Notes** what covers it. While **Apply** can't be pressed, the
dialog says beside it what's missing.

**3. Link the evidence.** The dialog lists only the evidence the decision
expects: your non-repairable models with their β verdicts, your degradation
models, or your saved analyses of the right kind. Pick one and press **Apply**.
The decision is saved straight away.

A decision with an interval becomes a scheduled task on the position, shown in
the **Task** column. Change the decision and the task follows; a decision with
no schedule (run-to-failure, redesign, accept) retires it.

## Several tasks for one failure mode, one task for several

Sometimes one task isn't enough: an inspection catches the slow failures, and
a replacement at a hard life catches the ones it can't see. And sometimes one
act of work answers several failure modes: one monthly water sample covers
five chemistry failure modes. Both are in the failure mode's dialog
(double-click its row, or **Open…** in its menu), under **Tasks**:

- **Add another task…** adds a second task to the failure mode, with its own
  name, interval and instructions. For an operational or non-operational
  consequence the dialog asks what the second task catches that the first
  doesn't: put the answer in the decision's notes. (**Add a task…** in the
  row's menu opens the same form.)
- **Use an existing task…** links a task that is already on the position, or
  on a position above it, so one task serves several failure modes. A task on
  a position can serve the failure modes on it and on the positions inside it,
  never the other way round.
- Each task shows how many other failure modes share it. A shared task keeps
  one interval for all of them: change it on the task (**Edit…** in the list),
  not in the decision dialog, which shows it read-only.
- **Remove** takes a task off the failure mode: a task that serves only this
  mode is retired; one that serves others too is unlinked and stays.

The **Task** column shows the decision's own task and *+1 task* when there are
more; the dialog lists them all. The evidence linked on a decision applies to
its own (first) task. Deleting a failure mode retires the tasks that served it
alone and unlinks the shared ones. In a worksheet, a second row for the same
failure mode with another task adds that task, and a task named on several
rows is one task linked to each; **Export CSV** writes one row per task.

If the evidence you need doesn't exist yet, the dialog says what to make, for
example *No saved failure-finding analyses (run the Strategy tool and save it)*.
Make it, then come back. A saved analysis comes from the Strategy tools: run
[optimal replacement](/guides/optimal-replacement-interval) or a
[failure-finding interval](/guides/failure-finding-interval), then press **Save
analysis**.

## Read the evidence check

Each decision's **Evidence check** shows one of these:

- **Supported** — the evidence agrees with the decision.
- **Contradicted** — the evidence points the other way. A run-to-failure
  decision linked to a wear-out model is the common case.
- **Inconclusive** — the evidence can't decide it. The line underneath says
  why: the wrong kind of analysis, mismatched units, or a fit with no
  confidence interval.
- **Stale link** — the linked analysis has been deleted.

A decision with nothing linked yet shows **Not linked**, quietly: plenty of
decisions are made from judgement, and linking evidence is optional. Its
Details offer **Link evidence…** when you're ready. Redesign and accept-risk
decisions need no evidence, so they show no status.

The chips beside the position's name, at the top of its panel, count the linked
statuses for that position (*3 supported, 1 contradicted*), and a function's row counts them for
everything inside it. A position with no red and no amber is one whose every
decision you can defend. **Show only → Evidence to look at** lists the
decisions that are contradicted, inconclusive or stale across the whole tree.

The check runs again every time the tree opens. Refit a linked non-repairable
model with new failures and the status follows the new fit. A decision that
was supported last quarter can turn red this quarter, and the tree tells you.
The **What changed** panel on Home lists the decisions whose evidence changed.

## Import an existing worksheet

If your FMEA or RCM worksheet already lives in a spreadsheet, choose **Import
worksheet…** in the position's row menu (or in the **⋯** beside **Add
function** at the top of its panel). Drop in the workbook or CSV, pick the
sheet and header row for a workbook, and map its columns: **Function**,
**Functional failure**, **Failure mode**, **Effects**, **Consequence**,
**Decision / task type**, **Task**, **Interval** and **Interval unit**. Only
**Failure mode** is required; without a Function or Functional failure column
everything goes under *Imported*. Blank function and failure cells carry down
from the row above, as most worksheets expect.

Reliafy lists the distinct values it finds in the consequence and decision
columns, guesses what each means, and lets you correct any guess. Other
columns, such as severity, occurrence and RPN, are kept in each failure mode's
notes. The preview counts what will be added, what the position has already,
and any rows it will skip, before you press **Add to “…”**.

The import only adds. A function or functional failure with the same text is
used as it is, and a failure mode already on the position is left alone, so
importing the same file again adds nothing. **Export CSV**, beside **Import
worksheet…**, downloads a position's RCM (and everything inside it) one row per
failure mode, with each decision's evidence and status, in the same layout the
import reads.

## Show the working behind a performance standard

Some standards come from sums, not a book: how much chlorine a pool needs from
its volume, its sunlight and its swimmers, or how many tonnes an hour a belt
must move to keep a silo filling. Open a function's Details and look under
**Performance standard** for **Working behind the standard**. It is optional.

- **Add a working…** (or **Edit**) opens a box where you write in Markdown:
  headings, lists, tables, bold, code and links. **Preview** shows what readers
  will see. Images and raw HTML are not shown. The text can be up to 20,000
  characters.
- **Upload .md** reads a Markdown or text file into the box. If there is text
  already, you choose **Replace it** or **Add below**.
- **Attach PDF** keeps a PDF of the working with the function, up to five, each
  up to 20 MB. Open one from its name; its **⋯** menu downloads, replaces or
  removes it.
- A small **i** beside the standard in the table means a working is there.
  Click it to open the working. If the Performance standard column is hidden,
  the **i** sits at the end of the function's name instead.

When the position (or one above it) has an operating context, the working links
to it, so the figures it uses are one click away. Over a spreadsheet, the
working travels in a **Standard working** column: it is exported with the RCM
as CSV and read back by **Import worksheet…**. PDFs are not part of the file.

## Working top down or bottom up

Because the RCM sits on the tree, a functional failure on a higher position
can be caused by functional failures on the positions inside it. Say a
swimming pool's *Free chlorine below 1 ppm* is caused by *No output* on the
salt chlorinator, a few levels down. Link them, and the failure modes and
decisions for that cause are answered once, down on the chlorinator, not again
on the pool.

- **From the top:** right-click the higher functional failure and choose **Link
  to a cause…**. Tick the failures on the positions inside it. If the lower one
  isn't written yet, use **New functional failure on a position below…** at the
  foot of the list: it is written and linked together.
- **From the bottom:** right-click the lower functional failure and choose
  **Link to an effect…**. Tick the failures on the positions above it.
- Under the higher failure each cause shows as a row starting **↳**, with the
  position it is on. Click it to go to the real row. The lower failure shows
  **↑ 1** (or more) to say it causes something above; click that to go up.
- A failure explained only below needs no failure modes of its own. Its Decision
  cell reads **Explained below**, or says how many are still to decide below.
  Add failure modes at the higher level only for causes that belong to that
  position itself.
- **Unlink** (in the row's menu, or in the failure's Details) takes a link
  off. If it was the only explanation of the higher failure, Reliafy asks first.
- The **Caused by (below)** column in the exported CSV holds the links, written
  as *Position › Functional failure*. Importing a worksheet with that column
  links failures that are already written on positions inside the one you
  import onto.

## What every account gets

RCM on the asset tree is part of every account, with the same evidence checks
on every plan. The tree, its RCM and the saved models and analyses it cites
all live in the same workspace, so in a
[team workspace](/guides/work-as-a-team) everyone in the team works on the same
tree.

## Where to go next

The two analyses most RCM decisions cite have their own guides:
[find the optimal replacement interval](/guides/optimal-replacement-interval)
and [set a failure-finding interval](/guides/failure-finding-interval).
On-condition decisions cite a degradation model; see
[predict failure from condition measurements](/guides/degradation-modelling).
