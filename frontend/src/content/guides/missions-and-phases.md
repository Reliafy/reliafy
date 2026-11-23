---
title: "Missions and phases"
task: "How do I work out the chance a product completes each of its missions, with its phases' own conditions (temperature, load, speed) and the blocks each phase needs?"
category: "Maintenance strategy"
prerequisites: "A position (or a product's design) with positions inside it, or an RBD of its own."
order: 29
# Reliafy Maintenance is operators-only for now: this guide is linked from the
# Explorer's Models tab itself and stays out of the index until Maintenance opens.
hidden: true
---

A **mission** is what a product is used for, start to finish: a survey drone
flies a corridor inspection, or a survey grid. Each mission runs through
**phases** (take-off, transit, survey, landing), and each phase can ask
different things of the same parts: all six motors on take-off but any four in
the cruise, the camera only while surveying, a hotter motor on the climb.

The answer is the chance the mission completes, and how that chance is lost
phase by phase.

## Where missions live

Each mission is flown on an RBD of its own, so it belongs to the **position**
it was added on. Open **Assets → Explorer** (or a product's page) and choose
the **Models** tab. It's one tree: under each position are its models, and
under each model the missions flown on it, then each mission's phases, then
each phase's covariates and node status rules:

- **Position** › **model** (an RBD, or a life or covariate model) ›
  **mission** › **phase** › **covariates** and **node status rules**.

A mission goes under the model it was started from: the RBD it's a copy of,
or the life or covariate model it flies as one block (in use or not). A mission
built from the positions inside, on a position with no RBD of its own, is a
row of the position itself, after its models.

The columns are the Models tab's own. For a mission's rows:

- **Kind**: Mission, Phase, Covariate or Node status.
- **Source**: how many phases and their names (a phase: its place, **Phase 2
  of 3**; a covariate: its value in the phase; a rule: the block's state).
- **Headline**: the chance the mission completes, once worked out, then its
  length (every phase added up, in the RBD's time unit). A phase shows the
  chance of getting through it once started, and its own length.
- **Used by**: the RBD it's flown on (a covariate: the blocks it feeds).

Over the tree, beside the position you picked, the line counts its models and
then its missions: its own, the missions on the positions below it at any
depth, and how many have their chance of completing worked out ("2 missions
here · 5 on 3 positions below · 4 of 7 worked out"). A closed row in the tree
says the same in short ("2 models · 5 missions").

Any position with positions inside it, or with a model of its own, can have
missions, the ones
inside a product included. A position doesn't take the missions of the position
above it: a gimbal's own missions are flown on the gimbal's own RBD.

## Add a mission

Choose **Add a mission…** on a model's **⋯** menu (right-click its row): on an
RBD, the mission is flown on a copy of that RBD; on any life or covariate
model, in use or not, it's that model as one block. The menu is the same on
every kind of model, and so are the mission's pane and its answer: only what
you enter differs. A condition-and-life model can't fly a mission yet. Or choose **Add a mission…** on the
position's own **⋯** menu (or **Add a mission** in the line over the tree).
Type the mission's name in the pane and choose **Add the mission**. Nothing is
saved until it's named. From the position, a position with an RBD
of its own gives the mission a copy of it, wired as it is there: parallel
trains, standby and k-out-of-n stay as they are (a repairable RBD's repairs and
planned work are left out: a mission doesn't repair). Without one, Reliafy
builds the mission's RBD from what's inside the position, the same way
**Build an RBD from what's inside…** does: each block takes the model in use
at its position, and a position with none gets a block with no model, never a
made-up figure. Positions marked as backing each other up (the position's
**Redundancy inside…**) are wired as redundancy. Where nothing says how the blocks are wired (no
connections and no redundancy sets), they go in series, and the mission says so
(**Check the wiring**) until you mark the sets or wire its RBD otherwise. It's saved once, named after the
position and the mission ("Pump station — Summer peak"), and renamed with the mission. A position with nothing
inside and no RBD is a single block: the position's own model in use. A
position with nothing inside and no model can't have a mission yet: its row says
why ("needs a life model or positions inside"). Give it a life model on the
**Models** tab first; a condition-and-life model can't be a block, so its menu says that instead.

A covariate model (a proportional-hazards model, an accelerated life model or
an NSWC-11 record, however it was fitted: one fitted from readings that change
over time is a covariate model like the rest) is a mission with a profile:
each phase sets the covariates' values (or a schedule over the phase), so the
mission is the model run through that profile of conditions over time.

### A mission on a life model with no covariates

On a plain life model (a Weibull, a lognormal, a mixture…) a mission is a
**length**, in the model's time unit, and the age the item **starts at**:

- **New**: age 0.
- **Its age now**: the fitted item's age, read each time the mission is worked
  out, as the Calculator's **As of now** reads it. This is the default where an
  item is fitted at the position.
- **An age**: one you give.

The answer is the chance the item lasts the mission from that age: R(age +
length) ÷ R(age). With it comes the **lower bound** at 90% one-sided (at least
this chance, at 90% confidence) for a fitted model; a model whose parameters
were typed in has no bound, and the answer says so. A Weibull with alpha 1,000
hours and beta 2 lasts a 200-hour mission from new with probability 96.08%, and
from 500 hours with probability 78.66%.

Phases add nothing to a plain model's mission, so its pane has no phases. Add
several missions to the same model to compare lengths side by side: each is a
row under the model with its chance of completing.

### Condition-and-life models

A mission on a condition-and-life (joint) model would be the chance a unit
lasts the length given its readings so far and how they're expected to go.
That isn't built yet.

## The mission tree and its details

Click a mission's row, or any row under it, to see its **details** beside the
tree (on a phone, as a sheet). Double-click it, or press **Enter**, to open the
mission editor across the table area.

- **A mission**: the chance of completing it, its phases in order with each
  one's length and its chance of getting through, the RBD it flies (**Open in
  the RBD builder**), and **Add a phase**, **Rename** and **Delete the
  mission…**.
- **A phase**: the chance of getting through it once started, and the mission's
  chance of still going at its end; its name and duration (with the unit);
  **Move earlier** and **Move later**; its covariates and node status rules;
  **Delete the phase…**.

Under each phase are two kinds of rows:

- **Covariates** (a gauge icon): one for each covariate a life model in the
  mission's RBD takes: a proportional-hazards or other regression model, an
  accelerated life model, or a covariate model such as an NSWC-11 record. They
  appear and go by themselves as the RBD's models change; you never type them
  in. Each shows its value in the phase with its unit. One with no value of its
  own says **Not set** and what stands in (the RBD's value or the model's
  default); one that nothing can stand in for says **Needs a value**. Click it
  and set its value in its details.
- **Node status rules** (a block-and-switch icon): a block's state in this
  phase. Choose **Add node status rule…** on the phase (its menu or its
  details), pick the block and its state: **Standby**, **Guaranteed working**
  or **Not needed**. A standby block can be warm: **Ages while idle** sets how
  fast it wears while idle, from 0% (cold) to 100% (as if running). **Chance it
  starts** is how often it starts when called on (100% unless you set it). Blocks
  with no rule are working. Edit or delete a rule in its details or its menu.

These are the very values the mission's RBD keeps: the RBD builder's **Phased
mission…** shows and edits the same block states and covariate values, so a
change in one is in the other.

The answer says why it has no bound: a mission is worked out from each block's
model at its point values. It is worked out exactly when no block stands by, or
when every block has a constant failure rate (an exponential life). A mission
with blocks on standby and other lives can only be simulated: that needs Pro,
and the range shown (90%, two-sided) is the simulation's own precision. The
simulation is seeded, so the same mission gives the same figures every time. A
mission too large to work out exactly is simulated too.

Under **Modelling → System models → RBDs**, a mission's RBD has a **Mission**
label and says which mission and position it belongs to.

Each mission's RBD is its own: change it (**Open its RBD** on the mission's
menu, or **open it** in the mission) in the RBD builder beside the tree, and the
other missions and the position's own RBD stay as they are. Deleting the
mission deletes its RBD. Missions added before missions had RBDs of their own
stay on the RBD they were added to and work as before.

The mission opens in the table area, the tree kept beside it (on a phone it
takes the screen, with **‹ Back**). Name it, then **Add a phase** for each
stage, in order, with how long it lasts. Use **↑** and **↓** to reorder and
**×** to remove one. **Save** keeps it.

## Blocks in each phase

Under the answer, **Blocks in each phase** is a grid: a row for each block of
the mission's RBD and a column for each phase. Each cell says what that block
does in that phase:

- **Working** (the default): it runs, ages and can fail.
- **Guaranteed working**: it runs and ages but can't fail in that phase (one
  that failed earlier stays failed).
- **Standby**: it's idle until the phase needs it, when a block it backs up
  fails, and then it runs to the phase's end. Idle, a cold spare neither ages
  nor fails; a warm one, given an **Ages while idle** on its rule, wears at that
  fraction. Called on, it starts with its **Chance it starts**; one that fails to
  start has failed for the rest of the mission, and the next spare is tried.
  A block on standby with nothing to back up (in series) is needed at once, so
  it runs.
- **Not needed**: the phase works without it. Its clock keeps running, so if it
  fails then, a later phase that needs it finds it failed.

Change a cell in place; **Calculate** works the mission out with what's on
screen, and **Save** keeps it. Two pumps in parallel, one running by day with
the other on standby and the other way round at night, each run only when
needed.

Each mission's phases are rows under it in the tree, in order, each with its
place (**Phase 2 of 3**) and its own length. A mission's row
menu (right-click it, or press its **⋯**) starts with **Add a phase**: it adds
one at the end and opens the mission on it, ready for its name and duration. A
phase's row menu has **Add node status rule…**, **Open in the mission
editor…** (on that phase), **Move earlier**, **Move later** and **Delete…**.

## Open a phase

Open a phase (the **▸** beside its number) to set what's different about it.

**Covariates in this phase.** Every use and environment covariate the RBD's
blocks take is listed here, grouped **Use** and **Environment**, each with its
unit. These come from blocks on covariate models (an NSWC-11 record, an
accelerated life model or a proportional-hazards model) whose design covariates
were fixed at the position, and from blocks on a saved regression model put
straight in the RBD. Under each covariate you
see which blocks it feeds.

- Type a value once for the phase: every block using that covariate takes it.
- Or choose **Schedule** to have it change during the phase: an expression in
  t, the time since the phase began (for a pump run hard by day and gently by
  night, `100 if t % 24 < 16 else 40`), or a table of values from set times.
  The mission follows every change, and each block carries its wear from one
  step to the next, exactly as if you had split the phase into shorter phases.
- **Set its own** gives one block its own value for this phase; the row then
  shows the block's value as its own.
- A block with no value says **needs a value**. That phase's result waits until
  it has one: the mission is worked out up to the phase before, and no further.
  Reliafy never guesses a missing value.

Design covariates (a bearing's load rating, a seal's material) are fixed at the
position and don't appear here.

**Vote counts.** Where the RBD has a k-of-n vote, set how many inputs this phase
needs: 4 of 6 motors on take-off, 3 of 6 in the cruise.

**Show the RBD** draws the diagram with the blocks this phase doesn't need, or
that stand by in it, faded.

## Calculate

**Calculate** works the mission out, saved or not. The answer comes first: the
chance the mission completes (on a plain life model, with its 90% one-sided
lower bound and the age it started at). Under it, **Reliability through the mission** is
one curve over the whole mission, phase boundaries marked: the chance the
mission is still going at each point. Then, for each phase:

- **Completes**: the chance the mission gets through the phase once it has
  started it.
- **Still going**: the chance the mission is still going at the phase's end.
- **Weakest**: the block whose failures end the most missions in that phase,
  and its share of the phase's failures; **Also** names the next blocks that
  drive the phase's failures.

### Blocks with no model

A position with no model becomes a block with no model. Reliafy never invents
a life for it, so a mission that needs such a block gives no answer: it names
the blocks that need a life model. The grid marks each one.

You choose what to do with them:

- **Give them a model**: open the mission's RBD and set each block's model.
- **Leave them out**: mark them **Not needed** in every phase, so the mission
  is worked out from the blocks with models.
- **Mark a block that never fails** (a frame, say) as **Working** under
  **Status** in the RBD.

The parts age across the **whole** mission, not afresh in each phase: wear in a
hot climb stays with a motor for the rest of the flight (except while a spare
is idle on standby). The result's notes say what **Standby** and **Not needed** mean. When a block's
covariates change between phases, its life carries on from where the last phase
left it (for an accelerated life model, by cumulative exposure: the wear done
at one stress counts at the next).

## In the tools

The same is in the API, the CLI and the Claude connector: `analyse
rbd_mission` works a mission out (or every mission on an RBD) and lists the
covariates its phases can set; `change rbd_mission` adds, changes and deletes
one (a mission on a plain life model starts at its saved starting age;
`current_state` overrides it), with a phase's `standby`, `guaranteed` and `not_needed` blocks (and a
standby block's `dormancy` and `start_probability`), and `models`: a block's
life model for one phase, its age carried in and out. See also [Model a mission in phases](/guides/phased-missions) for the RBD
builder's own phased mission.
