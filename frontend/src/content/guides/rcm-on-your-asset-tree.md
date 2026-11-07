---
title: "Build RCM on your asset tree, every decision backed by evidence"
task: "How do I record a position's functions, functional failures and failure modes, choose a maintenance task for each, and show the analysis behind it?"
category: "Maintenance strategy"
prerequisites: "A position in your asset tree, or the sample UAV product. Fitted models or saved strategy analyses to cite help, but you can start without them."
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

## Start from the sample UAV product

Open **Assets → Explorer** and pick the **RCM** tab. The tree of
positions is the first column, and under each position sit its functions,
their performance standards, functional failures and failure modes, with the
RCM's columns beside every row.

The sample is a product: *Survey quadcopter (sample)*, a small fictional
quadcopter's design. If your tree is empty, press **Open the sample UAV
product**. (With positions already there, it's in the **⋯** beside the tree's
search box; on **Products**, **Add the sample UAV product** adds it too.) It
is added to your workspace the first time, and its **Functional structure**
opens on the **RCM** tab: the same Explorer, scoped to the design. Its 25
positions (airframe, four motors, speed controllers and propellers, power,
flight control, comms and a payload gimbal) carry 25 functions, 34 functional
failures and 41 failure modes, each with its consequence and, all but two, its
decision. The higher positions' failures are explained by those below them
(see *Working top down or bottom up*, below), and some decisions link the
evidence behind them.

![The RCM tab on the sample UAV product: its functions, failures and modes, each decision with its evidence check](/guides/img/rcm-01-explorer.png)

The levels under a position are the ones classic RCM uses:

- **Function** — what the position must do: *Give the aircraft's position*
  (the GPS).
- **Performance standard** — how well it must do it, one parameter and one
  limit each: *Horizontal position within 2 m*. A function may have several;
  each is a row under the function. A function with none (most of the
  sample's) has its functional failures right under it.
- **Functional failure** — how it fails to do it, nested under the performance standard
  it is the loss of: *Position error over 2 m, or no fix*. A total loss, or a failure
  not tied to one performance standard yet, sits under a grey **No performance standard** row.
- **Failure mode** — what causes that failure: *Antenna connector works
  loose*.

The columns beside the tree are the worksheet: **Failure effects**,
**Consequence**, **Decision**, **Task** and, once any decision has evidence
linked, **Evidence check**. On a narrower screen the interval folds into the
Task cell (*every 130 hours*). A position, function or functional failure row
counts what's inside it, for example *1 to decide*, so you can close it and
still see what needs doing. Click a row to open its **Details** beside the
table: for a failure mode, that's its effects, consequence, notes, the decision,
its tasks and the link to the evidence with one line saying what it shows, for
example *Optimal interval ≈ 132 hours (73% saving vs run-to-failure)*. Move up
and down the tree with the arrow keys and the Details follow.

Double-click a row's name (or choose **Open…**, first in its row menu, or
**Expand** in the Details) to spread the Details across the table, with the
tree still on the left so you keep your place: pick another row there and the
Details show that one. **Back to table** (or **Esc**) puts the columns back.
Double-clicking a cell in the columns still edits that cell in place.

To find your way around a big tree:

- The **⋯** beside the tree's search box opens the tree to a level (**Open to
  level 1**, **2**, **3**, **Open everything**) and filters it with **Show
  only**: **Needs a decision**, **Hidden failures**, **Evidence to look at**
  and **Not analysed** (positions with no RCM yet). **Reset to the usual view**
  puts it all back.
- **Positions** / **Locations**, above the tree, switches how it's arranged:
  by what each position is inside, or by where things are. The RCM tab is
  always by position.
- To add a position at the top of the tree, press **+ New position**, the last
  row of the tree. To add one inside another, choose **New position inside**
  in that row's menu.
- The search box filters the tree and its RCM: descriptions, effects, tasks
  and notes, keeping the rows each match sits inside.
- **Isolate** in any row's menu (a position, function, performance standard, functional
  failure or failure mode) closes every other branch of the tree and opens
  that row **with 1 level open**, **2 levels open**, **3 levels open** or
  **everything open** below it. The other rows stay on show, closed, so you
  can still see where you are; open and close rows by hand after as usual.
- **Pin this branch** in a position's row menu shows that position and what's
  inside it on its own; **Show whole tree** brings the rest back.
- **Delete…** in a position's or location's menu (on the Summary tab, and a
  position's on the RCM and FME(C)A tabs too; or press **Delete** on the row)
  deletes it. Everything inside it goes too: the
  positions inside, their tasks and their RCM; open work orders are cancelled.
  Items are never deleted: those fitted there are taken out and kept, loose,
  in Items. The dialog counts what will go before you confirm. Its history
  stays, and **Undo** in the message that follows (or Ctrl+Z, Cmd+Z on a Mac)
  brings it all back.
- **Columns** shows or hides columns, such as **Evidence**, **What the evidence shows** and **Decision notes**. Drag a
  column's edge to resize it. The Explorer remembers these choices on this
  device.

One decision in the sample is red on purpose, on each of the four motors. The
first build's plan ran the motor bearings to failure, on the grounds that
bearing failures are random. The linked bearing model says otherwise: *β = 2.50
[1.88, 3.32] — the CI excludes 1: this is wear-out.* That's the point of linking
evidence. The worksheet says what was decided; the check says whether the data
still agree.

The rest of the sample shows the other cases. The BMS cut-off test and the
propeller replacement are **Supported** by the analyses they link. The battery
pack's retirement is **Inconclusive**: its task counts charge cycles, but the
analysis behind it is in flight hours, so the check can't compare them until
the units agree. Two failure modes are still undecided on purpose (**Show only
→ Needs a decision**), and three are hidden failures, each with its
failure-finding task (**Show only → Hidden failures**).

The sample product is yours to edit, so try things on it. Your own equipment
goes the same way: on any position.

## Build the RCM on a position

Pick a position in the tree on the RCM tab. Build from the top down:

1. **Add function** (at the top of the position's panel, or in the position's
   row menu: right-click the row, press its **⋯** button, or Shift+F10). Type
   what the position must do and press **Add function**.
2. In the function's row menu, **Add a performance standard…** adds a performance
   standard (one parameter and one limit), and **Add functional failure**
   adds a way it can fail. In a performance standard's row menu, **Add a functional
   failure…** adds one that breaches that performance standard, nested under it.
3. In the functional failure's row menu, **Add failure mode** adds a cause.
   Add one per cause.

Each of these opens the row's **Details** on the list you're adding to. The
list ends in a dashed **+ Add …** row; press it (or the row menu's item) and
it becomes a new row of the list: type the words and press Enter (or click
away) to keep it, Esc to drop it. The add row comes back under it, ready for
the next one, so you can type several in a row. If the app can't keep one, the
reason shows under it with your words still there. Open a new row from its
link in the list.

In a row's **Details**, its title is its description: click it to
change it. Under it, every level starts with what's inside it, then its own
fields, then the quieter things at the foot:

- a function: its **Performance standards**, its **Functional failures**,
  then the working behind its performance standards;
- a performance standard: its **Functional failures**, then its checkable
  limit;
- a functional failure: its **Failure modes** (with its state in words at
  the top), then what it is **Caused by** below and what it **Causes** above;
- a failure mode: its **Tasks**, then its **Failure effects**,
  **Consequence** (one tap on a choice) and **Decision**, then where it sits
  (**Under**) and its **Notes**.

**Edit description**
(on a performance standard, **Edit text**) in a row's menu changes the text in the table
itself. **Delete function…** (or performance standard, functional failure or
failure mode) in a row's menu, or **Delete this …** at the foot of its Details,
deletes the row and everything under it. A function takes its performance
standards, functional failures and failure modes; a performance standard takes
the functional failures that breach it; a functional failure takes its failure
modes. Their tasks go too, except a task that also serves a failure mode
elsewhere: that one stays with it. The dialog counts what will go before you
confirm (*Delete “Pump water” and everything under it? 2 functional failures,
5 failure modes, 3 tasks.*), and **Undo** in the message that follows (or
Ctrl+Z, Cmd+Z on a Mac) brings it all back as it was. Failures already recorded
against a failure mode keep it in their history.

Every change is saved as you make it: there is no Save button. A field says
**✓ Saved** by its label once it is; if a change can't be kept, it stays as you
typed it with the reason under it. What you see is what everyone in the
workspace sees.

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
five chemistry failure modes. Both are in the failure mode's Details, under
**Tasks**:

- **Add a task** adds another task to the failure mode as a new card of the
  list: its name and how often, then Enter. Its kind and instructions are its
  **⋯** › **Edit…**, as for any other task. For an operational or
  non-operational consequence the new card asks what the second task catches
  that the first doesn't: put the answer in the decision's notes. (**Add a
  task…** in the row's menu opens the same card.)
- **Use an existing task…** links a task that is already on the position, or
  on a position above it, so one task serves several failure modes. A task on
  a position can serve the failure modes on it and on the positions inside it,
  never the other way round.
- Each task shows how many other failure modes share it. A shared task keeps
  one interval for all of them: change it on the task (**Edit…** in the task's **⋯**),
  not in the decision dialog, which shows it read-only.
- A task by use (hours, cycles, km) shows its **Measurement** when you edit it:
  what it counts, the latest reading and the reading when it was last done.
  **Change the measurement…** picks another in the same unit, on the position,
  above or below it, or on the item fitted there, and asks for the last-done
  reading on the new one (or works it out from the date, marked as an
  estimate).
- **Remove…** in the task's **⋯** takes it off the failure mode: a task that serves only this
  mode is retired; one that serves others too is unlinked and stays.

The **Task** column shows the decision's own task and *+1 task* when there are
more; its Details list them all. The evidence linked on a decision applies to
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

## Several performance standards on one function

A function is one job: one verb, one object. How well it must do that job is
often several numbers: flow and pressure; pH, total alkalinity and calcium
hardness. Each is its own performance standard, and losing any one of them is
its own functional failure. Keeping them as a list, rather than a sentence
with *and* in it, keeps the function's words short and lets each functional
failure say what it breaches.

Each performance standard is a row of the tree under its function, and the functional
failures that breach it are nested under it: *pH above 7.8* and *pH below
7.2* under *pH 7.2–7.8*. A performance standard with no functional failure yet says so
in grey at the end of its row (*no failure yet*): a hint, not a rule. From
the rows:

- In a function's row menu, **Add a performance standard…** adds one. In a performance standard's
  row menu, **Add a functional failure…** adds one that breaches it,
  **Edit text** changes its words in the table, and **Delete performance
  standard…** deletes it with the functional failures that breach it and their
  failure modes, after counting them (**Undo** brings them back). To keep the
  functional failures, move them under another performance standard (or **No
  performance standard**) first. Drag a performance standard above or below
  another to change the order (from the keyboard: **Move up** and **Move
  down** in its menu).
- Which performance standard a functional failure breaches is where it sits in
  the tree. To change it, drag it onto another performance standard (or onto
  **No performance standard**, for the whole function, as a total loss is), or
  use **Move to…** in its menu.
- A performance standard's Details have its text and the functional failures
  that breach it. At the foot, **Make this checkable…** opens the limit as data
  (parameter, comparator, value, unit), when it applies and its source, so
  readings can be checked against it later. Once any of it is set, that line
  says what it reads as, with **Edit…**. Each field is kept as you leave it.
- A function that still has its one performance standard as a sentence shows it as one
  performance standard row, with every functional failure under it (there is nothing
  else to breach). The row's menu edits or removes that text; to make it a
  list, pick the function and use **Add a performance standard** at the end of its list, or **Split into
  performance standards…**, as below.

Pick a function and look under **Performance standards** in its Details:

- Each performance standard is one line: one parameter and one limit, such as *pH
  7.2–7.8*. **Add a performance standard**, at the end of the list, adds
  another in place (the **?** by the heading says what makes a good one).
  Each one's **⋯** has **Edit…**, **Move up**,
  **Move down** and **Remove…**; on a computer you can also drag one by its grip
  to change the order. **Limit…** unfolds the
  structured fields in **Edit…** (parameter, comparator, value, unit), **when** it applies
  (a condition such as *while the filter pump runs*, which is never a
  performance standard on its own) and its **source** (*AS 1926.3*, *the E25 manual*).
  Keep the text as the thing people read; the structured limit is optional.
- A function that had one performance standard before shows it as the first item. The
  moment you add a second, that text becomes the first item of the list,
  as written. Nothing is split for you: if the old text was a list joined by
  semicolons, **Split into performance standards…** proposes one performance standard per part, lets
  you edit each line or drop it, and writes them when you confirm.
- Put each functional failure under the performance standard it breaches: *pH above
  7.8* under *pH 7.2–7.8*; *No flow* under **No performance standard** (the whole
  function). It is a hint for the reader, not a rule: in a function's Details each performance
  standard with none says *No functional failure yet*, so you can decide
  whether those are performance standards of this function at all.
- A performance standard that needs its own verb is another function: *produce chlorine*
  and *not raise the pH* are two jobs.

In a worksheet, every distinct performance standard cell under a function is one performance standard (a
row with the function and a performance standard alone lists one), and when a function
has a list, a functional failure's row names the one it breaches; **Export
CSV** writes them that way, so a sheet reads back with each failure under its
performance standard.

## Move things around: drag and drop, and Undo

In a workshop the analysis changes shape as people talk. On a wide screen you
can drag rows in the RCM table to rearrange it:

- **A function** onto another position (it takes its performance standards, functional
  failures, failure modes and tasks with it), or above or below another
  function to change the order.
- **A performance standard** onto another function, on any position. It takes
  everything under it: the functional failures that breach it, their failure
  modes, decisions and tasks. The label says what moves, for example "the
  performance standard “At least 50 L/s” and its 3 functional failures". Drop it above or
  below another performance standard to change the order.
- **A functional failure** onto another function, onto a performance standard (it then
  breaches that one) or onto **No performance standard**, or above or below another
  functional failure.
- **Failure modes** onto a functional failure, on this position or another. To
  move several at once, pick them with Ctrl-click (Cmd-click on a Mac) or
  Shift-click, then drag one of them; the label shows how many.
- **A task**: drag a failure mode's **Task** cell onto another failure mode. The
  task moves there and stops preventing the mode it came from. To have one task
  prevent several modes, use **Add a task…** › **Use an existing task**.

While you drag, a line shows where it will go (above, below), or the row is
outlined (inside). If it can't go there, the pointer changes to a no-entry sign
and the label says why before you let go: for example, the other position
already has a failure mode with the same name, a task has an open work order,
or failures are recorded against a mode. Press **Esc** to cancel a drag.

A task by use keeps counting the same measurement when it moves, as long as
that measurement is on the new position, a position above or below it, or the
item fitted there. When it isn't (a task counting Truck 12's engine hours,
dropped on Truck 14), the drop asks what it should count there: a measurement
on the new position in the same unit (with its reading when the task was last
done, typed in or worked out from the date), the old one anyway, or calendar
time instead.

Each drop is done in one go, or not at all: if one failure mode under a
performance standard can't move, nothing does. A note at the bottom of the page
says what moved and has an **Undo** button (or press Ctrl+Z, Cmd+Z on a Mac,
while it shows). Undo puts everything back where it was, in the same order,
with each functional failure breaching the same performance standard as before. A link
between functional failures that a move took away (a cause must sit on a
position inside its effect's) is named in the note and isn't put back by Undo:
link them again if you need to.

**Move to…, without dragging:** every function, performance standard,
functional failure and failure mode has **Move to…** in its row menu
(right-click, its **⋯**, or Shift+F10) and in the **⋯** at the top of its
Details; a failure mode with a task also has **Move a task…**. It opens the
tree, with a search box: the places it can go can be picked, and the rest are
greyed, with the reason when you point at one or tap it (*A failure mode goes
under a functional failure*). A function goes on a position; a performance
standard under a function; a functional failure under a performance standard
or a function's **No performance standard**; a failure mode under a functional
failure or a position's **Not under a functional failure**; a task on a
failure mode or a position. Pick one and the dialog says what will happen,
with the same checks a drop has, then press **Move**: it's the same move, with
the same **Undo**, and the row is picked in its new place.

To change the order from the keyboard or on a phone, where there's no dragging,
the row's menu also has **Move up** / **Move down** (a performance standard's
too).

## Show the working behind a performance standard

Some performance standards come from sums, not a book: how much chlorine a pool needs from
its volume, its sunlight and its swimmers, or how many tonnes an hour a belt
must move to keep a silo filling. Open a function's Details: **Working behind the performance standard** is
at the foot, after its functional failures. It is optional.

- **Add a working…** (or **Edit**) opens a box where you write in Markdown:
  headings, lists, tables, bold, code and links. **Preview** shows what readers
  will see. Images and raw HTML are not shown. The text can be up to 20,000
  characters.
- **Upload .md** reads a Markdown or text file into the box. If there is text
  already, you choose **Replace it** or **Add below**.
- **Attach PDF** keeps a PDF of the working with the function, up to five, each
  up to 20 MB. Open one from its name; its **⋯** menu downloads, replaces or
  removes it.
- A small **i** at the end of each of the function's performance standards in
  the tree means a working is there (on a function with no performance
  standard, at the end of the function's name). Click it to open the working.

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
