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
inspection quadcopter's design with a complete RCM study on it. If your tree
is empty, press **Open the sample UAV product**. (With positions already
there, it's in the **⋯** beside the tree's search box; on **Products**, **Add
the sample UAV product** adds it too.) It is added to your workspace the first
time, and its **Functional structure** opens on the **RCM** tab: the same
Explorer, scoped to the design.

The study starts from a mission, written in the product's description and as
the top position's **operating context** (its Summary tab): monthly corridor
inspection of a 12 km rural distribution feeder, sorties of up to 25 minutes,
30 m above the conductors at 5 m/s, a 4K camera and a thermal imager, a 2 km
link with return-to-home, a geofence and a 120 m height limit, about 150
flight hours a year. Every performance standard below takes its numbers from
it. The 33 positions (the airframe with its four arms, centre frame and
landing gear; four motors, speed controllers and propellers; flight control
with its two IMUs, GPS and compass; the battery pack and its BMS; comms; the
gimbal and its camera) carry 47 functions with 63 performance standards, 79
functional failures and 83 failure modes, each with its consequence and, all
but two, its decision. The decisions use the whole logic: on-condition checks,
scheduled discards (the propellers at 130 hours, the battery at 300 cycles)
and restorations (the arm bolts re-torqued), failure-finding tests for the
hidden protective functions, redesigns, run-to-failure and accepted risks.
Read together, their tasks are the aircraft's maintenance programme: a
pre-flight check before every flight, a flight log review every 10 hours, the
25-hour, 100-hour and annual inspections and the failsafe function tests, each
a shared task on the product with the modes' checks as its checklist, plus the
parts' own limits. The higher positions' failures are explained by those below
them (see *Working top down or bottom up*, below), and some decisions link the
evidence behind them.

![The RCM tab on the sample UAV product: its functions, failures and modes, each decision with its evidence check](/guides/img/rcm-01-explorer.png)

The levels under a position are the ones classic RCM uses:

- **Function** — what the position must do: *Give the aircraft's position*
  (the GPS).
- **Performance standard** — how well it must do it, one parameter and one
  limit each: *Horizontal position within 2 m*. A function may have several;
  each is a row under the function. A function with none has its functional
  failures right under it.
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
- **Columns…**, in the **⋯** menu at the top right of the panel, shows or hides columns, such as **Evidence**, **What the evidence shows** and **Decision notes** (the failure mode's notes and rationale). Drag a
  column's edge to resize it. The Explorer remembers these choices on this
  device.

One decision in the sample is red on purpose, on each of the four motors. The
first build's plan ran the motor bearings to failure, on the grounds that
bearing failures are random. The linked bearing model says otherwise: *β = 2.50
[1.88, 3.32] — the CI excludes 1: this is wear-out.* That's the point of linking
evidence. The worksheet says what was decided; the check says whether the data
still agree.

The rest of the sample shows the other cases. The propeller replacement and
the BMS cut-off test are **Supported** by the analyses they link; so are the
speed controllers' thermal-pad check (a degradation model of their temperature
rise), the radio's run-to-failure (an exponential fit: its failures are random)
and the gimbal motor's (a replacement analysis that finds no interval worth
having). The battery pack's retirement is **Inconclusive**: its task counts
charge cycles, but the analysis behind it is in flight hours, so the check
can't compare them until the units agree. Two failure modes are still
undecided on purpose (**Show only → Needs a decision**), and eight are hidden
failures (the four failsafes, each IMU failing silently, the BMS cut-off and
its state of charge), each with its failure-finding task (**Show only → Hidden
failures**).

The sample product is yours to edit, so try things on it. Your own equipment
goes the same way: on any position.

## Build the RCM on a position

Pick a position in the tree on the RCM tab. Build from the top down:

1. **Add function** in the position's row menu (right-click the row, press
   its **⋯** button, or Shift+F10). Type
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

- a function: its **Performance standards**, then its **Functional failures**;
- a performance standard: its **Functional failures**, then its checkable
  limit;
- a functional failure: its **Failure modes** (with its state in words at
  the top), then what it is **Caused by** and what it **Causes**, each with
  the position it is on;
- a failure mode: three numbered steps. **1. Failure effects** is what
  happens when it occurs. **2. Failure consequences** is whether it's hidden
  and its consequence category (one tap on a choice each). **3. Proactive task
  or default action** is edited the same way. **Which task is worth doing?**
  offers only the tasks the decision diagram allows for your step 2 answers,
  then **No task is worth doing**; one tap saves the decision, and a second tap
  on the chosen one clears it. With **No task is worth doing**, a second row
  offers what's done instead (**Run to failure**, **Accept**, **Redesign**, as
  allowed), and run to failure asks why. Until step 2 is answered the choices
  wait, greyed out. Below them are the tasks as cards, each leading with what
  it's for: an on-condition task reads *Check: Weekly water level check ·
  every 1 week*, then **Then, if found:** what's done when the check finds it
  (type it in the card; it's kept when you leave the box or press Enter). A
  failure-finding task reads **Check it still works:** with **Then, if
  failed:**; a fixed-interval task **Do:**; run to failure **When it fails:**
  with what's done on failure; accept **Accepted:** and redesign **Change:**,
  each with the first line of the notes and rationale. Each task card has
  **Edit** and **Remove** at its right. A task kind with no task yet shows a
  small form: the task's name and how often (and, for a check, what's done when
  it finds it), or **Use an existing task…**. **Evidence**, open at the foot,
  shows the evidence (**Link evidence…** opens the evidence picker). Why you
  decided goes in the failure mode's **Notes and rationale**, under its title:
  there's one place for it.

Every row, whatever its level, opens its details with **Notes and rationale**,
a section of its own directly below its title and status line and above
everything else: the long description beside
its title, where you write why it's there and what it rests on (why a
performance standard is set where it is, the history behind a failure mode).
Press **Edit** (or **+ Add notes** beside the heading when there are none yet) to
write in a box in place, with a count up to 4,000 characters (25,000 on a
function, whose notes also hold the working behind its performance standards:
see below), then **Save** or **Cancel**. Line breaks are kept. A row with notes
shows a small note mark after its name in the table; hover over it to read the
first line. On a phone the same section is in the Details sheet, and the
FME(C)A tab's Details show a failure mode's notes the same way.

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

Answer steps 2 and 3 in a failure mode's Details, one tap at a time (see
above). Or click **To decide** in its **Decision** column, or choose **Decide…**
(**Change the decision…** once it has one) in its row menu, for a dialog that
walks the RCM decision diagram one step at a time, with every hint written out.

![The decision dialog: the two questions, the tasks in order, the task and its interval, and the linked evidence](/guides/img/rcm-02-decision.png)

### How the decision is made

Reliafy follows the decision diagram of SAE JA1011 and RCM II (Moubray).

- **Two questions, in order.** First: would the crew notice the failure on
  its own, in normal operation? If not, it's **Hidden**, like a trip that
  won't trip until it's needed. Then the consequence, the first that applies:
  **Safety**, **Environmental**, **Operational**, **Non-operational**. For a
  hidden failure, it's what the *multiple failure* would do: the hidden
  failure plus the one it was there to protect against.
- **Tasks, in order.** An on condition task first, then a fixed interval task
  (scheduled restoration or discard), then, for a hidden failure only, a
  failure finding task. For safety or environmental, a task is worth doing
  only if it makes the risk tolerable; cost isn't the test. For operational or
  non-operational, it must cost less over time than the failures it prevents.
  Two tasks together (a combination) only for safety or environmental, when no
  single task is good enough.
- **If no task is worth doing.** Evident and safety or environmental: redesign
  is compulsory, never run to failure. Evident and operational or
  non-operational: no scheduled maintenance (run to failure); a redesign may
  pay. Hidden and safety or environmental: failure finding, else redesign is
  compulsory. Hidden and operational or non-operational: failure finding if it
  pays, else no scheduled maintenance.

The Details and the dialog offer only what the diagram allows, and the dialog
names the default action. A decision saved before these rules (or
imported) that they'd refuse is kept, with a note asking you to look again.

**1. Would the crew notice the failure on its own?** Choose **Evident** or
**Hidden**.

**2. Consequence.** Choose **Safety**, **Environmental**, **Operational** or
**Non-operational**. For a hidden failure the question reads "What would the
multiple failure do?". Each choice says what makes a task worth doing.

**3. Which task is worth doing?** The tasks are listed in the diagram's order,
each with one line on what makes it worth doing here, then what's done if
none is:

| Decision | Evidence it expects |
|---|---|
| **On condition** | A degradation model that shows the failure develops measurably, or a saved check interval from the P-F calculator |
| **Fixed interval** | A saved optimal-replacement analysis with a worthwhile interval |
| **Failure finding** (hidden failures only) | A saved failure-finding analysis, or a saved test interval |
| **Run to failure**, *failures are random* | A Weibull fit whose β interval contains 1, or an exponential fit |
| **Run to failure**, *prevention isn't economic* | A saved optimal-replacement analysis that finds no worthwhile interval |
| **Accept** (no scheduled maintenance) | None. Write the reason in **Notes** |
| **Redesign** | None. Write the reason in **Notes** |

For a scheduled task, describe it under **Task** and give the interval and its
unit. Use the same unit as the analysis you link. If the units disagree, the
decision is marked inconclusive rather than converted. A fixed-interval
replacement or a failure-finding task needs its interval. An on-condition
decision can go without one, when another task already covers it: no task is
made, so say in **Notes** what covers it. While **Apply** can't be pressed, the
dialog says beside it what's missing.

**4. Link the evidence (optional).** Pick the kind of evidence, then one item,
and press **Apply**. The decision is saved straight away.

- **Models** lists only what the decision expects: your non-repairable models
  with their β verdicts, your degradation models, or your saved analyses of the
  right kind. Reliafy checks these against the decision.
- **Reports** lists your [reports](/reports). Link one when the case for the
  decision is written up there.
- **Function notes** lists the functions on this position that have notes and
  rationale, the failure mode's own function first. Link one when the working
  written there is what justifies the decision.

A report or a function's notes can back any decision, a redesign or an accepted risk
too. Reliafy doesn't check them against the decision, it only links them.

A decision with an interval becomes a scheduled task on the position, shown in
the **Task** column. Change the decision and the task follows; a decision with
no schedule (run-to-failure, redesign, accept) retires it.

### Combine tasks in one decision

Sometimes no single task is good enough on its own. RCM II calls the answer a
*combination of tasks*: a regular inspection plus a fixed-time replacement,
say. It's only for a failure that could hurt someone or harm the environment. In the
decision dialog, choose the first outcome, then pick another under **Add
another task**: *On condition*, *Fixed interval replacement* or
*Failure finding*. Each one you add asks for its own task name and interval,
and each becomes its own scheduled task on the position. A **Redesign** can
sit beside one task, the task done until the change is made. Run-to-failure
and accept stand alone. The notes are once for the whole decision, and the
**Decision** column reads *On condition + Fixed interval*. On an operational
or non-operational consequence only a redesign can sit beside the task.

Each task of a combination needs its own evidence. The evidence you link in
step 4 counts for every task it fits: a degradation model backs the
inspection, a replacement analysis backs the fixed-interval task, and a report
or a function's notes back any task. Where one piece can't cover them all,
open **Evidence for this task** under the other task and link its own. Until
every task has some, the check reads *Partly evidenced*, and the Evidence card
names the task that has none.

A worksheet import builds a combination too: a second row for the same
failure mode with another scheduled outcome joins its decision, in row order.
The export writes a combination the same way, one row per task, so a sheet you
export imports back as the same decisions.

## Several tasks for one failure mode, one task for several

Sometimes one task isn't enough: an inspection catches the slow failures, and
a replacement at a hard life catches the ones it can't see. And sometimes one
act of work answers several failure modes: one monthly water sample covers
five chemistry failure modes. Both are in the failure mode's Details, in its
decision card (**3. Proactive task or default action**): one card per task, each with what
it's for (**Check:**, **Do:**, …), its name and how often, and how many other failure modes share it.

- **+ Add another task**, the dashed row under the task cards, adds a task to
  the decision, making it a combination of tasks. It asks its kind in place
  first (*On condition*, *Fixed interval* or *Failure finding*, or a
  *Redesign* beside one task), then its name and how often, then Enter. Its
  instructions are its card's **Edit**, as for any other task. The row shows
  only when the decision diagram allows another task: a second scheduled task
  on a safety or environmental consequence, failure finding on a hidden
  failure, or a redesign beside one task. (**Add a task…** in the row's menu
  opens the same row, or the decision dialog when there's no decision yet.)
- **Use an existing task…** in the same form picks a task that is already
  on the position, or on a position above it, so one task serves several
  failure modes. A task on a position can serve the failure modes on it and on
  the positions inside it, never the other way round.
- Tasks linked before a failure mode had a decision show under **Tasks linked
  before the decision** until you decide.
- Each task shows how many other failure modes share it. A shared task keeps
  one interval for all of them: change it on the task (its card's **Edit**),
  not in the decision dialog, which shows it read-only.
- A task by use (hours, cycles, km) shows its **Measurement** when you edit it:
  what it counts, the latest reading and the reading when it was last done.
  **Change the measurement…** picks another in the same unit, on the position,
  above or below it, or on the item fitted there, and asks for the last-done
  reading on the new one (or works it out from the date, marked as an
  estimate).
- **Remove** on the task's card takes it off the failure mode: a task that serves only this
  mode is retired; one that serves others too is unlinked and stays. Choosing a
  decision that schedules nothing (or clearing it) asks first, naming the
  tasks that would come off.

### Tasks raised by an event

Some work isn't done on a calendar: after 120 mm of rain in 24 hours, test and
re-dose the pool; after a lightning strike, inspect the chlorinator. In the
task's **Edit**, set **Trigger** to **When an event happens**, then
choose what happens: **A reading passes a limit** (pick a measuring point and
the limit, at or above 120 mm on the rain gauge) or **Someone logs an event**
(type its name, *Lightning strike*). The decision stays as it is; the
**Interval** column shows *on event: 120 mm on POOL-RAIN* for the task, and the
CSV and Excel exports write the same words in that column. A reading past the
limit raises the task's work order, dated the reading's day; a named event is
logged on the position, or one above it, from its **⋯** › **Log an event…**
(also at the foot of **Work** on the Summary tab). Each event raises one work
order: another while it's open raises nothing. The task waits for the event,
so it's never overdue; tick **Keep the interval too** if the interval should
run as well.

The **Task** column shows the decision's own task and *+1 task* when there are
more; its Details list them all. The evidence linked on a decision applies to
its own (first) task. Deleting a failure mode retires the tasks that served it
alone and unlinks the shared ones. In a worksheet, a second row for the same
failure mode with another task adds that task, and a task named on several
rows is one task linked to each; **Export CSV** writes one row per task.

If the evidence you need doesn't exist yet, the evidence picker says what to make, for
example *No saved failure-finding analyses (run the Strategy tool and save it)*.
Make it, then come back. A saved analysis comes from the Strategy tools: run
[optimal replacement](/guides/optimal-replacement-interval) or a
[failure-finding interval](/guides/failure-finding-interval), then press **Save
analysis**.

## Working out the interval

Each scheduled task's card has **Calculate…** beside its *every N* (also while
you change the task with **Edit**). It opens the calculator the kind of task
calls for, says in a sentence or two what it works out, and starts from what
the failure mode already has: its linked model or analysis, and the failures
recorded at the position. Anything it assumed says so; change any input and
press **Work it out** again.

- **On condition: the P-F calculator.** A failure often gives a warning first
  (a noise, a leak, a rise in temperature). The time from that first sign to
  the failure is the P-F interval. Give it, how many failures a year to expect
  if nothing is done, and what a check, a fix in time and a failure cost. It
  finds the check interval with the lowest cost a year, and shows the rule of
  thumb (check at least every half P-F interval) beside it.
- **Failure finding: the test interval.** Give the protective device's failure
  rate (or pick its model) and the target: the most it may be failed when it's
  needed. 1% is filled in as a common starting point for safety, marked
  *assumed*. It finds the longest test interval that meets the target and
  shows yours beside it, for example *1 month → 0.4% unavailability*. Clear the
  target and give the test cost, the demand rate and what a demand on a failed
  device costs to find the cheapest interval instead.
- **Fixed interval: the replacement age.** The same calculation as
  [optimal replacement](/guides/optimal-replacement-interval), from a
  non-repairable model and the planned and unplanned costs, in the model's
  time unit.

**Use N months** writes the interval on the task, rounded down to hours, days,
weeks, months or years so the task is never later than the calculation, and
adds one paragraph to the failure mode's **Notes and rationale** saying what
went in and what came out. When the decision has no evidence yet, the
calculation is saved as a strategy analysis and linked as its evidence, so the
evidence check can read it: a task further apart than the P-F interval, or than
the longest that meets the target, shows as contradicted.

## Read the evidence check

Each decision's **Evidence check** shows one of these:

- **Supported** — the evidence agrees with the decision.
- **Contradicted** — the evidence points the other way. A run-to-failure
  decision linked to a wear-out model is the common case.
- **Inconclusive** — the evidence can't decide it. The line underneath says
  why: the wrong kind of analysis, mismatched units, or a fit with no
  confidence interval.
- **Stale link** — the linked analysis or report has been deleted, or the
  function's notes have been cleared.
- **Report linked** or **Notes linked** — a report or a function's notes and
  rationale are linked. Nothing is worked out from them, so it never says
  supported or contradicted. Click it to open the report, or the function's
  notes beside the table.

A decision with nothing linked yet shows **Not linked**, quietly: plenty of
decisions are made from judgement, and linking evidence is optional. Its
Details offer **Link evidence…** (under **Evidence** in step 3)
when you're ready. Redesign and accept-risk
decisions need no evidence, so they show no status unless you link a report
or a function's notes.

The chips beside the position's name, at the top of its panel, count the linked
statuses for that position (*3 supported, 1 contradicted*), and a function's row counts them for
everything inside it. A position with no red and no amber is one whose every
decision you can defend. **Show only → Evidence to look at** lists the
decisions that are contradicted, inconclusive or stale across the whole tree.
A linked report or function's notes are never one of them.

The check runs again every time the tree opens. Refit a linked non-repairable
model with new failures and the status follows the new fit. A decision that
was supported last quarter can turn red this quarter, and the tree tells you.
The **What changed** panel on Home lists the decisions whose evidence changed.

## Import an existing worksheet

If your FMEA or RCM worksheet already lives in a spreadsheet, choose **Import
worksheet…** in the position's row menu (or in the **⋯** menu at the top
right of its panel). Drop in the workbook or CSV, pick the
sheet and header row for a workbook, and map its columns: **Function**,
**Functional failure**, **Failure mode**, **Effects**, **Consequence**,
**Decision / task type**, **Task**, **Interval** and **Interval unit**. Each
level's notes and rationale has its own column: **Function notes**,
**Standard notes** (for the performance standard on the same row),
**Functional failure notes** and **Notes** (or **Failure mode notes**) for
the failure mode. Only
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
importing the same file again adds nothing. The one exception is notes: a
function, performance standard or functional failure already there with no
notes takes the file's; one with notes of its own keeps them. **Export CSV**, beside **Import
worksheet…**, downloads a position's RCM (and everything inside it) one row per
failure mode, with each decision's evidence and status and every row's notes,
in the same layout the import reads.

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
  prevent several modes, use **Add a task…** › **Use an existing task…**.

While you drag, a line shows where it will go (above, below), or the row is
outlined (inside). If it can't go there, the pointer changes to a no-entry sign
and the label says why before you let go: for example, the other position
already has a failure mode with the same name, a task has work done on it,
or failures are recorded against a mode. A task's open work orders move with
it, and the note says which. Press **Esc** to cancel a drag.

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
between functional failures that a move took away (both ends must be on the
same tree) is named in the note and isn't put back by Undo: link them again if
you need to.

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
must move to keep a silo filling. Write that working in the function's
**Notes and rationale**, the first section of its Details. The box says so:
*Why these limits: the working, the data and the sources behind the
performance standard.* There is one place for it, not two.

- Write in Markdown if you like: headings, lists, tables, bold, code and
  links. The notes show formatted. Images and raw HTML are not shown. A
  function's notes can be up to 25,000 characters.
- **Attach a PDF…**, at the end of the section, keeps a PDF of the working with
  the function, up to five, each up to 20 MB. Open one from its name; its
  **⋯** menu downloads, replaces or removes it.
- From one of the function's performance standards, open Details and choose
  **open them** to go to the function's notes.

A working written before November 2026, when it had a section of its own, now
shows inside the notes, under a **Working** line. Nothing is lost: the next
time you save the notes, both are kept as one text. Over a spreadsheet, the
function's notes travel in the **Function notes** column. A **Standard
working** column in a sheet you import is added to a new function's notes.
PDFs are not part of the file.

## Working top down or bottom up

Because the RCM sits on the tree, a functional failure can be caused by
functional failures elsewhere on the same tree: usually on the positions inside
it, but also on a position beside it or on the same position. Say a swimming
pool's *Free chlorine below 1 ppm* is caused by *No output* on the salt
chlorinator, a few levels down (or beside the pool water, at the same level).
Link them, and the failure modes and decisions for that cause are answered
once, on the chlorinator, not again on the pool. A pool shell that cracks
because the ground heaves links two functional failures on the same position.

- **From the effect:** right-click the functional failure and choose **Link
  to a cause…**. The list starts with its own position and the positions
  inside it, then the rest of the tree, branch by branch; type in the filter
  box to search the whole tree. Tick the causes. If one isn't written yet, use
  **New functional failure…** at the foot of the list: it is written and
  linked together.
- **From the cause:** right-click the functional failure and choose **Link to
  an effect…**. The list starts with its own position and the positions above
  it, then the rest of the tree.
- Reliafy refuses only a failure causing itself, a loop (A caused by B caused
  by A) and a cause on another tree, and says why.
- Under the higher failure each cause shows as a row starting **↳**, with the
  position it is on. Click it to go to the real row. The lower failure shows
  **↑ 1** (or more) to say it causes another failure; click that to go to it.
- A failure explained by its causes needs no failure modes of its own. Its
  Decision cell reads **Explained below**, or says how many are still to
  decide.
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
